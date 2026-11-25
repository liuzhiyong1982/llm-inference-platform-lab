# D4.6 tiered-KV 脚本

主文档：[`../../d4.6-tiered-cache-lab.md`](../../d4.6-tiered-cache-lab.md)。结果：[`../../results/d4.6/summary.md`](../../results/d4.6/summary.md)。

## 文件

| 文件 | 用途 |
|---|---|
| `modelserver-hbm.yaml` | HBM-only 控制组：2 个 vLLM 副本，`gpu-memory-utilization=0.60`，无 connector |
| `modelserver-tiered.yaml` | Tiered 组：同上 + `OffloadingConnector` + 16GiB CPU tier |
| `values-hbm.yaml` | HBM-only router（和 tiered 相同，去掉 CPU producer/scorer） |
| `values-tiered.yaml` | Tiered router（GPU + CPU prefix index，`lruCapacityPerServer=1800`） |
| `run_arm.sh` | 单轮闭环：重启 EPP → 抓 metrics → 跑 bench → 抓 metrics |
| `analyze.py` | 读 JSON/metrics，生成总体、按 turn、offload、EPP 索引表 |
| `plot_d46.py` | 生成 `results/d4.6/d4.6-tiered-vs-hbm.png` |

压测客户端复用 `scripts/d4/bench_prefix.py` / `bench-pod.yaml`。

## 最短路径

```bash
export LAB=${LAB:-/root/lab}
kubectl create namespace d46 --dry-run=client -o yaml | kubectl apply -f -

# 1. HBM-only
kubectl apply -n d46 -f "${LAB}/scripts/d4.6/modelserver-hbm.yaml"
kubectl wait --for=condition=Ready pod -l app=vllm-hbm -n d46 --timeout=900s
cd "${LAB}/llm-d"
helm upgrade --install d46-router oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d46 --version v1.0.0 \
  -f guides/recipes/router/base.values.yaml \
  -f "${LAB}/scripts/d4.6/values-hbm.yaml"
cd "${LAB}"
for r in 1 2 3; do bash scripts/d4.6/run_arm.sh hbm vllm-hbm "$r"; done

# 2. tiered
kubectl delete -n d46 -f "${LAB}/scripts/d4.6/modelserver-hbm.yaml"
kubectl wait --for=delete pod -l app=vllm-hbm -n d46 --timeout=300s
kubectl apply -n d46 -f "${LAB}/scripts/d4.6/modelserver-tiered.yaml"
kubectl wait --for=condition=Ready pod -l app=vllm-tiered -n d46 --timeout=900s
cd "${LAB}/llm-d"
helm upgrade d46-router oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d46 --version v1.0.0 \
  -f guides/recipes/router/base.values.yaml \
  -f "${LAB}/scripts/d4.6/values-tiered.yaml"
cd "${LAB}"
for r in 1 2 3; do bash scripts/d4.6/run_arm.sh tiered vllm-tiered "$r"; done

# 3. 分析
python3 scripts/d4.6/analyze.py
```

## 注意

- **reset 必须 `?reset_external=true`**：默认 `/reset_prefix_cache` 只清 HBM，不清 CPU tier；否则第 2、3 轮吃上一轮缓存，P99 会假性变好。`bench_prefix.py` 已固定带上。
- **c=4，不是 c=8**：0.60 下 HBM KV 只有 3.6GiB，8×4k 活跃 KV ≈4.6GiB 会 preempt；c=4 实测 preemption 0。
- **EPP `/metrics` 要 RBAC**：`d46-metrics-reader` + `system:auth-delegator`，见主文档 §5.1。
- **`lruCapacityPerServer` 单位是 block**：16GiB / 9MiB ≈ 1800；`blockSizeTokens` 必须等于 vLLM `--block-size`。
- **`/dev/shm` 高水位不降**不代表 reset 失败；看 `external_prefix_cache_hits_total` 是否还涨。
- 结果目录：`/results/d4.6/`（hostPath），VM 销毁前 scp 回本地。
