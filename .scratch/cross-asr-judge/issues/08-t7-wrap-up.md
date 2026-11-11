# T7 收口

Status: done（文档部分；代码修复与提交由主 agent 处理）
Type: task
依赖：07

## 内容

ADR-0012 状态按验收改 accepted／rejected；模块页去掉实施中标注并记录变更来源；`just docs-check` 交集无新增报错；吸收并删除 changes 文档。

## 文件所有权

文档

## 完成标准

当前正文不再引用 changes 文档。

## Comments

- 2026-10-19 文档部分完成：用户裁定采用 `cross` 为可选引擎、默认保持 `w0`（合计 −0.95 pp，低于预设 1.0 pp 验收线）。ADR-0012 改为已接受，新增"验收与裁定"一节并更新代价与后续。增量说明 `docs/changes/cross-asr-judge.md` 已吸收后删除：裁判算法、守卫、日志行、审计产物字段、显存与墙钟实测、x0 空白清理 → `docs/architecture/modules/stt-workers.md`；审计产物名与"不参与 is_current" → `artifact-contract.md`；`stt.engine` 取值、`CROSS` 配方与 hash `ab9f4532…`、`x0_text_cleaning` → `config-and-media.md`；asr 身份与 13 个模型文件 → `stage-plan.md`；接缝、judge 基础层、共驻例外 → `module-boundaries.md`；用户可见行为与实测 → `docs/specs/bilingual-subtitle-pipeline.md` §1.1／§2／§3.2／§4／§13；术语 → `GLOSSARY.md`；`docs/INDEX.md` 去掉 `changes/` 行并恢复"按需创建"。所有"实施中"标记与指向 changes 文档的链接已移除（两份验收记录的范围行链接改指 ADR-0012）。

- 2026-10-19 主 agent：代码部分完成。三个 worker 的 logger 固定为 `kototoki.workers.<stage>`（`-m` 运行时 INFO 行曾被丢弃），新增 `WorkerLoggerNameTest` 两项；`telemetry_run.py` 阶段正则兼容带时间戳与级别的新日志格式。core 455 项通过，docs-check 44 条与改动前一致。随本票一并提交。
