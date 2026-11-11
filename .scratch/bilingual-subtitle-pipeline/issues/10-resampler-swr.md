# 10 派生 WAV 重采样改回 swr

Status: done
Type: task
Blocked by: —

## 范围

- 依据：[最终验收](../../../docs/research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md) §1——soxr 28 bit 的派生 WAV 使 Pyannote 少保留约 9–10% 语音，产品 CER 比 2026-10-05 基线高 0.5–3.5 个百分点（全部是删除）；产品 VAD 在 swr 版 `hf-ii-full.wav` 上与基线窗口完全相等。用户 2026-10-15 裁定改回 swr。
- 代码：`kototoki/recipes.py` 的 `MEDIA["resample_filter"]` 改回 `aresample=16000`（ffmpeg 默认 swr，即提交 `ddcb644` 之前的值），注释改写为本次裁定；`MEDIA` 配方 hash 随之变化，已有 `.work` 中的 `probe.json` 身份全部失效、整条链重跑，这是预期行为，不做迁移。
- 文档：规格 §1.2"重采样器"行与 §2.2"重采样器"段改为 swr 并记录改回原因（§13 加一条）；[配置、配方与媒体提取](../../../docs/architecture/modules/config-and-media.md) 的派生 WAV 步骤、真实视频记录与"已知影响"一句；[技术选型](../../../docs/development/technology-stack.md) 的 ffmpeg 行去掉"须带 libsoxr"；ADR-0007 的"重采样保持默认 swr"条款重新成立，只在 ADR 加一行备注，不改原文。
- 不做：不改 VAD 阈值、不改 `timeline_filter`（`async=1:first_pts=0` 本就由 swr 完成）。

## 完成标准

- 离线：`tests/` 中涉及滤镜链与配方 hash 的测试更新；`just test`、`just check` 通过。
- 真实核对（不占 GPU）：用 HF II 的 mkv 走一次 `probe`／`extract`，派生 WAV 的 PCM SHA256 等于 `hf-ii-full.wav` 的 `ee4e2da3…`（票据 02 在 swr 下已证明一致）。这一条成立即可推出 VAD 与基线窗口相等（最终验收已核实），不必再跑 VAD。
- 可选（GPU，需用户确认）：两部整片重跑一次并用 `kototoki_eval` 复评，确认 CER 回到基线水平；写入验收记录新文件。

## 文件所有权

`kototoki/recipes.py` 的 `MEDIA` 节、对应测试；上述文档。

## Comments

- 2026-10-15 建票，依据最终验收 §1 与用户裁定。
- 2026-10-15 完成：`MEDIA["resample_filter"]` 改回 `aresample=16000`，配方 hash 变化；`tests/test_recipes.py`、`tests/test_media.py` 随之更新。真实核对：HF II mkv 走 `probe`／`extract`，派生 WAV PCM SHA256 `ee4e2da3…` 与基线 `hf-ii-full.wav` 一致。文档：规格 §1.2／§2.2／§13、配置与媒体模块页、技术选型 ffmpeg 行、ADR-0007 备注。可选的 GPU 整片重跑与复评未做，待用户确认。
- 2026-10-15 用户裁定：GPU 整片重跑与复评暂不进行。
