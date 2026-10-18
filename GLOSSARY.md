# Kototoki

Kototoki 是在原生 Windows 与 RTX 5080 上用本地 AI 模型转写音频、保留原语言的自托管 STT 工具，当前处于研究与 demo 阶段；另含独立的字幕翻译实验。本术语表收录这些基线、组件与实验流程的项目特有叫法。

## Language

只收录本项目特有的概念，不收录通用编程概念。一个概念有多个叫法时选定一个，其余列入 `_Avoid_`。定义只说它是什么，一两句。术语自然成簇时用子标题分组。

条目格式：

```md
**术语**：
一两句定义。
_Avoid_: 同义词一, 同义词二
```

### 基线身份

**W0**：
faster-whisper + new Pyannote segmentation-3.0 + MMS CTC alignment, with WhisperX
ideas ported (cut-merge, timestamp-free decoding, feature handling).

**X0**：
Qwen-ASR + new Pyannote + the same MMS, adopting only WhisperX ideas compatible
with Qwen (keep Qwen-native decoding/features). fixed30 and no-VAD cut-merge are separately
identified controls.

**Translation baseline**：
Separate experiment, not part of the STT milestone: Hy-MT2 30B-A3B
APEX-I-Compact, sampling recipe `official30b-cached-v1`; full-SRT flow baseline is the v3
recipe `dp10-cut` since 2026-10-17 (ADR-0010: joint-understanding prompt of `b10-joint`, DP packing of
6-10 targets around 10 with at most 12 visible cues, cuts penalised at short silences, never across a
>=20 s silence, gap-aware read-only neighbours; not GPU-screened). `dp6-grp` (ADR-0009: cuts only between
<1 s groups, 6-12 targets, never across >=10 s) briefly preceded it; `b10-joint` (ADR-0006: 10
targets/batch, 1 neighbour each side) is the earlier baseline and the control of rounds v3-v7; `dp10-cut`
is the control of round v8. `gap_pack` is the recipe field for silence-aware packing (`gap-pack-v1` in
`dp6-grp`, `gap-pack-v2` adds the tiered cut penalty of `dp10-cut`). `grp1` (v8: R2+ sentence groups
injected into `dp10-cut` packs with the `joint-understanding-v2` prompt, `group-reorder-v1`) produced no
reordering and the line was closed on 2026-10-18; it is kept as a recipe, not a baseline. The product
recipe `dp10-cut-degrade-v1` (ADR-0011, 2026-10-18) carries the same packing into `kototoki/`.

### 双语字幕流水线

**双语字幕流水线**：
产品包 `kototoki/`，入口 `python -m kototoki [kototoki.toml]`：一批日语视频按阶段整批推进（probe／extract → vad → asr → align → ja-cues → translate → 发布），每部产出 `<stem>.ja.srt`、`<stem>.zh.srt`、`<stem>.ja-zh.srt`。
_Avoid_: 产品后端, 正式后端

**STT 引擎（w0／x0）**：
配置键 `stt.engine` 的取值，分别按 W0／X0 的配方在产品统一 CUDA 12.8 环境中运行；环境升级即新身份，与基线成绩的回归本期未做，不直接继承 W0／X0 的分数。

**日文 cue**：
翻译与字幕的最小单元：由 `align.json` 字符时间回填后按句末、软断点、字数与时长切出的一条日文字幕（`ja-cues.json`／`ja.srt`），中文译文与之一一对应。

**整窗 fallback**：
日文 cue 回填时，一个窗口没有任何字符时间，按 VAD 子段比例给字符排时间（`time_source=fallback`）；只属时间回填，不是翻译回退。

**产品翻译配方 `dp10-cut-degrade-v1`**：
`kototoki/translate/recipes.py` 的产品翻译配方（2026-10-18 起，ADR-0011）：切包、邻文、提示、grammar、采样与请求字节与 v3 `dp10-cut` 完全相同，只把批次终态失败的处理（`overflow`）改为拆批降级（两半→单条）、单条仍失败保留日文，因此另算 `recipe_hash`。2026-10-14..18 的产品配方 `b10-joint-degrade-v1` 与 `b10-joint` 同此关系，保留作旧 run 目录的身份对照。
_Avoid_: dp10-cut、b10-joint（指产品配方时）

**回退 cue**：
降级到单条仍失败、译文保留日文原文的 cue；对该配方 hash 与 seed 是终态，重跑不再尝试，只有改 seed 才重译；数量记入 `translate/report.json` 与 `published.json`。

**阶段计划**：
双语字幕流水线中对一个文件从 vad 起逐阶段核对产物身份、给出"下一个要跑的阶段"（或终态 `publish`／`done`）与各阶段期望身份的模块（`kototoki/plan.py`）；编排只负责问，worker 壳从它取写进产物的身份。
_Avoid_: 计划器, 调度计划

**产物身份**：
写在每个中间产物里的身份（上游 SHA256、配方 hash、模型 SHA256、相关配置），续跑时与期望身份相同即跳过、不同即原地替换；不含绝对路径。翻译阶段没有单一产物文件，其身份（`ja.srt` SHA256、配方 hash、seed）与 run 目录键由翻译子系统的 `translate.plan` 给出。

**发布**：
三份最终 SRT 先写入工作目录暂存、记入 `published.json` 再一起移到输出目录；用户改动过的最终文件在 `force = false` 时不被覆盖。

Legacy CLI defaults (old PyanNet / fixed30) are **not** the adopted baselines; see [ADR-0003](docs/adr/0003-new-pyannote-baselines.md).
