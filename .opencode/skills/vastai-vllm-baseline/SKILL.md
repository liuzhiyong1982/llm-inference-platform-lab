---
name: Vast.ai vLLM Baseline
description: Rent a single L4 on Vast.ai and produce a reproducible vLLM serving baseline (TTFT/TPOT/throughput, GPU util, preemption, cost), including version compatibility, SSH/tmux, model download, benchmark and diagnostic runs, and metric/goodput interpretation.
---

# Vast.ai vLLM Baseline

## 何时使用

- 要在租来的单卡（L4/A10 等）上跑 vLLM，产出可复现的 serving baseline；
- 要解释 TTFT / TPOT / output tok/s / goodput 为什么随并发变化；
- 遇到 Vast 租卡、SSH、tmux、CUDA/driver 版本、模型下载、bench flag 的问题；
- 准备 D2 调参或 D3–D5 系统对比，需要先有一套可信的对照基线。

如果当前仓库有 `d1-vllm-baseline-runbook.md`，**以它为准**；本 skill 是跨项目的精简 playbook 和排错清单。

## 工作方式（重要）

- 除非用户明确说“你帮我跑”，**不要替用户执行实验命令**。给命令 + 解释，让用户自己跑；用户要的是学习，不是代跑。
- 每条新命令先写进 runbook，再在对话里使用；**对话和文档必须一致**。
- 先 baseline，后调参。没有可信 baseline 的“优化”都是噪声。
- 一次只动一个变量；同一台机器、同一 power limit、同一输入/输出长度、同一 SLO。

## 心智模型

### 版本链

```
GPU 架构 (L4 = sm_89)
  → driver（决定 Max CUDA，等于 nvidia-smi 右上角）
  → 镜像内 CUDA runtime（CUDA_VERSION）
  → PyTorch/vLLM 编译目标
```

两条约束缺一不可：

1. 镜像 `CUDA_VERSION` ≤ driver 的 Max CUDA，且**不跨大版本**；
2. GPU 的 compute capability 在镜像的 `TORCH_CUDA_ARCH_LIST` 里，否则 `no kernel image is available`。

`cuda_vers` 是 driver 推导出来的上限，不是 toolkit 版本；具体 driver 版本只在排查已知 bug 时看。

### 指标口径

**单请求**

| 指标 | 全称 | 定义 / 公式 |
|---|---|---|
| TTFT | Time To First Token | 请求发出到首 token；闭路压测含服务端排队，不只是 prefill |
| ITL | Inter-Token Latency | 相邻流式 chunk 的间隔；**单请求内 `mean(ITL) = TPOT`**；别名 TBT |
| TPOT | Time Per Output Token | `(e2el - ttft) / (output_tokens - 1)`；output=1 时按 0；即该请求 ITL 的算术平均 |
| E2EL | End-to-End Latency | 端到端延迟；常简写 E2E |

**TPOT vs ITL：同一份数据的两种切法。**

- ITL 是 **token 级分布**（N×255 个样本），TPOT 是 **请求级均值**（N 个样本）。单请求内二者相等，聚合后的百分位不是一回事。
- ITL 保留尖峰，TPOT 把尖峰摊平：D1 c=16 的 ITL P99.9 = 2.0s，而 TPOT P95 只有 137ms（每条请求 255 个 gap 里中位数有 13 个 >1s）；c=64 的 ITL P50 = 205ms，TPOT P50 = 453ms（中位数 34 个 gap >1s）。
- **查抖动看 ITL，算 SLO/容量看 TPOT。** `--goodput tpot:100` 用 per-request TPOT，平均达标即算过，中间有秒级停顿也可能合格——这是偏乐观的口径。
- 一个 chunk 多个 token（投机解码/非流式）时 `TPOT < mean(ITL)`，ITL 只是 chunk 间隔。

**聚合**

- `request_throughput = completed / duration`
- `output_throughput = sum(output_tokens) / duration`（不含 prefill）
- `total_token_throughput = (input + output) / duration`
- `goodput = good_completed / duration`，单位 **req/s，不是百分比**
- 达标比例 = `goodput / request_throughput`
- `duration` 是墙钟时长，包含 ramp-up、排队和尾部，不是延迟之和

**goodput 是逐请求 AND**：`ttft <= SLO_ttft` 且 `tpot <= SLO_tpot`（配了 e2el 也要满足）。`--goodput ttft:2000 tpot:100` 单位是 ms，内部转秒。P95 达标 ≠ goodput 高；goodput 要求每一条都达标。

**百分位**：对 per-request 数组算；P50=中位数，mean≠median；**百分位不能相加**，要先把同一请求的两项相加再算 P99。

**指标来源**

| 来源 | 指标 |
|---|---|
| `vllm bench serve`（客户端） | TTFT/TPOT/ITL/E2EL、throughput、goodput、百分位 |
| vLLM `/metrics` | 抢占、running/waiting、KV cache 使用率、prefix cache |
| vLLM 启动日志 | 加载耗时、KV cache 大小、最大并发 |
| vLLM per-request（opt-in） | `server_queue_times`、`server_ttfts`（秒） |
| nvidia-smi / NVML | util、显存、功耗、温度、clock、driver/CUDA |

两对易混：客户端 TTFT ≠ `server_ttfts`；`utilization.gpu` ≠ `vllm:gpu_cache_usage_perc`（前者是有 kernel 在跑的时间占比，后者是 KV 块使用率）。

## 流程

### 1. 选机器

硬条件：

| 条件 | 门槛 |
|---|---|
| 计费 | **on-demand**，不要 interruptible |
| GPU | 型号明确（如 L4 24GB），不是 RTX 消费卡替代 |
| Max CUDA | ≥ 镜像的 `CUDA_VERSION`（vLLM 0.34 镜像是 13.0.2，填 13.0） |
| Reliability | ≥ 98%，最好 ≥ 99% |
| Inet down | ≥ 500 Mbps |
| 磁盘 | ≥ 40GB（创建后不能扩容） |
| 租期 | > 6 小时 |
| **Power limit** | 优先 72W；40W 会显著降低吞吐，必须记录 |

Vast 网页默认满屏 RTX 4090/5090；L4 是数据中心卡，不在 RTX 分类。CLI 更可靠：

```bash
# -n 去掉默认 verified=true；-o dph 按含盘总价升序
vastai search offers -n \
  'gpu_name=L4 num_gpus=1 rentable=true reliability>=0.98 cuda_vers>=13.0 inet_down>=500 disk_space>=40 duration>0.25' \
  -o 'dph' --storage 40 --limit 20
```

创建（默认 on-demand；**不要加 `--bid_price`**）：

```bash
vastai create instance <offer_id> \
  --image vllm/vllm-openai:v0.34.0 \
  --disk 40 --ssh \
  --env '-p 8000:8000' \
  --label d1-l4-baseline
```

固定镜像 tag，不要 `latest`（nightly 的 CUDA 和 flag 都会漂）。

### 2. SSH 与 tmux

```bash
vastai show instances
vastai ssh-url <id>      # 输出 ssh://root@host:port
vastai scp-url <id>
vastai logs <id>
```

`ssh://` 是 URI，不能直接粘进 bash：

```bash
ssh -i ~/.ssh/<key> -p <port> root@<host>
```

- 实例 `stopped` 时连不上，先 `vastai start instance <id>`。
- 本机没有默认 `id_rsa`/`id_ed25519` 时必须显式 `-i`；公钥没注册：
  `vastai create ssh-key "$(cat ~/.ssh/<key>.pub)"` + `vastai attach ssh <id> ...`。
- Vast 的 `.bashrc` 会自动 `tmux attach -t ssh_tmux`，**每个 SSH 都进同一个会话**。用 `Ctrl-b c` 开新窗口，`Ctrl-b 0/1` 切换，`Ctrl-b d` 脱离。不要 `tmux kill-server`（会杀 vLLM）。

### 3. 容器 preflight

```bash
mkdir -p /workspace          # 有些镜像没有这个目录，/ 就是容器盘
nvidia-smi
df -h /
python3 -V                   # 镜像通常只有 python3
python3 -c "import vllm; print(vllm.__version__)"
python3 -c "import torch; print(torch.__version__, torch.version.cuda)"
vllm bench serve --help >/dev/null && echo ok
```

版本/功耗核对：

```bash
nvidia-smi --query-gpu=name,memory.total,driver_version,compute_cap,power.limit,power.draw,clocks.sm \
  --format=csv,noheader
```

vLLM 0.34 的 help 按 ConfigGroup 分组，必须 `--help=all` 才能 grep 到 flag：

```bash
vllm serve --help=all | grep -E "enable-per-request-metrics|prefix-caching"
vllm bench serve --help=all | grep -E "ignore-eos|metric-percentiles|save-detailed|goodput"
```

### 4. 下载模型

hub 2.4 用 Xet；`HF_HUB_ENABLE_HF_TRANSFER` 已弃用，用 `HF_XET_HIGH_PERFORMANCE=1`：

```bash
export HF_HOME=/workspace/hf
export HF_XET_HIGH_PERFORMANCE=1
python3 - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen3-8B-AWQ")
PY

# 关键：Xet 快照里是符号链接，du 不加 -L 会只看到几 MB
du -shL "$HF_HOME/hub/models--Qwen--Qwen3-8B-AWQ"
```

匿名下载会被限速；有 token 可 `export HF_TOKEN=hf_xxx`，不要写进 git。

### 5. 起服务

```bash
cd /workspace
vllm serve Qwen/Qwen3-8B-AWQ \
  --served-model-name qwen3-8b \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --max-num-seqs 64 \
  --disable-log-requests \
  --host 0.0.0.0 --port 8000 \
  2>&1 | tee /workspace/vllm.log
```

- `--served-model-name` 必须和请求里的 `model` 一致，否则 404。
- baseline **不要**开 `--enable-per-request-metrics`；只有诊断跑开。
- 等 `Application startup complete`，记录加载耗时、KV cache、最大并发：

```bash
grep -E "Loading model|GPU KV cache size|Maximum concurrency|Application startup" /workspace/vllm.log
```

### 6. Smoke test

```bash
curl -s http://127.0.0.1:8000/v1/models | python3 -m json.tool | head -20

curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-8b","messages":[{"role":"user","content":"hello /no_think"}],"max_tokens":32,"temperature":0}' \
  | python3 -m json.tool
```

压测走 `/v1/completions`；chat 端点只用来确认端到端可用。

### 7. Warmup

10 条、并发 1，结果丢弃。预热 lazy init、GPU 频率、功耗墙触发点、HTTP 连接；不是填 KV cache。

### 8. Baseline

并发 `c=1/4/16/64`，总请求 `n=100/200/500/1000`。核心 flag：

```bash
vllm bench serve \
  --backend openai --endpoint /v1/completions \
  --host 127.0.0.1 --port 8000 \
  --model qwen3-8b \
  --tokenizer Qwen/Qwen3-8B-AWQ \
  --dataset-name random \
  --random-input-len 1024 --random-output-len 256 \
  --num-prompts "$N" --max-concurrency "$C" \
  --ignore-eos --seed "$C" \
  --percentile-metrics ttft,tpot,itl,e2el \
  --metric-percentiles 50,95,99 \
  --goodput ttft:2000 tpot:100 \
  --save-result --save-detailed \
  --result-dir ./results \
  --result-filename "d1-c${C}-$(date +%Y%m%d-%H%M%S).json" \
  --metadata gpu=l4-24gb vllm="$VLLM_VERSION" concurrency="$C" n="$N"
```

必须知道的点：

- `--model` 是 API 里的 served name，`--tokenizer` 才是加载 tokenizer 的 repo；不写会报 `not a local folder`。
- `random` 数据集发的是**合成 token 序列**，不是自然语言；1024 输入、256 输出，长度可控，但分布不真实、默认无共享前缀。
- `--ignore-eos` 保证输出正好 256；否则提前 EOS，吞吐/TPOT 不可比。
- `--percentile-metrics` 选指标，`--metric-percentiles` 选百分位点，二者是笛卡尔积。
- v0.34 **不再默认 `temperature=0`**；跨次复现要显式加 `--temperature 0`。
- 每轮前 `reset_prefix_cache`，每轮换 seed；轮间 `sleep 30` 排空队列。

客户端指标只写两处：stdout 和 JSON。必须 `--save-result`；要 per-request 数组再加 `--save-detailed`。JSON 里**没有 `tpots` 数组**，TPOT 用 `latencies`/`ttfts`/`output_lens` 重算；`itls` 是所有 gap 展平后的列表。`--result-dir`/`--result-filename` 控制路径，`tee` 保留 stdout。

### 8.1 KV cache 与容量

Qwen3-8B：36 层、8 KV head、head_dim 128、FP16 KV：

```
每 token KV = 2 × 36 × 8 × 128 × 2B = 144 KiB
block 16 token = 2.25 MiB
91,648 tokens = 5,728 blocks ≈ 12.6 GiB
11.19x = 91,648 / 8,192（假设每条吃满 8k）
```

我们实际 1024+256：

```
1,280 tokens = 80 blocks
91,648 / 1,280 = 71.6  → KV 上限约 71
但 --max-num-seqs 64 先生效 → 实际 64
64 × 1,280 = 81,920 < 91,648 → c=64 抢占为 0
```

**SLO 容量看 goodput，不看 KV 上限。** 这台 40W L4（SLO：TTFT≤2s、TPOT≤100ms）：c=1 100%、c=4 25%、c=16 0.2%、c=64 0%，所以 SLO 安全吞吐约 **0.077 req/s**，不是 71 路并发。

### 9. 诊断跑

只在需要拆“排队 vs prefill”时做：

1. 停服务；
2. 同样参数重启，多一个 `--enable-per-request-metrics`；
3. c=16、200 条，`--save-detailed`；
4. 读 JSON 里的 `server_queue_times` / `server_ttfts`（**秒**）。

它只加这两个 per-request 字段，不提供 GPU util/power；只有 `openai` / `vllm` / `openai-chat` backend 有，拿不到是 `null`；会增加服务端 CPU 开销，所以 baseline 不开，诊断数字不和 headline 混。

近似：`client_ttft ≈ server_queue_time + server_ttft + 前端/网络`。
`queue_times`（客户端）是等并发槽位的时间，和 `server_queue_times` 不是一回事。
`server_ttfts` 是从调度到首 token，包含 chunked prefill 的多步调度，不是纯 prefill 计算；decode 看 TPOT/ITL。字段不存在就写“无法拆分”，不要硬凑。

### 10. 重复跑

至少重复 c=16；时间够再重复 c=64。**必须先停诊断服务，用不带 per-request metrics 的 baseline 配置重启**。同 seed、同 n，文件名加 `-run2`，报两次的中位数/范围。

### 11. 收尾

- [ ] 停 GPU 采样（`kill $(cat /workspace/gpu_smi.pid)`；run2 用 `gpu_smi_run2.pid`）
- [ ] 4 个 baseline JSON + 诊断 JSON + run2 JSON
- [ ] `gpu_util.csv`（必要时 `gpu_util_run2.csv`）
- [ ] 加载耗时 / KV cache / 最大并发
- [ ] README 表：c、n、TTFT P50/P95/P99、服务端排队 P99、TPOT P95、output tok/s、goodput、GPU util mean/P95、抢占 Δ
- [ ] 一句话归因（排队 vs prefill vs decode）
- [ ] 成本：GPU 小时 × 实际 $/h + 存储
- [ ] `scp` 回本地（结果、CSV、日志）
- [ ] 在**本地仓库** commit + push（不要在容器里 commit）
- [ ] Stop（24h 内继续）或 Destroy（隔几天），README 注明理由

归因模板：

> 并发 1→16 时 output throughput 从 __ 升到 __ tok/s，但 TTFT P99 从 __ 升到 __ ms、TPOT P95 从 __ 升到 __ ms；诊断显示排队 __ ms、prefill __ ms；KV 抢占为 __；瓶颈是 ______。

## 常见坑

| 症状 | 原因 | 处置 |
|---|---|---|
| UI 只有 4090/5090 | L4 是数据中心卡，不在 RTX；默认 `verified=true` | CLI 加 `-n`，`gpu_name=L4` |
| `ssh://...: No such file` | URI 直接粘进 shell | `ssh -i <key> -p <port> root@<host>` |
| `Permission denied (publickey)` | 本机 key 和实例 key 不配对 | `vastai attach ssh <id> "$(cat ...pub)"`；显式 `-i` |
| 连不上 | 实例 `stopped` | `vastai start instance <id>` |
| 新 SSH 被同一个日志占住 | Vast 自动 tmux attach | `Ctrl-b c` 开新窗口；`Ctrl-b d` 脱离 |
| `python: command not found` | 镜像只有 `python3` | 全部用 `python3` |
| `df: /workspace 不存在` | 镜像没预建 | `mkdir -p /workspace`；`df -h /` |
| `--help \| grep` 为空 | v0.34 的 help 分组 | `--help=all` |
| `CUDA driver version is insufficient` | host Max CUDA < 镜像 CUDA | 换 host 或换低 CUDA 镜像；不要装 driver |
| `no kernel image is available` | GPU arch 不在镜像编译列表 | 换镜像/换卡；和 CUDA 版本无关 |
| `du -sh` 只有 4.4M | Xet 用符号链接 | `du -shL`；`df -h /` 看真实占用 |
| `qwen3-8b is not a local folder` | bench 拿 `--model` 找 tokenizer | 加 `--tokenizer Qwen/Qwen3-8B-AWQ` |
| 抢占 > 0 | KV cache 不足 | 降并发/上下文，或升 `gpu-memory-utilization` |
| goodput 当百分比 | 它是 **req/s** | 比例 = `goodput / request_throughput` |
| `server_queue_times` 当 ms | JSON 里是**秒** | P99 算完 ×1000 再和客户端 TTFT 比 |
| P99 相加 | 百分位不可加 | 先把同一请求的 queue+prefill 相加，再算 P99 |
| 把 KV 上限 71 当容量 | KV 上限 ≠ SLO 容量 | 看 goodput 曲线；这台 40W L4 约 0.077 req/s |
| 吞吐远低于公开数字 | host power limit 40W、邻居噪声 | 记录 `power.limit`；换 72W host 重跑 baseline |
| 两个代码块粘在一起 | 缺换行，`export` 变成 `mkdir` 参数 | 一次只粘一个代码块 |

## 下一步学习路径

- **D2 参数**：`max-num-seqs`、chunked prefill、prefix caching、AWQ vs FP16 + 质量门。一次一个变量，同 host，先 c=16 找拐点；执行细节见 `d2-vllm-tuning-runbook.md`。参数网格可以用 `vllm bench sweep serve` 编排（run 之间会清 server cache）。D2 比的是 **goodput 曲线**，不是“最大并发”。
- **D3 K8s**：k3s + Deployment；initContainer 现下 vs node-local 缓存测冷启动；KEDA 按 `num_requests_waiting` 扩缩。
- **D4 路由**：2×L4，llm-d EPP prefix-cache 路由 vs round-robin，共享长前缀看 P99 和命中率。
- **D5 策略**：Kueue 配额 + Kyverno 校验，留下被拒 manifest 日志。

所有对比都遵守：同机器、同 power limit、同长度、同 SLO、至少两次、报中位数/范围。
