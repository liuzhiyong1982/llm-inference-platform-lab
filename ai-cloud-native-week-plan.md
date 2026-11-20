# 从 DevOps 到 AI Infra：高薪路径 + 休假周执行表

> 2026-11-20 · 为 Andrew 定制 · 目标函数：**薪资**，不是"学会"
> 本文是唯一版本（替代更早的一周计划与 12 周版），后续调整都改这里。

---

## 0. 先校准目标：高薪是「公司类别」的函数，不是「技能数量」的函数

美国 AI 基础设施岗位的 base 区间（同一 title 不同公司差 2 倍以上）：

| 方向 | IC | Senior | Senior Staff | 出处 |
|---|---|---|---|---|
| **ML Performance** / Kernel | $165–240K | $230–325K | $375–560K | DeepRec 2026 薪资指南（SF）[11] |
| **Inference** | $160–230K | $225–315K | $360–530K | 同上[11] |
| ML Infrastructure / ML Platform | $150–220K | $210–295K | $340–490K | 同上[11] |
| MLOps | $135–195K | $185–260K | $300–425K | 同上[11] |

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

## 1. 证书：该考的其实只有 1–2 个

先说清作用边界：**证书过 ATS/HR 的筛选，不过技术面。** 它的价值是"关键词匹配 + 低成本完成感"，不是能力证明。所以策略是**用最少小时拿到关键词**，绝不能用休假周的产出时间换。

| 证书 | 价格 / 时长 | 对你 | 结论 |
|---|---|---|---|
| **NVIDIA NCA-AIIO**（AI Infrastructure and Operations, Associate） | **$125 / 60 分钟 / 50 题 / 远程监考 / 有效期 2 年**[16] | 名字里就有 "AI Infrastructure"，ATS 直接命中；内容补的是硬件层认知（GPU 架构、NVLink、InfiniBand、存储、散热），面试聊 DGX/集群时不再露怯 | ✅ **就考这个**。7.5h 课程 + 60 分钟考试，$125 是这周最便宜的确定性 |
| **NVIDIA NCP-AII**（Professional, AI Infrastructure） | $400 / 2 小时，考部署、配置、验证高级 NVIDIA 基础设施 | 偏 DGX / 硬件运维，你没有这些设备 | ❌ 暂时不考 |
| **CKA**（Certified Kubernetes Administrator） | ~$445 / 2 小时 | 若有正式认证缺口，它是平台半边的门槛；但你已有 5 年真实 AKS 平台经验，边际价值低 | ⚠️ 只有在你连一个 K8s 认证都没有、且目标公司 HR 明确要求时才考 |
| **CKNE**（Certified Kubernetes Network Engineer） | 2026-11 刚发布，可考 | AI 集群的 RDMA/RoCE/InfiniBand 是热点，但方向偏网络 | 🔶 备选，等他明确投"AI 集群网络"岗再考 |
| **KAIA（Kubernetes AI Associate）/ CKIE（Certified Kubernetes Inference Engineer）** | **2027 年推出，尚未公布考纲、价格、日期**[17] | **这是你的时间窗口**：CNCF 把"Kubernetes 推理工程"正式确认为一个独立职业方向。等考纲发布时，你已经有一年的一手实验——你就是第一批 | 🎯 **按它的方向准备，不按它的日期焦虑** |

**最关键的一条：CKIE 的存在本身就是一个市场信号。** CNCF 在 2026-11-10 宣布要把"Certified Kubernetes Inference Engineer"做成独立认证[17]——说明这类岗位的职责边界已经稳定到可以出考纲了。你 12 周路线图里练的东西（GPU 调度、权重分发、扩缩、路由、配额），正是那个考纲会覆盖的东西。**2027 年考纲出来时，你不是去"学"，是去"对答案"。**

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

**放在 14 周计划的 W4–W5**，和 Kueue 同一周学——一次学两个，面试时"Kueue 和 KAI 怎么选"是极好的加分题。

#### 附：GPU 共享五种方案（面试原题，一张表答完）

| 方案 | 隔离性 | 显存切分 | 硬件要求 | 典型场景 |
|---|---|---|---|---|
| **MIG** | 硬件级（显存/故障隔离） | 固定档位（如 1g.5gb），档位不能自定义 | Ampere 及以后，部分卡不支持 | 生产多租户，要求强隔离 |
| **Time-slicing** | 无隔离，仅时间片轮转 | 不切显存，各负载都看到整卡 | 任意 NVIDIA 卡 | 开发/测试、超卖提利用率 |
| **HAMi**（CNCF Incubating，v2.11） | 软件限制（libvgpu 拦截 CUDA 调用） | **任意大小**（可以切 12GB 这种 MIG 切不出来的规格） | 异构（NVIDIA/AMD/昇腾等），不依赖 MIG | 国内/政企、异构算力、需要非标准切分 |
| **KAI GPU Fractioning**（NVIDIA 开源，2026-10） | 软件 + CUDA 原生显存强制 | 分数卡 | NVIDIA，配合较新 CUDA | NVIDIA 生态、想要比 time-slicing 更强的限制 |
| **DRA** | 由 device 驱动决定 | 取决于驱动（DRA 只负责申请与分配契约） | K8s ≥1.35（你集群 1.36 可用） | 新集群、结构化设备申请、未来默认 |

**一句话记住：** MIG 是硬件切、档位固定；time-slicing 是排队用整卡、没有隔离；HAMi 和 KAI Fractioning 是软件切、能切任意大小但没有硬件级故障隔离；DRA 是"怎么向 K8s 申请设备"的协议，不是切分方案本身——它常和上面几个一起用。

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

**两个现实障碍：** ① 三个 lab 必须在 BCM 环境里做，没有 NVIDIA 硬件就只能靠官方课程提供的 lab 环境练，风险高；② $500 + 约 20–30 小时，等于你 12 周预算的三分之一。

**决策建议：** 先回答"我到底投 neocloud/数据中心，还是 AI 公司的平台岗"，再决定要不要花这 $500。如果投前者，这张证优先级高于 CKIE；如果投后者，把这笔钱换成 30 小时 GPU 租用 + 六个数字，回报高得多。

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

但 CKIE 的现实约束要说清：2027 年推出，**考纲、价格、日期全都未公布**[17]。也就是说现在只能"按领域准备"，不能"按考纲准备"。好消息是这两件事在你的 12 周计划里是同一件事。

**今天就能做的三件事**

1. **订阅发布通知**（30 秒）：[KAIA & CKIE Notify Me](https://training.linuxfoundation.org/kaia-ckie-notify-me/)[41]
2. **申请当 SME（出题专家）**：同一页面在招募 subject matter experts 参与"define, write, and review"两份考卷[41]。这是最有杠杆的一步——报名成本为零，一旦入选，你会在考纲公开前就看到它考什么，简历上还会多一行"参与 CNCF 认证出题"。即使因为推理经验还不满被拒，也不损失什么。
3. **把 12 周计划标注成"CKIE 预科"**：考纲出来后你只需要"对答案"，不需要"从头学"。

**最终认证组合：** 现在可选 NCA-AIIO（$125，补硬件盲区）→ 2027 考 CKIE（目标证）→ 跳过 KAIA（Associate 级，对你太浅）与 CKNE（网络方向）→ CKA 仅在你连一个 K8s 认证都没有时补。

## 1.6 阿尔伯塔本地入口（真实 JD，不是推断）

你的观察是对的：**没有一份 JD 写着"要求 NCP-AIO"**。证书在加拿大几乎不出现在招聘要求里。但阿尔伯塔有一批岗位在真实使用 GPU 集群 / Slurm，而且其中两份几乎是照你的背景写的：

| 公司 | 岗位 | 关键要求 | 你的差距 |
|---|---|---|---|
| **Eleks** | Infrastructure/GPU Cluster/Platform Operations Lead（Remote Canada，**明确偏好 Calgary/Edmonton**）[44] | 8+ 年基础设施/平台运维、**GPU 集群管理**、强 K8s、NVIDIA GPU/CUDA 生态、Azure/AWS/GCP、存储网络 HPC、Terraform、运维领导力 | **只差"GPU 集群"这一条**——正是 12 周计划要做的；零证书要求 |
| **GeoSoftware** | Senior HPC and Platform Engineer（Calgary，hybrid，2026-11-02 发布）[45] | 同一套科学计算负载跑在 workstation / **Slurm 或 PBS** / Databricks / 云 batch 之上；checkpoint-restart；构建与交付流水线 | **Slurm/PBS**——你 BCM 已装，缺的只是 Slurm |
| **Groq** | Data Center Technician（Calgary，onsite，2026-10-09）[46] | 数据中心现场硬件运维，2+ 年 | 层级低于你，说明本地已有 AI 芯片公司在招人 |
| **Meta / Bell AI Fabric** | Sturgeon County 1GW 数据中心（2026-07 开工，投资超 CAD$13B）[47]；Bell 七个高密度数据中心 | 建设期为主，运营岗 2027–2028 释放 | 时间差正好：那时你已有 1–2 年 GPU 平台经验 |

**结论：本地不缺"要证书的公司"，缺的是"要 GPU 集群 + Slurm 经验的人"。** 证书不给你面试，Slurm 和 GPU 集群给你面试。

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
2. **能按模块买吗？总时长 ≤15 小时吗？** 几十小时的体系课会直接吃掉你 12 周预算。
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
| 休假周产出 | 六个数字 + 一张对比图 | **repo + 第一个数字（baseline）** |
| 后续节奏 | — | 每周 6h（两晚 + 周六上午），14 周 |
| 适合 | 在职但想三个月内换 | 在职、想 6 个月内换到更好的 |

**为什么推荐点火版：** 你有工作，休假烧成第二个工作周，第二周就会崩。而"拿到第一个数字 + 把 repo 建起来"这个动作，已经把最难的部分（启动惯性）解决了；剩下的靠每周 6 小时滚 14 周。

**防拖三条机制（比计划本身重要）：**
1. **固定时段**：周二、周四 21:00–22:30，周六 09:00–12:00。写进日历，不靠意志力。
2. **每两周一个可见产出**：repo 里必须多一个能跑的东西或一组数字。没有产出的一周，下周一补，不许顺延。
3. **每四周一个 gate**：还在学吗？有产出吗？要不要换方向？——允许停，但要在 gate 上停，不许无声消失。

## 3. 休假周执行表（冲刺版；点火版只做 D1–D2）

> **开工前（这个周末，6–8 小时）：先把 Slurm 做掉。**
> 它不需要 GPU、不用等租卡、BCM 你已经装好，而且它是 GeoSoftware 那类本地岗位的入场词、也是 NCP-AIO 三个 lab 里的两个。放在休假日之前做完，休假整周就能专心做 inference——两件事不在同一周抢时间。

**一周的唯一目标：一个 repo、六个数字、一张 llm-d 对比图、一次 10 分钟讲解。** 不是"学完什么"。

预算：GPU 租用 ≈ $10–15（按秒计费，单卡 L4/A10；Day 4 临时开 2 卡约 1 小时）。Azure 侧配额为 0，不要等审批。

| 天 | 时长 | 干什么 | 当天必须落地 |
|---|---|---|---|
| **D1** | 4h | 租 L4；`vllm serve` 8B 量化模型；跑并发 1/4/16/64 的压测；同时把 DL.AI 那门 vLLM 短课当手册过一遍[14] | baseline 表：TTFT P50/P95/P99、output tok/s、GPU util |
| **D2** | 3h | 三个旋钮逐个开：prefix caching、chunked prefill、`max-num-seqs`；AWQ vs FP16 对照；读 KV cache / batching 那两节[15] | 一张对照表 + 一句话结论（吞吐 +x%，TTFT −y%） |
| **D3** | 3h | k3s + vLLM Deployment；**权重分发实测**：initContainer 现下 vs node-local 缓存，测冷启动秒数；KEDA 按 `vllm:num_requests_waiting` 扩缩 | 冷启动对比（秒）+ 扩容曲线 |
| **D4** | 4h | **llm-d 日**：租 2×L4，按 Well-Lit Path 跑 `precise-prefix-cache-routing`（或 optimized baseline）[13]；同一批"共享长前缀"的请求，对比普通 round-robin vs EPP 路由的 P99 | 一张 P99 对比图 + 命中率数字 |
| **D5** | 3h | Kueue `ClusterQueue` 两团队配额[9] + Kyverno 强制 GPU workload 带 priorityClass / quota label；跑"抢卡"演示 | 两条被拒 manifest 日志（这是你独有的交叉点） |
| **D6** | 3h | 1500 字 writeup + 10 分钟讲稿 + 简历两行；**晚上**报名 NCA-AIIO（$125）[16]，把考试排在下一周 | 可发出去的链接 + 已预约考试 |
| **D7** | — | 休息。唯一动作：列 10 家目标公司 + 抄 3 个真实 JD。不碰终端 | 目标公司清单 |

**验收（不达标就是失败，不许自我安慰）**
- [ ] `make bench` 一键复现
- [ ] 3 张图：throughput vs concurrency / TTFT P99 / llm-d 路由前后 P99
- [ ] 2 条策略拒绝日志（Kyverno + Kueue）
- [ ] 冷启动：带缓存 ____ s vs 不带 ____ s
- [ ] 6 个数字全部填上
- [ ] 10 分钟讲得完，且能被追问 3 层

---

## 4. 12 周路线（休假周之后的节奏：每周 8h = 周二/周四晚各 2h + 周六 4h）

| 阶段 | 周 | 主题 | 验收 |
|---|---|---|---|
| Phase 1 | W2–W5 | GPU 资源语义：time-slicing vs MIG[8] → DRA（v1.35 起 Stable，你集群 1.36 可用）[6] → Kueue 配额与抢占[9] → Kyverno 准入即代码 | 4 份策略 + 一张隔离性对比表 |
| Phase 2 | W6–W9 | serving 平台化：W6 KServe `LLMInferenceService` 与它生成的资源关系[4]；**W7 llm-d 的四个概念**（EPP / InferencePool 契约 / prefix-cache 路由 / PD 分离什么时候不划算）[13]；W8 权重分发四种方案 + 冷启动矩阵；W9 DCGM + vLLM metrics + SLO + $/1M tokens 归属 | 一条 well-lit path 跑通 + 一张 SLO 面板 |
| Phase 3 | W10–W12 | 面试化：六个数字定稿、10 分钟讲解录音、10 道必答题自测、把 `uat-mobility-aks-01` 写成 case study、3 个 JD 逐条映射、开始投 | 答上 ≥8 题 + 简历 v2 + 5 个已投 |

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

**三问过滤法**，三问全过才动手：① 它在你目标岗位的 JD 里出现过吗？② 它能不能产出六个数字之一？③ 学它 ≤6 小时吗？

| 层级 | 工具 | 时间 | 为什么 / 边界 |
|---|---|---|---|
| **必修·下周就用** | **vLLM** | 2 天 | 所有数字的来源；`vllm serve` + `vllm bench serve` 就够开始 |
| | **k3s + Deployment + 权重缓存** | 1 天 | 你本来就熟，只是对象换成模型服务 |
| | **llm-d（一条 Well-Lit Path）** | 1 天 | 推理感知路由的唯一可讲证据；KServe 底层就是它[13] |
| **必修·W2–W9** | **Kueue** | 4h | 配额/排队/抢占的 k8s-sigs 原生答案[9] |
| | **DRA + NVIDIA GPU Operator** | 6h | 资源语义 + 共享模型（MIG/time-slicing）[6][8] |
| | **KServe `LLMInferenceService`** | 6h | 只学 GenAI 这一半：KV-cache 路由、PD 分离、token 限流[4]；传统 `InferenceService` 知道存在即可 |
| | **DCGM + vLLM `/metrics` + OTel** | 4h | SLO 与成本归属的证据 |
| **对症选修** | **Langfuse（+ OTel GenAI）** | 3h | 只对 **agentic infra 线** 有用：trace、单任务 token 成本、eval 回归[21]。接在你自己的 Hermes agent 上，产出一个"成本可归因"的案例 |
| | **Argo Workflows** | 4h | 批处理 / eval 流水线的编排；与 Kueue 组合是标准答案（Kueue 有官方 Argo 集成文档）[22]。不做训练平台就别深挖 |
| | **Gateway API Inference Extension** | 3h | `InferencePool` / EPP 契约；学它是为了不被 llm-d 的实现细节绑死 |
| **只需 30 分钟概念** | **Volcano** | 0.5h | gang scheduling + 层级 fairshare；只在训练平台或中国公司高权重[18][19] |
| | **Kubeflow** | 0.5h | 今天的 Kubeflow ≈ Trainer + Pipelines + Katib + Model Registry，且 KFP v2 已与 Argo 解耦[23]；Katib 已被 Trainer 的 OptimizationJob 取代。**只要不说错话即可** |
| | **KubeRay / Ray** | 0.5h | 定位：Ray Serve 是通用分布式 serving，链多个模型/Python 复杂编排才用；单一 LLM 的推理栈现在是 vLLM + llm-d |
| | SGLang / Triton / Kthena / Slurm | 0 | 知道名字和适用边界即可 |
| **跳过** | 传统 `InferenceService` 深挖、Kubeflow Pipelines 实操、MLflow/W&B 深挖 | — | 除非你转 MLOps 线（供给最过剩那条） |

**W10 就开始投，不要等"准备好"。** 面试是最便宜的缺口检测。

---

## 3.5 L4 去哪里租（2026-11 实际价格区间）

| 渠道 | 价格（USD/GPU-h） | 计费 | 适合你 | 注意 |
|---|---|---|---|---|
| **RunPod**（Community Cloud） | ~$0.44 | 按秒 | **首选**，开箱有 vLLM 镜像，无配额审批 | Community 是第三方机房，偶有中断；重要实验用 Secure（~$0.59） |
| **Vast.ai** | ~$0.36 起 | 按秒 | 最便宜 | 机器质量参差，挑信誉高的 host，先跑 10 分钟验证 |
| **Jarvislabs** | ~$0.44 按需 / ~$0.29 spot | 按小时 | 想省心、界面友好 | 区域在美/印，从卡尔加里延迟可接受 |
| **Google Cloud（Montréal）** | ~$0.62 | 按秒 | 数据要留在加拿大 | 需要 L4 quota，新项目可能要先申请 |
| **AWS（Montréal，g6 实例）** | 略高于 GCP | 按秒 | 同上 | 同样要 quota |
| **Azure** | — | — | ❌ 你的订阅里 T4/A100/H100/A10 配额全为 0，别折腾 | 配额审批要几天，不值得为一次实验等 |

**选它的理由（L4 的定位）：** 24GB 显存、72W、300GB/s 带宽——典型的"小模型高并发推理卡"。8B 模型 FP16 刚好塞得下（16GB 权重 + 少量 KV cache 紧张），8B AWQ（约 5–6GB）就很宽裕，能跑到有意义的并发。它**没有 NVLink**，不适合做 TP=2 的大模型实验——那一步临时开 2×L4 或 A100 40GB 一小时就够。

**不浪费钱的六条：**
1. 按秒计费 + **Stop 不 Delete**（保留磁盘和已下载权重）
2. 挂一个持久卷存模型，别每次重下 8–16GB
3. 直接用 `vllm/vllm-openai` 镜像，省掉装 CUDA/PyTorch 的两小时
4. 先开 1 小时验证能跑通，再决定要不要长开
5. 设一个 $15 预算上限，周末复盘花了多少、换到几个数字
6. 实验脚本全部进 git，机器随时可以删——**机器是租的，数字是你的**

## 4.5 为什么要在 K8s 上跑 vLLM（以及什么时候不该）

直说：**vLLM 本身不需要 K8s。** 它就是一个 Python 服务，装在哪都能跑；单模型、单机器、流量稳定的场景里，裸机 + systemd + 一个负载均衡器往往比 K8s **更快、更好调、故障面更小**。前沿实验室里也有大量推理服务直接跑在裸金属上，或者用 Slurm 分配节点。

**K8s 不是性能选择，是组织选择。** 它在这些条件下才开始赚回成本：

1. **多模型、多团队**：几十个模型、十几个团队要自助上线，需要统一的部署契约、配额、隔离
2. **弹性**：Karpenter 按需拉 GPU 节点、CPU/GPU 混合池、低峰缩容
3. **生命周期自动化**：滚动更新、金丝雀、模型回滚、与模型注册表联动
4. **治理**：Kyverno 准入、AKV CSI 密钥、命名空间级成本归属、审计
5. **生态**：KServe / llm-d / Gateway API Inference Extension / Kueue 全部假设你在 K8s 上

反过来，这些情况下 K8s 是**负资产**：只有一个模型；只有一个团队；流量平稳不需要弹性；团队里没人愿意维护控制面。

**K8s 带来的开销到底在哪（面试常被追问）：** 不是"容器慢"，而是 ① 多一跳网络（CNI / kube-proxy / 网关 TLS）；② 镜像拉取与权重加载让冷启动变长；③ 调度器排队；④ cgroup CPU 限制可能掐住 tokenizer 线程；⑤ device plugin 只能整数分配。

**对应的消除手段：** `hostNetwork: true`（绕过一层 NAT）、Gateway API 直连 Pod IP、权重预加载（node-local cache / Model Streamer）、CPU limit 设高或不设、用 DRA/KAI/HAMi 解决分数卡。

**面试标准答案（一句话 + 一个数字）：** "单模型单机时裸机更快，K8s 的价值在多模型、多租户和弹性；我们量过，走 Service 比 hostNetwork 多约 __ms 的 P99，所以推理热路径走 hostNetwork + 网关直连。"

## 5. 六个数字（缺一个 writeup 就不成立）

1. 冷启动：____ s（node-local cache）/ ____ s（initContainer 现下）
2. TTFT P99 @ 16 并发：____ ms
3. 单卡 output throughput：____ tok/s
4. 单卡可稳定支撑并发：____
5. $/1M output tokens（含 GPU 闲置摊销）：$____
6. 优化前后：吞吐 +__% / TTFT −__%

---

## 6. 十道必答题 + 四道 llm-d 题

1. device plugin 为什么不能申请"半张卡"；MIG / time-slicing / MPS / DRA 各解决什么、代价是什么[5][8]
2. 8B 模型 16GB 权重，怎么让新 pod 20 秒内起来；四种方案代价[5]
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

---

## 7. 怎么讲你的 DevOps 背景（不是道歉，是卖点）

> 我一直在做多租户平台的可靠性与治理：策略即代码、GitOps 收敛、密钥与身份、升级与回滚。现在我把同一套方法用到 GPU 上——配额、优先级、抢占、成本归属，以及模型服务的 SLO。**原型能跑的人很多，能把它做成 7×24 有人负责的服务的人很少，那是我的位置。**

证据三件套：Kyverno 收敛 runbook、GPU 配额策略集、六个性能数字。

---

## 8. 不要做

- ❌ 20h 以上的课程 / 通识认证（NCA-AIIO 那 $125 例外，它只花 1 小时）
- ❌ 在共享 UAT 集群做实验：污染环境 + 触发 Coder→Reviewer SOP + 花公司钱
- ❌ 从零写 RAG chatbot
- ❌ 只有 hello world 的 KServe / vLLM demo
- ❌ 先补 ML 理论再碰 GPU（顺序反了）
- ❌ 等 CKIE 考纲出来再开始学（2027 出考纲，你现在就该会）
- ❌ 把休假排满不留休息日

---

## 9. 如果只有 90 分钟

租一张 L4 → `vllm serve` 8B 量化模型 → 16 并发压一次 → 把 **TTFT P99** 和 **output tok/s** 抄进 README。

两个数字 > 四十小时视频。有了第一个数字，后面 11 周才有参照系。

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
