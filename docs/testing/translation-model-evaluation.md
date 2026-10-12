# 翻译模型评估

状态：持续维护；五候选正式 test 与报告已完成，结果保留缺分和证据限制。
最后更新：2026-10-07。
范围：日文到简体中文的字幕翻译评估，以及后续相关方法、实现流程与 demo 对比的文档导航。

本文是翻译模型评估的统一入口。详细规则和实验结果保留在各自文档中，通过这里串联；
当前实现属于独立固定窗口翻译实验，未将翻译接入 STT 产品流程。

## 当前已采纳基线

字幕翻译以 **Hy-MT2 30B-A3B APEX-I-Compact**（`hy-mt2-30b-a3b-apex-i-compact`）为基线，后续优化讨论与回归以此为准。原实验中的 Q3_K_M 仍是其冻结统计对照，历史报告不重新标记或重算。

- [ADR-0005：当前基线决定与固定配方](../adr/0005-apex-i-compact-translation-baseline.md)：模型身份、兼容引擎、采纳理由及优化边界；[ADR-0004](../adr/0004-hy-mt2-translation-baseline.md)保留此前 Q3_K_M 采纳历史。
- [基线 demo 入口与运行命令](../../experiments/translation_demo/README.md#当前已采纳基线)：完整 smoke 命令及运行产物。
- [四量化正式比较报告](../research/2026-10-07-hy30-four-quantization-results.md)：当前采纳所依据的质量、交付、性能与正式长跑证据及结论限制；此前[五候选报告](../research/2026-10-06-translation-model-comparison-results.md)保留历史范围。

## 评估库

- [翻译模型评估库 v2：说明与纳入范围](D:/subtitle-samples/翻译模型评估库_v2/README.md)
  —— 当前参考库入口，包含字幕清洗、分轨、抽样、修订和排除结果。
- [v2 评测规约](D:/subtitle-samples/翻译模型评估库_v2/评测规约.md)
  —— 数据划分、模型输入隔离、评分建议、运行与版本冻结规则。
- [电影目录与纳入状态](D:/subtitle-samples/翻译模型评估库_v2/电影目录与纳入状态.csv)
  —— 各电影的文件位置、计分规模与隔离状态。

以上链接指向本机 `D:/subtitle-samples/` 中的外部数据目录，未将字幕和评估库复制进仓库；
在其他机器上使用时，需要另行提供该目录或调整路径。

v2 固定集包含 11 部动画剧集及 4 部动画电影的抽样片段，共 124 个窗口、618 条计分字幕。
另有《天气之子》候选字幕，因日文源质量问题暂不计分。smoke 为 dev 的子集，不能重复计分；
具体名单、规模和取舍以对应版本的库说明及清单为准。

参考译文经过两轮 LLM 文本复核，未核验音画，不是人工审定金标准。
整集／整片清洗候选未经全量语义审核，不能直接全部作为标准答案。

## 评估方法

**后续评估已有翻译、比较模型或复核裁判结果时，agent 必须先读并执行
[字幕翻译自动评估流程](../agents/subtitle-translation-evaluation.md)。**
这是用户采纳的 `sol-high-auto-v1` 流程：全量机械检查 → `gpt-6.1-sol / high` 全量主评
→ 同模型全新请求独立复评（风险窗口＋固定抽样）→ 程序汇总；不安排人工抽查。
复评是同模型重复核查，不代表不同模型家族的独立验证；无法解决的争议保留并影响排名结论。

该流程沿用 [v2 评测规约](D:/subtitle-samples/翻译模型评估库_v2/评测规约.md) 的数据隔离、
语义评分及作品等权口径，补齐自然度分档、复评抽样和失败／争议处理；不修改外部冻结库。
先用 smoke/dev 检查接口与裁判流程，再冻结配置，主评全部 test（当前 83 窗口、414 条计分），
分别报告电影和剧集成绩。整片 demo 与固定窗口模型比较分轨，详见流程。

现有库校验脚本继续复用；[离线评估器](../../experiments/translation_eval/README.md)已实现 packet、schema 校验、
复评选择、裁决编排和完整分母汇总，[裁判执行面](../../experiments/translation_judge/README.md)提供独立请求与恢复记账。
离线检查、五版本 smoke/dev 与自动评估闭环已完成。正式配方冻结后，完整 test 本地推理、主评、盲复评及必要裁决均已完成。
这些检查不证明裁判准确率。早期调研中的人工评审建议不作为本流程步骤。

## 翻译实现流程

- [第二轮C档探索计划](../plans/hy-mt2-translation-flow-exploration-v2.md)
  —— 当前执行入口：96筛选（72代表＋24风险，分开报告）及48独立确认，优先10作品；先校准裁判波动、修正批次位置与配置耦合，再自适应探索批大小、上下文及非JSON／语义流程。不设死总调用配额，不穷举。已冻结源／参考和判定规则，正在执行多seed筛选及新协议资格，尚未收敛，见[第二轮台账](../context/2026-10-08-hy30-flow-exploration-v2.md)。第一轮“充分收敛”的解释已更正，历史结果保持。

- [翻译模式优化计划](../plans/hy-mt2-translation-mode-optimization.md)
  —— 本轮有界筛选完成；[结果报告](../research/2026-10-07-hy30-flow-optimization-results.md)与[探索台账](../context/2026-10-07-hy30-flow-exploration.md)保留证据。固定 Hy-MT2 APEX 模型，主要比较仅8窗／40评分cue，完整流程交付范围为120cue；未产生可靠胜出方案，未启动独立确认或全片验证，未替换基线。没有全测试集合横向对比。

- [四套字幕翻译流程：共同设计与方案入口](../specs/subtitle-translation-common.md)
  —— draft；合并语义单元、多单元请求、上下文／术语、可选全文预分析、fresh／compact、返回映射、失败恢复与显示时间。
  四套均包含可选反思（审校→必要修订→再校验），支持关闭／按需／全量，审校和修订模型暂不固定为本模型或其他模型。
  四份模型流程分别为[通用语言模型](../specs/subtitle-translation-generic.md)、
  [Hy-MT2](../specs/subtitle-translation-hy-mt2.md)、
  [TranslateGemma](../specs/subtitle-translation-translategemma.md)、
  [Tower+](../specs/subtitle-translation-tower-plus.md)。
  原生契约与辅助模型成本分别记录；草案中的完整增强流程尚未全部实现，当前固定窗口实验子集见下方 demo。
- [字幕翻译调研：上下文、语义映射、恢复与评估](../research/2026-10-05-subtitle-translation.md)
  —— Subtitle Edit、VideoLingo、pyVideoTrans 的源码调研总报告，涵盖 SRT 输入、聚合分段、
  上下文组织、输出校验、字幕重组与质量评估，并链接各分报告；建议尚未采纳，未执行翻译质量实验。
- [本地翻译模型资产与复用入口](../guides/local-translation-model-assets.md)
  —— 九个候选 GGUF 已下载并通过文件大小与完整 SHA256 核验；包含本地路径、量化版本、
  固定 revision、机器可读清单和获取方式。实际加载／推理证据、兼容处理及未决映射见[执行记录](../context/2026-10-06-translation-comparison-execution.md)。

已实现[三家族、五版本本地 demo](../../experiments/translation_demo/README.md)，当前验证固定窗口实验子集。
草案区分历史协议复现 `V2-replay`、
显式声明原生接口适配的 `V2-native-adapted`，以及另行冻结长片输入／状态的 `P-flow`；
已完成的五候选固定窗口主比较采用 `V2-native-adapted`；当前第二轮 `P-flow` 已有独立运行器并在执行，
其源范围、复审策略、匹配对照和进度以第二轮计划／台账为准，不修改外部 v2 规约。
全文预分析、额外背景和滚动记忆不能混入原版 v2 窗口，中文参考不得进入翻译或任何辅助准备步骤。

## Demo 对比

执行入口：[三个翻译模型家族、五个版本的评估计划](../plans/translation-model-comparison.md)。
范围已确认：Hy-MT2 7B／30B-A3B、TranslateGemma 12B／27B、Tower+ 9B 的五个已下载量化版本；
三套 demo、smoke/dev 闭环与 `V2-native-adapted` 配方冻结已完成，完整固定 test 与[中文报告](../research/2026-10-06-translation-model-comparison-results.md)已完成。
开始实现或恢复本轮比较时，先读该计划、上方自动评估流程和[执行记录](../context/2026-10-06-translation-comparison-execution.md)，
再核对运行目录；不能由代码存在或原生段落交付推定映射、评估及正式比较完成。

[五候选正式结果](../research/2026-10-06-translation-model-comparison-results.md)已交付，包含逐作品／分类分数、严重错误、运行成本和复现入口。415 个候选窗口中 408 个有语义终分；6 个映射不可评、1 个裁决未决，比较为暂定。报告同时披露两项原始响应后写的追溯限制。

相关实验报告按日期存放在 `docs/research/`，运行说明放在对应 demo 的 README；
本文维护导航和当前状态，不重复维护每份报告的细节。

## 相关入口

- [文档索引](../INDEX.md)
- [STT 质量与性能评估](stt-evaluation.md)：音频转写评估的独立入口。

## 当前实现与接跑

2026-10-08当前配置采用`official30b-cached-v1`（官方30B采样、缓存、输出4096／总context8192），
见[采纳检查](2026-10-08-official30b-cached-baseline-validation.md)。这是用户决定及配置smoke，
不增加历史质量评估分母；旧B0与旧运行结果继续按原设置解释。

- [执行记录](../context/2026-10-06-translation-comparison-execution.md)：权威接跑状态、原始证据目录与未完成项。
- [三家族 demo](../../experiments/translation_demo/README.md)：九个量化版本本地推理（含 APEX-I-Compact、两款 imatrix 及官方 Q4）与辅助映射。
- [离线评估器](../../experiments/translation_eval/README.md)：逐窗口终态、复评选择、裁决和完整分母汇总。
- [裁判执行面](../../experiments/translation_judge/README.md)：显式 Sol/high 独立请求，CLI 限制与 fresh subagent 路径。

当前实现进度以各 README、执行记录和实际产物为准；开发闭环与正式 test 均已完成；质量解释、未决覆盖和证据限制以结果报告为准。

## Q3／Q4 追加对照

[2026-10-06 实测报告](../research/2026-10-06-hy30-q3-q4-comparison-results.md)：同一固定 test、同一原生输入，两候选各 83/83 终分；166 主评、96 盲复评、33 裁决全部完成。Q4 部分 offload 的三次中位耗时为全 GPU Q3 的 4.18 倍，剧集语义基本持平、电影样本有均分收益但未稳定区分。用户当时确认保留 Q3，历史决定记录于 [ADR-0004](../adr/0004-hy-mt2-translation-baseline.md)，现由 ADR-0005 的 APEX-I-Compact 采纳决定取代；报告另含样本时间范围与整片耗时估算，不作为整片实测证据。

## 四种 Hy30 量化的大规模追加比较

[四量化实测报告](../research/2026-10-07-hy30-four-quantization-results.md)覆盖该轮冻结基线 Q3_K_M、APEX-I-Compact、i1-Q3_K_L、i1-Q3_K_M：原 83 窗／414 IDs 单列，新增 1,200 个双轮复核冻结窗口／6,000 IDs，完成 `sol-high-auto-v1` 全量主评、必需盲复评及有界裁决；四轮性能和四款正式 30 分钟长跑均完成。Q3_K_M 每轮同窗失败，所有有效相对冻结基线速度均为 NA；失败、语义缺分、协议偏差和评审波动均保留。报告附逐作品／类别统计、资源曲线与[复现入口](../research/2026-10-07-hy30-four-quantization-results-appendices/reproduction.md)。[方案](../plans/hy30-four-quantization-comparison.md)与[执行记录](../context/2026-10-06-hy30-four-execution.md)保存范围和历史；用户在交付后明确采纳 APEX-I-Compact，见[ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md)。报告及附录保留交付时结论，不因新决定更改原评分或统计基线。
