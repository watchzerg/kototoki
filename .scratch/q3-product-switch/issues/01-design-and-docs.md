# 01 设计与文档先行：ADR-0022、决定索引、模块边界与模块页、技术设计

Status: resolved
Type: task
Blocked by: —

范围、终点与门见计划 §4 第 1 张票据（docs/plans/product-names-on-strata.md）。

- 不写代码。
- ADR-0022 替代 ADR-0014 第 3 点的建表模型与 llama-server 部分、ADR-0019 第 2 点、ADR-0007 第 3 点剩下的建表引擎部分；ADR-0021 只追加状态行。
- 同一提交改：决定索引（当前有效决定、未关闭项、演进链、全部 ADR）、AGENTS.md 产品句、GLOSSARY Q3 词条、README、模块边界、模块页（专名一致性、翻译子系统、批次编排、阶段计划、配置与媒体）、架构总览、技术设计规格。

## 执行记录

- 2026-11-09：新增 `docs/adr/0022-product-names-on-strata.md`；改决定索引（当前有效决定 4 行、未关闭项关闭、演进链两条、全部 ADR 表、编号起点 0023）；ADR-0021／0019／0014／0007 只追加状态行；AGENTS.md 产品句与表行、GLOSSARY（Q0、Q3）、README、调研索引时间线；模块边界（llama_server 行拆成 llama_server 与 strata 两行、names 行、依赖方向、并发与生命周期、失败分级、锁、日志、接缝）；模块页：专名一致性整页重写，翻译子系统、批次编排、阶段计划、配置与媒体按点改；架构总览（引言、模块地图两行、mermaid、装配表）；技术设计规格 17 处＋变更记录。
- 设计定稿（写进 ADR-0022 与模块页，代码票据照此实现）：中间层 `kototoki/strata.py`（`StrataServer`、`StrataRefused`、身份常量、共享 `Session(config, *, on_server_pid, server_factory, client_factory)`，`<work root>/strata-sessions/`，日志前缀 `[strata]`，整批最多启动 3 次）；`kototoki/translate/strata.py` 保留为再导出（研究侧 `translation_v3/strata.py`、`v13.py` 导入它，`experiments/` 不改）；配方名 `q3-names-v1`；names 交换目录 `count-NN`／`chat-NN`；`kototoki.names` 不再导出 `Session`，`kototoki.translate` 也不再导出 `Session`。
- `docs-check`：44 条，全部是 main 上已有的冻结外链，无新增。

## Answer

完成：ADR-0022 与全部文档先行改完，未改代码。接口形状以模块边界与模块页为准，票据 02–05 据此实现。
