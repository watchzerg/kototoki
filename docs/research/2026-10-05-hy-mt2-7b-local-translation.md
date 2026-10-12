# Hy-MT2-7B-GGUF 本地翻译接口与字幕适用性调研

状态：exploratory；一手来源核查完成，未下载或运行模型，建议尚未采纳  
最后更新：2026-10-05  
范围：用户指定的 `tencent/Hy-MT2-7B-GGUF`；重点为日语→简体中文字幕、输入条件、分段与结构输出，以及原生 Windows／RTX 5080 部署边界。研究不增加当前 STT 里程碑功能。

**结论：Hy-MT2 可以接收翻译任务的自然语言条件，官方明确提供背景、术语、风格、分隔符和结构化数据模板。它具有尝试多段字幕与 JSON 输出的依据；段落对应关系和格式完整性仍需程序检查，不能把“能按要求生成”视为稳定契约。** 本文区分“官方明确支持”“源码可表达”“工程推断”“待测方案”。与此前[翻译方法研究](2026-10-05-translation-methods.md)配套阅读。

## 1. 模型身份与真正可用的窗口

当前对象是 2026-05-21 发布的 **Hy-MT2**，与 2025 年的 Hunyuan-MT、HY-MT1.5 分开。官方介绍写 33 种语言，详细语言表另外列出繁体中文、粤语及若干少数民族语言；其计数口径不完全一致。日语、中文与繁体中文在表中明确存在，故日译中有正式语言覆盖依据。语言覆盖不证明本机字幕质量。[官方发布记录与语言表](https://github.com/Tencent-Hunyuan/Hy-MT2)

| 事项 | 已核验事实 | 使用含义 |
| --- | --- | --- |
| 产物 | 官方 `Hy-MT2-7B-GGUF`；基础模型 `Hy-MT2-7B` | GGUF 与 Transformers 原权重是不同运行路线 |
| 权重文件 | Q4_K_M 4.62 GB；Q6_K 6.16 GB；Q8_0 7.98 GB | 是磁盘文件大小，尚须加 KV cache、计算缓冲与其他驻留模型 |
| 官方运行窗口 | GitHub 部署段写 `max_context: 8192` | 后续初始实验按 8192 tokens 预算输入、模板与输出总量 |
| 配置容量 | 原权重 `max_position_embeddings=262144` | 与官方运行窗口分开记录，不能宣布 262K 整片翻译已验证 |
| 输出上限示例 | `max_tokens=4096` | 是示例生成预算，并非每次都应该生成这么长 |
| 许可 | 官方 LICENSE.txt 为 Apache-2.0 | 本文仅记录许可证身份，不作法律解释 |

来源：[GGUF 文件树](https://huggingface.co/tencent/Hy-MT2-7B-GGUF/tree/main)、[官方部署说明](https://github.com/Tencent-Hunyuan/Hy-MT2#inference-and-deployment)、[配置](https://huggingface.co/tencent/Hy-MT2-7B/raw/main/config.json)、[许可证正文](https://huggingface.co/tencent/Hy-MT2-7B-GGUF/blob/main/LICENSE.txt)。

**工程推断：**实际字幕窗口还受运行服务的 `n_ctx`、输出预算和显存限制。标题、背景、术语及 JSON 字段也占 token。应对最终渲染后的请求计数；长片通常需要分窗，而非按模型配置容量直接塞入全片。

## 2. 输入：自然语言任务与 chat template 是两层

### 2.1 官方任务提示允许哪些条件

官方将以下写成代表性任务示例，并未规定所有请求只能使用一种固定句子。中文提示使用完整中文语言名；英文提示使用完整英文语言名。默认示例要求只输出译文。模型没有默认 `system_prompt`，官方调用例将完整任务放入一条 `user` 消息。[官方模型卡任务示例](https://huggingface.co/tencent/Hy-MT2-7B-GGUF#hy-mt2-translation-task-instruction-examples-chinese-english-comparison)

| 条件 | 支持等级与形式 | 字幕使用方式 |
| --- | --- | --- |
| 目标语言 | 官方明确支持；任务文字指定语言 | 日译简中明确写“简体中文”，防止输出繁体 |
| 术语表／人名 | 官方明确支持；前置源词→目标词对照 | 只提供当前窗口相关且已确认的译名 |
| 风格 | 官方明确支持；指明目标风格 | 可试对白口吻、礼貌程度；具体字幕效果待测 |
| 背景 | 官方明确支持；背景区与待译正文分开 | 对话场景、人物关系或专业领域可放背景区 |
| 标题 | 没有专用 title 字段；可作为背景信息 | 是官方背景方式的合理用法，未单独验证标题收益 |
| 用户偏好 | 官方列出个性化条件列表 | 可提出保留称呼、禁止补情节等要求；多项叠加待测 |
| 分隔符／结构 | 官方明确提供保留布局及选择翻译的任务 | 可用 ID、分隔符、JSON；程序仍检查对应性 |

自然语言理解：先告诉模型哪些资料只是背景或译名参考，再明确哪一块是要翻译的正文，最后规定返回方式。官方背景、术语等能力有明确依据；把它们组合成下面的字幕模板属于**待测方案**。

最小官方中文模板为“将以下文本翻译为 `{target_lang}`，注意只需要输出翻译后的结果，不要额外解释：”后接正文。术语模板在此前加入逐项“源词翻译成目标词”；背景模板先写背景区，再写结合该背景翻译正文的任务和正文区。两者都属于 prompt 文本，没有独立的 glossary／background API 参数。以下是其结构伪代码，字段名由本文解释使用：

```python
default_prompt = translate_only_instruction(target_language) + source_text
term_prompt = reference_term_pairs(glossary) + default_prompt
context_prompt = background_block(background) + contextual_translation_instruction(target_language) + source_block(source_text)
```

```python
def build_prompt(text, target_language, background="", glossary=None):
    sections = []
    if background:
        sections.append("[Reference background; do not translate]\n" + background)
    if glossary:
        sections.append("[Required term translations]\n" + format_term_pairs(glossary))
    sections.append("[Task]\nTranslate only the source into " + target_language)
    sections.append("Keep meaning, negation, numbers, names, and dialogue register.")
    sections.append("Return only the translation, without commentary.")
    sections.append("[Source]\n" + text)
    return "\n\n".join(sections)

messages = [{"role": "user", "content": build_prompt(source, "Simplified Chinese")}]
```

这里英文为伪代码示例；落地时可改为中文任务文字并使用中文语言名。输入中的影视名称、梗、人物身份若不可靠，宜省略或标记不确定，避免模型依据错误背景替原文添加情节。该风险是工程推断，未在本模型上实测。

### 2.2 原权重的准确外层格式

已核验 `Hy-MT2-7B` 的独立 `chat_template.jinja`，对应页面文件提交短 ID 为 `f1f6b69`。单条 `user` 的实际序列为下式；官方模板不会加通用的 `assistant:` 前缀。`<|extra_0|>` 是用户内容结束后衔接生成的标记。[官方 chat template 源码](https://huggingface.co/tencent/Hy-MT2-7B/blob/main/chat_template.jinja)

```text
<|startoftext|>{user_prompt}<|extra_0|>
```

该源码也能表达首个 `system` 与后续对话，典型串为：

```text
<|startoftext|>{system_text}<|extra_4|>{user_prompt}<|extra_0|>{assistant_text}<|eos|>
```

**源码可表达，不等于任意多轮质量有官方保证。** 空首条消息、后续轮次还有条件分支；应用应调用原生模板，而非依据上面两行手工实现全部规则。模板自身没有读取 `add_generation_prompt` 的分支，尾部用户标记已经为生成建立边界。本文没有读取大体积 GGUF 的内嵌模板，因此部署时还应核对本地 GGUF 与原权重模板是否一致。

```python
tokens = tokenizer.apply_chat_template(
    messages,
    add_generation_prompt=True,
    return_tensors="pt",
)
generated = model.generate(tokens, **explicit_generation_settings)
translation = decode_only_new_tokens(generated, prompt_length=len(tokens[0]))
```

对 GGUF 服务提交 `messages` 后让服务应用模型模板；避免在 `content` 中再次拼接特殊 token。以单条 user 建立控制实验，再试 system 或多轮，便于识别收益来自何种变化。

## 3. 多段：三个不同问题

**同一请求放多段并保持边界：有官方分隔符／结构保持能力依据，尚无任意字幕段数可靠性保证。** IFMTBench 单独评价布局保留、结构数据、代码标签，并把格式验证与背景／风格评分分开；它不是“每批 N 条字幕必定 N 条输出”的服务契约。[官方 IFMTBench 定义](https://github.com/Tencent-Hunyuan/Hy-MT2/tree/main/IFMTBench)

下面两条原文放在同一窗口，可共享上下文，但输出必须各归各段。这种“分开”指返回独立字段，**并不意味两段在模型内部彼此隔离**。

```json
{"segments":[{"id":"s17","text":"もういい。"},{"id":"s18","text":"帰ろう。"}]}
```

待测任务可要求仅翻译 `text`，保持对象、数组、ID、顺序；返回一个完整 JSON。也可采用 `<SEG:s17>` 等固定分隔符。字幕中本来出现同类符号时需转义或选择不会冲突的标记；该选择应由程序负责。

**真正独立推理：**每段各建一条请求，服务调度并行处理，结果由程序按 ID 组装。llama.cpp 提供多个服务 slot 和并行请求；它与“将多条消息放入一个聊天历史”不同。一个请求的多条 user 消息代表同一个对话历史，不能借此自动获得多个独立翻译结果。[llama.cpp server 说明](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)

```python
jobs = [(segment.id, make_single_request(segment.text)) for segment in segments]
outputs = bounded_parallel_requests(jobs, max_concurrency=measured_limit)
result = {segment_id: translated_text for segment_id, translated_text in outputs}
```

**连续上下文：**每段单独请求也可以携带只读邻接原文，让目标段与参考段分区。它保留一段一结果的接口，但重复上下文增加成本。是否优于同窗多段、需要前后几段，都应单独测。逐 cue 切碎完整句也可能妨碍翻译；窗口应优先尊重完整句／话轮，再处理字幕映射。

## 4. 输出：普通译文、JSON、SRT 与约束解码

Hy-MT2 的常规输出是生成文字。官方结构数据模板要求只翻译展示文字、保持结构、键名、变量和代码标签。因此**可请求 JSON 或自定布局，不局限于连续纯文本**；“JSON 输入内译文字段”有比任意新 schema 更直接的证据。IFMTBench 验证代码能检查 JSON、HTML、CSV 与 Markdown 表格；这说明官方关注此能力，不提供每次生成保证。其中 JSON 检查类型、键集合和数组长度，没有校验 ID 等具体值是否保持不变；布局检查分隔后的块数，没有证明块内译文忠实。[结构验证源码](https://github.com/Tencent-Hunyuan/Hy-MT2/blob/main/IFMTBench/eval/rule_validators.py)

| 层次 | 能保证什么 | 不能直接保证什么 |
| --- | --- | --- |
| API 请求是 JSON | 传输有结构 | 返回正文也是 JSON |
| prompt 要求保留 JSON | 模型可尝试遵循结构任务 | 无漏段、无错 ID、没有额外说明 |
| server grammar／JSON schema | 在支持的 schema 范围内约束可生成的语法 | 翻译正确、语义齐全、字幕顺序正确 |
| 程序包装译文 | 程序构造合法 JSON 并保留原 ID／时间 | 模型译文内容本身正确 |

llama.cpp server 当前文档提供 `response_format`、`json_schema` 和 `grammar`；可在运行服务支持的版本上为此 GGUF 尝试受约束解码。服务能力与模型受过的翻译训练分开；schema 支持范围、字段名和请求格式应按固定 server 版本核验。[llama.cpp JSON 接口](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#post-v1chatcompletions-openai-compatible-chat-completions)

```python
schema = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["segments"],
    "additionalProperties": False,
}
raw = generate_translation_with_schema(prompt, schema)
parsed = parse_json(raw)
validate_ids_order_nonempty_and_coverage(parsed, source_segments)
```

**建议：**单段任务只让模型输出译文，由程序包装 `{id, text}`；多段任务才比较 ID＋JSON 的价值。时间戳与原 cue 映射由程序保存；如果让模型输出 SRT，需逐项比对时间、编号和 cue 数量。严格保留每行并不一定产生最自然的中文，可把原始语义译文与显示排版分阶段保存。

## 5. 字幕相关证据与容易忽略的变量

官方论文的定性案例确实包含字幕翻译、SRT 格式与 honorifics 保留。它是模型家族的案例展示，没有证明指定 7B／Q8_0 在本机任意 SRT 上的成功率。论文 IFMTBench 的 7B 单约束、复合约束得分分别为 89.73、72.67；这支持从简单提示逐项增加条件，不能解释成字幕通过率。[论文 §3.4、§3.6](https://arxiv.org/html/2605.22064v1)

**量化影响值得单列。** 同一论文 Table 5 的 7B BF16 与 Q4_K_M，在一般 FLORES 聚合分数接近，但 IFMTBench 从 83.14 降到 75.11。普通翻译分数接近不代表结构、术语与背景条件同样稳健。Q6／Q8 在该表没有对应结果；不能由此量化它们的优势。考虑用户质量优先，优先核查现有 Q8_0 是合理实验建议，并非已测排名。[论文量化结果](https://arxiv.org/html/2605.22064v1#S3.SS5)

以下为后续字幕实验建议，全部尚未实测：

1. **人名和称呼：**测试同名角色、别名、敬语、外来语；术语表指定译名不等于所有词形都会命中。
2. **省略与跨行句子：**让模型看完整话轮，再决定译文如何回填；特别审查否定、主客体、性别与关系的无依据补全。
3. **说话人切换：**保留可信说话人提示，测试两人交替短句；无法确认时避免编造标签。
4. **格式与占位符：**测 ASS 标签、HTML 标签、音乐符号、括号、转义字符和重复文本；JSON 能解析仍可能漏译。
5. **长度与压缩：**“每条≤N字符”是可以尝试的偏好，没有核验到官方硬保证；检查是否牺牲意思、否定或数字。阅读速度和断行可由程序检测。
6. **错误传播：**模型生成的前文摘要或译名若有误，后续上下文可能持续污染；可靠原文与已审定信息优先。
7. **重试稳定性：**结构错误重试可能改变已正确译文，宜仅恢复失败单元；记录恢复次数、覆盖和总时间。

生成设置同样需要冻结。官方 README 的 7B 推荐为 `temperature=0.7`、`top_p=0.6`、`top_k=20`、`repetition_penalty=1.05`、输出预算 4096；实际发布的 `generation_config.json` 却写 `top_p=0.8`，其他主要采样值一致。直接加载默认值与显式按 README 执行不是同一配方。[推荐值](https://huggingface.co/tencent/Hy-MT2-7B-GGUF#inference-and-deployment)、[发布的 generation_config](https://huggingface.co/tencent/Hy-MT2-7B/blob/main/generation_config.json)

建议以显式推荐值建立第一份控制，再将低温／确定性解码列为独立对照；低温本身不证明更忠实。各后端的 repetition penalty 参数命名和作用范围也应核对。

## 6. Windows／RTX 5080 本地运行路线与未验证事项

GGUF 的自然候选是 **llama.cpp Windows CUDA 构建**；官方工程也提供 Windows Vulkan 构建。CUDA 与 Vulkan 是不同 GPU 后端，不能只凭界面显示“GPU”判定运行栈。应使用支持本架构和量化的固定稳定版，记录驱动、构建 ID 和实际设备；本文没有执行兼容性测试。[llama.cpp 构建说明](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)

已获取本地权重后，示意命令如下；仅为待验证运行配方，未执行：

```powershell
& '.\llama-server.exe' -m 'D:\models\HY-MT2-7B-Q8_0.gguf' --jinja -ngl 99 -c 8192 -np 1 --host 127.0.0.1 --port 8080
```

`-ngl 99` 请求足够层数的 GPU offload；需检查启动日志确认实际 offload、模板与 KV 配置。基础构建保留 CPU 后端，单凭传参不能证明全部模型层和算子均按预期在 GPU 上执行。`-c 8192`、单 slot 是初始验证窗口，后续并发增加前应重新量测资源。上述参数依据[server 选项](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)，不是本机性能结论。

**官方通用示例存在一处容易误读的部署说明。** GGUF 卡提到依赖 STQ PR #22836，同时给出 `-ngl 0`。该 PR 截至访问日仍为 Open，内容是 STQ1_0 极低位三值量化及 CPU ARM NEON 内核，示例对象主要为 1.8B／1.25-bit；指定 7B GGUF 文件树则为 Q4_K_M／Q6_K／Q8_0。本次未检查权重张量类型，因此既不认定普通 7B 文件都依赖 STQ，也不宣布其加载已通过。部署应按实际 GGUF 张量类型和目标 GPU 后端核验；不能把 CPU 示例当成 5080 推荐设置。[模型卡](https://huggingface.co/tencent/Hy-MT2-7B-GGUF#llama_cpp)、[STQ PR #22836](https://github.com/ggml-org/llama.cpp/pull/22836)

Transformers 路线对应原权重，不能直接把 GGUF 路径传给同一加载代码；官方当前示例要求 `transformers>=5.6.0`，且系列示例使用的是 30B-A3B 路径。后续若评估 7B，应明确改为指定 7B、显式设备和输出设置，再核对模型支持。16.1 GB 的原权重仓库文件总量也不能当作运行显存消耗。[原权重文件树](https://huggingface.co/tencent/Hy-MT2-7B/tree/main)

本轮未下载权重、安装软件、运行推理或传输用户字幕。尚待核验：本地 Q8_0 文件来源／SHA256／内嵌模板、稳定 llama.cpp 版本兼容性、5080 真实 offload、峰值显存、每秒生成速度、日中字幕质量、批段覆盖率、格式遵循率和最佳窗口。现有 STT 配方不受本研究改变。

## 来源记录

以上链接均于 **2026-10-05** 核验；HF／GitHub `main` 与 llama.cpp `master` 属于访问日快照，不是冻结部署版本。后续实验需记录完整 revision 和本地文件哈希。

- 用户指定 GGUF 仓库文件树当日最新页面短提交为 `ab84726`；原权重文件树为 `9b0eb4e`。模板与 generation_config 文件页面的来源提交短 ID 为 `f1f6b69`。
- 官方论文为 arXiv **2605.22064v1，2026-05-21**，取用其 Table 4、Table 5 与 §3.6；厂商评测不能代替本项目冻结日中字幕对照。
- IFMTBench 是官方翻译指令遵循基准；文中的 JSONL `md5/response` 输出包装是评测文件格式，不等于模型必须生成该包装。
- llama.cpp 文档取用当日 `master` 的 server 与 build 文档；接口能力需在最终选定的稳定发布版本重新确认。
