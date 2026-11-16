# 04 抽取质量门：解码远超视频时长、近乎全静音

Status: resolved
Type: task
Blocked by: 03（软依赖）

## 现象

两类明显坏掉的抽取结果被当作成功，一路跑完 VAD、识别、对齐、专名、翻译：

1. **解码远超视频时长（5 个）**：时间戳严重断裂，`aresample=async=1` 按时间戳补出数小时静音。

   | work_id | 净补齐 | 派生 WAV | VAD 窗口 | 最终字幕条数 |
   | --- | --- | --- | --- | --- |
   | 7c97f3c8abd1 | +116576 s | 34.3 h | 19 | 66 |
   | d600cc8e24d9 | +74380 s | 22.7 h | 29 | 100 |
   | 525791e56c33 | +20730 s | 7.6 h | 8 | 46 |
   | 0dd24671c4f4 | +19887 s | 7.4 h | 3 | 18 |
   | 7eade76a0087 | +7502 s | 4.4 h | 264 | 1235（跳变后整体错位约 2 h） |

   正常文件 VAD 窗口约 150–400、字幕 ≥337 条。实际样本数与时长之比 0.06–0.53，与 02 的采样率问题不是一类。

2. **近乎全静音（1 个，work_id 6a3f71d9853f）**：派生 WAV 3 h 58 m 中 14237 s 是静音，平均 −56 dB；VAD 1 个窗口，最终 2 条字幕。真实解码错误只有 60 条，静音不是解码造成的，疑似源音频本身近乎无声。

## 原因

- `check_duration`（`media.py` 约 327–340 行）：解码**短于**参照（视频输入）判失败；**长于**参照"一律只返回告警"。补出 30 多小时也只是一条 WARNING。
- 对派生 WAV 的内容（静音占比、音量）没有任何检查。
- VAD 窗口数、cue 条数异常低也没有告警。

## 影响

- 每个坏文件都白跑 GPU 阶段（34 h 的 WAV 识别与对齐耗时可观），最后产出近乎空的字幕，汇总里显示为"成功"。
- 用户只能靠人工翻日志才能发现。

## 候选方向（待讨论）

- 时长：解码时长超过视频时长一定比例或绝对值（阈值待定）时判失败（或新增"可疑"状态）；与 02 的采样率检测区分——02 的文件 WAV 与视频等长。
- 静音：抽取后测静音占比或整体音量（ffmpeg `silencedetect`/`volumedetect`，或直接在 WAV 上算 RMS），超阈值判失败或告警。
- 也可以在 VAD 之后用"窗口数 / 时长"兜底。
- 判失败还是只告警、汇总里是否新增一类，需要讨论；失败判定变化要先改模块页与技术设计。

## 证据

- 封存目录 `D:\jav_best_copy_work\2-unusable\`（6 个完整工作目录 + `_samples/`）。
- 台账 §A1（严重组）、§A2 中关于静音文件的测量方法：`ffmpeg -i audio-16k.wav -af silencedetect=n=-50dB:d=5,volumedetect -f null -`。

## Comments

### 2026-11-17 方向已定（用户拍板，均按建议）

讨论前的离线核实（读现有产物，纯 CPU）：212 个正常文件解码时长 − 视频时长最大 +60 s（比值 1.009，净补偿≈0，是音轨本身比视频长）；5 个断裂文件最小 +7502 s（比值约 1.9）。VAD 语音时长 ÷ 参照时长：正常文件中位 0.41、最低 0.048；URE-025 为 0.000，断裂组 0.004–0.041。另外，坏文件 VAD 窗口只有 1–29 个，识别与对齐实际耗时不大，主要危害是"汇总显示成功、字幕不可用"。

决定：
1. **时长超长判失败**：视频输入解码时长 > 参照时长 × 1.5 时 `MediaError`，不留下 `audio-16k.wav`；不新增"可疑"状态，不提供补救解码路径（断裂文件实际样本只够视频时长的 6%–53%）。
2. **阈值**：相对阈值 1.5 倍，不另设绝对值。
3. **音频输入**仍只告警（时长可能是估算值，ADR-0020）。
4. **阈值不进 `recipes.MEDIA`**，作为 `media` 模块常量；`MEDIA` 不升版本，已有工作目录不重新抽取。
5. **静音门放在 VAD 之后**：编排在 asr 之前检查 `vad.json` 的 `accounting.speech_samples` ÷ 16000 ÷ 参照时长，< 1% 记该文件 vad 阶段失败。VAD 窗口为空的"无语音"路径不变（照常发布零条目字幕）。
6. **不按解码错误数判失败**，保持 03 的告警。
7. **不回溯**：已有产物不重判，封存的 6 个不重跑。

## Answer

2026-11-17 已实现：
- `media.check_duration`：视频输入解码时长 > 参照 × `MAX_OVERLONG_RATIO`（1.5，模块常量，不进 `MEDIA`）时抛 `MediaError`（消息 `...; more than 1.5x, treating the timestamps as broken`），不留下 `audio-16k.wav`；1 s 容差到 1.5 倍之间仍只告警；音频输入只告警。`MEDIA` 不变（仍 `media-pcm16k-v2`）。
- `job.speech_gate`：计划停在 asr 的文件，跑 asr 前读 `vad.json` 的 `accounting.speech_samples`，语音不足参照时长 1%（`MIN_SPEECH_RATIO`）记 `vad` 阶段失败（`TooLittleSpeech`，写 `failure.json`，不带 traceback）。`vad.json` 保留，重跑时再判；VAD 窗口为空的无语音路径不变。
- 文档：`docs/architecture/modules/config-and-media.md`（时长校验）、`docs/architecture/modules/batch-orchestration.md`（"近乎无声"一段）、技术设计 §失败处理加一条。两页模块页为守住 12000 字预算顺带压缩了几处措辞，内容不变。
- 测试：`tests/core/test_media.py` 超长判失败、音频输入只告警；`tests/core/test_job.py` 近乎无声在 asr 前失败、重跑仍失败且不重跑 vad（`tests/fake_worker.py` 新增 vad 动作 `quiet`，伪 VAD 产物带 `accounting.speech_samples`）；`tests/full/test_media_ffmpeg.py` 真实 ffmpeg：音频比视频长 1.4 倍只告警、长 1.67 倍判失败且不留 WAV。
- 自动检查：`just test`（768）、`just check`、`just docs-check`、`just test-full`（20）通过。
- 未验证：没有对封存的 6 个坏文件重跑产品（决定 7 不回溯）；阈值只依据本批 212 个正常文件与 6 个坏文件的现有产物。
- 已知取舍：VAD 完全为空的文件照常发布零条目字幕，而语音不足 1% 的文件判失败，两者处理不同；这是有意保留的现有无语音路径。

