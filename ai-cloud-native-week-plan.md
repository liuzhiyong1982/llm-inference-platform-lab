# 从 DevOps 到 AI Infra：A 线（Inference Platform）主路线 + B 线（AI/ML Platform）就业轨道 + 季度执行表

> 2026-11-20 · 为 Andrew 定制 · 目标函数：**薪资**，不是"学会"
> 本文是唯一版本（替代更早的一周计划与 12 周版），后续调整都改这里。
>
> **2026-11-20 校准（Calgary / PR / A 线）**：执行策略 = **A 线专精，B 线就业**（不是 A-only，也不是 B-only）；不再按 12/14 周倒排，改用季度 gate；Calgary 本地以 B/C 线为主，A 线走 remote Canada / relocation；citizenship 是 US 通道的加速器，不是前提。详见 §0.6。

---

## 0. 先校准目标：高薪是「公司类别」的函数，不是「技能数量」的函数

美国 AI 基础设施岗位的 base 区间（同一 title 不同公司差 2 倍以上）：

| 方向 | IC | Senior | Senior Staff | 出处 |
|---|---|---|---|---|
| **ML Performance** / Kernel | $165–240K | $230–325K | $375–560K | DeepRec 2026 薪资指南（SF）[11] |
| **Inference** | $160–230K | $225–315K | $360–530K | 同上[11] |
| ML Infrastructure / ML Platform | $150–220K | $210–295K | $340–490K | 同上[11] |
| MLOps | $135–195K | $185–260K | $300–425K | 同上[11] |

> 下面是**美国 top lab 的 base band**，作为 ceiling 锚，不是加拿大起步价。加拿大本地 base 通常明显更低，remote-US 岗位也常按 local band/EOR 计价；校准见 §0.6。

同一个 "Platform Engineer" 头衔，公司之间的差距比方向之间的差距大得多：Anthropic 的 platform engineer band 是 **$316.9–429.2K**，OpenAI 是 **$258.9–419.2K**，而全站中位是 $198.6K[12]。前沿实验室的 Inference Infrastructure：Anthropic Staff/Senior **$320–485K**、OpenAI Inference-Performance **$266–500K**（base，不含 equity）[10]。

**所以三个杠杆，按顺序：**

1. **换公司类别**（公共部门 → AI 公司 / 超大规模云 / GPU 云）：一次跳跃 = 1.5–2.5 倍。这是最大杠杆，和学什么无关。
2. **换方向**（MLOps → Inference / Performance）：约 +15–25%[11]，但入场门槛更高。
3. **换框架**（多学一个 KServe / llm-d）：接近 0。框架是入场券，不是溢价来源。

**重要推论：你不需要变成 kernel 工程师才能拿高薪。** AI 公司的 platform engineer 本身就是高薪岗[12]。你要做的是**把平台能力和推理负载绑在一起**，让简历落在"AI 公司的 platform 岗"这个池子里，而不是"传统企业的 DevOps 岗"。

⚠️ 代价要认：AI 公司波动大、裁员快、强度高；你现在有稳定性和养老金。这是真实的交换，不是免费的升级。

---

## 0.5 市场现状（2026-11，先看事实再看策略）

**这是一个双速市场：总量在裁员，AI 基础设施在逆势招人。**

- 2026 年 9 月，美国在招技术岗位达到三年高点 **625,633**，同期 2026 年裁员总数已超过 2025 全年[31]。
- 结构性分化比总量更重要：ML 工程师岗位相对 2020 年 2 月基线 **+59%**，普通软件工程师 **−49%**[31]；顶级科技公司招聘量同比 **+20%**，但应届生更难[32]。
- AI 岗位底薪溢价约 **$25K / +18.7%**（staff 级）[31]。
- 真正的紧缺在基础设施侧：Data Center Engineer 平均每天 **2,615** 个在招岗位，是第二名的 5 倍多；Electrical / Power Engineer 的岗位份额半年内 **+97.9%**[34]。

**但要看清一个错位：** 招聘量最大的是数据中心建设、电力、制冷、设施运维[34]，不是"推理平台工程师"。AI 基建热的直接受益者是施工与运维岗；你想要的那类岗位，量小、单价高、竞争者是被裁的 FAANG 平台工程师。

**角色层面（你问的那个 title）：** 精确匹配 "inference engineer" 的在招岗位，2026 年 10 月全美约 **328 个**，多数要求 senior，约三分之一允许远程[37]；垂直板 inferencejobs 上 Platform Engineer 320 个、DevOps 188 个、Infrastructure Engineering 604 个[36]。薪资：inference engineer 平均 **$189–295K**（75 分位 $356K）[36]；platform engineer 平均 **$198.6–318.6K**（75 分位 $384.6K）[12]。

**最有说服力的一条：** 在这批 AI 公司岗位里，被要求最多的技能是 Python（4,724 个岗位），**第二名就是 Kubernetes（1,954 个）**，之后才是 C++（1,564）和 Distributed Systems（1,310）[36]。你的核心技能是这个小众市场的第二语言——这就是为什么"GPU + 平台"对你比对 ML 工程师更顺。

**加拿大（你的本地盘子）：** 数据中心相关 payroll 就业一年 **+22.8%**（约 8,000 人），Indeed 上数据中心岗位自 2025 年 1 月 **+68%**，而其他技术岗位只涨 **8%**；数据中心岗位比疫情前高 36%，其他技术岗位低 23%[33]。阿尔伯塔正在成为 AI 数据中心聚集地（Meta 的 Sturgeon County 项目、Bell AI Fabric 等），但现阶段岗位仍以设施管理与咨询为主[33]——本地"推理平台"岗少，这是你要么远程、要么搬迁的现实原因。

**风险，必须说清：** 2026 年 11 月的基金经理调查里，**52% 预期未来六个月内至少一家超大规模厂商宣布削减 capex**[35]，AI capex 增速已在 Q3 见顶。这意味着窗口是 **12–24 个月**，不是永久红利。

**但这个风险对你的方向反而是利好的一半：** 一旦进入紧缩周期，先被砍的是探索性项目和应用层团队；**成本优化、容量规划、多租户隔离、推理效率这类"省钱型"平台岗最后才被砍**，因为它们直接对着账单。你要练的恰好是这一半。

## 0.6 执行校准（2026-11-20：Calgary / PR / A 线）

**执行策略：A 线专精，B 线就业。不是 A-only，也不是 B-only。** 这里说的 A 线是 vLLM/SGLang、KV cache、batching、量化、llm-d 路由、K8s 服务化、性能方法论；不是 CUDA/Triton/算子优化的 ML Performance/Kernel 线。前者和 DevOps 背景重叠 30–40%，后者重叠更低。

**为什么不是 A-only，也不是 B-only：**

| 维度 | A 线：Inference Platform | B 线：AI/ML Platform |
|---|---|---|
| 岗位量 | 少，senior-heavy，集中在 AI 公司/neocloud | 更多、更分散：银行/电信/零售/企业 AI 都有 |
| 地理 | Toronto/remote/US 为主；Calgary 本地几乎没有 | Calgary 本地有 B 线；remote Canada 更多 |
| 薪资上限 | 更高（稀缺性 + 性能直接对账单） | 中高，但低于 A 线上限 |
| 入门门槛 | 高：2–3 个深度项目 + 性能方法论 | 中：DevOps/K8s 可直接平移 |
| 技能半衰期 | 框架相关部分短；性能/分布式/排障长 | 平台部分长；但容易同质化成“通用 DevOps + AI 标签” |
| 主要风险 | A-only 路窄；AI capex 波动时岗位更集中 | B-only 溢价低；容易被当通用平台工程师 |
| 代表 title | Inference Engineer / Model Serving / Inference Platform | AI Platform / ML Platform / MLOps / GPU Cloud |

**结论：A 线更有上限，B 线更有活路；最有前途的是交集——B 线就业 + A 线专精。** B 线不是“失败后的备胎”，而是就业基本盘；A 线是溢价和差异化。每季度保留两个 artifact：一个 B 线（K8s/GPU/成本/多租户），一个 A 线（benchmark/KV cache/routing）。这样任何一边市场变冷，另一边简历仍然可用。

A-only 的最低作品集门槛更高：2 个深度项目 + 1 个开源贡献/技术写作 + 能讲清 vLLM scheduler/KV cache/prefix caching/llm-d EPP 的取舍。B-only 则要避免只做 MLflow/Kubeflow 接线，必须至少有一个推理性能或 GPU 平台深度项目。

**Calgary 现实（2026-11 招聘快照，投递前核官网）：**

- 本地主要是 B/C 线：Neo Financial（Lead MLOps）、Katalyst（GPU 基础设施）、XYZ Reality（AI Platform）、Benevity（Senior Staff AI/ML）、Yotta Labs（GPU Cloud Platform Engineer）、Eleks（MLOps/LLMOps Architect，Alberta 优先）、Robots and Pencils（Staff AI Platform Engineer，Remote Canada）。
- 最接近 A 线的是 Yotta Labs：GPU 集群/多集群 K8s，不是模型性能。
- 不是 A 线：Groq（Data Center Technician，硬件运维）、GeoSoftware（HPC）、Meta/Bell（数据中心建设/运营）。
- 远程 A 线（senior/staff 门槛）：Cohere（Senior/Staff Back-End, Inference，Canada remote，$205–315K/yr，聚合站需核官网）[49]、Shopify（Senior Staff ML Inference，Remote Americas）[50]、Cerebras（Staff Inference Platform，Toronto onsite）[51]。
- 结论：A 线从 Calgary 走，主路径是 remote Canada 或 relocation；本地跳槽大概率是 B 线。

**PR / citizenship：** PR 在加拿大自由工作，但没有美国工作授权。现在能走加拿大实体/remote-Canada、少数美国公司的 EOR contractor、或加拿大公司的美国团队内部转岗（L-1 通常需海外任职满一年）。拿到 citizenship 后 TN 是最快通道；TN 的 "Engineer" 类别对学位/P.Eng 有要求，platform/DevOps title 可能更适合 "Computer Systems Analyst"。找移民律师确认，不要把"拿到护照"当成自动美国工作许可。等待期间不要停，先用加拿大 remote 岗位积累 A 线经验。

**时间分配（A 线专精 + B 线就业）：** A 线核心 60%（D1/D2/D4：benchmark 方法、KV 压力、量化质量、prefix-cache 路由）；平台支撑 25%（D3/D5：K8s、冷启动、Kueue/Kyverno，**同时作为 B 线 artifact 的主证据**）；阅读/写作 15%（vLLM/llm-d 源码、writeup）。**DRA、Volcano、Kubeflow 全家桶、PD 分离深挖降为 30 分钟概念，不进入 D1–D5 验收**；GPU Operator + MIG/time-slicing 的 6h 实操是 **B 线 Q3 可选加挂**（A 线可跳过），和 DRA 概念分开算；B 线只做 1 个 KServe/MLflow vertical slice，不展开全家桶。

> B 线不能只靠“我有 DevOps 履历”。D3（GPU 平台交付）、D5（多租户配额）、Q2 的 chargeback 要能各自独立讲成 10 分钟案例；否则投 B 线岗时仍然只有一个 inference benchmark 项目。

### 0.7 技术栈缺口校准（2026-11-24）

抽样 8 份 A 线 + 8 份 B 线 JD 后，D1–D5 的硬核部分（vLLM 调参、KV、prefix caching、PD/tiered KV、K8s/冷启动/KEDA/Kueue）覆盖良好；缺口集中在：

- **A 线：** SGLang/RadixAttention、TP/多卡、DCGM + Grafana + OTel、TensorRT-LLM/Triton 选型；
- **B 线：** KServe/OpenShift AI、Kubeflow/Ray/MLflow、Argo CD、GPU Operator/MIG/DRA、Vault/OPA/NetworkPolicy、OpenCost、RAG/MCP。

完整证据、覆盖矩阵和最小补法见 [`market-stack-gap-analysis.md`](./market-stack-gap-analysis.md)。原则：**不把 D1–D5 撑爆**，用加挂 lab 补；每个季度按依赖放 1–3 个 P0，P1 按余力再加。

**P0 按依赖关系分配（不是按“哪个季度看起来空”分配）：**

| 季度 | P0 | 关联的现有 artifact | 为什么放这里 | 验收 |
|---|---|---|---|---|
| Q1 | **P0-1 SGLang**（D2.5） | D2 | 引擎对照必须复用 D2 的同一模型、同一 workload、同一指标；隔一个季度再跑，控制变量会丢 | 1 张 vLLM vs SGLang 表 + 1 句选型结论 |
| Q1 | **P0-3a DCGM + Grafana** | D1/D3 | D3 已经装了 Prometheus，补 exporter/dashboard 成本最低；这一半不需要 D4 | 1 张 GPU + vLLM dashboard |
| Q1 | **P0-4 KServe**（D3.5） | D3 | 用 D3 的 raw Deployment 做 control，正好形成“裸 Deployment vs KServe”的 B 线基线 | 1 个 `InferenceService` + 冷启动/P99 对比 |
| Q2 | **P0-2 TP=2**（D2.6） | D4.5 | 先有 TP 的通信/显存概念，再跑 2P+2D；否则 PD 的变量和 TP 混在一起，结论不干净 | TP=1 vs TP=2 表 |
| Q2 | **P0-3b OTel + EPP trace**（D4.7） | D4 | 只有 D4 有 EPP/Envoy；trace 要覆盖“网关→EPP→vLLM”，放在 D4 之后才有对象 | 1 条 EPP→vLLM trace |
| Q2 | **P0-5 Argo CD + OpenCost**（D3.6） | D3/D4 + chargeback | GitOps 要部署 D4 的 manifest；OpenCost 直接服务 Q2 的 chargeback，不另开一条线 | 1 次 GitOps 回滚 + namespace 成本表 |
| Q3 | **P0-6 Vault/OPA/NetworkPolicy**（D5.5） | D5 | 安全策略要建在 Kueue/Kyverno 的 namespace/配额之上；先有配额，再谈准入和隔离 | 2 条拒绝日志 + 1 个 secret 注入 + 1 条 NetworkPolicy |

> **P1/P2 不排进 gate。** flow control、TensorRT-LLM/Triton、MLflow/Kubeflow slice、RAG/MCP 都是“有余力再加”的加分项；它们不改变上面 6 个 P0 的验收。不要为了 P1 把 P0 的季度挤掉。

**季度 gate（不再按 12/14 周倒排）：**

| 阶段 | 时间 | 目标 | 产出 |
|---|---|---|---|
| Q1 | 0–3 月 | 基线 + 方法学 | D1/D2 报告 + D3 冷启动/扩容 + 1 篇公开 writeup + 目标公司清单 |
| Q2 | 3–6 月 | 引擎深度 + 路由 | KV 压力/量化质量 + llm-d 路由 P99 + chargeback 表 + 第 2 篇 |
| Q3 | 6–9 月 | 生产化 + 故障 | Kueue/Kyverno 配额 + 故障日志 + SLO 面板 + 第 3 篇 |
| Q4 | 9–12 月 | 市场验证 | 3 个 A 线 artifact + 3 条 B 线 bullet + 10–20 个申请 + mock interview |
| 第 2 年 | 12–24 月 | 身份/市场扩展 | citizenship + A 线岗位或内部转岗 + US relocation |

每周 6–8h 是节奏，不是承诺；每季度一个 gate：有 artifact、有申请、有面试反馈，才进入下一阶段。

## 1. 证书：该考的其实只有 1–2 个

先说清作用边界：**证书过 ATS/HR 的筛选，不过技术面。** 它的价值是"关键词匹配 + 低成本完成感"，不是能力证明。所以策略是**用最少小时拿到关键词**，绝不能用休假周的产出时间换。

| 证书 | 价格 / 时长 | 对你 | 结论 |
|---|---|---|---|
| **NVIDIA NCA-AIIO**（AI Infrastructure and Operations, Associate） | **$125 / 60 分钟 / 50 题 / 远程监考 / 有效期 2 年**[16] | 名字里就有 "AI Infrastructure"，ATS 直接命中；内容补的是硬件层认知（GPU 架构、NVLink、InfiniBand、存储、散热），面试聊 DGX/集群时不再露怯 | ✅ **就考这个**。7.5h 课程 + 60 分钟考试，$125 是这周最便宜的确定性 |
| **NVIDIA NCP-AII**（Professional, AI Infrastructure） | $400 / 2 小时，考部署、配置、验证高级 NVIDIA 基础设施 | 偏 DGX / 硬件运维，你没有这些设备 | ❌ 暂时不考 |
| **CKA**（Certified Kubernetes Administrator） | ~$445 / 2 小时 | 若有正式认证缺口，它是平台半边的门槛；但你已有 5 年真实 AKS 平台经验，边际价值低 | ⚠️ 只有在你连一个 K8s 认证都没有、且目标公司 HR 明确要求时才考 |
| **CKNE**（Certified Kubernetes Network Engineer） | 2026-11 刚发布，可考 | AI 集群的 RDMA/RoCE/InfiniBand 是热点，但方向偏网络 | 🔶 备选，等他明确投"AI 集群网络"岗再考 |
| **KAIA（Kubernetes AI Associate）/ CKIE（Certified Kubernetes Inference Engineer）** | **2027 年推出，尚未公布考纲、价格、日期**[17] | **这是你的时间窗口**：CNCF 把"Kubernetes 推理工程"正式确认为一个独立职业方向。等考纲发布时，你已经有一年的一手实验——你就是第一批 | 🎯 **按它的方向准备，不按它的日期焦虑** |

**最关键的一条：CKIE 的存在本身就是一个市场信号。** CNCF 在 2026-11-10 宣布要把"Certified Kubernetes Inference Engineer"做成独立认证[17]——说明这类岗位的职责边界已经稳定到可以出考纲了。你路线图里练的东西（GPU 调度、权重分发、扩缩、路由、配额），正是那个考纲会覆盖的东西。**2027 年考纲出来时，你不是去"学"，是去"对答案"。**

---

## 1.5 重叠度地图：DevOps 平移能得到什么，得不到什么

先承认一个区分，我之前说得太粗：**"AI 平台岗"和"inference platform 岗"不是一回事。**

| 能力 | 你现在 | AI 平台 / MLOps 岗 | Inference platform 岗 | 迁移难度 |
|---|---|---|---|---|
| 集群生命周期、节点池、IaC、GitOps | 有 | 要 | 要 | 无 |
| GPU 调度语义（device plugin / MIG / DRA） | 概念 | 要 | 要 | 小 |
| 多租户、配额、成本归属 | 有 | 要 | 要 | 小 |
| 可观测与 on-call | 有 | 要 | 要（但要懂推理指标） | 中 |
| 模型交付：权重分发、冷启动、模型回滚 | 无 | 要 | 要 | 中 |
| 推理引擎内部：batching、KV cache、量化 | 无 | 不太要 | **核心** | 大 |
| 性能方法论：benchmark、P99、$/token | 无 | 次要 | **核心** | 大 |
| 推理感知路由 / PD 分离 | 无 | 不要 | 要 | 中 |

**结论：表面重叠约 50%，核心价值重叠只有 20%。** 你的经验能让你"进得去、站得住"，但不能让你"被认定为专家"——差了引擎内部和性能方法论这两块。

**但市场里存在一整类过渡岗，标题就写着 DevOps。** 例如 Staff/Principal DevOps Engineer, AI Inference：职责是 K8s 上的 GPU 调度与隔离、多租户共享、模型服务框架（vLLM / Triton / TGI）、请求路由、自动扩缩、成本与容量规划，同时明确要求懂 continuous batching、投机解码、量化（GPTQ/AWQ/FP8）、TP/PP[3]。

也就是说：**这个岗位的前半段是你的现有能力，后半段是你要补的那 20%。** 这类岗就是为你这种背景设计的桥——但面试一定从后半段问起，因为前半段人人都有。

**三条落点，按重叠度排序：**
1. **AI 公司的 Platform / Infrastructure Engineer（B 线）**：重叠 60–70%，最容易拿，薪资已到 $316–429K band[12]
2. **AI SRE / Production Engineering for ML（C 线）**：重叠 50%，需求新、供给少，但岗位数量还不稳定
3. **Inference Platform（A 线）**：重叠 30–40%，需要 2–3 个真项目才够格；薪资上限最高

**主目标按 2026-11-20 校准：A 线专精，B 线就业，不做 A-only，也不做 B-only。** 理由见 §0.6：A 线岗位少、senior-heavy；B 线 AI 公司的平台岗是就业基本盘，内部转 A 线比外部直接进更容易。

**判断一个 JD 属于哪条线，只看它有没有这三组词：** 引擎（vLLM/SGLang/Triton）、性能（TTFT/P99/tokens-s/量化）、并行（TP/PP/EP）。有 = A 线；只有 K8s/GPU/成本/多租户 = B 线。

### Run:ai / KAI Scheduler：3 小时，学概念不学平台

**2026-10-13，NVIDIA 把整个 Run:ai 平台开源了**（作为 DSX AI Factory 的一部分），拆成四个可独立采用的模块[48]：

- **KAI Scheduler**：GPU-aware 的 Kubernetes 调度器
- **GPU Fractioning Operator**：CUDA 原生的 GPU 切分（带显存强制，不是 time-slicing 那种"看不见彼此"）
- **KAI Resource Management**：组织级配额与层级
- **Workload Map**：统一的工作负载管理契约

八家 DSX 生态伙伴在集成，包括 **Crusoe、Nebius**——也就是那批在招人的 neocloud[48]。

**所以现在学它划算，理由有三：** ① 免费可练，没有 license 墙；② 刚开源两个月，早学等于早期优势；③ 直接对上 NCP-AIO 考纲里"Administer Run:ai"那一条。

**但只学 3 小时，而且只学两件事：**

1. 30 min：读架构，能说清四个模块各自干什么、和 Kueue 的分工（Kueue = 排队与准入；KAI = 调度器本身 + 切分；KAI RM = 配额层级）
2. 60 min：在 k3s/kind 上装 KAI Scheduler 或 GPU Fractioning Operator，跑一个 fractional GPU 的 demo
3. 30 min：写一张对比表——MIG vs time-slicing vs HAMi vs GPU Fractioning vs DRA，各自隔离性/显存可见性/适用场景

**不要做：** 不要学它的 UI 与商业版特性（开源版没有，学了也没用）；不要把它当默认答案（AI 公司内部栈里 Kueue 仍是中性默认，Run:ai 是 NVIDIA 生态加分项）。

**放在 Q3 的 4 小时里**，和 Kueue 同一周学——一次学两个，面试时"Kueue 和 KAI 怎么选"是极好的加分题。

#### 附：GPU 共享五种方案（面试原题，一张表答完）

| 方案 | 隔离性 | 显存切分 | 硬件要求 | 典型场景 |
|---|---|---|---|---|
| **MIG** | 硬件级（显存/故障隔离） | 固定档位（如 1g.5gb），档位不能自定义 | 仅部分数据中心卡：A100/A30/H100/H200/B200 等；**L4、L40S、4090、3060 不支持** | 生产多租户，要求强隔离 |
| **Time-slicing** | 无隔离，仅时间片轮转 | 不切显存，各负载都看到整卡 | 任意 NVIDIA 卡 | 开发/测试、超卖提利用率 |
| **HAMi**（CNCF Incubating，v2.11） | 软件限制（libvgpu 拦截 CUDA 调用） | **任意大小**（可以切 12GB 这种 MIG 切不出来的规格） | 异构（NVIDIA/AMD/昇腾等），不依赖 MIG | 国内/政企、异构算力、需要非标准切分 |
| **KAI GPU Fractioning**（NVIDIA 开源，2026-10） | 软件 + CUDA 原生显存强制 | 分数卡 | NVIDIA，配合较新 CUDA | NVIDIA 生态、想要比 time-slicing 更强的限制 |
| **DRA** | 由 device 驱动决定 | 取决于驱动（DRA 只负责申请与分配契约） | K8s ≥1.34 GA（1.35 起 gate 锁定；本仓库 1.37） | 新集群、结构化设备申请、未来默认 |

**一句话记住：** MIG 是硬件切、档位固定；time-slicing 是排队用整卡、没有隔离；HAMi 和 KAI Fractioning 是软件切、能切任意大小但没有硬件级故障隔离；DRA 是"怎么向 K8s 申请设备"的协议，不是切分方案本身——它常和上面几个一起用。

**L4 特别说明：** L4 是 Ada 卡，**不支持 MIG**；要在 K8s 里做 MIG 实验必须换 A100/A30/H100/H200 等。L4 上只能用 time-slicing / MPS 共享，或者整卡分配；DRA 也不能把不支持 MIG 的卡“变”出 MIG。

### NCP-AIO(L)：这张证到底证明什么（修正前一版）

先说清级别：**NCP-AI Operations 是 Professional 级、带实操**，不是 NCA-AIIO 那种 Associate 选择题。官方细节[42]：

- **$500 / 120 分钟 / 30 道选择题 + 3 个 hands-on lab**，两部分各占 50% 分数，Pass/Fail，英文，有效期 2 年
- 前置要求：**2–3 年在数据中心运维 NVIDIA 硬件的经验**（你现在没有——AKS 上没有 GPU）
- 考纲权重：Install & Deploy **32%**、Administration **28%**、Workload Management **20%**、Troubleshooting & Optimization **20%**、Cognition/Planning/Memory **10%**[43]
- 内容清单：NVIDIA **Fleet Command**、**Slurm** 集群、**Run:ai**、**MIG**、**Base Command Manager (BCM)**、DGX、DPU、InfiniBand
- 实操题明确要求：**在 BCM 里用 Slurm 排障**、用 Kubernetes 跑一个 workload、**用 BCM 给集群加节点**[43]

**所以这张证证明的是"你能运维 NVIDIA 的 AI 数据中心"，不是"你能设计推理平台"。** 它的价值完全取决于你投哪类岗：

| 目标岗 | 这张证的价值 |
|---|---|
| neocloud（CoreWeave / Lambda / Crusoe）、AI 数据中心运维、阿尔伯塔在建的数据中心项目 | **高**——岗位日常就是 Slurm + BCM + Run:ai + MIG，这张证几乎是岗位说明书的复刻 |
| AI 公司的 inference platform（vLLM / KServe / llm-d / Kueue） | **低到中**——Fleet Command、BCM、DGX 那部分用不上；只有 K8s 管理、Slurm、MIG 三段可迁移 |

**两个现实障碍：** ① 三个 lab 必须在 BCM 环境里做，没有 NVIDIA 硬件就只能靠官方课程提供的 lab 环境练，风险高；② $500 + 约 20–30 小时，等于你一个季度学习预算的三分之一。

**决策建议：** 先回答"我到底投 neocloud/数据中心，还是 AI 公司的平台岗"，再决定要不要花这 $500。如果投前者，这张证优先级高于 CKIE；如果投后者，把这笔钱换成 30 小时 GPU 租用 + 核心性能数字，回报高得多。

### NCA-AIIO 到底值不值：按官方考纲权重算

官方公布的三块权重[16]：

| 板块 | 权重 | 内容 | 对你 |
|---|---|---|---|
| Essential AI Knowledge | **38%** | NVIDIA 软件栈、训练 vs 推理架构差异、AI/ML/DL 概念、GPU vs CPU | 一天能背完，面试不加分 |
| AI Infrastructure | **40%** | 硬件选型、GPU 集群扩展、**供电与制冷**、on-prem vs cloud、集群组件、**数据中心网络协议 / IB / RoCE / DPU** | 你的盲区，也是唯一真正"学到东西"的部分 |
| AI Operations | **22%** | 数据中心监控、**集群编排与作业调度**、GPU 监控指标、加速资源虚拟化 | 你本来就会 |

**结论：这证对你是"补 40% 盲区"，不是"证明 22% 的强项"。** 面试官不会因为一张 Associate 证书认为你会运维 AI 数据中心——它只保证你不说错术语。但 $125 + 一个周六，换掉"供电/制冷/IB/RoCE/DPU"这块盲区，划算。

**降级处理：** 它不是"明年的目标"，是"某个周六的 2 小时任务"。顺序永远是先做出 artifact，再顺手考掉。半衰期也短（有效期两年），而且 2027 年 CKIE 出来后，"K8s 推理"这个标签会比"AI 设施"更值钱。

**2 小时备考路径（不用上 7.5 小时课）：**
1. 60 min：供电与制冷（kW/rack、PUE、液冷）、IB vs RoCE、rail-optimized 组网、DPU 为什么存在
2. 30 min：GPU 代际与规格（显存、带宽、NVLink/NVSwitch、H100/H200/GB200 差异）
3. 30 min：过一遍官方推荐阅读清单 + 一套练习题[16]

### 为什么 CKIE 比 NCA-AIIO 更适合你

| 维度 | NVIDIA NCA-AIIO | CNCF CKIE（2027） |
|---|---|---|
| 领域 | AI 数据中心基础设施（供电/制冷/网络/硬件） | Kubernetes 上的推理工程——你正在练的那条线 |
| 题型 | 50 道选择题，60 分钟[16] | CNCF 的工程师级认证历来是**实操型**（CKA/CKNE 都是考场动手） |
| 品牌权重 | neocloud / 设施运维侧更认 | 云原生雇主侧更认，和你的 GitHub / K8s 履历同一个语言 |
| 对你 | 补盲区 | **优势区**——你有 5 年实操，选择题考不出你的强项，实操题可以 |

**所以顺序改一下：CKIE 是目标证，NCA-AIIO 只是可选的补盲小任务。**

但 CKIE 的现实约束要说清：2027 年推出，**考纲、价格、日期全都未公布**[17]。也就是说现在只能"按领域准备"，不能"按考纲准备"。好消息是这两件事在你的路线图里是同一件事。

**今天就能做的三件事**

1. **订阅发布通知**（30 秒）：[KAIA & CKIE Notify Me](https://training.linuxfoundation.org/kaia-ckie-notify-me/)[41]
2. **申请当 SME（出题专家）**：同一页面在招募 subject matter experts 参与"define, write, and review"两份考卷[41]。这是最有杠杆的一步——报名成本为零，一旦入选，你会在考纲公开前就看到它考什么，简历上还会多一行"参与 CNCF 认证出题"。即使因为推理经验还不满被拒，也不损失什么。
3. **把路线图标注成"CKIE 预科"**：考纲出来后你只需要"对答案"，不需要"从头学"。

**最终认证组合：** 现在可选 NCA-AIIO（$125，补硬件盲区）→ 2027 考 CKIE（目标证）→ 跳过 KAIA（Associate 级，对你太浅）与 CKNE（网络方向）→ CKA 仅在你连一个 K8s 认证都没有时补。

## 1.6 Calgary 本地入口（真实 JD，不是推断）

你的观察是对的：**没有一份 JD 写着"要求 NCP-AIO"**。证书在加拿大几乎不出现在招聘要求里。但 Calgary/阿尔伯塔有一批岗位在真实使用 GPU 集群 / Slurm，而且其中两份几乎是照你的背景写的。**先分清线：这些主要是 B/C 线，不是 A 线 inference platform。**

| 公司 | 岗位 | 线 | 关键要求 | 你的差距 |
|---|---|---|---|---|
| **Eleks** | Infrastructure/GPU Cluster/Platform Operations Lead（Remote Canada，**明确偏好 Calgary/Edmonton**）[44] | B | 8+ 年基础设施/平台运维、**GPU 集群管理**、强 K8s、NVIDIA GPU/CUDA 生态、Azure/AWS/GCP、存储网络 HPC、Terraform、运维领导力 | **只差"GPU 集群"这一条**；零证书要求 |
| **GeoSoftware** | Senior HPC and Platform Engineer（Calgary，hybrid，2026-11-02 发布）[45] | B/C | 同一套科学计算负载跑在 workstation / **Slurm 或 PBS** / Databricks / 云 batch 之上；checkpoint-restart；构建与交付流水线 | **Slurm/PBS**——你 BCM 已装，缺的只是 Slurm |
| **Groq** | Data Center Technician（Calgary，onsite，2026-10-09）[46] | C | 数据中心现场硬件运维，2+ 年 | 层级低于你；**不要把它当 A 线入口** |
| **Meta / Bell AI Fabric** | Sturgeon County 1GW 数据中心（2026-07 开工，投资超 CAD$13B）[47]；Bell 七个高密度数据中心 | C | 建设期为主，运营岗 2027–2028 释放 | 设施/硬件运维，不是模型服务 |

**本地 B 线（2026-11 快照，投递前核官网）：** Neo Financial（Lead MLOps）、Katalyst（GPU 基础设施）、XYZ Reality（AI Platform）、Benevity（Senior Staff AI/ML）、Yotta Labs（GPU Cloud Platform Engineer）、Robots and Pencils（Staff AI Platform Engineer，Remote Canada）。Yotta 最接近 A 线，但仍偏 GPU 集群/多集群 K8s。

**A 线远程/多伦多（senior/staff 门槛）：** Cohere（Senior/Staff Back-End, Inference，Canada remote，$205–315K/yr，聚合站需核官网）[49]、Shopify（Senior Staff ML Inference，Remote Americas）[50]、Cerebras（Staff Inference Platform，Toronto onsite）[51]。

**结论：** Calgary 本地不缺"要 GPU 集群 + Slurm 经验的人"，但缺 A 线 inference platform 岗；A 线主路径是 remote Canada 或 relocation。证书不给你面试，GPU 集群/推理性能证据给你面试。

### 用一个周末把 Slurm 补上（BCM 已装 = 你已经有一半）

NCP-AIO 的实操 lab 是三个场景：**在 BCM 里用 Slurm 排障、用 K8s 跑 workload、用 BCM 加节点**[43]。这三件事在 BCM 里都能自己练，不需要 GPU 卡：

1. 用 BCM 起 2 个 VM 节点（head + compute），注册进集群 → 你就有了一个 Slurm 集群
2. 练日常：`sbatch` / `squeue` / `scancel` / `sinfo` / `scontrol show node`，分区与 QoS
3. 练加节点（lab 场景之一）：再起一个 VM，用 BCM 注册进集群，确认 `sinfo` 里出现
4. 练排障（lab 场景之二）：`scontrol update NodeName=x State=DRAIN`、kill 掉 `slurmctld` 看恢复、模拟节点 Not-Responding，读 `slurmctld.log` 定位
5. 产出一页 runbook：症状 → 检查命令 → 判据 → 处置

**6–8 小时，一个周末。** 做完这件事，你同时拿到：GeoSoftware 那类岗位的入场词、NCP-AIO 三个 lab 的肌肉记忆、以及一个能写进简历的"Slurm 集群运维"条目。

### 那 $500 还花吗

按优先级：**Slurm 实操 > 证书**。证书等出现具体面试机会再考——那时它会变成"我在准备这个认证"，而不是"我考了个证"。如果最终目标是 Eleks 那种 GPU 平台岗，证书完全不必要；如果目标转向 neocloud 的数据中心运维，再考不迟。

## 2. 课程：只有三门值得花时间，总共 ≤ 6 小时

不是"上课"，是"当手册用"：每门课必须配一个产出，否则不上。

| 资源 | 时长 | 该拿走什么 | 配什么产出 |
|---|---|---|---|
| **Fast & Efficient LLM Inference with vLLM**（DeepLearning.AI × Red Hat，Cedric Clyburn）[14] | 1h38 / 9 节 / 3 个代码示例 | 量化压显存 → vLLM 起服务 → 用 GuideLLM 压测 → 用 lm-eval 验质量，整条 optimize-deploy-benchmark 链路 | 你自己的 baseline 表（Day 1 直接复用） |
| **Efficiently Serving LLMs**（Predibase CTO Travis Addair）[15] | 2h09 / 8 节 / 6 个代码示例 | KV cache 为什么让生成变快、continuous batching 的取舍、LoRA 多模型共卡 | "为什么并发上去了单请求反而变慢"的一段解释 |
| **llm-d Well-Lit Paths**（官方 docs，不是课程）[13] | 边做边读 | 8 条经过 benchmark 的部署配方：optimized baseline、prefix-cache 精确路由、PD 分离、wide EP、flow control、推理池自动扩缩 | 跑通其中一条 + 一张前后对比图 |

**不上：** K8s 通识课、AI 通识课、prompt engineering、任何 20h+ 的"AI 工程师"专项。它们不会让面试官多问一句。

---

### 中文课程怎么判（买前三个问题）

个人 IP 的中文课（小乙那类 K8s/运维开发课）价值在"机制讲得密 + 有人答疑"，风险在"没有公开大纲、渠道靠私聊、更新不可控"。买前只问三件事：

1. **有公开目录吗？** 是否明确写了 device plugin / MIG / time-slicing / GPU 共享（HAMi）/ DCGM 监控 / 动手实验。写不出目录 = 不要买。
2. **能按模块买吗？总时长 ≤15 小时吗？** 几十小时的体系课会直接吃掉你一个季度的预算。
3. **价格 ≤ 你两小时工资吗？** 超过就是在为"被讲一遍"付费，而你要的是能被追问的理解。

**如果只买一门，买 K8s 机制 / Operator 开发，不要买"GPU 平台"那门。** 前者是跨公司、跨栈的长期资产；后者半年就过期——国内的 vGPU/HAMi 方案和北美的 vLLM + llm-d + Kueue 栈不是一回事。

**免费替代（今天就能用）**

- [ai-factory-ops-lab](https://github.com/ld-singh/ai-factory-ops-lab)[38]：K8s GPU 调度 + HAMi 共享 + Slurm + 可观测 + vLLM 推理，笔记本上就能练，再在一张便宜卡上验证。有 Makefile、runbooks、portfolio-lab 结构——**可以当免费课程大纲用**（项目很新、星不多，别当权威，当骨架）。
- [Kubernetes GPU Guide 2026](https://kubezilla.io/kubernetes-gpu-guide)[40]：免费长文，带可用 manifest、vLLM lab、DCGM 监控和"你真会撞到的报错"。
- [LearnKube: Building GPU Platforms on Kubernetes](https://learnkube.com/gpu-kubernetes-training)[39]：英文、四天、面向 platform engineer，贵，但方向最正——等你要冲 A 线时再考虑。

**判断标准一句话：课程解决"没人给我讲"，你的瓶颈是"没人逼我测"。** 先 clone 那个 lab 对着做三天，如果确实卡在机制上听不懂，再花钱买讲解——那时每一小时都值。

### 先选节奏：你在骑驴找马，不是在赶面试

有工作、不着急 = 时间在你这边，但风险换了一种：**不是失败，是拖。** 六个月后还在"准备开始"的人，比面试失败的人多得多。

| | 冲刺版（7 天出成果） | **点火版（推荐，有工作时用）** |
|---|---|---|
| 休假周投入 | 6 天 × 3–4h | **2 天 × 4h，其余真休息** |
| 休假周产出 | 核心 4 个数字 + 一张对比图 | **repo + 第一个数字（baseline）** |
| 后续节奏 | — | 每周 6–8h，按季度 gate 推进 |
| 适合 | 在职但想三个月内换 | 在职、想 12–24 个月换到更好的 |

**为什么推荐点火版：** 你有工作，休假烧成第二个工作周，第二周就会崩。而"拿到第一个数字 + 把 repo 建起来"这个动作，已经把最难的部分（启动惯性）解决了；剩下的靠每周 6–8 小时按季度滚。

**防拖三条机制（比计划本身重要）：**
1. **固定时段**：周二、周四 21:00–22:30，周六 09:00–12:00。写进日历，不靠意志力。
2. **每两周一个可见产出**：repo 里必须多一个能跑的东西或一组数字。没有产出的一周，下周一补，不许顺延。
3. **每四周一个 gate**：还在学吗？有产出吗？要不要换方向？——允许停，但要在 gate 上停，不许无声消失。

## 3. 可选 intensive（7 天冲刺；不是主路径）

> 这一节是可选冲刺，不是主路径。你有工作、按季度走；**D1 以 `d1-vllm-baseline-runbook.md` 为准**。点火版只做 D1–D2，下面的全周验收不适用。

> **开工前（这个周末，6–8 小时）：先把 Slurm 做掉。**
> 它不需要 GPU、不用等租卡、BCM 你已经装好，而且它是 GeoSoftware 那类本地岗位的入场词、也是 NCP-AIO 三个 lab 里的两个。放在休假日之前做完，休假整周就能专心做 inference——两件事不在同一周抢时间。

**冲刺周的唯一目标：一个 repo、核心 4 个数字 + 2 个对比、一张 llm-d 对比图、一次 10 分钟讲解。** 不是"学完什么"。

预算：GPU 租用 ≈ $10–15（按秒计费，D1/D2 用单卡 L4 容器；D4 用 2×3060 12GB VM，`$0.2615/h`，D4 + D4.6 约 6.3h / ~$1.66）。Azure 侧配额为 0，不要等审批。**Vast 没有 L4 VM，D4 不要按 2×L4 VM 租。**

| 天 | 时长 | 干什么 | 当天必须落地 |
|---|---|---|---|
| **D1** | 4h | 按 `d1-vllm-baseline-runbook.md` 跑 baseline；短课当手册，时间不够就跳过[14] | 4 个 baseline JSON + README 表 + 一句话归因 |
| **D2** | 3h | `max-num-seqs`、chunked prefill on/off、prefix caching 有/无（用 `--disable-prefix-caching` + `--random-prefix-len` 构造共享前缀）；AWQ vs FP16 + 质量门；读 KV cache / batching 那两节[15] | 一张对照表 + 一句话结论（吞吐 +x%，TTFT −y%，质量 Δ） |
| **D3** | 3h | k3s + vLLM Deployment；**权重分发实测**：initContainer 现下 vs node-local 缓存，测冷启动秒数；KEDA 按 `vllm:num_requests_waiting` 扩缩 | 冷启动对比（秒）+ 扩容曲线；**B 线：GPU 平台交付链路 + 每副本成本** |
| **D4** | 4h | **llm-d 日**：租 2×3060 12GB VM（instance 62540497；L4 VM 不可得）、模型 Qwen3-4B-AWQ，按 Well-Lit Path 跑 `precise-prefix-cache-routing`（或 optimized baseline）[13]；同一批"共享长前缀"的请求，对比普通 round-robin vs EPP 路由的 P99 | 一张 P99 对比图 + 命中率数字；**B 线：Gateway/InferencePool 运维图 + 路由故障表**。**2026-11-25 已跑**：TTFT P99 direct 4475ms / optimized 3459ms（−22.7%）/ precise 3969ms；图 `results/d4/d4-ttft.png` |
| **D5** | 3h | Kueue `ClusterQueue` 两团队配额[9] + Kyverno 强制 GPU workload 带 priorityClass / quota label；跑"抢卡"演示 | 两条被拒 manifest 日志；**B 线：配额/准入/审计说明** |
| **D6** | 3h | 1500 字 writeup + 10 分钟讲稿 + 简历两行；**晚上**报名 NCA-AIIO（$125）[16]，把考试排在下一周 | 可发出去的链接 + 已预约考试；**B 线：500 字平台案例 + 2 条 B 线 bullet** |
| **D7** | — | 休息。唯一动作：列 10 家目标公司 + 抄 3 个真实 JD。不碰终端 | 目标公司清单；**B 线：3 个本地 B 线 JD 映射** |

> D3 的学习文档见 [`d3-k8s-vllm-learning.md`](./d3-k8s-vllm-learning.md)（2026-11-24 已执行：§7 冷启动、§8 KEDA/1→2、§9 驱逐；实付约 `$4.00`）；D3 直接用 Vast RTX VM（你已在上面跑过 k8s），租借命令见该文档 §5.0。执行后把三个数（冷启动、扩容曲线、驱逐）补进 README。
>
> D4 的学习文档见 [`d4-llm-d-learning.md`](./d4-llm-d-learning.md)（2026-11-24 准备，**2026-11-25 已执行，实付 $1.19 / 4.54h**）：4h、**2×RTX 3060 12GB VM（instance 62540497，UK，`$0.26148/h` 含 130GB disk，40 vCPU / 98GB RAM）**、llm-d `v1.0.0` precise prefix-cache routing；主对比是 Service round-robin vs EPP，EPP random 作为控制组；模型改为 **Qwen3-4B-AWQ**（served name `qwen3-4b`）、TP=1、2 副本，`max-model-len 8192`、`max-num-seqs 16`、`gpu-memory-utilization 0.90`、`block-size 64`，`peakPrefillThroughput` 需重测。文档 §1.4 + 附录 A 另给 llm-d 核心 feature 覆盖矩阵（PD、wide EP、flow control、tiered/P2P、autoscaling、batch、rollout、API），D 档为概念/决策，不额外租卡。可执行 manifest/脚本在 `scripts/d4/`。**2026-11-25 复核：Vast 无 L4 VM（L4 只有容器，k3s 起不来），2×3090 只是备选；本次实际租 2×3060，结果标 3060。** D4 系列的缩写全称见 [`d4-llm-d-learning.md`](./d4-llm-d-learning.md) §1.0.1。
>
> **可选 D4.5（Q2，不是 D4 的 4h 内）：** PD 分离 2P+2D，4×4090 VM（4×L4 VM 不可得）；**本次 instance 62540497 是 2×3060 12GB，只有 2 张卡、不能 2P+2D；4×3060 VM 不存在，D4.5 标记 skipped/blocked**；4×4090 5h（约 $9.3，硬上限 $10）保留为可选，以后余额和需求都够再决定。文档见 [`d4.5-pd-lab.md`](./d4.5-pd-lab.md)（**本次不执行**），manifest/脚本在 `scripts/d4.5/`。它回答“4 个完整副本 vs 2 prefill+2 decode，在 4090/TCP 上 PD 是否值得”，不保证 PD 赢。
>
> **T0/T1 覆盖（按市场调研）：** T0 的 optimized baseline + EPP/`InferencePool` 和 T1-A precise 在 D4 主实验；T1-B PD 在 D4.5（本次 skipped/blocked）；T1-C tiered KV 在 [`d4.6-tiered-cache-lab.md`](./d4.6-tiered-cache-lab.md)（**2026-11-25 已执行**，2×3060 12GB + Qwen3-4B-AWQ，16GiB CPU tier，3+3 轮，增量 ~$0.29）：P50 **1434→336ms（−77%）**、goodput **0.81→1.10 req/s（+36%）**、整体 P99 不变（冷启动主导），复用请求 P50 **1444→289ms（−80%）**。三个 lab 合起来覆盖 T0 + T1，不要求塞进同一个 4h。
>
> D5 的学习文档见 [`d5-kueue-kyverno-lab.md`](./d5-kueue-kyverno-lab.md)（**2026-11-25 准备，尚未在 Vast 执行**；本地 kind 已用假 `nvidia.com/gpu=2` 验证 Kueue 配额/排队/抢占 + Kyverno CEL）：3h、2×3060 12GB、约 `$0.9`；Kueue `v0.20.7`、Kyverno `1.20.0`、k3s `v1.37.2+k3s1`；manifest 在 `scripts/d5/`。**版本坑：Kueue 0.20 只服务 `kueue.x-k8s.io/v1beta2`；Kyverno 1.20 已停止执行 `kyverno.io/v1 ClusterPolicy`，策略统一用 `policies.kyverno.io/v1` 的 CEL 类型。** D5 是 B 线“配额/准入/审计”主证据；执行后把两条拒绝日志、配额表和抢占证据补进 README。

### D3 / D5 的 B 线讲法

D3/D5 在 A 线作品集里是“平台支撑”，但在 B 线岗位面前要独立讲成两个案例，不能只说“我部署过 vLLM”：

- **D3（GPU 平台交付）**：“我把 vLLM 从裸机搬到单节点 k3s，量了 cold vs warm 冷启动的分阶段耗时（权重下载 __s / 模型加载+引擎 __s / 总 Ready __s），用 KEDA 按 `vllm:num_requests_waiting` 做 0→1 和 1→2 扩容；单卡 1→2 的 `Pending` 证明 GPU 整数分配是容量瓶颈，不是 HPA 算法问题。”
- **D5（多租户配额与准入）**：“我用 Kueue `ClusterQueue` 给两个团队分 GPU 配额，Kyverno 强制 GPU workload 带 `priorityClass` 和 quota label，跑了一次抢卡演示并留下两条拒绝日志；这解决的是‘谁能拿卡、拿不到怎么排队’，不是副本数。”

### B 线学习内容（D3–D7）

D1/D2 是纯 A 线；从 D3 起每天至少留 30–45 分钟给 B 线，并把内容写进当天记录。B 线不是额外项目，而是同一套实验的另一个视角：

| 天 | B 线学习内容 | 面试能接住的问题 |
|---|---|---|
| D3 | GPU 平台交付链路（driver → toolkit → k3s → device plugin → RuntimeClass → Pod）；模型分发（hostPath/local PV vs 镜像内置）；KEDA/HPA；PDB/驱逐；每副本 `$/h`；namespace/label 规范 | GPU 怎么被调度？冷启动慢在哪？单卡为什么扩不出第二副本？怎么优雅驱逐？ |
| D4 | Gateway API / `InferencePool` / EPP 的部署与健康检查；路由指标（命中率、P99、5xx）；多模型/多租户路由；故障模式（EPP 挂了、后端不健康、前缀不命中） | llm-d 和普通 Service 路由差在哪？EPP 挂了怎么办？多租户怎么隔离？ |
| D5 | `ClusterQueue` 配额/优先级/抢占；Kyverno 准入与审计；GPU 节点池/容量规划；模型版本回滚 | Kueue 和 HPA 怎么分工？怎么防止一个团队抢光 GPU？模型回滚怎么做？ |
| D6 | 把 D3/D4/D5 写成平台案例：SLO、成本、故障处置；B 线简历 bullet | 讲一个你交付过的 GPU 平台案例；怎么证明平台没被滥用？ |
| D7 | B 线公司/JD 清单（Calgary 本地优先）；逐条映射 D3/D5/chargeback | 你的 K8s 经验怎么迁移到 ML platform？chargeback 怎么算？ |

**冲刺版验收（可选；只做 D1 不要用这张表）**
- [ ] `make bench` 一键复现（尚未实现；做 D3 时补）
- [ ] 3 张图：throughput vs concurrency / TTFT P99 / llm-d 路由前后 P99
- [ ] 2 条策略拒绝日志（Kyverno + Kueue）
- [ ] 冷启动：带缓存 ____ s vs 不带 ____ s
- [ ] B 线：D3 冷启动表 + D5 两条拒绝日志 + 3 个 B 线 JD 映射
- [ ] 核心 4 个数字 + 2 个对比全部填上
- [ ] 10 分钟讲得完，且能被追问 3 层

---

## 4. 季度 gate 路线（每周 6–8h；不再按 12/14 周倒排）

> 时间表见 §0.6；这里只定义每个 gate 的内容和验收。**不要为了赶周次牺牲深度。**

### A/B 线 artifact 对照（每季度各一个）

§0.6 定了“A 线专精、B 线就业”，但只写在策略层会落空。下面把 B 线 artifact 固定进每个 gate；A 线沿用原验收。

| 季度 | A 线 artifact | B 线 artifact | B 线验收（能独立讲） |
|---|---|---|---|
| Q1 | D1 baseline + D2 调参表 | **D3 GPU 平台基线**：k3s + device plugin + vLLM Deployment + cold/warm 冷启动 + KEDA 0→1 | 分阶段冷启动表 + 1→2 `Pending` 或扩容曲线 |
| Q2 | KV 压力 + llm-d prefix-cache 路由 P99 | **$/1M tokens chargeback**：namespace/team 级成本归属 | 1 小时窗口的成本归属表 + 公式 + 口径说明 |
| Q3 | 故障 lab + SLO 面板 | **多租户配额**：Kueue `ClusterQueue` + Kyverno 准入 | 2 条拒绝日志 + 配额/优先级说明 |
| Q4 | 3 个 A 线 artifact 定稿 | **B 线简历 bullet + JD 映射** | 3 个 B 线 JD 逐条映射到证据，能讲 10 分钟 |

### Q1（0–3 月）：基线 + 方法学

- D1：4 个并发点 baseline + README 表 + 一句话归因（按 `d1-vllm-baseline-runbook.md`）。
- D2：`max-num-seqs`、chunked prefill on/off、prefix caching 有/无、AWQ vs FP16 + 质量门；执行细节见 `d2-vllm-tuning-runbook.md`。
- **D2 对比规矩（避免把噪声当优化）：**
  - 一次只动一个变量；模型、输入/输出长度、并发点、宿主（含 power limit）、采样方式全部固定。
  - 每个配置至少重复 2 次，报中位数/范围，不报单次最好值。
  - 只和**同一台机器**的 D1 baseline 比；换 host（尤其 40W vs 72W）必须重跑 baseline。
  - 不必每个配置都跑 4 个并发点：先用 c=16 找拐点、c=64 看吞吐上限，最优配置再补 c=1/4/16/64。
  - 每个配置记录：`max-num-seqs`、chunked prefill、prefix caching、量化格式、TTFT P50/P95/P99、TPOT P95、output tok/s、goodput、preemptions。
  - 结论写成「哪个旋钮、动了多少、哪个指标变了多少、为什么」，不是「调到最快」。
  - D3–D5 也各有 baseline：冷启动 naive vs cache、round-robin vs EPP、无策略 vs Kueue/Kyverno。
- D3（B 线 artifact）：k3s + vLLM Deployment、device plugin、cold/warm 冷启动、KEDA 0→1/1→2；执行细节见 `d3-k8s-vllm-learning.md`。
- B 线学习：GPU 平台交付链路、模型分发、KEDA/HPA、PDB/驱逐；能回答 `d3-k8s-vllm-learning.md` §12 的 B 线四问。
- 固定方法学：SLO、样本数、warmup、重复次数、开环/闭环、成本公式、货币。
- 写 1 篇公开 writeup；列 10 家目标公司 + 5 个真实 JD。
- **验收：** 4 个 baseline JSON + 1 张调参表 + 1 篇 writeup + D3 冷启动表/扩容证据 + 5 次信息面/招聘方沟通。

### Q2（3–6 月）：引擎深度 + 路由

- KV cache 压力实验：并发拉到 preemption，记录抢占次数、TTFT 拐点、吞吐塌陷。
- `max-num-batched-tokens` / chunked prefill 的取舍；量化质量 delta。
- llm-d prefix-cache routing：共享长前缀，对比 round-robin vs EPP 的 P99 和命中率。
- 源码阅读：vLLM scheduler / KV cache / prefix caching；llm-d EPP。
- **B 线 artifact：$/1M output tokens 的 chargeback**（按 namespace/team 归属；执行见本节后面的 lab）。
- B 线学习：llm-d 的 Gateway/`InferencePool`/EPP 运维；chargeback 口径；多租户路由。
- **验收：** 2 个 A 线深度 artifact + chargeback 表 + 第 2 篇 writeup + 5–10 个申请。

### Q3（6–9 月）：生产化 + 故障

- 生产级 manifest 收口：把 Q1 的单节点 D3 扩到多副本/多节点；只有单卡就保留“1→2 `Pending`”的结论，另补 PDB、滚动更新、node drain。
- **B 线 artifact：** Kueue `ClusterQueue` 两团队配额 + Kyverno 一条 GPU 准入策略；保留 2 条拒绝日志。
- B 线学习：Kueue 配额/抢占、Kyverno 准入/审计、GPU 节点池/容量规划、模型回滚。
- DCGM + vLLM `/metrics` + SLO 面板（`$/1M tokens` 归属已在 Q2 的 chargeback lab 完成）。
- 故障 lab：OOM、KV cache 打满/抢占、pod kill、node drain、权重下载超时、driver 不匹配；每条记录“症状 → 命令 → 判据 → 处置”。
- **验收：** 生产级 manifest + 2 条策略日志 + 故障日志 + SLO 面板 + B 线配额说明。

### Q4（9–12 月）：市场验证

- 3 个 A 线 artifact 定稿；简历 v2；10 分钟讲解录音；10 道必答题自测。
- **B 线 artifact：** 把 D3/D5/chargeback 各写成 1 条简历 bullet（共 3 条）；选 3 个真实 B 线 JD 逐条映射到证据，再选 3 个 A 线 JD 映射 D1/D2/D4。
- B 线学习：3 个 B 线 JD 逐条映射；至少 2 场 B 线模拟面试。
- 投 10–20 个 A/B 线岗位。
- 可选：给 vLLM/llm-d 提一个小 PR（docs/test/benchmark 都算）。
- **验收：** 3 个 A 线 artifact + 3 条 B 线简历 bullet + 简历 v2 + 10 个已投 + 答上 ≥8/10 题。

### B 线 lab：$/1M tokens 的 chargeback（Q2 执行）

目标：回答“哪个 namespace/team 用了多少 GPU 钱”，而不是只报一个全集群的 `$/1M tokens`。B 线 JD 里的“成本归属/chargeback”问的就是这件事。

**先把口径定死（面试第一问就是口径）：**

- 分母用 `vllm:generation_tokens_total`（output tokens），不要混入 prompt tokens；需要全口径时另报一列 `vllm:prompt_tokens_total`[56]。
- 分子用**副本占用的 GPU 小时 × 单价**，不是“实际忙时”。GPU 空闲也计费，闲置摊销必须算进去，否则低负载时 `$/1M tokens` 会虚低。
- 一张卡被多个模型共享时，先按 GPU-seconds 或约定份额分摊，再除以各自 tokens；不要直接把整张卡的钱按 token 比例分。

**PromQL（1 小时窗口）：**

```promql
# 每个 namespace 的 output tokens
sum by (namespace) (increase(vllm:generation_tokens_total[1h]))

# 每个 namespace 的 prompt tokens（可选，报全口径）
sum by (namespace) (increase(vllm:prompt_tokens_total[1h]))

# 每个 namespace 的 vLLM 副本数（按 1 GPU/副本估 GPU 小时）
count by (namespace) (kube_pod_status_phase{phase="Running", pod=~"vllm-.*"} == 1)
```

> `namespace` 标签由 Prometheus 的 Kubernetes 服务发现加上；如果查询结果为空，先检查 ServiceMonitor/PodMonitor 的 `namespaceSelector`。`kube_pod_status_phase` 来自 kube-state-metrics。

**算账模板（1 小时窗口，单价按实际账单）：**

| namespace | 副本 | GPU 小时 | GPU 成本 | output tokens | $/1M output tokens | 备注 |
|---|---|---|---|---|---|---|
| team-a | 1 | 1.0 | $0.2611 | 5.0M | $0.052 | 满负载 |
| team-b | 1 | 1.0 | $0.2611 | 2.0M | $0.131 | 低负载，闲置摊销高 |

```text
$/1M output tokens = (GPU 小时 × GPU 单价 + 存储/网络) / (output tokens / 1,000,000)
```

**交付物：** `results/chargeback-YYYYMMDD.csv` + README 一段“口径 + 一张表 + 一句结论”。结论要能回答：同样的卡，为什么 team-b 的 `$/1M` 是 team-a 的 2.5 倍——是输出长度/模型不同，还是利用率不同。

**面试怎么讲：** “chargeback 的难点不是 PromQL，是口径：按预留 GPU 小时还是按实际 token？我两种都算，差额就是闲置成本；平台团队要能解释这笔钱该由谁承担。”

### 为什么是 Kueue 而不是 Volcano（以及什么时候反转）

Volcano 是 CNCF Incubating 的高性能批处理调度器（2020 进沙箱、2022 进孵化），核心差异是 **gang scheduling**（8 卡任务要么全起、要么不起）、层级 fairshare 队列与 HyperNode 拓扑感知[18][19]；它已经在往"AI 原生统一调度"扩，甚至自带推理栈 Kthena[20]。但——

- 你的目标是 **inference platform**，不是训练调度：推理是长驻 Deployment，gang scheduling 用不上；你真正要的是配额、优先级、抢占 → **Kueue** 是 kubernetes-sigs 原生路径，KServe / Kubeflow / Ray 的集成最短[9]。
- Volcano 会替换 kube-scheduler，运维面变大；Kueue 是"排队 + 准入"层，不动调度器。对一个要交付平台的 DevOps，后者更好讲、更好维护。
- 中国 AI 公司（华为云/字节/百度）与 HPC 场景 Volcano 权重明显高；北美 inference 岗几乎不考。

**反转条件：** 如果你转向训练平台岗，或投中国公司，再花 20–30h 学 Volcano。现在只需要 30 分钟，能说清 gang scheduling 与 fairshare 这两件事，就够面试用了。

## 边学边问的正确用法（AI 陪练协议）

可以让 AI 全程陪着，但有四条铁律，否则会得到"artifact 有、理解没有"的结果：

1. **先预测，再提问。** 每次问之前写下自己的猜测（"我猜 TTFT 变高是因为 KV cache 挤占了 batch 空间"）。没有预测的提问，学到的是答案，不是机制。
2. **不让 AI 代写你没读过的 manifest / 命令。** 抄来的 YAML 能跑通，但你讲不出为什么；面试三层追问一定塌。
3. **参数名与版本以官方文档为准。** AI 记的 flag 会过时——例：vLLM 的 `performance/optimization` 页已经 404，正确路径是 `configuration/optimization`[24]。每个新参数去 docs 核一遍，这个习惯本身就是面试加分项。
4. **时间配比 70/30。** 七成自己跑，三成问。问得太舒服 = 没学。

**日循环（每天 20 分钟成本）：** 开工前我先给"今天的假设 + 命令骨架" → 你跑，卡住就贴**原始报错**（不是转述） → 收工我用 3 个追问考你，答不出就是当天的洞 → 最后一天做 10 分钟模拟面试。

## 教程清单（按顺序做，带时间盒）

链接已逐个验证可访问（2026-11-20）。**顺序不要打乱**：先拿数字，再看平台化。

### vLLM（2.5 天）

| 顺序 | 资源 | 时间 | 拿走什么 |
|---|---|---|---|
| 1 | [Quickstart](https://docs.vllm.ai/en/latest/getting_started/quickstart.html) | 30 min | 起服务 + OpenAI 兼容端点，先能 `curl` 通 |
| 2 | [OpenAI-Compatible Server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html) | 20 min | 参数怎么传（`--max-num-seqs`、`--gpu-memory-utilization`），为调参做准备 |
| 3 | [Optimization & Tuning（stable 版）](https://docs.vllm.ai/en/stable/configuration/optimization.html)[24] | 60–90 min | preemption / KV cache 不足 / TP 的正确定义——**这是唯一必读长文** |
| 4 | [Benchmark Suites](https://docs.vllm.ai/en/latest/benchmarking/)[26] | 30 min | `vllm bench serve` 的正确用法，别自己写压测脚本 |
| 5 | [Fast & Efficient LLM Inference with vLLM](https://deeplearning.ai/courses/fast-and-efficient-llm-inference-with-vllm)[14] | 1h38（可选） | 量化 → 起服务 → GuideLLM 压测 → lm-eval 验质量，整条链路当手册翻 |
| 6 | [production-stack](https://docs.vllm.ai/projects/production-stack/en/latest/)[29] | D3 参考 | 在 K8s 上怎么摆 router + cache + servers；**不要在 D1 读它**，会给还没跑起来的人制造焦虑 |

### llm-d（1 天）

| 顺序 | 资源 | 时间 | 拿走什么 |
|---|---|---|---|
| 1 | [Quickstart](https://llm-d.ai/docs/getting-started/quickstart)[27] | 2h | 端到端跑通一次 optimized baseline（k3s + GPU 即可） |
| 2 | [Well-Lit Paths 索引](https://llm-d.ai/docs/well-lit-paths) | 10 min | 看清 10 条 path 分别解决什么，只挑一条 |
| 3 | [Precise Prefix-Cache Aware Routing](https://llm-d.ai/docs/well-lit-paths/foundations/precise-prefix-cache-routing)[28] | 3h | **D4 主菜**：EPP 怎么把请求送到"已经算过这段前缀"的副本 |
| 4 | [Optimized Baseline](https://llm-d.ai/docs/well-lit-paths/foundations/optimized-baseline) | 1h | quickstart 的深入版，理解默认参数从哪来 |
| 5 | [PD Disaggregation](https://llm-d.ai/docs/well-lit-paths/foundations/pd-disaggregation) | 30 min，**只看不跑** | 需要两个池才跑得动；你只要读懂"什么时候不划算" |
| 6 | [KAITO docs](https://kaito-project.github.io/kaito/docs/)[30] | 20 min | 你集群里已经装了 KAITO——知道它和 llm-d 的关系，面试能接住追问 |

> **D4 Lab 0（前置，可选）：** request-driven 0→1 用 KEDA HTTP Add-on，见 [`d4-llm-d-learning.md`](./d4-llm-d-learning.md) §4。它解决“0 副本时请求怎么进来”，llm-d 解决“多副本时按 prefix cache 怎么路由”；两者不是同一个问题。4h 不够时先砍 Lab 0，保 Lab 1（llm-d precise routing）。

> **B 线视角：** llm-d 不只是路由算法，也是一个平台组件。D4 除了 P99，还要带走：Gateway API/`InferencePool`/EPP 的部署与健康检查、路由指标（命中率/5xx）、故障模式（EPP 挂了、后端不健康）。产出见 §3 的 B 线学习表。

**不要做的三件事：** 不要一上来读 production-stack（给已有集群的人看的）；不要把 10 条 path 都看一遍（一条就够）；不要在 vLLM quickstart 没跑通时去碰 llm-d。

### 万卡集群：30 分钟概念，0 小时实操

「万卡集群管理」不是 inference platform 的进阶，是另一个职业方向——AI 数据中心 / 训练集群运维，核心是 IB/RoCE 组网、拓扑感知、慢节点与 NCCL 故障定位、checkpoint 与恢复、供电散热约束。市面上的"万卡"课程/实训卖的就是这些名词 + 架构图；真实岗位（智算中心运维）要求的是组网设计与硬件交付经验，通常 3–5 年 onsite。

**对你：不必要，也不可迁移。** 你在 AKS 上永远不会有万卡，面试也不会问一个 100 卡平台的候选人怎么管万卡。它唯一的价值是"听得懂别人说什么"，30 分钟够：

1. 拓扑：节点内 NVLink/NVSwitch，节点间 IB/RoCE，rail-optimized 组网，超节点（NVL72 / HyperNode）
2. 调度：gang scheduling、拓扑感知、队列与配额
3. 可靠性：慢节点检测、NCCL timeout、checkpoint 频率与恢复时间、故障域隔离
4. 成本：MFU（模型算力利用率）、空闲归因、供电与散热上限
5. 数据：并行文件系统（Lustre/WEKA）常是真正的瓶颈

**替代动作（价值高得多）：** 在 1–8 卡上人为制造故障并记录诊断路径——OOM、KV cache 打满、驱动升级后 pod 全挂、权重下载超时、节点被抢占。面试问的是"你见过什么坏、怎么定位"，这个问题在任何规模都成立，而万卡课程给不了你这种经历。

**如果你确实想要"老师"：** 不要买 100+ 学时的训练营。花 1–2 小时找一位在 neocloud 或大厂做 inference/AI infra 的人做 1:1——拆一份 JD、做一次 mock、问他团队真实的一天。单位小时回报比课程高一个数量级。

## 工具优先级表（遇到「要不要学 X」先查这张表）

**三问过滤法**，三问全过才动手：① 它在你目标岗位的 JD 里出现过吗？② 它能不能产出核心数字之一？③ 学它 ≤6 小时吗？

| 层级 | 工具 | 时间 | 为什么 / 边界 |
|---|---|---|---|
| **必修·下周就用** | **vLLM** | 2 天 | 所有数字的来源；`vllm serve` + `vllm bench serve` 就够开始 |
| | **k3s + Deployment + 权重缓存** | 1 天 | 你本来就熟，只是对象换成模型服务 |
| | **llm-d（一条 Well-Lit Path）** | 1 天 | 推理感知路由的唯一可讲证据；KServe 底层就是它[13] |
| **必修·W2–W9** | **Kueue** | 4h | 配额/排队/抢占的 k8s-sigs 原生答案[9] |
| | **KServe `LLMInferenceService`** | 6h | 只学 GenAI 这一半：KV-cache 路由、PD 分离、token 限流[4]；传统 `InferenceService` 知道存在即可 |
| | **DCGM + vLLM `/metrics` + OTel** | 4h | SLO 与成本归属的证据 |
| **对症选修** | **Langfuse（+ OTel GenAI）** | 3h | 只对 **agentic infra 线** 有用：trace、单任务 token 成本、eval 回归[21]。接在你自己的 Hermes agent 上，产出一个"成本可归因"的案例 |
| | **Argo Workflows** | 4h | 批处理 / eval 流水线的编排；与 Kueue 组合是标准答案（Kueue 有官方 Argo 集成文档）[22]。不做训练平台就别深挖 |
| | **Gateway API Inference Extension** | 3h | `InferencePool` / EPP 契约；学它是为了不被 llm-d 的实现细节绑死 |
| **B 线·Q3 可选** | **GPU Operator + MIG/time-slicing** | 6h | **B 线 P0 gap，A 线可跳过**：driver/toolkit/device plugin/DCGM/NFD 生命周期 + 共享模型；有 MIG 卡（A100/A30/H100/H200）做一次 MIG，没有就做 time-slicing[6][8] |
| **只需 30 分钟概念** | **DRA** | 0.5h | 设备申请协议：`DeviceClass` / `ResourceSlice` / `ResourceClaim`；知道它解决“按属性选卡、MIG、拓扑”，不解决配额/排队/抢占；D5 不包含 DRA |
| | **Volcano** | 0.5h | gang scheduling + 层级 fairshare；只在训练平台或中国公司高权重[18][19] |
| | **Kubeflow** | 0.5h | 今天的 Kubeflow ≈ Trainer + Pipelines + Katib + Model Registry，且 KFP v2 已与 Argo 解耦[23]；Katib 已被 Trainer 的 OptimizationJob 取代。**只要不说错话即可** |
| | **KubeRay / Ray** | 0.5h | 定位：Ray Serve 是通用分布式 serving，链多个模型/Python 复杂编排才用；单一 LLM 的推理栈现在是 vLLM + llm-d |
| | SGLang / Triton / Kthena / Slurm | 0 | 知道名字和适用边界即可 |
| **跳过** | 传统 `InferenceService` 深挖、Kubeflow Pipelines 实操、MLflow/W&B 深挖 | — | 除非你转 MLOps 线（供给最过剩那条） |

**Q2（约第 6 个月）就开始投，不要等"准备好"。** 面试是最便宜的缺口检测；拿到 JD 反馈再决定 Q3 补什么。

---

## 3.5 L4 去哪里租（2026-11 实际价格区间）

| 渠道 | 价格（USD/GPU-h） | 计费 | 适合你 | 注意 |
|---|---|---|---|---|
| **Vast.ai** | ~$0.10–0.45（常见 $0.25–0.35） | 按秒 | **首选**（你实际使用的平台） | 租 **on-demand**，不要 interruptible；挑 reliability ≥ 99%、`Max CUDA` ≥ 12.1、`inet down` ≥ 500 Mbps 的 host |
| **RunPod**（Community Cloud） | ~$0.44 | 按秒 | 备选，开箱有 vLLM 镜像 | Community 是第三方机房，偶有中断；重要实验用 Secure（~$0.59） |
| **Jarvislabs** | ~$0.44 按需 / ~$0.29 spot | 按小时 | 想省心、界面友好 | 区域在美/印，从卡尔加里延迟可接受 |
| **Google Cloud（Montréal）** | ~$0.62 | 按秒 | 数据要留在加拿大 | 需要 L4 quota，新项目可能要先申请 |
| **AWS（Montréal，g6 实例）** | 略高于 GCP | 按秒 | 同上 | 同样要 quota |
| **Azure** | — | — | ❌ 你的订阅里 T4/A100/H100/A10 配额全为 0，别折腾 | 配额审批要几天，不值得为一次实验等 |

**选它的理由（L4 的定位）：** 24GB 显存、72W、300GB/s 带宽——典型的"小模型高并发推理卡"。8B 模型 FP16 刚好塞得下（16GB 权重 + 少量 KV cache 紧张），8B AWQ（约 5–6GB）就很宽裕，能跑到有意义的并发。它**没有 NVLink**，不适合做 TP=2 的大模型实验——那一步临时开 2×L4 或 A100 40GB 一小时就够。

**不浪费钱的七条：**
1. 按秒计费；Vast 的 **Stop** 保留容器盘但继续收存储费、且不保证能重启，**Destroy** 才停止计费
2. 结果先 `scp` 回本地并 push，再决定 Stop（D2 在 24h 内）还是 Destroy（隔几天）；不要长期 Stop 着挂存储费
3. 直接用 `vllm/vllm-openai` 镜像，省掉装 CUDA/PyTorch 的两小时
4. 先开 1 小时验证能跑通，再决定要不要长开
5. 设一个 $15 预算上限，周末复盘花了多少、换到几个数字
6. 实验脚本全部进 git，机器随时可以删——**机器是租的，数字是你的**
7. **D3 的 k3s 要 VM/privileged**：你以前就在 Vast 的 RTX VM 上跑过 k8s，租的时候选同类 RTX VM/template；普通容器实例没有 systemd/cgroup，k3s 起不来。2026-11-23 实测 Vast 没有 L4 VM，24GB VM 主要是 3090/4090，约 `$0.41–0.48/h`

## 4.5 推理平台要不要 K8s（价值、替代方案、什么时候不要）

直说：**vLLM 本身不需要 K8s。** 它就是一个 Python 服务，装在哪都能跑；单模型、单机器、流量稳定的场景里，裸机 + systemd + 一个负载均衡器往往比 K8s **更快、更好调、故障面更小**。前沿实验室里也有大量推理服务直接跑在裸金属上，或者用 Slurm 分配节点。

**K8s 不是性能选择，是组织选择。** 它不提升单卡指标，只把"性能问题"换成"容量、隔离、交付问题"：单卡上只能调参，集群里才能加副本、改路由、隔离 noisy neighbor。D1 已经把单卡挖到头——c=16→64 吞吐只 +18%，TTFT P99 11.7s→55.5s，SLO goodput 0.077 req/s；再要容量只能横向，而横向就是编排问题。

**价值来自"有多个东西要协调"：**

| 维度 | 对应的选择 | 该维度 = 1 时消失的东西 |
|---|---|---|
| 副本数 | 放哪、流量给谁、怎么发布 | 调度、负载均衡、滚动更新、扩缩、装箱 |
| 异构 | 谁和谁不能同节点、谁更急 | 节点池/亲和性、优先级、装箱 |
| 团队数 | 谁可以用多少 | 配额、公平性、隔离、RBAC |

三个都是 1（1 卡、1 模型、1 团队）时，K8s 只是一个昂贵的进程管理器。但**不是严格乘法**：1 个团队、100 个同构副本时它仍然值（滚动更新、故障转移、装箱），只是调度/多租户那一半用不上。副本数是硬门槛，异构和团队数是加分项。

**它在这些条件下才开始赚回成本：**

1. **多模型、多团队**：几十个模型、十几个团队要自助上线，需要统一的部署契约、配额、隔离
2. **弹性**：Karpenter 按需拉 GPU 节点、CPU/GPU 混合池、低峰缩容
3. **生命周期自动化**：滚动更新、金丝雀、模型回滚、与模型注册表联动
4. **治理**：Kyverno 准入、AKV CSI 密钥、命名空间级成本归属、审计
5. **生态**：KServe / llm-d / Gateway API Inference Extension / Kueue 全部假设你在 K8s 上

**推理特有的四件事（通用 K8s 教程不会讲）：**

1. **扩缩信号不是 CPU。** GPU 推理的 CPU 占用低且不随负载线性变化，要看 `vllm:num_requests_waiting` / KV 使用率 / TTFT P99。
2. **冷启动让反应式扩缩经常来不及。** 模型加载 69s，再加镜像和权重落地（5.7GB AWQ / 16.4GB FP16），尖峰过去副本才 ready。所以真正的指标是"从 0 到 ready 多少秒"，不是"KEDA 能不能扩"。
3. **路由只在多副本时才存在。** llm-d EPP 的 prefix-cache-aware 路由前提是"多副本 + 网关"；单进程没有路由问题——D4 的收益完全建立在 D3 的集群之上。
4. **滚动更新会杀在途请求。** D1 的 c=64 最大延迟 179.3s、中位 123.4s，而默认 `terminationGracePeriodSeconds` 是 30s[54]、Deployment 默认 `maxUnavailable` 25%[55]；单副本时 25% 就是 100% 不可用。

**它不解决什么：**

| 不解决 | 原因 |
|---|---|
| 单卡 TTFT/TPOT | 同一张卡、同一 power limit，指标不变 |
| SLO 容量 | 0.077 req/s 是卡的上限，不是编排的上限 |
| 模型质量 | AWQ 掉点要靠质量门 |
| 冷启动物理下限 | 权重传输 + 69s 加载只能缓存，不能消除 |
| 排队本身 | 副本不够只是把队列挪个地方 |

反过来，这些情况下 K8s 是**负资产**：只有一个模型；只有一个团队；流量平稳不需要弹性；团队里没人愿意维护控制面。**而且 K8s ≠ 省钱**：LLM 的 scale-to-zero 一次冷启动几十秒到几分钟，只适合低频/可容忍延迟的负载；稳态省的是装箱率和闲置，不是靠缩到 0。

**替代方案：按层看，别把框架当编排。**

| 层 | 解决什么 | 候选 |
|---|---|---|
| 1 进程管理 | 活着、重启 | `systemd`、`docker`、`compose` |
| 2 资源编排 | 放哪、分多少 | **K8s**、Nomad、Slurm、ECS、Ray |
| 3 推理专用 | 路由、扩缩、模型生命周期 | KServe、llm-d、Ray Serve LLM、BentoML、Dynamo/NIM |
| 4 托管/无服务器 | 外包前两层 | SageMaker、Vertex AI、Azure ML、Modal、RunPod、Baseten |

K8s 只在第 2 层；第 3 层大多是"K8s 之上"，不是替代。

| 编排方案 | 复杂度 | 推理生态 | 适合 / 代价 |
|---|---|---|---|
| **K8s** | 高 | 最强（KEDA / Kueue / Gateway API Inference Extension / llm-d / KServe） | 多云、多团队、要生态；代价是控制面 + 认知成本 |
| **Nomad** | 低（单二进制） | 弱，无 KEDA/Kueue 等价物 | 混合负载、小团队；路由/配额/按队列扩缩全自己写 |
| **Slurm** | 中 | 弱，抽象是"作业"不是"长驻服务" | HPC、科研、离线批推理；滚动更新/健康检查自己补 |
| **ECS** | 低（AWS 托管） | 弱 | 全 AWS、不想碰 K8s；锁 AWS |
| **Ray** | 中 | 中（Ray Serve LLM） | Python 原生流水线；多租户弱，底下仍要 VM/K8s |

第 4 层把前两层外包，代价是：冷启动几十秒到几分钟（"无服务器"在 LLM 上不成立）、稳态单价通常比自建贵、批处理/量化/KV 策略不可控。

| 场景 | 建议 |
|---|---|
| 1 卡、1 模型、作品集/D1 | `systemd` + `docker` + `nginx` |
| 2–10 卡、1 团队、要学平台 | K8s（生态值得付这个复杂度） |
| 多团队、要配额和优先级 | K8s + Kueue |
| 全 AWS、不想养控制面 | ECS |
| 混合负载（推理 + 批处理 + 定时任务）、小团队 | Nomad |
| HPC/科研、离线批推理 | Slurm |
| 流量稀疏、不想运维 | Modal / RunPod / 托管端点 |
| 稳态高利用率、要压成本 | 自建（K8s 或裸机） |

选 Nomad / ECS / Slurm 等于放弃 D4/D5 依赖的那一层（llm-d、Kueue、Gateway API Inference Extension），全部自己实现。

**D3 只测三个数**（"能部署"没有区分度）：冷启动（镜像已缓存但权重现拉 vs 节点本地缓存，差多少秒）、扩容曲线（KEDA 1→N 期间 P99 是先恶化还是立刻变好）、驱逐行为（删一个副本时在途请求的命运，用 179s 最大延迟反推 grace period）。

**K8s 带来的开销到底在哪（面试常被追问）：** 不是"容器慢"，而是 ① 多一跳网络（CNI / kube-proxy / 网关 TLS）；② 镜像拉取与权重加载让冷启动变长；③ 调度器排队；④ cgroup CPU 限制可能掐住 tokenizer 线程；⑤ device plugin 只能整数分配。

**对应的消除手段：** `hostNetwork: true`（绕过一层 NAT）、Gateway API 直连 Pod IP、权重预加载（node-local cache / Model Streamer）、CPU limit 设高或不设、用 DRA/KAI/HAMi 解决分数卡。

**面试标准答案（一句话 + 一个数字）：** "单模型单机时裸机更快，K8s 的价值在多模型、多租户和弹性；我们量过，走 Service 比 hostNetwork 多约 __ms 的 P99，所以推理热路径走 hostNetwork + 网关直连。"

## 5. 四个核心数字 + 两个对比（A 线版）+ 三个 B 线数

核心 4 个（缺一个 writeup 不成立）：

1. TTFT P50/P95/P99 @ c=1/16/64（c=4 可选）：____ ms
2. output tok/s + goodput @ SLO：____ tok/s / ____ req/s
3. TPOT/ITL P95：____ ms
4. $/1M output tokens（含 GPU 闲置摊销）：$____

两个对比（加分，不替代核心）：

5. 冷启动：____ s（node-local cache）/ ____ s（initContainer 现下）
6. 质量/路由：AWQ vs FP16 质量 delta ____；prefix-cache 路由 P99 改善 ____%

**B 线三个数（单独报，不要混进上面的 A 线核心）：**

1. 冷启动：cold ____ s / warm ____ s（D3，分阶段见 `d3-k8s-vllm-learning.md` §7）。
2. 多租户配额：`ClusterQueue` 配额 ____ GPU，拒绝 ____ 次（D5）。
3. 成本归属：team-a $____/1M output tokens，team-b $____/1M；差额来自 ____（Q2 chargeback）。

**方法学必须一起写：** 样本数、warmup、重复次数、开环/闭环、SLO 定义、GPU 单价/利用率、货币（CAD/USD）。没有这些，数字不可复核。

---

## 6. 十道必答题 + 四道 llm-d 题 + 四道 B 线题

1. device plugin 为什么不能申请"半张卡"；MIG / time-slicing / MPS / DRA 各解决什么、代价是什么[5][8]
2. 8B 模型 FP16 约 16GB 权重（AWQ 约 5.7GB），怎么让新 pod 20 秒内起来；四种方案代价[5]
3. 为什么 GPU inference 不该用 CPU 型 HPA，该用什么信号
4. chat 场景能不能 scale-to-zero，怎么折中[5]
5. P99 TTFT 高但 GPU util 只有 40%，怎么查
6. 一个租户的长 prompt 拖垮整个 endpoint，怎么办[5]
7. prefill/decode 为什么要分离、什么规模才值得[4][13]
8. TP / PP / EP 各自什么时候用，什么时候一定别用
9. PagedAttention 解决什么；KV cache 不足时 vLLM preempt 并重算，你付什么代价[24]
10. 怎么证明平台"没被滥用"：审计、配额、成本归属

**llm-d 四问（能答这四题，llm-d 就算学到位）**
- EPP 干什么？它凭什么比 round-robin 好？（预测/命中 KV cache 的位置，把请求送到"已经算过这段前缀"的副本）
- `InferencePool` 这个契约解决什么问题？为什么不直接用 Service？
- PD 分离在什么情况下**不划算**？（低并发、模型小、网络带宽不够搬 KV、集群没有第二个 GPU 池——大多数团队死在这条）
- wide EP 解决什么？（MoE 模型的专家并行，单机放不下时跨节点切专家）

**B 线四问（D3/D5，答案见 `d3-k8s-vllm-learning.md` §12）：**
- GPU 平台怎么做多租户隔离？namespace/RBAC、ResourceQuota、Kueue、Kyverno 各管什么？
- 模型版本回滚怎么做？hostPath/local PV 怎么避免回滚到旧权重？
- GPU 容量规划为什么不能只看 util？该看哪些指标？
- chargeback 按 GPU 小时还是按 token？两种口径的差额是什么？

### A 线源码阅读（每周 1h，不要求写 kernel）

- **vLLM**：scheduler、KV cache manager、prefix caching、chunked prefill。目标：画出一次请求从 HTTP 到 scheduler 到 GPU 的路径。
- **llm-d**：EPP、InferencePool、prefix-cache routing。目标：说清“为什么不是 round-robin”，以及命中率怎么测。
- 每读一块，写 5 行笔记 + 一个能被追问的问题；不要只收藏链接。

---

## 7. 怎么讲你的 DevOps 背景（不是道歉，是卖点）

> 我一直在做多租户平台的可靠性与治理：策略即代码、GitOps 收敛、密钥与身份、升级与回滚。现在我把同一套方法用到 GPU 上——配额、优先级、抢占、成本归属，以及模型服务的 SLO。**原型能跑的人很多，能把它做成 7×24 有人负责的服务的人很少，那是我的位置。**

证据三件套：Kyverno 收敛 runbook、GPU 配额策略集、4 个核心性能数字 + 2 个对比。

---

## 8. 不要做

- ❌ 20h 以上的课程 / 通识认证（NCA-AIIO 那 $125 例外，它只花 1 小时）
- ❌ 在共享 UAT 集群做实验：污染环境 + 触发 Coder→Reviewer SOP + 花公司钱
- ❌ 从零写 RAG chatbot
- ❌ 只有 hello world 的 KServe / vLLM demo
- ❌ 先补 ML 理论再碰 GPU（顺序反了）
- ❌ 等 CKIE 考纲出来再开始学（2027 出考纲，你现在就该会）
- ❌ 把休假排满不留休息日
- ❌ A-only：A 线岗位少，B 线是就业基本盘；不要拒绝 AI 公司的平台岗
- ❌ 把 Data Center Technician / 纯 MLOps 当 A 线入口；它们可以糊口，但不积累推理性能证据
- ❌ 没有 SLO/样本量就报 P99；用 random 数据测 prefix caching
- ❌ 只报全集群 `$/1M tokens`，不报 namespace/team 归属和闲置摊销
- ❌ 在 PR 阶段假设美国 remote 随便投；先确认身份/EOR/岗位所在地

---

## 9. 如果只有 90 分钟

租一张 L4 → 按 `d1-vllm-baseline-runbook.md` 起 8B 量化模型 → 16 并发压一次 → 把 **TTFT P99** 和 **output tok/s** 抄进 README。

两个数字 > 四十小时视频。有了第一个数字，后面几个季度才有参照系。

---

## Sources

[3] https://job-boards.greenhouse.io/lilasciences/jobs/4248032009 — Staff/Principal DevOps Engineer, AI Inference — Lila Sciences
[4] https://kserve.github.io/website/blog/kserve-0.17-release — Announcing KServe v0.17 — LLMInferenceService
[5] https://cloudsoftsol.com/blog/kubernetes-for-ai-interview-questions — Kubernetes for AI Interview Questions 2026: 55 Q&A
[6] https://kubernetes.io/docs/concepts/resource-management/dynamic-resource-allocation — Dynamic Resource Allocation — Kubernetes docs
[8] https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-sharing.html — Time-Slicing GPUs in Kubernetes — NVIDIA GPU Operator
[9] https://kueue.sigs.k8s.io/docs — Kueue Documentation
[10] https://inferenceinterviews.com/guide/inference-engineer-salary — Inference engineer salary in 2026: posted bands
[11] https://www.deeprec.ai/ai-infrastructure-us-salary-guide — AI Infrastructure US Salary Guide — DeepRec.ai
[12] https://www.inferencejobs.com/salaries/titles/platform-engineer — Platform Engineer Salaries — Inference Jobs
[13] https://llm-d.ai/docs — llm-d Documentation — Well-Lit Paths
[14] https://deeplearning.ai/courses/fast-and-efficient-llm-inference-with-vllm — Fast & Efficient LLM Inference with vLLM — DeepLearning.AI
[15] https://deeplearning.ai/courses/efficiently-serving-llms — Efficiently Serving LLMs — DeepLearning.AI
[16] https://www.nvidia.com/en-us/learn/certification/ai-infrastructure-operations-associate — NVIDIA-Certified Associate: AI Infrastructure and Operations (NCA-AIIO)
[17] https://www.cncf.io/announcements/2026/11/10/cncf-launches-certified-kubernetes-network-engineer-certification-ckne-to-advance-production-ready-networking-skills-for-ai-era — CNCF launches CKNE; announces KAIA and CKIE for 2027
[18] https://www.cncf.io/projects/volcano — Volcano — CNCF project page (Incubating since 2022)
[19] https://www.cncf.io/blog/2026/10/28/volcano-v1-16-released-namespacequeue-fairshare-and-a-broader-hypernode-ecosystem — Volcano v1.16: NamespaceQueue, fairshare, HyperNode
[20] https://cncf.io/blog/2026/03/23/beyond-batch-volcano-evolves-into-the-ai-native-unified-scheduling-platform — Beyond Batch: Volcano Evolves into AI-Native Unified Scheduling
[21] https://langfuse.com/docs — Langfuse — open-source AI engineering / LLM observability platform
[22] https://argo-workflows.readthedocs.io/en/latest — Argo Workflows documentation
[23] https://www.kubeflow.org/docs/components/pipelines/user-guides/migration — Kubeflow Pipelines v2 migration (decoupled from Argo Workflows)
[24] https://docs.vllm.ai/en/stable/configuration/optimization.html — Optimization and Tuning — vLLM (stable)
[26] https://docs.vllm.ai/en/latest/benchmarking — vLLM Benchmark Suites
[27] https://llm-d.ai/docs/getting-started/quickstart — llm-d Quickstart
[28] https://llm-d.ai/docs/well-lit-paths/foundations/precise-prefix-cache-routing — llm-d Well-Lit Path: Precise Prefix-Cache Aware Routing
[29] https://docs.vllm.ai/projects/production-stack/en/latest — vLLM production-stack
[30] https://kaito-project.github.io/kaito/docs — KAITO documentation
[31] https://www.pin.com/blog/tech-job-market-report — Tech Job Market 2026: Layoffs, AI Salaries, and Hiring Data
[32] https://newsletter.pragmaticengineer.com/p/state-of-the-job-market-2026 — State of the software engineering job market in 2026 — Pragmatic Engineer
[33] https://hiringlab.indeed.com/en-ca/2026/09/23/the-canadian-data-centre-build-out — The Canadian Data Centre Build-Out — Indeed Hiring Lab
[34] https://metix.ai/reports/mapping/nvidia-ai-infrastructure-talent-race-2026 — AI Infra Talent Race 2026 — Metix AI
[35] https://fortune.com/2026/11/17/ai-bubble-popping-bofa-fund-manager-survey-largest-cut-since-2006 — BofA fund manager survey: largest tech cut since 2006 — Fortune
[36] https://www.inferencejobs.com/salaries/titles/inference-engineer — Inference Engineer salaries & top skills — Inference Jobs
[37] https://jobsbylevel.com/blog/inference-engineer-jobs-llm-prices — Inference engineer jobs as LLM prices fall (Oct 2026)
[38] https://github.com/ld-singh/ai-factory-ops-lab — ai-factory-ops-lab: hands-on GPU/HPC K8s operations lab (free)
[39] https://learnkube.com/gpu-kubernetes-training — Building GPU Platforms on Kubernetes — LearnKube
[40] https://kubezilla.io/kubernetes-gpu-guide — Kubernetes GPU Guide 2026: Scheduling, Sharing, Monitoring
[41] https://training.linuxfoundation.org/kaia-ckie-notify-me — KAIA & CKIE — notify me / SME call (Linux Foundation)
[42] https://nvidia.com/en-us/learn/certification/ai-operations-professional — NVIDIA-Certified Professional: AI Operations (NCP-AIOL)
[43] https://dam-cdn.nvd.orangelogic.com/AssetLink/ub08c12vdc5l53ksln5d4dlpt3346464.pdf — NCP-AI Operations Exam Study Guide (official, with weights)
[44] https://jobs.lever.co/eleks/ce6ed932-5afa-460d-90fd-1aff7e7cf51a — Eleks — Infrastructure/GPU Cluster/Platform Operations Lead (Remote Canada, Alberta preferred)
[45] https://geosoftware.bamboohr.com/careers/90 — GeoSoftware — Senior HPC and Platform Engineer (Calgary, hybrid)
[46] https://www.jobs.ca/groq-94cbc6bcd84a/jobs/data-center-technician-calgary-ab-65643ce30a3c — Groq — Data Center Technician, Calgary AB
[47] https://datacenters.atmeta.com/2026/07/hello-sturgeon-county — Meta — Sturgeon County data centre (1GW)
[48] https://developer.nvidia.com/blog/nvidia-runai-is-now-open-source-as-part-of-nvidia-dsx-ai-factory-platform — NVIDIA Run:ai Is Now Open Source (NVIDIA Technical Blog, 2026-10-13)
[49] https://jobiba.com/job/senior-staff-software-engineer-back-end-inference-cohere-c7b0d6ec — Cohere — Senior/Staff Software Engineer (Back-End), Inference (aggregator; verify official careers page)
[50] https://www.shopify.com/careers/senior-staff-engineer-ml-inference_59a0b690-182f-465f-9059-b6ce3874fb62 — Shopify — Senior Staff Engineer, ML Inference (Remote Americas)
[51] https://jobs.ashbyhq.com/cerebras/ef15b7be-2fa3-4343-81aa-47ef65171af0/application — Cerebras — Staff Software Engineer, Inference Platform (Toronto)
[52] https://docs.vllm.ai/en/latest/benchmarking/cli/ — vLLM Benchmark CLI (per-request metrics, percentiles, ignore-eos)
[53] https://docs.vllm.ai/en/latest/cli/serve/ — vLLM serve CLI
[54] https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/ — Pod Lifecycle: terminationGracePeriodSeconds (默认 30s) — Kubernetes docs
[55] https://kubernetes.io/docs/concepts/workloads/controllers/deployment/ — Deployments: rolling update maxUnavailable / maxSurge 默认 25% — Kubernetes docs
[56] https://docs.vllm.ai/en/stable/design/metrics/ — vLLM Metrics: prompt/generation token counters, request success, model_name label
