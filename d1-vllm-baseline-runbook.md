# D1 Runbook：vLLM Baseline（单卡 L4，4 小时）

> 目标：在 **Vast.ai** 上租一张 24GB L4，把 8B 量化模型跑起来，产出 **4 个并发点** 的基线数字，存成可复现的 JSON。
> 验收：`results/` 里有 4 个 baseline JSON，README 里有 1 张表，你能用一句话解释“并发从 1 到 64 时 TTFT 为什么这样变”。
>
> 平台前提：Vast.ai **on-demand** 实例；容器盘 ≥ 40GB；镜像 `vllm/vllm-openai`；压测在实例内跑（127.0.0.1），避免公网 RTT 污染数字。
>
> **今天只做 D1。** 不做 D2 调参、不做 llm-d、不做 Kueue/Kyverno。D1 的价值是“可信的 baseline + 方法学”，不是“把所有工具都跑一遍”。

---

## 0. 时间盒（总 4h）

| 阶段 | 时长 | 产出 |
|---|---|---|
| 开机 + 环境确认 | 30 min | `nvidia-smi` 正常，vLLM/bench CLI 可用 |
| 下载模型 + 起服务 | 45 min | `/v1/models` 200，记录加载耗时/KV cache |
| Smoke test + warmup | 15 min | 一次 chat 成功，GPU 采样已开 |
| 压测 4 轮 | 75 min | 4 个 baseline JSON |
| 诊断跑（可选） | 15 min | 1 个带 `server_queue_times` 的 JSON |
| 记录 + 归档 + 关机 | 40 min | README 表格 + 一句话结论 + git commit + 结果拉回本地 + Stop/Destroy |

**如果时间不够，按这个顺序砍：** 诊断跑 → c=64 样本数 1000 降到 500 → c=1 样本数 100 降到 50。**不要砍掉 4 个并发点、commit、结果拉回本地。**

---

## 1. 前置检查（10 分钟）

- [ ] Vast.ai 账号已充值；预算上限 **$15**（Vast 是预付费，余额见底会自动停实例）
- [ ] GPU：**NVIDIA L4 24GB**，租 **on-demand**，不要 interruptible
- [ ] Container Disk **≥ 40GB**（创建后不能扩容）；Volume 不是必需
- [ ] Ports 填 `-p 8000:8000`（只在实例内压测可不填）
- [ ] 本地有 `git`、`curl`、`scp`；SSH public key 已加到 Vast 账号，能 SSH 进容器

Vast 是 marketplace，host 质量差异很大。挑 offer 的硬条件：

| 条件 | 门槛 | 为什么 |
|---|---|---|
| 租用类型 | **On-demand** | interruptible 会被暂停/抢占，压测数字直接作废 |
| Reliability | ≥ 98%，最好 ≥ 99% | 低信誉 host 会掉线、丢盘 |
| Max CUDA | ≥ 12.1 | 低于这个 vLLM 镜像跑不起来 |
| Inet down | ≥ 500 Mbps | 要下约 5GB 权重；太慢会拖掉半小时 |
| Max Duration | > 6h | 别租 1 小时就到期的 offer |
| 价格 | 记录实际 $/h | 同一张 L4 从 $0.10 到 $0.45 都有，不要按固定价算成本 |

镜像用 `vllm/vllm-openai:<tag>`（tag 与要跑的 vLLM 版本一致）。在 Vast 上把启动方式设为 **SSH / Jupyter**，或把 entrypoint 覆盖成 `/bin/bash`——这个镜像默认 entrypoint 会直接尝试起 server，没参数就退出，容器会反复重启。

进容器后先跑：

```bash
nvidia-smi
df -h /workspace
python -c "import vllm; print(vllm.__version__)"
vllm bench serve --help >/dev/null && echo "bench CLI ok"
```

检查今天要用的 flag 是否存在（版本不对就换镜像，不要盲目 `pip install -U vllm`）：

```bash
vllm serve --help | grep -E "enable-per-request-metrics|no-enable-prefix-caching"
vllm bench serve --help | grep -E "ignore-eos|metric-percentiles|percentile-metrics|save-detailed|goodput"
```

设置环境变量：

```bash
export HF_HOME=/workspace/hf
export HF_HUB_ENABLE_HF_TRANSFER=1
export VLLM_VERSION=$(python -c "import vllm; print(vllm.__version__)")
mkdir -p /workspace/hf /workspace/results
```

> 版本不匹配是这一步最常见的坑：driver 太旧会在加载模型时报 CUDA error。记下 `nvidia-smi` 右上角的 CUDA Version；vLLM 镜像要求 ≥ 12.x。Vast 的 offer 卡上会写 `Max CUDA`，租之前就核对，别等进容器才发现。

---

## 2. 下载模型（10–20 分钟，和起服务分开）

先把权重下完，避免把“下载慢”误判成“服务起不来”：

```bash
pip install -q hf_transfer
python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen3-8B-AWQ")
PY
du -sh "$HF_HOME/hub/models--Qwen--Qwen3-8B-AWQ"
```

模型约 4.8GB。若提示 gated/401，先 `huggingface-cli login`；Qwen3-8B-AWQ 通常是公开的。

Vast 的容器盘在 Stop 后保留、Destroy 时删除，所以**不需要额外 Volume**；Volume 只能挂回同一台物理机，换 host 就作废。权重放 `/workspace/hf` 即可，D2 换机器就重下（10–20 分钟）。

---

## 3. 起服务（10 分钟）

另开一个终端（Terminal A），前台起服务并落日志：

```bash
cd /workspace
vllm serve Qwen/Qwen3-8B-AWQ \
  --served-model-name qwen3-8b \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --max-num-seqs 64 \
  --disable-log-requests \
  --host 0.0.0.0 \
  --port 8000 \
  2>&1 | tee /workspace/vllm.log
```

参数为什么这么设：

- `--max-model-len 8192`：基线先保守。Qwen3 原生 32k，调到 32k 会吃掉大量 KV cache，D1 不需要。
- `--gpu-memory-utilization 0.90`：默认值；OOM 时再降（见第 9 节）。
- `--max-num-seqs 64`：同时最多 64 条序列；这是 D2 要动的旋钮之一。
- `--host 0.0.0.0`：Vast 通过端口映射把容器 8000 暴露出去；只绑 `127.0.0.1` 的话实例外访问不到。实例内压测仍用 `127.0.0.1`，不经过公网。
- **不要显式加 `--enable-prefix-caching`**：vLLM V1 默认已开启；D1 通过 `reset_prefix_cache` + 每轮不同 seed 避免跨轮污染。
- **不要加 `--enable-per-request-metrics`**：它会给 headline 数字增加 CPU 开销；只在第 6 节诊断跑时加。

等到日志出现 `Uvicorn running` / `Application startup complete`，然后记录三件事：

```bash
grep -E "Loading model|GPU KV cache size|Maximum concurrency|Application startup" /workspace/vllm.log
```

把 **模型加载耗时、GPU KV cache size、Maximum concurrency for 1024/256 tokens** 抄到第 7 节的表下面。面试写 writeup 时要用。

---

## 4. Smoke test（5 分钟）

两条都通，才能进压测：

```bash
curl -s http://127.0.0.1:8000/v1/models | python3 -m json.tool | head -30
```

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-8b",
    "messages": [{"role":"user","content":"用一句话解释 KV cache /no_think"}],
    "max_tokens": 64,
    "temperature": 0
  }' | python3 -m json.tool
```

说明：

- Qwen3 默认 thinking 模式；`/no_think` 是软开关，避免 64 个 token 全被 reasoning 吃掉。
- 如果 `/no_think` 没生效，改用 `"chat_template_kwargs": {"enable_thinking": false}`。
- 压测走 `/v1/completions`（random token IDs），不经过 chat template，所以 baseline 不受 thinking 模式影响；但 smoke test 必须走 chat 端点，确认端到端可用。

再确认 completions 端点：

```bash
curl -s http://127.0.0.1:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-8b","prompt":"hello","max_tokens":16}' \
  | python3 -m json.tool | head -20
```

---

## 5. 压测（75 分钟）

### 5.1 开 GPU 采样（Terminal B）

```bash
nvidia-smi --query-gpu=timestamp,utilization.gpu,memory.used,power.draw,temperature.gpu,clocks.sm \
  --format=csv -l 1 > /workspace/gpu_util.csv 2>&1 &
echo $! > /workspace/gpu_smi.pid
```

如果 `clocks.sm` 报错，删掉这一列重跑；至少保留 utilization/memory/power/temp。

### 5.2 Warmup（丢弃，不计入结果）

```bash
mkdir -p /workspace/results/warmup
vllm bench serve \
  --backend openai \
  --endpoint /v1/completions \
  --host 127.0.0.1 --port 8000 \
  --model qwen3-8b \
  --dataset-name random \
  --random-input-len 1024 \
  --random-output-len 256 \
  --num-prompts 10 \
  --max-concurrency 1 \
  --ignore-eos \
  --seed 999 \
  --save-result --result-dir /workspace/results/warmup
```

等 10 秒，让队列排空、GPU 频率稳定。

### 5.3 四轮基线（Terminal C）

`--num-prompts` 按并发调整：c=1/4 用较少样本省时间；c=16/64 需要更多样本，否则 P99 没有统计意义。

```bash
cd /workspace
mkdir -p results

for C in 1 4 16 64; do
  case $C in
    1)  N=100 ;;
    4)  N=200 ;;
    16) N=500 ;;
    64) N=1000 ;;
  esac

  echo "=== concurrency=$C n=$N ==="

  # 清 prefix cache（若端点不存在，忽略；每轮不同 seed 也会换 prompt）
  curl -s -X POST http://127.0.0.1:8000/reset_prefix_cache >/dev/null || true

  BEFORE=$(curl -s http://127.0.0.1:8000/metrics \
    | awk '/^vllm:num_preemptions_total/{s+=$NF} END{print s+0}')

  vllm bench serve \
    --backend openai \
    --endpoint /v1/completions \
    --host 127.0.0.1 --port 8000 \
    --model qwen3-8b \
    --dataset-name random \
    --random-input-len 1024 \
    --random-output-len 256 \
    --num-prompts "$N" \
    --max-concurrency "$C" \
    --ignore-eos \
    --seed "$C" \
    --percentile-metrics ttft,tpot,itl,e2el \
    --metric-percentiles 50,95,99 \
    --goodput ttft:2000 tpot:100 \
    --save-result --save-detailed \
    --result-dir ./results \
    --result-filename "d1-c${C}-$(date +%Y%m%d-%H%M%S).json" \
    --metadata gpu=l4-24gb vllm="$VLLM_VERSION" concurrency="$C" n="$N" input_len=1024 output_len=256 ignore_eos=true

  AFTER=$(curl -s http://127.0.0.1:8000/metrics \
    | awk '/^vllm:num_preemptions_total/{s+=$NF} END{print s+0}')

  echo "preemptions delta: $((AFTER-BEFORE))"
  sleep 30
done
```

关键 flag 说明：

- `--ignore-eos`：强制生成到 `--random-output-len`，否则模型提前 EOS，output tok/s 和 TPOT 不可比。
- `--metric-percentiles 50,95,99`：默认只报 P99；README 表要 P50/P95，必须显式加。
- `--percentile-metrics ttft,tpot,itl,e2el`：把 TPOT/ITL/E2EL 的百分位也输出。
- `--goodput ttft:2000 tpot:100`：暂定 SLO（TTFT ≤ 2s、TPOT ≤ 100ms）；如果 L4 上太严/太松，D2 再调，但 D1 要固定口径。若当前版本不认识 `--goodput`，删掉这一行，goodput 后面用 per-request 数据补算。
- `--seed "$C"`：每轮换 prompt，避免重复数据集命中 prefix cache。
- `--save-detailed`：保留 per-request 数组，后面写 writeup 可复算；文件会比较大，但 4 个点可接受。

每轮之间等 30 秒；不要连续压，否则队列没排空会污染下一轮。若 `vllm:num_preemptions_total` 取不到，用 `grep -c "PreemptionMode" /workspace/vllm.log` 记录增量。

### 5.4 如果还有时间：重复 c=16/64

单次跑不足以区分“参数效果”和“Vast host 抖动 / 邻居噪声”。时间允许就把 c=16/64 再跑一遍，`--result-filename` 加 `-run2`；README 里报两次的中位数/范围。**没时间就注明“single run，P99 仅指示性”。**

---

## 6. 诊断跑（15 分钟，可选但推荐）

`--enable-per-request-metrics` 会让服务端记录每个请求的 `server_queue_times` 和 `server_ttfts`，用来拆解“排队慢”还是“prefill 慢”。但它有 CPU 开销，**只用于诊断，不用于 headline**。

1. Terminal A `Ctrl-C` 停服务。
2. 用同样的命令重启，只多一个 flag：

```bash
vllm serve Qwen/Qwen3-8B-AWQ \
  --served-model-name qwen3-8b \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --max-num-seqs 64 \
  --disable-log-requests \
  --enable-per-request-metrics \
  --host 0.0.0.0 \
  --port 8000 \
  2>&1 | tee /workspace/vllm.log
```

3. 跑一次 c=16、200 prompts：

```bash
vllm bench serve \
  --backend openai \
  --endpoint /v1/completions \
  --host 127.0.0.1 --port 8000 \
  --model qwen3-8b \
  --dataset-name random \
  --random-input-len 1024 \
  --random-output-len 256 \
  --num-prompts 200 \
  --max-concurrency 16 \
  --ignore-eos \
  --seed 16 \
  --percentile-metrics ttft,tpot,itl,e2el \
  --metric-percentiles 50,95,99 \
  --save-result --save-detailed \
  --result-dir ./results \
  --result-filename "d1-diagnostic-c16-$(date +%Y%m%d-%H%M%S).json" \
  --metadata gpu=l4-24gb vllm="$VLLM_VERSION" diagnostic=per-request-metrics
```

4. 在 JSON 里找 `server_queue_times` / `server_ttfts`；P99 用 per-request 数组自己算，或看 bench 输出。

**口径必须说清：**

- `server_queue_times` = 服务端调度排队时间。
- `server_ttfts` = 调度到首 token 的时间（prefill），**不是 decode**。
- decode 看 TPOT/ITL。
- 如果当前 vLLM 版本没有这个 flag，跳过本节，在 writeup 里注明“无法拆分服务端排队”；不要伪造归因。

---

## 7. 记录表（复制进 README）

| 并发 | n | TTFT P50 | TTFT P95 | TTFT P99 | 服务端排队 P99 | TPOT P95 | output tok/s | goodput req/s | GPU util % | 抢占 Δ |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 100 | | | | | | | | | |
| 4 | 200 | | | | | | | | | |
| 16 | 500 | | | | | | | | | |
| 64 | 1000 | | | | | | | | | |

表下补充：

- 模型加载耗时：____ s
- GPU KV cache size：____
- Maximum concurrency for 1024/256 tokens：____
- GPU：L4 24GB，vLLM 版本：____
- 时间窗口：____ 到 ____；GPU 单价：$____/h（从 Vast 实例页抄实际价）；存储：$____/GB/小时；总花费：$____
- 样本/重复说明：____

GPU util 的取法：在 `gpu_util.csv` 里取每轮压测窗口的 `utilization.gpu`，排除 warmup 和 idle；报均值 + P95，不要只报一个峰值。

**“服务端排队 P99”只有第 6 节诊断跑才有；baseline 四个 JSON 没有这个字段。** 没做诊断就跑的话，这一列写 `n/a`，不要用 client TTFT 减去 server TTFT 硬凑（口径不对）。goodput 如果命令行不支持，就先用 `output tok/s` 和 TPOT P95 两个核心指标交差，D2 再补。

---

## 8. 一句话结论（模板）

> 并发 1→16 时，output throughput 从 __ 升到 __ tok/s，TTFT P95 基本持平；到 64 时 TTFT P99 从 __ 升到 __ ms，其中服务端排队 __ ms、prefill/首 token __ ms，decode TPOT P95 为 __ ms；因此瓶颈是 ______（KV cache 不足导致排队 / batch 太大挤压 / 网络 / 其他），goodput 从 __ 降到 __ req/s。

注意：不要写“生成占 __ ms”。`server_ttfts` 是 prefill/首 token，不是 decode；decode 用 TPOT/ITL。

---

## 9. 故障排查（按出现频率排序）

| 症状 | 原因 | 处置 |
|---|---|---|
| `torch.OutOfMemoryError` / 启动就 OOM | `gpu-memory-utilization` 太高，或 `max-model-len` 太大 | 降到 0.85 → 0.80；`--max-model-len 4096` |
| `CUDA error: no kernel image is available` | 镜像/vLLM 的 CUDA 与 driver 不匹配 | 换匹配的镜像 tag；先 `nvidia-smi` 看 driver 支持的 CUDA |
| `Connection refused` | 服务还在加载模型（8B AWQ 约 30–90 秒） | 看 Terminal A 日志等到 `Uvicorn running` |
| `404 model not found` | `--served-model-name` 和请求里的 `model` 不一致 | 统一用 `qwen3-8b` |
| smoke test 返回一堆 thinking | Qwen3 默认 `enable_thinking=True` | prompt 加 `/no_think`，或 `chat_template_kwargs: {"enable_thinking": false}` |
| `unrecognized arguments: --enable-per-request-metrics` | vLLM 版本较旧 | 跳过第 6 节；或换更新的 vLLM 镜像（不要盲目升级 CUDA 栈） |
| `unrecognized arguments: --ignore-eos` / `--metric-percentiles` | bench CLI 版本较旧 | `vllm bench serve --help` 对一遍；换镜像 |
| `reset_prefix_cache` 404 | 该版本没有这个端点 | 忽略；每轮不同 `--seed` 已能换 prompt；必要时重启服务 |
| P99 抖动巨大 | 有其他进程占卡 / 抢占 / Vast host 邻居噪声 | `nvidia-smi` 看进程；看 `vllm:num_preemptions_total`；重复跑 c=16/64；仍抖就换 host |
| 下载模型极慢 | 没开 hf_transfer / host 带宽差 | 见第 2 节；下次租 `inet down` ≥ 500 Mbps 的 host |
| `KeyError: 'qwen3'` | transformers 太旧 | 换新版 vLLM 镜像（内置新 transformers） |
| `quantization` / AWQ 相关报错 | 镜像不识别该量化格式 | 先试 `--quantization awq`；仍失败换新版 vLLM 镜像，不要临时改模型格式 |
| 实例一直 `scheduling` / 容器反复重启 | host 没 GPU 资源，或镜像 entrypoint 直接退出 | 等 2–3 分钟；不行就 destroy 换 host；把 entrypoint 覆盖成 `/bin/bash` |
| `nvidia-smi` 型号/显存和订单不符 | host 虚标或租错卡 | 立即 destroy，不要在这个实例上跑基线 |
| Stop 后重启一直 `scheduling` | 原 GPU 被其他用户租走 | 等或换 host；**Stop 前先把结果拉回本地** |
| 实例外访问 8000 失败 | 没映射端口 / 服务只绑 `127.0.0.1` | Ports 填 `-p 8000:8000`；serve 加 `--host 0.0.0.0`；用实例页给的映射端口 |
| interruptible 实例被 pause | 租错计费类型 | 类型不能转换；destroy 后重租 on-demand，被 pause 的那轮数据作废 |
| 磁盘满 | Vast 容器盘创建后不能扩容 | destroy 重建，disk 直接给 40GB+ |

---

## 10. 收工（40 分钟）

```bash
# 1. 停 GPU 采样
kill "$(cat /workspace/gpu_smi.pid)" 2>/dev/null || true

# 2. 确认结果
ls -lh /workspace/results/

# 3. 提交（没有 remote 就先本地 commit，不要卡在 push）
git add -A
git commit -m "D1: vLLM baseline on L4 (concurrency 1/4/16/64)"
git push
```

**结果必须拉回本地，不能只留在实例盘。** 在本地机器执行（SSH 端口和主机从 Vast 实例页抄）：

```bash
scp -P <ssh_port> -r root@<host>:/workspace/results ./results
scp -P <ssh_port> root@<host>:/workspace/gpu_util.csv ./gpu_util.csv
scp -P <ssh_port> root@<host>:/workspace/vllm.log ./vllm.log
```

**Vast 的 Stop 和 RunPod 不是一回事：**

- **Stop**：GPU 计费停止，但**容器盘继续按 GB 计存储费**，数据保留。重启要排队等同一台机器的 GPU 空出来，不保证马上能起。
- **Destroy**：容器盘和数据一起删除，存储费停止。
- **D1 结束怎么选**：D2 在 24 小时内 → Stop；隔几天 → Destroy（40GB 挂几天的存储费可能比重新下模型还贵）。不管选哪个，先 scp + push。
- 不要租 interruptible 跑基线；被 pause 的那一轮直接作废。

花费按 Vast 实例页 **Charges** 记：`GPU 小时 × 实际 $/h + 存储 GB × 小时单价`。不要沿用旧文档里的 $0.44。

---

## 11. 验收清单

- [ ] `results/` 里有 4 个 baseline JSON（c=1/4/16/64），文件名含并发数和时间
- [ ] 诊断 JSON（可选，但推荐）；没有则注明“无法拆分服务端排队”
- [ ] README 表格 4 行填满，含样本数、P50/P95/P99、TPOT P95、output tok/s、goodput、GPU util、抢占 Δ
- [ ] 一句话归因结论（排队 vs prefill vs decode 分清）
- [ ] `gpu_util.csv` 覆盖 warmup 之后的四轮压测
- [ ] 记下模型加载耗时、KV cache size、maximum concurrency
- [ ] 花费已记录（GPU 和存储分开）
- [ ] git commit 完成
- [ ] `results/`、`gpu_util.csv`、`vllm.log` 已 scp 回本地
- [ ] 实例已 Stop 或 Destroy，并在 README 注明选择理由

---

## 附：成本估算

Vast 是 marketplace 定价：L4 on-demand 大约 **$0.10–0.45/h**，常见 $0.25–0.35/h；存储按 GB/小时、带宽按 TB 单独计费，host 之间差异很大。

按 $0.35/h × 4h ≈ **$1.4/天**；加诊断/重复跑约 **$2**。$15 预算够 D1–D2，但**别让实例 Stop 着放一个月**——40GB 存储挂一个月的费用可能超过重新下模型。

## 参考

- vLLM Benchmark CLI：<https://docs.vllm.ai/en/latest/benchmarking/cli/>
- vLLM serve CLI：<https://docs.vllm.ai/en/latest/cli/serve/>
- Qwen3-8B-AWQ 模型卡：<https://huggingface.co/Qwen/Qwen3-8B-AWQ>
- Vast.ai 计费：<https://docs.vast.ai/guides/instances/pricing>
- Vast.ai 存储类型：<https://docs.vast.ai/guides/instances/storage/types>
- Vast.ai 实例类型（on-demand vs interruptible）：<https://docs.vast.ai/guides/instances/choosing/instance-types>
