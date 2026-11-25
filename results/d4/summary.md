# D4 summary — llm-d precise prefix-cache routing

## Setup

- **GPU**：2×RTX 3060 12GB（instance `62540497`，UK，`$0.26148/h` 含 130GB disk）
- **Driver / CUDA**：580.178.04 / CUDA 13.0；power limit 170W/卡
- **Model**：`Qwen/Qwen3-4B-AWQ`（served name `qwen3-4b`）
- **Versions**：vLLM `v0.34.0`、llm-d router standalone `v1.0.0`、GAIE `v1.6.2`、k3s `v1.37.2+k3s1`
- **Topology**：2 个 vLLM Pod × 1 GPU；TP=1；EPP replicas=1；`block-size=64`；`max-model-len=8192`；`max-num-seqs=16`；`gpu-memory-utilization=0.90`
- **`peakPrefillThroughput`**：2657（calibration 4096 token，median TTFT 1.5413s，经 EPP 的部署口径）
- **Workload**：32 sessions × 4 turns = 128 requests；prefix 1100 words（约 1.5k tokens）；suffix 80；`max_tokens=128`；c=16；seed=42；warmup=4

## Results（中位数；direct / optimized / precise 各 3 轮，random 1 轮）

| arm | n | ok / errors | TTFT P50 | TTFT P95 | TTFT P99 | TPOT P50 | output tok/s | goodput |
|---|---|---|---|---|---|---|---|---|
| direct | 3 | 384 / 0 | 628 ms | 3114 ms | 4475 ms | 27.6 ms | 424 | 0.914 |
| random | 1 | 128 / 0 | 798 ms | 3739 ms | 5056 ms | 26.1 ms | 438 | 0.844 |
| **optimized** | 3 | 384 / 0 | **216 ms** | **3140 ms** | **3459 ms** | **20.8 ms** | **570** | **0.906** |
| precise | 3 | 384 / 0 | 298 ms | 3292 ms | 3969 ms | 20.9 ms | 558 | 0.875 |

> direct 的 run1 是冷缓存（P50 1227ms），表中取 3 轮中位数；范围 P50 628–1227ms、P99 3866–4506ms。

## Attribution（TTFT P99）

| 对比 | ΔP99 | 解释 |
|---|---|---|
| direct → random | **+581 ms** | Envoy + EPP 的代理税；随机路由打散前缀缓存 |
| random → optimized | **−1597 ms** | 近似前缀亲和生效 |
| optimized → precise | **+510 ms** | render 平均 42 ms/请求 + 精确索引开销 > 准确性收益 |
| direct → precise | −506 ms（−11%） | 总收益存在，但不如 optimized |
| direct → optimized | **−1016 ms（−22.7%）** | 本次最佳 |

**结论**：在 2 副本、1.5k 长前缀、无驱逐压力的场景下，`optimized` 的近似索引已经够用；`precise` 的 render 成本没有被额外命中率抵消。precise 的价值应随副本数、驱逐频率、旁路 EPP 的请求比例上升。

## Failures / 调试记录

- `POST /reset_prefix_cache` 返回 404：vLLM 0.34 需要 `VLLM_SERVER_DEV_MODE=1`；否则 arm 之间缓存不干净。
- EPP `/metrics` 返回 401：默认 `--metrics-endpoint-auth=true`；需要给 scraper 绑 `/metrics` reader、给 EPP SA 绑 `system:auth-delegator`，再用 SA token 抓。
- tmux 旧 pane 不继承 `/etc/environment`：`tmux setenv -g LAB /root/lab` 只对新 pane 生效，当前 pane 要 `export`。
- 2 sessions 的 smoke 出现 5/5 分流，不是故障：一个 session 粘一个 Pod；判据是 `decisions_total{outcome="sticky"}` +8。
- 未逐 arm 采样 per-pod prefix hit rate（客户端 JSON 不含 cached_tokens）；结论使用 TTFT/goodput，不依赖该表。

## Cost

- Vast 计费时长：16344s ≈ **4.54h**
- `$0.26148/h` × 4.54h ≈ **$1.19**
