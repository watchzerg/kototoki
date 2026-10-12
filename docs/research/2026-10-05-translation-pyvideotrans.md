# pyvideotrans 字幕翻译实现核查

- 状态：concluded（源码调研完成；翻译质量未实测）
- 更新／来源访问日期：2026-10-05
- 范围：本地 `D:\AI_Projects\pyvideotrans` 的字幕翻译、提示词、结果匹配与显示换行；与官方当前 `main` 作有限对照。
- 本项目范围：仅供未来字幕翻译设计参考；不改变 Kototoki 当前仅做原语言 STT 的里程碑。

## 版本与证据身份

本地目录没有 `.git`，因此不能报告它的 HEAD 或干净工作区状态。首次沙箱内 Git 读取被拒绝，随后按项目规则在宿主侧重试，返回“not a git repository”；目录内也未找到 `AGENTS.md`。`pyproject.toml` 声明版本 4.14，版本号本身不能标识源码快照。

为使结论可复核，逐文件读取官方历史版本，与本地内容作 CRLF→LF 后的区分大小写全文比较。翻译核心 `_base.py`、`_openaicompat.py`、`_qwenmt.py`、`_hymt2.py`、`_gemini.py`、`_localllm.py`、`_m2m100.py`，任务 `_base.py`、`_stage_translate.py`、`translate_srt.py`、`_stage_subtitle.py`、`_stage_align.py`，工具 `_srt_parse.py`、`_srt_wrap.py`、`help_misc.py`，以及本文所用 ChatGPT／中文／ASR 后编辑提示词，均与官方提交 **`1a41120fa805bbb279c12d13ae04ed576d42bdf6`（2026-09-29 00:34:47 UTC）**完全一致。以下 P 类链接使用该提交。[历史提交](https://github.com/jianchang512/pyvideotrans/commit/1a41120fa805bbb279c12d13ae04ed576d42bdf6)

这只是所列文件的匹配证据，不证明本地整个目录来自同一提交。本地 `configure/constants.py`、`configure/_app_settings.py` 全文不匹配该历史提交；它们的观察分别用本地位置注明。可选上下文关闭、文本批次 10／完整 SRT 批次 40 等相关值，也在当前上游源码中得到核对。[C4]

2026-10-05 查询官方 GitHub `main` 得到 **`9945754bbe6d7a7108eb7eee941311a87f89d69e`（2026-10-03 14:09:51 UTC）**。该版本已调整语言映射、字段归属、模型对象生命周期，并将 `_qwenmt.py` 的功能放到 `_bailian.py`；本文没有把它视为本地 HEAD。当前共用核心仍沿用下述固定批次、纯文本／SRT 输出和全片上下文模式。[当前提交](https://github.com/jianchang512/pyvideotrans/commit/9945754bbe6d7a7108eb7eee941311a87f89d69e)、[C1]、[C3]

## 核心结论

| 核查点 | 实际实现 | 能力边界 |
| --- | --- | --- |
| 上下文、标题、摘要 | 可选把全部原始 SRT 放入每个批次的提示词；支持手工术语表和目标语言规则 | 没有自动生成视频标题、摘要、角色表或滚动摘要的阶段；启用全文上下文会重复携带整片文本。[P1][P6] |
| 行 ID | 纯文本按位置配对；完整 SRT 带序号和时间戳 | 未采用独立稳定 ID 映射；解析 SRT 时重新编号。[P2][P4] |
| 结构化输出 | 普通文本，外包 XML 风格标签；可要求完整 SRT | 共用路径没有 JSON Schema、函数调用或受约束解码；标签和 SRT 是格式约定。[P2][P3] |
| 50→25 回退 | 启动时按固定 `trans_thread` 切批；部分接口对异常重试同一输入 | 没有观察到因漏行、超长或格式错误而自动减半批次的翻译流程；架构文档中的 50 与源码默认 40 不一致。[P1][P7][C4] |
| 漏译／照抄原文 | 文本少行补空行；SRT 块数不同时按时间戳字符串匹配，找不到置空 | 没有漏译逐项补译或源文相等检测；同样行数可能直接接受错误映射。[P2][P5] |
| 专用 MT | Qwen-MT 使用专用翻译选项；HY-MT2 用独立简短提示；M2M100 用语言 token 与原生批量接口 | 不把所有模型统一套复杂字幕提示；未找到 TranslateGemma 专用适配。[P9][P10][P11] |
| 换行与时轴 | 显示阶段字符／标点换行，保留条目时间；配音另有变速与时轴更新 | 显示换行不是翻译后的语义重新切条，也不是基于目标语音的强制对齐。[P12][P13] |

## 1. 上下文与提示词

`BaseTrans._set_context()` 读取 `language_prompts/{target_code}.txt`，再替换模板里的语言、语言规则和上下文占位符。启用 `aitrans_context` 时，它把 **`text_list` 的全部原始字幕**按序号、时间戳、文字拼成 `GLOBAL_REFERENCE_CONTEXT`；每次 API 请求再把当前批次替换进 `INPUT`。没有摘要生成请求、逐批对话历史或前批译文记忆。[P1][P3]

全文参考提示要求只借背景理解故事、代词、语气和跨批次句子，只翻译当前 `INPUT`。这是提示词约束，没有防止模型从背景复制额外字幕的程序校验。本地开关默认 `False`；当前上游同样默认关闭。[本地 constants.py:254](../../../pyvideotrans/videotrans/configure/constants.py)、[本地 settings.py:154](../../../pyvideotrans/videotrans/configure/_app_settings.py)、[C4]

`get_prompt()` 将用户维护的 `glossary.txt` 中 `source=target` 转成 Markdown 术语表，插入 `GLOSSARY_DICT`。这是显式固定术语，不是自动从视频提取术语或进行跨批次记忆管理。[P6]

纯文本模板要求输入输出行数一致、片段逐行翻译、不跨行搬词、口语化表达，且不给输出加行号。SRT 模板要求块数、序号、时间戳保持；不把同一句的成分挪到相邻条，断句片段以省略号衔接，并按条目时长压缩配音文本。中文规则进一步给出约 3–4 字／秒的目标和可省略的冗余成分。这些均是**模型提示**，没有代码计量译文语速或验证意义保留。[P7][P8]

因此该项目值得借鉴的是“区分全局参考与当前目标”“显式术语表”“按语言追加规则”；不能据此认定它已经解决语义漏译、人物称谓一致性或目标字幕阅读速度。

## 2. 映射、格式与校验

纯文本模式首先把每条字幕内部换行改成空格，再拼成每条一行的输入。返回值经过轻量清理后按 `\n` 拆开，按当前位置写回原始条目；原始时间数据随条目保留。返回多行时超出原批次长度的行被忽略，少行时在尾部补空行。若模型漏掉中间一行，后续文本可能整体前移，尾部补空不能恢复正确对应关系。[P1][P2]

完整 SRT 模式把原序号、时间、文字发送给模型，再把模型返回的 SRT 解析成新的条目列表。`srt_str_to_listdict()` 主要寻找时间戳行，随后按解析顺序设置 `line=len(srt_list)+1`，而不是保留原始序号作可靠键。输出 writer 也按遍历顺序重新编号。[P2][P4]

调用方的 `check_target_sub()` 只在**源／目标条目数量不同**时修复：把目标列表做成 `time → text` 字典，再遍历原列表，按完全相同的规范化时间字符串取文本；找不到就填 `''`。数量相同则直接返回目标列表，未逐项检查序号、顺序、时间戳或是否有空译文。相同时间字符串的重复目标条目在字典中会覆盖。[P5]

共用 OpenAI 兼容路径使用 `chat.completions.create`，读取 `message.content`，正则提取 `TRANSLATE_TEXT` 标签；标签缺失时接受整个返回字符串。Gemini 同样依赖标签，但无标签会抛异常，可触发接口级重试。两者均没有 schema 验证，也没有把业务结果定义成 `{id, translation}` 列表。[P3][P14]

以上是源码可直接观察的行为；“错位输入可能被接受”是基于这些分支的推论，本轮未以真实 LLM 注入或字幕样本运行验证。

## 3. 批次、重试与漏译

本地配置的文本批次是 `trans_thread=10`，SRT 批次是 `aitrans_thread=40`。虽然字段名含 `thread`，本轮查看的共用循环是串行处理批次，不能把它解释为 10／40 个并发请求。批次在 `run()` 开始时一次性切出，不依据 token 数、内容复杂度或失败类型动态改变。[P1][P2][C4]

OpenAI 兼容路径以 Tenacity 按 `retry_nums` 和固定 2 秒间隔重试可重试异常；认证、权限、部分连接／请求错误转换成停止错误。它重发相同 `data`，没有把 50 行切成 25 行或继续递归缩小。LLM ASR 后编辑的 `llm_chunk_size=50` 是另一个阶段的批次设置，不能当成翻译批次回退。[P3][P15][C4]

本地 `docs/architecture.md` 写了完整 SRT 默认 50；实际设置为 40，当前官方源码仍为 40。文档还把参数列名写成“并发数”，而共用实现实际上是每批条目数。本文以执行代码和设置为准。[P16][C4]

空译文的处理主要是补空或异常：纯文本仅在整份结果全部为空时抛错；SRT 每批空字符串会立即抛错，解析结果全部为空也抛错。局部空译文可以到输出阶段。没有观察到对 `translation == source`、目标语言错误、短感叹词遗漏进行检测，也没有将未翻译的源文作为显式失败状态保留。[P2][P5]

缓存键包括渠道、URL、模型、语言、发送模式和当前批次，**不包括提示词、术语表和整片上下文**；因此改变这些内容不必然失效旧译文缓存。SRT 路径还有读取缓存传 `srt_str`、写入缓存传条目列表 `it` 的不一致。这里只列源码风险，未执行缓存命中实验。[P2]、[缓存实现](https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/translator/_base.py#L179-L193)

## 4. 专用翻译模型适配

- **Qwen-MT：**本地 `_qwenmt.py` 对 `qwen-mt*` 只发 user 原文，通过 `translation_options` 指定源／目标语言，并可提供 `terms` 和 `domains`；没有用前面已构建的通用字幕提示词。模型名不是 `qwen-mt*` 时才走通用 OpenAI 兼容提示路径。`result_format='message'` 是 API 的消息外壳设置，不能理解为字幕的结构化 schema。当前上游 `_bailian.py` 保留这个分流。[P9][C3]
- **HY-MT2-1.8B：**共用初始化强制关掉完整 SRT 模式，独立提示只给目标语言、翻译要求与保持换行数；走 tokenizer chat template，再本地 `generate(max_new_tokens=8092)`。不调用通用 `_set_context()`，因此不能把全片上下文／术语表模板的能力概括到此分支。[P1][P10]
- **M2M100：**按行 tokenize，`translate_batch` 使用目标语言前缀、beam 和重复惩罚等原生 MT 参数，再逐行 detokenize；不使用 chat 字幕提示。[P11]
- **本地通用 LLM：**`LocalLLM` 只配置 OpenAI 兼容 endpoint、模型名、token 上限、reasoning effort，继承通用字幕流程。查阅本地翻译目录和当前官方翻译目录，未发现 TranslateGemma 特有的输入结构、语言字段或 chat template 适配；这不等于任何服务端都不能自行提供 TranslateGemma。[P17][C1][C2]

这些分流说明“专用 MT 应按本身接口契约处理”在代码中确实存在；但 HY-MT2 的保持换行提示是否充分、Qwen-MT 如何处理 SRT、M2M100 质量如何，本轮没有模型实测。

## 5. 显示换行、重分段与时轴

视频字幕嵌入阶段的 `_process_subtitles()` 对译文调用 `simple_wrap()`，然后直接写回同一条目的 `line` 和 `time`。`simple_wrap()` 先把已有换行变空格，以字符长度为主，在阈值附近寻找空格／标点；CJK 与其他语言使用不同容差，特别短的最后一行可并到前一行。它可能超过名义字符上限，也没有最大两行、语法完整性、CPS 或最短显示时长的硬性校验。[P12]

这个换行只改变条目内文本布局，不创建新的时间片，不为跨条句子做语义重排。独立批量字幕翻译 `TranslateSrt` 直接保存译文或双语 SRT；它没有调用视频嵌入阶段的 `simple_wrap()`，所以不能将该显示处理说成所有字幕翻译出口的共同步骤。[P12][P18]

另有名称为 `llm_segment()` 的可选 ASR 后编辑：按固定块数请求 LLM，更正 ASR 文字和标点；其提示词反而要求保持块数、索引和时间戳。代码会裁剪重叠结束时间、修正开始晚于结束的情况；外层仅要求结果条目数大于原来的一半，否则恢复原稿。这是 ASR 后编辑及有限时间修正，不能作为翻译后严密的语义切条与时间分配算法。[P15][P19][P5]

配音路径另行调用 `SpeedRate`，以生成音频及用户的语音／视频变速选项处理同步，再用新的 `start_time`／`end_time` 保存目标字幕。纯提取模式、无配音或忽略同步时直接跳过。这里的时轴改变服务于配音流程，未见目标译文对原始外语声学内容重新做 forced alignment。[P13]

## 验证与限制

已完成本地相关代码／提示词／架构文档静态检查、官方历史文件逐项匹配，以及当前 `main` 核心与专用适配的有限核对。没有运行应用、调用翻译 API、下载模型、上传任何私人字幕或音频；没有修改 sibling 项目。本报告只新增这一份 Kototoki 调研文档。

所有有关“可能错位”“可能复用过期缓存”的内容是源码风险推论；没有故障注入实测。全片上下文、术语表、口语化、时长压缩和换行启发式均不等于翻译质量、信息完整度或观看体验已获验证。本轮不比较不同 LLM／MT 的准确率，也不据此推荐采用某个模型。若未来需要实施，应另行规定逐 ID 完整性、可恢复失败状态、目标语言检查、语义保真和显示速度的验收标准。

## 不可变源码来源

以下 P 类链接均为与本地相关文件完整匹配的 `1a41120…`；C 类为本次查询的当前官方提交 `9945754…`。

[P1]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/translator/_base.py#L46-L75
[P2]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/translator/_base.py#L88-L173
[P3]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/translator/_openaicompat.py#L50-L113
[P4]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/util/_srt_parse.py#L99-L165
[P5]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/task/_base.py#L98-L132
[P6]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/util/help_misc.py#L168-L203
[P7]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/prompts/text/chatgpt.txt#L1-L40
[P8]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/prompts/srt/chatgpt.txt#L8-L49
[P9]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/translator/_qwenmt.py#L30-L74
[P10]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/translator/_hymt2.py#L53-L69
[P11]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/translator/_m2m100.py#L54-L73
[P12]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/task/_stage_subtitle.py#L26-L61
[P13]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/task/_stage_align.py#L15-L56
[P14]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/translator/_gemini.py#L27-L64
[P15]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/translator/_openaicompat.py#L118-L191
[P16]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/docs/architecture.md#L531-L536
[P17]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/translator/_localllm.py#L8-L27
[P18]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/task/translate_srt.py#L47-L88
[P19]: https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/prompts/resegment/llm.txt#L1-L17
[C1]: https://github.com/jianchang512/pyvideotrans/blob/9945754bbe6d7a7108eb7eee941311a87f89d69e/videotrans/translator/_base.py#L55-L217
[C2]: https://github.com/jianchang512/pyvideotrans/blob/9945754bbe6d7a7108eb7eee941311a87f89d69e/videotrans/translator/_openaicompat.py#L42-L105
[C3]: https://github.com/jianchang512/pyvideotrans/blob/9945754bbe6d7a7108eb7eee941311a87f89d69e/videotrans/translator/_bailian.py#L17-L76
[C4]: https://github.com/jianchang512/pyvideotrans/blob/9945754bbe6d7a7108eb7eee941311a87f89d69e/videotrans/configure/_app_settings.py#L156-L204

- [全文上下文构造 P1 补充](https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/translator/_base.py#L195-L207)
- [字幕内换行 P12 补充](https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/util/_srt_wrap.py#L8-L64)
- [中文提示规则 P8 补充](https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/prompts/language_prompts/zh-cn.txt#L1)
- [缓存键／缓存读写 P1 补充](https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/translator/_base.py#L179-L193)
- [SRT 输出重编号 P4 补充](https://github.com/jianchang512/pyvideotrans/blob/1a41120fa805bbb279c12d13ae04ed576d42bdf6/videotrans/util/_srt_parse.py#L211-L233)
