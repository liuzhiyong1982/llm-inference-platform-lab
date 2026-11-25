# D4.5 PD lab 脚本

主文档：[`../../d4.5-pd-lab.md`](../../d4.5-pd-lab.md)。

## 文件

| 文件 | 用途 |
|---|---|
| `colocated-4x.yaml` | 4 个完整 vLLM 副本（每个 1×24GB GPU；实际 4090） |
| `values-colocated.yaml` | colocated 控制组的 llm-d EPP（approx prefix + token load） |
| `pd-2p2d.yaml` | `DisaggregatedSet`：2 prefill + 2 decode（每个 1×24GB GPU；实际 4090） |
| `values-pd.yaml` | PD 的 llm-d router（prefill/decode profiles） |

压测客户端复用 `scripts/d4/bench_prefix.py`、`run_bench.sh`、`bench-pod.yaml`。

## 最短路径

```bash
export LAB=${LAB:-$(pwd)}   # VM 上先 export LAB=/root/lab

# 0. 4×4090 VM / k3s / GPU / 权重见主文档 §4（4×L4 VM 不存在）

# 1. LWS + GAIE
export LWS_VERSION=1.0.0
helm pull oci://registry.k8s.io/lws/charts/lws --version=${LWS_VERSION} --untar
kubectl apply --server-side --force-conflicts -f lws/crds
helm upgrade --install lws oci://registry.k8s.io/lws/charts/lws \
  --version=${LWS_VERSION} --namespace lws-system --create-namespace \
  --set enableDisaggregatedSet=true --wait --timeout 300s
kubectl apply -f "https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.6.2/v1-manifests.yaml"
kubectl create namespace d45 --dry-run=client -o yaml | kubectl apply -f -

# 2. colocated 4 副本
kubectl apply -n d45 -f scripts/d4.5/colocated-4x.yaml
kubectl wait --for=condition=Ready pod -l app=vllm-colocated -n d45 --timeout=900s

cd "${LAB}/llm-d"
helm upgrade --install d45-router oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d45 --version v1.0.0 \
  -f guides/recipes/router/base.values.yaml \
  -f "${LAB}/scripts/d4.5/values-colocated.yaml"

# 3. 压测（见主文档 §5.3）
# 4. 清理 colocated：
helm uninstall d45-router -n d45
kubectl delete -n d45 -f "${LAB}/scripts/d4.5/colocated-4x.yaml"

# 5. PD 2P+2D
kubectl apply -n d45 -f "${LAB}/scripts/d4.5/pd-2p2d.yaml"
kubectl get pods -n d45 -l llm-d.ai/guide=pd-disaggregation -o wide -w

cd "${LAB}/llm-d"
helm upgrade --install d45-router oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d45 --version v1.0.0 \
  -f guides/recipes/router/base.values.yaml \
  -f "${LAB}/scripts/d4.5/values-pd.yaml"
```

## 注意

- PD 的 vLLM 固定 **v0.31.0**（llm-d PD guide 的 pin）；colocated 也用 v0.31.0，保证公平。
- decode Pod 的 sidecar 是 8000，engine 是 8200；`POD_URLS` 要包含 prefill 8000 + decode 8200。
- 4×L4 VM 不存在；只能用 4×4090 VM，必须标明显卡型号。
- 5h 缩小版目标 ≤$10；6h 已经 $11.2，到点先 scp 再 Destroy。
