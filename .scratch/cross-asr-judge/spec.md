# 产品 STT 增加 cross 模式：x0 转写＋Whisper 交叉打分裁判

Status: ready-for-agent

权威设计见 [docs/changes/cross-asr-judge.md](../../docs/changes/cross-asr-judge.md)（本次增量说明），本目录只跟踪票据执行状态。
用户 2026-10-19 裁定：按该文档实施到生产代码，主 agent 调度子 agent 实现并审查。

票据：01 T0 共驻显存探针 · 02 T1 文档先行 · 03 T2 裁判纯逻辑 · 04 T3 Whisper 打分 · 05 T4 配方配置计划产物 · 06 T5 worker cross 路径 · 07 T6 产品路径验收 · 08 T7 收口。
依赖：06 ← 03、04、05；07 ← 06、01；08 ← 07。01–05 并行。
