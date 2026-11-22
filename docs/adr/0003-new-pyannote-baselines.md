# ADR-0003：STT 基线、设备与产品 STT 引擎

状态：已接受。2026-11-18 按主题合并（用户授权）：并入 ADR-0001、ADR-0002、ADR-0012，原文见 git 历史（提交 807de3e 及之前）。「产品 STT 引擎」第 1 点的默认引擎与确认要求自 2026-11-20 起由 [ADR-0035](0035-cross-default-native-whisper-features.md) 替代（默认改为 `cross`）。
范围：本地 GPU 日语转写的两条基线身份与组件、设备约束，以及产品包 `kototoki/` asr 阶段的可选引擎 `w0`｜`x0`｜`cross`。操作入口与逐项组件定义见[当前基线](../research/2026-10-stt-demo-w0-x0.md)；阶段框架见 [ADR-0007](0007-bilingual-subtitle-pipeline-architecture.md)；整窗守卫见 [ADR-0030](0030-asr-window-plausibility-guard.md)。行为描述见[STT worker](../architecture/modules/stt-workers.md)、[阶段计划](../architecture/modules/stage-plan.md)、[产物契约](../architecture/modules/artifact-contract.md)、[配置与媒体](../architecture/modules/config-and-media.md)。

## 决定

### W0／X0 基线

1. **W0**：faster-whisper，无降噪、无人声分离，新 Pyannote VAD，MMS 日语 CTC 对齐。WhisperX 已核验的切分合并、独立无时间戳解码和特征处理是必要组成，须由自有适配层承接；只组合三个模型或直接调用标准 API 不算 W0。
2. **X0**：Qwen-ASR，无降噪、无人声分离，同一新 Pyannote VAD，同一 MMS 日语 CTC。只吸收适用于 Qwen 的 WhisperX 流程思想：保留 Qwen 原生 processor、特征与独立纯文字解码，不复制 Whisper 专属 Mel、token 或 CT2 参数，不要求照搬 Whisper 的特征。
3. **新 Pyannote** 指 `pyannote.audio 4.0.7` 与 `pyannote/segmentation-3.0`，权重 revision `e66f3d3b9eb0873085418a7b813d3b369bf160bb`，用原生 powerset 语音检测及源跨度切分合并；不是旧 PyanNet 配方，也不是完整 diarization。
4. **分段**：两路均先检测语音，再按原音频源跨度组织最多 30 秒的识别窗口，保留整数采样坐标、块内间隙与完整识别文字，MMS 对应同源窗口对齐。MMS 使用已核验的日语 `jpn` adapter，复用 W0 实现并带可选整数样本窗契约（秒坐标路径行为不变），ASR 与 MMS 消费同一音频片段，不另建第二套对齐器。
5. **保留语言与本地**：保留日语原文，本地 GPU 推理，不上传音频。
6. **历史身份**：旧 PyanNet W0、X0 无 VAD fixed30、X0 `cut-merge`（低能量切点＋按源跨度有界合并，方法适配，不声称与 WhisperX 神经 VAD 后处理等价）只作历史／对照身份；省略策略参数的旧命令不得称为最新基线。历史 manifest、route 值、目录和分数不改写，新运行另建身份并固定完整配置，不得跨身份归分（例如不得把旧 W0 的单模型成绩或旧 X0 的 Jonatas 对齐成绩归给新基线）。
7. **复用入口**：W0 持续迭代入口为 `archive/2026-11-18-pre-research-restructure:experiments/w0_demo/`，X0 为 `archive/2026-11-18-pre-research-restructure:experiments/x0_demo/`；分段、模型或解码变化须更新 recipe 与验证记录。基线测试从[标准基线测试指南](../research/2026-10-stt-demo-w0-x0.md)开始，契约见 [W0](../research/2026-10-stt-demo-w0-x0.md)、[X0](../research/2026-10-stt-demo-w0-x0.md)。

### 设备

1. ASR 与 CTC 强制对齐只跑 GPU，不回退 CPU。
2. VAD 可用 CPU 或 GPU，不以 GPU 支持作为资格条件；产品包的 VAD 固定 `cuda:0`。
3. 现有整片证据采用 CUDA FP32，换设备须独立记录。

### 产品 STT 引擎

1. **可选引擎，默认不变**：`[stt] engine` 取 `w0 | x0 | cross`，默认 `w0`；产品包的 STT 阶段承接上述两条基线。改默认须新 ADR，并先在全新隔离材料上确认。
2. **`cross` 裁判配方**（常量 `CROSS`，id `cross-w0-x0-whisper-judge-v1`，非配置项）：窗口级，两路文本规范化后做字符级编辑距离对齐，非匹配操作的极大连续段为分歧区间；Whisper 对每个区间的两个假设（w0 原文、仅该区间换成 x0 原文）做教师强制打分，分数为 Σ log `text_token_probs`（不含结束符）；d ＝ score(hyp_x) − score(hyp_w)，**d > −1.0 取 x0，否则保持 w0**，无长度项；多区间各自判定后一起应用；打分批上限 16。
3. **`cross` 守卫**：两路相同的窗口不打分；合并结果为空而 w0 非空时保持 w0；x0 窗口失败时取 w0；打分抛错的窗口取 w0 并告警计数（不算窗口级失败）；w0 窗口失败仍记失败。
4. **共驻**：同一 asr worker 进程内常驻 Whisper（CT2）与 Qwen（torch），逐文件按"Whisper 转写 → Qwen 转写 → 裁判"推进。判据是探针实测整卡峰值加 1 GB 余量 ≤ 13.5 GB，否则回退为 Whisper 整批转写 → 卸载 → Qwen 整批转写 → 卸载 → Whisper 整批打分的三段式（产物与接口不变；回退未实测）。
5. **阶段链不变**：裁判在 asr 阶段内部，不改阶段链与 align／cues／translate 接口；下游只见同构的 `asr.json`；两路结果与裁判记录另存 `asr-w0.json`、`asr-x0.json`、`asr-judge.json`，只作审计与离线复算，不参与 `is_current`。`CROSS` 配方嵌入 W0／X0 子配方，任一变化即身份变化。
6. **整窗守卫**只作用于 w0 路径（含 `cross` 的 w0 一路），规则与配方 id 见 [ADR-0030](0030-asr-window-plausibility-guard.md)；`cross` 用守卫处理后的 w0 文字打分。

## 身份

- `cross-w0-x0-whisper-judge-v1`：`cross` 裁判配方 id（`recipes.CROSS`）。
- 新 Pyannote 权重 revision `e66f3d3b9eb0873085418a7b813d3b369bf160bb`（`pyannote.audio 4.0.7`、`pyannote/segmentation-3.0`）。
- 产品 W0 配方 id 与 `recipe_hash`（含 guard）随整窗守卫演进，现行值见 ADR-0030。
- 历史：旧 PyanNet W0、X0 fixed30、X0 `cut-merge`（见基线第 6 点）。

## 依据

- 用户在两部完整电影对照后明确采纳新 Pyannote。[两片整片对照](../research/2026-10-vad-comparison.md)：W0 新 Pyannote 的文字与时间指标优于 cut-merge；X0 配对排除失败后文字几乎持平，选择新 Pyannote 主要由零 ASR 触顶及运行成本支持。
- [Whisper 框架研究](../research/2026-10-stt-demo-w0-x0.md)支持在 faster-whisper 上以明确适配层保留关键行为；[MMS 补充实测](../research/2026-10-components-and-ctc.md)支持其作为对齐方向。
- [X0 流程研究](../research/2026-10-x0-whisperx-flow.md)与 [demo 契约](../research/2026-10-stt-demo-w0-x0.md)定义样本守恒、30 秒边界、完整文字、实际 GPU 与错误记账验收项；对特定质量或性能提升的宣称须有可复现证据。
- `cross`：合并理论上限两部合计 CER 16.16% → 11.90%（oracle，[上限](../research/2026-10-cross-asr-judge.md)）；Whisper 当裁判到 14.31%，拿到上限增益的 43%，替换区间 AUC 0.774（[交叉打分](../research/2026-10-cross-asr-judge.md)）；MMS 当裁判只到 15.40%、AUC 0.49，叠加 Qwen 或 MMS 反而稀释。
- `cross` 产品路径验收（[T6](../research/acceptance/cross-asr-acceptance-2026-10-19.md)，HF II／III 官方整片口径）：CER 15.25% → 14.30%（−0.95 pp），两部都低于 w0；低于预设 1.0 pp 线，用户 2026-10-19 知悉后仍裁定采用，默认保持 `w0`。
- 显存：[T0 探针](../research/acceptance/cross-coresidency-probe-2026-10-19.md)整卡峰值 10688 MiB，产品验收 10030 MiB。成本：asr 阶段墙钟 1211.6 s，为 w0（323.4 s）的 3.75 倍，整批 1754.8 s 对 890.3 s；用户已接受。

## 未验证与已知限制

- **CLI 默认值未迁移**：`archive/2026-11-18-pre-research-restructure:experiments/w0_demo/run.py` 不给 `--vad-manifest`／`--frozen-vad` 时走旧 PyanNet 检查点（`--vad-checkpoint` 默认 `w0-assets/pytorch_model.bin`）；`archive/2026-11-18-pre-research-restructure:experiments/x0_demo/run.py` 的 `--segmentation` 默认 `fixed30`。运行最新基线须显式提供新 Pyannote 的 VAD manifest（X0 同时 `--segmentation vad`）。
- 未证明新 Pyannote 优于所有历史候选，也未证明满足严格字幕时间目标；X0 时间质量无普遍优势，极短窗 MMS 失败仍存在；未比较 fixed30 整片表现。
- `cross`：新材料确认与译文层收益未测（译文层需外部裁判，另行裁定）；Whisper 自偏好稳定存在（阈值 −1 吸收），分数不含结束符，多字少字类区间有"越短越占便宜"偏差；抽查 15 个切换中 6 个为纯表记改动，其余词义替换未听音判对错；增益构成替换 −82、插入 −175、删除 +47，未达线原因未拆分；w0 失败窗口以 x0 替代的做法未覆盖。
- [ADR-0008](0008-no-multi-translation-selection.md) 只约束翻译，不涉及两路识别之间的裁判。

## 沿革

- 2026-10-04 ADR-0001：采用 W0／X0 两条 STT 基准线（W0 旧 Pyannote，X0 无 VAD fixed30）；10-05 放宽 VAD 设备限制为 CPU 或 GPU。
- 2026-10-05 ADR-0002：X0 复用入口与 `cut-merge` 适配；无 VAD／fixed30 选择随后被新 Pyannote 取代。
- 2026-10-05 ADR-0003：两路统一改用新 Pyannote；2026-11-08 合并 ADR-0001、ADR-0002 的有效条款。
- 2026-10-19 ADR-0012：新增可选引擎 `cross`，默认仍 `w0`。
- 2026-11-18：按主题合并为本页，W0 持续迭代入口改指归档 tag。
