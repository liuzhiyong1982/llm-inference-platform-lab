# D5 学习文档：Kueue 多租户 GPU 配额 + Kyverno CEL 准入（单卡 Vast VM）

> 状态：**planned（2026-11-26 按实际单卡 VM 重写；本地 kind smoke test 已验证机制）**。本文按 `ai-cloud-native-week-plan.md` 的 D5 行准备：**3h、Vast 单卡 VM、Kueue `ClusterQueue` 两团队配额 + Kyverno 强制 GPU workload 带 `priorityClass` / queue label；跑一次“抢卡”演示，留下两条被拒 manifest 日志**。**尚未在 Vast 上跑正式结果**；文中“实测”表是模板，执行后填。本地 kind（单节点、假 `nvidia.com/gpu=2`）已把 Kueue 配额/排队/抢占和 Kyverno CEL 策略跑通，但那只验证机制，不代表 Vast 单卡容量，见 §9.8。
>
> 计划位置：`ai-cloud-native-week-plan.md` 的 **D5（3h）** 与 **B 线 D3–D7 学习表**；B 线讲法见该文件“D3 / D5 的 B 线讲法”。
>
> 性质：**控制面 lab，不是推理性能 lab**。D1/D2 回答“单机多快”，D3 回答“放进 K8s 后启动/扩容/驱逐要多少秒”，D4/D4.6 回答“多副本路由和 KV 分层能好多少”，D5 回答“**多个团队共享 GPU 时，谁能拿卡、拿不到怎么排队、怎么证明没被滥用**”。
>
> 硬约束：**不在共享 UAT 集群 `uat-mobility-aks-01` 上做实验**。用 Vast.ai 的 on-demand VM；所有 manifest、日志、结果进 git。
>
> 版本基线：**Kueue `v0.20.7`**（只服务 `kueue.x-k8s.io/v1beta2`）、**Kyverno `1.20.0`**（只执行 CEL 类型；新策略写 `policies.kyverno.io/v1`）、k3s `v1.37.2+k3s1`、Kubernetes `v1.37`。

---

## 0. 先看结论（执行前先记住）

1. **Kueue 管“批处理谁能拿卡、拿不到怎么排队”；HPA/KEDA 管“在线服务副本数”。** 两者不是替代关系，Kueue 也不会加 GPU 节点。Deployment 也能接 Kueue，但按 Pod 粒度，见 §3.4.1。
2. **Kueue 默认只接管带 `kueue.x-k8s.io/queue-name` 的 Job。** 不带 label 的 GPU Job 会直接跑，绕过配额；所以需要 Kyverno 在 API 入口强制 label、priorityClass。
3. **配额是 request-based 的上限，不是容量保证。** `nominalQuota` 超过实际 `nvidia.com/gpu` 时，Kueue 会放行，Pod 会在 kube-scheduler 层 `Pending`。
4. **Kyverno 1.20 不再执行旧 `ClusterPolicy`。** 新策略统一用 `policies.kyverno.io/v1` 的 `ValidatingPolicy` / `MutatingPolicy`，逻辑用 CEL 写；旧 CRD 在 1.20 还在，但 create/update 被拒，1.21 才删 CRD。
5. **两条“拒绝”要分清口径：**
   - Kyverno：API 直接返回 `Forbidden`，对象没创建；
   - Kueue：对象创建成功，但 `Workload` 的 `QuotaReserved=False`，Job 处于 `Suspended`，这是**排队**不是 API 拒绝。
6. **预期演示结果：** team A 提交 2 个 GPU Job，只跑 1 个，另一个 `QuotaReserved=False`；team B 的 Workload 被 Kueue 放行（`Admitted=True`），但 Pod 因物理卡在 team A 手里而 `Pending: Insufficient nvidia.com/gpu`；team A 高优先级 Job 可抢占同队列低优先级 Job。**单卡不是缩水版**：它把“配额账本”和“调度容量”的边界讲得最清楚。

---

## 1. 学习目标与验收

### 1.1 A 线：三个证据

| # | 证据 | 通过标准 |
|---|---|---|
| 1 | Kyverno 拒绝日志 ×2 | 缺 queue label、缺 priorityClass 各一条 `Forbidden`，保存 stderr |
| 2 | Kueue 配额表 | 集群 1 GPU；team A 2 个 Job → 1 `Admitted` / Running + 1 `QuotaReserved=False`；team B 1 个 → Workload `Admitted` + Pod `Pending: Insufficient nvidia.com/gpu`。B 的 `Admitted` 和 Pod `Pending` 必须同时记录，见 §9.3 |
| 3 | 抢占证据 | team A 高优先级 Job 使低优先级 Workload 出现 `Evicted=True, reason=Preempted`，并且 `kueue_preempted_workloads_total` 增加 |

### 1.2 B 线：三个交付物

- 一段 **10 分钟讲解**：配额 + 准入 + 审计，能回答“怎么防止一个团队抢光 GPU”。
- 一张 **Kueue vs HPA/KEDA 分工表**，能说清“为什么 Kueue 不负责扩副本”。
- 一条 **chargeback 公式**：`GPU-hours × $/GPU-h`，按 `team` / `cost-center` 标签聚合。

**CEL 学习目标（30–40 分钟，详见 §3.6）：**

- 能解释 CEL 是什么，以及 Kyverno 1.20 为什么只用 CEL 类型；
- 能读懂 `variables` / `validations` / `JSONPatch` 三类表达式；
- 能用 `kyverno apply --explain` 定位“哪条表达式返回了 false”；
- 能改一条 queue label 或 priorityClass 规则，并自己写一条新校验。

### 1.3 3 小时时间盒

| 时间 | 动作 | 必须落地 |
|---|---|---|
| 0:00–0:30 | 租 VM、装 toolkit/k3s/device plugin，确认 1 张卡 | `nvidia.com/gpu=1` |
| 0:30–1:00 | 装 Kueue，建 `ResourceFlavor` / `ClusterQueue` / `LocalQueue` | `kubectl get clusterqueue` 正常 |
| 1:00–1:20 | 跑“无 queue label 绕过配额”实验 | 1 个 Running Pod + 0 个 Workload |
| 1:20–1:50 | 装 Kyverno，写/应用 CEL 策略，跑两条拒绝 | 2 条 `Forbidden` 日志 |
| 1:50–2:30 | 抢卡、排队、抢占、释放后重排 | 1 张配额表 + 1 条 `Preempted` |
| 2:30–2:50 | 抓 metrics/events，清理 | `results/d5/` 快照 |
| 2:50–3:00 | `scp` 结果、Destroy VM | 成本记录 |

> 时间紧就砍：cohort 借用、wrong-queue 第三条拒绝、PolicyReport。**两条拒绝 + 配额 + 抢占**不能砍。

### 1.4 不做什么

- 不下载模型、不起 vLLM；D5 的 GPU 只是被 `pause` 容器占位。
- 不做多节点、不做真实 GPU 型号混部、不做生产级 HA。
- 不把 `nominalQuota` 当成“节点容量”。
- 不在 UAT 集群上试任何策略。

### 1.5 本 lab 回答的问题（索引）

| 问题 | 答案位置 |
|---|---|
| D5 必须 2 张卡吗？ | §2.1（单卡主路径；quota vs capacity） |
| 为什么 D5 用 Job，不用 D1–D4 的 Deployment？ | §3.4.1 |
| `nominalQuota` 是什么？ | §3.3.1 |
| `cohort` 是什么？ | §3.3.2 |
| `priority` 是什么？ | §3.3.3 |
| Kueue 和 HPA/KEDA 怎么分工？ | §3.4 |
| DRA 是替换 device plugin 吗？ | §3.1.1 |

> 这里只负责指路，不重复正文；每个问题在对应小节有完整答案。

---

## 2. 环境、版本、预算

### 2.1 机器

| 项 | 值 |
|---|---|
| 实例 | Vast.ai **单卡 VM（1×GPU）**，on-demand，`vms_enabled=true`；磁盘按实际 offer，≥40GB 足够 |
| GPU | **执行时填**：`nvidia-smi` 的型号 / 显存；不绑定型号 |
| host | **执行时填**：vCPU / RAM；D4 的 40 vCPU / 98GB 只是参考，不是 D5 要求 |
| 单价 | **执行时填**：Vast 实时价（不要沿用 D4 的旧单价） |
| 3.5h 成本（3h 实验 + 0.5h buffer） | **执行时填**：单价 × 3.5h；实际账单写 `results/d5/cost.txt` |
| 系统 | Ubuntu 22.04 VM；driver / k3s 版本执行时记录（基线 k3s `v1.37.2+k3s1`） |

**D5 对显存没有要求，1 张卡即可。** GPU 只被 `pause` 容器占位，不下载模型、不起 vLLM；D6 才需要 ≥12GB（1×RTX 4090 24GB 更宽裕）。

**单卡的代价：不能演示两个团队同时 `Running`。** 换来的是把 §0 第 3 条讲透：Kueue 的 `nominalQuota` 是配额账本，kube-scheduler 的 `nvidia.com/gpu` 才是物理容量。按下面的口径记录：

| 验收项 | 单卡可做 | 口径变化 |
|---|---|---|
| Kyverno 两条拒绝 | ✅ | 与 GPU 无关 |
| team A 2 Job → 1 `Admitted` + 1 `QuotaReserved=False` | ✅ | 不变 |
| 同队列高优先级抢占 | ✅ | 让低优先级先占住唯一一张卡 |
| team B 拿到“另一张卡”并 `Running` | ❌ | 只能到 `Admitted` + Pod `Pending` |

单卡的 team B 结果不是失败，而是 §0 第 3 条的最好证据：**`nominalQuota` 是请求上限，不等于节点容量**。写结果时不要写“B 仍能拿到卡”，改成“B 被 Kueue 放行但 scheduler `Pending`”，并保存 `kubectl describe pod` 里的 `Insufficient nvidia.com/gpu`。

> **flavor 名：** `ResourceFlavor` 仍叫 `gpu-3060`，只是沿用脚本里的逻辑名；实际卡型以 `nvidia-smi` 为准，不影响配额语义。若要改名，必须同步 `scripts/d5/20-kueue.yaml`、`scripts/d5/README.md` 和本文所有期望输出/cleanup 命令。

### 2.2 版本矩阵

| 组件 | 版本 | 关键 API / 说明 |
|---|---|---|
| Kubernetes | `v1.37`（k3s `v1.37.2+k3s1`） | Kueue 0.20 与 Kyverno 1.20 官方支持 1.34+ |
| Kueue | `v0.20.7` | **只服务 `kueue.x-k8s.io/v1beta2`**；v0.20.0 已移除 v1beta1 |
| Kyverno | `1.20.0`（Helm chart `3.10.0`） | **只执行 CEL 类型，新策略写 `policies.kyverno.io/v1`**；旧 `kyverno.io/v1 ClusterPolicy` 停止执行 |
| NVIDIA device plugin | `v0.18.0` | D3 已验证；static manifest 需补 `runtimeClassName: nvidia` |
| Helm | 3.x | 装 Kyverno 用；没有就装 |

### 2.3 三个版本坑

**坑 1：Kueue 旧 manifest 的 `v1beta1` 直接失效。**

Kueue v0.20.0 起不再服务 `kueue.x-k8s.io/v1beta1`。网上大量 2024–2025 的 `ClusterQueue` 示例还是 `v1beta1`，在 0.20 上 apply 会报 no matches。本文全部用：

```yaml
apiVersion: kueue.x-k8s.io/v1beta2
```

**坑 2：Kyverno 1.20 的“删除 ClusterPolicy”是停止执行，不是 1.20 就没 CRD。**

- 1.20：CRD 还在，旧对象可读/可导出/可删除；**create/update 被 webhook 拒绝，controller 不执行**。
- 1.21（计划）：删 CRD，旧对象会随 CRD 一起消失。
- 所以升级前必须迁移；Helm 默认会阻止带旧策略的升级。

**坑 3：Kueue 给 Pod 加的 label 是 `local-queue-name`，不是 `queue-name`。**

`AssignQueueLabelsForPods`（beta，默认开）给 Kueue 创建的 Pod 加：

```text
kueue.x-k8s.io/local-queue-name
kueue.x-k8s.io/cluster-queue-name
```

Job 上的 `kueue.x-k8s.io/queue-name` 不会自动出现在 Pod 上。Pod 策略要同时接受 `queue-name`（裸 Pod）和 `local-queue-name`（Kueue 托管 Pod），否则会把 Kueue 自己创建的 Pod 拒掉。

### 2.4 预算

| 项 | 金额 |
|---|---|
| 单卡 VM 实时单价 | **执行时填**（`$____/h`） |
| 3h 实验 + 0.5h buffer | **执行时填**（`$____`） |
| 合计（约 3.5h） | **执行时填** |

> 不在共享 UAT 集群上做，避免污染环境、触发 Coder→Reviewer SOP 和公司成本。
>
> 估算口径：**单卡实时价 × 3.5h**；实际账单写 `results/d5/cost.txt`。不要沿用 D4 的旧单价或旧余额，也不要把估算当成账单。

### 2.5 本地 kind 预演（可选，零成本）

没有 VM 时可以用 kind 先验证控制面逻辑：

```bash
kind create cluster --name d5 --image kindest/node:v1.34.0
kubectl patch node d5-control-plane --subresource=status --type=merge \
  -p '{"status":{"capacity":{"nvidia.com/gpu":"2"},"allocatable":{"nvidia.com/gpu":"2"}}}'
```

然后按本文装 Kueue/Kyverno。**能验证：** 配额、排队、抢占、CEL 策略、admission 顺序。
**不能验证：** 真实 GPU 调度、device plugin、Vast 成本、跨节点行为。正式结果仍要在 Vast 上跑。

> kind 节点默认只有 2 CPU。Kueue + Kyverno + 占位 Job 可能把 CPU 吃满，导致 Kyverno admission Pod `Pending`，甚至被高优先级 Job 抢占。预演时先停掉占位 Job、给控制面加 `priorityClassName: system-cluster-critical`，或接受只验证部分步骤；Vast 单卡 VM 通常不会这么紧，执行时按 `nproc` 记录实际 vCPU。
>
> kind 里 patch 出来的 `2` 是**假容量**，只为一次预演里同时观察配额/排队/抢占；Vast 正式实验只有 1 张卡，kind 结果不能当单卡容量证据。

---

## 3. 先修概念：面试会追问的七件事

### 3.1 一次 GPU Job 在 Kubernetes 里经过什么

```text
kubectl apply Job
  │
  ├─ 1. Kyverno ValidatingPolicy（validating webhook）
  │     检查：queue label / priorityClass / 其他平台策略
  │     失败 → API 返回 Forbidden，对象不创建
  │
  ├─ 2. Kueue mutating webhook + controller
  │     webhook 把 Job 置为 suspend；controller 创建 Workload
  │     Job 保持 Suspended，先不创建 Pod
  │
  ├─ 3. Kueue scheduler
  │     按 ClusterQueue 的 nominalQuota / cohort / priority 决定是否 Admit
  │     不满足 → Workload QuotaReserved=False，Job 继续 Suspended
  │
  ├─ 4. Kueue 放行
  │     Job suspend=false → Job controller 创建 Pod
  │
  ├─ 5. kube-scheduler
  │     按 nvidia.com/gpu 资源把 Pod 绑到节点
  │
  └─ 6. NVIDIA device plugin / kubelet
        把 GPU 分配给容器
```

**每一层都能单独失败：**

| 层 | 失败表现 | 责任方 |
|---|---|---|
| Kyverno | `Forbidden`，对象不存在 | 平台策略 |
| Kueue webhook | `InternalError` / webhook timeout | 平台控制面 |
| Kueue scheduler | `Workload` pending，Job `Suspended` | 配额/优先级 |
| kube-scheduler | Pod `Pending`，`Insufficient nvidia.com/gpu` | 真实容量 |
| device plugin | Pod Running 但看不到 GPU | 节点运行时 |

这张表就是 D5 的排障顺序：**先看对象有没有创建，再看 Workload 有没有 quota，再看 Pod 有没有调度。**

### 3.1.1 DRA 与 D5 的边界（为什么本 lab 不用 DRA）

> **结论：DRA 替换的是 device plugin 的分配模型，不是驱动本身。DRA 仍然需要 DRA driver。**

DRA（Dynamic Resource Allocation）是 Kubernetes 1.34 GA 的设备分配 API（`resource.k8s.io/v1`），解决的是“**Pod 要什么样的设备**”，不是“谁能拿到配额”。

**旧模型：** Pod 写 `nvidia.com/gpu: 1`，device plugin 把卡暴露成 extended resource；kube-scheduler 只看到整数，调度后由 kubelet / device plugin 选卡。

**DRA：** 用 `DeviceClass` / `ResourceSlice` / `ResourceClaim` 描述和申请设备；kube-scheduler 在**调度前**选中具体设备。它需要 NVIDIA DRA driver（如 `k8s-dra-driver-gpu`），不是“不用驱动”。

**不替换：** 厂商驱动、GPU Operator / 容器运行时、Kueue 的 quota / queue / preemption 都还在；device plugin 仍受支持，简单整卡场景可以继续用。

| 对象 | 作用 |
|---|---|
| `DeviceClass` | 设备类别，如 `gpu.nvidia.com`（以驱动发布为准） |
| `ResourceSlice` | 驱动发布“本节点有哪些设备、什么属性”：显存、型号、MIG profile、拓扑 |
| `ResourceClaim` | Pod 的设备申请：要几张、什么属性 |
| `ResourceClaimTemplate` | 每个 Pod 自动生成 claim，适合多副本 |

D5 用的是旧模型：NVIDIA device plugin 把 GPU 暴露成 extended resource `nvidia.com/gpu`，Pod 只写一个整数。两者差别：

| 维度 | D5：device plugin | DRA |
|---|---|---|
| 资源声明 | `nvidia.com/gpu: 1` | `ResourceClaimTemplate` + `DeviceClass` |
| 驱动 / 组件 | NVIDIA driver + device plugin | NVIDIA driver + NVIDIA DRA driver（如 `k8s-dra-driver-gpu`） |
| 选卡依据 | 数量 + `nodeSelector` / affinity | 设备属性：显存、型号、MIG、拓扑 |
| MIG / 共享 | 靠驱动暴露不同 resource name | 原生 partitionable devices、设备共享 |
| 配额 | Kueue 按 `nvidia.com/gpu` 计数 | Kueue DRA 集成按设备数或 counter 计 |
| Pod 调度 | kube-scheduler 只按数量调度；kubelet / device plugin 选卡 | kube-scheduler 在调度前选中具体设备（DRA 插件） |

**为什么 D5 不用 DRA：**

1. **时间盒只有 3h。** 装 NVIDIA DRA driver、确认 `ResourceSlice`、写 `ResourceClaimTemplate`，会挤掉配额、抢占和两条拒绝日志。
2. **本 lab 按消费级单卡准备（实际型号以 `nvidia-smi` 为准），没有 MIG 素材。** DRA 最有价值的“按显存/分区选卡”没有用武之地；D5 只申请整卡，设备属性不参与配额决策。
3. **问题正交，lab 目标是配额/准入，不是设备选择。** D5 回答“谁能拿卡、拿不到怎么排队”；DRA 回答“拿哪张卡”。DRA 不提供 quota、queue、preemption。
4. **版本不是障碍。** k3s 1.37 + Kueue 0.20.7 已支持 DRA（Kueue 0.18 起集成 beta，0.19 起相关 feature gate 默认开启），但“能跑”不等于“3h 内值得跑”。

**最容易混的两个词：**

- Kueue `ResourceFlavor`：**配额维度**，按节点 label/taint 划分“这批配额对应哪些节点”，不是设备；
- DRA `DeviceClass`：**设备类别**，描述“有哪些卡、什么属性”。

**如果要把 D5 扩成 DRA 版：** 需要 K8s ≥1.34、NVIDIA DRA driver（如 `k8s-dra-driver-gpu`）、`ResourceClaimTemplate`，并把 `20-kueue.yaml` 里按 `nvidia.com/gpu` 计的配额换成 DRA 设备计数或 counter；至少多 1.5–2h。建议单独做 Q3 的 GPU Operator/MIG lab，不要塞进 D5。

**面试一句话：** “DRA 是 device plugin 的替代模型，不是替代驱动；它把整数计数换成 ResourceClaim + ResourceSlice，让 scheduler 调度前选设备；配额/排队/抢占仍是 Kueue 的事。”

### 3.2 Kueue 的工作原理与对象模型

#### 3.2.1 控制循环：Kueue 是“准入控制器”，不是调度器

Kueue 不创建 Pod、不选节点、不扩节点。它只做一件事：**决定一个 Workload 现在能不能开始，并替它把配额记在账上。**

```text
Job 创建（带 queue-name）
  │
  ├─ 1. Kueue 的 Job controller 看到 Job
  │     按 Pod 模板生成一个 Workload：
  │       podSets[]（几个 Pod、每个 Pod 要多少 GPU/CPU/内存）
  │       priority（从 Pod priority 或 WorkloadPriorityClass 来）
  │       queueName（来自 Job 的 label）
  │
  ├─ 2. Workload 进入 LocalQueue → ClusterQueue 的 pending 队列
  │     排序：priority 高的先；同 priority 按 creationTimestamp
  │
  ├─ 3. Kueue 逐个尝试 admission
  │     a. namespace 是否被 namespaceSelector 允许？
  │     b. 某个 flavor 的 nominalQuota 够不够？
  │        不够 → cohort 里有没有闲置配额？borrowingLimit 允不允许？
  │     c. admissionChecks 是否通过？（本 lab 不配）
  │     都通过 → QuotaReserved=True，选好 flavor
  │
  ├─ 4. Admitted=True
  │     Kueue 把 Job 的 spec.suspend 改成 false
  │
  ├─ 5. Kubernetes Job controller 创建 Pod
  │     kube-scheduler 按 nvidia.com/gpu 选节点
  │     device plugin 分配 GPU
  │
  └─ 6. Job 完成 / 被删除 / 被抢占
        Workload 释放配额，Kueue 重新评估 pending 队列
```

四个必须记住的不变量：

1. **Kueue 只数 request，不看 util。** 一个 Job request 1 张卡、实际用 5%，仍然占 1 张卡的配额；只写 `limits` 时按 `limits` 算（Kubernetes 默认）。
2. **Kueue admission ≠ Pod 调度成功。** 配额是逻辑账本；`nominalQuota` 可以大于真实 GPU 数，此时 Workload `Admitted`、Pod 却 `Pending`。这是本文 §0 第 3 条，也是单卡演示的核心。
3. **一个 Job = 一个 Workload，原子准入。** 要么整个 Job 的所有 Pod 一起被放行，要么都不放；不会出现“半个 Job 在跑”。
4. **配额跟着 Workload 生命周期走。** Workload 没结束，配额就一直占着；Job 完成或删除才释放（Deployment 是每个 Pod 一个 Workload，按 Pod 释放）。

> 所以 Kueue 的本质是一个 **quota ledger（配额账本）**：admission 时记账，完成时销账，抢占时把账转给更高优先级的 Workload。它不测量、不优化、不扩节点。

#### 3.2.2 对象模型

| 对象 | 作用域 | 一句话 |
|---|---|---|
| `ResourceFlavor` | Cluster | 一类硬件（如 `gpu-3060`），可绑定 node label/taint |
| `ClusterQueue` | Cluster | 一个配额池，定义 `nominalQuota`、borrowing、preemption |
| `LocalQueue` | Namespace | 团队入口，指向某个 `ClusterQueue` |
| `Workload` | Namespace | Kueue 的调度单元，由 Job 自动生成；有 `QuotaReserved` / `Admitted` / `Evicted` 条件 |
| `Cohort` | Cluster（字符串） | 一组可互相借配额的 `ClusterQueue` |
| `PriorityClass` | Cluster | Kubernetes Pod 优先级；Kueue 从 Pod template 继承为 Workload priority |
| `WorkloadPriorityClass` | Cluster | 只影响 Kueue 排队/抢占、不影响 Pod priority 的优先级 |

关系：

```text
Job (label queue-name=team-a)
  → LocalQueue team-a (namespace team-a)
    → ClusterQueue team-a-cq (nominalQuota: 1 GPU)
      → ResourceFlavor gpu-3060
        → node with nvidia.com/gpu=1
```

> `LocalQueue` 是 namespace 级的“取号窗口”，`ClusterQueue` 是真正的“配额池”。用户只提交到 LocalQueue；改配额是平台管理员改 ClusterQueue。

### 3.3 配额、借用、抢占

#### 3.3.1 nominalQuota：配额账本，不是物理容量

`nominalQuota` 是**这个 ClusterQueue 在某个 flavor 上、不向 cohort 借用时，可以持有的资源量**。名字里的 “nominal” 就是在提醒你：它是配置出来的名义额度，不是节点上实测的容量。

admission 的判定（没有 cohort 时）：

```text
sum(已 Admitted Workload 的 request) + 新 Workload 的 request
  ≤ nominalQuota
```

有 cohort 时，条件放宽为“自己的 nominalQuota + 允许借的量”，见 §3.3.2。

它不是什么：

| 容易误解 | 实际 |
|---|---|
| 物理 GPU 数 | 逻辑额度；可以大于真实容量（然后 Pod Pending），也可以小于（然后 GPU 闲置） |
| GPU 利用率上限 | 只看 request；用 5% 也算占满 1 张 |
| 节点预留 | 不绑节点；真正绑定发生在 kube-scheduler |
| 永久硬上限 | 加入 cohort 后可以借，借了就可能超过 nominalQuota |
| 按 Pod 实时计费 | 按 Workload 占着；Job 结束才释放 |

D5 的取值：team A / team B 各 `nominalQuota: 1`，但集群只有 1 张物理卡，两个 CQ 合计 2 > 1。**这是故意的配额超卖**：team B 的 Workload 会被 Kueue 放行（`Admitted=True`），Pod 却因 `Insufficient nvidia.com/gpu` 留在 `Pending`——正好演示 §0 第 3 条。生产上应让 `nominalQuota` 不超过真实 allocatable；D5 反着配，是为了把账本和容量分开。

一个常见的排障 message：

```text
insufficient unused quota for nvidia.com/gpu in flavor gpu-3060, 1 more needed
```

翻成人话：**不是节点没卡，是这个 ClusterQueue 的账本上没额度了。** 先看 `kubectl get clusterqueue team-a-cq -o yaml` 的 `status.flavorsUsage`，再看 Pod 的 `Pending` 原因；两者不要混。

#### 3.3.2 cohort：把多个 ClusterQueue 的闲置配额放进一个池子

`cohort` 就是一个字符串名字。所有 `spec.cohortName` 相同的 ClusterQueue 属于同一个 cohort，可以在彼此**闲置**时借配额。

```text
cohort: research
  team-a-cq   nominalQuota: 1   borrowingLimit: 1
  team-b-cq   nominalQuota: 1
```

- team B 空闲时，team A 最多可以用 `1 + 1 = 2` 张卡（自己的 1 + 借来的 1）。
- team B 一提交，team A 是否要让出，取决于 `reclaimWithinCohort`。
- 没有 cohort（`cohortName` 为空）就是严格隔离：team A 只能用自己的 1 张，B 的卡空着也不能用。

注意这是**配额账本**上的 2 张，不代表物理上多了一张卡。D5 只有 1 张物理卡，借到额度的第二个 Workload 会 `Admitted`，但 Pod 仍可能 `Pending`（§9.6）。

三个限制字段：

| 字段 | 管谁 | 不设时 |
|---|---|---|
| `borrowingLimit` | 借方最多借多少 | 最多借到 cohort 所有 nominalQuota 之和 |
| `lendingLimit` | 贷方最多借出多少 | 闲置的全都可以借出 |
| `reclaimWithinCohort` | 贷方要收回时，能不能抢占借方 | `Never`（默认不抢） |

`borrowWithinCohort` 是另一个方向：**借方自己需要借配额时，能不能抢占 cohort 里其他低优先级的 Workload**。它只在 `reclaimWithinCohort != Never` 时生效，还可以用 `maxPriorityThreshold` 限制“只抢 priority ≤ N 的”。

最容易混的两点：

- **cohort 不是 namespace，也不是节点池。** 它只影响配额记账，不影响 Pod 能调度到哪些节点；节点范围仍由 `ResourceFlavor` 的 label/taint 决定。
- **cohort 不是“自动扩容”。** 借来的仍然是集群里已有的闲置配额，不会变出 GPU。

D5 核心实验**不设 cohort**，先讲严格隔离；有余力再加 10 分钟可选实验：给两个 CQ 加同一个 cohort，观察 A 借到 B 的额度、B 提交后 A 被 reclaim。单卡上只能看到额度借用/回收，不能看到两个团队同时 `Running`。

#### 3.3.3 priority：决定“谁先开始、谁被抢”

Workload 的 `priority` 是一个整数，越大越优先。它影响两件事：

1. **排队顺序**：pending 队列先按 priority 降序，再按 `creationTimestamp` 升序。
2. **抢占资格**：高 priority 的 Workload 可以按策略驱逐低 priority 的 Workload。

priority 有两个来源，别混：

| 来源 | 怎么设 | 影响范围 |
|---|---|---|
| **Pod priority** | Job 的 `spec.template.spec.priorityClassName` | Kueue 继承为 Workload priority，**同时**影响 kube-scheduler 的 Pod 抢占 |
| **WorkloadPriorityClass** | Job metadata 的 label `kueue.x-k8s.io/priority-class: <name>` | 只影响 Kueue 排队/抢占，不改变 Pod priority |

```yaml
# 方式 1：Pod priority（D5 用这个）
spec:
  template:
    spec:
      priorityClassName: gpu-high
---
# 方式 2：Workload priority（不想动 Pod priority 时）
metadata:
  labels:
    kueue.x-k8s.io/queue-name: team-a
    kueue.x-k8s.io/priority-class: high-priority
```

队列策略（`spec.queueingStrategy`）：

| 策略 | 行为 | 适合 |
|---|---|---|
| `StrictFIFO` | 前面的 Workload 进不来，后面的也不许插队 | 严格公平、可预测 |
| `BestEffortFIFO`（默认） | 前面大的进不来，后面小的能塞就塞 | 提高利用率，避免队头阻塞 |

**priority 不是配额。** 高优先级 Workload 也不能凭空超过 `nominalQuota`；它只是排到前面，或者在配额已满时按策略抢低优先级的额度。

#### 3.3.4 preemption：三个边界

Kueue 的抢占分三个边界，配置和语义都不同：

| 边界 | 字段 | 回答的问题 |
|---|---|---|
| 同 ClusterQueue 内 | `preemption.withinClusterQueue` | 队列满了，高 priority 能不能抢同队列的低 priority？ |
| cohort 内 reclaim | `preemption.reclaimWithinCohort` | 我把配额借给别人了，我要用时能不能收回？ |
| cohort 内 borrow | `preemption.borrowWithinCohort` | 我要借配额，能不能抢别人正在用的？ |

D5 只开第一个：

```yaml
preemption:
  withinClusterQueue: LowerPriority
```

抢占的动作是**驱逐 Workload**：Workload 变为 `Evicted=True, reason=Preempted`，Job 被重新 `suspend`，Pod 被删；等配额空出来，高 priority 的 Workload 被 admit，Job 再恢复。不是“暂停容器”，也不是“把 Pod 挪走”。

### 3.4 Kueue vs HPA/KEDA

| 维度 | Kueue | HPA / KEDA |
|---|---|---|
| 对象 | 批处理 Job / 训练 / 离线推理；Deployment/StatefulSet 也能接，但按 **Pod 粒度** 管（见 §3.4.1） | 长期运行的 Deployment / StatefulSet |
| 动作 | 准入、排队、挂起、抢占 | 增减副本数 |
| 触发 | 配额、优先级、cohort | CPU/GPU/队列深度/自定义指标 |
| 会加节点吗 | 不会 | 不会（要 Cluster Autoscaler / Karpenter） |
| 典型问题 | “为什么我的 Job 一直 Pending？” / “为什么 Deployment 只起来一部分 Pod？” | “为什么副本扩不出去？” |
| 和 D3 的关系 | D5 管“谁能拿卡” | D3 的 KEDA 管“服务扩几个副本” |

一句话：**Kueue 决定“能不能开始”，HPA/KEDA 决定“同时跑几个”。**

#### 3.4.1 为什么 D5 用 Job，不用 D1–D4 的 Deployment

D1–D4 的 Deployment 是 **serving 单元**：长期运行、滚动更新、HPA/KEDA 扩副本。D5 要演示的是**批处理队列**，Job 才是 Kueue 的一等公民：

| 维度 | Job | Deployment |
|---|---|---|
| Kueue 管理粒度 | **整个 Job 一个 Workload**，所有 Pod 原子准入 | **每个 Pod 一个 Workload**，不是整个 Deployment |
| 挂起/恢复 | `spec.suspend`；挂起后 Job controller 不建 Pod | 没有“挂起整个 Deployment”的字段；scale-out 的新 Pod 被 gate 住，旧 Pod 继续跑 |
| 抢占 | 驱逐 Workload → Job suspend → 可恢复 | 驱逐一个 Pod → ReplicaSet 补一个，队列语义变成 Pod 级 |
| 完成态 | 有 Succeeded/Failed，结束即释放配额 | 永远 Running，没有“做完释放配额” |
| 和 HPA/KEDA | 不适用 | 副本数由 HPA/KEDA 管，和配额准入会互相干扰 |

Kueue 的 Deployment integration 是 **Pod-based**，官方原话是 “Kueue does not yet support managing a Deployment as a single Workload”。所以用 Deployment 做 D5 会得到：

- `kubectl get workloads` 里是 2 个 Pod Workload，不是 1 个 Job Workload；
- 配额 1 时 Deployment 只起 1 个 Pod，另一个被 scheduling gate 挡住；
- 抢占演示不再是“一个 Workload 被 Evicted”，而是“一个 Pod 被删、ReplicaSet 再补一个”。

这不是说 Deployment 不能接 Kueue。生产上 serving + Kueue 的常见做法是：

- 用 `lendingLimit` 给在线服务预留配额，避免训练把卡借光；
- 或者 serving 走 `ResourceQuota` + `PriorityClass`，Kueue 只管 batch；
- 真要 Pod 级配额，就给 Deployment 的 `metadata.labels` 加 `kueue.x-k8s.io/queue-name`，并接受“只起一部分副本”。

D5 选 Job 还有实验原因：`pause` 镜像秒起，不下载模型；用 vLLM Deployment 每个样本要等 2–5 分钟 cold start，3h 里跑不了几轮，而且会把“配额排队”和“模型加载”混在一起。

### 3.5 为什么 Kueue 需要 Kyverno 补入口

Kueue 默认只管理带 `kueue.x-k8s.io/queue-name` 的 Job。原因是它要 opt-in，避免误管系统 Job。

于是有一个真实缺口：

```text
用户提交 GPU Job，但忘记/故意不写 queue label
  → Kueue 不创建 Workload
  → Job 直接运行
  → 配额被绕过
```

有两种补法：

| 方案 | 做法 | 优缺点 |
|---|---|---|
| Kueue 全局接管 | `manageJobsWithoutQueueName: true` | 能兜底，但会碰到系统 Job；错误信息不如策略清晰 |
| Kyverno 入口策略 | GPU Job 必须带 queue label / priorityClass | 精准、可审计、错误信息明确；推荐 |

D5 用第二种，并把第一种作为生产 hardening 的补充。

### 3.6 CEL 速成（D5 专用）

> 这一节是 D5 的“政策语言”基础。不会 CEL，后面的 Kyverno 策略只能抄；会 CEL，才能改、能测、能排障。

#### 3.6.1 CEL 是什么

**CEL = Common Expression Language**，Google 开源的表达式语言。Kubernetes 自己用它做：

- CRD 的 `x-kubernetes-validations`
- `ValidatingAdmissionPolicy`
- `MutatingAdmissionPolicy`
- 以及 Kyverno 1.20 的 CEL 策略

CEL 的特点：

- **无副作用**：不能创建资源、不能写文件、不能发任意请求；
- **一定终止**：没有 `while`/`for`，用 `exists` / `all` / `filter` / `map` 做集合运算；
- **可类型检查**：策略加载时就能发现类型错误；
- **确定性**：同一输入同一结果。

它像 SQL 的 `WHERE`，不是通用编程语言。

#### 3.6.2 “CEL 类型”指哪些

不是“一种数据类型”，而是 **CEL-based policy types**：

| Kind | 用途 | 逻辑写在哪 | 短名 |
|---|---|---|---|
| `ValidatingPolicy` | 校验/拒绝 | `spec.validations[].expression`，返回 `bool` | `vpol` |
| `NamespacedValidatingPolicy` | namespace 自管校验 | 同上 | `nvpol` |
| `MutatingPolicy` | 变更 | `spec.mutations[].applyConfiguration.expression` 或 `jsonPatch.expression` | `mpol` |
| `NamespacedMutatingPolicy` | namespace 自管变更 | 同上 | `nmpol` |
| `GeneratingPolicy` | 生成资源 | `spec.generate[].expression` | `gpol` |
| `ImageValidatingPolicy` | 镜像签名/证明 | `spec.attestations[].expression` 等 | `ivpol` |
| `DeletingPolicy` | 清理 | `spec.conditions[].expression` | `dpol` |

策略例外用 `policies.kyverno.io/v1` 的 `PolicyException`（不是 CEL 策略类型）。

D5 只用 `ValidatingPolicy` ×2 + `MutatingPolicy` ×1。

#### 3.6.3 旧 DSL vs CEL：不是“更短”，是“更清楚”

旧 `ClusterPolicy` 要求 Pod 带 `team` label：

```yaml
# 旧：kyverno.io/v1（1.20 已不执行）
validate:
  message: "label team is required"
  pattern:
    metadata:
      labels:
        team: "?*"
```

CEL：

```yaml
validations:
  - expression: >-
      has(object.metadata.labels) &&
      'team' in object.metadata.labels &&
      object.metadata.labels.team != ''
    message: "label team is required"
```

**简单场景旧 DSL 更短。** 但复杂场景 CEL 更清楚，例如“所有容器都设置 CPU limit”：

```cel
object.spec.containers.all(c,
  has(c.resources) &&
  has(c.resources.limits) &&
  'cpu' in c.resources.limits)
```

旧 DSL 要靠 `foreach` + `pattern` + `deny.conditions` 一层层套。D5 的“GPU 在 limits **或** requests 里”也是同理。

| 维度 | 旧 DSL | CEL |
|---|---|---|
| 简单 label/镜像校验 | 更短 | 稍长，但显式 |
| 集合、OR、嵌套字段 | 要 `foreach`/`deny`/锚点 | `all`/`exists`/`filter` 直接 |
| 类型检查 | 较弱 | 编译期检查 |
| 调试 | 报错偏模糊 | `kyverno apply --explain` 逐步显示 |
| 可移植 | Kyverno 专属 | 与 K8s 原生 VAP 同一套 CEL |
| 变更 | `patchStrategicMerge` 简单 | JSONPatch 更啰嗦 |

结论：**简单策略旧语法更省事；D5 这种带 OR、集合、跨字段条件的策略，CEL 更简单、更可维护。**

#### 3.6.4 语法速查

| 语法 | 含义 | 例子 |
|---|---|---|
| `object` | 当前 admission 对象 | `object.metadata.name` |
| `oldObject` | 更新前的对象 | `oldObject.spec.replicas` |
| `request` | admission 请求上下文 | `request.namespace` |
| `variables.x` | 前面定义的变量 | `variables.isGPU` |
| `has(x.y)` | 字段是否存在 | `has(object.spec.suspend)` |
| `'k' in map` | map 是否有 key | `'team' in labels` |
| `list.exists(x, cond)` | 是否存在一个满足 | `containers.exists(c, ...)` |
| `list.all(x, cond)` | 是否全部满足 | `containers.all(c, ...)` |
| `list.filter(x, cond)` | 过滤 | `containers.filter(c, ...)` |
| `list.map(x, expr)` | 映射 | `containers.map(c, c.name)` |
| `a ? b : c` | 三元 | `has(x) ? x : default` |
| `object.metadata.?labels.orValue({})` | 可选字段 + 默认值 | 取可能不存在的 labels |
| `size(x)` | 长度 | `size(object.spec.containers)` |
| `s.startsWith("x")` | 字符串前缀 | `c.image.startsWith("nginx")` |
| `s.contains("x")` | 字符串包含 | `c.image.contains("latest")` |

**布尔语义：** `ValidatingPolicy` 的 `expression` 返回 `true` = 通过，`false` = 违反策略。

#### 3.6.5 逐行读懂 D5 的 CEL

**变量 1：把 containers 和 initContainers 拼起来**

```cel
object.spec.template.spec.containers +
(has(object.spec.template.spec.initContainers)
  ? object.spec.template.spec.initContainers
  : [])
```

- Job 的 Pod 模板在 `spec.template.spec`；
- initContainer 也可能请求 GPU，不能漏；
- `has()` 防止字段不存在时报错。

**变量 2：判断是不是 GPU workload**

```cel
variables.containers.exists(c,
  (has(c.resources) && has(c.resources.limits) &&
   'nvidia.com/gpu' in c.resources.limits) ||
  (has(c.resources) && has(c.resources.requests) &&
   'nvidia.com/gpu' in c.resources.requests))
```

- `exists` = 任意一个容器满足；
- GPU 可以写在 `limits` 或 `requests`；
- 先 `has()` 再 `in`，避免空字段错误。

**变量 3：安全取 labels**

```cel
has(object.metadata.labels) ? object.metadata.labels : {}
```

- 没有 labels 时返回空 map；
- 后面 `'key' in variables.labels` 不会炸。

**校验 1：queue label 必须存在**

```cel
!variables.isGPU ||
('kueue.x-k8s.io/queue-name' in variables.labels)
```

- 非 GPU workload 直接放行；
- GPU workload 必须有 queue label。

**校验 2：queue label 必须等于 namespace**

```cel
!variables.isGPU ||
(variables.labels['kueue.x-k8s.io/queue-name'] == object.metadata.namespace)
```

- 防止 team A 把 Job 标成 team B 的 queue；
- Kueue 的 `namespaceSelector` 也会兜底，但入口拒绝更清晰。

**校验 3：priorityClass 必须在白名单**

```cel
!variables.isGPU ||
(has(object.spec.template.spec.priorityClassName) &&
 object.spec.template.spec.priorityClassName in ['gpu-high', 'gpu-low'])
```

- `in` 用于 list；
- 不允许用户随便造一个 `priorityClassName`。

**Pod 策略的 queueName：同时接受两种 label**

```cel
('kueue.x-k8s.io/queue-name' in variables.labels)
  ? variables.labels['kueue.x-k8s.io/queue-name']
  : (('kueue.x-k8s.io/local-queue-name' in variables.labels)
      ? variables.labels['kueue.x-k8s.io/local-queue-name']
      : '')
```

为什么：裸 Pod 用 `queue-name`；Kueue 创建的 Pod 用 `local-queue-name`。只认一个会把另一边拒掉。

**MutatingPolicy：加 `cost-center`**

```cel
has(object.metadata.labels) ?
[JSONPatch{op: "add", path: "/metadata/labels/cost-center", value: "shared-gpu"}] :
[JSONPatch{op: "add", path: "/metadata/labels", value: {"cost-center": "shared-gpu"}}]
```

两个注意点：

1. `cost-center` 带连字符，`ApplyConfiguration` 的对象字面量不能直接写 `cost-center: ...`（CEL 标识符不允许 `-`），所以用 `JSONPatch`。
2. labels 可能不存在，要分两条 patch 路径。

#### 3.6.6 写一条 CEL 策略的四步

1. **选 Kind**：拒绝用 `ValidatingPolicy`，改变改用 `MutatingPolicy`。
2. **写 `matchConstraints`**：资源、API group、操作。Job 是 `batch/v1 jobs`，裸 Pod 是 `v1 pods`。
3. **抽 `variables`**：把“什么是 GPU”“labels 是什么”抽出来，validation 只写布尔逻辑。
4. **写 `validations`**：每条一个条件，`message` 要能告诉用户怎么修。

模板：

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: <name>
spec:
  validationActions: [Deny]
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: ["batch"]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["jobs"]
  variables:
    - name: ...
      expression: ...
  validations:
    - expression: <bool>
      message: <how to fix>
```

#### 3.6.7 调试 CEL

**离线单测（不碰集群）：**

```bash
kyverno apply scripts/d5/30-kyverno-policies.yaml \
  --resource scripts/d5/jobs/team-a-low-1.yaml --explain
```

`--explain` 会打印：

- 策略是否 match；
- 每个 `variables` 的值；
- 每条 validation 的 true/false；
- 最终 verdict。

**集群内 dry-run（会走 webhook，但不创建对象）：**

```bash
kubectl apply --dry-run=server -f scripts/d5/jobs/invalid-no-priority.yaml
```

**看策略是否加载成功：**

```bash
kubectl get vpol
kubectl describe vpol d5-gpu-job-policy
```

`READY=true` 才说明 CEL 编译通过。

**常见错误：**

| 现象 | 原因 | 修法 |
|---|---|---|
| YAML 解析报 `mapping values are not allowed` | `expression:` 后面直接写带 `? :` 的 plain scalar | 用 `>-` 块，或加引号 |
| `no such key: labels` | 没判空 | `has(...) ? ... : {}` |
| Job 被 Pod 策略误拒 | autogen 从 Pod 规则生成了 Job 规则 | `spec.autogen.podControllers.controllers: []` |
| 明明写了 `suspend: false` 却没被拒 | Kueue mutating webhook 先把它改成 true | 不要用 validating policy 检查会被 mutating webhook 改写的字段 |
| `cost-center` 编译失败 | CEL 对象字面量 key 不能带 `-` | 用 `JSONPatch` |
| `matchConstraints` 不生效 | API group / resource 写错 | Job 是 `batch/v1 jobs`，Pod 是 `v1 pods` |

**admission 顺序的坑（D5 本地 kind 实测）：**

Kueue 的 mutating webhook 会把带 queue label 的 Job 的 `suspend` 改成 `true`，然后 Kyverno validating webhook 才看到对象。所以：

```yaml
# 这条 validation 在装了 Kueue 的集群里几乎永远不会失败
!variables.isGPU || object.spec.suspend == true
```

它不是没用（没有 Kueue 时可兜底），但**不能拿它做拒绝演示**。D5 的策略因此不强制校验 `suspend`，由 Kueue 自己保证。这个实验保留在 `scripts/d5/jobs/probe-suspend.yaml`，用来讲“mutating 先于 validating”。

#### 3.6.8 10 分钟练习

1. 给 GPU Job 再加一条校验：必须有 `team` label，且值等于 namespace。
2. 给 `MutatingPolicy` 加一条：把 `cost-center` 的值改成 `object.metadata.namespace`，而不是固定 `shared-gpu`。
3. 用 `kyverno apply --explain` 分别跑合法 Job 和 `invalid-no-priority.yaml`，确认前者全 pass、后者在 priority 那条 fail。

参考答案：

```cel
# 练习 1
!variables.isGPU ||
('team' in variables.labels &&
 variables.labels['team'] == object.metadata.namespace)
```

```cel
# 练习 2：JSONPatch 的 value 可以用表达式
[JSONPatch{
  op: "add",
  path: "/metadata/labels/cost-center",
  value: object.metadata.namespace
}]
```

#### 3.6.9 CEL 的边界

- **不能有副作用**：校验表达式不能创建资源；要生成资源用 `GeneratingPolicy`。
- **不是通用语言**：没有任意循环、异常处理；复杂逻辑拆 `variables`。
- **纯 CEL 不能调 API**：Kyverno 额外提供资源查询/镜像校验等 CEL 库，但那是扩展。
- **类型要匹配**：validation 返回 `bool`；mutation 返回对象或 `JSONPatch` 列表。
- **可读性**：超过几行的表达式拆变量，用 `messageExpression` 输出具体原因。

### 3.7 审计与 chargeback 的数据从哪来

| 数据源 | 能回答什么 | 注意 |
|---|---|---|
| Kueue `Workload` conditions | 谁被 admit、谁 pending、谁被 preempt | 对象删除后历史就没了，要定期快照 |
| Kueue metrics | pending 数、admitted 数、preempted 数 | 需要 Prometheus/port-forward |
| Kyverno metrics | 哪条策略拒绝了多少次 | `kyverno_validating_policy_results_total` |
| Kyverno `PolicyReport` | 现存资源的策略结果 | **不是历史审计日志**；被拒对象不存在，不会有 report |
| Kubernetes Events | 拒绝、抢占、调度失败 | 默认保留时间有限 |
| API server audit log | 谁在什么时候提交了什么 | 生产审计的最终依据；lab 可不配 |
| 标签 `team` / `cost-center` | 按团队/成本中心聚合 | 必须由准入策略强制，不能靠用户自觉 |

**结论：** 要证明“平台没被滥用”，不能只看 PolicyReport；要 **API audit + Kueue conditions/metrics + 强制标签** 三件套。

---

## 4. 目标架构

```text
                         kubectl apply (team-a)
                                  │
                                  ▼
                    ┌─────────────────────────────┐
                    │ Kyverno ValidatingPolicy     │
                    │ - queue label 存在且等于 ns   │
                    │ - priorityClass 在白名单      │
                    │ 失败 → Forbidden             │
                    └─────────────┬───────────────┘
                                  │ 通过
                                  ▼
                    ┌─────────────────────────────┐
                    │ Kueue mutating webhook       │
                    │ 创建 Workload，Job 保持 suspend│
                    └─────────────┬───────────────┘
                                  │
              ┌───────────────────┴───────────────────┐
              ▼                                       ▼
   LocalQueue team-a                        LocalQueue team-b
   ClusterQueue team-a-cq                   ClusterQueue team-b-cq
   nominalQuota: 1 GPU                      nominalQuota: 1 GPU
              │                                       │
              └───────────────────┬───────────────────┘
                                  ▼
                        ResourceFlavor gpu-3060
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
            team-a-low-1 Pod              team-b-low-1 Pod
              Running                       Pending
                    │                 Insufficient nvidia.com/gpu
                    ▼
              唯一 1 张物理 GPU
            （型号/显存以 nvidia-smi 为准）
```

`nominalQuota` 合计 2 > 物理 1，是**故意超卖**：Kueue 的账本放行 team B，kube-scheduler 的容量拒绝它。

**资源清单：**

| 对象 | 数量 | 说明 |
|---|---|---|
| 物理 GPU | 1 | 型号 / 显存执行时记录；两个 CQ 的 `nominalQuota` 合计 2 > 1 |
| Namespace | 2 | `team-a` / `team-b`，带 `gpu-pool: d5` |
| PriorityClass | 2 | `gpu-high`（1000）/ `gpu-low`（100） |
| ResourceFlavor | 1 | `gpu-3060`，空 spec 匹配所有节点；只是逻辑名 |
| ClusterQueue | 2 | 各 1 GPU、8 CPU、16Gi；合计 2 > 物理 1，故意超卖 |
| LocalQueue | 2 | 各指向自己的 ClusterQueue |
| ValidatingPolicy | 2 | Job + Pod 两层 |
| MutatingPolicy | 1 | 给 Pod 加 `cost-center` |

---

## 5. Lab 0：VM + k3s + GPU

### 5.0 租 VM

D5 复用 D3 的 Vast VM 路径。**必须用 `vms_enabled=true` 的 VM offer**，普通容器实例起不了 k3s。

```bash
vastai search offers -n \
  'num_gpus=1 rentable=true vms_enabled=true cuda_vers>=13.0 disk_space>=40 inet_down>=500 reliability>=0.98 cpu_ram>=64' \
  -o 'dph' --storage 40 --limit 10
```

不绑定 GPU 型号；选当时最便宜、满足 `vms_enabled=true` 的单卡 offer。D5 不需要 D4 的大磁盘，`40GB` 足够装 k3s/Kueue/Kyverno，实际按 offer 填。

创建走 API，显式 `"vm": true`（CLI 的 `create instance` 不带 `vm` 字段，可能起成容器）：

```bash
curl -s -X PUT "https://console.vast.ai/api/v0/asks/<OFFER_ID>/" \
  -H "Authorization: Bearer $(cat ~/.config/vastai/vast_api_key)" \
  -H "Content-Type: application/json" \
  -d '{"template_hash_id":"2c18cabd8f2f0525c2ff8446f5d4e063","vm":true,"disk":40,"runtype":"ssh_direct","label":"d5-kueue","cancel_unavail":true}' \
  | python3 -m json.tool
```

完整 VM 创建/SSH/排障见 D3 §5.0；模板 hash、`vm:true` 不要改错。`disk` 填 offer 的实际磁盘（≥40GB），D5 不需要 D4 那么大的磁盘；如果模板 hash 失效，选当前 Ubuntu VM 模板，但仍要保留 `"vm":true`。

### 5.1 安装 NVIDIA runtime + k3s + device plugin

先装 toolkit，再装 k3s，让 k3s 首次启动就识别 NVIDIA runtime：

```bash
# toolkit
sudo apt-get update
sudo apt-get install -y curl ca-certificates gnupg
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
nvidia-ctk --version
which nvidia-container-runtime

# k3s，固定版本
curl -sfL https://get.k3s.io | sudo INSTALL_K3S_VERSION=v1.37.2+k3s1 sh -s - --write-kubeconfig-mode 644
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown "$USER" ~/.kube/config
kubectl get nodes

# device plugin
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.18.0/deployments/static/nvidia-device-plugin.yml
kubectl -n kube-system patch ds nvidia-device-plugin-daemonset --type merge \
  -p '{"spec":{"template":{"spec":{"runtimeClassName":"nvidia"}}}}'
kubectl -n kube-system rollout status ds/nvidia-device-plugin-daemonset --timeout=180s
```

> 详细排障（runtime 没被 k3s 识别、device plugin allocatable=0）见 D3 §5.2–§5.4。

### 5.2 确认一张卡

```bash
nvidia-smi -L
nvidia-smi --query-gpu=name,memory.total --format=csv
kubectl get node -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}{"\n"}'
# 期望：1
```

GPU smoke：

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: gpu-smoke
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

kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/gpu-smoke --timeout=120s
kubectl logs gpu-smoke
kubectl delete pod gpu-smoke
```

看到 `nvidia-smi` 只报告 1 张卡（型号 / 显存以实际输出为准）和 smoke Pod 成功，才继续。把型号、显存写进 `results/d5/machine.txt`。

### 5.3 安装 Helm 和 jq

```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version
sudo apt-get install -y jq
jq --version
```

### 5.4 记录版本

```bash
mkdir -p results/d5
{
  k3s --version
  nvidia-smi --query-gpu=name,memory.total,driver_version,power.limit --format=csv
  kubectl version
} | tee results/d5/machine.txt
```

把版本写进 `results/d5/machine.txt`（可同时摘进 `summary.md`）；版本不同，Kueue/Kyverno 行为可能不同。

---

## 6. Lab 1：安装 Kueue + 配额对象

### 6.1 安装 Kueue

```bash
kubectl apply --server-side -f \
  https://github.com/kubernetes-sigs/kueue/releases/download/v0.20.7/manifests.yaml

kubectl wait deploy/kueue-controller-manager -n kueue-system \
  --for=condition=available --timeout=5m
kubectl get pods -n kueue-system

# Kueue 首次启动会轮换证书并重启一次；等 webhook endpoint 真正出现再 apply 配额
for i in $(seq 1 30); do
  EP=$(kubectl -n kueue-system get endpoints kueue-webhook-service \
    -o jsonpath='{.subsets[0].addresses[0].ip}' 2>/dev/null || true)
  if [ -n "$EP" ]; then break; fi
  sleep 2
done
kubectl -n kueue-system get endpoints kueue-webhook-service
```

> 必须用 `--server-side`；Kueue 的 CRD 很大，client-side apply 可能报 annotation 过大。
>
> 如果 apply `20-kueue.yaml` 报 `failed calling webhook ... connection refused`，不是 YAML 错，是 webhook 还没 ready；等 10–20s 重试。

### 6.2 创建 namespace、PriorityClass、队列

```bash
kubectl apply -f scripts/d5/00-namespaces.yaml
kubectl apply -f scripts/d5/10-priorityclasses.yaml
kubectl apply -f scripts/d5/20-kueue.yaml
```

### 6.3 验证

```bash
kubectl get resourceflavor
kubectl get clusterqueue
kubectl get localqueue -A
kubectl describe clusterqueue team-a-cq
```

期望：

```text
NAME        COHORT   PENDING WORKLOADS
team-a-cq            0
team-b-cq            0
```

`describe` 里应看到：

```text
nvidia.com/gpu  Nominal Quota: 1
cpu             Nominal Quota: 8
memory          Nominal Quota: 16Gi
Within Cluster Queue: LowerPriority
```

### 6.4 字段解释

| 字段 | 值 | 为什么 |
|---|---|---|
| `namespaceSelector` | `kubernetes.io/metadata.name: team-a` | 只允许 team-a 的 Workload 进入这个 CQ |
| `coveredResources` | GPU/CPU/memory | 防止只卡 GPU、CPU/内存被吃光 |
| `nominalQuota` | 1 GPU / 8 CPU / 16Gi | 两个 CQ 各 1，合计 2 > 物理 1；**故意超卖**，用来演示 quota ≠ capacity |
| `preemption.withinClusterQueue` | `LowerPriority` | 允许同团队高优先级抢占低优先级 |
| `reclaimWithinCohort` | 默认 `Never` | 核心实验严格隔离，不跨团队抢 |
| `borrowWithinCohort` | 默认 `Never` | 同上 |
| `queueingStrategy` | 默认 `BestEffortFIFO` | 后面的小 Job 可以绕过前面的大 Job，避免队头阻塞 |

> `gpu-3060` 只是沿用脚本的 flavor 逻辑名；实际卡型以 `nvidia-smi` 为准，不影响配额语义。改名要同步 `scripts/d5/20-kueue.yaml`、`scripts/d5/README.md` 和本文的期望输出/cleanup 命令。

### 6.5 为什么核心实验不用 cohort

- 用 cohort + borrowing，team A 可以在 team B 空闲时借额度（账本上多出 1 张）；但单卡集群不会因此多出物理卡，第二个 Workload 会 `Admitted` 但 Pod `Pending`。演示更花哨，但会掩盖“配额硬上限”。
- 先把严格配额跑通，再在 §9.6 可选加 cohort，讲“借用/回收”。

---

## 7. Lab 2：先证明 Kueue 的盲区

### 7.1 提交一个不带 queue label 的 GPU Job

这一步在**装 Kueue 之后、装 Kyverno 之前**做：Kueue 已装，但默认不接管没有 queue label 的 Job。`scripts/d5/jobs/bypass-no-queue.yaml` 的特征：

- 有 `nvidia.com/gpu: 1`；
- **没有** `kueue.x-k8s.io/queue-name`；
- `suspend: false`，所以不会被 Kueue 挂起。

```bash
kubectl apply -f scripts/d5/jobs/bypass-no-queue.yaml
kubectl get jobs,pods -n team-a -o wide
kubectl get workloads -n team-a
```

期望：

```text
job.batch/bypass-no-queue   Running
pod/bypass-no-queue-xxxxx   Running
No resources found in team-a namespace.   # 没有 Workload
```

节点上 GPU 被占用：

```bash
kubectl describe node | sed -n '/Allocated resources:/,/Events:/p'
# nvidia.com/gpu  1 (Requests 占满唯一一张卡)
```

> 记录后立即按 §7.3 删除；它会占住唯一的 GPU，不能留到后面的 Kyverno 拒绝和抢占步骤。

### 7.2 结论

- Kueue 默认 `manageJobsWithoutQueueName=false`；
- 没有 queue label 的 Job 不会被 Kueue 接管；
- 它会直接走 kube-scheduler，绕过配额。

这就是为什么需要 Kyverno：**在 API 入口就把不带 label 的 GPU Job 拒掉。**

### 7.3 清理

```bash
kubectl delete -f scripts/d5/jobs/bypass-no-queue.yaml
```

### 7.4 可选：Kueue 全局接管

如果想让 Kueue 管所有 Job：

```bash
kubectl -n kueue-system edit configmap kueue-manager-config
# 在 controller_manager_config.yaml 里加：
#   manageJobsWithoutQueueName: true
kubectl -n kueue-system rollout restart deploy/kueue-controller-manager
```

风险：系统 Job（如 k3s 的维护 Job）也会被 Kueue 挂起。生产上要么排除系统 namespace，要么用 Kyverno 精准策略。D5 不把这个作为主路径。

---

## 8. Lab 3：安装 Kyverno + CEL 策略

### 8.1 安装 Kyverno 1.20

```bash
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update
helm install kyverno kyverno/kyverno --version 3.10.0 -n kyverno --create-namespace
kubectl -n kyverno rollout status deploy/kyverno-admission-controller --timeout=300s
kubectl get pods -n kyverno

# 同样等 webhook endpoint 真正可用
for i in $(seq 1 30); do
  EP=$(kubectl -n kyverno get endpoints kyverno-svc \
    -o jsonpath='{.subsets[0].addresses[0].ip}' 2>/dev/null || true)
  if [ -n "$EP" ]; then break; fi
  sleep 2
done
kubectl -n kyverno get endpoints kyverno-svc
```

> 没有 Helm 也可以用 YAML：
> `kubectl create -f https://github.com/kyverno/kyverno/releases/download/v1.20.0/install.yaml`
>
> Kyverno 1.20 支持 Kubernetes 1.34–1.37；k3s 1.37.2 满足。

### 8.2 应用 CEL 策略

```bash
kubectl apply -f scripts/d5/30-kyverno-policies.yaml
kubectl get vpol,mpol
```

期望三个对象都是 `READY=true`：

```text
NAME                                                     READY
validatingpolicy.policies.kyverno.io/d5-gpu-job-policy   true
validatingpolicy.policies.kyverno.io/d5-gpu-pod-policy   true

NAME                                                     READY
mutatingpolicy.policies.kyverno.io/d5-gpu-cost-center    true
```

如果 `READY=false`：

```bash
kubectl describe vpol d5-gpu-job-policy
```

看 `status.conditions` 里的 CEL 编译错误。

### 8.3 三条策略分别做什么

| 策略 | Kind | 匹配 | 作用 |
|---|---|---|---|
| `d5-gpu-job-policy` | `ValidatingPolicy` | `batch/v1 Job` | GPU Job 必须有 queue label、label 等于 namespace、priorityClass 在白名单 |
| `d5-gpu-pod-policy` | `ValidatingPolicy` | `v1 Pod` | 同样的规则，兜住裸 Pod；接受 `local-queue-name` |
| `d5-gpu-cost-center` | `MutatingPolicy` | `v1 Pod`（`gpu-pool: d5` namespace） | 加 `cost-center: shared-gpu`，供 chargeback |

**为什么 Job 和 Pod 各一条：**

- 用户通常提交 Job；Job 策略给出最清晰的错误；
- 有权限的人可以绕过 Job 直接创建 Pod；Pod 策略兜底；
- Pod 策略显式关闭 autogen，避免 Kyverno 从 Pod 规则生成 Job 规则（Job 的 queue label 在 `metadata.labels`，不在 Pod template 里）。

**为什么 Pod 策略接受 `local-queue-name`：**

Kueue 给 Pod 加的是 `kueue.x-k8s.io/local-queue-name`；只认 `queue-name` 会把 Kueue 自己创建的 Pod 拒掉。详见 §2.3 坑 3。

### 8.4 先离线测试 CEL

不碰集群，先看表达式是否按预期。需要 Kyverno CLI 1.20；没有就跳过，直接用 §8.5 的 `--dry-run=server`：

```bash
# 可选：安装 Kyverno CLI 1.20.0
curl -sL -o /tmp/kyverno-cli.tar.gz \
  https://github.com/kyverno/kyverno/releases/download/v1.20.0/kyverno-cli_v1.20.0_linux_x86_64.tar.gz
tar xzf /tmp/kyverno-cli.tar.gz -C /tmp kyverno
sudo mv /tmp/kyverno /usr/local/bin/kyverno

kyverno apply scripts/d5/30-kyverno-policies.yaml \
  --resource scripts/d5/jobs/team-a-low-1.yaml --explain
```

期望：合法 Job 的 `d5-gpu-job-policy` 全部 pass。

```bash
kyverno apply scripts/d5/30-kyverno-policies.yaml \
  --resource scripts/d5/jobs/invalid-no-priority.yaml --explain
```

期望：在 priorityClass 那条 fail。

> `kyverno apply` 对 Pod 策略的 `namespaceSelector` 需要 namespace 上下文；离线测试 Job 时，以集群内 `--dry-run=server` 为准。

### 8.5 两条拒绝日志

```bash
mkdir -p results/d5
```

**拒绝 1：缺 queue label**

```bash
kubectl apply -f scripts/d5/jobs/bypass-no-queue.yaml \
  2> results/d5/reject-no-queue.txt || true
cat results/d5/reject-no-queue.txt
```

期望：

```text
Error from server: admission webhook "vpol.validate.kyverno.svc-fail" denied the request:
Policy d5-gpu-job-policy failed: GPU Job must carry label
kueue.x-k8s.io/queue-name=<localqueue>.
```

**拒绝 2：缺 priorityClass**

```bash
kubectl apply -f scripts/d5/jobs/invalid-no-priority.yaml \
  2> results/d5/reject-no-priority.txt || true
cat results/d5/reject-no-priority.txt
```

期望：

```text
Policy d5-gpu-job-policy failed: GPU Job must set
spec.template.spec.priorityClassName to gpu-high or gpu-low.
```

**可选拒绝 3：queue label 指向别的团队**

```bash
kubectl apply --dry-run=server -f scripts/d5/jobs/invalid-wrong-queue.yaml
```

期望：

```text
GPU Job queue label must equal its namespace (team-a -> team-a).
```

### 8.6 `failurePolicy: Fail` 的取舍

- Kyverno admission controller 挂掉时，`failurePolicy: Fail` 会**阻止** GPU Job/Pod 创建；
- 已有工作负载不受影响；
- 对“配额不能绕过”的平台，这通常是正确的 fail-closed；
- 必须排除 `kube-system` 和 `kyverno` namespace，否则 Kyverno 自己起不来时会把集群卡死。

生产上要配 HA（admission controller ≥2 副本）和 webhook 排除。

---

## 9. Lab 4：抢卡、排队、抢占

### 9.1 team A 提交第一个低优先级 Job

```bash
kubectl apply -f scripts/d5/jobs/team-a-low-1.yaml
kubectl get jobs,pods -n team-a -o wide
kubectl get workloads -n team-a -o wide
```

期望：

```text
job/team-a-low-1   Running
pod/team-a-low-1-xxxxx   Running
workload/job-team-a-low-1-xxxxx   team-a   team-a-cq   True
```

节点上唯一一张 GPU 已被占满：

```bash
kubectl describe node | sed -n '/Allocated resources:/,/Events:/p'
# nvidia.com/gpu  Requests 为 1（容量 1，占满）
```

### 9.2 team A 提交第二个 Job → 排队

```bash
kubectl apply -f scripts/d5/jobs/team-a-low-2.yaml
kubectl get jobs,pods -n team-a -o wide
kubectl get workloads -n team-a -o wide
kubectl get clusterqueue team-a-cq
```

期望：

```text
job/team-a-low-2   Suspended
# 没有第二个 Pod
workload/job-team-a-low-2-xxxxx   team-a   <none>   False
team-a-cq   PENDING WORKLOADS: 1
```

看 Workload 条件：

```bash
kubectl get workloads -n team-a -o json | \
  jq '.items[] | {name: .metadata.name, conditions: [.status.conditions[] | {type, status, reason, message}]}'
```

期望看到：

```text
QuotaReserved=False, reason=WaitingForQuota,
message="couldn't assign flavors to pod set main:
insufficient unused quota for nvidia.com/gpu in flavor gpu-3060, 1 more needed"
```

> 这是 **Kueue 排队**，不是 API 拒绝。对象已经创建，只是没有配额。

### 9.3 team B：配额放行，容量 Pending

```bash
kubectl apply -f scripts/d5/jobs/team-b-low-1.yaml
kubectl get jobs,pods -n team-b -o wide
kubectl get workloads -n team-b -o wide
kubectl describe pod -n team-b -l job-name=team-b-low-1 | sed -n '/Events:/,$p'
```

期望：

```text
job.batch/team-b-low-1   Running      # Job 已解除 suspend，Pod 已创建
pod/team-b-low-1-xxxxx   Pending
workload/job-team-b-low-1-xxxxx   team-b   team-b-cq   True
```

确认 `Admitted` 和 `QuotaReserved` 都为 `True`：

```bash
kubectl get workloads -n team-b -o json | \
  jq '.items[] | {name: .metadata.name, conditions: [.status.conditions[] | {type, status, reason}]}'
```

```text
Admitted=True, QuotaReserved=True
```

`describe pod` 的 Events 里应有：

```text
Warning  FailedScheduling  ...  0/1 nodes are available:
1 Insufficient nvidia.com/gpu.
```

**这是单卡实验的核心证据：**

- `Workload` 的 `QuotaReserved=True`、`Admitted=True`：Kueue 的配额账本认为 team B 有 1 张额度；
- `Pod` 是 `Pending`：唯一一张物理卡在 `team-a-low-1` 手里，kube-scheduler 没有容量可分配；
- 所以 **Kueue admission ≠ Pod 调度成功**。`nominalQuota` 是请求上限，不是节点容量。

把三条输出存到 `results/d5/team-b-admitted-pod-pending.txt`：`kubectl get workloads -n team-b -o wide`、`kubectl get pods -n team-b -o wide`、`kubectl describe pod` 的 `FailedScheduling` 事件。

> **口径：** team B 的 Workload 是 `Admitted`，不是 Kueue pending；`kueue_pending_workloads{cluster_queue="team-b-cq"}` 这时是 0。Pod `Pending` 是 kube-scheduler 的事实，不是 Kueue 排队。§10.2 的 metrics 和这里的 Pod 状态不要混。

记录完立即删除，避免它和 §9.4 的高优先级抢占互相干扰；单卡上它也永远等不到卡：

```bash
kubectl delete -f scripts/d5/jobs/team-b-low-1.yaml
kubectl get workloads -n team-b
# 期望：No resources found
```

### 9.4 team A 高优先级 Job → 抢占

先确认 §9.3 的 `team-b-low-1` 已删除，避免它和高优先级抢占互相干扰：

```bash
kubectl get jobs,pods -n team-b
# 期望：No resources found
```

```bash
kubectl apply -f scripts/d5/jobs/team-a-high.yaml
kubectl get jobs,pods -n team-a -o wide
kubectl get workloads -n team-a -o wide
```

期望：

```text
team-a-high    Running
team-a-low-1   Suspended   # 被抢占
team-a-low-2   Suspended   # 仍在排队
workload/team-a-high   Admitted=True
workload/team-a-low-1  Evicted=True, reason=Preempted
```

看条件：

```bash
kubectl get workloads -n team-a -o json | \
  jq '.items[] | select(.status.conditions[]?.type == "Evicted") |
      {name: .metadata.name, conditions: [.status.conditions[] | {type, status, reason, message}]}'
```

期望：

```text
type=Evicted, status=True, reason=Preempted,
message="Preempted to accommodate a workload ... due to prioritization in the ClusterQueue"
```

期间可能看到一条：

```text
Warning FailedScheduling ... Insufficient nvidia.com/gpu
```

这是高优先级 Pod 在低优先级 Pod 还没完全退出时先尝试调度；Kueue 驱逐完成后会重试成功。**不是抢占失败**。

### 9.5 释放高优先级 Job → 低优先级重排

```bash
kubectl delete job team-a-high -n team-a
kubectl get workloads -n team-a -o wide
kubectl get pods -n team-a -o wide
```

期望：team-a-low-1 重新 `Admitted=True` 并 `Running`，team-a-low-2 仍在 pending（因为配额只有 1）。通常 `low-1` 先恢复（它先入队）；若实际顺序不同，记录实际顺序即可，不要为了预期改结果。

**可选收尾：删掉 team-a 全部 Job，验证 team B 能真正 `Running`。**

```bash
kubectl delete jobs -n team-a --all
kubectl apply -f scripts/d5/jobs/team-b-low-1.yaml
kubectl get jobs,pods -n team-b -o wide
```

期望：`team-b-low-1` `Running`，唯一一张 GPU 被 B 占满。这一步证明**配额释放后能跨团队推进**，不是 B 抢了 A 的卡；单卡上仍然无法让两个团队同时 `Running`。

### 9.6 可选：cohort 借用与回收（单卡只演示账本）

先清空 §9.5 的可选收尾 Job，避免旧状态干扰：

```bash
kubectl delete jobs -n team-a --all --ignore-not-found
kubectl delete jobs -n team-b --all --ignore-not-found
```

如果时间够，给两个 CQ 加 cohort：

```yaml
spec:
  cohortName: gpu-pool
  resourceGroups:
    - coveredResources: ["nvidia.com/gpu", "cpu", "memory"]
      flavors:
        - name: gpu-3060
          resources:
            - name: nvidia.com/gpu
              nominalQuota: 1
              borrowingLimit: 1
            # ...
```

并允许回收：

```yaml
preemption:
  withinClusterQueue: LowerPriority
  reclaimWithinCohort: LowerPriority
```

单卡上的演示：

1. team B 空闲，team A 提交 2 个 low Job → 两个 Workload 都 `Admitted`（第二个借了 team B 的额度），但只有一个 Pod `Running`，另一个 Pod `Pending: Insufficient nvidia.com/gpu`。
2. team B 提交 1 个 low Job → B 的 Workload `Admitted`，Kueue 回收额度并驱逐 team A 的一个低优先级 Workload（通常是借额度那个）；但 A 自己的 Workload 仍可能占着唯一物理卡，B 的 Pod 也可能仍 `Pending`。按实际顺序记录。
3. 记录 `kueue_preempted_workloads_total{reason="InCohortReclamation"}`。

**单卡上 cohort 只演示额度借用/回收，不能演示两个团队同时 `Running`。** 这一步讲的是“配额可以弹性，但不能被永久占死”；教学价值低于 §9.3 的 quota vs capacity。**时间不够直接跳过。**

### 9.7 记录模板

| 场景 | team-a Running | team-b Running | Kueue pending | Pod Pending | preempted | 证据 |
|---|---:|---:|---:|---:|---:|---|
| A 提交 2 个 low | 1 | 0 | 1（`team-a-low-2`） | 0 | 0 | `cq-team-a.txt` |
| B 提交 1 个 low | 1 | 0 | 1（仍是 `team-a-low-2`） | 1（`team-b-low-1`） | 0 | `team-b-admitted-pod-pending.txt` |
| 删除 B，A 提交 high | 1（high） | 0 | 1（`team-a-low-2`） | 0 | 1 | `preemption-events.txt` |
| 删除 high | 1（low-1） | 0 | 1（`team-a-low-2`） | 0 | 1（累计） | `workloads-after.txt` |
| 可选：删 A 全部，重提 B | 0 | 1 | 0 | 0 | 1（累计） | `team-b-after-release.txt` |

> `Kueue pending` 只数 `QuotaReserved=False` 的 Workload；team B 的 Workload 是 `Admitted`，不计入这一列。team B 的 Pod `Pending` 单独一列，是 kube-scheduler 的事实。两列同时出现，才是单卡实验要的证据。

### 9.8 本地 kind 已观察到的行为（smoke test，非 Vast 正式结果）

2026-11-25 在本地 kind（K8s 1.34、假 `nvidia.com/gpu=2`）验证的是**机制**；kind 的 2 是 patch 出来的假容量，不是 Vast 单卡结果，单卡正式口径见 §9.3。

- 不带 queue label 的 Job：Pod `Running`，`kubectl get workloads -n team-a` 为空；
- 合法 Job：Workload `QuotaReserved=True`，Job `Resumed`，Pod `Running`；
- 第二个 Job：`QuotaReserved=False`，message 为 `insufficient unused quota for nvidia.com/gpu in flavor gpu-3060, 1 more needed`；
- team B Job：第二张卡被占用，节点 `nvidia.com/gpu 2/2`（kind 假 2 卡）；
- 高优先级 Job：低优先级 Workload 出现 `Evicted=True, reason=Preempted`；
- Kyverno Pod 策略最初误拒 Kueue 创建的 Pod，原因是只认 `queue-name`；改成同时接受 `local-queue-name` 后通过；
- Pod 策略最初被 autogen 生成 Job 规则，导致合法 Job 被误拒；加 `spec.autogen.podControllers.controllers: []` 后解决；
- `suspend: false` 的 Job 没有被 Kyverno 拒，因为 Kueue mutating webhook 先把它改成了 `true`。

这些是 **kind 机制验证**，不是 Vast 单卡结果，也不是性能/容量结论；正式结果仍要在 Vast 上重跑并保存日志。

---

## 10. 观测、审计、chargeback

### 10.1 kubectl 视角

```bash
kubectl get clusterqueue -o wide
kubectl get localqueue -A
kubectl get workloads -A -o wide
kubectl get events -A --sort-by=.lastTimestamp | tail -30
```

关键条件：

```bash
kubectl get workload -n team-a <name> -o yaml
# status.conditions:
#   QuotaReserved
#   Admitted
#   Evicted / Preempted
#   PodsReady
```

### 10.2 Kueue metrics

Kueue metrics 服务默认开在 `8443`，需要 token：

```bash
kubectl create clusterrolebinding d5-kueue-metrics \
  --clusterrole=kueue-metrics-reader \
  --serviceaccount=kueue-system:default

kubectl -n kueue-system port-forward \
  svc/kueue-controller-manager-metrics-service 18443:8443 >/tmp/pf-kueue.log 2>&1 &
PF=$!; sleep 3
TOKEN=$(kubectl create token default -n kueue-system)
curl -sk -H "Authorization: Bearer ${TOKEN}" https://127.0.0.1:18443/metrics \
  | grep -E '^kueue_(pending_workloads|admitted_active_workloads|preempted_workloads_total)'
kill $PF
```

有用的指标：

| 指标 | 用途 |
|---|---|
| `kueue_pending_workloads` | 哪个 CQ 在排队 |
| `kueue_admitted_active_workloads` | 当前跑着的 Workload |
| `kueue_preempted_workloads_total` | 抢占次数，按 `reason` 分 |
| `kueue_quota_reserved_wait_time_seconds` | 排队等了多久 |
| `kueue_cluster_queue_resource_usage` | 可选，需要 `enableClusterQueueResources` |

> §9.3 的 team B 是 `Admitted`，`kueue_pending_workloads` 不会把它算进去；它的 Pod `Pending` 只能从 `kubectl get pods` 和 `FailedScheduling` 事件看到。这是“配额账本”和“调度容量”的分界。

### 10.3 Kyverno metrics / PolicyReport

```bash
kubectl -n kyverno port-forward svc/kyverno-svc-metrics 18000:8000 >/tmp/pf-kyverno.log 2>&1 &
PF=$!; sleep 3
curl -s http://127.0.0.1:18000/metrics \
  | grep 'kyverno_validating_policy_results_total'
kill $PF
```

按策略/结果聚合：

```promql
sum by (policy_name, result) (
  increase(kyverno_validating_policy_results_total[1h])
)
```

**重要：PolicyReport 不是历史审计日志。**

- `validationActions: [Audit]` 的策略会对**现存资源**生成 report；
- `[Deny]` 拒绝的请求对象根本没创建，不会有 report；
- 被拒请求要看 Kyverno metrics、Kubernetes Events、API server audit log。

D5 的拒绝日志用 `kubectl apply 2> file` 保存，这是最直接的证据。

### 10.4 chargeback 公式

```text
team_gpu_hours = Σ (pod_gpu_request × pod_runtime_hours)
team_cost     = team_gpu_hours × $/GPU-hour
```

数据来源：

- `Workload.spec.podSets[].template.spec.containers[].resources.requests["nvidia.com/gpu"]`（与 Pod request 同源）
- Pod 的实际 `status.startTime` / 完成时间（不是 Workload `Admitted` 的时间）
- Pod 标签 `team`、`cost-center`、`kueue.x-k8s.io/local-queue-name`

D5 只演示“标签 + 配额 + 审计”，不做真实账单；生产要接 OpenCost/Kubecost 或自建计量。

特别注意：team B 的 Workload `Admitted` 但 Pod `Pending` 时，GPU-hours 是 **0**。chargeback 按实际 Pod 运行时长（或实际容器占用）算，不按 quota reservation；否则会把排队/等卡算成消费。

### 10.5 审计证据链

| 问题 | 证据 |
|---|---|
| 谁提交的？ | API server audit log 的 user/verb/resource |
| 有没有被准入挡住？ | Kyverno `Forbidden` 响应 + `kyverno_validating_policy_results_total{result="fail"}` |
| 有没有被 Kueue 排队？ | `Workload.status.conditions[QuotaReserved]` |
| 有没有被抢占？ | `Evicted` / `Preempted` condition + `kueue_preempted_workloads_total` |
| 用了多少 GPU 小时？ | Pod 实际运行时长 + request + `team`/`cost-center` 标签（不是 Workload `Admitted` 的时长） |

---

## 11. 故障与运维

### 11.1 故障表

| 故障 | 表现 | 处理 |
|---|---|---|
| Kueue controller 挂了 | 新 Job 保持 `Suspended`；已有 Pod 继续跑 | `kubectl -n kueue-system rollout status deploy/kueue-controller-manager`；看日志 |
| Kueue webhook 挂了 | Job create 报 `InternalError` / webhook timeout | 恢复 controller；webhook 是 fail-closed |
| Kyverno admission 挂了 | `failurePolicy: Fail` 时 GPU Job/Pod 创建被拒；已有负载不受影响 | 恢复 Kyverno；确保排除 `kube-system`/`kyverno` |
| 策略写错 | 所有 GPU Job 被拒 | 先 `kyverno apply --explain` 离线测；回滚策略 |
| `nominalQuota` > 实际 GPU | Kueue 放行，Pod `Pending: Insufficient nvidia.com/gpu` | 配额按真实 allocatable 配；配额不是容量（D5 是故意超卖，见 §9.3） |
| 抢占循环 | 低优先级 Job 反复被驱逐 | 调整 priority/队列；用 cohort 借用限制；避免同优先级互相抢 |
| Pod 被 Pod 策略误拒 | Job 创建了但 Pod 创建失败 | 检查 Pod 策略是否接受 `local-queue-name`；关闭 autogen |
| `ClusterQueue` 删不掉 | finalizer `resource-in-use` | 先删 Job/Workload，再删 LocalQueue/CQ |

### 11.2 排障顺序

```text
1. kubectl get job -n <ns>                 # 对象存在吗？
2. kubectl get events -n <ns>              # Kyverno 拒绝？调度失败？
3. kubectl get workloads -n <ns> -o wide   # 有 Workload 吗？QuotaReserved？
4. kubectl describe clusterqueue <cq>      # 配额满了吗？pending 多少？
5. kubectl get pods -n <ns> -o wide        # Pod 创建了吗？Running？
6. kubectl describe node | grep nvidia     # 节点还有 GPU 吗？
7. kubectl -n kueue-system logs deploy/kueue-controller-manager
8. kubectl -n kyverno logs deploy/kyverno-admission-controller
```

### 11.3 生产 hardening

- **RBAC**：团队只能在自身 namespace 创建 Job/Pod；不能改 ClusterQueue。
- **Kyverno HA**：admission controller ≥2 副本；排除系统 namespace。
- **Kueue HA**：leader election + 多副本；监控 webhook。
- **配额**：生产上 `nominalQuota` 按真实 GPU 数配，给系统组件留余量；D5 故意让两个 CQ 各 1、合计 2 > 物理 1，只为演示 quota ≠ capacity，不要照抄。
- **审计**：开 API server audit log；保留 Kyverno/Kueue metrics；定期导出 Workload 快照。
- **例外**：用 `PolicyException` 做 break-glass，设置过期时间和审批。
- **控制面优先级**：给 Kyverno/Kueue 设置 `system-cluster-critical` 或专用高优先级。否则 GPU Job 的 `gpu-high` 可能抢占控制面 Pod，导致 webhook 短暂不可用（本地 kind 2 CPU 时实测过）。
- **节点隔离**：生产最好把控制面和 GPU workload 分节点池，避免 CPU/内存争抢。
- **GitOps**：策略和 quota 都进 git；禁止手改生产 ClusterQueue。

### 11.4 模型版本回滚（B 线问法）

D5 的配额层不关心模型版本，但回滚时容易踩两个坑：

1. **Deployment 回滚不会改 Kueue 配额**：`kubectl rollout undo deploy/vllm -n team-a` 只换镜像；配额仍是 team-a-cq 的 1 GPU。
2. **新版本可能缺标签/优先级**：如果新 Deployment 的 Pod template 没带 queue label/priorityClass，Kyverno 会拒绝它的 Pod。回滚前先确认模板仍满足策略。

对批处理 Job：Job 不可变，回滚 = 用同样的 queue label/priority 重新提交一个 Job，而不是改旧 Job。

---

## 12. 成本、清理、验收

### 12.1 成本

| 项 | 金额 |
|---|---|
| 单卡 VM 实时单价 | **执行时填**（`$____/h`） |
| 3h 实验 + 0.5h buffer | **执行时填**（`$____`） |
| 合计（约 3.5h） | **执行时填** |

执行后把 Vast 实际账单写进 `results/d5/cost.txt`；不要用估算替代实际账单，也不要沿用 D4 的旧金额。

### 12.2 清理顺序

**先删 Kueue 对象，再卸载 Kueue**，否则 finalizer 会让对象卡在 `Terminating`：

```bash
# 1. 删 Job（会带走 Workload）
kubectl delete jobs -n team-a --all
kubectl delete jobs -n team-b --all

# 2. 检查残留 Workload
kubectl get workloads -A
# 有就删：kubectl delete workload -n <ns> <name>

# 3. 按 Kueue 文档顺序删：LocalQueue -> ClusterQueue -> ResourceFlavor
kubectl delete localqueue -n team-a team-a --ignore-not-found
kubectl delete localqueue -n team-b team-b --ignore-not-found
kubectl delete clusterqueue team-a-cq team-b-cq --ignore-not-found
kubectl delete resourceflavor gpu-3060 --ignore-not-found
# 兜底：kubectl delete -f scripts/d5/20-kueue.yaml

# 4. 删 Kyverno（Helm 不会删 cluster-scoped CRD；复用集群时另删）
helm uninstall kyverno -n kyverno
kubectl delete namespace kyverno --ignore-not-found

# 5. 删 Kueue
kubectl delete -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.20.7/manifests.yaml

# 6. 删 namespace / PriorityClass
kubectl delete -f scripts/d5/00-namespaces.yaml
kubectl delete -f scripts/d5/10-priorityclasses.yaml

# 7. 删 metrics RBAC
kubectl delete clusterrolebinding d5-kueue-metrics --ignore-not-found
```

最后 `scp` 结果（IP/端口按当时实例替换），再 `vastai destroy instance <ID> -y`：

```bash
scp -i ~/.ssh/id_ed25519 -P <PORT> -r \
  root@<HOST>:/root/llm-inference-platform-lab/results/d5/. results/d5/
# 或从本地 repo 直接打包；确保 results/d5/ 已 commit + push
```

### 12.3 结果目录

```text
results/d5/
  summary.md
  machine.txt                     # nvidia-smi 型号/显存、driver、k3s、kubectl 版本
  reject-no-queue.txt
  reject-no-priority.txt
  reject-wrong-queue.txt          # 可选
  cq-team-a.txt
  cq-team-b.txt
  workloads-team-a.txt
  workloads-team-b.txt
  node-allocated.txt
  team-b-admitted-pod-pending.txt # Workload Admitted + Pod Pending 的三条证据
  preemption-events.txt
  team-b-after-release.txt        # 可选：删 A 全部后 B Running
  kueue-metrics.txt
  kyverno-metrics.txt
  cost.txt
```

### 12.4 验收清单

- [ ] `nvidia.com/gpu=1`；`nvidia-smi` 型号/显存、Kueue/Kyverno/k3s 版本进 `machine.txt`
- [ ] 两条 Kyverno 拒绝日志（缺 queue label、缺 priorityClass）
- [ ] 无 label Job 绕过配额的证据（装 Kyverno 前）：Pod Running + 0 Workload
- [ ] team A 2 个 Job → 1 Running + 1 `QuotaReserved=False`；保存 Workload 条件快照
- [ ] team B 1 个 Job → Workload `Admitted=True` / `QuotaReserved=True` + Pod `Pending: Insufficient nvidia.com/gpu`；保存 `kubectl get workloads`、`kubectl get pods`、`FailedScheduling` 事件
- [ ] 记录完 team B 后删除 `team-b-low-1`，再做抢占，避免干扰
- [ ] 高优先级抢占：低优先级 Workload `Evicted=True, reason=Preempted`
- [ ] 删除 high 后 `team-a-low-1` 重新 `Admitted` 并 Running；可选：删 team A 全部后 team B Running
- [ ] `kueue_preempted_workloads_total` 或 event 证据（team B 的 Pod Pending 不计入 `kueue_pending_workloads`）
- [ ] `results/d5/` 进 git
- [ ] VM Destroy，成本记录

### 12.5 B 线简历 bullet

> 用 Kueue `ClusterQueue` 给两个团队各 1 张 GPU 配额（单卡集群上两个队列合计 2 > 物理 1，故意超卖），Kyverno `ValidatingPolicy` 在 API 入口强制 GPU Job 带 queue label 和 priorityClass；演示了 team A 提交 2 个 Job 只能跑 1 个、team B 被 Kueue 放行（`Admitted`）但 kube-scheduler 因 `Insufficient nvidia.com/gpu` 让 Pod `Pending`，证明 quota 与 capacity 分离；高优先级抢占低优先级并在释放后恢复；留下 2 条拒绝日志和 1 条 `Preempted` condition。

---

## 13. 面试问答（D5 版）

**Q1：Kueue 和 HPA/KEDA 怎么分工？**

Kueue 管批处理 Job 的准入/排队/抢占，决定“能不能开始”；HPA/KEDA 管长期服务副本数，决定“同时跑几个”。两者都不加节点；节点扩容靠 Cluster Autoscaler/Karpenter。

**Q2：怎么防止一个团队抢光 GPU？**

三层：RBAC 限制 namespace；Kyverno 强制 GPU workload 带 queue label/priority；Kueue `ClusterQueue` 的 `nominalQuota` 卡上限。没有 cohort/borrowing 时是硬隔离；有 cohort 时用 `borrowingLimit`/`lendingLimit` 限制借用。

**Q3：Kueue 挂了会怎样？**

新 Job 会保持 `Suspended`，已有 Pod 继续跑；不会突然把所有负载杀掉。恢复 controller 后 Workload 继续调度。Kueue webhook 挂了则 Job 创建可能直接失败（fail-closed）。

**Q4：Kyverno 挂了会怎样？**

`failurePolicy: Fail` 时，匹配的 GPU Job/Pod 创建会被拒绝；已有负载不受影响。对“配额不能绕过”的平台这是可接受的 fail-closed；要配 HA 并排除系统 namespace。

**Q5：配额为什么不是容量？**

Kueue 只看 Pod requests，不看节点实际 allocatable。D5 里两个 CQ 各 `nominalQuota: 1`、集群只有 1 张卡，Kueue 仍会放行 team B 的 Workload，但 kube-scheduler 只能让一个 Pod `Running`，另一个 `Pending: Insufficient nvidia.com/gpu`。配额是策略上限，容量是节点事实。

**Q6：为什么 Kueue 默认管不到不带 label 的 Job？**

Kueue 用 `kueue.x-k8s.io/queue-name` 做 opt-in，避免误管系统 Job。没有 label 就不创建 Workload，Job 直接走 kube-scheduler。补法：Kyverno 强制 label，或 `manageJobsWithoutQueueName: true`。

**Q7：怎么证明平台没被滥用？**

API audit log（谁提交了什么）+ Kyverno metrics/events（谁被拒）+ Kueue Workload conditions/metrics（谁排队/被抢占）+ `team`/`cost-center` 标签（chargeback）。PolicyReport 只反映现存资源，不是历史审计。

**Q8：模型版本回滚怎么做？**

Deployment 用 `kubectl rollout undo`；回滚前确认新 Pod template 仍带 queue label/priorityClass，否则 Kyverno 会拒绝。批处理 Job 不可变，回滚是重新提交 Job。

**Q9：为什么 Kyverno 1.20 用 CEL，不用旧 ClusterPolicy？**

旧引擎在 1.20 停止执行，create/update 被拒；CEL 与 K8s 原生 VAP 同语言，有编译期类型检查、`--explain` 调试和更好的可维护性。简单 pattern 旧语法更短，但复杂条件 CEL 更清楚。

**Q10：多租户还缺什么？**

RBAC、NetworkPolicy、Pod Security Admission、镜像签名、节点隔离/taint、审计日志、配额外的成本监控。D5 只覆盖“配额 + 准入 + 审计”这一层。

**Q11：只有一张卡，怎么证明多团队配额？**

一张卡反而把问题讲得更干净，因为配额和容量被迫分开：

1. **配额是账本**：两个 ClusterQueue 各 `nominalQuota: 1`，合计 2 > 物理 1。Kueue 按账本放行，不按 `nvidia-smi` 的卡数放行。
2. **team A 的边界**：team A 提交 2 个 Job，只有 1 个 `Admitted` / Running，另一个 `QuotaReserved=False`，说明同一团队的配额上限生效。
3. **team B 的 `Admitted` + Pod `Pending`**：team B 提交 1 个 Job，Workload `Admitted=True` / `QuotaReserved=True`，但 Pod `Pending: Insufficient nvidia.com/gpu`。这同时证明两件事：B 的配额没有被 A 吃掉；Kueue 的 admission 不等于 kube-scheduler 的容量。
4. **抢占**：team A 高优先级 Job 让低优先级 Workload 出现 `Evicted=True, reason=Preempted`，高优先级 Running；删掉 high 后 low-1 重新 `Admitted`。
5. **释放后跨团队**：删掉 team A 全部 Job 再提交 B，B 真正 Running，证明配额和物理卡都能回收。
6. **边界**：单卡不能证明两个团队同时 Running，那需要 2 张物理卡；但“B 被 Kueue 放行、Pod 仍 Pending”恰好是 quota vs capacity 最有说服力的证据，比每个团队各跑一个更能说明 Kueue 管什么、不管什么。

如果追问“这是不是配置错误”：D5 是**故意超卖**；生产上 `nominalQuota` 总和不应超过 allocatable，或者用 cohort/borrowing 明确借用上限。

---

## 14. 与 D3/D4/D6 的衔接

| 文档 | 关系 |
|---|---|
| `d3-k8s-vllm-learning.md` | VM/k3s/device plugin/驱逐；D5 复用其 §5.0–§5.4 |
| `d4-llm-d-learning.md` | 多副本路由；D5 是“多团队配额”，不是路由 |
| `d4.6-tiered-cache-lab.md` | KV 分层；和 D5 无关，但同属平台优化 |
| `d6-kserve-observability.md` | KServe 服务抽象 + 推理可观测性（D6a/D6b）；D5 的配额/准入发生在 serving 之前 |

**一句话串起来：**

> D3 证明“能把 vLLM 放进 K8s 并优雅扩缩”，D4 证明“多副本时路由能降 P99”，D5 证明“多团队时配额和准入能防止抢卡，而且配额不等于物理容量”，D6 证明“服务抽象能交付、指标能解释故障”；四者合起来才是“GPU 平台”，而不是“一个能跑的 Pod”。

---

## 15. Sources

- Kueue 安装（v0.20.7）：<https://kueue.sigs.k8s.io/docs/getting-started/installation/>
- Kueue `ClusterQueue`：<https://kueue.sigs.k8s.io/docs/concepts/cluster_queue/>
- Kueue `Workload` 与 priority：<https://kueue.sigs.k8s.io/docs/concepts/workload/>
- Kueue `WorkloadPriorityClass`：<https://kueue.sigs.k8s.io/docs/concepts/workload_priority_class/>
- Kueue cohort：<https://kueue.sigs.k8s.io/docs/concepts/cohort/>
- Kueue Deployment integration（Pod-based）：<https://kueue.sigs.k8s.io/docs/tasks/run/deployment/>
- Kueue 抢占：<https://kueue.sigs.k8s.io/docs/concepts/preemption/>
- Kueue v1beta2 API：<https://kueue.sigs.k8s.io/docs/reference/kueue.v1beta2/>
- Kueue labels/annotations：<https://kueue.sigs.k8s.io/docs/reference/labels-and-annotations/>
- Kueue metrics：<https://kueue.sigs.k8s.io/docs/reference/metrics/>
- Kyverno 1.20 发布说明（legacy 移除）：<https://kyverno.io/blog/2026/11/12/announcing-kyverno-release-1.20/>
- Kyverno 安装：<https://kyverno.io/docs/installation/installation/>
- Kyverno `ValidatingPolicy`：<https://kyverno.io/docs/policy-types/validating-policy/>
- Kyverno `MutatingPolicy`：<https://kyverno.io/docs/policy-types/mutating-policy/>
- CEL 语言规范：<https://github.com/google/cel-spec>
- Kubernetes CEL 文档：<https://kubernetes.io/docs/reference/using-api/cel/>
- Kyverno CEL 库：<https://kyverno.io/docs/policy-types/cel-libraries/>
- Kyverno Policy Reports：<https://kyverno.io/docs/guides/reports/>
- Kyverno metrics：<https://kyverno.io/docs/reference/metrics/>
- k3s v1.37.2+k3s1：<https://github.com/k3s-io/k3s/releases/tag/v1.37.2%2Bk3s1>
- Kueue v0.20.7：<https://github.com/kubernetes-sigs/kueue/releases/tag/v0.20.7>
- Kyverno v1.20.0：<https://github.com/kyverno/kyverno/releases/tag/v1.20.0>
- D3 文档（VM/k3s/device plugin）：[`d3-k8s-vllm-learning.md`](./d3-k8s-vllm-learning.md)
- 本 lab 脚本：[`scripts/d5/`](./scripts/d5/)
