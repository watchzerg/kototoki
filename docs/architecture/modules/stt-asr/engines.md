---
covers:
  - kototoki/asr_whisper.py
  - kototoki/asr_qwen.py
---
# STT ASR 子页：w0／x0 适配器

`STT ASR` 的子页：两个推理适配器 w0（faster-whisper large-v3）与 x0（Qwen3-ASR-1.7B-hf）的加载、解码参数与单窗失败处理。

## ASR w0（`asr_whisper.WhisperAsr`）

- 模块顶层先 `import torch` 再 `import ctranslate2`、`faster_whisper`：CT2 的 Linux wheel 不自带 CUDA 运行库，按 soname 加载 `libcublas.so.12`、`libcudnn.so.9`，复用 torch 已从 `site-packages/nvidia/` 加载的那一份；不设 `LD_LIBRARY_PATH`。smoke `ct2_after_torch` 核对这一点（Linux 上尚待首跑）。
- 解码参数同 W0 契约，取自 `recipes.W0`；特征用 faster-whisper 按模型 `preprocessor_config.json` 建的 `FeatureExtractor`（`features()`：`extractor(window)[..., :-1]`，Mel 补零／截断到 3000 帧，同 faster-whisper `BatchedInferencePipeline`，ADR-0035「W0 特征」）；模型不在 CUDA float16 上或不是 128 Mel 即失败。
- 窗口输入要求整数样本（`schema.validate_windows`）。
- 单窗解码抛 `RuntimeError` 时该窗文字为空、trace 为 `null` 并作为失败窗口返回，壳用 `protocol.fail_window` 记入 `failed_windows`，继续下一窗。

## ASR x0（`asr_qwen.QwenAsr`）

参数取自 `recipes.X0`：

- CUDA BF16、SDPA，加载后整体 `.to("cuda:0")`；原生 `AutoProcessor.apply_transcription_request`（强制日语、16 kHz、不补到 30 s）、greedy、`max_new_tokens` 4096、batch 1、逐窗独立无前文。
- CUDA 不可用、参数或输入张量不在 CUDA 上即失败。
- 触顶（生成 token 数达到 4096）的窗口：段内保留截断文字、trace 照常记录，并以原因 `token_limit_reached: generated <n> tokens` 作为失败窗口返回；壳经 `protocol.fail_window` 把该窗 `text` 置空、截断文字移入 `failed_windows`，不进对齐、cue 与翻译（[失败收敛](../../collaborations/failure-convergence.md)）。
- 单窗生成抛 `RuntimeError` 的处理同 w0。段结构与 w0 相同，`avg_logprob` 为 `null`。

## 代码与验证入口

- 代码：`kototoki/asr_whisper.py`、`kototoki/asr_qwen.py`；壳 `kototoki/workers/asr.py` 见[枢纽页](../stt-asr.md#代码与验证入口)。
- `tests/core/test_asr_whisper.py`：短窗裁一帧再补零；单窗 `RuntimeError` 记为失败窗口，其余窗口继续。
- `tests/core/test_asr_qwen.py`（伪 processor／模型）：触顶窗口保留截断文字并返回失败；经壳串到对齐与 `build_cues`：触顶窗口置空、截断文字进 `failed_windows`、不进 cue。
- 测试精简（2026-11-22）后不再有测试覆盖：
  - w0：torch 先于 ctranslate2 的导入顺序、满窗裁到 3000 帧、空窗或超 30 s 窗口被拒、按整数样本裁剪、非法窗口解码前被拒。
  - x0：配方生成参数与逐窗独立转写、只取 prompt 之后的 token、`RuntimeError` 窗口、模型不在 CUDA 即失败、非法窗口被拒、x0 壳的配方 hash 与模型文件清单随引擎变化。
- 真实模型验证：`mise run smoke ct2_after_torch`（CT2 的 CUDA 库来源）。
