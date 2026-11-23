# LLM Inference Platform Lab

`echo 我要测：TTFT P50/P95/P99、output tok/s、GPU util、$/1M tokens`

D1：单卡 L4 上的 vLLM serving 基线。执行步骤见 [`d1-vllm-baseline-runbook.md`](./d1-vllm-baseline-runbook.md)；D2 调参见 [`d2-vllm-tuning-runbook.md`](./d2-vllm-tuning-runbook.md)。

## 环境

- **GPU**：NVIDIA L4 24GB（23,034 MiB），**40W power cap**（`SW Power Cap Active`；不是默认 72W）
- **平台**：Vast.ai on-demand，实例 `61674313`，`$0.2611/h`
- **镜像**：`vllm/vllm-openai:v0.34.0`（镜像内 CUDA 13.0.2）
- **host**：driver 595.99.02（Max CUDA 13.2），24 vCPU / 125GB RAM
- **模型**：`Qwen/Qwen3-8B-AWQ`（约 5.7GB）
- **服务**：`max-model-len 8192`、`gpu-memory-utilization 0.90`、`max-num-seqs 64`、prefix caching 默认开
- **启动指标**：模型加载约 **69s**；KV cache **91,648 tokens**；8k 请求最大并发 **11.19x**
- **负载**：`vllm bench serve` → `/v1/completions`，random 数据集，输入 1024 / 输出 256，`--ignore-eos`，`--temperature 0`
- **采样**：`nvidia-smi` 每秒一次（util / 显存 / 功耗 / 温度 / SM clock）+ vLLM `/metrics` 抢占计数

## D1 baseline（2026-11-20）

c=16 / c=64 各跑两轮，表中为两轮中位数，括号内为范围；c=1 / c=4 单轮。

| 并发 c | n | 轮次 | TTFT P50 (ms) | TTFT P95 (ms) | TTFT P99 (ms) | 服务端排队 P99 (ms) | TPOT P95 (ms) | output tok/s | goodput (req/s) | GPU util mean/P95 | 抢占 Δ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 100 | 1 | 1,038 | 1,053 | 1,057 | n/a | 47.4 | 19.6 | 0.077 | 99.8% / 100% | 0 |
| 4 | 200 | 1 | 2,914 | 3,066 | 3,839 | n/a | 63.2 | 59.3 | 0.058 | 99.9% / 100% | 0 |
| 16 | 500 | 2 | 3,217 (3,212–3,222) | 7,459 (7,026–7,893) | 11,715 (10,917–12,514) | 9,051¹ | 135.7 (134.4–137.0) | 112.5 (111.9–113.0) | 0.0009 | 100% / 100% | 0 |
| 64 | 1,000 | 2 | 7,036 (7,033–7,040) | 14,551 (14,541–14,561) | 55,474 (55,454–55,495) | n/a | 469.9 (469.7–470.1) | 132.8 (132.7–132.8) | 0 | 100% / 100% | 0 |

¹ 来自单独的诊断跑：c=16、n=200、服务端开 `--enable-per-request-metrics`。`server_queue_times` 单位是秒，已换算成 ms。baseline 的四个 JSON 没有这个字段，其余点写 `n/a`。

重复性：c=64 两轮几乎完全一致（吞吐差 0.1%）；c=16 吞吐/TPOT 稳定，TTFT P99 有约 13% 的尾部波动。

## 诊断：排队 vs prefill

诊断跑（c=16、n=200、同一台 40W L4）：

| 指标 | P50 | P95 | P99 |
|---|---|---|---|
| 客户端 TTFT | 4,559 ms | 7,877 ms | 13,507 ms |
| 服务端调度排队 `server_queue_times` | ~0 ms | 2,504 ms | 9,051 ms |
| 服务端首 token `server_ttfts` | 3,038 ms | 5,788 ms | 5,911 ms |
| 同一请求 `排队 + 首 token` | 3,045 ms | 6,171 ms | 12,738 ms |
| 差额（前端/网络/tokenization） | 1,057 ms | 1,959 ms | 1,982 ms |

- 排队是双峰的：约 90% 请求排队几乎为 0，约 10% 排队数秒，P99 到 9.05s；
- 服务端首 token 在 c=16 下 P50 已到 3.0s（c=1 时客户端 TTFT 才 1.0s），说明 chunked prefill 与 decode 争抢后，prefill 被拉长；
- 同一请求相加后的 P99 是 12.74s，客户端 TTFT P99 13.51s，差约 0.8s 是 API 前端/网络开销。
- decode 也不是匀速：展平 `itls` 后 P50 80ms、P99 1.83s、P99.9 1.99s，但 per-request TPOT P95 只有 133.5ms——每条请求的 255 个 gap 里中位数有 8 个超过 1s，被平均掉了。所以“TPOT 达标”不等于“没有卡顿”。
- 停顿不是抢占（计数为 0），更像 prefill 调度步长：一个 iteration 塞进大块 prefill 时，decode 要等这一大步算完。D2 用 `--max-num-batched-tokens 512` 直接压小步长；`--disable-chunked-prefill` 只有在固定 2048 预算下才可比（默认会自动把预算抬到 8192，见 D2 runbook §4.3）。

## 一句话结论

在这台 **40W 限功耗**的 L4 上，c=1→16 时 output throughput 从 19.6 升到 112.5 tok/s（×5.7），但 TTFT P99 从 1.06s 升到 11.7s（×11）、TPOT P95 从 47ms 升到 136ms（×2.9）；c=16→64 吞吐只再 +18%，TPOT P95 到 470ms、TTFT P99 到 55.5s、goodput 归零。诊断跑显示 c=16 的尾部主要是**调度排队（P99 9.05s）**加**服务端首 token（P99 5.91s）**，decode TPOT P95 133.5ms，四轮抢占均为 0。因此瓶颈是 **40W 功耗墙下的 batching/排队**，不是 KV cache 不足；这台卡不能直接和公开的 72W L4 数字对比。

## 成本

Vast Charges：**$1.01**（GPU + 存储，2026-11-20，实例 `61674313`）。GPU 单价 `$0.2611/h`。

## 复现

1. 按 `d1-vllm-baseline-runbook.md` 租同规格 on-demand L4，记录 `power.limit`；
2. 用 `vllm/vllm-openai:v0.34.0` 和 `Qwen/Qwen3-8B-AWQ` 起服务；
3. 跑 c=1/4/16/64，结果写 `results/`；
4. 需要拆排队时，用 §6 的诊断跑；
5. 重复 c=16/64 时按 §5.4，报中位数/范围。

## 下一步

D2 的参数对比、概念问答（chunked prefill / batched tokens / prefix caching / AWQ）和执行步骤见 `d2-vllm-tuning-runbook.md`。
