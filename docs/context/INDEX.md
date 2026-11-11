# 执行台账索引

状态：current（目录内其余文件全部是冻结证据，只读）

本目录是冻结的执行台账，记录各任务／轮次当时的执行过程。**不要整篇读取**：先用 `grep -n '^#' <file>` 列出标题，再按行号区间只读需要的节。台账里的“当前”“进行中”“下一步”只描述写作当时的状态；其中的作业不再恢复，接续旧任务前先对照仓库核实实际状态。第二轮（v2）已停止并冻结，先验只取 [v1/v2 教训](../research/2026-10-10-hy30-flow-v1-v2-lessons.md)，不从台账里另取结论。

| 文件 | 字符数 | 标题数 | 用途 | 对应计划／报告 |
| --- | --- | --- | --- | --- |
| [2026-10-04-demo-execution.md](2026-10-04-demo-execution.md) | 11875 | 11 | 本地 STT demo 首轮与两片复核的执行记录。 | [选型计划](../plans/local-stt-demo-selection.md)、[实施结论](../research/2026-10-04-stt-demo-conclusions.md) |
| [2026-10-05-vad-comparison-execution.md](2026-10-05-vad-comparison-execution.md) | 3086 | 6 | W0／X0 四种 VAD 十组合实验的执行状态。 | [VAD 对照计划](../plans/vad-baseline-comparison.md)、[比较报告](../research/2026-10-05-vad-baseline-comparison.md) |
| [2026-10-06-hy30-four-execution.md](2026-10-06-hy30-four-execution.md) | 59272 | 11 | Hy-MT2 30B-A3B 四量化大规模比较的接跑与核验记录。 | [四量化方案](../plans/hy30-four-quantization-comparison.md)、[结果报告](../research/2026-10-07-hy30-four-quantization-results.md) |
| [2026-10-06-translation-comparison-execution.md](2026-10-06-translation-comparison-execution.md) | 6653 | 8 | 三个翻译模型家族五个版本评估的接跑记录。 | [评估计划](../plans/translation-model-comparison.md)、[结果报告](../research/2026-10-06-translation-model-comparison-results.md) |
| [2026-10-07-hy30-flow-exploration.md](2026-10-07-hy30-flow-exploration.md) | 7345 | 6 | Hy30 完整字幕流程第一轮探索的台账与接跑。 | [模式优化计划](../plans/hy-mt2-translation-mode-optimization.md)、[最终报告](../research/2026-10-07-hy30-flow-optimization-results.md) |
| [2026-10-08-hy30-flow-exploration-v2.md](2026-10-08-hy30-flow-exploration-v2.md) | 259807 | 66 | Hy30 字幕流程第二轮（v2）探索的台账与接跑，已停止。 | [v2 计划](../plans/hy-mt2-translation-flow-exploration-v2.md)、[v1/v2 教训](../research/2026-10-10-hy30-flow-v1-v2-lessons.md) |
| [2026-10-10-hy30-flow-exploration-v3.md](2026-10-10-hy30-flow-exploration-v3.md) | 17038 | 30 | Hy30 字幕流程第三轮（v3）探索的台账。 | [v3 计划](../plans/hy-mt2-translation-flow-exploration-v3.md)、[v3 报告](../research/2026-10-10-hy30-flow-v3-report.md) |
| [2026-10-11-hy30-flow-exploration-v4.md](2026-10-11-hy30-flow-exploration-v4.md) | 20750 | 32 | Hy30 字幕流程第四轮（v4）探索的台账。 | [v4 计划](../plans/hy-mt2-translation-flow-exploration-v4.md)、[v4 报告](../research/2026-10-11-hy30-flow-v4-report.md) |

字符数为 `len(text)`（UTF-8 解码），标题数不含代码块内的 `#` 行。

## 节地图

### 2026-10-06-hy30-four-execution.md（346 行，11 个标题）

- L1–170：Hy30 四量化大规模比较接跑记录
- L171–188：已核验事实
- L189–196：执行与恢复约束
- L197–200：尚未完成
- L201–300：最新观测与待接续修复
- L301–307：2026-10-06 17:16 UTC 参考协调阶段
- L308–314：2026-10-06 17:37 UTC 首批裁决及替补
- L315–321：2026-10-06 17:44 UTC 已确认的未来冻结检查误拦截
- L322–328：2026-10-06 17:50 UTC 替补第二轮与未应用修复
- L329–332：2026-10-06 18:05 UTC 第二批32窗口替补
- L333–346：正式运行轻量观测

### 2026-10-08-hy30-flow-exploration-v2.md（1315 行，66 个标题）

标题过多，只列 `##` 级；`###` 级为按时间追加的小节，用 `grep -n '^###' <file>` 查看。

- L9–41：2026-10-09 切换 agent 接跑入口（最新，覆盖下方历史状态）（含 3 个 `###` 小节）
- L42–45：此前累积摘要（含 0 个 `###` 小节）
- L46–1269：本次执行进度（含 55 个 `###` 小节）
- L1270–1278：已完成的准备审计（含 0 个 `###` 小节）
- L1279–1297：初始探索台账（含 0 个 `###` 小节）
- L1298–1306：执行前待冻结项目（含 0 个 `###` 小节）
- L1307–1315：接跑边界（含 0 个 `###` 小节）
- 其中 L48–1269 的“本次执行进度”是按时间追加的流水账（L9 起的“切换 agent 接跑入口”是最后一次交接说明，也只描述 2026-10-09 当时的状态）。
