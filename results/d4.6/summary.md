# D4.6 Tiered KV Cache vs HBM-only — 结果

> 执行日期：2026-11-25（UTC）。实例：Vast.ai `62540497`，2×RTX 3060 12GB，`$0.2615/h`。
> 模型：Qwen3-4B-AWQ（`qwen3-4b`）。vLLM `v0.34.0`，llm-d `v1.0.0`。
> 结论先行：**tiered 把 P50 降了 77%、goodput 提了 36%，但没有改善整体 P95/P99**——因为 25% 的请求是 turn 1 冷启动，tiered 不能消除首次 prefill。复用请求（turn 2–4）的 P50 从 1.44s 降到 0.29s，机制本身是成立的。

## 1. Setup

| 项 | 值 |
|---|---|
| GPU | 2×RTX 3060 12GB，driver 580.178.04，power limit 170W |
| Host | 40 vCPU / 98GB RAM / 130GB disk |
| Model | Qwen3-4B-AWQ，TP=1，2 副本 |
| vLLM | `vllm/vllm-openai:v0.34.0` |
| llm-d | `llm-d-router-standalone:v1.0.0` |
| Engine flags | `--max-model-len=8192 --gpu-memory-utilization=0.60 --max-num-seqs=16 --max-num-batched-tokens=4096 --block-size=64 --enable-prefix-caching` |
| HBM KV | **3.6GiB / 24,576 tokens / 384 blocks**（每副本） |
| CPU tier | **16GiB / ≈1820 blocks**（`cpu_bytes_to_use=17179869184`） |
| Router | HBM arm：GPU index；tiered arm：GPU + CPU index，`lruCapacityPerServer=1800`，`blockSizeTokens=64` |
| Workload | 32 sessions × 4 turns，prefix 3000 words（prompt P50 3658 tokens），suffix 80 words，max_tokens 128，c=4，seed 42，warmup 4 |
| 每轮 | 128 请求，16,384 output tokens |

**为什么 c=4 而不是文档原计划的 c=8：** 0.60 下 HBM KV 只有 3.6GiB，8 个 4k-token 请求的活跃 KV ≈ 4.6GiB，必然触发 vLLM preemption，混入“抢占”而不仅是“offload”。c=4 的活跃 KV ≈ 2.3GiB，实测 `num_preemptions_total=0`。

## 2. 总体结果（3 轮，c=4）

| arm | run | ok | TTFT P50 | TTFT P95 | TTFT P99 | TPOT P95 | goodput | output tok/s | wall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hbm | 1 | 128/128 | 1418 | 2458 | 2809 | 36.7 | 0.841 | 114.9 | 142.6s |
| hbm | 2 | 128/128 | 1434 | 2479 | 2542 | 36.9 | 0.810 | 115.4 | 142.0s |
| hbm | 3 | 128/128 | 1451 | 2527 | 2737 | 35.9 | 0.795 | 115.3 | 142.1s |
| **hbm 中位数** | 3 | — | **1434** | **2479** | **2737** | **36.7** | **0.810** | **115.3** | **142.1s** |
| tiered | 1 | 128/128 | 336 | 2426 | 2561 | 26.0 | 1.163 | 161.5 | 101.5s |
| tiered | 2 | 128/128 | 402 | 2533 | 2559 | 25.9 | 1.105 | 160.2 | 102.3s |
| tiered | 3 | 128/128 | 331 | 2505 | 2717 | 25.9 | 1.103 | 162.7 | 100.7s |
| **tiered 中位数** | 3 | — | **336** | **2505** | **2561** | **25.9** | **1.105** | **161.5** | **101.5s** |

中位数变化：

| 指标 | HBM-only | tiered | 变化 |
|---|---:|---:|---:|
| TTFT P50 | 1434ms | 336ms | **−76.6%** |
| TTFT P95 | 2479ms | 2505ms | +1.0% |
| TTFT P99 | 2737ms | 2561ms | −6.4% |
| TPOT P95 | 36.7ms | 25.9ms | −29.4% |
| goodput | 0.810 req/s | 1.105 req/s | **+36.4%** |
| output tok/s | 115.3 | 161.5 | **+40.0%** |
| wall time | 142.1s | 101.5s | **−28.6%** |
| SLO 达标率 | 89.8% | 88.3% | −1.7%（噪声范围内） |

## 3. 按 turn 拆：冷启动 vs 复用

| arm | turn | n/轮 | TTFT P50（3 轮中位数） | 说明 |
|---|---|---:|---:|---|
| hbm | turn 1 | 32 | 1327ms | 冷启动，必须完整 prefill |
| hbm | turn 2–4 | 96 | **1444ms** | HBM 命中率只有 5.9%，绝大多数还是重算 |
| tiered | turn 1 | 32 | 1339ms | 冷启动，和 HBM 一样 |
| tiered | turn 2–4 | 96 | **289ms** | CPU tier 命中，拉回代替重算 |

- 复用请求 P50：**1444ms → 289ms（−80.0%）**；这是 tiered 真正的收益来源。
- 冷启动 P50：1327ms → 1339ms（基本不变）；tiered 不能加速首次 prefill，偶尔还会因为驱逐写 CPU 而略慢（run3 turn 1 P50 1872ms）。
- 整体 P95/P99 由 turn 1 冷请求决定：128 个请求里 32 个（25%）是冷启动，P99 落在冷启动尾部，所以 tiered 的 P99 不会明显变好。

## 4. 机制证据（vLLM metrics，两副本求和，单轮增量）

| arm | run | CPU store | CPU load | CPU hit | HBM hit | preemptions | store time | load time |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hbm | 1 | 0 | 0 | 0% | 5.8% | 0 | 0 | 0 |
| hbm | 2 | 0 | 0 | 0% | 6.5% | 0 | 0 | 0 |
| hbm | 3 | 0 | 0 | 0% | 5.9% | 0 | 0 | 0 |
| tiered | 1 | 28.17GiB | 32.62GiB | 53.1% | 4.6% | 0 | 2.39s | 3.13s |
| tiered | 2 | 28.71GiB | 30.77GiB | 51.2% | 6.6% | 0 | 2.47s | 2.96s |
| tiered | 3 | 27.77GiB | 32.07GiB | 53.1% | 6.0% | 0 | 2.37s | 3.06s |

解读：

- **store 28GiB/run**：HBM 装不下的前缀块确实被写到 CPU tier；`/dev/shm` 高水位 16G/18G。
- **load 31GiB/run，CPU hit 51–53%**：后续请求真的从 CPU tier 拉回，不是只存不用。
- **preemption 0**：c=4 下没有抢占污染，差异来自 offload/hit，不是 vLLM 的 recompute preemption。
- **load time ≈3s/run**：128 个请求里约一半命中，摊到每个命中请求约 **50ms**；而重算 3.6k token 的 prefill 约 **1.4s**，差约 30×。这就是复用 P50 从 1.44s 降到 0.29s 的原因。

## 5. EPP CPU 索引交叉验证

| arm | run | GPU index | GPU hit | CPU index | CPU hit |
|---|---:|---:|---:|---:|---:|
| hbm | 1–3 | 768 | 3.6% | 0 | 0% |
| tiered | 1 | 768 | 3.5% | 3600 | 51.6% |
| tiered | 2 | 768 | 4.3% | 3600 | 46.8% |
| tiered | 3 | 768 | 2.9% | 3600 | 48.7% |

- `GPU index = 768` = 2 pods × 384 blocks（24,576 tokens / 64），和 vLLM HBM 容量一致。
- `CPU index = 3600` = 2 pods × 1800 blocks（16GiB / 9MiB），和 `lruCapacityPerServer=1800` 一致。
- EPP CPU hit 47–52%，vLLM `external_prefix_cache_hits/queries` 51–53%，两边对得上：路由器确实把请求钉在了 CPU tier 有块的副本上。
- 每轮前重启 EPP，after 快照里 index size 从 0 长到 768/3600；before 快照为 0，说明索引是每轮重建的。

## 6. 归因与结论

**为什么 P50 赢：** 复用请求命中 CPU tier，`CPU→GPU` 拷贝约 50ms，取代了 3.6k-token 的重算（约 1.4s）。128 个请求里 96 个是复用请求，所以中位数从 1.43s 降到 0.34s。

**为什么 P95/P99 不赢：** 25% 的请求是 turn 1 冷启动，必须完整 prefill（约 1.3–2.6s）。整体 P99 取到的是冷启动尾部，不是缓存命中路径。要看 tiered 的尾延迟，应该看 turn 2–4 的 P99（median 1687ms vs HBM 2649ms），或做 warm-cache 稳态实验；不能拿含 25% 冷启动的整体 P99 判断 tiered。

**为什么 goodput 赢：** 同样的 128 请求、同样的输出 token 数，tiered 用 101s 完成，HBM 用 142s；goodput 从 0.81 提到 1.10 req/s（+36%），output tok/s 从 115 提到 161（+40%）。但 SLO 达标率没有提升（89.8% → 88.3%），因为未达标的主要是冷 turn 1；tiered 提升的是“单位时间完成多少请求”，不是“每个请求都达标”。

**一句话结论：**

> 在 2×3060 12GB / 16GiB CPU tier / 3.6k-token 前缀 / 32 sessions 下，tiered KV **值得做吞吐和中位数优化**（P50 −77%，goodput +36%），但**不是 P99 银弹**；它的收益边界是“工作集能放进 HBM+CPU，且请求有复用”，冷启动 tail 需要 warmup、请求隔离或更大的 tier。

**什么时候会翻盘：**

- 工作集远大于 HBM+CPU：CPU tier 也会驱逐，hit rate 下降，收益变小；
- 前缀复用距离太远 / 请求没有重复前缀：store 有、load 很少，纯亏拷贝；
- 上下文更长、复用更高：重算成本更高，tiered 的相对收益更大；
- 需要 P99：必须先消除冷启动，或把冷请求与热请求分开做容量规划。

## 7. 方法学：第一次 tiered 结果是错的

第一次跑 tiered 时，bench 用的是：

```text
POST /reset_prefix_cache
```

vLLM 的默认行为是 **`reset_external=false`**：只清 HBM 前缀缓存，**不清 `OffloadingConnector` 管理的 CPU tier**。结果：

```text
run1: CPU hit 59.2%, store 23.8GiB, load 35.3GiB
run2: CPU hit 86.9%, store  7.3GiB, load 52.6GiB
run3: CPU hit 95.4%, store  2.2GiB, load 57.8GiB
```

CPU tier 越跑越热，P99 从 2.5s 降到 1.4s，看起来“tiered 完胜”。复查 `/dev/shm` 发现 16G/18G，确认后两轮吃了前一轮的缓存。改成：

```text
POST /reset_prefix_cache?reset_external=true
```

重跑后 CPU hit 稳定在 51–53%，store 稳定在 28GiB/run，P99 回到 2.5s。**这组干净数据才是本文的结论。** 受控验证：同一前缀先驱逐到 CPU，再打一次，`external_prefix_cache_hits_total` +3648、`kv_offload_load_bytes_total` +513MiB；reset 后再打，hits +0、load +0、TTFT 1.43s（冷）。

> 这个 bug 已修在 `scripts/d4/bench_prefix.py` 的 `reset_caches()`：现在固定请求 `?reset_external=true`。没有 connector 的 engine 会把它当 no-op，所以 D4 的 HBM-only 结果不受影响。

## 8. 成本

| 项 | 值 |
|---|---|
| 实例 | Vast.ai `62540497`，2×3060 12GB，`$0.2615/h` |
| D4.6 增量 | ~1.1h，**~$0.29**（复用 D4 的 VM，未重新 bootstrap） |
| 实例累计 | ~6.3h，**~$1.66**（含 D4 收尾与 D4.6） |
| 余额 | 约 **$13.3**（初始 $15） |

## 9. 复现

```bash
# VM 上
export LAB=/root/lab
cd "$LAB"

# 1. HBM-only
kubectl apply -n d46 -f scripts/d4.6/modelserver-hbm.yaml
kubectl wait --for=condition=Ready pod -l app=vllm-hbm -n d46 --timeout=900s
helm upgrade --install d46-router \
  oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d46 --version v1.0.0 \
  -f llm-d/guides/recipes/router/base.values.yaml \
  -f scripts/d4.6/values-hbm.yaml

for r in 1 2 3; do
  bash scripts/d4.6/run_arm.sh hbm vllm-hbm "$r"
done

# 2. tiered
kubectl delete -n d46 -f scripts/d4.6/modelserver-hbm.yaml
kubectl wait --for=delete pod -l app=vllm-hbm -n d46 --timeout=300s
kubectl apply -n d46 -f scripts/d4.6/modelserver-tiered.yaml
kubectl wait --for=condition=Ready pod -l app=vllm-tiered -n d46 --timeout=900s
helm upgrade d46-router \
  oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d46 --version v1.0.0 \
  -f llm-d/guides/recipes/router/base.values.yaml \
  -f scripts/d4.6/values-tiered.yaml

for r in 1 2 3; do
  bash scripts/d4.6/run_arm.sh tiered vllm-tiered "$r"
done

# 3. 分析
python3 scripts/d4.6/analyze.py
```

`run_arm.sh` 每轮会：重启 EPP（冷索引）→ 抓 vLLM/EPP metrics → 跑 128 请求（bench 先 `reset_external=true`）→ 再抓 metrics。

## 10. 文件

| 文件 | 内容 |
|---|---|
| `hbm-run{1,2,3}.json` | HBM-only 三轮客户端结果 |
| `tiered-run{1,2,3}.json` | tiered 三轮客户端结果 |
| `metrics-*-before/after-*.txt` | 每轮每副本 vLLM `/metrics` 快照 |
| `epp-*-before/after.txt` | 每轮 EPP `/metrics` 快照 |
| `d4.6-tiered-vs-hbm.png` | 三联图：整体 TTFT、冷/热 P50、goodput |
| `cost.txt` | Vast 实例年龄/单价/增量成本记录 |
| `scripts/d4.6/analyze.py` | 生成上面的表 |
| `scripts/d4.6/plot_d46.py` | 生成图 |
| `scripts/d4.6/run_arm.sh` | 单轮闭环 |
