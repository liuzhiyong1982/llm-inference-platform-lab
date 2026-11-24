# D3 学习文档：k3s + vLLM 的冷启动、扩缩容与驱逐

> 状态：**执行中（2026-11-24）**。§5–§6 已完成；§7 warm/cold/image-cold 已测（cold 下载到旧目录，按可用口径接受；image-cold 是 containerd 本地复用层，不是网络冷拉）；§8–§9 待执行。后续把实测数字补进 §7–§9、§16，并在 README 增加 D3 结果小节。
>
> 计划中的位置：`ai-cloud-native-week-plan.md` §4 Q1 的 **B 线 artifact**；B 线讲法见该文件 §3「D3 / D5 的 B 线讲法」。执行后同时回填该文件 §5 的“三个 B 线数”。
>
> 性质：学习文档 + 可执行 lab，不是 D1/D2 那种逐命令 runbook。D1/D2 回答“单机多快”，D3 回答“把它放进 K8s 后，启动、扩容、驱逐各要付多少秒”。
>
> 硬约束：**不在共享 UAT 集群 `uat-mobility-aks-01` 上做实验**。用自己租的/本地的单机 GPU；所有对比同机、同模型、同输入/输出长度、同 SLO。
>
> 环境：本地 Linux 或 **Vast RTX VM**（你已在 Vast 的 RTX VM 上跑过 k8s）；Vast 普通容器实例没有 systemd/cgroup，不要用。

---

## 0. 先看结论（执行前先记住）

1. **K8s 不会让推理变快。** 它提供的是声明式发布、服务发现、调度、扩缩容；代价是镜像拉取、权重分发、网络转发、调度排队四层开销。
2. **冷启动不等于“启动到 ready 69s”。** D1 的 69s 是 L4 上进程启动到 API ready，其中 `Model loading took ... 7.72s`、`init engine ... 21.72s`；完整冷启动还要加镜像拉取和权重下载（5.7GB）。D3 跑在 RTX 3090/4090 上，绝对值不能和 D1 的 L4 直接比；但“调度 / 镜像 / 权重 / 加载 / Ready”的分阶段口径一致。
3. **单卡上 KEDA 1→2 必然 Pending。** `nvidia.com/gpu` 是整数资源，device plugin 不会把一张 24GB 卡切成两张；这不是 KEDA 的 bug，是 GPU 调度模型的边界。
4. **scale-to-zero 对 chat 基本不可用。** 几十秒级冷启动会打穿 TTFT SLO；它只适合异步、批处理、低频请求。KEDA 缩到 0 也不会替你排队——请求会直接失败。
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

- [ ] Vast 实例是 RTX VM（`ps -p 1` = `systemd`），记录 GPU 型号 / driver / power limit；
- [ ] k3s 单节点起来，`nvidia.com/gpu` 可分配；
- [ ] vLLM Deployment Ready，`/v1/models` 和一次 completion 成功；
- [ ] 冷启动表：cold / warm（可选 image-cold），每段有秒数；
- [ ] KEDA 扩容证据：单卡 1→2 的 Pending 事件，或 2 卡 1→2 的 P99 曲线；
- [ ] 驱逐实验：无排空 vs 有排空的成功/失败对比；
- [ ] 一段带数字的归因结论；
- [ ] 结果、manifest、日志进 git。

### 1.1 3 小时最小路径 vs 完整路径

| 阶段 | 最小路径（单卡 RTX，3h） | 完整路径（2 卡 RTX，4–5h） |
|---|---|---|
| 租 VM + 启动（不含在 3h 内） | 10–15 min | 10–15 min |
| 读 §2–§4 概念 | 30 min | 30 min |
| k3s + GPU runtime + device plugin | 45 min | 45 min |
| 模型缓存 + Deployment + Service | 30 min | 30 min |
| 冷启动 cold / warm | 30 min | 45 min |
| KEDA | 30 min（0→1 + 1→2 Pending） | 60 min（真实 1→2 曲线） |
| 驱逐 | 15 min | 30 min |
| 记录 + commit | 30 min | 30 min |

> 3h 是**登录 VM 之后**的净时间；租 VM、等 `creating → running` 另加 10–15 分钟。如果只能租一张卡，接受“1→2 Pending”这个结果，它本身就是 D3 的核心结论之一。真实扩容曲线留给 2 卡；2 卡 RTX VM 约 `$0.85–1.0/h`，比单卡贵一倍，预算紧就只做单卡。
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
| **Vast.ai RTX GPU VM** | 高（你已在 Vast 的 RTX VM 上跑过 k8s） | 按小时计费；必须是 VM/privileged，普通容器实例不行 | **D3 主路径**；复用你上次成功的 image/template，先做 §5.0–§5.1 的确认 |
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
| 成本（单卡 RTX VM / 2 卡 RTX VM） | 约 `$0.41–0.48/h` | 约 `$0.85–1.0/h`（GPU ×2 + 存储） |

> L4 容器 `$0.2611/h` 只作 D1/D2 参照；D3 的 k3s 不能跑在普通容器里，所以 D3 不报 L4 容器的价格。
>
> 机制可以用 CPU + 小模型（如 `Qwen3-0.6B`）练，但**冷启动秒数只能用目标 GPU 测**；不要把 CPU 数字写进作品集。

> 2026-11-23 实测：Vast 上搜不到 L4 VM（`gpu_name=L4 vms_enabled=true` 返回空），24GB VM 只有 3090/4090/5090。你以前已经在 Vast 的 RTX VM 上跑过 k8s，所以 **RTX 3090/4090 VM 是 D3 的主路径**，不是临时兜底。用 RTX 时，D3 只做内部 cold/warm 对比，**不要**把吞吐或冷启动秒数和 D1/D2 的 L4 数字直接比。

> 租 VM 的具体命令见 §5.0；这一节只比较环境方案。

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

- **device plugin 只做整数分配**：一张 24GB 卡（L4/3090/4090）只能给一个 Pod（除非 MIG / time-slicing / MPS / DRA）。
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

## 5. Lab 0：租 RTX VM + GPU runtime + k3s + device plugin

### 5.0 在 Vast 租一台 RTX VM（CLI）

k3s 需要 systemd/cgroup；**普通容器实例不行**，必须选 `vms_enabled=true` 的 VM。你上次已经在 RTX VM 上跑通 k8s，直接复用同一类机器和安装方式。下面命令按顺序执行。

**0）账号与 SSH key：**

```bash
vastai show user -q
vastai show ssh-keys

# 没有 key 时，把路径换成你的公钥
vastai create ssh-key "$(cat ~/.ssh/id_ed25519.pub)"
```

**1）搜 VM offer：**

```bash
# 直接搜 RTX VM（L4 VM 当前为空，不用先试）
vastai search offers -n \
  'num_gpus=1 gpu_ram>=24 rentable=true vms_enabled=true cuda_vers>=13.0 disk_space>=100 inet_down>=500 reliability>=0.98 cpu_ram>=64' \
  -o 'dph' --storage 130 --limit 10
```

挑 `R >= 0.98`、`Net_down >= 500`、`Disk >= 100`、`Max_Days >= 1`、`ports >= 1`、`RAM >= 64GB` 的。**必须用 `vms_enabled=true` 查询返回的 offer ID**；同一个 GPU 的 VM 和容器 offer ID 不同，拿容器 ID 建 VM 会失败。`cpu_ram>=64` 是为了给 §6.2 的 `memory: 20Gi`、k3s 和页缓存留余量；32GB 的机器单副本余量很小，1→2 的 2×20Gi 直接不够。

> 如果以后 Vast 上出现 L4 VM，把 `gpu_ram>=24` 换成 `gpu_name=L4` 即可；当前（2026-11-23）没有，别为它多跑一次查询。
>
> 2 卡路径：把 `num_gpus=1` 改成 `num_gpus=2`，`--disk` 加到 160；单卡是主路径，2 卡只用来测真实扩容曲线。**2026-11-24 实测 2 卡 VM 在 machine `69146`（CN）和 `38668`（UK verified）都卡在 `created`；machine `20876`（Virginia，2×4090）正常启动。host 很关键，先用单卡完成 §7–§9，2 卡等单卡跑通后再试。**

```bash
# 2 卡 VM（单价含 160GB 盘）
vastai search offers -n \
  'num_gpus=2 gpu_ram>=24 rentable=true vms_enabled=true cuda_vers>=13.0 disk_space>=160 inet_down>=500 reliability>=0.99 cpu_ram>=64' \
  -o 'dph' --storage 160 --limit 15
```

> **选 host 时避开 `country=CN` 和 `status=deverified`。** VM 模板镜像在 Docker Hub（`docker.io/vastai/kvm`），CN host 拉镜像可能十几分钟都起不来；优先 `verified`、`R >= 0.99`、`Net_down >= 500`。2026-11-24 实测 2×5090 的 machine `69146`（CN、deverified）13 分钟仍 `actual_status=null`、SSH 拒绝，只能 destroy。UK verified 的 `38668` 同样失败，所以 CN 不是唯一变量；**2 卡 VM 的稳定性是更大的问题**。
>
> 2026-11-24 补测：machine `20876`（2×4090，Virginia，verified）用同一个 `2c18...` 模板正常启动，SSH 可达；所以 2 卡 VM 不是全坏，host 很关键。

**2）创建 VM（走 API，显式 `vm:true`）：**

`vastai create instance` 的 CLI payload 不带 `vm` 字段（当前 CLI 也没有 `--vm` 开关），用它配 VM 模板可能起成普通容器：`actual_status=created`、`uptime=null`、SSH `Connection refused`，盘几乎不写。VM 必须走 API，显式传 `"vm": true`：

```bash
curl -s -X PUT "https://console.vast.ai/api/v0/asks/<OFFER_ID>/" \
  -H "Authorization: Bearer $(cat ~/.config/vastai/vast_api_key)" \
  -H "Content-Type: application/json" \
  -d '{"template_hash_id":"2c18cabd8f2f0525c2ff8446f5d4e063","vm":true,"disk":130,"runtype":"ssh_direct","label":"d3-k3s-vm","cancel_unavail":true}' \
  | python3 -m json.tool
```

返回里的 `new_contract` 就是实例 ID；2 卡把 `disk` 改成 160。

> 2026-11-24 实测：两次 CLI 2 卡创建（`47476583`，machine `38668`）都卡在 `actual_status=created`、`uptime=null`、SSH 拒绝，盘用量几乎为 0；改用 API 显式 `vm:true` 后 4 分钟内仍未起来（你已 destroy）。作为对照，2026-11-23 的 **1 卡 bid VM** 用同一模板、同一 CLI key 正常。结论：VM 创建优先用上面的 API；但当前 2 卡 VM 本身不可靠，**D3 先单卡**。

`--template_hash` 是 Vast **模板**的 `hash_id`（32 位十六进制），不是 offer ID，也不是从镜像名算出来的。它把「镜像 + tag + 启动参数 + `vms_enabled` 过滤」打包在一起；模板本身带 `vm: true`，但 **API 请求仍要显式传 `vm: true`**。

当前 hash 对应 Vast recommended 的 `Ubuntu 22.04 VM` 模板：

| 字段 | 值 |
|---|---|
| `name` | `Ubuntu 22.04 VM` |
| `image` | `docker.io/vastai/kvm` |
| `tag` | `@vastai-automatic-tag`（跟随最新镜像） |
| `vm` / `recommended` | `true` / `true` |
| `recommended_disk_space` | `130` |

自己查/复核（换机器或 hash 失效时用）：

```bash
# 按名字找 recommended 的 Ubuntu 22.04 VM 模板
vastai search templates 'name == Ubuntu_22.04_VM recommended == True' --raw | \
  python3 -c 'import json,sys; [print(t["hash_id"], "|", t["name"], "|", t["image"], "|", t.get("tag"), "| vm", t.get("vm")) for t in json.load(sys.stdin)]'

# 已知 hash 时反查它是不是 VM 模板
vastai search templates 'hash_id == 2c18cabd8f2f0525c2ff8446f5d4e063' --raw | \
  python3 -c 'import json,sys; t=json.load(sys.stdin)[0]; print(t["name"], t["image"], t.get("tag"), "vm=", t.get("vm"), "recommended=", t.get("recommended"))'
```

Web UI 的 Templates → `Ubuntu 22.04 VM` 也能看 hash；Web UI 建 VM 会自动带 `vm:true`。`--image` 不能代替 `--template_hash`。

> `@vastai-automatic-tag` 会跟随 Vast 更新镜像 tag；2026-11-24 实际解析成 `docker.io/vastai/kvm:cuda-12.9.1-auto`。记录 D3 结果时把实例的 `image_uuid` 一起记下来。如果 API 报 unknown template，用上面的命令重新查 hash，不要猜。

**3）SSH 与 VM 确认：**

```bash
vastai show instances
vastai ssh-url <ID>

# ssh-url 输出形如 ssh://root@host:port；换成：
ssh -p <PORT> root@<HOST>

# 在 VM 里执行：
ps -p 1 -o comm=                 # 必须是 systemd
systemctl is-system-running      # running/degraded 都算起来了
```

`ps -p 1` 不是 `systemd` 就说明拿到的是容器，立刻 `vastai destroy instance <ID> -y`，不要继续装 k3s。

**4）计费与清理：**

```bash
vastai show instances
vastai stop instance <ID>        # 保留磁盘，继续收存储费
vastai destroy instance <ID> -y  # 结果 scp 回本地后再执行
```

2026-11-23 实测：3090 VM 约 `$0.41/h`（含 130GB 盘），4090 约 `$0.48/h`；3h 约 `$1.2–1.5`。比 D2 的 L4 容器贵，但在 `$15` 预算内。

> **不要用 interruptible（`--bid_price`）做 D3 的正式测量。** D3 的 cold start、KEDA 扩容曲线和驱逐实验都要求同一台机器连续运行；bid 实例被 outbid 后会 pause/stop，k3s、Prometheus TSDB 和 in-flight 请求一起断，这一段数据只能作废重跑。省下来的约 `$0.7` 不值得拿作品集数字冒险。
>
> **预算紧时按这个顺序省：** ① 选 3090 而不是 4090；② 只做单卡，接受 1→2 `Pending`；③ 砍 image-cold、scale-to-zero、PDB、2 卡曲线、驱逐的“有排空”对照；④ 提前把 YAML/脚本准备好，租完直接跑；⑤ 结果 `scp` 后立刻 Destroy，不要 Stop 着收存储费。

**Bid 排练（可选，不产出正式数字）：**

```bash
# 1) 搜 interruptible VM；$/hr 是当前最低 bid
vastai search offers -n -t bid \
  'num_gpus=1 gpu_ram>=24 rentable=true vms_enabled=true cuda_vers>=13.0 disk_space>=100 inet_down>=500 reliability>=0.98 cpu_ram>=64' \
  -o 'dph' --storage 130 --limit 10

# 2) 创建；price 要 >= 上一步的 $/hr，建议上浮 10–20%
#    当前 3090 约 0.153，所以示例用 0.18
curl -s -X PUT "https://console.vast.ai/api/v0/asks/<OFFER_ID>/" \
  -H "Authorization: Bearer $(cat ~/.config/vastai/vast_api_key)" \
  -H "Content-Type: application/json" \
  -d '{"template_hash_id":"2c18cabd8f2f0525c2ff8446f5d4e063","vm":true,"disk":130,"price":0.18,"runtype":"ssh_direct","label":"d3-k3s-vm-bid","cancel_unavail":true}' \
  | python3 -m json.tool
```

> bid 也用 API：CLI 的 `create instance` 同样不带 `vm:true`。bid 实例被 outbid 后可能直接 pause/stop；每完成一步就 `scp`，正式 cold start/扩容/驱逐仍然回到 §5.0 的 on-demand 命令重跑。

### 5.1 记录机器并检查 k3s 前置条件

§5.0 的 `ps -p 1` / `systemctl` 已经确认是 systemd；这里补 k3s 真正依赖的几项：

```bash
# 目的：这些是后面所有数字的可比性前提
# 5090=sm_120、4090=sm_89；driver 的 Max CUDA 必须 >= vLLM 镜像的 CUDA（v0.34 约 13.0）
nvidia-smi | sed -n '1,4p'
nvidia-smi --query-gpu=name,memory.total,driver_version,compute_cap,power.limit --format=csv,noheader
nvidia-ctk --version 2>/dev/null || echo "no nvidia-ctk"
uname -r
nproc
free -g | head -2

# 目的：k3s/kubelet 要 cgroup v2
stat -fc %T /sys/fs/cgroup
cat /sys/fs/cgroup/cgroup.controllers

# 目的：k3s 要写 /var/lib/rancher
sudo test -w /var/lib && echo "var-lib writable"
df -h /var/lib
```

- `nvidia-smi` 右上角的 `CUDA Version` 是 driver 支持的 **Max CUDA**。低于 vLLM 镜像的 `CUDA_VERSION`（v0.34 镜像约 13.0）时会报 `CUDA driver version is insufficient`；换镜像或换 host，不要装 driver。
- `compute_cap` 直接给出架构：3090=8.6、4090=8.9、5090=12.0。镜像的 `TORCH_CUDA_ARCH_LIST` 不含对应架构时会报 `no kernel image is available`，和 CUDA 版本是两回事。

**2026-11-24 实际 VM 记录（2×4090，machine `20876`）：**

| 项 | 实测值 |
|---|---|
| OS / kernel | Ubuntu 22.04.5 LTS / `6.8.0-59-generic` |
| init / cgroup | `systemd` / `cgroup2fs`，controllers `cpuset cpu io memory hugetlb pids rdma misc` |
| GPU | 2×RTX 4090 24564MiB，compute_cap 8.9，power limit 450W |
| driver / Max CUDA | `580.95.05` / `13.0`（**以 VM 内 `nvidia-smi` 为准**；API 的 `driver_version` 可能显示 host 的 580.159.03） |
| CPU / RAM | 15 vCPU / 48GiB（`MemTotal` 约 50.7GB） |
| 磁盘 | 126GB，约 120GB 可用 |
| toolkit | `nvidia-ctk`、`nvidia-container-runtime` 均未安装 |
| k8s | 无 `k3s`、无 `kubeadm`（干净 VM，模板 `2c18...` 的 `onstart` 为空） |
| image | `docker.io/vastai/kvm:cuda-12.9.1-auto`，template id `781848` |

> 2026-11-24 16:57 `apt-daily-upgrade.timer` 补跑 `unattended-upgrade`，把 NVIDIA 用户态包从 580.95.05 升到 580.178.04，内核模块仍是 580.95.05；新 Pod 因此报 `failed to initialize NVML: Driver/library version mismatch`。同一轮还装上了 6.8.0-149 内核。17:44 重启后实测 kernel `6.8.0-149-generic`、driver `580.178.04`，`nvidia-smi` 正常，k3s 和 vLLM 都恢复；后续以实际 `nvidia-smi` / `uname -r` 为准。

> 如果上次用的是 k3s，直接复用同一版安装命令，并记录 `k3s --version`、实例 image/template、GPU 型号和关键参数（`--disable traefik`、`--flannel-backend` 等）。如果上次是 kubeadm/kind，先告诉我要换哪套；不要在同一份 D3 里混两种发行版。

- 如果 `stat -fc %T /sys/fs/cgroup` 不是 `cgroup2fs`（例如 `tmpfs`），说明还是 cgroup v1，k3s/kubelet 可能起不来。Ubuntu 22.04 可在 `/etc/default/grub` 的 `GRUB_CMDLINE_LINUX` 里加 `systemd.unified_cgroup_hierarchy=1`，`sudo update-grub` 后重启；改不了就换支持 cgroup v2 的 VM。
- `/var/lib` 不可写，通常是权限或磁盘满；先解决再装。
- **关掉自动升级。** 见下面的“关掉自动升级”命令；Vast 的 Ubuntu VM 默认带 `apt-daily-upgrade.timer`，`unattended-upgrades.service` 可能是 inactive/disabled，但 timer 仍会触发。
- 如果检查失败，换 RTX VM 或本地/云 VM，不要在 Vast 普通容器里硬扛。

#### 关掉自动升级（必须）

Vast 的 Ubuntu VM 默认带 `apt-daily-upgrade.timer` + `/etc/apt/apt.conf.d/20auto-upgrades`。触发链是：

```text
apt-daily-upgrade.timer
  → apt-daily-upgrade.service
  → /usr/lib/apt/apt.systemd.daily install
  → /usr/bin/unattended-upgrade
```

`unattended-upgrades.service` 本身可能是 `inactive/disabled`，但 timer 仍然会跑。timer 的配置是：

```ini
[Timer]
OnCalendar=*-*-* 6:00
RandomizedDelaySec=60m
Persistent=true
```

`Persistent=true` 表示 6:00 没开机时会补跑；`RandomizedDelaySec=60m` 会把它推到开机后 0–60 分钟内的某个点。2026-11-24 这台 VM 约 15:57 开机，16:57 被 timer 补跑，把 NVIDIA 用户态驱动从 `580.95.05` 升到 `580.178.04`，内核模块还是旧版，于是新 Pod 报 `Driver/library version mismatch`。

先确认，再关：

```bash
# 目的：看是谁在跑、下次什么时候跑
systemctl list-timers --all | grep -E 'apt|unattended'
cat /etc/apt/apt.conf.d/20auto-upgrades

# 目的：停掉 timer 和 service；只 disable unattended-upgrades.service 不够
sudo systemctl disable --now unattended-upgrades.service
sudo systemctl disable --now apt-daily.timer apt-daily-upgrade.timer
sudo systemctl mask unattended-upgrades.service apt-daily.timer apt-daily-upgrade.timer

# 目的：确认没有下次触发
systemctl list-timers --all | grep -E 'apt|unattended' || echo "no apt timers"
```

> `mask` 会阻止 timer/service 再被拉起；实验结束后如需恢复，用 `sudo systemctl unmask ...`。如果已经升级过，先等 `/var/lib/dpkg/lock-frontend` 释放，再重启 VM 让新内核模块加载；不要在 apt 事务中间 reboot。

### 5.2 安装 NVIDIA runtime（toolkit）

k3s 会自动探测 PATH 里的 `nvidia-container-runtime`，所以**先装 toolkit，再装 k3s**；这样 k3s 首次启动就能识别，不用额外 restart。默认 runtime 仍是 `runc`，Pod 仍要显式写 `runtimeClassName: nvidia`（或者给 k3s 加 `--default-runtime nvidia`）。

> 2026-11-24 实测：这台 Ubuntu 22.04.5 VM 只有 driver `580.95.05`，`nvidia-ctk` 和 `nvidia-container-runtime` 都没有；按下面装。

```bash
# 目的：先看发行版，以及 apt 里有没有现成的包
cat /etc/os-release
apt-cache policy nvidia-container-toolkit

# 目的：安装依赖和 NVIDIA 官方 repo（apt-cache 没有 Candidate 时才需要）
sudo apt-get update
sudo apt-get install -y curl ca-certificates gnupg
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# 目的：确认 toolkit 和 runtime 都在
nvidia-ctk --version
which nvidia-container-runtime
```

> 如果 `apt-cache policy nvidia-container-toolkit` 已经显示 `Candidate:`，可以跳过加 repo，直接 `sudo apt-get install -y nvidia-container-toolkit`。
>
> 装完先跑 `nvidia-smi`。如果报 `Driver/library version mismatch`，说明 apt 或 `apt-daily-upgrade.timer` 把用户态驱动升到了新版本，但内核模块还是旧版；不要继续装 k3s/device plugin，先重启 VM 让新模块加载，确认 `nvidia-smi` 正常后再走 §5.3。
>
> 如果你已经先装了 k3s，装完 toolkit 后执行 `sudo systemctl restart k3s`；还没装就继续 §5.3，k3s 启动时会自己探测。
>
> RTX VM 镜像通常已带 driver；先 `nvidia-smi` 和 `nvidia-ctk --version` 确认，缺 toolkit 再按上面的 repo 安装。`nvidia-container-toolkit` 包会带上 `nvidia-container-runtime`，装完用 `which nvidia-container-runtime` 复核。RTX 3090/4090 是消费卡，**不要**假设 `nvidia-fabricmanager` 或 NVLink 存在；D3 单卡用不到。

### 5.3 安装 k3s

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

装完确认 k3s 探测到了 NVIDIA runtime：

```bash
# 目的：确认 containerd 配置里出现 nvidia
grep -n nvidia /var/lib/rancher/k3s/agent/etc/containerd/config.toml

# 目的：确认 RuntimeClass 存在；没有它，runtimeClassName: nvidia 的 Pod 会卡住
kubectl get runtimeclass nvidia
```

如果 `grep` 没有任何输出：

1. 确认 `which nvidia-container-runtime` 有路径；
2. 确认它在 k3s 服务的 PATH 里（`/usr/bin` 或 `/usr/local/bin`）；
3. 再 `sudo systemctl restart k3s`；仍不行就查 `journalctl -u k3s -n 100`。

> 不要手写整份 `config.toml` 覆盖 k3s 生成的文件；k3s 升级/重启会重新渲染。要用模板就用官方 `config-v3.toml.tmpl` 的 `{{ template "base" . }}` 方式。

### 5.4 安装 NVIDIA device plugin

```bash
# 目的：把 GPU 暴露成 nvidia.com/gpu 扩展资源；版本按 release 页核对
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.18.0/deployments/static/nvidia-device-plugin.yml

# 目的：static manifest 没有写 runtimeClassName；k3s 默认 runtime 是 runc，
# 不补这一行，device plugin 可能看不到 GPU（allocatable 一直是 0）
kubectl -n kube-system patch ds nvidia-device-plugin-daemonset --type merge \
  -p '{"spec":{"template":{"spec":{"runtimeClassName":"nvidia"}}}}'

kubectl -n kube-system rollout status ds/nvidia-device-plugin-daemonset --timeout=180s

# 目的：确认 allocatable 里有卡（单卡 1，双卡 2）
kubectl get node -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}{"\n"}'
```

> k3s 会为检测到的 NVIDIA runtime 创建 `RuntimeClass/nvidia`；static manifest 本身不带 `runtimeClassName`，所以必须 patch。用 Helm 装 GPU Operator 时这一步由 chart 的 `runtimeClassName` 完成。
>
> `rollout status` 只代表 device plugin pod Ready；它还要向 kubelet 注册，`allocatable` 可能晚几秒。第一次查为空时，先确认日志有 `Registered device plugin for 'nvidia.com/gpu' with Kubelet`，再重查。双卡 instance 这里返回 `2`，不是 `1`。

### 5.5 GPU smoke test

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

看到 `nvidia-smi` 输出和 RTX 3090/4090 型号，才说明 runtime + device plugin + scheduling 三层都通了。

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

**本节目的：把 D1 的 vLLM 进程搬进 k3s，做一次端到端功能验收，并固定 §7–§9 的对照 manifest。** 它不是吞吐/延迟实验——那些在 D1/D2 已经测过；这里只回答四个问题：

1. **调度链是否通**：`runtimeClassName: nvidia` + `nvidia.com/gpu: 1` 能把 Pod 放到 GPU 上，device plugin 暴露的 `nvidia.com/gpu` 能被真正消费。
2. **权重路径是否对**：hostPath `/var/lib/models` 挂进容器；缓存完整时 initContainer 打印 `weights cached` 并跳过下载，缓存缺失时才从 HF 拉 5.7GB。
3. **服务是否可用**：startup/readiness/liveness 三个 probe 的语义正确，`/health` 变 Ready，Service 后面能 `curl /v1/models` 拿到 `qwen3-8b`。
4. **对照是否可复现**：这份 `k8s/vllm.yaml` 就是 §7 冷启动、§8 KEDA、§9 驱逐的 baseline；后面只改 replicas/删除/资源，不再改镜像、模型路径和启动参数。

**通过标准（缺一不算）：**

- `kubectl rollout status` 成功，Pod `1/1 Running`；
- 日志有 `Application startup complete` 和 `GPU KV cache size`；
- `curl /v1/models` 返回 `qwen3-8b`；
- 删除 Pod 重建时，initContainer 打印 `weights cached`，不再重新下载；
- 记录调度→容器启动、initContainer、模型加载/KV cache 三个时间点，作为 §7 的 warm 参照。

**本节不测：** 吞吐、TTFT/TPOT、并发曲线（D1/D2 已做）；KEDA 0→1/1→2（§8）；驱逐排空（§9）；多副本扩缩容（§8 的 2 卡实验）。

> 为什么用 Deployment 而不是裸 Pod：§8 的 KEDA 要 scale 一个带 ReplicaSet 的对象，§9 驱逐后也要有控制器把 Pod 重建；裸 Pod 没有这两个语义。单副本用 `Recreate`，避免滚动更新先起一个因 GPU 不足而 Pending 的第二个 Pod。

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
            cpu: "4"
            memory: "20Gi"
            nvidia.com/gpu: 1
          limits:
            cpu: "4"
            memory: "20Gi"
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
> **资源前提：** 上面的 `cpu: 4` / `memory: 20Gi` 是**每个 pod**。本次 VM 只有 **15 vCPU / 48GiB**：2×4=8 vCPU、2×20=40GiB，1→2 能放下。如果改成 `cpu: 8`，2×8=16 vCPU 超过 15，第二个副本会因 **CPU** Pending，看起来像 GPU 问题，§8 就看不到真实 1→2。所以主 manifest 直接用 4 CPU，避免实验中途再改。
>
> **不要用带 `kubeadm init` onstart 的模板：** 它会装 `containerd`/`kubeadm` 并在每次开机跑 `kubeadm init`，和 k3s 冲突，也会污染冷启动测量。建 VM 前用 `vastai search templates 'hash_id == <hash>' --raw` 看 `onstart` 是否为空；D3 用 `2c18cabd8f2f0525c2ff8446f5d4e063`（onstart 为空）。
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

把 §6.2 的 `args` 第一项和 initContainer 的缓存检查都改成 `$(MODEL_PATH)` / `$MODEL_PATH`：

```yaml
spec:
  template:
    spec:
      initContainers:
      - name: fetch-weights
        env:
        - name: HF_XET_HIGH_PERFORMANCE
          value: "1"
        - name: MODEL_PATH
          value: /models/Qwen3-8B-AWQ-v1
        args:
        - |
          set -eu
          if [ -f "$MODEL_PATH/config.json" ] && \
             find "$MODEL_PATH" -maxdepth 1 -name '*.safetensors' | grep -q .; then
            echo "weights cached"
            exit 0
          fi
          python3 -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-8B-AWQ', local_dir='$MODEL_PATH')"
        # 其余 image / command / volumeMounts 省略
      containers:
      - name: vllm
        env:
        - name: MODEL_PATH
          value: /models/Qwen3-8B-AWQ-v1
        args:
        - "$(MODEL_PATH)"
        # 其余 args / image / resources 省略
```

> **initContainer 必须和主容器共用 `MODEL_PATH`。** 只改主容器 `args` 的话，initContainer 仍检查 `/models/Qwen3-8B-AWQ`，会打印 `weights cached` 但完全没校验实际服务的 `-v1` 目录；§7 的 cold 删除 `-v1` 后也不会触发重新下载，vLLM 直接启动失败。`snapshot_download` 那段用双引号包 Python 代码、里面用单引号，`$MODEL_PATH` 才会被 shell 展开。
>
> 主实验 §6.2 用的是字面路径 `/models/Qwen3-8B-AWQ`；做本节前先把上面的改动 `kubectl apply`，否则 `kubectl set env` 只改环境变量，模型路径不会变。

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
| **cold** | 已缓存 | 删除当前 `MODEL_PATH` 对应的宿主机目录 | 权重下载 + 模型加载 + 引擎初始化，最接近“新节点” |
| **warm** | 已缓存 | 保留 | 只测模型加载 + 引擎初始化 |
| **image-cold**（可选） | `sudo k3s crictl rmi docker.io/vllm/vllm-openai:v0.34.0` 删除镜像 | 保留 | 单独测镜像拉取；`crictl rmi` 后 containerd 若保留层，只会测到本地重新注册，不是网络拉取 |

> 镜像引用名先用 `sudo k3s crictl images | grep vllm` 确认；不同 registry 前缀可能不同。
>
> 不要用 `emptyDir` 做 cold/warm 对比：Pod 一删缓存就没了，两次都是 cold，结论会错。
>
> D3 在 RTX 3090/4090 上测，**不要拿 D1 的 69s 当目标或基线**；D1 是 L4 容器内进程启动，D3 是 RTX VM 上从 scale 到 Ready。本节只比较同一台机器上的 cold vs warm，以及各阶段占比。

### 7.2 操作

```bash
# warm：权重已在宿主机
kubectl rollout restart deploy/vllm-qwen3-8b
kubectl rollout status deploy/vllm-qwen3-8b --timeout=15m

# cold：先缩到 0，等 Pod 真正退出，再删当前 MODEL_PATH 指向的宿主机目录
kubectl scale deploy/vllm-qwen3-8b --replicas=0
kubectl wait --for=delete pod -l app=vllm --timeout=180s

MODEL_DIR=$(kubectl get deploy vllm-qwen3-8b \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="MODEL_PATH")].value}')
MODEL_DIR=${MODEL_DIR:-/models/Qwen3-8B-AWQ}
case "$MODEL_DIR" in
  /models/*) HOST_DIR="/var/lib/models/${MODEL_DIR#/models/}" ;;
  *) echo "unexpected MODEL_PATH: $MODEL_DIR" >&2; exit 1 ;;
esac
echo "deleting $HOST_DIR"
sudo rm -rf "$HOST_DIR"

kubectl scale deploy/vllm-qwen3-8b --replicas=1
kubectl rollout status deploy/vllm-qwen3-8b --timeout=30m

# image-cold（可选）：先缩到 0，删掉节点上的 vLLM 镜像，再拉起
kubectl scale deploy/vllm-qwen3-8b --replicas=0
kubectl wait --for=delete pod -l app=vllm --timeout=180s

# 目的：确认没有容器还占着镜像
sudo k3s crictl ps -a | grep vllm || echo "no vllm containers"

# 目的：删镜像记录；--prune 清掉所有未被引用的镜像
sudo k3s crictl rmi docker.io/vllm/vllm-openai:v0.34.0
sudo k3s crictl rmi --prune
sudo k3s crictl images | grep vllm || echo "image removed"

kubectl scale deploy/vllm-qwen3-8b --replicas=1
kubectl rollout status deploy/vllm-qwen3-8b --timeout=30m
```

> 删之前先看 `echo "deleting $HOST_DIR"` 打的是不是当前服务的版本目录。initContainer 没和主容器共用 `MODEL_PATH` 时，`weights cached` 会骗你：删了正在服务的目录也不会重新下载。
>
> **image-cold 的可信度取决于 containerd 有没有真的删掉 blobs。** `crictl rmi` 删的是 image record；content store/snapshot 可能还留着层，重新拉起如果只花几秒，那是本地复用，不是网络拉取。要测真实网络冷拉，用一台干净 VM 或另一个没拉过该镜像的节点；不要为了这个可选场景去手删 containerd 的 content store。10GB 镜像在 900Mbps 下理论约 1.5–2 分钟，Docker Hub 限速或冷缓存会更久。image-cold 的 `init_start - scheduled` 才是镜像拉取，主容器不会再拉一次。

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

如果 initContainer 使用了和主容器相同的 vLLM 镜像，`init_start - scheduled` 主要是镜像拉取和容器创建；镜像已缓存时（event 里是 `already present`）只剩 pause/容器创建开销。`init_end - init_start` 是权重下载；`ready - main_start` 是模型加载 + 引擎初始化。

> 你的 manifest 里 initContainer 是“检查缓存，不存在才下载”。为了测 cold，必须确保 `rm -rf` 之后 initContainer 真的走了下载分支；看 `kubectl logs "$pod" -c fetch-weights`。

### 7.4 记录与实测

机器：`2×RTX 4090 24GB / driver 580.95.05 / power limit 450W / k3s v1.37.2+k3s1 / $0.8524/h`（2026-11-24，machine `20876`）。

| 场景 | 调度 (s) | 镜像 (s) | 权重下载 (s) | 模型加载+引擎 (s) | 总到 Ready (s) |
|---|---|---|---|---|---|
| cold（2026-11-24，下载到旧目录） | 0 | 1 | 56 | 83 | 141 |
| warm（2026-11-24） | 0 | 2 | 0 | 83 | 86 |
| image-cold（2026-11-24，本地复用） | 0 | 4 | 0 | 90 | 95 |

> cold 原始时间点：`created=16:50:38Z` → `scheduled=16:50:38Z` → `init_start=16:50:39Z` → `init_end=16:51:35Z` → `main_start=16:51:36Z` → `ready=16:52:59Z`。initContainer 日志 `Fetching 12 files` 从 `16:50:40.468Z` 到 `16:51:35.464Z`，实际下载约 55.0s，5.7GB ≈ 104MB/s；模型加载+引擎仍是 83s（`Loading model from scratch` `16:52:10Z`，torch.compile 27.28s，engine init 41.11s，KV cache 101,376 tokens）。init 结束到主容器启动还有 1s 未单列，故 0+1+56+83=140，总时间 141s。
>
> **cold 口径（已接受）：** initContainer 仍用旧脚本检查/下载 `/models/Qwen3-8B-AWQ`，实际服务的 `/models/Qwen3-8B-AWQ-v1` 没被删（`config.json` mtime 仍是 16:18Z）。这 56s 是真实的 5.7GB 下载，且 vLLM 必须等 init 完成后才启动；下载目标目录不改变字节数和下载耗时，所以 141s 作为 cold 数字可用。严格说它不是“服务路径 cold”的对照：`-v1` 未删，加载的是已有缓存。若之后要做严格对照，再修 §6.5 的 initContainer 并删 `-v1` 重跑。
>
> warm 原始时间点：`created=16:45:59Z` → `scheduled=16:45:59Z` → `init_start=16:46:01Z` → `init_end=16:46:01Z`（`weights cached`）→ `main_start=16:46:02Z` → `ready=16:47:25Z`。镜像已在节点上（event `Container image ... already present`），所以“镜像 2s”是 pause/容器创建开销，不是拉取；init 结束到主容器启动还有 1s 未单列，故 0+2+0+83=85，总时间 86s。
>
> warm 的 83s 内部：vLLM banner `16:46:12Z`；`Loading model from scratch` `16:46:36Z`；torch.compile `16:46:43Z`→`16:47:10Z`（27.23s）；engine init 共 41.01s；`GPU KV cache size: 101,376 tokens`（8192 上下文最大并发 12.38x）；`Application startup complete` `16:47:24Z`；Ready `16:47:25Z`。
>
> image-cold 原始时间点：`created=17:00:19Z` → `scheduled=17:00:19Z` → `init_start=17:00:23Z` → `init_end=17:00:23Z`（`weights cached`）→ `main_start=17:00:24Z` → `ready=17:01:54Z`。event：`Pulling` → `Pulled ... in 942ms ... Image size: 10036574238 bytes`；`init_start - scheduled` = 4s（0.9s 拉取 + 容器创建）。模型加载+引擎 90s：`Loading model from scratch` `17:00:59Z`，torch.compile 28.14s，engine init 44.00s，KV cache 101,376 tokens。init 结束到主容器启动还有 1s 未单列，故 0+4+0+90=94，总时间 95s。
>
> **image-cold 不是网络冷拉：** 10GB 镜像 942ms 拉完，等效 10GB/s 以上，说明 `crictl rmi` 只删了 image record，containerd 的 content store/snapshot 还在本地复用了层。这个数字只证明“镜像记录删除后能重新注册”，不能回答“新节点从 Docker Hub 拉 10GB 要多久”。真实网络冷拉要用干净 VM/节点，或在另一个从没拉过该镜像的 host 上测；不要手删 content store。90s 对 83s 的差异是单次噪声，不要归因到镜像拉取（镜像只占 0.9s）。
>
> 三次运行都说明实际服务的是 `/models/Qwen3-8B-AWQ-v1`（§6.5 之后），但 initContainer 当时仍检查 `/models/Qwen3-8B-AWQ`。§6.5 已改成两者共用 `MODEL_PATH`；若之后要做严格 cold 对照或重跑 image-cold，先重新 `kubectl apply`，否则会删错目录或根本不触发下载。
>
> 这三次测量时 Deployment 的 `cpu` / `memory` 是 `8` / `32Gi`；§6.2 之后已改为 `4` / `20Gi`。CPU/memory request/limit 不直接参与 vLLM 的启动路径，预计不影响这组时间。另外 17:44 重启后 kernel 从 `6.8.0-59` 变成 `6.8.0-149`、driver 从 `580.95.05` 变成 `580.178.04`。**决定不重跑 warm**：§7 这组数字只作为旧环境记录，§8 的扩容窗口按新环境单独记录，不直接和 86s / 141s 对比。

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
# 终端 A：前台阻塞命令，必须一直保持运行
kubectl -n monitoring port-forward svc/kps-kube-prometheus-stack-prometheus 9090:9090

# 终端 B：另开一个 shell
curl -sG http://localhost:9090/api/v1/query \
  --data-urlencode 'query=vllm:num_requests_waiting' | jq .
```

不想开两个终端，也可以在一段命令里后台起 port-forward、查完再杀掉：

```bash
kubectl -n monitoring port-forward svc/kps-kube-prometheus-stack-prometheus 9090:9090 \
  >/tmp/pf.log 2>&1 &
sleep 3
curl -sG http://localhost:9090/api/v1/query \
  --data-urlencode 'query=vllm:num_requests_waiting' | jq .
kill %1
```

正常输出是 `"status": "success"`，`result` 里有 1 条，`value` 的第二项是 `"0"`——**0 是正常值**（当前没有排队请求），不是验证失败。如果 `result` 为空，再看 ServiceMonitor 和 target：

```bash
curl -sG http://localhost:9090/api/v1/query \
  --data-urlencode 'query=up{job=~".*vllm.*"}' | jq .
```

`value` 为 `"1"` 才说明 Prometheus 正在 scrape vLLM 的 `/metrics`。

> `port-forward` 是前台阻塞命令：在同一个 shell 里直接跑 `curl` 会一直等不到提示符；换到另一个 shell 时如果 port-forward 已退出，就会得到 `Connection refused`。SSH 断开或命令超时也会杀掉 port-forward。`ss -ltnp | grep 9090` 没有输出，就说明 9090 根本没在监听。

### 8.2 装 KEDA

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm install keda kedacore/keda -n keda --create-namespace
kubectl -n keda get pods
```

### 8.3 ScaledObject

`ScaledObject` 是 KEDA 的 CRD，不是 HPA 的替代品。它**不直接改 Deployment 的 `replicas`**，而是做三件事：

1. 按 `pollingInterval` 查询 trigger（这里是 Prometheus）；
2. 把查询结果通过 KEDA metrics adapter 暴露成 `external.metrics.k8s.io` 指标；
3. 创建并维护一个 HPA（名字是 `keda-hpa-<ScaledObject 名>`），由 HPA 真正改 Deployment 的 replicas。

链路：

```text
Prometheus --PromQL--> KEDA operator
                         |
                         v
              external.metrics.k8s.io
                         |
                         v
              HPA keda-hpa-vllm-scaler
                         |
                         v
              Deployment vllm-qwen3-8b
```

所以排障要分三层：Prometheus 查询有没有值 → KEDA 有没有把指标暴露出来 → HPA 有没有算出新副本数。不要一看到副本没变就只查 Deployment。

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: vllm-scaler
spec:
  scaleTargetRef:
    name: vllm-qwen3-8b       # 同 namespace 的 Deployment
  minReplicaCount: 1          # 不缩到 0：GPU 冷启动 86–141s，Service 不能没有 endpoint
  maxReplicaCount: 2          # 本机 2 张 4090；单卡机器这里只能是 1
  pollingInterval: 15         # KEDA 每 15s 查一次 Prometheus
  cooldownPeriod: 300         # 只影响 scale-to-zero；min=1 时 2→1 看 HPA behavior
  triggers:
  - type: prometheus
    metadata:
      serverAddress: http://kps-kube-prometheus-stack-prometheus.monitoring.svc:9090
      metricName: vllm_requests_waiting   # KEDA/scaler 的指标名；HPA 里实际是 s0-prometheus
      query: sum(vllm:num_requests_waiting)  # 必须返回单条序列
      threshold: "8"            # 目标队列深度；字符串
EOF

kubectl get scaledobject
kubectl get hpa
```

| 字段 | 值 | 作用 | 注意 |
|---|---|---|---|
| `scaleTargetRef.name` | `vllm-qwen3-8b` | 要伸缩的 Deployment | ScaledObject 必须和 Deployment 同 namespace，KEDA 不支持跨 namespace 直接 scale |
| `minReplicaCount` | `1` | 最少副本 | 设 `0` 才能 scale-to-zero，但需要能缓冲请求的入口；见下文 |
| `maxReplicaCount` | `2` | 最多副本 | 不能超过节点空闲 GPU 数；本机 2 张 4090 |
| `pollingInterval` | `15` | KEDA 刷新 ScaledObject 状态/事件的间隔（秒） | KEDA 2.21 在 `minReplicaCount: 1` 时**不影响 HPA 伸缩**：admission event 明确提示它只影响 scale-to-zero、`idleReplicaCount` 或 `useCachedMetrics`；真正触发伸缩的是 HPA 的 sync period |
| `cooldownPeriod` | `300` | 最后一次 trigger 活跃后等多久缩到 0 | 只在 `minReplicaCount: 0` 时生效；`min=1` 时 2→1 由 HPA 的 scaleDown stabilization 控制 |
| `triggers[].type` | `prometheus` | trigger 类型 | 还支持 cpu/memory/rabbitmq/kafka 等 |
| `serverAddress` | `http://...monitoring.svc:9090` | Prometheus HTTP API | 从 `keda-operator` Pod 里必须能解析和访问；NetworkPolicy 要放行 |
| `metricName` | `vllm_requests_waiting` | KEDA/scaler 的指标名 | HPA 实际用 `s0-prometheus`；这个值不会原样出现在 HPA 的 `metric.name` 里；用下划线，避免冒号 |
| `query` | `sum(vllm:num_requests_waiting)` | 实际 PromQL | 必须返回单条序列；多 Pod/多 engine 要先 `sum`/`avg` 聚合 |
| `threshold` | `"8"` | 目标值 | 字符串；HPA 用 external metric 的 averageValue 作为目标 |

### 8.3.1 KEDA 生成的 HPA：完整对象与字段来源

`kubectl get hpa keda-hpa-vllm-scaler -o yaml` 的实测对象（`creationTimestamp` / `resourceVersion` / `uid` 每次重建都会变）：

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  annotations:
    kubectl.kubernetes.io/last-applied-configuration: |
      {"apiVersion":"keda.sh/v1alpha1","kind":"ScaledObject","metadata":{"annotations":{},"name":"vllm-scaler","namespace":"default"},"spec":{"cooldownPeriod":300,"maxReplicaCount":2,"minReplicaCount":1,"pollingInterval":15,"scaleTargetRef":{"name":"vllm-qwen3-8b"},"triggers":[{"metadata":{"metricName":"vllm_requests_waiting","query":"sum(vllm:num_requests_waiting)","serverAddress":"http://kps-kube-prometheus-stack-prometheus.monitoring.svc:9090","threshold":"8"},"type":"prometheus"}]}}
  creationTimestamp: "2026-11-24T18:06:06Z"
  generation: 1
  labels:
    app.kubernetes.io/managed-by: keda-operator
    app.kubernetes.io/name: keda-hpa-vllm-scaler
    app.kubernetes.io/part-of: vllm-scaler
    app.kubernetes.io/version: 2.21.1
    scaledobject.keda.sh/name: vllm-scaler
  name: keda-hpa-vllm-scaler
  namespace: default
  ownerReferences:
  - apiVersion: keda.sh/v1alpha1
    blockOwnerDeletion: true
    controller: true
    kind: ScaledObject
    name: vllm-scaler
    uid: 435b19d6-9de3-4a14-9917-ddc7f3ba77e2
  resourceVersion: "7006"
  uid: 2bcf194d-5d21-4d51-a8b2-8dc3dd06e046
spec:
  maxReplicas: 2
  metrics:
  - external:
      metric:
        name: s0-prometheus
        selector:
          matchLabels:
            scaledobject.keda.sh/name: vllm-scaler
      target:
        averageValue: "8"
        type: AverageValue
    type: External
  minReplicas: 1
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: vllm-qwen3-8b
```

这个对象不是手写的，是 KEDA operator 根据 `ScaledObject/vllm-scaler` 生成的。字段来源：

| 字段 | 值 | 来源 | 意义 / 注意 |
|---|---|---|---|
| `apiVersion` / `kind` | `autoscaling/v2` / `HorizontalPodAutoscaler` | Kubernetes HPA | KEDA 最终通过标准 HPA 执行伸缩，不是自己改 replicas |
| `metadata.annotations.kubectl.kubernetes.io/last-applied-configuration` | ScaledObject 的 JSON | `kubectl apply` ScaledObject 时的记录，KEDA 带到 HPA 上 | 内容是 ScaledObject，不是 HPA 配置；不参与伸缩，可忽略 |
| `metadata.creationTimestamp` / `generation` / `resourceVersion` / `uid` | 创建时间、版本号、UID | Kubernetes API server | 集群内唯一；重建 HPA 会变，不要写进配置 |
| `metadata.labels.app.kubernetes.io/managed-by` | `keda-operator` | KEDA | 标记这个 HPA 由 KEDA 管理，不要手改 |
| `metadata.labels.app.kubernetes.io/name` | `keda-hpa-vllm-scaler` | KEDA | 与 `metadata.name` 一致 |
| `metadata.labels.app.kubernetes.io/part-of` | `vllm-scaler` | ScaledObject 名 | 表示归属哪个 ScaledObject |
| `metadata.labels.app.kubernetes.io/version` | `2.21.1` | KEDA 版本 | 排障时先确认版本，字段形态可能随版本变 |
| `metadata.labels.scaledobject.keda.sh/name` | `vllm-scaler` | KEDA | 关键关联标签；external metric 的 selector 也用它 |
| `metadata.name` | `keda-hpa-vllm-scaler` | KEDA 命名规则 `keda-hpa-<ScaledObject 名>` | 不要手建同名 HPA |
| `metadata.namespace` | `default` | 与 ScaledObject 同 namespace | ScaledObject 不能跨 namespace 直接 scale |
| `metadata.ownerReferences` | `ScaledObject/vllm-scaler`，`controller: true` | KEDA | HPA 的属主是 ScaledObject；删 ScaledObject 会级联删 HPA |
| `spec.minReplicas` | `1` | ScaledObject `minReplicaCount: 1` | 不缩到 0；原因见 §8.3.2 |
| `spec.maxReplicas` | `2` | ScaledObject `maxReplicaCount: 2` | 不能超过节点空闲 GPU 数 |
| `spec.scaleTargetRef.apiVersion` / `kind` / `name` | `apps/v1` / `Deployment` / `vllm-qwen3-8b` | ScaledObject `scaleTargetRef.name`，KEDA 默认补 `apps/v1 Deployment` | 真正被伸缩的对象 |
| `spec.metrics[].type` | `External` | KEDA | 指标来自 `external.metrics.k8s.io`，由 KEDA metrics adapter 提供 |
| `external.metric.name` | `s0-prometheus` | **KEDA 生成**：`s` + trigger 序号 `0` + `-` + scaler 类型 `prometheus` | **不是** ScaledObject 里的 `metricName: vllm_requests_waiting`；有些 KEDA 版本会带 metricName 后缀，实际以 `kubectl get hpa -o yaml` 为准 |
| `external.metric.selector.matchLabels` | `scaledobject.keda.sh/name: vllm-scaler` | KEDA | 让 metrics adapter 只返回这个 ScaledObject 的指标 |
| `external.target.type` | `AverageValue` | KEDA / HPA external metric | HPA 用 external metric 的平均值目标计算副本数 |
| `external.target.averageValue` | `"8"` | ScaledObject `triggers[0].metadata.threshold: "8"` | 目标队列深度；`sum()` 时近似 `desiredReplicas = ceil(totalQueue / 8)` |
| `status`（示例里没有） | — | HPA controller 写入 | `kubectl get hpa` 的 `TARGETS` / `REPLICAS` 来自 `status.currentMetrics` / `status.desiredReplicas`，不在 spec 里 |

几个容易误解的点：

- **`metricName` 不是 HPA 的 `metric.name`。** ScaledObject 里写的是 `metricName: vllm_requests_waiting`，但 HPA 实际用 `s0-prometheus`。所以不要在 HPA 里搜 `vllm_requests_waiting`，也不要用它判断 KEDA 是否生效；要看 `s0-prometheus` 和 `scaledobject.keda.sh/name` selector。
- **`pollingInterval`、`cooldownPeriod`、`serverAddress`、`query` 不在 HPA 里。** 它们是 ScaledObject/trigger 的配置：KEDA operator 按 `pollingInterval` 查 Prometheus，执行 `query`，把结果通过 adapter 暴露成 `s0-prometheus`；HPA 只消费结果。
- **`behavior` 没出现。** 说明 KEDA 没给 HPA 设置自定义行为，HPA 用默认的 scaleDown stabilization（300s）。`cooldownPeriod: 300` 只影响 scale-to-zero；`minReplicaCount: 1` 时 2→1 由 HPA 这个默认窗口控制。
- **`ownerReferences` 决定生命周期。** 删 ScaledObject 时 HPA 会被级联删除；反过来手删 HPA，KEDA 会按 ScaledObject 重新创建它。

`threshold: "8"` 的语义：KEDA 把 `sum(vllm:num_requests_waiting)` 作为 external metric，HPA 的目标是每个副本平均 8 个排队请求。对 `sum()` 来说，可以近似记成：

```text
desiredReplicas = ceil(totalQueue / 8)
```

在 1 副本时：队列 0–8 → 1 副本；9–16 → 2 副本；17 以上会被 `maxReplicaCount: 2` 截断。在 2 副本时队列降到 8 以下，HPA 会想缩回 1，但要等 scaleDown stabilization（默认 300s），不会立刻缩。

> `sum()` 和 `avg()` 的语义不同：`sum(vllm:num_requests_waiting)` 是全局排队总数，threshold 8 表示“总队列 8 就加一个副本”；`avg(...)` 是每副本平均排队，threshold 8 表示“平均每副本 8 个才加”。D3 用 `sum()`，因为队列是全局 backlog。不要返回多条序列；KEDA 的 Prometheus scaler 期望单条结果，多 Pod 时先聚合。

### 8.3.2 为什么 `minReplicaCount` 是 1，不是 0

D3 不测 scale-to-zero，原因是 vLLM 本身不排队：

- 副本为 0 时，Service 没有 endpoint，新请求直接失败，不会在 vLLM 里形成 `num_requests_waiting`；
- Prometheus 里没有 vLLM Pod，`vllm:num_requests_waiting` 序列消失，KEDA 没有信号把副本从 0 拉回 1；
- 要实现 0→1，需要一个能缓冲请求的入口（KEDA HTTP add-on、Knative、网关队列等），或者用别的外部队列指标。

另外 GPU 冷启动 86–141s，保留 1 个 warm 副本是 D3 的基线。`cooldownPeriod: 300` 在 `min=1` 时不负责 2→1；2→1 由 HPA 的 scaleDown stabilization 控制。要显式控制就写：

```yaml
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 300
```

### 8.3.3 资源前提：HPA 说 2 不等于第二个 Pod 能跑

本机是 2×4090，GPU 够，但只有 **15 vCPU / 48GiB**。§6.2 的 Deployment 现在是 `cpu: 4` / `memory: 20Gi`；两个副本需要 **8 CPU / 40GiB**，能放进 15 vCPU / 48GiB，1→2 可以真实调度。如果谁把 CPU 改回 8，2×8=16 > 15，第二个会先因 CPU Pending，不是 KEDA 失败。

§7 的基线数字是在 `8 CPU / 32Gi` 下测的；§8 的扩容实验用 `4 CPU / 20Gi`，两组不要混。`maxReplicaCount: 2` 也不要超过实际 GPU 数，否则第三个副本会 Pending 在 GPU 上。另外 `shm` 是 `medium: Memory` 的 2Gi，会计入 Pod 实际内存；2×20Gi + 2×2Gi + 系统接近 48GiB，跑 1→2 时要盯 `kubectl top pod` 和 OOMKilled。

### 8.3.4 排障顺序

```bash
# 1) Prometheus 查询本身有没有值（port-forward 后台跑，查完杀掉）
kubectl -n monitoring port-forward svc/kps-kube-prometheus-stack-prometheus 9090:9090 \
  >/tmp/pf.log 2>&1 &
sleep 3
curl -sG http://localhost:9090/api/v1/query \
  --data-urlencode 'query=sum(vllm:num_requests_waiting)' | jq .
kill %1

# 2) KEDA 有没有把 ScaledObject 标成 Ready
kubectl describe scaledobject vllm-scaler

# 3) KEDA operator / metrics adapter 日志
kubectl -n keda get pods
kubectl -n keda logs deploy/keda-operator --tail=80
kubectl -n keda logs deploy/keda-operator-metrics-apiserver --tail=80

# 4) HPA 有没有拿到 external metric
kubectl describe hpa keda-hpa-vllm-scaler
```

常见现象：

| 现象 | 原因 | 处理 |
|---|---|---|
| `ScaledObject` `READY=False` | trigger 配置错、Prometheus 不可达 | `kubectl describe scaledobject` 看 condition 和 event |
| HPA `TARGETS` 是 `<unknown>/8` | KEDA metrics adapter 没拿到指标 | 查 `keda-operator-metrics-apiserver` 日志；先在 Prometheus 里跑同样的 PromQL |
| `FailedGetExternalMetric` | HPA 找不到 `s0-prometheus`：`serverAddress` DNS/网络不通、KEDA metrics adapter 没 Ready，或 ScaledObject 没 Ready | 查 `kubectl -n keda get pods` 和 adapter 日志；不要在 HPA 里找 `vllm_requests_waiting`，那是 ScaledObject 的 `metricName`，不是 HPA 的 `metric.name` |
| HPA 里没有 `vllm_requests_waiting` | KEDA 把 trigger 暴露成 `s0-prometheus` + `scaledobject.keda.sh/name` selector | 看 `metric.name: s0-prometheus` 和 selector；这是正常现象 |
| HPA 算出 2，但第二个 Pod `Pending` | CPU/内存/GPU 不够 | 看 `kubectl describe pod` 的 event；按 §8.3.3 改资源 |
| 队列很高但 HPA 不动 | 查询返回空/多序列，或 `threshold` 太大 | 直接跑 PromQL 比较结果；多序列用 `sum()` |

### 8.3.5 扩容时间线要记什么

KEDA 不是“队列一超 8 立刻多一个 Pod”。实际链路是：

```text
队列超过 threshold
  → HPA 下一次 sync（默认 15s）通过 external metrics API 取 s0-prometheus
  → KEDA metrics adapter 查询 Prometheus（Prometheus 已按 5s scrape）
  → HPA 算出 desiredReplicas > 1
  → Deployment 创建 Pod
  → 调度 + 镜像/权重/模型加载（§7 的 86–141s）
  → Pod Ready，Service 才有新 endpoint
```

> KEDA 2.21 的 admission event 会提示：`PollingInterval is configured but is not relevant for scaling...`。`minReplicaCount: 1` 时不要把它当成伸缩延迟；HPA 的 sync period 才是采样节拍。

所以扩容实验至少记四个时间点：

1. 队列首次超过 8 的时间（压测脚本/`kubectl get --raw` 或 Prometheus 查询）；
2. HPA `REPLICAS` 从 1 变 2 的时间（`kubectl get hpa -w`）；
3. 第二个 Pod `Scheduled` 的时间（`kubectl get pod -o json` 的 `PodScheduled`）；
4. 第二个 Pod `Ready` 的时间（condition `Ready`）。

`HPA 变 2 → Pod Ready` 这一段就是 D3 要讲的“扩容代价”；它主要不是 KEDA 慢，而是新副本的冷启动慢。反过来，如果 HPA 一直不变 2，才去查 KEDA/Prometheus。

> 不要再给同一个 Deployment 手建 HPA；KEDA 已经生成了 `keda-hpa-vllm-scaler`，两个 HPA 会互相打架。删除 ScaledObject 时也要确认 HPA 一起被清理。

### 8.4 压测

**确认 Deployment 是 `cpu: 4` / `memory: 20Gi`。** §6.2 的 YAML 已经是 4 CPU；如果集群里还是旧 manifest（8 CPU），先改，否则 HPA 扩到 2 时第二个 Pod 会因 CPU Pending。正常情况下先确认：

```bash
kubectl get deploy vllm-qwen3-8b \
  -o jsonpath='{.spec.template.spec.containers[0].resources}{"\n"}'
```

如果输出不是 `cpu: 4` / `memory: 20Gi`，再执行：

```bash
kubectl set resources deploy/vllm-qwen3-8b \
  --requests=cpu=4 --limits=cpu=4
kubectl rollout status deploy/vllm-qwen3-8b --timeout=15m
```

§6.2 的基线 manifest 已经是 `4 CPU / 20Gi`；§7 的数字是历史上在 `8 CPU / 32Gi` 下测的，§8 用当前配置，两组不要混。

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
    --num-prompts 600 \
    --max-concurrency 128 \
    --ignore-eos \
    --temperature 0 \
    --percentile-metrics ttft,tpot,itl,e2el \
    --metric-percentiles 50,95,99
```

> bench Pod 没有挂 hostPath，`--tokenizer Qwen/Qwen3-8B` 会从 HF 拉 tokenizer（几十 MB）。离线集群要改成挂 `/var/lib/models` 并用 `--tokenizer /models/Qwen3-8B-AWQ`（与当前 Deployment 的 `MODEL_PATH` 一致）；`-it` 只适合交互终端，脚本里去掉。

#### 8.4.1 为什么这条压测会触发 KEDA

不是 `vllm bench` 直接调用 KEDA，也不是 KEDA 在监听某个 bench flag。触发链是：

```text
vllm bench --max-concurrency 128
  → 同一时刻最多 128 个 HTTP 请求打到 Service
  → 1 个 vLLM 副本，--max-num-seqs 64
  → 64 条进入 running batch，其余在 engine 队列里等
  → vLLM 暴露 vllm:num_requests_waiting（gauge，>0）
  → Prometheus 每 5s scrape 一次（ServiceMonitor interval: 5s）
  → HPA 每 15s sync 一次，通过 external metrics API 取 s0-prometheus
  → KEDA metrics adapter 用 sum(vllm:num_requests_waiting) 查 Prometheus
  → 结果 > threshold 8
  → HPA 算出 desiredReplicas > 1
  → Deployment 创建第二个 Pod
  → 新 Pod Ready 前队列继续堆积；Ready 后 Service 把请求分到两个 Pod
```

关键点：

- **`--max-concurrency` 是压测客户端侧的并发数**，KEDA 完全看不到它；它只是用来制造“等待请求”。
- **真正触发 KEDA 的是 `vllm:num_requests_waiting`**：vLLM 的 engine 队列里等待调度的请求数，是一个 gauge。
- vLLM 的 `--max-num-seqs 64` 是每个副本的 running batch 上限。128 个并发请求进来，64 条在跑，其余在等，所以队列很容易超过 `threshold: 8`。
- `--num-prompts` 决定总共发多少请求。如果请求数不够（例如只发 300 个），会在新 Pod Ready 前就跑完，队列掉下去，HPA 可能还没完成扩容；所以命令里用 `600`，必要时加到 `1000`。
- `--random-output-len 256` + `--ignore-eos` 让每个请求有足够的 decode 工作，队列不会瞬间排空；`--random-input-len 1024` 影响 prefill 工作量，但不是触发器。
- `--temperature 0` 只为可复现，`--percentile-metrics` 只影响 bench 输出，都和 KEDA 无关。

各 flag 在触发链里的角色：

| flag | 在触发链里的作用 |
|---|---|
| `--max-concurrency 128` | **关键**：并发请求数 > `max-num-seqs 64`，制造 waiting 队列 |
| `--num-prompts 600` | 压测持续时间；太小会在第二个 Pod Ready 前结束 |
| `--random-input-len 1024` | 每个请求的 prefill 工作量；影响 running batch 占用 |
| `--random-output-len 256` + `--ignore-eos` | 每个请求的 decode 工作量；让队列维持到扩容完成 |
| `--temperature 0` | 不影响触发，只保证可复现 |
| `--percentile-metrics` / `--metric-percentiles` | 只影响 bench 统计输出，不参与 KEDA |

**为什么 `--max-concurrency 64` 不够：** 它和 `--max-num-seqs 64` 相等，64 个请求可能全部被 engine 接走，`num_requests_waiting` 接近 0，KEDA 不会触发。要用 128 或更高，让 running batch 满、其余排队。如果你把 vLLM 的 `--max-num-seqs` 调大，压测并发也要相应调大。

**2026-11-24 实测反例：** 用旧的 `--num-prompts 300 --max-concurrency 64` 跑完后：

- `vllm:request_success_total{finished_reason="length"}` = 300，说明请求确实到了 vLLM；
- `sum(vllm:num_requests_waiting)` 只在开始出现一次 `29`，下一个采样点就是 `0`；
- `sum(vllm:num_requests_running)` 很快到 `64` 并保持，说明 64 条已经在跑，没有持续等待；
- HPA `TARGETS 0/8`、`REPLICAS 1`，KEDA 没算错，是队列没有持续超过 8。

原因是 `--max-concurrency 64` 刚好等于 `--max-num-seqs 64`：64 个请求全部被 engine 接走，等待队列只在启动瞬间出现。HPA 每 15s 采样一次，5s 的瞬时尖峰很容易错过。用 `--max-concurrency 128` 让 64 条持续等待，才能稳定触发。

压测期间确认队列：

```bash
kubectl -n monitoring port-forward svc/kps-kube-prometheus-stack-prometheus 9090:9090 \
  >/tmp/pf.log 2>&1 &
sleep 3
curl -sG http://localhost:9090/api/v1/query \
  --data-urlencode 'query=sum(vllm:num_requests_waiting)' | jq .
kill %1
```

`value` 超过 `8`，再看 `kubectl get hpa -w` 的 `REPLICAS` 是否从 1 变 2。如果队列一直 0，说明并发不够或压测已经结束；如果队列 >8 但 HPA 不动，去查 KEDA/ScaledObject（§8.3.4）。

> 这是扩容实验，不是吞吐基线；TTFT/P99 变差不代表模型有问题。目标是让 `sum(vllm:num_requests_waiting) > 8` 并维持到第二个 Pod Ready。

同时观察：

```bash
kubectl get pods -w
kubectl get hpa -w
kubectl get events --sort-by=.lastTimestamp | tail -20
```

### 8.5 单卡预期：1→2 会 Pending

> 本机是 2×4090，实际应看 §8.6；这一节保留给单卡节点/降级路径。单卡时第二个副本会因 `Insufficient nvidia.com/gpu` Pending。

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
- Ready 之后 Endpoint 加入，后续请求才会分到新 Pod；但如果压测在 Ready 前结束，新 Pod 一个请求都接不到（本次实测就是）；
- 所以“KEDA 扩容”不是立刻变好，而是“先更糟，几十秒后才更好”。这就是 D3 要写进结论的曲线。

**2026-11-24 实测（4 CPU / 20Gi，2×4090，KEDA 2.21.1）：**

| 时间点 | 实测 | 说明 |
|---|---|---|
| `t_trigger` | 18:27:15Z | `sum(vllm:num_requests_waiting)=107`，第一次超过 8 |
| HPA 决策 | 18:27:22Z | `SuccessfulRescale New size: 2` |
| `t_scheduled` | 18:27:22Z | 第二个 Pod 创建/调度 |
| `t_running` | ≈18:27:50Z | 主容器 running（Prometheus 第一个采样点） |
| `t_ready` | 18:29:18Z | 第二个 Pod Ready；距 HPA 决策 **116s** |
| `t_first_success` | **未发生** | 第二个 Pod 处理 **0** 个请求 |
| 队列归零 | 18:29:05Z | bench 600 个请求结束，比第二个 Pod Ready 早 **13s** |
| 缩回 1 | 18:33:53Z | `New size: 1`，约 5 分钟后 |

**这次扩容没有帮到这批流量。** 第二个 Pod 在 18:29:18 Ready，但 600 个请求在 18:29:05 就全部完成；`vllm:request_success_total{finished_reason="length"}` 显示第一个 Pod **600**、第二个 Pod **0**。HPA 确实扩到了 2，第二个 Pod 也确实用了第二张 GPU（`nvidia-smi` 同时有两个 `VLLM::EngineCore`），但它 Ready 时队列已经空了。

要看到第二个 Pod 真正分担请求，必须让压测持续到 Ready 之后：把 `--num-prompts` 加到 `1000–2000`，或提高 `--random-output-len` / 降低吞吐。否则只能证明“扩容机制通了”，不能证明“扩容降低了 P99”。

这也正是 D3 的结论：扩容的代价是 **116s 冷启动**；如果流量窗口短于这个时间，扩容对当前这批请求没有帮助，只是为后续流量准备容量。

### 8.7 scale-to-zero 实验（可选，但很有说服力）

把 `minReplicaCount` 改成 `0`，等 `cooldownPeriod` 过去：

```bash
kubectl patch scaledobject vllm-scaler --type merge -p '{"spec":{"minReplicaCount":0}}'
kubectl get pods -w
# 等到 Pod 数为 0（cooldownPeriod 默认 300s，别在 1 分钟后就下结论）
kubectl get pods -l app=vllm
```

Pod 缩到 0 后，先确认 Service 没有 endpoint：

```bash
kubectl get endpoints vllm-qwen3-8b
# ENDPOINTS 应该是 <none>
```

再发请求（这就是“发一个请求”的命令）：

```bash
kubectl run curl-trigger --rm -it --restart=Never \
  --image=curlimages/curl --command -- \
  curl -v -m 30 -X POST http://vllm-qwen3-8b:8000/v1/completions \
    -H 'Content-Type: application/json' \
    -d '{"model":"qwen3-8b","prompt":"hello","max_tokens":16,"temperature":0}'
```

预期：`connection refused` / `no route to host` / 超时。请求到不了 vLLM，也到不了 KEDA。

**关键：这条请求不会触发扩容。** 当前 ScaledObject 用的是 `sum(vllm:num_requests_waiting)`，这个指标由 vLLM Pod 暴露；副本为 0 时没有 Pod、没有 `/metrics`、没有这条序列，KEDA 没有信号。Service 也没有 endpoint 可以排队，请求直接失败。

所以“发一个请求触发扩容”只在有 **interceptor / 队列** 时成立。

**需要 Knative 吗？不需要。** Knative 是另一条完整的 serverless 路线，不是 KEDA HTTP add-on 的前置条件。可选路线：

| 方案 | 0 副本时谁接住请求 | 触发信号 | 适合 | 代价 |
|---|---|---|---|---|
| KEDA HTTP add-on | interceptor | HTTP 请求数/并发 | 同步 HTTP，想继续用 KEDA | 多一套 interceptor/operator；客户端要等冷启动 |
| Knative Serving | activator | 请求并发 | 完整 serverless | 更重：Serving/Kourier/autoscaler 等；它自己就能 0→1，通常不再让 KEDA 管这个 HTTP 服务 |
| 外部队列（Redis/Kafka/SQS） | broker | 队列深度 | 异步/批处理 | 请求必须异步，不能同步返回 |
| `minReplicaCount: 1` | 不需要 | 无 | chat/低延迟 | 一直占一张 GPU |

D3 不装任何一套：直接 curl 只能得到“0 副本时请求失败”的负结果；这本身就是要写进结论的：**chat 场景不要 scale-to-zero，除非前面有能缓冲请求的网关。**

如果只是想测 0→1 的冷启动，可以手工把 `minReplicaCount` 改回 1（这不是 request-driven，报告里要注明）：

```bash
kubectl patch scaledobject vllm-scaler --type merge -p '{"spec":{"minReplicaCount":1}}'
kubectl get pods -w
# 记录 created → Ready；测完再改回 0
```

请求失败和手工 0→1 的冷启动要分开写，不要混成“KEDA 被请求触发”。

结论：chat 场景用 `minReplicaCount: 1` + 预热池；scale-to-zero 只给异步/批处理，而且前面要有 HTTP add-on 或队列接住请求。

> D4 的完整 request-driven 0→1 见 [`d4-llm-d-learning.md`](./d4-llm-d-learning.md) Lab 0：KEDA HTTP Add-on 的 `InterceptorRoute` + `external-push` ScaledObject。

---

## 9. Lab 4：驱逐与优雅退出

### 9.1 先修概念：删除 Pod 时到底发生什么

`kubectl delete pod`、Deployment 缩容、`kubectl drain` 最终都会让 apiserver 给 Pod 打上 `deletionTimestamp`。之后的顺序是：

```text
1. apiserver 标记 Pod Terminating
2. EndpointSlice controller 把 Pod 从 ready endpoints 摘除
3. kubelet 执行 preStop hook（如果有）
4. preStop 结束，kubelet 给容器 PID 1 发 SIGTERM
5. vLLM 停止接新请求，等待在途请求，最多 --shutdown-timeout
6. 进程退出；超过 terminationGracePeriodSeconds 还没退出，kubelet 发 SIGKILL
```

三个旋钮不是一回事：

| 旋钮 | 作用 | 不配会怎样 |
|---|---|---|
| `preStop` | 在 SIGTERM 前等待，给 Endpoint/kube-proxy/网关收敛时间 | SIGTERM 可能早于 endpoint 摘除，新请求仍被路由到正在退出的 Pod |
| `--shutdown-timeout` | vLLM 收到 SIGTERM 后等在途请求的上限 | 默认可能立即退出，在途请求被 abort |
| `terminationGracePeriodSeconds` | kubelet 从 deletion 开始算的总宽限；包含 preStop + shutdown | 太短会在 vLLM 还没排空时 SIGKILL（exit 137） |

时间关系必须满足：

```text
terminationGracePeriodSeconds > preStop + shutdown-timeout + 余量
120s > 15s + 90s + 15s
```

另外两个概念：

- **自愿驱逐**：`kubectl drain`、节点维护、升级，走 Eviction API，受 PDB 约束；
- **非自愿/直接删除**：`kubectl delete pod`、节点故障、OOM，**不受 PDB 保护**。

本实验只看“删除瞬间已经在途的请求”。删除后 Deployment 会起新 Pod，但新 Pod 要几十秒才 Ready；这段窗口的**新请求**失败是另一件事，不能算进排空成功率。

### 9.2 实验矩阵与通过标准

| 场景 | preStop | shutdown-timeout | grace | 请求 | 目的 |
|---|---|---|---|---|---|
| A 无排空基线 | 0 | 默认 | 30s | 8 × 512 | 证明 SIGTERM 直接打断在途请求 |
| B 有排空 | 15s | 90s | 120s | 8 × 512 | 证明在途请求能跑完、无 SIGKILL |
| C 窗口不够 | 15s | 90s | 120s | 32 × 1024 | 证明 shutdown-timeout 必须大于最长请求 |
| D PDB | 15s | 90s | 120s | 8 × 512 | 说明 PDB 只保护自愿驱逐 |

通过标准：

- A：至少出现 1 个失败/异常，或 Pod 很快退出（记录实际结果；如果 vLLM 默认也等了，说明默认值比预期温和）；
- B：8/8 HTTP 200，无 5xx/连接重置，Pod 在 120s 内退出，`exitCode=0`，没有 SIGKILL；
- C：出现失败是预期，记录失败比例和 Pod 退出方式；
- D：单副本 + `minAvailable: 1` 时 `kubectl drain` 被 PDB 阻塞；`kubectl delete pod` 绕过 PDB。

### 9.3 准备：停掉 KEDA，确认主 Deployment

驱逐实验期间不要让 KEDA/HPA 改 replicas；否则删 Pod 后 HPA 可能同时扩缩，变量不干净。

```bash
# 目的：停掉 D3 §8.3 的队列 ScaledObject
kubectl delete scaledobject vllm-scaler --ignore-not-found
kubectl get hpa
# 确认 keda-hpa-vllm-scaler 已删除

# 主 Deployment 固定 1 副本
kubectl scale deploy vllm-qwen3-8b --replicas=1
kubectl rollout status deploy/vllm-qwen3-8b --timeout=15m
```

确认主 Deployment 是 §6.2 的“有排空”配置：

```bash
kubectl get deploy vllm-qwen3-8b -o json | jq -r '
  .spec.template.spec.terminationGracePeriodSeconds,
  .spec.template.spec.containers[0].args,
  .spec.template.spec.containers[0].lifecycle,
  .spec.template.spec.containers[0].resources
'
```

期望看到：

- `terminationGracePeriodSeconds: 120`；
- args 里有 `--shutdown-timeout` 和 `90`；
- `lifecycle.preStop` 是 `sleep 15`；
- resources 是 `cpu: 4` / `memory: 20Gi`。

如果不是，先按 §6.2 的完整 YAML 恢复，再做 §9。

### 9.4 场景 A：无排空基线

这台 VM 有 2 张 4090，主 vLLM 占 1 张；可以再起一个 `vllm-nodrain` 占第二张，两个 Deployment 并存，不动主服务。

> 只有 1 张卡时不要并存：先删主 Deployment，跑完 A 再恢复 §6.2；但这样中间会有一段不可用。下面按 2 卡机写。

#### 9.4.1 创建无排空 Deployment

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-nodrain
  labels:
    app: vllm-nodrain
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: vllm-nodrain
  template:
    metadata:
      labels:
        app: vllm-nodrain
        model: qwen3-8b
    spec:
      runtimeClassName: nvidia
      # 默认 30s；故意不配 preStop 和 --shutdown-timeout
      terminationGracePeriodSeconds: 30
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
        - "--disable-log-requests"
        # 故意不写 --shutdown-timeout
        ports:
        - name: http
          containerPort: 8000
        resources:
          requests:
            cpu: "4"
            memory: "20Gi"
            nvidia.com/gpu: 1
          limits:
            cpu: "4"
            memory: "20Gi"
            nvidia.com/gpu: 1
        startupProbe:
          httpGet:
            path: /health
            port: http
          periodSeconds: 5
          failureThreshold: 120
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
          initialDelaySeconds: 30
          periodSeconds: 10
          failureThreshold: 6
        # 故意不写 preStop
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
  name: vllm-nodrain
spec:
  selector:
    app: vllm-nodrain
  ports:
  - name: http
    port: 8000
    targetPort: http
EOF

kubectl rollout status deploy/vllm-nodrain --timeout=15m
kubectl get pods -l app=vllm-nodrain -o wide
```

启动约 116s。等它 `1/1 Running` 后再发请求。

#### 9.4.2 客户端 Pod

把压测脚本放进 ConfigMap，Pod 用 vLLM 镜像（已缓存，自带 `requests`）：

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: drain-client
data:
  client.py: |
    import concurrent.futures, os, time, requests

    URL = os.environ["URL"]
    N = int(os.getenv("N", "8"))
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "512"))

    def one(i):
        t0 = time.time()
        print(f"START req={i}", flush=True)
        try:
            r = requests.post(URL, json={
                "model": "qwen3-8b",
                "prompt": "Write a long detailed story about a lighthouse.",
                "max_tokens": MAX_TOKENS,
                "temperature": 0,
                "ignore_eos": True,
            }, timeout=300)
            dt = time.time() - t0
            print(f"END req={i} status={r.status_code} latency={dt:.2f}s", flush=True)
            return r.status_code, dt
        except Exception as e:
            dt = time.time() - t0
            print(f"END req={i} error={type(e).__name__} latency={dt:.2f}s", flush=True)
            return type(e).__name__, dt

    print(f"START url={URL} n={N} max_tokens={MAX_TOKENS}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=N) as ex:
        futs = [ex.submit(one, i) for i in range(N)]
        results = [f.result() for f in concurrent.futures.as_completed(futs)]
    ok = sum(1 for r in results if r[0] == 200)
    print(f"SUMMARY ok={ok}/{N} results={results}", flush=True)
---
apiVersion: v1
kind: Pod
metadata:
  name: drain-client
spec:
  restartPolicy: Never
  containers:
  - name: client
    image: vllm/vllm-openai:v0.34.0
    imagePullPolicy: IfNotPresent
    command: ["python3", "-u", "/scripts/client.py"]
    env:
    - name: "URL"
      value: http://vllm-nodrain:8000/v1/completions
    - name: "N"
      value: "8"
    - name: "MAX_TOKENS"
      value: "512"
    volumeMounts:
    - name: scripts
      mountPath: /scripts
  volumes:
  - name: scripts
    configMap:
      name: drain-client
EOF

kubectl get pod drain-client
```

> `N` 在 YAML 1.1 里会被解析成布尔值；env 的 `name` 必须写成带引号的 `"N"`（`MAX_TOKENS`/`URL` 也建议一起加引号），否则 `kubectl apply` 会报 `cannot unmarshal bool into Go struct field EnvVar.spec.containers.env.name`。

`N=8`、`MAX_TOKENS=512`，8 条请求大约 45s；90s 的 shutdown 窗口足够跑完。

#### 9.4.3 发请求 + 删 Pod

终端 A：

```bash
kubectl logs -f drain-client
```

等日志里出现 `START req=0` 到 `START req=7`（8 条都在途）后，终端 B：

```bash
# 先记录目标 Pod 和时间点
POD=$(kubectl get pod -l app=vllm-nodrain -o jsonpath='{.items[0].metadata.name}')
date -u +%Y-%m-%dT%H:%M:%SZ
kubectl get pod "$POD" -o json > /tmp/nodrain-before.json

# 5 秒后删 Pod；不要等它退出
sleep 5
kubectl delete pod -l app=vllm-nodrain --wait=false
date -u +%Y-%m-%dT%H:%M:%SZ
```

观察：

```bash
kubectl get pods -l app=vllm-nodrain -w
kubectl get endpointslice -l kubernetes.io/service-name=vllm-nodrain -w
kubectl get events --sort-by=.lastTimestamp | tail -20
```

客户端结束后：

```bash
kubectl logs drain-client
kubectl get pod drain-client -o jsonpath='{.status.phase}{"\n"}'
```

#### 9.4.4 记录 A

- `SUMMARY ok=x/8`；
- 失败类型（`ConnectionError` / `ReadTimeout` / 5xx）；
- 最大 latency；
- Pod 从 `Terminating` 到消失的秒数；
- 容器 `exitCode`：0 / 143（SIGTERM）/ 137（SIGKILL）。

无排空基线预期：没有 preStop，SIGTERM 到达时 endpoint 可能还没摘干净；vLLM 没有 `--shutdown-timeout`，在途请求容易被 abort。失败是预期结果，不是你脚本写错了。

#### 9.4.5 清理 A

```bash
kubectl delete deploy vllm-nodrain --ignore-not-found
kubectl delete svc vllm-nodrain --ignore-not-found
kubectl delete pod drain-client --ignore-not-found
```

等 GPU 释放：

```bash
kubectl get pods -l app=vllm-nodrain
# 没有 Pod 再继续
```

### 9.5 场景 B：有排空

主 Deployment 已经是 §6.2 的完整配置：`preStop 15s` + `--shutdown-timeout 90` + grace 120s。确认后把客户端 URL 改回主 Service：

```bash
# 改客户端 URL（删掉重建）
kubectl delete pod drain-client --ignore-not-found
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: drain-client
spec:
  restartPolicy: Never
  containers:
  - name: client
    image: vllm/vllm-openai:v0.34.0
    imagePullPolicy: IfNotPresent
    command: ["python3", "-u", "/scripts/client.py"]
    env:
    - name: "URL"
      value: http://vllm-qwen3-8b:8000/v1/completions
    - name: "N"
      value: "8"
    - name: "MAX_TOKENS"
      value: "512"
    volumeMounts:
    - name: scripts
      mountPath: /scripts
  volumes:
  - name: scripts
    configMap:
      name: drain-client
EOF
```

先抓旧 Pod 日志（Pod 删除后日志就没了）：

```bash
POD=$(kubectl get pod -l app=vllm -o jsonpath='{.items[0].metadata.name}')
kubectl logs -f "$POD" -c vllm > /tmp/vllm-drain.log 2>&1 &
```

终端 A：

```bash
kubectl logs -f drain-client
```

等 8 条 `START` 都出现后，终端 B：

```bash
POD=$(kubectl get pod -l app=vllm -o jsonpath='{.items[0].metadata.name}')
date -u +%Y-%m-%dT%H:%M:%SZ
kubectl get pod "$POD" -o json > /tmp/drain-before.json

sleep 5
kubectl delete pod -l app=vllm --wait=false
date -u +%Y-%m-%dT%H:%M:%SZ
```

观察：

```bash
kubectl get pods -l app=vllm -w
kubectl get endpointslice -l kubernetes.io/service-name=vllm-qwen3-8b -w
kubectl get events --sort-by=.lastTimestamp | tail -30
```

期望顺序：

1. 旧 Pod `Terminating`，先从 EndpointSlice 摘除；
2. `preStop` sleep 15s，新请求不再进来；
3. SIGTERM 后 vLLM 继续跑在途请求，最多 90s；
4. 8 条请求完成，Pod 在 120s 内退出；
5. `exitCode=0`，没有 SIGKILL；Deployment 起新 Pod，新 Pod 约 116s 后 Ready。

客户端结果：

```bash
kubectl logs drain-client
# SUMMARY ok=8/8 results=[(200, ...), ...]
```

检查旧 Pod 退出方式（Pod 对象还在时）：

```bash
kubectl get pod "$POD" -o jsonpath='{.status.containerStatuses[0].state.terminated.exitCode}{"\n"}'
kubectl get pod "$POD" -o jsonpath='{.status.containerStatuses[0].state.terminated.reason}{"\n"}'
```

- `0`：正常退出；
- `143`：被 SIGTERM 结束（可能正常，但说明 vLLM 没等到自己 graceful exit）；
- `137`：SIGKILL，说明 grace 不够或进程卡住。

vLLM 日志里找 shutdown 相关行：

```bash
grep -iE "shutdown|drain|abort|SIGTERM|waiting" /tmp/vllm-drain.log | tail -30
```

### 9.6 场景 C：排空窗口不够

把客户端改成 `N=32`、`MAX_TOKENS=1024`，重复 B：

```bash
kubectl delete pod drain-client --ignore-not-found
# 重新 apply 时把 env N=32、MAX_TOKENS=1024
```

预期：

- 32 条请求的总时长超过 90s；
- vLLM 在 `--shutdown-timeout 90` 到期后 abort 剩余请求；
- 客户端出现失败/超时；
- Pod 可能在 90s 左右退出，也可能拖到 120s 被 SIGKILL；记录实际值。

这个场景不是“配置错了”，而是用来证明：

```text
shutdown-timeout 必须大于最长在途请求，否则排空窗口不够
```

调参方向：增大 `--shutdown-timeout`、增大 grace、限制单请求最大输出（`max_tokens`）、或把长请求拆小。

### 9.7 场景 D：PDB 的取舍

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

结论先说：

- **单副本 + `minAvailable: 1`**：`kubectl drain` 会一直阻塞，因为没有任何自愿驱逐能保持 1 个可用副本；
- **至少 2 副本 + `minAvailable: 1`**：drain 可以逐个驱逐，但要有第二张 GPU/第二个节点承接；
- **PDB 只管自愿驱逐**：`kubectl delete pod`、节点宕机、OOM 都不受它保护；
- **PDB 不保证零 downtime**：它只保证“驱逐时至少还有 N 个 Ready”，新 Pod 冷启动期间新请求仍可能失败。

单节点 k3s 不要真跑 `kubectl drain` 来验证 PDB：它会把 CoreDNS、metrics-server 等系统 Pod 也纳入驱逐，可能把集群弄坏。PDB 放在 2 节点集群或多副本环境验证；单节点只做概念题。

如果要在 2 卡机上验证多副本 PDB，需要先把主 Deployment 扩到 2（4 CPU/20Gi × 2），再观察 `kubectl get pdb` 和 `kubectl drain`；不要和 §9 的单副本排空实验混在一起。

### 9.8 记录模板

| 场景 | preStop | shutdown/grace | 在途请求 | 200 | 失败/5xx | 最大延迟 | Terminating 时长 | exitCode | SIGKILL |
|---|---|---|---|---|---|---|---|---|---|
| A 无排空 | 0 | 默认/30s | 8×512 | | | | | | |
| B 有排空 | 15s | 90s/120s | 8×512 | | | | | | |
| C 窗口不够 | 15s | 90s/120s | 32×1024 | | | | | | |

补充记录：

- 删除动作时间戳（`date -u`）；
- 旧 Pod `deletionTimestamp`；
- EndpointSlice 摘除时间（如果抓到了）；
- 新 Pod `created` / `Ready` 时间（用来解释删除后的新请求失败）；
- 客户端 URL 是 Service 还是 port-forward（port-forward 断开本身会导致失败，不能算 vLLM 排空失败）。

### 9.9 结论与面试问法

**Q：为什么需要 preStop？**
A：SIGTERM 只告诉进程退出，不保证 Endpoint/kube-proxy/网关已经把这个 Pod 摘掉。preStop sleep 给控制面收敛时间，避免新请求继续打到正在退出的 Pod。

**Q：grace、preStop、shutdown-timeout 的关系？**
A：grace 是总预算，从 deletion 开始算；preStop 在 SIGTERM 前；shutdown-timeout 是 vLLM 收到 SIGTERM 后等在途请求的上限。必须满足 `grace > preStop + shutdown-timeout + 余量`，否则 SIGKILL（exit 137）。

**Q：`kubectl delete pod` 能验证 PDB 吗？**
A：不能。PDB 只约束 Eviction API（drain/维护）；直接 delete 绕过 PDB。

**Q：单副本为什么不能配 `minAvailable: 1`？**
A：任何自愿驱逐都会让可用副本降到 0，PDB 会拒绝，drain 永远阻塞。要么 2 副本 + minAvailable 1，要么单副本接受维护窗口。

**Q：扩容/替换期间新请求为什么失败？**
A：旧 Pod 摘除后、新 Pod Ready 前，Service 没有可用 endpoint；vLLM 冷启动约 116s。这个窗口要靠多副本、PDB、surge/预热池或网关重试来覆盖。

### 9.10 清理

```bash
kubectl delete pod drain-client --ignore-not-found
kubectl delete deploy vllm-nodrain --ignore-not-found
kubectl delete svc vllm-nodrain --ignore-not-found

# 恢复主 Deployment 1 副本
kubectl scale deploy vllm-qwen3-8b --replicas=1
kubectl rollout status deploy/vllm-qwen3-8b --timeout=15m

# 重新 apply D3 §8.3 的 ScaledObject/vllm-scaler（min=1, max=2）
```

如果创建过 PDB，也要删除：

```bash
kubectl delete pdb vllm-pdb --ignore-not-found
```

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
| 单卡 RTX VM（3090/4090） | 约 `$0.41–0.48/h`（含 130GB 盘） | 3h 约 `$1.2–1.5` |
| 2 卡 RTX VM | 约 `$0.85–1.0/h`（GPU ×2 + 存储） | 3h 约 `$2.6–3.0`；4h 约 `$3.4–4.0` |
| 公网/存储 | ingress 通常不计费；Stop 后存储照计 | 见 Vast 账单 |

D2 后账户余额约 `$18.78`；D3 单卡 VM 3h 约 `$1.3`，2 卡 4h 约 `$3.7`，预算足够。**先 scp 结果再 Destroy**。VM 创建比容器慢（几分钟），`creating` 不是失败；用 `vastai logs <ID>` 看进度。

---

## 11. 常见坑

| 症状 | 原因 | 处置 |
|---|---|---|
| k3s 起不来 / 卡在 `Starting` | 当前是 Vast 普通容器，没有 systemd/cgroup/privileged | 按 §5.0 用 `vms_enabled=true` + VM 模板重建；不要在普通容器里硬装 |
| 建 VM 报 `no_such_ask` / 创建失败 | offer 被租走，或用了非 VM 的 offer ID | 重新搜；必须用 `vms_enabled=true` 查询返回的 ID |
| `nvidia.com/gpu` allocatable 是 0 | device plugin 没 Ready，或 runtime 没配 | 看 `kubectl -n kube-system logs ds/nvidia-device-plugin-daemonset`；`grep nvidia .../config.toml` |
| device plugin 日志报 `No devices found` | static manifest 没写 `runtimeClassName: nvidia`，Pod 用 runc 看不到 GPU | patch DaemonSet 加 `runtimeClassName: nvidia`（§5.4） |
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
| 新 Pod 报 `failed to initialize NVML: Driver/library version mismatch` | `apt-daily-upgrade.timer` 补跑 `unattended-upgrade`，升级了 NVIDIA 用户态驱动，内核模块还是旧版 | `nvidia-smi` 也会报同样错；先等 apt/dpkg 结束，`disable --now` + `mask` apt timers，重启 VM 加载新模块，确认 `nvidia-smi` 正常再继续 |

---

## 12. 面试问答（D3 版）

**Q1：device plugin 为什么不能申请“半张卡”？MIG / time-slicing / MPS / DRA 各解决什么？**

device plugin 把 GPU 暴露成整数扩展资源（`nvidia.com/gpu`），调度器只认整数。MIG 把 A100/H100 切成固定切片（硬隔离，但 L4 不支持）；time-slicing 让多个 Pod 共享同一张卡（软隔离，互相抢算力，LLM 的 TPOT 会抖）；MPS 做进程级并发（共享显存，隔离弱）；DRA 是 K8s 新的设备分配 API，支持更细的设备属性和配额。对 LLM 推理，优先整卡；要切卡先想清楚 SLO。

**Q2：8B 模型 FP16 约 16GB 权重（AWQ 约 5.7GB），怎么让新 Pod 20 秒内起来？四种方案和代价。**

① 节点本地缓存（hostPath/local PV）：最快，但只对单节点有效；② Model Streamer / 远程权重流式加载：省下载，但依赖高速网络；③ 预热池（minReplica ≥ 1）：没有冷启动，但一直占卡；④ 更小的量化/模型（AWQ/FP8/更小参数）：加载和显存都降，但质量/能力要重测。D1 的 69s 是 L4 上启动到 ready 的参照；D3 在 RTX VM 上要重新测，20s 需要模型/量化/存储一起优化，不是单靠 K8s。

**Q3：为什么 GPU inference 不该用 CPU 型 HPA？该用什么信号？**

GPU 打满时 CPU 可能很低，CPU 利用率和排队长度不相关；CPU HPA 会在最需要扩容时不扩。用 `vllm:num_requests_waiting`（队列深度）、`vllm:gpu_cache_usage_perc`（KV 压力）、TTFT P99 或 goodput 作为信号；KEDA 的 Prometheus scaler 直接查这些指标。

**Q4：chat 场景能不能 scale-to-zero？怎么折中？**

默认不能：冷启动几十秒级，请求在 Pod 起来前就超时；KEDA 缩到 0 也不排队。折中：`minReplicaCount: 1` + 预热池；按时间段/预测扩容；异步任务用队列 + scale-to-zero；或者用 KEDA HTTP add-on/网关先接住请求，但 TTFT 仍然包含冷启动。

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

- **D1**：69s 启动到 ready、96,256 KV、c=64 132.8 tok/s 是 D3 的**口径参照**，不是 D3 的目标值。D1 是 L4 容器内进程启动，D3 是 RTX VM 上从 scale 到 Ready；绝对值不能直接比，D3 只比较同机的 cold vs warm 和各阶段占比。
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
# 目录名以模型版本为准（如 Qwen3-8B-AWQ-v1/-v2）
sudo rm -rf /var/lib/models/Qwen3-8B-AWQ /var/lib/models/Qwen3-8B-AWQ-v1 /var/lib/models/Qwen3-8B-AWQ-v2

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
11. Vast.ai Virtual Machines（VM 与容器差异、`vms_enabled=true`、VM 模板）：https://docs.vast.ai/guides/instances/virtual-machines
12. Vast.ai create instance API（`vm: true`、`runtype: ssh_direct`）：https://docs.vast.ai/api-reference/instances/create-instance
13. k3s release channel（2026-11-23 的 stable 为 `v1.37.2+k3s1`）：https://update.k3s.io/v1-release/channels/stable
