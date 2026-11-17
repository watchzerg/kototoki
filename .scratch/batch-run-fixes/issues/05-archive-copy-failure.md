# 05 归档音轨流复制失败导致整片失败

Status: resolved
Type: task
Blocked by: —

## 现象

1 个文件（work_id 084410474fc8）在抽取阶段失败，`failure.json`：

```
ffmpeg stream copy failed (3199971767): [aac_adtstoasc @ ...] Error parsing ADTS frame header!
[ipod @ ...] Error applying bitstream filters to an output packet for stream #0: Invalid data found when processing input
...
```

该音轨有 3 个损坏的 AAC 包。解码路径能跳过坏包（对源文件 `-f null` 解码退出码 0），模型输入本来可以正常生成。

## 原因

- 抽取先 `extract_original`（`media.py` 约 383–395 行）用 `-c:a copy` 把原始音轨原样复制为 `audio.<ext>`，失败即抛 `MediaError`，整片判失败。
- 技术设计 §2.1 对 `audio.<ext>` 的定位是"只作归档"，模型输入 `audio-16k.wav` 直接从输入容器解码，并不依赖它。
- 复制到 m4a 时经过 `aac_adtstoasc` 比特流过滤器，坏包在这里无法容忍。

## 影响

- 一个可以出字幕的文件整片无字幕。

## 候选方向（待讨论）

- 流复制失败时降级为 WARNING，`audio_copy` 记为空，继续派生 WAV 与后续阶段。
- 或换不需要 `aac_adtstoasc` 的容器（如 ADTS `.aac`）重试一次。
- 改变产物契约（`audio_copy` 可为空、续跑与身份核对如何处理），需先改技术设计与模块页。

## 证据

- `D:\jav_best_copy_work\1-extract-failed\JUFD-732__084410474fc8\`（`failure.json`、`_samples/run-log-excerpt.txt`）。
- 台账 §C2。

## Comments

- 2026-11-17 讨论定案：不做降级、不换容器重试，而是**取消归档流复制**（用户裁定）。副本没有任何阶段读取；ADR-0020 后源文件留在原地、工作目录不交付，副本只是重复数据，还多读一遍源文件。另一方案"先复制到 `.mka` 再从副本派生"会改变 PCM 身份、需要新 `MEDIA` 版本，且坏包仍可能在封装时失败，未采纳。落为 [ADR-0027](../../../docs/adr/0027-no-original-audio-copy.md)。
- 2026-11-17 已实现：删除 `extract_original`、`copy_command`、`CONTAINERS`、`AUDIO_COPY_STEM` 与 `Extract.audio_copy`；派生命令与 `MEDIA` hash 不变。`just test`、`just test-full` 通过。未验证：JUFD-732 本片重跑（源盘不在线）。
