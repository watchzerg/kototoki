# 字幕与文档翻译：上下文、语义单元与专用模型

状态：调研完成；方案建议，未实现、未采纳、未做本机翻译质量实验。

最后更新：2026-10-05。

范围：补充 Subtitle Edit、VideoLingo、pyvideotrans 之外的一手实践与论文；讨论日语→简体中文、上下文组织、字幕结构和翻译专用模型。所有外部链接访问日期均为 2026-10-05；动态模型卡/API 文档按本次读取内容记录，不视为冻结 checkpoint。项目当前里程碑仍是原语言 STT，本报告不改变 [README](../../README.md) 或现有 W0／X0 的边界。

## 结论与证据强度

较稳妥的后续实验起点是：**按完整句子／话轮组织待译正文，在有限窗口中提供相邻原文、可靠背景和相关术语，保留独立的源字幕映射，最后再检查中文显示与时间。** 这是下述证据的工程综合，不是已证明的日中最优配方。

有一手证据支持上下文帮助短句消歧、术语一致及段落质量；没有证据支持“文本越长必然越好”“把整部影片一次交给模型就能解决字幕”“JSON 必然降低翻译质量”。不同模型的输入契约差别很大，通用聊天 prompt 不能自动作为所有翻译模型的接口。

下文明确区分三类内容：**观察**指官方接口／源码／研究报告实际说明的行为；**研究结果**只在论文模型、语对、数据和指标范围内成立；**建议／推断**是待验证的 Kototoki 实验设计。

## 1. 主流翻译工具怎样处理上下文

**观察：DeepL 的批量请求不等于共享上下文。** 官方 API 明确说明，`text[]` 中各项独立翻译、按输入顺序返回，彼此不共享上下文；`context` 是影响译文、但本身不被翻译的额外文本；相关内容也可以放在同一个 `text` 中。[DeepL API](https://developers.deepl.com/api-reference/translate/request-translation)

其指南用邻接内容帮助多义词、语法指代和姓名拼写消歧；同一 `context` 会应用到该请求的每个文本项。文档翻译会自动使用较广的文档上下文。指南同时把背景正文与指令分开：`context` 不适合代替风格要求或术语强制规则，这些应使用专门的 custom instructions／glossary 接口。[DeepL context 指南](https://developers.deepl.com/docs/learning-how-tos/examples-and-guides/how-to-use-context-parameter)

**观察：专业 CAT 工作流没有要求把整份文档作为一个输出单元。** memoQ 12.5 以 segment 编辑，正文通常是句子，结构化内容可能是单元格或记录；允许 join／split，提供文档预览、translation memory 和 term base。确认的译文可进入工作 TM。这说明“译者能看到较大上下文”与“可追踪、可复用的翻译单元”可以并存；不证明某个 LLM 自动照做就有相同质量。[memoQ translation editor](https://docs.memoq.com/current/en/Workspace/translation-editor.html)

**观察：文档结构可通过中间表示保留。** BabelDOC 的 ACL 2026 论文将语义内容与页面布局 metadata 分离，在语义层拼接跨页／跨栏段落、抽取并使用 glossary，再将译文放回布局。可借鉴的是这种边界；PDF 几何恢复算法不是字幕时间恢复算法。上游 README 仍声明主要关注英语→中文，其他情境未充分测试，因此不能据此推荐其日中字幕质量。[BabelDOC 论文](https://aclanthology.org/2026.acl-demo.25.pdf)、[官方仓库](https://github.com/funstory-ai/BabelDOC)

## 2. 语义翻译单元与字幕显示 cue 应分开理解

**观察：一条 cue 可以只是一句的片段。** Netflix 简中规范明确讨论同一句横跨连续字幕，要求姓名一致、按语义处理断行，并规定该平台的每行 16 字、成人 9 字／秒等显示规则。这些是 Netflix 交付要求，不能无条件当成 Kototoki 的默认标准；它们证明显示尺寸与句义不是同一个约束。[Netflix 简中 Timed Text Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215986007-Chinese-Simplified-Timed-Text-Style-Guide)

**研究结果：已有成熟级联路线保留源时间模板。** AppTek IWSLT 2025 §2.3 将可能跨多个 subtitle blocks 的句子送入 MT，再约束译文回填到相同 block 数量与大致相对大小，源 block 时间保持固定；§4 用时长和阅读速度决定可用文字空间，通过模型长度控制和局部重译处理拥挤字幕。其研究是英语→德语／阿拉伯语和自有 NMT，不是日中 LLM 实测。[AppTek 2025 论文](https://aclanthology.org/2025.iwslt-1.21.pdf)

2019 年同团队已把若干连续短字幕拼接后翻译、保留分隔标记，并另用模型预测合适的行／块边界；研究观察到包括代词消歧在内的收益。这支持“完整语义＋局部上下文＋结构恢复”路线，而非永久锁死逐 cue 的孤立翻译。[Customizing NMT for Subtitling](https://aclanthology.org/W19-5209.pdf)

**建议：字幕方案应保留两种可比较路线。** 一种按上述 source-template 方式合句翻译、回填原 cue；另一种允许在原词／句的时间跨度内重新分配中文 cue。前者便于保持现有编辑成果，后者更自由但需要独立的映射与同步验证。不能仅按汉字数量比例切译文就声称解决了语义时间：语序变化、否定和重点位置都可能让字符比例对应错误。不得让翻译模型凭空生成新的声学时间戳。

## 3. 有上下文，不等于一次输入巨量文本

**研究结果：段落确实可能优于孤立句子。** WMT 2023 的文学翻译研究对 GPT-3.5 `text-davinci-003`、18 个语对做人工评价，整段翻译较逐句翻译减少误译、语法和风格问题；仍有严重错误与漏译。其范围是文学段落，包含日语相关语对，不能外推为整片日中字幕的最优长度。[WMT 2023 研究](https://aclanthology.org/2023.wmt-1.41/)

EMNLP 2023 的文档翻译研究比较多轮逐句与连续多句输入，发现上下文和术语／零代词处理可受益，也观察到模型有时丢掉句间标记并合句；其中文→英文与英语→德语结果不证明日中效果。[Document-Level MT with LLMs](https://aclanthology.org/2023.emnlp-main.1036.pdf)

**建议：独立控制“待译正文大小”和“只供参考的上下文大小”。** 例如正文是一个完整话轮，参考是前后若干话轮；不要把大量历史都标成需要输出的正文。按场景、说话人交接和完整句边界建立窗口；超长句可拆语义分句，但应保留同句关联。具体 token／句数应作为实验变量，不能从上述论文臆造一个通用的 30 行、100 行或 2 分钟最佳值。

窗口预算需同时容纳输入、背景、glossary、聊天模板与预期输出。模型架构标称长度、推理服务实际 `n_ctx`、生成上限和有效翻译长度分别记录；权重能加载也不证明长窗口的 KV cache、延迟及输出覆盖合格。

## 4. 标题／简介、滚动摘要和术语记忆

**标题与简介：建议作为低成本先验，不能代替邻接对白。** 可靠的视频标题、用户提供的简介、体裁和领域可帮助区分谈话主题；简介可能是宣传文字，甚至包含对白当时未知的信息。应标记为背景，并仅在与原文一致时用于消歧；人名表应给出源写法、已批准译法和来源。Hy-MT2 官方有背景信息模板，DeepL 有显式背景接口；本次没有找到能证明“视频标题＋简介”在本项目日中字幕上必然提升的独立评测。

**研究结果：摘要式上下文有具体但有限的证据。** ACL 2024 CAP 先选相关句、摘要，再从平行语料库取示例，用示例指导翻译；它不是仅把滚动摘要直接附在每段 prompt。Table 1 的 Qwen-1.8B-Chat 中，该方法低于 zero-shot，而较大模型有收益，不能忽略容量差异。[CAP 2024](https://aclanthology.org/2024.findings-acl.646.pdf)

**研究结果：有视频级历史与领域 memory 的研究系统。** ViDove v1 使用短期翻译历史／视觉音频线索和长期领域知识，组合翻译、校对、编辑 agents；实测主要用 Gemini-2.5-flash 与 GPT-4o。领域 memory 消融在其 StarCraft 子集改善 BLEU／SubER，却略降低 BLEURT；不是日中、本地量化模型或单独滚动摘要的验证。不能将整套系统收益全部归因于 memory。[ViDove v1 §3.5、§5.4](https://arxiv.org/html/2507.07306v1)

**建议：分清三种记忆。** glossary 是有来源的短语／人名译法；TM 是已确认的源译句对；summary 是有损的事件／指代／话题记录。优先检索当前正文确实涉及的 glossary 和已确认 TM，再评估 summary 的增益。摘要应附源范围、未知项和置信限制，定期回看原文；不能把一次错误译文升级成后续整片必须遵守的事实。TM 对相同短句也要带场景信息，例如同一个日语应答在不同情境下并不总有相同中文译法。

## 5. 专用模型与提示词接口

用户随后指定三个本地重点候选；完整模板、伪代码、多段与 JSON 边界见[专项模型对比](2026-10-05-local-translation-model-comparison.md)及其三份详细报告。本节保留较宽的候选背景。

本节是候选身份与接口核验，**不是模型质量排名，也未确认本机显存、Windows 后端、量化质量或运行状态。** 官网／模型卡的自家 benchmark 只能作为候选线索。翻译专用模型不等于都禁止额外条件：应逐模型检查其受支持输入，避免把 TranslateGemma 的限制错误套到 Hy-MT2。

### Hy-MT2 与旧 Hunyuan-MT／HY-MT

官方记录分别在 2025-09-01 发布 Hunyuan-MT-7B／Chimera、2025-12-30 发布 HY-MT1.5、2026-05-21 发布 Hy-MT2；当前不应把 1.5 写成最新。[官方仓库发布记录](https://github.com/Tencent-Hunyuan/Hy-MT2) Hy-MT2-7B 卡列出日语／中文，Apache-2.0，无默认 `system_prompt`，中文 prompt 使用完整中文语言名。它提供普通翻译、术语、风格、背景、分隔符和结构化数据任务的模板；这直接反驳“该专用模型只能接收一种裸翻译 prompt”的绝对说法。[Hy-MT2-7B 官方卡](https://huggingface.co/tencent/Hy-MT2-7B)

7B 官方推荐采样为 `temperature=0.7`、`top_p=0.6`、`top_k=20`、`repetition_penalty=1.05`，输出上限示例为 4096。建议先以官方接口建立控制，再单独比较确定性解码、额外字幕条件和输入窗口；不要默认低 temperature 更准确。本次进一步核查发现，[官方仓库部署说明](https://github.com/Tencent-Hunyuan/Hy-MT2#inference-and-deployment)明确写有 `max_context: 8192`；后续窗口预算应先按这个使用说明设置并预留输出。配置里的 `max_position_embeddings=262144` 只证明配置容量，不能覆盖该用法说明，也不能作为 Subtitle Edit 实际 `n_ctx` 或整片有效质量证据。[官方配置](https://huggingface.co/tencent/Hy-MT2-7B/raw/main/config.json)

用户已有的 `Hy-MT2 7B (Q8_0)` 应记录确切 GGUF 来源、哈希、chat template、llama.cpp 版本和服务参数后再实验；官方 GGUF 存在，Q8_0 文件列为 7.98 GB，不能仅凭 UI 标签假定本地文件就是官方产物。[官方 GGUF 卡](https://huggingface.co/tencent/Hy-MT2-7B-GGUF) 先检查正常正文翻译，再一次增加背景／glossary／结构要求；长通用指令可能增加任务冲突，是待测假设，不能据历史现象直接判定它造成质量下降。

### 其他候选

| 候选与本次核验身份 | 官方输入契约／长度含义 | 日中、本地与许可边界 |
| --- | --- | --- |
| Hy-MT2-7B／官方 GGUF，2026-05-21 发布 | 翻译 task prompt，可单独加入术语、风格、背景和结构规则；官方仓库用法 `max_context: 8192`，示例输出上限 4096；配置容量 262144 不代表实际服务／有效翻译容量 | 日语与中文在官方语言表；本地权重，Apache-2.0；本机 Q8_0 质量与 GPU 运行未测。来源见上文 |
| TranslateGemma 4B／12B／27B，2026 年系列 | 官方卡写总输入 **2K tokens**；仅 user／assistant，单个 content item 提供 `source_lang_code`、`target_lang_code`、待译 `text`；text 应只含待译内容；其他 prompt 用法明确未获官方支持 | 日语／中文为支持语言；本地开放权重受 Gemma terms 约束，不是 Apache-2.0。语言支持不证明日中字幕质量排名。[Google 官方卡](https://huggingface.co/google/translategemma-12b-it) |
| Qwen-MT plus／flash／turbo／lite，官方指南更新 2026-09-28 | 单条 user 消息与 `translation_options`；支持 terms、domain、TM；不支持多轮／system role。Plus 页面列输入 8192、输出 8192、总长 16384；其他型号不可直接沿用 | 官方云 API 支持日语、简中／繁中；没有在这些来源核验到可下载本地 Qwen-MT 权重，不与通用 Qwen 权重／许可混同。Flash 为厂商一般建议，Turbo 不再更新，均不等于独立日中排名。[官方指南](https://www.alibabacloud.com/help/en/model-studio/machine-translation)、[Plus 信息](https://www.alibabacloud.com/help/en/model-studio/qwen-mt-plus) |
| NLLB-200-distilled-600M，Meta 官方卡 | seq2seq 通过语言 token 配置，不是聊天 prompt；训练输入未超过 512 tokens，长输入可能退化，512 不是通用架构硬上限；官方不以文档翻译为用途 | 可下载，CC-BY-NC-4.0，研究用途、不面向 production deployment；日语→简中 tokenizer 代码为 `jpn_Jpan`→`zho_Hans`，实现时核对版本。[Meta 卡](https://huggingface.co/facebook/nllb-200-distilled-600M)、[官方 Transformers 集成](https://huggingface.co/docs/transformers/model_doc/nllb) |

**推断：先研究既有 Hy-MT2-7B 的接口最有针对性。** TranslateGemma 是可作本地对照的专用系列，但其官方模板不能直接附加任意角色指令或背景段；那将是另立身份的非标准 prompt 实验。Qwen-MT 的专门术语／TM／domain 参数适合借鉴接口设计，云服务不能自动成为本地方案。NLLB 更适合受控句级研究对照；其许可证与官方用途限制使它不能直接成为产品默认建议。上述候选的实际日中优劣只能由冻结配方和人工评价确定。

## 6. JSON 约束与质量应分别验证

**观察：三件事不能混称“JSON 模式”。** API 请求本身用 JSON 包装；prompt 请求输出 JSON；解码器用 grammar／schema 屏蔽不合法 token，是三个不同层次。TranslateGemma 官方请求结构包含源语／目标语字段，但输出是译文，这不等于要求它生成 JSON。Hy-MT2 明确提供结构保持任务，也不能因此假定每种 schema 都可靠。

**研究结果：结构约束存在取舍，但不是翻译定律。** RANLP 2025 比较 11 个模型，观察到 instruction-tuned 模型在部分生成任务下受约束解码性能下降，base 模型有时收益；实验任务是 QA、事实生成、分类与指令遵循，未测试日中字幕或 Hy-MT2。其结果支持同时测内容质量与格式合格率，不能拿来宣布 JSON 普遍降低翻译质量。[The Hidden Cost of Structure](https://aclanthology.org/2025.ranlp-1.124.pdf)

**建议：把元数据更多留在程序端。** 待译单元有稳定 ID，时间和原 cue 映射由程序保存；若单条调用只输出译文，程序可自行装配对象。批量输出需要 ID／schema 时，检查 ID 集合、重复、缺失、顺序、空译文、未译日语及截断，而不只检查 JSON 能解析。已知 grammar 可保证的语法性质不包括忠实度和完整覆盖。可修复结构时尽量不整段重译，以免已正确译文在重试中漂移；单条恢复失败也必须在全分母里记账。

## 7. 日语→简中实验建议

零代词研究在日语→英语与中文→英语中表明篇章上下文可帮助恢复省略项；日语和中文都允许省略，因此不能直接推导“翻成中文必须补足每个主语”。[零代词与篇章翻译研究](https://aclanthology.org/D19-1085/) 建议保留自然省略，仅在中文表达需要且邻接证据充分时补明人物；没有证据时不要编造性别、施事者或人物关系。

建议把问题分成可配对的实验，不一开始同时更换模型、量化、窗口、prompt 与回填策略：

1. 同一冻结日文输入，先比较逐 cue、完整句／话轮、完整句＋邻接上下文；正文与参考分开标记。
2. 在固定正文策略上，依次加入可靠标题／简介、相关 glossary、已确认 TM；summary 单列，测试收益与错误传播。
3. 同一模型按其官方接口比较纯译文、最小 ID 输出、JSON schema；同时报告翻译质量、覆盖、重试率、错误恢复和总耗时。
4. 固定译文后比较保持源 cue 模板与允许重排中文 cue，独立检查否定、主客体、数字、人名、语气、跨 cue 连续性及语义出现时间。
5. 用日语省略主语、跨 cue 句子、问答、人物称呼、政治／技术术语、歌词／重复语句和口误构成小型人工审查集；通顺与忠实分别评分，保留有歧义例子。

显示压缩另设开关：简中字幕受阅读速度约束时可能需要压缩，但原文完整语义译文应保留为审查依据。不得把“只输出译文”误写成禁止自然改写，也不得把“自然中文”写成允许增添情节。示例条件可压缩为“译成简体中文，保留意思、否定、数字和称呼；保持对白语气；仅输出译文”，再按模型接口添加有证据的背景与术语；该示例是待测建议。

本轮只完成公开文档与论文核查：未下载模型，未发送用户字幕／音视频到外部服务，未建立翻译入口，未改变 STT 配方。质量、资源和最佳窗口仍需本地实测；云端 API 仅作接口实践参照，使用私有字幕需另有用户明确请求。
