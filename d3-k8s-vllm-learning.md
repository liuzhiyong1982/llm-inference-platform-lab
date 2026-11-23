# D3 学习文档：k3s + vLLM 的冷启动、扩缩容与驱逐

> 状态：**draft（2026-11-23），尚未执行**。执行后把实测数字补进 §7–§9、§16，并在 README 增加 D3 结果小节。
>
> 计划中的位置：`ai-cloud-native-week-plan.md` §4 Q1 的 **B 线 artifact**；B 线讲法见该文件 §3「D3 / D5 的 B 线讲法」。执行后同时回填该文件 §5 的“三个 B 线数”。
>
> 性质：学习文档 + 可执行 lab，不是 D1/D2 那种逐命令 runbook。D1/D2 回答“单机多快”，D3 回答“把它放进 K8s 后，启动、扩容、驱逐各要付多少秒”。
>
> 硬约束：**不在共享 UAT 集群 `uat-mobility-aks-01` 上做实验**。用自己租的/本地的单机 GPU；所有对比同机、同模型、同输入/输出长度、同 SLO。
>
> 环境：本地 Linux 或 **Vast GPU VM**（你已在 Vast GPU VM 上跑过 k8s）；Vast 普通容器实例没有 systemd/cgroup，不要用。

---

## 0. 先看结论（执行前先记住）

1. **K8s 不会让推理变快。** 它提供的是声明式发布、服务发现、调度、扩缩容；代价是镜像拉取、权重分发、网络转发、调度排队四层开销。
2. **冷启动不等于“启动到 ready 69s”。** D1 的 69s 是进程启动到 API ready，其中 `Model loading took ... 7.72s`、`init engine ... 21.72s`；完整冷启动还要加镜像拉取和权重下载（5.7GB）。不分阶段测，数字不可比。
3. **单卡上 KEDA 1→2 必然 Pending。** `nvidia.com/gpu` 是整数资源，device plugin 不会把一张 L4 切成两张；这不是 KEDA 的 bug，是 GPU 调度模型的边界。
4. **scale-to-zero 对 chat 基本不可用。** 70s 级冷启动会打穿 TTFT SLO；它只适合异步、批处理、低频请求。KEDA 缩到 0 也不会替你排队——请求会直接失败。
5. **驱逐要三层配合。** Endpoint 摘除 → `preStop` 等传播 → `SIGTERM` 后 vLLM `--shutdown-timeout` 排空；`terminationGracePeriodSeconds` 必须大于 `preStop + shutdown-timeout`，否则 SIGKILL 会把排空窗口直接截断。

---

## 1. 学习目标与验收

D3 只测三个数（“能部署”没有区分度）：

| 实验 | 要回答的问题 | 产出 |
|---|---|---|
| **冷启动** | 镜像已缓存时，权重现拉 vs 节点本地缓存，差多少秒？时间花在哪一段？ | 分阶段秒数表（调度 / 镜像 / 权重 / 加载 / Ready） |
| **扩容曲线** | KEDA 在队列堆积时扩 1→N，P99 是先恶化还是立刻变好？新副本多久 Ready？ | 时间序列：queue、replicas、TTFT P99 |
| **驱逐** | 删一个副本时，在途请求是完成还是失败？pod 多久退出？ | 成功/失败请求数、最大延迟、Terminating 时长 |

验收清单：

- [ ] k3s 单节点起来，`nvidia.com/gpu` 可分配；
- [ ] vLLM Deployment Ready，`/v1/models` 和一次 completion 成功；
- [ ] 冷启动表：cold / warm（可选 image-cold），每段有秒数；
- [ ] KEDA 扩容证据：单卡 1→2 的 Pending 事件，或 2 卡 1→2 的 P99 曲线；
- [ ] 驱逐实验：无排空 vs 有排空的成功/失败对比；
- [ ] 一段带数字的归因结论；
- [ ] 结果、manifest、日志进 git。

### 1.1 3 小时最小路径 vs 完整路径

| 阶段 | 最小路径（单卡，3h） | 完整路径（2 卡，4–5h） |
|---|---|---|
| 读 §2–§4 概念 | 30 min | 30 min |
| k3s + GPU runtime + device plugin | 45 min | 45 min |
| 模型缓存 + Deployment + Service | 30 min | 30 min |
| 冷启动 cold / warm | 30 min | 45 min |
| KEDA | 30 min（0→1 + 1→2 Pending） | 60 min（真实 1→2 曲线） |
| 驱逐 | 15 min | 30 min |
| 记录 + commit | 30 min | 30 min |

> 3h 是最小路径；如果只能租一张卡，接受“1→2 Pending”这个结果，它本身就是 D3 的核心结论之一。真实扩容曲线留给 2 卡（也可以和 D4 的 2×L4 合并）。
>
> **3h 不够时按这个顺序砍：** image-cold → scale-to-zero → PDB → 2 卡曲线 → 驱逐的“有排空”对照。**不要砍 cold/warm 和 1→2 Pending**：前者是 B 线 artifact 的核心数字，后者是单卡 GPU 调度的核心结论。

### 1.2 B 线学习目标（从 D3 起）

D3 不只是 A 线的“平台支撑”，也是 B 线案例 1。三个数之外，还要带走：

- **交付链路**：driver → nvidia-container-toolkit → k3s containerd → device plugin → RuntimeClass → Pod；能解释每一层坏了会怎样。
- **模型分发**：hostPath/local PV vs 镜像内置 vs 对象存储；冷启动、回滚、节点亲和性的取舍。
- **弹性**：KEDA/HPA 的信号、扩容延迟、单卡容量边界；为什么 CPU HPA 是错的。
- **运维**：startup/readiness/liveness、PDB、优雅驱逐、故障处置。
- **成本与多租户**：每副本 `$/h`、namespace/label 规范、Q2 chargeback 的埋点。

B 线验收：§16 至少 1 条简历 bullet 能脱稿讲 10 分钟，并接住 §12 的 B 线四问。

---

## 2. 环境选择：先解决“k3s 跑在哪”

| 方案 | 可行性 | 代价 | 建议 |
|---|---|---|---|
| **本地 Linux + NVIDIA GPU** | 最高 | 需要 root、能装内核模块/容器运行时 | **首选**；最接近生产，调试成本最低 |
| **Vast.ai GPU VM** | 高（你已在 Vast GPU VM 上跑过 k8s） | 按小时计费；必须是 VM/privileged，普通容器实例不行 | **首选之一**；复用你上次成功的 image/template，先做 §5.0 的确认 |
| **云 GPU VM**（Azure/AWS/GCP 单卡） | 高 | 按小时计费；注意配额和 GPU 型号 | 次选；记录 `power.limit` 和驱动版本 |
| **Vast.ai 普通容器实例** | 低 | 无 systemd/cgroup 权限 | 不要用；换 VM |
| **共享 UAT AKS `uat-mobility-aks-01`** | — | 污染共享环境、触发 Coder→Reviewer SOP、花公司钱 | **禁止** |

单卡 vs 2 卡：

| | 单卡 | 2 卡 |
|---|---|---|
| 冷启动 | 可以测 | 可以测 |
| KEDA 0→1 | 可以测 | 可以测 |
| KEDA 1→2 | 第二个 Pod 会 `Pending`（`Insufficient nvidia.com/gpu`） | 可以测真实扩容曲线 |
| 驱逐 | 可以测，但删掉唯一副本会短暂 0 可用 | 可以测 PDB / 滚动更新 |
| 成本（L4 容器 / 24GB VM） | `$0.2611/h` / 约 `$0.41–0.48/h` | `$0.5111/h`（GPU ×2 + 存储） |

> 机制可以用 CPU + 小模型（如 `Qwen3-0.6B`）练，但**冷启动秒数只能用目标 GPU 测**；不要把 CPU 数字写进作品集。

> 2026-11-23 实测：Vast 上搜不到 L4 VM（`gpu_name=L4 vms_enabled=true` 返回空），24GB VM 只有 3090/4090/5090。用 3090/4090 时，D3 只做内部 cold/warm 对比，**不要**把吞吐或冷启动秒数和 D1/D2 的 L4 数字直接比。

### 2.1 在 Vast 租一台 GPU VM（CLI）

k3s 需要 systemd/cgroup；**普通容器实例不行**，必须选 `vms_enabled=true` 的 VM。下面命令按顺序执行。

**0）账号与 SSH key：**

```bash
vastai show user -q
vastai show ssh-keys

# 没有 key 时，把路径换成你的公钥
vastai create ssh-key "$(cat ~/.ssh/id_ed25519.pub)"
```

**1）搜 VM offer：**

```bash
# L4 VM：先试；当前返回空是正常的
vastai search offers -n \
  'gpu_name=L4 num_gpus=1 rentable=true vms_enabled=true cuda_vers>=13.0 disk_space>=100 inet_down>=500 reliability>=0.95' \
  -o 'dph' --storage 130 --limit 10

# 24GB VM 兜底：3090/4090/5090
vastai search offers -n \
  'num_gpus=1 gpu_ram>=24 rentable=true vms_enabled=true cuda_vers>=13.0 disk_space>=100 inet_down>=500 reliability>=0.98' \
  -o 'dph' --storage 130 --limit 10
```

挑 `R >= 0.98`、`Net_down >= 500`、`Disk >= 100`、`Max_Days >= 1`、`ports >= 1` 的。**必须用 `vms_enabled=true` 查询返回的 offer ID**；同一个 GPU 的 VM 和容器 offer ID 不同，拿容器 ID 建 VM 会失败。

**2）创建 VM：**

```bash
vastai create instance <OFFER_ID> \
  --template_hash 2c18cabd8f2f0525c2ff8446f5d4e063 \
  --disk 130 \
  --label d3-k3s-vm \
  --cancel-unavail
```

模板是官方 `Ubuntu 22.04 VM`（`vm=True`、SSH、自带 CUDA/Docker），自带 `vms_enabled` 过滤。不要用 `vllm/vllm-openai` 镜像建 VM：那是容器模板，不会给你 systemd。

如果建出来不是 VM（下一步 `ps -p 1` 不是 `systemd`），destroy 后走 API：

```bash
curl -s -X PUT "https://console.vast.ai/api/v0/asks/<OFFER_ID>/" \
  -H "Authorization: Bearer $(cat ~/.config/vastai/vast_api_key)" \
  -H "Content-Type: application/json" \
  -d '{"template_hash_id":"2c18cabd8f2f0525c2ff8446f5d4e063","vm":true,"disk":130,"runtype":"ssh_direct","label":"d3-k3s-vm","cancel_unavail":true}'
```

**3）SSH 与 VM 确认：**

```bash
vastai show instances
vastai ssh-url <ID>

# ssh-url 输出形如 ssh://root@host:port；换成：
ssh -p <PORT> root@<HOST>

# 在 VM 里执行：
ps -p 1 -o comm=                 # 必须是 systemd
systemctl is-system-running      # running/degraded 都算起来了
stat -fc %T /sys/fs/cgroup       # 期望 cgroup2fs
nvidia-smi
df -h /
```

`ps -p 1` 不是 `systemd` 就说明拿到的是容器，立刻 `vastai destroy instance <ID> -y`，不要继续装 k3s。

**4）计费与清理：**

```bash
vastai show instances
vastai stop instance <ID>        # 保留磁盘，继续收存储费
vastai destroy instance <ID> -y  # 结果 scp 回本地后再执行
```

2026-11-23 实测：3090 VM 约 `$0.41/h`（含 130GB 盘），4090 约 `$0.48/h`；3h 约 `$1.2–1.5`。比 D2 的 L4 容器贵，但在 `$15` 预算内。

开工前记录：

```bash
# 目的：这些是后面所有数字的可比性前提
nvidia-smi --query-gpu=name,memory.total,driver_version,power.limit --format=csv,noheader
nvidia-container-toolkit --version 2>/dev/null || nvidia-ctk --version
uname -r
df -h /var/lib
```

---

## 3. 先修概念：面试会追问的六件事

### 3.1 一次请求在 K8s 里经过什么

```text
client
  → Service (ClusterIP)         # kube-proxy / iptables 选一个 Endpoint
  → Pod (vLLM)                  # 容器网络 namespace
  → vLLM OpenAI API :8000
```

- `Service` 不是进程，是一组 iptables/ipvs 规则；它多一跳，但换来稳定的虚拟 IP 和负载均衡。
- `hostNetwork: true` 让 Pod 直接用宿主机网络，少一层 NAT；代价是端口冲突、调度约束变多。
- 单副本时“负载均衡”没有意义；D3 的 Service 主要是为了练 Endpoint 摘除和后续多副本。

### 3.2 GPU 是怎么被调度的

```text
NVIDIA driver (host)
  → nvidia-container-toolkit / runtime
  → k3s containerd
  → NVIDIA device plugin (DaemonSet)
  → Node allocatable: nvidia.com/gpu: 1
  → Pod resources.limits: nvidia.com/gpu: 1
  → scheduler 绑定节点 → kubelet 调 containerd → 容器里看到 GPU
```

关键点：

- **device plugin 只做整数分配**：一张 L4 只能给一个 Pod（除非 MIG / time-slicing / MPS / DRA）。
- `nvidia.com/gpu` 要写在 `limits` 里；只写 `requests` 可能拿不到设备。两者同时写时必须相等。
- Pod 里能不能看到 GPU，取决于 runtime（`runtimeClassName: nvidia`）和 device plugin 是否 Ready；两者缺一不可。
- MIG 把 A100/H100 切成固定切片；time-slicing 让多个 Pod 共享同一张卡但互相抢算力；MPS 做进程级并发；DRA 是 K8s 新的设备分配 API。**对 LLM 推理，time-slicing 会直接破坏 TPOT/ITL，不要把它当“免费切卡”。**

### 3.3 冷启动的四个阶段

| 阶段 | 发生什么 | 典型量级 | 怎么测 |
|---|---|---|---|
| 调度 | scheduler 找有 GPU 的节点 | ms–s | `PodScheduled` condition 时间 |
| 镜像拉取 | containerd 拉 vLLM 镜像（数 GB） | 0s（已缓存）–几分钟 | `containerStatuses[].state.running.startedAt` 之前 |
| 权重下载 | initContainer / 启动脚本拉 5.7GB AWQ | 几十秒–几分钟 | init container 的 `startedAt`/`finishedAt` |
| 模型加载 + 引擎初始化 | 读权重、KV profiling、CUDA graph capture、API server 起来 | D1 启动到 ready 约 **69s**（其中 model loading 7.72s、init engine 21.72s） | 主容器 `startedAt` → `Ready=True` |

> D1 的 69s 是“进程启动到 API ready”（权重加载约 7.7s + 引擎初始化约 21.7s + 其余编译/启动开销），不含镜像拉取和权重下载。把 69s 当完整冷启动，会低估 2–5 倍。

### 3.4 startupProbe / readinessProbe / livenessProbe

| 探针 | 失败会怎样 | D3 用法 |
|---|---|---|
| `startupProbe` | 容器被重启 | 保护 60–120s 的模型加载；`failureThreshold` 给够 |
| `readinessProbe` | Pod 从 Service Endpoint 摘除，不重启 | `/health` 200 才接流量 |
| `livenessProbe` | 容器被重启 | 只在启动成功后开始；不要用它等模型加载 |

常见错误：只配 `livenessProbe` + `initialDelaySeconds: 60`，模型加载 90s 时被重启，日志出现 `KeyboardInterrupt: terminated`。正确做法是 `startupProbe` 管启动，`livenessProbe` 管运行中卡死。

### 3.5 HPA vs KEDA vs Kueue

| 组件 | 管什么 | 信号 | 典型用途 |
|---|---|---|---|
| HPA | 副本数 | CPU / memory / custom metrics | 无状态 Web 服务 |
| KEDA | 副本数（可到 0） | 事件源 / Prometheus 查询 | 队列驱动、vLLM 的 `num_requests_waiting` |
| Kueue | 排队与准入 | ClusterQueue 配额、优先级 | 多团队抢 GPU、批处理 Job |

- **CPU HPA 对 vLLM 是错的**：GPU 打满时 CPU 可能只有 20%，CPU 利用率与排队长度不相关；扩副本要按**队列深度 / KV 使用率 / TTFT**。
- KEDA 不替代 HPA，它生成一个 HPA，把 Prometheus 查询结果喂给 HPA。
- Kueue 不扩副本，它决定“这个 Job/Deployment 能不能现在拿 GPU”；D5 再展开。

### 3.6 驱逐的完整顺序

```text
kubectl delete pod / rollout / drain
  → Pod 标记 Terminating，从 Service Endpoints 摘除（不再接新请求）
  → 执行 preStop hook（例如 sleep 15s，等 kube-proxy/网关收敛）
  → 向容器 PID 1 发 SIGTERM
  → vLLM：
       默认：立即 abort 在途请求并退出
       --shutdown-timeout N：继续服务在途请求，最多 N 秒
  → 进程退出；超过 terminationGracePeriodSeconds 则 SIGKILL
```

三个数必须满足：

```text
terminationGracePeriodSeconds > preStop 秒数 + --shutdown-timeout + 进程清理余量
```

例：`preStop 15s` + `--shutdown-timeout 90s` + 15s 余量 = `terminationGracePeriodSeconds: 120`。

---

## 4. 目标架构

```text
                    ┌─────────────────────────────────────────┐
                    │ k3s single node (GPU host)              │
                    │                                         │
  kubectl/bench ──→ │ Service (ClusterIP :8000)               │
                    │      │                                  │
                    │      ▼                                  │
                    │ Deployment vllm-qwen3-8b (replicas 1)   │
                    │   ┌───────────────────────────────┐     │
                    │   │ Pod                           │     │
                    │   │  initContainer: weight check  │     │
                    │   │  vLLM :8000                   │     │
                    │   │  hostPath /var/lib/models ────┼──┐  │
                    │   └───────────────────────────────┘  │  │
                    │                                      │  │
                    │ /var/lib/models/Qwen3-8B-AWQ ←───────┘  │
                    │                                         │
                    │ NVIDIA device plugin → nvidia.com/gpu   │
                    │ Prometheus ← ServiceMonitor /metrics    │
                    │ KEDA → HPA → Deployment                 │
                    └─────────────────────────────────────────┘
```

---

## 5. Lab 0：k3s + GPU runtime + device plugin

### 5.0 先检查“能不能跑 k3s”

先按 §2.1 租 VM。你以前在 Vast 的 GPU VM 上跑过 k8s，说明 Vast 这条路可行；但 Vast 也有普通容器实例，租完先在**当前实例**上确认它是 VM/privileged：

```bash
# 目的：确认有 systemd / cgroup v2 / 能写 /var/lib/rancher
ps -p 1 -o comm=
systemctl is-system-running 2>/dev/null || true
stat -fc %T /sys/fs/cgroup
sudo test -w /var/lib && echo "var-lib writable"
```

> 如果上次用的是 k3s，直接复用同一版安装命令，并记录 `k3s --version`、实例 image/template、GPU 型号和关键参数（`--disable traefik`、`--flannel-backend` 等）。不要在 D3 里换发行版，先把冷启动数字测出来。

- `ps -p 1` 不是 `systemd`（例如是 `tini`/`bash`），k3s 的 systemd 服务方式就不适用；可以试 `k3s server` 前台运行，但重启管理要自己做。
- cgroup 不是 `cgroup2fs`，k3s/kubelet 可能起不来。
- 如果检查失败，换 Vast GPU VM 或本地/云 VM，不要在 Vast 普通容器里硬扛。

### 5.1 安装 k3s

```bash
# 目的：单节点 k3s；版本固定为 2026-11-23 的 stable，避免版本漂移
curl -sfL https://get.k3s.io | sudo INSTALL_K3S_VERSION=v1.37.2+k3s1 sh -s - --write-kubeconfig-mode 644

# 目的：确认节点 Ready（k3s 自带 kubectl）
sudo k3s kubectl get nodes -o wide
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown "$USER" ~/.kube/config
kubectl get nodes
```

> 复用上次成功的 k3s 版本时，把 `INSTALL_K3S_VERSION` 换成你记录的那版；版本不同，冷启动数字不可比。把 `k3s --version` 记进结果。

### 5.2 让 k3s 识别 NVIDIA runtime

k3s 会自动探测 PATH 里的 `nvidia-container-runtime`；装好 toolkit 后重启 k3s 即可。默认 runtime 仍是 `runc`，所以 Pod 要显式写 `runtimeClassName: nvidia`（或者给 k3s 加 `--default-runtime nvidia`）。

```bash
# 目的：安装 NVIDIA container toolkit（Ubuntu/Debian）
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# 目的：重启 k3s，让它重新探测 runtime
sudo systemctl restart k3s

# 目的：确认 containerd 配置里出现 nvidia
grep -n nvidia /var/lib/rancher/k3s/agent/etc/containerd/config.toml

# 目的：确认 RuntimeClass 存在；没有它，runtimeClassName: nvidia 的 Pod 会卡住
kubectl get runtimeclass nvidia
```

如果 `grep` 没有任何输出：

1. 确认 `which nvidia-container-runtime` 有路径；
2. 确认它在 k3s 服务的 PATH 里（`/usr/bin` 或 `/usr/local/bin`）；
3. 再重启 k3s；仍不行就查 `journalctl -u k3s -n 100`。

> 云 GPU 镜像通常已带 driver + toolkit；先 `nvidia-ctk --version` 确认，缺了再按 NVIDIA 官方 repo 安装。`nvidia-container-toolkit` 包会带上 `nvidia-container-runtime`，装完用 `which nvidia-container-runtime` 复核。
>
> 不要手写整份 `config.toml` 覆盖 k3s 生成的文件；k3s 升级/重启会重新渲染。要用模板就用官方 `config-v3.toml.tmpl` 的 `{{ template "base" . }}` 方式。

### 5.3 安装 NVIDIA device plugin

```bash
# 目的：把 GPU 暴露成 nvidia.com/gpu 扩展资源；版本按 release 页核对
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.18.0/deployments/static/nvidia-device-plugin.yml

# 目的：static manifest 没有写 runtimeClassName；k3s 默认 runtime 是 runc，
# 不补这一行，device plugin 可能看不到 GPU（allocatable 一直是 0）
kubectl -n kube-system patch ds nvidia-device-plugin-daemonset --type merge \
  -p '{"spec":{"template":{"spec":{"runtimeClassName":"nvidia"}}}}'

kubectl -n kube-system rollout status ds/nvidia-device-plugin-daemonset --timeout=180s

# 目的：确认 allocatable 里有 1 张卡
kubectl get node -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}{"\n"}'
```

> k3s 会为检测到的 NVIDIA runtime 创建 `RuntimeClass/nvidia`；static manifest 本身不带 `runtimeClassName`，所以必须 patch。用 Helm 装 GPU Operator 时这一步由 chart 的 `runtimeClassName` 完成。

### 5.4 GPU smoke test

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: gpu-test
spec:
  restartPolicy: Never
  runtimeClassName: nvidia
  containers:
  - name: cuda
    image: nvidia/cuda:12.4.1-base-ubuntu22.04
    command: ["nvidia-smi"]
    resources:
      limits:
        nvidia.com/gpu: 1
EOF

kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/gpu-test --timeout=120s
kubectl logs gpu-test
kubectl delete pod gpu-test
```

看到 `nvidia-smi` 输出和 L4 型号，才说明 runtime + device plugin + scheduling 三层都通了。

---

## 6. Lab 1：模型缓存 + vLLM Deployment + Service

### 6.1 节点本地权重缓存

D3 的核心对比是“权重现拉 vs 节点缓存”，所以缓存必须放在**宿主机**上，而不是 `emptyDir`（Pod 重建就没了）。

```bash
# 目的：宿主机缓存目录；后面用 hostPath 挂进 Pod
sudo mkdir -p /var/lib/models
sudo chmod 777 /var/lib/models
```

第一次下载（warm 基线）可以用一个一次性 Job：

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: model-download
spec:
  backoffLimit: 2
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: download
        image: vllm/vllm-openai:v0.34.0
        env:
        - name: HF_XET_HIGH_PERFORMANCE
          value: "1"
        command: ["python3", "-c"]
        args:
        - |
          from huggingface_hub import snapshot_download
          snapshot_download("Qwen/Qwen3-8B-AWQ", local_dir="/models/Qwen3-8B-AWQ")
        volumeMounts:
        - name: models
          mountPath: /models
      volumes:
      - name: models
        hostPath:
          path: /var/lib/models
          type: DirectoryOrCreate
EOF

kubectl wait --for=condition=complete job/model-download --timeout=30m
kubectl logs job/model-download --tail=20
du -sh /var/lib/models/Qwen3-8B-AWQ
```

> 5.7GB；按 100MB/s 约 1 分钟，按 20MB/s 约 5 分钟。这个时间就是“权重现拉”的主要成本。

### 6.2 Deployment + Service

把下面保存为 `k8s/vllm.yaml`。关键点都在注释里：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-qwen3-8b
  labels:
    app: vllm
    team: platform
spec:
  replicas: 1
  # 单卡 + 单副本：Recreate 避免 RollingUpdate 先起一个 Pending 的第二个 Pod
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: vllm
  template:
    metadata:
      labels:
        app: vllm
        team: platform
        model: qwen3-8b
    spec:
      runtimeClassName: nvidia
      terminationGracePeriodSeconds: 120
      initContainers:
      - name: fetch-weights
        image: vllm/vllm-openai:v0.34.0
        imagePullPolicy: IfNotPresent
        env:
        - name: HF_XET_HIGH_PERFORMANCE
          value: "1"
        command: ["/bin/sh", "-c"]
        args:
        - |
          set -eu
          if [ -f /models/Qwen3-8B-AWQ/config.json ] && \
             find /models/Qwen3-8B-AWQ -maxdepth 1 -name '*.safetensors' | grep -q .; then
            echo "weights cached"
            exit 0
          fi
          python3 -c 'from huggingface_hub import snapshot_download; snapshot_download("Qwen/Qwen3-8B-AWQ", local_dir="/models/Qwen3-8B-AWQ")'
        volumeMounts:
        - name: models
          mountPath: /models
      containers:
      - name: vllm
        image: vllm/vllm-openai:v0.34.0
        imagePullPolicy: IfNotPresent
        # 直接 exec vllm，保证 PID 1 能收到 SIGTERM；不要用 sh -c 包一层
        command: ["vllm", "serve"]
        args:
        - "/models/Qwen3-8B-AWQ"
        - "--served-model-name"
        - "qwen3-8b"
        - "--max-model-len"
        - "8192"
        - "--gpu-memory-utilization"
        - "0.90"
        - "--max-num-seqs"
        - "64"
        - "--shutdown-timeout"
        - "90"
        - "--disable-log-requests"
        ports:
        - name: http
          containerPort: 8000
        resources:
          requests:
            cpu: "8"
            memory: "32Gi"
            nvidia.com/gpu: 1
          limits:
            cpu: "8"
            memory: "32Gi"
            nvidia.com/gpu: 1
        startupProbe:
          httpGet:
            path: /health
            port: http
          periodSeconds: 5
          failureThreshold: 120      # 最多等 10 分钟
        readinessProbe:
          httpGet:
            path: /health
            port: http
          periodSeconds: 5
          failureThreshold: 3
        livenessProbe:
          httpGet:
            path: /health
            port: http
          periodSeconds: 10
          failureThreshold: 6
        lifecycle:
          preStop:
            exec:
              # 给 Endpoint 摘除/网关收敛留时间，再让 SIGTERM 进来
              command: ["/bin/sh", "-c", "sleep 15"]
        volumeMounts:
        - name: models
          mountPath: /models
        - name: shm
          mountPath: /dev/shm
      volumes:
      - name: models
        hostPath:
          path: /var/lib/models
          type: Directory
      - name: shm
        emptyDir:
          medium: Memory
          sizeLimit: "2Gi"
---
apiVersion: v1
kind: Service
metadata:
  name: vllm-qwen3-8b
  labels:
    app: vllm
spec:
  selector:
    app: vllm
  ports:
  - name: http
    port: 8000
    targetPort: http
  type: ClusterIP
```

> initContainer 用 `config.json` + 至少一个 `*.safetensors` 判断缓存完整，避免“下载中断但 config.json 已写入”导致 vLLM 启动失败。真要严格，可让 `snapshot_download` 每次都跑（完整缓存时它只做元数据校验）。
>
> B 线埋点：在 `template.metadata.labels` 里加 `team`/`model`，并把 Deployment 放到团队 namespace；D3 可以先单 namespace，但 Q2 的 chargeback 依赖这些 label。

应用并验证：

```bash
kubectl apply -f k8s/vllm.yaml
kubectl rollout status deploy/vllm-qwen3-8b --timeout=15m

kubectl get pod -l app=vllm -o wide
kubectl logs -l app=vllm --tail=30

# 目的：确认服务真的能推理
kubectl run curl-test --rm -it --restart=Never --image=curlimages/curl --command -- \
  curl -s http://vllm-qwen3-8b:8000/v1/models
```

从本机访问（二选一）：

```bash
# A. port-forward，简单
kubectl port-forward svc/vllm-qwen3-8b 8000:8000

# B. 直接 Pod IP（hostNetwork 时是节点 IP）
kubectl get pod -l app=vllm -o jsonpath='{.items[0].status.podIP}{"\n"}'
```

### 6.3 两个容易踩的坑

- **`command: ["/bin/sh", "-c", "vllm serve ..."]`**：SIGTERM 发给 shell，vLLM 收不到，驱逐时不会排空。要么直接 `command: ["vllm","serve"]`，要么 `exec vllm serve ...`。
- **`hostPath` 的权重只在这一个节点上**：多节点时 Pod 可能调度到没缓存的节点，冷启动又变成“现拉”。生产要用 node affinity、local PV，或共享存储/Model Streamer。

### 6.4 可选：hostNetwork 对比

复制一份 Deployment，改：

```yaml
spec:
  hostNetwork: true
  dnsPolicy: ClusterFirstWithHostNet
```

然后对比：

```bash
# Service 路径
vllm bench serve --host 127.0.0.1 --port 8000 ...
# Pod/节点 IP 路径（绕过 kube-proxy）
vllm bench serve --host <node-ip> --port 8000 ...
```

> 单副本才能用 `hostNetwork: true` + 8000 端口；多副本会端口冲突。这个对比只回答“网络多一跳值多少”，不要把它当生产默认。

记录 TTFT P50/P99。单节点上差距通常不大；这个实验的价值是让你能回答“K8s 的网络开销在哪”，而不是背一个固定毫秒数。

### 6.5 B 线加练：模型版本与回滚（可选，30 分钟）

B 线 JD 里的“模型交付”不只有冷启动，还有回滚。最小做法是把权重按版本目录存放，而不是覆盖同一个目录：

```text
/var/lib/models/
  Qwen3-8B-AWQ-v1/   # 当前
  Qwen3-8B-AWQ-v2/   # 新版本
```

把 §6.2 的 `args` 第一项改成 `$(MODEL_PATH)`，并加环境变量：

```yaml
spec:
  template:
    spec:
      containers:
      - name: vllm
        env:
        - name: MODEL_PATH
          value: /models/Qwen3-8B-AWQ-v1
        args:
        - "$(MODEL_PATH)"
        # 其余 args / image / resources 省略
```

> 主实验 §6.2 用的是字面路径 `/models/Qwen3-8B-AWQ`；做本节前先把 `args` 第一项改成 `$(MODEL_PATH)` 并加上面的 `env`，重新 `kubectl apply`。否则 `kubectl set env` 只改环境变量，模型路径不会变。

发布/回滚：

```bash
# 目的：准备两个版本目录（各 5.7GB；磁盘不够就只读本节，不做实测）
sudo mkdir -p /var/lib/models/Qwen3-8B-AWQ-v1 /var/lib/models/Qwen3-8B-AWQ-v2
sudo cp -a /var/lib/models/Qwen3-8B-AWQ/. /var/lib/models/Qwen3-8B-AWQ-v1/
sudo cp -a /var/lib/models/Qwen3-8B-AWQ/. /var/lib/models/Qwen3-8B-AWQ-v2/

# 目的：切到 v2
kubectl set env deploy/vllm-qwen3-8b MODEL_PATH=/models/Qwen3-8B-AWQ-v2
kubectl rollout status deploy/vllm-qwen3-8b --timeout=15m

# 目的：回滚到 v1
kubectl set env deploy/vllm-qwen3-8b MODEL_PATH=/models/Qwen3-8B-AWQ-v1
kubectl rollout status deploy/vllm-qwen3-8b --timeout=15m
```

> 不要在运行中的目录上覆盖权重：旧 Pod 可能还在读，新 Pod 可能读到半套文件；版本目录是回滚的前提。生产上还要配 node affinity/local PV，避免 Pod 调度到没有该版本权重的节点。

---

## 7. Lab 2：冷启动测量

### 7.1 测什么

| 场景 | 镜像 | 权重 | 目的 |
|---|---|---|---|
| **cold** | 已缓存 | 删除 `/var/lib/models/Qwen3-8B-AWQ` | 权重下载 + 模型加载 + 引擎初始化，最接近“新节点” |
| **warm** | 已缓存 | 保留 | 只测模型加载 + 引擎初始化 |
| **image-cold**（可选） | `sudo k3s crictl rmi docker.io/vllm/vllm-openai:v0.34.0` 删除镜像 | 保留 | 单独测镜像拉取 |

> 镜像引用名先用 `sudo k3s crictl images | grep vllm` 确认；不同 registry 前缀可能不同。
>
> 不要用 `emptyDir` 做 cold/warm 对比：Pod 一删缓存就没了，两次都是 cold，结论会错。

### 7.2 操作

```bash
# warm：权重已在宿主机
kubectl rollout restart deploy/vllm-qwen3-8b
kubectl rollout status deploy/vllm-qwen3-8b --timeout=15m

# cold：先缩到 0，等 Pod 真正退出，再删缓存
kubectl scale deploy/vllm-qwen3-8b --replicas=0
kubectl wait --for=delete pod -l app=vllm --timeout=180s
sudo rm -rf /var/lib/models/Qwen3-8B-AWQ
kubectl scale deploy/vllm-qwen3-8b --replicas=1
kubectl rollout status deploy/vllm-qwen3-8b --timeout=30m
```

### 7.3 分阶段拆解

`rollout status` 只给“总时间”。要拆阶段，读 Pod 的 condition 和 container status（需要 `jq`；没有就 `sudo apt-get install -y jq`）：

```bash
pod=$(kubectl get pod -l app=vllm -o jsonpath='{.items[0].metadata.name}')
kubectl get pod "$pod" -o json | jq -r '
  "created=\(.metadata.creationTimestamp)",
  "scheduled=\(([.status.conditions[]|select(.type=="PodScheduled")][0].lastTransitionTime))",
  "init_start=\(.status.initContainerStatuses[0].state.terminated.startedAt // "n/a")",
  "init_end=\(.status.initContainerStatuses[0].state.terminated.finishedAt // "n/a")",
  "main_start=\(.status.containerStatuses[0].state.running.startedAt)",
  "ready=\(([.status.conditions[]|select(.type=="Ready")][0].lastTransitionTime))"
'
```

如果 initContainer 使用了和主容器相同的 vLLM 镜像，`init_start - scheduled` 主要就是镜像拉取；`init_end - init_start` 是权重下载；`ready - main_start` 是模型加载 + 引擎初始化。

> 你的 manifest 里 initContainer 是“检查缓存，不存在才下载”。为了测 cold，必须确保 `rm -rf` 之后 initContainer 真的走了下载分支；看 `kubectl logs "$pod" -c fetch-weights`。

### 7.4 记录模板

| 场景 | 调度 (s) | 镜像 (s) | 权重下载 (s) | 模型加载+引擎 (s) | 总到 Ready (s) |
|---|---|---|---|---|---|
| cold | | | | | |
| warm | | | | | |
| image-cold（可选） | | | | | |

归因规则：

- **权重下载占比最大** → node-local cache / Model Streamer / 预热池；D1 的 5.7GB 是硬成本。
- **模型加载占比最大** → 量化、换更小模型、更快的本地盘、减少 `max-model-len`/`gpu-memory-utilization` 的 profiling 开销。
- **镜像拉取占比最大** → 预拉 DaemonSet、镜像缓存、减小镜像；`imagePullPolicy: IfNotPresent`。
- **调度占比最大** → GPU 不够/亲和性太严；K8s 不会凭空造卡。

---

## 8. Lab 3：KEDA 按队列深度扩缩容

### 8.1 先装 Prometheus

KEDA 的 Prometheus scaler 需要**一个 Prometheus HTTP API**，不是直接读 Pod 的 `/metrics` 文本。

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  --set grafana.enabled=false \
  --set alertmanager.enabled=false \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false
```

最后那个 `serviceMonitorSelectorNilUsesHelmValues=false` 很重要：否则 Prometheus 只会发现带 release label 的 ServiceMonitor，你的 vLLM 指标永远进不来。

给 vLLM 加 ServiceMonitor：

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: vllm
  labels:
    release: kps
spec:
  selector:
    matchLabels:
      app: vllm
  endpoints:
  - port: http
    path: /metrics
    interval: 5s
EOF
```

> `interval: 5s` 是为了让扩容实验的时间分辨率够用；默认 30s 会让“扩容慢”看起来像 KEDA 的问题，其实是 scrape 太稀。

验证：

```bash
kubectl -n monitoring port-forward svc/kps-kube-prometheus-stack-prometheus 9090:9090

# 另一个 shell
curl -sG http://localhost:9090/api/v1/query \
  --data-urlencode 'query=vllm:num_requests_waiting' | jq .
```

看到 `result` 里有数值，才继续。

### 8.2 装 KEDA

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm install keda kedacore/keda -n keda --create-namespace
kubectl -n keda get pods
```

### 8.3 ScaledObject

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: vllm-scaler
spec:
  scaleTargetRef:
    name: vllm-qwen3-8b
  minReplicaCount: 1
  maxReplicaCount: 2
  pollingInterval: 15
  cooldownPeriod: 300
  triggers:
  - type: prometheus
    metadata:
      serverAddress: http://kps-kube-prometheus-stack-prometheus.monitoring.svc:9090
      metricName: vllm_requests_waiting
      query: sum(vllm:num_requests_waiting)
      threshold: "8"
EOF

kubectl get scaledobject
kubectl get hpa
```

`threshold: "8"` 的语义：HPA 目标值是 8，`desiredReplicas = ceil(queue / 8)`。在 1 副本时，队列 9 → 2 副本；队列 17 → 3 副本（但 `maxReplicaCount: 2` 会截断）。

> 不要再给同一个 Deployment 手建 HPA；KEDA 已经生成了 `keda-hpa-vllm-scaler`，两个 HPA 会互相打架。

### 8.4 压测

在集群内跑 bench（镜像里自带 `vllm bench`）：

```bash
kubectl run bench --rm -it --restart=Never \
  --image=vllm/vllm-openai:v0.34.0 --command -- \
  vllm bench serve \
    --backend openai \
    --endpoint /v1/completions \
    --host vllm-qwen3-8b \
    --port 8000 \
    --model qwen3-8b \
    --tokenizer Qwen/Qwen3-8B \
    --dataset-name random \
    --random-input-len 1024 \
    --random-output-len 256 \
    --num-prompts 300 \
    --max-concurrency 64 \
    --ignore-eos \
    --temperature 0 \
    --percentile-metrics ttft,tpot,itl,e2el \
    --metric-percentiles 50,95,99
```

> bench Pod 没有挂 hostPath，`--tokenizer Qwen/Qwen3-8B` 会从 HF 拉 tokenizer（几十 MB）。离线集群要改成挂 `/var/lib/models` 并用 `--tokenizer /models/Qwen3-8B-AWQ`；`-it` 只适合交互终端，脚本里去掉。

同时观察：

```bash
kubectl get pods -w
kubectl get hpa -w
kubectl get events --sort-by=.lastTimestamp | tail -20
```

### 8.5 单卡预期：1→2 会 Pending

```text
vllm-qwen3-8b-xxxxx   1/1 Running
vllm-qwen3-8b-yyyyy   0/1 Pending
```

```bash
kubectl describe pod -l app=vllm | grep -A5 Events
# 0/1 nodes are available: 1 Insufficient nvidia.com/gpu.
```

这不是 KEDA 失败，而是 **GPU 是整数资源**。结论要写成：

> KEDA 能把“想要 2 个副本”表达出来，但不能创造第二张 GPU；在单卡节点上，扩容的瓶颈是容量，不是 HPA 算法。

### 8.6 2 卡预期：真实扩容曲线

两个 GPU 节点（每个 1 卡）或一个 2 卡节点时，第二个 Pod 能调度。记录：

| 时间点 | 事件 | 怎么取 |
|---|---|---|
| `t_trigger` | queue > threshold | Prometheus 第一次超过 8 |
| `t_scheduled` | 新 Pod `PodScheduled=True` | Pod condition |
| `t_ready` | 新 Pod `Ready=True` | Pod condition |
| `t_first_success` | 新 Pod 收到第一个成功请求 | vLLM 日志/网关日志 |

扩容窗口内的 P99 用 Prometheus 取，不依赖 bench 的聚合结果：

```promql
# 队列深度
sum(vllm:num_requests_waiting)

# 运行中请求数
sum(vllm:num_requests_running)

# Ready 副本数
kube_deployment_status_replicas_ready{deployment="vllm-qwen3-8b"}

# 服务端 TTFT P99（1 分钟窗口）
histogram_quantile(0.99,
  sum(rate(vllm:time_to_first_token_seconds_bucket[1m])) by (le)
)
```

采样脚本：

```bash
# 目的：每 5s 打一行，扩容后画时间序列；先 port-forward Prometheus 到 9090
for i in $(seq 1 120); do
  ts=$(date +%s)
  q=$(curl -sG http://localhost:9090/api/v1/query \
    --data-urlencode 'query=sum(vllm:num_requests_waiting)' \
    | jq -r '.data.result[0].value[1] // "0"')
  r=$(curl -sG http://localhost:9090/api/v1/query \
    --data-urlencode 'query=kube_deployment_status_replicas_ready{deployment="vllm-qwen3-8b"}' \
    | jq -r '.data.result[0].value[1] // "0"')
  p99=$(curl -sG http://localhost:9090/api/v1/query \
    --data-urlencode 'query=histogram_quantile(0.99,sum(rate(vllm:time_to_first_token_seconds_bucket[1m])) by (le))' \
    | jq -r '.data.result[0].value[1] // "NaN"')
  echo "$ts queue=$q ready=$r ttft_p99=$p99"
  sleep 5
done
```

预期形态（要实测，不要背）：

- 新 Pod 从调度到 Ready 要经历镜像（已缓存则≈0）+ 权重（缓存则≈0）+ 模型加载（几十秒）；
- 在它 Ready 之前，所有流量仍压在旧 Pod 上，**P99 会先恶化**；
- Ready 之后 Endpoint 加入，P99 才回落；
- 所以“KEDA 扩容”不是立刻变好，而是“先更糟，几十秒后才更好”。这就是 D3 要写进结论的曲线。

### 8.7 scale-to-zero 实验（可选，但很有说服力）

把 `minReplicaCount` 改成 `0`，等 `cooldownPeriod` 过去：

```bash
kubectl patch scaledobject vllm-scaler --type merge -p '{"spec":{"minReplicaCount":0}}'
kubectl get pods -w
# 等到 Pod 数为 0（cooldownPeriod 默认 300s，别在 1 分钟后就下结论）
kubectl get pods -l app=vllm
```

Pod 缩到 0 后，直接请求 Service：

```bash
kubectl run curl-test --rm -it --restart=Never --image=curlimages/curl --command -- \
  curl -sS -m 10 http://vllm-qwen3-8b:8000/v1/models
# 预期：connection refused / 无 endpoint / 超时
```

然后发一个请求触发扩容，测“从请求到第一个 token”：

- KEDA 只负责把副本从 0 拉到 1，**不负责排队**；请求在 Pod 起来之前就失败了。
- 如果要“请求不丢”，需要 KEDA HTTP add-on 之类的 interceptor 先接住请求，或者网关排队；对 LLM 还要再加 70s 冷启动。
- 结论：chat 场景用 `minReplicaCount: 1` + 预热池；scale-to-zero 只给异步/批处理。

---

## 9. Lab 4：驱逐与优雅退出

### 9.1 先测“没有排空”的基线

复制 Deployment，去掉这三样：

- `--shutdown-timeout 90`
- `preStop` 的 `sleep 15`
- `terminationGracePeriodSeconds`（默认 30s）

复制时至少要改三处，否则两个 Deployment 会抢同一张卡和同一个 Service：`metadata.name`（如 `vllm-nodrain`）、`spec.selector.matchLabels.app`（如 `vllm-nodrain`）、`template.metadata.labels.app`（同上），并单独建一个 Service。更简单的做法是**先**用无排空配置做本节，再 apply §6.2 的完整配置做 §9.2，不要让两个 Deployment 并存。复制路径还要把下面脚本的 URL 改成新 Service 名；简单路径 Service 名不变。

然后压一批长请求（8 并发 × 512 output tokens，约 45s；能在 90s 排空窗口内跑完），5 秒后删 Pod：

> 脚本要在集群内跑（例如用一个带 `requests` 的 Pod），或者先 `kubectl port-forward svc/vllm-qwen3-8b 8000:8000` 再把 URL 改成 `127.0.0.1:8000`。port-forward 在 Pod 删除时会断，这本身也是“客户端观测到失败”的一部分；报告里要注明用的是哪条路径。

```bash
# 终端 A：客户端（在集群内或能直连 Service 的地方）
python3 - <<'PY'
import concurrent.futures, time, requests

URL = "http://vllm-qwen3-8b:8000/v1/completions"

def one(i):
    t = time.time()
    try:
        r = requests.post(URL, json={
            "model": "qwen3-8b",
            "prompt": "Write a long detailed story about a lighthouse.",
            "max_tokens": 512,
            "temperature": 0,
            "ignore_eos": True,
        }, timeout=180)
        return r.status_code, time.time() - t
    except Exception as e:
        return type(e).__name__, time.time() - t

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    futs = [ex.submit(one, i) for i in range(8)]
    for f in concurrent.futures.as_completed(futs):
        print(f.result())
PY

# 终端 B：5 秒后删 Pod
sleep 5
kubectl delete pod -l app=vllm
```

> 想验证“排空窗口不够”时，把 `range(8)` 改成 `range(32)`、`max_tokens` 改成 1024；这时 90s 内跑不完是预期结果，不是脚本 bug。

统计：

- HTTP 200 多少条；
- 异常/5xx 多少条；
- 最大延迟；
- Pod 从 `Terminating` 到消失多少秒。

### 9.2 再测“有排空”

先把无排空的 Deployment/Service 缩到 0 或删掉，再 apply §6.2 的完整配置（`--shutdown-timeout 90` + `preStop 15s` + grace 120s），重复同一批请求和删除动作。

> 删除 Pod 后 Deployment 会立刻起新 Pod，但新 Pod 要几十秒才 Ready；这段窗口 Service 没有可用 Endpoint，**新请求**会失败。本实验只看“删除瞬间已在途的请求”，不要把新请求的失败算进排空成功率。

预期：

1. Pod 进入 `Terminating`，先从 Endpoints 摘除；
2. `preStop` sleep 15s，新请求不再进来；
3. SIGTERM 后 vLLM 继续跑在途请求，最多 90s；
4. 请求完成，Pod 在 120s 内退出，没有 SIGKILL；如果 90s 内没跑完，说明 `--shutdown-timeout` 小于最长请求，应该调大或缩短请求。

验证日志：

```bash
# Pod 消失后日志就没了；删除前先开一个 `kubectl logs -f` 到文件，或删除后立刻抓
kubectl logs -l app=vllm --tail=100 | grep -iE "shutdown|drain|abort|SIGTERM"
kubectl get pod -l app=vllm -w
```

### 9.3 记录模板

| 配置 | 在途请求 | 成功 | 失败 | 最大延迟 | Terminating 时长 | 是否 SIGKILL |
|---|---|---|---|---|---|---|
| 无排空（默认 30s） | 8 | | | | | |
| 有排空（90s + 15s + 120s） | 8 | | | | | |
| 有排空 + 32×1024（可选，验证窗口不够） | 32 | | | | | |

### 9.4 PDB 的取舍

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: vllm-pdb
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: vllm
```

- 单副本 + `minAvailable: 1`：`kubectl drain` 会永远阻塞，因为没有任何自愿驱逐能保持 1 个可用副本。
- 生产要至少 2 副本 + `minAvailable: 1`，再配合 `maxUnavailable` 滚动更新。
- PDB 只管**自愿驱逐**（drain/升级），不管 `kubectl delete pod` 和节点故障。

---

## 10. 指标、SLO 与记录

### 10.1 指标定义

| 指标 | 定义 | 采集 |
|---|---|---|
| 冷启动总时长 | `apply/scale` → `Ready=True` | Pod condition + 时间戳 |
| 权重下载 | initContainer `startedAt` → `finishedAt` | Pod status |
| 模型加载 + 引擎 | 主容器 `startedAt` → `Ready=True` | Pod status |
| 扩容延迟 | `queue > threshold` → 新 Pod `Ready=True` | Prometheus + Pod condition |
| 扩容窗口 P99 | 扩容前后各 2 分钟的 TTFT P99 | `histogram_quantile` |
| 驱逐成功率 | 成功完成 / 在途请求 | 客户端统计 |
| goodput | `good_completed / duration`（req/s）；达标比例 = `goodput / request_throughput` | 同 D1/D2 |

SLO 沿用 D1/D2：`TTFT ≤ 2,000ms`、`TPOT ≤ 100ms`（per-request）。不要中途换 SLO，否则 goodput 不可比。

### 10.2 成本

| 项目 | 单价 | 成本 |
|---|---|---|
| 单卡 L4 容器 | `$0.2611/h`（GPU + 40GB 存储） | 3h 约 `$0.78` |
| 单卡 3090/4090 VM | 约 `$0.41–0.48/h`（含 130GB 盘） | 3h 约 `$1.2–1.5` |
| 2×L4 容器 | `2 × $0.25 + $0.0111 = $0.5111/h` | 3h 约 `$1.53`；4h 约 `$2.04` |
| 公网/存储 | ingress 通常不计费；Stop 后存储照计 | 见 Vast 账单 |

D2 后账户余额 `$18.81`；D3 单卡 VM 3h 约 `$1.3`，2 卡 4h 约 `$2.0`，预算足够。**先 scp 结果再 Destroy**。VM 创建比容器慢（几分钟），`creating` 不是失败；用 `vastai logs <ID>` 看进度。

---

## 11. 常见坑

| 症状 | 原因 | 处置 |
|---|---|---|
| k3s 起不来 / 卡在 `Starting` | 当前是 Vast 普通容器，没有 systemd/cgroup/privileged | 按 §2.1 用 `vms_enabled=true` + VM 模板重建；不要在普通容器里硬装 |
| 建 VM 报 `no_such_ask` / 创建失败 | offer 被租走，或用了非 VM 的 offer ID | 重新搜；必须用 `vms_enabled=true` 查询返回的 ID |
| `nvidia.com/gpu` allocatable 是 0 | device plugin 没 Ready，或 runtime 没配 | 看 `kubectl -n kube-system logs ds/nvidia-device-plugin-daemonset`；`grep nvidia .../config.toml` |
| device plugin 日志报 `No devices found` | static manifest 没写 `runtimeClassName: nvidia`，Pod 用 runc 看不到 GPU | patch DaemonSet 加 `runtimeClassName: nvidia`（§5.3） |
| k3s 安装脚本报 permission denied | 没有用 root 执行 | 用 `sudo sh -s -` 安装，不要直接 `sh` |
| Pod 里 `nvidia-smi` 报错 | 没写 `runtimeClassName: nvidia` | 加 `runtimeClassName`，或给 k3s `--default-runtime nvidia` |
| Pod 一直 `ContainerCreating` | 镜像太大/拉取慢；hostPath 不存在 | `kubectl describe pod` 看 Events；hostPath 用 `DirectoryOrCreate` 或先建目录 |
| 模型加载中被重启 | 只配了 liveness，没配 startupProbe | 用 `startupProbe` 保护启动；liveness 只在启动后生效 |
| 冷启动每次都很慢 | 缓存用了 `emptyDir`，Pod 删了就没了 | 用 hostPath / local PV / 共享存储 |
| 多节点时冷启动忽快忽慢 | Pod 调度到没有缓存的节点 | node affinity / local PV / 共享存储 |
| KEDA 不扩 | Prometheus 没抓到指标；ServiceMonitor label 不匹配 | 查 Prometheus `Targets`；`serviceMonitorSelectorNilUsesHelmValues=false` |
| KEDA 扩了但 Pod Pending | GPU 不够（单卡 1→2） | 这是预期；记录 `Insufficient nvidia.com/gpu`，不要怪 KEDA |
| 扩容后 P99 先变差 | 新 Pod 未 Ready，旧 Pod 独扛 | 记录曲线；用预热池/提前扩容缓解 |
| 缩到 0 后请求直接失败 | KEDA 不排队 | chat 用 `minReplicaCount: 1`；要排队就上 HTTP add-on/网关 |
| 删 Pod 时请求 502 | vLLM 默认 SIGTERM 立即 abort | 加 `--shutdown-timeout` + `preStop` + 足够 grace |
| 排空没生效 | `sh -c` 包住了 vLLM，SIGTERM 没到 PID 1 | `command: ["vllm","serve"]` 或 `exec vllm serve` |
| Pod 被 SIGKILL | `terminationGracePeriodSeconds` < `preStop + shutdown-timeout` | 120 > 15 + 90 + 15 |
| CPU limit 掐住 tokenizer | cgroup throttling | 提高/去掉 CPU limit，观察 TTFT |
| `hostPath` 权限不对 | 容器非 root / 目录属主 | 统一 UID，或 initContainer `chown` |

---

## 12. 面试问答（D3 版）

**Q1：device plugin 为什么不能申请“半张卡”？MIG / time-slicing / MPS / DRA 各解决什么？**

device plugin 把 GPU 暴露成整数扩展资源（`nvidia.com/gpu`），调度器只认整数。MIG 把 A100/H100 切成固定切片（硬隔离，但 L4 不支持）；time-slicing 让多个 Pod 共享同一张卡（软隔离，互相抢算力，LLM 的 TPOT 会抖）；MPS 做进程级并发（共享显存，隔离弱）；DRA 是 K8s 新的设备分配 API，支持更细的设备属性和配额。对 LLM 推理，优先整卡；要切卡先想清楚 SLO。

**Q2：8B 模型 FP16 约 16GB 权重（AWQ 约 5.7GB），怎么让新 Pod 20 秒内起来？四种方案和代价。**

① 节点本地缓存（hostPath/local PV）：最快，但只对单节点有效；② Model Streamer / 远程权重流式加载：省下载，但依赖高速网络；③ 预热池（minReplica ≥ 1）：没有冷启动，但一直占卡；④ 更小的量化/模型（AWQ/FP8/更小参数）：加载和显存都降，但质量/能力要重测。D1 的 69s 是启动到 ready 的参照，20s 需要模型/量化/存储一起优化，不是单靠 K8s。

**Q3：为什么 GPU inference 不该用 CPU 型 HPA？该用什么信号？**

GPU 打满时 CPU 可能很低，CPU 利用率和排队长度不相关；CPU HPA 会在最需要扩容时不扩。用 `vllm:num_requests_waiting`（队列深度）、`vllm:gpu_cache_usage_perc`（KV 压力）、TTFT P99 或 goodput 作为信号；KEDA 的 Prometheus scaler 直接查这些指标。

**Q4：chat 场景能不能 scale-to-zero？怎么折中？**

默认不能：冷启动 70s 级，请求在 Pod 起来前就超时；KEDA 缩到 0 也不排队。折中：`minReplicaCount: 1` + 预热池；按时间段/预测扩容；异步任务用队列 + scale-to-zero；或者用 KEDA HTTP add-on/网关先接住请求，但 TTFT 仍然包含冷启动。

**Q5：P99 TTFT 高但 GPU util 只有 40%，怎么查？**

先分服务端/客户端：看 `vllm:num_requests_waiting`（排队）、`vllm:time_to_first_token_seconds`（prefill）、`vllm:gpu_cache_usage_perc`（KV 压力）、`vllm:num_preemptions_total`（抢占）。常见原因：长 prompt 的 prefill 阻塞 decode、CPU tokenizer 被 cgroup 限流、KV 不足导致排队、网络/网关、批大小太小。D1 的诊断跑就是拆“排队 vs 首 token”。

**Q6：一个租户的长 prompt 拖垮整个 endpoint，怎么办？**

入口限制 `max-model-len`/`max_tokens`；按租户做队列/配额（Kueue/Gateway API）；长 prompt 走单独 pool；开 chunked prefill 降 ITL 尾部；必要时做 prefill/decode 分离。不要只靠“加副本”，长 prompt 会把每个副本都拖慢。

**Q7：prefill/decode 为什么要分离？什么规模才值得？**

prefill 计算密集、decode 带宽密集，混在一起会互相抢资源；分离后可以分别扩缩、用不同 GPU。代价是 KV 传输、两套调度、复杂度。规模小（单卡、低并发）不值得；长 prompt + 高并发 + 多卡时才考虑。D3 的单卡不涉及，D4 的 llm-d 才是入口。

**Q8：TP / PP / EP 各自什么时候用？**

TP（张量并行）用于单卡放不下模型，卡间通信最重；PP（流水并行）跨节点放超大模型， bubble 代价；EP（专家并行）用于 MoE，把专家分散。8B 模型单卡 L4 能放（AWQ 5.7GB），不要为了“看起来分布式”上 TP=2；通信开销会把收益吃掉。

**Q9：K8s 带来的开销到底在哪？怎么消？**

① CNI/kube-proxy/网关多一跳；② 镜像拉取 + 权重加载让冷启动变长；③ 调度器排队；④ cgroup CPU 限制可能掐住 tokenizer；⑤ device plugin 只能整数分配。对应手段：`hostNetwork`、Gateway API 直连 Pod IP、node-local cache/Model Streamer、CPU limit 设高或不设、DRA/KAI/HAMi 做分数卡。

**Q10：KEDA、HPA、Kueue 怎么选？**

HPA 是副本伸缩的底层机制；KEDA 在 HPA 之上接事件源/Prometheus，支持 scale-to-zero；Kueue 是配额/排队/准入，不扩副本。推理平台通常三者一起：Kueue 管“能不能拿卡”，KEDA 管“根据什么信号扩到几张”，HPA 是 KEDA 底下的执行机制。D5 会把 Kueue 的配额和 Kyverno 的准入补上。

**B 线四问（D3/D5 的 B 线面试会追问）**

- **GPU 平台怎么做多租户隔离？** 四层：namespace/RBAC 做逻辑隔离；ResourceQuota 限 CPU/内存；Kueue `ClusterQueue` 限 GPU 配额与优先级；Kyverno 强制 label/priorityClass/资源上限。device plugin 不做隔离；time-slicing/MIG 才会切分算力，但会破坏 SLO。
- **模型版本回滚怎么做？** 权重按版本目录存放（`/var/lib/models/<model>-v1`、`-v2`），Deployment 用 `MODEL_PATH` 指向版本；回滚 = 改路径 + rollout restart。不要在运行中的目录上覆盖权重，否则旧 Pod 读旧文件、新 Pod 读半套文件，回滚也没有旧版本可回。
- **GPU 容量规划为什么不能只看 util？** GPU util 高不代表排队；要看 `num_requests_waiting`、KV 使用率、TTFT P99、goodput。容量 = 满足 SLO 的并发，不是“卡跑满”；D2 的 c=64 goodput 0 就是例子。
- **chargeback 按 GPU 小时还是按 token？** 两种口径都要：按 GPU 小时是财务口径（预留/闲置都算），按 token 是业务口径（谁用得多）；差额是闲置成本。D3 先把 namespace/label 和每副本 `$/h` 埋好，Q2 再算。

---

## 13. 与 D1/D2/D4/D5 的衔接

- **D1**：69s 启动到 ready、96,256 KV、c=64 132.8 tok/s 是 D3 冷启动和容量的参照；D3 的 cold start 必须大于 69s（还要加镜像/权重下载）。
- **D2**：AWQ + prefix caching 是默认配置；`max-num-seqs 64`、`max-model-len 8192` 直接复用。D2 的 c=8 goodput 25%、c=16 0.5% 说明“副本数不等于容量”，KEDA 的阈值要按队列/goodput 调，不要按 CPU。
- **D4**：llm-d 的 prefix-cache-aware 路由需要 ≥2 副本 + 网关；D3 的 Deployment/Service/Endpoint 是底座。D3 的 1→2 曲线直接决定 D4 的“扩容期间 P99”基线。
- **D5**：Kueue 的 ClusterQueue 和 Kyverno 的准入策略建在同一个集群上；D3 的 namespace/label 规范要提前定好。
- **计划**：D3 是 Q1 的 B 线 artifact；执行后把冷启动/扩容/驱逐三个数回填 `ai-cloud-native-week-plan.md` §5 的“三个 B 线数”，并按该文件 §3 的讲法准备 10 分钟讲解。

---

## 14. 清理

```bash
# 目的：先删应用，再删 KEDA/Prometheus，最后卸 k3s
kubectl delete -f k8s/vllm.yaml
kubectl delete scaledobject vllm-scaler --ignore-not-found
helm uninstall keda -n keda --ignore-not-found
helm uninstall kps -n monitoring --ignore-not-found
kubectl delete namespace keda monitoring --ignore-not-found

# 目的：卸 k3s（会停服务、删集群数据；先确认结果已 scp）
sudo /usr/local/bin/k3s-uninstall.sh

# 目的：权重缓存按需删除；下次重下约 5.7GB
sudo rm -rf /var/lib/models/Qwen3-8B-AWQ

# 目的：确认没有残留 GPU 进程/实例
nvidia-smi
```

云端实例：先 `scp` 结果和 manifest，再 Stop/Destroy；规则同 D1/D2（24h 内继续 → Stop；隔几天 → Destroy）。

```bash
# 在本地执行，不在 VM 里
vastai show instances
vastai scp-url <ID>
vastai destroy instance <ID> -y
```

---

## 15. 验收清单（执行后勾）

- [ ] Vast 实例是 VM：`ps -p 1` 输出 `systemd`
- [ ] k3s 单节点 Ready；`nvidia.com/gpu` allocatable = 1（或 2）
- [ ] GPU smoke test 通过
- [ ] vLLM Deployment Ready；`/v1/models` + completion 成功
- [ ] cold / warm 冷启动分阶段表
- [ ] KEDA ScaledObject + HPA 生效
- [ ] 单卡 1→2 Pending 事件，或 2 卡 1→2 曲线
- [ ] scale-to-zero 的失败/延迟证据（可选）
- [ ] 驱逐：无排空 vs 有排空的成功/失败对比
- [ ] 一段带数字的归因结论
- [ ] 能画出 GPU 平台交付链路，并回答 §12 的 B 线四问
- [ ] 能脱稿讲 §16 的 B 线 bullet（至少 1 条，每条接住三层追问）
- [ ] 回填计划 §5 的“三个 B 线数”和 README D3 小节
- [ ] 结果、manifest、日志 commit + push
- [ ] 成本记录；实例 Stop/Destroy

---

## 16. D3 的 B 线简历 bullet（执行后填，选 1–3 条）

执行完 §5–§9 后，把下面三条填上数字，直接投 B 线岗位（K8s / GPU platform / ML platform）：

- 在单节点 k3s 上交付 vLLM 推理服务：用 NVIDIA device plugin + `runtimeClassName: nvidia` 暴露 GPU，hostPath 缓存 5.7GB 权重，cold/warm 冷启动从 ____s 降到 ____s（−__%）。
- 用 KEDA + Prometheus 按 `vllm:num_requests_waiting` 做队列驱动扩缩：0→1 在 ____s 内 Ready；单卡 1→2 的 `Pending` 证明 GPU 整数分配是容量瓶颈，不是 HPA 算法问题。
- 设计优雅驱逐：`preStop` 15s + `--shutdown-timeout` 90s + grace 120s，在途 ____ 条长请求成功率从 __% 提升到 __%，Pod 在 ____s 内退出且无 SIGKILL。

> 每条都要能接住三层追问：为什么用 hostPath 不用 emptyDir？为什么不用 CPU HPA？为什么 grace 是 120 不是 90？答案分别在 §6.3、§3.5、§3.6。

---

## 17. Sources

1. k3s Advanced Options（NVIDIA runtime 自动探测、`runtimeClassName: nvidia`、containerd 模板）：https://docs.k3s.io/advanced
2. NVIDIA Kubernetes device plugin（安装与 DaemonSet）：https://github.com/NVIDIA/k8s-device-plugin
3. vLLM Kubernetes 部署（Deployment/Service/probe 示例）：https://docs.vllm.ai/en/stable/deployment/k8s/
4. KEDA Prometheus scaler（`serverAddress` / `query` / `threshold`）：https://keda.sh/docs/2.21/scalers/prometheus/
5. vLLM Production Stack 的 KEDA 自动扩缩容（`vllm:num_requests_waiting` 示例）：https://docs.vllm.ai/projects/production-stack/en/latest/use_cases/autoscaling-keda.html
6. llm-d Graceful Shutdown & Request Draining（`--shutdown-timeout`、`preStop`、grace period）：https://llm-d.ai/docs/dev/operations/lifecycle/graceful-shutdown
7. Kubernetes Pod Lifecycle（Terminating / grace period）：https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/
8. Kubernetes Probes（startup/readiness/liveness）：https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
9. Kubernetes GPU scheduling（device plugin / 整数资源）：https://kubernetes.io/docs/tasks/manage-gpus/scheduling-gpus/
10. vLLM Metrics（`vllm:num_requests_waiting`、TTFT histogram 等）：https://docs.vllm.ai/en/stable/design/metrics/
