# 03 文档同步（计划 §3 第 6 项）

Status: resolved
Type: task
Blocked by: 02

范围与终点见计划 §4 票据 03（docs/plans/asr-repeat-guard.md）。ADR-0023 状态行里的验收结果在 04 之后补。

## 执行记录

- 2026-11-11：技术设计（§1.1 w0 行、§4 `asr.json` 行、§6 新增"w0 整窗复读"一条、变更记录）；STT worker 模块页（状态行、身份表、`asr_traces`、新增"w0 复读守卫"一节、cross 的三步／守卫／日志行、测试清单、代码清单、变更记录）；产物契约（失败原因取值、`asr_traces[].guard`、变更记录）；阶段计划页（W0 配方换 id 的说明）；架构总览分层图基础层加 `judge · guard`；文档索引的计划状态。
- ADR-0023 状态行、决定索引与调研索引时间线放到 04：要写验收结果，且验收不过时不能写成"已实现并验收"。
- `just docs-check`：仍只有 main 上已有的冻结外链，本次改动的文件无新增条目。`<待填` 标记只剩 `docs/development/workflow.md` 的发布流程一处，时机未到，保留。

## Answer

完成（ADR 状态行与决定索引除外，归 04 收尾）。
