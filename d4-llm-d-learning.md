# D4 学习文档：llm-d 前缀感知路由（2×RTX 3060 12GB + Qwen3-4B-AWQ）

> 状态：**planned，硬件已就位（2026-11-24 起草；2026-11-25 按实际实例修正）**。本文按 `ai-cloud-native-week-plan.md` 的 D4 行准备：**4h、2×RTX 3060 12GB VM（instance 62540497）、跑一条 llm-d Well-Lit Path、对比 round-robin vs EPP（Endpoint Picker，端点选择器）的 P99（第 99 百分位）、留下命中率数字和 B 线故障表**；同时用 §1.4 + 附录 A 覆盖 llm-d 核心 feature（PD（Prefill/Decode，预填充/解码）、wide EP（Expert Parallelism，专家并行）、flow control、tiered/P2P、autoscaling、batch、rollout、API）。实例已租（`actual_status=running`，2026-11-25 已可 SSH 登录），文档、manifest、benchmark 脚本已就绪，**尚未跑实验**；所有“实测”表都是待填模板。
>
> 计划位置：`ai-cloud-native-week-plan.md` 的 **D4（llm-d 日）** 与 **Q2（Gateway/路由）**；B 线学习表见该文件 §3，llm-d 四问见 §6。
>
> 性质：学习文档 + 可执行 lab。D1/D2 回答“单机多快”，D3 回答“放进 K8s（Kubernetes）后启动/扩容/驱逐要多少秒”，D4 回答“**多副本时，把请求送到已经缓存了这段前缀的副本，P99 能好多少；这套路由组件挂了怎么办**”。
>
> 硬约束：**不在共享 UAT 集群 `uat-mobility-aks-01` 上做实验**。用 Vast.ai 租的 **2×RTX 3060 12GB VM（instance 62540497）**，on-demand；同机、同模型、同输入/输出长度、同 SLO（Service Level Objective，服务等级目标），只改路由策略。
>
> 版本基线：llm-d `v1.0.0`、Gateway API Inference Extension `v1.6.2`、vLLM `v0.34.0`（以 `--help` 为准）、KEDA（Kubernetes Event-driven Autoscaling） `2.21.1`（只用于 Lab 0）。
>
> **硬件前提修正（2026-11-25）：** 本文原写“2×24GB VM”。Vast 上 **没有 L4 VM**（`gpu_name=L4 vms_enabled=true` 返回 0）；L4 只有容器，k3s 起不来。**本次实际租的是 2×RTX 3060 12GB VM（instance 62540497，UK，`$0.26148/h` 含 130GB disk）**：每卡 12GB、TP（Tensor Parallelism，张量并行）=1、2 副本；2×3090 只是备选。模型相应从 Qwen3-8B-AWQ 改为 **Qwen3-4B-AWQ**（served name `qwen3-4b`）。结果标注 2×3060 12GB，不标 L4/3090。详见 §3.1。

---

## 0. 先看结论（执行前先记住）

1. **D4 的主菜是 llm-d，不是 Lab 0。** Lab 0（KEDA HTTP Add-on）只解决“0 副本时请求怎么进来”；llm-d 解决“多副本时按 prefix cache 怎么路由”。4h 不够就砍 Lab 0，保 Lab 1。
2. **路由只在多副本时存在。** 1 个 vLLM 进程没有路由问题；D4 的收益完全建立在 D3 的 2 副本之上。
3. **llm-d 1.0 的 precise routing 不是“猜前缀”。** vLLM 通过 ZMQ 上报 KV（Key-Value，键值） block 事件，EPP 建精确索引；每个请求先 tokenize/render，再查索引。需要 `--kv-events-config`、`/v1/*/render`、`--block-size=64` 与 `blockSizeTokens: 64` 对齐。
4. **2×3060 12GB 跑不了 guide 默认配置。** guide 默认 Qwen3-32B、TP=2、2 副本 = 4×H100。我们改成 Qwen3-4B-AWQ（Activation-aware Weight Quantization，激活感知权重量化）、TP=1、2 副本 = 2×RTX 3060 12GB；模型名、`peakPrefillThroughput`、绝对数字都不能照抄。
5. **主对比是 Service round-robin vs EPP precise。** 可选 EPP random 作为控制组，隔离 Envoy/EPP 的固定开销；`direct` / `precise` 各跑 3 次，`random` 时间够就 3 次，取中位数。
6. **EPP 单副本是有意为之。** precise 的 in-flight token 记账和 KV 索引是进程本地的；D4 不跑 active-active。生产 HA 需要共享状态/索引快照，先作为面试追问。
7. **交付物不是“跑通了”。** 一张 P99 对比图、命中率、每 Pod 请求分布、故障表、成本；缺一项不算 D4 完成。

---

## 1. 按计划定义 D4

### 1.0 什么是 Well-Lit Path（术语）

**Well-Lit Path 是 llm-d 官方“把路灯铺好”的部署路径**：针对某种推理模式，官方已经选好拓扑、参数和验证步骤，并在真实硬件上跑通过的 **end-to-end 配方**。它不是教程、不是 API 文档，也不是“所有参数的解释”。

三条 pillar：

| Pillar | 回答什么问题 | 例子 |
|---|---|---|
| **Foundations** | 某个能力怎么开、开了之后系统长什么样 | optimized baseline、precise prefix-cache routing、tiered prefix cache、PD 分离、wide EP |
| **Models** | 某个模型在某张卡上怎么跑到最好 | DeepSeek-V4 on GB200、GLM-5.2 on H200、Qwen3.5-397B on TPU |
| **Operations** | 集群日常怎么运营 | autoscaling、rollout、flow control、multi-model、batch |

一条 guide 必须包含：固定拓扑、可执行 manifest、Verify/Cleanup、**reference environment**（平台/卡/模型/引擎）、已知限制。成熟度分 Tier 0–5（Planned → Experimental → Deployable → Validated → Benchmarked → Proven）；**Tier 是绑在 reference environment 上的**，“H100 上 nightly 通过”不等于“L4/3060 上也能跑出同样数字”。

对 D4 的含义：

- 主实验跑 **Foundations / precise-prefix-cache-routing**；`optimized-baseline` 是 fallback/control；
- D4.5 对应 `pd-disaggregation`，D4.6 对应 `tiered-prefix-cache`；
- guide 的默认参考环境是 Qwen3-32B、TP=2、2 副本 = 4×H100；我们改成 Qwen3-4B-AWQ、TP=1、2 副本 = 2×3060 12GB，所以 **`peakPrefillThroughput` 要重测，绝对数字只和同机 round-robin 比**；
- Well-Lit Path 是“可复现的起点”，不是“可照抄的生产答案”；换模型/换卡后，硬件相关参数必须自己校准。

### 1.0.1 缩略语表（D4 系列）

> 正文第一次出现时已尽量给全称；这里集中列出，便于回查。通用词（GPU/CPU/API/HTTP/JSON/YAML）不展开。

| 缩写 | 全称 | 中文/备注 |
|---|---|---|
| TTFT | Time to First Token | 首 token 延迟 |
| TPOT | Time Per Output Token | 每输出 token 耗时 |
| ITL | Inter-Token Latency | token 间延迟 |
| SLO | Service Level Objective | 服务等级目标 |
| EPP | Endpoint Picker | 端点选择器 |
| KV | Key-Value | 键值（KV cache） |
| PD / P/D | Prefill/Decode | 预填充/解码 |
| HBM | High Bandwidth Memory | 高带宽显存 |
| TP | Tensor Parallelism | 张量并行 |
| PP | Pipeline Parallelism | 流水线并行 |
| EP | Expert Parallelism | 专家并行 |
| DP | Data Parallelism | 数据并行 |
| MoE | Mixture of Experts | 混合专家 |
| NIXL | NVIDIA Inference Xfer Library | NVIDIA 推理传输库 |
| GAIE | Gateway API Inference Extension | Gateway API 推理扩展 |
| CRD | Custom Resource Definition | 自定义资源定义 |
| LWS | LeaderWorkerSet | K8s 多 Pod 组控制器 |
| KEDA | Kubernetes Event-driven Autoscaling | 事件驱动自动扩缩 |
| HPA | Horizontal Pod Autoscaler | 水平 Pod 自动扩缩器 |
| PDB | Pod Disruption Budget | Pod 中断预算 |
| AWQ | Activation-aware Weight Quantization | 激活感知权重量化 |
| FP8 / FP16 | 8-bit / 16-bit Floating Point | 8/16 位浮点 |
| GPTQ | GPT Quantization | GPT 量化 |
| LoRA | Low-Rank Adaptation | 低秩适配 |
| MIG | Multi-Instance GPU | 多实例 GPU |
| DRA | Dynamic Resource Allocation | 动态资源分配 |
| DCGM | Data Center GPU Manager | GPU 监控 |
| OTel | OpenTelemetry | 可观测性框架 |
| LLM | Large Language Model | 大语言模型 |
| K8s | Kubernetes | 容器编排 |
| RDMA | Remote Direct Memory Access | 远程直接内存访问 |
| CNI | Container Network Interface | 容器网络接口 |
| CSI | Container Storage Interface | 容器存储接口 |
| E2E | End-to-End | 端到端 |
| OOM | Out Of Memory | 内存耗尽 |
| PCIe | Peripheral Component Interconnect Express | 高速外设互连 |
| P50 / P95 / P99 | 50th / 95th / 99th percentile | 第 50/95/99 百分位 |
| QoS | Quality of Service | 服务质量 |
| RBAC | Role-Based Access Control | 基于角色的访问控制 |

### 1.0.2 并行方式速查（TP / PP / DP / EP）

> 这一节回答“多张卡怎么用”，也是 §3.1 选 `TP=1 × 2 副本` 的依据。flag 以 `vllm serve --help` 为准（本文镜像是 `vllm/vllm-openai:v0.34.0`）。

**四种并行切的是什么**

| 维度 | 切什么 | 通信 | 频率 | 放哪 | vLLM flag | 解决什么 |
|---|---|---|---|---|---|---|
| TP | 每层权重矩阵 | all-reduce | 每层一次 | 节点内（NVLink） | `--tensor-parallel-size` | 单卡装不下 / 降单请求延迟 |
| PP | 连续若干层 | stage 间 p2p 传 activation | 每 microbatch 一次 | 可跨节点 | `--pipeline-parallel-size` | 单节点也装不下 / 卡间无 NVLink |
| DP | 整个模型复制 | 推理时无 | — | 任意 | `--data-parallel-size`（内部）或不带 DP flag 的独立实例（外部） | 提吞吐 |
| EP | MoE 专家 | all-to-all | 每层（MoE） | 跨节点（RDMA） | `--enable-expert-parallel` | 专家多到单机放不下 |

**TP vs 副本：延迟换吞吐**

- TP 把同一层的矩阵拆到多卡，每卡算得更少 → 单请求 TTFT/TPOT 更低；但每层 all-reduce，PCIe 上开销大，**总吞吐不涨反可能降**。
- 副本复制整个模型，副本间零通信 → 总吞吐近似线性涨，单请求延迟不变。
- 故障域：TP 是一个进程组，一崩全崩；副本挂一个还剩一半。
- 扩容粒度：TP=2 是 2 卡一跳；副本是 1 卡一跳。
- 前缀缓存：TP 内部仍是一份逻辑 KV cache；副本是 N 份独立 cache，互相看不见——**这正是 D4 要测的东西**。
- 2×3060 上的具体选型和四条理由见 §3.1「为什么是 2 副本 × TP=1」。

**vLLM 自带的 DP 有三种形态**

| 形态 | 启动 | 入口 | 谁选副本 | 是否 KV-aware |
|---|---|---|---|---|
| 内部 DP | `--data-parallel-size N` | 一个 | vLLM API server | 否，只看 running/waiting 队列 |
| Hybrid LB | `--data-parallel-hybrid-lb` | 每节点一个 | 上游 LB + 节点内 API server | 否 |
| 外部 DP | N 个独立 `vllm serve`，不带 `--data-parallel-*` | N 个 | 外部 router（Envoy/EPP） | 取决于 router |

- 内部 DP 是「engine core 复制、API server 共享」：一个 endpoint，N 份权重、N 份独立 KV cache；`--max-num-seqs` 按 rank 计，`--max-num-queued-reqs` / `--max-num-queued-tokens` 按整个 server 计。
- DP 与 TP 正交：`--data-parallel-size 4 --tensor-parallel-size 2` 需要 8 张卡。
- 官方文档原话：内部 LB「could be made more sophisticated in future by incorporating KV cache aware logic」——**vLLM 知道每个 rank 有独立 KV cache，但还没做前缀感知路由**，这就是 llm-d/EPP 的空间。
- 对非 MoE 模型，外部 DP 就是「起 N 个完全独立的 vLLM，前面挂 router」；`--data-parallel-rank` 那套 CLI 只在 MoE 的 DP+EP 场景需要。

**PP 可以跨节点，但不必跨节点**

- PP 按层切：36 层的 4B 用 `--pipeline-parallel-size 2`，就是每卡 18 层。
- 通信只在 stage 边界传 activation，量级远小于 TP 的每层 all-reduce → **适合跨节点**。
- 实践公式：`TP = 每节点 GPU 数，PP = 节点数`；2 节点 × 8 卡就是 TP=8、PP=2。
- 跨节点两种跑法：Ray（`--distributed-executor-backend ray`），或 mp 后端 + `--nnodes/--node-rank/--master-addr`，worker 节点加 `--headless`。
- 代价是 **pipeline bubble**：batch=1 时 stage 0 算完要等 stage 1，fill/drain 让首 token 更慢；并发高、气泡被连续批处理填满后吞吐才起来。所以 PP 是吞吐/容量工具，不是延迟工具。
- vLLM 文档的边角结论：**卡间没有 NVLink（如 L40S）时，拆模型优先用 PP 而不是 TP**，因为 all-reduce 太贵。2×3060 同理，但 4B 根本不需要拆。
- 约束：模型必须实现 `SupportsPP`，否则启动报错；层要能切（vLLM 支持不等分，但每段至少一层）。
- **PP ≠ P/D 分离**：PP 是同一请求在层维度串行，仍是一个实例、一份逻辑 KV；P/D 是把 prefill/decode 拆成两个服务并传 KV。D4.5 做的是后者。

**选型顺序**

```text
单卡装得下吗？          否 → 加 TP 到装得下
单卡延迟达 SLO 吗？     否 → 继续加 TP
还有卡？                   → 全部做副本（DP）
模型跨节点？               → TP 留在节点内，PP 跨节点
MoE 专家放不下？           → EP（需要 RDMA）
```

### 1.1 计划里的 D4 要求

| 计划要求 | 本文对应 | 产出 |
|---|---|---|
| 4h、2×3060 12GB VM | §3、§10.5 | 时间盒 + 资源规划 |
| 按 Well-Lit Path 跑 `precise-prefix-cache-routing`（或 optimized baseline） | §5 | 可执行步骤 + fallback |
| 同一批“共享长前缀”的请求，对比普通 round-robin vs EPP 的 P99 | §6 | 4 个 arm（T0 optimized + T1 precise）、固定 workload、JSON |
| 一张 P99 对比图 + 命中率数字 | §6.6、§6.8 | `d4-ttft.png` + hit rate 表 |
| B 线：Gateway/`InferencePool`/EPP 运维图 + 路由故障表 | §7 | 图 + 表 |
| 方法学必须一起写 | §6.4 | 样本、warmup、重复、开环/闭环、SLO、单价、货币 |
| llm-d 四问 | §8 | EPP / InferencePool / PD / wide EP |
| 核心 feature 全景 | §1.4 + 附录 A | 19 项覆盖矩阵；D 档能讲清“何时用/不用” |

> 这只是 D4 主实验的验收；llm-d 的其余核心 feature 用 §1.4 的覆盖矩阵和附录 A 的决策/蓝图覆盖，不额外租卡。

### 1.2 D4 不做什么

按计划的“不要做的三件事”和 4h 预算：

- **不读 production-stack**：它是给已有集群的人看的；D3/D4 已经够用。
- **不把 10 条 Well-Lit Path 都看一遍**：只跑 precise；optimized baseline 只作为 fallback。
- **不在 vLLM quickstart 没跑通时碰 llm-d**：本 lab 的模型服务器就是 vLLM 的最小验证。
- **不跑 PD 分离、wide EP、多模型**：只看概念，不进验收；附录 A 给“什么时候值得/不划算”和最小实验蓝图。
- **不装生产 Gateway**（Istio / Envoy Gateway / agentgateway）：D4 用 standalone + `InferencePool` 足够；Gateway Mode 只给 YAML 和面试讲法。
- **不在 `uat-mobility-aks-01` 上跑任何东西**。

### 1.3 和 D3 的衔接

D4 不是从零开始，它直接用 D3 的集群和结论：

| D3 的结果 | D4 怎么用 |
|---|---|
| 2 副本、每副本 1 GPU | 路由的前提；单副本没有 EPP 收益 |
| 冷启动约 116s（HPA（Horizontal Pod Autoscaler，水平 Pod 自动扩缩器）决策→Ready） | D4 不重复测冷启动；EPP 0→1 仍受这个时间约束 |
| `preStop 15s` + `--shutdown-timeout=45` + grace 120s | D4 的模型服务器沿用；滚动更新时在途请求可排空 |
| KEDA 按队列扩缩 | Lab 0 的 0→1 入口；D4 主实验把 `minReplicaCount` 保持在 1 |
| 单卡 1→2 Pending | D4 用 2 张卡，两个副本各 1 张；不测 Pending |

> 换句话说：D3 证明“副本能起来、能扩、能优雅退出”；D4 证明“多副本时请求该去哪一个”。两者不是重复实验。

### 1.4 llm-d 核心 feature 覆盖矩阵

D4 的“cover”分四档，避免把“读过”说成“跑过”：

| 标记 | 含义 |
|---|---|
| **H** | Hands-on：动手跑过，有配置/数字 |
| **C** | Config-ready：manifest/values 已就绪，未跑 |
| **D** | Decision：能讲清是什么、何时用/不用、怎么观测，但 D4 不跑 |
| **O** | Out of scope：明确不在 D4 范围 |

| # | 核心 feature | D4 档位 | 位置 |
|---|---|---|---|
| 1 | `InferencePool` / EPP / Envoy 数据面 | **H** | §5、§7 |
| 2 | precise prefix-cache routing（KV events + render） | **H** | §5、§6 |
| 3 | optimized baseline（近似 prefix + token load） | **H** | §5.10、§6 |
| 4 | KV events / KV index / `active_subscribers` | **H** | §5.4、§5.6 |
| 5 | load-aware scoring（token-load / active-request） | **H/C** | §5.1、`values-precise.yaml` |
| 6 | FailOpen / FailClose / 健康检查 | **H** | §7.3 |
| 7 | Gateway Mode / HTTPRoute | **C** | §7.6 |
| 8 | 多模型 / 多租户路由 | **D** | §7.2、§7.6、附录 A.4 |
| 9 | PD 分离（prefill/decode pools + NIXL；NIXL = NVIDIA Inference Xfer Library） | **D + D4.5** | §8 Q3、[`d4.5-pd-lab.md`](./d4.5-pd-lab.md) |
| 10 | wide EP / MoE（Mixture of Experts，混合专家）；DP（Data Parallelism，数据并行）/ EP + DeepEP | **D** | §8 Q4、附录 A.3 |
| 11 | flow control / fairness / priority / `InferenceObjective` | **D** + YAML | 附录 A.4 |
| 12 | tiered prefix cache（HBM（High Bandwidth Memory，高带宽显存）→CPU/FS） | **D + D4.6** | 附录 A.5、[`d4.6-tiered-cache-lab.md`](./d4.6-tiered-cache-lab.md) |
| 13 | P2P KV cache sharing（NIXL peer pull） | **D** | 附录 A.5 |
| 14 | autoscaling（KEDA + EPP metrics） | **D**；Lab 0 的 KEDA 0→1 是 **H** | 附录 A.6、§4 |
| 15 | batch / async serving | **D** | 附录 A.6 |
| 16 | rollouts / zero-downtime / 模型生命周期 | **D**；D3 的优雅退出是 **H** | 附录 A.7、D3 §9 |
| 17 | observability / tracing | **H**（metrics）/ **D**（tracing） | 附录 A.8 |
| 18 | API surface（chat / messages / responses / multimodal） | **D** | 附录 A.9 |
| 19 | predicted-latency routing（latency predictor） | **D** | 附录 A.1 |

**怎么读这张表：**

- D4 的**主实验**覆盖 **T0（optimized baseline + EPP/InferencePool）** 和 **T1-A（precise prefix routing）**，这是市场采用信号最强的一层；
- **T1-B（PD）** 在 [`d4.5-pd-lab.md`](./d4.5-pd-lab.md)，**T1-C（tiered KV）** 在 [`d4.6-tiered-cache-lab.md`](./d4.6-tiered-cache-lab.md)；两个都是独立 lab，不塞进 4h；
- wide EP、flow control、P2P、autoscaling、batch、rollout 以 **D 档**覆盖：能讲清、能给决策、能给最小实验蓝图，但不假装跑过；
- 这样面试时既不会被“你只会 prefix routing”卡住，也不会被“你 PD 的 KV 带宽多少”问穿。

> 附录 A 是这 19 项里 D 档内容的展开；主实验仍按 §5–§6 执行，不额外租卡。

### 1.5 T0 / T1 覆盖计划（按市场调研）

市场调研里 T0 = 入口级、T1 = 大规模生产主力。D4 用“一个 4h 主实验 + 两个独立 lab”覆盖：

| 层级 | Feature | 在哪做 | 时间/预算 | 产出 |
|---|---|---|---|---|
| **T0** | optimized baseline（approx prefix + token load） | **D4 第 4 个 arm** | 4h 内 | 1–3 轮 JSON；和 precise 对比 |
| **T0** | EPP / `InferencePool` / Gateway API Inference Extension | **D4 主实验 + §7** | 4h 内 | 运维图 + 故障表 |
| **T1** | precise prefix-cache routing | **D4 主实验** | 4h 内 | P99 + hit rate |
| **T1** | PD 分离 | **D4.5** | 本次 skipped/blocked | 4×3060 VM 不存在；2×3060 只有 2 卡；4×4090 5h 为可选项 |
| **T1** | tiered KV cache / offload | **D4.6** | 4–5h / ~$1.0–1.3 | tiered vs HBM-only；`kv_offload_*` 证据 |

> **为什么 T1 不都塞进 D4 的 4h：** T0 是“装一个 router 就能量”的入口；T1 的 PD 要第二个池 + NIXL，tiered 要 CPU tier + 额外内存。它们各自是独立拓扑/资源实验，塞进 4h 会把 D4 的“只改路由”变量弄脏。D4 的 4h 只做 T0 + T1-A；T1-B/C 单独排，但属于同一个学习计划。

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
| Envoy（EPP Pod 的 sidecar） | 数据面；ext_proc 调 EPP；转发/流式响应 | Pod 不 Ready；Service 没有 endpoint |
| EPP | 解析、tokenize、查索引、过滤/打分、选 Pod | FailOpen 时绕过 EPP；FailClose 时 503 |
| `InferencePool` | 声明“哪些 Pod 是模型服务器、端口是多少、EPP 是谁” | EPP 没有 endpoint；路由不到 |
| `token-producer` | 调 vLLM `/v1/*/render`，拿精确 token IDs | render 失败→无 cache 信息，仍可路由 |
| `precise-prefix-cache-producer` | 订阅 ZMQ KV 事件，建 block 索引 | 索引为空→退化成无 cache 感知 |
| `prefix-cache-affinity-filter` | 把前缀组留在 cache-warm Pod；过热时扩散 | 命中率下降；P99 变差 |
| `token-load-scorer` | 选 in-flight token 最少的候选 | 负载不均；热点 |
| vLLM | 推理、prefix caching、KV 事件、render 端点 | 请求失败/重试；EPP 摘除 endpoint |

> **Envoy 是谁的 sidecar：** 在 standalone 模式，Envoy 是 **EPP Pod 的 sidecar**（同一个 Pod 里两个 container：EPP + Envoy），**不是 vLLM Pod 的 sidecar**；由 `llm-d-router-standalone` chart 显式渲染，**不是 webhook 自动注入**。Envoy 在 Pod 内通过 `localhost:9002` 调 EPP 的 ext_proc，再把请求转发到选中的 vLLM Pod:8000。
>
> Gateway Mode 下，Envoy 是 Gateway 的数据面（Envoy Gateway / Istio），EPP 独立部署；也不是注入到模型 Pod。只有你额外装 Istio 并开启 namespace injection，才会有 Istio 自己的 Envoy sidecar 被注入，那是另一件事，D4 不用。

### 2.5 GAIE 与 llm-d 是什么关系

一句话：**GAIE 定标准，llm-d 做实现（并扩展）。**

| 层 | 谁负责 | 在 D4 集群里对应什么 |
|---|---|---|
| API 契约 | GAIE（Kubernetes SIG） | `InferencePool` CRD + 对象 `d4-router` |
| EPP 协议 | GAIE 规范（ext_proc / Endpoint Picker Protocol） | Envoy ↔ EPP 的 gRPC 9002 |
| EPP 实现 + 插件 | llm-d（`llm-d-router`） | `d4-router-epp` Pod 里的 `epp` 容器 |
| 数据面 | standalone 用 llm-d 自带 Envoy；Gateway Mode 用你的 Gateway | 同 Pod 的 `envoy-proxy` |
| 插件配置格式 | llm-d 扩展（`llm-d.ai/v1 EndpointPickerConfig`） | `values-precise.yaml` 的内联配置 |
| 模型服务 | vLLM（也可换 SGLang） | 两个 `vllm-d4` Pod |

**为什么会分成两个项目**：GAIE 早期自带 EPP 参考实现；2026 年 GAIE 把完整 EPP、`InferenceObjective`、`InferenceModelRewrite` 迁到 `llm-d/llm-d-router`，自己只保留 `InferencePool` CRD、EPP 协议规范和 conformance 测试。所以现在：

- 你 `kubectl apply` 的 GAIE `v1-manifests.yaml` **只有一个 CRD**（`InferencePool`）；
- 真正干活的 EPP 来自 llm-d 的镜像 `ghcr.io/llm-d/llm-d-router-endpoint-picker`。

**类比**：GAIE 像 USB 标准（接口、供电、协议），llm-d 像具体的 USB 设备。标准保证「任何符合协议的网关 + 任何符合协议的 EPP 能互通」；llm-d 在这个协议之上加了 precise prefix index、flow control 等自己的插件。

在现有集群里可以直接看出分工：

```bash
# CRD 来自 GAIE
kubectl get crd inferencepools.inference.networking.k8s.io -o jsonpath='{.spec.group}{"\n"}'
# inference.networking.k8s.io

# InferencePool 对象由 llm-d chart 创建
kubectl get inferencepool -n d4
# d4-router

# EPP 镜像来自 llm-d
kubectl get deploy -n d4 d4-router-epp \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="epp")].image}{"\n"}'
# ghcr.io/llm-d/llm-d-router-endpoint-picker:v1.0.0
```

> 三个容易混的概念：
> - **Gateway API**：`Gateway`/`HTTPRoute`，是 GAIE 的上游标准，只有 Gateway Mode 才需要；
> - **GAIE**：在 Gateway API 之上加 `InferencePool` + EPP 协议；
> - **llm-d**：整套推理平台（router / model server / PD / tiered cache），其中 router 实现了 GAIE 的 EPP。

**llm-d 有 operator 吗？** 上游 v1.0.0 **没有**。llm-d 走的是「Helm chart + well-lit path」的模块化路线；官方文档明确说，想要「单个 CRD 驱动整套部署」的用户应该用 **KServe 的 `LLMInferenceService`**。operator 形态只存在于依赖和下游：

| 形态 | 谁提供 | 管什么 |
|---|---|---|
| LWS + `DisaggregatedSet` controller | `kubernetes-sigs/lws` | 多机 Pod 组；PD 的 prefill/decode 作为一个版本整体滚动 |
| KEDA operator | KEDA | 按队列/饱和/token backlog 扩缩 |
| `LLMInferenceService` | KServe | 一个 CR 建出 vLLM + EPP + InferencePool |
| Red Hat AI Inference operator | Red Hat（下游产品） | 平台级 meta-operator，统管 KServe/llm-d/网关的版本与升级 |
| `InferenceScheduler` operator | 社区（非官方） | 单 CR 建 vLLM/Service/pool/Gateway |

> D4 用 Helm 就够：单模型、静态拓扑，加 operator 只会多一层抽象。真正需要 operator 的场景是「多租户、每个模型自动生成一套 pool + EPP」——那是 KServe 或下游平台要解决的问题。

---

## 3. 环境、版本、预算

### 3.1 机器规格

| 项 | 实际值 | 说明 |
|---|---|---|
| 实例 | Vast **62540497** | UK；`actual_status=running`，已可 SSH 登录；登录后先 `nvidia-smi` |
| GPU | **2×RTX 3060 12GB** | 每个副本 1 张，TP=1；只有 2 张卡，不能做 2P+2D |
| GPU 功耗 | 170W/卡 | 记录 `nvidia-smi -q -d POWER`；绝对数字不能和 D1/D2 的 40W L4 比 |
| CPU / RAM | 40 vCPU（effective）/ **98GB**（VM 内 `free -g`；Vast host 字段 252GB 不是 VM 配额） | 2×vLLM + EPP + Envoy + bench 客户端足够 |
| 磁盘 | 130GB 购买（VM 内 126G，120G 可用） | 镜像 ~10GB + 4B 权重 ~2.7GB + 结果/日志 |
| 价格 | **`$0.26148/h`**（含 130GB disk） | on-demand，按秒计费 |
| 镜像 / 驱动 | `docker.io/vastai/kvm:cuda-12.9.1-auto`；host driver 580.95.05，CUDA max 13.0 | `nvidia-smi` 确认两张卡都在 |
| SSH | `ssh3.vast.ai:16434` | 端口以 Vast 控制台为准 |
| 平台 | Vast.ai **on-demand VM** | 必须 `vms_enabled=true`；不要 interruptible；不要普通容器 |
| 网络 | 同机、同 CNI（Container Network Interface，容器网络接口） | 客户端和 vLLM 同集群，避免公网变量 |

> 如果只有 1 张卡，D4 不成立：没有第二个副本就没有路由问题。至少 2 张。
>
> **硬件前提复核（2026-11-25）：Vast 上没有 L4 VM。** `gpu_name=L4 vms_enabled=true` 返回 0；L4 只有容器实例（14 个，其中 8 个多卡：6×2 + 2×4，$0.50–1.87/h），而 k3s 需要 VM/systemd，普通容器起不来。D3 在 2026-11-23 已记录过这个限制，D4 原计划漏了它。
>
> **本次实际租到 2×RTX 3060 12GB（instance 62540497）**：12GB/卡、TP=1、2 副本；4B-AWQ 权重约 2.7GB，放得下，且单价只有 3090 的约 28%。2 卡 VM 的备选（2026-11-25 快照，库存会变）：
>
> | GPU | 地点 | $/h | RAM | 备注 |
> |---|---|---|---|---|
> | 2×3060 12GB | UK | 0.26148 | 98GB（VM） | **本次实际租用（62540497）** |
> | 2×3090 | UK | 0.935 | 251GB | 备选；24GB 显存，8B 也能跑 |
> | 2×4090 | Quebec | 0.935 | 125GB | 备选；更快，但 R<0.99 |
> | 2×5090 | UK | 1.868 | 503GB | 32GB，没必要 |
>
> 2×3090 只是备选：如果 62540497 起不来或要重租，再按下面的命令搜；结果必须把卡型改成 3090，不能和本次 3060 的数字混在一起。预检：
>
> ```bash
> vastai search offers 'gpu_name=L4 vms_enabled=true'                     # 期望 0
> vastai search offers 'gpu_name=RTX_3060 num_gpus=2 vms_enabled=true' -o 'dph+'
> vastai search offers 'gpu_name=RTX_3090 num_gpus=2 vms_enabled=true' -o 'dph+'   # 备选
> ```
>
> `vms_enabled=false` 的 VM 再便宜也不能用；同一 GPU 的 VM 和容器 offer ID 不同。创建后先 `nvidia-smi` 确认两张卡都在，再装 k3s。62540497 的镜像是 `docker.io/vastai/kvm:cuda-12.9.1-auto`（VM，不是容器）。

**为什么是「2 副本 × TP=1」，不是「单实例 × TP=2」**（四种并行的完整对比见 §1.0.2）

TP（Tensor Parallelism，张量并行）换单请求延迟，副本换总吞吐：

| 维度 | TP=2 单实例 | 2 副本 × TP=1 |
|---|---|---|
| 单请求 TTFT/TPOT | 更快（前向拆到 2 卡） | 不变 |
| 总吞吐 | 约 1 卡的 1.2–1.5 倍 | 约 2 倍 |
| 故障域 | 整个进程组，一崩全崩 | 挂一个还剩 50% |
| 扩容粒度 | 2 卡一跳 | 1 卡一跳 |
| 前缀缓存 | 一个逻辑 cache，天然全局命中 | 两个独立 cache，互相看不见 |

1. **4B-AWQ 放得下**：权重约 2.7GB，12GB 卡还剩约 7GB 给 KV；TP 的第一价值（单卡装不下才拆）用不上。
2. **3060 没有 NVLink**：TP 每层 all-reduce 只能走 PCIe，decode 小 batch 下固定开销占比高，实际加速远低于 2 倍；副本之间零通信。
3. **SLO 是 P99 + 高并发**：c=16/64 的瓶颈是单位时间 token 数，不是单流 TPOT；2 副本 = 2 份算力 + 2 份 batch 槽位。
4. **D4 要测路由，路由的前提是「有得选」**：单实例只有一个 KV cache，`direct`/`optimized`/`random`/`precise` 会退化成同一个数；2 副本才有「A 有、B 没有」这个状态。

> **vLLM 自带的 DP 为什么也不用：** `--data-parallel-size 2` 是「引擎内核复制、API server 共享」，内部 LB 只看各引擎的 running/waiting 队列，**不看 KV cache**（官方文档原话：could be made more sophisticated in future by incorporating KV cache aware logic），EPP 也插不进去。D4 的 2 副本是**外部 DP**：两个独立 Pod，路由权在 Envoy + EPP 手里。

> 选型法则：**取满足「放得下 + 单卡延迟达 SLO」的最小 TP，剩下的卡全做副本。** TP 与副本正交（可 `TP=2 × DP=2`）；本例两条都满足 → TP=1。换成 Qwen3-32B-AWQ（约 18GB）单卡装不下 → 必须 TP=2，那时也做不了路由实验。

### 3.1.1 从零安装环境（每台新 VM 独立）

**最快路径（推荐）**

在本地仓库根目录，把脚本传到 VM 并执行：

```bash
scp -i ~/.ssh/<key> -P <port> scripts/d4/bootstrap-vm.sh root@<host>:/root/
ssh -i ~/.ssh/<key> -p <port> root@<host> 'bash /root/bootstrap-vm.sh'
```

脚本默认 **`EXPECTED_GPUS=2`、不限定 GPU 型号**；换 1/4 卡或换卡型时不用改脚本，传 `EXPECTED_GPUS=1/4`、`EXPECTED_GPU_NAME='RTX 3090'` 即可。它会先停 `unattended-upgrades` / `apt-daily`，再等 apt/dpkg lock，装 NVIDIA toolkit、k3s、device plugin、Helm，最后建 `d4` namespace 并跑 `EXPECTED_GPUS` 张卡的 `gpu-smoke`。日志在 `/var/log/d4-bootstrap.log`，版本记录写到 `~/d4-versions.txt`。

> 如果 `nvidia-smi` 报 `Driver/library version mismatch`，脚本会 **exit 2** 并提示先 reboot；按提示 reboot 后重跑同一条命令。不要 kill 进程、不要删 lock、不要让脚本自动 reboot。

> **不要先手工 `apt-get install` 再跑脚本。** 脚本会在任何 apt 之前停自动升级；顺序反了会再次遇到 dpkg lock / driver mismatch。

**手工步骤（脚本失败或需要理解细节时再看）**

> **D1–D4 每天独立**：不要假设 D3 的 k3s 集群、namespace、镜像缓存、device plugin 还在。下面在**新 VM** 上从零执行；命令基线是 `d3-k8s-vllm-learning.md` §5.1–§5.5，D4 只把卡型/namespace 换成 **2×3060 12GB / `d4`**。装完再回 §5.2 下载权重。

**1）preflight：确认是 VM、两张卡都在**

```bash
ps -p 1 -o comm=                 # 必须是 systemd；不是就说明拿到的是容器，停止，重建 VM
nvidia-smi --query-gpu=name,memory.total,driver_version,compute_cap,power.limit \
  --format=csv,noheader
# 期望两行：RTX 3060 / 12288 MiB / 170 W 左右
df -h /                          # 期望 >=120GB 可用（购买 130GB，VM 内约 126G）
free -g                          # 期望 ~98GB（Vast host 字段 252GB 不是 VM 配额）
lsb_release -ds                  # Ubuntu 22.04.x LTS；没有该命令就 cat /etc/os-release
stat -fc %T /sys/fs/cgroup       # 期望 cgroup2fs
```

`ps -p 1` 不是 `systemd`、或 `nvidia-smi` 看不到两张 3060：不要继续装，先回 §3.1 换/重建 VM。不要为了“修好”一个容器实例去装 k3s。

**2）tmux：防 SSH 断线**

```bash
command -v tmux >/dev/null || echo "tmux 未安装：先做第 3 步停自动升级，再 sudo apt-get install -y tmux"
tmux new -s d4
# 断线后重连：tmux attach -t d4；暂时离开：Ctrl-b 然后 d
```

> 镜像没带 tmux 时**不要先 `apt-get install`**：先做第 3 步的“停自动升级”，再 `sudo apt-get install -y tmux`，然后回来 `tmux new -s d4`。

**tmux 速查**：tmux 是终端复用器，命令跑在 VM 的会话里，SSH 断了不会停。

```bash
tmux new -s d4
# 跑安装/长命令；SSH 断了重连后：
tmux ls
tmux attach -t d4
```

detach：`Ctrl-b` 松手，再按 `d`；会话继续在后台跑。

| 按键 | 作用 |
|---|---|
| `Ctrl-b d` | detach（离开但不停） |
| `Ctrl-b c` | 新建窗口 |
| `Ctrl-b 0/1` | 切到第 0/1 个窗口 |
| `Ctrl-b n/p` | 下一个/上一个窗口 |
| `Ctrl-b %` | 左右分屏 |
| `Ctrl-b "` | 上下分屏 |
| `Ctrl-b o` | 分屏间切换 |
| `Ctrl-b ?` | 查看所有快捷键 |

- `tmux new -s d4` 报 duplicate session → 用 `tmux attach -t d4`。
- Vast 可能自动 attach `ssh_tmux`；`echo $TMUX` 非空说明已在 tmux 里；`tmux ls` 看会话。
- 不要 `tmux kill-server`（会杀掉所有会话，包括正在跑的安装）。
- tmux **不跨 VM reboot**；k3s/vLLM 这类长期服务用 systemd，不靠 tmux。
- 结束会话：确认里面没跑东西后 `tmux kill-session -t d4`。
- `unattended-upgrade` 是 systemd 服务，不在 tmux 里；等锁释放、reboot 后，装 toolkit/k3s 时再把命令放进 tmux。

**3）先关自动升级，再装基础包（顺序不能反）**

Vast 的 Ubuntu VM 带自动升级 timer，可能把 NVIDIA 用户态驱动升到与内核模块不匹配；D3 已踩过。**在第一次 `apt-get install` 之前就关掉**：

```bash
systemctl list-timers --all | grep -E 'apt|unattended' || true
for u in unattended-upgrades.service apt-daily.service apt-daily-upgrade.service \
         apt-daily.timer apt-daily-upgrade.timer; do
  sudo systemctl stop "$u" 2>/dev/null || true
  sudo systemctl disable "$u" 2>/dev/null || true
  sudo systemctl mask "$u" 2>/dev/null || true
done
```

如果已经遇到 `Could not get lock /var/lib/dpkg/lock-frontend ... unattended-upgr`：**不要删 lock 文件**。先看进程，等它结束：

```bash
ps -fp "$(sudo fuser /var/lib/dpkg/lock-frontend 2>/dev/null | awk '{print $1}')" 2>/dev/null || true
while sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
  echo "waiting for dpkg lock"; sleep 5
done
sudo dpkg --configure -a
```

然后装基础包：

```bash
sudo apt-get update
sudo apt-get install -y curl ca-certificates jq git gnupg lsb-release tmux pciutils
```

**4）NVIDIA container toolkit（先于 k3s）**

```bash
# 目的：装 nvidia-container-runtime；k3s 启动时会探测 PATH 里的它
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
```

给宿主机 containerd 配 nvidia runtime（如果这台 VM 有独立 containerd）：

```bash
if systemctl cat containerd.service >/dev/null 2>&1; then
  sudo nvidia-ctk runtime configure --runtime=containerd
  sudo systemctl restart containerd
else
  echo "no standalone containerd; k3s will detect nvidia-container-runtime on start"
fi
```

> **k3s 用的是 embedded containerd，不读 `/etc/containerd/config.toml`。** 不要为了这一步另装一个 containerd 和 k3s 抢状态；k3s 首次启动会根据 `nvidia-container-runtime` 自动渲染 `/var/lib/rancher/k3s/agent/etc/containerd/config.toml`。第 5 步会验证 `grep nvidia`。

**5）k3s（版本与 D3 一致）**

```bash
curl -sfL https://get.k3s.io | sudo INSTALL_K3S_VERSION=v1.37.2+k3s1 sh -s - --write-kubeconfig-mode 644

sudo systemctl status k3s --no-pager
sudo k3s kubectl get nodes -o wide

mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown "$USER" ~/.kube/config
kubectl get nodes

# 目的：确认 k3s 的 containerd 配置里出现 nvidia
grep -n nvidia /var/lib/rancher/k3s/agent/etc/containerd/config.toml
```

如果 `grep` 没有输出：确认 `which nvidia-container-runtime` 在 `/usr/bin` 或 `/usr/local/bin`，再 `sudo systemctl restart k3s`；仍不行看 `journalctl -u k3s -n 100`。

**6）NVIDIA device plugin + `RuntimeClass/nvidia`**

```bash
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.18.0/deployments/static/nvidia-device-plugin.yml

# static manifest 不带 runtimeClassName；不 patch，device plugin 可能看不到 GPU
kubectl -n kube-system patch ds nvidia-device-plugin-daemonset --type merge \
  -p '{"spec":{"template":{"spec":{"runtimeClassName":"nvidia"}}}}'
kubectl -n kube-system rollout status ds/nvidia-device-plugin-daemonset --timeout=180s

kubectl get runtimeclass nvidia
```

如果 `RuntimeClass/nvidia` 不存在（k3s 没探测到），手动补：

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: nvidia
handler: nvidia
EOF
```

**7）Helm（D4 的 router 用 `helm upgrade --install`）**

```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version --short
```

**8）namespace + GPU smoke test（2 张卡）**

```bash
kubectl create namespace d4 --dry-run=client -o yaml | kubectl apply -f -

kubectl get node -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}{"\n"}'
# 期望 2

kubectl run gpu-smoke -n d4 --restart=Never \
  --image=nvidia/cuda:12.4.1-base-ubuntu22.04 \
  --overrides='{"apiVersion":"v1","spec":{"runtimeClassName":"nvidia","containers":[{"name":"gpu-smoke","image":"nvidia/cuda:12.4.1-base-ubuntu22.04","command":["nvidia-smi"],"resources":{"limits":{"nvidia.com/gpu":2}}}]}}'

kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/gpu-smoke -n d4 --timeout=180s
kubectl logs -n d4 gpu-smoke
kubectl delete pod -n d4 gpu-smoke
```

`kubectl logs` 里必须出现两张 **RTX 3060 12GB**；只出现一张说明 `nvidia.com/gpu` 或 device plugin 只暴露了 1 张，回第 6 步。

**9）版本与功耗记录**

```bash
{
  echo "== date"; date -Is
  echo "== k3s"; k3s --version
  echo "== kubectl"; kubectl version --client
  echo "== helm"; helm version --short
  echo "== ctk"; nvidia-ctk --version
  echo "== gpu"; nvidia-smi --query-gpu=name,memory.total,driver_version,compute_cap,power.limit \
    --format=csv,noheader
  echo "== gpu-summary"; nvidia-smi | sed -n '1,4p'
} | tee ~/d4-versions.txt
```

**验证清单（缺一项不进入 §5.2）：**

- [ ] `kubectl get nodes` 为 `Ready`；
- [ ] `kubectl get node -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}'` 返回 `2`；
- [ ] `gpu-smoke` 的 `nvidia-smi` 输出两张 RTX 3060 12GB；
- [ ] `gpu-smoke` Pod 已删除；
- [ ] `~/d4-versions.txt` 记录了 k3s / driver / CUDA / helm / kubectl / power limit。

**常见失败排查：**

| 现象 | 原因 | 处理 |
|---|---|---|
| `nvidia-smi: command not found` | 镜像没带 driver，或根本不是 GPU VM | `lspci` 看有没有 NVIDIA 设备；没有 GPU 就重建 VM，不要盲装数据中心的 driver |
| `nvidia-smi` 报 `Driver/library version mismatch` | apt 把用户态驱动升级了，内核模块还是旧版 | 重启 VM 让新模块加载；确认 `nvidia-smi` 正常后再继续，并检查自动升级 timer 已关 |
| k3s 起来但 `grep nvidia` 无输出 | toolkit 装在 k3s 之后，或 runtime 不在 PATH | `which nvidia-container-runtime`；`sudo systemctl restart k3s`；看 `journalctl -u k3s -n 100` |
| device plugin Pod 不 Ready | 没 patch `runtimeClassName`，或镜像拉取失败 | `kubectl -n kube-system describe pod -l name=nvidia-device-plugin-ds`；补 patch 后重启 DS |
| `RuntimeClass/nvidia` 不存在 | k3s 首次启动没探测到 nvidia runtime | 按第 6 步手动创建；`handler` 必须是 `nvidia` |
| k3s 根本起不来 / `ps -p 1` 不是 systemd | 拿到的是普通容器，不是 VM | 停止；回 §3.1 用 `vms_enabled=true` 的 VM 重建，不要在容器里硬装 |
| `allocatable nvidia.com/gpu` 为 0 或空 | device plugin 没注册成功 | 看 DS 日志是否有 `Registered device plugin`；确认 patch 生效；等几秒再查 |
| `kubectl` 连不上 / node NotReady | kubeconfig 没拷、k3s 服务失败、磁盘满 | `systemctl status k3s`；`journalctl -u k3s`；`df -h /` |

> 这一节只装环境，不跑 vLLM/bench。装完 `nvidia.com/gpu=2`、`RuntimeClass/nvidia`、`helm` 都验证过，再进 §5.2 下载 `Qwen/Qwen3-4B-AWQ`。

### 3.2 和 llm-d guide 默认配置的差异

| 项 | guide 默认 | D4 | 影响 |
|---|---|---|---|
| 模型 | `Qwen/Qwen3-32B` | `Qwen/Qwen3-4B-AWQ` | 权重约 2.7GB（4-bit），12GB 卡放得下；KV 几何与 8B 相同 |
| TP | 2 | 1 | 每个副本 1 张 3060 |
| 副本 | 2 | 2 | 共 2 张卡 |
| GPU | 4×H100 80GB | 2×RTX 3060 12GB | **绝对数字不可比** |
| `modelName` | `Qwen/Qwen3-32B` | `qwen3-4b` | 必须等于 `--served-model-name` |
| `peakPrefillThroughput` | 15926（H100/Qwen3-32B） | 用 calibration 重测 | 不重测就相当于关掉 saturation gate |
| 请求长度 | guide 示例 ~2k 前缀 | 1100 words ≈ 1.5k tokens | 按 3060 12GB 的 KV 预算设计；32 个前缀合计约 6.8GB，接近单卡 KV 容量，正好制造 cache 竞争 |

> 这张表是面试时要主动说的：**“我跑的是同一条 Well-Lit Path，但不是同一个参考配置；所以我的 P99 只和同机的 round-robin 比，不和 llm-d 公布的 H100 数字比，也不和 D1/D2 的 40W L4 比。”**
>
> 也正因为默认配置是 4×H100，**D4 不按 Quickstart 的默认 manifest 跑**（那会直接 Pending）；直接用 §5.3 的 2×3060 适配 manifest，把 2h 的默认部署时间省给主实验。Quickstart 只读它的请求路径和 CRD（Custom Resource Definition，自定义资源定义）安装顺序。

### 3.3 资源规划

| 组件 | requests | limits | 备注 |
|---|---|---|---|
| vLLM ×2 | 4 CPU / 16Gi / 1 GPU | 8 CPU / 24Gi / 1 GPU | `--gpu-memory-utilization=0.90` |
| EPP | 2 CPU / 4Gi | 8Gi | 单副本 |
| Envoy | 1 CPU / 1Gi | 2Gi | sidecar |
| bench 客户端 | 2 CPU / 4Gi | 4 CPU / 8Gi | 不用 GPU |
| 合计 requests | ~13 CPU / ~41Gi | — | 40 vCPU / 98GB 够 |

### 3.4 版本矩阵与预检

| 组件 | 版本 | 预检 |
|---|---|---|
| k3s | D3 同版本 | `kubectl version` |
| NVIDIA driver | 记录 | `nvidia-smi`；`nvidia.com/gpu` allocatable=2 |
| vLLM | `v0.34.0` | `vllm serve --help` 确认 `--enable-scale-out`、`--kv-events-config`、`--block-size` |
| llm-d | `v1.0.0` | `helm show chart oci://ghcr.io/llm-d/charts/llm-d-router-standalone --version v1.0.0` |
| GAIE（Gateway API Inference Extension） CRDs | `v1.6.2` | `kubectl get crd inferencepools.inference.networking.k8s.io` |
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

2×3060 12GB VM on-demand 为 **`$0.26148/h`**（含 130GB disk，2026-11-25 实例 62540497 的实际单价）；4h 实验 + 1h 安装/排障 ≈ **`$1.31`**。D3 后 credit 约 `$14.93`，D4 后约 `$13.6`。记录实付，Destroy 前以 Vast 账单为准。

---

## 4. Lab 0（前置，可选）：KEDA HTTP Add-on 0→1

> **4h 不够时先砍这一节。** 它不是 D4 的主菜；它回答的是“0 副本时请求怎么进来”。如果你已经做过 D3 §8.7 的 scale-to-zero 负结果，Lab 0 只是把失败变成可用的 0→1。
>
> **D4 在独立 VM 上默认跳过这一节。** Lab 0 是 D3 的 0→1 延续，命令里的 `vllm-qwen3-8b` 是 D3 集群的 Deployment；只有你明确复用 D3 集群时才看它。新 VM 直接从 §5 的 Lab 1 开始，不要为了 Lab 0 去装 KEDA HTTP Add-on。

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

**一句话定位：optimized 是「推断」，precise 是「观测」。**

- optimized：EPP 只根据自己路由过的请求和前缀 hash，推断副本「大概」缓存了什么；和 vLLM 之间只有数据面交互，**没有 KV 状态面**。
- precise：vLLM 通过 ZMQ 把 KV block 的分配/驱逐推给 EPP，EPP 再用引擎的 `/render` 对齐 token IDs，得到和引擎一致的实时索引。

> 所以差别是**信息保真度**，不是功能多少：optimized 的失败模式是「**猜错**」（驱逐、旁路请求、分词差异），precise 的失败模式是「**没收到/对不齐**」（事件断流、索引为空、`block-size` 不匹配）。precise 更准，但和 vLLM 强耦合、故障面更大——§6.7 要求用 P99 和命中率证明它值这个复杂度，赢不了 optimized 就说明成本没换来收益。

**两种模式各自需要哪些 vLLM flag**

| vLLM flag | optimized | precise | 作用 |
|---|---|---|---|
| `--enable-prefix-caching` | 要 | 要 | 打开自动前缀缓存；没有它，路由到哪都没有缓存可命中 |
| `--served-model-name` | 要 | 要 | 请求的 `model`、EPP 的 `modelName`、KV topic 三者对齐 |
| `--enable-scale-out` | 不要 | **要** | 注册 `/v1/*/render`，EPP 用引擎 tokenizer 拿 token IDs |
| `--kv-events-config` | 不要 | **要** | ZMQ PUB 上报 block 分配/驱逐（5556），replay 在 5559 |
| `--block-size=64` | 不要 | **要** | 和 EPP 的 `blockSizeTokens` 对齐，否则永远 miss |

> `optimized` 只要 EPP + 普通 OpenAI 接口；`precise` 多出的这三行，就是“llm-d 与 vLLM 的 KV 状态面交互”。每个 flag 的完整作用、失败表现和对齐关系见 §5.3。

**为什么必须精确 token IDs？** vLLM 的 prefix cache 以 block 为单位；EPP 如果自己用另一套 tokenizer 或近似 hash，算出来的 block key 和 vLLM 的不一致，索引查不到，路由就退化成普通负载均衡。

**为什么 P99 会变？** 单请求的 TTFT（Time to First Token，首 token 延迟）可以粗略拆成：

```text
TTFT ≈ 排队时间 + prefill(prompt_tokens - cached_tokens) / prefill_throughput + 首 token 开销
```

EPP 把请求送到已经缓存了这段前缀的副本，等价于把 `cached_tokens` 抬高、把 prefill 时间压低；在 c=16 的闭环里，prefill 变短还会减少 decode 被 prefill 抢占的时间，所以尾延迟的改善通常大于“少算一次 prefill”本身。反过来，如果前缀没有复用、或 EPP 的 tokenize/索引开销大于省下的 prefill，P99 就不会变好——这就是 §6.7 要判读的东西。

### 5.2 前置：k3s + GPU + 权重

本次实例 **62540497 已经是 2×RTX 3060 12GB VM**（`actual_status=running`，已可 SSH 登录），不用重新创建；登录后按 **§3.1.1** 从零装 NVIDIA toolkit、k3s、device plugin。如果实例起不来、要重租，搜 2 卡 3060 VM：

```bash
# 本次卡型是 RTX 3060 12GB；L4 VM 不存在（gpu_name=L4 vms_enabled=true 返回 0），不要浪费时间。
vastai search offers -n \
  'num_gpus=2 gpu_name=RTX_3060 rentable=true vms_enabled=true cuda_vers>=13.0 disk_space>=130 inet_down>=500 cpu_ram>=64' \
  -o 'dph' --storage 130 --limit 15
```

**重租时必须走 D3 §5.0 的 API + `"vm": true`**；`vastai create instance` 的 CLI payload 不带 `vm` 字段，可能起成普通容器（SSH 拒绝、k3s 起不来）。拿到 offer ID 后复用 D3 §5.0 的 `curl PUT /asks/<OFFER_ID>/`，把 `disk` 设为 130、`label` 改成 `d4-llmd`。62540497 的镜像是 `docker.io/vastai/kvm:cuda-12.9.1-auto`，已经是 VM。

以下命令都在 lab 仓库根目录执行：

```bash
cd /path/to/llm-inference-platform-lab
export LAB=$(pwd)

nvidia-smi
kubectl get nodes -o wide
kubectl get nodes -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}{"\n"}'
# 期望 2
```

> **VM 上的固定布局（本 lab 约定）**：`/root/lab/{scripts,llm-d,notes}`，`export LAB=/root/lab`（已写入 `/etc/profile.d/lab.sh` 和 `~/.bashrc`）；`models -> /models`、`results -> /results`。新 VM 按这个建目录，不要把 `llm-d`、`scripts` 散在 `/root` 下。**`LAB` 必须同时包含 `scripts/` 和 `llm-d/`**，否则 §5.5 的 `guides/recipes/...` 会报 `no such file or directory`。

下载权重到宿主机（两个 Pod 共享，不要每个 Pod 各下一次）：

```bash
sudo mkdir -p /models
sudo apt-get install -y python3-pip
sudo python3 -m pip install -U huggingface_hub

sudo python3 - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen3-4B-AWQ", local_dir="/models/Qwen3-4B-AWQ")
PY

# 关键：确认没有指向 /workspace/hf 的 symlink；Pod 只挂 /models，symlink 会断
find /models/Qwen3-4B-AWQ -type l | head
# 如果输出非空，重新下载为实体文件，或把 /workspace/hf 一起挂进 Pod
ls /models/Qwen3-4B-AWQ | head
```

4B-AWQ 权重约 2.7GB；下载和 Pod 启动都比 8B 快，但仍要先确认 `config.json` 和 `model.safetensors` 完整。

预拉镜像（可选，减少 Pod 启动时间）：

```bash
sudo k3s ctr images pull docker.io/vllm/vllm-openai:v0.34.0
```

准备结果目录：

```bash
sudo mkdir -p /results
sudo chmod 777 /results
```

> **以上「下载权重 / 预拉镜像 / 建结果目录」已内置在 `scripts/d4/bootstrap-vm.sh` 的 12–14 步**：正常只需跑一次脚本，不用手工重复。`SKIP_MODEL_DOWNLOAD=1`、`SKIP_VLLM_PULL=1` 可分别跳过；`MODEL_ID` / `MODEL_DIR` / `VLLM_IMAGE` / `RESULTS_DIR` 可覆盖默认值。手工执行时按本节命令。

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

期望返回 `qwen3-4b`。

**`modelserver.yaml` 里每个 flag 为什么这么写**

precise 路由不是“开个 EPP 就行”，它依赖 vLLM 暴露三样东西：**引擎的 tokenizer（render）**、**真实的 KV block 事件（ZMQ）**、**和 EPP 一致的 block 粒度**。下面按“必需 / 影响结果 / 运维”分组。

**A. precise 必需（少一个就跑不成 precise）**

| flag | 作用 | 不设或设错会怎样 |
|---|---|---|
| `--enable-scale-out` | 注册 `/v1/completions/render`、`/v1/chat/completions/render`、`/v1/responses/render`，EPP 的 token-producer 靠它拿到引擎 tokenizer 的 token IDs | 404；EPP 无法 tokenize，precise 直接不可用 |
| `--kv-events-config '{...}'` | 打开 ZMQ PUB，上报 KV block 的分配/驱逐；JSON 需含 `enable_kv_cache_events=true`、`publisher=zmq`、`endpoint=tcp://*:5556`、`replay_endpoint=tcp://*:5559`、`topic=kv@<podIP>:<port>@<model>` | `publisher` 默认 `null`，5556 不监听；EPP 索引为空，`active_subscribers=0` |
| `--block-size=64` | 固定 KV block 粒度，保证引擎的 block key 和 EPP 的索引一致 | 默认 16；和 EPP 的 `blockSizeTokens` 不一致时**不报错，只是永远 miss** |
| `--served-model-name=qwen3-4b` | 让请求里的 `model`、EPP 的 `modelName`、KV topic 三者对齐 | 请求 404 `model not found`，或事件 topic 匹配不上 |
| `--enable-prefix-caching` | 打开 vLLM 自动前缀缓存——路由到“有缓存”的副本，前提是那里真有缓存 | V1 多数版本默认已开；显式写是为了不依赖版本默认值。关掉则 precise 收益归零 |

**B. 影响命中率 / 延迟（不是 precise 专用，但会改变结果）**

| flag | 作用 | 对 D4 的影响 |
|---|---|---|
| `--max-model-len=8192` | 单请求上下文上限 | 决定单个 session 的 KV 占用；32×1.5k tokens 的 cache 竞争就按它算 |
| `--gpu-memory-utilization=0.90` | 分配给 KV cache 的显存比例 | 越高 block 越多、驱逐越少、命中越高，但 activation 余量越小 |
| `--max-num-seqs=16` | 每副本最大并发序列数 | 和压测 c=16 对齐；太小会排队，太大 KV 峰值过高 |
| `--max-num-batched-tokens=4096` | 单步最多处理多少 token（chunked prefill 预算） | 影响 TTFT 和 prefill/decode 抢占；四个 arm 必须保持一致 |

**C. 运维 / 噪声（不影响正确性）**

| flag | 作用 |
|---|---|
| `--shutdown-timeout=45` | 优雅退出，等 in-flight 请求跑完 |
| `--disable-log-requests` | 关逐请求日志，避免压测时 I/O 拖慢 |

**vLLM 与 EPP 的对齐关系**（任何一项不一致，precise 都不报错，只会静默 miss）：

| vLLM | EPP（`values-precise.yaml`） |
|---|---|
| `--block-size=64` | `blockSizeTokens: 64` |
| `endpoint: tcp://*:5556` | `socketPort: 5556` |
| `replay_endpoint: tcp://*:5559` | `replaySocketPort: 5559` |
| `topic: kv@...` | `topicFilter: "kv@"` |
| `--served-model-name=qwen3-4b` | `modelName: qwen3-4b` |

### 5.4 验证 render 与 KV events

这一步验收两个前提：**两个 Pod 都能用引擎 tokenizer 渲染 token IDs**，**KV events 的 PUB/REPLAY 都在监听**。两者都由 flag 显式打开，默认是关的：

| 能力 | 打开它的 flag | 默认 | 缺了的表现 |
|---|---|---|---|
| `/v1/completions/render`、`/v1/chat/completions/render`、`/v1/responses/render` | `--enable-scale-out` | **关** | 404 |
| KV events PUB（5556） | `--kv-events-config` 里的 `enable_kv_cache_events=true` + `publisher=zmq` + `endpoint=tcp://*:5556` | **关**（publisher=`null`） | 5556 不监听，EPP `active_subscribers=0` |
| replay（5559） | 同一 JSON 的 `replay_endpoint` | 空 | EPP 重启后补不了历史 |
| 索引能对上 | `--block-size=64` + `topic` | block 16（以启动日志为准） | key 对不上、永远 miss |

> `vllm launch render` 和 `vllm serve --tokens-only` **总是**注册 render 端点，不受 `--enable-scale-out` 影响；D4 不用这两种模式。
>
> 对应 `modelserver.yaml` 的三行：`--enable-scale-out`、`--kv-events-config`、`--block-size=64`；每个 flag 的完整说明见 §5.3。`optimized` baseline 两个能力都不需要，见 §5.10。
>
> `--enable-prefix-caching` 只影响“命中能不能发生”，不影响这两个能力是否可用。

**1）render：两个 Pod 都要返回 `token_ids`**

在**宿主**上跑，少一层测试 Pod 的网络和 attach 干扰：

```bash
POD_IPS=$(kubectl get pods -n d4 -l app=vllm-d4 -o jsonpath='{range .items[*]}{.status.podIP}{" "}{end}')
for ip in $POD_IPS; do
  code=$(curl -sS -m 5 -o "/tmp/render-$ip.json" -w '%{http_code}' \
    -X POST "http://$ip:8000/v1/completions/render" \
    -H "Content-Type: application/json" \
    -d '{"model":"qwen3-4b","prompt":"render check","max_tokens":1}')
  echo "== $ip http=$code $(grep -o '"token_ids":\[[^]]*\]' "/tmp/render-$ip.json" | head -1)"
done
# 期望两行：http=200 token_ids=[7322,...]
```

- **404**：`--enable-scale-out` 没开（默认 false）。先确认版本支持，再决定是否走 §5.10：
  ```bash
  kubectl exec -n d4 deploy/vllm-d4 -- vllm serve --help | grep enable-scale-out
  ```
- **只打印一个 IP 就结束**：测试脚本被打断（常见于 `kubectl run -i` 的 attach 流被 `head` 提前关闭），不是 vLLM 返回空；用上面的宿主 curl 复测即可。

**2）KV events：声明、监听、可达是三件事**

`kubectl get pods -o wide` **没有 PORTS 列**，K8s 不像 `docker ps` 那样显示端口。

| 层级 | 含义 | 判据 |
|---|---|---|
| 声明 | `spec.containers[].ports` 写了什么 | `http=8000 kv-events=5556 kv-replay=5559` |
| 监听 | 进程真的 bind 了 | Pod 内连 `127.0.0.1:5556/5559` 为 open |
| 可达 | 别的 Pod 能不能连上 | 宿主连 Pod IP 为 open（EPP 走 Pod 网络） |

```bash
# 声明
kubectl get pods -n d4 -l app=vllm-d4 \
  -o jsonpath='{range .items[*]}{.metadata.name}{"  "}{range .spec.containers[0].ports[*]}{.name}={.containerPort}{" "}{end}{"\n"}{end}'

# 监听（Pod 内连本地端口；vLLM 镜像自带 python3）
for pod in $(kubectl get pods -n d4 -l app=vllm-d4 -o name); do
  echo -n "$pod: "
  kubectl exec -n d4 "$pod" -- python3 -c 'import socket; [print(p, "open" if socket.socket().connect_ex(("127.0.0.1", p)) == 0 else "closed") for p in (5556, 5559)]' | tr '\n' ' '
  echo
done

# 可达（宿主 -> Pod IP；单节点 k3s 默认没有 NetworkPolicy）
for ip in $(kubectl get pods -n d4 -l app=vllm-d4 -o jsonpath='{range .items[*]}{.status.podIP}{" "}{end}'); do
  python3 - "$ip" <<'PY'
import socket, sys
ip = sys.argv[1]
print(ip, *(f"{p}={'open' if socket.socket().connect_ex((ip, p)) == 0 else 'closed'}" for p in (5556, 5559)))
PY
done
# 期望两个 Pod 都是 5556=open 5559=open
```

> 5556 `closed` → `--kv-events-config` 没生效（看 Pod args 和启动日志）；`open` 但 EPP 订阅不到 → 看 §5.6 的 `active_subscribers`。**端口 open 只证明 vLLM 在发，最终判据是 EPP 收到。**

**3）ZMQ 是什么**

> 一个嵌入式异步消息库，不是 Kafka 那样的消息队列中间件。vLLM 在每个 KV block 分配/驱逐时，通过 **PUB 5556** 发事件；EPP 用 **SUB** 订阅，建“哪个副本有哪段前缀”的精确索引；**5559 是 replay**，EPP 重启后补历史。`PUB/SUB` 没有 ACK、没有持久化，所以必须监控 `active_subscribers`、`messages_received_total`，并保证 topic（`kv@podIP:port@model`）和 `block-size=64` 对齐。用 ZMQ 而不是 HTTP/gRPC，是因为事件频率高、需要一对多 fan-out、且不想引入 broker。

**本节验收**

- [ ] 两个 Pod IP 都返回 `http=200` + `token_ids`
- [ ] 两个 Pod 的 5556/5559 都 `open`（声明、监听、可达三层一致）
- [ ] `vllm serve --help` 里有 `--enable-scale-out`
- [ ] 进入 §5.5；EPP 起来后用 §5.6 的 `active_subscribers=2` 收口

### 5.5 安装 GAIE CRD + llm-d router

在 `llm-inference-platform-lab` 仓库根目录先确认 `LAB`，再 clone llm-d：

```bash
: "${LAB:?先在 §5.2 设置 LAB 为 llm-inference-platform-lab 根目录}"
[ -d llm-d ] || git clone https://github.com/llm-d/llm-d.git
cd "${LAB}/llm-d"
git checkout release-1.0

export GAIE_VERSION=v1.6.2
kubectl apply -f "https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/${GAIE_VERSION}/v1-manifests.yaml"

kubectl get crd inferencepools.inference.networking.k8s.io
```

> **要先装 Gateway API CRD 吗？** standalone 路径**不需要**。GAIE v1.6.2 的 `v1-manifests.yaml` 只含 `InferencePool` 一个 CRD（`InferenceObjective` 已迁到 `llm-d/llm-d-router`）；standalone router 用 Envoy sidecar，不创建 `Gateway`/`HTTPRoute`。
>
> Gateway API CRD 是 **Gateway Mode（§7.6）** 的前置，而且只装 CRD 还不够，还要一个 Gateway controller（Envoy Gateway / Istio / agentgateway）。D4 不装。
>
> 如果 `helm upgrade d4-router` 报 `no matches for kind "HTTPRoute"`，说明该 chart 版本引用了 Gateway API 资源，再补：
>
> ```bash
> kubectl apply -f "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/standard-install.yaml"
> ```

安装 standalone router（在 llm-d 仓库根目录）：

```bash
helm upgrade --install d4-router \
  oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d4 --version v1.0.0 \
  -f guides/recipes/router/base.values.yaml \
  -f "${LAB}/scripts/d4/values-precise.yaml"
```

**`values-precise.yaml` 关键字段**

先看外层（谁进 pool、proxy 怎么跑）：

| 字段 | 值 | 作用 / 为什么 |
|---|---|---|
| `router.inferencePool.failureMode` | `FailOpen` | EPP 不可用时 Envoy 继续按 headless Service 转发；`FailClose` 则返回 503。§7.3 会实测 |
| `router.modelServers.matchLabels` | `llm-d.ai/guide=d4-prefix-routing` | **决定哪些 Pod 进 pool**；必须等于 `modelserver.yaml` 里的 label |
| `router.modelServers.targetPorts` | `8000` | vLLM 的 HTTP 端口 |
| `router.proxy.proxyType` | `envoy` | standalone 自带的数据面 |
| `router.proxy.failOpen` | `true` | Envoy 自己的 ext_proc 失败策略；和 `failureMode` 是**两个开关**，别混 |
| `router.epp.replicas` | `1` | precise 的索引是进程本地状态；D4 不做 active-active |

再看 EPP 插件链（`pluginsCustomConfig.precise-plugins.yaml`）：

| 插件 | 关键参数 | 作用 |
|---|---|---|
| `token-producer` | `modelName: qwen3-4b`；`attemptTimeout: 2s` | 调 vLLM `/v1/*/render` 拿 token IDs。`modelName` 必须等于 `--served-model-name`，否则 render 被拒、路由**静默退化** |
| `endpoint-notification-source` | — | 监听 Ready endpoints，把 Pod 增删喂给 dataLayer |
| `precise-prefix-cache-producer` | `blockSizeTokens: 64`；`hashAlgorithm: xxh64`；`speculativeIndexing: true` | 订阅 KV events、建精确索引。block 必须等于 vLLM `--block-size`；hash 算法在整个索引生命周期内不能变 |
| ↳ `kvEventsConfig` | `engineType: vllm`；`topicFilter: kv@`；`socketPort: 5556`；`replaySocketPort: 5559` | 与 vLLM 的 `--kv-events-config` 逐项对齐 |
| ↳ `indexerConfig` | `enableMetrics: true` | 暴露 `llm_d_epp_kv_cache_index_*`，§5.6/§6 要用 |
| `inflight-load-producer` | 引用 `precise-prefix-cache-producer` | 统计每个 Pod 的 in-flight token，供 filter/scorer 使用 |
| `prefix-cache-affinity-filter` | `peakPrefillThroughput` | 用预测 TTFT 做饱和门控。guide 的 `15926` 是 H100/32B/TP=2，**必须按 §5.8 重测** |
| `token-load-scorer` | — | 按当前 token 负载打分，避免压到已经忙的副本 |

最后是装配关系：

| 字段 | 作用 |
|---|---|
| `dataLayer.sources[].pluginRef` | 把 `endpoint-notification-source` 的 Pod 事件交给 producer 索引 |
| `schedulingProfiles[].plugins` | 顺序：先 `prefix-cache-affinity-filter`（过滤/扩散），再 `token-load-scorer`（打分） |
| `extraServicePorts` | 对外 80 → Envoy sidecar 8081；EPP 的 9002 是 ext_proc，不对外 |

> 换 arm 只改插件：`optimized` 把 producer 换成 `approx-prefix-cache-producer`（`values-optimized.yaml`），`random` 换成 `random-picker`（`values-random.yaml`）；pool/proxy 部分不动。

> **为什么 block 是 64，不是 32/16？** block 越小，索引粒度越细、序列最后一个不完整 block 的浪费越少；但 KV events 和索引条目成倍增加，vLLM 的 paged attention 也多一层间接寻址。对 D4 的 ~1.5k token 前缀，64 和 32 的**可命中长度通常一样**（都向下取整到 1472），差异 <5%；16 则会让事件量再翻倍。所以跟 guide 默认 64，**不要在中途改**。真要测就单独做 A/B：同时改 vLLM `--block-size` 和 EPP `blockSizeTokens`，重启 vLLM + EPP（索引和 KV cache 都会清空），否则静默 miss。

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

> **Helm 不装 operator，也不「生成」pool。** chart 把 `InferencePool`、Deployment、Service、ConfigMap、RBAC 直接渲染成 YAML 交给 API server；集群里没有 llm-d operator。EPP 本身是 controller，但它只 **watch** `InferencePool` 和 Pod，不创建它们。
>
> 名字容易混：`d4-router` 既是 **Helm release 名**，也是 **`InferencePool` 对象名**；release 里还有 `d4-router-epp` Deployment（epp + envoy 两个容器）、两个 Service、两个 ConfigMap、SA/RBAC。`kubectl get deploy -n d4` 只有 `d4-router-epp` 和 `vllm-d4`，没有第三个「controller」。

### 5.6 验证 EPP 和索引

**先补 metrics 的 RBAC。** EPP v1.0.0 的 `/metrics` 默认 `--metrics-endpoint-auth=true`：无 token 返回 **401**；有 token 但 EPP 不能做 TokenReview/SubjectAccessReview 返回 **500**。chart 不创建这两项授权：

```bash
kubectl create clusterrole d4-metrics-reader \
  --verb=get --non-resource-url=/metrics \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl create clusterrolebinding d4-metrics-reader \
  --clusterrole=d4-metrics-reader --serviceaccount=d4:default \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl create clusterrolebinding d4-epp-auth-delegator \
  --clusterrole=system:auth-delegator --serviceaccount=d4:d4-router-epp \
  --dry-run=client -o yaml | kubectl apply -f -
```

> 第一条让抓取方（`d4:default`）能读 `/metrics`；第二条让 EPP 的 SA 能调 TokenReview/SAR。单机 lab 也可以给 EPP 加 `--metrics-endpoint-auth=false`，但 `helm upgrade` 会覆盖，不推荐。

**抓取：port-forward + SA token。**

```bash
EPP_POD=$(kubectl get pods -n d4 -o jsonpath='{.items[*].metadata.name}' \
  | tr ' ' '\n' | grep '^d4-router-epp' | head -1)
TOKEN=$(kubectl create token default -n d4 --duration=1h)

kubectl port-forward -n d4 "pod/$EPP_POD" 19090:9090 >/tmp/pf-epp.log 2>&1 &
PF=$!; sleep 3
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:19090/metrics \
  | grep -E 'active_subscribers|index_(admissions|lookup)|decisions_total'
kill $PF

kubectl logs -n d4 "$EPP_POD" -c epp --tail=80
```

> **不要用 `kubectl get --raw "...:9090/proxy/metrics"`**：API server 会剥掉 `Authorization` 头，EPP 仍返回 401，kubectl 显示为 “You must be logged in”。

**判据分两层，别混：**

| 指标 | 期望 | 说明 |
|---|---|---|
| `llm_d_epp_kv_cache_events_active_subscribers` | `2` | 只证明 ZMQ 连上了两个副本，**不证明有事件或命中** |
| `llm_d_epp_kv_cache_index_admissions_total` | 发请求后 > 0 | block 进了索引 |
| `llm_d_epp_kv_cache_index_lookup_hits_total` | 重复前缀后 > 0 | 查到了 |
| `llm_d_epp_prefix_cache_affinity_filter_decisions_total` | 出现 `outcome="sticky"` | 路由真的按命中粘住了 |

> **测试 prompt 必须 ≥ 1 个 block（64 token）且前缀重复**，否则 `outcome` 永远是 `no_match`，看起来像“路由没生效”。用 ~2k token 的同一段文本打两次：vLLM 侧 `vllm:prefix_cache_hits_total` 会涨，EPP 侧 `lookup_hits_total` / `admissions_total` 也会涨。

如果 subscribers 不是 2：检查 `podDiscoveryConfig.socketPort: 5556`、`topicFilter: kv@`、Pod 的 5556/5559 端口，以及 vLLM 启动日志里是否真的开了 KV events。

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

`prefix-cache-affinity-filter` 用 `peakPrefillThroughput` 把 in-flight token 负载换算成预测 TTFT。guide 的 15926 是 H100/Qwen3-32B/TP=2 的值，2×3060 + Qwen3-4B-AWQ 上不能用；**必须在本机重测，不要照抄，也不要编一个数**。

```bash
cd "${LAB}/llm-d"

GUIDE_NAME=d4-router \
NAMESPACE=d4 \
MODEL_NAME=qwen3-4b \
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

### 5.10 optimized baseline：T0 arm + fallback

`values-optimized.yaml` 有两个用途：

1. **T0 市场默认 arm**：在 §6 里作为第 4 个 arm 跑 1–3 轮，回答“大多数团队用的 optimized baseline，和 precise 差多少”；
2. **fallback**：precise 的 render/KV events 跑不通时，用它完成 round-robin vs EPP 的对比。

切换命令：

```bash
helm upgrade d4-router \
  oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d4 --version v1.0.0 \
  -f guides/recipes/router/base.values.yaml \
  -f "${LAB}/scripts/d4/values-optimized.yaml"
```

它用 `approx-prefix-cache-producer`，不需要 `--enable-scale-out` 和 KV events；仍然能对比 round-robin vs EPP 的 P99 和命中率，只是“前缀位置”是估计的。结果里必须写清楚是 **optimized baseline，不是 precise**。

**optimized 的最小依赖**

| 组件 | 需要？ | 说明 |
|---|---|---|
| EPP | 要 | 路由决策本体：approx prefix + token load + saturation gate |
| `InferencePool`（GAIE CRD） | 要 | EPP 找后端的契约 |
| Envoy（standalone sidecar） | 要 | ext_proc 调用方，没有它 EPP 收不到请求 |
| Gateway API / Gateway controller | 不要 | standalone 模式不用 |
| `--enable-scale-out` + ZMQ 5556/5559 | 不要 | 那是 precise 的 KV 事件通道 |
| vLLM `/v1/*/render` | 不要 | approx 用 EPP 自己的 tokenizer |
| `block-size=64` 对齐 | 不要 | 同上，precise 才需要 |

> optimized 少掉的正是 D4 最容易翻车的部分：KV events、render、block size 对齐。precise 跑不通时，它至少还能证明「EPP 比 round-robin 好」。

**不装 llm-d 自己实现？**

| 方案 | 覆盖 prefix | 覆盖 load | 缺什么 |
|---|---|---|---|
| Envoy/NGINX consistent hash（按前 N 个 token 哈希） | 部分 | 否 | cached_tokens 估计、saturation gate |
| 自己写 router | 看实现 | 看实现 | tokenize、索引、健康检查、ext_proc 都要自己做 |
| vLLM `--data-parallel-size` 内部 LB | **否** | 是（队列） | 前缀完全没覆盖，本质是 round-robin 变体 |
| llm-d optimized | 是（近似） | 是（token 级） | — |

> 自己写出来的是「另一个 router」，不是 optimized baseline：EPP 的固定开销、tokenize 路径、saturation 逻辑都不同，数字不能和 precise 直接比，§6.7 的归因会失效。而 optimized 只是换一个 `values-optimized.yaml`（一次 `helm upgrade`），DIY 的成本远高于此。

> **公平性：** `optimized` 和 `precise` 要用同一个 `peakPrefillThroughput`。如果你在 §5.8 校准了 precise，把 `${LAB}/scripts/d4/values-optimized.yaml` 也改成同一个值；否则 T0 vs T1 的差异会混入 saturation gate 的差异。

如果模型服务器本身就是因为 `--enable-scale-out` / `--kv-events-config` 起不来，先把 `scripts/d4/modelserver.yaml` 里的这两段删掉，再 `kubectl apply`；optimized baseline 不需要它们。

---

## 6. 压测设计

### 6.1 四个 arm

| arm | URL | 说明 | 优先级 |
|---|---|---|---|
| `direct` | `http://vllm-direct:8000/v1/completions` | 普通 Service；K8s per-connection 选择，不是严格轮询；用 `FORCE_CLOSE=1` 让每个请求新建连接 | **P0** |
| `precise` | `http://d4-router-epp/v1/completions` | llm-d precise prefix routing（T1-A） | **P0** |
| `optimized` | `http://d4-router-epp/v1/completions` | llm-d optimized baseline（approx prefix + token load，T0）；市场默认入口 | P1 |
| `random` | `http://d4-router-epp/v1/completions` | 同一 EPP/Envoy 路径，`random-picker`；隔离固定开销 | P2 |

- **主对比**：`direct` vs `precise`（计划要求，各 3 轮）。
- **T0 参考**：`optimized` 至少 1 轮，时间够 3 轮；回答“市场默认的 approx baseline 和 precise 差多少”。
- **控制组**：`random` 至少 1 轮，时间不够可砍；它只用来判断“P99 改善是不是 EPP/Envoy 的固定开销”。

### 6.2 Workload

固定一批“共享长前缀”的请求：

| 参数 | 值 | 理由 |
|---|---|---|
| sessions | 32 | 32 个不同长前缀，制造 cache 竞争 |
| turns | 4 | 每个 session 4 轮，共 128 请求 |
| prefix words | 1100 | 约 1.5k tokens；32 个前缀合计约 6.8GB KV，接近单张 3060 在 0.90 下的 KV 预算 |
| suffix words | 80 | 每轮新增约 100 tokens，模拟多轮对话 |
| max tokens | 128 | 固定输出长度；`ignore_eos=true` |
| concurrency | 16 | 闭环；足以制造排队，又不会把 3060 打到完全过载 |
| seed | 42 | 请求顺序固定，四个 arm 相同 |

请求顺序：每个 turn 内把 32 个 session 打乱；同一 session 的连续 turn 被其他 session 隔开。这样 random 路由会在 turn 之间丢失 session 的 prefix，而 precise 可以保持。

> **3060 的 cache 竞争是设计出来的：** 32 个 session 的 KV 合计约 6.8GB。若 precise 把 32 个 session 全压到同一个副本，会逼近该卡在 `gpu-memory-utilization=0.90` 下的 KV 预算（4B 权重约 2.7GB，剩下约 7GB 给 KV/activation）；`prefix-cache-affinity-filter` 的 saturation gate 应该把一部分 session 扩散到第二个副本。这正是 §5.8 要校准 `peakPrefillThroughput` 的原因。如果两个副本预热后都能全命中，说明 cache 压力不够，可把 `max-model-len` 或 `gpu-memory-utilization` 调小（并在结果里注明）。

> 对话历史里的 assistant 回复是**固定文本**，不是模型真实输出。这样四个 arm 的 prompt 完全一致，避免自回归内容把变量引进来；代价是它不完全等同真实多轮 chat，但足以测路由对 prefix cache 的影响。

**为什么不用 `vllm bench serve --dataset-name prefix_repetition`？** 它也能测 prefix caching，但请求顺序是“一个前缀的请求连在一起”，random 路由只要前两条把两个 Pod 都预热，后面就都命中；对“多轮 session 被交错”的场景不够敏感。本 lab 用 `scripts/d4/bench_prefix.py` 控制交错顺序。

### 6.3 指标与 SLO

| 指标 | 定义 | 采集 |
|---|---|---|
| TTFT P50（第 50 百分位）/P95/P99 | 请求发出→第一个内容 chunk | 客户端 `bench_prefix.py` |
| TPOT（Time Per Output Token，每输出 token 耗时） P95（第 95 百分位） | `(end - first_token) / (completion_tokens - 1)` | 客户端 |
| E2E（End-to-End，端到端） P99 | 请求发出→最后一个 chunk | 客户端 |
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

- **闭环**：16 并发，固定 128 条请求；不是开环固定 QPS（Queries Per Second，每秒查询数）。
- **样本数**：128 请求/轮；`direct` / `precise` 各 3 轮；`optimized` 至少 1 轮（时间够 3 轮）；`random` 至少 1 轮（可砍）。
- **warmup**：每轮前 4 条 `max_tokens=1` 的 warmup；脚本 warmup 后 reset prefix cache；precise arm 在启动脚本前重启 EPP，让索引从空开始。
- **重复**：主对比 3 轮，顺序 `direct → optimized → precise`（或反过来）；如果 GPU 热节流明显，记录 `nvidia-smi` 的 clock/power。
- **同机同模型**：四个 arm 用同一对 vLLM Pod、同一 `max-model-len`、同一 `max-num-seqs`、同一输出长度。
- **cache 状态**：每轮开始前 `POST /reset_prefix_cache` 到两个 Pod；precise arm 重启 EPP。否则上一轮的热缓存会让结果不可比。
- **货币/单价**：USD；Vast 实时 `$/h`；记录 GPU 型号、power limit、driver。
- **GPU 采样**：`nvidia-smi --query-gpu=utilization.gpu,power.draw,clocks.sm --format=csv -l 5` 另开一个终端记录；util 只作解释，不作 SLO。
- **不要**：把 direct 的 per-connection 随机说成“严格 round-robin”；把 EPP 的固定开销算成 prefix routing 的收益；把不同模型/不同卡的数字混在一起。

### 6.5 跑四组

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

`direct` arm 把 `URL` 换成 `http://vllm-direct:8000/v1/completions`，`FORCE_CLOSE=1`。

`optimized` arm 先把 router 切到 `values-optimized.yaml`，再按上面的命令跑，`ARM="optimized"`：

```bash
cd "${LAB}/llm-d"
helm upgrade d4-router \
  oci://ghcr.io/llm-d/charts/llm-d-router-standalone \
  -n d4 --version v1.0.0 \
  -f guides/recipes/router/base.values.yaml \
  -f "${LAB}/scripts/d4/values-optimized.yaml"
kubectl rollout restart deploy/d4-router-epp -n d4
kubectl rollout status deploy/d4-router-epp -n d4 --timeout=120s
```

`random` arm 先把 router 切到 `values-random.yaml`，`URL` 保持 `http://d4-router-epp/v1/completions`，`ARM="random"`。

每轮开始前，脚本会自动对 `POD_URLS` 发 `POST /reset_prefix_cache`；如果返回 404/405，手动重启两个 Pod，或在结果里注明“cache reset 不可用，轮次之间可能有残留”。

### 6.6 结果模板

**客户端汇总**（`direct` / `precise` 3 轮；`optimized` 1–3 轮；`random` 1–3 轮，填中位数/范围）：

| arm | 轮次 | ok | TTFT P50 (ms) | TTFT P95 | TTFT P99 | TPOT P95 | E2E P99 | output tok/s | goodput (req/s) |
|---|---|---|---|---|---|---|---|---|---|
| direct | 3 | | | | | | | | |
| optimized | 1–3 | | | | | | | | |
| random | 1–3 | | | | | | | | |
| precise | 3 | | | | | | | | |

**命中率与分布**（每轮前后各取一次 metrics，算 delta）：

| arm | Pod A requests | Pod B requests | Pod A hit rate | Pod B hit rate | 加权 hit rate | EPP predicted cached share |
|---|---|---|---|---|---|---|
| direct | | | | | | n/a |
| optimized | | | | | | n/a（approx） |
| random | | | | | | n/a |
| precise | | | | | | |

**P99 对比图**：把四份 JSON 交给 `plot_d4.py`（没跑 random 就删掉那一个文件）：

```bash
cd "${LAB}"
python3 scripts/d4/plot_d4.py \
  /results/direct-run1.json /results/optimized-run1.json \
  /results/random-run1.json /results/precise-run1.json \
  --out /results/d4-ttft.png
```

**一句话归因模板**：

> 在同一对 RTX 3060 12GB、同一 Qwen3-4B-AWQ、同一 128 条共享前缀请求下，市场默认的 optimized baseline（approx prefix + token load）TTFT P99 是 `____ ms`，precise 是 `____ ms`（`__%`），direct 是 `____ ms`；precise 的加权 prefix hit rate 从 optimized 的 `__%` 升到 `__%`。代价是 EPP `____ ms` 的固定开销（用 random arm 对比），以及 single-EPP 的可用性风险。

### 6.7 怎么判读

**precise 应该出现**：

- 同一 session 的 4 轮请求集中到一个 Pod；另一个 Pod 只分到少量 session；
- 该 Pod 的 prefix hit rate 高（每轮第 2–4 条请求复用第 1 条的前缀）；
- TTFT P99 比 direct 低；**也应该比 optimized 低或至少不差**——optimized 是市场默认，如果 precise 连 optimized 都赢不了，说明 KV events/render 的额外成本没有换来命中率；
- output tok/s 可能略高（少做重复 prefill），也可能持平；
- EPP 的 predicted cached share 与 vLLM 的实际 hit rate 趋势一致。

**如果没有差异**：

1. 先看 `active_subscribers` 是否 = 2、`messages_received_total` 是否增长；没有就是 KV events 没进来。
2. 看 `/v1/completions/render` 是否 200 且有 `token_ids`；没有就是 precise 没生效。
3. 看 `blockSizeTokens` 是否等于 `--block-size`；不等就全 miss。
4. 看 workload 是否真的共享前缀：32 个 session 的前缀必须不同、同一 session 的 turn 必须复用；如果每条 prompt 都不同，路由没有可用的前缀。
5. 看 KV cache 是否大到“两个 Pod 都能缓存所有 32 个前缀”：如果两张 3060 的 KV 足够大，random 也会在预热后全命中，差异会被稀释。可以增加到 64 个 session，或缩短 `max-model-len`/`gpu-memory-utilization` 让 cache 更紧张。

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
- **多租户**：namespace + RBAC（Role-Based Access Control，基于角色的访问控制）做逻辑隔离；ResourceQuota 限 CPU/内存；NetworkPolicy 限制跨 namespace；每个租户自己的 pool/route；`InferenceObjective` 做优先级（如果启用 flow control）。
- **不要**用“同一个 pool + 请求头里的 tenant”做硬隔离；请求头可以伪造，真正的隔离在 namespace/配额/网络策略。

### 7.3 路由故障表（至少跑前两项）

> **FailOpen / FailClose 是什么：** 它们是“依赖组件（EPP）不可用时，数据面（Envoy）怎么办”的两种策略。
>
> - **FailOpen（失败时放行）**：ext_proc 调不通 EPP 时，Envoy 不阻断请求，按自己的负载均衡把请求发给后端（通常是 headless Service 里的某个 vLLM）。**可用性优先**，但丢掉 prefix/load 感知，可能打到冷副本或热点副本。
> - **FailClose（失败时阻断）**：ext_proc 调不通 EPP 时，Envoy 直接返回 503/关闭请求。**路由正确性/控制优先**，但 EPP 成了硬依赖，可用性下降。
>
> 记法：**FailOpen = 失败时把路打开（继续放行）；FailClose = 失败时把路关掉（拒绝请求）**。类比门禁断电：FailOpen 是门自动打开，FailClose 是门自动锁死。

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

- **每副本成本**：2×3060 VM `$0.26148/h` ÷ 2 个副本 ≈ `$0.13/h/副本`；再加 EPP/Envoy 的 CPU 成本（可忽略，但不能说 0）。
- **容量**：满足 SLO 的并发，不是 GPU util 100%。用 D1/D2 的方法：c=16 找拐点，c=32/64 看吞吐上限；D4 只跑 c=16。
- **EPP 容量**：单副本 EPP 的 CPU 是路由 QPS 的上限；看 `llm_d_epp_plugin_duration_seconds` 和 Pod CPU。请求率上去后，EPP 可能先于 vLLM 成为瓶颈。
- **prefix cache 容量**：32 个 1.5k-token 前缀约 6.8GB KV；单张 3060 的 KV 预算约 7GB，session 数增加会触发驱逐，命中率下降。

### 7.5 升级与回滚

- **模型版本**：权重按版本目录存放（`/models/Qwen3-4B-AWQ-v1`、`-v2`），Deployment 用 `MODEL_PATH` 指向版本；回滚 = 改路径 + `kubectl rollout undo`。不要在运行中的目录上覆盖权重。
- **路由配置**：EPP 的 `EndpointPickerConfig` 不是 CRD，改 ConfigMap 后必须重启 EPP；`helm upgrade` 后补 `kubectl rollout restart`。
- **滚动更新**：`maxSurge: 0`、`maxUnavailable: 1`（2 副本时一次只动一个）；`preStop 15s` + `--shutdown-timeout=45` + grace 120s，沿用 D3 Lab 4 的结论。
- **回滚验证**：`kubectl rollout undo deploy/vllm-d4`；确认两个 Pod 都 Ready、`/v1/models` 正常、EPP subscribers 回到 2。

### 7.6 Gateway Mode（概念，不跑）

D4 用 **standalone**：Envoy sidecar 和 EPP 在同一个 Pod，客户端直接访问 `d4-router-epp:80`。生产多模型/多租户通常用 **Gateway Mode**：一个共享 Gateway（Istio / Envoy Gateway / agentgateway）承载多条 HTTPRoute，每条 route 的 backendRef 指向一个 `InferencePool`。

**先厘清「router」指什么**：llm-d 的 router 不是一个二进制，而是 **数据面（proxy，默认 Envoy）+ 控制面（EPP）** 的打包。standalone 和 Gateway Mode 的区别**不是路由算法**——两边是同一个 EPP、同一套 precise/optimized 插件——而是**数据面由谁提供**：

```text
standalone:   client → Service d4-router-epp:80
                       → [Pod: Envoy :80 ──ext_proc──> EPP :9002]
                       → Envoy 直接转发到选中的 vLLM Pod:8000

Gateway Mode: client → Gateway（Istio / Envoy Gateway / agentgateway）
                       → ext_proc → EPP Service（独立 Deployment）
                       → Gateway 转发到选中的 vLLM Pod:8000
```

所以：**standalone = llm-d 自带 proxy**；**Gateway Mode = 复用你已有的 Gateway，llm-d 只提供 EPP**。D4 选 standalone 是为了少装一个 Gateway controller，不是因为路由能力弱。

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
>
> **standalone 自己也有两种形态**：`router.proxy.mode: sidecar`（默认，Envoy 与 EPP 同 Pod，删 EPP 会连数据面一起删）和 `service`（proxy 独立 Deployment，EPP 挂掉时 Envoy 还在，更接近生产）。§7.3 测 FailOpen/FailClose 时会用到这个区别。

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
| EPP 日志 `token-producer` 失败 | `modelName` 与 `--served-model-name` 不一致 | 改成 `qwen3-4b`；重启 EPP |
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

| 项 | 单价 | 5h 成本 |
|---|---|---|
| 2×3060 12GB VM + 130GB 存储 | `$0.26148/h` | 约 `$1.31` |
| 安装/排障 +1h | 同上 | 已含在 5h 内 |
| 合计 | — | **约 `$1.31`** |

D3 后 credit 约 `$14.93`；D4 后约 `$13.6`。实付以 Vast 账单为准。

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

- [ ] 2×3060 12GB VM（instance 62540497），`nvidia.com/gpu` allocatable = 2；记录 driver / power limit；
- [ ] 两个 vLLM Pod 各 1 GPU，`/v1/models` 返回 `qwen3-4b`；
- [ ] `/v1/completions/render` 返回 `token_ids`（precise 路径）；
- [ ] EPP `active_subscribers=2`，`messages_received_total` 增长；
- [ ] `InferencePool` + EPP + Envoy Ready；`d4-router-epp:80` 可访问；
- [ ] smoke test：同一前缀集中到一个 Pod，hit rate 明显高于另一个；
- [ ] `peakPrefillThroughput` 已校准（或明确写“gate 关闭”）；
- [ ] `direct` / `precise` 各 3 轮；`optimized` 至少 1 轮（时间够 3 轮）；`random` 至少 1 轮（可砍）；
- [ ] 每轮前 reset cache；precise 每轮前重启 EPP；
- [ ] P99 表 + 命中率表 + 每 Pod 分布 + `d4-ttft.png`；
- [ ] 故障表至少跑 EPP FailOpen；时间够再跑 FailClose / render 404；
- [ ] B 线运维图 + 10 分钟讲法；
- [ ] §1.4 的 19 项核心 feature 至少到 D 档：每项能说清“是什么/何时不用/关键指标”；
- [ ] 附录 A 的 PD/wide EP/flow control/tiered/P2P/autoscaling/batch/rollout/API 每项能讲 1 分钟；
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
| 2:15–3:10 | 跑 direct/precise 各 3 轮，每轮 reset | 6 份 JSON |
| 3:10–3:30 | 切 optimized，跑 1–2 轮 | 1–2 份 JSON（T0 参考） |
| 3:30–3:50 | 采样 metrics、画图、写表 | P99 图 + 命中率 |
| 3:50–4:05 | 故障测试（至少 FailOpen）、清理、scp | 故障表 + 成本 |

**砍单顺序**：Lab 0 → random arm（整组）→ optimized 的第 2/3 轮 → FailClose/render 404 故障 → 校准（改 gate=100000 并注明）。**不要砍**：direct vs precise、optimized 至少 1 轮、cache reset、EPP subscribers、P99 表。

> **核心 feature 阅读**：§1.4 + 附录 A 约 45–60 min，建议在租 VM 前读完，不占 4h 主实验。时间不够时优先 A.2（PD）、A.4（flow control）、A.5（tiered/P2P），其余实验后补。

### 10.6 B 线简历 bullet（执行后填，选 1–2 条）

- 在 2×RTX 3060 12GB 上用 llm-d 1.0 / Gateway API Inference Extension 部署 precise prefix-cache routing：对比 Service round-robin，TTFT P99 从 `____ ms` 降到 `____ ms`（`__%`），加权 prefix hit rate 从 `__%` 升到 `__%`；用 EPP random 控制组分离路由算法与代理固定开销。
- 为 EPP / `InferencePool` 设计故障演练：EPP FailOpen/FailClose、render 404、KV events 丢失、后端不健康；记录检测指标（`active_subscribers`、`index_lookup_*`、`prefix_cache_hits/queries`）和处置顺序，明确单副本 EPP 的可用性边界。

---

## 11. 附录：llm-d 核心 feature 全景

> 这一节把 §1.4 的 **D 档**展开：每个 feature 给“是什么、何时用/不用、D4 怎么覆盖、面试一句话”。它不是 4h 主实验，不额外租卡，也不写假数字。

### 11.1 Routing + KV：D4 已经动手的部分

- **`InferencePool`**：声明“哪些 Pod 是同一个模型的副本、目标端口、EPP 是谁、failureMode”。它替代不了 Service，而是给 Gateway/Envoy 一个推理专用的 backend 契约。
- **EPP**：解析请求、tokenize/render、查 KV 索引、过滤/打分、选 Pod；通过 ext_proc 告诉 Envoy 把请求发到哪。
- **precise prefix routing**：vLLM 用 ZMQ 上报 KV block 事件，EPP 建精确索引；请求先 `POST /v1/*/render` 拿 token IDs，再查索引。
- **optimized baseline**：不依赖 KV events，用请求流量/前缀 hash 近似估计；部署简单，但命中率不如 precise。D4 把它作为 fallback。
- **关键指标**：`vllm:prefix_cache_hits_total/queries_total`、`llm_d_epp_kv_cache_events_active_subscribers`、`llm_d_epp_kv_cache_index_lookup_*`、`llm_d_epp_prefix_predicted_cached_tokens_sum/prefix_prompt_tokens_sum`、`llm_d_epp_plugin_duration_seconds`。
- **predicted-latency routing（D 档）**：EPP 也可以用 latency predictor 预测 TTFT/TPOT，按 SLO 选副本；它需要训练/预测 server 和历史样本，D4 不跑。2 副本 + 固定 workload 用不上；面试能说清“它和 prefix routing 是两个信号，可以叠加”即可。
- **面试一句话**：“EPP 不是更快的 round-robin，它把请求送到已经持有这段前缀 KV 的副本；代价是每请求一次 tokenize/render 和索引查询。”

### 11.2 PD 分离（Prefill/Decode Disaggregation）

**是什么：** 把推理拆成两个池：prefill 池只算 prompt 的 KV，decode 池通过 NIXL 把 KV 拉过去、只做自回归生成。两个池属于同一个 `InferencePool`，router 每个请求调度两次（一次 prefill、一次 decode）。它和 prefix routing 不是二选一：prefill 池仍然可以做 prefix-affinity。

**llm-d 1.0 的实际要求：**

| 项 | 官方默认 |
|---|---|
| 模型 | `openai/gpt-oss-120b` |
| 拓扑 | 1 个 prefill pod（TP=1）+ 1 个 decode pod（TP=4） |
| GPU | **5 张**（最小完整 P/D（Prefill/Decode，预填充/解码）路径） |
| 编排 | LeaderWorkerSet 的 `DisaggregatedSet`（`enableDisaggregatedSet=true`） |
| KV 传输 | NIXL；TCP 能跑，生产推荐 RDMA/InfiniBand/RoCE |
| 关键指标 | prefill `request_success_total`（以 `max_tokens=1` 跑）、decode `external_prefix_cache_hits_total`、EPP `llm_d_epp_disagg_decision_total` |

**什么时候值得：**

| 条件 | 说明 |
|---|---|
| prompt 很长（通常 4k–8k+） | prefill 占比高，拆池的收益才明显 |
| 高并发、P:D 比例可独立扩缩 | prefill 和 decode 的最优配比不同，能分别加副本 |
| KV 传输够快 | NVLink / RDMA（Remote Direct Memory Access，远程直接内存访问）/ 同机高带宽；TCP 跨节点会吃掉收益 |
| 有第二个 GPU 池 | 至少能让 prefill/decode 各自有副本 |

**什么时候不划算：**

- 低并发、短 prompt、小模型：decode 占大头，拆池只是多一跳；
- 只有 2 张卡：1P1D 没有复制、没有池内路由、没有 HA，测出来的是玩具；
- KV 传输慢：搬 KV 的时间 > 重算 prefill；
- 没有第二个池：PD 的“独立扩缩”根本用不上。

**D4 怎么覆盖：**

- §8 Q3 给“什么时候不划算”的面试口径；
- 本节给完整拓扑、指标和决策表；
- **不跑**：guide 默认 5 GPU；本次 62540497 只有 **2 张 RTX 3060 12GB**，连 2P+2D 的 4 张卡都不够，只能 1P1D；1P1D 没有池内路由/HA，会破坏 D4 的“多副本 prefix routing”对照，且 gpt-oss-120b 放不下。

**如果要真跑，单独排一个 lab（不是 D4 的 4h）：**

```text
4×24GB VM（4×4090，2P + 2D，每池 2 副本、TP=1）
  + LWS DisaggregatedSet
  + NIXL over TCP（4090 无 NVLink；这就是要量的问题）
  + Qwen3-8B-AWQ
对比：
  colocated 4 副本 vs PD 2P+2D
  c=8/16/32，同 SLO
记录：
  TTFT、TPOT、goodput、KV transfer bytes/s、每 1M token 成本
预算：
  5h，约 $9.3（6h 起 $11.2，超 $10 上限）
```

> 4090/TCP 上 PD 很可能不划算；把这个“不划算”量出来，比在 2×3060 上硬跑 1P1D 更有价值。**本次 62540497 是 2×3060，不能跑 2P+2D；4×3060 VM 在 Vast 不存在**，所以 D4.5 当前 marked **skipped/blocked**，只保留 4×4090 5h 作为可选方案。完整 runbook 见 [`d4.5-pd-lab.md`](./d4.5-pd-lab.md)。

**面试一句话：** “PD 的收益来自 prefill 和 decode 的 resource profile 不同；没有长 prompt、高并发、快 KV 传输和第二个池，拆池只会增加复杂度和空闲。”

### 11.3 Wide EP / MoE

**是什么：** 面向 MoE 的专家并行：单机放不下全部专家时，把专家切到多机/多卡，用 DP/EP + DeepEP 做 all-to-all，用 NIXL 搬 KV。llm-d 的默认 wide-EP guide 是 `DeepSeek-R1-0528`、32×H200、prefill DP16 + decode DP16、每角色 2 节点，要求 full-mesh RDMA。

**何时用：** MoE 模型单机放不下、需要跨节点 EP、吞吐优先；**何时不用：** dense 4B、2×3060 12GB、没有 RDMA、低并发。

**D4 怎么覆盖：** §8 Q4 + 本节；不跑。2×3060 连 dense 4B 的 EP 都不需要，更不用说 32×H200 的 DeepEP。

**面试一句话：** “TP 切层、PP（Pipeline Parallelism，流水线并行）切阶段、EP 切专家；wide EP 解决 MoE 单机放不下，不是解决路由。”

### 11.4 Flow control / fairness / 多租户

**是什么：** EPP 在把请求放到后端之前，先在网关层排队/准入：`featureGates: [flowControl]`、priority bands、fairness policy、FCFS ordering、saturation detector。`InferenceObjective`（`llm-d.ai/v1`）给一个模型 workload 定义 priority 和 pool 目标；负 priority 表示可丢弃。

```yaml
apiVersion: llm-d.ai/v1
kind: InferenceObjective
metadata:
  name: premium-traffic
spec:
  priority: 100
  poolRefs:
    - name: d4-router
```

> `InferenceObjective` 只是“声明优先级”；要真正排队，还要在 EPP 配置里开 `featureGates: [flowControl]`，并实例化 `fcfs-ordering-policy`、`global-strict-fairness-policy` 等插件。不要只抄这一张 YAML 就以为 flow control 生效。

**何时用：** 多租户、premium vs batch、noisy neighbor、SLO 保护；**何时不用：** 单租户、低负载、请求都能立刻被接住——排队只会增加延迟。

**D4 怎么覆盖：** D 档 + 上面的 YAML；§7.2 讲多租户隔离；D5 用 Kueue 做 GPU 配额。**不跑**：flow control 需要多个优先级客户端和持续过载，和 D4 的“同 workload 只改路由”冲突；EPP 单副本的 queue 状态也不适合做 HA 结论。

**面试一句话：** “flow control 解决的是‘谁先被服务、谁可以被丢’，不是‘副本够不够’；配额在 Kueue，准入在 Kyverno，排队/公平在 EPP。”

### 11.5 Tiered prefix cache / P2P KV sharing

**Tiered prefix cache：** HBM 里的 KV 被驱逐后不丢，落到 CPU RAM，必要时再落到共享文件系统；请求复用时从 CPU/FS 拉回，而不是重算。vLLM 用 `OffloadingConnector`（`--kv-transfer-config`），router 增加 CPU tier 的 prefix index（`cpu-prefix-cache-producer`、`lruCapacityPerServer`）。默认参考是 Qwen3-32B、2 副本 × TP=2（4 GPU）、每副本 300GiB CPU tier。

关键指标：

```text
vllm:kv_offload_store_bytes_total
vllm:kv_offload_load_bytes_total
vllm:external_prefix_cache_hits_total / queries_total
llm_d_epp_prefix_indexer_size / hit_ratio（按 plugin_name 分 tier）
```

**P2P KV sharing：** 一个 Pod 直接从另一个 Pod 的 CPU tier 拉前缀 KV（NIXL，端口 7777），不经过共享文件系统。要求所有 peer 的 `--block-size`、`PYTHONHASHSEED`、TP layout 一致；`minCachedTokenDelta` 要校准。默认参考是 2×gpt-oss-120b、TP=1、每 Pod 88GiB CPU tier；guide 标记为 experimental/community。

**何时用：** 长共享前缀、多轮/agentic、HBM 压力大、CPU RAM 富余；**何时不用：** 短 prompt、缓存本来就能全放 HBM、CPU RAM 不够、没有快传输。

**D4 怎么覆盖：** precise HBM 索引是 H 档；tiered 另排 [`d4.6-tiered-cache-lab.md`](./d4.6-tiered-cache-lab.md)（2×3060 12GB，98GB RAM，CPU tier 16GiB），跑 tiered vs HBM-only；P2P 是 D 档，不在 D4.6 范围。2×3060 的 HBM 只有 12GB/卡，P2P 的默认 gpt-oss-120b 放不下，且没有 NVLink。

**面试一句话：** “tiered 是单 Pod 的 HBM→CPU/FS 扩展，P2P 是跨 Pod 从 peer 的 CPU tier 拉；两者都只在‘前缀复用 + HBM 不够’时才划算。”

### 11.6 Autoscaling / batch / async

**Autoscaling：** llm-d 1.0 推荐 **KEDA + EPP metrics**：按 queue depth、pool saturation、token backlog、estimated latency vs SLO 扩模型服务器；KEDA 直接创建/拥有 HPA，不需要 Prometheus Adapter。scale-to-zero 支持，但 LLM（Large Language Model，大语言模型）冷启动让同步 chat 基本不可用。WVA（Workload Variant Autoscaler）已 deprecated。

**D4 怎么覆盖：** D3 + Lab 0 已经动手验证 KEDA 0→1 和队列信号；D4 主实验固定 c=16、最多 2 张卡，没有 scale-out 空间，所以不跑 llm-d autoscaling。

**Batch/async：** llm-d 的 async processor 面向离线/批处理，用队列 + priority，不保 TTFT SLO；D4 不跑。

**面试一句话：** “GPU 推理的扩缩信号不是 CPU，是队列/饱和/token backlog/SLO；冷启动让 scale-to-zero 只适合异步或可接受等待的场景。”

### 11.7 Rollouts / zero-downtime / 模型生命周期

**是什么：** `DisaggregatedSet` 把 prefill/decode 两个角色作为一个版本滚动；LWS（LeaderWorkerSet）管多 Pod 组；配合 `preStop`、drain、`maxUnavailable/maxSurge`、PDB（Pod Disruption Budget，Pod 中断预算）做零停机。模型版本用独立权重目录 + Deployment revision 回滚。

**D4 怎么覆盖：** D3 Lab 4 已经动手量了 `preStop`/`--shutdown-timeout`/grace 的驱逐行为（H 档）；D4 只讲 llm-d 的 `DisaggregatedSet` 和 rollout 语义（D 档）。2×3060 没有空闲 GPU 做 surge，所以不跑 llm-d 零停机。

**面试一句话：** “零停机的必要条件是‘有地方起新副本’；2 张卡跑 2 副本时，滚动更新只能接受一个副本短暂不可用，或者加第 3 张卡。”

### 11.8 Observability / tracing

- **EPP `/metrics`（9090）**：`llm_d_epp_request_total`、`llm_d_epp_plugin_duration_seconds`、`llm_d_epp_kv_cache_events_*`、`llm_d_epp_kv_cache_index_lookup_*`、`llm_d_epp_disagg_decision_total`、`llm_d_epp_prefix_indexer_*`；flow control 的 queue/fairness 指标以实际 `/metrics` 为准。
- **vLLM `/metrics`**：`prefix_cache_hits/queries`、`num_requests_waiting`、`kv_cache_usage_perc`、TTFT/ITL、`external_prefix_cache_hits`（tiered/P2P/PD）。
- **Tracing**：OTel（OpenTelemetry） collector + router `tracing.values.yaml`；span 覆盖 tokenize、index lookup；KV event tracing 默认关，避免事件量淹没请求 trace。
- **D4**：metrics 是 H 档；tracing 是 D 档（不装 collector）。

**面试一句话：** “先看 EPP 的 routing 指标，再看 vLLM 的 queue/cache 指标；两边趋势不一致，通常是索引不完整或 render 失败。”

### 11.9 API surface / multimodal

- llm-d router 支持 OpenAI 兼容的 `/v1/completions`、`/v1/chat/completions`、Anthropic `/v1/messages`、`/v1/responses`；precise routing 的 `token-producer` 会按 API 调对应的 `/v1/*/render`。
- `InferenceModelRewrite`（`llm-d.ai/v1alpha2`）：按请求里的 `model` 做加权 rewrite，用于 A/B、canary、流量切分；`poolRef` + `rules[].matches.model` + `targets[].modelRewrite/weight`。D4 不跑，但面试要能说清“它是改请求里的 model 名，不是改路由算法”。
- 多模态/Omni 有独立 Well-Lit Path；D4 只用 `/v1/completions`，不测 chat/messages/responses/multimodal。
- **面试一句话：** “API 兼容不是路由的全部；不同 API 的 render/tokenizer 路径不同，precise routing 要保证 token IDs 和 engine 一致。”

### 11.10 核心 feature 验收清单

- [ ] 能画出 `client → Envoy → EPP → InferencePool → vLLM` 的请求路径；
- [ ] 能解释 precise vs optimized，以及 KV events/render/block size 的对齐；
- [ ] 能解释 PD 的 5-GPU 默认拓扑、NIXL、何时不划算；
- [ ] 能解释 wide EP 的 DP/EP/DeepEP，以及为什么 2×3060 12GB 不跑；
- [ ] 能解释 flow control 的 priority band/fairness/saturation，以及 `InferenceObjective`；
- [ ] 能解释 tiered vs P2P，以及各自的关键指标；
- [ ] 能解释 KEDA + EPP 的四种扩缩信号，以及为什么 CPU HPA 是错的；
- [ ] 能解释 `DisaggregatedSet`/rollout/零停机的容量前提；
- [ ] 每个 feature 能接住“什么时候不划算”的追问。

### 11.11 如果要把 D 档变成 hands-on：最小机器与预算

| feature | 最小可行拓扑 | 时间 | 预算 | 建议 |
|---|---|---|---|---|
| PD | 4×24GB VM（4×4090），2P + 2D，TP=1 | 5h（6h 起超 $10） | ~$9.3 | **本次 skipped/blocked**：[`d4.5-pd-lab.md`](./d4.5-pd-lab.md)；62540497 是 2×3060，不能 2P+2D；4×3060 VM 不存在；4×4090 5h 保留为可选 |
| wide EP | 32×H200 + RDMA | — | — | 只读；个人预算不现实 |
| flow control | 2×3060 12GB（现成实例）+ 两类客户端（premium/batch） | 3–4h | ~$1.0 | D5/Q2 扩展；不用另租卡 |
| tiered prefix cache | 2×3060 12GB，98GB RAM，CPU tier 16GiB | 4–5h | ~$1.0–1.3 | 已排：[`d4.6-tiered-cache-lab.md`](./d4.6-tiered-cache-lab.md)；先量 HBM 命中率 |
| P2P KV sharing | 2×H100/H200，NIXL | — | — | 只读；24GB 卡上默认模型放不下 |
| autoscaling | 4×24GB VM（2→4 副本） | 3h | ~$8 | Q2；D3 已有 0→1/1→2 基础 |
| rollout / 零停机 | 3–4×24GB VM（留 surge） | 2h | ~$4 | D3 §9 的扩展 |
| multi-model Gateway | 4×24GB VM（2 模型 × 2 副本） | 3–4h | ~$8 | Q2；需要 Gateway controller |

> 这张表是“如果要动手”的成本，不是 D4 的 4h 计划。D4 的 4h 只做 routing/KV 主实验；其余先做到 D 档，面试够用，预算留给 Q2 的 PD/chargeback。**本次已租 2×3060 12GB（instance 62540497，`$0.26148/h`）；D4 和 D4.6 都在这台机器上做，2×3090 只是备选。**

### 11.12 本轮问答补充（2026-11-25）

**Q1：llm-d 的 Well-Lit Path 到底是什么？**
A：官方验证过的 end-to-end 部署配方，分 Foundations / Models / Operations 三条 pillar，成熟度 Tier 0–5；Tier 绑定 reference environment。D4 只跑 `precise-prefix-cache-routing`，`optimized-baseline` 作 fallback。详见 §1.0。

**Q2：Vast 上能租到 2×L4 的 VM 吗？**
A：**不能。** 2026-11-25 实测 `gpu_name=L4 vms_enabled=true` 返回 0；L4 只有容器实例（14 个，8 个多卡：6×2 + 2×4，$0.50–1.87/h），而 k3s 需要 VM/systemd，容器起不来。2 卡 VM 当时只有 RTX 3090/4090/5090；**本次实际租的是 2×RTX 3060 12GB（instance 62540497，UK，`$0.26148/h` 含 130GB disk，40 vCPU / 98GB RAM）**，2×3090（UK $0.935/h、251GB RAM）只是备选。**“L4 容器”和“L4 VM”是两回事**，看 `vms_enabled`，不要拿容器 offer ID 建 VM。D4 用 2×3060 + Qwen3-4B-AWQ，结果标 3060；D4.5 的 4×L4 VM 同样不存在，**本次 2×3060 只有 2 卡、不能 2P+2D，D4.5 标记 skipped/blocked**，4×4090 5h（约 $9.3）保留为可选。详见 §3.1。

**Q3：ZMQ 是什么？为什么 precise routing 需要它？**
A：ZeroMQ，嵌入式消息库；vLLM PUB 5556 发 KV block 事件，EPP SUB 建精确 prefix 索引，5559 replay 补历史；PUB/SUB 不可靠，所以要监控 `active_subscribers` 和 topic/block size。详见 §5.4。

**Q4：Envoy 是谁的 sidecar，是自动注入的吗？**
A：standalone 模式下 Envoy 是 **EPP Pod 的 sidecar**，不是 vLLM Pod 的 sidecar；由 `llm-d-router-standalone` chart 显式渲染（`router.proxy.mode: sidecar`，默认），**不是 webhook 自动注入**。Envoy 通过 `localhost:9002` 调 EPP 的 ext_proc，再把请求转发到选中的 vLLM Pod。Gateway Mode 下 Envoy 是 Gateway 的数据面，EPP 独立部署；只有额外装 Istio 并开启 namespace injection 才会有 Istio 自己的 Envoy sidecar，那是另一层。

**Q5：FailOpen / FailClose 是什么意思？**
A：EPP 不可用时数据面的两种策略。**FailOpen = 放行**：Envoy 的 ext_proc 失败后不阻断，按自己的 LB 把请求发给后端，可用性优先，但失去 prefix/load 感知，P99 可能升高。**FailClose = 阻断**：直接返回 503，路由控制优先，但 EPP 变成硬依赖。standalone 看 `router.proxy.failOpen`，Gateway Mode 看 `InferencePool.failureMode`；两者不要混。D4 用 `kill -STOP 1` 暂停 EPP 来测，不能直接删 Pod（会连 Envoy 一起删）。详见 §7.3。

**Q6：2 张卡为什么不跑 TP=2，而要开 2 个副本？**
A：TP 换的是**单请求延迟**，副本换的是**总吞吐**。4B-AWQ 单卡放得下（约 2.7GB），TP 的第一价值用不上；3060 没有 NVLink，TP 每层 all-reduce 走 PCIe 不划算；而且 D4 要测路由，必须有 2 份**独立** KV cache，单实例只有一份。详见 §3.1、§1.0.2。

**Q7：vLLM 自己能做 DP 吗？为什么不直接 `--data-parallel-size 2`？**
A：能，分内部 DP（一个 endpoint，vLLM 自己分发）、Hybrid LB（每节点一个 endpoint + 上游 LB）、外部 DP（N 个独立实例 + 外部 router）三种。内部 DP 的 LB 只看各 engine 的 running/waiting 队列，**不感知 KV cache**（官方文档原话：could be made more sophisticated in future by incorporating KV cache aware logic），EPP 也插不进去。D4 用的是外部 DP。详见 §1.0.2。

**Q8：PP 一定要跨物理节点吗？**
A：不必。PP 按层切，同机也能跑；但它只在 stage 边界传 activation，通信量远小于 TP 的每层 all-reduce，所以实践公式是 `TP = 每节点 GPU 数，PP = 节点数`。代价是 **pipeline bubble**，低并发时延迟更差，所以 PP 是吞吐/容量工具。**PP 也不等于 P/D 分离**：前者是一个实例在层维度串行，后者是 prefill/decode 两个服务。详见 §1.0.2。

---

## 12. Sources

- llm-d Quickstart：<https://llm-d.ai/docs/getting-started/quickstart>
- llm-d Optimized Baseline：<https://llm-d.ai/docs/well-lit-paths/foundations/optimized-baseline>
- llm-d Precise Prefix-Cache Aware Routing：<https://llm-d.ai/docs/well-lit-paths/foundations/precise-prefix-cache-routing>
- llm-d PD Disaggregation：<https://llm-d.ai/docs/well-lit-paths/foundations/pd-disaggregation>
- llm-d Tiered Prefix Cache：<https://llm-d.ai/docs/well-lit-paths/foundations/tiered-prefix-cache>
- llm-d P2P KV Cache Sharing：<https://llm-d.ai/docs/well-lit-paths/foundations/enable-p2p-prefix-cache-sharing>
- llm-d Wide Expert Parallelism：<https://llm-d.ai/docs/well-lit-paths/foundations/wide-expert-parallelism>
- llm-d Predicted Latency Routing：<https://llm-d.ai/docs/well-lit-paths/foundations/predicted-latency>
- llm-d Flow Control：<https://llm-d.ai/docs/architecture/router/flow-control>
- llm-d Autoscaling：<https://llm-d.ai/docs/architecture/autoscaling>
- llm-d InferenceObjective API：<https://llm-d.ai/docs/api-reference/inferenceobjective>
- llm-d InferenceModelRewrite API：<https://llm-d.ai/docs/api-reference/inferencemodelrewrite>
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
