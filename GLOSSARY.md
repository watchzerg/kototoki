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
recipe `b10-joint` (ADR-0006: 10 targets/batch, 1 neighbour each side, joint-understanding prompt).

Legacy CLI defaults (old PyanNet / fixed30) are **not** the adopted baselines; see [ADR-0003](docs/adr/0003-new-pyannote-baselines.md).
