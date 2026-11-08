# ADR-0012：产品 STT 可选引擎 cross（x0 转写＋Whisper 交叉打分裁判）

状态：已接受。合并整理于 2026-11-08（精简为现行条款；原文见 Git 历史，历次变更见[决定索引·演进链](INDEX.md#演进链)）。  
范围：产品包 `kototoki/` 的 asr 阶段取值 `cross`；STT 基线身份见 [ADR-0003](0003-new-pyannote-baselines.md)，阶段框架见 [ADR-0007](0007-bilingual-subtitle-pipeline-architecture.md)。不改阶段链与 align／cues／translate 接口。行为描述见[STT worker](../architecture/modules/stt-workers.md)、[阶段计划](../architecture/modules/stage-plan.md)、[产物契约](../architecture/modules/artifact-contract.md)、[配置与媒体](../architecture/modules/config-and-media.md)。

## 决定

1. **可选引擎，默认不变。** `[stt] engine` 取 `w0 | x0 | cross`，默认 `w0`；改默认须新 ADR，并先在全新隔离材料上确认。
2. **裁判配方**（常量 `CROSS`，id `cross-w0-x0-whisper-judge-v1`，非配置项）：窗口级，两路文本规范化后做字符级编辑距离对齐，非匹配操作的极大连续段为分歧区间；Whisper 对每个区间的两个假设（w0 原文、仅该区间换成 x0 原文）做教师强制打分，分数为 Σ log `text_token_probs`（不含结束符）；d ＝ score(hyp_x) − score(hyp_w)，**d > −1.0 取 x0，否则保持 w0**，无长度项；多区间各自判定后一起应用；打分批上限 16。
3. **守卫**：两路相同的窗口不打分；合并结果为空而 w0 非空时保持 w0；x0 窗口失败时取 w0；打分抛错的窗口取 w0 并告警计数（不算窗口级失败）；w0 窗口失败仍记失败。
4. **共驻**：同一 asr worker 进程内常驻 Whisper（CT2）与 Qwen（torch），逐文件按"Whisper 转写 → Qwen 转写 → 裁判"推进。判据是探针实测整卡峰值加 1 GB 余量 ≤ 13.5 GB，否则回退为 Whisper 整批转写 → 卸载 → Qwen 整批转写 → 卸载 → Whisper 整批打分的三段式（产物与接口不变；回退未实测）。
5. **阶段链不变。** 裁判在 asr 阶段内部；下游只见同构的 `asr.json`；两路结果与裁判记录另存 `asr-w0.json`、`asr-x0.json`、`asr-judge.json`，只作审计与离线复算，不参与 `is_current`。`CROSS` 配方嵌入 W0／X0 子配方，任一变化即身份变化。

## 依据

- 合并理论上限：两部合计 CER 16.16% → 11.90%（oracle，[上限](../research/2026-10-19-asr-pair-oracle.md)）。Whisper 当裁判到 14.31%，拿到上限增益的 43%，替换区间 AUC 0.774（[交叉打分](../research/2026-10-19-asr-pair-cross-score.md)，候选见[裁判选型调研](../research/2026-10-19-acoustic-judge-survey.md)）；MMS 当裁判只到 15.40%，AUC 0.49（[MMS 裁判](../research/2026-10-19-asr-pair-ctc-judge.md)）；叠加 Qwen 或 MMS 反而稀释。
- 产品路径验收（[T6](../research/acceptance/2026-10-19-cross-asr-acceptance.md)，HF II／III 官方整片口径）：CER 15.25% → 14.30%（−0.95 pp），两部都低于 w0；低于预设 1.0 pp 线，用户 2026-10-19 知悉后仍裁定采用，默认保持 `w0`。
- 显存：[T0 探针](../research/acceptance/2026-10-19-cross-coresidency-probe.md)整卡峰值 10688 MiB，产品验收 10030 MiB，翻译阶段照常启动。
- 成本：asr 阶段墙钟 1211.6 s，为 w0（323.4 s）的 3.75 倍，整批 1754.8 s 对 890.3 s；用户已接受。

## 约束与未关闭项

- 新材料确认与译文层收益未测（译文层需外部裁判，另行裁定）。
- Whisper 自偏好稳定存在（阈值 −1 吸收）；分数不含结束符，多字少字类区间有"越短越占便宜"偏差；抽查 15 个切换中 6 个为纯表记改动，其余词义替换未听音判对错。
- 增益构成：替换 −82、插入 −175、删除 +47；未达线原因未拆分。
- w0 失败窗口以 x0 替代的做法未覆盖，本期不做。
- [ADR-0008](0008-no-multi-translation-selection.md) 只约束翻译，不涉及两路识别之间的裁判。
