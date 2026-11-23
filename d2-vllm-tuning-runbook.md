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

> 默认 `max_num_batched_tokens` 是 2048。D1 看到的 ~2.3s decode 停顿，量级正好等于“一个调度步塞进 2048 个 prefill token”的耗时；`bt512` 把一步的 prefill 预算压到 512，是比 `chunk-off` 更直接的假设检验。`chunk-off` 则是另一个极端（整段 1024 一次算完），两者一起看能分清“停顿来自步长”还是“来自 prefill 与 decode 交错”。

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

### 4.3 chunked prefill off（固定 2048 预算，含对照）

v0.34 源码里有两条约束：

1. `--disable-chunked-prefill` 要求 `max_num_batched_tokens >= max_model_len`，否则启动直接 `ValueError`；
2. 不显式传 budget 时，EngineArgs 会自动把 budget 抬到 `max_model_len`（这里是 8192）。

所以“直接关 chunking”会同时把步长预算从 2048 改成 8192，两个变量一起动。要单变量，就把 `max-model-len` 和 budget 都钉在 2048，先跑一个 chunking 仍开着的对照：

> **先重启服务**：tmux A `Ctrl-C` 停掉当前服务，确认 `curl -sf http://127.0.0.1:8000/v1/models` 失败后再启动。

```bash
# 目的：#4 的同预算对照；除了 chunked prefill 开关，其他都与 chunk-off 相同
serve_awq control-2k --max-model-len 2048 --max-num-batched-tokens 2048
```

就绪后：

```bash
d2_bench control-2k 16 200 0    # TAG=control-2k；C=16 客户端并发；N=200 总请求；PREFIX=0 无前缀
```

再关：

> **先重启服务**：先停掉 `control-2k` 服务，确认端口空了再启动 `chunk-off`。

```bash
# 目的：同一 2048 预算下，关掉 prefill/decode 交错
serve_awq chunk-off --max-model-len 2048 --max-num-batched-tokens 2048 --disable-chunked-prefill
```

就绪后：

```bash
d2_bench chunk-off 16 200 0    # TAG=chunk-off；C=16 客户端并发；N=200 总请求；PREFIX=0 无前缀
```

> `max-model-len 2048` 对 1024+256 的请求够用；KV cache 总池由显存决定，不随 `max-model-len` 变小。

预期：1024-token prompt 在 2048 budget 下本来就能塞进一个 step，chunking 很少真的把单条 prompt 切开；所以 on/off 的差异可能很小。**这组回答的是“交错策略”，不是“步长”**。如果差异很大，先回看启动日志的 `max_num_batched_tokens`，很可能预算被抬到了 8192。

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

预期：如果 D1 的 ~2.3s 停顿来自“一个 step 塞进约 2048 个 prefill token”，这组应看到 ITL P99.9 和 `>1s gaps/req` 明显下降，代价是 TTFT P99 上升（同样多的 prefill 要拆成更多步）。若 ITL 不变，假设被否定，停顿另有来源。

### 4.4 prefix caching on/off（共享前缀）

先跑“缓存开 + 共享前缀”：

> **先重启服务**：tmux A `Ctrl-C` 停掉 `bt512` 服务，确认 `curl -sf http://127.0.0.1:8000/v1/models` 失败后再启动。

```bash
# 目的：默认 prefix caching 已开；这批请求共享 512-token 前缀
serve_awq prefix-on
```

就绪后：

```bash
d2_bench prefix-on 16 200 512    # TAG=prefix-on；C=16 客户端并发；N=200 总请求；PREFIX=512 共享前缀
```

再跑“缓存关 + 同样前缀”：

> **先重启服务**：先停掉 `prefix-on` 服务，确认端口空了再启动 `prefix-off`。

```bash
serve_awq prefix-off --disable-prefix-caching
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

### 4.5 AWQ vs FP16

**主对比用 c=8，不要直接 c=16。** AWQ 权重 5.7GB、FP16 16.4GB，差 10.7GB；按 144KiB/token 算，这 10.7GB 约等于 7.2 万 token 的 KV。D1 的 AWQ KV 是 91,648 token，所以 FP16 大约只剩 **1.9 万 token**，而 c=16 × 1280 token/请求 = 20,480，已经压到 KV 上限——TTFT 会被排队/KV 压力污染，不能把差异全算成量化。

AWQ 的 c=8 对照已经在 §4.1 用控制组服务跑过（`control-c8`），这里直接换 FP16：

> **先重启服务**：tmux A `Ctrl-C` 停掉 `prefix-off` 服务，确认 `curl -sf http://127.0.0.1:8000/v1/models` 失败后再启动 FP16。

```bash
# 目的：同一 served name，换 FP16 权重；先确认显存够，OOM 就降 max-model-len
serve_fp16 fp16-c8
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
serve_fp16 fp16-4k --max-model-len 4096
```

就绪后：

```bash
d2_bench fp16-4k 8 100 0    # TAG=fp16-4k；C=8 客户端并发；N=100 总请求；PREFIX=0 无前缀
```

> 读启动日志时记下 FP16 的 `GPU KV cache size`；它和 AWQ 的 91,648 对比，就是“量化多换来的容量”，这比单纯的 tok/s 更能解释 24GB 卡上的取舍。

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
| 0 | control-c16 | AWQ mns=64 | 16 | 200 | | | | | | | | | | |
| 0b | control-c8 | AWQ mns=64 | 8 | 100 | | | | | | | | | | |
| 1 | control-c64 | AWQ mns=64 | 64 | 300 | | | | | | | | | | |
| 2 | mns16 | mns=16 | 64 | 300 | | | | | | | | | | |
| 3 | mns32 | mns=32 | 64 | 300 | | | | | | | | | | |
| 4a | control-2k | 2k len + 2k budget | 16 | 200 | | | | | | | | | | |
| 4 | chunk-off | chunked off, 2k budget | 16 | 200 | | | | | | | | | | |
| 4b | bt512 | batch-tokens=512 | 16 | 200 | | | | | | | | | | |
| 5 | prefix-on | prefix on | 16 | 200 | | | | | | | | | | 命中率 __% |
| 6 | prefix-off | prefix off | 16 | 200 | | | | | | | | | | 命中率 0% |
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

一句话结论模板：

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

调大 budget：每步塞更多 token，吞吐上升，但单步变长、ITL 尾部变差；调小：ITL 更平滑，但步数变多、吞吐下降、长 prompt 的 TTFT 变差。D1 的 ~2.3s 停顿，量级等于一个 1024–2048 token 的 prefill step，所以 `bt512` 是直接检验。

### Q3：chunked prefill 是什么？

关闭时，一条 prefill 必须**整体**放进一个 step；它占满 step 时，所有正在 decode 的序列都得等。开启后，预算不够就把 prefill 拆成多个 chunk，和 decode 混在同一 step：decode 更平滑、GPU 利用率更高，但长 prompt 的 TTFT 可能变大。

v0.34 默认开启，关闭用 `--disable-chunked-prefill`。

两个容易误解的点：

1. **chunked prefill 不是强行切碎**。1024-token prompt 在 2048 预算下通常一次就能算完；只有预算不够（多条 prefill 竞争，或你把 budget 调小）时才切。所以 `chunk-off` 在 2048 预算下可能和 control 几乎没差异；`bt512` 才是“步长”实验。
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

**容量**：AWQ 权重 5.7GB、FP16 16.4GB，差 10.7GB ≈ 7.2 万 token 的 KV；D1 的 AWQ KV 是 91,648 token，所以 FP16 大约只剩 1.9 万。c=16 × 1280 = 20,480 已经压到 FP16 的 KV 上限，因此 AWQ vs FP16 的主对比放 c=8，c=16 只作 KV 容量观察（看抢占）。

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

时间线：

| 时刻 | 客户端已发 | 客户端在飞 | 服务端 running | 服务端 waiting |
|---|---|---|---|---|
| t0 | 64 | 64 | 16 | 48 |
| t1 | 65 | 64 | 16 | 48 |
| ... | ... | ... | ... | ... |
| 结束前 | 300 | 64→0 | 16→0 | 48→0 |

关键区别：

- **静态批处理**：64 条一批，等最慢的一条完成才发下一批；GPU 会有空洞，尾延迟差。
- **continuous batching**：每个 iteration 重新组 batch；完成的走、排队的进；没有“批”的屏障。

服务端日志里直接看 `Running: 16 reqs, Waiting: 48 reqs`；这就是这个状态。`mns16` 这个 tag 只表示服务是用 `--max-num-seqs 16` 起的，bench 命令本身不会改服务端配置。
