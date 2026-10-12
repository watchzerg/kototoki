# TranslateGemma 12B：本地字幕翻译的输入契约与使用边界

状态：exploratory；官方资料调研完成，未下载模型、未运行真实翻译，建议未采纳。

最后更新：2026-10-05。

范围：用户指定的 `google/translategemma-12b-it`，重点是日语→简体中文字幕、标题／背景／术语、独立多段、结构化输出，以及原生 Windows／RTX 5080 的候选运行方式。本文是后续翻译研究，不改变当前原语言 STT 里程碑或 W0／X0。相关讨论见[既有翻译方法研究](2026-10-05-translation-methods.md)。所有外部来源访问日期为 2026-10-05；动态页面未冻结模型 revision。

**主要判断：适合先作为“给定源语言、目标语言，返回译文”的专用翻译基准。若工作流高度依赖独立背景、词汇表和逐条 JSON，它的官方接口限制会增加应用层工作。** 这不代表日中质量落后于另外两个候选；本次没有同条件质量实验。

本文的“官方支持”指模型卡、Google 示例或团队说明明确提供的契约；“工程建议”指应用层设计；“待测”指无法从文档推出可靠性的行为。

## 1. 模型身份与证据边界

TranslateGemma 是 Gemma 3 派生的翻译模型家族，提供 4B、12B、27B。Google 报告 12B 在 WMT24++ 的 MetricX 上优于 Gemma 3 27B；这是与基础 Gemma 的比较，不能直接当成与 Hy-MT2 或 Tower-Plus 的排名。Google 重点评估 55 个语言／地区方向，并训练了更广的额外语言对，但额外覆盖缺少同等验证。[Google 发布说明](https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/)

论文采用 SFT 后 RL 的训练路线，并测试文本与图片中文字翻译。其语言评价主要围绕英语方向；人工评价含日语→英语、英语→简中，不能据此声称日语→简中字幕已通过人工验证。英文枢纽结果也不能等同于所有非英语语对都达到相同质量。[技术报告 v3，§5–6](https://arxiv.org/pdf/2601.09012)

“12B”是型号名称；Hugging Face 页面的权重统计约为 13B，BF16，包含多模态组件。部署预算应读取所选权重文件与实际架构，不能只用名称中的 12 估算全部资源。[官方模型卡](https://huggingface.co/google/translategemma-12b-it)

## 2. 输入：有规定模板，普通聊天指令并非受支持接口

### 2.1 官方消息结构

官方契约只支持 `user`／`assistant`，用户 `content` 必须是恰好一个元素的列表。文本项包含 `type`、`source_lang_code`、`target_lang_code`、`text`；语言可以是简码或地区码，不受支持的码会在模板应用阶段报错。`text` 是待翻译正文。[Google Gemma Cookbook](https://github.com/google-gemini/gemma-cookbook/blob/main/Research/%5BTranslateGemma%5DExample.ipynb)

下面是日语→简中的消息结构示意；例句为本报告自行编写。`ja` 与 `zh-CN` 应在锁定 processor／template 后做一次模板渲染验证，不能把 API 能接收任意字符串理解为模型已验证所有语对。

```python
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "source_lang_code": "ja",
                "target_lang_code": "zh-CN",
                "text": "もう一度、最初から説明してください。",
            }
        ],
    }
]

inputs = processor.apply_chat_template(
    messages,
    tokenize=True,
    add_generation_prompt=True,
    return_dict=True,
    return_tensors="pt",
)
output = model.generate(**inputs, do_sample=False, max_new_tokens=512)
translation = decode_generated_suffix(output, inputs)
```

这是伪代码，省略模型加载、设备移动及错误处理；`max_new_tokens=512` 是示例预算，不是官方最佳参数或字幕长度要求。生成后只解码新生成部分，避免把源文与模板一起误当成译文。

### 2.2 模板内的自然语言含义

`apply_chat_template()` 将语言码映射成语言名，构造“专业源语言→目标语言译者”的任务描述，要求传达含义和细节、符合目标语言表达，只返回译文，然后追加正文。论文 Figure 3 给出原始英文 prompt；下面仅解释含义，不声称是可替代官方英文字符串的逐 token 模板。[技术报告 Figure 3](https://arxiv.org/pdf/2601.09012)

```text
official_prompt = build_translation_instruction(
    source_language_name,
    source_language_code,
    target_language_name,
    target_language_code,
    output_policy="translation_only",
)
rendered = official_gemma_chat_wrapper(
    user_text=official_prompt + source_text,
    add_model_turn=True,
)
```

如果使用 Transformers，应让所选 checkpoint 自带的 processor／tokenizer 渲染模板。若使用原始 completion 接口，需要保留 Gemma 控制 token 和模型轮次包装，不能只复制那段英文说明便声称输入等价。Hugging Face 文档也强调不同模型有不同角色控制 token，重复插入 special tokens 会损害效果。[Transformers chat templates](https://huggingface.co/docs/transformers/main/chat_templating)

### 2.3 标题、背景、词汇表和风格

Google 团队在模型讨论区明确说明：没有独立 system prompt 或指令参数；放进 `text` 的内容会作为源文翻译，普通 prompt engineering 不能强制术语或风格，建议在应用层做预处理、后处理及术语校验。[Google 团队答复，discussion #2，2026-02-13](https://huggingface.co/google/translategemma-12b-it/discussions/2)

| 想输入的内容 | 官方接口内的含义 | 字幕工作流的判断 |
| --- | --- | --- |
| 要翻译的标题 | 可以作为待译正文 | 与对白同放时，标题也属于输出内容 |
| 只供参考的片名／剧情简介 | 没有独立背景字段 | 放进 `text` 后不能可靠要求只参考、不输出 |
| 人物表／glossary | 没有独立术语字段 | 不能据通用 LLM 经验宣称可强制统一译法 |
| 简短／口语／每行限制 | 没有独立风格控制字段 | 应另做字幕显示检查；尝试自由 prompt 要单列实验 |
| 源语言自动判断 | 官方模板要求提供语言码 | 在应用层确定源语言；混合语言内容另测 |

**允许尝试自由 prompt，但属于实验路线。** 模型卡提到其他手写提示可能用于翻译后编辑；它们不受官方支持，需要直接使用控制 token／tokenizer，绕开上述严格模板。不能将“模板会拒绝 system role”扩大成“模型数学上不可能理解任何指令”，也不能把可绕过校验扩大成已验证支持。[官方模型卡 Usage](https://huggingface.co/google/translategemma-12b-it)

应用层术语替换也有边界：占位符可能被模型改写或重排；译后替换只在明确匹配时安全，可能破坏语法。建议先统计术语命中和变体，再比较占位符与译后校验策略，不把字符串替换等同于受约束翻译。

## 3. 多段输入：成段正文与独立 batch 是两种方式

### 3.1 一个正文包含多段

可以把多个自然段放进同一个 `text`。Google Cookbook 展示两段文学正文及其成段译文，演示模型是 4B，同家族接口可作为 12B 的用法参考；这不是 12B 对字幕边界保持的实测。[Google Cookbook 原始 notebook](https://raw.githubusercontent.com/google-gemini/gemma-cookbook/main/Research/%5BTranslateGemma%5DExample.ipynb)

```python
source_text = paragraph_a + "\n\n" + paragraph_b
request = make_official_request(source_text, "ja", "zh-CN")
translated_document = translate(request)
```

这样有共享正文语境，但仍是一个生成序列。官方没有保证空行数、段落数、字幕条数或 ID 一一保留。模型可能合句或重排；“一次输入多段”和“每段独立返回一个记录”不能视为同一能力。

### 3.2 多条独立请求做推理 batch

需要稳定一条输入对应一条结果时，由应用建立多份独立请求，推理后按 batch 位置回填 ID。batch 内记录没有通过同一文本窗口共享前后文；这是 GPU 运行方式。Transformers 提供 batch 管线，但吞吐收益取决于长度、padding 和显存，不能预先保证更快。[Transformers pipelines：batching](https://huggingface.co/docs/transformers/en/main_classes/pipelines)

```python
records = [
    {"id": "cue_001", "text": source_a},
    {"id": "cue_002", "text": source_b},
]
requests = [make_official_request(r["text"], "ja", "zh-CN") for r in records]
translations = infer_independent_batch(requests)  # Runtime-specific adapter
assert len(translations) == len(records)
results = [
    {"id": r["id"], "translation": t}
    for r, t in zip(records, translations)
]
```

`infer_independent_batch` 是应用层接口示意，不是 TranslateGemma 的官方函数。初次验证从单条开始，再逐步增加小 batch；按相近 token 长度分组，分别记录吞吐、峰值显存和生成截断。不要把多份 `user` 消息塞进同一次聊天，假设它会按多条独立任务运行。

### 3.3 字幕语义与 cue 边界

工程建议保留两条对照：逐 cue 独立翻译，容易保 ID，但短片段缺上下文；完整句／话轮翻译，可以给出更完整语义，但需要额外回填 cue。对于第二条路线，不能仅按中文字符数比例切译文就声称已恢复语义同步。原时间戳与说话人信息留在应用层，翻译模型不负责推断声学时间。

## 4. 输出：默认纯译文，JSON 有三个层次

**官方任务输出是目标语言译文。** 没有文档承诺原生 JSON schema、带 ID 的数组、SRT／ASS 输出或逐段结构严格保持。普通换行、对话标点可以出现在译文里，但格式稳定性需要测量。[官方模型卡 Inputs and outputs／Usage](https://huggingface.co/google/translategemma-12b-it)

| 方式 | 能得到什么 | 应如何定位 |
| --- | --- | --- |
| 模型按默认模板输出 | 译文字符串 | 官方受支持起点 |
| 应用将译文包入 JSON | 确定的键、ID、时间、正确转义 | 推荐先采用；不增加模型格式任务 |
| 自由 prompt 请求模型输出 JSON | 可能输出结构化文字 | 官方接口无保证，单列待测 |
| 推理引擎使用 grammar／schema | 可约束语法 | 引擎能力；不自动保证翻译、条数对应或术语正确 |

推荐先让程序写外层结构，例如：

```python
translation = translate(make_official_request(source_text, "ja", "zh-CN"))
result = {
    "id": source_record.id,
    "start_ms": source_record.start_ms,
    "end_ms": source_record.end_ms,
    "translation": translation,
}
payload = json.dumps(result, ensure_ascii=False)
```

这可以确定得到可解析 JSON；它解决存储和接口格式，不解决翻译是否准确，也不证明多段已正确对齐。外层 HTTP 响应本来是 JSON，同样不代表 `translation` 字符串内部是 JSON。

llama.cpp 的 GBNF 能限制输出语法，也有 JSON schema 转 grammar 的路线。[llama.cpp GBNF 指南](https://github.com/ggml-org/llama.cpp/tree/master/grammars) 若对 TranslateGemma 的“只出译文”任务强行加 JSON 数组 grammar，需要测试任务冲突、词义遗漏、ID 对应、提前结束和译文逃逸；本次没有证据证明这种组合可靠。不要仅验证 `json.loads()` 成功便宣布字幕翻译成功。

## 5. 对字幕最有影响的其他特性

**上下文预算偏保守。** 模型卡写的是总输入上下文 2K tokens。这应作为有文档依据的起点；Gemma 3 通用配置中的 131072 位置容量并不建立 TranslateGemma 的长文本翻译质量保证。模板、正文和任何实验性背景都消耗预算；输出仍需独立预算，超长内容应显式拆分而非静默截断。[TranslateGemma 卡](https://huggingface.co/google/translategemma-12b-it)、[Gemma 3 配置说明](https://huggingface.co/docs/transformers/main/en/model_doc/gemma3)

**短对白消歧依赖输入组织。** 日语省略主语、性别／称谓、人名读法、否定跨 cue、敬语与语气，都可能需要相邻对白。此模型缺少独立“只参考的上下文”字段，官方路线可将完整语义单元作为正文，但相邻正文也要翻译。用特殊标记只提取其中一段、拼接历史 assistant 译文或输入滚动摘要，都应作为待测条件，不能预设成功。

**不提供字幕长度与时间控制。** 每行汉字、阅读速度、双说话人断行、保留标签等由程序检查。修改 `max_new_tokens` 只会改变生成上限，不能保证译文恰好缩短到可读字幕，更可能导致截断。对中文字幕是否需要压缩，应同时检查信息保真，而非仅考核字数。

**图像能力用途明确、范围有限。** 官方支持图片中文字提取并翻译；论文图像实验只保留单一文本实例，不能据此声称它能理解整段视频、同时利用画面剧情和对白、或替代 OCR／字幕定位。官方消息只允许一个 content 项，因此“图片＋对白＋背景”也不是现成的受支持输入组合。[技术报告 §5.3](https://arxiv.org/pdf/2601.09012)、[Google Cookbook 图片示例](https://github.com/google-gemini/gemma-cookbook/blob/main/Research/%5BTranslateGemma%5DExample.ipynb)

**文本里的指令应作为文本翻译。** 影片可能出现“别翻译这句”等台词；应在小样本里验证是否忠实翻译而非被台词改变任务。拒译、解释、净化粗口、重复、错语种、空输出、专名变动也应列入字幕错误分类，当前未测，不推断固定失败率。

## 6. 本地 Windows／RTX 5080 的使用路线

### 6.1 显存与量化

RTX 5080 标准显存为 16 GB。[NVIDIA 规格](https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5080/) 仅以 12B–13B 权重估算，BF16 约 24–26 GB 十进制字节，已经超过单卡显存；这还未含 KV cache、运行缓冲区、图像组件和其他常驻模型。因此原始全 BF16 单卡全 GPU 不应作为预期方案。`device_map="auto"` 可能分派 CPU／磁盘，加载成功不能代替 GPU 驻留检查。

下面是理想位数的算术估计，**不是实际 GGUF 文件大小或实测显存**：

| 权重精度 | 12B–13B 参数理论字节 | 对 16 GB 的判断 |
| --- | --- | --- |
| BF16／FP16 | 24–26 GB | 全量单卡不适合 |
| 8-bit | 12–13 GB | 需确认实际量化开销与 batch；留给运行的空间较少 |
| 4-bit | 6–6.5 GB | 显存候选空间更大，翻译质量仍需验证 |

量化 scale、未量化层及容器开销会让实际占用偏离上表；Q8_0／Q4_K_M 不能直接当成理论 8／4 bit。多模态 GGUF 还需核实视觉组件及 projector；仅测文本字幕时不要无故加载视觉路径。此次未选定量化发布者，也未验证其转换 provenance、文件哈希与量化翻译损失。

### 6.2 可选引擎

| 路线 | 已有证据 | 尚需核实 |
| --- | --- | --- |
| Transformers + PyTorch + 合适量化 | 官方提供 processor／模型 API；bitsandbytes 文档列出 Windows 支持 | 选定版本与 RTX 5080 内核、具体 Gemma 3 量化覆盖、峰值显存 |
| llama.cpp + GGUF + CUDA | 上游有 Windows／CUDA 构建文档和 TranslateGemma 模板适配历史 | 所选稳定构建的模板、语言码、EOS、全部 GPU 驻留、量化质量 |
| vLLM | 官方 GPU 安装文档要求 Linux，无原生 Windows 支持 | WSL 是额外部署路线；需另测，不等于原生 Windows |

来源：[Transformers bitsandbytes](https://huggingface.co/docs/transformers/en/quantization/bitsandbytes)、[llama.cpp 构建文档](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)、[vLLM GPU 文档 v0.28.0](https://docs.vllm.ai/en/v0.28.0/getting_started/installation/gpu/)。这些是工具的一般能力，尚不构成此模型本机 smoke test。

llama.cpp 在 2026-01 的 [PR #19019](https://github.com/ggml-org/llama.cpp/pull/19019) 与 [PR #19052](https://github.com/ggml-org/llama.cpp/pull/19052/files) 修复过此模板适配；后者显示从 `chat_template_kwargs` 读取语言码，并为普通字符串构造专用内容，历史缺省为 `en-GB`。这证明输入适配需要特别注意语言参数，不能套用普通聊天示例；它不是当前所有 GUI 或稳定构建已经兼容的保证。当前 master 代码已变化，后续应渲染并检查最终 prompt，再冻结实测版本。

### 6.3 模型获取与许可

官方 Hugging Face 仓库需要接受 Gemma 使用条件。可本地使用，但不是 Apache-2.0；再分发权重、量化派生物或提供托管服务时需按 Gemma 条款处理许可、通知和限制。Google 不主张生成输出的权利。[官方仓库访问说明](https://huggingface.co/google/translategemma-12b-it)、[Gemma Terms §3](https://ai.google.dev/gemma/terms)

后续实际部署应把模型获取与正常推理分开，明确本地模型目录与离线运行；本次未做下载、安装、环境升级或 GPU 验证。

## 7. 后续实验建议

优先验证下列问题，保持官方模板作为控制组：

1. **日中基本质量**：短对白、完整句／话轮、带自然段的局部窗口；分别评估漏译、专名、否定、指代和语气。
2. **cue 保持**：换行／空行／自定义分隔符，测源条数、顺序与含义归属；出现合句不能只按格式判失败，应检查回填能力。
3. **部署精度**：所选 8-bit、4-bit 量化在同一小样本上对照；记录模型来源／revision／哈希、引擎版本、模板和显存。BF16 参考如无法全 GPU 运行，应明确其不同设备条件。
4. **背景与术语实验**：仅在自由 prompt 分支尝试，记录是否被翻译进结果、是否漏掉目标正文、是否真实提升专名一致性；不要与官方能力混写。
5. **结构化输出实验**：应用包装 JSON 作为可靠格式基准；模型 JSON／grammar 分支同时检查语法与翻译对应，统计失败后单条重试成本。
6. **长度与吞吐**：显式 token 计数，测 2K 文档范围内的短／中／长输入及小 batch，标注截断；超出官方输入范围单列探索，避免按架构容量宣称长片可用。

当前可以确定的是接口边界；最值得后续确认的是日语→简中对白质量、量化损失，以及放弃独立背景控制后还能否达到目标字幕质量。以上仍是研究建议，没有接入 Kototoki 或改变当前已采纳基线。

## 来源与版本记录

| 来源 | 本次记录的身份／版本 | 用途 |
| --- | --- | --- |
| [google/translategemma-12b-it](https://huggingface.co/google/translategemma-12b-it) | main 动态模型卡；未冻结权重 SHA | 身份、2K 输入、输出、许可、非官方 prompt |
| [Google discussion #2](https://huggingface.co/google/translategemma-12b-it/discussions/2) | Google org 成员 2026-02-13 回复；截至访问日 | system／glossary／style 限制 |
| [Google Gemma Cookbook](https://github.com/google-gemini/gemma-cookbook/blob/main/Research/%5BTranslateGemma%5DExample.ipynb) | main 动态；示例使用 4B | 消息字段、双段正文、图片输入 |
| [TranslateGemma 技术报告](https://arxiv.org/pdf/2601.09012) | arXiv:2601.09012v3，2026-01-19；PDF 标题页日期 2026-01-21 | prompt 含义、评价方向及图像范围 |
| [Google 发布说明](https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/) | 2026-01-15 | 家族、语言与基本模型比较 |
| [Transformers chat templates](https://huggingface.co/docs/transformers/main/chat_templating)、[pipelines](https://huggingface.co/docs/transformers/en/main_classes/pipelines)、[Gemma 3](https://huggingface.co/docs/transformers/main/en/model_doc/gemma3)、[bitsandbytes](https://huggingface.co/docs/transformers/en/quantization/bitsandbytes) | 在线文档；main 不视为稳定版本承诺 | 模板包装、batch、架构长度及量化工具 |
| [llama.cpp #19019](https://github.com/ggml-org/llama.cpp/pull/19019)、[#19052](https://github.com/ggml-org/llama.cpp/pull/19052/files)、[build](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)、[grammars](https://github.com/ggml-org/llama.cpp/tree/master/grammars) | PR 于 2026-01-23／24 合并；其他为动态 master | 历史模板适配、Windows GPU、grammar |
| [vLLM v0.28.0 GPU](https://docs.vllm.ai/en/v0.28.0/getting_started/installation/gpu/) | 版本化在线文档 | 无原生 Windows 支持；不据此锁定运行版本 |
| [NVIDIA RTX 5080](https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5080/)、[Gemma Terms](https://ai.google.dev/gemma/terms) | 截至访问日的官方页面 | 显存与许可边界 |

核验限制：官方 `chat_template.jinja`／`config.json` 文件页面在本次匿名 web 读取中未成功取得；因此字段契约由官方卡与 Google Cookbook 交叉核对，内部 prompt 含义由论文核对，未审计 12B 模板源码的每个字符。最终部署时应固定可访问 checkpoint，再核对实际文件，而非将本文伪代码当作生产适配器。
