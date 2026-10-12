# VideoLingo 字幕翻译实现核查

状态：已完成源码调研；借鉴建议尚未采纳
最后更新：2026-10-05
范围：主题／术语、上下文、直译和润色、源译切分、时间映射、JSON 校验、重试与缓存。未运行翻译 API、ASR、TTS 或私有素材；不代表质量实测，也不将翻译纳入 Kototoki 当前 STT 里程碑。

## 版本与证据边界

本地来源为 `D:\AI_Projects\VideoLingo`。目录没有 `.git`；沙箱外只读 Git 检查同样返回 `not a git repository`，所以无法报告本地 HEAD、dirty 状态或整个目录的来源提交。未发现该目录内的 `AGENTS.md`。

2026-10-05 通过官方 GitHub API 核验：最新 `main` 是 [01f843492759be9bbfd1a5cb697b799cc9de1609](https://github.com/Huanshere/VideoLingo/commit/01f843492759be9bbfd1a5cb697b799cc9de1609)，提交时间 2026-09-30；最新发布是 [v3.1.1](https://github.com/Huanshere/VideoLingo/releases/tag/v3.1.1)，发布时间 2026-09-27，对应提交 [11ca23ebb2639f9c24cd115b56c9c93997df5608](https://github.com/Huanshere/VideoLingo/commit/11ca23ebb2639f9c24cd115b56c9c93997df5608)。本文引用固定 `main` 提交，不声称发布版所有文件相同。

逐文件取官方固定提交源码，与本地文件统一 CRLF/LF 并去掉末尾空白后比较，以下 14 个文件全部一致：`core/prompts.py`、`core/_4_1_summarize.py`、`core/_4_2_translate.py`、`core/translate_lines.py`、`core/_5_split_sub.py`、`core/_6_gen_sub.py`、`core/utils/ask_gpt.py`、`core/utils/decorator.py`、`core/_3_2_split_meaning.py`、`core/_8_1_audio_task.py`、`config.yaml`、`core/pipeline.py`、`core/_2_import_subtitles.py`、`core/tts_backend/estimate_duration.py`。因此以下固定提交、文件和行号链接可以定位本次实际核查的代码；这不是整个本地目录的版本鉴定。

部分本地字节 SHA256，供后来复查（换行变化会改变字节哈希）：

| 文件 | SHA256 |
| --- | --- |
| `core/prompts.py` | `581370E1C91F90285015BC50709EAD89F3A51D95E9461FD40AC4CDDF9D1C048B` |
| `core/translate_lines.py` | `CEAB4B45F73CA79413CC713A25D2E42ECB4E802BEBF210702FC231F3FF6AE358` |
| `core/_5_split_sub.py` | `DDE160B6EE9FBED445BDD5ADB5A194C715E2458488A4793A615A4464E454D8CD` |
| `core/utils/ask_gpt.py` | `3D9BB9E35E22FB501F90D3E6602E18CFE69913412864D6DAC2F0FCD1465F6945` |

## 实际数据流

源文本／词时间 → NLP 与 LLM 切句 → 主题与术语 → 多行块直译 → 可选反思及自然改写 → 按时长缩短译文 → 超长字幕源译共同切分 → 用源文词时间生成单语／双语 SRT。人工复核点位于术语完成后和翻译完成后。[流程入口](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/pipeline.py#L14-L24)

这里的“对齐”有两种含义：LLM 负责源译文本分段对应；音频时间沿用源语言词时间。不能把二者混同为目标语言 forced alignment。

## 主题与术语：全局准备，实际只看开头

`combine_chunks` 将切句文件拼为一串，然后只截取前 `summary_length` 个字符；当前默认 8000。因此它不是完整长视频的全文摘要，后段人物、术语和主题变化可能不进入首次全局准备。[截断代码](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_4_1_summarize.py#L9-L15)、[默认值](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/config.yaml#L94-L110)

提示词要求两句主题摘要、少于 15 个专业术语／名字，各项含 `src/tgt/note`；已有自定义术语要求不重复提取。读取 `custom_terms.xlsx` 的前三列，转成字符串，LLM 结果后再 `extend` 自定义项。程序没有做冲突消解、去重或自定义项优先覆盖；“排除重复”依赖提示词。[摘要提示词](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/prompts.py#L53-L124)、[合并实现](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_4_1_summarize.py#L35-L68)

每个翻译块仅加入其源文包含的术语，匹配方法为忽略大小写的子串检索。它不能可靠区分同形词、词边界或屈折形式，也没有实体／角色库。主题则每块共用。自动摘要校验只查 `terms` 和条目键存在，不检查 `theme` 必须存在；人工术语复核开启时，会额外检查列表和字符串类型。[术语筛选](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_4_1_summarize.py#L17-L31)、[人工检查](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/pipeline.py#L47-L75)

## 分块、上下文和两阶段翻译

每块目标为 600 字符、最多 10 行；按完整句行累积，单条超长句可超过 600。上下文是前块最后 3 行源文和后块最前 2 行源文，另加主题和命中术语。块以线程池并行，当前 `max_workers=4`，没有前块译文反馈、逐块术语更新或全片末尾统一校对。[分块及上下文](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_4_2_translate.py#L16-L79)、[共享提示](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/prompts.py#L128-L142)

第一阶段按 `1…N` 行号 JSON 直译，要求保留原意、专业术语和上下文。第二阶段收到源文、直译及相同上下文，要求逐行反思流畅度、风格和简洁性，再产出自然译文 `free`；提示模板含 `origin/direct/reflect/free`。默认 `reflect_translate=true`；关闭则使用 `direct`。`translation_style` 在启用润色时加在第二阶段，否则加在直译阶段。两个阶段使用同一个配置模型，并非独立评审模型。[两阶段提示](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/prompts.py#L157-L263)、[结果选择与回退](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/translate_lines.py#L46-L98)

润色调用失败会退回直译，停止任务例外继续抛出。`reflect` 不是强制检查字段，也未作为另一轮判定输入；实际必需字段只分别为 `direct`／`free`。这是一种提示式自我修改流程，源码不能证明质量比直译更好。[校验键](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/translate_lines.py#L10-L44)

## 源译对齐与字幕切分

翻译前的长句切分先由 LLM 给出两种 `[br]` 方案并选择一种。代码用 `SequenceMatcher` 将模型方案的分界映射回原句，再从原句切片，尽量防止 LLM 改写源文；低于 0.9 相似度仅警告。LLM 失败时机械切分，优先附近标点、其次空格；使用空格分词的语言不会强行切开一个词。方案检查要求存在非空分段，不严格核查请求的段数和字数。[切分及原文回映](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_3_2_split_meaning.py#L18-L114)

翻译完成后的显示切分：源文 `len(src)` 或译文加权长度 × `target_multiplier` 超过 `max_length` 才触发；当前默认 75 和 1.2。译文汉字／假名／全角符号权重实际是 1.75，韩文 1.5，泰文及其他字符 1；顶部注释的 2.5 等数字已经与实现不符。[长度与触发](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_5_split_sub.py#L17-L84)

先把源文切两段，再要求 LLM 按其语义对应切译文；为凑对应，提示词明确允许适当重写译句。校验保证目标段数恰等于源段数、各段为非空字符串；源译作为一组写回，失败保留原行。最多尝试三轮，仍超长也会保存，故长度不是严格硬保证。译文重新合并供配音用，显示版本保存切分行。[对齐提示](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/prompts.py#L268-L314)、[共同切分和保存](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_5_split_sub.py#L36-L120)、[三轮和输出](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_5_split_sub.py#L140-L177)

另有一个并非语义校验的步骤：汇总翻译块时对所有返回源串做相似度查找，低于 0.9 报错；但 `translate_lines` 返回的是传入源串，而不是模型回显的 `origin`。因此这个匹配不能发现模型在句中删改或串行。相同块或仅大小写／换行不同的块并列最高分时，查找可能复用首次返回的译文；代码已经带块编号却未直接按编号取结果。这是静态推导的风险，未用真实字幕复现实测。[相似匹配](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_4_2_translate.py#L81-L102)、[返回原输入](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/translate_lines.py#L92-L98)

## 时间、缩短与导入字幕

时间映射把源语言词文本去标点、小写后拼接，建立字符→词序号映射，再顺序精确查找每句源文，取首词 start 和末词 end；目标字幕继承同一时间。源文匹配失败直接抛错，纯标点句使用邻句间隙，可能产生零时长；若切在一个带时间的词内部，相邻片段可能共享词边界。源译语序不同也没有重新声学对齐。[时间查找](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_6_gen_sub.py#L59-L113)

字幕输出时，0～1 秒的正间隙被前一字幕延长填平；`duration` 列先计算、后改结束时间，因此用于其他处理的 duration 可能与显示跨度不同。显示译文会去中文逗号／句号，再写源语、目标语和两个顺序的双语 SRT。[间隙、清理及输出](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_6_gen_sub.py#L115-L153)

翻译阶段本身就按时长调用配音估时器：仅句时长大于默认 3.5 秒时检查，估计朗读时长／最大倍速仍超过窗口则请 LLM 缩短。结果只要求存在 `result`，没有缩短后重新估时或保义验证；异常回退为去标点。短而密集的句子反而跳过缩短。估时是字符／音节及标点系数，并非阅读速度实测。[调用位置](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_4_2_translate.py#L104-L115)、[缩短及回退](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_8_1_audio_task.py#L18-L44)、[估时器](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/tts_backend/estimate_duration.py#L75-L123)

导入 SRT 时，用原 cue 文本和时间替代识别／初次切句，词时间按文本长度均分，跳过显示再次切分。但原 cue 行内换行合为一行、格式标签去掉，纯符号和非正时长 cue 被过滤，生成阶段仍有上述间隙填平。配音任务还会合并／延长过短条目；这属于配音支路，不应误认为显示 SRT 通用合并逻辑。[导入规则](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_2_import_subtitles.py#L17-L106)、[跳过再次切分](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_5_split_sub.py#L143-L152)、[配音短句处理](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_8_1_audio_task.py#L102-L124)

## JSON、重试与缓存

统一 API 边界使用 OpenAI-compatible Chat Completions，可指向本机服务；请求为单条 user message，超时 300 秒，可按配置启用 JSON object 模式。解析器去除 `<think>`、从最后的 JSON 围栏开始尝试，再用 `json_repair` 修复；找到非空对象后返回。随后调用各阶段专用校验器，失败写 `output/gpt_log/error.json`。[API 及解析](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/utils/ask_gpt.py#L85-L149)

`ask_gpt` 装饰器设置 `retry=5`，实际为首次加五次重试，等待 1、2、4、8、16 秒；没有把验证错误附加到修复提示，而是重发原请求。翻译内部虽有三次循环并加空格改变缓存键，但异常不在该循环里捕获；所需键均筛到固定 N 项后，行数也自然相等。因此不能简单描述为“每个阶段固定 3×6 次修复”。结构检查通过后，字符串类型、空译文、`origin` 一致性、完整术语采用、目标语言和语义没有统一检查；`origin` 未校验却在日志／润色模板中访问，缺它可导致后续错误。[装饰器](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/utils/decorator.py#L12-L29)、[翻译校验和循环](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/translate_lines.py#L10-L44)

缓存写完整模型名、提示、原回复、解析回复及错误消息；进程锁保护 JSON 读写。命中条件只有日志类别下的精确 prompt 和 resp_type，**不包含模型、API 服务、参数、解析器版本或校验器版本**；命中后直接返回，未再运行校验。改变模型或加强校验可能复用旧结果。读取只返回第一条匹配；文件线性读写，规模变大也有成本。已完成摘要／翻译等阶段还会按输出文件存在直接跳过，未绑定输入哈希。[缓存实现](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/utils/ask_gpt.py#L20-L40)、[缓存优先返回](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/utils/ask_gpt.py#L105-L117)、[文件存在跳过](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/utils/decorator.py#L38-L47)

人工翻译复核可编辑 Excel 的 Translation 列，重新读取后检查源列／行数未改以及原非空译文未被清空；默认复核关闭，已有下阶段产物时跳过。这给流程提供可恢复的人工修正点，但不构成自动质量保证。[复核代码](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/pipeline.py#L78-L113)

## 对后续本地字幕翻译最有价值的借鉴

以下为建议，不是 Kototoki 已采用的实现：

1. 保留“主题／术语 → 带邻句上下文的块翻译 → 可选改写 → 显示分段”的阶段边界，保存直译与改写两版，失败可回退。
2. 长片用分层／全片覆盖的摘要与术语维护，保留人物名、称呼、指代和角色关系；不能只用前 8000 字符代表全片。
3. 句、块、cue 均使用稳定 ID 和源字符跨度；源译配对按 ID，时间始终来自不可变源跨度。把语义译文和显示重排分开，避免为了凑段数静默重写含义。
4. 校验 JSON 只是第一层；还需非空字符串、精确 ID 覆盖、源文不变、数字／人名／否定／术语检查，以及显式的疑似遗漏与添加标记。LLM 自我反思不能代替独立检查和人工抽样。
5. 缓存身份绑定输入哈希、模型／服务／生成参数、提示版本、术语版本和校验器版本；缓存返回仍过校验。各阶段完成文件需要内容清单，而不只检测文件存在。
6. 显示使用 CPS、最短／最长时长、最大行数、断行、间隙／重叠、说话人切换等约束；配音估时和字幕阅读约束分别定义。标注导入 cue 时间保留是否允许间隙调整。
7. 审查本地 LLM 的具体表现：此处只证实 OpenAI-compatible 端点接入方式。未测本机模型在日→中翻译、字幕口语、长片一致性和 JSON 服从上的可靠性，不能据代码结构推断质量。

## 验证与未覆盖项

已完成官方仓库网页浏览、官方 API 提交／发布身份核验、14 个关键文件逐项比对和源码静态审查。未安装依赖、修改 VideoLingo、运行其测试或调用任何推理 API；未读取／上传私有字幕与音频。本文所列失败模式除版本比对外均为代码观察或明确标注的静态推断，未计入翻译质量实测。仓库已有针对 JSON 解析、切分回退、润色回退和源译共同切分的测试，测试文件存在不等于本次执行通过。

所有外部链接访问日期：2026-10-05；来源为 VideoLingo 官方仓库源码和发布信息。后续升级需重新固定提交并复核实际调用链。
