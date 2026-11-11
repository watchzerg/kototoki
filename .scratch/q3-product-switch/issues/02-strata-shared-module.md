# 02 Strata 生命周期下沉为共享模块 kototoki/strata.py

Status: resolved
Type: task
Blocked by: 01

范围、终点与门见计划 §4 第 2 张票据（docs/plans/product-names-on-strata.md）。

- 移动 `StrataServer`、`StrataRefused` 与辅助函数；Strata 身份常量搬到中间层；新增共享 `Session`。
- 翻译子系统改用共享模块，行为不变：`test_translate_strata.py`、`test_translate.py` 全过，只改导入路径。

## 执行记录

- 2026-11-09 新建 `kototoki/strata.py`：`StrataServer`／`StrataRefused`／`probe`／`ResourceSampler` 等从 `translate/strata.py` 原样搬入（日志前缀 `[translate]`→`[strata]`、显存等待 `stage="strata"`、logger `kototoki.strata`）；Strata 身份常量 `MODEL`、`STRATA_VERSION`、`STRATA_ENGINE_BUILD`、`STRATA_LAUNCH`、`STRATA_RESOLVED` 搬入，`translate/recipes.py` 改为从中间层导入（`RECIPE_HASH` 钉子测试照过，配方内容不变）；共享 `Session(config, *, on_server_pid, server_factory, client_factory)` 搬入并加 `start_failures`／`MAX_START_FAILURES`；`SESSIONS_DIR = "strata-sessions"`。
- `kototoki/translate/strata.py` 改为显式再导出（研究侧 `translation_v3/strata.py`、`v13.py` 的惰性导入全部可解析，`test_research_import_path_still_works` 守门）；`generate.py` 删掉 `Session` 类与 `SESSIONS_DIR`，从 `kototoki.strata` 导入；`translate/__init__.py` 暂仍导出 `Session`（取自 `kototoki.strata`，供 `job.py` 在票据 04 前继续工作）。
- 测试：`test_translate_strata.py` → `test_strata.py`（`git mv`；logger 与常量来源改为 `kototoki.strata`，新增 `SessionTests` 7 项）；`test_translate.py` 只改导入与 `strata-sessions` 断言；`scripts/smoke/translate_product.py` 改用 `strata.Session`。
- 偏离：票据 01 定的"整批最多启动 3 次"会让 `test_mixed_failures_do_not_mark_strata_unavailable` 失败（翻译既有行为允许一部影片耗掉 3 次启动后下一部再起），本票据要求行为不变，故改为只计启动失败（整批累计 3 次即 `unavailable`）；ADR-0022 决定 5、模块边界、翻译子系统、批次编排、专名一致性、技术设计规格、map Notes 同步改写。
- 自动检查：`just test` 600 过；`just check` 过；`docs-check` 44 条失败均为 main 上已有。未动 `experiments/`。

## Answer

完成。Strata 生命周期与身份常量在 `kototoki/strata.py`，翻译子系统改用之，行为不变；`translate/strata.py` 只剩再导出。
