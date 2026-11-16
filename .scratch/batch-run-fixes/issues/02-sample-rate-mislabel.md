# 02 音轨采样率标错

Status: resolved
Type: task
Blocked by: —

## 现象

10 个文件在抽取时出现几百秒的净补齐或丢弃（`Resampler padded/discarded ... s`），一开始被当作"时间戳跳变、字幕错位几分钟"。复查后：

- 派生 WAV 与视频时长全部一致（差 ≤0.5 s），整体时间轴没错。
- 补偿不是一次大跳，而是每 1.3–1.5 s 一次、每次约 0.1 s，共三四千次（`extract.log` 里的 `adding N audio samples of silence` / `discarding N audio samples`，单次约 4500–5600 样本）。
- 实际样本数 ÷ 声明采样率 ÷ 视频时长 = **0.919（= 44100/48000）或 1.088（= 48000/44100）**，10 个文件全部落在这两个值上（0.9190–0.9202、1.0871–1.0884）。

| 类型 | 文件数 | 解码结果 |
| --- | --- | --- |
| 声明 48 kHz、实为 44.1 kHz | 7 | 语音快约 9%、音调偏高，每 ~1.5 s 插 ~0.1 s 静音；样本没丢 |
| 声明 44.1 kHz、实为 48 kHz | 3 | 语音慢约 9%，每 ~1.3 s 丢 ~0.1 s，约 8% 的语音被丢弃 |

佐证：同一作品的正常版本有 384159744 样本 ÷ 48000 = 8003 s；标错版本 353401856 样本，按 48000 算 7363 s、按 44100 算 8014 s，与其视频 8011 s 吻合。

## 原因

- `derive_pcm16k` 用 `aresample=async=1:first_pts=0` 让样本对齐容器时间戳（`media.py` 模块说明：本模块唯一定义时间轴零点）。容器时间戳按真实时长走，解码器却按 AAC 配置里错误的采样率产出样本，两者每帧都差约 9%，swr 只能靠频繁补静音或丢样本硬对齐。
- 目前只在 `parse_compensation` 里记 `net_padding_s` 并在超过阈值时告警，不判断成因，也不纠正。

## 影响

- 7 个"补静音"文件：识别输入是变速变调、被切碎的语音。同作品对照，字幕条数少 5%–12%。
- 3 个"丢样本"文件：约 8% 的语音直接没进识别，同作品对照字幕条数少约 6%。
- 字幕时间整体基本对，所以不容易被发现；10 个里有 9 个是文件名带 `[ZH]` 的二次封装版本。

## 候选方向（待讨论）

- 检测：抽取后计算 `input_samples / 声明采样率 / 视频时长`，落在 44100/48000 或 48000/44100 附近（容差待定）即判为采样率标错。
- 纠正：按真实采样率重新解码（例如在 `aresample` 前加 `asetrate=<真实值>`，或用 `-ar` 覆盖解码器参数），再走 async 对齐；要确认纠正后补偿次数接近 0。
- 不纠正时的退路：判失败，或在 summary 里单列。
- 抽取配方变化 → 出新版本；产物 `probe.json` 可能要加字段（声明值、推断值、是否纠正）。
- 是否推广到其他比值（如 32000/48000）由讨论定，目前只观察到这两种。

## 证据

- 封存目录 `D:\jav_best_copy_work\3-recheck\`（10 个，含 `audio.m4a` 原始音轨，可离线复现）；对照用的正常版本在 `.local/work/jav_best_copy-15fff3e12253/` 的 work_id `1e5f579efb5c`、`37fca0aba693`、`9b5648ab37ce`、`b65f1ab17a07`。
- `probe.json` 的 `input_samples`、`net_padding_s`；`_samples/extract-log-sample.txt` 的补偿事件样例。
- 台账"2026-11-16 复查：A1/A2 的结论修正"。

## Comments

### 2026-11-16 方向已定（用户拍板，均按建议）

讨论前的离线核实（封存的 `audio.m4a`，纯 CPU）：
- ffprobe 元数据就能看出真实采样率：`nb_frames × 1024 ÷ 流 duration` ≈ 44115（声明 48000）或 ≈ 47940（声明 44100）。时间基与声明值一致，是帧的时长按真实速率走。
- 候选方向里的"`aresample` 前加 `asetrate`"直接用是错的：600 s 片段被拉成 653 s，补偿次数不降。`asetrate` 会按比例改写时间戳。改成 `asetrate=<真实值>,asetpts=PTS*<真实值>/<声明值>` 后时长正确、补偿从 372／122 次降到 11／8 次。

决定：
1. **自动纠正**，不判失败、不只告警。
2. **在探测阶段检测**：只看 ffprobe 元数据（AAC-LC 且有 `nb_frames` 与流时长），一次解码完成纠正；元数据缺失时不检测，不加解码后兜底。
3. **只认 44100↔48000 这一对**，不推广到其他比例。
4. **容差** ±1%（实测 ÷ 真实值）。
5. 本批已产出的 10 个文件**不重跑**。

`MEDIA` 出 v2；`probe.json` 的音轨记录加 `measured_sample_rate`、`corrected_sample_rate`，纠正时记一条告警；`net_padding_s` 按纠正后的采样率算。

## Answer

2026-11-16 已实现：
- `recipes.MEDIA` → `media-pcm16k-v2`，新增 `sample_rate_correction`（两对、±1%、滤镜模板）。已有工作目录下次运行会重新探测与抽取（只占 CPU）；没有纠正的音轨命令与 v1 逐字相同，PCM 不变，VAD 及下游身份仍当前。
- `media.sample_rate_check`；`AudioTrack.measured_sample_rate`／`corrected_sample_rate`（进 `probe.json`）；`parse_probe` 对所选音轨记告警；`derive_filter` 在 `aresample=async` 前插纠正滤镜；`parse_compensation` 按纠正值算净补偿。
- 测试：`tests/core/test_media.py` `SampleRateCheckTests`（两个方向、正常与容差外、非 AAC-LC 与元数据缺失、探测记录与告警、滤镜位置、净补偿）；`tests/core/test_recipes.py` 钉住 v2 hash、纠正规则进 hash。
- 文档：`docs/architecture/modules/config-and-media.md`、技术设计时间零点一条。
- 离线验证（产品的 `parse_probe` + `derive_pcm16k`，对封存的 10 个 `audio.m4a` 完整解码）：10 个全部命中；派生时长与视频差 ≤0.06 s；净补偿从 455–818 s 降到 0.01–11.8 s，swr 补偿事件从每片三四千次降到 1–42 次；同作品正常版本 2 个未命中，补偿 0。残留来自容器时间戳与名义采样率约 0.01%–0.16% 的偏差（实测 44110–44169、47940–48005）。
- 自动检查：`just test` 通过。未验证：纠正后的识别质量（要跑 GPU，用户决定不重跑这 10 个）；Matroska 等不给 `nb_frames` 的容器。
