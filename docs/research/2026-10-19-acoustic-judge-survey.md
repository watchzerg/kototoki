# 音频接地裁判候选调研：MMS CTC 是最优，还是只是顺手

状态：exploratory（2026-10-19）。纯桌面调研：读本机文件与模型目录、联网读模型卡／论文；**没有加载任何模型、没有 GPU 作业、没有下载权重**，也没有在本项目数据上测过任何候选的判别能力。排序是依据公开证据与本项目已有测量做的推断，不是实测结果。  
范围：为 w0（faster-whisper large-v3）与 x0（Qwen3-ASR 1.7B）在同一 Pyannote 窗口上的分歧区间挑选更优一路，并单独标出 w0 独有的幻觉文字的"音频接地裁判"；比较可用的声学／似然来源。不含选择器的融合策略、阈值、译文层收益。  
前置：[w0／x0 oracle 上限](2026-10-19-asr-pair-oracle.md)（误差构成）、[v5 §11–§12](2026-10-16-quality-exploration-v5.md#11-vad-召回)（avg_logprob 分不开真假幻觉）、[ASR 候选调研](2026-10-05-asr-model-landscape.md)、[日语 CTC 补充实测](2026-10-04-japanese-ctc-results.md)、[推理选型](../development/inference-selection.md)、[ADR-0003](../adr/0003-new-pyannote-baselines.md)。外部来源访问日期均为 2026-10-19。

## 1. 结论

**MMS CTC 是顺手的选择，没有证据表明它是最优。** 依据：

1. **选它的理由是时间对齐，不是文字判别。** [日语 CTC 补充实测](2026-10-04-japanese-ctc-results.md)按"半秒内成功率"挑出 MMS jpn；这份评估固定了上游文字，从未衡量过"哪一段文字更对"。项目自己也记过"错误识别文字也可能被强制放进错误位置"（[Whisper 框架架构](2026-10-04-whisper-framework-architecture.md)）：强制对齐给任何文本都能画出时间轴。
2. **没有 mms-1b-all `jpn` 的公开日语 CER。** 能找到的最近数字是 MMS 论文 Table A3：在 FLEURS 带标注数据上逐语言微调、**外加 20-gram 字符 LM**，日语 test CER 14.6%（普通话 14.9%、韩语 11.8%，多数语言在 2–8%）。这是另一个模型配置，不能当作 `mms-1b-all`＋`jpn` adapter 的成绩。本机其他日语 CTC 都有公开数字（见 §3），MMS 反而没有。
3. **声学 CTC 本来就看不出这批错误的大头。** 30 个人工分类的分歧区间里，同音／近音词 12，另有 8 个纯表记差异（分属同音词与人名两类，见 oracle §6）；这些在声学上等价，任何只听声音的模型都只能给出平局，或靠训练文本的正字法偏好"蒙"。分歧区间很短：40% 只差 1 个字，近七成不超过 2 个字。
4. **词表有缺口，许可偏紧。** 在 1253 个分歧区间里，MMS jpn 词表缺字的字符占 1.13%，3.8% 的区间含至少一个缺字（如 桐、凛、慰、蝦、夷、沌；§6）；现有对齐器把缺字当通配符，等于这些位置没有声学证据。权重许可 CC-BY-NC-4.0，自托管研究用途可以，但会限制将来的分发。
5. **MMS 的真实优点是成本。** 同一批 w0／x0 窗口，对齐阶段已经算出 emission（[`kototoki/align.py`](../../kototoki/align.py) 当前只留哈希，不留矩阵）；评分另一路文字只需再做一次 CTC 前向，不用新的神经网络前向。这是继续把它留作候选之一的理由，不是它判别更准的证据。

### 排序后的候选（按预期价值，未实测）

| 名次 | 方案 | 一句话理由 | 首要风险 |
| --- | --- | --- | --- |
| 1 | **两个 ASR 互相给对方的假设打分**（Whisper `align()` 教师强制；Qwen3-ASR 前向取 token 对数概率） | 唯一同时具备 ① 最强的日语声学（项目实测 CER 16–17%，已有数字）② 上下文语言模型，能裁同读异形（意志／意思、者／社）③ 已在盘上且依赖已在 `.venv`，不新增权重与许可 | 自偏好（各模型偏爱自己的输出）、Whisper 对自己幻觉打高分；需要把"对方得分 − 自己得分"作信号并用 oracle 标注标定 |
| 2 | **`nvidia/parakeet-tdt_ctc-0.6b-ja` 的 CTC 头** 作独立声学第二意见 | 公开日语 CER 在 CTC 候选里最好（JSUT 6.5%、CV8 7.2%、TEDxJP 9.1%，贪心无 LM），CC-BY-4.0，体量 0.6B；与 w0／x0 训练数据家族无关 | Windows 路径未证实：NeMo 官方文档未提 Windows；本机 transformers 5.20.1 含 `ParakeetForCTC`，但是否能直接装入该混合 `.nemo` 的 CTC 分支**未验证**；词表是 3072 个 SentencePiece 子词，不是字符 |
| 3 | **`japanese-wav2vec2-large-rs35kh`**（已在盘，Apache-2.0，字符级 CTC，词表含 2268 个汉字） | 零下载、零新依赖，与 MMS 同一接口（`Wav2Vec2ForCTC`），319M 参数；有公开 CER（JSUT 11.0%、CV 18.2%、TEDxJP 19.5%）；缺字更少（0.86% 字符、3.0% 区间） | 公开 CER 明显差于 Parakeet；在项目的时间对齐实测里 MMS 的半秒成功率更高（与判别无关，但说明它们不是同一把尺子） |
| 4 | MMS-1b-all jpn（现状） | 成本最低（emission 可复用），已被产品对齐流程验证过稳定性 | 无公开日语 CER、词表缺口、CC-BY-NC |
| 5 | **音素化归一器**（pyopenjtalk-plus G2P＋日语 HuBERT 音素 CTC） | 不当裁判，当"把同读异形压成平局"的工具；对表记差异免疫 | 人名读音 G2P 容易错（9/30 样本是人名），同音词仍是平局 |
| — | 不推荐：音频 LLM 裁判、Qwen3-ForcedAligner、TTS 似然（READ）、RNN-T 假设打分、`omniASR`、jonatasgrosman XLSR-53、slplab 假名模型 | 见 §3 | 见 §3 |

**建议的验证顺序**（§5）：先做零 GPU 的离线探针（用 v5 第 1 步已有的 `align.json` 中逐字 `token_probability` 与 1253 个区间的 oracle 标签对照），再决定是否值得为上面前三名占用 GPU；任何加载模型的验证都按 [AGENTS.md](../../AGENTS.md) 重任务先问。

## 2. 要判什么：误差构成与必须打败的基线

来自 [oracle 测算](2026-10-19-asr-pair-oracle.md)，另加我对其中间产物 `intervals.jsonl` 的计数（只读，CPU）：

| 事实 | 数值 |
| --- | --- |
| 分歧区间 | 1253 个；替换 895（71%）、w0 多出 229、x0 多出 129；"多出"类的中位长度 1 字 |
| oracle 拼接取 w0／x0 | 815／438（65%／35%）；替换区间 w0 占 639／895（71.4%） |
| w0 多出的区间 | oracle 删掉它（取 x0）125／229（54.6%）；x0 多出的区间，oracle 删掉它（取 w0）72／129（55.8%） |
| 一边完全没有文本的单元 | w0 独有的单元删掉的占 43／56（77%）；x0 独有的单元删掉的占 27／45（60%） |
| 误差类别（30 个人工标注） | 同音／近音词 12、人名 9、漏句 3、助词语尾 2、幻觉窗 2、其他 2；纯表记 8 |
| 共享错误 | 48% 的有参考单元两路都错，其中 352 个两路文本完全相同——任何裁判都救不了 |

必须打败的朴素基线（不用任何模型）：

- "总取 w0"：区间正确率 65%（替换区间 71%）。
- "只有一边有字就删掉它"：区间级只有约 55%，单边单元级 60–77%。所以**"删掉另一路没有的字"本身不是好规则**，裁判要真的判断那段字有没有声学支持，而不是对比有无。

另一个与裁判设计相关的事实：v5 §11 已测得 Whisper 的 `avg_logprob` 分不开真假幻觉（"by H."、"ありがとうございました" 与真台词重叠）。

## 3. 比较表

证据强度标记：**实测**＝本机文件／命令直接读取；**自报**＝模型卡或论文作者自己的数字；**第三方**＝他人复现；**推断**＝我根据结构做的判断，未测。CER 数字来自不同测试集与归一化，**不能跨行直接比大小**。

### 3.1 能力与偏差

| # | 候选 | 日语声学证据 | 汉字／读音处理 | 校准与已知偏差 | 能判的类别（插入／漏句／异读替换／同读替换／人名） |
| --- | --- | --- | --- | --- | --- |
| C1 | MMS-1b-all `jpn` CTC（现状，965M，FP32） | 无 `mms-1b-all` 日语 CER；FLEURS 微调＋字符 LM 版日语 test 14.6%（自报，另一配置） | 字符级，2268 类（2048 个汉字、158 假名）；缺字走通配符 | CTC 对数似然按字符累加，较长假设天然吃亏，跨假设比较需做共同上下文差分或长度校准（推断）；无校准数据 | 部分／部分／部分（取决于未测的声学质量）／**否（声学等价）**／部分（有缺字） |
| C2 | `reazon-research/japanese-wav2vec2-large-rs35kh`（319M） | 自报 CER：JSUT-basic5000 11.00%、Common Voice 18.23%、TEDxJP 19.53%、长篇 JSUT-BOOK 30.98%（35k 小时 ReazonSpeech v2） | 字符级，3000 项（2268 汉字、163 假名、518 个多字符项）；缺 蝦、沌 | 推荐前后各垫 0.5 s（模型卡）；训练目标是电视转写的正字法，对表记有隐式偏好（推断） | 同 C1，缺字更少 |
| C3 | `jonatasgrosman/wav2vec2-large-xlsr-53-japanese`（317M） | 作者自报 Common Voice CER 20.16%；Reazon 复测 JSUT 4.25%、CV 40.58%、TEDxJP 50.63%（第三方，口径与自报不同） | 字符级，2341 项；**缺 桜**（分歧区间里出现 96 次）、凛 | 域外鲁棒性差（第三方数字） | 不推荐 |
| C4 | `slplab/wav2vec2-xls-r-300m-japanese-hiragana`（本机） | 自报 CV CER 19.35% | 只有平假名，122 项；缺片假名，直接对原文字符的 OOV 达 54% | 需要先做读音转换 | 不推荐（时间对齐试验中曾需新增 pykakasi 依赖） |
| C5 | `nvidia/parakeet-tdt_ctc-0.6b-ja`（CTC 分支） | 自报 CER（CTC／TDT）：JSUT 6.5／6.4、CV8 7.2／7.1、TEDxJP-10k 9.1／9.0；第三方 FLEURS-ja 上 TDT 路径 9.41%（归一化 5.94%）对 large-v3 的 7.51%（4.49%） | 3072 个 SentencePiece 子词（含汉字），假设要先分词；多种切分需取最优或对数求和 | 8 倍下采样（推算帧长约 80 ms）；训练数据与 rs35kh 同源（电视），对动漫台词是域外 | 同 C1，预计声学质量高于 C1／C2 |
| C6 | `reazon-research/reazonspeech-nemo-v2`（RNN-T，619M）及 K2 v2 | 自报（kotoba 表）CV8 9.1、JSUT 7.4、ReazonSpeech 留出 11.2（large-v3 为 8.5／7.1／14.9）；K2 v2 在第三方 FLEURS 上 15.01% | 子词 | 给定假设的转导器似然需要前后向格点，比 CTC 贵，且无额外信息 | 不推荐（Parakeet CTC 同数据、更简单） |
| C7 | Whisper large-v3 教师强制（CT2 `Whisper.align`） | w0 本身：两部合计 CER 16.16%（**实测**，本项目） | BPE，Whisper 的隐式语言模型决定表记；能看上下文 | 偏爱自己的输出；对自己的幻觉（"ご視聴ありがとうございました"）同样给高分（推断，v5 §11 间接支持）；`align()` 的概率只在文本词表上归一化，不含 EOT／时间戳（C++ 源码摘要，未本机验证） | 评 x0 多出：可；评 w0 自己的插入：不独立／漏句：可／异读：可／**同读：部分**（靠上下文）／人名：部分 |
| C8 | Qwen3-ASR-1.7B 教师强制（HF 前向） | x0 本身：两部合计 CER 17.41%（**实测**） | 同上，汉字用法由其 LLM 决定 | 偏爱自己的输出；3 倍 wall-clock 在生成而非前向（推断） | **评 w0 独有插入：可且相对独立**／漏句：可／异读：可／同读：部分／人名：部分 |
| C9 | Qwen3-ForcedAligner-0.6B（本机，HF＋GGUF） | 官方只声称时间戳精度，无文字判别指标 | 文本是**输入**，每个时间戳槽位做 5000 类（×80 ms）分类 | 输出是"时间分布"，不是文本似然；任何文本都会得到时间（推断） | 否（没有文本概率） |
| C10 | 音素化：pyopenjtalk-plus G2P＋`prj-beatrice/japanese-hubert-base-phoneme-ctc(-v2)` | 模型卡无 PER；训练标签由 pyopenjtalk-plus 生成（自洽但不是人工真值） | 对表记免疫；同音词变平局 | G2P 错误直接变成假声学错误，人名最危险（推断，未测） | 部分／部分／**是**／**平局（正确行为）**／**弱** |
| C11 | 音频 LLM 裁判：Qwen2.5-Omni-7B、Qwen3-Omni-30B-A3B、Phi-4-multimodal | 模型卡无日语 ASR 数字（Qwen2.5-Omni 仅英中粤法德；Phi-4 有日语但数字只在图里） | 自由文本判断 | 提示敏感；零样本裁判在文本 LLM 研究里提升有限（见 §4.C11）；未校准 | 未知，不应假设 |
| C12 | TTS 似然（READ，CosyVoice2／3） | 论文只测英语与中英混合，**不含日语** | 文本经 TTS 前端，读音由其决定 | 偏向基线系统 0.95（论文自述）；不能区分替换／删除／插入 | 论文方法面向整句选择；日语未知 |
| C13 | Meta `omniASR_CTC_*`（Omnilingual ASR） | 找到的日语 CER 是 7B LLM 版 19.2%（日语训练 934.8 小时，聚合口径）；CTC 版日语数字未找到 | 见模型卡 | — | 不评（见 §3.2 的平台障碍） |

### 3.2 工程与许可

| # | 候选 | 额外成本（阶段×批设计） | 权重许可 | Windows＋CUDA 12.8＋Python 3.13 | 盘上现状 | 证据强度 |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | MMS jpn | emission 已在对齐阶段产生，可落盘复用（约 T×2268 个 float；30 s 窗约 1500 帧）；评分另一路文字只做 CTC 前向算子 | **CC-BY-NC-4.0**（模型卡 `license: cc-by-nc-4.0`） | 已在产品里运行（实测） | `mms-1b-all/`（3.86 GB）＋`adapter.jpn.safetensors` | 许可、词表：实测；日语质量：无 |
| C2 | rs35kh | 需要在判别阶段多加载一次 319M 并做一次前向（或纳入对齐阶段并存） | Apache-2.0 | 同 `Wav2Vec2ForCTC`，与 MMS 同一依赖；未在本机运行过，但接口相同 | `japanese-wav2vec2-large-rs35kh/` | 许可、词表：实测；CER：自报 |
| C3 | jonatasgrosman | 同 C2 | Apache-2.0 | 同上 | `wav2vec2-large-xlsr-53-japanese/`（含 `.partial` 残留） | 词表：实测；CER：自报／第三方不一致 |
| C4 | slplab 假名 | 同 C2＋读音转换 | 卡片未声明（[源核验](2026-10-04-japanese-ctc-source-verification.md)） | pykakasi 为额外依赖 | 在盘 | 词表：实测 |
| C5 | Parakeet-ja CTC | 一次 0.6B 前向（第三方 FLEURS 测得峰值显存 5.50 GiB、RTF 0.0004，L40S，TDT 路径）；分词与格点评分在 CPU／GPU 上都很小 | **CC-BY-4.0** | **未证实**：NeMo 3.0.0（2026-08-07）要求 Python ≥3.12，官方测试栈 Python 3.13／PyTorch 2.12／CUDA 12.6／13.2，文档未提 Windows；本机 transformers 5.20.1 有 `ParakeetForCTC`（含 `labels` 损失），可能绕开 NeMo，但需自己转换权重 | 不在盘（约 2.4 GB 级，需下载，先问） | 自报＋推断 |
| C6 | RNN-T | 格点前后向，更重 | Apache-2.0（nemo-v2） | 同 C5 且更依赖 NeMo | 不在盘 | — |
| C7 | Whisper 教师强制 | `model.model.align(encoder, sot_sequence, text_tokens, num_frames)`：[`kototoki/asr_whisper.py`](../../kototoki/asr_whisper.py) 已有 `model.encode`／`model.model.generate` 句柄，只多一个调用；每个有分歧的窗口 2 次解码器前向（可批）。无自回归生成，成本远小于重新转写（推断） | MIT（`faster-whisper-large-v3` 卡片） | 已在产品里运行；本机 ctranslate2 4.8.3、faster-whisper 1.2.1 暴露 `Whisper.align`（**实测**：签名、`WhisperAlignmentResult.text_token_probs`） | 在盘 | API 存在：实测；概率语义：外部源码摘要；判别力：无 |
| C8 | Qwen 教师强制 | 一次 1.7B 的预填充前向（音频 token＋提示＋假设 token），无生成；x0 转写阶段的 2.8 倍 wall-clock 主要在生成（推断，需测） | Apache-2.0 | 已在产品里运行（transformers 5.20.1，bf16，`AutoModelForMultimodalLM`） | `qwen3-asr-1.7b-hf/`（在盘，另有残留 `.partial`）；GGUF 另有 | 前向可行：推断；判别力：无 |
| C9 | Qwen3-ForcedAligner | 一次 0.6B 前向 | Apache-2.0 | 模型卡要求 transformers 主干版；本机 5.20.1 有 `qwen3_asr` 模型目录，是否含 ForcedAligner 类未核对 | 在盘（HF＋GGUF） | — |
| C10 | 音素化 | 94M HuBERT 前向＋CPU 上的 G2P；每个分歧区间做一次读音比对 | HuBERT 音素 CTC：Apache-2.0；pyopenjtalk-plus：MIT | pyopenjtalk-plus 0.4.1.post9（2026-08-11）有 cp313 Windows 轮子（PyPI 页面）；模型卡固定 transformers 4.52.4／torch 2.7.1 仅是训练记录 | 不在盘（约 0.4 GB） | 自报＋推断 |
| C11 | 音频 LLM | 7–30B 级：Qwen2.5-Omni-7B 的 safetensors 元数据为 11B 参数，BF16 按算术约 22 GB，超过 16 GB，需量化；Qwen3-Omni-30B-A3B（30B MoE，BF16 约 60 GB）需激进量化；Phi-4-multimodal（5.6B）BF16 约 11–12 GB 可放下 | Qwen2.5-/3-Omni：Apache-2.0；Phi-4：MIT | Phi-4 卡片要求 flash-attn 2.7.4 或改 eager；Omni 的 `qwen-omni-utils` 在非 Linux 可去掉 `decord` | 不在盘 | 推断 |
| C12 | CosyVoice | 0.5B 级 LLM，需 TTS 前端 | 仓库 Apache-2.0，权重许可需查模型页 | 安装说明以 Linux、Python 3.10 为准，未提 Windows | 不在盘 | 论文自报，无日语 |
| C13 | omniASR CTC | CTC 300M–7B | Apache-2.0 | 基于 fairseq2，模型卡称 Windows 需额外配置，不是项目首选 | 不在盘 | — |

## 4. 逐候选说明

### C1 MMS-1b-all `jpn`（现状）

- **来历与角色**：W0／X0 基线的强制对齐器（[ADR-0003](../adr/0003-new-pyannote-baselines.md)），产品配方 `mms-1b-all-jpn-ctc-v1`（[`kototoki/recipes.py`](../../kototoki/recipes.py) 的 `MMS`），FP32 CUDA、2268 类。选它的依据是 12 窗时间对齐实测（[日语 CTC 补充实测](2026-10-04-japanese-ctc-results.md)）。
- **日语识别质量**：模型卡只给 WER，且未分语言。MMS 论文 [Table A3](https://arxiv.org/abs/2305.13516)（我对 PDF 抽取文本核对）是 FLEURS-102 微调版加 CC 字符 LM，日语 dev 14.5%、test 14.6%；这不是 `mms-1b-all` 的 `jpn` adapter。相比之下 Whisper large-v3 在第三方 FLEURS-ja 上为 7.51%（归一化 4.49%）。结论：**无直接证据，间接证据偏弱**。
- **已有可零成本利用的信号**：产品 `align.json` 里每个字符有 `token_probability`（路径上该字符帧概率的均值，见 `_align_segment`），w0 与 x0 各自对自己的文字对齐过。它不是 CTC 总似然，且 CTC 的尖峰性质会让数值偏小，但足以做第 0 步探针（§5）。
- **与幻觉检测相关的外部证据偏弱**：[arXiv:2606.23060](https://arxiv.org/abs/2606.23060)（HALAS，Earnings-22，Whisper large-v3，3611 条预测）中，wav2vec 强制对齐置信度的 AUC 只有 60.8%，低于"每秒字符数"68.2% 与 GPT-2 困惑度 66.0%；该文未交代 wav2vec 模型与语言，且幻觉标注包含替换式幻觉，与本项目的"多出的字"不同口径。[Barański 等 2025](https://arxiv.org/abs/2501.11378)把 wav2vec2 强制对齐当作可选的二次确认。
- **缺字**：见 §6（实测）。

### C2 `japanese-wav2vec2-large-rs35kh`

本机已有，Apache-2.0，是 Reazon 对 `japanese-wav2vec2-large` 在 ReazonSpeech v2.0 上的 CTC 微调（[模型卡](https://huggingface.co/reazon-research/japanese-wav2vec2-large-rs35kh)）。项目历史上用它做过时间对齐候选（X0＋Reazon 无填充：共同可测的 P99 7.98→0.76 s，但半秒成功率不及 MMS）。它字符级、词表含 2268 个汉字，对本批分歧区间的缺字率比 MMS 低。公开 CER 是作者自报且测的是朗读／TED 类语音，对动漫台词是域外。把它放在第 3 名的理由是**验证成本几乎为零**：与 MMS 共用同一套加载、归一化与 CTC 损失代码。

### C3、C4 其他日语字符／假名 CTC

jonatasgrosman 的词表缺"桜"（分歧区间里 96 次），Reazon 对它的复测在 Common Voice 与 TEDxJP 上 CER 为 40–50%，远差于作者自报，说明域外鲁棒性差。slplab 假名模型只有平假名与少量符号，直接比较原文会把 54% 的字符判成 OOV，必须先做读音转换，等于引入 C10 的风险却没有 C10 的音素监督。二者不进入后续验证。

### C5 Parakeet-tdt_ctc-0.6b-ja

- **为什么值得看**：同一份 ReazonSpeech v2.0（35k 小时），[模型卡](https://huggingface.co/nvidia/parakeet-tdt_ctc-0.6b-ja)给出 CTC 分支贪心 CER 6.5／7.2／9.1，几乎等于 TDT 分支；第三方 L40S 上 TDT 路径 FLEURS-ja 5.94%（归一化）对 large-v3 的 4.49%，吞吐是 large-v3 的约 19 倍（[Classmethod](https://dev.classmethod.jp/articles/japanese-asr-l40s-fleurs-benchmark/)，该文未测 CTC 分支）。作为与 w0／x0 家族完全无关的第三个声学模型，它给的是"独立意见"。
- **障碍**：NeMo 官方文档与模型卡未给出 Windows 支持声明（[安装页](https://docs.nvidia.com/nemo/speech/latest/starthere/install.html)、[PyPI nemo-toolkit 3.0.0](https://pypi.org/project/nemo-toolkit/)），要求 Python ≥3.12、PyTorch ≥2.7。本机已有的 transformers 5.20.1 含 `ParakeetForCTC`／`ParakeetForTDT`，理论上可只搬编码器＋CTC 头的权重，不装 NeMo；这条路径**没有核实过**（需检查梅尔维度、词表大小＋blank、卷积核等配置是否与混合模型一致）。安装 NeMo 会改环境，按 AGENTS.md 需先问。
- **子词词表**：一个假设要先 SentencePiece 分词；不同切分的路径数不同，评分取最优切分即可，差异在逐区间比较时很小（推断）。

### C6 RNN-T（reazonspeech-nemo-v2、K2 v2）

对一个给定假设求转导器似然要对（时间×符号）格点做前后向，成本和实现都高于 CTC；训练数据与 C5 同源，没有额外信息。第三方 FLEURS-ja 上 K2 v2 为 15.01%，也不占优势。不推荐。

### C7 Whisper large-v3 教师强制（交叉打分的一半）

- **接口存在**：本机 ctranslate2 4.8.3 的 `Whisper.align(features, start_sequence, text_tokens, num_frames, *, median_filter_width=7)` 返回 `WhisperAlignmentResult`，含 `alignments` 与 `text_token_probs`（**实测**，读自已安装的包）；faster-whisper 1.2.1 的 `find_alignment` 就是这样用的（`transcribe.py`）。`generate()` 的 `return_scores` 只给生成序列的分数，不能用来给指定文本打分。
- **语义（外部源码摘要，未本机验证）**：CTranslate2 `whisper.cc` 中 `WhisperReplica::align` 把 `start_sequence`、`<|notimestamps|>`、文本 token、EOT 一起作为教师强制输入；`text_token_probs[t]` 是 token t 的概率，**softmax 只在文本词表上归一化**（不含 EOT、特殊符号与时间戳）。含义：不能用它得到"这句话该不该结束"的概率；但对比"同一窗口两种文字"时共同后缀相同，影响有限（推断）。
- **偏差**：Whisper 对自己的幻觉不是独立裁判——这类文字正是它自己最可能生成的。所以 C7 的合理用途是评 **x0 的输出**（x0 多出 129 个区间、替换区间里 x0 的写法），而不是评 w0 的多出字。
- **已知偏差类研究**：非语音输入上 Whisper large-v3 的幻觉有高度集中的短语库（Barański 等：在 301,317 次无语音推理中 40.3% 有幻觉，"thank you"占 24.76%；仅英语），列表过滤法对日语需要自建。[Careless Whisper (arXiv:2402.08021)](https://arxiv.org/abs/2402.08021) 是同方向的参考读物（本调研未复核其数字）。

### C8 Qwen3-ASR 教师强制（交叉打分的另一半）

- **做法（推断，未执行）**：用与产品相同的 `apply_transcription_request(language="Japanese")` 构造提示，把 `language Japanese<asr_text>` 后的假设 token 接上、末尾接结束符，一次前向取各位置对数概率（[模型卡](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf)；本机 `qwen3-asr-1.7b-hf`、transformers 5.20.1 已在产品中使用同一模型类）。
- **用途**：评 **w0 的插入**——x0 的解码器对 w0 独有文字给出的概率，是与 Whisper 相对独立的"有没有声学支持"的判断；漏句、异读替换同理。
- **风险**：x0 对 w0 的同读异形（桜／さくら）可能因其自身偏好而系统性给低分，需要标定；在 oracle 标注上看它是否偏袒自己的输出（自偏好率）是验证的核心指标之一。
- **成本直觉**：x0 阶段 wall-clock 是 w0 的 2.8 倍（oracle §1），主要来自自回归生成；教师强制只做预填充，预计显著便宜。需要实测。

### C9 Qwen3-ForcedAligner-0.6B

[模型卡](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf)与本机 README 说明：非自回归，把转写文本连同时间戳占位符一起输入，在每个占位符上做 5000 类分类（类别×80 ms），Apache-2.0。**输出只有时间，没有文本似然**，任何文本都会得到时间轴，因此不能作裁判。唯一可能的弱信号是时间分布的熵或时长异常，**没有任何证据**，不列入验证。

### C10 音素化归一器

`prj-beatrice/japanese-hubert-base-phoneme-ctc`（及 v2；v2 说明里还提到更新的 v3，未核对）是 Apache-2.0、94.4M 参数的日语音素 CTC，由 rinna 的 `japanese-hubert-base` 微调，训练标签是对 ReazonSpeech 文本用 pyopenjtalk-plus 生成的音素，无公开 PER。pyopenjtalk-plus（MIT）有 cp313 Windows 轮子。作用：把两路文字都转成音素串后做比较——读音相同则判平局（解决 8/30 的纯表记差异与同音词的"伪分歧"），读音不同才交给声学模型。**局限**：G2P 对人名与多音词会错（样本里 衛宮／間桐／慎二 等），错的读音会变成一个"声学上错误"的假设；同音词（12/30）声学上等价，仍是平局，需要 C7／C8 的上下文判断。因此它是**分流器**而非裁判。

### C11 音频 LLM 裁判

- **能装下的**：Phi-4-multimodal（MIT，5.6B，日语音频在支持列表中，建议音频 ≤40 s，要求 flash-attn 或 eager）。Qwen2.5-Omni-7B 的元数据是 11B 参数，BF16 约 22 GB，16 GB 卡必须量化；Qwen3-Omni-30B-A3B（Apache-2.0）更大。Qwen3.5-Omni 的开放程度各来源互相矛盾，未核实。
- **证据**：外部研究里，纯文本 LLM 做"从 N-best 中选最佳"零样本提升有限（Judge-Editor，[arXiv:2601.21347](https://arxiv.org/abs/2601.21347)，经搜索摘要，未复核）；HALAS 上零样本 GPT-4o mini 召回 62.6%、精确率 30.1%（[arXiv:2606.23060](https://arxiv.org/abs/2606.23060)，文本方式）。没有找到音频 LLM 在日语分歧区间上的评测。
- **结论**：成本高、不可校准、与"逐区间 1 字之差"的粒度不匹配，不进入验证。

### C12 TTS 似然（READ）

[arXiv:2606.04680](https://arxiv.org/abs/2606.04680)用预训练 CosyVoice2 在教师强制下计算"以假设文本为条件的语音 token 负对数似然"，逐词定位错误并做段级合并，报告相对 Whisper large-v3 首选假设的相对降错率 2.9–21.5%（英语与中英混合，**无日语**）；论文自述无法区分替换／删除／插入、需 0.95 的基线偏置以保持语言合理性，也没有与 LM 重打分对照。方法与本项目结构相同，但日语、Windows、许可（权重）均未验证，列为观察项。

### C13 Omnilingual ASR

[facebookresearch/omnilingual-asr](https://github.com/facebookresearch/omnilingual-asr) 的代码与模型为 Apache-2.0，有 300M–7B 的 CTC 与 LLM 两种解码，音频 <40 s；日语只找到 7B LLM 版聚合 CER 19.2%（日语训练 934.8 小时，来自仓库 CSV）。基于 fairseq2，Windows 需额外配置，且本项目已在 [ASR 候选调研](2026-10-05-asr-model-landscape.md)中把它排到观察。不进入验证。

## 5. 对前三名需要验证什么

所有验证共用同一把尺子：**1253 个分歧区间＋oracle 标签**（`.local/quality-exploration-v5/asr-pair-oracle/intervals.jsonl`）。评价指标：

- 区间级正确率（对 oracle_pick，平局不计），与"总取 w0"65% 对照；按类别（替换／w0 多出／x0 多出）分列。
- 把裁判结果套回晶格后的单元口径 CER（复用 [`experiments/quality_v5/asr_pair_oracle.py`](../../experiments/quality_v5/asr_pair_oracle.py)），对 w0 16.16%、oracle 拼接 11.90%。
- 插入删除的精确率／召回，对"一边有字就删"约 55%。
- 标定与泛化：用 II 标定阈值、III 上评估，再反过来；30 个人工分类样本用来看表记差异是否被正确判成平局。
- 自偏好率（C7／C8）：在 oracle 判定两路等价的区间里，模型偏爱自己输出的比例。
- 成本：每窗口 wall-clock 与显存峰值，和 x0 阶段（903 s）、w0 阶段（323 s）对比。

### 第 0 步（零 GPU，先做）

用 v5 第 1 步已有的 w0／x0 `align.json`（`alignment_records[].tokens[].token_probability`，两路各自对自己的文字对齐过）把分歧区间的 w 侧／x 侧字符映射到 MMS 置信度，看：① 对 oracle 判定为"该删"的 w0 多出字，置信度是否低于被保留的；② 替换区间里，置信度均值较高的一侧是否更常是 oracle 选中的一侧。这能在不跑任何模型的前提下回答"MMS 现有信号有没有判别力"，并给后面所有 CTC 方案一个下限。

### 第 1 名：交叉打分（需要 GPU，先问）

1. 在产品的 w0 句柄上调用 `align()`：确认对产品窗口的 `start_sequence`（与 `get_prompt` 一致）、日语 token 化后的 `text_token_probs` 可复现；比较"全窗文本替换区间"得到的对数概率差。
2. Qwen 前向：确认教师强制 x0 自己的输出得到的 token 对数概率与 `generate` 的得分一致（自洽检查）；再给 w0 的文字打分。
3. 每个区间用"两模型对称差"：Δ_W＝logP_W(A)−logP_W(B)，Δ_Q＝logP_Q(A)−logP_Q(B)，看一致时的准确率与不一致时的回退策略；检查是否被自偏好支配。
4. 幻觉：w0 多出字的 Δ_Q 与 oracle 删除标签的 ROC，对 55% 基线与 C1 第 0 步结果。

### 第 2 名：Parakeet-ja CTC 头（先问：下载与可能改环境）

1. 先在隔离环境（不动 `.venv`）验证 `.nemo` 的 CTC 分支能否装入 `ParakeetForCTC`，或 NeMo 能否在 Windows＋CUDA 12.8 上运行；两条都不通则放弃，不要为它改产品环境。
2. 同一把尺子下，与 MMS、rs35kh 在相同的共同上下文差分协议下对比。

### 第 3 名：rs35kh（与 MMS 一起验证，成本最低）

1. 对齐阶段落盘 emission（或判别阶段重算），用 `torch.nn.functional.ctc_loss` 在 FP32 上对"原窗口文本＋区间替换"逐个评分；用同一协议比较 MMS 与 rs35kh。
2. 处理缺字（MMS 3.8%、rs35kh 3.0% 的区间）与帧数不足（已见 2 帧容纳 4 个目标的失败，[分段比较](2026-10-05-fullfilm-segmentation-comparison.md)）：按"不可评分"处理，不要当作低分。
3. 在评分前用 C10 的读音比对把"读音相同"的区间标为平局，看是否提高其余区间的准确率。

## 6. 本地实测：分歧区间的字符覆盖

在 `intervals.jsonl` 的 1253 个区间上，取 w、x 两侧文字（NFKC、去空白与标点、小写）逐字符对词表（只读 `vocab.json`，CPU）：

| 词表 | 缺字占字符 | 含缺字的区间 | 主要缺字（出现次数） |
| --- | ---: | ---: | --- |
| MMS jpn（2268） | 1.13% | 3.8% | 爺 6、拳 4、珠 3、哀 3、凛 2、慰 1、堅 1 |
| rs35kh（3000） | 0.86% | 3.0% | 爺 6、孕 2、牌 2、贖 2 |
| jonatasgrosman（2341） | 4.26% | 11.3% | 桜 96、ゾ 9、殿 4 |
| slplab 假名（122） | 53.96% | 70.3% | 桜 96、片假名整体缺 |

作品相关的人名用字：MMS 缺 桐、凛；rs35kh 全有；jonatasgrosman 缺 桜、凛。oracle 样本里出现的"混沌"（沌）、"慰め"（慰）、"蝦夷や四郎"（蝦、夷）也是 MMS 缺字。缺字比例不大，但**恰好落在人名与生僻词上**，而这些就是分歧最集中的位置之一。

## 7. 限制

- **没有任何候选在本项目数据上测过判别力。** 表里"能判的类别"是依据结构的推断；名次是预期价值×验证成本的判断，第 0 步探针与 §5 的实验可能推翻它。
- **自报与第三方 CER 不可互比**：JSUT／Common Voice／TEDxJP 是朗读与演讲，FLEURS 是朗读，本项目是电影对白与动漫声线，带音乐与音效；MMS 无日语成绩，其余 CTC 的数字口径各异。唯一同源于本项目的数字是 w0 16.16%、x0 17.41%（两部合计，单元口径）。
- **外部页面经抓取摘要得到**，其中以下条目只是摘要、未逐字核对：CTranslate2 `whisper.cc` 的 `align` 语义、Parakeet 与 omniASR 模型卡细节、`japanese-hubert-base-phoneme-ctc` 系列、Phi-4／Qwen-Omni 卡片、Judge-Editor（2601.21347）、Calm-Whisper（2505.12969）、Careless Whisper（2402.08021）。arXiv 编号为 2026 年的论文（2606.04680、2606.23060 等）只通过检索与抓取读到，作者陈述的数字我没有复现；2606.23060 自身还有内部数字不一致（内部状态探针 F1 65.5% 与 62.1%）。
- **本机实测的只有**：模型目录与词表（§6）、ctranslate2／faster-whisper／transformers 的已安装接口（`Whisper.align`、`WhisperAlignmentResult.text_token_probs`、`ParakeetForCTC` 存在）、MMS 论文 PDF 的 Table A3 文本、`intervals.jsonl` 的计数。没有运行 `align()`，也没有把任何模型装入内存。
- **oracle 标签本身来自 SRT 显示字幕**，含字幕组的表记惯例与笔误；"该选哪一路"的标签在表记差异上不是声学真值。
- **许可只记录了权重身份的页面声明**，未做法律审查；MMS 的 CC-BY-NC-4.0 是否构成问题取决于本项目将来是否分发。
- 本文不含选择器的融合策略设计，也不评估译文层收益（见 [oracle §7](2026-10-19-asr-pair-oracle.md#7-限制) 对换算的警告）。

## 8. 待用户裁定

以下只陈述事实，不含采纳建议。

1. 是否先做 §5 的第 0 步（零 GPU，用现有 `align.json` 检验 MMS 的 `token_probability` 的判别力）。
2. 是否批准一次有界的 GPU 验证（交叉打分，第 1 名）；它占 GPU、加载 Whisper 与 Qwen，按 [AGENTS.md](../../AGENTS.md) 属于重任务。
3. 是否允许为 Parakeet-ja 做隔离环境试装与下载（约数 GB，可能改环境）；不批准时，该候选停在"Windows 路径未证实"。
