# D2 Runbook：vLLM 参数对比（单卡 L4，3 小时）

> 目标：在同一台 L4 上，一次只动一个变量，量化 4 个旋钮对吞吐/延迟/质量的影响：
> `max-num-seqs`、chunked prefill、prefix caching、AWQ vs FP16。
>
> 前置：D1 已完成（4 个 baseline JSON + README 表）。D2 不是“调到最快”，而是“说清楚每个旋钮换了什么”。
>
> 纪律：**同 host、同 power limit、同输入/输出长度、同 SLO、一次一个变量**。换机器就重跑控制组，不能拿 40W 和 72W 的数字比。

---

## 0. 时间盒（总 3h）

| 阶段 | 时长 | 产出 |
|---|---|---|
| 前置检查 + 下载 FP16 | 20 min | `Qwen/Qwen3-8B` 可用；flag 核对完 |
| 控制组（c=16 / c=64） | 25 min | 当天的 AWQ baseline |
| `max-num-seqs` 16/32 | 25 min | 吞吐 vs TPOT 拐点 |
| chunked prefill off + `bt512` | 20 min | TTFT/TPOT/ITL 变化，步长假设 |
| prefix caching on/off | 20 min | 共享前缀下的 TTFT、命中率 |
| AWQ vs FP16 | 15 min | 吞吐/显存对比 |
| 质量门（GSM8K 50 条） | 30 min | exact match delta |
| 记录 + 收尾 | 25 min | 对照表 + 一句话结论 + commit |

**时间不够按这个顺序砍：** 质量门（先注明 deferred）→ `max-num-seqs=32` → `bt512` → c=64 控制组。**不要砍掉控制组和“一次一个变量”。**

---

## 1. 前置检查

- [ ] D1 的 4 个 JSON 和 README 表还在；知道 D1 的 c=16/c=64 数字
- [ ] 确认今天用的是哪台：同 host 就重跑控制组；**新 host 也必须重跑控制组**，D1 数字只作参考
- [ ] `nvidia-smi` 的 `power.limit` 已记录（D1 是 40W；本台若不同，报告里必须写明“D1/D2 不可直接比”）
- [ ] `vllm --version` 是 `0.34.0`；不是就先核对 `--disable-*` / bench flag，再决定是否继续
- [ ] 容器盘 ≥ 40GB：AWQ 5.7GB + FP16 16.4GB + 结果，约 23GB（新实例缓存为空，两个都要下）
- [ ] 有 HF token（FP16 约 16GB，匿名下载可能 80 分钟）
- [ ] `vllm serve --help=all` 能查到 `--disable-chunked-prefill` / `--disable-prefix-caching`

```bash
# 目的：记录这张卡的规格和功耗上限；和 D1 不同时，D1 只能当参考，不能混在一张表里比
nvidia-smi --query-gpu=name,memory.total,driver_version,power.limit,power.draw --format=csv,noheader

# 目的：确认盘够放 FP16
df -h /

# 目的：确认两个负向 flag 的名字；v0.34 用 EnableDisableAction，help 显示 --enable-x / --disable-x
vllm serve --help=all 2>&1 | grep -E "disable-(chunked-prefill|prefix-caching)"
```

> v0.34 默认：chunked prefill = on，prefix caching = on，`max_num_seqs` = **128**（不是 64）。
> 关闭用 `--disable-chunked-prefill` / `--disable-prefix-caching`（v0.34 的 `EnableDisableAction` 在 help 里只显示 `--enable-x` / `--disable-x`；`--no-enable-x` 是隐藏的兼容别名，也能用，但不要写进文档）。D1 显式传了 `--max-num-seqs 64`，所以 D2 的控制组也必须显式传 64，否则控制组不是同一配置。

---

## 2. 实验矩阵

所有 bench 固定：`random` 数据集、输入 1024、输出 256、`--ignore-eos`、`--temperature 0`、P50/P95/P99/99.9。

| # | tag | 服务端配置 | bench | 目的 |
|---|---|---|---|---|
| 0 | `control-c16` | AWQ，`--max-num-seqs 64`，chunked on，prefix on | c=16, n=200 | 当天延迟基准 |
| 1 | `control-c64` | 同上 | c=64, n=300 | 当天吞吐基准 |
| 2 | `mns16` | `--max-num-seqs 16` | c=64, n=300 | 服务端并发上限的影响 |
| 3 | `mns32` | `--max-num-seqs 32`（可选） | c=64, n=300 | 找拐点 |
| 4 | `chunk-off` | `--disable-chunked-prefill` | c=16, n=200 | 整段 prefill 不再切块 |
| 4b | `bt512`（可选，优先于 mns32） | `--max-num-batched-tokens 512` | c=16, n=200 | 直接验证“大步 prefill 造成 decode 停顿” |
| 5 | `prefix-on` | 默认（prefix on） | c=16, n=200, prefix=512 | 共享前缀的缓存收益 |
| 6 | `prefix-off` | `--disable-prefix-caching` | c=16, n=200, prefix=512 | 无缓存对照 |
| 7 | `fp16` | `Qwen/Qwen3-8B` + `--dtype float16` | c=16, n=200 | 量化 vs 半精度 |

> 默认 `max_num_batched_tokens` 是 2048。D1 看到的 ~2.3s decode 停顿，量级正好等于“一个调度步塞进 2048 个 prefill token”的耗时；`bt512` 把一步的 prefill 预算压到 512，是比 `chunk-off` 更直接的假设检验。`chunk-off` 则是另一个极端（整段 1024 一次算完），两者一起看能分清“停顿来自步长”还是“来自 prefill 与 decode 交错”。

为什么 c=16/c=64：c=16 看延迟和 TPOT，c=64 看吞吐上限和排队。D2 的 n 比 D1 小，是为了在 3 小时内跑完多个配置；**同一张表内所有行必须用同样的 n**。

---

## 3. 准备

### 3.1 环境变量

```bash
# 目的：权重和结果都放容器盘；新 shell 也要有
export HF_HOME=/workspace/hf
export HF_XET_HIGH_PERFORMANCE=1
export HF_TOKEN=hf_xxx          # 可选；FP16 很大，强烈建议设置，不要提交进 git
export VLLM_VERSION=$(python3 -c "import vllm; print(vllm.__version__)")
# 目的：把功耗上限写进每条结果的 metadata；换 host 后这是判断可比性的第一依据
export POWER_LIMIT=$(nvidia-smi --query-gpu=power.limit --format=csv,noheader | tr -d ' W')
mkdir -p /workspace/results
```

### 3.2 下载模型（先下 AWQ，再下 FP16）

新实例的 HF cache 是空的，先下 AWQ；否则 `serve_awq` 会在启动时现场下载 5.7GB，看起来像卡住。

```bash
# 目的：控制组和大部分实验用 AWQ；约 5.7GB
python3 - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen3-8B-AWQ")
PY

# 目的：确认真实占用约 5.7GB（Xet 用符号链接，必须 -L）
du -shL "$HF_HOME/hub/models--Qwen--Qwen3-8B-AWQ"

# 目的：把 FP16 权重下到同一个 HF cache；约 16.4GB，可与控制组并行
python3 - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen3-8B")
PY

# 目的：确认真实占用约 16GB（Xet 用符号链接，必须 -L）
du -shL "$HF_HOME/hub/models--Qwen--Qwen3-8B"
```

如果 FP16 下载 2 分钟后速度仍然 < 5MB/s，ETA 会超过 30 分钟：先跳过 #7 和质量门，把其余实验做完；README 里注明“FP16/质量门 deferred”。AWQ 是控制组必需，不能跳过。

### 3.3 安装质量门工具（可与下载并行）

```bash
# 目的：GSM8K 50 条的质量门；只装客户端，不占 GPU
pip install -q lm-eval
lm_eval --help >/dev/null && echo "lm-eval ok"
```

### 3.4 公共函数（每个新 shell 粘一次）

```bash
# 目的：统一启动 AWQ 服务；额外参数由调用方传，比如 --max-num-seqs 16
# 注意：v0.34 的 max_num_seqs 默认是 128；控制组必须显式传 --max-num-seqs 64 才能和 D1 对齐
serve_awq() {
  local TAG="$1"; shift
  cd /workspace
  vllm serve Qwen/Qwen3-8B-AWQ \
    --served-model-name qwen3-8b \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.90 \
    "$@" \
    --disable-log-requests \
    --host 0.0.0.0 --port 8000 \
    2>&1 | tee "/workspace/d2-${TAG}.log"
}

# 目的：统一启动 FP16 服务；OOM 时把 max-model-len 降到 4096
serve_fp16() {
  local TAG="$1"; shift
  cd /workspace
  vllm serve Qwen/Qwen3-8B \
    --served-model-name qwen3-8b \
    --dtype float16 \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.90 \
    "$@" \
    --disable-log-requests \
    --host 0.0.0.0 --port 8000 \
    2>&1 | tee "/workspace/d2-${TAG}.log"
}

# 目的：统一 bench；PREFIX=0 表示不构造共享前缀
d2_bench() {
  local TAG="$1" C="$2" N="$3" PREFIX="${4:-0}"
  local IN=$((1024 - PREFIX))
  cd /workspace
  # 目的：清 prefix cache，避免同一服务上上一轮的 prompt 命中缓存；刚起的服务上是 no-op
  curl -s -X POST http://127.0.0.1:8000/reset_prefix_cache >/dev/null || true
  vllm bench serve \
    --backend openai --endpoint /v1/completions \
    --host 127.0.0.1 --port 8000 \
    --model qwen3-8b \
    --tokenizer Qwen/Qwen3-8B \
    --dataset-name random \
    --random-input-len "$IN" \
    --random-prefix-len "$PREFIX" \
    --random-output-len 256 \
    --num-prompts "$N" --max-concurrency "$C" \
    --ignore-eos --seed 16 --temperature 0 \
    --percentile-metrics ttft,tpot,itl,e2el \
    --metric-percentiles 50,95,99,99.9 \
    --goodput ttft:2000 tpot:100 \
    --save-result --save-detailed \
    --result-dir ./results \
    --result-filename "d2-${TAG}-c${C}-n${N}-$(date +%Y%m%d-%H%M%S).json" \
    --metadata gpu=l4-24gb vllm="$VLLM_VERSION" tag="$TAG" concurrency="$C" n="$N" \
      prefix_len="$PREFIX" input_len=1024 output_len=256 temperature=0 \
      power_limit="$POWER_LIMIT"
}

# 目的：读抢占计数，bench 前后各一次，相减就是本轮增量
preempts() {
  curl -s http://127.0.0.1:8000/metrics \
    | awk '/^vllm:num_preemptions_total/{s+=$NF} END{print s+0}'
}
```

> `--random-prefix-len` 会在 `--random-input-len` 之外**再前置**一段共享前缀，所以函数里用 `IN = 1024 - PREFIX` 保证总输入仍是 1024。跑完看 JSON 的 `input_lens` 是否全为 1024，不是就调整。

---

## 4. 逐个实验

每个实验的固定动作：

1. Terminal A `Ctrl-C` 停旧服务；
2. 用对应命令启动，日志写 `d2-<tag>.log`；
3. 等 `Application startup complete`，`curl /v1/models` 确认；
4. 记录该配置的 KV cache / 最大并发；
5. Terminal C 跑 `d2_bench`；记录 bench 前后的 `preempts`；
6. 把结果记到 §6 的表。

### 4.1 控制组（当天 baseline）

```bash
# 目的：用当天、当台机器的控制配置；不要直接拿几小时前的 D1 数字当对照
# 必须显式 --max-num-seqs 64：v0.34 默认 128，不传就不是 D1 的配置
serve_awq control-c16 --max-num-seqs 64
```

等就绪后，另开窗口：

```bash
# 目的：记录控制组启动时的 KV cache 和最大并发
grep -E "GPU KV cache size|Maximum concurrency" /workspace/d2-control-c16.log | tail -2

# 目的：延迟基准
d2_bench control-c16 16 200 0
```

再跑 c=64 吞吐基准（同一个服务，不用重启）：

```bash
# 目的：吞吐基准；n 比 D1 小，控制总时长
d2_bench control-c64 64 300 0
```

### 4.2 `max-num-seqs` 16 / 32

```bash
# 目的：把服务端并发上限压到 16，观察 c=64 客户端负载下的排队和吞吐
serve_awq mns16 --max-num-seqs 16
```

就绪后：

```bash
d2_bench mns16 64 300 0
```

可选，时间够再做 32：

```bash
serve_awq mns32 --max-num-seqs 32
d2_bench mns32 64 300 0
```

预期：`max-num-seqs` 降低会减少每批序列数，TPOT 可能下降、TTFT 排队可能变化，但 output tok/s 通常下降；找“吞吐开始明显掉”的拐点。

### 4.3 chunked prefill off

```bash
# 目的：关闭 chunked prefill，对比默认（控制组 c=16）
serve_awq chunk-off --disable-chunked-prefill
```

就绪后：

```bash
d2_bench chunk-off 16 200 0
```

预期：关闭后每段 prefill 一次算完，不再按 2048-token 预算切块；TTFT P99 可能变大，但 ITL P99.9 / `>1s gaps` 可能变小。**这组主要看 ITL，不只看 TPOT**——TPOT 会把秒级停顿平均掉。

### 4.3b `max-num-batched-tokens` 512（可选，优先于 mns32）

```bash
# 目的：把每个调度步的 prefill 预算从默认 2048 压到 512，直接检验“步长造成 decode 停顿”
serve_awq bt512 --max-num-seqs 64 --max-num-batched-tokens 512
```

就绪后：

```bash
d2_bench bt512 16 200 0
```

预期：如果 D1 的 ~2.3s 停顿来自“一个 step 塞进约 2048 个 prefill token”，这组应看到 ITL P99.9 和 `>1s gaps/req` 明显下降，代价是 TTFT P99 上升（同样多的 prefill 要拆成更多步）。若 ITL 不变，假设被否定，停顿另有来源。

### 4.4 prefix caching on/off（共享前缀）

先跑“缓存开 + 共享前缀”：

```bash
# 目的：默认 prefix caching 已开；这批请求共享 512-token 前缀
serve_awq prefix-on
```

就绪后：

```bash
d2_bench prefix-on 16 200 512
```

再跑“缓存关 + 同样前缀”：

```bash
serve_awq prefix-off --disable-prefix-caching
d2_bench prefix-off 16 200 512
```

记录服务端日志的命中率：

```bash
# 目的：确认 prefix-on 真的命中；应该看到较高的 Prefix cache hit rate
grep "Prefix cache hit rate" /workspace/d2-prefix-on.log | tail -3
grep "Prefix cache hit rate" /workspace/d2-prefix-off.log | tail -3
```

预期：`prefix-on` 的 TTFT 明显低于 `prefix-off`；如果两者一样，先检查 `input_lens` 是否 1024、前缀是否真的相同。

### 4.5 AWQ vs FP16

```bash
# 目的：同一 served name，换 FP16 权重；先确认显存够，OOM 就降 max-model-len
serve_fp16 fp16
```

就绪后：

```bash
grep -E "GPU KV cache size|Maximum concurrency" /workspace/d2-fp16.log | tail -2
d2_bench fp16 16 200 0
```

FP16 的 KV cache 会比 AWQ 小（权重占 16.4GB），c=64 可能触发抢占；D2 只在 c=16 比，不强行跑 c=64。如果启动 OOM：

```bash
# 目的：FP16 权重太大时缩短上下文，先保证能跑；在 README 里注明
serve_fp16 fp16-4k --max-model-len 4096
d2_bench fp16-4k 16 200 0
```

---

## 5. 质量门（GSM8K 50 条）

只在 AWQ 和 FP16 两个服务都跑过性能后做；它衡量“量化掉了多少质量”，不是性能。

AWQ 服务还开着时：

```bash
# 目的：用当前 vLLM 服务做 50 条 GSM8K，5-shot，greedy；记录 exact_match
# max_gen_toks=1024 必须显式传：lm-eval 默认只生成 256 token，Qwen3 的 thinking CoT 会在中途被截断
# max_length=4096 防止 5-shot prompt（约 1.2k token）被 2048-1024 的默认上限截掉
lm_eval --model local-completions \
  --model_args base_url=http://127.0.0.1:8000/v1/completions,model=qwen3-8b,tokenizer=Qwen/Qwen3-8B-AWQ,num_concurrent=8,max_retries=3,max_gen_toks=1024,max_length=4096 \
  --tasks gsm8k --num_fewshot 5 --limit 50 --batch_size 8
```

换 FP16 服务后重复同一命令（tokenizer 可换 `Qwen/Qwen3-8B`）。记录 `exact_match,strict-match` 和 `exact_match,flexible-extract`。

> **先看是否被截断再看分数**：如果两边的 exact match 都接近 0，先检查 lm-eval 日志里的 `Some contexts exceeded` 和响应结尾——默认 256 token 下 Qwen3 还没写完 CoT 就被切断，这是测量假象，不是量化掉点。单配置超过 12 分钟就把两边都降到 `--limit 20`，**不要一个 50 一个 20**。

如果 `local-completions` 不兼容，退路：

```bash
# 目的：退路——让 lm-eval 自己起 vLLM 引擎；先停掉 8000 端口的服务，避免抢显存
lm_eval --model vllm \
  --model_args pretrained=Qwen/Qwen3-8B-AWQ,max_model_len=4096,gpu_memory_utilization=0.85,max_gen_toks=1024 \
  --tasks gsm8k --num_fewshot 5 --limit 50 --batch_size 8
```

> 50 条 GSM8K 只是指示性质量门，不是完整评测。AWQ 掉 1–2 个点以内通常可接受；掉超过 5 个点要在结论里明确写“质量不可接受”。

---

## 6. 结果表与归因

复制到 D2 报告或 README 的 D2 小节：

| # | tag | 配置 | c | n | output tok/s | TTFT P50 | TTFT P99 | TPOT P95 | ITL P99.9 | >1s gaps/req | goodput | 抢占 Δ | KV cache | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | control-c16 | AWQ mns=64 | 16 | 200 | | | | | | | | | | |
| 1 | control-c64 | AWQ mns=64 | 64 | 300 | | | | | | | | | | |
| 2 | mns16 | mns=16 | 64 | 300 | | | | | | | | | | |
| 3 | mns32 | mns=32 | 64 | 300 | | | | | | | | | | |
| 4 | chunk-off | chunked off | 16 | 200 | | | | | | | | | | |
| 4b | bt512 | batch-tokens=512 | 16 | 200 | | | | | | | | | | |
| 5 | prefix-on | prefix on | 16 | 200 | | | | | | | | | | 命中率 __% |
| 6 | prefix-off | prefix off | 16 | 200 | | | | | | | | | | 命中率 0% |
| 7 | fp16 | FP16 | 16 | 200 | | | | | | | | | | |

`ITL P99.9` 也可以直接读 JSON 的 `p99.9_itl_ms`（bench 已加 `99.9`；**key 里是小数点，不是下划线**）；`>1s gaps/req` 要自己从 `itls` 数：

```python
# 目的：补 ITL 尾部与每条请求的秒级停顿次数；这是验证“步长假设”的直接证据
import glob, json, numpy as np

for f in sorted(glob.glob("results/d2-*.json")):
    d = json.load(open(f))
    flat = np.array([x for r in d["itls"] for x in r]) * 1000
    gaps = [sum(1 for x in r if x > 1.0) for r in d["itls"]]
    print(f.split("/")[-1],
          "ITL p50/p99/p99.9 = %.1f/%.1f/%.1f ms" % tuple(np.percentile(flat, [50, 99, 99.9])),
          "| >1s gaps/req median = %d" % int(np.median(gaps)),
          "| output = %.1f tok/s" % d["output_throughput"])
```

一句话结论模板：

> 在 40W L4 上，`max-num-seqs` 从 64 降到 16 使 output tok/s 变化 __%、TPOT P95 变化 __%；`max-num-batched-tokens` 从 2048 降到 512 使 ITL P99.9 从 __ 变为 __、TTFT P99 从 __ 变为 __；关闭 chunked prefill 使 ITL P99.9 __、TTFT P99 __；共享 512-token 前缀时 prefix caching 使 TTFT P99 从 __ 降到 __（命中率 __%）；AWQ 相对 FP16 吞吐 __%、GSM8K exact match 变化 __ 个点。因此 D3/D4 应优先保留 ______ 配置。

每条结论必须带数字和方向（+x% / −y%），不要写“效果更好”。

---

## 7. 收尾

```bash
# 目的：停掉当前服务后，确认 D2 结果都在
ls -lh /workspace/results/d2-*.json
ls -lh /workspace/d2-*.log
```

- 把 `d2-*.json`、`d2-*.log` scp 回本地仓库；
- 在本地 `git add results d2-*.log d2-vllm-tuning-runbook.md README.md`，commit + push；
- 成本：D2 约 3h × 实际 $/h（这台 $0.2611）≈ $0.8；FP16 下载是 ingress，通常不计带宽费；**Stop 期间存储照计费**，把 `vastai show instance <id>` 里的 storage 费用一并记入 README（D1 只记了 GPU+存储的账单总额，D2 要分开写清）；
- Stop / Destroy 规则同 D1：24h 内做 D3 → Stop；隔几天 → Destroy。

---

## 8. 常见坑

| 症状 | 原因 | 处置 |
|---|---|---|
| 两次结果差很多 | host 噪声 / 功耗墙波动 | 同一配置重复 2 次；报中位数/范围；不要拿单次最好值 |
| FP16 启动 OOM | 16.4GB 权重 + 8k KV 放不下 | `--max-model-len 4096`；或只跑 c=1/4/16 |
| `--no-enable-*` 在 help 里搜不到 | v0.34 的 EnableDisableAction 只显示 `--enable-x` / `--disable-x`；`--no-enable-x` 是隐藏兼容别名 | 用 `--disable-*`；`grep -E "disable-(chunked-prefill\|prefix-caching)"` 对一遍 |
| `--max-num-seqs 64` 没生效 | v0.34 默认是 128 | 控制组命令里显式写；看启动日志 `non-default args` 的 `max_num_seqs` |
| prefix 实验没差异 | 前缀不是共享的，或总长度不是 1024 | 看 JSON `input_lens`；确认 `PREFIX=512` 且 `IN=512` |
| `max-num-seqs` 改了没变化 | 客户端 c 低于服务端上限 | 用 c=64 才看得出 16/32 的差别 |
| `local-completions` 报错 | lm-eval 与当前 API 不兼容 | 用 `--model vllm` 退路；先停 8000 服务 |
| 质量门跑太久 | 5-shot + thinking 模型 | 降到 `--limit 20` 或 `--num_fewshot 0`，并注明 |
| 和 D1 数字对不上 | 换了 host / power limit / n | 只和同一天的 control 比；D1 只作参考 |

---

## 9. 验收清单

- [ ] 同一天、同一台 L4 的 control（c=16 / c=64）
- [ ] `max-num-seqs` 16（可选 32）结果
- [ ] `max-num-batched-tokens 512` 结果（可选，但优先于 mns32）
- [ ] chunked prefill off 结果
- [ ] prefix caching on/off（共享 512-token 前缀）+ 命中率
- [ ] AWQ vs FP16 吞吐/显存对比（时间不够可 deferred，但要写明）
- [ ] GSM8K 50 条质量门（或明确 deferred；记录 max_gen_toks）
- [ ] ITL P50/P99/P99.9 + `>1s gaps/req`（不只 TPOT）
- [ ] 一张对照表 + 一句话结论（带数字和方向）
- [ ] 结果和日志 scp 回本地，commit + push
- [ ] 成本记录
- [ ] 实例 Stop 或 Destroy，并注明理由
