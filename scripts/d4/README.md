# D4 脚本与 manifest

主文档：[`../../d4-llm-d-learning.md`](../../d4-llm-d-learning.md)。这里只放可执行文件，解释和验收标准在主文档。

## 文件

| 文件 | 用途 |
|---|---|
| `modelserver.yaml` | 2 个 vLLM 副本（每个 1×L4）+ 普通 Service `vllm-direct` |
| `values-precise.yaml` | llm-d standalone + precise prefix-cache routing |
| `values-random.yaml` | 同一条 Envoy/EPP 路径 + `random-picker`（控制组） |
| `values-optimized.yaml` | fallback：optimized baseline（近似 prefix cache） |
| `bench_prefix.py` | 交错多轮 session 的压测客户端，输出 TTFT/TPOT/latency JSON |
| `run_bench.sh` | 客户端 Pod 的入口脚本（按 env 拼参数） |
| `bench-pod.yaml` | 压测客户端 Pod 模板（`envsubst` 渲染） |
| `plot_d4.py` | 从 JSON 画 TTFT P50/P95/P99 柱状图（宿主机跑，需要 matplotlib） |

## 最短路径

```bash
# 0. 在 llm-inference-platform-lab 根目录
export LAB=$(pwd)

# 1. 模型服务器（前置：k3s + NVIDIA device plugin + /models/Qwen3-8B-AWQ）
kubectl create namespace d4 --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n d4 -f scripts/d4/modelserver.yaml
kubectl wait --for=condition=Ready pod -l app=vllm-d4 -n d4 --timeout=900s

# 2. GAIE CRD + llm-d router
[ -d llm-d ] || git clone https://github.com/llm-d/llm-d.git
cd "${LAB}/llm-d" && git checkout release-1.0
kubectl apply -f "https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.6.2/v1-manifests.yaml"
helm upgrade --install d4-router oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d4 --version v1.0.0 \
  -f guides/recipes/router/base.values.yaml \
  -f "${LAB}/scripts/d4/values-precise.yaml"

# 3. 压测客户端 ConfigMap
cd "${LAB}"
kubectl create configmap d4-bench -n d4 \
  --from-file=bench_prefix.py=scripts/d4/bench_prefix.py \
  --from-file=run_bench.sh=scripts/d4/run_bench.sh \
  --dry-run=client -o yaml | kubectl apply -f -

# 4. 跑 direct（round-robin 基线）
export URL="http://vllm-direct:8000/v1/completions"
export ARM="direct" RUN="1" FORCE_CLOSE="1"
export POD_URLS=$(kubectl get pods -n d4 -l app=vllm-d4 \
  -o jsonpath='{range .items[*]}http://{.status.podIP}:8000,{end}' | sed 's/,$//')
export SESSIONS="32" TURNS="4" PREFIX_WORDS="1100" SUFFIX_WORDS="80"
export MAX_TOKENS="128" CONCURRENCY="16" SEED="42" WARMUP="4"
kubectl delete pod d4-bench -n d4 --ignore-not-found
envsubst < scripts/d4/bench-pod.yaml | kubectl apply -n d4 -f -
kubectl logs -f d4-bench -n d4

# 5. 跑 precise（把 URL 换成 router，FORCE_CLOSE=0，ARM=precise）
#    每轮前重启 EPP：kubectl rollout restart deploy/d4-router-epp -n d4
```

## 结果

- JSON 在宿主机 `/results/`（`bench-pod.yaml` 的 hostPath）。
- VM 销毁前 `scp` 回本地，放到 `results/d4/`。
- 画图：

```bash
python3 scripts/d4/plot_d4.py /results/direct-run1.json /results/precise-run1.json \
  --out /results/d4-ttft.png
```

## 注意

- 所有命令都在 **Vast 租的 2×24GB VM（Vast 无 L4 VM，实际 2×3090）** 上跑；不要碰 `uat-mobility-aks-01`。
- vLLM flag 可能随小版本变化，先看主文档 §3.4 的 `--help` 预检。
- precise 跑不通时用 `values-optimized.yaml`，结果里注明是 fallback。
