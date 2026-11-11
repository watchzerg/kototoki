# 地图

## 接跑手册

1. 读计划 §7，找第一张未 resolved、且 Blocked by 全部 resolved 的票据，读它的 `## 执行记录`。状态以文件为准。
2. 顺序：01 文档先行 → 02 Strata 下沉 → 03 names 走 Strata → 04 编排共用 session → 05 删除与配置 → 06 GPU 验证 → 07 收尾。
3. 每完成一张票据：票据写 Answer 并标 resolved；本文 Decisions-so-far 加一行；计划 §7 加一行；Git 提交（中文、签名）。
4. GPU 只在 06：开跑前 `Get-Process`（无 llama-server、无别的 Strata、无 GPU 作业）、读 `.local/gpu.lock`、可用内存 ≥52 GiB、`strata launch --plan` 下载量为 0。不杀进程、不关用户程序。
5. 需要裁定的事写计划 §8，不中途问。
6. 在 Windows 上用 Python 写文件一律 `newline='\n'`；仓库行尾 LF。

## Notes

- 与 v13 对照的参照实现：`experiments/scene_batching_v6/v13.py`（`s1_recipe("v4")`、`strata_body`、`NamesClient`、`build_one`），只在测试里导入。
- 产品 Strata 身份常量现在在 `kototoki/translate/recipes.py`（`MODEL`、`STRATA_VERSION`、`STRATA_ENGINE_BUILD`、`STRATA_RESOLVED`）；下沉后 names 不能导入翻译子系统，常量须搬到中间层 `kototoki/strata.py`，翻译配方从那里导入（`RECIPE_HASH` 不变，测试钉住）。
- 共享 session 的启动上限：票据 01 定为"整批最多启动 3 次"；票据 02 实现时发现它改变翻译既有行为（`test_mixed_failures_do_not_mark_strata_unavailable`：一部影片耗掉 3 次启动后下一部仍应能起），而票据 02 要求行为不变，故改为只计**启动失败**：整批累计 3 次即不可用，成功启动不限次（ADR-0022 与模块页同步改写）。
- `just docs-check` 在 main 上本就失败 44 处冻结外链，只看新增条目。

## Decisions-so-far

- 2026-11-09 立项：按计划 §3 执行，tracker 建在本目录。
- 2026-11-09 01：ADR-0022＋文档先行完成（[票据](issues/01-design-and-docs.md)）。设计定稿：`kototoki/strata.py` 中间层＋共享 `Session`；`translate/strata.py` 保留为研究侧再导出（`experiments/translation_v3/strata.py`、`v13.py` 导入它，不能改 experiments，写进 §8 供用户裁定是否改研究侧导入）；配方名 `q3-names-v1`；sessions 目录改 `strata-sessions/`；日志前缀 `[strata]`（偏离"只改导入路径"：测试里的 logger 名与前缀随之改，原因是 Strata 现在也为 names 启动，`[translate]` 前缀会误导）。

- 2026-11-09 02：Strata 下沉完成（[票据](issues/02-strata-shared-module.md)）。共享 session 的上限改为"启动失败整批累计 3 次"（见 Notes）；`kototoki.translate.Session` 暂为再导出，票据 04 删除。

- 2026-11-09 03：names 走 Strata 完成（[票据](issues/03-names-on-strata.md)）。调整：names 的 llama-server 代码（`Session`、`NAMES_SPEC`、`NAMES_SERVER`、`model_asset`）提前在 03 删除——新 `build_document` 用不上它们，留着会让未改的编排在 llama-server 上默默建表；配置键、smoke、依赖文档仍归 05。5 次尝试放在 `table.ATTEMPTS`（计划 §3.1 允许），ADR-0022 决定 1 与模块页同步改写。04 之前 `job.py` 的 names 阶段不可运行（只是中间提交，测试不受影响）。

- 2026-11-09 04：编排共用 session 完成（[票据](issues/04-shared-session-orchestration.md)）。`kototoki.translate` 的 `Session` 过渡再导出随之删除。产品 names 阶段自此可运行（03 的中间状态结束）。

- 2026-11-09 05：配置键与 llama-server 路径删除、`names_product` smoke 改走 Strata、三份开发文档改完（[票据](issues/05-deletions-and-config.md)）。`[names] seed` 新增正整数校验（Strata 要求）。

- 2026-11-09 06：**blocked**。开跑前核对除可用内存外全过（无 llama-server／Strata／GPU 作业，显存 15089 MiB，status 空，plan 无下载）；可用内存 50.5 GiB < 52 GiB，等 10 分钟不变，按 §5 停下写 §8（[票据](issues/06-gpu-validation.md)）。未启动 Strata、未跑 smoke 与整片。
- 2026-11-09 07：收尾完成（[票据](issues/07-wrap-up.md)）；计划状态写“停在票据 06”，不是 done。
- 2026-11-09 06 重跑：用户重启后可用内存 53.7 GiB，smoke（87.5 s，建表 1 次 ok）与 HF-II 整片（1014.8 s，建表 2 次 ok，翻译回退 0，Strata 一次启动、停后释放）均通过；计划状态改 done。

## Fog

- `count_tokens` 在产品里的真实形状只在 06 实测（v13 已观测可用，有退路）；`LlamaClient.request` 的 `trace_label="count"` 目录命名也在 06 看一眼。
- 整片 HF-II 的 5 次建表是否全部需要：06 才知道。
