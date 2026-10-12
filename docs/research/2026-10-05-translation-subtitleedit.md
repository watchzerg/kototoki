# Subtitle Edit 字幕翻译实现调查

- 状态：concluded（源码机制已核验；翻译质量未实测）
- 最后更新／来源访问日期：2026-10-05
- 范围：只读检查 `D:\AI_Projects\subtitleedit`；研究现成字幕的文本翻译，不涉及语音识别或音频上传。
- 与 Kototoki 的关系：供未来翻译能力研究参考，不改变当前仅转录、保留原语言的项目范围。

## 版本与证据身份

本地目录没有 `.git`；`git status`、`git rev-parse HEAD`、`git remote -v` 均报告不是 Git 仓库。因此不能称其为已确认 HEAD 的 checkout，也不能证明所有文件均未被修改。未发现本地 `AGENTS.md`。

根据文件时间找到官方参考 commit [3a391f06d5994422013210e78585eb87947f704a](https://github.com/SubtitleEdit/subtitleedit/commit/3a391f06d5994422013210e78585eb87947f704a)，官方 committer 时间为 `2026-10-03T08:21:58Z`。本次将下列本地文件与此 commit 的 raw 文件逐一比较，归一化 CRLF／LF 后内容完全相同：`AdvancedTranslatorBase`、`LlamaCppAdvancedProtocol`、`LlamaCppAdvancedClient`、`MergeAndSplitHelper`、`DoAutoTranslate`、`TranslationEchoGuard`、`LlamaCppTranslate`、`LlmTranslatePrompt`、`CrispAsrMadladTranslate`、`LlamaCppServerManager`、`AutoTranslateViewModel`、`LlamaCppDownloadHelper`、`AssaTagStripper`、`CopyPasteTranslateViewModel`、`ChatGptTranslate`、`DeepLTranslate`、`SeAutoTranslate`、`SeLlamaCppAdvanced`、`AdvancedTranslatorEchoTests`、`TranslationEchoGuardTests`、`LlamaCppAdvancedClientReasoningTests`，以及 README。以下固定 commit 链接因此可追溯所观察的本地代码；匹配这些文件不等于证明整个目录的来源版本。

调查时官方 `main` 为 [df69ea0093dfd432f8263d8e07068c72fb0c2b11](https://github.com/SubtitleEdit/subtitleedit/commit/df69ea0093dfd432f8263d8e07068c72fb0c2b11)，时间 `2026-10-05T07:22:54Z`。两者的[官方比较](https://github.com/SubtitleEdit/subtitleedit/compare/3a391f06d5994422013210e78585eb87947f704a...df69ea0093dfd432f8263d8e07068c72fb0c2b11)显示 advanced 三个核心文件未变；普通路径增加 ChatGPT 的 `ILineBreakPreservingTranslator` 标记，修正按原换行拆回连续字幕的逻辑；Index-Translate 的下载源改为 IndexTeam 官方 GGUF。下文普通拆分描述以本地参考 commit 为准，不将这些新改动反推为本地已有。

## 结论

Subtitle Edit 没有一个统一的“字幕翻译算法”。它把普通文本翻译引擎和 advanced 本地 LLM 分开调度：前者依靠合并／拆分启发式，后者以编号 JSON 协议保持字幕条目对应关系。advanced 已具备滚动历史、剧情简介、术语表、批次重试与缩小，但这些工程措施主要防止漏条、空回复、格式失配和明显原文回声；它们没有验证译文语义、指代、目标语言或术语是否实际正确。[调度代码](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/Translate/DoAutoTranslate.cs#L22-L67)、[advanced 译文验收](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/AdvancedTranslatorBase.cs#L110-L144)。

| 项目 | 普通翻译器路径 | advanced 本地 LLM 路径 |
| --- | --- | --- |
| 请求单位 | 合并后的文本；可强制每条独立 | 保持独立文本的编号批次，默认 10 条，限制 1–50 条 |
| 上下文 | 当前请求中相邻字幕的文字；通常不带跨请求历史 | 批内文字＋此前已译源／目标对；默认 12 对，限制 0–50 对 |
| 对齐 | 按标点、换行、文本拆分和比例等启发式拆回 | 请求 `n`，响应 `"1"` 等 key，按 key 写回原条目 |
| 失败缩小 | 拆分失败触发较小合并范围；随后可逐条 | 无效／回声回复重试，再递归处理前半批 |
| 时间码 | 保留原行的 Show／Hide | 不交给模型；只修改 TranslatedText |

来源：[普通 merge/split 入口](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/Translate/MergeAndSplitHelper.cs#L48-L123)、[advanced 批次和写回](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/AdvancedTranslatorBase.cs#L72-L144)、[默认设置](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Logic/Config/SeLlamaCppAdvanced.cs#L10-L24)。

## advanced：上下文、JSON 与字幕对应

系统提示要求专业字幕翻译、保留意义／语气／风格和格式；可附加保持条内换行、正式／非正式称呼、用户填写的 Synopsis、`源词 = 译词` Glossary。术语表以文本指令加入，没有译后检查或强制字符串替换。用户消息为 `{"history":[{"source":"…","translation":"…"}],"lines":[{"n":1,"text":"…"}]}`；历史仅用于人名、代词、称谓等一致性，不重新翻译。[协议与提示构造](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/LlamaCppAdvancedProtocol.cs#L20-L142)。

历史从当前批次之前向后收集已经有译文的条目，再恢复时间顺序；跳过空内容和纯绘图标签行。没有另取下一批的未来字幕，没有按场景边界清空历史的逻辑。缩到一条时历史被置空，避免翻译专用模型把历史混进当前译文。这意味着失败后上下文能力会减弱。[CollectHistory 与单条例外](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/AdvancedTranslatorBase.cs#L110-L113)、[历史收集](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/AdvancedTranslatorBase.cs#L233-L261)。

每批编号从 1 重新开始，不是文件全局字幕 ID；调用端使用当前 `index` 映射回原条目。输入复制出 `Number`、Show、Hide 等后，模型请求只包括文字和批内编号，译后只写 `TranslatedText`。因此“保留时间”指沿用原字幕时间，不是重新声学对齐，也不能据此保证每条译文对应的含义正确。[原条目复制](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/Translate/DoAutoTranslate.cs#L41-L64)、[批内编号与写回](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/AdvancedTranslatorBase.cs#L102-L133)。

响应 schema 要求所有批内编号对应 string，全部 required、禁止 additionalProperties，并设置 strict。服务拒绝时客户端依次降为 `json_object` 和普通回复；后两者已没有同样的结构约束。解析器从第一个 `{` 到最后一个 `}` 尝试提取对象，容忍 JSON 外的 Markdown／说明；数字 key 的 string 值进字典。无约束 fallback 中重复 key 会被后者覆盖，多余数字 key 不由 `IsComplete` 拒绝；`IsComplete` 主要检查所需 key 是否存在，以及多条批次的非空源文是否有非空译文。故不能笼统宣称“JSON 永久保证恰好一次”。[schema 与解析](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/LlamaCppAdvancedProtocol.cs#L145-L242)、[客户端降级](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/LlamaCppAdvancedClient.cs#L51-L84)、[完整性检查](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/AdvancedTranslatorBase.cs#L284-L300)。

ASS/SSA 首尾 override 标签先剥离、译后原样拼回；绘图行剥为无文本。文本中间的标签仍会进入模型。`KeepLineBreaks` 是提示要求，schema 只要求 string，并不验证实际换行数量。[标签处理](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/Translate/AssaTagStripper.cs#L13-L58)、[换行提示](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/LlamaCppAdvancedProtocol.cs#L40-L43)。

## 重试、缩批与原文复制

advanced 每个批次至多尝试两次。不完整或原文回声后会重试；原文回声的重试 temperature 增加 0.3、最高 1.0。两次仍不能接受的多条批次递归处理 `count / 2` 的前半批；外层再处理余下字幕，成功前半批此时可进入历史。例如配置 50 条，失败可按 `50→25→12→6→3→1` 缩小；各级各自最多两次内容尝试，只有成功部分被写回。下一轮重新读取配置 BatchSize，不会永久保持 25 条。不是同时将整批二分后并行翻译。单条仍缺 key／不可解析时抛错结束；第二次 HTTP 异常也直接抛出，未进入这种语义／结构失败的缩批步骤。一次内容尝试的客户端格式降级另可能产生三次 HTTP 请求，所以“至多两次”不是网络请求总上限。[批次读取](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/AdvancedTranslatorBase.cs#L72-L91)、[重试与缩批](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/AdvancedTranslatorBase.cs#L136-L214)、[格式降级](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/LlamaCppAdvancedClient.cs#L51-L74)。

效率方面，系统提示按稳定内容优先排列（指令、简介、术语），变化的历史和本批文字位于用户消息；请求设置 `cache_prompt: true`，希望 llama-server 复用相同前缀的 KV cache，减少重复预填充。其收益依赖服务端实现及缓存命中，本次没有测量加速比例，也不能把 llama.cpp 特有参数的效果推广到全部 OpenAI-compatible 服务。[前缀设计](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/LlamaCppAdvancedProtocol.cs#L11-L15)、[cache_prompt 请求](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/LlamaCppAdvancedClient.cs#L92-L132)。

客户端流式读 SSE，首包／中途无数据／总时间默认上限分别 5／2／15 分钟；停滞时不继续尝试更松的响应格式。请求输出预算默认 `200 + Σ(32 + 2×源文字符数)`，用户 MaxTokens 优先。该预算是字符估计，不是 tokenizer 计算的上下文余量；按条数分批也没有结合历史、简介和术语的总 token 预算。它限制失控生成，不证明长上下文不会溢出。[客户端时限、请求、采样](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/LlamaCppAdvancedClient.cs#L33-L191)、[批次输出预算](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/AdvancedTranslatorBase.cs#L159-L168)。

原文回声检测只判定“源文几乎原样返回”：去除大小写、空白／换行和 HTML 标签差异；常规有空格文字至少 10 字母且 3 词，CJK／泰语至少 6 字母，短词、人名、数字免判；多行回声按符合门槛行的过半比例判定。语言名去除括号后相同则跳过，因此简／繁中文等变体也免判。它检测不到换词后的错误译文、漏掉部分信息或错误语言中的新文字。[EchoGuard](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/AutoTranslate/TranslationEchoGuard.cs#L19-L185)。

特别需要保留两个弱点：advanced 多条批次回声会缩小，但最终单条在较暖重试后仍回声会被接受；单条响应若含所需 key、值为空，`IsComplete` 也通过，批次写回时复制原文。普通 llama.cpp 路径也会在两次回声后记录日志并接受原文。流程“完成”因此不等于全部已经翻译。[advanced 单条与空值](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/AdvancedTranslatorBase.cs#L115-L133)、[完整性中的单条例外](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/AdvancedTranslatorBase.cs#L284-L300)、[普通 llama.cpp 回声接受](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/AutoTranslate/LlamaCppTranslate.cs#L74-L90)。

另有用户开启“保持音乐符号行原文”的主动例外；该行不发送给翻译器，会中断当前批次，原样复制。这应与翻译失败造成的原文保留区分。[音乐行判断](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/Translate/MergeAndSplitHelper.cs#L126-L157)、[advanced 对音乐行的处理](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/AdvancedTranslatorBase.cs#L74-L91)。

## 普通路径：合并／拆回不是 JSON 对齐

普通路径结合翻译器 `MaxCharacters` 与用户 `AutoTranslateMaxBytes` 限制请求；实际合并大小检查使用 URL 编码长度，不能将这个配置直接理解为模型 token 上限。连续未完句字幕在间隔小于 1000 ms 时以空格（支持保留换行的引擎则以换行）合并；日／中等特殊语言走以换行和独立句点分隔的策略。它不是语义嵌入切分、场景切分或说话人分析。[大小控制](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/Translate/MergeAndSplitHelper.cs#L209-L232)、[特殊语言合并](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/Translate/MergeAndSplitHelper.cs#L756-L827)、[间隔和连续合并](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/Translate/MergeAndSplitHelper.cs#L888-L917)。

拆分依次尝试标点且句点数匹配、换行数、数字中句点归一化、带长度比例护栏的宽松标点拆分，并要求条数和空行形态匹配。缩略词表用于避免在 `Mrs.` 等处错断。连续句拆回还存在 AutoBreak、字符比例、时长比例、标点候选和 CPS 评分。它们处理显示分配，并不能识别译文语义漂移。失败设 `MergeSplitProblems`，下次上限超过 500 时减半一次；累计错误会转逐条，无进展超过 3 次抛错，连续 8 次成功后可恢复合并。[拆分策略](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/Translate/MergeAndSplitHelper.cs#L279-L335)、[连续句拆分候选](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/Translate/MergeAndSplitHelper.cs#L1130-L1410)、[流程恢复／无进展上限](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/Translate/DoAutoTranslate.cs#L70-L146)。

DeepL 与 ChatGPT 另有 HTTP 层退避，对 429／503 等最多再试 3 次；这与内容失败后的缩批不同。普通 ChatGPT 请求的外层虽然是 JSON，但模型输出仍是普通译文 `content`，没有编号译文 schema。[DeepL 退避](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/AutoTranslate/DeepLTranslate.cs#L238-L253)、[重试条件](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/AutoTranslate/DeepLTranslate.cs#L303-L309)、[ChatGPT 请求与回复](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/AutoTranslate/ChatGptTranslate.cs#L121-L178)。

## 翻译专用模型与 Hy-MT2 的路径差异

本地模型列表包含 TranslateGemma、Hy-MT2、MiLMMT-46、Index-Translate 等翻译专用模型以及通用指令模型；这只是可选集，不构成质量排名。`LlamaCppModel` 保存 prompt、sampling、chat template、NoThinking、CompletionOnly 等兼容性配置。TranslateGemma 使用 `gemma` chat template 与 NoJinja，MiLMMT-46 则要求源文嵌入 `{2}` 的 completion 模板。[模型兼容性字段](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/LlamaCpp/LlamaCppServerManager.cs#L18-L49)、[模型列表与模板](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/LlamaCpp/LlamaCppServerManager.cs#L58-L107)、[completion 消息构造](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/AutoTranslate/LlmTranslatePrompt.cs#L29-L65)。

Hy-MT2 7B Q8_0 的列表记录专用 `Translate the following text into {1}…` 模板，以及 temperature 0.7、top_p 0.6、top_k 20、repeat_penalty 1.05。普通 `LlamaCppTranslate` 优先读取 `LlamaCppModelPrompt`，由模型选择时的 `ApplyTranslatePromptSettings` 写入；advanced 则只通过自己的设置构建专业字幕＋JSON系统提示，没有读取这个专用模板。advanced 的 sampling 可继承这些模型参数，所以它也不必然使用默认 0.2。[Hy-MT2 配置](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/LlamaCpp/LlamaCppServerManager.cs#L178-L191)、[普通模型设置](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/LlamaCpp/LlamaCppServerManager.cs#L650-L665)、[普通提示读取](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/AutoTranslate/LlamaCppTranslate.cs#L52-L68)、[advanced 提示构建](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/AdvancedTranslatorBase.cs#L147-L157)、[advanced sampling 优先级](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/LlamaCppAdvanced/LlamaCppAdvancedClient.cs#L160-L191)。

advanced 模型列表仅显式排除 CompletionOnly（MiLMMT-46），Hy-MT2 仍可选。这证明两种协议存在兼容性区别，应当在后续验证中作为单独因素控制；未运行同源字幕的两路径配对测试，不能把用户观察的日译中语义错误归因于这个差异。源码中的“模型回声／某提示更好”注释属于上游作者陈述，本次不将其当作本机复现实测。[模型筛选](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/AutoTranslateViewModel.cs#L1044-L1055)。

CrispASR MADLAD 是另一条专用机器翻译路径：启动本地 CLI `--backend madlad --text … -tl … --translate-max-tokens 1024`；按支持目标语言白名单拒绝未知语言。调度层强制逐字幕条执行，没有 advanced 的历史／术语 JSON 批次。NLLB 两个引擎也强制逐条。[MADLAD CLI](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/AutoTranslate/CrispAsrMadladTranslate.cs#L60-L118)、[强制逐条调度](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/libuilogic/Translate/DoAutoTranslate.cs#L26-L35)。

人工 Copy/Paste Translate 是独立路径：按配置字符块和分隔符构造文字，弹窗让用户粘贴译文，再依起始索引写回并记录已译条目。它不是自动 JSON 翻译的另一种模式。默认块大小 5000、分隔符 `(...)`。[人工路径](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Features/Translate/CopyPasteTranslateViewModel.cs#L75-L149)、[默认参数](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/src/ui/Logic/Config/SeAutoTranslate.cs#L160-L161)。

## 质量证据与未来可借鉴边界

本次没有构建 Subtitle Edit、运行其测试、调用模型或发送私有字幕。检查到的测试主要覆盖回声规则、SSE／reasoning_content 提取和故障响应，属于协议健壮性证据，不能推出日译中质量。[回声测试](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/tests/UI/Features/Translate/AdvancedTranslatorEchoTests.cs#L20-L69)、[EchoGuard 测试](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/tests/libuilogic/AutoTranslate/TranslationEchoGuardTests.cs#L11-L125)、[客户端测试](https://github.com/SubtitleEdit/subtitleedit/blob/3a391f06d5994422013210e78585eb87947f704a/tests/UI/Features/Translate/LlamaCppAdvancedClientReasoningTests.cs#L20-L198)。

研究建议（未实施／未采纳）：未来若单独开展翻译功能，优先借鉴“时间码留在调用端、稳定字幕 ID、译文按 ID 回填、有限历史和用户术语表、输出验证、失败缩批”的边界；进一步明确单条失败状态，避免原文复制被记作翻译成功。必须分别测量结构完整率、漏译／回声、目标语言、语义忠实度、专名与指代一致性，再决定合并文本或编号批次和模型专用提示的组合。JSON 合法率与字幕对应率不能替代翻译质量评估。
