#!/usr/bin/env bash
# D4.6 单个 arm 的完整一轮：重启 EPP（冷索引）→ 抓 vLLM/EPP metrics
# → 跑 bench（bench 会先 /reset_prefix_cache，清 HBM + CPU tier）→ 抓 metrics。
#
# 用法（在 VM 上，LAB=/root/lab）：
#   bash scripts/d4.6/run_arm.sh hbm vllm-hbm 1
#   bash scripts/d4.6/run_arm.sh tiered vllm-tiered 1
#
# 可选参数：sessions turns prefix_words concurrency
#   bash scripts/d4.6/run_arm.sh hbm vllm-hbm 1 32 4 3000 4
#
# 为什么要重启 EPP：EPP 的 prefix 索引是进程内近似索引，不随
# /reset_prefix_cache 清空；每轮重启才能和 engine 的冷 cache 对齐。
set -euo pipefail

ARM=${1:?usage: run_arm.sh <arm> <app-label> <run> [sessions] [turns] [prefix_words] [concurrency]}
APP=${2:?}
RUN=${3:?}
SESSIONS=${4:-32}
TURNS=${5:-4}
PREFIX_WORDS=${6:-3000}
CONCURRENCY=${7:-4}

NS=${NS:-d46}
LAB=${LAB:-/root/lab}
OUTDIR=${OUTDIR:-/results/d4.6}

mkdir -p "$OUTDIR"

echo "[1/6] restart EPP for a cold router index"
kubectl rollout restart deploy/d46-router-epp -n "$NS" >/dev/null
kubectl rollout status deploy/d46-router-epp -n "$NS" --timeout=180s

PODS=$(kubectl get pods -n "$NS" -l "app=$APP" -o jsonpath='{.items[*].metadata.name}')
POD_URLS=$(kubectl get pods -n "$NS" -l "app=$APP" \
  -o jsonpath='{range .items[*]}http://{.status.podIP}:8000,{end}' | sed 's/,$//')
echo "pods=$PODS"
echo "pod_urls=$POD_URLS"

snapshot_vllm() {
  local phase=$1
  local p
  for p in $PODS; do
    kubectl get --raw "/api/v1/namespaces/$NS/pods/${p}:8000/proxy/metrics" \
      > "$OUTDIR/metrics-${ARM}-run${RUN}-${phase}-${p}.txt"
  done
}

snapshot_epp() {
  local phase=$1
  local epp token pf
  epp=$(kubectl get pods -n "$NS" --no-headers | awk '/d46-router-epp/{print $1; exit}')
  token=$(kubectl create token default -n "$NS" --duration=10m)
  kubectl port-forward -n "$NS" "pod/$epp" 19090:9090 >"/tmp/pf-epp-${ARM}-${RUN}-${phase}.log" 2>&1 &
  pf=$!
  sleep 3
  curl -s -m 10 -H "Authorization: Bearer $token" http://127.0.0.1:19090/metrics \
    > "$OUTDIR/epp-${ARM}-run${RUN}-${phase}.txt" || true
  kill "$pf" 2>/dev/null || true
  wait "$pf" 2>/dev/null || true
}

echo "[2/6] metrics before"
snapshot_vllm before
snapshot_epp before

echo "[3/6] refresh bench configmap"
kubectl create configmap d4-bench -n "$NS" \
  --from-file=bench_prefix.py="$LAB/scripts/d4/bench_prefix.py" \
  --from-file=run_bench.sh="$LAB/scripts/d4/run_bench.sh" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

echo "[4/6] run bench: sessions=$SESSIONS turns=$TURNS prefix_words=$PREFIX_WORDS concurrency=$CONCURRENCY"
kubectl delete pod d4-bench -n "$NS" --ignore-not-found >/dev/null
URL="http://d46-router-epp/v1/completions" \
ARM="$ARM" RUN="$RUN" OUTPUT_DIR="$OUTDIR" FORCE_CLOSE=0 \
POD_URLS="$POD_URLS" SESSIONS="$SESSIONS" TURNS="$TURNS" \
PREFIX_WORDS="$PREFIX_WORDS" SUFFIX_WORDS=80 MAX_TOKENS=128 \
CONCURRENCY="$CONCURRENCY" SEED=42 WARMUP=4 \
envsubst < "$LAB/scripts/d4/bench-pod.yaml" | kubectl apply -n "$NS" -f - >/dev/null
kubectl wait --for=condition=Ready pod/d4-bench -n "$NS" --timeout=120s
kubectl logs -f d4-bench -n "$NS" || true
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/d4-bench -n "$NS" --timeout=900s

sleep 3
echo "[5/6] metrics after"
snapshot_vllm after
snapshot_epp after
echo "[6/6] done: $OUTDIR/${ARM}-run${RUN}.json"
