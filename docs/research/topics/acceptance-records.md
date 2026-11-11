# 验收记录

状态：current（子索引；记录本身冻结）

条目格式：`[主题 日期](../acceptance/文件.md)：验收范围与未覆盖项`

- [专名一致性产品路径 2026-10-20](../acceptance/2026-10-20-name-consistency-product.md)：HF II／III 以 w0 整批运行 `python -m kototoki`（`[names]` 默认启用），STT 与翻译按身份跳过、Qwen3.8-27B-UD-IQ3_S 建表 2 部后重新发布；ADR-0014 四条判据：① 退出码 0、两表 `ok`、替换 55／32 个 cue；② `apply_table measure` 不一致率两部都下降（0.151 → 0.135、0.121 → 0.094，term 集合随替换缩小）；③ 研究脚本 `apply_table` 默认参数在产品表上的输出与发布 `zh.srt` 逐字节相同；④ 列出改动最密的 5 分钟片段待用户抽看。另记建表 tokens、秒数与显存峰值。未覆盖：改动逐行评审、表条目人工核对、x0 与其他作品、失败路径真实运行、建表可重复性
- [cross 模式 T6 产品路径验收 2026-10-19](../acceptance/2026-10-19-cross-asr-acceptance.md)：HF II／III 以 `engine = cross` 整批运行 `python -m kototoki`（含 align、translate），`kototoki_eval` 评 cross `align.json` 与同次运行的 `asr-w0.json`／`asr-x0.json`：两部 CER 都低于 w0（−0.88／−1.01 pp），合计 −0.95 pp 未达 1.0 pp 线；裁判与 T0 探针逐区间相同；asr 峰值 10030 MiB、墙钟 1211.6 s；翻译降级与回退 0；附 15 个改为 x0 区间的抽查。未覆盖：译文层收益、听音核对、表记改动对 CER 的拆分、剧集与新材料
- [cross 模式 T0 共驻显存探针 2026-10-19](../acceptance/2026-10-19-cross-coresidency-probe.md)：同一进程常驻产品 `WhisperAsr` 与 `QwenAsr`，HF II／III 全部窗口按 ①w0 转写 ②x0 转写 ③Whisper 分歧区间打分（d > −1 取 x0）运行，0.5 s 整卡采样与每阶段 torch 峰值：整卡峰值 10688 MiB，峰值＋1 GB ≤ 13.5 GB，判定共驻；DLL 与导入顺序无问题；PCM、VAD 与 13 个模型文件 SHA 核对通过。未覆盖：产品 worker 路径、重复性与桌面占用变化、三段式回退实测、CER 与听音核对
- [ffmpeg 升级到 9.0 维护分支 2026-10-19](../acceptance/2026-10-19-ffmpeg-9.0-upgrade.md)：BtbN `n9.0.2-28-g669f5ab083` 与旧 gyan.dev 构建用产品 extract 代码派生 HF II／III 的 16 kHz WAV，PCM SHA256 逐字节相同且等于基线，补偿记录相同；未重跑整片，只覆盖这两部的 FLAC 立体声音轨

- [双语字幕流水线 swr 回归重测 2026-10-16](../acceptance/2026-10-16-bilingual-pipeline-swr-regression.md)：改回 swr 后 HF II／III 各以 w0、x0 整批重跑 `python -m kototoki`：派生 WAV 与基线 PCM 逐字节一致，w0 CER 与 2026-10-05 基线逐项相同（16.81%／13.77%），x0 差 ≤0.15 个百分点；477 个翻译批次降级与回退 0；记录各阶段墙钟与显存峰值。未覆盖：翻译质量评分、失败路径重跑。
- [双语字幕流水线最终验收 2026-10-15](../acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)：同一评分器下产品 STT 与 2026-10-05 基线回归（CER 高 0.5–3.5 个百分点，根因为 soxr 派生 WAV 使 Pyannote 少保留语音，GPU 核实）；cue 规则统计与人工抽看；真实环境的无语音、5.1、损坏文件、强杀与残留锁、`force` 覆盖、确定性全部通过；发现 `DURATION-<lang>` 标签缺陷与 cue 内切词。未覆盖：翻译裁判评分、worker 退出码 2 真实路径、6.1／7.1 与广播 `.ts`。
- [双语字幕流水线两部整片 2026-10-14](../acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)：Heaven's Feel II／III 各以 w0、x0 整批运行 `python -m kototoki`，12 份 SRT 齐全、STT 零失败、降级与回退 0；记录各阶段墙钟、显存峰值、失败清单与磁盘占用。首轮翻译因桌面占显存低于启动阈值而失败，经进程内临时阈值 14700 MiB 续跑成功。未覆盖：质量与基线回归、真实降级路径、GPU 阶段中途中断、强杀与其他声道布局。
