# 日语 CTC 候选的官方来源核验

> 2026-10-05 后续开发入口：将本文 MMS 输入／adapter 契约用于当前 W0 时，复用并更新 [W0 demo](../../experiments/w0_demo/README.md) 的 `alignment.py`；模型许可和来源结论仍以本文为据，实际移植与数值配置见 [demo 验证](../testing/2026-10-05-w0-demo-validation.md)。

状态：来源核验完成；接入建议不代表声学质量或生产后端采用结论  
最后更新：2026-10-04  
范围：用户提供的四个日语 CTC 候选，模型身份、输入契约、token 粒度、许可与当前对齐体系的接入条件。

相关文档：[外部参考](2026-10-04-japanese-ctc-alignment-reference.md)、[基准线及历史候选](../architecture/stt-candidate-pipelines.md)、[推理选择原则](../development/inference-selection.md)、[验证边界](../testing/validation.md)。全部来源访问日期为 **2026-10-04**。本核验只读取官方模型卡、配置、词表与 API 元数据，没有上传音频或执行 GPU 推理；实测另行记录。

## 固定模型身份

模型 API 的 `sha` 是本次核验时 `main` 的最新提交，模型仓库没有以语义版本发布这些 checkpoint。后续下载须固定对应 revision，避免运行期间移动 `main`。

| 候选 | revision | 已核验许可 | 接入关键点 |
| --- | --- | --- | --- |
| `reazon-research/japanese-wav2vec2-large-rs35kh` | `2162c9edb97f362f7623d6b3a2e417458e879bca` | Apache-2.0 | 混合单字与多字 token；模型 blank 与 tokenizer pad 不同。 |
| `jonatasgrosman/wav2vec2-large-xlsr-53-japanese` | `cf031e020336460d15a417eba710bbc5bb43be9a` | Apache-2.0 | 当前已测基线；字符映射与已有体系相容。 |
| `facebook/mms-1b-all`＋`jpn` | `3d33597edbdaaba14a8e858e2c8caa76e3cec0cd` | CC-BY-NC-4.0 | 必须同步加载日语 tokenizer 与 adapter；默认语言为 `eng`。 |
| `slplab/wav2vec2-xls-r-300m-japanese-hiragana` | `d3a14c42fb73398697e5815e548b16994773b636` | 模型卡/API 未声明，仓库列表无独立许可文件 | 假名文字与原文映射需要新增契约；blank 为 121。 |

身份和许可来源分别是官方 API：[Reazon](https://huggingface.co/api/models/reazon-research/japanese-wav2vec2-large-rs35kh)、[Jonatas](https://huggingface.co/api/models/jonatasgrosman/wav2vec2-large-xlsr-53-japanese)、[MMS](https://huggingface.co/api/models/facebook/mms-1b-all)、[slplab](https://huggingface.co/api/models/slplab/wav2vec2-xls-r-300m-japanese-hiragana)。其中前三个新增候选的 API 原始证据存放在忽略目录 `.local/japanese-ctc/*-metadata.json`。许可缺失不等于禁止实验，也不能据 backbone 的许可推定该 fine-tune 权重许可。

## Reazon：有价值，但不能只替换模型名称

[发布者模型卡](https://huggingface.co/reazon-research/japanese-wav2vec2-large-rs35kh)将其描述为日语 Wav2Vec2 Large、ReazonSpeech v2.0 fine-tune。官方 API 记录 **318,507,067** 个 F32 参数；模型卡的公开 ASR 比较包含 JSUT、Common Voice、TEDxJP 和长语音 JSUT-BOOK。这支持开展独立对齐实验的动机，但不能证明 forced alignment 优于现有模型。

[config](https://huggingface.co/reazon-research/japanese-wav2vec2-large-rs35kh/blob/2162c9edb97f362f7623d6b3a2e417458e879bca/config.json)、[vocab](https://huggingface.co/reazon-research/japanese-wav2vec2-large-rs35kh/blob/2162c9edb97f362f7623d6b3a2e417458e879bca/vocab.json)、[added tokens](https://huggingface.co/reazon-research/japanese-wav2vec2-large-rs35kh/blob/2162c9edb97f362f7623d6b3a2e417458e879bca/added_tokens.json)揭示了外部参考未指出的边界：

- `Wav2Vec2ForCTC`，24 层、hidden size 1024；输出维度 3003。基础词表 3000 个，另加 `<s>` 3000、`</s>` 3001、`<pad>` 3002。
- 模型 `pad_token_id=0`，基础词表 `<unk>=0`；tokenizer 的 `<pad>` 则为 3002。因此 CTC blank 必须按模型配置取 0，不能改取 tokenizer pad，也不能把未知文字的 0 作为对齐 target。
- 词表混合单字符与多字符，包括 `今日`、`東京`、`です`、`と思います`，以及带 `▁` 的 token。逐字符查表会改变该 checkpoint 的原生 token 序列。
- 词表存在 `。`、`、` 和 `▁`；tokenizer 配置的 word delimiter `|` 没有基础词表项。ASCII 大写 `A` 没有词表项，小写 `a` 为 382。文字大小写、空格及边界标记必须显式验证。

官方示例使用 `AutoProcessor`、`Wav2Vec2ForCTC`、16 kHz、CUDA BF16、`flash_attention_2`，并建议两侧各补 0.5 秒静音。[feature extractor 配置](https://huggingface.co/reazon-research/japanese-wav2vec2-large-rs35kh/blob/2162c9edb97f362f7623d6b3a2e417458e879bca/preprocessor_config.json)要求均值/方差归一化。原生 Windows 是否能执行示例 attention 实现须另测；使用稳定环境已有 SDPA/eager 时，应登记与示例的差异。补静音必须修正输出源时间坐标，不能将新增样本压缩进原窗口。

本机已有 Transformers 4.57.6 环境完成了只读、离线 tokenizer 探针：`今日は東京へ行きます。` 实际分成 `今日 / は / 東京 / へ / 行 / きます / 。`；`3人のABC` 保留 `A / B / C` 原字符再转为 ID 0，因此可按原字符区间记 OOV，不会自动输出字面 `<unk>`。` この 東京 ` 的空格被 added-token `lstrip/rstrip` 吸收，只保留 `この / 東京`；只有输入字面 `▁この` 才得到对应边界 token。词表存在 `▁` 不代表当前 processor 会自动按 SentencePiece 规则插入它。这些是固定 tokenizer 的运行观察，不能扩展为未知训练预处理的结论。

**建议：**进入实测，但新增 token-span 到原文-span 的映射；多字 token 内部没有独立字符声学边界时，须标识共享区间，不应伪造逐字精度。至少对比原生 token 序列与逐字诊断，保留 OOV、blank target、窗口失败的完整记账。

## Jonatas：保留同条件基线

[模型卡](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-japanese)说明其在 XLSR-53 上用 Common Voice 6.1、CSS10、JSUT fine-tune，要求 16 kHz。[固定 config](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-japanese/blob/cf031e020336460d15a417eba710bbc5bb43be9a/config.json)为 `Wav2Vec2ForCTC`、24 层、hidden size 1024、vocab size 2341、blank/pad 0。[preprocessor](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-japanese/blob/cf031e020336460d15a417eba710bbc5bb43be9a/preprocessor_config.json)要求归一化与 attention mask。

个人账号、发布时间和 ASR 分数不能单独证明对齐质量较差，WhisperX 使用历史也不能证明其具有更精确边界。沿用当前已测 checkpoint，用同一 PCM、固定 ASR 文字、搜索窗、标准 CUDA CTC 解码与计分作基线，才可回答是否值得替换。

## MMS：日语 adapter 必须真正加载

[Meta 模型卡](https://huggingface.co/facebook/mms-1b-all)确认 Wav2Vec2 CTC、1B 规模、语言 adapter，以及 CC-BY-NC-4.0。[固定 tokenizer 配置](https://huggingface.co/facebook/mms-1b-all/blob/3d33597edbdaaba14a8e858e2c8caa76e3cec0cd/tokenizer_config.json)的默认 `target_lang` 是 `eng`；日语资源为 `adapter.jpn.safetensors` / `adapter.jpn.bin` 和对应词表。不能仅给 WhisperX `align_model` 传入模型名后假定已切换日语。

[Transformers MMS 官方 API 文档](https://huggingface.co/docs/transformers/v4.57.1/model_doc/mms)给出两种路径：初始化 processor 和 model 均传 `target_lang="jpn"`，模型配合 `ignore_mismatched_sizes=True`；或加载后执行 `processor.tokenizer.set_target_lang("jpn")` 与 `model.load_adapter("jpn")`。后者会替换语言 head，必须确认实际语言、head 维度、adapter 文件及 revision，不能将随机初始化 head 当作已加载日语模型。

离线 provision 只需要共享权重、配置、tokenizer 与日语 adapter，无需下载所有语言 adapter。正常推理设置 `local_files_only` 并禁止隐式获取缺失资源。官方模型卡的旧“若 4.30 未发布则从源码安装”文字已是历史说明，不构成本轮升级到开发版本的理由。新模型 forward、显存与速度需要实测；NC 许可使它更适合作研究对照，不能直接声称适合商业产品默认。

## Hiragana：按发布者转换规则试验，保留原文映射

[slplab 模型卡](https://huggingface.co/slplab/wav2vec2-xls-r-300m-japanese-hiragana)说明其基于 XLS-R-300M，在 JSUT 和 Common Voice 上以平假名 fine-tune，输出无词边界。示例实际文字转换是：移除 `[、,。]`，`strip()`，调用 `pykakasi.kakasi().convert(text)`，拼接每项 `hira`。示例虽然安装/实例化 MeCab 与 UniDic，但显示的转换函数没有使用 MeCab 分词；不能据此把 MeCab 当作必要推理依赖。

[config](https://huggingface.co/slplab/wav2vec2-xls-r-300m-japanese-hiragana/blob/d3a14c42fb73398697e5815e548b16994773b636/config.json)与[词表](https://huggingface.co/slplab/wav2vec2-xls-r-300m-japanese-hiragana/blob/d3a14c42fb73398697e5815e548b16994773b636/vocab.json)为 122 个输出项、blank `[PAD]` 121；tokenizer 使用 `[UNK]`，不能照抄当前模型的 blank 0。汉字、片假名不直接存在于该词表；平假名、长音、小假名和部分数字/Latin 符号存在。输入契约仍为 16 kHz、feature extractor 归一化。

**建议：**可用作者推荐的 pykakasi 开展有界诊断，但要把自动读音、原文字符区间和假名区间作为证据保存；不人工按字幕改读音，不改写最终 ASR 原文。姓名、数字、多音词及助词实际发音可能成为额外误差来源，低 OOV 并不等于读音正确。多字词读取后的边界只能可靠映射到原文词组区间，不能把均匀分配的字符时间宣称为声学证据。模型权重许可仍未明确，不宜直接采纳为生产默认。

## 对本轮验证的影响

Reazon、MMS、hiragana 都值得先检验“接口与 token 契约是否成立”，再以相同 ASR 文字和音频补充对齐比较。本文能够确认身份、API 与工程差异；谁值得纳入 W0/W1/X0 下一轮质量评估，必须结合实际 GPU 运行、完整分母时间成功、文字覆盖、灾难性漂移、耗时与显存。当前来源证据不能选择新默认。
