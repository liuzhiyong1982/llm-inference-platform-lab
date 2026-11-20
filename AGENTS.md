# AGENTS.md

## 仓库性质

- 纯文档仓库：个人 LLM 推理平台作品集的计划与 runbook。没有应用代码、包清单、CI、测试或构建步骤；不要臆造 `npm test` 之类的命令。
- 全部正文用简体中文。命令、参数、指标名（`TTFT`、`P99`、`output tok/s`、`$/1M tokens`）保持英文原样。
- 两个文件分工不同：
  - `ai-cloud-native-week-plan.md`：路线图、选型、市场/薪资论证、面试题。
  - `d1-vllm-baseline-runbook.md`：D1 的可执行步骤（起服务、压测、排障）。

## 唯一事实源

- 计划文件自称「本文是唯一版本……后续调整都改这里」。改计划就改它，不要新建 v2、并行路线图或按周倒排的旧版。当前节奏是季度 gate，不是 12/14 周。
- 计划里的 `[n]` 引用在文末 `Sources` 解析。新增事实性论断要补 `Sources` 条目，不要内联裸 URL；市场/薪资数据标注为 2026-11，没有新来源不要改数字。
- runbook 是 D1 细节的唯一出处；不要把其中的命令大段复制到 README 或计划里。

## 现状：不要假设已存在

- `results/`、`gpu_util.csv`、`Makefile` 都不存在（`ls` 可验证）。计划验收清单里的 `make bench` 是目标，不是现在能跑的命令。
- `README.md` 目前只有一行指标范围占位（`echo 我要测：...`），不是构建脚本。保留这句指标定义，把 runbook §5 的基线表补进 README，而不是另开报告文件。

## 硬约束

- **禁止在共享 UAT 集群 `uat-mobility-aks-01` 上做实验**（见计划「不要做」一节：污染共享环境、触发 Coder→Reviewer SOP、花公司钱）。该集群只能作为简历 case study 来写。
- 所有压测在 **Vast.ai** 租用的单卡 L4 上做；租 **on-demand**，不要 interruptible（会被 pause，基线作废），总预算 $15。
- 租用机操作：`HF_HOME=/workspace/hf`；容器盘 ≥ 40GB（创建后不能扩容）。Vast 的 Stop 会继续收存储费且不保证能重启，**结果先 `scp` 回本地并 push**，再决定 Stop（D2 在 24h 内）还是 Destroy（隔几天）。
- 实验脚本和结果必须进 git：「机器是租的，数字是你的」。

## vLLM 版本坑

- flag 和文档路径会随小版本变，用前先 `<cmd> --help` 加 docs.vllm.ai 核对。计划里已记录 `performance/optimization` 已 404、正确路径是 `configuration/optimization`。
- baseline 跑不要开 `--enable-per-request-metrics`：它会给 headline 数字增加 CPU 开销。只有 D1 诊断跑加这个服务端参数；加完后 `--save-detailed` 的结果里才有 `server_queue_times` / `server_ttfts`，用来区分「排队慢」还是「prefill 慢」。
- 请求里的 `model` 必须匹配 `--served-model-name qwen3-8b`，否则返回 404。

## D1 完成标准

`results/` 里 4 个 baseline JSON（并发 1/4/16/64）+ README 表格 + 一句归因结论（排队 vs prefill vs decode；只有诊断 JSON 才能拆服务端排队）+ `gpu_util.csv` + 启动时的模型加载耗时/KV cache 容量/最大并发 + 花费记录；缺一项不算完成。
