# D1 Runbook：vLLM Baseline（单卡 L4，4 小时）

> 目标：在一张 24GB 卡上，把 8B 量化模型跑起来，产出 **4 个并发点** 的基线数字，存成可复现的 JSON。
> 验收：`results/` 里有 4 个 json，README 里有 1 张表，你能用一句话解释"并发从 1 到 64 时 TTFT 为什么这样变"。

---

## 0. 时间盒（总 4h）

| 阶段 | 时长 | 产出 |
|---|---|---|
| 开机 + 环境确认 | 30 min | 能 `nvidia-smi`，能 curl 通 |
| 起服务 + smoke test | 60 min | `/v1/models` 200，一次对话成功 |
| 压测 4 轮 | 90 min | 4 个 JSON + GPU 利用率曲线 |
| 记录 + 归档 | 30 min | README 表格 + git commit |
| 复盘 + 关机 | 30 min | 一句话结论 + 花费结算 |

---

## 1. 前置检查（5 分钟）

- [ ] RunPod / Vast 账号已充值（建议 **$15 上限**）
- [ ] 本地有 `git` 和 `curl`
- [ ] 建好空 repo：`llm-inference-platform-lab`
- [ ] README 先写死这句话："我要测：TTFT P50/P95/P99、output tok/s、GPU util、$/1M tokens"

---

## 2. 开机（RunPod，L4 Community）

1. Deploy → GPU → **NVIDIA L4 24GB** → Community Cloud（约 $0.44/h）
2. Template 选 **RunPod PyTorch** 或 **vLLM**（有 vLLM 模板就直接用，省 40 分钟）
3. **Container Disk 40GB**，Volume 40GB（挂到 `/workspace`，模型放这里，Stop 后不丢）
4. Expose HTTP Ports：**8000**
5. Deploy，等 1–2 分钟

连上后先确认三件事：

```bash
nvidia-smi                              # 看到 L4, 24GB, driver/CUDA 版本
df -h /workspace                        # 卷挂上了
python -c "import vllm; print(vllm.__version__)"   # 没装就 pip install vllm
```

> 版本不匹配是这一步最常见的坑：driver 太旧会在加载模型时报 CUDA error。记下 `nvidia-smi` 右上角的 CUDA Version，vLLM 镜像要求 ≥ 12.x。

---

## 3. 起服务

### 3.1 设置缓存目录（模型只下一次）

```bash
export HF_HOME=/workspace/hf
export HF_HUB_ENABLE_HF_TRANSFER=1     # 大文件下载快 3-5 倍
pip install -q hf_transfer
```

### 3.2 启动 vLLM（前台，方便看日志）

```bash
vllm serve Qwen/Qwen3-8B-AWQ \
  --served-model-name qwen3-8b \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --max-num-seqs 64 \
  --enable-per-request-metrics \
  --port 8000
```

参数为什么这么设：

- `--max-model-len 8192`：基线先保守。调到 32k 会吃掉大量 KV cache，第一天不需要。
- `--gpu-memory-utilization 0.90`：0.90 是默认值，先别动；OOM 时再降（见第 6 节）。
- `--max-num-seqs 64`：同时最多 64 条序列在跑，这是 D2 要动的旋钮之一。

启动日志里**必须**记下两行：模型加载耗时、`GPU KV cache size` / `Maximum concurrency for ... tokens per request`。这两个数字后面写 writeup 时要用。

### 3.3 Smoke test

```bash
curl -s localhost:8000/v1/models | head -c 400

curl -s localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-8b","messages":[{"role":"user","content":"用一句话解释 KV cache"}],"max_tokens":64}' \
  | python3 -m json.tool | head -30
```

两条都通，才能进压测。

---

## 4. 压测（D1 的核心，90 分钟）

### 4.1 先记录空闲显存

```bash
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
```

### 4.2 开始采样 GPU 利用率（另开一个终端）

```bash
nvidia-smi --query-gpu=timestamp,utilization.gpu,memory.used,power.draw \
  --format=csv -l 2 > /workspace/gpu_util.csv &
```

### 4.3 四轮压测（固定输入 1024 token / 输出 256 token）

```bash
mkdir -p results

for C in 1 4 16 64; do
  vllm bench serve \
    --backend openai \
    --port 8000 \
    --model qwen3-8b \
    --dataset-name random \
    --random-input-len 1024 \
    --random-output-len 256 \
    --num-prompts 200 \
    --max-concurrency $C \
    --save-result --save-detailed \
    --result-dir ./results
  echo "done concurrency=$C"
done
```

说明：

- `--num-prompts 200`：每轮 200 个请求，统计才有意义；样本太少 P99 会飘。
- `--max-concurrency`：闭环压测，固定并发数，这是最有解释力的口径。
- `--save-result --save-detailed`：结果落 JSON，别只截屏。
- 服务端加了 `--enable-per-request-metrics`，detailed 结果里会多出 **`server_queue_times`**（调度排队时间）和 **`server_ttfts`**（真正生成首 token 的时间）。**这两个字段是你归因的证据**：P99 变差到底是"排队"还是"算得慢"，一眼能分。
- 如果某个 flag 报错，先 `vllm bench serve --help` 对一遍——vLLM 的小版本会改参数名。

### 4.4 每轮之间做的事

- 等 30 秒让队列排空
- 记一行到表格（见下）
- 检查服务日志里有没有 `preempted`（KV cache 不足会抢占请求并重算，这会污染结果）

```bash
grep -c "PreemptionMode" /workspace/vllm.log 2>/dev/null || echo "no log file, check terminal scrollback"
```

---

## 5. 记录表（直接复制进 README）

| 并发 | TTFT P50 | TTFT P95 | TTFT P99 | 服务端排队 P99 | TPOT | output tok/s | req/s | GPU util % | 抢占次数 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | | |
| 4 | | | | | | | | | |
| 16 | | | | | | | | | |
| 64 | | | | | | | | | |

`vllm bench serve` 结束时会打印这些指标，直接从输出或 JSON 里抄。

**必须写的一句话结论**（D1 的交付物，不是可选项）：

> 并发 1 → 16 时吞吐从 __ 涨到 __ tok/s，TTFT 基本持平；到 64 时 TTFT P99 从 __ 跳到 __，其中服务端排队占 __ ms、生成占 __ ms，所以瓶颈是 ______（KV cache 被占满导致排队 / batch 太大挤压 / 其他）。

---

## 6. 故障排查（按出现频率排序）

| 症状 | 原因 | 处置 |
|---|---|---|
| `torch.OutOfMemoryError` / 启动就 OOM | `gpu-memory-utilization` 太高，或 `max-model-len` 太大 | 降到 0.85 → 0.80；`--max-model-len 4096` |
| `CUDA error: no kernel image is available` | 镜像/vLLM 的 CUDA 与 driver 不匹配 | 换匹配的镜像 tag；先 `nvidia-smi` 看 driver 支持的 CUDA |
| `Connection refused` | 服务还在加载模型（8B AWQ 约 30–90 秒） | 看前台日志等到 `Uvicorn running` |
| `404 model not found` | `--served-model-name` 和请求里的 `model` 不一致 | 统一用 `qwen3-8b` |
| 压测 P99 抖动巨大 | 有其他进程占卡 / 抢占 / 网络 | `nvidia-smi` 看有没有别的进程；检查 `preempted` 计数 |
| 下载模型极慢 | 没开 hf_transfer / 机房带宽差 | 见 3.1；或换 Secure Cloud |
| `ValueError: ... max_num_seqs` | 小版本参数名变化 | `vllm serve --help \| grep -i seq` |

---

## 7. 收工（30 分钟）

```bash
# 1. 停采样
kill %1 2>/dev/null

# 2. 归档
cp -r results /workspace/
git add -A && git commit -m "D1: vLLM baseline on L4 (concurrency 1/4/16/64)"
git push

# 3. 记花费
# 打开账单页，把「小时数 × 单价」写进 README 的 Cost 一节
```

**RunPod 上按 Stop，不要 Terminate** —— 卷和已下载的权重都保留，第二天 D2 直接续。

---

## 8. 验收清单

- [ ] `results/` 里有 4 个结果文件（c=1/4/16/64）
- [ ] README 表格 4 行填满
- [ ] 有一句话归因结论
- [ ] `gpu_util.csv` 里能看到压测期间利用率的变化
- [ ] 记下了服务启动时的模型加载耗时和 KV cache 容量
- [ ] 花费已记录

---

## 9. 明天（D2）预告

D2 只做一件事：**在同一台机器上，改三个旋钮重新跑这四轮**，看哪个参数动了 P99、哪个动了吞吐。

三个旋钮：`--enable-prefix-caching`、`--max-num-seqs`（64 → 128/256）、量化格式（AWQ vs FP16，如果显存放得下）。

产出：一张"参数 → 吞吐/延迟"对照表。这张表就是 writeup 的第二节。

---

## 附：成本估算

L4 Community $0.44/h × 4h ≈ **$1.8/天**；一周 5 天实验 ≈ **$9**，加 D4 的 2 卡 1 小时 ≈ **$11**。总预算 $15 足够。
