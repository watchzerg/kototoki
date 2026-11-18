# 2026-10-19 审计发现的后续处理

Status: needs-triage
建票：2026-11-18（用户要求把审计报告中尚未处理的发现转成票据，之后再分析是否需要修复）。

## 依据

[2026-10-19 架构与流程评估](2026-10-19-report.md)。报告 §3 第 1 项（纯工程小修）已由[票据 01](issues/01-small-fixes.md) 完成；A-1（w0 重复／幻觉）已由 ADR-0023 解决；C-4 只是管线预算的观察，没有问题可修，不建票。

## 票据

其余发现每条一张，状态都是 `needs-triage`。报告基于 2026-10-19 的代码和 llama-server 时期的翻译，分诊时先对照当前代码确认问题是否还在。

| 票据 | 发现 | 类型 |
| --- | --- | --- |
| [02](issues/02-a2-in-window-silence.md) | A-2 窗内长静音疑有漏转 | research |
| [03](issues/03-a4-timeline-edge-tests.md) | A-4 时间轴边界缺 full 测试 | task |
| [04](issues/04-a5-cue-start-accuracy.md) | A-5 cue 起点精度未实测 | research |
| [05](issues/05-a6-identity-code-versions.md) | A-6 阶段身份不含代码与依赖版本 | task |
| [06](issues/06-a7-cue-boundaries.md) | A-7 cue 边界小问题 | task |
| [07](issues/07-a8-empty-window-count.md) | A-8 空文字窗口不计数 | task |
| [08](issues/08-a9-wav-read-peak-memory.md) | A-9 读 WAV 内存峰值 | task |
| [09](issues/09-a10-wav-content-check.md) | A-10 跳过 extract 时不核对 WAV | task |
| [10](issues/10-b4-worker-start-event.md) | B-4 worker 启动崩溃被当成文件问题 | task |
| [11](issues/11-b5-work-dir-size.md) | B-5 工作目录体积 | task |
| [12](issues/12-b7-subprocess-timeouts.md) | B-7 子进程无超时 | task |
| [13](issues/13-b8-worker-stdout-noise.md) | B-8 worker 非 JSON 行被丢弃 | task |
| [14](issues/14-b11-case-only-rename.md) | B-11 只改大小写整链重算 | task |
| [15](issues/15-b12-force-reminder.md) | B-12 `force` 持续生效 | task |
| [16](issues/16-b15-test-gaps.md) | B-15 测试缺口 | task |
| [17](issues/17-c3-translate-time-budget.md) | C-3 翻译耗时与提速项 | research |
| [18](issues/18-c7-fixed-port.md) | C-7 端口固定 8080 | task |
| [19](issues/19-c8-engine-identity.md) | C-8 翻译身份不含引擎版本 | task |
| [20](issues/20-c9-srt-consumer-quality.md) | C-9 SRT 消费侧质量 | research |
| [21](issues/21-c1-c2-vram-headroom.md) | C-1、C-2 翻译显存余量与慢化 | research |

## 进度

## Comments
