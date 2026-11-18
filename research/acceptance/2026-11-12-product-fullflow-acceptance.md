# 2026-11-12 产品全流程验收（强制走 ASR）

## 时间
2026-11-12，整批约 28 分钟；同日追加 ADR-0026 验证与内嵌字幕补漏。代码为运行日志补缺票据结题后的 main，首轮未改任何代码、参数、提示或配方。

## 对象
产品 `python -m kototoki` 在 w0 路径上的整片工程行为：能否从头跑通、各阶段与中间产物是否齐全自洽、日志里有无拒答、截断、降级、重启、残留进程或锁。追加部分验证 [ADR-0026](../../docs/adr/0026-names-output-and-prompt-budget.md)（`q3-names-v2`，建表输出上限与提示预算放宽）与内嵌字幕选轨修复（[ADR-0024](../../docs/adr/0024-embedded-japanese-subtitles.md)）。不评字幕质量。

## 环境与版本
Python 3.13、torch 2.11.0+cu128；ASR 为产品 w0（`w0-faster-whisper-large-v3-guard-v2`，含复读守卫）；翻译与建表为 Q3 规则：Strata 0.2.12 上的 Qwen3.8-Flash-Next IQ3_S，不加参数启动（DFlash2，专家区放内存）；RTX 5080。配置：`[input] use_embedded_subtitles = false`（两部 mkv 都带日文文本字幕轨，不关会跳过 STT），`stt.engine = "w0"`，其余默认。

## 测试
- 素材：2 部日语电影整片（HF II／III）；追加：Black Panther（内嵌字幕路径）。原计划另加两集剧集，来源（网络盘）不可用，经用户同意只跑电影。
- 入口：整批 `python -m kototoki`；再重跑原命令（应全跳过）；移走 HF II 字幕后再跑（应只重发布）。
- 判据：退出码；各阶段失败计数；翻译批次的 `finish_reason` 与降级回退计数；中间产物可解析且带身份、时间轴无偏移；最终双语 SRT 严格解析、两行、日文行与 `ja.srt` 逐条相同；GPU 锁与 Strata 正常释放。

## 结果
- 退出码 0，2 个文件全部发布，0 失败、0 回退 cue。翻译 296 批全部 `stop`，降级 0、回退 0、Strata 重启 0，无拒答；结束后锁释放、Strata `stop ok`、显存回到空闲。
- 阶段（HF II／III）：vad 195／207 窗；asr 0 失败，HF III 第 51 窗被复读守卫折叠（对应 [ADR-0023](../../docs/adr/0023-asr-repeat-guard.md)）；align 各 1 个极短窗口 CTC 失败，回退文字插值；cue 1099／1217，0 未渲染字符；names 建表 HF II 第 1 次成功、HF III 第 3 次成功；asr 307.9 s、names 238.6 s（含 Strata 启动）、translate 905.7 s，总计 1686 s。Strata 会话峰值显存 15955 MiB、内存 61.0 GiB。
- 非语义产物校验全部通过；续跑成立（全跳过；移走字幕后只重发布，未启动 Strata，重发布结果与原字幕 SHA256 相同）。
- 观察：HF III 建表前两次在 8192 completion token 处被截断，不是复读循环，而是模型列实体过多；同 seed 建表结果不可重复（DFlash2 推测解码）。
- ADR-0026 验证：HF III 在 16384 上限下仍有两次无限罗列截断（回复列了 135 个实体、大量低价值项），第 4 次 11K token 成功（解析器丢弃超 schema 条数的 101 条后剩 40 条）；放宽救回一次合格表，但失败成本翻倍。用户裁定保留 `max_tokens` 16384。
- Black Panther：首跑选中了标题标 forced 的字幕轨（disposition 为 0，forced 只写在标题里），修复后配方升为 `embedded-ja-subtitle-v2`；重跑选中完整日文轨（1655 条），建表提示约 20K token（旧预算下会写空表）第 2 次成功，翻译 207 批降级与回退 0，非语义校验通过。

## 结论
产品整片全流程工程行为通过，续跑与锁行为正常；提示预算放宽使对白密的长片能正常建表，输出上限放宽收效有限。未覆盖：剧集、x0 与 cross 引擎、字幕质量与基线回归、失败／中断／强杀路径。
