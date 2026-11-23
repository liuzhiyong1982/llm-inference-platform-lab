# D2 Runbook：vLLM 参数对比（单卡 L4，3 小时）

> 目标：在同一台 L4 上，一次只动一个变量，量化 4 个旋钮对吞吐/延迟/质量的影响：
> `max-num-seqs`、chunked prefill、prefix caching、AWQ vs FP16。
>
> 前置：D1 已完成（4 个 baseline JSON + README 表）。D2 不是“调到最快”，而是“说清楚每个旋钮换了什么”。
>
> 纪律：**同 host、同 power limit、同输入/输出长度、同 SLO、一次一个变量**。换机器就重跑控制组，不能拿 40W 和 72W 的数字比。
>
> 概念不清楚先读 **§10 概念与问答**：prefill/decode、`max-num-batched-tokens`、chunked prefill、prefix caching、AWQ W4A16。

---

## 0. 时间盒（总 3h）

| 阶段 | 时长 | 产出 |
|---|---|---|
| 前置检查 + 下载 FP16 | 20 min | `Qwen/Qwen3-8B` 可用；flag 核对完 |
| 控制组（c=16 / c=64） | 25 min | 当天的 AWQ baseline |
| `max-num-seqs` 16/32 | 20 min | 吞吐 vs TPOT 拐点 |
| chunked prefill off + `bt512` | 30 min | 同预算对照 + 步长假设 |
| prefix caching on/off | 20 min | 共享前缀下的 TTFT、命中率 |
| AWQ vs FP16 | 15 min | 吞吐/显存对比 |
| 质量门（GSM8K 50 条） | 25 min | exact match delta |
| 记录 + 收尾 | 25 min | 对照表 + 一句话结论 + commit |

**时间不够按这个顺序砍：** 质量门（先注明 deferred）→ `max-num-seqs=32` → `chunk-off` 对照对 → `bt512` → c=64 控制组。**不要砍掉控制组和“一次一个变量”。**

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
| 0b | `control-c8` | 同上 | c=8, n=100 | #7 的同并发对照 |
| 1 | `control-c64` | 同上 | c=64, n=300 | 当天吞吐基准 |
| 2 | `mns16` | `--max-num-seqs 16` | c=64, n=300 | 服务端并发上限的影响 |
| 3 | `mns32` | `--max-num-seqs 32`（可选） | c=64, n=300 | 找拐点 |
| 4a | `control-2k` | `--max-model-len 2048 --max-num-batched-tokens 2048` | c=16, n=200 | #4 的同预算对照 |
| 4 | `chunk-off` | 同上 + `--disable-chunked-prefill` | c=16, n=200 | 固定预算下关掉 prefill/decode 交错 |
| 4b | `bt512`（可选，优先于 mns32） | `--max-num-batched-tokens 512` | c=16, n=200 | 直接验证“大步 prefill 造成 decode 停顿” |
| 5 | `prefix-on` | 默认（prefix on） | c=16, n=200, prefix=512 | 共享前缀的缓存收益 |
| 6 | `prefix-off` | `--disable-prefix-caching` | c=16, n=200, prefix=512 | 无缓存对照 |
| 7 | `fp16-c8` | `Qwen/Qwen3-8B` + `--dtype float16` | c=8, n=100 | 量化 vs 半精度（主对比） |
| 7b | `fp16-c16`（可选） | 同上 | c=16, n=200 | KV 容量效应，不是纯量化对比 |

> 默认 `max_num_batched_tokens` 是 2048。D1 c=64 的 ITL P99 = 2,345ms，量级正好等于“一个调度步里 1024–2048 个 prefill token 和 decode 同批”的耗时；`bt512` 把一步的 prefill 预算压到 512，是比 `chunk-off` 更直接的假设检验。`chunk-off` 则是另一个极端（整段 1024 一次算完），两者一起看能分清“停顿来自步长”还是“来自 prefill 与 decode 交错”。

为什么 c=16/c=64：c=16 看延迟和 TPOT，c=64 看吞吐上限和排队。D2 的 n 比 D1 小，是为了在 3 小时内跑完多个配置；**同一个对比对内的 n 必须一致**（c=16 对用 n=200，c=64 用 n=300，AWQ/FP16 的 c=8 对用 n=100）。

---

## 3. 准备

### 3.1 环境变量

```bash
# 目的：权重和结果都放容器盘；新 shell 也要有
export HF_HOME=/workspace/hf
export HF_XET_HIGH_PERFORMANCE=1
# export HF_TOKEN=hf_xxx        # 可选；需要时取消注释并替换，不要提交进 git
export VLLM_VERSION=$(python3 -c "import vllm; print(vllm.__version__)")
# 目的：把功耗上限写进每条结果的 metadata；换 host 后这是判断可比性的第一依据
export POWER_LIMIT=$(nvidia-smi --query-gpu=power.limit --format=csv,noheader | tr -d ' W')
mkdir -p /workspace/results
```

> 这段 export 在 §3.4 的公共函数代码块里也完整包含一次；新 shell 直接粘 §3.4 即可，两处的 `HF_HOME` / `VLLM_VERSION` / `POWER_LIMIT` 必须一致。

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

> 为了让每个 flag 后面都能写注释，函数用 bash 数组收集参数；`"${args[@]}"` 会原样展开成多个参数，和逐行反斜杠写法等价。代码块里的 `#` 是逐行速查，3.4.2 / 3.4.3 的表补充“为什么 / 坑”。

```bash
# ---- 每个新 shell 先执行这一段 ----
export HF_HOME=/workspace/hf                                            # 模型缓存；所有 shell 必须一致
export HF_XET_HIGH_PERFORMANCE=1                                        # Xet 高吞吐下载
# export HF_TOKEN=hf_xxx                                                # 可选；需要时取消注释并替换
export VLLM_VERSION=$(python3 -c "import vllm; print(vllm.__version__)") # 写进 JSON metadata
export POWER_LIMIT=$(nvidia-smi --query-gpu=power.limit \
  --format=csv,noheader | tr -d ' W')                                   # 例如 40.00；换 host 要重记
mkdir -p /workspace/results                                             # d2_bench 的输出目录
# ------------------------------------

serve_awq() {
  local TAG="$1"; shift                                                 # $1=日志标签；shift 后 $@ 只剩额外参数
  cd /workspace                                                        # 日志和 results 相对这里
  local args=(
    --served-model-name qwen3-8b                                       # API 模型名；bench --model 必须匹配
    --max-model-len 8192                                               # 单请求 prompt+output 上限，不是每步预算
    --gpu-memory-utilization 0.90                                      # 权重+KV+激活可用的显存比例
    "$@"                                                               # 调用方追加；同名参数后者优先
    --disable-log-requests                                             # 关闭逐请求日志，降噪
    --host 0.0.0.0                                                     # Vast 端口映射需要；实例内压测走 127.0.0.1
    --port 8000                                                        # 和 bench 的 --port 一致
  )
  vllm serve Qwen/Qwen3-8B-AWQ "${args[@]}" 2>&1 | tee "/workspace/d2-${TAG}.log"  # 终端+日志
}

serve_fp16() {
  local TAG="$1"; shift                                                 # 同上
  cd /workspace
  local args=(
    --served-model-name qwen3-8b                                       # 和 AWQ 用同一个 API 名
    --dtype float16                                                    # 强制 FP16；和 AWQ 的 auto_awq 对齐
    --max-model-len 8192                                               # OOM 时改 4096，并在报告注明
    --gpu-memory-utilization 0.90                                      # 和 AWQ 控制组一致
    "$@"                                                               # 可追加 --max-model-len 4096 等
    --disable-log-requests                                             # 同上
    --host 0.0.0.0                                                     # 同上
    --port 8000                                                        # 同上
  )
  vllm serve Qwen/Qwen3-8B "${args[@]}" 2>&1 | tee "/workspace/d2-${TAG}.log"
}

d2_bench() {
  local TAG="$1" C="$2" N="$3" PREFIX="${4:-0}"                         # TAG=标签；C=客户端并发；N=总请求数；PREFIX=共享前缀
  local IN=$((1024 - PREFIX))                                          # 随机后缀；总输入 = IN + PREFIX = 1024
  cd /workspace
  curl -s -X POST http://127.0.0.1:8000/reset_prefix_cache >/dev/null || true  # 清 prefix cache，避免跨轮命中
  local args=(
    --backend openai                                                   # OpenAI 兼容 HTTP 客户端
    --endpoint /v1/completions                                         # 压测走 completions，不是 chat
    --host 127.0.0.1                                                   # 实例内环回，不走公网
    --port 8000                                                        # 和服务端一致
    --model qwen3-8b                                                   # 必须等于 --served-model-name
    --tokenizer Qwen/Qwen3-8B                                          # 编码/统计 token；AWQ/FP16 共用
    --dataset-name random                                              # 合成 token，长度可控
    --random-input-len "$IN"                                           # 随机后缀长度
    --random-prefix-len "$PREFIX"                                      # 共享前缀长度；0=不构造
    --random-output-len 256                                            # 每条固定输出 256 token
    --num-prompts "$N"                                                 # 这一轮总请求数（样本量），不是并发
    --max-concurrency "$C"                                             # 客户端同时在飞的上限
    --ignore-eos                                                       # 强制生成到 256，不被 EOS 截断
    --seed 16                                                          # prompt 采样固定；配 reset_prefix_cache
    --temperature 0                                                    # greedy；v0.34 不再默认 0
    --percentile-metrics ttft,tpot,itl,e2el                            # 这些指标算百分位
    --metric-percentiles 50,95,99,99.9                                 # 百分位点；ITL P99.9 看停顿
    --goodput ttft:2000 tpot:100                                       # SLO（ms）；逐请求 AND
    --save-result                                                      # 保存汇总 JSON
    --save-detailed                                                    # 加 per-request 数组
    --result-dir ./results                                             # 相对 /workspace
    --result-filename "d2-${TAG}-c${C}-n${N}-$(date +%Y%m%d-%H%M%S).json"  # tag/c/n/时间戳，避免覆盖
    --metadata gpu=l4-24gb vllm="$VLLM_VERSION" tag="$TAG" \
      concurrency="$C" n="$N" prefix_len="$PREFIX" input_len=1024 \
      output_len=256 temperature=0 power_limit="$POWER_LIMIT"          # 溯源信息；值里不要有空格
  )
  vllm bench serve "${args[@]}"
}

preempts() {
  curl -s http://127.0.0.1:8000/metrics |                              # Prometheus 文本
    awk '/^vllm:num_preemptions_total/{s+=$NF} END{print s+0}'         # 累加 counter；bench 前后相减
}
```

> 这段 export 与 §3.1 的 `HF_HOME` / `VLLM_VERSION` / `POWER_LIMIT` 保持一致；`HF_TOKEN` 在这里默认注释，避免把占位符 `hf_xxx` 当成真 token 导出。新 shell 整段粘 §3.4 即可。

> `--random-prefix-len` 会在 `--random-input-len` 之外**再前置**一段共享前缀，所以函数里用 `IN = 1024 - PREFIX` 保证总输入仍是 1024。跑完看 JSON 的 `input_lens` 是否全为 1024，不是就调整。

#### 3.4.1 四个函数的分工

| 函数 | 作用 | 在哪跑 | 行为 |
|---|---|---|---|
| `serve_awq` | 起 AWQ 服务 | 服务窗口（tmux A） | 前台阻塞；`Ctrl-C` 停服务 |
| `serve_fp16` | 起 FP16 服务 | 服务窗口（tmux A） | 前台阻塞；`Ctrl-C` 停服务 |
| `d2_bench` | 跑一轮压测并写 JSON | bench 窗口（tmux B） | 前台跑完返回 |
| `preempts` | 读当前累计抢占数 | bench 窗口（tmux B） | 立即返回一个整数 |

它们都是**当前 shell 的函数**，不是脚本文件。新开 SSH / tmux 窗口 = 新 shell，要重新粘一次 §3.4 的**整段**代码块（含 export）；否则函数找不到，JSON metadata 也会是空值。

#### 3.4.2 `serve_awq` / `serve_fp16` 逐行解释

调用形式：

```bash
serve_awq <TAG> [额外的 vllm serve 参数...]
serve_fp16 <TAG> [额外的 vllm serve 参数...]
```

| 行 / 参数 | 作用 | 为什么这么设 | 坑 |
|---|---|---|---|
| `local TAG="$1"; shift` | 第一个位置参数是日志标签，`shift` 把它从 `$@` 移除 | 避免把 `control-c16` 当成 vLLM 参数 | 忘记传 TAG，第一个 flag 会被当成 TAG 吃掉，报错很难懂 |
| `cd /workspace` | 固定工作目录 | 日志和 `./results` 都相对这里 | 不 `cd` 会在当前目录生成 `results/`，scp 时找不到 |
| `Qwen/Qwen3-8B-AWQ` / `Qwen/Qwen3-8B` | 权重仓库 | AWQ 是 4-bit 预量化；FP16 是全精度 | 两个仓库的 tokenizer 必须一致，否则 token 数不可比 |
| `--served-model-name qwen3-8b` | API 里的模型名 | bench 的 `--model` 必须匹配它 | 不匹配直接 404；它不是 HF 仓库名 |
| `--max-model-len 8192` | **单条请求** prompt+output 的上限 | D1/D2 的请求是 1024+256，8192 足够；和 D1 对齐 | 不是每步 token 预算；OOM 时可降 4096，但要在报告里写 |
| `--gpu-memory-utilization 0.90` | 权重 + KV + 激活可用的显存比例 | 与 D1 一致；0.90 留一点余量 | 同一组对比里不要改；OOM 先降这个或 `max-model-len` |
| `"$@"` | 调用方追加的参数 | 让一个函数覆盖所有配置：`--max-num-seqs 16`、`--max-num-batched-tokens 512`、`--disable-chunked-prefill`、`--max-model-len 2048` | 同名参数会重复，argparse **后者优先**；写在 `"$@"` 之后的固定参数（host/port/log）会覆盖调用方 |
| `--disable-log-requests` | 关闭逐请求日志 | 减少日志量和 CPU 噪声 | 不影响 metrics；排查 404/超时仍可临时去掉 |
| `--host 0.0.0.0 --port 8000` | 监听地址 | Vast 通过端口映射暴露 8000；实例内压测用 `127.0.0.1` | 只绑 `127.0.0.1` 时实例外访问不到；写在 `"$@"` 之后，调用方改不了 |
| `2>&1 \| tee /workspace/d2-${TAG}.log` | stdout+stderr 同时写终端和日志 | 后面要 grep `GPU KV cache size`、`Maximum concurrency`、`Prefix cache hit rate` | 同一个 TAG 重跑会**覆盖**旧日志；TAG 要唯一 |
| `--dtype float16`（仅 FP16） | 强制 FP16 | Qwen3-8B 的 config 是 float16；和 AWQ 的 `auto_awq` 对齐 | 不要用 bf16 和 FP16 混比 |

`serve_awq` 的 `"$@"` 在 `--max-model-len` / `--gpu-memory-utilization` **之后**，所以调用方可以覆盖这两个；但 `--host` / `--port` / `--disable-log-requests` 在 `"$@"` **之后**，调用方覆盖不了。这是故意设计的：地址和日志路径不应该在每个实验里变。

例子：

```bash
serve_awq control-c16 --max-num-seqs 64
# TAG=control-c16; "$@"="--max-num-seqs 64"
# 最终：--max-model-len 8192 ... --max-num-seqs 64 --disable-log-requests ...

serve_awq chunk-off --max-model-len 2048 --max-num-batched-tokens 2048 --disable-chunked-prefill
# 调用方的 --max-model-len 2048 覆盖函数里的 8192（后者优先）
```

#### 3.4.3 `d2_bench` 逐行解释

调用形式：

```bash
d2_bench <TAG> <C> <N> [PREFIX]
```

| 位置 | 变量 | 例子 | 含义 |
|---|---|---|---|
| `$1` | `TAG` | `control-c16` | 写进 JSON metadata 和文件名 |
| `$2` | `C` | `16` | **客户端**并发（同时在飞的请求数） |
| `$3` | `N` | `200` | 这一轮总共发多少条请求 |
| `$4` | `PREFIX` | `0` / `512` | 共享前缀长度；默认 0 |

> 输入总长 1024（`IN = 1024 - PREFIX`）和输出 256 是函数里的**固定设计**，不是 vLLM 默认值；v0.34 的 `bench serve` 默认是 **input 1024 / output 128**。要改长度就改函数，不要在同一张对比表里混用。

逐行：

| 行 / 参数 | 作用 | 为什么 | 坑 |
|---|---|---|---|
| `local IN=$((1024 - PREFIX))` | 随机后缀长度 | `--random-prefix-len` 是在随机输入**之外**再加前缀；总输入 = `IN + PREFIX` | 只有 `PREFIX <= 1024` 才合理；`PREFIX=1024` 会让 `IN=0`，bench 可能报错 |
| `cd /workspace` | 固定目录 | `--result-dir ./results` 相对这里 | 不 `cd` 会把 JSON 写到别处 |
| `curl -X POST /reset_prefix_cache` | 清空服务端 prefix cache | 同一服务上先跑 c16 再跑 c64 时，prompt 可能相同；不清会命中上一轮缓存 | 端点不存在时 `\|\| true` 静默跳过；如果服务没起，也会失败但继续 |
| `--backend openai --endpoint /v1/completions` | 走 OpenAI 兼容 HTTP | 和真实服务路径一致；`/v1/chat/completions` 只用于 smoke test | 选错 endpoint 会 404；bench 不测 chat |
| `--host 127.0.0.1 --port 8000` | 压测目标 | 实例内环回，不走公网 | 服务端口改了这里也要改 |
| `--model qwen3-8b` | API 模型名 | 必须等于 `--served-model-name` | 写成 HF 仓库名会 404 |
| `--tokenizer Qwen/Qwen3-8B` | 编码/统计 token 的 tokenizer | AWQ 和 FP16 用**同一个** tokenizer，保证 input/output 长度完全一致 | 不写会拿 `qwen3-8b` 去 HF 找，报 `not a local folder` |
| `--dataset-name random` | 合成 token 序列 | 长度可控、无需下载数据；只适合性能测试 | 分布不真实；不能拿来推断真实文本的 TTFT |
| `--random-input-len "$IN"` | 随机后缀长度 | 和 PREFIX 相加为 1024 | 和 `--random-prefix-len` 的关系别搞反 |
| `--random-prefix-len "$PREFIX"` | 共享前缀长度 | 所有请求共享同一段前缀，测 prefix caching | 只对 `random` 数据集有效；前缀必须从第 0 个 token 开始完全相同 |
| `--random-output-len 256` | 每条请求输出长度 | 固定工作量，吞吐/TPOT 可比 | 必须配 `--ignore-eos`，否则 EOS 提前截断 |
| `--num-prompts "$N"` | 这一轮总请求数（样本量） | 统计样本量；n 不是并发，也不是 batch | `n < c` 时到不了目标并发；n 太小 P99 不稳；同一对比对内 n 必须一致 |
| `--max-concurrency "$C"` | 客户端并发上限 | 闭路压测：保持 C 条在飞，完成一条补一条 | 不是服务端 `max-num-seqs`；C=64 时服务端可能只 admit 16 |
| `--ignore-eos` | 强制生成到 256 token | 不让 EOS 改变输出长度 | 不写会让不同配置的输出长度不同，TPOT/吞吐不可比 |
| `--seed 16` | 随机 prompt 的种子 | 所有配置用同一批 prompt，减少输入差异 | 固定 seed + 同一服务连续跑，必须配合 `reset_prefix_cache`，否则会命中上一轮 |
| `--temperature 0` | 贪心解码 | v0.34 不再默认 0；不写可能按 1.0 采样 | 采样会让输出长度和延迟抖动 |
| `--percentile-metrics ttft,tpot,itl,e2el` | 哪些指标算百分位 | 我们要 TTFT/TPOT/ITL/E2EL 的尾部 | 不列 `itl` 就没有 ITL P99.9 |
| `--metric-percentiles 50,95,99,99.9` | 百分位点 | P50/P95/P99 + ITL P99.9 看秒级停顿 | 和 `--percentile-metrics` 是笛卡尔积；小数点的 JSON key 是 `p99.9_itl_ms` |
| `--goodput ttft:2000 tpot:100` | SLO（ms） | 逐请求 AND：TTFT ≤ 2s 且 TPOT ≤ 100ms | goodput 单位是 **req/s**；达标比例 = `goodput / request_throughput` |
| `--save-result --save-detailed` | 保存 JSON + per-request 数组 | 后面要复算 ITL/TPOT/停顿次数 | JSON 没有 `tpots` 数组；TPOT 用 `latencies`、`ttfts`、`output_lens` 重算 |
| `--result-dir ./results` | 结果目录 | 相对 `/workspace` | 目录不存在时先 `mkdir -p`；scp 时别漏 |
| `--result-filename "d2-${TAG}-c${C}-n${N}-$(date ...).json"` | 文件名 | tag/c/n/时间戳，避免覆盖 | 同一秒跑两次会撞名；TAG 要唯一 |
| `--metadata ...` | 写进 JSON 的溯源信息 | gpu、vllm 版本、tag、c、n、prefix、长度、温度、power_limit | `VLLM_VERSION` / `POWER_LIMIT` 没 export 就是空值；metadata 里不要有空格 |

#### 3.4.4 `preempts` 逐行解释

```bash
curl -s http://127.0.0.1:8000/metrics \
  | awk '/^vllm:num_preemptions_total/{s+=$NF} END{print s+0}'
```

- `curl -s /metrics`：拿 Prometheus 文本格式；vLLM 的 counter 暴露时名字是 `vllm:num_preemptions_total`。
- `awk '/^vllm:num_preemptions_total/{s+=$NF}'`：匹配所有带 label 的序列，把最后一列（数值）累加；单卡通常只有一条。
- `END{print s+0}`：没有匹配时打印 0，避免空输出。
- 它是**服务启动以来的累计值**，不是本轮增量。用法是 bench 前后各读一次，相减：

```bash
BEFORE=$(preempts)
d2_bench control-c16 16 200 0    # TAG=control-c16；C=16 客户端并发；N=200 总请求；PREFIX=0 无前缀
AFTER=$(preempts)
echo "preemptions delta: $((AFTER-BEFORE))"
```

- `>0` 说明本轮发生了 KV 抢占（序列被换出/重算），这一组的 TTFT/ITL 已经受 KV 压力影响，不能把差异全算到旋钮头上。
- 如果读出来一直是 0，先确认 `curl -s /metrics | grep -c preempt` 不是 0；**curl 失败也会打印 0**，不要把“没连上”当成“没抢占”。D1 的三个日志里也没有 `Preemptions:` 行（vLLM 只在 >0 时打印），可以交叉验证。

#### 3.4.5 一次完整调用示例

服务窗口（tmux A）：

```bash
# 粘贴 §3.4 的整段代码块（export + 四个函数）
serve_awq control-c16 --max-num-seqs 64
```

bench 窗口（tmux B）：

```bash
# 在另一个 shell 里再粘一次整段（函数和 export 都不会跨 shell）
preempts
d2_bench control-c16 16 200 0    # TAG=control-c16；C=16 客户端并发；N=200 总请求；PREFIX=0 无前缀
preempts
ls -lh /workspace/results/d2-control-c16-*.json
```

`serve_*` 是前台命令，**不要加 `&`**；放 tmux 窗口里，`Ctrl-C` 才是干净地停服务。`d2_bench` 跑完会回到提示符；如果卡住，先看服务窗口是不是还在加载/已经崩了。

#### 3.4.6 常见错误

| 现象 | 原因 | 处置 |
|---|---|---|
| `unrecognized arguments: control-c16` | 忘了第一个参数是 TAG，或 TAG 写在了 flag 后面 | 调用形式是 `serve_awq <TAG> [flags]` |
| `--model qwen3-8b` 404 | served name 不匹配 | 检查 `--served-model-name` 和 bench `--model` |
| `qwen3-8b is not a local folder` | bench 拿 `--model` 找 tokenizer | 加 `--tokenizer Qwen/Qwen3-8B` |
| `input_lens` 不是 1024 | `IN` 和 `PREFIX` 没配平 | 确认 `PREFIX=512` 时 `IN=512`，且看 JSON |
| 输出长度不是 256 | 没加 `--ignore-eos`，或模型提前 EOS | 加 `--ignore-eos`；看 JSON `output_lens` |
| 两轮结果异常接近 | 固定 seed + 没清 prefix cache | `d2_bench` 已带 `reset_prefix_cache`；仍异常就手动 POST 一次 |
| metadata 为空 | `VLLM_VERSION` / `POWER_LIMIT` 没 export | 在当前 shell 重新 export，再跑 |
| 日志被覆盖 | 同一 TAG 重跑 | 用新 TAG，或先把旧日志改名 |
| `preempts` 一直是 0 | curl 失败 / 指标名变了 | `curl -s /metrics \| grep preempt` 确认 |
| 函数找不到 | 新 shell 没粘代码块 | 每个新窗口重新粘 §3.4 |

---

## 4. 逐个实验

### 4.0 各小节在测什么

| 小节 | 改的变量 | 对照 | 回答的问题 |
|---|---|---|---|
| 4.1 控制组 | **不改变量**：mns=64、chunk on、prefix on、budget 默认 2048 | — | 当天基线；c16/c64 给 4.2–4.4，c8 给 4.5 |
| 4.2 `mns` 16/32 | `max-num-seqs` 64→16（可选 32） | 4.1 的 c=64 | 服务端并发上限的吞吐/延迟取舍 |
| 4.3 `chunk-off` | chunked prefill on/off，**固定** `max-model-len=2048` + `budget=2048` | `control-2k` | prefill/decode 交错策略 |
| 4.3b `bt512` | `max-num-batched-tokens` 2048→512，chunking 保持 on | 4.1 的 c=16 | 每步 token 预算/步长；验证 D1 的秒级停顿假设 |
| 4.4 prefix on/off | prefix caching on/off，共享 512-token 前缀 | `prefix-on` vs `prefix-off` | 前缀复用能省多少 TTFT |
| 4.5 AWQ vs FP16 | 权重 4-bit vs FP16 | `control-c8` vs `fp16-c8` | 量化对吞吐/显存的影响；c=16 只看 KV 容量 |
| §5 质量门 | 模型精度 | AWQ vs FP16 | 量化对 GSM8K 质量的影响 |

> 两个容易说错的点：**4.1 不是研究 `max-num-seqs`，它是所有对比的当天基准**；**4.3b 动的不是 chunked prefill 开关，而是 token 预算**。4.3 和 4.3b 都作用在 prefill 调度上，但一个测“交错策略”，一个测“步长”。

每个实验的固定动作：

1. Terminal A `Ctrl-C` 停旧服务；
2. 用对应命令启动，日志写 `d2-<tag>.log`；
3. 等 `Application startup complete`，`curl /v1/models` 确认；
4. 记录该配置的 KV cache / 最大并发；
5. Terminal C 跑 `d2_bench`；记录 bench 前后的 `preempts`；
6. 把结果记到 §6 的表。

停服务后确认端口真的空了：

```bash
# 目的：旧服务还在时会抢 8000 端口；返回非 0 才说明端口空了
curl -sf http://127.0.0.1:8000/v1/models >/dev/null && echo "旧服务还在" || echo "端口空闲"
```

### 4.1 控制组（当天 baseline）

> **先重启服务**：第一次启动可跳过；如果已有服务，先在 tmux A `Ctrl-C`，确认 `curl -sf http://127.0.0.1:8000/v1/models` 失败后再启动。

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
d2_bench control-c16 16 200 0    # TAG=control-c16；C=16 客户端并发；N=200 总请求；PREFIX=0 无前缀
```

再跑 c=64 吞吐基准（同一个服务，不用重启）：

```bash
# 目的：吞吐基准；n 比 D1 小，控制总时长
d2_bench control-c64 64 300 0    # TAG=control-c64；C=64 客户端并发；N=300 总请求；PREFIX=0 无前缀
```

再补一个 c=8，作为 §4.5 AWQ vs FP16 的同并发对照（同一个服务，仍然不用重启）：

```bash
# 目的：FP16 在 c=16 会受 KV 上限影响，c=8 才是纯量化对比
d2_bench control-c8 8 100 0    # TAG=control-c8；C=8 客户端并发；N=100 总请求；PREFIX=0 无前缀
```

### 4.2 `max-num-seqs` 16 / 32

> **先重启服务**：tmux A `Ctrl-C` 停旧服务 → `curl -sf http://127.0.0.1:8000/v1/models` 失败 → 再启动下面的配置。

```bash
# 目的：把服务端并发上限压到 16，观察 c=64 客户端负载下的排队和吞吐
serve_awq mns16 --max-num-seqs 16
```

就绪后：

```bash
d2_bench mns16 64 300 0    # TAG=mns16；C=64 客户端并发；N=300 总请求；PREFIX=0 无前缀
```

> 请求怎么流动（64 在飞 → 16 running + 48 waiting → 完成即补位）见 §10 **Q12**。

可选，时间够再做 32：

> **先重启服务**：同样先 `Ctrl-C` 停掉 mns16，确认端口空了再启动 mns32。

```bash
serve_awq mns32 --max-num-seqs 32
```

就绪后：

```bash
d2_bench mns32 64 300 0    # TAG=mns32；C=64 客户端并发；N=300 总请求；PREFIX=0 无前缀
```

预期：`max-num-seqs` 降低会减少每批序列数，TPOT 可能下降、TTFT 排队可能变化，但 output tok/s 通常下降；找“吞吐开始明显掉”的拐点。注意：这不是“64 条一批、跑完再下一批”；vLLM 是 continuous batching，16 条 running 完成一条就补一条，日志里应看到 `Running: 16 reqs, Waiting: ~48 reqs`。

#### 4.2.1 结果与归因（2026-11-23）

条件：实例 `62184627`，L4 23,034 MiB / 40W，`Qwen/Qwen3-8B-AWQ`，vLLM 0.34.0；c=64、n=300、input 1024 / output 256；控制组 mns=64。三组抢占均为 0；KV cache 91,648（mns=64）vs 92,672（mns=16/32），差异来自启动 profiling，不是容量变化。

| 配置 | output tok/s | vs mns64 | TTFT P50 | TTFT P99 | TPOT P95 | ITL P99.9 | >1s gaps/req | goodput |
|---|---|---|---|---|---|---|---|---|
| mns=64（控制） | 143.1 | — | 8,102ms | 57,706ms | 426.2ms | 2,172ms | 31 | 0 |
| mns=32 | 137.5 | −3.9% | 63,271ms | 82,912ms | 226.4ms | 1,883ms | 17 | 0 |
| mns=16 | 119.8 | −16.3% | 104,945ms | 111,659ms | 130.1ms | 1,811ms | 3 | 0 |

**预期是否被证实：方向证实，但 TTFT 代价被低估。**

- output tok/s：64→32 只掉 3.9%，32→16 再掉 12.9%（相对 32）；**拐点在 32 与 16 之间**，mns32 保留 96.1% 的吞吐。
- TPOT P95：426→226→130ms（−46.9% / −69.5%），**减少每批序列数确实显著改善 TPOT**（mns 同时限制每步 decode 序列数；TPOT≈step_time，机制见 §10 Q15）。
- ITL P99.9：2,172→1,883→1,811ms，只小幅下降；`>1s gaps/req` 31→17→3，尾部停顿次数大幅减少，但 ~1.8s 的尖峰仍在——mns 只能缓解、不能消除 prefill 造成的停顿，这正是 4.3b 要测的。
- TTFT：8.1s→63.3s→104.9s（P50），57.7s→82.9s→111.7s（P99）。**不是“可能变化”，而是灾难性变差**。服务端只跑 16/32 条，其余 48/32 条在 waiting；Little's law 对得上：48 / 0.468 ≈ 102.6s，32 / 0.537 ≈ 59.6s（再加 prefill）。
- goodput：三组都是 0。TTFT P50 已远超 2s，TPOT P95 也都 >100ms；**没有一个 c=64 的 mns 配置满足 SLO**。

**最关键的一条**：`mns16`（c=64）的 output tok/s 和 TPOT P95 与 `control-c16` 几乎完全相同（119.8 vs 119.8 tok/s；130.1 vs 126.4ms），但 TTFT P50 是 **104.9s vs 4.1s（25.8×）**。服务端只跑 16 条，客户端多出来的 48 条只是在排队；**客户端并发超过服务端 `max-num-seqs` 不会增加吞吐，只会增加排队**。（两次跑的 n 不同：300 vs 200，但吞吐/TPOT 量级一致；机制上由 mns 决定。）

结论：`max-num-seqs` 不是“免费的吞吐旋钮”，而是**用 TTFT 排队换 TPOT**。在这台 40W L4、这个 SLO 下：

- 想要吞吐：保持 mns=64，但 c=64 已不满足 SLO；
- 想要 TPOT：mns=16，但 TTFT 105s，同样不满足 SLO；
- 想要 SLO 安全：先把客户端并发降到 c≤8，再按 goodput 曲线找容量；c=8 的 goodput 0.088（25% 达标），c=16 只有 0.0023（0.5%），c=64 全为 0。

> 控制组 c64 的 output 143.1 比 D1 的 132.8 高 7.8%：D2 的 n=300 比 D1 的 n=1000 短，持续功耗/热节流更少；只做同一天、同一 n 的对比，不跨 D1。
>
> 数据说明：这批 4.2 JSON 的 `metadata` 是 `null`，tag 从文件名恢复；`power_limit` 从启动日志/实例确认是 40W。后续跑 4.3 前确认 `d2_bench` 用的是最新版（带 `--metadata`），否则报告里只能靠文件名溯源。

### 4.3 chunked prefill off（固定 2048 预算，含对照）

v0.34 源码里有两条约束：

1. `--disable-chunked-prefill` 要求 `max_num_batched_tokens >= max_model_len`，否则启动直接 `ValueError`；
2. 不显式传 budget 时，EngineArgs 会自动把 budget 抬到 `max_model_len`（这里是 8192）。

所以“直接关 chunking”会同时把步长预算从 2048 改成 8192，两个变量一起动。要单变量，就把 `max-model-len` 和 budget 都钉在 2048，先跑一个 chunking 仍开着的对照：

> **先重启服务**：tmux A `Ctrl-C` 停掉当前服务，确认 `curl -sf http://127.0.0.1:8000/v1/models` 失败后再启动。

```bash
# 目的：#4 的同预算对照；除了 chunked prefill 开关，其他都与 chunk-off 相同
serve_awq control-2k --max-model-len 2048 --max-num-batched-tokens 2048 --max-num-seqs 64
```

就绪后：

```bash
d2_bench control-2k 16 200 0    # TAG=control-2k；C=16 客户端并发；N=200 总请求；PREFIX=0 无前缀
```

再关：

> **先重启服务**：先停掉 `control-2k` 服务，确认端口空了再启动 `chunk-off`。

```bash
# 目的：同一 2048 预算下，关掉 prefill/decode 交错
serve_awq chunk-off --max-model-len 2048 --max-num-batched-tokens 2048 --max-num-seqs 64 --disable-chunked-prefill
```

就绪后：

> 注意：最后的 `0` 是 **PREFIX=0**（无共享前缀），不是 `prefill=0`；每条请求仍有 1024 个输入 token。

```bash
d2_bench chunk-off 16 200 0    # TAG=chunk-off；C=16 客户端并发；N=200 总请求；PREFIX=0 无前缀
```

> `max-model-len 2048` 对 1024+256 的请求够用；KV cache 总池由显存决定，不随 `max-model-len` 变小。

预期：1024-token prompt 在 2048 budget 下本来就能塞进一个 step，chunking 很少真的把单条 prompt 切开；所以 on/off 的差异可能很小。**这组回答的是“交错策略”，不是“步长”**。如果差异很大，先回看启动日志的 `max_num_batched_tokens`，很可能预算被抬到了 8192。

> **结果（2026-11-23）：差异很大，但不是预算被抬高。** 日志确认两边都是 `max_model_len=2048`、`max_num_batched_tokens=2048`；ITL 尾部如预期下降，TTFT **也下降**，吞吐/TPOT 基本不变。见 §4.3.1。

#### 4.3.1 结果与归因（2026-11-23）

条件：实例 `62184627`，L4 23,034 MiB / 40W，`Qwen/Qwen3-8B-AWQ`，vLLM 0.34.0；c=16、n=200、input 1024 / output 256。两边启动日志都确认 `max_model_len=2048`、`max_num_batched_tokens=2048`；`control-2k` 是 `enable_chunked_prefill=True`，`chunk-off` 是 `enable_chunked_prefill=False`。抢占均为 0；KV cache 88,064（control-2k）vs 92,672（chunk-off），都远高于 16×1280，不是 KV 压力。

> 实际两轮启动时未显式传 `--max-num-seqs 64`，v0.34 默认 **128**；c=16 时 16 running < 64/128，mns 不绑定，所以结果不受影响。上面的命令已补 `--max-num-seqs 64`。

| run | output tok/s | TTFT P50 | TTFT P95 | TTFT P99 | TPOT P95 | ITL P99 | ITL P99.9 | >1s gaps/req | goodput |
|---|---|---|---|---|---|---|---|---|---|
| control-2k（chunk on） | 119.4 | 4,152ms | 7,194ms | 12,324ms | 126.6ms | 1,678ms | 1,811ms | 3（190/200 条有） | 0.0023 |
| chunk-off（chunk off） | 120.4 | 2,761ms | 4,715ms | 11,467ms | 125.6ms | 939ms | 993ms | 0（0/200 条有） | 0.0024 |
| 4.1 control-c16（8192，on） | 119.8 | 4,068ms | 7,160ms | 12,104ms | 126.4ms | 1,642ms | 1,810ms | 3 | 0.0023 |

**预期是否被证实：一半。**

- **ITL：证实且超预期。** ITL P99 1,678→939ms（−44.0%），P99.9 1,811→993ms（−45.2%）；control-2k 有 190/200 条请求出现 `>1s gap`（每条中位数 3 个、最多 7 个），chunk-off **0/200**，最大 ITL 999ms。
- **TTFT：预期被推翻。** 原以为关 chunking 会让 TTFT 变差，实际 P50 4,152→2,761ms（−33.5%），P95 7,194→4,715ms（−34.5%），P99 12,324→11,467ms（−7.0%）。
- **吞吐/TPOT：基本不变。** output 119.4→120.4（+0.8%），total token throughput 596.8→601.9（+0.9%），TPOT P95 126.6→125.6（−0.8%）。
- **goodput：** 0.0023→0.0024，都是 0.5% 达标；SLO 仍不满足（TTFT P50 2.76s、TPOT P95 125.6ms 都超）。

**为什么 chunk-off 反而全面更好**（解释，不是已证实的因果）：

- chunking on 时，scheduler 可以用剩余预算调度**部分** prefill；一步可能装进约 2032 个 prefill token（例如一条 1024 prompt + 另一条的 1008 token），decode 要等约 1.8s。
- chunking off 时，每条 prefill 必须整体调度；剩下装不下的部分不能塞，所以一步最多处理一条 1024-token prompt，decode 最多等约 1s。结果就是 ITL 尾部从 1.8s 降到 1.0s，`>1s gap` 清零。
- TTFT 变好更像是“整段 prefill 一次完成”减少了分块/交错带来的调度延迟；这一点是解释，不是直接测量。
- 这不是“预算被抬到 8192”的假象：日志明确是 2048/2048。

**结论**：在这台 40W L4、c=16、1024-token prompt 的负载下，`--disable-chunked-prefill` 不是“用 TTFT 换 ITL”，而是**同时改善 ITL 尾部和 TTFT，吞吐不变**。原因是它把每步的 prefill 上限从“剩余预算（约 2032）”变成“一条完整 prompt（1024）”，等价于一个隐式的 prefill 步长上限。

**但不要外推**：这是低并发、短 prompt 的结果。并发更高或 prompt 更长时，关 chunking 可能造成 head-of-line blocking、TTFT 变差、GPU 利用率下降。D2 的结论只覆盖 c=16 / 1024 in / 256 out / 40W L4。

> 与 4.1 `control-c16` 对比：control-2k 和它几乎完全一致（output 119.4 vs 119.8，TTFT P99 12,324 vs 12,104，ITL P99.9 1,811 vs 1,810），说明 `max-model-len=2048` 对这个 workload 没有影响，control-2k 是有效对照。

### 4.3b `max-num-batched-tokens` 512（可选，优先于 mns32）

> **先重启服务**：tmux A `Ctrl-C` 停掉 `chunk-off` 服务，确认 `curl -sf http://127.0.0.1:8000/v1/models` 失败后再启动。

```bash
# 目的：把每个调度步的 prefill 预算从默认 2048 压到 512，直接检验“步长造成 decode 停顿”
serve_awq bt512 --max-num-seqs 64 --max-num-batched-tokens 512
```

就绪后：

```bash
d2_bench bt512 16 200 0    # TAG=bt512；C=16 客户端并发；N=200 总请求；PREFIX=0 无前缀
```

> **“~2.3s 停顿”到底是什么**：D1 **c=64** 的 **ITL P99 = 2,345ms**（P99.9 2,367ms），来自 1000 条请求 × 255 个 token gap 展平后的分布；不是 TPOT，也不是 TTFT。同一轮 TPOT P95 只有 470ms，因为 TPOT 把 255 个 gap 平均掉了。
>
> 运行条件：40W L4、Qwen3-8B-AWQ、vLLM 0.34.0、`max-model-len 8192`、`max-num-seqs 64`、chunked prefill on、prefix caching on、random 1024 in / 256 out、`--ignore-eos`、`--temperature 0`、c=64、n=1000。D1 c=16 的 ITL P99.9 约 2.0s；诊断跑 c=16/n=200 的 ITL P99 1.83s / P99.9 1.99s。
>
> **D1 的 chunked prefill 是开的**（启动日志 `enable_chunked_prefill=True`）；1024-token prompt 在 2048 预算下没被切开。`bt512` 是通过压预算**强制**分块，不是打开 chunking。

预期：如果 D1 的秒级停顿（c=16 的 ITL P99.9 ≈ 2.0s，c=64 的 ITL P99 ≈ 2.3s）来自“一个 step 里 1024–2048 个 prefill token 和 decode 同批”，这组应看到 ITL P99.9 和 `>1s gaps/req` 明显下降，代价是 TTFT P99 上升（同样多的 prefill 要拆成更多步）。若 ITL 不变，假设被否定，停顿另有来源。

> 机制细节（为什么大段 prefill 会拉高同一 step 里其他序列的 ITL）见 §10 **Q14**。

> **结果（2026-11-23）：假设成立。** ITL P99.9 1,811→566ms（−68.7%），`>1s gap` 190/200→0/200；TTFT P99 12,324→12,779ms（+3.7%），output 119.4→118.3（−0.9%）。见 §4.3b.1。

#### 4.3b.1 结果与归因（2026-11-23）

条件：实例 `62184627`，L4 23,034 MiB / 40W，AWQ，vLLM 0.34.0；c=16、n=200、input 1024 / output 256。`bt512` 的启动日志确认 `max_model_len=8192`、`max_num_batched_tokens=512`、`max_num_seqs=64`、chunked prefill on、prefix caching on；抢占 0；KV cache 92,160。

| run | 每步最大 prefill（推断） | output tok/s | TTFT P50 | TTFT P95 | TTFT P99 | TPOT P95 | ITL P99 | ITL P99.9 | max ITL | >1s gaps/req | goodput |
|---|---|---|---|---|---|---|---|---|---|---|---|
| control-2k（budget 2048，on） | ~2032 | 119.4 | 4,152 | 7,194 | 12,324 | 126.6 | 1,678 | 1,811 | 1,820 | 3 | 0.0023 |
| chunk-off（budget 2048，off） | ~1024 | 120.4 | 2,761 | 4,715 | 11,467 | 125.6 | 939 | 993 | 999 | 0 | 0.0024 |
| bt512（budget 512，on） | ~496 | 118.3 | 2,501 | 5,514 | 12,779 | 127.3 | 516 | 566 | 574 | 0 | 0.0023 |

**预期是否被证实：是，ITL 假设成立。**

- ITL P99.9：1,811→566ms（−68.7%）；max ITL 1,820→574ms；`>1s gap` 190/200→**0/200**。
- TTFT：P50 4,152→2,501ms（−39.8%），P95 7,194→5,514ms（−23.3%），**P99 12,324→12,779ms（+3.7%）**。预期的“TTFT P99 上升”成立，但代价只在尾部；中位数/P95 反而更好。
- 吞吐/TPOT：output 119.4→118.3（−0.9%），total 596.8→591.7（−0.9%），TPOT P95 126.6→127.3（+0.6%）。代价很小。
- goodput：0.0023，0.5% 达标；SLO 仍不满足（TTFT P50 2.50s、TPOT P95 127.3ms 都超）。

**三点连起来看，证据很强**：

| 每步最大 prefill | ITL P99.9 | max ITL |
|---|---|---|
| ~2032 token（budget 2048） | 1,811ms | 1,820ms |
| ~1024 token（chunk-off，整条 prompt） | 993ms | 999ms |
| ~496 token（budget 512） | 566ms | 574ms |

ITL 尾部大致随“每步最大 prefill token 数”线性变化（约 0.9–1.2ms/token）。这和“一个 prefill step 要 ~1ms/token”的估算一致，而不是 KV 抢占或排队造成的——三组抢占都是 0。

**和 chunk-off 的取舍**：

- `bt512` 的 ITL 尾部更低（566 vs 993ms），但 TTFT P95/P99 更差（5,514/12,779 vs 4,715/11,467ms），吞吐略低（118.3 vs 120.4 tok/s）。
- `chunk-off` 是更均衡的点：ITL 尾部 ~1s，TTFT 比 control 更好，吞吐不降。
- `bt512` 是更激进的 ITL 尾部修复：用 TTFT 尾部和 ~1% 吞吐换 0.57s 的 max ITL。

**结论**：D1 的秒级停顿主要来自 **prefill step 的 token 数**，不是 KV 抢占；把每步 prefill 从 ~2032 压到 ~496，ITL P99.9 从 1.81s 降到 0.57s，代价是 TTFT P99 +3.7% 和吞吐 −0.9%。这也解释了为什么 `mns16` 只能把 TPOT 降下来、却去不掉 ~1.8s 的 ITL 尖峰：mns 改的是 decode batch，不是 prefill step。

> JSON metadata 仍为 `null`；配置从启动日志确认（`max_num_batched_tokens=512`）。

### 4.4 prefix caching on/off（共享前缀）

先跑“缓存开 + 共享前缀”：

> **先重启服务**：tmux A `Ctrl-C` 停掉 `bt512` 服务，确认 `curl -sf http://127.0.0.1:8000/v1/models` 失败后再启动。

```bash
# 目的：默认 prefix caching 已开；这批请求共享 512-token 前缀
serve_awq prefix-on --max-num-seqs 64
```

就绪后：

```bash
d2_bench prefix-on 16 200 512    # TAG=prefix-on；C=16 客户端并发；N=200 总请求；PREFIX=512 共享前缀
```

再跑“缓存关 + 同样前缀”：

> **先重启服务**：先停掉 `prefix-on` 服务，确认端口空了再启动 `prefix-off`。

```bash
serve_awq prefix-off --max-num-seqs 64 --disable-prefix-caching
```

就绪后：

```bash
d2_bench prefix-off 16 200 512    # TAG=prefix-off；C=16 客户端并发；N=200 总请求；PREFIX=512 共享前缀
```

记录服务端日志的命中率：

```bash
# 目的：确认 prefix-on 真的命中；应该看到较高的 Prefix cache hit rate
grep "Prefix cache hit rate" /workspace/d2-prefix-on.log | tail -3
grep "Prefix cache hit rate" /workspace/d2-prefix-off.log | tail -3
```

预期：`prefix-on` 的 TTFT 明显低于 `prefix-off`；如果两者一样，先检查 `input_lens` 是否 1024、前缀是否真的相同。

> **配置说明**：实际 4.4 两轮启动时没有显式传 `--max-num-seqs 64`，v0.34 默认 **128**；c=16 时 16 running < 64/128，mns 不绑定，所以结果不受影响。上面的命令已补 64，后续按 64 复现。

#### 4.4.1 结果与归因（2026-11-23）

条件：实例 `62184627`，L4 23,034 MiB / 40W，AWQ，vLLM 0.34.0；c=16、n=200、input 1024 / output 256、`PREFIX=512`。`prefix-on` 的启动日志是 `enable_prefix_caching=True`，`prefix-off` 是 `False`；两边 `enable_chunked_prefill=True`；抢占均为 0。`input_lens` 全为 1024，`output_lens` 全为 256。

| run | output tok/s | total tok/s | TTFT P50 | TTFT P95 | TTFT P99 | TPOT P50 | TPOT P95 | ITL P99 | ITL P99.9 | >1s gaps/req | goodput | 命中率 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| prefix-off | 120.0 | 600.0 | 4,168ms | 7,081ms | 12,446ms | 115.3ms | 126.2ms | 1,685ms | 1,776ms | 3 | 0.0023（0.5%） | 0% |
| prefix-on | 149.9 | 749.7 | 4,002ms | 5,324ms | 7,106ms | 90.0ms | 101.8ms | 534ms | 1,689ms | 2 | **0.1084（18.5%）** | **~50%** |

**预期是否被证实：TTFT 证实，但效果不止 TTFT。**

- TTFT：P50 只降 4.0%（4,168→4,002ms），但 P95 降 24.8%（7,081→5,324ms），P99 降 42.9%（12,446→7,106ms）。所以“TTFT 明显低于”主要体现在**尾部**，中位数变化不大。
- 吞吐/TPOT：**意外的大收益**。output 120.0→149.9（+24.9%），total 600.0→749.7（+24.9%），TPOT P50 115.3→90.0ms（−21.9%），P95 126.2→101.8ms（−19.3%）。
- ITL：P99 1,685→534ms（−68.3%），P99.9 1,776→1,689ms（−4.9%）。大多数 prefill step 减半，尾部尖峰频率下降；但非共享的 512-token 后缀仍偶尔形成一个完整 prefill step，所以 max ITL 仍在 ~1.7s。
- goodput：0.0023（0.5%）→ **0.1084（18.5%）**，约 46×。
- 命中率：prefix-on 稳态约 **49.5–50%**，正好等于 512/1024；prefix-off 为 0%。
- KV cache：88,064（on）vs 92,672（off），差约 4,600 token，来自 prefix cache 元数据/profiling；两组都远高于 16×1,280，不是 KV 压力。

**为什么吞吐和 TPOT 也会变好**：

- prefix caching 省的是 **prefill 计算**：512-token 共享前缀的 KV 直接复用，不再重算。
- c=16 时 prefill 和 decode 争同一张 40W 卡；每条请求少算 512 个 prefill token，decode 就能多拿回一部分算力。
- 所以不只是 TTFT 下降：output tok/s +25%，TPOT −19%，goodput 从 0.5% 到 18.5%。

**边界**：这是“所有请求共享同一段 512-token 前缀”的合成负载，命中率能稳定到 50%。真实 traffic 的前缀复用率取决于 system prompt / RAG 上下文 / 多轮对话的重合度；不要假设任何负载都能拿到 +25% 吞吐。

> 这两轮实际用的是 v0.34 默认 `max_num_seqs=128`（命令里没显式传 64）；c=16 时 16 running < 64/128，mns 不绑定，所以对结果无影响。上面的命令已补 `--max-num-seqs 64`。

### 4.5 AWQ vs FP16

**主对比用 c=8，不要直接 c=16。** AWQ 权重 5.7GB、FP16 16.4GB，差 10.7GB；按 144KiB/token 算，这 10.7GB 约等于 7.2 万 token 的 KV。D2 控制组的 AWQ KV 是 91,648 token（D1 是 96,256），所以 FP16 大约只剩 **1.9 万 token**，而 c=16 × 1280 token/请求 = 20,480，已经压到 KV 上限——TTFT 会被排队/KV 压力污染，不能把差异全算成量化。

> D1 本身就是 AWQ baseline（`Qwen/Qwen3-8B-AWQ`，`quantization=auto_awq`）；D1 没有跑过 FP16，FP16 是 D2 新增的对照。
>
> D1 与 D2 的 AWQ KV 差约 4,600 token（96,256 vs 91,648），来自不同 host / 启动 profiling；4.5 用 D2 控制组的值估算 FP16，因为 FP16 也跑在 D2 这台机器上。

#### 4.5.1 这笔账怎么算：为什么主对比用 c=8

1. **AWQ 只省权重，不省 KV/token。** AWQ 是 W4A16：权重 4-bit，激活和 KV cache 仍是 FP16。所以 Qwen3-8B 每 token 的 KV 在 AWQ 和 FP16 下都是 **144KiB**。
2. **权重差多少。** AWQ 文件 5.7GB，FP16 16.4GB，差 **10.7GB**。换算成 GiB：`10.7×10^9 / 1024^3 ≈ 9.96GiB`。（5.7GB 不是纯 4-bit 的 4GB：embedding/lm_head 仍是 BF16，另有 scale/zero。）
3. **这些显存能放多少 KV。** `9.96GiB / 144KiB ≈ 72,500 token`。
4. **FP16 还剩多少 KV。** D2 的 AWQ 控制组 KV 是 91,648 token；FP16 权重多占 9.96GiB，所以 KV 大约剩 `91,648 − 72,500 ≈ 19,100 token`。
5. **c=16 要多少 KV。** 每条请求最多 1024 input + 256 output = **1,280 token**；16 条同时跑满需要 `16 × 1,280 = 20,480 token > 19,100`。**差约 1,300 token**，至少一条请求会被排队/抢占，TTFT 会被 KV 压力污染。
6. **c=8 要多少。** `8 × 1,280 = 10,240 < 19,100`，留约 8,900 token 余量；AWQ 和 FP16 都不会因为 KV 不够而排队，吞吐/TPOT 的差异才能归因到“权重 4-bit vs FP16”。

所以：**c=8 是纯量化对比；c=16 是“量化 + KV 容量”的混合效应**，只能作观察，不能当因果。

> 这是估算：实际 FP16 的 KV 以启动日志 `GPU KV cache size` 为准；FP16 的激活显存可能比 AWQ 略大，实际 KV 可能比 19,100 更小，所以 c=8 是保守选择。
>
> 2026-11-23 实测：FP16 启动日志 `GPU KV cache size: 18,944 tokens`，和估算 19,100 基本一致；`c=8` 需要 `8 × 1,280 = 10,240`（够），`c=16` 需要 `20,480`（不够）。启动日志的 `Maximum concurrency for 8,192 tokens per request: 2.31x` 是“每条请求吃满 8,192”时的并发，不是 1,280-token 请求的并发；见 §10 Q18。

AWQ 的 c=8 对照已经在 §4.1 用控制组服务跑过（`control-c8`），这里直接换 FP16：

> **先重启服务**：tmux A `Ctrl-C` 停掉 `prefix-off` 服务，确认 `curl -sf http://127.0.0.1:8000/v1/models` 失败后再启动 FP16。

```bash
# 目的：同一 served name，换 FP16 权重；先确认显存够，OOM 就降 max-model-len
serve_fp16 fp16-c8 --max-num-seqs 64
```

就绪后：

```bash
grep -E "GPU KV cache size|Maximum concurrency" /workspace/d2-fp16-c8.log | tail -2
d2_bench fp16-c8 8 100 0    # TAG=fp16-c8；C=8 客户端并发；N=100 总请求；PREFIX=0 无前缀
```

可选：在同一个 FP16 服务上再跑 c=16（不用重启），观察 KV 容量效应。**先看抢占增量**；如果 `>0`，这一行只能说明“FP16 的 KV 不够”，不是纯量化对比：

```bash
d2_bench fp16-c16 16 200 0    # TAG=fp16-c16；C=16 客户端并发；N=200 总请求；PREFIX=0 无前缀（同一 FP16 服务）
```

如果启动 OOM：

> **先重启服务**：先停掉当前 FP16 服务（或失败的启动进程），确认端口空了再降上下文重试。

```bash
# 目的：FP16 权重太大时缩短上下文，先保证能跑；在 README 里注明
serve_fp16 fp16-4k --max-num-seqs 64 --max-model-len 4096
```

就绪后：

```bash
d2_bench fp16-4k 8 100 0    # TAG=fp16-4k；C=8 客户端并发；N=100 总请求；PREFIX=0 无前缀
```

> 读启动日志时记下 FP16 的 `GPU KV cache size`；它和 D2 AWQ 控制组的 91,648（D1 是 96,256）对比，就是“量化多换来的容量”，这比单纯的 tok/s 更能解释 24GB 卡上的取舍。

---

## 5. 质量门（GSM8K 50 条）

只在 AWQ 和 FP16 两个服务都跑过性能后做；它衡量“量化掉了多少质量”，不是性能。

两个服务不能同时占 8000 端口。如果当前开着的是 FP16，就先测 FP16；测完 `Ctrl-C` 停掉。**两边 `max_gen_toks` 必须一致**。

如果当前不是 AWQ，先重启：

> **先重启服务**：确认 `curl -sf http://127.0.0.1:8000/v1/models` 失败后，再启动 AWQ。

```bash
serve_awq qgate-awq --max-num-seqs 64
```

AWQ 就绪后：

```bash
# 目的：用当前 vLLM 服务做 50 条 GSM8K，5-shot，greedy；记录 exact_match
# max_gen_toks=1024 必须显式传：lm-eval 默认只生成 256 token，Qwen3 的 thinking CoT 会在中途被截断
# max_length=4096 防止 5-shot prompt（约 1.2k token）被 2048-1024 的默认上限截掉
# batch_size 8 × num_concurrent 8 = 客户端最多 64 条 prompt 在途；服务端 batch 仍由 vLLM 决定
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

> 50 条 GSM8K 只是指示性质量门，不是完整评测：n=50 时单个比例的 95% 置信区间约 ±11 个点，**分辨不了 1–2 个点的差异**。报告里写原始命中数（如 43/50 vs 44/50）和“未检测到明显掉点 / 检测到明显掉点”，不要写“AWQ 只掉 1.2 个点”。

---

## 6. 结果表与归因

复制到 D2 报告或 README 的 D2 小节：

| # | tag | 配置 | c | n | output tok/s | TTFT P50 | TTFT P99 | TPOT P95 | ITL P99.9 | >1s gaps/req | goodput | 抢占 Δ | KV cache | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | control-c16 | AWQ mns=64 | 16 | 200 | 119.8 | 4,068 | 12,104 | 126.4 | 1,810 | 3 | 0.0023（0.5%） | 0 | 91,648 | |
| 0b | control-c8 | AWQ mns=64 | 8 | 100 | 90.4 | 2,780 | 6,836 | 83.0 | 1,760 | 0（mean 0.4） | 0.0883（25%） | 0 | 91,648 | 4.5 对照 |
| 1 | control-c64 | AWQ mns=64 | 64 | 300 | 143.1 | 8,102 | 57,706 | 426.2 | 2,172 | 31 | 0 | 0 | 91,648 | 4.2 控制组 |
| 2 | mns16 | mns=16 | 64 | 300 | 119.8 | 104,945 | 111,659 | 130.1 | 1,811 | 3 | 0 | 0 | 92,672 | Running 16 / Waiting 48 |
| 3 | mns32 | mns=32 | 64 | 300 | 137.5 | 63,271 | 82,912 | 226.4 | 1,883 | 17 | 0 | 0 | 92,672 | Running 32 / Waiting 32 |
| 4a | control-2k | 2k len + 2k budget | 16 | 200 | 119.4 | 4,152 | 12,324 | 126.6 | 1,811 | 3 | 0.0023（0.5%） | 0 | 88,064 | 同预算对照 |
| 4 | chunk-off | chunked off, 2k budget | 16 | 200 | 120.4 | 2,761 | 11,467 | 125.6 | 993 | 0 | 0.0024（0.5%） | 0 | 92,672 | 0/200 条 >1s |
| 4b | bt512 | batch-tokens=512 | 16 | 200 | 118.3 | 2,501 | 12,779 | 127.3 | 566 | 0 | 0.0023（0.5%） | 0 | 92,160 | 0/200 条 >1s |
| 5 | prefix-on | prefix on | 16 | 200 | 149.9 | 4,002 | 7,106 | 101.8 | 1,689 | 2 | 0.1084（18.5%） | 0 | 88,064 | 命中率 ~50% |
| 6 | prefix-off | prefix off | 16 | 200 | 120.0 | 4,168 | 12,446 | 126.2 | 1,776 | 3 | 0.0023（0.5%） | 0 | 92,672 | 命中率 0% |
| 7 | fp16-c8 | FP16 | 8 | 100 | | | | | | | | | | |
| 7b | fp16-c16 | FP16（可选） | 16 | 200 | | | | | | | | | | KV 受限，看抢占 |

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

### 6.1 全 D2 一句话结论（其余实验完成后填）

> 在 40W L4 上，`max-num-seqs` 从 64 降到 16 使 output tok/s 变化 __%、TPOT P95 变化 __%；`max-num-batched-tokens` 从 2048 降到 512 使 ITL P99.9 从 __ 变为 __、TTFT P99 从 __ 变为 __；关闭 chunked prefill（固定 2048 预算）使 ITL P99.9 __、TTFT P99 __；共享 512-token 前缀时 prefix caching 使 TTFT P99 从 __ 降到 __（命中率 __%）；AWQ 相对 FP16 吞吐 __%（c=8）、GSM8K exact match 变化 __ 个点。因此 D3/D4 应优先保留 ______ 配置。

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
| FP16 启动 OOM | 16.4GB 权重 + 8k KV 放不下 | `--max-model-len 4096`；或只跑 c=1/4/8 |
| FP16 c=16 TTFT 明显变差 | FP16 KV 只剩约 1.9 万 token，16×1280 已压上限 | 主对比用 c=8；c=16 单独标“KV 受限”，看抢占 |
| `--no-enable-*` 在 help 里搜不到 | v0.34 的 EnableDisableAction 只显示 `--enable-x` / `--disable-x`；`--no-enable-x` 是隐藏兼容别名 | 用 `--disable-*`；`grep -E "disable-(chunked-prefill\|prefix-caching)"` 对一遍 |
| `--max-num-seqs 64` 没生效 | v0.34 默认是 128 | 控制组命令里显式写；看启动日志 `non-default args` 的 `max_num_seqs` |
| `chunk-off` 启动报 `max_num_batched_tokens < max_model_len` | v0.34 关 chunked prefill 时 budget 必须 ≥ max_model_len | 同时传 `--max-model-len 2048 --max-num-batched-tokens 2048` |
| `chunk-off` 差异巨大 | 没显式传 budget，被自动抬到 8192，步长也变了 | 固定 2048 预算，先跑 `control-2k` 对照 |
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
- [ ] chunked prefill off（含 `control-2k` 同预算对照）结果，或明确 deferred
- [ ] prefix caching on/off（共享 512-token 前缀）+ 命中率
- [ ] AWQ vs FP16：c=8 主对比 + 两边 KV cache 数字（时间不够可 deferred，但要写明）
- [ ] GSM8K 50 条质量门（或明确 deferred；记录 max_gen_toks）
- [ ] ITL P50/P99/P99.9 + `>1s gaps/req`（不只 TPOT）
- [ ] 一张对照表 + 一句话结论（带数字和方向）
- [ ] 结果和日志 scp 回本地，commit + push
- [ ] 成本记录
- [ ] 实例 Stop 或 Destroy，并注明理由

---

## 10. 概念与问答（执行前读）

这一节记录 D2 讨论中被问到的问题；操作命令仍以第 3–4 节为准，这里解释“为什么”和“数字从哪来”。

### Q1：prefill 和 decode 到底在争什么？

**Prefill** 把整段 prompt 的所有 token 并行算一遍，写 KV cache，产出首 token；计算密集。**Decode** 每条运行中的序列每步只生成 1 个 token，读 KV cache；显存带宽密集。TTFT 主要是排队 + prefill，TPOT/ITL 主要是 decode step 的时间。

一个 scheduler step 的 token 预算由 `max_num_batched_tokens` 控制，prefill 和 decode 共用这个预算，所以一条新请求的 prefill 会拖慢同一 step 里正在 decode 的请求。

### Q2：`max-num-batched-tokens` 是什么？和 `max-num-seqs` 有什么区别？

- `max-num-batched-tokens`：**一次 forward 最多处理多少个 token**，prefill token 和 decode token 都算；v0.34 默认 **2048**。
- `max-num-seqs`：**同时最多有多少条序列**；v0.34 默认 **128**，D1/D2 控制组显式用 64。

例子：64 条序列各 decode 1 token = 64 token；一条 1024-token prompt 做 prefill = 1024 token；两条 1024-token prompt 同一步 = 2048 token，正好打满。

调大 budget：每步塞更多 token，吞吐上升，但单步变长、ITL 尾部变差；调小：ITL 更平滑，但步数变多、吞吐下降、长 prompt 的 TTFT 变差。D1 c=64 的 ITL P99 = 2,345ms，量级等于一个 1024–2048 token 的 prefill step，所以 `bt512` 是直接检验。

### Q3：chunked prefill 是什么？

关闭时，一条 prefill 必须**整体**放进一个 step；它占满 step 时，所有正在 decode 的序列都得等。开启后，预算不够就把 prefill 拆成多个 chunk，和 decode 混在同一 step：decode 更平滑、GPU 利用率更高，但长 prompt 的 TTFT 可能变大。

v0.34 默认开启，关闭用 `--disable-chunked-prefill`。

两个容易误解的点：

1. **chunked prefill 不是强行切碎**。1024-token prompt 在 2048 预算下通常一次就能算完；只有预算不够（多条 prefill 竞争，或你把 budget 调小）时才切。D1 就是“开着但没触发”：启动日志里 `enable_chunked_prefill=True`，1024 prompt 在 2048 预算下没被切开。所以 `chunk-off` 在 2048 预算下可能和 control 几乎没差异；`bt512` 才是“步长”实验。
2. **关掉 chunking 会连带改预算**。v0.34 要求 `max_num_batched_tokens >= max_model_len`，否则启动 `ValueError`；不显式传 budget 时，EngineArgs 会自动把它抬到 `max_model_len`（8192）。这样就不是单变量了。§4.3 因此固定 `max-model-len 2048` + `budget 2048`，并加 `control-2k` 对照。

### Q4：prefix caching 是什么？

Prefill 的 KV 按 **block** 对齐做哈希；新请求从第 0 个 block 开始匹配，命中就复用 KV，不重算。只有完整 block 能复用，且前缀必须从第 0 个 token 开始完全相同；中间改一个 token，后面的 block 全部失效。

它省的是 **prefill 计算**，不是 decode：TTFT 下降，output tok/s 基本不变，每 token 的 KV 仍是 144KiB。缓存和运行中的请求共用 KV 池，显存紧张时会被驱逐。

D2 用 `--random-prefix-len 512` 造一段所有请求共享的 512-token 前缀，总输入仍是 1024。命中率按 token 计，所以 `prefix-on` 稳态大约 **50%**（512/1024），不是 100%；首波请求会 miss。

### Q5：AWQ 量化后的“精度”是多少？

要分两个层面：

**数值位宽**：`Qwen/Qwen3-8B-AWQ` 是 **W4A16**——权重 4-bit（`bits=4, group_size=128, zero_point=true, gemm`），激活和 KV cache 仍是 FP16。文件 5.7GB 而不是理论 4GB，是因为 embedding/lm_head 保留 BF16（各约 1.2GB），再加 scale/zero。

**模型质量**：没有固定值。Qwen 官方模型卡给的 bf16 vs AWQ-int4（厂商数字，不是我们这台机器的测量）：

| 模式 | Benchmark | bf16 | AWQ-int4 | 差值 |
|---|---|---|---|---|
| Thinking | LiveBench 2024-11-25 | 67.1 | 65.5 | −1.6 |
| Thinking | GPQA | 62.0 | 59.0 | −3.0 |
| Thinking | MMLU-Redux | 87.5 | 86.4 | −1.1 |
| Thinking | AIME24 | 76.0 | 71.3 | −4.7 |
| Non-Thinking | LiveBench 2024-11-25 | 53.5 | 48.9 | −4.6 |
| Non-Thinking | GPQA | 39.3 | 35.9 | −3.4 |
| Non-Thinking | MMLU-Redux | 79.5 | 79.1 | −0.4 |

合理预期是 1–5 个点，随任务而变。D2 的 50 条 GSM8K 只是 smoke test：n=50 时单个比例的 95% CI 约 ±11 个点，分辨不了 1–2 个点；报告写原始命中数（如 43/50 vs 44/50），不要写“只掉 1.2 个点”。

**容量**：AWQ 权重 5.7GB、FP16 16.4GB，差 10.7GB ≈ 7.2 万 token 的 KV；D2 控制组的 AWQ KV 是 91,648 token（D1 是 96,256），所以 FP16 大约只剩 1.9 万。c=16 × 1280 = 20,480 已经压到 FP16 的 KV 上限，因此 AWQ vs FP16 的主对比放 c=8，c=16 只作 KV 容量观察（看抢占）。

### Q6：TPOT 和 ITL 有什么区别？

单条请求内，`mean(ITL) = TPOT`；差别在聚合层级：ITL 是 token 级（N×255 个样本），TPOT 是请求级（N 个样本）。ITL 保留尖峰，TPOT 把尖峰平均掉。查抖动看 ITL，算 SLO/容量看 TPOT；`--goodput tpot:100` 用 per-request TPOT，是偏乐观的口径。D1 的实测对比和复算脚本在 `d1-vllm-baseline-runbook.md` §1.1。

### Q7：为什么一定要当天控制组？

host 噪声、功耗墙、邻居、驱动/clock 都可能变；D1 的数字只作参考。跨 host / power limit 的数字不能放进同一张表，`power_limit` 已写进每条 JSON 的 metadata。一次只动一个变量，同一对比对内的 n 必须一致。

### Q8：并发数、batch size、`max-num-batched-tokens` 有什么区别？

一句话：**并发数是“有多少请求在飞”，batch size 是“一次 forward 里有多少序列”，`max-num-batched-tokens` 是“一次 forward 里最多多少 token”。**

| 概念 | 层级 | 定义 | 谁控制 | D2 取值 |
|---|---|---|---|---|
| 并发数 `c` | 客户端 / 负载 | 同时在飞的请求数，包含排队、prefill、decode | bench `--max-concurrency` | 1/4/8/16/64 |
| batch size（序列） | 服务端调度 | 一次 forward 调度的序列数 | `--max-num-seqs` 是上限 | 64（控制组） |
| `max-num-batched-tokens` | 服务端调度 | 一次 forward 的 token 总预算，prefill+decode 共用 | CLI flag | 2048；bt512=512 |

关键：**`c=64` 不等于 64 条序列在同一个 forward 里算。**

- `c=64`、`max-num-seqs=16`：64 条在飞，服务端只 admit 16 条，48 条排队；decode 一步是 16 条 × 1 token = 16 token，离 2048 的 token 预算很远。这时瓶颈是序列数，不是 token 预算。
- `c=16`、`max-num-seqs=64`、一条新请求 prefill 1024 token、15 条在 decode：一步是 1024 + 15 = 1039 token，16 条序列。token 预算 2048 没打满，但这一步要算 1039 个 token，decode 要等它。
- `c=1`：只有 1 条序列，但第一步 prefill 就是 1024 token；之后每步 1 token。**序列 batch size = 1，token batch size 却是 1024。**

为什么 vLLM 不用一个固定的 “batch size”：训练时序列等长、阶段单一，batch size 是一个数；serving 时序列长度不同、prefill 和 decode 混在一起、prefill 还能分块，所以用两个上限分别控制“序列数”和“token 数”。

别把 lm-eval 的 `--batch_size 8` 当成 vLLM 的 batch：那是客户端一次发 8 条请求，服务端仍按 `max-num-seqs` / `max-num-batched-tokens` 调度。

### Q9：`max-num-batched-tokens` 和 `max-model-len` 有什么区别？

一句话：**`max-model-len` 管“一条请求最长能有多长”，`max-num-batched-tokens` 管“一步最多算多少 token”。** 一个是空间/上下文上限，一个是时间/每步计算上限。

| | `max-model-len` | `max-num-batched-tokens` |
|---|---|---|
| 限制对象 | 单条请求的 prompt + output 长度 | 一次 forward 所有序列的 token 总数 |
| 维度 | 空间 / 上下文 | 时间 / 每步计算 |
| 默认 | 模型 config 的 `max_position_embeddings`（Qwen3-8B 是 40960），我们设 8192 | 2048 |
| 影响 | 单请求能否被接受、单请求 KV 上限 | 每步 prefill/decode 多少、ITL/TTFT/吞吐 |
| 调小 | 拒绝更长请求；每 token KV 不变 | 步长变小、ITL 更稳、吞吐下降、TTFT 上升 |
| 调大 | 接受更长请求；单请求 KV 上限变大 | 步长变大、吞吐上升、ITL 尾部变差 |
| 与 chunking | 长于 budget 的 prompt 需要分块 | 预算小于 prompt 时触发分块 |

关键：

- `max-model-len` **不预分配** KV；KV 块按需分配，总池由显存决定。它只限制单条序列最多能长到多少。8192 token × 144KiB = **1.125GiB**，是一条 8k 请求的 KV 上限；40960 token 则要 **5.6GiB**。
- `max-num-batched-tokens` **不限制单条请求长度**。`max-model-len=8192`、budget=512 是合法的（chunking on）：一条 8192-token prompt 会被拆成 16 个 prefill step，只是 TTFT 变长。
- 反过来，`max-model-len=2048`、budget=8192 也合法：单条请求最多 2048 token，但一步可以同时 prefill 多条短请求。
- 只有关掉 chunked prefill 时，才有 `budget >= max_model_len` 的硬约束：一条 prefill 必须整体塞进一个 step。D2 的 `control-2k` / `chunk-off` 就是为这个约束设计的。

图示：

```text
max_model_len = 8192        一条请求最多 8192 token
        ┌──────────────────────────────────────────────┐
req A   │ prompt 1024 + output 256 = 1280              │
        └──────────────────────────────────────────────┘

max_num_batched_tokens = 2048   一步最多 2048 token
step 1  [req A prefill 1024][req B prefill 1024]  = 2048
step 2  [A decode 1][B decode 1][C prefill 1024]   = 1026
```

常见误解：

- “`max-model-len` 是 batch size” → 不是，它是单条序列长度。
- “`max-num-batched-tokens` 是一条请求的最大长度” → 不是，它是一步的总 token 预算。
- “调小 `max-model-len` 会让 KV 每 token 变小” → 不会，KV/token 由模型结构和 dtype 决定（Qwen3-8B FP16 是 144KiB）。
- “`max-model-len` 一定要 ≥ `max-num-batched-tokens`” → 反了；只有 chunking off 时要求 budget ≥ max_model_len。

### Q10：lm-eval 的 `--batch_size 8` 是 8 条 vLLM 序列吗？

不是。`--batch_size` 是 **lm-eval 客户端的评估 batch**，不是 vLLM 的 `max-num-seqs`，也不保证 8 条序列在同一个 forward 里。

对 `local-completions`：

- `--batch_size 8` 会把 8 条 prompt 放进**一个 HTTP 请求**的 `prompt` 数组（OpenAI completions 支持 list）；
- vLLM 的 OpenAI 前端把它展开成 8 条独立序列，再按自己的 `max-num-seqs` / `max-num-batched-tokens` / KV 调度；
- `--num_concurrent 8` 允许最多 8 个这样的 HTTP 请求同时在飞，所以客户端最多可能有 **64 条 prompt** 在途；
- 服务端实际同时跑多少，看日志的 `Running` / `Waiting`，不是看 `--batch_size`。

```text
lm-eval: batch_size=8, num_concurrent=8
  HTTP req 1: [p1..p8]    ─┐
  HTTP req 2: [p9..p16]   ─┼─ 最多 8 个请求在飞
  ...                      │
  HTTP req 8: [p57..p64]  ─┘
            ↓
vLLM OpenAI 前端：最多 64 条独立序列
            ↓
scheduler：max_num_seqs=64, budget=2048
  → 5-shot prompt 约 1.2k token，一个 prefill step 只装得下 1–2 条
```

所以：`batch_size 8` ≈ “每个 HTTP 请求 8 条 prompt”，`num_concurrent 8` ≈ “8 个请求并发”；两者相乘是**客户端在途上限**，最终 batch 仍由 vLLM 决定。`local-chat-completions` 不支持 batched chat，会把 `batch_size` 强制改成 1。

### Q11：`--num-prompts` 是什么？和并发数、batch size 有什么区别？

`--num-prompts N` = **这一轮总共发多少条请求**，也就是样本量 n。它不是并发数，不是 batch size，不是输出长度。

- 闭路压测：客户端最多保持 `--max-concurrency C` 条在飞；完成一条补一条，直到总共发完 N 条。
- 如果 `N < C`，永远到不了 C 并发；N 至少要是 C 的几倍，稳态才占主导。
- N 决定运行时长和百分位的分辨率：
  - c=16、n=200 约 12.5 波，稳态够；P99 只有第 2 慢的请求，仍然粗。
  - c=64、n=300 约 4.7 波，ramp-up 占比更大；吞吐和 P99 要注明。
  - per-request P99.9 在 n=200 时基本就是最慢的一条，不要当稳定百分位；ITL P99.9 有 N×255 个 gap，才有意义。
- 我们的时间估算（D1 实测，n=500/1000 线性折算）：

| 配置 | n | 预计时长 |
|---|---|---|
| c=16 | 200 | ~7.6 min |
| c=64 | 300 | ~9.6 min |
| c=8 | 100 | ~5 min |

- 同一对比对内 n 必须一致；跨并发比较时 n 不同会影响 ramp-up 占比，报告里要写。
- `--num-prompts` 不是 `--limit`（lm-eval 的 50 条样本），也不是 `--max-num-seqs`；它只是客户端的样本量。

### Q12：`d2_bench mns16 64 300 0` 是“发 64 条、处理完再发下一批 64 条”吗？

不是。这是**静态批处理**的直觉，vLLM 用的是 **continuous batching**（连续批处理）：

- 客户端 `--max-concurrency 64` 是一个**滑动窗口**：保持最多 64 条在飞；任意一条完成，就立刻从剩下的请求里补一条，不会等 64 条全部完成。
- 服务端 `--max-num-seqs 16` 是另一个上限：最多 16 条 running，其余在 waiting 队列。
- 所以典型状态是：客户端 64 条在飞；服务端 16 条 running + 约 48 条 waiting；每完成一条，waiting 里补一条，客户端再补一条。
- 直到 300 条全部发完，客户端停止补发，窗口从 64 逐渐排空。

实际流动：

```text
t0:  客户端发 64 条
     服务端：16 条 running + 48 条 waiting

t1:  1 条完成
     服务端：从 waiting 补 1 条 → 仍 16 running + 约 48 waiting
     客户端：收到 1 个响应 → 从剩下的请求补 1 条 → 仍 64 在飞

t2:  又完成 1 条 → 同样补位
     ...
```

| 时刻 | 客户端已发 | 客户端在飞 | 服务端 running | 服务端 waiting |
|---|---|---|---|---|
| t0 | 64 | 64 | 16 | 48 |
| t1 | 65 | 64 | 16 | 48 |
| ... | ... | ... | ... | ... |
| 结束前 | 300 | 64→0 | 16→0 | 48→0 |

三个数分别管什么：

| 数 | 层级 | 作用 |
|---|---|---|
| `--max-concurrency 64` | 客户端 | 最多 64 条 HTTP 请求在飞；完成一条补一条 |
| `--max-num-seqs 16` | 服务端 | 最多 16 条序列 running；其余在 waiting 队列 |
| `--num-prompts 300` | 客户端 | 总共发 300 条，发完就不再补 |

和静态批处理的区别：

| | 静态批处理 | continuous batching |
|---|---|---|
| 批次边界 | 64 条一批，等最慢的完成 | 每个 iteration 重新组 batch |
| 新请求 | 等整批结束 | 完成一条就补一条 |
| GPU 利用 | 尾部会空转 | 持续填满 |
| 尾延迟 | 被最慢请求拖住 | 只影响队列，不阻塞整批 |

服务端日志里直接看 `Running: 16 reqs, Waiting: 48 reqs`；这就是这个状态。`mns16` 这个 tag 只表示服务是用 `--max-num-seqs 16` 起的，bench 命令本身不会改服务端配置。

### Q13：4.3b 里的 “~2.3s 停顿” 是什么指标？当时是什么条件？

**指标是 ITL，不是 TPOT/TTFT。** D1 c=64 的 ITL P99 = 2,345ms、P99.9 = 2,367ms、max 2,387ms；这是 1000 条请求 × 255 个 gap = 255,000 个样本展平后的尾部。

| D1 跑 | c | n | ITL P99 | ITL P99.9 | TPOT P95 | >1s gaps/req 中位数 |
|---|---|---|---|---|---|---|
| 主跑 | 64 | 1000 | 2,345ms | 2,367ms | 470ms | 34 |
| 主跑 | 16 | 500 | 1,082ms | 2,006ms | 137ms | 13 |
| 诊断 | 16 | 200 | 1,832ms | 1,985ms | 134ms | 8 |

运行条件：40W L4、Qwen3-8B-AWQ（W4A16）、vLLM 0.34.0、`max-model-len 8192`、`max-num-seqs 64`、chunked prefill on、prefix caching on、random 1024 in / 256 out、`--ignore-eos`、`--temperature 0`；主跑 c=64/n=1000，诊断 c=16/n=200 且开了 `--enable-per-request-metrics`。ITL 数组来自客户端 `--save-detailed` 的 JSON。

为什么不是 TPOT：同一轮 c=64 的 TPOT P95 只有 470ms，因为每条请求的 255 个 gap 里中位数有 34 个超过 1s，平均后变成 453ms 的 TPOT P50。**ITL 看的是单个 gap，TPOT 看的是整条请求的平均。**

这不是“某一条请求总共卡了 2.3s”，而是“所有 decode gap 里最慢的 1% 约 2.3s”。它说明 decode 不是匀速的，但**不能单凭这个数字证明是 prefill 造成的**；4.3b 的 `bt512` 就是把这个假设变成可检验的实验：如果压小每步 prefill 预算后 ITL 尾部明显下降，假设才成立。

### Q14：把 `max-num-batched-tokens` 从 2048 降到 512，为什么会减小 ITL？D1 不是没开 chunked prefill 吗？

**先纠正：D1 开了 chunked prefill。** 启动日志里是 `enable_prefix_caching=True, enable_chunked_prefill=True`；v0.34 默认就是开的。问题不是“没开”，而是“开了但没触发”。

chunked prefill 只在“剩余预算装不下这段 prefill”时才切。D1 的请求是 1024-token prompt，预算 2048；16 条 decode 只占 16 token，还剩 2032，足够把 1024 一次算完。所以：

- `max-num-batched-tokens=2048`：一步 ≈ 1024 prefill + 16 decode = 1040 token；prefill 占主导，这一步在 40W L4 上约 1–2s；16 条 decode 在这段时间内出不了下一个 token → ITL gap 变成秒级。
- `max-num-batched-tokens=512`：1024 prompt 必须拆成约 2–3 个 chunk（每步扣掉 16 个 decode token，实际 prefill 约 496）；每个 step 里 decode 仍能各出 1 个 token，但只需等这个 ~496-token chunk 算完，不用等整段 1024。单步 prefill 工作量减半，ITL 尾部下降，但 TTFT 可能上升（prefill 分更多步），吞吐也可能因步数变多而略降。

> **一句话确认**：是的。当 scheduler 把一段 1024-token prefill 和正在 decode 的序列放进同一个 step 时，这个 step 的耗时由 prefill 主导；所有 decode 序列的下一个 token 都要等它算完，所以它们这一轮的 ITL gap 会变成 ~1–2s。2.3s 是 c=64 的 P99 尾部，不是每个 step、每条请求都这样；大多数 decode-only step 仍然很快。
>
> 注意：被延迟的是**同一 step 里已经在 decode 的序列**；发起 prefill 的那条请求此时还在 prefill，它的首 token 延迟算在 TTFT，不是 ITL。

用 step 画出来：

```text
step t:   [1024 prefill][16 decode]  → 这一步 1–2s
          → 16 条 decode 的下一 token 都要等它算完

step t+1: [16 decode]                → ~80ms
          → ITL 恢复正常
```

c=16 的 ITL 分布（D1 主跑，n=500，255 gap/请求）：

| P50 | P95 | P99 | P99.9 | >1s gaps/req |
|---|---|---|---|---|
| 80ms | 83ms | 1,082ms | 2,006ms | 13 |

大多数 gap 在 80ms；只有含 prefill 的 step 把尾部拉到 1–2s。

所以 `bt512` 不是“打开 chunking”，而是**把预算压到 prompt 以下，强制 chunking 发生**。

注意：它降的是 **ITL 尾部**（P99/P99.9、`>1s gaps`），不是 P50；decode-only step 仍然是 ~80ms。不要期待中位数变化。

为什么 2.3s 不一定是“2048 个 prefill token”：2048 是上限，不是每步实际值。c=16 时一步大约是 1024 prefill + 15–16 decode；c=64 时是 1024 + 63–64 decode。2.3s 的尾部更像是“1024-token prefill 在这张 40W 卡上的耗时”，或者偶尔两步 prefill 挤在一起。具体每步多少 token，vLLM 默认不打印；`bt512` 就是用来验证这个因果关系的。

支持这个解释的证据：

- 四轮抢占都是 0，排除 KV 抢占；
- 排队延迟体现在 TTFT，不是 ITL；
- ~2s 的 gap 量级和 1024-token prefill 的耗时对得上。

但这不是已证实的因果：D1 没有打印每步 token 组成，`bt512` 才是对照实验。

一句话类比：prefill 是“大货车”，decode 是“小包裹”。预算 2048 时，大货车一次装完，小包裹要等它卸完；预算 512 时，大货车分几趟，小包裹可以在每趟之间走。总工作量差不多，但小包裹的单次等待变短。

### Q15：为什么减小 `max-num-seqs` 会降低 TPOT？mns 不是只管排队吗？

不是只管排队。`max-num-seqs` 同时限制两件事：

1. **admission**：最多多少条序列进入 running；
2. **每步 decode batch 的序列数**：一次 forward 最多算多少条序列的下一个 token。

TPOT 是“这条请求每个输出 token 的平均时间”，在 decode 阶段约等于 **一步 forward 的耗时**。一步里 64 条序列各出 1 token，和 16 条序列各出 1 token，计算量、attention/KV 读取、MLP 都不同：

```text
mns=64: 一步算 64 条序列 → step 约 419ms → TPOT P50 419ms
mns=32: 一步算 32 条序列 → step 约 215ms → TPOT P50 215ms
mns=16: 一步算 16 条序列 → step 约 126ms → TPOT P50 126ms
```

D2 实测（c=64，n=300）：

| mns | Running | TPOT P50 | TPOT P95 | output tok/s | mns / TPOT P50 |
|---|---|---|---|---|---|
| 64 | 64 | 419ms | 426ms | 143.1 | 152.7 |
| 32 | 32 | 215ms | 226ms | 137.5 | 149.2 |
| 16 | 16 | 126ms | 130ms | 119.8 | 126.8 |

`output tok/s ≈ mns / TPOT`（实测比估算低 5–8%，差在 prefill、ramp-up、调度开销）。所以不是“mns 和 TPOT 没关系”，而是：

> **mns 决定一步里有多少条序列；TPOT 就是这一步的耗时摊到每个 token 上。**

为什么 64 条和 16 条差这么多：这张卡是 40W 限功耗，GPU 不能靠升频把多出来的 attention/MLP/KV 读取藏掉；每多一条序列，这一步的 attention 和 KV 读取就多一份，step time 随 batch 上升（近似线性到次线性）。权重只读一次，所以吞吐仍然随 batch 上升（64 条 143 tok/s > 16 条 120 tok/s），但每条 token 的延迟变差——这是典型的 throughput-latency trade-off。

**什么时候 mns 不影响 TPOT**：客户端并发 c ≤ mns 时，running 最多只有 c 条，mns=64 和 mns=16 的 decode batch 一样大。4.2 用 c=64 就是为了让 mns 真正绑定；c=8 时改 mns 不会有 TPOT 差异。

**mns 不能解决什么**：它降低的是平均 decode step（TPOT），但 prefill 造成的 ~1.8s ITL 尖峰还在（mns16 的 ITL P99.9 仍有 1,811ms）。那部分要靠 4.3b 的 budget 实验。

### Q16：4.3 里 `d2_bench chunk-off 16 200 0` 的 `0` 是“prefill=0”吗？

不是。最后一个位置参数是 **PREFIX**（共享前缀长度），0 表示“不构造共享前缀”，和 prefill 无关。

- 每条请求仍然是 `--random-input-len 1024` + `--random-output-len 256`；1024 个输入 token 必须做 prefill，才能生成首 token。
- 如果 `PREFIX=512`，则 random input = 512，前缀 512，总输入还是 1024；4.4 才用这个。
- `PREFIX=0` 只是说“没有可复用的相同前缀”，不是“没有 prefill”。

证据：chunk-off 的 `request_throughput = 0.470 req/s`，每条 1024 input → 0.470 × 1024 ≈ **481 input tok/s**；加 output 120.4 = **601.7**，正好等于 `total_token_throughput = 601.9`。如果 prefill=0，total 应该只有约 120 tok/s。

如果你在日志里看到 `Avg prompt throughput: 0.0 tokens/s`，那是 benchmark 结束后的空闲 tail；跑的时候 prompt throughput 是非零的。

### Q17：1024-token prompt 在 2048 预算下，为什么 chunked prefill on/off 还会不同？

因为 chunking 影响的不只是“单条 prompt 是否被切开”，还影响“这一步能不能用**别的请求的部分 prefill**填满剩余预算”。

- **chunk on**：16 条 decode 占 16 token，剩 2032；一条 1024 prompt 算完后还剩 1008，scheduler 可以把**第二条请求的 1008 个 prefill token**也塞进同一步 → 一步约 2032 prefill，decode 等 ~1.8s。
- **chunk off**：第二条 prefill 必须整体调度，1008 < 1024，装不下 → 只能等下一步；这一步最多一条 1024 prompt → decode 等 ~1s。

所以差异来自“一步里塞了几个 prefill”，不是“prefill 有没有发生”。4.3 实测 ITL P99.9 1,811→993ms，`>1s gap` 190/200→0/200，就是这个机制。

### Q18：FP16 日志说 `Maximum concurrency ... 2.31x`，为什么还能跑 c=8？

因为 2.31 的分母是 `max_model_len=8192`，不是我们每条请求的 1,280。

- `18,944 / 8,192 = 2.31`：假设每条请求都吃满 8,192 token 上下文；
- 我们的请求是 `1,024 input + 256 output = 1,280`：`18,944 / 1,280 = 14.8`；
- c=8 需要 `8 × 1,280 = 10,240 < 18,944`，所以 8 条能同时跑。

KV 是按需分配的：请求开始时只有 1,024 prompt 的 KV，生成到 256 才到 1,280；它不会一上来就占 8,192。`max-model-len` 是上限，不是预分配。

真正同时能跑多少条，是三个上限的最小值：

```text
min(client c, max_num_seqs, KV_pool / per_request_tokens)

c=8:  min(8,  64, 14.8) = 8
c=16: min(16, 64, 14.8) = 14.8 → 至少一条排队
```
