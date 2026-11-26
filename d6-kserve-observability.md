# D6 学习文档：KServe 服务抽象 + 推理可观测性（KServe + vLLM + OTel）

> 状态：**planned（2026-11-26 合并原 D6/D7；尚未在 Vast 执行）**。本文把原计划的 **D6（KServe 服务抽象）** 和 **D7（Inference Observability）** 合成一个 lab，按内容分成两段：**D6a KServe（3h）** + **D6b 观测（2–3h）**。两段用同一台 VM、同一套 manifest，**不重跑 D1–D4**。
>
> 性质：**B 线 serving 抽象 + 平台可观测性 lab**，不是 A 线引擎性能 lab。D5 回答“谁能拿 GPU”，D6 回答“模型怎么被部署、怎么被观测”。
>
> 版本基线：**KServe `v0.21.0`**、k3s `v1.37.2+k3s1`、Kubernetes `v1.37`（KServe 要求 ≥1.32）、vLLM `v0.34.0`、Qwen3-8B-AWQ、OTel Collector `0.166.0`、DCGM exporter `4.9.0`。
>
> 机器：优先复用 **D5 的单卡 VM（显存 ≥12GB 时）**；新租选 1×RTX 4090 24GB。**canary 需要 2 张卡；单卡跳过（`trafficPercent: 0` 也会创建第二个 Deployment，仍要 GPU）**（见 §8.4）。**不要按 L4 VM 租**：Vast 的 L4 只有容器，k3s 起不来。
>
> 预算：2×3060 参考 **`$1.5–1.8`（含 buffer）**；1×4090 或复用 D5 单卡按 Vast 实时价重算。实际账单写进 `results/d6/cost.txt`，不要用估算替代。

---

## 0. 先看结论（执行前先记住）

1. **KServe 是控制面，不是更快的引擎。** 它把 Deployment / Service / Ingress / HPA / revision 收成一个 `InferenceService` CRD；TTFT/TPOT 不会因为装了 KServe 就变好。
2. **LLM 优先 Standard/RawDeployment，不优先 Serverless。** Knative 的 scale-to-zero 对长驻 LLM 通常不划算；Standard mode 本身也**不支持 HTTP 0→1**。
3. **`InferenceService` 和 `LLMInferenceService` 不是二选一。** 前者是通用 serving 抽象（HuggingFace runtime + vLLM backend）；后者是 GenAI 专用 CRD，底层组合 llm-d/EPP。
4. **D6b 不是再装一套 Prometheus。** 微服务 obs 的骨架不变，补的是 TTFT/TPOT、KV cache、goodput、prefix 命中、$/1M tokens 这些推理语义。
5. **不重跑 D4。** D6b 把 D4 的 EPP/vLLM manifest 当被观测对象，跑 10 分钟负载即可；EPP trace 是 optional。
6. **D6 的验收是证据，不是“装好了”**：KServe Ready + raw vs KServe 冷启动表 + 1 张 dashboard + 1 条 trace + 1 条告警 + 1 次 game day。

---

## 1. 学习目标与验收

### 1.1 三个证据

| # | 证据 | 说明 |
|---|---|---|
| 1 | **raw vs KServe 冷启动表** | 镜像拉取 / 权重下载 / 引擎初始化 / Ready；同一模型、同一 vLLM 镜像 |
| 2 | **KServe 运维行为** | canary Deployment 10%（需 2 卡；单卡跳过）、HPA 1→2、rollback；scale-to-zero 的限制 |
| 3 | **推理 dashboard + trace + alert** | TTFT/TPOT/goodput/KV/GPU；一条 `gateway→vLLM` trace；一条 SLO 告警 |

### 1.2 B 线交付物

- 一个 `InferenceService`（READY=True）+ 一个 raw Deployment 对照；
- 一张 dashboard 截图 + PromQL 清单；
- 一条 OTel trace（`gen_ai.*` attributes）；
- 一条 TTFT P99 或 KV > 90% 告警；
- `results/d6/summary.md` + `cost.txt` + `game-day.md`。

### 1.3 时间盒

**D6a（3h）**

| 时间 | 动作 | 判据 |
|---|---|---|
| 0:00–0:25 | 复用 D5 VM；确认 k3s/GPU/镜像 | `nvidia.com/gpu=1`；canary 另需 2 卡，按 §8.4 单卡跳过 |
| 0:25–0:55 | 装 cert-manager/Gateway API/Envoy/KServe | `kserve` pod 全 Ready |
| 0:55–1:35 | raw Deployment + benchmark | `/v1/models` 200；记录冷启动 |
| 1:35–2:15 | `InferenceService` + benchmark | `READY=True`；同一 workload |
| 2:15–2:45 | canary / HPA（单卡跳过 canary） | stable + canary Deployment；副本 1→2 |
| 2:45–3:00 | 记录 | `results/d6/` |

**D6b（2–3h）**

| 时间 | 动作 | 判据 |
|---|---|---|
| 0:00–0:30 | Prometheus/Grafana/DCGM（复用 D3 最好） | GPU 指标可见 |
| 0:30–1:00 | vLLM PodMonitor + dashboard | TTFT/TPOT/KV/队列有曲线 |
| 1:00–1:30 | OTel Collector + vLLM trace | 1 条 trace |
| 1:30–2:00 | 告警 + game day | 告警触发/恢复有记录 |
| 2:00–2:30 | 记录/清理 | `summary.md` |

### 1.4 不做什么

- 不装完整 Knative/Serverless（除非专门测 0→1，额外 30–45 min）；
- 不做 `LLMInferenceService` 的性能/PD 实验（optional，见 §10）；
- 不做 Kubeflow Pipelines / MLflow / OpenShift AI；
- 不做 MIG/DRA/Dragonfly；
- 不重跑 D1–D4 的全量对比。

### 1.5 D6 学习问题索引

执行和阅读时反复问到的概念问题，统一收在 §3.8：

| 问题 | 位置 |
|---|---|
| D6 到底要几张 GPU？ | §2.1、§3.8 Q1 |
| ISVC 是什么？ | §3.8 Q2 |
| InferenceService 和 LLMInferenceService 怎么选、怎么结合？ | §3.8 Q3、§13 Q3 |
| LWS 是什么？ | §3.8 Q4 |
| TP / DP / EP 分别是什么？ | §3.8 Q5 |
| PP 是什么？PP 和 PD 有什么区别？ | §3.8 Q6 |
| `ClusterServingRuntime` 是什么？§6.2 检查 runtime 在干嘛？ | §3.8 Q7 |
| ServingRuntime 和容器 runtime 是一回事吗？ | §3.8 Q8 |

---

## 2. 环境、版本、预算

### 2.1 机器

| 方案 | 说明 |
|---|---|
| **复用 D5 单卡 VM** | 推荐（显存 ≥12GB 时）；D5 只占位 GPU，D6 直接换模型；canary 单卡跳过；增量 5–6h |
| 1×RTX 4090 24GB | 单卡更宽裕；按 Vast 实时价 |
| 1×L4 VM | **不可行**：Vast L4 只有容器，k3s 需要 VM |

**要几张 GPU：**

| 目标 | 最少 GPU | 说明 |
|---|---:|---|
| D6a 核心：raw vs ISVC | 1 | 顺序跑：先 raw，删掉，再 ISVC |
| D6a 并行对比 | 2 | raw 和 ISVC 各 1 卡，省时间 |
| canary（stable + canary） | 2 | 两个 Deployment 各要 1 卡；单卡跳过 |
| D6b 观测 | 1 | Prometheus/Grafana/OTel/DCGM 不额外占 GPU |
| 显存 | ≥12GB | Qwen3-8B-AWQ 约 5.7GB；24GB 更宽裕 |

> 结论：**KServe 核心 1 张卡就能做；2 张卡是为了并行对比和 canary。**

### 2.2 版本矩阵

| 组件 | 版本 | 备注 |
|---|---|---|
| KServe | `v0.21.0` | 2026-09-25 发布；K8s ≥1.32 |
| k3s | `v1.37.2+k3s1` | D3/D5 已验证 |
| Kubernetes | `v1.37` | 满足 KServe 要求 |
| cert-manager | `v1.17.0` | KServe 要求 ≥1.15 |
| Gateway API | `v1.2.1` | Standard 文档；LLMISvc 依赖可能更高 |
| Envoy Gateway | `v1.8.1` | KServe Standard 的 GatewayClass |
| vLLM | `v0.34.0` | raw 与 custom runtime 对齐 |
| 模型 | `Qwen/Qwen3-8B-AWQ` | 约 5.7GB，12GB 卡可跑 |
| OTel Collector | `0.166.0` | `otel/opentelemetry-collector-contrib` |
| DCGM exporter | `4.9.0` | GPU 指标 |
| KServe 内置 runtime | `kserve-vllmserver` | 镜像 tag 以安装方式为准：repo 脚本是 `latest`，release manifest 是 `v0.21.0`；本文用 custom runtime 对齐 v0.34.0 |

### 2.3 七个版本/路径坑

1. **KServe v0.21 的 runtime 清单叫 `kserve-cluster-resources.yaml`**，不是老文档里的 `kserve-runtimes.yaml`。
2. **Standard mode 不支持 HTTP scale-to-zero。** KServe 文档明确写了；要测 0→1 必须 Knative/Serverless。
3. **`InferenceService` 是 `serving.kserve.io/v1beta1`；`LLMInferenceService` 是 `serving.kserve.io/v1alpha2`。** 不要把 v1alpha1 的旧示例直接抄到 v0.21。
4. **不要把 `InferenceService` 建在 `kserve` 控制面 namespace。** KServe 会跳过 storage-initializer 注入，Pod 报 `/mnt/models` 不存在。
5. **内置 `kserve-vllmserver` 的 vLLM 版本和 D1–D4 的 `v0.34.0` 不一致。** 要比 TTFT/TPOT，用本文的 custom `ClusterServingRuntime`；否则只比冷启动/运维行为，并明确 confound。
6. **Standard mode 的 canary 用 `spec.canary`，不是 `canaryTrafficPercent`。** 后者是 Knative 字段，在 Standard mode 会被静默忽略；v0.20+ 用 `spec.canary`（`predictor.name` + `trafficPercent`）。
7. **repo 安装脚本生成的 runtime tag 是 `latest`，不是 `v0.21.0`。** `./hack/kserve-install.sh` 使用 `config/runtimes/kustomization.yaml` 的 `newTag: latest`；release asset `kserve-cluster-resources.yaml` 才 pin `v0.21.0`。不要假设内置 runtime 的 vLLM 版本，先查 `.spec.containers[0].image`。

### 2.4 预算

| 项 | 金额 |
|---|---|
| 2×3060 5–6h | `$1.31–1.57` |
| buffer | `$0.20` |
| 合计 | **≈ `$1.5–1.8`** |

> 上表是 2×3060 参考场景；如果复用 D5 单卡或新租 1×4090，按 Vast 实时价重算，不套用这个合计。

执行后把 Vast 实际账单写进 `results/d6/cost.txt`。

---

## 3. 概念：KServe 在栈里的位置

### 3.1 两层，不是二选一

```text
KServe InferenceService（控制面：CRD、Deployment、Service、Ingress、HPA、revision）
  └─ vLLM（engine：continuous batching、KV cache、OpenAI API）

KServe LLMInferenceService（GenAI 控制面）
  └─ llm-d / GAIE / EPP（路由：prefix cache 感知、PD、flow control）
       └─ vLLM workers
```

- **KServe + vLLM**：企业标准路径；KServe 管部署/流量/生命周期，vLLM 管推理。
- **KServe + llm-d + vLLM**：`LLMInferenceService` 的 advanced 路径；KServe 生成 Gateway/HTTPRoute/InferencePool/EPP。
- **llm-d + vLLM（无 KServe）**：D4 已做；不是必须套 KServe。

### 3.2 核心对象

| 对象 | 作用 |
|---|---|
| `InferenceService` | 一个模型服务的声明：predictor/transformer/explainer |
| `ServingRuntime` / `ClusterServingRuntime` | 运行时模板：镜像、args、probe、支持的 modelFormat |
| `InferenceGraph` | 多模型编排（本文不做） |
| `LLMInferenceService` | GenAI 专用：vLLM workers + Gateway/HTTPRoute/InferencePool/EPP |
| `LocalModelCache` | 节点本地模型缓存（optional） |

> `LeaderWorkerSet`（LWS）不是 KServe CRD，而是 Kubernetes SIG Apps 的 workload API；`LLMInferenceService` 在多机/多 Pod 场景会创建它。见 §3.8 Q4。

### 3.3 Standard vs Serverless

| | Standard（RawDeployment） | Serverless（Knative） |
|---|---|---|
| 底层 | Deployment + Service + Ingress/Gateway + HPA | Knative Service + Revision |
| scale-to-zero | **不支持 HTTP 0→1** | 支持 |
| 冷启动 | 可预测 | 多一层 Knative/queue-proxy |
| LLM 适配 | **推荐** | 不推荐长驻 LLM |
| 依赖 | cert-manager + Gateway API/Envoy | 额外 Knative + Istio/Kourier |

### 3.4 canary / autoscaling

- **canary（Standard）**：`spec.canary` 列表，每项 `predictor.name` + `trafficPercent`；KServe 创建 `{isvc}-{name}-predictor` Deployment，按比例分流。
- **canary（Serverless）**：才用 `canaryTrafficPercent`；它在 Standard mode 会被静默忽略。
- **HPA**：`minReplicas`/`maxReplicas`；Standard mode 默认按 CPU，LLM 应换 KEDA/Prometheus 按 `num_requests_waiting` 或自定义指标。
- **rollback**：删掉 canary entry（只把 `trafficPercent` 设 0 不一定会删掉 canary Deployment）；记录 stable/canary Deployment。
- **scale-to-zero**：Standard 不支持；LLM 冷启动代价高，生产一般 `minReplicas >= 1`。

### 3.5 推理 observability 的五个增量

| 维度 | 微服务常见 | 推理层补充 |
|---|---|---|
| 延迟 | HTTP P99 | TTFT、TPOT/ITL、E2E、queue/prefill/decode |
| 吞吐 | RPS | input/output tok/s、goodput |
| 饱和度 | CPU/memory | KV cache、running/waiting、preemption |
| 路由 | upstream 5xx | EPP prefix hit、后端倾斜、重试 |
| 成本/质量 | 无 | $/1M tokens、GPU-hours、eval pass |

### 3.6 指标地图

| 层 | 关键指标 | 回答 |
|---|---|---|
| Gateway | RPS、5xx、429、上游延迟 | 入口是否限流/超时？ |
| KServe | `READY`、revision、HPA 副本、reconcile 错误 | 控制面是否正常？ |
| vLLM | TTFT、TPOT、E2E、running/waiting、KV%、prefix hit、preemption | 引擎慢在哪？ |
| GPU/DCGM | util、显存、功耗、XID、throttle | 硬件是否降频/故障？ |
| K8s | Pending、重启、OOMKilled、cold start | 调度/生命周期是否正常？ |

### 3.7 常见误区

- `nvidia-smi` 的 GPU util ≠ `vllm:gpu_cache_usage_perc`；
- 客户端 TTFT ≠ 服务端 TTFT；
- 平均 TPOT 会掩盖长尾，ITL P99 才能看抖动；
- GPU util 40% 不代表空闲，decode 可能已经 KV-bound；
- 不要用 `request_id` / prompt 做 metric label（高基数）；
- 默认不要记录 prompt/completion 原文。

### 3.8 学习问答：ISVC、LLMISVC、LWS、并行

这一节记录 D6 学习过程中提出的概念问题。命令、参数、指标名保持英文；结论以 KServe `v0.21.0` 和 vLLM `v0.34.0` 为准。

#### Q1：D6 到底要几张 GPU？

| 目标 | 最少 GPU | 说明 |
|---|---:|---|
| D6a 核心：raw vs ISVC | 1 | 顺序跑：先 raw，删掉，再 ISVC |
| D6a 并行对比 | 2 | raw 和 ISVC 各 1 卡，省时间 |
| canary（stable + canary） | 2 | 两个 Deployment 各要 1 卡；单卡跳过 |
| D6b 观测 | 1 | Prometheus/Grafana/OTel/DCGM 不额外占 GPU |
| 显存 | ≥12GB | Qwen3-8B-AWQ 约 5.7GB；24GB 更宽裕 |

> **结论：核心 1 张卡就能做；2 张卡是为了并行对比和 canary。** 单卡上 `trafficPercent: 0` 仍会创建第二个 Deployment，不能当 dark launch。

#### Q2：ISVC 是什么？

`ISVC` 是 `InferenceService` 的 `kubectl` 短名，是 KServe 的通用 serving CRD：

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: qwen3-8b
```

它用一份 YAML 描述“模型从哪来、用哪个 runtime、要几副本、怎么扩缩容、怎么分流”，KServe 控制器再翻译成：

```text
InferenceService
├── Deployment qwen3-8b-predictor
├── Service    qwen3-8b-predictor
├── HPA        qwen3-8b-predictor
└── （可选）Ingress/HTTPRoute、canary Deployment
```

关键点：

- ISVC 是**控制面抽象**，不是推理引擎；底层仍然是 vLLM。
- 它不会让 TTFT/TPOT 变好；D6 的 raw vs ISVC 就是验证“KServe 只加运维抽象，不换引擎”。
- 与 raw Deployment 的区别是：模型存储、runtime 模板、revision、canary、HPA、Gateway 都收进一个 CRD。

#### Q3：InferenceService 和 LLMInferenceService 怎么选、怎么结合？

**两者是 KServe 的双轨，不是新旧版本，也不是二选一。**

| 维度 | `InferenceService` | `LLMInferenceService` |
|---|---|---|
| API | `serving.kserve.io/v1beta1`，stable | `serving.kserve.io/v1alpha2`，alpha |
| 定位 | Predictive AI + 基础单机 LLM | GenAI / LLM 专用 |
| 控制器 | `kserve-controller-manager` | 独立的 `llmisvc-controller-manager` |
| 底层 | Deployment/Service/HPA/Ingress，或 Knative | Deployment 或 **LWS** + Service + Gateway/HTTPRoute + **InferencePool/EPP** |
| 路由 | 普通 Ingress/Gateway，按副本负载均衡 | **KV cache / prefix-aware**、PD 分离路由 |
| 并行 | 单机为主 | TP/DP/EP、多机多卡 |
| 扩缩容 | HPA；Standard 不支持 HTTP 0→1 | HPA/KEDA，支持 **scale-to-zero** |
| 流量 | `spec.canary` | Gateway/HTTPRoute 流量管理，字段体系不同 |
| 依赖 | cert-manager，可选 Gateway | Gateway API、GIE、LWS、Envoy Gateway、KEDA、llm-d |
| 典型负载 | sklearn/TF/PyTorch、embedding、rerank、≤7B 单机 LLM | 7B–405B、多机、PD 分离、LoRA 多租户 |

> 版本注意：v0.21 源码的 storage version 是 `v1alpha2`，部分文档示例仍写 `v1alpha1`；以集群里的 `kubectl api-resources | grep -i llm` 为准。

**怎么选：**

```text
传统 ML / embedding / rerank
  → InferenceService

LLM，单机单卡、一个模型、标准 OpenAI API
  → InferenceService

多机多卡、TP/DP/EP、PD 分离、KV-aware 路由、KEDA 0→1
  → LLMInferenceService

7B–70B，单机多卡，暂时不需要 PD/EPP
  → 先 InferenceService；不够再迁 LLMInferenceService
```

**怎么结合：**

- **同集群双轨**：ISVC 跑小模型/embedding/分类器，LLMISVC 跑旗舰 LLM；共享同一个 Gateway 和 PVC/模型缓存，按 host/path 分流。
- **迁移路径**：ISVC 做 POC → 需要多机/PD/EPP 时新建 LLMISVC；同一模型 URI、同一 vLLM 镜像，压测后再切流。
- **不要嵌套**：LLMISVC 不是建在 ISVC 之上，两者是并列 CRD；LLMISVC 不会创建 ISVC，ISVC 也不会创建 LLMISVC。
- **不要同一 endpoint 双挂**：同一 host/path 同时挂 ISVC 和 LLMISVC 会导致路由冲突。

D6 是单卡 RTX 3060，选 ISVC 是正确的；LLMISVC 会多引入 Gateway/EPP/LWS 控制面，但单卡没有 PD/多机/KV-aware 的收益。

#### Q4：LWS 是什么？

`LWS` = **LeaderWorkerSet**，Kubernetes SIG Apps 的 workload API：

```yaml
apiVersion: leaderworkerset.x-k8s.io/v1
kind: LeaderWorkerSet
```

它把“1 个 leader + N 个 worker”的 Pod 组当作**一个副本单位**：

```text
replicas=1, size=2
→ 1 个组
→ 1 个 leader + 1 个 worker
```

它解决 Deployment/StatefulSet 表达不了的问题：

| | Deployment | StatefulSet | LeaderWorkerSet |
|---|---|---|---|
| 副本单位 | 单个 Pod | 单个 Pod | **一个 Pod 组** |
| 身份 | 随机 | 稳定序号 | 稳定序号 + leader/worker 角色 |
| 扩缩容 | 扩 Pod 数 | 扩 Pod 数 | **扩组数** |
| 组内关系 | 无 | 无 | leader + workers，互相发现 |
| 滚动更新 | 单 Pod | 单 Pod | **整组一起更新** |
| 典型场景 | 无状态服务 | 数据库/有状态服务 | **多机 LLM 推理、分布式训练** |

核心字段和行为：

- `spec.replicas`：组的数量，不是 Pod 数量；
- `leaderWorkerTemplate.size`：每组 Pod 总数，**包含 leader**；`size=2` 表示 1 leader + 1 worker；
- `leaderTemplate` 可选，不写就复用 `workerTemplate`；
- 注入 `LWS_LEADER_ADDRESS`、`LWS_GROUP_SIZE`、`LWS_WORKER_INDEX`；
- `startupPolicy`：`LeaderReady` 等 leader Ready 再起 worker；`LeaderCreated` 等 leader 创建后起 worker；
- 支持组级滚动更新、组级重启、HPA scale subresource；
- gang scheduling 仍是 **alpha**，不要当作默认保证；
- LWS 不分配 GPU；GPU 仍由 device plugin + kube-scheduler 分配。

在 LLMISVC 里，`spec.worker` 存在时控制器会创建 LWS 而不是 Deployment；`size = data / dataLocal`。例如：

```yaml
parallelism:
  data: 8
  dataLocal: 2
```

得到 `size = 8 / 2 = 4`，即 1 leader + 3 worker。

> 单卡 D6 不会创建 LWS；一个 Pod 里 2 张卡做 `TP=2` 也不需要 LWS。**只有模型跨多个 Pod/节点时才需要 LWS。**

#### Q5：TP / DP / EP 分别是什么？

| | TP | DP | EP |
|---|---|---|---|
| 全称 | Tensor Parallelism | Data Parallelism | Expert Parallelism |
| 切什么 | 层内权重/注意力头 | 请求/副本 | MoE 的 expert |
| 每张卡存什么 | 部分权重 | 完整模型 | 部分 expert |
| 通信 | all-reduce / all-gather | 推理几乎无 | all-to-all |
| 显存 | 降 | 不降 | 降 expert |
| 主要收益 | 单卡放不下、降延迟 | 提吞吐 | 跑超大 MoE、提容量 |
| 通信代价 | 高，优先 NVLink | 低 | 高，怕负载不均 |
| 典型 | 70B 单机 8 卡 TP=8 | 8B 多副本 DP=8 | DeepSeek/Mixtral 的 EP |

一句话：

> **TP 切模型，DP 切请求，EP 切专家。**

补充：

- **TP**：同一个 token 的计算分到多卡，每层通常要 all-reduce；TP degree 要能整除 attention heads/hidden size 等维度。
- **DP**：每个副本都有完整模型，各自处理不同请求；推理 DP 没有梯度同步，和训练 DP 不是一回事。
- **EP**：只对 MoE 有意义；token 经 router 选 top-k expert，再 all-to-all 发到对应 GPU。vLLM 的 `EP_SIZE = TP_SIZE × DP_SIZE`，通过 `--enable-expert-parallel` 打开。

KServe LLMISVC 的 `spec.parallelism` 直接对应这些轴：

```yaml
spec:
  parallelism:
    tensor: 4        # TP=4
    pipeline: 1      # PP=1
    data: 2          # 总共 2 个 DP 副本
    dataLocal: 1     # 每个 Pod 1 个 DP 副本
    expert: false    # 不开 EP
```

dense 模型的总 GPU 数近似：

```text
总 GPU ≈ DP × TP × PP
```

`dataLocal` 不是“本地有几张 GPU”，而是“一个 Pod 里放几个 DP 副本”；`size = data / dataLocal`。

D6 的 Qwen3-8B-AWQ 是 dense 模型，单卡配置就是：

```text
TP=1, PP=1, DP=1, EP=false
```

`max-num-seqs=16` 是连续批处理，不是 DP；HPA 1→2 是扩 Pod 副本，也不是 DP。

#### Q6：PP 是什么？PP 和 PD 有什么区别？

**PP = Pipeline Parallelism，按层切 stage：**

```text
80 层模型，PP=4：

Stage 0 / GPU0: layers 0-19
Stage 1 / GPU1: layers 20-39
Stage 2 / GPU2: layers 40-59
Stage 3 / GPU3: layers 60-79

请求 → Stage0 → Stage1 → Stage2 → Stage3 → 输出
```

特点：

- 每张卡只存一部分层，降低显存；
- stage 之间传 activation，是 point-to-point 通信，比 TP 的每层 all-reduce 更适合跨节点；
- 有 **pipeline bubble**：低并发时 stage 会空转，单请求延迟通常不占优；
- 需要足够多的 microbatch/并发来填满流水线；
- 通常要求层数能被 PP 整除，具体以 vLLM 版本约束为准。

PP 和 PD 不是一回事：

| | PP（Pipeline Parallelism） | PD（Prefill/Decode 分离） |
|---|---|---|
| 切什么 | **模型层** | **请求阶段** |
| 同一个请求 | 顺序经过所有 stage | prefill 池算完，decode 池接着跑 |
| 目的 | 模型放得下、跨机扩展 | 按阶段配资源，降 TTFT/提吞吐 |
| 通信 | stage 间 activation | **KV cache 传输** |
| KServe 字段 | `spec.parallelism.pipeline` | `spec.prefill` |
| 是否并行轴 | 是 | 更偏 serving 架构，不是 TP/DP/EP 那种轴 |

vLLM：

```bash
--pipeline-parallel-size 2
```

> **PP 是“模型太大，按层切开”；PD 是“prefill 和 decode 资源需求不同，分开部署”。**

#### Q7：`ClusterServingRuntime` 是什么？§6.2 检查 runtime 在干嘛？

`ClusterServingRuntime` 是 KServe 的**模型服务运行时模板** CRD：

> 它本身不跑 Pod，只告诉 KServe：某类模型应该用哪个镜像、什么命令、什么端口、什么探针来跑。

```yaml
apiVersion: serving.kserve.io/v1alpha1
kind: ClusterServingRuntime
metadata:
  name: kserve-vllmserver-d6
spec:
  supportedModelFormats:
    - name: vLLM
      version: "1"
      autoSelect: true
      priority: 1
  containers:
    - name: kserve-container          # 主容器必须叫这个
      image: vllm/vllm-openai:v0.34.0
      command:
        - python3
        - -m
        - vllm.entrypoints.openai.api_server
      args:
        - --port=8080
        - --model=/mnt/models
        - --served-model-name={{.Name}}
      ports:
        - name: http
          containerPort: 8080
      readinessProbe:
        httpGet:
          path: /v1/models
          port: 8080
```

ISVC 这样引用：

```yaml
spec:
  predictor:
    model:
      modelFormat:
        name: vLLM
      runtime: kserve-vllmserver-d6
      storageUri: pvc://d6-models-pvc/Qwen3-8B-AWQ
```

不写 `runtime` 时，KServe 按 `modelFormat` + `autoSelect` + `priority` 自动选择。

`ClusterServingRuntime` 和 `ServingRuntime` 的区别：

| | `ClusterServingRuntime` | `ServingRuntime` |
|---|---|---|
| 作用域 | 集群级 | namespace 级 |
| 谁维护 | 平台团队 | 租户/团队 |
| 典型用途 | 平台默认 runtime | 团队自定义镜像/参数 |
| 命令 | `kubectl get clusterservingruntime` | `kubectl -n xxx get servingruntime` |

**§6.2 在干嘛：**

`kserve-controller-manager` Ready 只说明控制面在跑；§6.2 检查的是数据面模板有没有装上：

```bash
kubectl get clusterservingruntime | grep -E 'vllm|huggingface'
kubectl get clusterservingruntime kserve-vllmserver -o yaml | head -40
```

它要确认：

1. `kserve-vllmserver` 对象存在；
2. `supportedModelFormats` 包含 `vLLM`；
3. 镜像 tag 符合预期：repo 脚本常见 `latest`，release manifest 是 `v0.21.0`；端口/args/probe 符合预期。

如果 runtime 缺失，后面创建 ISVC 会报“找不到匹配的 ServingRuntime”。所以 §6.2 是“装完 KServe 后的第一层 smoke test”。

D6 用自定义 `kserve-vllmserver-d6` 的原因：内置 `kserve-vllmserver` 的 vLLM tag 可能是 `latest` 或 `v0.21.0`，和 raw 的 `v0.34.0` 不一致；为了只比较“raw vs KServe”，不让 vLLM 版本成为变量，D6 把镜像、args、端口、probe 都对齐到 `v0.34.0`。

#### Q8：ServingRuntime 和容器 runtime 是一回事吗？

不是。`runtime` 这个词在两层出现：

| | 容器 runtime | KServe ServingRuntime |
|---|---|---|
| 例子 | `containerd`、`nvidia-container-runtime`、`runc` | `kserve-vllmserver`、`kserve-huggingfaceserver` |
| 管什么 | 怎么起容器、怎么把 GPU 挂进容器 | 怎么起模型服务、用什么镜像/端口/探针 |
| 配置位置 | k3s/containerd 配置 | Kubernetes CRD |
| D6 里的角色 | 让 Pod 能看见 `nvidia.com/gpu` | 告诉 KServe 怎么跑 vLLM |

所以“装 NVIDIA runtime”和“装 KServe ServingRuntime”是两件不同的事，不要混。

---

## 4. 目标架构

```text
D6a:
  client
    └─ Envoy Gateway (Gateway API)
         └─ InferenceService qwen3-8b
              └─ vLLM (custom ClusterServingRuntime, v0.34.0)

D6b:
  vLLM / KServe / Envoy / DCGM
    ├─ Prometheus (metrics)
    ├─ OTel Collector (traces)
    └─ Grafana (dashboard + alerts)

Optional:
  LLMInferenceService
    └─ Gateway / HTTPRoute / InferencePool / EPP (llm-d)
         └─ vLLM workers
```

---

## 5. Lab 0：VM + k3s + GPU

复用 D5 §5.0–§5.4（NVIDIA runtime、k3s、device plugin）。确认：

```bash
kubectl get nodes -o wide
kubectl describe node | grep -A2 'nvidia.com/gpu'
nvidia-smi -L
```

预期 `nvidia.com/gpu: 2`。预拉镜像和模型（可选，省冷启动）：

```bash
sudo k3s ctr images pull docker.io/vllm/vllm-openai:v0.34.0
export HF_HOME=/workspace/hf
python3 - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen3-8B-AWQ")
PY
```

> 如果复用 D5 VM，先删 D5 的占位 Job，释放 GPU；Kueue/Kyverno 可以保留，但 D6 的 `kserve-test` namespace 不要被 Kyverno 的 GPU 策略误伤。D6 是独立 lab，建议先 `kubectl delete -f scripts/d5/jobs` 或删 namespace。

---

## 6. Lab 1：安装 KServe v0.21.0（Standard）

### 6.1 用官方 install script

```bash
git clone --depth 1 --branch v0.21.0 https://github.com/kserve/kserve.git
cd kserve
./hack/kserve-install.sh \
  --kserve-version v0.21.0 \
  --standard \
  --type kserve
```

脚本会装 cert-manager、Gateway API、Envoy Gateway 和 KServe。等待：

```bash
kubectl -n kserve rollout status deploy/kserve-controller-manager --timeout=5m
kubectl -n kserve get pods
kubectl get crd | grep -E 'inferenceservice|servingruntime|llminferenceservice'
kubectl -n kserve get gateway
```

预期能看到 `kserve-ingress-gateway`（或类似名字）和 `kserve-controller-manager` Ready。

### 6.2 检查 runtime

```bash
kubectl get clusterservingruntime | grep -E 'vllm|huggingface'
kubectl get clusterservingruntime kserve-vllmserver -o yaml | head -40
```

内置 `kserve-vllmserver` 的镜像 tag 取决于安装方式：repo 的 `hack/kserve-install.sh` 用 `latest`，release asset `kserve-cluster-resources.yaml` 用 `v0.21.0`。先查实际值：

```bash
kubectl get clusterservingruntime kserve-vllmserver \
  -o jsonpath='{.spec.containers[0].image}{"\n"}'
```

本文用 `scripts/d6/20-clusterservingruntime.yaml` 的 `kserve-vllmserver-d6`（v0.34.0）对齐 D1–D4；不要拿内置 runtime 的 `latest` 做 benchmark。

### 6.3 如果 install script 失败

手动路径（仅排障用）：

```bash
# cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.17.0/cert-manager.yaml
# Gateway API
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml
# Envoy Gateway（Helm）
helm install eg oci://docker.io/envoyproxy/gateway-helm \
  --version v1.8.1 -n envoy-gateway-system --create-namespace
# KServe
helm install kserve-crd oci://ghcr.io/kserve/charts/kserve-crd \
  --version v0.21.0 -n kserve --create-namespace
helm install kserve oci://ghcr.io/kserve/charts/kserve-resources \
  --version v0.21.0 -n kserve \
  --set kserve.controller.deploymentMode=Standard \
  --set kserve.controller.gateway.ingressGateway.enableGatewayApi=true \
  --set kserve.controller.gateway.ingressGateway.createGateway=true
kubectl apply --server-side -f \
  https://github.com/kserve/kserve/releases/download/v0.21.0/kserve-cluster-resources.yaml
```

> `--server-side` 是必须的：`InferenceService` CRD 很大，client-side apply 可能 annotation 过大。

---

## 7. Lab 2：raw Deployment 控制组

### 7.0 前置：创建 namespace 和模型 PVC

Lab 1 只安装 KServe 控制面，**不会创建业务 namespace**。raw Deployment 和 ISVC 都放在 `kserve-test`，所以先执行：

```bash
cd /root
kubectl apply -f scripts/d6/00-namespace.yaml
kubectl apply -f scripts/d6/05-models-pvc.yaml

kubectl -n kserve-test get pvc
# 期望：d6-models-pvc   Bound
```

如果 PVC 不是 `Bound`，先确认模型目录存在：

```bash
ls -la /workspace/models/Qwen3-8B-AWQ/config.json
```

`05-models-pvc.yaml` 把宿主机的 `/workspace/models` 挂成 PV，ISVC 再用 `pvc://d6-models-pvc/Qwen3-8B-AWQ` 读取。模型没下载时，先补：

```bash
mkdir -p /workspace/models
HF_HOME=/workspace/hf hf download Qwen/Qwen3-8B-AWQ \
  --local-dir /workspace/models/Qwen3-8B-AWQ
```

> 顺序不能反：`00-namespace.yaml` → `05-models-pvc.yaml` → `10-raw-vllm.yaml`。直接 apply raw 会报 `namespaces "kserve-test" not found`。

然后才执行：

```bash
kubectl apply -f scripts/d6/10-raw-vllm.yaml
kubectl -n kserve-test rollout status deploy/vllm-raw --timeout=15m
kubectl -n kserve-test get pods -o wide
```

验证：

```bash
kubectl -n kserve-test port-forward svc/vllm-raw 8000:8000
curl -s http://127.0.0.1:8000/v1/models | jq
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-8b","messages":[{"role":"user","content":"hello"}],"max_tokens":32}' | jq
```

#### 7.0.1 PV、PVC、StorageClass 是什么关系

```text
宿主机目录
/workspace/models/Qwen3-8B-AWQ
        │
        ▼
PV  d6-models-pv              # 集群级存储资源，hostPath 指向宿主机目录
        │
        ▼
PVC d6-models-pvc             # namespace 级申请，在 kserve-test 里
        │
        ├─ raw Deployment：mount /models，subPath Qwen3-8B-AWQ
        └─ ISVC：pvc://d6-models-pvc/Qwen3-8B-AWQ → /mnt/models
```

| 对象 | 作用 |
|---|---|
| **PV** | 代表一块实际存储；这里是 `hostPath: /workspace/models`，容量声明 20Gi |
| **PVC** | Pod 对 PV 的申请；Pod 只认 PVC，不直接写 hostPath |
| **StorageClass** | 这里是静态 `d6-local`，不自动创建存储 |
| **Pod volumeMount** | 把 PVC 挂进容器，变成 `/models` 或 `/mnt/models` |

> **PVC 绑定的是 PV，不是 Pod。** 我们的 PVC 在 `spec.volumeName` 里直接指定了 `d6-models-pv`，所以 PVC 创建后 PV controller 就会完成绑定，**不需要先有 Pod**。Pod 只是引用 PVC；Pod 不存在时，PVC 仍然可以是 `Bound`。
>
> 绑定方向：`PVC.spec.volumeName → PV`，同时 PV 的 `spec.claimRef` 指回 PVC。一个 PVC 只能绑一个 PV，一个 PV 也只能绑一个 PVC。
>
> 例外：如果 StorageClass 是 `volumeBindingMode: WaitForFirstConsumer`，PVC 会等到有 Pod 调度时才绑定。本 lab 的 `d6-local` 是静态 PV + `volumeName`，不是这种模式，所以 apply `05-models-pvc.yaml` 后就会 `Bound`。
>
> `ReadWriteOnce` 是“单节点读写”，不是“只能一个 Pod”；同一节点上的多个 Pod 可以同时挂同一个 RWO PVC。

`20Gi` 是 PV 的声明容量；`hostPath` 不会真的限制目录大小，生产要用 CSI/配额来管。

#### 7.0.2 raw 和 ISVC 怎么挂这份模型

raw Deployment：

```yaml
volumeMounts:
  - name: models
    mountPath: /models
    subPath: Qwen3-8B-AWQ
    readOnly: true
volumes:
  - name: models
    persistentVolumeClaim:
      claimName: d6-models-pvc
      readOnly: true
```

vLLM 参数：

```text
--model=/models
```

InferenceService：

```yaml
storageUri: pvc://d6-models-pvc/Qwen3-8B-AWQ
```

KServe 解析 `pvc://` 后，把 PVC 的 `Qwen3-8B-AWQ` subPath 挂到 `/mnt/models`，**不会创建 storage-initializer，也不会复制模型**。所以 runtime 仍然是：

```text
--model=/mnt/models
```

#### 7.0.3 为什么不用 `hf://`

| | `hf://Qwen/Qwen3-8B-AWQ` | `pvc://d6-models-pvc/Qwen3-8B-AWQ` |
|---|---|---|
| 模型来源 | 每个 Pod 从 Hugging Face 下载 | 宿主机本地盘，只下载一次 |
| 冷启动 | 受网络影响，raw/ISVC 各下一次 | 只挂载，`model_download_s` 接近 0 |
| 失败模式 | HF 限流/断网、storage-initializer OOM | PVC 未 Bound、hostPath 不存在 |
| 磁盘 | 每个 Pod 的 emptyDir 各一份 | 全节点共用一份 |
| 适用 | 一次性 smoke test、无本地盘 | 本 lab 的 raw vs ISVC 对比 |

KServe 默认给 storage-initializer 的 `memoryLimit` 只有 1Gi，下载 Qwen3-8B 容易 `OOMKilled`。用 PVC 可以避开这个坑，也让 raw 和 ISVC 的冷启动对比不被“下载时间”污染。

#### 7.0.4 hostPath 的边界

这个 PVC 是**单机 lab 方案**：

- `hostPath` 只存在于当前 VM；多节点调度到别的节点会看不到模型；
- `ReadWriteOnce` 只适合单节点挂载；多副本跨节点要共享存储；
- 不是生产存储：生产用 S3/NFS/CephFS/CSI PVC，或 KServe `LocalModelCache` 做节点级缓存；
- `persistentVolumeReclaimPolicy: Retain`：删 PVC 不会删宿主机模型文件；但旧 PV 可能变成 `Released`，再次 apply 前要先清理。

#### 7.0.5 验证与排障

```bash
kubectl -n kserve-test get pv,pvc
kubectl -n kserve-test describe pvc d6-models-pvc
kubectl -n kserve-test exec deploy/vllm-raw -- ls -la /models/config.json
```

期望：

```text
NAME             STATUS   VOLUME         CAPACITY   ...
d6-models-pvc    Bound    d6-models-pv   20Gi       ...
```

常见问题：

| 现象 | 原因 | 处理 |
|---|---|---|
| PVC `Pending` | hostPath 不存在 / PV `Released` | 确认 `/workspace/models`；删旧 PV 后重新 apply `05` |
| Pod `ContainerCreating` | PVC 未 Bound | `kubectl describe pod`，先修 PVC |
| `/models/config.json` 不存在 | `subPath` 写错 | 确认 `subPath: Qwen3-8B-AWQ` |
| `namespaces "kserve-test" not found` | 没 apply `00` | `kubectl apply -f scripts/d6/00-namespace.yaml` |
| `persistentvolumeclaim not found` | 没 apply `05` | `kubectl apply -f scripts/d6/05-models-pvc.yaml` |

如果 PV 处于 `Released`：

```bash
kubectl delete pv d6-models-pv
kubectl apply -f scripts/d6/05-models-pvc.yaml
```

### 7.1 冷启动分解

```bash
# 记录删除到 Ready 的总时间
kubectl -n kserve-test delete deploy vllm-raw --wait=true
kubectl apply -f scripts/d6/10-raw-vllm.yaml
time kubectl -n kserve-test rollout status deploy/vllm-raw --timeout=15m

# 分阶段：镜像拉取 / 模型下载 / 引擎初始化 / CUDA graph / Ready
kubectl -n kserve-test describe pod -l app=vllm-raw | sed -n '/Events:/,$p'
kubectl -n kserve-test logs deploy/vllm-raw | grep -E 'Loading|model|KV|CUDA|Started|ready'
```

记录到 `results/d6/cold-start.csv`。**本节只测 raw**，先写 raw 行：

```csv
path,image_pull_s,model_download_s,engine_init_s,total_ready_s
raw,,,,
```

> KServe 行不在本节采集；等 §8.3 部署 ISVC 后，用同样的字段补 `kserve` 行，最后合并成一张表。
>
> 当前 `scripts/d6/10-raw-vllm.yaml` 用 PVC 直挂 `/workspace/models/Qwen3-8B-AWQ`，所以 `model_download_s` 记为 0（模型已在本机）。如果要测 HF 下载，把 `--model` 改回 `Qwen/Qwen3-8B-AWQ`，并单独记录下载时间。

### 7.2 benchmark

```bash
kubectl -n kserve-test run bench --rm -it --restart=Never \
  --image=vllm/vllm-openai:v0.34.0 -- \
  vllm bench serve \
  --model qwen3-8b \
  --tokenizer Qwen/Qwen3-8B-AWQ \
  --base-url http://vllm-raw.kserve-test.svc:8000 \
  --dataset-name random \
  --random-input-len 1024 \
  --random-output-len 256 \
  --num-prompts 100 \
  --max-concurrency 16 \
  --ignore-eos \
  --percentile-metrics ttft,tpot,itl,e2el \
  --metric-percentiles 50,95,99 \
  --goodput ttft:2000 tpot:100
```

保存 JSON 到 `results/d6/raw-bench.json`。

---

## 8. Lab 3：KServe InferenceService

### 8.0 前置：单卡先释放 GPU

D6 的 raw 和 ISVC 都请求 `nvidia.com/gpu: 1`。这台 VM 只有 1 张 RTX 3060，raw 不删，ISVC Pod 会一直：

```text
Pending
  Warning  FailedScheduling  0/1 nodes are available: 1 Insufficient nvidia.com/gpu.
```

所以 Lab 3 之前必须：

1. 确认 §7.1 冷启动和 §7.2 benchmark 数据已记录；
2. 删除 raw Deployment + Service；
3. 等 raw Pod 完全消失；
4. **保留 PVC/PV**；
5. 再 apply runtime + ISVC。

```bash
cd /root

# 1) 确认数据已记录；没有就先补，别急着删
ls -l results/d6/cold-start.csv results/d6/raw-bench.json

# 2) 删 raw（Deployment + Service）
kubectl -n kserve-test delete -f scripts/d6/10-raw-vllm.yaml --wait=true

# 3) 等 Pod 消失
kubectl -n kserve-test wait --for=delete pod -l app=vllm-raw --timeout=120s
kubectl -n kserve-test get pods

# 4) 再起 ISVC
kubectl apply -f scripts/d6/20-clusterservingruntime.yaml
kubectl apply -f scripts/d6/30-inferenceservice.yaml
```

**不要删：**

| 对象 | 原因 |
|---|---|
| `d6-models-pvc` | ISVC 还要用 `pvc://...` 读模型 |
| `d6-models-pv` | PVC 的底层存储，删了模型盘就没了 |
| `kserve-test` namespace | 删了 raw/ISVC 都没地方建 |

`kubectl delete -f 10-raw-vllm.yaml` 只删 Deployment 和 Service，不会删 PVC。

**2 张卡的情况：**

- 2×3060 可以 raw 和 ISVC 各占 1 卡同时跑；
- 但冷启动对比建议顺序跑，避免 CPU/网络互相干扰；
- ISVC HPA `maxReplicas: 2` 扩到 2 时仍会抢第二张卡；单卡上不要用 HPA 压测。

确认 GPU 已释放：

```bash
kubectl -n kserve-test get pods
kubectl describe node | sed -n '/Allocated resources:/,/Events:/p' | grep nvidia.com/gpu
```

### 8.1 应用 custom runtime + ISVC

> 单卡的前置步骤见 §8.0；确认 raw Pod 已删除、GPU 空闲后再执行本节。

```bash
kubectl apply -f scripts/d6/20-clusterservingruntime.yaml
kubectl apply -f scripts/d6/30-inferenceservice.yaml
kubectl -n kserve-test get inferenceservice qwen3-8b -w
```

预期：

```text
NAME        URL                                      READY   PREV   LATEST   ...
qwen3-8b    http://qwen3-8b.kserve-test.example.com  True    ...
```

如果 `storageUri` 用 `hf://`，首次会拉 storage-initializer 下载模型，5–15 分钟取决于网络/缓存。

> 本仓库的 `30-inferenceservice.yaml` 默认用 `storageUri: pvc://d6-models-pvc/Qwen3-8B-AWQ` 直挂本地模型，**不会创建 storage-initializer**，所以没有“下载模型”阶段。要测 HF 下载路径，把 `storageUri` 改成 `hf://Qwen/Qwen3-8B-AWQ`；注意 KServe 默认给 storage-initializer 的 `memoryLimit` 只有 1Gi，下载 Qwen3-8B 可能 OOMKilled，需要把 `kserve/inferenceservice-config` 的 `storageInitializer.memoryLimit` 调大。

### 8.2 访问

```bash
kubectl -n kserve get svc
# 找到 envoy-... 的 Service，port-forward 8080:80
kubectl -n kserve port-forward svc/<envoy-svc> 8080:80
SERVICE_HOSTNAME=$(kubectl -n kserve-test get inferenceservice qwen3-8b \
  -o jsonpath='{.status.url}' | cut -d/ -f3)
curl -s -H "Host: ${SERVICE_HOSTNAME}" \
  http://127.0.0.1:8080/openai/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-8b","messages":[{"role":"user","content":"hello"}],"max_tokens":32}' | jq
```

> 如果 DNS 不通，用 `status.url` 的 host + port-forward；不要直接访问 ClusterIP。

### 8.3 冷启动 + benchmark

**KServe 的冷启动数据在这里采集，不在 §7.1。** 删 Pod 前先确认 ISVC `READY=True`；删 Pod 后 KServe 会重建，记录四个阶段：

```bash
POD_LABEL='serving.kserve.io/inferenceservice=qwen3-8b'

# 1) 触发重建并计时
kubectl -n kserve-test delete pod -l "$POD_LABEL"
time kubectl -n kserve-test wait --for=condition=Ready pod \
  -l "$POD_LABEL" --timeout=15m

# 2) Pod 时间线：created / container startedAt / Ready
kubectl -n kserve-test get pod -l "$POD_LABEL" -o json > /tmp/isvc-pod.json
jq -r '.items[0] | {
  created: .metadata.creationTimestamp,
  startedAt: .status.containerStatuses[0].state.running.startedAt,
  ready: (.status.conditions[] | select(.type=="Ready") | .lastTransitionTime)
}' /tmp/isvc-pod.json

# 3) 镜像拉取和调度事件
kubectl -n kserve-test describe pod -l "$POD_LABEL" | sed -n '/Events:/,$p'

# 4) 如果有 storage-initializer（hf:// 路径），看下载耗时
kubectl -n kserve-test logs -l "$POD_LABEL" -c storage-initializer --tail=50 2>/dev/null \
  || echo 'no storage-initializer（PVC 直挂路径）'

# 5) vLLM 引擎初始化
kubectl -n kserve-test logs -l "$POD_LABEL" -c kserve-container \
  | grep -E 'Model loading took|Loading weights took|Starting vLLM|Application startup complete|Initializing model took'
```

各字段来源：

| 字段 | 从哪拿 | PVC 直挂（本仓库默认） | `hf://` |
|---|---|---|---|
| `image_pull_s` | Events 里的 `Pulled ... in Xs` | 镜像已缓存时接近 0 | 同左 |
| `model_download_s` | storage-initializer 日志起止时间 | **0**（PVC 挂载，无下载） | `Copying contents...` 到下载完成 |
| `engine_init_s` | 主容器 `Model loading took` / `Loading weights took` / `Starting vLLM` | vLLM 初始化时间 | 同左 |
| `total_ready_s` | Pod `creationTimestamp` → `Ready.lastTransitionTime` | 总时间 | 总时间 |

把结果追加到 `results/d6/cold-start.csv`：

```csv
path,image_pull_s,model_download_s,engine_init_s,total_ready_s
kserve,,,,
```

用同一个 bench 命令，把 `--base-url` 换成 KServe 的 Service/网关；保存 `results/d6/kserve-bench.json`。

### 8.4 canary

```bash
kubectl apply -f scripts/d6/40-canary.yaml
kubectl -n kserve-test get inferenceservice qwen3-8b
kubectl -n kserve-test get deploy
```

> Standard mode 没有 Knative `Revision` 对象；canary 的 PREV/LATEST 看 `InferenceService` status 列，底层是两个 Deployment。不要用 `kubectl get revisions`（那是 Serverless/Knative）。
>
> canary 会额外占 1 张 GPU：`spec.canary` 会创建第二个 Deployment（`qwen3-8b-canary-predictor`），stable + canary 各要 1 卡。**单卡上即使 `trafficPercent: 0`，这个 Deployment 仍然会被创建并需要 GPU**，所以 dark launch 不成立；单卡只能跳过 canary，或先停掉 stable 做停机验证（那不是 canary）。

观察：

- `spec.canary[].trafficPercent: 10`；
- `qwen3-8b-predictor` 和 `qwen3-8b-canary-predictor` 两个 Deployment 都在；
- 用 10–20 个请求看是否大约 1–2 个命中 canary（不要用 2 个请求下结论）。

### 8.5 HPA / 扩缩

```bash
kubectl -n kserve-test get hpa
kubectl -n kserve-test describe hpa -l serving.kserve.io/inferenceservice=qwen3-8b
```

> `30-inferenceservice.yaml` 已带 `serving.kserve.io/autoscalerClass: hpa`；Standard mode 默认就是 HPA，但显式写出来更好讲。

Standard mode 默认 HPA 按 CPU；LLM 更合理的是 KEDA/Prometheus 按 `vllm:num_requests_waiting`。D6 只验证 1→2 的机制；不要用 CPU HPA 得出“LLM 该这么扩”的结论。

### 8.6 scale-to-zero

**Standard mode 不支持 HTTP 0→1。** 如果你要测：

1. 另装 Knative/Serverless（`./hack/kserve-install.sh --serverless ...`），30–45 min；
2. 或只讲结论：LLM 冷启动 = 权重加载 + KV cache 重建，生产用 `minReplicas >= 1`。

### 8.7 可选：LocalModelCache

```yaml
apiVersion: serving.kserve.io/v1alpha1
kind: LocalModelCache
metadata:
  name: qwen3-8b
spec:
  sourceModelUri: hf://Qwen/Qwen3-8B-AWQ
  modelSize: 10Gi
  nodeGroups: [workers]
```

> `nodeGroups` 必须匹配已存在的 `LocalModelNodeGroup`；这是 optional，D6 核心不验收。没有 group 就跳过，别让 optional 卡住主线。

需要 `localmodel` 组件：

```bash
./hack/kserve-install.sh --kserve-version v0.21.0 --standard --type localmodel
```

对比“第二次 Pod 启动是否还下载模型”。D3 已做过 initContainer vs node-local PV；这里是 KServe 原生版。

---

## 9. Lab 4：推理可观测性（D6b）

> 原 D7/D4.7 的内容合并到这里。**不重跑 D4**；如果只看 KServe，观测对象是 `InferenceService` + vLLM + Envoy；如果要看 EPP，复用 D4 的 manifest 跑 10 分钟负载。

### 9.1 监控栈

优先复用 D3 的 Prometheus/Grafana。没有就装：

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace

helm repo add gpu-helm-charts https://nvidia.github.io/dcgm-exporter/helm-charts
helm install dcgm-exporter gpu-helm-charts/dcgm-exporter -n monitoring
```

确认：

```bash
kubectl -n monitoring get pods | grep -E 'prometheus|grafana|dcgm'
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
```

### 9.2 vLLM PodMonitor

```bash
kubectl apply -f scripts/d6/60-podmonitor.yaml
```

如果 Prometheus 没选 `release: monitoring`，改 label 或：

```bash
kubectl -n monitoring get prometheus -o yaml | grep -A5 podMonitorSelector
```

在 Prometheus UI 确认 `vllm:time_to_first_token_seconds_bucket` 有数据。

### 9.3 指标语义

| 指标 | 回答 | 注意 |
|---|---|---|
| `vllm:time_to_first_token_seconds` | 排队 + prefill + 首 token | 客户端 TTFT 还含网关/网络 |
| `vllm:time_per_output_token_seconds` | decode 速度 | 平均会掩盖长尾 |
| `vllm:e2e_request_latency_seconds` | 端到端 | 流式/非流式口径不同 |
| `vllm:num_requests_running` | 正在 decode 的序列 | 接近 `max_num_seqs` 说明 batch 满 |
| `vllm:num_requests_waiting` | 排队 | 比 RPS 更适合 HPA |
| `vllm:gpu_cache_usage_perc` | KV 块使用率 | 不是 GPU util |
| `vllm:cpu_cache_usage_perc` | CPU tier | D4.6 的 tiered KV |
| `vllm:num_preemptions_total` | KV 压力 | 增长说明序列被换出/重算 |
| prefix cache hit/query | 前缀复用 | 名字随版本变 |
| `DCGM_FI_DEV_GPU_UTIL` | kernel 活跃时间 | decode 可能低 util 但 KV 满 |
| `DCGM_FI_DEV_XID_ERRORS` | 硬件/驱动错误 | 出现即 critical |

PromQL 和 dashboard 面板见 `scripts/d6/63-dashboard-queries.md`。

### 9.4 OTel trace

装 Collector：

```bash
kubectl apply -f scripts/d6/62-otel-collector.yaml
kubectl -n monitoring rollout status deploy/otel-collector
```

让 vLLM 发 trace（custom runtime 的 args 加）：

```yaml
- --otlp-traces-endpoint=http://otel-collector.monitoring.svc:4317
```

> flag 以 `vllm serve --help | grep otlp` 为准；不同版本可能还要 `--collect-detailed-traces`。

期望一条 trace：

```text
POST /v1/chat/completions
  └─ vllm.generate
       ├─ queue
       ├─ prefill (TTFT)
       └─ decode (TPOT)
```

OTel GenAI 属性：`gen_ai.system`、`gen_ai.request.model`、`gen_ai.usage.input_tokens`、`gen_ai.usage.output_tokens`、`gen_ai.response.finish_reasons`。

如果要做 `gateway → EPP → vLLM`：

1. 复用 D4 的 `scripts/d4/`，起 EPP + vLLM；
2. Envoy/Gateway 开 OTel tracing，Collector 收 OTLP；
3. 把 D4 的 10 分钟 workload 跑一遍；
4. 保存 `results/d6/trace-epp.json`。

**不要为了 trace 重跑 D4 的 4h 对比。**

### 9.5 告警

```bash
kubectl apply -f scripts/d6/61-prometheusrule.yaml
kubectl -n monitoring get prometheusrule d6-inference-slo
```

至少验证一条。`scripts/d6/61-prometheusrule.yaml` 里的是 **lab 阈值**，方便在几分钟内触发/恢复：

- TTFT P99 > 0.5s 持续 1m；
- KV > 50% 持续 1m；
- waiting > 4 持续 1m；
- preemption > 0；
- GPU XID > 0。

生产按 SLO 调回，例如 TTFT P99 > 2s 持续 10m、KV > 90% 持续 10m、waiting > 10 持续 5m。

### 9.6 game day

```bash
# 1) kill 一个 vLLM pod，观察 5xx / 恢复时间
kubectl -n kserve-test delete pod -l serving.kserve.io/inferenceservice=qwen3-8b

# 2) 如果装了 LLMInferenceService/EPP，kill EPP，观察路由/队列
# 3) 记录时间线：t0 故障、t1 告警、t2 恢复
```

保存 `results/d6/game-day.md`。

### 9.7 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 没有 vLLM 指标 | PodMonitor selector/port 不匹配 | `kubectl get pod --show-labels`；确认 port 名 `http` |
| 有指标但 dashboard 空 | PromQL 指标名/标签不对 | 在 Prometheus UI 先查原始序列 |
| GPU 指标缺失 | DCGM exporter 没跑/没权限 | `kubectl -n monitoring logs ds/dcgm-exporter` |
| trace 为空 | vLLM 没开 OTLP 或 Collector 地址错 | 看 vLLM 启动日志和 Collector debug |
| 告警不触发 | `for` 太长/阈值不合适 | 先用手动查询验证表达式 |
| 高基数慢查询 | 用 request_id/prompt 做 label | 只保留 model/tenant/status 等低基数标签 |

---

## 10. 可选 Lab 5：LLMInferenceService + llm-d

时间：+1.5h；不进入 D6 验收。

```bash
./hack/kserve-install.sh \
  --kserve-version v0.21.0 \
  --standard \
  --type llmisvc

kubectl apply -f scripts/d6/50-llminferenceservice.yaml
kubectl -n kserve-test get llminferenceservice
kubectl -n kserve-test get deploy,svc,gateway,httproute,inferencepool
```

观察 KServe 生成的：

- vLLM worker Deployment；
- Gateway / HTTPRoute；
- InferencePool；
- EPP（Endpoint Picker）。

结论：**`LLMInferenceService` 不是“另一个 vLLM”，它把 llm-d/GIE/EPP 组合成一个 CRD。** 如果只看单模型高吞吐，`InferenceService` + vLLM 就够了；要多模型/prefix 感知/PD，再看 LLMISvc。

---

## 11. 故障与排障

| 现象 | 可能原因 | 排查 |
|---|---|---|
| `namespaces "kserve-test" not found` | 忘了创建业务 namespace | `kubectl apply -f scripts/d6/00-namespace.yaml` |
| `persistentvolumeclaim "d6-models-pvc" not found` | 跳过 PVC 步骤 | `kubectl apply -f scripts/d6/05-models-pvc.yaml`，确认 PVC `Bound` |
| PVC `Pending` / PV `Released` | 没有匹配 PV、旧 PV 未清理，或 StorageClass 是 `WaitForFirstConsumer` | 确认 `/workspace/models`；删旧 PV 后重新 apply `05`；看 `kubectl describe pvc` 事件 |
| `/models/config.json` 不存在 | `subPath` 写错或模型未下载 | 检查 `subPath: Qwen3-8B-AWQ` 和 `/workspace/models/Qwen3-8B-AWQ/config.json` |
| `InferenceService` READY=False | cert-manager/Gateway/storage initializer | `kubectl describe isvc`，看 Events |
| `/mnt/models` 不存在 | 建在 `kserve` 控制面 namespace | 换 `kserve-test` |
| 401 / gated model | HF token 未配 | `hf-secret` + `ClusterStorageContainer` |
| `ImagePullBackOff` | 镜像/网络/凭据 | `kubectl describe pod` |
| `Insufficient nvidia.com/gpu` | 两张卡被占 | 顺序跑；删 raw/ISVC |
| HPA 不扩 | metrics-server/CPU 指标/上限 | `kubectl describe hpa` |
| canary 没流量 | 没有 canary entry / 比例太小 | 确认 `spec.canary` 已生效；多发请求；检查 HTTPRoute 权重 |
| Gateway 502 | Envoy/Gateway 未 Ready / Host 错 | `kubectl -n kserve get gateway,svc` |
| PodMonitor 不生效 | label/port/namespaceSelector | 对照 Prometheus 配置 |
| OTel 无 trace | flag/endpoint/采样 | vLLM 日志 + Collector debug |

---

## 12. 成本、清理、验收

### 12.1 成本

| 项 | 金额 |
|---|---|
| 2×3060 5–6h | `$1.31–1.57` |
| buffer | `$0.20` |
| 合计 | **≈ `$1.5–1.8`** |

> 2×3060 参考场景；复用 D5 单卡或 1×4090 按实时价重算。

实际账单写 `results/d6/cost.txt`。

### 12.2 清理

```bash
kubectl delete -f scripts/d6/50-llminferenceservice.yaml --ignore-not-found
kubectl delete -f scripts/d6/30-inferenceservice.yaml --ignore-not-found
kubectl delete -f scripts/d6/10-raw-vllm.yaml --ignore-not-found
kubectl delete -f scripts/d6/40-canary.yaml --ignore-not-found
kubectl delete -f scripts/d6/00-namespace.yaml --ignore-not-found

# KServe 卸载（脚本会处理依赖；按需保留 cert-manager/Envoy）
cd kserve
./hack/kserve-install.sh --uninstall

# 监控栈按需删
helm uninstall monitoring -n monitoring
helm uninstall dcgm-exporter -n monitoring
```

VM 先 `scp` 结果回本地并 push，再 Destroy。

### 12.3 结果目录

```text
results/d6/
  summary.md
  cold-start.csv
  raw-bench.json
  kserve-bench.json
  dashboard.png
  trace.json
  alerts.txt
  game-day.md
  cost.txt
```

### 12.4 验收清单

- [ ] `InferenceService` READY=True；
- [ ] raw vs KServe 冷启动表（4 个阶段）；
- [ ] 同一 workload 的 raw/KServe benchmark；
- [ ] canary 10%（stable + canary Deployment；单卡跳过并记录原因）；
- [ ] HPA 1→2（或说明 Standard HPA 的限制）；
- [ ] dashboard 截图（TTFT/TPOT/KV/GPU）；
- [ ] 1 条 OTel trace；
- [ ] 1 条告警触发/恢复；
- [ ] game day 时间线；
- [ ] `cost.txt`；
- [ ] 一句话结论。

---

## 13. 面试问答（D6 版）

**Q1：KServe 和 raw Deployment 有什么区别？**

> raw 只有 Deployment/Service；KServe 多了模型 CRD、runtime 抽象、storage initializer、revision、canary、HPA、Gateway/Ingress。它不提升单请求性能，提升的是交付/运维抽象。

**Q2：KServe 和 llm-d 是什么关系？**

> KServe 是 serving 控制面；llm-d/EPP 是下面的推理感知路由层。`InferenceService` 可以只配 vLLM；`LLMInferenceService` 才会生成 Gateway/HTTPRoute/InferencePool/EPP。

**Q3：`InferenceService` 和 `LLMInferenceService` 怎么选？**

> 两者是 KServe 的双轨，不是新旧版本，也不是替代关系：`InferenceService` 面向 Predictive AI + 基础单机 LLM；`LLMInferenceService` 面向 GenAI 规模化（多机、PD、KV-aware、EP）。默认从 ISVC 开始，需要高级能力再迁 LLMISVC。两者可以同集群共存，但 LLMISVC 不是建在 ISVC 之上，不能互相嵌套。详见 §3.8 Q3。

**Q4：Standard 和 Serverless 怎么选？**

> LLM 选 Standard：Deployment 可预测、没有 Knative/queue-proxy 一层；Serverless 适合短请求/CPU 模型和 scale-to-zero。Standard 不支持 HTTP 0→1。

**Q5：为什么 LLM 不适合 scale-to-zero？**

> 冷启动要拉镜像、下载权重、初始化引擎、建 KV cache、warmup；几十秒到几分钟，P99 不可接受。生产用 `minReplicas >= 1`，低峰缩到 1。

**Q6：KServe 的 HPA 该看什么指标？**

> 默认 CPU 不适合 LLM；用 KEDA/Prometheus 按 `vllm:num_requests_waiting`、KV cache 或 goodput。CPU 高不等于 GPU 忙，GPU util 也不等于 KV 满。

**Q7：canary 怎么做？**

> Standard mode 用 `spec.canary`（`predictor.name` + `trafficPercent`）；Serverless 才用 `canaryTrafficPercent`。用模型版本、TTFT/TPOT、错误率决定是否全量。

**Q8：推理 observability 和微服务 obs 差在哪？**

> 骨架一样，语义不同：TTFT/TPOT 分解、KV cache 饱和度、prefix 命中、goodput、$/1M tokens；GPU util 不是唯一饱和度，客户端/服务端 TTFT 不能混。

**Q9：怎么证明平台没被滥用？**

> D5 的 Kueue/Kyverno + D6 的 per-tenant token/成本指标；配额、拒绝日志、chargeback 三件套。

**Q10：模型版本怎么回滚？**

> KServe canary（Standard 用 `spec.canary`）+ Deployment 回滚；镜像/模型/配置都要带版本标签；回滚前先看指标和 eval，不要只看 Pod Ready。

**Q11：LWS 是什么？**

> LeaderWorkerSet，Kubernetes SIG Apps 的 workload API；把“1 leader + N worker”作为一个副本组来管理，解决多机多 Pod 模型的组级扩缩容、滚动更新、稳定身份和互相发现问题。LLMISVC 的 `spec.worker` 存在时会创建 LWS；单卡/单 Pod 不需要。详见 §3.8 Q4。

**Q12：TP / DP / EP / PP 怎么选？**

> TP 切层内权重，优先 NVLink；PP 切层间 stage，适合跨机但有 bubble；DP 复制完整模型切请求，主要提吞吐；EP 切 MoE expert，只对 MoE 有意义。dense 模型总 GPU 近似 `DP × TP × PP`；MoE 还要把 EP 算进去。详见 §3.8 Q5、Q6。

---

## 14. 与 D1–D5 的衔接

| 文档 | 关系 |
|---|---|
| D1/D2 | TTFT/TPOT/goodput 的口径；D6 把 CSV 变成 dashboard |
| D3 | k3s/device plugin/冷启动/KEDA；D6 复用 VM 和冷启动方法 |
| D4 | EPP/llm-d 路由；D6b 的 EPP trace 复用 D4 manifest，不重跑 |
| D5 | Kueue/Kyverno 配额/准入；D6 是 serving 抽象 + 观测 |
| D6a | KServe `InferenceService`、canary、HPA、冷启动 |
| D6b | DCGM/vLLM/OTel/Grafana/SLO/game day |

**一句话串起来：**

> D3 证明“能部署”，D4 证明“路由能降 P99”，D5 证明“配额能防抢卡”，D6 证明“服务抽象能交付、指标能解释故障”。四者合起来才是 GPU 推理平台，而不是一个能跑的 Pod。

---

## 15. Sources

- KServe v0.21.0 release：<https://github.com/kserve/kserve/releases/tag/v0.21.0>
- KServe v0.21.0 runtimes kustomization（`newTag: latest`）：<https://github.com/kserve/kserve/blob/v0.21.0/config/runtimes/kustomization.yaml>
- KServe v0.21.0 release `kserve-cluster-resources.yaml`（pin `v0.21.0`）：<https://github.com/kserve/kserve/releases/download/v0.21.0/kserve-cluster-resources.yaml>
- KServe Standard 安装：<https://kserve.github.io/website/docs/admin-guide/kubernetes-deployment>
- KServe `InferenceService` + Qwen：<https://kserve.github.io/website/docs/getting-started/genai-first-isvc>
- KServe `LLMInferenceService`：<https://kserve.github.io/website/docs/model-serving/generative-inference/llmisvc/llmisvc-overview>
- KServe LLMISVC 架构（Gateway/EPP/InferencePool）：<https://kserve.github.io/website/docs/concepts/architecture/control-plane-llmisvc>
- KServe LLMISVC 依赖（Gateway API/GIE/LWS）：<https://kserve.github.io/website/docs/model-serving/generative-inference/llmisvc/llmisvc-dependencies>
- LeaderWorkerSet 文档：<https://lws.sigs.k8s.io/docs/>
- LeaderWorkerSet 仓库：<https://github.com/kubernetes-sigs/lws>
- vLLM parallelism/scaling：<https://docs.vllm.ai/en/latest/serving/parallelism_scaling/>
- vLLM data parallel：<https://docs.vllm.ai/en/latest/serving/data_parallel_deployment/>
- vLLM expert parallel：<https://docs.vllm.ai/en/latest/serving/expert_parallel_deployment/>
- KServe v0.17 LLM 发布说明：<https://kserve.github.io/website/blog/kserve-0.17-release>
- KServe v0.18 多节点/llm-d：<https://kserve.github.io/website/blog/kserve-0.18-release>
- vLLM KServe 集成：<https://docs.vllm.ai/en/stable/deployment/integrations/kserve>
- KServe LocalModelCache 示例：<https://github.com/kserve/kserve/tree/v0.21.0/docs/samples/localmodelcache>
- Gateway API Inference Extension：<https://gateway-api-inference-extension.sigs.k8s.io>
- OTel GenAI semantic conventions：<https://opentelemetry.io/docs/specs/semconv/gen-ai/>
- DCGM exporter：<https://github.com/NVIDIA/dcgm-exporter>
- Prometheus Operator PodMonitor：<https://prometheus-operator.dev/docs/operator/api/#monitoring.coreos.com/v1.PodMonitor>
- KServe 自动扩缩：<https://kserve.github.io/website/docs/model-serving/predictive-inference/autoscaling/hpa-autoscaler>
- KServe canary：<https://kserve.github.io/website/docs/model-serving/predictive-inference/rollout-strategies/canary>
