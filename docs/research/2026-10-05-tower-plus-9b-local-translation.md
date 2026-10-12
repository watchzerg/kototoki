# Tower-Plus-9B：本地翻译接口、结构输出与字幕适用性

状态：公开资料调研完成；探索性建议，未采纳，未下载模型、未做本机推理或日中字幕质量实验。

最后更新：2026-10-05。

范围：用户指定的 `Unbabel/Tower-Plus-9B`，重点是日语→简体中文字幕。模型仓库本次公开 API 返回 revision `c59d17c5bbf5eb6d9f0f8ba67e0ee76b4b106ecc`；论文核查包括 arXiv 2025 v1 和 ACL 2026 正式版。外部来源访问日期均为 2026-10-05；推理引擎动态文档未冻结为本机版本。本文不改变项目当前原语言 STT 里程碑。[模型仓库](https://huggingface.co/Unbabel/Tower-Plus-9B)、[公开 metadata](https://huggingface.co/api/models/Unbabel/Tower-Plus-9B)、[ACL 2026 正式论文](https://aclanthology.org/2026.acl-long.1366/)

## 1. 直接回答

Tower+ 9B 值得作为“翻译质量＋额外指令”的候选：它使用聊天消息接口，可以把术语和格式要求写进任务说明。应保留它自己的 chat template；正文任务不必限制在唯一一句固定 prompt。文档支持程度与实际字幕可靠性要分开看。

| 用户关心的能力 | 本次结论 | 证据边界 |
| --- | --- | --- |
| 自由提示词 | 可以改写任务说明；属于带通用指令能力的翻译模型 | 官方推荐格式是起点；任意复杂 prompt 没有逐项保证 |
| 标题、背景 | 可作为 user 内容的一部分输入 | 没有独立 `context` 参数；收益和“只参考不输出”的服从率未测 |
| 词汇表 | 有较强研究依据，可用自然语言列出对应关系 | IF-MT 包含 glossary following；不是词汇强制解码接口 |
| 一次输入多段 | 可放在同一待译文本中，也可给每段 ID | 同一序列共享上下文；保留段数、ID 和独立边界需验证 |
| 每段真正独立处理 | 可以由推理引擎批处理多个独立请求 | 批处理不是把所有段落拼进一个 user 消息 |
| JSON／特定格式 | 可以做 prompt 实验，也可用引擎 schema／grammar | 未找到 Tower+ 9B 官方 JSON 翻译契约或合格率 |
| 字幕时间与断行 | 程序端保留时间；译文长度与断行另行处理 | 未找到该 checkpoint 的 SRT／ASS 时间保持保证 |

上表综合来源为[模型卡](https://huggingface.co/Unbabel/Tower-Plus-9B)、[实际 tokenizer 模板](https://huggingface.co/Unbabel/Tower-Plus-9B/blob/main/tokenizer_config.json)、[论文 §2、§3 及附录 H](https://aclanthology.org/2026.acl-long.1366.pdf)、[vLLM 批量聊天接口](https://docs.vllm.ai/en/latest/api/vllm/entrypoints/llm/)。背景／JSON／字幕映射行中的工程判断是本文建议。

## 2. 身份、语言和容量

**已核验：**这是基于 Gemma 2 9B 的 decoder-only 文本模型，原始发布为 BF16 Safetensors；官方列日语、简体／繁体中文及多种欧洲语言。卡中“22 languages”与地区／字形变体的逐项列表使用不同计数口径，不能理解为所有语言组合都获得了相同质量验证。[模型卡](https://huggingface.co/Unbabel/Tower-Plus-9B)

配置与 tokenizer 都给出 **8192 tokens**。配置的 `sliding_window=4096` 是滑动注意力窗口，不能直接当成总输入长度；`max_position_embeddings=8192` 才是本 checkpoint 标称总上下文的关键值。[配置](https://huggingface.co/Unbabel/Tower-Plus-9B/blob/main/config.json)、[tokenizer 配置](https://huggingface.co/Unbabel/Tower-Plus-9B/blob/main/tokenizer_config.json)

**工程建议：**把模板、任务说明、背景、glossary、待译正文和预期输出一起算入预算。不要将“8192 上下文”写成“可输入 8192，再生成 8192”。官方示例的 `max_tokens=8192` 是生成上限参数，也受总上下文约束。卡里的旧版 vLLM 长上下文环境变量提示应在未来实验时按当时稳定版本重核，不作为本机已需要的配置。[官方用法](https://huggingface.co/Unbabel/Tower-Plus-9B)

```python
input_tokens = count_tokens(apply_chat_template(messages))
output_budget = estimate_translation_tokens(source_text, output_format)
assert input_tokens + output_budget <= effective_context_limit
```

`effective_context_limit` 应取 checkpoint、引擎与服务实际配置中适用的上限。预算不足时缩小正文或检索背景；静默裁掉尾部会让字幕漏译看起来像正常结果。

## 3. 两层模板：聊天包装与翻译任务

### 3.1 必须匹配的聊天包装

官方 tokenizer 按消息顺序写出 `<start_of_turn>`／`<end_of_turn>`，把 `assistant` 角色换成 `model`，并在请求生成时添加 model 开头。单轮的可视化结构如下；花括号是本文占位符。[实际模板](https://huggingface.co/Unbabel/Tower-Plus-9B/blob/main/tokenizer_config.json)

```text
<bos><start_of_turn>user
{translation_task_and_source_text}<end_of_turn>
<start_of_turn>model
```

自然语言解释：user 回合包含“要做什么＋待译内容”；model 回合由模型补出译文。使用 Transformers 时交给 `apply_chat_template`；支持该模板的聊天服务应自己包装消息，避免用户手工包装后服务再包一层。

```python
messages = [{"role": "user", "content": task_text}]
input_ids = tokenizer.apply_chat_template(
    messages,
    tokenize=True,
    add_generation_prompt=True,
    return_tensors="pt",
)
output_ids = model.generate(input_ids, do_sample=False, max_new_tokens=budget)
translation = tokenizer.decode(
    output_ids[0][input_ids.shape[-1]:],
    skip_special_tokens=True,
)
```

以上是接口伪代码，省略设备与权重获取。官方示例使用确定性生成；建议先照此建立格式控制，再比较额外要求。解码时仅取新生成的 token，避免将原始 prompt 误当成输出。[模型卡示例](https://huggingface.co/Unbabel/Tower-Plus-9B)

**`system` 的细节容易误判：**这个仓库的模板没有拒绝 system role，也没有检查 user／assistant 是否交替；它会把其他角色名称原样写入。因而“Gemma 系列一律不能接 system”不适用于这个模板的代码层面。另一方面，能序列化 system 不证明这个模型在该角色上的语义服从率。未来字幕控制实验优先把规则放在一个 user 消息里，并单列 system／多轮实验。[tokenizer 源码](https://huggingface.co/Unbabel/Tower-Plus-9B/blob/main/tokenizer_config.json)

### 3.2 官方推荐的翻译任务形状

卡中示例的任务结构是“说明源语和目标语，给源语言标签和正文，最后给目标语言标签”。下面把示例语言替换成日语与简体中文；这是模板结构的改写示例，未在本机运行。[官方翻译示例](https://huggingface.co/Unbabel/Tower-Plus-9B)

```text
Translate the following Japanese source text to Chinese (Simplified):
Japanese: {source_text}
Chinese (Simplified):
```

```python
def build_basic_task(source_text):
    return (
        "Translate the following Japanese source text to Chinese (Simplified):\n"
        f"Japanese: {source_text}\n"
        "Chinese (Simplified):"
    )
```

这个任务文本与上一节的 token 包装是两回事。要准确保持聊天包装；任务说明可增加规则。论文使用多种翻译 instruction 模板，SFT 包含文档翻译和风格适配；IF-MT 专门测试翻译同时执行额外规则。因此不能把官方示例误写成唯一允许的自然语言句式。[正式论文 §2.2、§3.1 及附录 D](https://aclanthology.org/2026.acl-long.1366.pdf)

## 4. 标题、背景、词汇表怎样输入

Tower+ 没有在模型卡中定义 `title`、`context`、`glossary` 专门字段。可把这些作为普通 prompt 内容传入；这是调用者设计的文本协议。

**研究证据：**IF-MT 包含术语、日期和货币等可检验规则，语对为英语→中文／西班牙语。它支持“可以要求翻译同时遵守规则”的判断，但不证明日中影视称呼、人物指代或复杂 glossary 必然服从。[正式论文 §3.1](https://aclanthology.org/2026.acl-long.1366.pdf)

论文附录 H 的 **Table 5 明确报告英语→中文**：Tower+ 9B 的规则服从评分为 **4.02／6**，翻译 COMET-22 为 **89.42**；对照 Tower-v2 70B 为 2.38／88.25，Gemma-2 9B 为 4.06／88.94，Tower+ 72B 为 4.93／89.82。这是实际测试 9B 的证据；它较旧 Tower-v2 明显改善，却不能声称比基础 Gemma-2 9B 更遵守规则。该平均分也不等于 glossary 命中率或 JSON 合格率；本报告采用分语对 Table 5，避免将正文综合表不同数值当成同一结果。[正式论文附录 H，Table 5](https://aclanthology.org/2026.acl-long.1366.pdf)

**建议模板，未实测：**标题与相邻对白明确标记为参考；正文单列；术语只放当前文本可能用到的项。下面的提示词用于说明接口设计，英文标签和文本不是模型的强制语法。

```python
task_text = f"""
Translate SOURCE from Japanese into Simplified Chinese.
Use BACKGROUND and CONTEXT only to resolve ambiguity; do not translate them.
Apply relevant GLOSSARY entries. Preserve meaning, negation, numbers, and tone.
Return only the translation of SOURCE.

BACKGROUND:
Title: {title}
Scene: {verified_scene_description}

CONTEXT:
Previous dialogue: {previous_source_turns}
Next dialogue: {next_source_turns}

GLOSSARY:
{source_term_to_approved_translation_pairs}

SOURCE:
{current_source_unit}
"""
messages = [{"role": "user", "content": task_text}]
```

自然语言解释：先规定只翻译 SOURCE；参考区只帮助消歧；glossary 给已确认译法；最后列当前要翻译的内容。模型是否漏掉参考区界限、强行套入不适用术语，均需要人工和程序检查。

**字幕建议：**标题是主题先验，相邻原文通常更接近当前对白。不要让简介中的剧情信息替代句内证据；不要把模型猜出的性别、称呼或人物关系放进“已确认背景”。glossary 与 TM 分开：前者固定术语译法，后者是审核过的源译句对；滚动摘要也要保留源范围，避免一次误译传遍整片。

## 5. 多段输入：共享上下文与真正独立的 batch

### 5.1 一个请求包含多个段落

可以把完整段落或几个话轮放入一个 SOURCE；模型能读取所有段落，但产出仍是一条生成序列。多段正文的语义能力不等于字幕段界自动可靠。需要每段返回时，可以尝试 ID 列表协议，另测合并、重复、错配、漏段和提前结束。

```python
task_text = build_rule_prompt(
    instruction="Translate each item; preserve IDs; keep one result per item.",
    items=[
        {"id": "u101", "text": "明日、駅で待ってる。"},
        {"id": "u102", "text": "分かった。"},
    ],
    reference_context=nearby_dialogue,
)
```

这两个项目共享上下文，适合问答消歧；“每段分开返回”只约束输出边界，不能称作推理独立。输入 ID 可对应完整句／话轮，无需等于原 SRT cue ID。

### 5.2 多个独立请求由引擎批处理

vLLM `LLM.chat` 接收一个会话或一组会话，并按输入顺序返回各请求结果；各会话有独立的 prompt 序列。[vLLM API](https://docs.vllm.ai/en/latest/api/vllm/entrypoints/llm/)

```python
conversations = [
    [{"role": "user", "content": build_basic_task(segment.text)}]
    for segment in segments
]
outputs = llm.chat(conversations, sampling_params)
results = [
    {"id": segment.id, "translation": output.outputs[0].text}
    for segment, output in zip(segments, outputs)
]
```

自然语言解释：模型权重只加载一次，引擎同时或连续调度多个独立任务；相邻句不会自动互相可见。若希望每个任务知道共同背景，要在各自 prompt 中显式重复或检索提供。请求级隔离与后台是否复用 prefix cache 是不同概念。

**工程建议：**批处理大小是吞吐和显存变量，正文窗口大小是语义变量，分别调。不要往一个会话里连续追加多个 user 消息，期待引擎将它们自动视为多个独立翻译请求。

## 6. JSON、定制格式与普通译文

### 6.1 普通译文

最容易建立的基线是每个语义单元只生成译文，程序自行保存 ID／时间和 JSON 外壳。模型不用重复已经确定的元数据；结构完整性也不依赖它逐字符复制时间。

```python
translated_text = translate_one(source_unit.text)
result = {
    "id": source_unit.id,
    "translation": translated_text,
    "source_cue_ids": source_unit.source_cue_ids,
}
```

这是本文建议，不能据此宣布 JSON 生成必然降低译文质量。

### 6.2 Prompt 要求 JSON 或分隔符

可以要求模型生成如下结构，也可以要求固定标签／分隔符。未找到官方保证的 Tower+ 9B JSON 翻译接口；准确说法是“可实验，可靠性未核验”。

```json
{"translations":[{"id":"u101","text":"明天我在车站等你。"},{"id":"u102","text":"知道了。"}]}
```

```python
task_text = build_translation_task(items)
task_text += "\nReturn a JSON object with a translations array."
task_text += " Each item must contain the original id and translated text."
task_text += " Do not include Markdown fences or explanations."
raw_output = generate(task_text)
parsed = json.loads(raw_output)
validate_exact_id_set(parsed, expected_ids)
validate_nonempty_translations(parsed)
```

上面的中文译文仅为人工示意，不是模型实测。JSON 解析成功仍可能漏项、串译、反转否定、留下未译日文。分隔符也可能出现在原文中，或被模型改写。应选择不与正文冲突的标记，并设计单项重试与完整分母的失败统计。

**证据误用提醒：**论文中确实出现要求输出 JSON 的 prompt，但该处是 IF-MT 的评审模型打分格式；不能把它当成 Tower+ 翻译模型已支持 JSON 的实验。[正式论文附录 H，评审 prompt](https://aclanthology.org/2026.acl-long.1366.pdf)

### 6.3 引擎约束解码

vLLM 文档提供 JSON schema、regex、grammar 等 structured outputs；llama.cpp server 提供 schema 约束 JSON。它们是解码引擎能力，需要绑定实际引擎版本、后端和支持的 schema 子集。[vLLM 文档](https://docs.vllm.ai/en/latest/features/structured_outputs/)、[llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)、[llama.cpp schema 子集源码](https://github.com/ggml-org/llama.cpp/blob/master/common/json-schema.h)

```python
# Engine-specific pseudocode; this shape follows vLLM documentation.
response = client.chat.completions.create(
    model=served_model_name,
    messages=messages,
    extra_body={"structured_outputs": {"json": result_schema}},
)
```

自然语言解释：grammar／schema 屏蔽不允许的下一 token，以提高格式合格率；prompt 仍要说明哪个字段放译文。约束覆盖的语法可以更可靠，但不保证忠实度、段落对应关系或不漏语义；输出被 token 上限截断时也可能没有完整 JSON。别把上面的 vLLM 参数原样视为 llama.cpp 参数。

建议并行比较“纯译文＋程序包装”“prompt JSON”“schema JSON”。分别记录翻译错误、格式失败、ID 完整率、重试次数与端到端耗时；不能只排名 JSON 解析率。

## 7. 尤其影响字幕的特性

以下是基于接口与项目需求提出的验证项目，均未在该模型上实测：

| 特性／风险 | 对日中字幕的影响 | 建议验证或处理 |
| --- | --- | --- |
| 文档与额外指令能力 | 有机会利用相邻对白、风格、术语 | 比较逐 cue、完整话轮、话轮＋邻接原文；不能用一般 benchmark 替代日中人工检查 |
| 单一生成序列 | 多段可能被改写为流畅长段，破坏 ID 对应 | 用 1／若干语义单元做受控比较，严格检查遗漏和串译 |
| 日语省略主语和宾语 | 孤立短句容易猜错施事者、对象、语气 | 提供可靠邻接上下文；不要求中文把每个省略项都补出来 |
| 通用聊天能力 | 可能解释、回答对白中的问题、添加点评 | 明确待译区与输出任务；用命令、问句、引号内容做挑战样本 |
| 术语规则是软指令 | 人名表可能执行不一致或过度套用 | 只检索相关术语；检查原写法、简称、同音和多人称呼 |
| 长度约束与忠实度冲突 | 为字数目标压缩时可能删除否定、数字、态度 | 保留完整语义译文；压缩另列步骤或实验开关 |
| 文字模型 | 不从文字推导真实声学时间；看不到画面和声音 | 上游提供可验证 metadata；时间留在程序端 |
| 本次没有字幕专用证据 | 一般翻译成绩不覆盖读速、断行、时间对应 | 冻结源字幕和映射，独立检查显示及语义出现时间 |

**本文建议：**完整句／话轮是翻译单元，cue 是显示单元。一个完整句可能跨几个源 cue；先保留 `source_cue_ids` 和时间跨度，译后再按语义、读速和原时间模板回填。若需要重新分配 cue，应独立验证，不让模型生成“看似合理”的新时间戳。具体窗口、字数、读速阈值应来自后续字幕规格，不在本报告里凭空指定。

## 8. 本地 Windows／RTX 5080 的可行路线

### 8.1 原始 BF16 与量化

公开 metadata 给出 `9,241,705,984` 参数；按 BF16 两字节计算，单权重载荷约 **18.48 GB＝17.21 GiB**，还未计 KV cache 和运行缓冲。这是算术估算，文件列表约 18.5 GB 与之相符。[公开 metadata](https://huggingface.co/api/models/Unbabel/Tower-Plus-9B)、[官方文件列表](https://huggingface.co/Unbabel/Tower-Plus-9B/tree/main)

RTX 5080 官方标准显存为 16 GB。因此原始 BF16 全权重驻留单卡就超过容量；全 GPU 路线需要量化，不能把 `device_map="auto"` 成功加载误当成全 GPU。[NVIDIA 规格](https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5080/)

**建议：**优先评估能保留较高精度的 GGUF Q8，再按 KV cache、窗口和并发压力决定是否比较 Q6／Q5。精度越高不代表固定16 GB下所有窗口都能运行；GGUF 标签不能证明术语或格式质量。此次没有核验某个第三方量化文件的哈希、体积或转换参数，也没有选定量化发布者。原仓库发布的是 Safetensors，不能把 HF 自动显示的“本地 app／quantizations”链接当成 Unbabel 官方 GGUF 保证。[原始发布文件](https://huggingface.co/Unbabel/Tower-Plus-9B/tree/main)

配置还标记 hybrid cache、42 层、8 个 KV heads、head dimension 256；这些影响长上下文显存。配置里 `use_cache=false` 也值得在选定后端核查，不应静默改配置后把性能归给官方原配方。[配置](https://huggingface.co/Unbabel/Tower-Plus-9B/blob/main/config.json)

### 8.2 推理引擎

| 路线 | 文档支持 | 本项目判断 |
| --- | --- | --- |
| vLLM | 模型卡优先推荐；官方安装文档以 Linux 为要求，明确不原生支持 Windows | 可作为 WSL／Linux 实验路线；不作为原生 Windows 已验证方案 |
| Transformers | 官方提供加载和聊天示例 | 原始 BF16 全卡不适合16 GB；量化 backend／Blackwell kernel 支持需另查实测 |
| llama.cpp＋GGUF | 上游转换源码注册 Gemma2；发布提供 Windows CUDA／Vulkan 构建；server 有批处理和 schema | 有原生 Windows 探索价值；仍须核验转换来源、Tower 自定义模板、停止 token 和全GPU驻留 |

来源：[模型卡](https://huggingface.co/Unbabel/Tower-Plus-9B)、[vLLM 平台要求](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)、[Gemma2 转换源码](https://github.com/ggml-org/llama.cpp/blob/master/conversion/gemma.py)、[llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases)、[server 文档](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)。引擎支持某架构不等于指定量化文件已在 RTX5080 正常翻译。

未来复现至少冻结：原 checkpoint revision、GGUF 哈希／量化和转换 revision、引擎稳定版本、CUDA 或 Vulkan backend、chat template、EOS=`<end_of_turn>`／107、上下文配置、采样、输出上限、GPU驻留与峰值显存。先做单条与多段完整性 smoke test，再测吞吐；没有本机证据时不声称运行速度或具体并发。

## 9. 许可证与质量证据的限制

**官方资料存在冲突：**HF 仓库 metadata 为 `cc-by-nc-sa-4.0`，模型卡正文写 `CC-BY-NC-4.0`；二者都有 NC，但 ShareAlike 条款不同。不能将其归为 Apache／MIT 或无条件商用许可；产品使用或再分发前应确认发布者适用文本。此次只记录冲突，不替发布者作法律解释。[模型卡与 metadata](https://huggingface.co/Unbabel/Tower-Plus-9B)

**质量证据：**正式论文的 IF-MT 包含英语→中文，证明评测关注“翻译＋规则”；不涵盖本项目日中动画字幕。9B 的规则服从成绩并非满分，也不能把 72B 的结论直接归给 9B。论文讨论 GRPO 的收益有限，发布卡对 9B 只写 CPT／IT／WPO；不要用系列训练介绍断言该发布权重已经受所有阶段强化。[正式论文 §4.2、附录 H](https://aclanthology.org/2026.acl-long.1366.pdf)、[模型卡](https://huggingface.co/Unbabel/Tower-Plus-9B)

## 10. 最小而有区分力的后续实验

建议按以下次序准备实验；这是研究计划，本轮未实现：

1. 单条官方形状 prompt＋纯译文，确认模板、EOS、语言和无附加解释；记录单GPU驻留、延迟与峰值显存。
2. 固定模型／量化，比较逐 cue 和完整话轮；再增加邻接原文，检查省略、否定、人称、数字、称呼与口吻。
3. 独立添加相关 glossary、标题／背景；使用同义词、简称和歧义名字检查收益与误用。
4. 比较独立 batch 与单 prompt 多项；批处理大小和共享语义窗口分别记录。
5. 同一输入比较纯译文包装、prompt JSON、schema JSON；将漏项、重复、ID 错配、截断和结构重试计入全分母。
6. 固定译文后评估原 cue 回填与重排策略；读速、断行和时间同步单独验收。

本轮交付是公开来源与接口核查。没有把用户字幕／音频送入外部推理，没有模型下载、安装、性能测量或产品翻译入口；尚不能给出日中质量排名、最佳窗口或 quantization 质量结论。综合比较见同目录的三模型汇总文档。
