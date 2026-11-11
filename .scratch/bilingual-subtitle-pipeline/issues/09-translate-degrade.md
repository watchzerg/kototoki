# 09 翻译降级与报告

Status: done
Type: task
Blocked by: 05

## 范围

- 架构（[目标架构](../../../docs/architecture/bilingual-pipeline-architecture.md)"翻译子系统"行）：降级全部在子系统内部完成，`translate_document` 的对外接口不变，编排只从 `TranslateResult` 读 report 与回退计数。
- 产品配方 `b10-joint-degrade-v1`（追加到 `kototoki/translate/recipes.py`，05 完成后动手）：字段与 b10-joint 相同，仅 `overflow` 策略改为 `degrade-10-5-1-keep-source`；另算 `recipe_hash`；测试固定"提示、grammar、采样与请求字节与 b10-joint 完全相同"，并保留 05 的 v3 hash 钉子。
- 降级流程：批次终态失败（输出上限、grammar、上下文超限，经 v3 的尝试次数后）→ 拆成两个 5 条批次（各取前后 1 条只读邻文，seed 不变）→ 仍失败的拆单条 → 单条仍失败则译文 = 日文原文。子批次 ID `父ID.a`／`父ID.b`，场景文件记录降级树与各级尝试。
- 终态语义：回退为日文的 cue 对该配方 hash 与 seed 是终态，重跑同一命令不再尝试；要重试须改 seed（2026-10-14 用户裁定删去 `force = true` 重试，见 Comments）。
- `translate/report.json`：降级批次、回退 cue ID、原因、尝试次数；控制台汇总条数；`published.json` 记录回退 cue 数。

## 完成标准

- 伪客户端测试（`tests/`）：三级降级、单条回退、续跑时识别已降级完成的批次与回退终态、报告内容、`published.json` 回退计数。
- 一部电影真实运行记录降级次数。

## 文件所有权

`kototoki/translate/degrade.py`、`kototoki/translate/recipes.py` 中追加的产品配方（文件本身由 05 建）、对应测试。

## Comments

- 2026-10-13 建票，依据规格 §12。
- 2026-10-14 按两轮评审修订（规格 §13）。
- 2026-10-14 第三轮评审：配方文件归属明确为 `translate/recipes.py`；回退终态语义；`published.json` 回退计数。
- 2026-10-14 实施（直接在 main 上开发，按用户指示）。离线部分完成；完成标准第二项（整片真实运行记录降级次数）待用户确认后执行，故 Status 为 claimed。
  - 用户裁定：允许改票据 05 拥有的 `kototoki/translate/generate.py` 与 `tests/test_translate.py`（降级必须接入批次循环）；规格 §6 的"`force = true` 重跑整个翻译阶段"本票不做，编排器侧另行处理。
  - 实现：`translate/recipes.py` 给 `Recipe` 加 `overflow` 字段（进 `fixed`，与 v3 位置相同，`b10-joint` hash 不变），追加 `B10_JOINT_DEGRADE_V1`（hash `994c0d03…95fe`）并设为 `PRODUCT`；新文件 `translate/degrade.py`（拆分、降级树、回退、`report.json` 内容）；`generate.py` 把批次终态失败转入降级、加 `degrade.jsonl` 节点日志与续跑、完成时写 `report.json`、`fallback_count` 取真实回退数，删掉 `terminal-failures/`。编排器的 `published.json` 回退计数与控制台汇总沿用票据 06 已有代码，未改。
  - 与票据正文的细化（规格只写到两半，按最小设计补全，规格 §13 已记）：① 单条子批次 ID 为 `父ID.a.1`…；② 奇数条批次前半多 1 条，只有 1 条的批次失败即回退；③ 降级中各节点结果追加写 `degrade.jsonl`，续跑不重做已有结果的节点（含失败的原批次）；④ `report.json` 放在 `<配方名>__s<seed>/` run 目录内；⑤ 降级批次在 `batches.jsonl` 的行不带顶层 `request`，原批次请求在 `degrade.nodes[0]`。
  - 独立 Opus 只读审计：无严重问题；已改：降级日志行 ID 前缀校验收紧、`degrade_requests` 不再计原批次、去掉重复的请求记录、去掉循环论证的请求字节测试（字节仍由 `RequestBytesTests` 钉住）、补"原批次 OOM 不进降级""已记录单条失败续跑时直接回退"两条测试。未改：最后一个子批次结果已记录、批次行尚未写入时崩溃，续跑会先冷启动 server 再从日志重建该批次（结果正确，只浪费一次加载，窗口极窄）。
  - 自动检查：`tests/test_translate_degrade.py`（12）、`test_translate.py`、`test_translate_recipes.py` 更新；`just test` 312 个测试通过，`just check` 通过。
  - 文档：翻译子系统模块页、模块边界、目标架构页状态行、规格 §13。
  - 遗留：完成标准第二项；GLOSSARY 未登记产品配方名（归票据 08 收口）。
- 2026-10-14 用户裁定：删去规格 §6 的"`force = true` 重跑整个翻译阶段"，回退 cue 只经改 seed 重试；`force` 只管最终文件覆盖。规格 §6、§13 与模块页已改，代码不变。
- 2026-10-14 用户裁定：整片真实运行暂不执行（Status 保持 claimed）；GLOSSARY 登记移交票据 08，已写入 08 的范围正文与 Comments。
- 2026-10-14 完成标准第二项随票据 08 整片运行完成：Heaven's Feel II／III × w0／x0 四个文件 468 批，降级批次 0、回退 cue 0、降级请求 0（真实数据未触发降级路径），见 `docs/research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md`。
