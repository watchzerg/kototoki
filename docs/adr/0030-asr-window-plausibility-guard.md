# ADR-0030：ASR 整窗守卫加语速与已知幻听句两条规则（`guard-v3`）

状态：已接受（2026-11-17／18，用户决定，依据 [batch-run-fixes 09](../../.scratch/batch-run-fixes/issues/09-short-window-asr-overflow.md)），已实现（2026-11-18）：产品 W0 配方 id 为 `w0-faster-whisper-large-v3-guard-v3`，`recipe_hash` W0 为 `6a47318c7732534270f64d14bb5da9830a79fdcae9f6d84e01a309532d62403b`、CROSS 为 `bd5bc55527a539beab598e98f687f1bcbbcc6c23b3ba3a823fd3e9dfb46338e3`。

本 ADR 替代 [ADR-0023](0023-asr-repeat-guard.md) 的两处内容：第 4 点的配方 id 与 hash；第 5 点"不管低压缩比的插入套话"。ADR-0023 的复读规则与折叠动作不变。[ADR-0003](0003-new-pyannote-baselines.md) 的 W0 基线身份不变，[ADR-0012](0012-cross-asr-judge.md) 的 `cross` 规则不变。

范围：产品包 `kototoki/` 的 w0 路径（含 `cross` 的 w0 一路），只做解码后的后处理。不改解码参数、VAD、MMS 对齐、cue 回填，也不改 x0 路径。

## 决定

1. **同一个守卫，三条规则，按顺序。** 对每个未失败的 w0 窗口：
   - 先跑复读 `repeat-strict`（ADR-0023 第 1、2 点不变）；
   - 再在复读处理后的文字上（可能已折叠）看语速和已知幻听句；
   - 第一个判"置空"的规则生效。

   置空沿用 `failed_windows`：原因记为 `guard:<规则名>`，段文字移入 `failed_windows[].text`，不进对齐、cue 与翻译。
2. **语速 `speech-rate`。** 规范化字数（`judge.normalize`：NFKC、去标点与空白）÷ 窗口时长（`end − start` 秒）**大于 20 字/秒** 即置空。
   - 依据：正常对白最快约 13 字/秒。
   - 这条规则与模型无关；同时保证 MMS（每 20 ms 一帧）放得下全部字符，对齐不会再出现 `targets length is too long for CTC`。
3. **已知幻听句 `hallucination-phrase`。** 整窗规范化文字**等于**名单中的一句即置空。名单只有三句：`ご視聴ありがとうございました`、`チャンネル登録よろしくお願いします`、`byH`（即 `by H.`）。
   - 这几句是 Whisper large-v3 在没有可辨语音时编出的视频结尾字幕。名单随模型走、不随内容走，因此写在 W0 配方里；换 ASR 模型时要重新整理。
   - 这几句作为长句的一部分出现时不拦。`ありがとうございました` 单独成窗也不进名单，因为它可能是真话；它在极短窗口里的幻听由第 2 点拦住。
4. **trace 记录。** 被守卫改动的窗口在 trace 的 `guard` 里记一条记录，只含规则名与计数，不含文字：
   - 复读：同 ADR-0023；
   - 语速：`{rule, action, chars, duration_s}`；
   - 幻听句：`{rule, action, phrase_index}`。
5. **配方。** `recipes.W0["guard"]` 改为 `repeat`、`speech_rate`、`hallucination_phrases` 三个子块，加上 `normalize`、`order`，并换新 id；hash 级联到 `CROSS` 与全部下游身份。既有工作目录整批重算，不做迁移。
6. **不做的事。**
   - 不用 Whisper 的 `no_speech_prob`／`avg_logprob` 规则：测量显示它拦不住目标幻听，主要拦下的是真实叫声；只看静音概率还会误杀歌词。
   - 不抬高 VAD 最短语音时长。
   - 不拦长窗口里整窗只有一句「おやすみなさい」「お疲れ様でした」之类的情况（用户裁定不管）。

## 依据

票据 09 的复查与测量，数据为首次大批量运行的 228 个文件，以及有参考字幕的 HF II、HF III。测量包 `experiments/asr_nospeech/`，产物在 `.local/asr-nospeech/`，不进 Git。

- 对齐失败的 54 个窗口只有 17–253 ms 长，文字只有 6 种 Whisper 结尾套话。由于 `cues._fallback` 回填时间，这些文字全部进了 `ja.srt`。
- 语速超过 20 字/秒的窗口共 95 个（含上面 54 个），其余 41 个也是同类套话，或物理上说不完的短句。
- `no_speech_prob`：已核对单步解码与完整解码的值相同、完整解码与产品 trace 逐 token 相同，然后在 230 个文件、60392 个非空窗口上测量。
  - OpenAI 规则（> 0.6 且 `avg_logprob` < −1）在语速规则之外只多拦 7 个套话窗口，却同时拦下 221 个「ああああ」类叫声。
  - 原因是 Whisper 对编出的套话很有把握：`avg_logprob` 中位约 −0.56；窗口越长，静音概率越低。
- 整窗套话匹配：在语速规则之外多拦 206 个窗口（111 个文件）。两部样本片只命中 1 个窗口，就是语速规则已经拦下的那个 0.08 s 幻听。
- 实现后在现有识别结果上离线重放新规则，结果与测量一致：
  - 本批语速 95 个、幻听句 206 个；
  - 样本片只有 2 个窗口被置空，都是幻听：HF II 一个 51 ms 的 `by H.`，没有参考 cue；HF III 一个 84 ms 的 `ありがとうございました。`，参考是「先…輩…」。

## 未验证

- 两部样本片没有用 GPU 重跑整条链、计算官方 CER。按离线重放，变化只有上面 2 个幻听窗口被置空，CER 只会减少插入错误。
- 名单只来自这一批成人向内容和两部动画电影。其他题材中 Whisper 是否另有固定幻听句，未扫。
- 长窗口整窗只转出一句的漏转现象，不在本 ADR 范围。
