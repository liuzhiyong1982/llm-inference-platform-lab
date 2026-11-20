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

## 1. 租机器 + 前置检查（30 分钟）

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
| Max CUDA | ≥ 镜像的 `CUDA_VERSION`（`v0.34.0` 是 **13.0.2**，所以填 13.0） | Max CUDA 由 host driver 决定；镜像自带 CUDA runtime，runtime 不能高于这个上限 |
| Inet down | ≥ 500 Mbps | 要下约 5GB 权重；太慢会拖掉半小时 |
| Max Duration | > 6h | 别租 1 小时就到期的 offer |
| 价格 | 记录实际 $/h | 同一张 L4 从 $0.10 到 $0.45 都有，不要按固定价算成本 |

### 1.1 装 CLI、配 API key

网页 UI 的默认列表按热门卡排序，满屏是 RTX 4090/5090；**L4 不属于 RTX 分类**，它是 Ada 数据中心卡。UI 的 GPU 筛选框要直接输入 `L4`，而且默认搜索带 `verified=true`，会把大量 L4 host 藏掉。所以用 CLI 更可靠。

```bash
pip install -q vastai
vastai --version          # 2026-11 实测 1.11.2
```

> 安装时出现 `~rllib3` / `~equests` 临时目录删除失败、`conda-libmamba-solver requires conda>=24.11` 的报错都可以忽略——前者是 pip 残留，后者是环境里既有的 conda 版本冲突，和 vastai 无关。只要 `vastai --version` 有输出就算成功。

API key 在 <https://cloud.vast.ai/manage-keys/> 生成，然后：

```bash
vastai set api-key <你的key>
```

key 存在 `~/.config/vastai/vast_api_key`，**不要提交进 git，也不要贴到聊天/issue 里**。

### 1.2 搜 L4

```bash
vastai search offers -n \
  'gpu_name=L4 num_gpus=1 rentable=true reliability>=0.98 cuda_vers>=13.0 inet_down>=500 disk_space>=40 duration>0.25' \
  -o 'dph' --storage 40 --limit 20
```

每个字段对应上面的门槛：

| 参数 | 含义 |
|---|---|
| `-n` | 去掉默认 query；默认带 `verified=true`，会把 unverified 的 L4 host 过滤掉 |
| `gpu_name=L4` | 精确匹配 L4；不要写成 `L40S` 或 `RTX_4090` |
| `num_gpus=1` | 单卡；D1 只测单卡 |
| `reliability>=0.98` | host 历史可用率 |
| `cuda_vers>=13.0` | offer 卡上的 **Max CUDA**，由 host driver 推导（等于 `nvidia-smi` 右上角那行），不是装的 toolkit 版本 |
| `driver_version>=580` | 可选；只有要规避已知 driver bug 或做精确复现时才加，平时用 `cuda_vers` 就够 |
| `inet_down>=500` | Mbps，下载权重用 |
| `disk_space>=40` | host 可用磁盘 GB；实际分配仍看 `--disk` |
| `duration>0.25` | 单位是**天**，`0.25` = 6 小时 |
| `-o 'dph'` | 按总价升序；字段加 `-` 后缀是降序 |
| `--storage 40` | 让 `dph_total` 把 40GB 盘的小时费算进去 |

> **GPU / driver / CUDA / 镜像的关系**：容器里的 vLLM 自带 CUDA runtime 和 PyTorch，host 只提供 driver。`cuda_vers`（Max CUDA）是 driver 能支持的最高 runtime 版本，所以它是「能不能跑」的天花板，不是镜像里装的版本。再往上追一层，GPU 架构决定的是 driver 的**下限**（driver 必须认识这张卡）和镜像必须包含的 arch（L4 = sm_89），不是 driver 的上限；反过来老卡会被新 driver 分支逐步淘汰，那才是上限。
>
> 所以完整约束是两条，缺一不可：
>
> 1. 镜像的 `CUDA_VERSION` ≤ driver 的 Max CUDA，且**不跨大版本**（CUDA 11 起有 minor version compatibility，12.x runtime 能跑在支持 12.0 的 driver 上）；
> 2. GPU 的 compute capability 在镜像的编译列表里（`TORCH_CUDA_ARCH_LIST`），否则会报 `no kernel image is available`，这跟 CUDA 版本无关。`v0.34.0` 的列表是 `7.5 8.0 8.6 8.9 9.0 10.0 12.0`，L4 的 8.9 在里面。
>
> `v0.34.0` 镜像里的 `CUDA_VERSION=13.0.2` 是**镜像内 CUDA runtime/toolkit 的版本**（不是 driver；`NV_CUDA_CUDART_VERSION=13.0.96-1` 是其中 cudart 包的版本号，编号规则不同），`NVIDIA_REQUIRE_CUDA=cuda>=13.0` 是容器启动时由 runtime 校验的约束。所以 host 的 Max CUDA 必须 ≥ 13.0；driver 的具体版本号只在排查已知 bug 时才需要看。镜像已经拉到本地后可以这样核对：
>
> ```bash
> docker image inspect vllm/vllm-openai:v0.34.0 \
>   --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E 'CUDA_VERSION|NVIDIA_REQUIRE_CUDA'
> ```

**例：加州那台 `59651491` 为什么能跑**

| 层 | 值 | 从哪看 |
|---|---|---|
| GPU | L4，sm_89 | `nvidia-smi` 的型号；compute capability 查 NVIDIA 表 |
| driver 的 Max CUDA | 13.2 | offer 卡的 Max CUDA；进容器后是 `nvidia-smi` 右上角 |
| 镜像 CUDA runtime | 13.0.2 | `CUDA_VERSION` |
| torch 编译用的 CUDA | 13.0 | `torch.version.cuda` |

判断：`13.0.2 ≤ 13.2`、同为 13 大版本，且 sm_89 在 `TORCH_CUDA_ARCH_LIST` 里 → 能跑。这里 `13.0.2` 和 `13.2` 不是同一个东西：前者是镜像里的 runtime 版本，后者是 host driver 支持的上限；`.0.2` 是 toolkit 的 patch 号，`13.0.96-1` 则是 cudart 包的编号，不要混着比。

反例：同一台 L4，如果 driver 只到 Max CUDA **12.4**，镜像还是 `v0.34.0`（runtime 13.0.2）→ 13.0 > 12.4 且跨大版本，容器启动时会被 `NVIDIA_REQUIRE_CUDA=cuda>=13.0` 拦下，或者加载时报 `CUDA driver version is insufficient for CUDA runtime version`。处置：换 `cuda_vers>=13.0` 的 host，或换 cu124 的镜像 tag；**不要在容器里 `pip install` 降级 torch**。

2026-11-20 的 L4 行情快照（只用于判断量级，**租之前必须重新跑上面的命令**）：

| offer id | 地区 | $/h | reliability | inet down | Max CUDA | 可用磁盘 | 最长天数 |
|---|---|---|---|---|---|---|---|
| 49589443 | Hong Kong | 0.104 | 98.6% | 106 Mbps | 13.4 | 286 GB | 29 |
| 58330911 | Japan | 0.104 | 98.0% | 61 Mbps | 13.4 | 302 GB | 19 |
| **59651491** | **California** | **0.252** | **98.9%** | **768 Mbps** | **13.2** | **1003 GB** | **17** |
| 57462232 | Texas | 0.350 | 98.5% | 912 Mbps | 13.2 | 427 GB | 15 |
| 57478835 | Arizona | 0.350 | 98.5% | 912 Mbps | 13.2 | 450 GB | 15 |
| 58034037 | Utah | 0.431 | 98.5% | 938 Mbps | 13.2 | 236 GB | 26 |

香港/日本那两台 $0.104 的因为 `inet_down` 只有 61–106 Mbps，会被 `inet_down>=500` 过滤掉——省下的几毛钱不值得拿下载时间和邻居噪声去换。

### 1.3 创建实例

```bash
vastai create instance <offer_id> \
  --image vllm/vllm-openai:v0.34.0 \
  --disk 40 \
  --ssh \
  --env '-p 8000:8000' \
  --label d1-l4-baseline
```

- **默认就是 on-demand**；只有加 `--bid_price` 才会变成 interruptible。基线跑绝对不要加。
- `--disk 40`：容器盘创建后不能扩容，一开始就给够。
- `--ssh`：以 SSH 方式启动，避开 `vllm/vllm-openai` 默认 entrypoint 无参数直接退出、容器反复重启的问题。仍然反复重启时再加 `--entrypoint /bin/bash`。
- `--env '-p 8000:8000'`：端口映射；只在实例内压测可以不写，但写了方便从本地 smoke test。
- 镜像用固定 tag，不要 `latest`：`latest` 指向 nightly，flag 会漂、基线不可复现。2026-11 的 stable 是 `v0.34.0`；如果 `vllm bench serve --help` 缺 1.5 节要查的 flag，再换 tag。

### 1.4 连上实例

```bash
vastai show instances          # 看 status 是否 running
vastai ssh-url <instance_id>   # 给出 ssh 命令/端口
vastai scp-url <instance_id>   # scp 用的 host:port
vastai logs <instance_id>      # 起不来时先看这个
```

### 1.5 进容器后的 preflight

进容器后先跑：

```bash
nvidia-smi
df -h /workspace
python -c "import vllm; print(vllm.__version__)"
python -c "import torch; print('torch', torch.__version__, 'cu', torch.version.cuda)"
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

> 版本不匹配是这一步最常见的坑：driver 太旧会在加载模型时报 CUDA error。`nvidia-smi` 右上角的 CUDA Version 就是 offer 卡上的 **Max CUDA**；`v0.34.0` 镜像要求 ≥ **13.0**（镜像里是 13.0.2）。租之前就核对，别等进容器才发现。

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
| 网页 UI 只看到 4090/5090，找不到 L4 | L4 是数据中心卡，不在 RTX 分类；默认搜索还带 `verified=true` | GPU 筛选框直接输入 `L4`；或用 1.2 节的 CLI 命令（`-n` 去掉默认条件） |
| `vastai: command not found` | 没装，或 conda 的 bin 不在 PATH | `pip install vastai`；确认 `which vastai`；临时可用 `python -m vastai` |
| 装 vastai 报 `~rllib3` / `conda-libmamba-solver` 冲突 | pip 残留 + 既有 conda 版本冲突，与 vastai 无关 | 忽略；`vastai --version` 有输出即成功 |
| `401` / `Invalid API key` | key 没设或已失效 | 重新生成后 `vastai set api-key <key>` |
| `search offers` 返回空 | 门槛太严，或 `duration` 单位写错（是天，不是小时） | 逐条放宽 `inet_down`/`reliability`；`duration>0.25` 表示 6 小时 |
| `torch.OutOfMemoryError` / 启动就 OOM | `gpu-memory-utilization` 太高，或 `max-model-len` 太大 | 降到 0.85 → 0.80；`--max-model-len 4096` |
| `CUDA error: no kernel image is available` | 镜像/vLLM 的 CUDA 与 driver 不匹配 | 换匹配的镜像 tag；先 `nvidia-smi` 看 driver 支持的 CUDA |
| `CUDA driver version is insufficient for CUDA runtime version` | host 的 Max CUDA 低于镜像的 `CUDA_VERSION` | destroy 换 host，或换更低 CUDA 的镜像 tag；**不要在容器里装 driver** |
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

**结果必须拉回本地，不能只留在实例盘。** 先拿连接信息，再在本地机器执行：

```bash
vastai scp-url <instance_id>    # 输出 ssh/scp 用的 host 和端口，以它为准
```

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

2026-11-20 实测：同时满足 reliability ≥ 98%、inet down ≥ 500 Mbps 的 L4 单卡最低 **$0.252/h**（加州，`--storage 40` 后约 $0.26–0.27/h），所以 4h 实际约 **$1.1**，比按 $0.35/h 估的还低。

按 $0.35/h × 4h ≈ **$1.4/天**；加诊断/重复跑约 **$2**。$15 预算够 D1–D2，但**别让实例 Stop 着放一个月**——40GB 存储挂一个月的费用可能超过重新下模型。

## 参考

- vLLM Benchmark CLI：<https://docs.vllm.ai/en/latest/benchmarking/cli/>
- vLLM serve CLI：<https://docs.vllm.ai/en/latest/cli/serve/>
- Qwen3-8B-AWQ 模型卡：<https://huggingface.co/Qwen/Qwen3-8B-AWQ>
- Vast.ai 计费：<https://docs.vast.ai/guides/instances/pricing>
- Vast.ai 找机器/租实例：<https://docs.vast.ai/guides/instances/choosing/find-and-rent>
- Vast.ai `search offers` 参考：<https://docs.vast.ai/api-reference/search/search-offers>
- Vast.ai 存储类型：<https://docs.vast.ai/guides/instances/storage/types>
- vLLM 镜像 tag 列表：<https://hub.docker.com/r/vllm/vllm-openai/tags>
- Vast.ai 实例类型（on-demand vs interruptible）：<https://docs.vast.ai/guides/instances/choosing/instance-types>
