# D4.6 tiered-KV 脚本

主文档：[`../../d4.6-tiered-cache-lab.md`](../../d4.6-tiered-cache-lab.md)。

## 文件

| 文件 | 用途 |
|---|---|
| `modelserver-hbm.yaml` | HBM-only 控制组：2 个 vLLM 副本，`gpu-memory-utilization=0.60` |
| `modelserver-tiered.yaml` | Tiered 组：同上 + `OffloadingConnector` + 16GiB CPU tier |
| `values-hbm.yaml` | HBM-only router（和 tiered 相同，去掉 CPU producer/scorer） |
| `values-tiered.yaml` | Tiered router（GPU + CPU prefix index） |

压测客户端复用 `scripts/d4/bench_prefix.py` / `bench-pod.yaml`。

## 最短路径

```bash
export LAB=$(pwd)

# 0. 2×3060 12GB VM / k3s / GPU / 权重见主文档 §4（instance 62540497；2×L4 VM 不存在）
kubectl create namespace d46 --dry-run=client -o yaml | kubectl apply -f -

# 1. HBM-only
kubectl apply -n d46 -f scripts/d4.6/modelserver-hbm.yaml
kubectl wait --for=condition=Ready pod -l app=vllm-hbm -n d46 --timeout=900s
cd "${LAB}/llm-d"
helm upgrade --install d46-router oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d46 --version v1.0.0 \
  -f guides/recipes/router/base.values.yaml \
  -f "${LAB}/scripts/d4.6/values-hbm.yaml"

# 2. 跑 HBM 3 轮（见主文档 §5.3）

# 3. 切 tiered
kubectl delete -n d46 -f "${LAB}/scripts/d4.6/modelserver-hbm.yaml"
kubectl apply -n d46 -f "${LAB}/scripts/d4.6/modelserver-tiered.yaml"
kubectl wait --for=condition=Ready pod -l app=vllm-tiered -n d46 --timeout=900s
helm upgrade d46-router oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d46 --version v1.0.0 \
  -f guides/recipes/router/base.values.yaml \
  -f "${LAB}/scripts/d4.6/values-tiered.yaml"

# 4. 验证 store/load，再跑 tiered 3 轮（见主文档 §6）
```

## 注意

- CPU tier 在 `/dev/shm`，**计入 Pod memory limit**；2×16GiB + vLLM 需要 ≥96GB host；本次 VM 内 98GB，刚够，余量约 30–40GB。
- Qwen3-4B 的 KV 几何与 8B 相同（36 层 × 8 KV head × head_dim 128）≈ 144KiB/token；16GiB / (64×144KiB) ≈ 1800 blocks。
- `gpu-memory-utilization=0.60` 是故意的，让 HBM 先驱逐；生产不要照抄。
- tiered 输了也是有效结论：3060 12GB 上 CPU→GPU 拉回可能比重算慢；3090/L4 的结论不能直接搬。
