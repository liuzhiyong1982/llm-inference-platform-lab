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
# 安装 Vast.ai 的 CLI（只是本地 Python 包，不占 GPU、不产生费用）
pip install -q vastai

# 验证 CLI 可用；有版本号输出即成功，安装时的 pip/conda 警告可忽略
vastai --version          # 2026-11 实测 1.11.2
```

> 安装时出现 `~rllib3` / `~equests` 临时目录删除失败、`conda-libmamba-solver requires conda>=24.11` 的报错都可以忽略——前者是 pip 残留，后者是环境里既有的 conda 版本冲突，和 vastai 无关。只要 `vastai --version` 有输出就算成功。

API key 在 <https://cloud.vast.ai/manage-keys/> 生成，然后：

```bash
# 把 API key 写入 ~/.config/vastai/vast_api_key，后续 vastai 命令自动读取
# key 在 https://cloud.vast.ai/manage-keys/ 生成；不要提交进 git，也不要贴到聊天里
vastai set api-key <你的key>
```

key 存在 `~/.config/vastai/vast_api_key`，**不要提交进 git，也不要贴到聊天/issue 里**。

### 1.2 搜 L4

```bash
# 目的：列出当前可租、且满足 D1 硬条件的 L4 单卡，按含盘总价从低到高排。
# -n 关掉默认 query（默认带 verified=true），否则大量 unverified 的 L4 host 不会出现。
# 引号里是筛选条件：L4 / 单卡 / 可租 / reliability>=98% / Max CUDA>=13.0（镜像要求）/
# 下载>=500 Mbps / 可用磁盘>=40GB / 最长租期>0.25 天（=6 小时）。
# -o dph 按 dph_total 升序；--storage 40 让总价把 40GB 容器盘的小时费算进去。
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
> # 目的：读出镜像内置的 CUDA runtime 版本（CUDA_VERSION）和启动校验条件（NVIDIA_REQUIRE_CUDA）
> # 不需要 GPU；镜像 pull 到本地后就能跑，用来核对 host 的 Max CUDA 够不够
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

判断：`13.0.2 ≤ 13.2`、同为 13 大版本，且 sm_89 在 `TORCH_CUDA_ARCH_LIST` 里 → 能跑。`sm_89` 是 compute capability 8.9 的编译目标写法（Ada 架构：L4 / L40S / RTX 4090），**不是 CUDA 版本**。这里 `13.0.2` 和 `13.2` 不是同一个东西：前者是镜像里的 runtime 版本，后者是 host driver 支持的上限；`.0.2` 是 toolkit 的 patch 号，`13.0.96-1` 则是 cudart 包的编号，不要混着比。

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
# 目的：用 1.2 选中的 offer_id 创建实例，默认就是 on-demand。
# 不要加 --bid_price：那会把实例变成 interruptible，被 pause 的那轮基线直接作废。
# 参数从上到下：固定镜像 tag、40GB 容器盘、SSH 启动方式、映射 8000 端口、打个标签方便找。
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
# 目的：确认实例已经 running；stopped/loading 时 SSH 一定连不上
vastai show instances

# 目的：拿到 SSH 的 host 和端口；输出是 ssh://... URI，不能直接当命令执行
vastai ssh-url <instance_id>

# 目的：拿 scp 用的 host:port；实例重启后端口可能变，第 10 节拉结果前重新取
vastai scp-url <instance_id>

# 目的：实例起不来/容器反复重启时，看容器里的启动日志定位原因
vastai logs <instance_id>
```

`ssh-url` 输出的是 `ssh://root@ssh8.vast.ai:34388` 这种 URI，**不能直接粘进 bash**（会被当成命令名，报 `No such file or directory`）。要拆成：

```bash
# 目的：登录容器。-i 指定私钥（本机没有默认 id_rsa/id_ed25519 时必填），
# -p 是 ssh-url 里的端口，root@ 后面是 ssh-url 里的主机名。
ssh -i ~/.ssh/<你的私钥> -p 34388 root@ssh8.vast.ai
```

两个前提：

1. 实例状态是 `running`。`stopped` 时连不上，先 `vastai start instance <instance_id>`，再等镜像拉完。
2. Vast 账号/实例里注册的公钥，和 `-i` 指向的私钥配对。本机没有默认 `id_rsa`/`id_ed25519` 时必须显式 `-i`；公钥没注册就：

> **Vast 会自动 tmux**：镜像的 `~/.bashrc` 末尾有 `tmux attach -t ssh_tmux || tmux new-session -s ssh_tmux`，所以**每个新 SSH 都会进入同一个 tmux 会话**，看到的是同一个前台进程（比如 vLLM 日志）。这不是 SSH 复用，是 Vast 故意的。在 tmux 里：
>
> ```bash
> Ctrl-b c        # 新建窗口，得到干净 shell
> Ctrl-b 0 / 1    # 按编号切换窗口
> Ctrl-b d        # 脱离会话，进程继续跑（断线不会杀 vLLM）
> tmux ls         # 列出会话
> tmux attach -t ssh_tmux
> ```
>
> 清理多余窗口/会话时注意别杀掉 vLLM：
>
> ```bash
> exit                             # 关掉当前空闲窗口（最安全）
> # 或 Ctrl-b & 然后按 y          # 关当前窗口
> tmux kill-session -t <name>      # 关指定会话
> tmux kill-session -a             # 关掉除当前会话外的所有
> tmux list-clients -t ssh_tmux    # 多个 SSH 是 client，不是 session
> tmux detach-client -t /dev/pts/N # 踢掉某个 client，不影响会话
> ```
>
> **不要用 `tmux kill-server`**，它会把 `ssh_tmux` 和里面的 vLLM 一起杀掉。vLLM 通常在 window 0，关窗口前先 `Ctrl-b 0` 确认。
>
> 想禁用自动 tmux（每个 SSH 独立 shell，但断线会杀前台进程）：`touch ~/.no_auto_tmux` 后重连。长压测不要禁用。

```bash
# 目的：把本机公钥注册到 Vast 账号（一次即可；已注册过会提示重复，可跳过）
vastai create ssh-key "$(cat ~/.ssh/<你的公钥>.pub)"

# 目的：把同一把公钥注入已经创建好的实例（创建时选错 key 时用），几秒后生效
vastai attach ssh <instance_id> "$(cat ~/.ssh/<你的公钥>.pub)"
```

### 1.5 进容器后的 preflight

进容器后先跑：

```bash
# 目的：有些镜像/启动方式没有预建 /workspace；/ 就是 40GB 容器盘，建目录统一路径
mkdir -p /workspace

# 目的：确认 GPU 型号/显存/driver 与订单一致（应看到 NVIDIA L4、23034 MiB）
nvidia-smi

# 目的：确认容器盘容量是 40G，并确认权重会写到这个盘
df -h /

# 目的：确认 Python 版本；镜像只有 python3，没有 python
python3 -V

# 目的：确认 vLLM 版本和镜像 tag 一致（应为 0.34.0），后续 flag 核对以它为准
python3 -c "import vllm; print(vllm.__version__)"

# 目的：确认 torch 的 CUDA 版本和 GPU compute capability；应输出 cu 13.0 / (8, 9)
python3 -c "import torch; print('torch', torch.__version__, 'cu', torch.version.cuda)"

# 目的：确认 bench 子命令能加载；成功会打印 bench CLI ok
vllm bench serve --help >/dev/null && echo "bench CLI ok"
```

> 2026-11-20 实测（实例 `61674313`）：L4 23034 MiB、driver 595.99.02、torch 2.14.0+cu130、`torch.version.cuda=13.0`、compute capability `(8, 9)`、24 vCPU / 125GB RAM。`python` 不存在，所有命令用 `python3`。

检查今天要用的 flag 是否存在（版本不对就换镜像，不要盲目 `pip install -U vllm`）：

```bash
# 目的：确认服务端支持 per-request metrics（第 6 节诊断跑用）和 prefix caching 开关。
# 注意：v0.34.0 的 help 按 ConfigGroup 分组，--help 只显示目录，必须加 =all。
vllm serve --help=all | grep -E "enable-per-request-metrics|prefix-caching"

# 目的：确认压测 CLI 支持固定输出长度、百分位、详细结果和 goodput；缺哪个就调整 D1 命令。
vllm bench serve --help=all | grep -E "ignore-eos|metric-percentiles|percentile-metrics|save-detailed|goodput"
```

> 2026-11-20 在 `v0.34.0` 上实测：上面这些 flag 都存在；`--enable-per-request-metrics` 和 `--disable-per-request-metrics` 是成对出现的，默认关闭。用 `--help` 不加 `=all` 会 grep 不到任何东西，不要误判成版本太旧。

设置环境变量：

```bash
# 目的：模型缓存放 /workspace/hf，避免写满根盘；所有终端都要指向同一个目录
export HF_HOME=/workspace/hf

# 目的：启用 Xet 高速传输。hub 2.4.0 默认走 Xet，旧的 HF_HUB_ENABLE_HF_TRANSFER 已弃用
export HF_XET_HIGH_PERFORMANCE=1

# 目的：把 vLLM 版本写进压测 JSON 的 metadata，保证结果可追溯
export VLLM_VERSION=$(python3 -c "import vllm; print(vllm.__version__)")

# 目的：预建权重和结果目录；后面的 serve/bench 都依赖这两个路径
mkdir -p /workspace/hf /workspace/results
```

`export` 只对当前 shell 生效，而后面要开 Terminal A/B/C。写进 `~/.bashrc` 一次，避免每个窗口忘设 `HF_HOME` 导致重复下载 5GB：

```bash
# 目的：把 HF 路径写进 ~/.bashrc，Terminal A/B/C 新开 shell 也能找到同一份缓存；
# 否则每个窗口都要手动 export，忘了就会把 5GB 权重重复下一遍。
cat >> ~/.bashrc <<'EOF'
export HF_HOME=/workspace/hf
export HF_XET_HIGH_PERFORMANCE=1
EOF

# 目的：让当前 shell 立即生效，不用退出重登
source ~/.bashrc
```

> 版本不匹配是这一步最常见的坑：driver 太旧会在加载模型时报 CUDA error。`nvidia-smi` 右上角的 CUDA Version 就是 offer 卡上的 **Max CUDA**；`v0.34.0` 镜像要求 ≥ **13.0**（镜像里是 13.0.2）。租之前就核对，别等进容器才发现。

---

## 2. 下载模型（10–20 分钟，和起服务分开）

先把权重下完，避免把“下载慢”误判成“服务起不来”：

```bash
# 目的：把 Qwen3-8B-AWQ 的完整快照（权重 + config + tokenizer）下到 $HF_HOME/hub。
# v0.34.0 自带 huggingface_hub 2.4.0，走 Xet 传输；旧版 hub 才需要 hf_transfer。
# snapshot_download 支持断点续传，中断后重跑会接着下，不会从头开始。
python3 - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen3-8B-AWQ")
PY

# 目的：确认实际占用约 5.7GB。
# 注意：Xet 布局下快照里是符号链接，du 不加 -L 只会统计链接本身（会看到 4.4M，不是没下完）。
du -shL "$HF_HOME/hub/models--Qwen--Qwen3-8B-AWQ"

# 目的：确认整个 HF 缓存（含共享 blob 存储）的真实占用
du -sh "$HF_HOME/hub"
```

模型约 5.7GB（`du -L` 口径）。若提示 gated/401，先 `hf auth login`（旧版命令是 `huggingface-cli login`）；Qwen3-8B-AWQ 通常是公开的。

下载日志里出现 `unauthenticated requests` 说明在匿名限速（实测 3.4MB/s）。有 HF token 可以 `export HF_TOKEN=hf_xxx` 提速，但**不要写进 git**。

**为什么 `du -sh` 只有 4.4M**：hub 2.4.0 的 Xet 布局把真实权重放在 `$HF_HOME/hub/blobs/`，快照目录里是符号链接；`du` 默认不跟随符号链接，`du -L` 才统计目标文件。`df -h /` 显示已用 5.8G，说明数据确实在盘上，不是没下完。

Vast 的容器盘在 Stop 后保留、Destroy 时删除，所以**不需要额外 Volume**；Volume 只能挂回同一台物理机，换 host 就作废。权重放 `/workspace/hf` 即可，D2 换机器就重下（10–20 分钟）。

---

## 3. 起服务（10 分钟）

另开一个终端（Terminal A），前台起服务并落日志。Vast 的 tmux 新窗口会自动 source `~/.bashrc`；如果沿用旧 shell，先 `source ~/.bashrc` 确认 `HF_HOME=/workspace/hf`：

```bash
# 目的：进 /workspace，保证日志和结果都落在容器盘上
cd /workspace

# 目的：前台起 OpenAI 兼容服务，stdout/stderr 同时写终端和 /workspace/vllm.log。
# 参数逐个说明：
#   Qwen/Qwen3-8B-AWQ              模型 repo；HF_HOME 已指向缓存，不会重复下载
#   --served-model-name qwen3-8b   请求里的 model 必须叫这个名字，否则 404
#   --max-model-len 8192           上下文上限 8k，控制 KV cache 占用（原生 32k，D1 不用）
#   --gpu-memory-utilization 0.90  权重 + KV cache 最多占 90% 显存
#   --max-num-seqs 64              同时在跑的序列上限，D2 要调的旋钮
#   --disable-log-requests         压测时不逐条打请求日志，避免日志 I/O 干扰吞吐
#   --host 0.0.0.0 --port 8000     监听所有网卡，Vast 端口映射后才能从实例外访问
#   2>&1 | tee vllm.log            保存日志，后面 grep 加载耗时/KV cache/最大并发
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
# 目的：从启动日志抓 4 个要写进 README 的数字：
#   Loading model       模型加载耗时
#   GPU KV cache size   KV cache 容量（能缓存多少 token）
#   Maximum concurrency 1024/256 输入输出下的最大并发
#   Application startup 服务真正可用的时间点
grep -E "Loading model|GPU KV cache size|Maximum concurrency|Application startup" /workspace/vllm.log
```

把 **模型加载耗时、GPU KV cache size、Maximum concurrency for 1024/256 tokens** 抄到第 7 节的表下面。面试写 writeup 时要用。

服务起来后先做个快速健康检查（不产生压测结果，只确认端口和模型名）：

```bash
# 目的：确认 8000 端口通、模型名是 qwen3-8b；返回 JSON 才继续
curl -s http://127.0.0.1:8000/v1/models | head -c 200
```

---

## 4. Smoke test（5 分钟）

两条都通，才能进压测：

```bash
# 目的：确认服务已起来、模型名是 qwen3-8b；返回 200 + JSON 才能继续
curl -s http://127.0.0.1:8000/v1/models | python3 -m json.tool | head -30
```

```bash
# 目的：走 chat 端点做端到端 smoke test，确认 chat template、生成、JSON 返回都正常。
# /no_think 关掉 Qwen3 默认的 thinking，避免 64 个 token 全花在推理过程上。
# temperature=0 让输出确定，便于复现。
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
# 目的：确认压测要用的 /v1/completions 端点可用。
# bench 的 random 数据集直接发 token IDs 到这个端点，不经过 chat template。
curl -s http://127.0.0.1:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-8b","prompt":"hello","max_tokens":16}' \
  | python3 -m json.tool | head -20
```

---

## 5. 压测（75 分钟）

### 5.1 开 GPU 采样（Terminal B）

```bash
# 目的：每秒采一次 GPU 指标，后台写入 CSV；压测结束后用它算 util 均值和 P95。
# 采集项：时间戳、GPU 利用率、显存占用、功耗、温度、SM 频率。
nvidia-smi --query-gpu=timestamp,utilization.gpu,memory.used,power.draw,temperature.gpu,clocks.sm \
  --format=csv -l 1 > /workspace/gpu_util.csv 2>&1 &

# 目的：记下后台采样进程的 PID，第 10 节用它停止采样
echo $! > /workspace/gpu_smi.pid
```

如果 `clocks.sm` 报错，删掉这一列重跑；至少保留 utilization/memory/power/temp。

**这个窗口不要关**：`nvidia-smi` 虽然是后台进程，但关闭 tmux window 会向它发 SIGHUP，采样会静默停止。要么留着这个窗口，要么启动时改成 `nohup nvidia-smi ... &`。

### 5.2 Warmup（丢弃，不计入结果）

```bash
# 目的：建 warmup 目录；这轮结果丢弃，不参与 README 统计
mkdir -p /workspace/results/warmup

# 目的：10 条请求、并发 1，让 CUDA kernel 完成首次编译、GPU 频率稳定。
# 输入/输出长度与正式跑一致（1024/256），保证预热的是同一套 kernel。
vllm bench serve \
  --backend openai \
  --endpoint /v1/completions \
  --host 127.0.0.1 --port 8000 \
  --model qwen3-8b \
  --tokenizer Qwen/Qwen3-8B-AWQ \
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

**warmup 到底在预热什么**（结果丢弃，不进 README）：

- 首次真实 batch 的 lazy init / 内存池首次分配；
- GPU 从空闲低频爬到工作频率（这台 L4 还有 40W 功耗墙，爬坡更明显）；
- 温度、风扇、功耗墙触发点进入稳态；
- HTTP 连接、tokenizer 加载等客户端一次性开销。

它不负责填 KV cache / prefix cache：每轮正式跑前会 `reset_prefix_cache`，且每轮换 `seed`，缓存不会跨轮复用。`sleep 30` 是排空上一轮尾请求，和 warmup 是两件事。

### 5.3 四轮基线（Terminal C）

`--num-prompts` 按并发调整：c=1/4 用较少样本省时间；c=16/64 需要更多样本，否则 P99 没有统计意义。

新 tmux 窗口不会继承 §1.5 的 `export`，跑循环前先补上，否则 JSON 的 metadata 里 `vllm=` 是空的：

```bash
export VLLM_VERSION=$(python3 -c "import vllm; print(vllm.__version__)")
echo "$VLLM_VERSION"   # 应输出 0.34.0；空值说明 export 没执行
```

> 两个代码块要分开粘。连在一起会变成 `mkdir ... warmupexport VLLM_VERSION=...`，结果只创建两个目录，`export` 根本没执行。

```bash
# 目的：进 /workspace，结果 JSON 统一写到 ./results
cd /workspace
mkdir -p results

# 目的：依次跑 4 个并发点；每个并发点单独一个 JSON，README 表格一行
for C in 1 4 16 64; do
  case $C in
    1)  N=100 ;;
    4)  N=200 ;;
    16) N=500 ;;
    64) N=1000 ;;
  esac

  # 目的：按并发选样本数；低并发省时间，高并发要更多样本 P99 才有统计意义
  echo "=== concurrency=$C n=$N ==="

  # 目的：清掉上一轮的 prefix cache，避免缓存命中把 TTFT 压低（端点不存在时忽略）
  curl -s -X POST http://127.0.0.1:8000/reset_prefix_cache >/dev/null || true

  # 目的：记录压测前的抢占计数；和 AFTER 相减得到本轮发生了几次 KV cache 抢占
  BEFORE=$(curl -s http://127.0.0.1:8000/metrics \
    | awk '/^vllm:num_preemptions_total/{s+=$NF} END{print s+0}')

  # 目的：跑当前并发点的基线。固定输入 1024 / 输出 256 且 ignore-eos，
  # 保证 4 个并发点的数字可比；--save-detailed 保留 per-request 数组供复算。
  # --seed $C 让每轮换 prompt，配合 reset_prefix_cache 避免跨轮缓存污染。
  vllm bench serve \
    --backend openai \
    --endpoint /v1/completions \
    --host 127.0.0.1 --port 8000 \
    --model qwen3-8b \
    --tokenizer Qwen/Qwen3-8B-AWQ \
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

  # 目的：再读一次抢占计数，和 BEFORE 相减得到本轮增量
  AFTER=$(curl -s http://127.0.0.1:8000/metrics \
    | awk '/^vllm:num_preemptions_total/{s+=$NF} END{print s+0}')

  # 目的：打印本轮抢占次数；>0 说明 KV cache 不够，序列被换出过
  echo "preemptions delta: $((AFTER-BEFORE))"

  # 目的：等队列排空、GPU 频率回落，避免上一轮的尾请求污染下一轮
  sleep 30
done
```

关键 flag 说明：

- `--tokenizer Qwen/Qwen3-8B-AWQ`：`--model qwen3-8b` 只是请求里的 served name，bench 加载 tokenizer 时需要真实 repo；不写会报 `OSError: qwen3-8b is not a local folder and is not a valid model identifier`。
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
# 目的：与 baseline 相同的启动参数，只多 --enable-per-request-metrics。
# 它让服务端记录每个请求的 server_queue_times / server_ttfts，用来拆解排队 vs prefill。
# 它会给 headline 数字增加 CPU 开销，所以只用于诊断，不用于正式基线。
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
# 目的：诊断跑 c=16、200 条，和 baseline 完全同口径（1024/256、ignore-eos、同百分位），
# 这样 server_queue_times / server_ttfts 才能和 baseline 的 TTFT 直接对照。
vllm bench serve \
  --backend openai \
  --endpoint /v1/completions \
  --host 127.0.0.1 --port 8000 \
  --model qwen3-8b \
  --tokenizer Qwen/Qwen3-8B-AWQ \
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
| `ssh://root@host:port: No such file or directory` | 把 `ssh-url` 输出的 URI 直接粘进了 shell | 用 `ssh -i <私钥> -p <port> root@<host>` |
| `Permission denied (publickey)` | 账号/实例里的公钥和本机私钥不配对；或本机没有默认 key 却没写 `-i` | `vastai attach ssh <id> "$(cat ~/.ssh/xxx.pub)"`；连接时显式 `-i`；`ssh -v` 看 offered key |
| 新 SSH 会话被 vLLM 日志占住 | Vast 的 `.bashrc` 自动 attach 到同一个 tmux（`ssh_tmux`） | `Ctrl-b c` 开新窗口；`Ctrl-b d` 脱离；`touch ~/.no_auto_tmux` 可禁用 |
| `Connection refused` / 超时 | 实例 `stopped` 或还在 `loading` | `vastai start instance <id>`；`vastai show instance <id>` 等到 `running` |
| `python: command not found` | 镜像里只有 `python3` | 所有命令改用 `python3`；不要额外装 python |
| 日志里出现 `HF_HUB_ENABLE_HF_TRANSFER` deprecated | hub 2.4 改用 Xet，旧变量失效 | `sed -i 's/^export HF_HUB_ENABLE_HF_TRANSFER=1$/export HF_XET_HIGH_PERFORMANCE=1/' ~/.bashrc` |
| `df: /workspace: No such file or directory` | 该镜像没有预建 `/workspace`，`/` 就是容器盘 | `mkdir -p /workspace`；用 `df -h /` 确认容量 |
| `vllm ... --help \| grep` 什么都 grep 不到 | v0.34.0 的 help 按 ConfigGroup 分组 | 用 `--help=all`，不是版本缺 flag |
| `search offers` 返回空 | 门槛太严，或 `duration` 单位写错（是天，不是小时） | 逐条放宽 `inet_down`/`reliability`；`duration>0.25` 表示 6 小时 |
| `torch.OutOfMemoryError` / 启动就 OOM | `gpu-memory-utilization` 太高，或 `max-model-len` 太大 | 降到 0.85 → 0.80；`--max-model-len 4096` |
| `CUDA error: no kernel image is available` | 镜像/vLLM 的 CUDA 与 driver 不匹配 | 换匹配的镜像 tag；先 `nvidia-smi` 看 driver 支持的 CUDA |
| `CUDA driver version is insufficient for CUDA runtime version` | host 的 Max CUDA 低于镜像的 `CUDA_VERSION` | destroy 换 host，或换更低 CUDA 的镜像 tag；**不要在容器里装 driver** |
| `Connection refused` | 服务还在加载模型（8B AWQ 约 30–90 秒） | 看 Terminal A 日志等到 `Uvicorn running` |
| `404 model not found` | `--served-model-name` 和请求里的 `model` 不一致 | 统一用 `qwen3-8b` |
| `OSError: qwen3-8b is not a local folder...` | bench 拿 `--model` 去加载 tokenizer，但它是 served name | bench 加 `--tokenizer Qwen/Qwen3-8B-AWQ` |
| smoke test 返回一堆 thinking | Qwen3 默认 `enable_thinking=True` | prompt 加 `/no_think`，或 `chat_template_kwargs: {"enable_thinking": false}` |
| `unrecognized arguments: --enable-per-request-metrics` | vLLM 版本较旧 | 跳过第 6 节；或换更新的 vLLM 镜像（不要盲目升级 CUDA 栈） |
| `unrecognized arguments: --ignore-eos` / `--metric-percentiles` | bench CLI 版本较旧 | `vllm bench serve --help` 对一遍；换镜像 |
| `reset_prefix_cache` 404 | 该版本没有这个端点 | 忽略；每轮不同 `--seed` 已能换 prompt；必要时重启服务 |
| P99 抖动巨大 | 有其他进程占卡 / 抢占 / Vast host 邻居噪声 | `nvidia-smi` 看进程；看 `vllm:num_preemptions_total`；重复跑 c=16/64；仍抖就换 host |
| 下载模型极慢 | 匿名限速 / host 带宽差 | 设 `HF_TOKEN`；下次租 `inet down` ≥ 500 Mbps 的 host |
| 下载完 `du -sh` 只有 4.4M | hub 2.4 的 Xet 布局用符号链接，`du` 默认不跟随 | 用 `du -shL`；`df -h /` 看到 5.8G 就说明下全了 |
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
# 1. 目的：停掉 5.1 启动的 nvidia-smi 后台采样；PID 文件不在了也不报错
kill "$(cat /workspace/gpu_smi.pid)" 2>/dev/null || true

# 2. 目的：确认 4 个 baseline JSON（+ 可选诊断 JSON）都在，且大小不是 0
ls -lh /workspace/results/

# 3. 目的：确认日志里仍能抓到加载耗时 / KV cache / 最大并发，写 README 要用
grep -E "Loading model|GPU KV cache size|Maximum concurrency" /workspace/vllm.log
```

**结果必须拉回本地，不能只留在实例盘。** 先拿连接信息，再在本地机器执行：

```bash
# 目的：拿 scp 的 host/port；实例重启后端口会变，以这次输出为准
vastai scp-url <instance_id>
```

```bash
# 目的：把 4 个 baseline JSON + 诊断 JSON 拉回本地（-r 递归目录）
scp -P <ssh_port> -r root@<host>:/workspace/results ./results

# 目的：拉回 GPU 采样，后面算 util 均值和 P95
scp -P <ssh_port> root@<host>:/workspace/gpu_util.csv ./gpu_util.csv

# 目的：拉回服务日志，保留加载耗时/KV cache/报错现场
scp -P <ssh_port> root@<host>:/workspace/vllm.log ./vllm.log
```

```bash
# 目的：在本地仓库提交结果；不要在容器里 git commit，容器里没有这个 repo
cd ~/liuzhiyong1982-org/llm-inference-platform-lab
git add results gpu_util.csv vllm.log
git commit -m "D1: vLLM baseline on L4 (concurrency 1/4/16/64)"
git push
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
