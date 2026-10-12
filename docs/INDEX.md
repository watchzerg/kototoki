# Documentation Index

Use this index to locate documents relevant to the current task. Read only the
applicable documents; an empty directory represents a reserved category, not an
implemented capability or an adopted decision.

## W0 task routing

For any current baseline test or comparison, begin with the shared
[W0/X0 baseline testing guide](guides/baseline-testing.md). It routes to both
canonical demo READMEs, contracts, validation records, and evaluation steps.
这是demo阶段的临时路由，正式入口建立后再替换对应引用。两条已采纳基线均使用新Pyannote，
见[ADR-0003](adr/0003-new-pyannote-baselines.md)。X0保留Qwen原生特征；fixed30和无VAD cut-merge
保留为独立对照身份。当前CLI仍有旧默认，测试最新基线须显式选择新Pyannote。

For current W0 execution, development, or comparison, start with the
[reusable demo](../experiments/w0_demo/README.md) and reuse/update that implementation.

| Task | Entry point |
| --- | --- |
| Run W0 or restore its local assets/environment | [Demo usage](../experiments/w0_demo/README.md) |
| Replace VAD or change cutting/merging | [Demo boundaries](specs/w0-reusable-demo.md), 再检查`experiments/w0_demo/vad_candidates.py`（新Pyannote）或`vad.py`（历史配方） |
| Change Whisper features/decoding or MMS alignment | [Demo contract](specs/w0-reusable-demo.md), then `asr.py` or `alignment.py` in the demo |
| Regress, benchmark, or compare a changed W0 | [Current validation](testing/2026-10-05-w0-demo-validation.md) and [evaluation method](testing/stt-evaluation.md) |
| Reproduce an older W0/W1 experiment | Use its frozen historical entry point; keep that identity separate from current W0 |

The demo README owns execution and iteration instructions. Historical reports
remain evidence; their older implementation plans do not replace the current demo.

## X0 task routing

当前X0运行或开发从[可复用demo](../experiments/x0_demo/README.md)开始，由它维护单命令入口及固定跨环境执行。
X0现采用新Pyannote、MMS及Qwen兼容的流程适配；现有fixed30 CLI旧默认与无VAD cut-merge保留历史／对照身份。

| Task | Entry point |
| --- | --- |
| Run X0 with existing local assets | [X0 demo usage](../experiments/x0_demo/README.md) |
| Change segmentation, Qwen inputs or MMS handoff | [X0 contract](specs/x0-reusable-demo.md), then the corresponding demo module |
| Understand adopted flow logic versus quality claims | [ADR-0002](adr/0002-x0-demo-flow.md) |
| Regress the current implementation | [X0 validation](testing/2026-10-05-x0-demo-validation.md) |

Historical `x0_flow`, `qwen` and cached CTC runs retain their identities and
source snapshots. Use the current demo for continued implementation.

两部完整电影的新Pyannote／cut-merge对照见[整片实验计划](plans/fullfilm-segmentation-comparison.md)
与[实验入口](../experiments/fullfilm_comparison/README.md)。该入口复用canonical模型适配器，
增加逐窗失败后继续与整片评分。用户随后采纳两条新Pyannote基线，CLI旧默认尚未迁移。
完成结果见[2026-10-05整片对照报告](research/2026-10-05-fullfilm-segmentation-comparison.md)，
包含失败与家族内配对排除、逐片和加权汇总，以及恢复运行的来源审计。

## 最新采纳决定

2026-10-12：v4 第四轮字幕翻译流程探索已完成，详见 [v4 报告](research/2026-10-11-hy30-flow-v4-report.md) 和 [v4 台账](context/2026-10-11-hy30-flow-exploration-v4.md)。**1 个配方通过确认：`mbr8c`**，即每批 8 个样本，逐条用本地 chrF-MBR 选择。确认集上 Δ −0.016（约 4%，集中在剧集），Holm p 0.016，代价是约 6 倍墙钟。`t03`（temperature 0.3）在确认集上未通过。基线 b10-joint 不自动替换，等待用户决策。实现入口为 [translation_v4](../experiments/translation_v4/README.md)。

2026-10-11：用户采纳 **b10-joint** 作为完整 SRT 流程基线（[ADR-0006](adr/0006-b10-joint-translation-flow-baseline.md)，入口 `just translation-srt`）；模型和采样仍按 ADR-0005。这是工程选择：b10-joint 在 v3 确认集上没有通过显著性检验。下一轮见 [v4 计划](plans/hy-mt2-translation-flow-exploration-v4.md)（proposed）。

2026-10-10：v3 第三轮字幕翻译流程探索已完成，[v3 报告](research/2026-10-10-hy30-flow-v3-report.md)：19 个配方、Claude MQM 裁判、确认集检验，**0 个配方通过确认**；唯一 promising 的 b10-joint 在确认集上未复现。基线 `official30b-cached-v1` 不变，待用户决策。

2026-10-10：字幕翻译流程探索改为[第三轮计划](plans/hy-mt2-translation-flow-exploration-v3.md)（Claude Opus 5.5 MQM 裁判，重新起跑），[v3 台账](context/2026-10-10-hy30-flow-exploration-v3.md)维护执行状态，[v1/v2 教训](research/2026-10-10-hy30-flow-v1-v2-lessons.md)只作为先验使用，[参考 v3 复核](testing/2026-10-10-reference-v3-audit.md)完成；实现入口为[translation_v3](../experiments/translation_v3/README.md)；第二轮已停止，下面关于 v2 的条目均为历史记录。

2026-10-08用户选择[第二轮C档字幕流程探索计划](plans/hy-mt2-translation-flow-exploration-v2.md)：96筛选＋48独立确认，批次大小采用资源宽松的自适应搜索。[新台账](context/2026-10-08-hy30-flow-exploration-v2.md)记录已冻结的源／参考、评估校准、判定规则及正在执行的候选实验，当前尚未收敛、未替换基线。第一轮仅完成有限局部筛选，不证明1-5-1最优或主要方向充分收敛。

[翻译模式筛选报告](research/2026-10-07-hy30-flow-optimization-results.md)完成固定 Hy-MT2 APEX 的一轮有界探索：主要低成本方向无可靠胜出方案，完整SRT实验外层及机械验证可用，未替换基线。[起始计划](plans/hy-mt2-translation-mode-optimization.md)和[探索台账与接跑](context/2026-10-07-hy30-flow-exploration.md)保留范围、证据及未验证方向。

用户于2026-10-08随后采纳官方30B采样、4096输出与缓存，当前配置为`official30b-cached-v1`，总context8192；见[ADR-0005](adr/0005-apex-i-compact-translation-baseline.md)和[新配方验证](testing/2026-10-08-official30b-cached-baseline-validation.md)。历史筛选结论不回写。

[Hy30 四量化大规模报告](research/2026-10-07-hy30-four-quantization-results.md)汇总旧 83 窗及新增 1,200 窗全量评估、四轮性能和正式长跑；[复现入口](research/2026-10-07-hy30-four-quantization-results-appendices/reproduction.md)、[方案](plans/hy30-four-quantization-comparison.md)和[接跑记录](context/2026-10-06-hy30-four-execution.md)保留命令与历史。用户在交付后明确采纳 APEX-I-Compact，原报告与附录保留当时的结论和 Q3_K_M 冻结统计对照。

配套工具：[独立语料构建与双轮参考复核](../experiments/translation_corpus/README.md)、[串行 GPU 比较与恢复](../experiments/translation_four_quantization/README.md)、[全量评估及配对统计](../experiments/translation_eval/README.md)。

[ADR-0005：字幕翻译 Hy-MT2 30B-A3B APEX-I-Compact 基线](adr/0005-apex-i-compact-translation-baseline.md)记录当前采纳决定（`hy-mt2-30b-a3b-apex-i-compact`）；执行复用[翻译 demo](../experiments/translation_demo/README.md)，后续讨论和回归以该固定身份与配方为起点。[ADR-0004](adr/0004-hy-mt2-translation-baseline.md)保留此前 Q3_K_M 采纳历史，已被新决定取代。

[国会讨论 W0／X0 整段实测](research/2026-10-05-parliament-baselines.md)记录新增三小时素材的当前基线运行；
字幕准确度未知，仅作参考，与电影主参考分开报告。

[ADR-0003：W0／X0统一采用新Pyannote](adr/0003-new-pyannote-baselines.md)更新当前组件定义；
ADR-0001／0002中被替代的选择保留历史范围，原生特征及可复用入口原则继续有效。

## Directory map

| Directory | Purpose | Read or update when |
| --- | --- | --- |
| [agents/](agents/) | Repository-specific engineering skill configuration. | Tracking tickets, triaging work, or locating domain documents for skills. |
| [architecture/](architecture/) | Current system structure, module boundaries, data flow, and deployment design. | Changing component responsibilities, interfaces, or cross-cutting behavior. |
| [research/](research/) | Source-backed investigations, model/backend comparisons, experiments, and unresolved questions. | Evaluating an approach or verifying external technical claims. |
| [plans/](plans/) | Execution steps, dependencies, milestones, progress, and validation for a bounded task. | Planning or continuing work spanning multiple steps. |
| [specs/](specs/) | Required behavior, scope, use cases, interfaces, and acceptance criteria. | Implementing or reviewing a feature or a behavior change. |
| [context/](context/) | Project background, constraints, dated handoffs, and relevant working context. | Onboarding or resuming work where the request and repository do not supply enough context. |
| [adr/](adr/) | Architecture Decision Records: significant choices, alternatives, rationale, and consequences. | Making or revisiting a durable technical decision. |
| [glossary/](glossary/) | Canonical domain vocabulary, abbreviations, and naming conventions. | Introducing or changing terminology in code, interfaces, or documentation. |
| [guides/](guides/) | Task-oriented setup, local usage, development, model provisioning, and troubleshooting instructions. | Changing how a person installs, runs, develops, or operates the tool. |
| [development/](development/) | Engineering conventions for toolchains, dependency management, task commands, and platform compatibility. | Changing tooling, build configuration, subprocesses, or GPU integration. |
| [testing/](testing/) | Validation strategies, evaluation protocols, quality/performance reports, and test-data provenance. | Changing validation or comparing transcription quality, latency, or resource use. |
| [archive/](archive/) | Completed plans, obsolete investigations, and historical context retained for reference. | Retiring documents whose content is no longer current guidance. |

Empty directories contain `.gitkeep` placeholders so Git preserves the
structure. Remove a placeholder when its directory gains a real document.

## Where information belongs

- **Spec** defines what must happen; **plan** describes how to deliver it.
- **Architecture** describes the current system; **ADR** explains why a durable
  choice was made. Label proposed architecture explicitly until implemented.
- **Research** supplies evidence and recommendations; a recommendation alone
  does not establish an adopted decision.
- **Context** supplies background and handoff information. Link to specs, ADRs,
  and plans instead of duplicating their requirements, decisions, or task lists.
- **Glossary** owns terminology. Start with `glossary/GLOSSARY.md` when domain
  vocabulary needs recording; use preferred term, meaning, and aliases to avoid.
- **Guides** explain procedures; **testing** records validation methodology and
  evidence. Executable tests and test fixtures belong with the code.
- **Development** defines engineering conventions; guides link to these policies
  when explaining setup or operation.
- **Agents** defines skill workflows: [local Markdown task tracking](agents/issue-tracker.md),
  [triage status vocabulary](agents/triage-labels.md), and
  [single-context domain rules](agents/domain.md).

Keep one authoritative home for each fact and use relative Markdown links
elsewhere. Repository code and configuration describe actual behavior; specs
describe intended behavior. Flag discrepancies and resolve them in the task
rather than silently treating an old document as current.

## Document conventions

- Choose language by audience: Simplified Chinese for human-facing plans, guides,
  reports, and explanations; English for agent instructions, code/comments,
  commands and identifiers. Keep `lower-kebab-case.md` filenames.
- Use descriptive topic names, such as `specs/audio-file-transcription.md`.
  Date research, reports, and handoffs when chronology matters:
  `YYYY-MM-DD-topic.md`.
- Give each substantive document a title, status, last-updated date
  (`YYYY-MM-DD`), and scope. Add related links where applicable.
- Use category-appropriate statuses: specs may be draft/accepted/implemented;
  plans proposed/active/completed; research exploratory/concluded. State
  limitations and open questions explicitly.
- Research must include source links, access dates, relevant versions, and a
  distinction between observations and inferences. Experiments and evaluation
  reports must include enough model, hardware, configuration, and input details
  to reproduce the results.
- Specs should include scope, exclusions, observable behavior, and acceptance
  criteria. Plans should link the relevant spec or request and include steps,
  dependencies, progress, and verification criteria.
- ADRs use `NNNN-short-title.md`, starting at `0001`. Include status
  (proposed/accepted/rejected/superseded), date, context, decision, alternatives,
  and consequences. Mark acceptance only when the decision has actually been
  adopted; record the basis. Supersede accepted decisions with a linked new ADR
  rather than rewriting their history. Keep ADRs in `adr/` for stable references.
- Archive obsolete material under `archive/<original-category>/`, preserving
  its status and linking any replacement. Repair incoming links when moving it.
  Archived material is historical evidence, not current task instructions.
- Keep private recordings, transcripts, model weights, secrets, and large
  generated outputs outside documentation and Git. Link reproducible procedures
  and permitted artifact locations instead.

## Navigation and growth

Add links below when substantive documents are created. Group them by category
and include their status so future readers can find current guidance without
searching every file. For a large category, create its own `INDEX.md` and link
that index here.

### Current documents

- Plans: [Hy30 四种量化大规模比较](plans/hy30-four-quantization-comparison.md) — 实测与评估完成；原 83 窗口及新增 1,200 窗口、完整自动评估、四轮性能与正式长跑，失败和缺分完整保留；[结果报告](research/2026-10-07-hy30-four-quantization-results.md)。

- Specs: [字幕翻译共同设计](specs/subtitle-translation-common.md) — draft；四套流程共用的语义单元、上下文／术语、源文预分析、记忆、映射、恢复、可选反思与评测隔离；反思的审校／修订模型可配置，暂不固定。模型流程：[通用语言模型](specs/subtitle-translation-generic.md)、[Hy-MT2](specs/subtitle-translation-hy-mt2.md)、[TranslateGemma](specs/subtitle-translation-translategemma.md)、[Tower+](specs/subtitle-translation-tower-plus.md)；完整增强设计尚未全部实施，固定窗口实验子集已完成 smoke/dev 并冻结正式 test 配方，不改变当前 STT 里程碑。

- Guides: [本地翻译模型资产](guides/local-translation-model-assets.md) — 共九个 GGUF 已下载并通过完整 SHA256，含新增 Hy30 APEX-I-Compact、i1-Q3_K_L、i1-Q3_K_M；本地路径、固定 revision、哈希、核验记录及两份资产清单入口。新增三款已完成固定窗口质量、四轮性能及正式长跑验证；官方 Q4 已完成与 Q3 的历史对照。

- Research: [RTX 5080 16GB 翻译模型量化选择](research/2026-10-06-translation-5080-quantization.md) — exploratory；五个指定模型的可下载 GGUF、文件大小、全 GPU 与混合运行边界；纠正 30B-A3B Q4 的显存预期，未实测。

- Research: [Hy-MT2 30B-A3B Q4 候选](research/2026-10-06-hy-mt2-30b-q4-candidates.md) — exploratory；首次四位 GGUF 来源与容量调查；后续官方 Q4 实测和最新候选排序见文内更新链接。

- Research: [Hy-MT2 30B-A3B：5080 量化候选推荐](research/2026-10-06-hy30-5080-quantization-shortlist.md) — 历史 exploratory；固定文件、作者背景与试验优先级。候选 1、2、4 的后续实测见四量化报告；用户随后采纳 APEX-I-Compact，当前决定由[ADR-0005](adr/0005-apex-i-compact-translation-baseline.md)维护。
- Research: [Hy30 四量化质量、耗时与显存稳定性](research/2026-10-07-hy30-four-quantization-results.md) — 83 旧窗＋1,200 新窗分别报告，配对不确定性、严重错误、评审波动、四轮耗时与 30 分钟长跑；[附录与复现](research/2026-10-07-hy30-four-quantization-results-appendices/reproduction.md)。

- Research: [Hy-MT2 字幕流程官方资料复核](research/2026-10-06-hy-mt2-subtitle-flow-review.md) — exploratory；核查提示、批量协议、采样与验证边界；建议已回写 Hy-MT2 草案，保留可迭代设计与待测参数，未实施／未运行推理。

- Research: [三个本地翻译模型对比](research/2026-10-05-local-translation-model-comparison.md) — exploratory；Hy-MT2、TranslateGemma、Tower+ 的输入契约、背景／术语、多段／JSON、字幕约束与本地部署；来源核查，未进行模型实测。
- Research: [Hy-MT2-7B-GGUF 详解](research/2026-10-05-hy-mt2-7b-local-translation.md)、[TranslateGemma-12B 详解](research/2026-10-05-translategemma-12b-local-translation.md)、[Tower-Plus-9B 详解](research/2026-10-05-tower-plus-9b-local-translation.md) — exploratory；分别提供模板解释、伪代码、证据等级及字幕应用边界。

- Research: [字幕翻译调研总报告](research/2026-10-05-subtitle-translation.md) — exploratory；三个相邻项目源码、上下文与语义映射、JSON／缩批恢复及质量评估；未运行翻译实验、未改变 W0／X0。
- Research: [Subtitle Edit 翻译源码](research/2026-10-05-translation-subtitleedit.md)、[VideoLingo 翻译源码](research/2026-10-05-translation-videolingo.md)、[pyVideoTrans 翻译源码](research/2026-10-05-translation-pyvideotrans.md) — exploratory；本地快照与固定上游证据、实际机制及边界。
- Research: [翻译主流方法与模型契约](research/2026-10-05-translation-methods.md)、[日译中字幕质量评估](research/2026-10-05-translation-evaluation.md) — exploratory；一手资料与后续实验建议，不构成模型排名或已采纳实现。

- Plans: [第一批 ASR 两片整片比较](plans/asr-candidates-fullfilm.md) — 已完成；Cohere／Granite 基础版／Nemotron 与新运行 W0／X0，共同新 Pyannote／MMS、完整 II／III。

- Testing: [YODAS2 国会讨论素材](testing/yodas2-parliament-reference.md) — 用户指定的 3 小时国会录音、1,371 条原字幕与 SRT 已获取；哈希、逐条转换、整段解码通过，听辨／ASR 待执行。

- Research: [YODAS2 日语元数据与选样](research/2026-10-05-yodas2-japanese-selection.md) — 两子集 32,899 条时长实查、字幕质量陷阱与按包获取方案；后续用户选择国会讨论，获取结果见素材记录。

- Research: [日语长音频与对应文本来源](research/2026-10-05-japanese-longform-asr-sources.md) — 公开有声书、播客、长篇语料与会议录像的获取入口、长度和参考质量；来源调研，未下载或纳入正式评测。

- Research: [ASR 模型全景与候选优先级](research/2026-10-05-asr-model-landscape.md) — 官方来源调研；面向日语、本地 Windows／RTX 5080 的候选与验证门槛，未改变 W0／X0 基线。
- Research: [第一批 ASR 两片整片实测](research/2026-10-05-asr-candidates-fullfilm.md) — 五路线十次运行完成；Cohere／Nemotron 更快但 CER 落后，Granite 多次重复触顶，保留 W0／X0。

- ADR: [W0／X0统一采用新Pyannote](adr/0003-new-pyannote-baselines.md) — 最新已接受决定；两条均新Pyannote＋MMS，区分采纳定义与待迁移CLI默认。
- Research: [两片整片分段对照](research/2026-10-05-fullfilm-segmentation-comparison.md) — 八组整片运行、完整／配对排除评分及独立审计；后续用户已采纳新Pyannote。

- Plans: [W0／X0 四种 VAD 对照](plans/vad-baseline-comparison.md) — 十组合十二窗已执行；119 项完成、1 项触发生成上限，完整失败记账。
- Research: [VAD 稳定版本核验](research/2026-10-05-vad-stable-versions.md) — 官方发布、权重 revision、默认参数与许可；FireRed Beta 例外和 Pyannote 访问门控明确区分。
- Research: [W0／X0 十组合 VAD 比较](research/2026-10-05-vad-baseline-comparison.md) — 十组合实测与分析完成；119 份完整产物审计通过、1 次 X0＋新 Pyannote 生成上限失败保留；质量、时间、成本、资源及不确定性保留当时口径；后续采纳见ADR-0003。
- Plans: [新 Pyannote GPU 补测](plans/pyannote-gpu-comparison.md) — 保留 CPU 原始结果，仅重测两条 Pyannote 路线。
- Research: [新 Pyannote CPU／GPU 对照](research/2026-10-05-pyannote-gpu-comparison.md) — 23次完成、1次同窗触顶；切分／质量一致，新进程较慢，单窗模型复用约快13.1倍。

- Guides: [W0／X0标准基线测试](guides/baseline-testing.md) — 当前统一入口；两套demo命令、环境、结果核验、评测及历史复现边界。

- Demo: [X0 可复用入口](../experiments/x0_demo/README.md) — 新Pyannote显式入口、Qwen／共用MMS；fixed30代码旧默认与无VADcut-merge作为对照。
- Specs: [X0 demo契约](specs/x0-reusable-demo.md) — 整数采样窗口、独立纯文字识别、Qwen原生特征、MMS全文及错误记账。
- ADR: [X0流程采用依据](adr/0002-x0-demo-flow.md) — Qwen兼容流程原则继续有效；无VAD基线选择由ADR-0003替代。
- Testing: [X0 demo验证](testing/2026-10-05-x0-demo-validation.md) — 当前实现的离线与本机GPU验证范围。

- Research: [X0 吸收 WhisperX 流程](research/2026-10-05-x0-whisperx-flow.md) — 历史两窗三臂GPU验证；energy与VAD均有取舍。后续流程设计采用见ADR-0002，新demo的cut-merge不继承历史energy分数。
- Research: [X0／WhisperX 源码核查](research/2026-10-05-x0-whisperx-source-audit.md) — 可跨模型策略、已有等价行为、Whisper 专属逻辑及旧入口 CTC 身份差异。
- Plans: [X0 流程最小验证](plans/x0-whisperx-flow.md) — 已完成；运行前冻结两窗及三臂，按无回归条件停止扩展。

- Specs: [W0 可复用 demo 契约](specs/w0-reusable-demo.md) — 已实现；VAD／ASR／MMS 边界、完整文字与源坐标及验收范围。
- Demo: [W0 可复用入口](../experiments/w0_demo/README.md) — 后续 session 复用并更新的实现、离线运行和迭代流程。
- Testing: [W0 demo 验证](testing/2026-10-05-w0-demo-validation.md) — 独立端到端回归、数值配置约束及小样本边界。

- Research: [VAD 全景与 W0／X0 分片改进](research/2026-10-05-vad-landscape.md) — 探索性来源调研；VAD允许CPU／GPU、对白优先且歌声保留不扣分；比较检测与保留音频的断点策略，未更换基准线组件或执行新推理。
- Research: [成熟 VAD 来源核查](research/2026-10-05-established-vad-sources.md) — Silero、Pyannote、FSMN、NeMo、SpeechBrain 的发布、模型身份、语言和 Windows／GPU 边界。
- Research: [新兴 VAD 来源核查](research/2026-10-05-emerging-vad-sources.md) — FireRed、OmniVAD-Kit、TEN 的模型关系、维护记录、许可及部署限制。
- ADR: [未来 W0／X0 两条 STT 基准线](adr/0001-two-stt-baselines.md) — 历史采纳记录；两路线组织和W0移植要求保留，VAD与X0分段选择由ADR-0003更新。
- Plans: [Whisper 流程等价性与架构依据](plans/whisper-framework-equivalence.md) — 已完成；固定 Pyannote／MMS，源码核验与隔离等价性原型，不迁移正式架构。
- Research: [Whisper 长期架构选择](research/2026-10-04-whisper-framework-architecture.md) — 已完成；推荐faster-whisper＋保行为适配，含维护成本、反证和迁移门槛，不代表正式采用。
- Research: [Whisper 冻结VAD等价实验](research/2026-10-04-whisper-framework-experiment.md) — 已完成；两窗17块适配层ASR严格一致、46项VAD后处理一致，标准API不等价；MMS复用输入契约证据，未重跑。
- Research: [Whisper ASR 源码核验](research/2026-10-04-whisper-framework-asr-audit.md) — 已完成；三种生成路径、有效参数、特征处理及安装源码完整性。
- Research: [Whisper VAD／MMS 边界核验](research/2026-10-04-whisper-framework-vad-alignment-audit.md) — 已完成；原始VAD分数到窗口、MMS自研替换点及残留框架职责。
- Plans: [日语 CTC 候选补充实测](plans/japanese-ctc-supplement.md) — 已完成；固定上游文字，四窗筛查及五个组合的十二窗复验。
- Research: [日语 CTC 官方来源核验](research/2026-10-04-japanese-ctc-source-verification.md) — 已核验模型身份、blank／tokenizer 契约、日语 adapter 与许可；质量结论另见实测。
- Research: [日语 CTC 补充实测](research/2026-10-04-japanese-ctc-results.md) — 已完成；MMS补充W1／X0、Reazon补充X0、假名模型补充W0均有证据，保留严重偏移、粒度及许可取舍。
- Research: [Japanese CTC Forced Alignment 外部会话参考](research/2026-10-04-japanese-ctc-alignment-reference.md) — 保留外部会话原始建议的历史身份；后续官方核验和本机实测分别见以上报告。

- Plans: [W0＋VAD＋CTC 时间优先追加实验](plans/w0-vad-ctc-follow-up.md) — 已完成用户指定的独立追加，保持原评分并分别报告时间收益与内容代价。
- Research: [W0＋VAD＋CTC 追加比较](research/2026-10-04-w0-vad-ctc-follow-up.md) — 已完成同十二窗六配置对照；VAD 叠加未提高全分母时间成功，长尾与漏字存在取舍。
- Plans: [三候选单组件增量评估](plans/component-augmentation.md) — 本轮完成；保持原三基线，单变量筛查及扩展，未通过替换护栏的分支停止。
- Research: [新增组件与对齐器兼容性](research/2026-10-04-component-augmentation-sources.md) — 官方来源核查；Demucs、GPU VAD、Qwen FA、Canary 日语限制及现有 wav2vec2 身份，不代表质量已验证。
- Research: [组件增量实测](research/2026-10-04-component-augmentation-results.md) — 已完成；分离／VAD 回归，W0＋CTC 输入契约修复与时间收益、覆盖取舍，无新的总体优胜组合。
- Plans: [两片主参考固定候选复核](plans/two-film-stt-revalidation.md) — 已完成；五条固定配置、两片共 60 分钟同输入比较。
- Research: [两片主参考复核结果](research/2026-10-04-two-film-revalidation.md) — 已完成；保留原实验建议与分数，均未达到严格时间目标。
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
- Research: [开发集对比](research/2026-10-04-dev-comparison.md)
  — 完整分母的开发汇总和质量取舍；不代表验证或保留结果。
- Research: [第一轮固定验证结果](research/2026-10-04-validation-results.md)
  — 六配置完整分母、实际 GPU 证据、验证退化与保留配置锁定。
- Research: [固定保留测试结果](research/2026-10-04-heldout-results.md)
  — 五条预锁路线、完整分母与失败、独立审查和单独恢复敏感性。
- Research: [最终性能与重复性](research/2026-10-04-final-performance.md)
  — 两路线三次新推理、单次完整电影、实测墙钟和整卡采样限制。
- Research: [整片质量与连续性](research/2026-10-04-fullfilm-results.md)
  — 完整N1026的文字/时间、失败、源坐标与早中晚分布；不增加独立样本。
- Research: [实测结论与实施顺序](research/2026-10-04-stt-demo-conclusions.md)
  — 两条有明确取舍的实施方向、未达时间目标的证据及后续边界。
- Research: [开发集字幕显示检查](research/2026-10-04-display-analysis.md)
  — 固定 writer 重放、实际 SRT 文字覆盖与保留 sidecar 的区别。
- Research: [数字静音预检](research/2026-10-04-silence-preflight.md)
  — 全零输入的插入文字、VAD 空结果与接口失败分开记账。
- Research: [Whisper 执行准备](research/2026-10-04-whisper-execution.md)
  — 本轮接口、依赖约束和可复现适配器。
- Research: [Whisper 后续实现边界](research/2026-10-04-whisper-engineering-boundaries.md)
  — 已测机制、GPU/runtime 身份和后续加固范围；不构成采用或达标判定。
- Research: [W0 与标准 CTC 的有界探索](research/2026-10-04-w0-ctc-exploration.md)
  — 锁定后同文字对齐比较、验证长尾及停止扩展的证据。
- Research: [Qwen 执行准备](research/2026-10-04-qwen-execution.md)
  — 本轮原生 Transformers 接口、模型和限制核查。
- Research: [Crisp 执行准备](research/2026-10-04-crisp-execution.md)
  — 本轮 Windows 程序、模型、设备证明与适配器。
- Research: [模型资产获取记录](research/2026-10-04-model-assets.md)
  — 固定 revision、完整性校验、缓存复用与断点续传入口。
- Research: [Subtitle Edit 模型复用](research/2026-10-04-subtitle-edit-model-reuse.md)
  — 现有14个权重的发布身份核验、规划候选外部路径登记和预下载缺口检查。
- Research: [环境与复现清单](research/2026-10-04-runtime-inventory.md)
  — 七组资产、实际安装版本、许可来源与本机离线恢复配方。
- Research: [STT pipeline design reference](research/2026-10-03-stt-pipeline-design.md)
  — exploratory; entry point for research adapted from `subtitle-edit-fix`.
- Research: [Whisper and Qwen backend contracts](research/2026-10-03-stt-backend-contracts.md)
  — exploratory; fixed-version observations, not dependency selections.
- Research: [Model and backend candidates](research/2026-10-03-model-backend-candidates.md)
  — exploratory shortlist; no model or backend adopted.
- Research: [Timestamp failure cases](research/2026-10-03-timestamp-failure-cases.md)
  — concluded historical synthesis; no Kototoki repair validated.
- Research: [STT application comparison](research/2026-10-03-stt-application-comparison.md)
  — concluded historical comparison; implementation suggestions remain exploratory.
- Research: [Whisper demo readiness](research/2026-10-03-whisper-demo-readiness.md)
  — exploratory; newly checked upstream versions, Japanese alignment, VAD and
  native Windows GPU provisioning boundaries.
- Research: [Qwen and Crisp demo readiness](research/2026-10-03-qwen-crisp-demo-readiness.md)
  — exploratory; newly checked API/artifact identities, packaging, maintenance,
  and controlled versus native-pipeline experiments.

Migrated research is adapted prose, not a copy of the sibling project's task
state, permissions, or assets. Each document records sources and limitations.
Links to `../../../subtitle-edit-fix/` require that sibling checkout; original
experiment artifacts remain there and were not imported. External findings are
attributed to the original investigation dates, not newly verified by migration.

Current feature requirements come from explicit user requests and accepted specs
in `specs/` when written. Tasks and feature specs use the
[local Markdown tracker](agents/issue-tracker.md) under `.scratch/<feature-slug>/`
at the repository root. Feature specs link to existing accepted specifications
rather than duplicating them; durable changes belong in the relevant project docs.
Plans and research do not supersede requirements by themselves. For conflicts,
identify the applicable scope and linked superseding decision rather than assuming
the newest file overrides every older document.

Create subdirectories when a category becomes difficult to navigate. Add a new
top-level category only for a distinct recurring purpose, and update this
directory map in the same change. Keep root `CLAUDE.md` focused on reading
triggers; put detailed documentation rules in this index.


- Research: [五候选字幕翻译正式比较](research/2026-10-06-translation-model-comparison-results.md) — 三家族五版本固定 test；408/415 语义终分、条件化质量／性能建议、完整失败成本和复现入口。

- Plans: [Hy30 Q3／Q4 追加对照](plans/hy30-q3-q4-comparison.md) — 同固定 test、同原生模板、Q4 显式部分 offload；三次性能重复与全量 Sol/high 自动质量评估。

- Research: [Hy30 Q3／Q4 实测对照](research/2026-10-06-hy30-q3-q4-comparison-results.md) — 已完成；两候选各 83/83 终分，三次性能重复与 offload 控制；Q4 中位耗时 4.18 倍，质量收益有限且不稳定，用户当时保留 Q3 基线；当前 APEX-I-Compact 采纳见[ADR-0005](adr/0005-apex-i-compact-translation-baseline.md)。

- Testing: [APEX-I-Compact 基线采纳验证](testing/2026-10-07-apex-baseline-adoption-validation.md) — 当前基线入口、离线检查与新输出身份的本机 smoke 验证；不覆盖四量化历史报告或冻结证据。

- Research: [Hy30 流程参数核对](research/2026-10-07-hy30-flow-parameter-check.md) — 30B 官方采样与 native HTTP 映射、模板和资源实测边界。
