# 11 视频时长误取 `DURATION-<lang>` 统计标签

Status: done
Type: task
Blocked by: —

## 范围

- 缺陷（[最终验收](../../../docs/research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md) §3）：`kototoki/media.py::_tag_duration` 遍历 `stream.tags`，把 `DURATION` 与 mkvmerge 统计标签 `DURATION-<lang>` 同等接受、先到先得。ffmpeg `-c copy` 剪出的 mkv 保留原片的 `DURATION-eng`（原片全长）并新写正确的 `DURATION`，ffprobe 返回时 `DURATION-eng` 在前，产品取到原片时长，把 303 s 的合法片段判为"音频短于视频 7022 s"而失败。复现：`ffmpeg -ss 1200 -t 20 -i <HF III.mkv> -map 0:v:0 -map 0:a:0 -c copy x.mkv`，`ffprobe -show_entries stream_tags` 可见两种标签并存。
- 修复：`_tag_duration` 先取精确的 `DURATION`（大小写不敏感），没有时再取 `DURATION-<lang>`；取到的流时长与 `format.duration` 相差超过 `MEDIA["duration_tolerance_s"]` 时，以较小者为准并写入 `Probe.warnings`（不失败），`video_duration_source` 记录实际来源。时长校验本身（解码短于视频超过 1 s 失败）不变。
- 范围外：不改 `stream.duration` 优先级，不处理无视频流的输入。

## 完成标准

- `tests/test_media.py`：① 两种标签并存且 `DURATION-eng` 在前时取 `DURATION`；② 只有 `DURATION-<lang>` 时仍可用；③ 标签与 `format.duration` 矛盾时取较小者并告警；现有时长校验测试不变。
- 真实核对（不占 GPU）：用上面的流复制片段跑 `probe`，`video_duration_s` 约 23 s、无 `MediaError`。
- 模块页"已知缺陷"一句改为已修复并链接本票；规格 §2.2 时长校验段补一句标签优先级。

## 文件所有权

`kototoki/media.py`、`tests/test_media.py`、[配置、配方与媒体提取](../../../docs/architecture/modules/config-and-media.md)、规格 §2.2。

## Comments

- 2026-10-15 建票，依据最终验收 §3 与用户裁定。
- 2026-10-15 完成：`_tag_duration` 先取精确 `DURATION`（大小写不敏感）再取 `DURATION-<lang>`；`parse_probe` 在标签来源与 `format.duration` 相差超过 `duration_tolerance_s` 时取较小者并写 `Probe.warnings`。新增 3 个测试。真实核对：`-c copy` 剪出的 `copycut.mkv`（`DURATION-eng` 在前）`probe` 得 `video_duration_s` 23.148，无 `MediaError`。文档：模块页时长来源一句改为已修复，规格 §2.2 补来源优先级。
