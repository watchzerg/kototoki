# Japanese CTC Forced Alignment 外部会话参考

状态：外部原文历史参考；后续核验与实测另列，原文不构成已采纳决策  
最后更新：2026-10-04（导入日期；原文撰写日期未知）  
范围：日语 CTC 强制对齐候选、测试指标与实验设计，供后续研究参考。

## 来源与使用边界

后续工作见[官方来源核验](2026-10-04-japanese-ctc-source-verification.md)与
[本机补充实测](2026-10-04-japanese-ctc-results.md)。以下“本次仅保存”描述导入时的动作，
下方原文保持不变；实际 tokenizer／blank／adapter 契约以核验和实测报告为准。

- 来源：用户从其他 session 提供的《Japanese CTC Forced Alignment 候选模型评估与测试计划》，本次附件 `Pasted text.txt`；接收日期为 2026-10-04。下方完整保留原文。
- 原文未附可核查的外部来源链接、访问日期、模型 revision 或实测记录。本次仅保存文档，未联网核验模型信息，也未下载模型或运行实验。
- 关于模型规模、许可、训练数据、维护情况、ASR 泛化与 WhisperX 兼容性的陈述均为原文主张；默认候选排序、质量预期和测试集合属于建议或假设，不构成本项目验证结果。
- 原文中的“我们的系统只需要 Japanese”等表述保留其原会话语境，不据此新增项目范围约束；“必须保留测试”等措辞也不自动转化为当前执行任务。
- 当前候选与已测配置以[当前 STT 候选集与组件边界](../architecture/stt-candidate-pipelines.md)为准；后续评估遵循[推理选型原则](../development/inference-selection.md)、[评估素材与参考优先级](../testing/fatestay-reference.md)及[验证边界](../testing/validation.md)。本参考不覆盖现有冻结规则或既有实验结论。

## 原文

---

# Japanese CTC Forced Alignment 候选模型评估与测试计划

## 背景

当前目标不是比较一般意义上的 Japanese ASR accuracy，而是为字幕系统选择一个 **Japanese CTC backend**，用于：

```text
ASR transcript
  ↓
text normalization
  ↓
CTC emissions
  ↓
forced alignment
  ↓
character / word / segment timestamps
```

主要使用场景是：

- 日语电影 / 动画 / 长视频
- Whisper / WhisperX / Qwen 等模型已经先产生 transcript
- CTC 模型只负责 acoustic alignment，不负责最终 transcription
- 最终希望获得稳定、精确的字符级或词级时间戳
- 长音频和真实影视语音的鲁棒性比 clean ASR benchmark 更重要

因此不能简单按照 CER/WER 排名选模型。

---

# 候选 1：Reazon Research

模型：

```text
reazon-research/japanese-wav2vec2-large-rs35kh
```

## 定位

目前最值得作为 **新默认候选** 测试的 Japanese CTC 模型。

## 优点

- 来自 `reazon-research` verified organization，不是个人账号。
- Japanese-specific acoustic model。
- backbone 本身就在大规模日语语音上训练，而不是 multilingual backbone 再少量 fine-tune。
- CTC checkpoint 可以直接获得 emissions。
- 约 319M 参数，规模合理。
- Apache-2.0。
- 对真实日语、长语音、TED 类数据的公开 ASR 泛化结果明显强于旧 XLSR-53 Japanese checkpoint。
- 对新建 Japanese-only pipeline 来说，技术路线比老 XLSR-53 更现代。

## 主要担忧

### 1. ASR CER 好，不等于 forced alignment 好

这是最大的未知点。

CTC forced alignment 更关心：

- 正确 transcript 给定之后，emission 是否有清晰峰值
- blank / character posterior 是否稳定
- 边界是否准确
- 长 segment 中是否发生 alignment drift
- transcript 与 acoustic pronunciation 有轻微差异时是否还能稳定对齐

所以不能因为 CER 更低就直接确定它一定更适合作 alignment。

### 2. Vocabulary / normalization 行为需要检查

必须确认：

- 汉字是否直接存在于 tokenizer vocab
- kana / kanji / punctuation 的处理规则
- 是否有 `<unk>`
- 空格如何表示
- 长音符 `ー`
- 促音 `っ`
- 拗音
- 日文标点
- 英文字母
- 数字
- 外来语
- 人名

如果 transcript 中大量字符落到 `<unk>`，即使 ASR 很好，也可能不适合我们的 forced alignment。

### 3. 影视语音与训练数据 domain gap

需要特别测试：

- 背景音乐
- 环境噪声
- 多人同时讲话
- 喊叫
- 耳语
- 情绪化台词
- 动画角色声线
- 较快对白

---

# 候选 2：WhisperX 传统 baseline

模型：

```text
jonatasgrosman/wav2vec2-large-xlsr-53-japanese
```

## 定位

不再建议作为新项目默认，但应当作为：

```text
WhisperX-compatible baseline
```

必须保留测试。

## 优点

- WhisperX 长期用于 Japanese alignment。
- 已经有大量实际 forced-alignment 使用经验。
- wav2vec2 CTC 接口成熟。
- 约 317M 参数。
- Apache-2.0。
- 对 WhisperX alignment 的数据结构、token mapping、实现方式可以直接参考。

## 主要担忧

### 1. 个人维护 checkpoint

owner 是个人账号：

```text
jonatasgrosman
```

不是 Meta / Hugging Face / Reazon 官方组织。

长期依赖稳定性不如 organization-maintained model。

### 2. 技术代际较旧

基于：

```text
facebook/wav2vec2-large-xlsr-53
```

属于较老的 XLSR-53 路线。

### 3. 泛化能力一般

在更真实的数据集、TED、long-form 场景中，公开测试明显弱于 Reazon Japanese model。

### 4. 但 alignment 可能反而很好

这一点不能忽略。

虽然 ASR CER 较差，但它可能具有：

- 更适合 character alignment 的 vocab
- 更明确的 token posterior
- WhisperX 多年调优留下的 implicit compatibility

因此它非常适合作为 baseline。

如果 Reazon 的 ASR 明显更好，但 forced alignment 最终没有超过 Jonatas，也完全合理。

---

# 候选 3：Meta MMS

模型：

```text
facebook/mms-1b-all
```

Japanese adapter：

```text
jpn
```

## 定位

官方大型 multilingual CTC 对照组。

不建议默认，但值得 benchmark。

## 优点

- Meta 官方。
- Wav2Vec2 / CTC architecture。
- 支持 Japanese adapter。
- 多语言 acoustic representation 很强。
- 维护来源可信。
- 可用于测试“大模型 multilingual CTC 是否比 Japanese-specific 模型更稳定”。

## 主要担忧

### 1. 模型过大

约：

```text
1B parameters
```

相对于 300M 级模型：

- 显存更高
- 推理更慢
- throughput 更低
- 多模式 pipeline 切换成本更大

对于“只取 CTC emissions”可能不划算。

### 2. Multilingual-first，不是 Japanese-first

我们的系统只需要 Japanese。

Reazon 的优势是整个 backbone 就是为 Japanese acoustic representation 训练的。

MMS 的 multilingual 能力在这里可能属于不必要成本。

### 3. License

MMS 需要特别重新确认当前模型卡的 license 和商业使用限制。

如果仍为 NC 类许可，则长期产品依赖不理想。

### 4. Japanese vocab 适配必须详细检查

尤其需要确认：

- adapter tokenizer
- kanji 覆盖
- kana normalization
- `<unk>` 情况
- punctuation handling

---

# 候选 4：Hiragana / phonetic CTC

这一类不是单纯替换模型，而是另一条 architecture direction。

可测试候选例如：

```text
slplab/wav2vec2-xls-r-300m-japanese-hiragana
```

以及其他 Reazon-based hiragana CTC checkpoint。

## 核心思路

不直接拿原始 orthographic text 做 alignment：

```text
今日は東京へ行きます
```

而是先转换成 pronunciation representation：

```text
きょうはとうきょうへいきます
```

然后 CTC 对齐 pronunciation。

最后再映射回原始 transcript。

Pipeline：

```text
original transcript
  ↓
Japanese text normalization
  ↓
kanji → kana reading
  ↓
phonetic / hiragana transcript
  ↓
CTC forced alignment
  ↓
kana timestamps
  ↓
map timestamps back to original text
```

## 理论优势

Forced alignment 本质上是：

```text
speech ↔ pronunciation
```

而不是：

```text
speech ↔ orthography
```

日语尤其存在：

```text
今日
きょう

東京
とうきょう

一日
いちにち / ついたち
```

acoustic signal 实际对应 pronunciation，而不是汉字。

因此 kana/phoneme CTC 从理论上比直接 kanji alignment 更自然。

## 潜在优势

可能改善：

- 生僻汉字
- 人名
- 专有名词
- 多种 orthography
- kanji/kana 混写
- ASR 输出与 acoustic pronunciation 的 mismatch

也可能让 CTC search space 更简单。

## 最大担忧

### 1. Reading conversion 本身变成新的 failure source

例如：

```text
今日
```

可能是：

```text
きょう
こんにち
```

必须根据上下文正确确定 reading。

如果 reading normalization 错误，则 alignment 必然失败。

### 2. 原始字符映射复杂

例如：

```text
東京
```

变成：

```text
とうきょう
```

不是 1:1 character mapping。

需要保存：

```text
original character range
↔
normalized kana range
```

最终才能把 kana timestamps 映射回原始字幕。

### 3. 字幕中存在大量非标准表达

需要处理：

- English
- Arabic numbers
- abbreviation
- slang
- emoji
- symbols
- names
- katakana
- furigana-like expressions

### 4. 复杂度明显增加

Orthographic CTC pipeline：

```text
text → CTC
```

Phonetic pipeline：

```text
text
→ normalization
→ morphological / reading conversion
→ CTC
→ reverse mapping
```

所以除非 alignment quality 有明显收益，否则不一定值得第一版引入。

---

# 建议最终测试的候选集合

第一阶段不要测试十几个模型。

建议控制在：

```text
A. reazon-research/japanese-wav2vec2-large-rs35kh
   新默认候选

B. jonatasgrosman/wav2vec2-large-xlsr-53-japanese
   WhisperX compatibility baseline

C. facebook/mms-1b-all + jpn
   Meta official multilingual baseline

D. 一个可靠的 Japanese hiragana / phonetic CTC
   experimental phonetic alignment
```

其中 A/B 是最高优先级。

C 用来回答：

> 官方 1B multilingual CTC 是否值得额外资源成本？

D 用来回答：

> pronunciation-based alignment 是否值得增加 normalization complexity？

---

# 测试时不要主要比较 CER

我们的最终任务不是重新识别 transcript。

输入 transcript 已经由 Whisper/Qwen 等生成。

因此 ASR CER 只是辅助指标。

真正需要测试的是以下指标。

---

## 1. Alignment success rate

```text
成功对齐的 segment 数
----------------------
总 segment 数
```

需要定义严格成功条件，例如：

- 所有必要字符都有时间
- monotonic
- 时间范围合法
- 不跨越 search window
- 不出现异常长 token duration

---

## 2. Unaligned character ratio

```text
无法对齐字符数
--------------
总可对齐字符数
```

同时分类原因：

```text
OOV
<unk>
CTC search failed
window too short
acoustic mismatch
normalization failure
```

---

## 3. Boundary accuracy

如果有人工标注，测试：

```text
start MAE
end MAE
median
P90
P95
max
```

尤其关注：

```text
subtitle onset
subtitle offset
```

因为最终字幕体验对 boundary error 很敏感。

---

## 4. Catastrophic failure rate

比平均误差更重要。

定义类似：

```text
boundary error > 1s
boundary error > 2s
alignment shifted to another sentence
entire segment collapsed
```

影视字幕最怕这种 failure。

---

## 5. Long-window stability

分别测试：

```text
5s
10s
20s
30s
60s
```

看窗口变长后：

- alignment 是否 drift
- decoding complexity 是否急剧上涨
- posterior 是否变得模糊

---

## 6. Search-window tolerance

给正确 transcript，但人为扩大搜索窗口：

```text
±0.5s
±1s
±2s
±5s
```

测试模型是否还能定位到正确 utterance。

这直接关系到 W0 / W1 / X0 上游给出的 coarse timestamps 有多精确。

---

## 7. Transcript mismatch robustness

模拟真实 ASR 错误：

### 删除字符

```text
今日は東京に行きます
↓
今日は東京行きます
```

### 多字符

```text
今日は東京に行きますね
```

### 同音不同字

```text
会う / 合う
```

### kanji / kana variation

```text
出来る
できる
```

### 数字

```text
三人
3人
```

检查 CTC 是否：

- 完全失败
- 局部失败
- 仍能对齐其他字符

---

# 必须单独检查 tokenizer / vocab

对每个模型打印：

```text
vocab size
blank token
unk token
word delimiter
特殊 token
```

并测试这些字符：

```text
漢字
ひらがな
カタカナ
ー
っ
ゃゅょ
々
数字
ASCII
全角字符
Japanese punctuation
English words
```

重点统计：

```text
OOV rate
<unk> rate
```

这对于 forced alignment 的意义可能比 ASR CER 更大。

---

# 测试数据必须覆盖真实影视场景

不要只拿 JSUT 之类 clean corpus。

建议测试集至少覆盖：

## Clean speech

作为 sanity baseline。

## Anime

- 高音角色
- 夸张语调
- 快速对白
- 背景音乐

## Live-action movie / drama

- 自然口语
- 含混发音
- 环境声音

## Male / female

分别覆盖。

## Quiet speech / whisper

## Shouting

## Fast conversation

## Music underneath speech

## Multiple speakers

## Foreign names / English loanwords

## Long utterance

建议直接从最终项目里的真实电影样本抽测试集。

---

# Performance 指标

同时记录：

```text
model load time
VRAM usage
peak VRAM
RTF (real-time factor)
GPU utilization
CPU utilization
batchability
```

例如：

```text
30 min audio alignment:
runtime = ?
RTF = runtime / 1800
```

因为 CTC 将是共享 backend：

```text
W0+CTC
W1
X0
```

如果一个模型慢 3 倍，但 alignment quality 只提升极少，则不值得默认使用。

---

# 最终决策标准

目前假设：

```text
Reazon
```

是最可能的新默认。

但只有在真实 alignment benchmark 后才能确认。

建议决策顺序：

```text
1. catastrophic failure rate
2. alignment success rate
3. boundary accuracy
4. OOV / normalization complexity
5. long-form stability
6. performance / VRAM
7. maintenance / license
8. ASR CER
```

CER 放得很靠后。

---

# 当前预期

## Reazon

预期：

```text
最可能成为默认 Japanese orthographic CTC
```

但需验证 emissions 是否适合 forced alignment。

## Jonatas

预期：

```text
可能不是最好的 acoustic model，
但有机会仍然是非常强的 alignment baseline。
```

绝对不能因为模型老就跳过。

## MMS

预期：

```text
质量可能不错，但资源成本和 multilingual overhead 可能不值得。
```

除非 alignment 明显优于 300M 模型，否则不建议默认。

## Hiragana CTC

预期：

```text
理论上最符合 forced alignment 本质，
但工程复杂度最高。
```

如果它在：

```text
人名
生僻词
kanji
orthography variation
```

等场景明显降低 failure rate，则值得考虑作为长期方向。

否则第一版保持 orthographic CTC 更简单。

---

# 最终希望测试回答的问题

测试结束后，请明确回答：

1. Reazon 是否能够取代 Jonatas，作为默认 Japanese CTC？
2. Jonatas 是否因为 WhisperX 长期使用而表现出特殊的 forced-alignment 优势？
3. MMS-1B 的 alignment improvement 是否值得它的模型规模和显存开销？
4. Hiragana / phonetic CTC 是否显著降低 catastrophic alignment failure？
5. 哪个模型的 tokenizer 最容易与 Whisper / Qwen Japanese transcript 对接？
6. 哪个模型对真实电影、动画长音频最稳定？
7. 哪个模型应该作为生产默认？
8. 哪些模型应该仅保留为 benchmark / fallback？
