# T3 Whisper 打分 `WhisperAsr.score`

Status: done
Type: task
依赖：无

## 内容

`kototoki/asr_whisper.py` 增加教师强制打分：编码一次、批 `align()`、Σ log text_token_probs；新增真实模型 smoke 项。

## 文件所有权

`kototoki/asr_whisper.py`、`tests/core/test_asr_whisper.py`、`scripts/smoke/whisper_score.py`、`scripts/smoke/run_all.py`（只加注册行）

## 完成标准

伪模型离线测试通过；smoke 在冻结窗口上产品文本分数高于打乱文本且与产品 avg_logprob 差 < 0.5 nat（smoke 需用户批准后才运行）。

## Comments

### 实现说明（2026-10-19）

- `WhisperAsr.score(audio, chunk, texts, max_batch=16) -> list[float]` 已加，`start_sequence` 取 `tokenizer.sot_sequence`（调研已核实；传含 `<|notimestamps|>` 的产品提示会被 CT2 重复补一次）。`max_batch` 默认 16，T4 定义 `recipes.CROSS["judge"]["max_batch"] = 16` 后由调用方传入；本票未改 `recipes.py`。
- 离线测试（`tests/core/test_asr_whisper.py::ScoreTest`，伪 torch／ctranslate2／模型）通过，`tests/core` 全量 417 项通过，`compileall` 通过。
- smoke `whisper_score` 已写并登记到 `scripts/smoke/run_all.py`（`just smoke whisper_score`），**未运行**，须用户批准。冻结窗口 wav 约 300 s 超过 30 s 上限，因此改用同窗 W0 结果里的前 3 个 VAD 窗口（与任务原文"整个文件当一个窗口"不同）。
- 空文本及编码后无 token 的文本得 0.0 且不进 `align`；全部为空时 `score` 不跑 mel、编码器。

- 2026-10-19 主 agent 审查：实现与研究脚本一致（sot_sequence、Σ log probs、空文本 0.0、批 ≤16）；changes 文档 §2.2 的 start_sequence 措辞已按此更正。smoke 项待用户批准后运行。
