# 专名一致性进产品：建表＋生成后替换接入双语字幕流水线

Status: resolved

权威设计见 [docs/changes/name-consistency-product.md](../../docs/changes/name-consistency-product.md)（本次增量说明），本目录只跟踪票据执行状态。用户 2026-10-19 裁定：直接集成到产品代码，验收只看总体正向，其余按设计稿推荐；同日按 review 缩减票据 01、02、05、08（见设计稿 §6）。

来源：[ADR-0013](../../docs/adr/0013-name-consistency-closed.md) 冻结的最佳已知配置；进产品由票据 01 的 ADR-0014 记录（替代 ADR-0013 第 3 条）。研究台账 `.scratch/name-consistency/`（只读）。

票据：01 ADR 与模块边界 · 02 共享 llama-server 模块 · 03 建表模块 · 04 替换纯函数 · 05 配置／清单／计划接入 · 06 编排接入 · 07 smoke · 08 产品路径验收 · 09 收口。
依赖：02–05 ← 01；06 ← 02、03、04、05；07 ← 06；08 ← 06、07；09 ← 08。02–05 并行，各用独立 worktree；07 与 08 共用一次 GPU 批准。
