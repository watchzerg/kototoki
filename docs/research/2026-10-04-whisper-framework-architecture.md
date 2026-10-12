# 同一 Pyannote／MMS 条件下的 Whisper 架构选择

> 2026-10-05 后续开发入口：本文结论与未完成项描述的是2026-10-04研究范围。随后已建立 [W0 可复用 demo](../../experiments/w0_demo/README.md)，独立 Pyannote／ASR／MMS 的两窗端到端对照通过，见 [新增验证](../testing/2026-10-05-w0-demo-validation.md)。继续开发应复用并更新该 demo；无 WhisperX 安装的新环境及正式迁移仍未验收。

状态：已完成；架构建议为 A＋保行为适配层，不构成正式后端采用  
最后更新：2026-10-04  
范围：Kototoki 在原生 Windows／RTX 5080 上的长期本地日语转写；不含降噪、人声分离、说话人标注或翻译。

后续决定：用户先确认W0（faster-whisper＋Pyannote＋MMS）和X0（Qwen固定30秒、无VAD＋MMS）两条基准线，
均无降噪及人声分离，历史决定见[ADR-0001](../adr/0001-two-stt-baselines.md)。2026-10-05 整片比较后，用户再明确采用两条新 Pyannote＋MMS 基线，见[ADR-0003](../adr/0003-new-pyannote-baselines.md)；W0 仍须保留 WhisperX 切分合并、独立无时间戳解码及特征处理，X0 仅采用兼容 Qwen 的流程。本文保留研究时的旧ID、结论和证据边界；canonical demo 的执行默认仍待迁移，确认方向不等于正式迁移完成。

## 大白话结论

**长期建议以 faster-whisper 为基础，自己掌握 Pyannote 分段和 MMS 对齐的流程，但保留一层明确的兼容适配。**
WhisperX 有值得保留的处理方法；当前证据不要求把整个 WhisperX 框架作为长期底座才能保住这些方法。
不能把它换成一次标准 `transcribe` 调用：那样会改变实际行为，本轮对照已经看到了不同文字。

这不是因为 WhisperX “没做什么”。它的切分合并、独立无时间戳解码和特征处理都影响结果。
关键是这些差异已能列清，并且适配原型在两片10分钟、17块上复现了全部特征、token和分段结果。
项目最棘手的 MMS 输入契约与标准 CTC 时间语义又已经由自研代码承担。
继续基于 WhisperX 修改，会继续同时维护上游流程与本项目对它的替换点；A 可以将这些边界变为显式接口。

**这个建议不是立即卸载许可。** 本轮没有建立完整的、完全不安装 WhisperX 的三组件产品实现；
独立 ASR 与 VAD 后处理已验证，MMS 仍沿用现有实现，原生字幕cue兼容和新环境部署尚未迁移。
近期保留已测 WhisperX 作为基线与回归参照，按文末门槛分步抽取。

## 本次问题与证据分层

比较对象为 **A：faster-whisper＋自有 Pyannote 流程＋MMS jpn** 与 **B：WhisperX＋Pyannote＋同一 MMS jpn**。
A 必须区分“直接调用未修改的标准 API”和“使用 faster-whisper／CTranslate2 的保行为适配层”。
两者不能混称，否则会掩盖窗口、特征及解码逻辑变化。

旧 W0 没有外部 VAD，保留 Whisper 时间戳和标准回退；旧 W1 使用外部 VAD 窗口及无时间戳的独立解码。
[两片旧成绩](2026-10-04-two-film-revalidation.md)与[后续 MMS 成绩](2026-10-04-japanese-ctc-results.md)
保留原实验身份，不能证明 WhisperX 框架比等价自研流程更准，也不能将全部收益归因于 VAD。

本报告区分四类证据：本机源码事实、实际运行观察、同输入的等价性推论、未来迁移门槛。
研究建议只影响下一步设计方向；没有改默认后端、升级推理环境或覆盖旧结果。

本机基线是 WhisperX **3.8.6**、faster-whisper **1.2.1**、CT2 **4.8.2**、Pyannote Audio **4.0.7**、
Torch／TorchAudio **2.8.0+cu128**、Transformers **4.57.6**。
large-v3 权重来自 `Systran/faster-whisper-large-v3@edaa852ec7e145841d8ffdb056a99866b5f0a478`；
MMS 为 `facebook/mms-1b-all@3d33597edbdaaba14a8e858e2c8caa76e3cec0cd`＋`jpn`。
WhisperX 打包 VAD 是5秒训练窗的 PyanNet，不能以另一份“Pyannote VAD”替代后仍称同条件。
核验时官方稳定版仍为 WhisperX3.8.6／faster-whisper1.2.1；3.8.7rc1 的环境约束变化单列于 ASR 审计，未安装。

完整差异表按职责分为两份，包含源码行号、实际影响、直接实现成本与运行证据：

- [ASR 逐项表](2026-10-04-whisper-framework-asr-audit.md)：标准 `transcribe`、原生 batch、自定义生成器；特征／补齐、提示、上下文、有效解码参数、静音／回退、token与底层实现完整性。
- [VAD／MMS 逐项表](2026-10-04-whisper-framework-vad-alignment-audit.md)：checkpoint／滑窗预处理、阈值／min-cut／merge、源坐标、MMS文字／窗口／tokenizer／adapter／归一化／CTC／输出，以及失败和依赖边界。

## 本轮最小实验证据

独立身份为 `.local/framework-equivalence/v1/`；可复现代码位于
[`experiments/framework_equivalence/`](../../experiments/framework_equivalence/)。
选样在运行前固定为 II／III 各 window-01，600秒，同一 large-v3、CUDA FP16、beam5、日语、batch1。
Pyannote 只运行一遍并保存原始分数，两条 ASR 接收同一份未舍入的源音频裁剪。

| 检查 | 观察 | 能支持什么 |
| --- | --- | --- |
| 自研适配层 vs WhisperX | 17/17 特征逐元素及字节精确相同；prompt、CT2有效kwargs、生成token、文本、3位小数边界、avg_logprob全部严格相同 | 当前配置与所测片段的ASR行为可独立复现；不是只比较分数接近 |
| 未修改的标准 `transcribe`，同块且温度0／无时间戳／无前文 | 只有7/17块全文相同 | 标准入口不是现有W1的可直接替换接口；这条诊断也不是旧W0默认配置 |
| 未修改的原生 `BatchedInferencePipeline`，冻结clip窗口／batch1 | 0/2窗口全文相同 | faster-whisper已经具备批量能力，但其默认特征和后处理不自动等于WhisperX |
| 独立cut/merge vs WhisperX | 同两份真实score，加44个合成／固定seed边界案例，46/46结果相同；覆盖75秒持续活动的min-cut | 迟滞、长段切分及合并可以复现；未证明所有输入／版本或独立新VAD加载等价 |
| 新WhisperX／适配层 vs 旧W1及MMS缓存 | 两窗的完整ASR segment（含avg_logprob）、MMS上游文字／窗口、PCM与源offset均一致 | 所测两窗可衔接原MMS证据；没有把不同识别结果的旧分数套给新输入 |
| 原素材保护 | manifest记录裁剪PCM文件前后hash一致；旧结果未覆盖 | 本轮只有独立产物，没有改音频或历史成绩 |

新ASR、VAD和API诊断总wrapper墙钟约151.7秒，包含两进程加载与多个对照调用，不是目标流水线吞吐。
本轮没有新增MMS推理，不能把缓存对齐计为新端到端性能。阶段计时和所有私有token／全文留在实验记录。

对于适配层与本次WhisperX，两条完整文字及窗口完全相同，框架替换引入的漏字、插字、重复和分段差异均为0。
这只说明两条路径一致，**不说明它们相对真实语音没有错误**。
两路送入同一MMS时不存在新增的文本／搜索窗变量；相同对齐行为是固定实现下的推论，不冒充本轮重新跑过两次MMS。

原生API差异也并非只有空白：相对WhisperX，II窗的标准／原生batch均有7替换、61删除、9插入，III为4／9／24；
这是**路径之间的文字编辑差异，不是真值CER，也不能直接称为真实漏听**。适配层对应两窗均为0／0／0。
采用既有评分器文字规范化后，标准API为11/17块相同，II全文S/D/I为6/55/3、III为2/0/2，说明差异并非只有空白和标点。
本轮生成最长80 token，没有触及CT2源码所示的224步上限；不能把本次API差异归因为生成触顶。

自研ASR进程未导入WhisperX，但使用了从已安装包冻结的mel矩阵资产，其与FW动态生成矩阵最大差为约`3.73e-9`。
所以“只换回FW默认特征”仍不是已验证替代；保行为迁移需要将该小型资产及来源单独管理。
这说明的是不依赖WhisperX运行时代码的复现能力，不是已经完成全新、无WhisperX安装环境的交付。

没有扩展到十二窗或重跑MMS，是因为本轮要回答的关键缺口——是否必须依赖WhisperX才能保留同块ASR和cut/merge——
已经得到实际复现。完整三阶段迁移尚未实施，扩大评分不会代替该实现及其回归。
旧W1＋MMS的342/590半秒成功与约12.207秒最大偏移仍属旧十二窗证据，**不能冒充本轮无WhisperX三阶段的成绩**，
也没有被适配层“修复”。

## WhisperX 的贡献应如何理解

WhisperX 不只是把两个模型串起来。它选择了外部语音边界、长段低分切分与短段合并、保留窗口内静音、
独立无时间戳解码，以及用识别窗口约束对齐的完整策略。它的价值主要在这些行为的组合。
[原论文](https://arxiv.org/html/2303.00747v2)支持 Cut & Merge 的研究动机和原实验收益，
但论文使用的模型、阈值、语种／数据集与本机不同，不能代替本任务的公平对照。
论文的批量吞吐收益也不能解释本机 batch1 的全部质量差异。

本机 ASR 由 WhisperX 的 `WhisperModel(faster_whisper.WhisperModel)` 与 pipeline 包装组成，
直接调用 CTranslate2 的 `encode`／`generate`；没有发现专属重新训练权重、额外声学网络、
修改后的 beam-search 内核或另一个必须依赖 WhisperX 才能调用的识别引擎。
安装记录校验与调用链证据以 ASR 审计为准；这不等于对所有历史环境或上游版本作保证。

最容易误判的三处：

- 配置含有 `temperatures`、`no_speech_threshold`、`compression_ratio_threshold`，不等于 WhisperX 自定义生成器真的执行回退或静音过滤。
- VAD 初始化的 `min_duration_on/off=0.1` 不是当前 cut/merge 的实际最短时长；被覆写的 pipeline 返回原始分数，随后另一个 binarizer 才执行阈值和切分。
- MMS 当前不是原版 WhisperX 的默认加载／对齐。项目已接管语言 adapter 校验、每窗音频归一化及最终标准 CUDA CTC 时间单位，但原版对齐和字幕结果整理仍有残留职责。

## 为什么推荐 A，以及什么证据会推翻它

按用户的标准，WhisperX 确实有重要流程，尤其是 cut/merge 与独立无时间戳解码；但没有发现当前启用路径中
“重要、有效、又无法有界复现”的隐藏识别内核。本轮运行证据把“理论上可以移植”推进到了固定配置下的实际复现。
这比仅依据源码短、项目热度或旧W0/W1分数作选择更有支持。

项目需要继续保留：同一Pyannote推理、cut/merge和原音频坐标、正确的mel输入、固定prompt及解码语义、
每块文字与MMS搜索窗的关联、完整原文与无时间内容。已自研的部分包括MMS语言加载校验、归一化、标准CTC、
最终时间单位与统一writer。当前不需要沿用说话人分离、翻译、多语种自动切换或原版CTC trellis作为产品时间依据。

**保留 B 的最强理由**是降低近期改动和回归建设成本：已经存在一条可运行基线，框架提供加载、分段、分句和结果结构。
如果项目不愿维护上述适配契约，直接保留固定版本WhisperX，比声称标准API等价后草率替换更稳妥。
如果后续十二窗／整片验证发现无法定位的文字差异、原生cue成为必须完全兼容的接口，或将来明确需要上游新增的复杂能力，
应重新评估保留更多WhisperX代码；当前小样本不排除这些反证。

反过来，“保留WhisperX就免维护”也不成立：当前最重要的MMS修复不来自stock路径，hook依赖上游内部调用顺序，
TorchAudio弃用与OOV时间语义仍由项目负责。长期可维护性的收益主要是**职责明确和独立回归**，不是减少几个文件或承诺更快。

## 维护成本不能用代码行数代替

| 责任 | A 自有流程需要承担 | B 继续修改 WhisperX 需要承担 |
| --- | --- | --- |
| 声学模型与运行时 | faster-whisper／CT2、Pyannote、PyTorch、Transformers／MMS 仍都需要 | 同样需要，并受 WhisperX 的组合版本约束 |
| VAD 窗口 | 固定 checkpoint、推理聚合、阈值、min-cut 状态机、合并与源坐标的回归 | 沿用实现，但升级仍要核查默认值和实际路径变化 |
| ASR | 维护小而明确的特征／prompt／generate 边界；升级核对内部 helper 与 CT2 语义 | 维护 WhisperX 自定义 generator 的未执行字段、特征与上游接口兼容性 |
| MMS | 现有自研加载、归一化、解码、OOV 与时间映射责任不会消失 | 同样的自研责任，当前还通过 hook／函数替换接入 WhisperX |
| 结果与异常 | 明确完整原文、无时间内容、失败记账、取消与生命周期 | 仍需补产品级边界；上游成功返回不代表没有漏字或时间错误 |
| 验证 | 首次抽取成本更高，需要证明保行为；此后边界可单独验证 | 初期改动较少；每次升级要验证组合流程与自研替换没有相互干扰 |

因此，移除 WhisperX 不会把三模型系统变成轻量的单模型系统，也没有天然的速度或显存收益。
如果只移除一层 import，却复制整个上游并长期追补所有功能，维护收益会很小。
自研的合理边界应只覆盖当前已采用的日语、单 GPU、固定策略，而不是重新造多语种、说话人或通用字幕框架。

## 最小迁移门槛（仅供未来采用，不在本任务执行）

任何移除依赖的建议都应经过以下顺序，不能一次同时换框架、VAD 策略、特征和 CTC。

1. **先冻结接口与基线。** 保存 PCM 与源 offset、VAD 原始分数及精确采样索引、ASR 特征／prompt／token、完整文字和对齐搜索窗。
   版本和模型权重必须一致；当前实验原始产物继续保留，WhisperX 可作为离线回归参照。
2. **只抽出 ASR。** 用已核验的无时间戳、无前文、单次 beam 路径替换 WhisperX generator；保持 batch1 与特征数值。
   在既有十二窗要求完整文字、token、分段／窗口相同。发现差异必须定位，不能只用平均 CER 相近放行。
3. **抽出 VAD 包装与 cut/merge。** 保留同 checkpoint 和 Pyannote 推理聚合；先对冻结 score 重放，随后做新 GPU VAD 对照。
   覆盖空音频／全静音、等于阈值、刚过30秒、持续长语音、短间隙、片尾和重复最小值，核对浮点秒到样本坐标。
4. **抽出已自研的 MMS 边界。** 将加载校验、音频归一化、emissions、标准 CTC 和原文位置映射改成显式调用，逐步替代进程级 hook。
   先保持现有 `attention_mask`、wildcard、blank、取整和失败语义，不顺手“修正”。核对完整 units、text-only、失败类别和完整分母时间指标，
   逐条检查原严重偏移是否原样保留；改善和退步都应另立行为变更，不用失去可测性冒充修复。
5. **最后处理输出及删依赖。** 既有统一 writer 按 `text/units` 生成 SRT，原生 `cues` 只保留为诊断；
   参见 [display 契约](../testing/demo-display-contract.md)与 [replay.py](../../experiments/display/replay.py)。
   因此可以优先验证内容时间和统一显示，而不把 WhisperX 的 Pandas／NLTK 分句当成必须复制的核心。
   如果仍对外提供原生 cues/native_evaluation，则另做等价回归或明确变更输出契约，不能静默删除。

正式移除前，还需在完全不安装 WhisperX 的隔离环境验证本地 checkpoint／mel 资产解析、无网络推理、异常与取消、GPU 释放及长音频连续性。
批量大于1、语言检测、其他模型、流式模式均不在本轮等价范围。
运行时／TorchAudio 解码器升级另开验证轮次，不能与依赖移除合并。

这一门槛的成本高于“删掉一个 import”，但每一步有固定输入和可比较输出。
这也是评估可维护性的依据：承担有限且可观测的行为契约，而不是依据上游文件短就认定简单。

## 共用的长期风险

1. 现有标准 CTC 使用已弃用的 TorchAudio 2.8 `forced_align`。无论选 A 还是 B，都要单独替换／维护并验证该解码边界；保留 WhisperX 不会自动解决。
2. 外部 VAD 漏掉的声音不会靠 MMS 补回；错误识别文字也可能被强制放进错误位置。旧 MMS 的严重偏移与完整分母失败必须保留。
3. 复现当前行为不等于证明当前行为最优。加入温度回退、调整 attention mask、修正窗口边界或更换解码器都应另立配置，不能夹在依赖移除中。
4. MMS 的模型许可身份与软件框架是两回事。A／B 使用同一权重，不会因框架变化而改变模型卡声明；详情见[已核验模型来源](2026-10-04-japanese-ctc-source-verification.md)。

## 研究入口

- [执行范围与验证原则](../plans/whisper-framework-equivalence.md)
- [隔离实验及复现记录](2026-10-04-whisper-framework-experiment.md)
- [ASR 源码与参数执行表](2026-10-04-whisper-framework-asr-audit.md)
- [VAD 与 MMS 源码／责任表](2026-10-04-whisper-framework-vad-alignment-audit.md)
- [当前候选与既有组件边界](../architecture/stt-candidate-pipelines.md)
- [Whisper 原实验工程边界](2026-10-04-whisper-engineering-boundaries.md)

外部一手来源访问日期：2026-10-04。
除上文论文外，CTranslate2 的职责与参数语义参见[官方 Whisper API](https://opennmt.net/CTranslate2/python/ctranslate2.models.Whisper.html)
及[固定 4.8.2 实现](https://github.com/OpenNMT/CTranslate2/blob/v4.8.2/src/models/whisper.cc)。
版本化源码及本机行号的完整差异表由配套审计记录提供。

## 本次完成与保留项

已完成固定版本调用链与源码完整性核验、两窗新GPU识别等价对照、46项VAD后处理对照、旧W1／MMS输入衔接核验，
以及新增脚本语法和受影响文档链接检查。另在项目Python环境验证了输出越界、覆盖既有实验、覆盖既有阶段结果三项拒绝行为；均在推理前拒绝。
ASR与VAD审计各由独立子任务完成，主报告另经ASR审计者只读复核。
没有重跑与本次隔离原型无关的全项目历史测试。

明确未做：新MMS推理、独立MMS移植、完全不安装WhisperX的新环境、十二窗／整片适配层复验、batch>1、
新的人工声学标注、取消／OOM等产品级故障注入。旧模型／依赖／默认后端／历史结果保持原身份。
这些边界限制“立即切换”的结论，但不妨碍根据已定位、已复现的核心差异选择长期自研方向。
