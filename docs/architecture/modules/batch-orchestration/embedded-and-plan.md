---
covers:
  - kototoki/job.py
---
# 批次编排子页：内嵌字幕与计划

`批次编排` 的子页：内嵌日文字幕路径，以及续跑与跳过所用的计划与身份。

**内嵌日文字幕**（`job.use_embedded_subtitle`，在 probe／extract 的线程池里；选轨、抽取与清洗规则见[配置、配方与媒体提取](../config-and-media.md)）：

- 跳过：由[阶段计划](../stage-plan.md)判定内嵌记录是否当前（`plan.embedded_current`：身份等于 `plan.embedded_identity(probe 身份, 流索引)`，另核对 `ja_srt_sha256`，细则见阶段计划），当前即不再抽取。
- 否则 `media.extract_subtitle` → `embedded.clean`；先删上次强杀留下的临时文件，再写 `ja.srt`，最后写 `ja-embedded.json`（流信息、清洗计数、`ja.srt` 的 SHA256）。
- 不删 `ja-cues.json`：字幕轨改写 `ja.srt` 后它不再当前，以后改走 STT 时 cues 阶段自然重建；反过来，cue 阶段改写 `ja.srt` 后内嵌记录不再相符，下次走内嵌路径时重新抽取。
- `probe.json` 不当前时写出，`extract` 为 null；以后该文件改走 STT 时照常提取并改写。
- 采用后 `VideoFile.embedded` 记该身份，计划从 names 起；日志行为 `[extract] done <相对路径>: embedded subtitle stream N (<codec>), M cue(s), skipping speech recognition`，只把选轨告警与 `ffprobe`／字幕抽取的零退出码非空 `stderr` 记为 WARNING，音轨告警不记。发布行加 ` (embedded subtitles)`，`Summary.embedded` 列出这些文件，汇总行给出个数。
- 不可用（抽取失败，或清洗后零条目）：不写任何内嵌产物，记 WARNING `[extract] <相对路径>: Embedded subtitle stream N is unusable (<原因>); falling back to speech recognition`，该文件照常提取音频走 STT；不算失败、不缓存，下次运行再试。
- 字幕文字不进日志。整批都是这类文件时没有 GPU worker，GPU 锁到 names 需要模型时才取。

**计划与身份**：续跑与跳过的唯一判据是[阶段计划](../stage-plan.md)给出的 `Plan`（`stage`、各阶段期望身份、`no_speech`、`TranslatePlan`）；编排对每文件调用一次 `next_stage`，每跑完一个阶段调用一次 `advance`，不自己拼身份。

- 模型文件 SHA256 由 `model_sha_lookup` 经 `gpu.verify_models`（`plan.model_files` 给出期望值，size+mtime 缓存与 worker 共用）按阶段每次运行最多核对一次；失败结果同样缓存，模型缺失或不符时需要该阶段核对的文件记失败。
- `published.json`（审计记录）的 `sources` 即 `Plan.sources`（全部身份与 `no_speech`，含 `names`），另记 `translate_untranslated_cues`，不参与任何判定。
- 用户手改 `name-table.json` 的 `entries`：是否重译见[专名一致性](../name-consistency.md)；已发布的字幕不会自动重做。

## 代码与验证入口

- 代码与测试入口见[主流程](flow.md#代码与验证入口)。
