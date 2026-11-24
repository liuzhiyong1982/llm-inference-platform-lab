# D4 学习文档：llm-d 前缀感知路由（2×L4）

> 状态：**planned（2026-11-24）**。本文按 `ai-cloud-native-week-plan.md` 的 D4 行准备：**4h、2×L4、跑一条 llm-d Well-Lit Path、对比 round-robin vs EPP 的 P99、留下命中率数字和 B 线故障表**。文档、manifest、benchmark 脚本已就绪，**尚未租 VM 执行**；所有“实测”表都是待填模板。
>
> 计划位置：`ai-cloud-native-week-plan.md` 的 **D4（llm-d 日）** 与 **Q2（Gateway/路由）**；B 线学习表见该文件 §3，llm-d 四问见 §6。
>
> 性质：学习文档 + 可执行 lab。D1/D2 回答“单机多快”，D3 回答“放进 K8s 后启动/扩容/驱逐要多少秒”，D4 回答“**多副本时，把请求送到已经缓存了这段前缀的副本，P99 能好多少；这套路由组件挂了怎么办**”。
>
> 硬约束：**不在共享 UAT 集群 `uat-mobility-aks-01` 上做实验**。用 Vast.ai 租的 2×L4，on-demand；同机、同模型、同输入/输出长度、同 SLO，只改路由策略。
>
> 版本基线：llm-d `v1.0.0`、Gateway API Inference Extension `v1.6.2`、vLLM `v0.34.0`（以 `--help` 为准）、KEDA `2.21.1`（只用于 Lab 0）。

---

## 0. 先看结论（执行前先记住）

1. **D4 的主菜是 llm-d，不是 Lab 0。** Lab 0（KEDA HTTP Add-on）只解决“0 副本时请求怎么进来”；llm-d 解决“多副本时按 prefix cache 怎么路由”。4h 不够就砍 Lab 0，保 Lab 1。
2. **路由只在多副本时存在。** 1 个 vLLM 进程没有路由问题；D4 的收益完全建立在 D3 的 2 副本之上。
3. **llm-d 1.0 的 precise routing 不是“猜前缀”。** vLLM 通过 ZMQ 上报 KV block 事件，EPP 建精确索引；每个请求先 tokenize/render，再查索引。需要 `--kv-events-config`、`/v1/*/render`、`--block-size=64` 与 `blockSizeTokens: 64` 对齐。
4. **2×L4 跑不了 guide 默认配置。** guide 默认 Qwen3-32B、TP=2、2 副本 = 4×H100。我们改成 Qwen3-8B-AWQ、TP=1、2 副本 = 2×L4；模型名、`peakPrefillThroughput`、绝对数字都不能照抄。
5. **主对比是 Service round-robin vs EPP precise。** 可选 EPP random 作为控制组，隔离 Envoy/EPP 的固定开销；`direct` / `precise` 各跑 3 次，`random` 时间够就 3 次，取中位数。
6. **EPP 单副本是有意为之。** precise 的 in-flight token 记账和 KV 索引是进程本地的；D4 不跑 active-active。生产 HA 需要共享状态/索引快照，先作为面试追问。
7. **交付物不是“跑通了”。** 一张 P99 对比图、命中率、每 Pod 请求分布、故障表、成本；缺一项不算 D4 完成。

---

## 1. 按计划定义 D4

### 1.1 计划里的 D4 要求

| 计划要求 | 本文对应 | 产出 |
|---|---|---|
| 4h、2×L4 | §3、§10.5 | 时间盒 + 资源规划 |
| 按 Well-Lit Path 跑 `precise-prefix-cache-routing`（或 optimized baseline） | §5 | 可执行步骤 + fallback |
| 同一批“共享长前缀”的请求，对比普通 round-robin vs EPP 的 P99 | §6 | 3 个 arm、固定 workload、JSON |
| 一张 P99 对比图 + 命中率数字 | §6.6、§6.8 | `d4-ttft.png` + hit rate 表 |
| B 线：Gateway/`InferencePool`/EPP 运维图 + 路由故障表 | §7 | 图 + 表 |
| 方法学必须一起写 | §6.4 | 样本、warmup、重复、开环/闭环、SLO、单价、货币 |
| llm-d 四问 | §8 | EPP / InferencePool / PD / wide EP |

### 1.2 D4 不做什么

按计划的“不要做的三件事”和 4h 预算：

- **不读 production-stack**：它是给已有集群的人看的；D3/D4 已经够用。
- **不把 10 条 Well-Lit Path 都看一遍**：只跑 precise；optimized baseline 只作为 fallback。
- **不在 vLLM quickstart 没跑通时碰 llm-d**：本 lab 的模型服务器就是 vLLM 的最小验证。
- **不跑 PD 分离、wide EP、多模型**：只看概念，不进验收。
- **不装生产 Gateway**（Istio / Envoy Gateway / agentgateway）：D4 用 standalone + `InferencePool` 足够；Gateway Mode 只给 YAML 和面试讲法。
- **不在 `uat-mobility-aks-01` 上跑任何东西**。

### 1.3 和 D3 的衔接

D4 不是从零开始，它直接用 D3 的集群和结论：

| D3 的结果 | D4 怎么用 |
|---|---|
| 2 副本、每副本 1 GPU | 路由的前提；单副本没有 EPP 收益 |
| 冷启动约 116s（HPA 决策→Ready） | D4 不重复测冷启动；EPP 0→1 仍受这个时间约束 |
| `preStop 15s` + `--shutdown-timeout=45` + grace 120s | D4 的模型服务器沿用；滚动更新时在途请求可排空 |
| KEDA 按队列扩缩 | Lab 0 的 0→1 入口；D4 主实验把 `minReplicaCount` 保持在 1 |
| 单卡 1→2 Pending | D4 用 2 张卡，两个副本各 1 张；不测 Pending |

> 换句话说：D3 证明“副本能起来、能扩、能优雅退出”；D4 证明“多副本时请求该去哪一个”。两者不是重复实验。

---

## 2. 架构

### 2.1 Lab 0（可选）：request-driven 0→1

```text
curl / 业务客户端
  → Service vllm-qwen3-8b-proxy（ExternalName）
  → KEDA HTTP Add-on interceptor（keda namespace）
  → 匹配 InterceptorRoute
  → 后端 0 副本：hold request，上报 concurrency
  → KEDA ScaledObject（external-push）
  → HPA keda-hpa-vllm-http
  → Deployment vllm-qwen3-8b: 0 → 1
  → Pod Ready 后 interceptor 转发
  → vLLM 返回 /v1/models 或 /v1/completions
```

Lab 0 解决的是“**0 副本时请求怎么进来**”，不是“多副本时怎么选副本”。两者可以叠加，但不是同一个问题。

### 2.2 Lab 1（主菜）：precise prefix-cache routing

```text
client（d4-bench Pod）
  → Service d4-router-epp:80（Envoy sidecar）
  → ext_proc → EPP
      ├─ token-producer：向一个 Ready 的 vLLM POST /v1/completions/render
      ├─ precise-prefix-cache-producer：查 KV block 索引
      │    ← ZMQ 5556（事件）/ 5559（replay），由每个 vLLM Pod 上报
      ├─ prefix-cache-affinity-filter：把同一前缀组留在 cache-warm 的 Pod
      └─ token-load-scorer：在候选中选 in-flight token 最少的
  → Envoy 转发到选中的 vLLM Pod:8000
  → 响应流式返回

EPP 不可用 + FailOpen：
  Envoy → headless Service（<release>-epp-model-servers）→ 两个 vLLM Pod
```

### 2.3 一次请求经过什么

1. 客户端把 OpenAI 兼容请求发到 `d4-router-epp:80`（Envoy）。
2. Envoy 的 ext_proc 把请求头和 body 交给 EPP。
3. EPP 解析请求；`token-producer` 把 prompt 发到某个 Ready vLLM 的 `/v1/completions/render`，拿到**精确 token IDs**。
4. `precise-prefix-cache-producer` 用 token IDs 查索引：哪些 Pod 的 KV cache 里有这段前缀。
5. `prefix-cache-affinity-filter` 保留 cache-warm 的候选；`token-load-scorer` 在候选中选负载最低的。
6. Envoy 把请求转发到选中的 Pod；响应流式返回。
7. vLLM 在 KV block 分配/驱逐时发 ZMQ 事件；EPP 更新索引。

### 2.4 组件表

| 组件 | 作用 | 挂了会怎样 |
|---|---|---|
| Envoy sidecar | 数据面；ext_proc 调 EPP；转发/流式响应 | Pod 不 Ready；Service 没有 endpoint |
| EPP | 解析、tokenize、查索引、过滤/打分、选 Pod | FailOpen 时绕过 EPP；FailClose 时 503 |
| `InferencePool` | 声明“哪些 Pod 是模型服务器、端口是多少、EPP 是谁” | EPP 没有 endpoint；路由不到 |
| `token-producer` | 调 vLLM `/v1/*/render`，拿精确 token IDs | render 失败→无 cache 信息，仍可路由 |
| `precise-prefix-cache-producer` | 订阅 ZMQ KV 事件，建 block 索引 | 索引为空→退化成无 cache 感知 |
| `prefix-cache-affinity-filter` | 把前缀组留在 cache-warm Pod；过热时扩散 | 命中率下降；P99 变差 |
| `token-load-scorer` | 选 in-flight token 最少的候选 | 负载不均；热点 |
| vLLM | 推理、prefix caching、KV 事件、render 端点 | 请求失败/重试；EPP 摘除 endpoint |

---

## 3. 环境、版本、预算

### 3.1 机器规格

| 项 | 要求 | 说明 |
|---|---|---|
| GPU | **2×L4 24GB** | 两个副本各 1 张；和 D1/D2 同型号，便于解释 |
| CPU / RAM | ≥16 vCPU / 64GB | 2×vLLM + EPP + Envoy + bench 客户端 |
| 磁盘 | ≥130GB | 镜像 ~10GB + 权重 5.7GB + 结果/日志 |
| 平台 | Vast.ai **on-demand VM** | 不要 interruptible；不要普通容器 |
| 网络 | 同机、同 CNI | 客户端和 vLLM 同集群，避免公网变量 |
| power limit | 记录 `nvidia-smi -q -d POWER` | L4 可能是 72W 或限功耗；和 D1 的 40W 不可直接比 |

> 如果只有 1 张 L4，D4 不成立：没有第二个副本就没有路由问题。至少 2 张；2×L4 足够。
>
> **Vast 实况（2026-11-24）：** L4 VM 不一定有货；如果没有，**2×4090 VM 是可接受的 fallback**，但结果里必须写明显卡型号，不能标成 L4。2 卡 VM 的创建失败率比单卡高（D3 实测过 `created`/SSH 拒绝），优先 `verified`、`R ≥ 0.99`、`Net_down ≥ 500`、64GB RAM、130GB disk 的 host；创建后先 `nvidia-smi` 确认两张卡都在，再开始装 k3s。

### 3.2 和 llm-d guide 默认配置的差异

| 项 | guide 默认 | D4 | 影响 |
|---|---|---|---|
| 模型 | `Qwen/Qwen3-32B` | `Qwen/Qwen3-8B-AWQ` | 权重 5.7GB，24GB L4 放得下 |
| TP | 2 | 1 | 每个副本 1 张卡 |
| 副本 | 2 | 2 | 共 2 张卡 |
| GPU | 4×H100 80GB | 2×L4 24GB | **绝对数字不可比** |
| `modelName` | `Qwen/Qwen3-32B` | `qwen3-8b` | 必须等于 `--served-model-name` |
| `peakPrefillThroughput` | 15926（H100/Qwen3-32B） | 用 calibration 重测 | 不重测就相当于关掉 saturation gate |
| 请求长度 | guide 示例 ~2k 前缀 | 1100 words ≈ 1.5k tokens | 按 L4 KV 容量设计 |

> 这张表是面试时要主动说的：**“我跑的是同一条 Well-Lit Path，但不是同一个参考配置；所以我的 P99 只和同机的 round-robin 比，不和 llm-d 公布的 H100 数字比，也不和 D1/D2 的 40W L4 比。”**
>
> 也正因为默认配置是 4×H100，**D4 不按 Quickstart 的默认 manifest 跑**（那会直接 Pending）；直接用 §5.3 的 2×L4 适配 manifest，把 2h 的默认部署时间省给主实验。Quickstart 只读它的请求路径和 CRD 安装顺序。

### 3.3 资源规划

| 组件 | requests | limits | 备注 |
|---|---|---|---|
| vLLM ×2 | 4 CPU / 16Gi / 1 GPU | 8 CPU / 24Gi / 1 GPU | `--gpu-memory-utilization=0.90` |
| EPP | 2 CPU / 4Gi | 8Gi | 单副本 |
| Envoy | 1 CPU / 1Gi | 2Gi | sidecar |
| bench 客户端 | 2 CPU / 4Gi | 4 CPU / 8Gi | 不用 GPU |
| 合计 requests | ~13 CPU / ~41Gi | — | 16 vCPU / 64GB 够 |

### 3.4 版本矩阵与预检

| 组件 | 版本 | 预检 |
|---|---|---|
| k3s | D3 同版本 | `kubectl version` |
| NVIDIA driver | 记录 | `nvidia-smi`；`nvidia.com/gpu` allocatable=2 |
| vLLM | `v0.34.0` | `vllm serve --help` 确认 `--enable-scale-out`、`--kv-events-config`、`--block-size` |
| llm-d | `v1.0.0` | `helm show chart oci://ghcr.io/llm-d/charts/llm-d-router-standalone --version v1.0.0` |
| GAIE CRDs | `v1.6.2` | `kubectl get crd inferencepools.inference.networking.k8s.io` |
| KEDA | `2.21.1` | 仅 Lab 0 |
| KEDA HTTP Add-on | `0.16.x` | 仅 Lab 0；`HTTPScaledObject` 已 deprecated |

**vLLM flag 漂移是最大的时间坑。** 先跑：

```bash
kubectl run vllm-help --rm -i --restart=Never -n default \
  --image=vllm/vllm-openai:v0.34.0 -- \
  vllm serve --help | grep -E 'enable-scale-out|kv-events-config|block-size|enable-prefix-caching|shutdown-timeout'
```

如果 `--enable-scale-out` 不存在，先确认该版本的 `/v1/*/render` 是否默认开启；如果不存在，直接走 §5.10 的 optimized baseline fallback，不要在现场改 llm-d 源码。

### 3.5 预算

2×L4 on-demand 约 `$0.55–0.70/h`（含 130GB 存储，按 Vast 实时报价为准）；4h 实验 + 1h 安装/排障 ≈ **`$3.0–3.5`**。D3 后余额约 `$14.81`，D4 后约 `$11.3`。记录实付，Destroy 前以 Vast 账单为准。

---

## 4. Lab 0（前置，可选）：KEDA HTTP Add-on 0→1

> **4h 不够时先砍这一节。** 它不是 D4 的主菜；它回答的是“0 副本时请求怎么进来”。如果你已经做过 D3 §8.7 的 scale-to-zero 负结果，Lab 0 只是把失败变成可用的 0→1。
>
> 这一节默认你还在 **D3 的集群**上，Deployment 叫 `vllm-qwen3-8b`；如果你直接开 D4 新 VM，先跳过这一节，或把名字换成 D4 的 `vllm-d4`。

### 4.1 它回答什么

D3 §8.7 的负结果：

```text
minReplicaCount: 0
  → Service 没有 endpoint
  → 直接 curl 失败
  → vLLM 没有 Pod，也没有 vllm:num_requests_waiting
  → KEDA 没有信号，0→1 不会发生
```

Lab 0 要证明：

1. 请求可以触发 0→1：不是靠 Prometheus 队列指标，而是 interceptor 接住 HTTP 请求并上报 concurrency；
2. 请求不丢：interceptor 在 vLLM 冷启动期间 hold 住连接，Pod Ready 后再转发；
3. 代价可量化：从 `curl` 发出到拿到响应，主要时间仍是 vLLM 冷启动（D3 §8.6 约 116s）；
4. 和 Knative 的区别：KEDA HTTP Add-on 不是 Knative，也不需要 Knative。

### 4.2 安装

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm search repo kedacore/keda-add-ons-http --versions | head

# 目的：确认 chart 版本和 KEDA 2.21 兼容；0.16.x 使用 InterceptorRoute
helm install http-add-on kedacore/keda-add-ons-http -n keda --version 0.16.0

kubectl -n keda get pods
kubectl get crd | grep -E 'interceptorroutes|httpscaledobjects'
kubectl explain interceptorroute.spec | head -40
```

期望：operator、interceptor、external scaler 三类 Pod Running。

### 4.3 停掉 D3 的队列 autoscaler

一个 Deployment 只能有一个 autoscaler；D3 的 `ScaledObject/vllm-scaler` 会和 Lab 0 的 `vllm-http` 打架。

```bash
kubectl delete scaledobject vllm-scaler --ignore-not-found
kubectl get hpa
# 应该看不到 keda-hpa-vllm-scaler
```

删除 ScaledObject 不会自动缩到 0；先保持 1 副本，后面再手动缩。

### 4.4 创建 InterceptorRoute

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: http.keda.sh/v1beta1
kind: InterceptorRoute
metadata:
  name: vllm-qwen3-8b
  namespace: default
spec:
  target:
    service: vllm-qwen3-8b
    port: 8000
  rules:
    - hosts:
        - vllm-qwen3-8b-proxy
        - vllm-qwen3-8b-proxy.default.svc.cluster.local
  scalingMetric:
    concurrency:
      targetValue: 1
  coldStart:
    maxPendingRequests: 100
  timeouts:
    readiness: 5m
    request: 5m
    responseHeader: 5m
EOF

kubectl get interceptorroute vllm-qwen3-8b
kubectl describe interceptorroute vllm-qwen3-8b
```

字段解释：

| 字段 | 值 | 意义 |
|---|---|---|
| `target.service` / `port` | `vllm-qwen3-8b` / `8000` | interceptor 最终转给哪个 Service |
| `rules[].hosts` | `vllm-qwen3-8b-proxy` | 按 HTTP `Host` 匹配；客户端必须带这个 Host |
| `scalingMetric.concurrency.targetValue` | `1` | 每个副本目标 1 个并发；一个 pending 请求就触发 0→1 |
| `coldStart.maxPendingRequests` | `100` | 每个 interceptor 副本最多 hold 100 个请求 |
| `timeouts.readiness` | `5m` | 等后端 Ready 的上限；必须大于 vLLM 冷启动 116s |
| `timeouts.request` | `5m` | 整个请求生命周期上限 |

> `readiness` 是最容易踩的坑：默认值通常只有几十秒，vLLM 冷启动 116s 会在 Pod Ready 前被切断，客户端看到 503。

### 4.5 创建 external-push ScaledObject

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: vllm-http
  namespace: default
spec:
  scaleTargetRef:
    name: vllm-qwen3-8b
  minReplicaCount: 0
  maxReplicaCount: 2
  cooldownPeriod: 300
  triggers:
    - type: external-push
      metadata:
        scalerAddress: keda-add-ons-http-external-scaler.keda:9090
        interceptorRoute: vllm-qwen3-8b
EOF

kubectl get scaledobject vllm-http
kubectl get hpa keda-hpa-vllm-http
```

先有 `InterceptorRoute`，再建 `ScaledObject`；顺序反了，KEDA 可能拿不到 metric spec。`scalerAddress` 以 `kubectl -n keda get svc` 的实际名字为准。

### 4.6 建 proxy Service

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: vllm-qwen3-8b-proxy
  namespace: default
spec:
  type: ExternalName
  externalName: keda-add-ons-http-interceptor-proxy.keda.svc.cluster.local
  ports:
    - port: 8080
EOF
```

调用方用 `http://vllm-qwen3-8b-proxy:8080`，并显式带 `Host: vllm-qwen3-8b-proxy`；Host 必须匹配 §4.4 的 `rules[].hosts`。

### 4.7 缩到 0 并触发 0→1

```bash
kubectl scale deploy vllm-qwen3-8b --replicas=0
kubectl wait --for=delete pod -l app=vllm --timeout=180s

kubectl run curl-trigger --rm -it --restart=Never \
  --image=curlimages/curl --command -- \
  curl -v -m 300 \
    -H 'Host: vllm-qwen3-8b-proxy' \
    http://vllm-qwen3-8b-proxy:8080/v1/models
```

预期：curl 不立刻失败；interceptor hold；KEDA 0→1；vLLM 冷启动约 116s；Pod Ready 后返回 200。

记录四个时间点：`t_request`、`t_pod_created`、`t_ready`、`t_response`。

| 场景 | `t_request` | `t_pod_created` | `t_ready` | `t_response` | 总耗时 |
|---|---|---|---|---|---|
| 0→1（HTTP interceptor） | | | | | |

### 4.8 结论与清理

- **能 0→1**：interceptor 接住请求，external-push scaler 触发 HPA；
- **不需要 Knative**：Knative 是另一条完整 serverless 路线，自带 activator；
- **冷启动仍是主成本**：116s 不会因为 interceptor 变短，只是请求不再立刻失败；
- **chat 仍建议 `minReplicaCount: 1`**：hold 116s 对同步聊天 SLO 不可接受；scale-to-zero 适合异步/批处理，或前端明确接受等待。

清理：

```bash
kubectl delete scaledobject vllm-http --ignore-not-found
kubectl delete interceptorroute vllm-qwen3-8b --ignore-not-found
kubectl delete svc vllm-qwen3-8b-proxy --ignore-not-found
kubectl scale deploy vllm-qwen3-8b --replicas=1
```

如果不再需要 add-on：

```bash
helm uninstall http-add-on -n keda
kubectl get crd | grep -E 'interceptorroutes|httpscaledobjects'
# CRD 不会自动删；确认没有 InterceptorRoute/HTTPScaledObject 后再删
```

---

## 5. Lab 1（主菜）：llm-d precise prefix-cache routing

> 可执行文件在 `scripts/d4/`，最短路径见 [`scripts/d4/README.md`](./scripts/d4/README.md)；本节解释每一步的“为什么”和验收点。

### 5.1 先修概念：approximate vs precise

| | optimized baseline（近似） | precise（精确） |
|---|---|---|
| 前缀信息来源 | EPP 自己根据请求流量/前缀 hash 估计 | vLLM 通过 ZMQ 上报 KV block 分配/驱逐 |
| 是否需要 tokenize | 不要求精确 token IDs | 必须；EPP 调 `/v1/*/render` |
| vLLM 额外配置 | 基本不需要 | `--kv-events-config`、`--enable-scale-out`、`--block-size=64` |
| 典型失败 | 估计不准、命中率低 | 索引空、render 404、block size 不匹配 |
| 适用 | fallback、快速验证 | D4 主实验 |

**为什么必须精确 token IDs？** vLLM 的 prefix cache 以 block 为单位；EPP 如果自己用另一套 tokenizer 或近似 hash，算出来的 block key 和 vLLM 的不一致，索引查不到，路由就退化成普通负载均衡。

**为什么 P99 会变？** 单请求的 TTFT 可以粗略拆成：

```text
TTFT ≈ 排队时间 + prefill(prompt_tokens - cached_tokens) / prefill_throughput + 首 token 开销
```

EPP 把请求送到已经缓存了这段前缀的副本，等价于把 `cached_tokens` 抬高、把 prefill 时间压低；在 c=16 的闭环里，prefill 变短还会减少 decode 被 prefill 抢占的时间，所以尾延迟的改善通常大于“少算一次 prefill”本身。反过来，如果前缀没有复用、或 EPP 的 tokenize/索引开销大于省下的 prefill，P99 就不会变好——这就是 §6.7 要判读的东西。

### 5.2 前置：k3s + GPU + 权重

按 D3 §5.0–§5.5 租 2×L4 VM、装 NVIDIA toolkit、k3s、device plugin。搜 2 卡 VM：

```bash
# 严格 L4：加 gpu_name=L4；没有结果再去掉这一项（4090/3090 也可，但结果必须标注）
vastai search offers -n \
  'num_gpus=2 gpu_name=L4 gpu_ram>=24 rentable=true vms_enabled=true cuda_vers>=13.0 disk_space>=130 inet_down>=500 reliability>=0.99 cpu_ram>=64' \
  -o 'dph' --storage 130 --limit 15
```

**创建必须走 D3 §5.0 的 API + `"vm": true`**；`vastai create instance` 的 CLI payload 不带 `vm` 字段，可能起成普通容器（SSH 拒绝、k3s 起不来）。拿到 offer ID 后复用 D3 §5.0 的 `curl PUT /asks/<OFFER_ID>/`，把 `disk` 设为 130、`label` 改成 `d4-llmd`。

以下命令都在 lab 仓库根目录执行：

```bash
cd /path/to/llm-inference-platform-lab
export LAB=$(pwd)

nvidia-smi
kubectl get nodes -o wide
kubectl get nodes -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}{"\n"}'
# 期望 2
```

下载权重到宿主机（两个 Pod 共享，不要每个 Pod 各下一次）：

```bash
sudo mkdir -p /models
HF_HOME=/workspace/hf huggingface-cli download Qwen/Qwen3-8B-AWQ \
  --local-dir /models/Qwen3-8B-AWQ

# 关键：确认没有指向 /workspace/hf 的 symlink；Pod 只挂 /models，symlink 会断
find /models/Qwen3-8B-AWQ -type l | head
# 如果输出非空，重新下载为实体文件，或把 /workspace/hf 一起挂进 Pod
ls /models/Qwen3-8B-AWQ | head
```

预拉镜像（可选，减少 Pod 启动时间）：

```bash
sudo k3s ctr images pull docker.io/vllm/vllm-openai:v0.34.0
```

准备结果目录：

```bash
sudo mkdir -p /results
sudo chmod 777 /results
```

### 5.3 部署两个 vLLM 副本

```bash
cd "${LAB}"
kubectl create namespace d4 --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n d4 -f scripts/d4/modelserver.yaml

kubectl get pods -n d4 -l app=vllm-d4 -w
# 期望两个 Pod 都 1/1 Running；每个占 1 张 GPU
```

如果 Pod CrashLoop：

```bash
kubectl logs -n d4 -l app=vllm-d4 --tail=100 --prefix
kubectl describe pods -n d4 -l app=vllm-d4
```

最常见的三个原因：`--enable-scale-out` 在该 vLLM 版本不存在；`replay_endpoint` 不被该版本支持；`--enable-prefix-caching` 在新版本已默认开启、不再接受这个 flag。先看 §3.4 的 `--help`，再决定删哪一行。

验证 `/v1/models`：

```bash
kubectl run curl-models --rm -i --restart=Never -n d4 \
  --image=curlimages/curl -- \
  curl -sS http://vllm-direct:8000/v1/models
```

期望返回 `qwen3-8b`。

### 5.4 验证 render 与 KV events

拿到两个 Pod IP，并逐个测 render（vLLM 0.30+ 在 `--enable-scale-out` 下提供；0.34 以 `--help` 为准）：

```bash
POD_IPS=$(kubectl get pods -n d4 -l app=vllm-d4 \
  -o jsonpath='{range .items[*]}{.status.podIP} {end}')
echo "$POD_IPS"

kubectl run render-check --rm -i --restart=Never -n d4 \
  --image=curlimages/curl --env="POD_IPS=${POD_IPS}" -- sh -c '
    for ip in $POD_IPS; do
      echo "== $ip"
      curl -sS -X POST "http://$ip:8000/v1/completions/render" \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"qwen3-8b\",\"prompt\":\"render check\",\"max_tokens\":1}" \
        | head -c 400
      echo
    done'
```

期望返回里有 `token_ids`。如果 404：`--enable-scale-out` 没开，或该版本没有 render 端点——**不要继续 precise，走 §5.10 fallback**。

确认 KV events 端口在监听：

```bash
kubectl get pods -n d4 -l app=vllm-d4 -o wide
# Pod IP 的 5556/5559 应可从 EPP Pod 访问；单节点 k3s 默认没有 NetworkPolicy
```

### 5.5 安装 GAIE CRD + llm-d router

在 `llm-inference-platform-lab` 仓库根目录先确认 `LAB`，再 clone llm-d：

```bash
: "${LAB:?先在 §5.2 设置 LAB 为 llm-inference-platform-lab 根目录}"
[ -d llm-d ] || git clone https://github.com/llm-d/llm-d.git
cd "${LAB}/llm-d"
git checkout release-1.0

export GAIE_VERSION=v1.6.2
kubectl apply -f "https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/${GAIE_VERSION}/v1-manifests.yaml"

kubectl get crd | grep -E 'inferencepools|inferenceobjectives'
```

安装 standalone router（在 llm-d 仓库根目录）：

```bash
helm upgrade --install d4-router \
  oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d4 --version v1.0.0 \
  -f guides/recipes/router/base.values.yaml \
  -f "${LAB}/scripts/d4/values-precise.yaml"
```

> `values-precise.yaml` 里的 `modelServers.matchLabels` 必须匹配模型服务器 Pod 的 `llm-d.ai/guide=d4-prefix-routing`；`targetPorts` 必须是 8000；`modelName` 必须是 `qwen3-8b`。

检查：

```bash
kubectl get pods -n d4
kubectl get inferencepool -n d4
kubectl get svc -n d4
kubectl get deploy -n d4
```

期望：`d4-router-epp` Pod Running；`d4-router-epp` Service 有 80 端口；`InferencePool` 的 selector 指向两个 vLLM Pod。`InferencePool` 应该长这样：

```yaml
spec:
  selector:
    matchLabels:
      llm-d.ai/guide: d4-prefix-routing
  targetPorts:
    - number: 8000
  endpointPickerRef:
    name: d4-router-epp
    port:
      number: 9002
    failureMode: FailOpen
```

### 5.6 验证 EPP 和索引

```bash
EPP_POD=$(kubectl get pods -n d4 -o jsonpath='{.items[*].metadata.name}' \
  | tr ' ' '\n' | grep '^d4-router-epp' | head -1)
echo "$EPP_POD"

kubectl logs -n d4 "$EPP_POD" -c epp --tail=120
kubectl get --raw "/api/v1/namespaces/d4/pods/${EPP_POD}:9090/proxy/metrics" \
  | grep -E 'kv_cache_events_active_subscribers|kv_cache_events_messages_received_total|kv_cache_index_lookup'
```

如果 `-c epp` 报容器名不存在，先看 Pod 的容器列表：

```bash
kubectl get pod -n d4 "$EPP_POD" -o jsonpath='{.spec.containers[*].name}{"\n"}'
```

期望：

- `llm_d_epp_kv_cache_events_active_subscribers` = 2（两个 vLLM Pod）；
- `messages_received_total` 在发请求后增长；
- `index_lookup_requests_total` 在发请求后增长。

如果 subscribers 不是 2：检查 `podDiscoveryConfig.socketPort: 5556`、`topicFilter: kv@`、Pod 的 5556/5559 端口，以及 vLLM 日志里是否真的启用了 KV events。

### 5.7 路由 smoke test

先用小负载确认“同一前缀会落到同一个 Pod”，再跑正式压测。用 bench 客户端跑 2 个 session × 5 turn、`max_tokens=16`、并发 1：

```bash
cd "${LAB}"

POD_URLS=$(kubectl get pods -n d4 -l app=vllm-d4 \
  -o jsonpath='{range .items[*]}http://{.status.podIP}:8000,{end}' | sed 's/,$//')
echo "$POD_URLS"

export URL="http://d4-router-epp/v1/completions"
export ARM="smoke" RUN="1" FORCE_CLOSE="0"
export POD_URLS
export SESSIONS="2" TURNS="5" PREFIX_WORDS="1100" SUFFIX_WORDS="80"
export MAX_TOKENS="16" CONCURRENCY="1" SEED="42"

kubectl create configmap d4-bench -n d4 \
  --from-file=bench_prefix.py=scripts/d4/bench_prefix.py \
  --from-file=run_bench.sh=scripts/d4/run_bench.sh \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl delete pod d4-bench -n d4 --ignore-not-found
envsubst < scripts/d4/bench-pod.yaml | kubectl apply -n d4 -f -
kubectl wait --for=condition=Ready pod/d4-bench -n d4 --timeout=120s
kubectl logs -f d4-bench -n d4
```

然后看每个 Pod 的 `vllm:request_success_total` 和 `vllm:prefix_cache_hits_total`：

```bash
for name in $(kubectl get pods -n d4 -l app=vllm-d4 -o jsonpath='{.items[*].metadata.name}'); do
  echo "== $name"
  kubectl get --raw "/api/v1/namespaces/d4/pods/${name}:8000/proxy/metrics" \
    | grep -E '^vllm:(prefix_cache_hits_total|prefix_cache_queries_total|request_success_total)'
done
```

期望：10 条请求里，大部分落在一个 Pod；该 Pod 的 `prefix_cache_hits_total / prefix_cache_queries_total` 明显高于另一个。如果两个 Pod 各 5 条、命中率接近 0：precise 没生效，回到 §5.6。

### 5.8 校准 `peakPrefillThroughput`

`prefix-cache-affinity-filter` 用 `peakPrefillThroughput` 把 in-flight token 负载换算成预测 TTFT。guide 的 15926 是 H100/Qwen3-32B/TP=2 的值，L4 上不能用。

```bash
cd "${LAB}/llm-d"

GUIDE_NAME=d4-router \
NAMESPACE=d4 \
MODEL_NAME=qwen3-8b \
CHUNK_SIZE=4096 \
guides/recipes/router/calibration/calibrate.sh
```

`CHUNK_SIZE` 必须等于 vLLM 的 `--max-num-batched-tokens`（本 lab 是 4096）。脚本会打印 `peakPrefillThroughput=<value>`。注意：calibration 默认走 EPP Service，TTFT 含 tokenize/路由开销，是**部署口径**，不是纯 vLLM prefill 峰值；写进结果时说明这一点。如果要测纯 vLLM，设 `VLLM_ENDPOINT=http://<pod-ip>:8000` 指向单个 Pod。

如果报 `envsubst: command not found`：

```bash
sudo apt-get update && sudo apt-get install -y gettext-base
```

把值写回 `${LAB}/scripts/d4/values-precise.yaml` 的 `prefix-cache-affinity-filter.parameters.peakPrefillThroughput`，然后：

```bash
helm upgrade d4-router \
  oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d4 --version v1.0.0 \
  -f guides/recipes/router/base.values.yaml \
  -f "${LAB}/scripts/d4/values-precise.yaml"

kubectl rollout restart deploy/d4-router-epp -n d4
kubectl rollout status deploy/d4-router-epp -n d4 --timeout=120s
```

如果 calibration Job 跑不通：临时把 `peakPrefillThroughput` 设成 `100000`（相当于关闭 saturation override，只保留 prefix affinity），在结果里明确写“未校准，gate 被人为关闭”。不要把这个值当生产值。

### 5.9 切到 random baseline

```bash
helm upgrade d4-router \
  oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d4 --version v1.0.0 \
  -f guides/recipes/router/base.values.yaml \
  -f "${LAB}/scripts/d4/values-random.yaml"

kubectl rollout restart deploy/d4-router-epp -n d4
kubectl rollout status deploy/d4-router-epp -n d4 --timeout=120s
```

`random-picker` 和 precise 走同一条 Envoy + EPP 路径，只是忽略 cache/score；它用来回答：“P99 的改善是路由算法带来的，还是因为多了一跳 EPP？” 如果时间只够两组，跑 direct vs precise，random 作为加分项。

### 5.10 Fallback：optimized baseline

如果 precise 的 render/KV events 在当前 vLLM 版本跑不通，用 `values-optimized.yaml`：

```bash
helm upgrade d4-router \
  oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d4 --version v1.0.0 \
  -f guides/recipes/router/base.values.yaml \
  -f "${LAB}/scripts/d4/values-optimized.yaml"
```

它用 `approx-prefix-cache-producer`，不需要 `--enable-scale-out` 和 KV events；仍然能对比 round-robin vs EPP 的 P99 和命中率，只是“前缀位置”是估计的。结果里必须写清楚是 **optimized baseline，不是 precise**。

如果模型服务器本身就是因为 `--enable-scale-out` / `--kv-events-config` 起不来，先把 `scripts/d4/modelserver.yaml` 里的这两段删掉，再 `kubectl apply`；optimized baseline 不需要它们。

---

## 6. 压测设计

### 6.1 三个 arm

| arm | URL | 说明 | 优先级 |
|---|---|---|---|
| `direct` | `http://vllm-direct:8000/v1/completions` | 普通 Service；K8s per-connection 选择，不是严格轮询；用 `FORCE_CLOSE=1` 让每个请求新建连接 | **P0** |
| `precise` | `http://d4-router-epp/v1/completions` | llm-d precise prefix routing | **P0** |
| `random` | `http://d4-router-epp/v1/completions` | 同一 EPP/Envoy 路径，`random-picker`；隔离固定开销 | P1 |

主对比是 `direct` vs `precise`（计划要求）；`random` 是控制组，用来说明“不是 EPP 本身变快/变慢”。

### 6.2 Workload

固定一批“共享长前缀”的请求：

| 参数 | 值 | 理由 |
|---|---|---|
| sessions | 32 | 32 个不同长前缀，制造 cache 竞争 |
| turns | 4 | 每个 session 4 轮，共 128 请求 |
| prefix words | 1100 | 约 1.5k tokens；32 个前缀约 7GB KV，L4 放得下 |
| suffix words | 80 | 每轮新增约 100 tokens，模拟多轮对话 |
| max tokens | 128 | 固定输出长度；`ignore_eos=true` |
| concurrency | 16 | 闭环；足以制造排队，又不会把 L4 打到完全过载 |
| seed | 42 | 请求顺序固定，三个 arm 相同 |

请求顺序：每个 turn 内把 32 个 session 打乱；同一 session 的连续 turn 被其他 session 隔开。这样 random 路由会在 turn 之间丢失 session 的 prefix，而 precise 可以保持。

> 对话历史里的 assistant 回复是**固定文本**，不是模型真实输出。这样三个 arm 的 prompt 完全一致，避免自回归内容把变量引进来；代价是它不完全等同真实多轮 chat，但足以测路由对 prefix cache 的影响。

**为什么不用 `vllm bench serve --dataset-name prefix_repetition`？** 它也能测 prefix caching，但请求顺序是“一个前缀的请求连在一起”，random 路由只要前两条把两个 Pod 都预热，后面就都命中；对“多轮 session 被交错”的场景不够敏感。本 lab 用 `scripts/d4/bench_prefix.py` 控制交错顺序。

### 6.3 指标与 SLO

| 指标 | 定义 | 采集 |
|---|---|---|
| TTFT P50/P95/P99 | 请求发出→第一个内容 chunk | 客户端 `bench_prefix.py` |
| TPOT P95 | `(end - first_token) / (completion_tokens - 1)` | 客户端 |
| E2E P99 | 请求发出→最后一个 chunk | 客户端 |
| output tok/s | 总 completion tokens / wall time | 客户端 |
| goodput | 满足 `TTFT ≤ 2000ms` 且 `TPOT ≤ 100ms` 的 req/s | 客户端 |
| prefix hit rate | `Δvllm:prefix_cache_hits_total / Δvllm:prefix_cache_queries_total` | 每个 vLLM Pod 的 `/metrics` |
| per-Pod 请求分布 | `Δvllm:request_success_total` | 每个 Pod |
| EPP 预测命中 | `llm_d_epp_prefix_predicted_cached_tokens_sum / llm_d_epp_prefix_prompt_tokens_sum` | EPP `/metrics` |
| EPP 索引 | `active_subscribers`、`messages_received_total`、`index_lookup_*` | EPP `/metrics` |

SLO 沿用 D1/D2/D3：`TTFT ≤ 2,000ms`、`TPOT ≤ 100ms`（per-request）。不要中途换 SLO。

命中率按 vLLM 的 block 计数算，不是按请求数：

```text
hit_rate = Δvllm:prefix_cache_hits_total / Δvllm:prefix_cache_queries_total
```

`queries` 是“查了多少个 block”，`hits` 是“命中了多少个 block”；两个 Pod 的加权口径是 `Σhits / Σqueries`。EPP 的 `llm_d_epp_prefix_predicted_cached_tokens_sum / llm_d_epp_prefix_prompt_tokens_sum` 是“预测的 cached token 占比”，用来和 vLLM 的实际 hit rate 对照；两者趋势不一致，通常说明索引不完整或 render 失败。

### 6.4 方法学（必须一起写）

- **闭环**：16 并发，固定 128 条请求；不是开环固定 QPS。
- **样本数**：128 请求/轮；3 轮/arm；报中位数和范围。
- **warmup**：每轮前 4 条 `max_tokens=1` 的 warmup；脚本 warmup 后 reset prefix cache；precise arm 在启动脚本前重启 EPP，让索引从空开始。
- **重复**：3 轮，顺序 `direct → random → precise` 或反过来；如果 GPU 热节流明显，记录 `nvidia-smi` 的 clock/power。
- **同机同模型**：三个 arm 用同一对 vLLM Pod、同一 `max-model-len`、同一 `max-num-seqs`、同一输出长度。
- **cache 状态**：每轮开始前 `POST /reset_prefix_cache` 到两个 Pod；precise arm 重启 EPP。否则上一轮的热缓存会让结果不可比。
- **货币/单价**：USD；Vast 实时 `$/h`；记录 GPU 型号、power limit、driver。
- **GPU 采样**：`nvidia-smi --query-gpu=utilization.gpu,power.draw,clocks.sm --format=csv -l 5` 另开一个终端记录；util 只作解释，不作 SLO。
- **不要**：把 direct 的 per-connection 随机说成“严格 round-robin”；把 EPP 的固定开销算成 prefix routing 的收益；把不同模型/不同卡的数字混在一起。

### 6.5 跑三组

先把脚本打进 ConfigMap（回到 lab 仓库根目录）：

```bash
cd "${LAB}"

kubectl create configmap d4-bench -n d4 \
  --from-file=bench_prefix.py=scripts/d4/bench_prefix.py \
  --from-file=run_bench.sh=scripts/d4/run_bench.sh \
  --dry-run=client -o yaml | kubectl apply -f -
```

拿 Pod IP：

```bash
POD_URLS=$(kubectl get pods -n d4 -l app=vllm-d4 \
  -o jsonpath='{range .items[*]}http://{.status.podIP}:8000,{end}' | sed 's/,$//')
echo "$POD_URLS"
```

跑一轮（以 precise 为例）：

```bash
# precise arm：每轮前重启 EPP，清空 KV 索引（vLLM cache 由脚本 reset）
kubectl rollout restart deploy/d4-router-epp -n d4
kubectl rollout status deploy/d4-router-epp -n d4 --timeout=120s

export URL="http://d4-router-epp/v1/completions"
export ARM="precise" RUN="1" FORCE_CLOSE="0"
export POD_URLS
export SESSIONS="32" TURNS="4" PREFIX_WORDS="1100" SUFFIX_WORDS="80"
export MAX_TOKENS="128" CONCURRENCY="16" SEED="42" WARMUP="4"

kubectl delete pod d4-bench -n d4 --ignore-not-found
envsubst < scripts/d4/bench-pod.yaml | kubectl apply -n d4 -f -
kubectl wait --for=condition=Ready pod/d4-bench -n d4 --timeout=120s
kubectl logs -f d4-bench -n d4
```

`direct` arm 把 `URL` 换成 `http://vllm-direct:8000/v1/completions`，`FORCE_CLOSE=1`。`random` arm 先把 router 切到 `values-random.yaml`，`URL` 保持 `http://d4-router-epp/v1/completions`。

每轮开始前，脚本会自动对 `POD_URLS` 发 `POST /reset_prefix_cache`；如果返回 404/405，手动重启两个 Pod，或在结果里注明“cache reset 不可用，轮次之间可能有残留”。

### 6.6 结果模板

**客户端汇总**（每 arm 3 轮，表中填中位数，括号内范围）：

| arm | 轮次 | ok | TTFT P50 (ms) | TTFT P95 | TTFT P99 | TPOT P95 | E2E P99 | output tok/s | goodput (req/s) |
|---|---|---|---|---|---|---|---|---|---|
| direct | 3 | | | | | | | | |
| random | 1–3 | | | | | | | | |
| precise | 3 | | | | | | | | |

**命中率与分布**（每轮前后各取一次 metrics，算 delta）：

| arm | Pod A requests | Pod B requests | Pod A hit rate | Pod B hit rate | 加权 hit rate | EPP predicted cached share |
|---|---|---|---|---|---|---|
| direct | | | | | | n/a |
| random | | | | | | n/a |
| precise | | | | | | |

**P99 对比图**：把三份 JSON 交给 `plot_d4.py`（没有跑 random 就删掉那一个文件）：

```bash
cd "${LAB}"
python3 scripts/d4/plot_d4.py \
  /results/direct-run1.json /results/random-run1.json /results/precise-run1.json \
  --out /results/d4-ttft.png
```

**一句话归因模板**：

> 在同一对 L4、同一模型、同一 128 条共享前缀请求下，EPP precise 把 TTFT P99 从 `____ ms` 降到 `____ ms`（`__%`），加权 prefix hit rate 从 `__%` 升到 `__%`；代价是 EPP `____ ms` 的固定开销（用 random arm 对比），以及 single-EPP 的可用性风险。

### 6.7 怎么判读

**precise 应该出现**：

- 同一 session 的 4 轮请求集中到一个 Pod；另一个 Pod 只分到少量 session；
- 该 Pod 的 prefix hit rate 高（每轮第 2–4 条请求复用第 1 条的前缀）；
- TTFT P99 比 direct/random 低；output tok/s 可能略高（少做重复 prefill），也可能持平；
- EPP 的 predicted cached share 与 vLLM 的实际 hit rate 趋势一致。

**如果没有差异**：

1. 先看 `active_subscribers` 是否 = 2、`messages_received_total` 是否增长；没有就是 KV events 没进来。
2. 看 `/v1/completions/render` 是否 200 且有 `token_ids`；没有就是 precise 没生效。
3. 看 `blockSizeTokens` 是否等于 `--block-size`；不等就全 miss。
4. 看 workload 是否真的共享前缀：32 个 session 的前缀必须不同、同一 session 的 turn 必须复用；如果每条 prompt 都不同，路由没有可用的前缀。
5. 看 KV cache 是否大到“两个 Pod 都能缓存所有 32 个前缀”：如果 L4 的 KV 足够大，random 也会在预热后全命中，差异会被稀释。可以增加到 64 个 session，或缩短 `max-model-len`/`gpu-memory-utilization` 让 cache 更紧张。

**如果 precise 更差**：

- EPP 的 tokenize/render 是每请求一次网络调用，可能增加 TTFT；看 `llm_d_epp_token_producer_render_duration_seconds`。
- EPP 单副本可能成为 CPU 瓶颈；看 EPP 的 CPU 使用率和 `llm_d_epp_plugin_duration_seconds`。
- `peakPrefillThroughput` 太低会让 gate 过早扩散，破坏 affinity；用 calibration 值或临时调高做敏感性对比。
- Envoy/EPP 的资源 limit 太小；把 EPP 提到 2 CPU/4Gi 以上。

### 6.8 采样 metrics 的脚本

每轮开始/结束各跑一次：

```bash
snapshot() {
  local label="$1"
  {
    for name in $(kubectl get pods -n d4 -l app=vllm-d4 -o jsonpath='{.items[*].metadata.name}'); do
      echo "== ${name}"
      kubectl get --raw "/api/v1/namespaces/d4/pods/${name}:8000/proxy/metrics" \
        | grep -E '^vllm:(prefix_cache_hits_total|prefix_cache_queries_total|request_success_total|num_requests_waiting|kv_cache_usage_perc)'
    done
    EPP_POD=$(kubectl get pods -n d4 -o name | grep d4-router-epp | head -1 | cut -d/ -f2)
    echo "== epp"
    kubectl get --raw "/api/v1/namespaces/d4/pods/${EPP_POD}:9090/proxy/metrics" \
      | grep -E 'llm_d_epp_(kv_cache_events|kv_cache_index_lookup|prefix_predicted|prefix_prompt|request_total|plugin_duration)'
  } | tee "/results/metrics-${label}.txt"
}

snapshot before-precise-run1
# run bench
snapshot after-precise-run1
```

`/results` 是宿主机目录，VM 销毁前 `scp` 回本地。

---

## 7. B 线：Gateway / InferencePool / EPP 运维

### 7.1 运维图

```text
client
  │
  ▼
Service d4-router-epp:80
  │
  ▼
┌─────────────────────────────┐
│ EPP Pod                     │
│  ┌─────────┐  ext_proc  ┌───┴────┐
│  │ Envoy   │◄──────────►│  EPP   │
│  └────┬────┘             └───┬────┘
│       │                      │ watch
│       │                      ▼
│       │              InferencePool（selector + port + EPP ref）
│       │                      │
│       │              ┌───────┴────────┐
│       │              ▼                ▼
│       │        vLLM Pod A        vLLM Pod B
│       └──────────────►:8000       :8000
│                      │                │
│                 KV events 5556/5559（ZMQ）
└─────────────────────────────────────
```

健康检查点：

| 层 | 检查 | 期望 | 失败时 |
|---|---|---|---|
| vLLM | `/health`、`/v1/models` | 200 | Pod 重启/滚动更新 |
| vLLM KV events | 5556/5559 监听；EPP `active_subscribers=2` | 2 | 查 `--kv-events-config`、端口、topic |
| EPP | Pod Ready；`/metrics` 可读 | 200 | 查 config、CRD、资源 |
| Envoy | Service 80 可访问 | 200 | 查 sidecar、端口 |
| InferencePool | `status.parents` / `ResolvedRefs` | Accepted | 查 selector、EPP Service 名 |
| Gateway（如果启用） | HTTPRoute Accepted | True | 查 Gateway controller、backendRef |

### 7.2 多模型 / 多租户路由

- **一个 `InferencePool` 对应一个模型**。不要把两个不同模型放进同一个 pool；EPP 的 `modelName` 和 tokenizer 是 per-pool 的。
- **同 namespace**：`InferencePool` 的 selector 只匹配同一 namespace 的 Pod，跨 namespace 不能共享一个 pool；多租户就每个 namespace 自己建 pool/route。
- **多模型**：每个模型一个 pool + 一个 HTTPRoute path/header；Gateway 按 path 分流。EPP 仍然只负责自己 pool 内的副本选择。
- **多租户**：namespace + RBAC 做逻辑隔离；ResourceQuota 限 CPU/内存；NetworkPolicy 限制跨 namespace；每个租户自己的 pool/route；`InferenceObjective` 做优先级（如果启用 flow control）。
- **不要**用“同一个 pool + 请求头里的 tenant”做硬隔离；请求头可以伪造，真正的隔离在 namespace/配额/网络策略。

### 7.3 路由故障表（至少跑前两项）

| 故障 | 现象 | 检查 | 根因 | 处置 | 用户影响 |
|---|---|---|---|---|---|
| EPP 挂（FailOpen） | 请求仍 200，但 P99/分布变化 | `kill -STOP 1` 暂停 EPP 容器；发 20 条 | Envoy ext_proc 超时后走 headless Service | `kill -CONT 1` 恢复；观察索引重建 | 短暂无 cache 路由，不应 5xx |
| EPP 挂（FailClose） | 503/超时 | `helm upgrade ... --set router.proxy.failOpen=false`；再暂停 EPP | standalone Envoy 的 failOpen 关了 | 恢复 EPP；`--set router.proxy.failOpen=true` | 请求失败 |
| render 404 | 请求 200，但 hit rate ~0 | 直接 POST `/v1/completions/render` | `--enable-scale-out` 没开；`modelName` 不匹配 | 修 vLLM flag/模型名；重启 EPP | 退化成普通负载均衡 |
| KV events 没进来 | `active_subscribers` < 2；索引空 | EPP metrics；`kubectl exec` 测 5556 | 端口/topic/NetworkPolicy 错 | 修 `--kv-events-config`；重启 Pod/EPP | 无 prefix 路由 |
| block size 不匹配 | hit rate ~0，索引有数据但 lookup miss | 对比 `--block-size` 与 `blockSizeTokens` | 两处不一致 | 统一成 64；重启 | 无收益 |
| 后端 Pod 不健康 | 5xx/超时；endpoint 被摘除 | `kubectl get pods`；EPP logs | OOM/模型加载失败/GPU 错 | 重启/替换；看 D3 Lab 4 的排空 | 在途请求可能失败 |
| 前缀不命中 | P99 与 direct 持平 | 看 workload 前缀是否重复 | 请求本身没有共享前缀 | 改 workload；不是 bug | 无收益 |
| EPP 单副本重启 | FailOpen 下短暂延迟升高；FailClose 下 503 | `kill -STOP/-CONT` 或 rollout restart | 单副本 + 索引重建 | 生产用 HA/快照；D4 接受 | 短暂降级 |

> **sidecar 模式的坑：** standalone 默认把 Envoy 和 EPP 放在同一个 Pod。`kubectl scale deploy/d4-router-epp --replicas=0` 会把 Envoy 一起删掉，客户端直接 `connection refused`——这不是 FailOpen，是数据面整体消失。要测 FailOpen/FailClose，必须让 Envoy 活着、只让 EPP 不响应：用 `kill -STOP 1` 暂停 EPP 容器，测完 `kill -CONT 1`。EPP 的 readiness 默认是 `periodSeconds: 2` × `failureThreshold: 3`，几秒内就会把 Pod 从 Service 摘掉；而 Envoy 的 ext_proc 超时是 10s，可能还没 fail-open 就被摘掉。**所以下面的测试先把 readiness 的 failureThreshold 调到 60（约 120s），测完再改回 3。** 如果要更长的故障窗口/更接近生产，把 chart 切成 `router.proxy.mode=service`，让 proxy 独立于 EPP。

> **两个 fail-open 开关，别混：**
> - `InferencePool.spec.endpointPickerRef.failureMode` 是 **Gateway/EPP 契约**；支持它的 Gateway 会读。
> - `router.proxy.failOpen` 是 **standalone Envoy 自己的行为**。standalone chart 的 `values.yaml` 默认是 `true`；helper 的兜底在 sidecar 模式是 `false`，但 chart 默认值会覆盖它。D4 的 `values-precise.yaml` 仍显式写 `failOpen: true`，避免依赖默认值。
>
> 所以 standalone 的 FailClose 测试要改 `router.proxy.failOpen`，只 patch `InferencePool.failureMode` 不一定生效。
>
> FailOpen 也不是“瞬间绕过”：Envoy 的 ext_proc 有超时（chart 默认 10s），所以暂停 EPP 后前几条请求可能先等超时，P99 会升高但不应 5xx。记录时把“等待超时”与“请求失败”分开。
>
> FailClose 下，如果 readiness 先把 Pod 摘掉，客户端看到的可能是 `connection refused` 而不是 503；两者都属于 fail-close，但要在结果里分开写，别把 connection refused 当成“fail-open 失败”。

**FailOpen 测试命令**：

```bash
# 1. 临时放宽 EPP readiness，避免 Pod 在 ext_proc 超时前被摘掉
kubectl patch deploy d4-router-epp -n d4 --type=strategic -p '
spec:
  template:
    spec:
      containers:
      - name: epp
        readinessProbe:
          failureThreshold: 60
'
kubectl rollout status deploy/d4-router-epp -n d4 --timeout=120s

EPP_POD=$(kubectl get pods -n d4 -o jsonpath='{.items[*].metadata.name}' \
  | tr ' ' '\n' | grep '^d4-router-epp' | head -1)
echo "$EPP_POD"

# 2. 暂停 EPP 进程（容器还在，Envoy sidecar 还在）
# 如果 EPP 不是 PID 1，先 `ps -eo pid,args | grep -E 'epp|endpoint-picker'` 找 PID
kubectl exec -n d4 "$EPP_POD" -c epp -- kill -STOP 1

# 3. 发 20 条请求，记录 200/503/延迟；期望仍 200（ext_proc 超时后 fail-open）
# 4. 恢复
kubectl exec -n d4 "$EPP_POD" -c epp -- kill -CONT 1

# 5. 把 readiness 改回默认
kubectl patch deploy d4-router-epp -n d4 --type=strategic -p '
spec:
  template:
    spec:
      containers:
      - name: epp
        readinessProbe:
          failureThreshold: 3
'
kubectl rollout status deploy/d4-router-epp -n d4 --timeout=120s
```

如果容器里没有 `kill` 或权限不够，用 `sh -c`：

```bash
kubectl exec -n d4 "$EPP_POD" -c epp -- sh -c 'kill -STOP 1'
kubectl exec -n d4 "$EPP_POD" -c epp -- sh -c 'kill -CONT 1'
```

如果 `CONT` 失败，直接删 Pod 让它重启：

```bash
kubectl delete pod -n d4 "$EPP_POD"
kubectl rollout status deploy/d4-router-epp -n d4 --timeout=120s
```

**FailClose 测试**：

```bash
# standalone Envoy 的 failOpen 改成 false（standalone chart 默认是 true；
# values-precise.yaml 也显式写了 true；这里用 --set 覆盖）
helm upgrade d4-router \
  oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d4 --version v1.0.0 \
  -f "${LAB}/llm-d/guides/recipes/router/base.values.yaml" \
  -f "${LAB}/scripts/d4/values-precise.yaml" \
  --set router.proxy.failOpen=false

kubectl rollout restart deploy/d4-router-epp -n d4
kubectl rollout status deploy/d4-router-epp -n d4 --timeout=120s

# Pod 会被重建，重新取名字
EPP_POD=$(kubectl get pods -n d4 -o jsonpath='{.items[*].metadata.name}' \
  | tr ' ' '\n' | grep '^d4-router-epp' | head -1)

# 再暂停 EPP；重复 20 条请求；期望 503
kubectl exec -n d4 "$EPP_POD" -c epp -- kill -STOP 1

# 恢复
kubectl exec -n d4 "$EPP_POD" -c epp -- kill -CONT 1
helm upgrade d4-router \
  oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d4 --version v1.0.0 \
  -f "${LAB}/llm-d/guides/recipes/router/base.values.yaml" \
  -f "${LAB}/scripts/d4/values-precise.yaml" \
  --set router.proxy.failOpen=true
kubectl rollout restart deploy/d4-router-epp -n d4
```

> `InferencePool` 的实际名字是 `d4-router`（chart 用 release name），可以用 `kubectl get inferencepool -n d4` 确认。`InferencePool.failureMode` 留给 Gateway Mode 的面试讲法；standalone 的实测以 `router.proxy.failOpen` 为准。

**故障实测记录**：

| 故障 | 请求数 | 200 | 503/5xx | P99 (ms) | 恢复时间 | 备注 |
|---|---:|---:|---:|---:|---|---|
| FailOpen（暂停 EPP 10s） | 20 | | | | | |
| FailClose（暂停 EPP 10s） | 20 | | | | | |
| EPP Deployment 整体 0 副本 | 20 | | | | | 这是数据面整体消失，不是 FailOpen |
| render 404（错误 modelName） | 20 | | | | | hit rate 应掉到 ~0 |

### 7.4 容量与成本

- **每副本成本**：2×L4 VM `$/h` ÷ 2 个副本；再加 EPP/Envoy 的 CPU 成本（可忽略，但不能说 0）。
- **容量**：满足 SLO 的并发，不是 GPU util 100%。用 D1/D2 的方法：c=16 找拐点，c=32/64 看吞吐上限；D4 只跑 c=16。
- **EPP 容量**：单副本 EPP 的 CPU 是路由 QPS 的上限；看 `llm_d_epp_plugin_duration_seconds` 和 Pod CPU。请求率上去后，EPP 可能先于 vLLM 成为瓶颈。
- **prefix cache 容量**：32 个 1.5k-token 前缀约 7GB KV；L4 的 KV 不是无限大。session 数增加会触发驱逐，命中率下降。

### 7.5 升级与回滚

- **模型版本**：权重按版本目录存放（`/models/Qwen3-8B-AWQ-v1`、`-v2`），Deployment 用 `MODEL_PATH` 指向版本；回滚 = 改路径 + `kubectl rollout undo`。不要在运行中的目录上覆盖权重。
- **路由配置**：EPP 的 `EndpointPickerConfig` 不是 CRD，改 ConfigMap 后必须重启 EPP；`helm upgrade` 后补 `kubectl rollout restart`。
- **滚动更新**：`maxSurge: 0`、`maxUnavailable: 1`（2 副本时一次只动一个）；`preStop 15s` + `--shutdown-timeout=45` + grace 120s，沿用 D3 Lab 4 的结论。
- **回滚验证**：`kubectl rollout undo deploy/vllm-d4`；确认两个 Pod 都 Ready、`/v1/models` 正常、EPP subscribers 回到 2。

### 7.6 Gateway Mode（概念，不跑）

D4 用 **standalone**：Envoy sidecar 和 EPP 在同一个 Pod，客户端直接访问 `d4-router-epp:80`。生产多模型/多租户通常用 **Gateway Mode**：一个共享 Gateway（Istio / Envoy Gateway / agentgateway）承载多条 HTTPRoute，每条 route 的 backendRef 指向一个 `InferencePool`。

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: d4-inference
  namespace: d4
spec:
  parentRefs:
    - name: inference-gateway
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /v1
      backendRefs:
        - group: inference.networking.k8s.io
          kind: InferencePool
          name: d4-router
          port: 8000
```

关键区别：

| | standalone（D4） | Gateway Mode（生产） |
|---|---|---|
| 数据面 | EPP Pod 里的 Envoy sidecar | 共享 Gateway（Istio/Envoy/agentgateway） |
| 路由资源 | `InferencePool` + EPP Service | `Gateway` + `HTTPRoute` + `InferencePool` |
| 多模型 | 每个模型一个 release/Service | 一个 Gateway + 多条 HTTPRoute |
| 多租户 | namespace + Service | namespace + HTTPRoute + Gateway 策略 |
| 适用 | 单模型、学习/验证 | 共享入口、多模型、金丝雀/分流 |

> `InferencePool` 的实际名字以 `kubectl get inferencepool -n d4` 为准；HTTPRoute 的 backendRef 必须指向它。

D4 不装 Gateway 的原因：4h 内要装 Gateway controller、调 listener/证书/路由，时间会挤掉主实验；standalone 已经能验证 `InferencePool`/EPP 的核心契约。面试时把这张表和 HTTPRoute 讲清楚即可。

---

## 8. llm-d 四问（按计划 §6）

**Q1：EPP 干什么？它凭什么比 round-robin 好？**
A：EPP 是推理感知的 endpoint picker。普通 round-robin 只看“下一个是谁”，EPP 看“谁的 KV cache 里已经有这段前缀、谁的 in-flight token 最少”。它把请求送到已经算过这段前缀的副本，减少重复 prefill，从而降低 TTFT P99、提高有效吞吐。代价是每请求一次 tokenize/render 和索引查询，以及一个额外的 EPP 组件。

**Q2：`InferencePool` 这个契约解决什么问题？为什么不直接用 Service？**
A：Service 只提供“按 label 选 Pod + 端口”的 L4 负载均衡，它不知道模型、tokenizer、KV cache、EPP。`InferencePool` 把“哪些 Pod 是同一个模型的副本、目标端口是多少、EPP 是谁、失败模式是什么”变成一个标准资源；Gateway/Envoy 通过它把请求交给 EPP，而不是直接 round-robin。它还让多模型/多租户路由有统一的 backend 类型（HTTPRoute 的 `backendRef` 可以指向 `InferencePool`）。

**Q3：PD 分离在什么情况下不划算？**
A：低并发、模型小、KV 传输带宽不够、集群没有第二个 GPU 池——大多数团队死在这条。PD 分离把 prefill 和 decode 拆到不同池，收益来自“prefill 和 decode 的 resource profile 不同”；如果模型小、请求短、网络搬 KV 的成本高于重算，或者你只有 2 张卡，拆池只会增加复杂度和空闲。D4 不跑 PD，只记住“什么时候不划算”。

**Q4：wide EP 解决什么？**
A：MoE 模型的专家并行。单机放不下全部专家时，把专家切到多机/多卡，用 EP（expert parallelism）跨节点通信。它解决的是“模型太大、单机显存不够”，不是“路由”。D4 不跑 wide EP；面试能说清它和 TP/PP 的区别即可。

---

## 9. 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| `render` 404 | `--enable-scale-out` 没开；vLLM 版本没有该端点 | 看 §3.4 `--help`；走 optimized fallback |
| EPP 日志 `token-producer` 失败 | `modelName` 与 `--served-model-name` 不一致 | 改成 `qwen3-8b`；重启 EPP |
| `active_subscribers=0/1` | 5556/5559 没开、topic 不匹配、NetworkPolicy | 查 `--kv-events-config`、端口、topic |
| hit rate ~0 | `blockSizeTokens` 与 `--block-size` 不一致 | 统一 64；重启 vLLM/EPP |
| 两个 Pod 各 50% | precise 没生效，或 workload 没有共享前缀 | 看 render/索引；改 workload |
| EPP 一重启就 503 | single EPP + FailClose | D4 用 FailOpen；生产 HA |
| direct arm 看起来“很均匀” | HTTP keep-alive 把连接钉在一个 Pod | 用 `FORCE_CLOSE=1`；说明 K8s Service 是 per-connection |
| 第二轮结果变好 | 上一轮的热缓存 | 每轮 `reset_prefix_cache`；precise 重启 EPP |
| `peakPrefillThroughput` 用了 15926 | 这是 H100/Qwen3-32B 的值 | 跑 §5.8 calibration；或明确写“gate 关闭” |
| `InferencePool` 没有 endpoint | selector 不匹配；端口不是 8000 | 对比 Pod label 和 `matchLabels` |
| 2 副本滚动更新卡住 | `maxSurge: 0` + 没有空闲 GPU | 一次只动一个；或先 scale 到 1 再更新 |
| Lab 0 curl 立刻 503 | Host 不匹配、InterceptorRoute 不 Ready | 带 `Host: vllm-qwen3-8b-proxy`；看 describe |
| `stream_options.include_usage` 400 | vLLM 版本不接受该字段 | 删掉 `stream_options`；`completion_tokens` 会缺失，TPOT/goodput 标注 n/a |
| `ignore_eos` 400 | 该版本不接受 vLLM 扩展字段 | 在 `run_bench.sh` 里加 `--no-ignore-eos`；输出长度会变，结果里注明 |

---

## 10. 成本、清理、验收

### 10.1 成本

| 项 | 单价 | 4h 成本 |
|---|---|---|
| 2×L4 VM + 130GB 存储 | 约 `$0.55–0.70/h` | 约 `$2.2–2.8` |
| 安装/排障 +1h | 同上 | 约 `$0.6–0.7` |
| 合计 | — | **约 `$3.0–3.5`** |

D3 后余额约 `$14.81`；D4 后约 `$11.3`。实付以 Vast 账单为准。

### 10.2 清理

```bash
cd "${LAB}"

# 1. 删 router（会删 EPP/Envoy/InferencePool/Service）
helm uninstall d4-router -n d4

# 2. 删模型服务器和 namespace
kubectl delete -n d4 -f scripts/d4/modelserver.yaml
kubectl delete namespace d4

# 3. 如果装了 Lab 0
kubectl delete scaledobject vllm-http -n default --ignore-not-found
kubectl delete interceptorroute vllm-qwen3-8b -n default --ignore-not-found
kubectl delete svc vllm-qwen3-8b-proxy -n default --ignore-not-found
helm uninstall http-add-on -n keda

# 4. 结果先 scp 回本地，再 Destroy VM
mkdir -p results/d4
scp root@<host>:/results/* results/d4/
```

> GAIE CRD 是集群级的；单机 k3s 直接 Destroy VM 即可，不用清理。不要把 CRD 删到共享集群。

### 10.3 验收清单

- [ ] 2×L4 VM，`nvidia.com/gpu` allocatable = 2；记录 driver / power limit；
- [ ] 两个 vLLM Pod 各 1 GPU，`/v1/models` 返回 `qwen3-8b`；
- [ ] `/v1/completions/render` 返回 `token_ids`（precise 路径）；
- [ ] EPP `active_subscribers=2`，`messages_received_total` 增长；
- [ ] `InferencePool` + EPP + Envoy Ready；`d4-router-epp:80` 可访问；
- [ ] smoke test：同一前缀集中到一个 Pod，hit rate 明显高于另一个；
- [ ] `peakPrefillThroughput` 已校准（或明确写“gate 关闭”）；
- [ ] `direct` / `precise` 各 3 轮；`random` 至少 1 轮（时间够就 3 轮）；
- [ ] 每轮前 reset cache；precise 每轮前重启 EPP；
- [ ] P99 表 + 命中率表 + 每 Pod 分布 + `d4-ttft.png`；
- [ ] 故障表至少跑 EPP FailOpen；时间够再跑 FailClose / render 404；
- [ ] B 线运维图 + 10 分钟讲法；
- [ ] `results/d4/` 提交 + push；VM Destroy；成本记录。

### 10.4 结果目录

```text
results/d4/
  direct-run1.json
  direct-run2.json
  direct-run3.json
  random-run1.json
  precise-run1.json
  precise-run2.json
  precise-run3.json
  metrics-before-*.txt
  metrics-after-*.txt
  d4-ttft.png
  summary.md          # 表 + 一句话归因 + 故障记录 + 成本
```

`summary.md` 模板：

```markdown
# D4 summary

## Setup
- GPU / driver / power limit:
- Model / vLLM / llm-d / GAIE:
- 2 vLLM pods, 1 GPU each; EPP replicas: 1
- `peakPrefillThroughput`:

## Results (median of 3 runs)
| arm | TTFT P50 | TTFT P95 | TTFT P99 | TPOT P95 | output tok/s | goodput | hit rate |
|---|---|---|---|---|---|---|---|
| direct | | | | | | | |
| random | | | | | | | |
| precise | | | | | | | |

## Attribution
- 一句话：
- 证据：per-pod request distribution / EPP predicted cached share / render latency

## Failures
- FailOpen:
- FailClose:
- render 404 / KV events / block size:

## Cost
- Vast charges:
- Runtime:
- 备注：
```

### 10.5 4h 时间盒

> 4h 是**登录 VM 之后**的净时间；租 VM + 装 k3s/NVIDIA runtime 另加 45–60 min。要压到 4h，复用 D3 的 k3s 安装步骤和镜像/权重缓存。

| 时间 | 动作 | 必须产出 |
|---|---|---|
| 0:00–0:30 | 预检 GPU/k3s、下载权重/镜像 | `nvidia.com/gpu=2` |
| 0:30–1:15 | 部署 2×vLLM；验证 `/v1/models`、render、KV events | 2 Pod Running |
| 1:15–1:45 | 装 GAIE CRD + router；验证 InferencePool/EPP | EPP Ready，subscribers=2 |
| 1:45–2:15 | smoke test；校准 `peakPrefillThroughput` | 集中路由 + 校准值 |
| 2:15–3:15 | 跑 direct/precise（random 可选），每轮 reset | 6–9 份 JSON |
| 3:15–3:45 | 采样 metrics、画图、写表 | P99 图 + 命中率 |
| 3:45–4:00 | 故障测试（至少 FailOpen）、清理、scp | 故障表 + 成本 |

**砍单顺序**：Lab 0 → random arm 的第 2/3 轮 → FailClose/render 404 故障 → 校准（改 gate=100000 并注明）。**不要砍**：direct vs precise、cache reset、EPP subscribers、P99 表。

### 10.6 B 线简历 bullet（执行后填，选 1–2 条）

- 在 2×L4 上用 llm-d 1.0 / Gateway API Inference Extension 部署 precise prefix-cache routing：对比 Service round-robin，TTFT P99 从 `____ ms` 降到 `____ ms`（`__%`），加权 prefix hit rate 从 `__%` 升到 `__%`；用 EPP random 控制组分离路由算法与代理固定开销。
- 为 EPP / `InferencePool` 设计故障演练：EPP FailOpen/FailClose、render 404、KV events 丢失、后端不健康；记录检测指标（`active_subscribers`、`index_lookup_*`、`prefix_cache_hits/queries`）和处置顺序，明确单副本 EPP 的可用性边界。

---

## 11. Sources

- llm-d Quickstart：<https://llm-d.ai/docs/getting-started/quickstart>
- llm-d Optimized Baseline：<https://llm-d.ai/docs/well-lit-paths/foundations/optimized-baseline>
- llm-d Precise Prefix-Cache Aware Routing：<https://llm-d.ai/docs/well-lit-paths/foundations/precise-prefix-cache-routing>
- llm-d InferencePool API：<https://llm-d.ai/docs/api-reference/inferencepool>
- llm-d EPP Configuration：<https://llm-d.ai/docs/architecture/router/configuration>
- llm-d Router Proxy（standalone / gateway）：<https://llm-d.ai/docs/architecture/router/proxy>
- llm-d `peakPrefillThroughput` calibration：<https://github.com/llm-d/llm-d/tree/release-1.0/guides/recipes/router/calibration>
- Gateway API Inference Extension：<https://gateway-api-inference-extension.sigs.k8s.io/>
- KEDA HTTP Add-on 安装：<https://keda.sh/http-add-on/0.16/operations/installation/>
- KEDA HTTP Add-on `InterceptorRoute`：<https://keda.sh/http-add-on/0.16/reference/interceptorroute/>
- KEDA HTTP Add-on 架构：<https://keda.sh/http-add-on/0.16/concepts/architecture/>
- vLLM Automatic Prefix Caching：<https://docs.vllm.ai/en/latest/features/automatic_prefix_caching>
- vLLM Benchmark Suites：<https://docs.vllm.ai/en/latest/benchmarking>
- D3 文档（k3s / 冷启动 / KEDA / 驱逐）：[`d3-k8s-vllm-learning.md`](./d3-k8s-vllm-learning.md)
- 计划：`ai-cloud-native-week-plan.md` §3（B 线学习）、§4（D4）、§5（B 线三个数）、§6（llm-d 四问）
