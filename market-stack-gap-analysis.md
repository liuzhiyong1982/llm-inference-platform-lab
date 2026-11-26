# 北美 A/B 线技术栈调研与 D1–D6 缺口分析

> 状态：**research snapshot（2026-11-24；2026-11-26 合并 D6）**。样本是 8 份 A 线 JD + 8 份 B 线 JD + 6 份市场/项目报告，不是统计显著性调查，也不把 JD 当课程表。
>
> 目的：回答两个问题——**北美招 A 线（Inference Platform）和 B 线（AI/ML Platform）时，实际在用什么栈？我们的 D1–D6 缺什么、先补什么？**
>
> 结论先行：**D1–D5 的“硬核推理”覆盖高于市场平均；缺口不在 vLLM 调参，而在 A 线的引擎广度/多卡/可观测，和 B 线的企业平台层/交付/安全/成本。**

---

## 0. 结论（先看这 10 条）

### 0.1 一句话

- **A 线**：我们已经有一个“能打”的 vLLM + KV + prefix routing + PD/tiered KV 故事；缺的是 **SGLang、TP/多卡、DCGM/OTel 可观测、TensorRT-LLM/Triton 的选型能力**。
- **B 线**：我们已经有一个“能打”的 K8s + GPU + 冷启动 + KEDA + 配额故事；缺的是 **KServe/OpenShift AI、Kubeflow/Ray/MLflow、Argo CD、GPU Operator/MIG/DRA、安全合规、OpenCost、RAG/MCP**。
- 两边都不是“再多学一个框架”的问题，而是**缺一个生产级 vertical slice**：A 线缺“从引擎到可观测的闭环”，B 线缺“从模型到多租户交付的闭环”。

### 0.2 A 线记分卡

| 能力 | 市场信号 | 我们的状态 | 判定 |
|---|---|---|---|
| vLLM serving / 调参 / 基准 | 几乎每份 A 线 JD 都有 | D1/D2 实测，有数字 | ✅ 强 |
| KV cache / prefix caching / 容量计算 | staff JD 必问 | D1 附录 + D2 + D4.6 | ✅ 强 |
| chunked prefill / batching / TPOT | 常见 | D2 实测 | ✅ 强 |
| 量化 + 质量门（AWQ vs FP16） | 常见 | D2 实测 + GSM8K | ✅ 强（但只覆盖 AWQ） |
| prefix-aware routing / EPP / GAIE | llm-d 岗位的核心 | D4 设计完整，未执行 | 🟡 待跑 |
| PD 分离 | staff/前沿岗位 | D4.5 已排，未执行 | 🟡 待跑 |
| tiered KV / offload | 中高频 | D4.6 已排，未执行 | 🟡 待跑 |
| **SGLang / RadixAttention** | **6/8 份 A 线 JD 明写** | **没有** | ❌ P0 |
| **TP / PP / EP / 多卡** | staff JD 明写 | 只有概念问答；没有 TP 实验 | ❌ P0 |
| **DCGM / OTel / Grafana / Nsight** | 平台岗几乎默认 | 只有 nvidia-smi + Prometheus；Grafana 被关掉 | ❌ P0 |
| TensorRT-LLM / Triton / Dynamo | 6/8、3/8、2/8 | 没有 | ❌ P1 |
| speculative decoding / FP8 / KV 量化 | 中频 | 没有 | ❌ P1 |
| flow control / token rate limiting | 上升期 | D4 只有 D 档 YAML | ❌ P1 |
| 多模型 / LoRA | 中频 | D4 明确不跑 | ❌ P2 |
| 多节点 IB/RoCE/NCCL | 前沿/大集群 | 没有环境 | ❌ P2（知道即可） |

### 0.3 B 线记分卡

| 能力 | 市场信号 | 我们的状态 | 判定 |
|---|---|---|---|
| Kubernetes 核心 | 7/8 份 B 线 JD 明写 | D3 实测（k3s） | ✅ 强 |
| GPU device plugin / 冷启动 / 驱逐 | 平台岗核心 | D3 实测 | ✅ 强 |
| KEDA 队列扩缩 / HPA | 中高频 | D3 实测 0→1、1→2 | ✅ 强 |
| Kueue / Kyverno 配额准入 | 平台岗加分 | D5 已设计，未执行 | 🟡 待跑 |
| **KServe / OpenShift AI** | **3/8 + 2/8** | **没有** | ❌ P0 |
| **Kubeflow / Ray / MLflow** | **4/8、3/8、1/8** | **没有** | ❌ P0 |
| **Argo CD / Flux / GitOps** | 3/8 | 工作日常使用；补 1 条回滚证据 | ✅ 工作覆盖 |
| **GPU Operator / NFD / MIG / DRA** | 大企业平台岗默认；样本 1/8 明写 | 手装 device plugin；MIG/DRA 只有概念 | ❌ P0 |
| **Vault / OPA / mTLS / cosign** | 受监管企业必问 | 只有 Kyverno 计划 | ❌ P0 |
| Terraform / IaC | 4/8 | 没有 | ❌ P1 |
| OpenCost / Kubecost / showback | 成本控制 2/8；OpenCost 未明写，但成本岗必问 | Q2 手工 chargeback 未执行 | ❌ P1 |
| RAG / vector DB / MCP | 3/8、1/8 | 没有 | ❌ P1 |
| SLO / on-call / DR / game day | 平台岗默认 | D3/D4 有零散故障表 | 🟡 P1 |
| Slurm / HPC | 本地 C 线为主 | 计划里另做 | ⚪ 不在 D1–D5 |

### 0.4 如果只补 6 件事

| # | 补什么 | 为什么是它 | 最小 artifact | 时间/成本 |
|---|---|---|---|---|
| 1 | **SGLang 对照实验** | A 线 JD 里出现频率仅次于 vLLM；RadixAttention 是 prefix-heavy 的默认答案 | 同一 workload 的 vLLM vs SGLang 表 + 一句选型结论 | 3h / 1×L4 / ~$2 |
| 2 | **TP=2 / 多卡实验** | staff JD 明确要求 distributed inference；我们只有单卡 + PD | 2×L4 TP=1 vs TP=2 的 TTFT/TPOT/吞吐表 | 3h / 2×L4 / ~$3 |
| 3 | **DCGM + Grafana + OTel** | 所有平台岗的“默认语言”；我们目前是 CSV + `nvidia-smi` | 1 张 GPU/推理 dashboard + 1 条 trace | 2–3h / 复用集群 / ~$1 |
| 4 | **KServe（或 OpenShift AI）** | 企业 B 线最标准的 serving 抽象；llm-d 在 KServe 下面 | 同一模型 raw Deployment vs KServe `InferenceService` 对比 | 3h / 1×L4 / ~$2 |
| 5 | **OpenCost**（Argo CD 工作已覆盖） | 成本岗必问；GitOps 日常工作已有证据 | namespace 成本表 + `$/1M tokens` | 1.5h / 复用 ~$1 |
| 6 | **Kyverno/OPA + Vault + NetworkPolicy** | 受监管企业的硬门槛；只会 Kueue 不够 | 2 条拒绝日志 + 1 个 secret 注入 + 1 条 NetworkPolicy | 3h / 复用集群 / ~$1 |

> 6 件事合计约 **17–19h + $10**；可以拆进 Q1–Q3，不需要一次租 4 卡。按 §5.1.1 的依赖顺序分配，不要按“平均每季度两个”硬拆。

---

## 1. 方法与样本

### 1.1 为什么用 JD + 项目报告

- **JD** 是“市场当前愿意付钱的关键词”，不是“正确学习顺序”。它滞后于前沿，但领先于课程。
- **项目报告/发布**（CNCF、llm-d、KServe、vLLM）是“栈正在往哪走”的信号。
- 两者交叉，才能区分“JD 里的遗留在用”与“新项目在长”。

### 1.2 样本（2026-11 快照）

**A 线（8 份，US/Canada 为主）**

| # | 公司 | title | 地点 | 关键栈 |
|---|---|---|---|---|
| A1 | DRW | AI Inference Platform Engineer | Chicago | vLLM/SGLang/TensorRT-LLM、KV、PD、TP、DCGM/Nsight/OTel、多租户 |
| A2 | Baseten | SWE, Inference Platform | NY / Toronto | K8s、routing、autoscaling、vLLM/SGLang/TensorRT-LLM/TGI/Dynamo、quota/metering |
| A3 | Anthropic | Staff/Senior SWE, Inference | Ontario | 分布式系统、routing、autoscaling、K8s/cloud、Python/Rust、batching/caching |
| A4 | Fluidstack | SWE, Inference Platform | US remote | vLLM/SGLang/TRT-LLM、PD/NIXL、IB/RoCE/NCCL、GPTQ/AWQ/FP8、Medusa/EAGLE-3 |
| A5 | Syllo | Staff SWE, AI Inference | US remote | vLLM/SGLang/TRT-LLM/Triton/TGI/Dynamo、routing、autoscaling、Python+Go/Rust/C++ |
| A6 | Thomson Reuters | Staff Inference Engineer | Toronto | 多云 GPU、K8s、profiling、GPU/CPU 瓶颈 |
| A7 | Cerebras | SWE, Development & Deployment | Toronto | vLLM/SGLang/TRT-LLM/Triton |
| A8 | JarvisLabs | Senior Inference Platform Engineer | Remote | vLLM/SGLang/Ollama/TRT-LLM/Triton |

> PhysicsX（London/NY）作为对照，不参与上面的计数；它的 JD 把 A 线栈写得最完整：vLLM/SGLang、KServe、KV、spec decode、TP/DP/EP、cache-aware routing、PD、GPU 信号扩缩、identity/secrets、Go/Rust/C++。

**B 线（8 份，US/Canada 为主）**

| # | 公司 | title | 地点 | 关键栈 |
|---|---|---|---|---|
| B1 | Mechanics Bank | AI Platform Engineer | US (CA) | OpenShift / OpenShift AI、KServe、vLLM、GPU 配额、RAG/vector store、MCP、GitOps、安全审计 |
| B2 | Wealthsimple | Senior SWE, ML Platform & Infra | Toronto | K8s、vLLM/Ray/Triton、Kubeflow/MLflow/SageMaker、benchmark |
| B3 | Rakuten Kobo | Senior ML Platform Engineer | Toronto | Kubeflow/TFX、Airflow、Terraform、GKE、Vertex AI Model Registry、Feature Store |
| B4 | Nutanix | SWE 4, Kubernetes AI Platform | Vancouver | Kubeflow、KServe、Ray、vLLM、Triton、Prom/Grafana/OTel、vector DB/RAG |
| B5 | UnitedHealth | Principal AI/ML Platform Engineer | US remote | OpenShift、GPU Operator、NFD、MIG、DCGM、Kueue、Volcano、KServe、vLLM、Argo CD、Vault、mTLS |
| B6 | Scotiabank | AI Platform Software Engineer | Toronto | K8s、Docker、cloud-native、IaC、CI/CD |
| B7 | Homebase | Platform Engineer, K8s/GitOps/AI-ML | Toronto | Kubernetes、GitOps、Flux CD、AI/ML infra |
| B8 | AI Talent Canada | MLOps / AI Platform Engineer | Remote Canada | 容器化 serving、batch inference、feature pipeline、vector store、GPU、LLM gateway |

> 说明：部分 posting 已关闭或来自聚合站（Wealthsimple、UnitedHealth、Scotiabank、Homebase），引用的是抓取时快照；投递前以官网为准。JD 计数只用于“同一批岗位里哪些词反复出现”，不是市场频率。

### 1.3 JD 原话（最能说明问题的 10 句）

> 只摘短句，完整上下文见来源链接。

| 线 | 原话 | 它说明什么 |
|---|---|---|
| A | “Deep expertise in at least one modern inference runtime such as TensorRT-LLM, vLLM, or SGLang.”（DRW） | 引擎是硬门槛，不是“了解” |
| A | “KV cache architecture, including prefix caching, block management, sizing, eviction, quantization, cache-aware routing, and multi-tier caching.”（DRW） | KV 已经细到 block/eviction/tier |
| A | “Distributed inference systems, including tensor parallelism, multi-node deployments, and disaggregated prefill and decode.”（DRW） | TP + 多节点 + PD 是 staff 线 |
| A | “Integrate and optimize inference runtimes such as vLLM, SGLang, Ollama, TensorRT-LLM, Triton…”（JarvisLabs） | 引擎广度是加分项 |
| A | “Disaggregated prefill/decode pipelines… NIXL… InfiniBand or RoCE… NCCL… GPTQ, AWQ, FP8… Medusa, EAGLE-3.”（Fluidstack） | 前沿栈的完整清单 |
| A | “Tuning continuous and chunked batching, KV and prefix caching, quantisation, speculative decoding and tensor, data or expert parallelism.”（PhysicsX） | 这些词会出现在同一份 JD |
| B | “Red Hat OpenShift, OpenShift Virtualization, and OpenShift AI… KServe or comparable serving frameworks, vLLM…”（Mechanics Bank） | 受监管企业的默认栈 |
| B | “Kubeflow, KServe, Ray, vLLM, and Triton Inference Server… Prometheus, Grafana, OpenTelemetry… vector databases (Milvus, Qdrant, PGVector)… RAG.”（Nutanix） | B 线是“平台 + ML 生命周期 + 数据” |
| B | “GPU Operator, NFD, MIG, DCGM, GPUDirect RDMA, NCCL… Kueue, Volcano… Argo CD… Vault… mTLS.”（UnitedHealth） | 大企业平台岗的 GPU/安全清单 |
| B | “Kubeflow, MLflow, Ray, Triton, or SageMaker.”（Wealthsimple） | 加拿大本地 B 线也认这套 |

### 1.4 市场报告（用来判断“往哪走”）

| 来源 | 关键信号 | 对我们的含义 |
|---|---|---|
| CNCF 2026 年度调查 | 82% 容器用户在 production 跑 K8s；66% 托管生成式 AI 的组织用 K8s 做部分/全部推理 | K8s 是底座，不再是加分项 |
| GAIE v1.0 GA | `InferencePool` / EPP 成为 K8s 推理路由的标准接口 | D4 的方向是对的，不是“llm-d 私货” |
| llm-d 1.0（2026-10-20）+ CNCF Sandbox | PD、tiered KV、precise routing 进入 CNCF 中立项目 | D4/D4.5/D4.6 的投入有市场背书 |
| KServe `LLMInferenceService` | KServe 把 llm-d 作为生成式推理的实现之一 | B 线学 KServe 和 A 线学 llm-d 不冲突，是同一栈的两层 |
| Hugging Face TGI 维护模式 | 新项目推荐 vLLM / SGLang | 不要把时间花在 TGI 上 |
| vLLM / SGLang / TensorRT-LLM 对比报道 | vLLM 是默认 baseline；SGLang 强在共享前缀；TRT-LLM 强在稳定 NVIDIA 高吞吐 | 选型要能讲“为什么不是另一个”，不能只会一个 |

### 1.5 读法（避免过度拟合）

1. **JD 计数不是市场频率。** 8 份样本只能说明“这些词在同一批岗位里反复出现”，不能推出“X% 的岗位要求”。
2. **JD 会写“or equivalent”。** 它要的是“你懂这一层”，不是“你装过这个软件”。所以补 gap 优先补**层**，不是补**牌子**。
3. **staff 岗的 JD 是“上限清单”。** 不需要每条都 hands-on；但要能对每条说出“我做过什么、没做过什么、如果要做怎么开始”。
4. **加拿大本地 B 线更保守。** OpenShift、Kubeflow、MLflow、Terraform 的出现率高于前沿 A 线；美国 remote A 线更看引擎/KV/分布式。
5. **不要为了关键词去学 Kubeflow 全家桶。** B 线的溢价在“平台交付 + 成本 + 安全”，不在“会装 Kubeflow”。

---

## 2. A 线：Inference Platform 技术栈

### 2.1 分层图

```text
┌──────────────────────────────────────────────────────────────┐
│ 接入 / 路由   GAIE InferencePool + EPP · Envoy/Istio/kgateway │
│               LiteLLM/Portkey（多 provider）· session affinity │
│               prefix-aware · load-aware · flow control        │
├──────────────────────────────────────────────────────────────┤
│ 服务抽象      KServe · llm-d · Ray Serve · NVIDIA NIM         │
│               managed（Baseten/Fireworks/Together/Modal）      │
├──────────────────────────────────────────────────────────────┤
│ 引擎          vLLM · SGLang · TensorRT-LLM · Triton · Dynamo  │
├──────────────────────────────────────────────────────────────┤
│ 分布式 / 缓存 TP · PP · EP · PD（NIXL）· NCCL · IB/RoCE       │
│               HBM prefix · CPU/FS tier · KV quant · LMCache   │
├──────────────────────────────────────────────────────────────┤
│ 调度          K8s · GPU Operator · DRA · Kueue · KEDA · LWS   │
├──────────────────────────────────────────────────────────────┤
│ 可观测 / 质量 DCGM · Prometheus · Grafana · OTel · Nsight     │
│               TTFT/TPOT/P99/goodput · eval · $/1M tokens      │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 引擎层：市场已经分成“默认 / 特化 / 边缘”

| 引擎 | 市场位置 | 什么时候用 | JD 信号 | 我们的状态 |
|---|---|---|---|---|
| **vLLM** | **默认 baseline**，硬件覆盖最广 | 通用 serving、快速上线、需要社区/生态 | 6/8 份 A 线 JD 明写 | ✅ D1/D2 实测 |
| **SGLang** | **prefix-heavy 的默认答案** | 多轮 chat、RAG、agent、结构化输出、共享 system prompt | 6/8 份 A 线 JD 明写 | ❌ 没有 |
| **TensorRT-LLM** | NVIDIA 高吞吐特化 | 稳定模型、长期高流量、愿意为 engine build 付成本 | 6/8 份 A 线 JD 明写 | ❌ 没有 |
| **Triton Inference Server** | 多框架/多模型 serving | 非 LLM 模型、传统 ML、需要 ensemble | 3/8 份 A 线 JD 明写 | ❌ 没有 |
| **NVIDIA Dynamo** | PD/大规模编排的新选择 | 超大集群、NVIDIA 生态、PD 一体化 | 2/8 份 A 线 JD 明写 | ❌ 没有（D4.5 用 llm-d） |
| **TGI** | 维护模式 | 只维护存量，不新上 | 少数 JD 仍列 | ⚪ 不学 |
| **Ollama / llama.cpp** | 本地/边缘 | 单机 demo、<10 并发 | 少数 JD 提，但明确不是生产 | ⚪ 不投入 |

**关键判断：**

- **vLLM 是必须的，SGLang 是“第二引擎”。** 不是“再学一个框架”，而是理解 **RadixAttention vs PagedAttention** 的取舍：SGLang 把共享前缀放在 radix tree 里，vLLM 用 block hash + prefix cache；前者对多轮/agent 更自然，后者生态/硬件更广。
- **TensorRT-LLM 不是必跑，但必须能讲清“什么时候值得”。** 它的代价是 engine build、模型换版、NVIDIA 绑定；收益是稳定高流量的 kernel 级优化。
- **Triton 是 B 线/A 线交叉点。** 企业里大量非 LLM 模型（分类、embedding、rerank）仍走 Triton；会 Triton 能让 B 线故事更完整。
- **Dynamo 先知道，不急着跑。** llm-d 已经覆盖 PD 的开源路径；Dynamo 是 NVIDIA 的商业/生态选项，等有 H100 集群再说。

### 2.3 服务抽象层：KServe 和 llm-d 不是二选一

```text
KServe LLMInferenceService
  └─ 底层可以用 llm-d（GAIE + EPP + vLLM）
       └─ 再底层是 vLLM / SGLang
```

| 抽象 | 谁在用 | 解决的问题 | 我们的状态 |
|---|---|---|---|
| **raw Deployment + Service** | 小团队、学习、单模型 | 最简单，但不懂 token/KV/模型 | ✅ D3/D4 会用 |
| **KServe** | 企业、OpenShift AI、Kubeflow 生态 | 模型 CRD、scale-to-zero、canary、ingress | ❌ 没有 |
| **llm-d** | AI 公司、neocloud、Red Hat/Google/IBM | 推理感知路由、PD、tiered KV | 🟡 D4 设计 |
| **Ray Serve** | Python 原生团队、Ray 生态 | 模型组合、Python 编排、autoscaling | ❌ 没有 |
| **NVIDIA NIM** | 企业 NVIDIA 栈 | 打包好的优化模型 + 推理服务 | ⚪ 知道即可 |
| **managed**（Baseten/Fireworks/Together/Modal） | 小团队、不想养 GPU | 把 GPU 运维外包 | ⚪ 知道即可 |

**对我们的含义：**

- A 线不需要“会 KServe 全家桶”，但要知道 **KServe 是 B 线的 serving 抽象，llm-d 是它下面的一层**；面试时能把两层分开讲。
- D4 的 `InferencePool`/EPP 是 GAIE 标准，不是 llm-d 私有；这一点要能讲清。
- 如果时间只够一个 B 线 serving lab，选 **KServe**，不要选 Ray Serve；KServe 在企业 JD 里更常见，而且能复用 D4 的 llm-d 知识。

### 2.4 路由 / 网关层

| 能力 | 常见实现 | JD 信号 | 我们的状态 |
|---|---|---|---|
| 推理感知路由 | GAIE `InferencePool` + EPP | D4 核心 | 🟡 设计完整，未执行 |
| 通用网关 | Envoy Gateway、Istio、kgateway、NGINX Gateway Fabric | 常见 | 🟡 D4 用 standalone Envoy |
| 多 provider 路由 | LiteLLM、Portkey、OpenRouter | B 线/AI 应用岗更多 | ❌ 没有 |
| prefix-aware | EPP precise（KV events）或 approx | D4 核心 | 🟡 待跑 |
| load-aware | queue depth、token load、active request | D4 optimized arm | 🟡 待跑 |
| session affinity | cookie/header、consistent hash | 多轮 chat 常见 | ❌ 没有 |
| flow control / fairness | EPP `flowControl`、priority bands、token rate limit | 上升期 | ❌ 只有 D 档 |
| PD routing | llm-d PD router、Dynamo | staff/前沿 | 🟡 D4.5 待跑 |

**关键判断：**

- **路由是 A 线最值钱的一层。** 会 vLLM 的人多，能把“为什么这个请求去这个 Pod”讲清楚的人少。
- **prefix-aware 只是路由的一种。** 生产还要 load-aware、session affinity、flow control；D4 已经覆盖前两个，flow control 是下一个 gap。
- **LiteLLM/Portkey 是 B 线/应用层的路由，不是 A 线的 EPP。** 不要把两者混为一谈。

### 2.5 分布式 / 缓存层

| 能力 | 市场用法 | JD 信号 | 我们的状态 |
|---|---|---|---|
| TP（tensor parallel） | 单卡放不下模型；NVLink 内 | staff JD 明写 | ❌ 只有概念 |
| PP（pipeline parallel） | 跨节点放超大模型 | 大模型岗 | ❌ 只有概念 |
| EP（expert parallel） | MoE 专家分散 | 前沿/MoE 岗 | ❌ 只有概念 |
| PD（prefill/decode 分离） | 长 prompt + 高并发；NIXL 传 KV | 2/8 份 JD 明写 | 🟡 D4.5 待跑 |
| tiered KV | HBM → CPU/FS；OffloadingConnector | 中频 | 🟡 D4.6 待跑 |
| KV 量化 | FP8/INT8 KV，省显存 | 中频 | ❌ 没有 |
| 多节点网络 | IB/RoCE、NCCL、GPUDirect | 大集群岗 | ❌ 没有环境 |
| LMCache / Mooncake | 跨实例 KV 复用 | 前沿 | ⚪ 知道即可 |

**关键判断：**

- **TP=2 是“分布式推理”的最小可信证据。** 不需要多节点，2×L4 就能测：TP=2 的通信开销是否吃掉收益、TTFT/TPOT 怎么变、KV 怎么分片。
- **PD 和 tiered KV 是“深度差异化”，不是入门门槛。** D4.5/D4.6 已经排了，先跑完再谈多节点。
- **多节点 IB/RoCE 在 Vast 上很难复现。** 不要为了简历硬租多节点；能把“为什么 L4/TCP 上 PD 可能输”讲清楚，比假装跑过 H100 集群更有说服力。

### 2.6 调度 / 可观测 / 质量

| 能力 | 常见实现 | JD 信号 | 我们的状态 |
|---|---|---|---|
| K8s 调度 | Deployment、GPU device plugin、DRA、Kueue、LWS | 平台岗默认 | ✅ D3；🟡 DRA/Kueue |
| GPU 共享 | MIG、time-slicing、MPS | 企业平台 | 🟡 只有概念 |
| 队列扩缩 | KEDA、HPA、cluster autoscaler | 平台岗默认 | ✅ D3（KEDA） |
| GPU 指标 | DCGM exporter、`nvidia-smi` | 几乎默认 | 🟡 只有 nvidia-smi |
| 应用指标 | vLLM `/metrics`、Prometheus | 默认 | ✅ D3 装过 Prometheus |
| Dashboard | Grafana | 默认 | ❌ D3 明确 `grafana.enabled=false` |
| Tracing | OTel collector、span | 中高频 | ❌ D4 只有 D 档 |
| Profiling | Nsight Systems/Compute、py-spy | staff/性能岗 | ❌ 没有 |
| 负载测试 | `vllm bench serve`、inference-perf、genai-perf、llm-d-benchmark | 常见 | ✅ D1/D2 用 `vllm bench serve`；🟡 没有 open-loop/trace replay |
| 质量评估 | lm-eval、task-specific eval、回归门 | 中频 | ✅ D2 GSM8K；🟡 没有回归 harness |
| 成本 | `$/1M tokens`、GPU 小时、闲置摊销 | 平台/成本岗 | ✅ D1 成本；🟡 chargeback 未执行 |

**关键判断：**

- **D1/D2 的指标方法已经比大多数候选人强**：TTFT/TPOT/ITL/goodput/preemption 都拆过。缺的是“生产可观测栈”的手感，不是指标定义。
- **DCGM + Grafana + OTel 是 2 小时就能补的“面试语言”**：不需要新 GPU，复用 D3 集群即可。
- **Nsight 是 staff 线的分水岭**：能定位到 kernel/内存带宽，而不是只会看 TTFT。可以不会用，但要知道它能回答什么。

### 2.7 A 线栈的“默认答案”（面试用）

> “2026 年做自托管 LLM serving，默认是 **K8s + vLLM + GAIE/EPP + Prometheus/DCGM**；共享前缀重就上 **SGLang**；稳定高流量且愿意维护 engine build 就上 **TensorRT-LLM**；需要 PD/tiered KV 就用 **llm-d**（或 KServe `LLMInferenceService`）；多模型/非 LLM 模型用 **Triton**。选型的核心不是框架，是 **workload 的 prefix 复用率、SLO、GPU 型号、团队运维成本**。”

---

## 3. B 线：AI/ML Platform 技术栈

### 3.1 分层图

```text
┌──────────────────────────────────────────────────────────────┐
│ 体验 / 自助   JupyterHub · Backstage · CLI · 模板/配额申请     │
├──────────────────────────────────────────────────────────────┤
│ ML 生命周期   Kubeflow Pipelines · MLflow · Ray · Feast        │
│               Airflow/Dagster · model registry · eval         │
├──────────────────────────────────────────────────────────────┤
│ 服务          KServe / OpenShift AI · llm-d · vLLM · Triton   │
│               Ray Serve · Seldon · BentoML                    │
├──────────────────────────────────────────────────────────────┤
│ 调度          Kueue · Volcano · KEDA · HPA · cluster autoscaler│
├──────────────────────────────────────────────────────────────┤
│ GPU           GPU Operator · NFD · device plugin · MIG        │
│               time-slicing · DRA · DCGM                       │
├──────────────────────────────────────────────────────────────┤
│ 交付          Argo CD / Flux · Helm · Terraform · CI/CD       │
├──────────────────────────────────────────────────────────────┤
│ 安全 / 成本   Kyverno / OPA · Vault · mTLS · NetworkPolicy    │
│               cosign/SBOM · OpenCost/Kubecost · chargeback    │
├──────────────────────────────────────────────────────────────┤
│ 数据 / RAG    S3/MinIO · pgvector/Milvus/Qdrant · embedding   │
│               rerank · MCP · Langfuse                         │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 K8s / GPU 层

| 能力 | 常见实现 | JD 信号 | 我们的状态 |
|---|---|---|---|
| K8s 发行版 | upstream、EKS、GKE、AKS、OpenShift、Rancher | 7/8 明写 | ✅ k3s |
| GPU 暴露 | NVIDIA device plugin | 默认 | ✅ D3 手装 |
| GPU 生命周期 | GPU Operator + NFD | 大企业平台岗默认；样本 1/8 明写 | ❌ 没有 |
| GPU 切分 | MIG、time-slicing、MPS | 企业平台 | 🟡 只有概念 |
| 设备分配 | DRA | 2026 上升 | 🟡 只有概念 |
| GPU 监控 | DCGM exporter | 默认 | ❌ 没有 |
| 队列/配额 | Kueue、Volcano | 平台岗加分 | 🟡 D5 设计 |
| 副本扩缩 | KEDA、HPA、cluster autoscaler/Karpenter | 默认 | ✅ KEDA；🟡 其余 |

**关键判断：**

- **D3 的“手装 device plugin”是理解原理的好路径，但生产 JD 要的是 GPU Operator。** 两者不冲突：先懂 device plugin，再用 Operator 管生命周期。
- **MIG 在 L4 上通常不可用**（以 NVIDIA 支持矩阵为准）；如果目标岗位要求 MIG，至少在 A100/H100 环境里跑过一次，或者能讲清“MIG vs time-slicing vs MPS”的隔离/利用率取舍。
- **DRA 是 2026 的新标准**，但还没到“不会就找不到工作”的程度；知道它解决“整数 GPU + 设备属性匹配”即可。

### 3.3 服务 / ML 生命周期层

| 能力 | 常见实现 | JD 信号 | 我们的状态 |
|---|---|---|---|
| 模型 serving 抽象 | KServe、OpenShift AI、Seldon、BentoML | 3/8 + 2/8 | ❌ 没有 |
| LLM serving | vLLM、Triton、llm-d | 3/8 明写 vLLM | 🟡 vLLM/llm-d 设计 |
| Pipeline | Kubeflow Pipelines、Argo Workflows | 4/8 | ❌ 没有 |
| Experiment tracking | MLflow、W&B | 1/8 明写；企业常见 | ❌ 没有 |
| Model registry | MLflow Registry、Vertex AI Model Registry、OCI artifacts | 2/8 明写 | 🟡 D3 版本目录 |
| Feature store | Feast、Tecton | 1/8 明写（Feature Store 设计）；企业常见 | ❌ 没有 |
| 数据编排 | Airflow、Dagster | 1/8 明写；企业常见 | ❌ 没有 |
| 分布式 Python | Ray、KubeRay | 3/8 | ❌ 没有 |
| Notebook | JupyterHub | 企业常见 | ❌ 没有 |

**关键判断：**

- **B 线不是“ML 全家桶”。** 面试问的是“你怎么让一个数据科学团队从 notebook 到 production”，不是“你装过几个工具”。
- **最小可信 vertical slice：** MLflow（tracking + registry）→ KServe（serve）→ Argo CD（deploy）→ Prometheus/Grafana（observe）→ OpenCost（cost）。这一条链能讲 30 分钟，比“我会 Kubeflow”有用。
- **Kubeflow 和 Ray 不是二选一。** Kubeflow 偏 pipeline/平台，Ray 偏分布式 Python/训练/推理；B 线知道两者边界即可。

### 3.4 交付 / 安全 / 成本层

| 能力 | 常见实现 | JD 信号 | 我们的状态 |
|---|---|---|---|
| GitOps | Argo CD、Flux | 3/8 | ❌ 没有 |
| 包管理 | Helm、Kustomize | 默认 | 🟡 用 Helm 装过 |
| IaC | Terraform、Crossplane、Ansible | 4/8 | ❌ 没有 |
| CI/CD | GitHub Actions、GitLab CI、Jenkins | 默认 | 🟡 会用，但没有 GPU 流水线 |
| 策略 | Kyverno、OPA Gatekeeper | 受监管企业 | 🟡 D5 设计 |
| 密钥 | Vault、Sealed Secrets、AKV/CSI | 受监管企业 | ❌ 没有 |
| 网络安全 | NetworkPolicy、mTLS、Istio | 企业 | ❌ 没有 |
| 供应链 | cosign、SBOM、镜像扫描 | 企业 | ❌ 没有 |
| 审计 | RBAC、audit log、SIEM | 受监管企业 | 🟡 只有 namespace/RBAC 概念 |
| 成本 | OpenCost、Kubecost、showback/chargeback | 成本控制 2/8；OpenCost 未明写 | 🟡 Q2 手工 chargeback |
| SLO | error budget、on-call、runbook、DR | 平台岗默认 | 🟡 零散故障表 |

**关键判断：**

- **B 线的“高级感”不在装了什么，而在“怎么证明平台没被滥用”。** 配额、准入、审计、成本归属、回滚，这五件事能讲清，就比“我会 Kubeflow”强。
- **Argo CD/GitOps 已由日常工作覆盖，不再排 lab。** 用工作里的 1 条“发布→改坏→回滚”证据讲交付链即可；B 线真正要补的是 **OpenCost 成本归属**。
- **Vault/OPA/cosign 不需要全跑。** 每个至少做一次最小实验，能讲清“解决什么、代价是什么”即可。

### 3.5 数据 / RAG / Agent 层

| 能力 | 常见实现 | JD 信号 | 我们的状态 |
|---|---|---|---|
| 对象存储 | S3、MinIO、GCS | 默认 | 🟡 hostPath |
| 向量库 | pgvector、Milvus、Qdrant、Weaviate | 3/8 | ❌ 没有 |
| Embedding/rerank | TEI、vLLM embedding、Cohere rerank | RAG 岗 | ❌ 没有 |
| RAG 编排 | LangChain/LlamaIndex、自定义 | 企业 AI 岗 | ❌ 没有 |
| LLM 观测 | Langfuse、Phoenix | 1/8 | ❌ 没有 |
| MCP | MCP server/client | 上升期 | ❌ 没有 |
| 数据治理 | lineage、retention、entitlement | 受监管企业 | ❌ 没有 |

**关键判断：**

- **RAG 不是 A 线的核心，但它是 B 线进入企业 AI 的“业务语言”。** 银行/保险/电信的 AI Platform 岗经常要求 RAG/vector store/MCP；不需要成为 RAG 专家，但要能部署一个受控的 RAG 服务。
- **最小 RAG lab：** pgvector + embedding + rerank + 一个 OpenAI-compatible endpoint + NetworkPolicy/租户隔离。3 小时够了。

### 3.6 B 线栈的“默认答案”（面试用）

> “企业 B 线的默认栈是 **K8s（很多是 OpenShift）+ GPU Operator + KServe/OpenShift AI + vLLM/Triton + Kubeflow/MLflow/Ray + Argo CD + Prometheus/Grafana + Vault/OPA + OpenCost**。A 线关心‘这个 token 为什么慢’，B 线关心‘这个团队为什么拿不到卡、花了多少钱、出事怎么回滚’。两者在 K8s + serving + 可观测重叠，但 B 线多的是 **生命周期、交付、安全、成本**。”

---

## 4. D1–D5 覆盖矩阵

### 4.1 状态说明

| 标记 | 含义 |
|---|---|
| ✅ | 已实测，有数字/日志 |
| 🟡 | 有设计/manifest，未执行；或只有概念问答 |
| ❌ | 没有 |
| ⚪ | 明确不在范围 |

> D4/D4.5/D4.6 目前是 **设计完整、未执行**；D5 只有计划，没有独立 runbook。矩阵按“文档 + 脚本”状态标记，不假装跑过。

### 4.2 A 线覆盖

| # | 能力 | D1 | D2 | D3 | D4 | D4.5 | D4.6 | D5 | 市场 | 判定 |
|---|---|---|---|---|---|---|---|---|---|---|
| A1 | vLLM baseline | ✅ | ✅ | ✅ | 🟡 | 🟡 | 🟡 | — | 高 | ✅ |
| A2 | TTFT/TPOT/ITL/goodput 方法 | ✅ | ✅ | — | 🟡 | 🟡 | 🟡 | — | 高 | ✅ |
| A3 | KV 容量/并发估算 | ✅ | ✅ | — | 🟡 | — | 🟡 | — | 高 | ✅ |
| A4 | max-num-seqs / chunked prefill | — | ✅ | — | — | — | — | — | 高 | ✅ |
| A5 | prefix caching | — | ✅ | — | 🟡 | — | 🟡 | — | 高 | ✅ |
| A6 | AWQ vs FP16 + 质量门 | — | ✅ | — | — | — | — | — | 高 | ✅ |
| A7 | FP8 / GPTQ / KV 量化 | — | ❌ | — | — | — | — | — | 中 | ❌ P1 |
| A8 | speculative decoding | — | ❌ | — | — | — | — | — | 中 | ❌ P1 |
| A9 | SGLang / RadixAttention | — | ❌ | — | — | — | — | — | **高** | ❌ P0 |
| A10 | TensorRT-LLM | — | ❌ | — | — | — | — | — | 高 | ❌ P1 |
| A11 | Triton | — | ❌ | — | — | — | — | — | 中 | ❌ P1 |
| A12 | Dynamo | — | ❌ | — | — | — | — | — | 低 | ⚪ |
| A13 | TP / PP / EP | — | — | 🟡 | 🟡 | — | — | — | **高** | ❌ P0 |
| A14 | PD 分离 | — | — | — | 🟡 | 🟡 | — | — | 中高 | 🟡 待跑 |
| A15 | tiered KV / offload | — | — | — | 🟡 | — | 🟡 | — | 中 | 🟡 待跑 |
| A16 | prefix-aware routing | — | — | — | 🟡 | — | — | — | 高 | 🟡 待跑 |
| A17 | load-aware routing | — | — | — | 🟡 | — | — | — | 高 | 🟡 待跑 |
| A18 | FailOpen / FailClose | — | — | — | 🟡 | — | — | — | 中 | 🟡 待跑 |
| A19 | flow control / fairness | — | — | — | ❌ | — | — | — | 上升 | ❌ P1 |
| A20 | KEDA 队列扩缩 | — | — | ✅ | 🟡 | — | — | — | 高 | ✅ |
| A21 | 冷启动 / 模型分发 | — | — | ✅ | — | — | — | — | 高 | ✅ |
| A22 | 优雅退出 / PDB / 驱逐 | — | — | ✅ | 🟡 | — | — | — | 中高 | ✅ |
| A23 | DCGM / Grafana / OTel | — | — | ❌ | ❌ | — | — | — | **高** | ❌ P0 |
| A24 | Nsight / kernel profiling | — | — | — | — | — | — | — | 中 | ❌ P1 |
| A25 | 负载测试工具 | ✅ | ✅ | — | 🟡 | — | — | — | 高 | ✅/🟡 |
| A26 | 质量回归 harness | — | 🟡 | — | — | — | — | — | 中 | ❌ P1 |
| A27 | 多模型 / LoRA | — | — | — | ❌ | — | — | — | 中 | ❌ P2 |
| A28 | API surface（chat/responses/tool） | — | — | — | ❌ | — | — | — | 中 | ❌ P2 |
| A29 | 模型生命周期 / canary | — | — | 🟡 | 🟡 | — | — | — | 中高 | 🟡 |
| A30 | $/1M tokens / chargeback | ✅ | 🟡 | 🟡 | 🟡 | — | — | — | 高 | 🟡 |
| A31 | 安全 / quota / rate limit | — | — | — | ❌ | — | — | 🟡 | 中高 | ❌ P1 |
| A32 | 多节点 IB/RoCE/NCCL | — | — | — | — | — | — | — | 中 | ⚪ |
| A33 | Python + Go/Rust/C++ | — | — | — | — | — | — | — | 中高 | 🟡 |
| A34 | 开源贡献 / 公开 writeup | — | — | — | — | — | — | — | 中 | ❌ |

### 4.3 B 线覆盖

| # | 能力 | D1 | D2 | D3 | D4 | D4.5 | D4.6 | D5 | 市场 | 判定 |
|---|---|---|---|---|---|---|---|---|---|---|
| B1 | Kubernetes 核心 | — | — | ✅ | 🟡 | 🟡 | 🟡 | — | 高 | ✅ |
| B2 | device plugin / runtime | — | — | ✅ | — | — | — | — | 高 | ✅ |
| B3 | GPU Operator / NFD | — | — | ❌ | — | — | — | — | 中高 | ❌ P0 |
| B4 | MIG / time-slicing / MPS | — | — | 🟡 | — | — | — | — | 中高 | 🟡 |
| B5 | DRA | — | — | 🟡 | — | — | — | — | 中 | 🟡 |
| B6 | Kueue 配额/抢占 | — | — | — | — | — | — | 🟡 | 中高 | 🟡 待跑 |
| B7 | Kyverno 准入 | — | — | — | — | — | — | 🟡 | 中高 | 🟡 待跑 |
| B8 | KEDA / HPA | — | — | ✅ | 🟡 | — | — | — | 高 | ✅ |
| B9 | cluster autoscaler / Karpenter | — | — | ❌ | — | — | — | — | 中 | ❌ P2 |
| B10 | OpenShift / OpenShift AI | — | — | ❌ | — | — | — | — | 中高 | ❌ P0 |
| B11 | KServe | — | — | ❌ | — | — | — | — | **高** | ❌ P0 |
| B12 | Kubeflow Pipelines | — | — | ❌ | — | — | — | — | 高 | ❌ P0 |
| B13 | Ray / KubeRay | — | — | ❌ | — | — | — | — | 中高 | ❌ P1 |
| B14 | MLflow tracking/registry | — | — | ❌ | — | — | — | — | 中高 | ❌ P0 |
| B15 | Feast / feature store | — | — | ❌ | — | — | — | — | 中 | ❌ P2 |
| B16 | Airflow / Dagster | — | — | ❌ | — | — | — | — | 中 | ❌ P2 |
| B17 | 模型 registry / artifact | — | — | 🟡 | — | — | — | — | 中高 | 🟡 |
| B18 | Argo CD / Flux | — | — | ❌ | — | — | — | — | **高** | ✅ 工作覆盖 |
| B19 | Helm / Kustomize | — | — | 🟡 | 🟡 | 🟡 | 🟡 | — | 高 | 🟡 |
| B20 | Terraform / IaC | — | — | ❌ | — | — | — | — | 高 | ❌ P1 |
| B21 | CI/CD for GPU workloads | — | — | ❌ | — | — | — | — | 中高 | ❌ P1 |
| B22 | Vault / secrets | — | — | ❌ | — | — | — | — | 中高 | ❌ P0 |
| B23 | OPA / Kyverno 策略 | — | — | — | — | — | — | 🟡 | 中高 | 🟡 |
| B24 | NetworkPolicy / mTLS | — | — | ❌ | — | — | — | — | 中高 | ❌ P1 |
| B25 | cosign / SBOM / 扫描 | — | — | ❌ | — | — | — | — | 中 | ❌ P1 |
| B26 | RBAC / audit | — | — | 🟡 | 🟡 | — | — | — | 中高 | 🟡 |
| B27 | Prometheus / Grafana / OTel | — | — | 🟡 | ❌ | — | — | — | **高** | 🟡 |
| B28 | OpenCost / Kubecost | — | — | ❌ | — | — | — | — | 中高 | ❌ P1 |
| B29 | 多租户 quota/priority | — | — | 🟡 | 🟡 | — | — | 🟡 | 高 | 🟡 |
| B30 | RAG / vector DB | — | — | ❌ | — | — | — | — | 中高 | ❌ P1 |
| B31 | MCP / agentic | — | — | ❌ | — | — | — | — | 中 | ❌ P1 |
| B32 | SLO / on-call / DR | — | — | 🟡 | 🟡 | — | — | — | 中高 | 🟡 |
| B33 | 模型回滚 | — | — | 🟡 | 🟡 | — | — | — | 中高 | 🟡 |
| B34 | 多集群 / fleet | — | — | ❌ | — | — | — | — | 低 | ⚪ |
| B35 | Slurm / HPC | — | — | — | — | — | — | — | 低（本地 C 线） | ⚪ |

> 覆盖矩阵的列仍是 D1–D5；D6a/D6b 没有单独列。D6 覆盖 B11（KServe）、B27（observability），以及 A23/A29 的一部分；详见 §6.3/§6.4。

### 4.4 已经比市场平均强的地方

不要只盯缺口；这些是面试里的差异化：

1. **实测的数字链**：D1 的 c=1/4/16/64 + 诊断跑（排队 vs prefill）+ D2 的 chunked prefill/prefix caching/AWQ 质量门。大多数候选人只有“我部署过 vLLM”。
2. **KV 容量与抢占的解释**：能从 `KV cache tokens` 推到“8k 请求最大并发 11.75x”，再推到 c=16 的排队/P99。
3. **前缀缓存的双面性**：D2 证明 prefix caching 不只降 TTFT，还降 TPOT/提吞吐；D4 又把它放进路由。
4. **PD/tiered KV 的拓扑能力**：D4.5/D4.6 就算没跑，manifest、容量计算、失败表已经比“只知道 PD 这个名字”强。
5. **B 线的平台细节**：冷启动分阶段、KEDA 1→2 的 `Pending`、PDB/驱逐、`shutdown-timeout` 不是总退出上限——这些都是真踩过的坑。

---

## 5. 缺口清单

### 5.1 P0：不补会被问穿

| # | 缺口 | JD 证据 | 最小实验 | 时间 | 成本 | 放哪 |
|---|---|---|---|---|---|---|
| P0-1 | **SGLang / RadixAttention** | 6/8 份 A 线 JD 明写 | 同一 32-session 共享前缀 workload，vLLM vs SGLang；记录 TTFT P99、output tok/s、hit rate | 3h | 1×L4 ~$2 | 新增 `d2.5-runtime-comparison.md` |
| P0-2 | **TP=2 / 多卡** | DRW/Fluidstack/PhysicsX 明写 TP/PP/EP | 2×L4，Qwen3-8B-AWQ，TP=1 vs TP=2；记录 TTFT/TPOT/吞吐/显存/KV 分片 | 3h | 2×L4 ~$3 | 新增 `d2.6-tp2-lab.md`，或并进 D4.5 前置 |
| P0-3 | **DCGM + Grafana + OTel** | 平台岗默认；DRW 明写 Nsight/DCGM/OTel | **拆两半：** Q1 在 D3 上做 DCGM exporter + Grafana；Q2 在 D4 上做 OTel + EPP/Envoy trace | 2–3h | 复用 ~$1 | `d6-kserve-observability.md`（D6b-1/D6b-2） |
| P0-4 | **KServe / OpenShift AI** | B 线 3/8 + 2/8；Mechanics/Nutanix/UnitedHealth | 同一模型 raw Deployment vs KServe `InferenceService`；记录 CRD、scale-to-zero、canary | 3h | 2×3060 或 1×4090 ~$1–2 | 并入 `d6-kserve-observability.md`（D6a） |
| P0-5 | **OpenCost**（Argo CD 工作已覆盖） | 成本岗必问；GitOps 有日常证据 | OpenCost 出 namespace 成本 + `$/1M tokens`；不再做 Argo CD lab | 1.5h | 复用 ~$1 | 新增 `d3.6-opencost.md` |
| P0-6 | **Vault / OPA / NetworkPolicy** | 受监管企业（Mechanics/UnitedHealth） | Kyverno 拒绝 1 个无 label 的 GPU Pod；Vault/SealedSecret 注入 1 个 secret；1 条 NetworkPolicy | 3–4h | 复用 ~$1 | 并入 `d5.5-security.md` |

> **级别/轨道差异：** P0-2（TP=2）对 staff/前沿 A 线是 P0，对 mid/senior 可以降到 P1，但至少要能讲清 TP 的通信/显存取舍。P0-4/5/6 是 **B 线就业**的 P0；如果只投 A 线，可以降到 P1。不要因为表里写了 P0 就六件事一起上。

#### 5.1.1 P0 的季度分配（按关联性）

分配原则只有一条：**P0 跟着它依赖的 artifact 走，而不是跟着“哪个季度看起来空”走。**

| 季度 | P0 | 关联/依赖 | 为什么是这个顺序 | 验收 |
|---|---|---|---|---|
| **Q1** | P0-1 SGLang（D2.5） | D2 | 必须复用 D2 的同一模型、同一 workload、同一指标；隔季度再跑，控制变量就丢了 | vLLM vs SGLang 对比表 |
| **Q1** | P0-3a DCGM + Grafana（D6b-1） | D1/D3 | D3 已装 Prometheus，补 exporter/dashboard 成本最低；这一半不依赖 D4 | GPU + vLLM dashboard |
| **Q1** | P0-4 KServe（D6a） | D3 | 用 D3 的 raw Deployment 做 control，形成“裸 Deployment vs KServe”的 B 线基线 | `InferenceService` + 冷启动/P99 对比 |
| **Q2** | P0-2 TP=2（D2.6） | D4.5 | 先有 TP 的通信/显存概念，再跑 2P+2D；否则 PD 和 TP 的变量混在一起 | TP=1 vs TP=2 表 |
| **Q2** | P0-3b OTel + EPP trace（D6b-2） | D4 | 只有 D4 有 EPP/Envoy；trace 要覆盖“网关→EPP→vLLM” | 1 条 EPP→vLLM trace |
| **Q2** | P0-5 OpenCost（D3.6） | D3/D4 + chargeback | Argo CD 工作已覆盖；只补成本表 | namespace 成本表 |
| **Q3** | P0-6 Vault/OPA/NetworkPolicy（D5.5） | D5 | 安全策略要建在 Kueue/Kyverno 的 namespace/配额之上；先有配额，再谈准入和隔离 | 2 条拒绝日志 + secret + NetworkPolicy |

> **为什么不是平均每季度 2 个：** Q1 的 3 个 P0 都复用 D1–D3 的现成集群/模型/指标，边际成本低；Q2 的 3 个 P0 都依赖 D4/D4.5 或 chargeback，提前做会重复搭环境；Q3 只剩 1 个 P0，因为安全必须等 D5 的配额/namespace 先落地。

> **P1/P2 不排进 gate。** flow control、TensorRT-LLM/Triton、MLflow/Kubeflow slice、RAG/MCP 都是“有余力再加”的加分项；它们不改变 6 个 P0 的验收。

**为什么这些是 P0：**

- 它们不是“多学一个工具”，而是**面试官用来判断“你是在生产里做过，还是只会 demo”的分界线**。
- 每一个都能在 2–4 小时内做出“可截图、可讲 10 分钟”的 artifact；投入产出比最高。
- 它们互相复用：P0-3a 的 Grafana 可以看 P0-2 的 TP=2；P0-5 的 OpenCost 可以按 P0-4 的 KServe namespace 出成本；P0-6 的策略可以管 P0-5 的 namespace。

### 5.2 P1：补了明显加分

| # | 缺口 | 为什么 | 最小实验 | 时间/成本 |
|---|---|---|---|---|
| P1-1 | TensorRT-LLM 选型 + smoke | 6/8 份 JD 明写；能讲“什么时候值得” | 1 个 8B 模型 engine build + 一次 benchmark；不追求全量 | 3–4h / 1×L4 ~$2 |
| P1-2 | Triton 多模型 | 企业非 LLM 模型多；B 线加分 | 1 个 ONNX/embedding 模型 + 1 个 vLLM backend | 2h / 1×L4 ~$1 |
| P1-3 | FP8 / KV 量化 | 省显存、提吞吐；staff 线会问 | Qwen3-8B FP8 或 KV FP8；质量门 + 吞吐 | 2h / 1×L4 ~$2 |
| P1-4 | speculative decoding | Fluidstack/DRW 明写；长尾优化 | vLLM spec decode（draft model / n-gram）一次对比 | 2h / 1×L4 ~$1 |
| P1-5 | flow control / token rate limit | 多租户平台上升期 | EPP `flowControl` + 两个 priority class；记录拒绝/排队 | 3h / 2×L4 ~$2 |
| P1-6 | 质量回归 harness | 量化/引擎升级会掉点 | 把 D2 GSM8K 扩成 3 个任务 + 阈值 + CI 脚本 | 2h / 复用 ~$1 |
| P1-7 | 负载测试 open-loop / trace replay | D1 是闭环；生产是开环 | `inference-perf`/`genai-perf`/`llm-d-benchmark` 跑一次 Poisson | 1h / 复用 ~$0 |
| P1-8 | MLflow + Kubeflow/Ray vertical slice | B 线 4/8、3/8、1/8 | MLflow tracking + registry + 1 条 Kubeflow/Ray pipeline | 4–6h / 1×L4 ~$2 |
| P1-9 | RAG + pgvector + MCP | B 线 3/8、1/8 | 1 个受控 RAG 服务：embedding + pgvector + rerank + MCP | 3h / 复用 ~$1 |
| P1-10 | SLO / on-call / DR | 平台岗默认 | 1 个 SLO 面板 + 1 次 game day（kill pod / drain node） | 2h / 复用 ~$1 |
| P1-11 | Terraform / IaC | 4/8 份 B 线 JD | 用 Terraform 起 1 个 namespace/quota（或 kind 集群） | 2h / 本地 ~$0 |
| P1-12 | cosign / SBOM | 受监管企业供应链 | 签名 1 个 vLLM 镜像 + 生成 SBOM + Kyverno 验签 | 2h / 复用 ~$0 |

### 5.3 P2：知道就行，不要现在做

| 缺口 | 为什么不做 | 怎么覆盖 |
|---|---|---|
| 多节点 IB/RoCE/NCCL | Vast 上难复现；成本高 | 读 NCCL/IB 文档；能讲“TP 在 NVLink vs IB 的差异” |
| wide EP / DeepEP | 只有超大 MoE 集群需要 | D4 附录 A.3 + 面试一句话 |
| 多集群 / fleet（Karmada/RHACM） | B 线大厂专属；本地用不上 | 知道“多集群解决什么”即可 |
| 训练 / fine-tuning | 不是 A/B 线主线 | 不投入 |
| CUDA / Triton kernel | 是 ML Performance 线，不是 Inference Platform | 能读懂即可 |
| Slurm / HPC | 本地 C 线（GeoSoftware 类）才用 | 计划里已有周末 Slurm，不塞进 D1–D5 |
| 多模型 / LoRA | 中频，不是入门门槛 | D4 §7.2 的多模型路由 + 一次 LoRA 概念 |
| API surface（tool calling/structured output/multimodal） | 偏应用层 | 知道 vLLM 支持哪些 endpoint 即可 |
| Go/Rust/C++ | 不是推理核心，但 staff JD 常写 | 用 Go 写 1 个 bench/gateway CLI，作为代码样本 |

---

## 6. 对 D1–D5 的修改建议

### 6.1 不改主线的部分

- **D1/D2 不动。** 它们已经是“方法学 + 数字”的核心资产，不要为了加工具把 4h/3h 撑爆。
- **D4 的 4h 不动。** 4 个 arm + cache reset + P99 表已经是满负荷；可观测/flow control 用加挂 lab，不要塞进主实验。
- **D5 的 Kueue/Kyverno 核心不动。** 安全和成本用加挂 lab，不要把一个 3h 的配额实验变成“平台全家桶”。

### 6.2 D1/D2 的加挂

| 加挂 | 内容 | 时间 | 产出 |
|---|---|---|---|
| D1+ | 用 DCGM exporter 替代/补充 `nvidia-smi` 采样；Grafana 看 `DCGM_FI_DEV_GPU_UTIL`、`DCGM_FI_DEV_POWER_USAGE`、`DCGM_FI_DEV_MEM_COPY_UTIL` | +1h | 1 张 GPU dashboard；D1 的功耗墙结论有更标准的证据 |
| D2+ | 在 D2 结尾加 1 页“引擎选型”：vLLM vs SGLang vs TRT-LLM vs Triton 的决策树；不跑也算 artifact | +1h | 1 页决策表；面试可直接讲 |
| D2.5 | SGLang 对照实验（P0-1） | 3h | 1 张对比表 + 1 句选型结论 |
| D2.6 | TP=2 实验（P0-2） | 3h | 1 张 TP=1 vs TP=2 表 |

### 6.3 D6a：KServe 服务抽象（3h）

D6a 接过 D3 的 raw Deployment，**不重跑 D3**：同一模型（Qwen3-8B-AWQ）、同一 vLLM 镜像（v0.34.0），对比 raw Deployment 和 KServe `InferenceService`。

```text
D3 raw Deployment
  → KServe Standard（cert-manager + Gateway API + Envoy）
  → InferenceService + custom ClusterServingRuntime
  → canary / revision / HPA
```

验收：

- [ ] 同一模型 raw vs KServe 的冷启动分段（镜像/权重/引擎/Ready）；
- [ ] 同一 workload 的 TTFT/TPOT/output tok/s；
- [ ] canary 10% 或两个 revision；
- [ ] HPA 1→2，或明确 Standard mode 的 HPA/scale-to-zero 限制；
- [ ] 不装 Knative；需要 0→1 时另开 optional。

> k3s 上用 KServe **Standard/RawDeployment**，避免 Knative/Istio 全家桶；3h 才够。Vast 没有 L4 VM，用 2×3060 或 1×4090。OpenShift AI 用文档/截图补概念，不要为了一个 lab 去装 OpenShift。

### 6.4 D6b：推理可观测性（2–3h）

D6b **不重跑 D4**；把 D4 的 EPP/vLLM manifest 或 D6a 的 KServe/vLLM 当作被观测对象，跑 10 分钟负载。

- **D6b-1（Q1，1.5h）**：DCGM exporter + Grafana；GPU util/power/mem + vLLM queue/KV；
- **D6b-2（Q2，1–1.5h）**：OTel Collector + EPP/Envoy/vLLM 一条 trace；D4 的 P99 有服务端归因；
- 一条 SLO 告警 + 一次 game day（kill pod/EPP）。

验收：

- [ ] 1 张 GPU + vLLM dashboard；
- [ ] 1 条 `gateway→EPP→vLLM` 或 `gateway→vLLM` trace；
- [ ] 1 条 TTFT P99 / KV 告警；
- [ ] game day 时间线；
- [ ] `summary.md` + `cost.txt`。

> D4.8/D4.9（flow control、多模型 Gateway）仍是 P1/P2，不并入 D6。

### 6.5 D5 的加挂（D5.5）

D5 的 Kueue + Kyverno 只覆盖“谁能拿卡”。企业 B 线还会问“拿不到怎么办、出了事怎么查、镜像可信不可信”。新增 **D5.5 “安全 / 成本 / 审计”**，4–6h（最小版 3h：Kyverno + Vault + NetworkPolicy）：

- [ ] Kyverno：拒绝无 `priorityClass`/`quota-label` 的 GPU Pod（2 条拒绝日志）；
- [ ] OPA Gatekeeper 或 Kyverno 的 1 条镜像签名/仓库白名单策略；
- [ ] Vault/SealedSecret 注入 1 个模型 token；
- [ ] NetworkPolicy：只允许 bench namespace 访问 vLLM；
- [ ] OpenCost/Kubecost：1 小时 namespace 成本 + `$/1M tokens`；
- [ ] audit log：`kubectl auth can-i --list` + 1 条 RBAC 拒绝。

> 最小版用 Vault dev mode 或 SealedSecret；不要为了一个 lab 上 Vault HA/auto-unseal。OPA 和 Kyverno 二选一即可，不要同时上两套策略引擎。

### 6.6 新增 lab 清单（建议，不一次性全做）

| 文档 | 内容 | 时间 | 成本 | 依赖 |
|---|---|---|---|---|
| `d2.5-runtime-comparison.md` | vLLM vs SGLang；TRT-LLM/Triton 选型页 | 3h | ~$2 | D2 |
| `d2.6-tp2-lab.md` | 2×L4 TP=1 vs TP=2 | 3h | ~$3 | D1/D2 |
| `d6-kserve-observability.md` | D6a KServe + D6b DCGM/Grafana/OTel/EPP trace | 5–6h | ~$1.5–1.8 | D3/D4 |
| `d3.6-opencost.md` | OpenCost + Grafana 成本面板 | 1.5h | ~$1 | D3/D4 |
| `d3.7-ml-platform-slice.md` | MLflow + Kubeflow/Ray + KServe | 4–6h | ~$2 | D6a |
| `d4.8-flow-control.md` | EPP flow control + token rate limit | 3h | ~$2 | D4 |
| `d5.5-security.md` | Vault/OPA/NetworkPolicy/cosign | 4–6h | ~$1 | D5 |

> 不要一次全写。P0 按 §5.1.1 的季度分配走：Q1 D2.5 + D6b-1 + D6a；Q2 D2.6 + D6b-2 + D3.6；Q3 D5.5。P1（D4.8/D3.7/RAG）只在有余力时加，不改变 P0 验收。

### 6.7 季度 gate 调整（只列 P0）

| 季度 | 原 artifact | P0 加挂 | 验收 |
|---|---|---|---|
| Q1 | D1/D2 + D3 冷启动/KEDA | D2.5 SGLang + D6b-1 DCGM/Grafana + D6a KServe | 1 张 vLLM/SGLang 对比表 + 1 张 Grafana 图 + 1 个 `InferenceService` |
| Q2 | D4 路由 + KV 压力 + chargeback | D2.6 TP=2 + D6b-2 OTel/EPP trace + D3.6 OpenCost | TP=1 vs TP=2 表 + 1 条 trace + 成本表 |
| Q3 | D5 配额 + 故障 + SLO | D5.5 安全 | 2 条拒绝日志 + secret 注入 + 1 条 NetworkPolicy |
| Q4 | 简历/JD 映射 | 不新增大 lab；把 P0 结果写进 bullet | 3 个 A 线 + 3 个 B 线 JD 逐条映射 |

> P1/P2（flow control、TensorRT-LLM/Triton、MLflow/Kubeflow slice、RAG/MCP）不在这张表里。它们不是 P0，不要为了“表看起来满”把 P0 挤掉。

---

## 7. JD 关键词 → 证据映射

### 7.1 A 线

| 关键词 | 我们现在的证据 | 缺口动作 |
|---|---|---|
| vLLM | D1/D2 实测；D4.5/D4.6 manifest | 保持 |
| SGLang | 无 | D2.5 |
| TensorRT-LLM | 无 | D2.5 的选型页 + 1 次 smoke |
| Triton | 无 | P1-2 |
| KV cache / prefix caching | D1 附录、D2 §4.4、D4.6 | 保持 |
| chunked prefill / batching | D2 §4.3 | 保持 |
| CUDA Graphs / PagedAttention | D1 附录有 PagedAttention/KV；CUDA Graphs 是 vLLM 默认 | 能讲清 kernel launch/显存管理即可，不单独跑 |
| quantization / AWQ | D2 §4.5 + GSM8K | 加 FP8/KV 量化（P1-3） |
| speculative decoding | 无 | P1-4 |
| TP/PP/EP | D3 §12 Q8 概念；D4 §8 Q4 | D2.6 TP=2 |
| PD / NIXL | D4.5 设计 | 跑 D4.5 |
| tiered KV / offload | D4.6 设计 | 跑 D4.6 |
| prefix-aware routing | D4 设计 | 跑 D4 |
| load-aware routing | D4 optimized arm | 跑 D4 |
| flow control | D4 附录 A.4（D 档） | D4.8 |
| K8s / KEDA / Kueue | D3 实测；D5 设计 | 跑 D5 |
| DCGM / OTel / Grafana / Nsight | 只有 `nvidia-smi` + Prometheus | D6b + Nsight 概念 |
| SLO / goodput / P99 | D1/D2/D4 | 保持 |
| `$/1M tokens` | D1 成本；Q2 chargeback | 跑 chargeback |
| Python + Go/Rust/C++ | Python 为主 | 用 Go 写一个小 gateway/CLI（P2） |

### 7.2 B 线

| 关键词 | 我们现在的证据 | 缺口动作 |
|---|---|---|
| Kubernetes | D3 实测 | 保持 |
| OpenShift / OpenShift AI | 无 | D6a（或至少 concept + screenshot） |
| KServe | 无 | D6a |
| Kubeflow / MLflow / Ray | 无 | D3.7 vertical slice |
| vLLM / Triton serving | vLLM 强；Triton 无 | D6a + P1-2 |
| GPU Operator / NFD | 手装 device plugin | Q3 GPU Operator/MIG lab（D6a 不覆盖） |
| MIG / time-slicing / DRA | D3 概念 | 至少 1 次 time-slicing 或 MIG（有硬件时） |
| Kueue | D5 设计 | 跑 D5 |
| Kyverno / OPA | D5 设计 | 跑 D5 + D5.5 |
| KEDA / HPA | D3 实测 | 保持 |
| Argo CD / Flux | 工作日常使用；补 1 条回滚证据 | 不排 lab；D3.6 只做 OpenCost |
| Helm / Kustomize | 用 Helm 装过 | D3.6 自己写 chart |
| Terraform / IaC | 无 | P1-11 |
| Vault / mTLS / NetworkPolicy | 无 | D5.5 |
| cosign / SBOM | 无 | P1-12 |
| Prometheus / Grafana / OTel | Prometheus 有；Grafana 关；OTel 无 | D6b |
| OpenCost / Kubecost | 无 | D3.6 |
| RAG / vector DB / MCP | 无 | P1-9 |
| SLO / on-call / DR | 零散故障表 | P1-10 |
| Slurm / HPC | 计划里另做 | 不塞进 B 线 |

### 7.3 简历 bullet 模板（执行后填）

**A 线：**

- 在 2×L4 上对比 vLLM 与 SGLang 的共享前缀 workload：TTFT P99 `____ ms` vs `____ ms`，output `____ tok/s` vs `____ tok/s`，结论是 `____`（SGLang 在 `__%` prefix 复用率以上值得）。
- 在 2×L4 上测 Qwen3-8B-AWQ 的 TP=1 vs TP=2：TTFT P99 `____`，TPOT P95 `____`，吞吐 `____`，证明 `____`（通信开销/显存收益）。
- 用 DCGM + Prometheus + Grafana + OTel 搭推理可观测：覆盖 GPU util/power/mem、vLLM queue/KV、EPP 路由；把 c=16 的 P99 从“客户端黑盒”拆到 `____`（排队/prefill/decode）。

**B 线：**

- 用 KServe/OpenShift AI 把 vLLM 模型从 raw Deployment 迁到 `InferenceService`，保留 `____` 的冷启动/P99，增加 `____`（canary/scale-to-zero/CRD）。
- 用 Argo CD 把 GPU 推理栈做成 GitOps：1 次 image tag 变更 + 1 次回滚，回滚时间 `____` 秒；OpenCost 出 namespace 级 `$/1M tokens`。
- 用 Kueue + Kyverno + Vault + NetworkPolicy 做多租户 GPU 平台：`____` 个团队配额，`____` 条拒绝日志，`____` 个 secret 注入，`____` 条网络策略。

---

## 8. 面试追问（gap-driven）

### 8.1 A 线 10 问

1. **vLLM 和 SGLang 的 KV/前缀管理有什么本质区别？** 你能讲 PagedAttention/block hash vs RadixAttention/radix tree，以及什么 workload 下 SGLang 更快吗？
2. **TP=2 在 2×L4 上为什么可能更慢？** 通信/同步、KV 分片、batch 变小、PCIe vs NVLink。
3. **PD 分离的 KV 怎么传？** NIXL、RDMA/TCP、KV 布局、block size、失败回退。
4. **tiered KV 什么时候不值得？** CPU→GPU 拷贝比重算慢；CPU 带宽/PCIe 瓶颈；命中率不够。
5. **speculative decoding 的 acceptance rate 怎么影响 TPOT？** draft model 成本、质量风险、什么场景值得。
6. **FP8/KV 量化会不会掉质量？** 怎么设质量门、怎么回归。
7. **DCGM 的哪个指标能区分“GPU 忙”与“GPU 有效”？** `GPU_UTIL` vs `MEM_COPY_UTIL` vs SM occupancy；Nsight 看什么。
8. **flow control 和 Kueue 的分工？** 请求级排队/公平 vs 作业级配额/准入。
9. **多模型/多租户路由怎么做硬隔离？** namespace/RBAC/NetworkPolicy vs 请求头 tenant。
10. **如果 EPP 挂了，FailOpen 和 FailClose 的用户影响分别是什么？** 你测过吗？

### 8.2 B 线 10 问

1. **KServe 和 raw Deployment 的区别？** CRD、scale-to-zero、canary、ingress、runtime。
2. **OpenShift AI 和上游 KServe/Kubeflow 的关系？** 企业发行版、支持、安全、UI。
3. **Kueue 和 KEDA 怎么分工？** 配额/准入 vs 副本扩缩。
4. **GPU Operator 帮你管什么？** driver/toolkit/device plugin/DCGM/NFD 生命周期。
5. **MIG、time-slicing、MPS 的隔离/利用率取舍？** 什么时候不该切卡。
6. **Argo CD 怎么回滚一个模型服务？** Git revert vs `rollout undo`；image tag/weights 版本。
7. **Vault/OPA/cosign 各解决什么？** secret、准入、供应链；不要混。
8. **OpenCost 的 namespace 成本怎么算？** GPU 小时、闲置摊销、共享卡分摊。
9. **RAG 服务怎么做租户隔离？** vector store namespace、embedding 权限、检索过滤、审计。
10. **SLO 怎么定义？** TTFT/TPOT/goodput/error budget；on-call 怎么被唤醒。

### 8.3 现在还答不好的题（诚实清单）

- “你们线上用 SGLang 还是 vLLM？为什么？”——只能答 vLLM，缺 SGLang 一手数据。
- “TP=2 的 TTFT/TPOT 怎么变？”——只有概念，没有数字。
- “你们怎么定位 GPU 瓶颈？”——只有 `nvidia-smi` + vLLM metrics，缺 DCGM/Nsight。
- “KServe 的 `InferenceService` 和 llm-d 什么关系？”——知道概念，没跑过。
- “Argo CD 怎么回滚模型？”——没有 GitOps 实践。
- “Vault/OPA 怎么落地？”——只有 Kyverno 计划。
- “OpenCost 怎么分摊共享 GPU？”——只有手工 chargeback 设计。

> 这 7 题就是 P0 清单的来源。补完 P0，它们会变成“我做过，数字是……”而不是“我知道”。

---

## 9. Sources

### 9.1 A 线 JD

- DRW, AI Inference Platform Engineer: <https://job-boards.greenhouse.io/drweng/jobs/8230509>
- Baseten, Software Engineer - Inference Platform: <https://linkedin.com/jobs/view/software-engineer-inference-platform-at-baseten-4476113451>
- Anthropic, Staff + Senior Software Engineer, Inference (Ontario): <https://job-boards.greenhouse.io/anthropic/jobs/5385998008>
- Fluidstack, Software Engineer, Inference Platform: <https://jobs.dukecapitalpartners.duke.edu/companies/fluidstack/jobs/69876074-software-engineer-inference-platform>
- Syllo, Staff Software Engineer, AI Inference: <https://job-boards.greenhouse.io/syllo/jobs/4314674009>
- PhysicsX, Platform Engineer - Self Hosting LLMs: <https://job-boards.greenhouse.io/physicsx/jobs/5025659101>
- Thomson Reuters, Staff Inference Engineer - AI (Toronto): <https://linkedin.com/jobs/view/staff-inference-engineer-ai-at-thomson-reuters-4481947439>
- Cerebras, Software Engineer, Development & Deployment (Toronto): <https://ca.jooble.org/rjdp/-4385096388642973292>
- JarvisLabs, Senior Inference Platform Engineer: <https://jarvislabs.ai/careers/senior-inference-platform-engineer>

### 9.2 B 线 JD

- Mechanics Bank, AI Platform Engineer: <https://linkedin.com/jobs/view/ai-platform-engineer-irvine-roseville-or-walnut-creek-ca-at-mechanics-bank-4493216494>
- Wealthsimple, Senior Software Developer, ML Platform & Infrastructure (Toronto): <https://scaleengineer.com/jobs/wealthsimple/senior-software-developer-ml-platform-infrastructure>（原帖已 410；引用的是搜索快照）
- Rakuten Kobo, Senior ML Platform Engineer (Toronto): <https://indexventures.getro.com/companies/rakuten-2/jobs/63499641-senior-machine-learning-engineer>
- Nutanix, Software Engineer 4 - Kubernetes AI Platform Engineering (Vancouver): <https://careers.nutanix.com/en/jobs/32958/software-engineer-4-kubernetes-ai-platform-engineering>
- UnitedHealth Group, Principal AI/ML Platform Engineer (Remote US): <https://hiringcafe.com/jobs/ml-platform-engineer>
- Scotiabank, AI Platform Software Engineer (Toronto): <https://jobs.scotiabank.com/job/Toronto-AI-Platform-Software-Engineer-ON-M5H-1H1/607010417>
- Homebase, Platform Engineer - Kubernetes, GitOps, Flux CD & AI/ML Infrastructure: <https://ca.jooble.org/jdp/-3334617801187709324>
- AI Talent Canada, MLOps / AI Platform Engineer (Remote Canada): <https://ai-talent.ca/mlops-ai-platform-engineer.html>

### 9.3 市场 / 项目

- CNCF, “Kubernetes Fuels AI Growth”: <https://cncf.io/blog/2026/01/20/kubernetes-fuels-ai-growth-organizational-culture-remains-the-decisive-factor>
- CNCF, “The great migration: Why every AI platform is converging on Kubernetes”: <https://cncf.io/blog/2026/03/05/the-great-migration-why-every-ai-platform-is-converging-on-kubernetes>
- CNCF, “Welcome llm-d to the CNCF”: <https://cncf.io/blog/2026/03/24/welcome-llm-d-to-the-cncf-evolving-kubernetes-into-sota-ai-infrastructure>
- llm-d, “llm-d v1.0: State-of-the-art inference, ready for Day 2”: <https://llm-d.ai/blog/llm-d-v1.0-state-of-the-art-inference-ready-for-day-2>
- KServe, “Understanding LLMInferenceService”: <https://kserve.github.io/website/docs/model-serving/generative-inference/llmisvc/llmisvc-overview>
- Kubernetes Blog, “Introducing Gateway API Inference Extension”: <https://kubernetes.io/blog/2025/06/05/introducing-gateway-api-inference-extension/>
- Hugging Face, TGI maintenance notice: <https://huggingface.co/docs/text-generation-inference/index>
- Adroit, “Kubernetes for LLM Inference in 2026: The Stack That Fits”: <https://adroit.io/field-notes/kubernetes-llm-serving-2026>
- JarvisLabs, “vLLM, SGLang, or TensorRT-LLM? Picking an LLM Serving Stack”: <https://jarvislabs.ai/blog/vllm-sglang-trtllm-comparison>

### 9.4 我们自己的文档

- D1: [`d1-vllm-baseline-runbook.md`](./d1-vllm-baseline-runbook.md)
- D2: [`d2-vllm-tuning-runbook.md`](./d2-vllm-tuning-runbook.md)
- D3: [`d3-k8s-vllm-learning.md`](./d3-k8s-vllm-learning.md)
- D4: [`d4-llm-d-learning.md`](./d4-llm-d-learning.md)
- D4.5: [`d4.5-pd-lab.md`](./d4.5-pd-lab.md)
- D4.6: [`d4.6-tiered-cache-lab.md`](./d4.6-tiered-cache-lab.md)
- 计划: [`ai-cloud-native-week-plan.md`](./ai-cloud-native-week-plan.md)
