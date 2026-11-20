# ADR-0035：产品默认 STT 引擎改为 `cross`，W0 特征改用 faster-whisper 自带的计算

状态：已接受，2026-11-20（用户裁定）；代码已实现，Linux 上的真实模型尚未运行。
替代关系：
- 取代 [ADR-0003](0003-new-pyannote-baselines.md)「产品 STT 引擎」第 1 点中的"默认 `w0`"与"改默认须先在全新隔离材料上确认"；
- 取代 [ADR-0030](0030-asr-window-plausibility-guard.md)「身份」中的产品 W0 配方 id 与 hash（守卫规则本身不变）。

范围：产品 asr 阶段的默认引擎；产品 w0 路径（含 `cross` 的 w0 一路和 Whisper 裁判打分）的特征计算。

不改：W0／X0 研究基线的身份（只作历史）、W0 解码参数、整窗守卫规则、`cross` 裁判规则、X0 配方。

## 决定

### 默认引擎

1. `[stt] engine` 默认改为 `cross`；`w0`、`x0` 仍可选。
2. 用户明确不做 ADR-0003 要求的"全新隔离材料确认"，依据只有已有的 `cross` 产品路径验收（见「依据」）。
3. 默认配置因此需要两路 ASR 模型（faster-whisper-large-v3 与 qwen3-asr-1.7b-hf），asr 阶段耗时约为 w0 的 3.75 倍。

### W0 特征

1. 产品 w0 不再移植 WhisperX 的特征链（torch STFT，乘随 WhisperX 3.8.6 分发的 `mel_filters.npz`，波形先补零到 30 s 再算）。
2. 改用 faster-whisper 加载模型时按 `preprocessor_config.json` 建好的 `FeatureExtractor`，与 faster-whisper `BatchedInferencePipeline` 的逐块路径相同：
   - 每个 VAD 窗口算 `extractor(window)[..., :-1]`；
   - 再在 Mel 上补零或截断到 3000 帧（同 `faster_whisper.audio.pad_or_trim`）。
3. Whisper 裁判打分用同一个特征函数。
4. 删除 `w0-assets`：
   - `assets.toml` 里的条目；
   - 配置键 `[asr.w0] mel_assets`；
   - jobs 的模型键 `w0_mel_assets`。
   旧配置写着 `mel_assets` 时，按未知键报配置错误。
5. 和基线特征链的差别：
   - 补零区的取值：基线在归一化之前补波形，这里在归一化之后补 Mel；
   - STFT 与 Mel 滤波器的实现：numpy 对 torch，faster-whisper 现算的滤波器对预存矩阵。
   因此转写可能与 W0 基线有细微差别。配方的 `baseline` 字段仍记 `w0-pyannote-current-mms-v1`，表示解码参数取自该基线。

## 身份

- 产品 W0 配方 id `w0-faster-whisper-large-v3-fwmel-guard-v3`；`recipe_hash`：
  - W0：`9f2c8ea8dc8f6334b45f6f257e466363acc947d75ad94531aa13bc531c5d09b4`；
  - CROSS：`4041dd2496f73aa3e46f17afc2a769c161a94e7d7894a3bc0f48f2d9decb2cf2`（嵌套 W0 而随之改变，id 仍是 `cross-w0-x0-whisper-judge-v1`）；
  - X0 不变：`5d1bec25fbb4acae6d82a866620faf75e2c55498aa304c1dadd7dc401bfd057b`。
- w0 与 `cross` 的模型文件身份不再含 `w0-assets/mel_filters.npz`。
- 已有的 w0／`cross` 产物身份随之失效，续跑会从 asr 阶段重做。

## 依据

- 用户 2026-11-20 裁定：生产默认用 `cross`；不保留 WhisperX 的 mel 资产，直接用 faster-whisper 自己的特征计算。这符合 [ADR-0034](0034-ubuntu-only-platform.md)「平台」的全新开始原则，不与 Windows 时期或研究期的结果比对。
- `cross` 的收益见 ADR-0003「依据」：产品路径验收在 HF II／III 官方整片上测得 CER 15.25% → 14.30%（−0.95 pp），两部都低于 w0；显存峰值约 10 GB。

## 未验证与已知限制

- `cross` 的 −0.95 pp 是在旧特征链、Windows 环境下测得的；换特征后，w0 与 `cross` 的质量都没有重新测。
- 没有在全新隔离材料上确认，这是用户的豁免。
- Linux 上还没有跑过真实模型；共驻显存峰值来自 Windows 时期的测量。

## 沿革

- 2026-11-20：默认引擎由 ADR-0003 的 `w0` 改为 `cross`；W0 特征从移植的 WhisperX 特征链改为 faster-whisper 自带的计算。
