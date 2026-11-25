# scripts/d5 — Kueue 配额 + Kyverno CEL 准入

配合 [`d5-kueue-kyverno-lab.md`](../../d5-kueue-kyverno-lab.md) 使用。D5 是控制面实验：
GPU 只是被 Job 占位，不需要下载模型或起 vLLM。

## 文件

| 文件 | 作用 |
|---|---|
| `00-namespaces.yaml` | `team-a` / `team-b` 两个租户 namespace，带 `gpu-pool: d5` 标签 |
| `10-priorityclasses.yaml` | `gpu-high` / `gpu-low` 两个 Kubernetes `PriorityClass` |
| `20-kueue.yaml` | `ResourceFlavor`、两个 `ClusterQueue`、两个 `LocalQueue` |
| `30-kyverno-policies.yaml` | 两个 `ValidatingPolicy` + 一个 `MutatingPolicy`（`policies.kyverno.io/v1`） |
| `jobs/team-a-low-1.yaml` | team A 低优先级，合法 Job，应被 Kueue 接纳 |
| `jobs/team-a-low-2.yaml` | team A 第二个低优先级 Job，应因配额排队 |
| `jobs/team-a-high.yaml` | team A 高优先级 Job，应抢占低优先级 |
| `jobs/team-b-low-1.yaml` | team B 低优先级，合法 Job，应拿第二张卡 |
| `jobs/bypass-no-queue.yaml` | 故意不带 queue label；装 Kyverno 前会绕过配额运行，装后被拒 |
| `jobs/invalid-no-priority.yaml` | 有 queue label、无 `priorityClassName`，应被 Kyverno 拒 |
| `jobs/invalid-wrong-queue.yaml` | queue label 指向别的团队，应被 Kyverno 拒 |
| `jobs/probe-suspend.yaml` | `suspend: false` 探针；Kueue mutating webhook 会先改成 true，用来讲 admission 顺序 |

## 执行顺序

```bash
# 0. Kueue / Kyverno 已安装，namespace / quota 已创建
kubectl apply -f scripts/d5/00-namespaces.yaml
kubectl apply -f scripts/d5/10-priorityclasses.yaml
kubectl apply -f scripts/d5/20-kueue.yaml

# 1. 先证明 Kueue 的盲区（装 Kyverno 前）
kubectl apply -f scripts/d5/jobs/bypass-no-queue.yaml
kubectl get pods -n team-a
kubectl get workloads -n team-a
kubectl delete -f scripts/d5/jobs/bypass-no-queue.yaml

# 2. 装 Kyverno + CEL 策略
kubectl apply -f scripts/d5/30-kyverno-policies.yaml
kubectl get vpol,mpol

# 3. 抢卡 / 排队 / 抢占
kubectl apply -f scripts/d5/jobs/team-a-low-1.yaml
kubectl apply -f scripts/d5/jobs/team-a-low-2.yaml
kubectl apply -f scripts/d5/jobs/team-b-low-1.yaml
kubectl apply -f scripts/d5/jobs/team-a-high.yaml

# 4. 两条拒绝日志
kubectl apply -f scripts/d5/jobs/bypass-no-queue.yaml 2> results/d5/reject-no-queue.txt || true
kubectl apply -f scripts/d5/jobs/invalid-no-priority.yaml 2> results/d5/reject-no-priority.txt || true

# 5. 快照
kubectl get clusterqueue -o wide
kubectl get workloads -A -o wide
kubectl describe node | sed -n '/Allocated resources:/,/Events:/p'
```

## 依赖

- Kubernetes ≥ 1.34（Kueue 0.20 与 Kyverno 1.20 的要求）
- Kueue `v0.20.7`，API `kueue.x-k8s.io/v1beta2`
- Kyverno `1.20.0`，API `policies.kyverno.io/v1`
- 2 张 GPU（`nvidia.com/gpu=2`），或本地 kind 用假容量预演

## 本地 kind 预演（可选，零成本）

kind 节点默认没有 GPU，可以临时 patch allocatable 做控制面彩排：

```bash
kind create cluster --name d5 --image kindest/node:v1.34.0
kubectl patch node d5-control-plane --subresource=status --type=merge \
  -p '{"status":{"capacity":{"nvidia.com/gpu":"2"},"allocatable":{"nvidia.com/gpu":"2"}}}'
```

这只验证 Kueue/Kyverno 的 admission、quota、preemption 逻辑，**不能**证明真实 GPU 调度或性能。
正式结果仍要在 Vast 2×RTX 3060 VM 上跑。

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `failed calling webhook ... connection refused` | Kueue/Kyverno webhook 还没 ready | 等 `endpoints` 出现，或 10–20s 后重试 |
| Kyverno admission Pod `Pending`（kind） | kind 默认 2 CPU，被占位 Job 吃满 | 停掉 Job、给控制面高优先级，或用更大节点 |
| Kueue 创建的 Pod 被 Pod 策略拒 | Pod 只有 `local-queue-name`，没有 `queue-name` | Pod 策略同时接受两个 label |
| 合法 Job 被 Pod 策略误拒 | Pod 策略的 autogen 生成了 Job 规则 | `spec.autogen.podControllers.controllers: []` |
| `suspend: false` 没被拒 | Kueue mutating webhook 先改成 `true` | 不要用 validating policy 检查会被改写的字段 |

## 注意

- `ValidatingPolicy` 的 `validations[].expression` 必须返回 `bool`；`true` = 通过。
- `MutatingPolicy` 的 `JSONPatch` 用来加 `cost-center`，因为 `ApplyConfiguration` 的对象字面量不能直接写带连字符的 key。
- Pod 策略显式关闭了 autogen：`spec.autogen.podControllers.controllers: []`。否则 Kyverno 会从 Pod 规则自动生成 Job 规则，而 Job 的 queue label 在 `metadata.labels`，不在 Pod template 里，会误报。
- Kueue 给 Pod 加的是 `kueue.x-k8s.io/local-queue-name`，不是 `queue-name`；Pod 策略两个都接受。
- Kyverno 1.20 不再执行 `kyverno.io/v1 ClusterPolicy`；不要从旧教程复制。
