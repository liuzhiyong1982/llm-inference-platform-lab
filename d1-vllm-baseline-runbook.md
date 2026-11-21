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

先把三个数分清：

- `c` / `--max-concurrency`：**同时在飞的请求数**，即并发档位 1/4/16/64；
- `n` / `--num-prompts`：这一轮总共发多少条，100/200/500/1000；
- `--max-num-seqs`：服务端一个 batch 最多几条序列（启动参数，固定 64），不是客户端并发。

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

`--dataset-name random` 发的**不是自然语言**，是合成 token 序列：

- 从词表中排除 special tokens，按 `(offset + index + arange(1024)) % vocab_size` 取一段滑动窗口；
- decode 成字符串后再 re-encode、截断，保证每条正好 1024 个 token（不同 tokenizer 的合并规则会让原始 ID 数变化）；
- 每个请求的起点不同，避免 100/1000 条完全一样；
- 实测 c=1：`total_input_tokens=102400`、`input_lens` 全为 1024、`output_lens` 全为 256。

所以它测的是“固定长度下的计算性能”，不代表真实文本分布，也没有天然的共享前缀；要测 prefix cache 得显式加 `--random-prefix-len`。

数据集怎么选：

| `--dataset-name` | 内容 | 适合 | 代价 |
|---|---|---|---|
| `random` | 合成定长 token 序列 | 吞吐/延迟基线、并发对比 | 分布不真实、默认无共享前缀 |
| `sharegpt` | 真实多轮对话 | 真实长度分布、prefix 复用 | 需下载、长度不可控、样本可能不够 |
| `hf` / `custom` | 自有数据或 HF 数据集 | 贴近业务流量 | 要准备数据、定义长度口径 |

`--random-range-ratio` 默认 `0.0`（长度完全固定）；调大后长度在均值附近波动，更接近真实流量，但四个并发点的可比性会变差。D1 固定为 0。

D1 用到的 flag 逐项解释：

| flag | 我们传的值 | 作用 | 注意 |
|---|---|---|---|
| `--backend` | `openai` | 用 OpenAI 兼容 HTTP 客户端打服务端；其他可选 `vllm` 原生、`openai-chat`、embeddings 等 | 选错 backend 会打错 endpoint |
| `--endpoint` | `/v1/completions` | 请求路径；random 数据集直接发 token IDs，不经过 chat template | chat 模型要用 `/v1/chat/completions`，D1 刻意不用 |
| `--host` | `127.0.0.1` | 服务地址；实例内回环，避免公网 RTT 污染 | 不要填 Vast 公网 host |
| `--port` | `8000` | 服务端口，与 `vllm serve --port` 一致 | |
| `--model` | `qwen3-8b` | 请求体里的 `model` 字段，必须匹配 `--served-model-name` | 不匹配 404；它还会被当作默认 tokenizer 来源 |
| `--tokenizer` | `Qwen/Qwen3-8B-AWQ` | 加载 tokenizer 的 HF repo 或本地路径，用于编码 prompt、统计 token 数 | 不写会拿 `qwen3-8b` 去 HF 找，报 `not a local folder` |
| `--dataset-name` | `random` | 随机 token ID 数据集，长度可控、无需下载数据 | 只适合测性能，不能代表真实文本分布 |
| `--random-input-len` | `1024` | 每条请求的输入 token 数（固定） | 四个并发点必须一致，否则不可比 |
| `--random-output-len` | `256` | 每条请求的输出 token 数 | 需配合 `--ignore-eos` 才能精确生成 256 |
| `--num-prompts` | `100/200/500/1000` | 这一轮总共发多少条 | 不是并发；和 `c` 区分 |
| `--max-concurrency` | `1/4/16/64` | 同时在飞的请求上限（并发档位） | 闭路：有空位才发下一条；不是 GPU batch size |
| `--ignore-eos` | 开关 | 请求里带 `ignore_eos`，强制生成到 output-len，不被 EOS 截断 | 否则 output tok/s、TPOT 不可比 |
| `--seed` | `$C` | 控制随机 prompt 采样；每轮换 seed 避免命中 prefix cache | 同 seed 可复现同一批 prompt |
| `--percentile-metrics` | `ttft,tpot,itl,e2el` | 指定哪些指标输出百分位 | 不写就只报默认指标 |
| `--metric-percentiles` | `50,95,99` | 指定百分位点 | 默认只有 P99；README 要 P50/P95 |
| `--goodput` | `ttft:2000 tpot:100` | 定义 SLO（毫秒），统计同时满足 TTFT ≤ 2000 且 TPOT ≤ 100 的请求 | 允许的 key 是 `ttft`/`tpot`/`e2el`；太严会得到 0 |
| `--save-result` | 开关 | 把汇总结果写成 JSON | 不加只在终端看，无法归档 |
| `--save-detailed` | 开关 | JSON 里保留 per-request 数组（`ttfts`、`tpot`、`itls`、`latencies` 等） | 文件大，但复算 P99/画图靠它 |
| `--result-dir` | `./results` | 结果输出目录 | 相对路径基于当前 cwd；我们在 `/workspace` 下跑 |
| `--result-filename` | `d1-c${C}-时间戳.json` | 输出文件名，带并发和时间戳避免覆盖 | 重复跑加 `-run2` |
| `--metadata` | `gpu=... vllm=...` | 任意 key=value 写进 JSON，做实验溯源 | 新 shell 里 `VLLM_VERSION` 可能为空，先 export |

`--percentile-metrics` 和 `--metric-percentiles` 是笛卡尔积：前者选**指标**（`ttft`/`tpot`/`itl`/`e2el`），后者选**百分位点**（`50`/`95`/`99`）。只写 `--metric-percentiles 50,99` 不会让 TPOT 自动有 P50/P99，必须同时在 `--percentile-metrics` 里列出 `tpot`。JSON 字段是 `p50_ttft_ms`、`p99_tpot_ms` 这种；`mean_*`、`median_*` 是独立字段。

本次没用、但值得知道的 flag：

- `--request-rate`：默认 `inf`，即闭路压测；给有限值会按到达率发请求（配合 `--burstiness` 控制 Poisson/均匀）。
- `--temperature`：v0.34 **不再默认 0**，服务端会用自己的默认值。本次四轮都没显式设，所以横向可比；**跨次复现要加 `--temperature 0`**。
- `--num-warmups`：bench 内置的预热条数；我们用单独的 §5.2 代替。
- `--disable-tqdm`：关进度条，脚本日志更干净。
- `--append-result`：追加到已有 JSON，适合分段跑。
- `--label` / `--base-url` / `--header` / `--extra-body`：结果标签、直连 URL、自定义 header、额外请求体。

每轮之间等 30 秒；不要连续压，否则队列没排空会污染下一轮。若 `vllm:num_preemptions_total` 取不到，用 `grep -c "PreemptionMode" /workspace/vllm.log` 记录增量。

**“抢占”（preemption）是什么**：vLLM 的 KV cache 是固定大小的块池。当新请求要不到空闲块时，调度器会把**已经在跑**的某条序列的 KV 块收走腾地方：要么丢弃、之后重算（recompute），要么换到 CPU 再换回来（swap）。被抢占的请求会多出重算/搬运开销，表现为 ITL/TTFT 尖峰。所以 `num_preemptions_total` 的增量 > 0 是 KV cache 压力的直接信号。

它和 Vast 的 interruptible 实例被 host 暂停**不是一回事**：前者是 vLLM 内部的显存调度，后者是整台实例被 marketplace 抢占。D1 里 c=64 的 KV 需求约 `64 × (1024+256) = 81,920` tokens，小于 91,648 的 KV 容量，所以预期抢占为 0。

### 5.4 重复 c=16/64（可选，约 20–50 分钟）

单次跑不足以区分“真实差异”和“Vast host 抖动 / 邻居噪声”。时间允许就把 c=16/64 再跑一遍，报两次的中位数/范围；没时间就在 README 注明“single run，P99 仅指示性”。

时间预算：c=16（n=500）约 19 分钟；c=64（n=1000）约 32 分钟。只做 c=16 就把下面的 `for C in 16 64` 改成 `for C in 16`。

**前提：必须用 baseline 配置。**

- 如果当前跑的是 §6 的诊断服务（带 `--enable-per-request-metrics`），先在 Terminal A 按 `Ctrl-C` 停掉；
- 重复跑不能带这个 flag，否则 per-request metrics 的 CPU 开销会污染数字。

#### 5.4.1 重启 baseline 服务

```bash
# 目的：用与 D1 baseline 完全相同的参数重启，唯一区别是不带 --enable-per-request-metrics。
# 日志写到 vllm-run2.log，保留原来的 vllm.log 不动。
cd /workspace
vllm serve Qwen/Qwen3-8B-AWQ \
  --served-model-name qwen3-8b \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --max-num-seqs 64 \
  --disable-log-requests \
  --host 0.0.0.0 \
  --port 8000 \
  2>&1 | tee /workspace/vllm-run2.log
```

等 `Application startup complete`，再确认服务可用：

```bash
# 目的：确认 8000 端口通、模型名是 qwen3-8b；返回 JSON 才继续
curl -s http://127.0.0.1:8000/v1/models | head -c 200
```

#### 5.4.2 重开 GPU 采样

第一轮的采样进程在 §10 才停；如果已经停了，重复跑前要重新开一份，写到单独 CSV，避免覆盖 `gpu_util.csv`：

```bash
# 目的：每秒采一次 GPU 指标，写到 gpu_util_run2.csv；重复跑期间不要关这个窗口
nvidia-smi --query-gpu=timestamp,utilization.gpu,memory.used,power.draw,temperature.gpu,clocks.sm \
  --format=csv -l 1 > /workspace/gpu_util_run2.csv 2>&1 &

# 目的：记录 PID，重复跑结束后用它停采样
echo $! > /workspace/gpu_smi_run2.pid
```

#### 5.4.3 跑重复轮次

`--seed` 保持和第一轮相同（16/64），这样两次的 prompt 集合一致，差异只来自 host/run 噪声；文件名加 `-run2`。

```bash
# 目的：进 /workspace，结果仍写 ./results
cd /workspace
export VLLM_VERSION=$(python3 -c "import vllm; print(vllm.__version__)")

# 目的：只重复 c=16 和 c=64；其他并发点不动
for C in 16 64; do
  case $C in
    16) N=500 ;;
    64) N=1000 ;;
  esac

  echo "=== run2 concurrency=$C n=$N ==="

  # 清 prefix cache，避免和第一轮共用缓存
  curl -s -X POST http://127.0.0.1:8000/reset_prefix_cache >/dev/null || true

  # 记录本轮开始前的抢占计数
  BEFORE=$(curl -s http://127.0.0.1:8000/metrics \
    | awk '/^vllm:num_preemptions_total/{s+=$NF} END{print s+0}')

  # 与 5.3 完全相同的 bench 参数，只改文件名和 metadata 的 run=2
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
    --result-filename "d1-c${C}-run2-$(date +%Y%m%d-%H%M%S).json" \
    --metadata gpu=l4-24gb vllm="$VLLM_VERSION" concurrency="$C" n="$N" run=2 input_len=1024 output_len=256 ignore_eos=true

  AFTER=$(curl -s http://127.0.0.1:8000/metrics \
    | awk '/^vllm:num_preemptions_total/{s+=$NF} END{print s+0}')

  echo "preemptions delta: $((AFTER-BEFORE))"
  sleep 30
done
```

#### 5.4.4 停采样并对比两次结果

```bash
# 目的：停掉 5.4.2 的采样；PID 文件不在了也不报错
kill "$(cat /workspace/gpu_smi_run2.pid)" 2>/dev/null || true

# 目的：确认 run2 的 JSON 都在
ls -lh /workspace/results/*run2*.json
```

用下面的脚本把第一轮和 run2 放在一起，打印每个指标的两次值与中位数：

```bash
python3 - <<'PY'
import glob, json, statistics

for c, n in ((16, 500), (64, 1000)):
    rows = []
    for f in glob.glob(f"/workspace/results/d1-c{c}-*.json"):
        d = json.load(open(f))
        if int(d["num_prompts"]) == n:      # 排除 diagnostic 的 200 条
            rows.append((f.split("/")[-1], d))

    print(f"=== c={c} runs={len(rows)} ===")
    for key in ("output_throughput", "p50_ttft_ms", "p95_ttft_ms",
                "p99_ttft_ms", "p95_tpot_ms"):
        vals = [d[key] for _, d in rows]
        med = statistics.median(vals)
        print(f"{key:18s} {['%.2f' % v for v in vals]} median={med:.2f}")
PY
```

README 里报两次的中位数和范围（min–max）。如果两次差异超过 10–15%，在结论里注明“host 噪声较大，P99 仅指示性”，不要把它当成参数效果。

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

> **单位是秒，不是毫秒**（vLLM 文档明确写了 seconds）。算完 P99 要 ×1000 再和客户端 TTFT（ms）对比；否则会把 0.012 当成 0.012ms。数组里可能有 `null`（该请求没拿到服务端指标），算分位数前先过滤。

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

## 附：指标口径与计算

vLLM bench 内部用**秒**记录延迟，输出到终端/JSON 时乘 1000 变成 ms。例外：`server_queue_times`、`server_ttfts` 在 JSON 里仍是秒，`duration` 也是秒。

### 1. 单请求指标

| 指标 | 全称 | 定义 | 计算 |
|---|---|---|---|
| TTFT | Time To First Token | 请求发出到首 token | 直接记录（秒→ms） |
| ITL | Inter-Token Latency | 相邻流式 chunk 的间隔 | 每次 gap；标准解码 1 token/chunk，所以 ITL≈TPOT；投机解码一个 chunk 可能多个 token，ITL 只记 chunk 间隔 |
| TPOT | Time Per Output Token | 每个输出 token 的时间（不含首 token） | `(e2el - ttft) / (output_tokens - 1)`；`output_tokens = 1` 时按 0 |
| E2EL | End-to-End Latency | 端到端延迟 | 请求发出到完整响应 |

别名：ITL 在某些工具里叫 **TBT**（Time Between Tokens）；E2EL 常简写 **E2E**。TPOT 与 ITL 的单位都是 ms/token，但统计对象不同——TPOT 是整条请求摊薄，ITL 是相邻 chunk 的瞬时间隔，所以同一请求的 P99 不一定相等。

### 2. 聚合指标

| 指标 | 计算 | JSON 字段 |
|---|---|---|
| request throughput | `completed / duration` | `request_throughput` |
| output throughput | `sum(output_tokens) / duration` | `output_throughput` |
| total token throughput | `(total_input_tokens + total_output_tokens) / duration` | `total_token_throughput` |
| goodput | `good_completed / duration` | `request_goodput`（没配 `--goodput` 时为 `null`） |
| 达标比例 | `goodput / request_throughput` | 自己算 |
| 百分位 | 对 per-request 数组做 `np.percentile` | `p50_*` / `p95_*` / `p99_*` |
| 均值/中位数/标准差 | 对 per-request 数组 | `mean_*` / `median_*` / `std_*` |

`duration` 是 benchmark 的**墙钟时长**：从开始压测到最后一条请求结束，包含 ramp-up、排队和尾部，不是所有请求延迟之和。`completed` 只算成功请求，失败的不进分子。

### 3. Goodput 的计算

```
good_completed = 满足【所有】SLO 的成功请求数
goodput        = good_completed / duration          # req/s
达标比例       = goodput / request_throughput
```

单请求判定是逐条 **AND**：

```
ttft <= SLO_ttft  且  tpot <= SLO_tpot   （若配了 e2el 也要满足）
```

`--goodput ttft:2000 tpot:100` 的值是毫秒，代码内部除以 1000 转成秒。所以 SLO 是 `ttft <= 2.0s` 且 `tpot <= 0.1s`。

用 D1 的四个 JSON 反算：

| c | completed | duration (s) | good 条数 | goodput = good/duration | request_throughput | 达标比例 |
|---|---|---|---|---|---|---|
| 1 | 100 | 1,305.291 | 100 | 100 / 1,305.291 = **0.076611** | 0.076611 | 100% |
| 4 | 200 | 862.915 | 50 | 50 / 862.915 = **0.057943** | 0.231773 | 25% |
| 16 | 500 | 1,143.871 | 1 | 1 / 1,143.871 = **0.000874** | 0.437112 | 0.2% |
| 64 | 1,000 | 1,927.376 | 0 | 0 / 1,927.376 = **0** | 0.518840 | 0% |

失败原因拆开看（TTFT 和 TPOT 各自是否超标）：

| c | 都达标 | 只有 TTFT 超标 | 只有 TPOT 超标 | 两个都超标 |
|---|---|---|---|---|
| 1 | 100 | 0 | 0 | 0 |
| 4 | 50 | 150 | 0 | 0 |
| 16 | 1 | 5 | 31 | 463 |
| 64 | 0 | 0 | 3 | 997 |

c=4 的 25% 就是这么来的：200 条里 150 条 TPOT 合格但 TTFT > 2s，整条不算。c=16 只剩 1 条：TTFT 和 TPOT 同时达标的极少。

单条请求的例子：

| 点 | TTFT | TPOT | TTFT ≤2s | TPOT ≤100ms | 算达标 |
|---|---|---|---|---|---|
| c=4 #1 | 895 ms | 63.2 ms | ✅ | ✅ | ✅ |
| c=4 #2 | 2,839 ms | 55.8 ms | ❌ | ✅ | ❌ |
| c=16 #1 | 879 ms | 131.4 ms | ✅ | ❌ | ❌ |
| c=64 #1 | 895 ms | 434.8 ms | ✅ | ❌ | ❌ |

可以自己复算：

```python
import json

d = json.load(open("results/d1-c4-20261120-190221.json"))
good = 0
for ttft, e2el, out in zip(d["ttfts"], d["latencies"], d["output_lens"]):
    tpot = (e2el - ttft) / (out - 1) if out > 1 else 0.0
    good += (ttft <= 2.0 and tpot <= 0.1)   # bool 相加就是计数
print(good, good / d["duration"], d["request_goodput"])
```

### 4. 百分位与均值

- `P50` 就是中位数；`mean` 和 `median` 不一定相等（c=4 的 mean TTFT 2,348ms < P50 2,914ms，分布左偏）。
- `P99` 是排序后的第 99 百分位，不是“最慢的那条”，也不等于最大值。
- 百分位是**逐指标**算的：TTFT 的 P99 和 TPOT 的 P99 来自不同的请求。
- **百分位不能相加**：`queue P99 + prefill P99` 不等于 `(queue+prefill) P99`；要先把同一请求的两项相加，再对和算 P99。

### 5. GPU 与服务端指标

- `utilization.gpu`：采样窗口内有 kernel 在跑的时间占比，**不是 SM 占用率**。100% 只说明“一直有活干”，不说明效率高；功耗墙下会看到 100% + 低 clock。
- 采样：`nvidia-smi` 每秒一次；每轮的 util 取该轮 `[date - duration, date]` 窗口内的均值和 P95。
- `power.draw` / `power.limit` / `clocks.sm`：判断是否被功耗墙限制；`SW Power Cap: Active` 就是限功耗。
- `vllm:num_preemptions_total`：Prometheus counter，压测前后相减；>0 说明 KV cache 不够，序列被换出/重算。
| 字段 | 哪一侧 | 含义 | 单位 |
|---|---|---|---|
| `queue_times` | 客户端 bench | 等待并发槽位、还没发出去的时间 | 秒 |
| `server_queue_times` | 服务端 | 调度器排队，请求还没被调度 | 秒 |
| `server_ttfts` | 服务端 | 从被调度到首 token，含 chunked prefill 的多步调度 | 秒 |
| `ttfts` | 客户端 | 从发出请求到收到首个流式 token | 秒 |

同一请求近似：

```
client_ttft ≈ server_queue_time + server_ttft + 前端/网络开销
```

前端开销包括 tokenization、chat template、multimodal 预处理、detokenization、传输。残差不要硬塞进 prefill。

`--enable-per-request-metrics` 只额外提供 `server_queue_times` / `server_ttfts` 这两个 per-request 字段（仅 `openai`、`vllm`、`openai-chat` backend 有；拿不到时为 `null`）。它**不**提供 GPU util/power，也不改变 nvidia-smi 的指标；而且会加服务端 CPU 开销，尤其高并发时，所以只用于诊断跑，不用于 headline。

### 6. 指标来源：vLLM vs nvidia-smi

| 指标 | 谁产生 | 怎么拿 |
|---|---|---|
| 客户端 TTFT / TPOT / ITL / E2EL | `vllm bench serve`（客户端测） | JSON 的 `ttfts` / `tpots` / `itls` / `latencies`，或 `p*_*_ms` |
| request / output / total throughput | `vllm bench serve`（客户端算） | `request_throughput` / `output_throughput` / `total_token_throughput` |
| goodput、达标比例 | `vllm bench serve` 后处理 | `request_goodput`；比例自己除 |
| P50/P95/P99、mean/median | `vllm bench serve` 后处理 | `p50_*` / `mean_*` 等 |
| `server_queue_times` / `server_ttfts` | **vLLM 服务端**（需 opt-in） | 启动加 `--enable-per-request-metrics`，bench JSON 里的两个数组（秒） |
| 抢占次数 | **vLLM `/metrics`** | `vllm:num_preemptions_total` |
| running / waiting 请求数 | **vLLM `/metrics`** | `vllm:num_requests_running` / `vllm:num_requests_waiting` |
| KV cache 使用率 | **vLLM `/metrics`** | `vllm:gpu_cache_usage_perc`（0–1，只是 KV 块） |
| prefix cache 命中率 | **vLLM 日志 / `/metrics`** | 日志 `Prefix cache hit rate`，或 prefix cache counters |
| 模型加载耗时、KV cache 大小、最大并发 | **vLLM 启动日志** | `grep "Loading model\|GPU KV cache size\|Maximum concurrency"` |
| GPU 利用率 | **nvidia-smi / NVML** | `utilization.gpu` |
| 显存占用 | **nvidia-smi / NVML** | `memory.used` |
| 功耗、功耗上限 | **nvidia-smi / NVML** | `power.draw` / `power.limit` |
| 温度 | **nvidia-smi / NVML** | `temperature.gpu` |
| SM 频率 | **nvidia-smi / NVML** | `clocks.sm` |
| driver / Max CUDA / compute cap | **nvidia-smi / NVML** | `driver_version` / 右上角 CUDA Version / `compute_cap` |

容易混的两组：

- `utilization.gpu`（nvidia-smi）≠ `vllm:gpu_cache_usage_perc`（vLLM）。前者是“有 kernel 在跑的时间占比”，后者是“KV cache 块用了多少”。
- 客户端 TTFT ≠ `server_ttfts`。前者从请求发出算起，包含排队/前端/网络；后者从服务端调度算起。

生产里不要长期 `nvidia-smi` 轮询，用 **DCGM exporter + Prometheus + Grafana**；vLLM 的指标直接抓 `/metrics`。

### 7. 客户端指标怎么抓

`vllm bench serve` **不会**把客户端指标暴露成 HTTP 接口；它只写两个地方：

1. **stdout**：结束时打印的汇总表，给人看；
2. **JSON 文件**：加 `--save-result` 才会写，机器读；再加 `--save-detailed` 才有 per-request 数组。

推荐这样跑：

```bash
vllm bench serve \
  ... \
  --save-result --save-detailed \
  --result-dir ./results \
  --result-filename "d1-c${C}-$(date +%Y%m%d-%H%M%S).json" \
  --metadata gpu=l4-24gb vllm="$VLLM_VERSION" concurrency="$C" n="$N" \
  2>&1 | tee "./results/d1-c${C}-stdout.log"
```

- `--save-result`：写汇总 JSON（没有它，终端一关就没了）；
- `--save-detailed`：写入 `ttfts`、`latencies`、`output_lens` 等 per-request 数组，文件会大很多；
- `--result-dir` / `--result-filename`：输出路径和文件名；
- `--append-result`：追加到已有 JSON，适合分段跑；
- `--disable-tqdm`：关进度条，stdout 日志更干净；
- `tee`：同时保留人类可读的汇总，方便回看。

JSON 字段分组：

| 组 | 字段 |
|---|---|
| 汇总 | `completed`、`failed`、`duration`、`request_throughput`、`output_throughput`、`total_token_throughput`、`request_goodput` |
| 延迟汇总 | `mean_*`、`median_*`、`p50_*`、`p95_*`、`p99_*`（TTFT/TPOT/ITL/E2EL） |
| 逐请求 | `ttfts`、`latencies`、`output_lens`、`input_lens`、`start_times`、`generated_texts` |
| 其他 | `itls`（所有请求的 gap **展平**成一个列表）、`errors`、`metadata`、`date`（结束时间） |

注意：没有 `tpots` 数组；TPOT 要用 `latencies`、`ttfts`、`output_lens` 逐条重算。`itls` 是展平的，不能直接和 `ttfts` 一一对应。

批量读取：

```python
import json, glob

for f in sorted(glob.glob("results/d1-c*.json")):
    d = json.load(open(f))
    if "concurrency" not in d:      # 跳过 diagnostic 等
        continue
    print("%-40s c=%2s n=%4s out=%6.1f TTFT p99=%7.0f TPOT p95=%6.1f goodput=%.4f" % (
        f.split("/")[-1], d["concurrency"], d["num_prompts"],
        d["output_throughput"], d["p99_ttft_ms"], d["p95_tpot_ms"],
        d["request_goodput"]))
```

如果忘了 `tee`，但还在 tmux 里，可以事后抓屏：

```bash
tmux capture-pane -p -t ssh_tmux:2 -S -300 > /workspace/results/client-stdout.log
```

不过 JSON 才是权威来源，stdout 只用于人看。

### 8. 常见误读

| 误读 | 正确理解 |
|---|---|
| goodput 是百分比 | 是 req/s；百分比要除以 request_throughput |
| goodput 从 P95 算 | 逐请求 AND 判定，和百分位无关 |
| output tok/s 包含 prefill | 不包含；total token throughput 才包含输入 |
| TTFT 就是 prefill 时间 | 闭路压测里还包含服务端排队 |
| P99 可以相加 | 先逐请求相加，再对和算 P99 |
| duration 是延迟之和 | 是墙钟时长，包含排队和尾部 |
| mean 等于 P50 | 不一定；分布偏斜时会差很多 |

## 附：KV cache 与并发估算

以 Qwen3-8B（36 层、8 个 KV head、head_dim 128、FP16 KV）为例：

```
每 token KV = 2(K,V) × 36 层 × 8 KV head × 128 × 2 B
            = 147,456 B = 144 KiB
每个 block（默认 16 token）= 147,456 × 16 = 2.25 MiB
91,648 tokens = 5,728 blocks ≈ 12.6 GiB
```

vLLM 日志里的两个数：

- `GPU KV cache size: 91,648 tokens`：按 `gpu-memory-utilization` 扣掉权重和激活后，剩下的显存能放多少 KV token；
- `Maximum concurrency for 8,192 tokens per request: 11.19x`：`91,648 / 8,192 = 11.19`，假设每条请求都吃满 8k 上下文。

按我们实际的 1024 输入 + 256 输出：

```
每条请求 = 1,280 tokens = 80 blocks
91,648 / 1,280 = 71.6  → KV 上限约 71 条
但 --max-num-seqs 64 先生效 → 实际最多 64 条
64 × 1,280 = 81,920 < 91,648 → 所以 c=64 抢占为 0
```

**这三个“最大并发”要分清**：KV 上限（71）、服务端 batch 上限（64）、SLO 安全并发（见下）。

Goodput 的定义、逐条判定和完整计算示例见上一节。这里只记结论：SLO 是 TTFT ≤ 2,000 ms 且 TPOT ≤ 100 ms，c=1 全部达标、c=4 25%、c=16 0.2%、c=64 0%，所以这台 40W L4 的 SLO 安全容量约 **0.077 req/s**（c=1），而不是 KV 上限 71。换 SLO（比如只看 P95、TPOT 放宽到 150ms）容量会变，必须写清口径。

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
