# 文档索引

本页是文档总入口，只负责路由：说明每个入口回答什么问题，以及没有具体任务时从哪读起。按任务读取的触发表在 [AGENTS.md](../AGENTS.md)，文档分类、权威归属与维护流程在[文档维护规则](agents/documentation.md)，本页不复制。

## 冷启动阅读路径

1. [架构总览](architecture/INDEX.md)：系统由什么组成、模块地图、依赖与不变量。
2. [模块边界](architecture/module-boundaries.md)：职责归属与依赖方向；对照 [GLOSSARY.md](../GLOSSARY.md) 理解术语。
3. 按需打开 `architecture/modules/` 中的模块页，再沿链接进代码与测试。
4. 涉及取舍时查 `adr/`；需要证据或最新采纳决定时查[调研索引](research/INDEX.md)。

## 入口分工

| 入口 | 回答的问题 |
| --- | --- |
| [README](../README.md) | 怎么安装和使用 |
| [AGENTS.md](../AGENTS.md) | agent 的常驻约束和按任务读取入口 |
| [GLOSSARY.md](../GLOSSARY.md) | 领域术语与基线身份是什么意思 |
| [CODING_STANDARDS.md](../CODING_STANDARDS.md) | diff 评审按什么判断 |
| [架构总览](architecture/INDEX.md) | 系统现在怎样组成与运行 |
| [模块边界](architecture/module-boundaries.md) | 规则归谁、依赖方向与状态所有权 |
| `architecture/modules/` | 某个能力现在完整地怎样工作 |
| `adr/` | 为什么做出重要决定 |
| [调研索引](research/INDEX.md) | 比较与验证的证据和适用条件；[决定与探索时间线](research/INDEX.md#决定与探索时间线) |
| `specs/` | 已接受的行为契约（W0／X0 demo、字幕翻译设计） |
| [开发工作流](development/workflow.md)、[技术选型](development/technology-stack.md) | 怎么开发、构建和验证 |
| [依赖布局与资产清单](development/dependencies.md) | 依赖放在哪、版本由谁锁定、哪个 recipe 安装或编译 |
| [测试设计与验收](agents/testing.md) | 测试怎么写、归哪类、怎么验收 |
| [文档维护规则](agents/documentation.md) | 文档放哪、怎么同步 |
| `agents/` 其余文件 | 工程 skills 的 tracker、标签映射与领域文档约定，以及旧字幕翻译评估流程 |

按需创建的目录：`specs/`、`operations/`、`changes/`、`adr/`、`architecture/modules/`。创建条件见[文档维护规则](agents/documentation.md#权威归属与创建时机)。

## 项目特有入口

以下文档不在标准结构内，按冻结证据规则（见 [AGENTS.md](../AGENTS.md) 常驻约束）原位保留：它们本身是冻结证据，或被冻结文件链接，或其字节被代码按 sha256 校验，移动会让链接或自检失效。当前正文只链接它们，不复制内容。

| 路径 | 保留原因 |
| --- | --- |
| `docs/architecture/stt-candidate-pipelines.md` | W0／X0 基线与组件边界的权威表；被 ADR 与调研报告链接，[架构总览](architecture/INDEX.md)链接它 |
| `docs/development/toolchain.md`、`docs/development/windows-nvidia.md` | 工具链与平台细则的权威正文；被归档与调研文件链接，[开发工作流](development/workflow.md)与[技术选型](development/technology-stack.md)摘要并链接 |
| `docs/development/inference-selection.md` | 推理选型原则；`experiments/run_round2.py` 对其字节取 sha256 |
| `docs/guides/*.md` | 基线测试与翻译模型资产操作指南；被冻结报告大量链接 |
| `docs/plans/*.md` | 已完成、已停止或已取代的执行计划（含 `claude-judge-profile.md`）；多数被冻结报告与台账链接，保留为计划历史 |
| `docs/testing/2026-*.md` | 带日期的验证、审计与冻结记录（冻结证据） |
| `docs/testing/*.md`（无日期） | 评估方法、评测器与显示契约、语料参考；`evaluation-config-v1.md` 由 `experiments/analysis/build_heldout.py` 等校验 sha256，`stt-evaluation.md`、`fatestay-reference.md`、`validation.md` 由 `experiments/run_round2.py` 取 sha256 |
| `docs/context/*.md` | 带日期的接跑台账（冻结证据） |
| `docs/archive/agents/2026-10-09-codex-AGENTS.md` | Codex 时代的 agent 指令归档（冻结证据），只作历史参考 |
| `experiments/**/README*.md`、`experiments/**/*.md`、`experiments/**/THIRD_PARTY_NOTICES.txt` | 各实验与 demo 包自带的说明、第三方许可声明与参考复核 prompt（`experiments/translation_corpus/*-prompt.md` 属冻结的参考 prompt）；与代码同目录维护 |

### 既有文档清单

调研条目已登记在[调研索引](research/INDEX.md)，此处只列其他既有文档，按原登记顺序保留。

- ADR: [专名一致性进产品](adr/0014-name-consistency-in-product.md) — 已接受（2026-10-19）；冻结配置（no-think、提示 v5、规则一＋孤立单字）原样移植：`names` 阶段在 ja-cues 与 translate 之间用 Qwen3.8 建表，发布时替换；建表失败写空表照常发布，`[names] enabled` 默认 true，已交付影片重新发布不重译，表可手改后重跑；验收只看总体正向。证据无 MQM 抽样，用户接受。只替代 ADR-0013 第 3 条。
- ADR: [专名一致性研究线结题](adr/0013-name-consistency-closed.md) — 已接受（2026-10-19）；"通用模型建专名表＋生成后替换"研究线关闭，最佳已知配置冻结（no-think、提示 v5、程序兜底全开；替换默认规则一＋孤立单字，89%／2.5%）、不再开新轮次（第 3 条"不进产品"已被 [ADR-0014](adr/0014-name-consistency-in-product.md) 替代）；重开只限模糊匹配或"表可人工校对"形态。不替代任何 ADR。
- ADR: [产品 STT 增加可选引擎 cross](adr/0012-cross-asr-judge.md) — 已接受（2026-10-19）；asr 阶段内 w0 与 x0 共驻、Whisper 交叉打分裁判，默认仍 w0；两部合计 CER −0.95 pp（低于预设 1.0 pp 验收线，用户裁定采纳）。不替代 ADR-0007 与 ADR-0008。
- ADR: [产品翻译配方改为 dp10-cut-degrade-v1](adr/0011-dp10-cut-product-recipe.md) — 已接受（2026-10-18）；产品包切包与邻文同步到 dp10-cut，降级规则不变；已交付影片的翻译身份过期、下次整批重译；仍无质量证据。替代 ADR-0007 决定 4 与 ADR-0010 关于产品配方的部分。
- ADR: [字幕翻译流程基线改为 dp10-cut](adr/0010-dp10-cut-translation-flow-baseline.md) — 已接受（2026-10-17）；每包 ≤10 条、可见 ≤12 条，分级切点偏向停顿，不跨 ≥20 s；按逻辑推定，未做 GPU 筛选；产品配方不变。替代 ADR-0009。
- ADR: [字幕翻译流程基线改为 dp6-grp](adr/0009-dp6-grp-translation-flow-baseline.md) — 已被 ADR-0010 替代（2026-10-17）；完整 SRT 流程按停顿与 <1 s 小组拼包，提示同 `b10-joint`；v7 两次合并与 b10-joint 无可分辨差异；产品配方不变。部分替代 ADR-0006。
- ADR: [放弃多样本 MBR，不自动选用"翻译多次再挑选"](adr/0008-no-multi-translation-selection.md) — 已接受（2026-10-16）；放弃 v5 `mbr8s` 与 v4 `mbr8c`，翻译基线仍为 `b10-joint`；多样本选择、best-of-N、多次全量翻译投票等方法只在用户明确要求时使用，边界情况先问。
- ADR: [双语字幕流水线架构](adr/0007-bilingual-subtitle-pipeline-architecture.md) — 已接受（2026-10-13）；阶段 × 整批的 GPU 调度、单一 CUDA 12.8 Python 环境（torch 2.11.0+cu128）与官方 llama.cpp、以日文 cue 为翻译单元、翻译 10→5→1 降级、配置文件驱动无 CLI；已实现（2026-10-14）。
- ADR: [字幕翻译流程基线改为 b10-joint](adr/0006-b10-joint-translation-flow-baseline.md) — 已被部分替代；批次部分 2026-10-17 由 ADR-0009、再由 ADR-0010 替代，joint 提示仍有效。
- ADR: [字幕翻译采用 APEX-I-Compact 基线](adr/0005-apex-i-compact-translation-baseline.md) — 已接受（2026-10-07，2026-10-08 更新采样配方）；模型、采样与运行时参数仍是当前翻译基线；引擎条款由 ADR-0007 替代，完整 SRT 流程部分先后由 ADR-0006／0009／0010 替代。
- ADR: [字幕翻译采用 Hy-MT2 30B-A3B Q3_K_M 基线](adr/0004-hy-mt2-translation-baseline.md) — 历史决定；2026-10-07 被 ADR-0005 替代。
- Specs: [中日双语字幕批量生产流水线：技术设计](specs/bilingual-subtitle-pipeline.md) — implemented（2026-10-14）；第一个正式产品形态（配置文件驱动）：固定配方、八阶段分解、CPU 流水线＋GPU 分阶段批处理、产物与续跑、统一 CUDA 12.8 环境、配置边界与里程碑。
- Plans: [Hy30 四种量化大规模比较](plans/hy30-four-quantization-comparison.md) — 实测与评估完成；原 83 窗口及新增 1,200 窗口、完整自动评估、四轮性能与正式长跑，失败和缺分完整保留；[结果报告](research/2026-10-07-hy30-four-quantization-results.md)。
- Specs: [字幕翻译共同设计](specs/subtitle-translation-common.md) — draft；四套流程共用的语义单元、上下文／术语、源文预分析、记忆、映射、恢复、可选反思与评测隔离；反思的审校／修订模型可配置，暂不固定。模型流程：[通用语言模型](specs/subtitle-translation-generic.md)、[Hy-MT2](specs/subtitle-translation-hy-mt2.md)、[TranslateGemma](specs/subtitle-translation-translategemma.md)、[Tower+](specs/subtitle-translation-tower-plus.md)；完整增强设计尚未全部实施，固定窗口实验子集已完成 smoke/dev 并冻结正式 test 配方，不改变当前 STT 里程碑。
- Guides: [本地翻译模型资产](guides/local-translation-model-assets.md) — 共九个 GGUF 已下载并通过完整 SHA256，含新增 Hy30 APEX-I-Compact、i1-Q3_K_L、i1-Q3_K_M；本地路径、固定 revision、哈希、核验记录及两份资产清单入口。新增三款已完成固定窗口质量、四轮性能及正式长跑验证；官方 Q4 已完成与 Q3 的历史对照。
- Plans: [第一批 ASR 两片整片比较](plans/asr-candidates-fullfilm.md) — 已完成；Cohere／Granite 基础版／Nemotron 与新运行 W0／X0，共同新 Pyannote／MMS、完整 II／III。
- Testing: [YODAS2 国会讨论素材](testing/yodas2-parliament-reference.md) — 用户指定的 3 小时国会录音、1,371 条原字幕与 SRT 已获取；哈希、逐条转换、整段解码通过，听辨／ASR 待执行。
- ADR: [W0／X0统一采用新Pyannote](adr/0003-new-pyannote-baselines.md) — 已接受；两条均新Pyannote＋MMS，区分采纳定义与待迁移CLI默认。
- Plans: [W0／X0 四种 VAD 对照](plans/vad-baseline-comparison.md) — 十组合十二窗已执行；119 项完成、1 项触发生成上限，完整失败记账。
- Plans: [新 Pyannote GPU 补测](plans/pyannote-gpu-comparison.md) — 保留 CPU 原始结果，仅重测两条 Pyannote 路线。
- Guides: [W0／X0标准基线测试](guides/baseline-testing.md) — 当前统一入口；两套demo命令、环境、结果核验、评测及历史复现边界。
- Demo: [X0 可复用入口](../experiments/x0_demo/README.md) — 新Pyannote显式入口、Qwen／共用MMS；fixed30代码旧默认与无VADcut-merge作为对照。
- Specs: [X0 demo契约](specs/x0-reusable-demo.md) — 整数采样窗口、独立纯文字识别、Qwen原生特征、MMS全文及错误记账。
- ADR: [X0流程采用依据](adr/0002-x0-demo-flow.md) — Qwen兼容流程原则继续有效；无VAD基线选择由ADR-0003替代。
- Testing: [X0 demo验证](testing/2026-10-05-x0-demo-validation.md) — 当前实现的离线与本机GPU验证范围。
- Plans: [X0 流程最小验证](plans/x0-whisperx-flow.md) — 已完成；运行前冻结两窗及三臂，按无回归条件停止扩展。
- Specs: [W0 可复用 demo 契约](specs/w0-reusable-demo.md) — 已实现；VAD／ASR／MMS 边界、完整文字与源坐标及验收范围。
- Demo: [W0 可复用入口](../experiments/w0_demo/README.md) — 后续 session 复用并更新的实现、离线运行和迭代流程。
- Testing: [W0 demo 验证](testing/2026-10-05-w0-demo-validation.md) — 独立端到端回归、数值配置约束及小样本边界。
- ADR: [未来 W0／X0 两条 STT 基准线](adr/0001-two-stt-baselines.md) — 历史采纳记录；两路线组织和W0移植要求保留，VAD与X0分段选择由ADR-0003更新。
- Plans: [Whisper 流程等价性与架构依据](plans/whisper-framework-equivalence.md) — 已完成；固定 Pyannote／MMS，源码核验与隔离等价性原型，不迁移正式架构。
- Plans: [日语 CTC 候选补充实测](plans/japanese-ctc-supplement.md) — 已完成；固定上游文字，四窗筛查及五个组合的十二窗复验。
- Plans: [W0＋VAD＋CTC 时间优先追加实验](plans/w0-vad-ctc-follow-up.md) — 已完成用户指定的独立追加，保持原评分并分别报告时间收益与内容代价。
- Plans: [三候选单组件增量评估](plans/component-augmentation.md) — 本轮完成；保持原三基线，单变量筛查及扩展，未通过替换护栏的分支停止。
- Plans: [两片主参考固定候选复核](plans/two-film-stt-revalidation.md) — 已完成；五条固定配置、两片共 60 分钟同输入比较。
- Architecture: [当前 STT 基准线与组件边界](architecture/stt-candidate-pipelines.md) — 用户已确认未来W0／X0两条基准线；明确组件、新旧ID与历史实测边界，W1保留回归身份。
- Development: [Python toolchain](development/toolchain.md) — accepted conventions;
  lightweight demo toolchain implemented; backend environments isolated.
- Development: [Inference selection](development/inference-selection.md) — 已接受的 ASR／对齐 GPU 要求、VAD CPU／GPU 例外及对白／歌声偏好；实测证据见有日期的报告。
- Development: [Windows and NVIDIA](development/windows-nvidia.md) — accepted
  platform constraints; backend compatibility matrix pending.
- Testing: [Validation boundaries](testing/validation.md) — accepted conventions;
  offline executable checks and independent evaluator audit available.
- Testing: [电影评估素材与参考优先级](testing/fatestay-reference.md) — II/III 原版日文字幕为精确主参考，
  I/Black Panther 依可信度递减仅作补充；直接使用已分离音频，保留当前与历史身份边界。
- Testing: [四部电影音视频与字幕核验](testing/2026-10-04-media-matching.md) — 全片提取身份核对与 12 段机器抽查；人工听辨待完成，Black Panther 存在配音/字幕措辞差异疑点。
- Testing: [翻译模型评估](testing/translation-model-evaluation.md) — 翻译评估统一入口，链接本地 v2 字幕参考库、自动评估流程、实现和接跑证据；开发闭环和正式 test 已完成；结果含缺分和证据限制。
- Plans: [三个翻译模型家族、五个版本的评估计划](plans/translation-model-comparison.md) — 已完成；五版本 smoke/dev、冻结配置、完整固定 test 与中文报告。
- Agents: [字幕翻译自动评估流程](agents/subtitle-translation-evaluation.md) — adopted；机械检查、Sol/high 全量主评、独立复评与程序汇总，不安排人工抽查；固定窗口 runner 已实现，实际开发闭环和正式 test 已完成，结果中的缺分保留。
- Demo: [本地字幕翻译](../experiments/translation_demo/README.md) — 三家族九个量化版本的原生模板、逐窗结果、独立辅助映射与原始尝试；当前 APEX-I-Compact 基线入口与具体 GPU 运行证据由 demo、运行目录和接跑记录维护。
- Demo: [字幕翻译离线评估器](../experiments/translation_eval/README.md) — packet、schema、固定复评并集、裁决、完整分母和缺分边界；合成与真实语料关联检查通过，不代表裁判准确率。
- Demo: [字幕翻译裁判执行面](../experiments/translation_judge/README.md) — CLI 与 fresh subagent 传输、隔离、有限重试和恢复；旧版 CLI 失败保留为历史证据；正式运行使用显式 gpt-6.1-sol/high fresh subagent。
- Context: [翻译比较执行接跑](context/2026-10-06-translation-comparison-execution.md) — 五候选正式 test 运行、裁判证据、恢复审计及未完成项。
- Testing: [STT 质量与性能评估](testing/stt-evaluation.md) — 已更新两片主参考、补充结果分层及音频输入流程；
  首轮及两片固定样本复核完成，产品验收门槛仍需明确采纳。
- Testing: [时间同步优先的字幕评估标准](testing/subtitle-timing-benchmark.md)
  — 区分连续文字、内容时间与显示；当前参考分层已更新，首轮数值规则单独冻结。
- Plans: [本地 STT demo 实测与选型方案](plans/local-stt-demo-selection.md)
  — 本轮实测完成；后续优先两片主参考，沿用有界调参与保留集评价原则。
- Context: [本地 demo 执行记录](context/2026-10-04-demo-execution.md)
  — 当前执行状态、可恢复入口和证据边界。
- Testing: [语料冻结与音频身份](testing/2026-10-04-corpus-freeze.md)
  — 已执行，章节划分、样本精确时间映射及未完成人工核对的限制。
- Testing: [评测器接口与边界](testing/evaluator-contract.md)
  — 离线实现、完整分母与时间粒度、合成测试和使用入口。
- Testing: [评测器独立审查](testing/2026-10-04-evaluator-audit.md)
  — 穷举、故障注入及规模测试；不代表声学或 GPU 验证。
- Testing: [统一字幕显示契约](testing/demo-display-contract.md)
  — 固定 writer 重放规则、未渲染文字保留和独立显示诊断。
- Testing: [实验汇总契约](testing/demo-analysis-contract.md)
  — 固定清单、失败记账、共同有效子集和场景成组统计。
- Testing: [第一轮筛选规则](testing/evaluation-config-v1.md)
  — 决策规则已冻结；开发结束后另冻结晋级清单，声学资格仍未验证。
- Plans: [Hy30 Q3／Q4 追加对照](plans/hy30-q3-q4-comparison.md) — 同固定 test、同原生模板、Q4 显式部分 offload；三次性能重复与全量 Sol/high 自动质量评估。
- Testing: [APEX-I-Compact 基线采纳验证](testing/2026-10-07-apex-baseline-adoption-validation.md) — 当前基线入口、离线检查与新输出身份的本机 smoke 验证；不覆盖四量化历史报告或冻结证据。
