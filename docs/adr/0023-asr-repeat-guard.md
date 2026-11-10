# ADR-0023：ASR 阶段加整窗复读守卫（`repeat-strict`＋折叠）

状态：已接受（2026-11-10，用户裁定 [v15](../research/2026-11-10-asr-robustness-v15.md) §8 第 7 项的 A：进产品）、**已实现（2026-11-11）**：纯逻辑 `kototoki/guard.py`，接入 `kototoki/workers/asr.py`；产品 W0 配方 id `w0-faster-whisper-large-v3-guard-v2`，`recipe_hash` W0 `b73198fac0a1b8eb1ccc24d7d33479e3a42059989e4ef2a6820367efcb603e76`、CROSS `d29b138b492290b3c1fbf788c029472c97ecc1fb58aa7cdc4bb415c1cbec717f`。验收（2026-11-11，产品 asr＋align worker 重算）：HF III 只有第 51 窗被折叠（94 → 31 字），官方 CER 13.3973%（S 769／D 448／I 304）逐项复现；HF II 守卫零命中，CER 16.8073%（S 876／D 676／I 260）与对照逐项相同；两部其余窗口文字与对照全等；`just check`／`just test`／`just test-full` 全绿；`just smoke` 只跑了 STT 六项（w0 冻结窗口门禁通过，x0 冻结窗口仍是 2026-10-14 已接受的窗口 0 差异，起 llama-server／Strata 的三项未跑）。过程与数字见[实现计划](../plans/asr-repeat-guard.md) §7、§8。下文"未验证"一节写于实现之前。不替代任何 ADR：[ADR-0003](0003-new-pyannote-baselines.md) 的 W0 基线身份（解码器、VAD、对齐）不变，本 ADR 只在产品 ASR 阶段加一步后处理；[ADR-0012](0012-cross-asr-judge.md) 的 `cross` 规则不变。  
范围：产品包 `kototoki/` 的 w0 路径。不改解码参数、VAD 参数、MMS 对齐，不改 x0 路径，不改研究侧 demo。

## 决定

1. **规则 `repeat-strict`。** 对每个未失败的 w0 窗口，在规范化文本（NFKC、去标点与空白）上检测：
   - 相邻重复：周期 ≥2 字的单元连续重复 ≥10 份（同一字符连写按周期 2 计）；或
   - 非相邻复现：长度 ≥3 字的子串不重叠出现 ≥10 次；
   - 且重复部分覆盖该窗规范化文字的 ≥50%。
   定义以 `experiments/asr_robustness_v15/repeat.py` 为准（产品实现时移植为产品自己的纯函数，产品不导入 `experiments.*`）。
2. **动作：折叠。** 命中的相邻重复区段只保留第一个单元；折叠后仍命中规则的窗口置空，按现有 `failed_windows` 协议记录（原文字移入 `failed_windows[].text`，由 `align` 按既有规则分配时间）。trace 记录规则名、周期、份数、删去的字符数。
3. **位置。** `asr` 阶段内、解码返回之后、写转写文档之前；只做后处理，不重解码、不温度回退。`cross` 引擎照常拿折叠后的 w0 文字打分；被置空的窗口沿用 `w0_failed_window: stays failed`。
4. **配方。** 产品 W0 配方加 `guard` 块并换新 id（草案 `w0-faster-whisper-large-v3-guard-v2`）；hash 级联到 `CROSS` 与全部下游身份。既有工作目录的 `asr.json` 身份失效、整批重算，不做迁移。
5. **不做的事。** 不以压缩比或 `avg_logprob` 单独置空（有歌词误报）；不用更宽的重复阈值（6 份有 13 个误报，8 份出现第一个正常窗）；不管低压缩比的插入套话（重复规则拦不住，另需信号）。

## 依据

- [v15](../research/2026-11-10-asr-robustness-v15.md) 票据 01：6 条候选规则里只有 `repeat-strict` 在 101 个 w0 样本／5618 窗上对 Opus 判为正常语音的窗口零标记（17 窗＝16 幻觉＋1 无法判断）；份数阈值 ≥9 起零误报。
- 票据 02：HF III 第 51 窗（94 字、参考 11 字）折叠净 −42 编辑（官方 CER 13.7673% → 13.3973%），优于置空 −40 与 `no_repeat_ngram_size` 补解 −37；Opus 读感同序。HF II 零命中、CER 逐项不变。
- 判据是安全网（零误报＋拦住已知复读窗），不是平均 CER；收益是堵住偶发的整窗复读。

## 影响

- 实现时要改：`kototoki/workers/asr.py`、`kototoki/recipes.py`、新的守卫纯函数模块；重钉 `tests/core/test_recipes.py` 的 W0、CROSS hash；同步[技术设计](../specs/bilingual-subtitle-pipeline.md)与 [STT worker 模块页](../architecture/modules/stt-workers.md)。草案细节见 v15 §8 第 8 项。
- 召回有限：v15 样本里 78 个幻觉窗只拦 16 个。

## 未验证

- 产品实现尚不存在；配方 id 与 hash 以实现时为准。
- 验收（实现时做）：HF III 第 51 窗被折叠、官方 CER 13.3973% 逐项复现；HF II 全量 CER 与对照逐项相同；`just test` 全绿；`just smoke` 一次。
- 证据只来自两部电影、国会与若干 demo 样本上的 w0 输出；剧集与其他作品未扫。
