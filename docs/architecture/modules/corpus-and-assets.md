# 语料与模型资产准备

## 定位与阅读

负责推理之前的两类一次性准备：一是从私有源素材冻结语料划分、生成样本精确的 mono／16 kHz／PCM16 输入 WAV 与参考 JSON；二是按固定 revision 联网获取 STT 模型资产并记录 SHA256 清单。推理入口只读取这些本地产物；本模块是仓库中唯一会主动联网下载模型的代码。不负责翻译模型 GGUF 的获取（见[本地翻译模型资产指南](../../guides/local-translation-model-assets.md)），也不负责门控 Pyannote 权重的获取（见 [VAD 版本核验](../../research/2026-10-05-vad-stable-versions.md)）。

上级总览见[架构总览](../INDEX.md)；素材规则见 [FateStay 参考](../../testing/fatestay-reference.md)；冻结证据见[语料冻结记录](../../testing/2026-10-04-corpus-freeze.md)；环境与资产清单见[环境清单](../../research/2026-10-04-runtime-inventory.md)。

## 当前行为规格

- 语料（`experiments/corpus/`，CPU 文件处理，无推理）：
  - `prepare.py`：按容器章节与固定规则冻结单片 dev／validation／heldout 划分（章节两端 10 秒隔离），校验源 SRT SHA256、要求唯一日语音轨，`--decode` 时用 ffmpeg 解码并按样本裁剪；输出不可变写入，私有根不能位于源素材目录。
  - `prepare_round2.py`：按固定比例为 HF II／III 冻结 300 秒窗口（修订 `hf-ii-iii-fixed-fractions-round2-2026-10-04`），生成样本精确 PCM 与包含跨边界 cue 的参考；基线测试指南中的 `.local/round2/corpus/` 输入即由此生成。
  - `prepare_heldout.py`、`prepare_scoring_reference.py`、`prepare_silence.py`：从冻结 PCM 提取保留章、派生源侧排除覆盖层、生成可再分发的数字静音预检输入。
- 模型（`experiments/provision/`，联网）：`acquire_models.py` 对 `SPECS` 中每个模型核对 Hugging Face revision，优先复用本地已校验副本，否则下载；写 `.local/manifests/model-<name>.json`（文件大小、SHA256、上游 LFS 哈希、获取方式），失败写 `model-<name>-failure.json` 并保留部分文件以便续传。`japanese_ctc.py` 只获取 Reazon／MMS／hiragana 三个日语 CTC 资产；`range_models.py` 对单文件做有界并行 Range 续传。
- W0 资产：`experiments/w0_demo/prepare_assets.py --source <whisperx assets>` 从已有本地文件复制旧 PyanNet checkpoint 与 Mel 文件到 `.local/models/w0-assets/`，校验固定 SHA256，目标已存在时拒绝覆盖。

## 实现设计

- 语料脚本把规则修订号、源哈希、样本范围写入 manifest，复跑时校验并复用已有音频，不把复用记为新结果。
- 获取脚本只用标准库 `urllib`；同一 revision 的已存在文件重新计算哈希后记 `existing_verified`。

## 接口与依赖

- 产物通过文件被[外部 VAD 阶段](vad-stage.md)、[W0 pipeline](w0-pipeline.md)、[X0 pipeline](x0-pipeline.md)（WAV、模型目录）和 [STT 评分与显示重放](stt-evaluation.md)（参考 JSON）读取；这些模块不导入本模块。
- 推理入口不得调用本模块（见[模块边界：依赖方向](../module-boundaries.md#依赖方向)）。

## 代码与验证入口

- 源码：`experiments/corpus/prepare.py`（`freeze`、`decode_full`、`crop`、`parse_srt`）、`prepare_round2.py`（`fixed_windows`、`window_reference`、`prepare`）、`prepare_heldout.py`、`prepare_scoring_reference.py`、`prepare_silence.py`；`experiments/provision/acquire_models.py`（`SPECS`、`acquire`）、`japanese_ctc.py`、`range_models.py`；`experiments/w0_demo/prepare_assets.py`。
- 测试（离线，`just experiments-test`）：`experiments/corpus/test_prepare.py`、`test_round2.py`、`test_silence.py`；`experiments/provision/test_acquire_models.py`（伪响应下的获取与完整性）、`test_range_models.py`。
- 已知差异：[语料冻结记录](../../testing/2026-10-04-corpus-freeze.md)说明 `prepare.py` 的默认路径与参考常量属于旧单片 FateStay 冻结，"不代表已经支持新的两片语料流程"；代码中 `prepare.py` 仍以 `D:/movie/FateStay/...` 为默认参数。新语料须另建 manifest，不覆盖旧哈希。
- 已知限制：`acquire_models.SPECS` 的清单停留在 2026-10-04 的候选集（含历史 Qwen ForcedAligner、Crisp GGUF 等），不覆盖新 Pyannote 与翻译 GGUF。

## 变更与决策来源

[语料冻结记录](../../testing/2026-10-04-corpus-freeze.md)、[MMS 来源核验](../../research/2026-10-04-japanese-ctc-source-verification.md)、[环境清单](../../research/2026-10-04-runtime-inventory.md)。
