# ADR-0030：ASR 整窗守卫（复读、语速、已知幻听句，`guard-v3`）

状态：已接受。2026-11-18 按主题合并（用户授权）：并入 ADR-0023，原文见 git 历史（提交 807de3e 及之前）。
范围：产品包 `kototoki/` 的 w0 路径（含 `cross` 的 w0 一路），只做解码后的后处理（纯逻辑 `kototoki/guard.py`，接入 `kototoki/workers/asr.py`）。不改解码参数、VAD、MMS 对齐、cue 回填，也不改 x0 路径与研究侧 demo。[ADR-0003](0003-new-pyannote-baselines.md) 的 W0 基线身份（解码器、VAD、对齐）与 `cross` 规则不变。

## 决定

### 守卫顺序

1. 对每个未失败的 w0 窗口依次过三条规则，都在规范化文本（`judge.normalize`：NFKC、去标点与空白）上判定；后两条看复读处理后（可能已折叠）的文字，第一个置空的规则生效。
2. 位置：`asr` 阶段内、解码返回之后、写转写文档之前；只做后处理，不重解码、不温度回退。`cross` 引擎照常拿处理后的 w0 文字打分；被置空的窗口沿用 `w0_failed_window: stays failed`。
3. 置空沿用 `failed_windows`：原因记为 `guard:<规则名>`，原文字移入 `failed_windows[].text`（由 `align` 按既有规则分配时间），不进对齐、cue 与翻译。

### 复读 repeat-strict

1. 相邻重复：周期 ≥2 字的单元连续重复 ≥10 份（同一字符连写按周期 2 计）；或非相邻复现：长度 ≥3 字的子串不重叠出现 ≥10 次；且重复部分覆盖该窗规范化文字的 ≥50%。
2. 动作折叠：命中的相邻重复区段只保留第一个单元；折叠后仍命中的窗口置空。
3. 定义来源 `archive/2026-11-18-pre-research-restructure:experiments/asr_robustness_v15/repeat.py`；产品用自己的纯函数，不导入 `experiments.*`。

### 语速 speech-rate

规范化字数 ÷ 窗口时长（`end − start` 秒）**大于 20 字/秒** 即置空。正常对白最快约 13 字/秒；这条规则与模型无关，同时保证 MMS（每 20 ms 一帧）放得下全部字符，对齐不会再出现 `targets length is too long for CTC`。

### 已知幻听句 hallucination-phrase

整窗规范化文字**等于**名单中的一句即置空。名单只有三句：`ご視聴ありがとうございました`、`チャンネル登録よろしくお願いします`、`byH`（即 `by H.`）。这几句是 Whisper large-v3 在没有可辨语音时编出的视频结尾字幕；名单随模型走、不随内容走，因此写在 W0 配方里，换 ASR 模型时要重新整理。作为长句一部分出现时不拦；`ありがとうございました` 单独成窗也不进名单（可能是真话，极短窗口里的幻听由语速规则拦住）。

### 记录与配方

1. trace 的 `guard` 里为被改动的窗口记一条记录，只含规则名与计数，不含文字：复读记规则名、周期、份数、删去的字符数；语速 `{rule, action, chars, duration_s}`；幻听句 `{rule, action, phrase_index}`。
2. `recipes.W0["guard"]` 含 `repeat`、`speech_rate`、`hallucination_phrases` 三个子块及 `normalize`、`order`；hash 级联到 `CROSS` 与全部下游身份，守卫变化即换配方 id、既有工作目录整批重算，不做迁移。

### 不做的事

- 不以压缩比或 `avg_logprob` 单独置空（有歌词误报）；不用更宽的复读阈值（6 份有 13 个误报，8 份出现第一个正常窗）。
- 不用 Whisper 的 `no_speech_prob`／`avg_logprob` 规则：它拦不住目标幻听，主要拦下真实叫声，只看静音概率还会误杀歌词。
- 不抬高 VAD 最短语音时长；不拦长窗口里整窗只有一句「おやすみなさい」「お疲れ様でした」之类的情况（用户裁定不管）。

## 身份

- 产品 W0 配方 `w0-faster-whisper-large-v3-guard-v3`：`recipe_hash` W0 `6a47318c7732534270f64d14bb5da9830a79fdcae9f6d84e01a309532d62403b`，CROSS `bd5bc55527a539beab598e98f687f1bcbbcc6c23b3ba3a823fd3e9dfb46338e3`。
- 历史：`w0-faster-whisper-large-v3-guard-v2`（仅复读守卫），`recipe_hash` W0 `b73198fac0a1b8eb1ccc24d7d33479e3a42059989e4ef2a6820367efcb603e76`，CROSS `d29b138b492290b3c1fbf788c029472c97ecc1fb58aa7cdc4bb415c1cbec717f`；2026-11-12 全流程验收记录绑定在它上。

## 依据

- 复读（v15 [票据](../../research/2026-11-asr-robustness-v14-v15/README.md)）：6 条候选规则里只有 `repeat-strict` 在 101 个 w0 样本／5618 窗上对判为正常语音的窗口零标记（17 窗＝16 幻觉＋1 无法判断）；份数阈值 ≥9 起零误报。HF III 第 51 窗（94 字、参考 11 字）折叠净 −42 编辑（官方 CER 13.7673% → 13.3973%），优于置空 −40 与 `no_repeat_ngram_size` 补解 −37；HF II 零命中、CER 逐项不变。判据是安全网（零误报＋拦住已知复读窗），不是平均 CER。2026-11-11 产品实现验收：HF III 只有第 51 窗被折叠（94 → 31 字），CER 13.3973% 逐项复现，`just smoke` 通过。
- 语速与幻听句（batch-run-fixes 票据 09，首次大批量运行的 228 个文件加 HF II／III）：对齐失败的 54 个窗口只有 17–253 ms 长，文字只有 6 种 Whisper 结尾套话，因 `cues._fallback` 回填时间而全部进了 `ja.srt`；语速超 20 字/秒的窗口共 95 个，其余 41 个也是同类套话或物理上说不完的短句。
- `no_speech_prob`（230 个文件、60392 个非空窗口）：OpenAI 规则（> 0.6 且 `avg_logprob` < −1）在语速规则之外只多拦 7 个套话窗口，却拦下 221 个「ああああ」类叫声；Whisper 对编出的套话很有把握（`avg_logprob` 中位约 −0.56）。整窗套话匹配在语速规则之外多拦 206 个窗口（111 个文件）。
- 离线重放新规则：样本片只有 2 个窗口被置空，都是幻听（HF II 一个 51 ms 的 `by H.`，无参考 cue；HF III 一个 84 ms 的 `ありがとうございました。`，参考是「先…輩…」）。

## 未验证与已知限制

- 复读召回有限：v15 样本里 78 个幻觉窗只拦 16 个；证据只来自两部电影、国会与若干 demo 样本上的 w0 输出，剧集与其他作品未扫。
- 两部样本片没有用 GPU 重跑整条链（语速与幻听句规则）计算官方 CER；按离线重放只会减少插入错误。
- 名单只来自成人向内容和两部动画电影，其他题材中 Whisper 是否另有固定幻听句未扫。
- 长窗口整窗只转出一句的漏转现象不在本 ADR 范围。

## 沿革

- 2026-11-10 ADR-0023 采纳（用户裁定 v15 §8 第 7 项 A）、11-11 实现：复读守卫 `repeat-strict`＋折叠，产品 W0 配方 `guard-v2`。
- 2026-11-17／18 ADR-0030：加语速与已知幻听句两条规则，配方 `guard-v3`；撤销"不管低压缩比的插入套话"。
- 2026-11-18：按主题合并，复读规则并入本页。
