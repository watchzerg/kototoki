# 03 names 改走 Strata：新 BUILD 配方、chat／count_tokens 回调、5 次尝试

Status: resolved
Type: task
Blocked by: 02

范围、终点与门见计划 §4 第 3 张票据（docs/plans/product-names-on-strata.md）。

- 新 `BUILD` 与 hash（新配方名）；请求体与 seed 序列与 v13 逐字节一致（测试导入 experiments 对照）。
- 伪服务测试：正常、首次失控后重试成功、5 次都失败写空表、`count_tokens` 退路、传输失败、`StrataRefused`。

## 执行记录

- 2026-11-09 `table.py`：`MAX_TOKENS` 8192、`CONTEXT_SIZE` 24576（预算仍 15872）、`ATTEMPTS` 5；`_request_body` 去掉 `response_format`、末尾加 `model`，直接产出 v13 `strata_body` 的结果，5 次尝试在一次 `build_table` 内完成（计划 §3.1 允许不照搬外层循环；`meta.attempt`／`build.reason` 因此如实）。
- `recipes.py`：配方 `q3-names-v1`，嵌套 `name`／`build`／`model`／`runtime`（含 kv int8）／`request`，身份常量来自 `kototoki.strata`；hash `d3317926…`。用产品四块拼回 v13 `s1_recipe("v4")` 形状，hash 等于 ADR-0021 的 `38cb7bcd…`——建表块与基线逐字节相同已由测试证明。
- `__init__.py`：`build_document(work_dir, document, session, seed)` 接共享 `kototoki.strata.Session`；`_TokenCounter` 走 `/v1/messages/count_tokens`（trace `count-NN`），退路同 v13；`StrataRefused`／`InfraFailure`→`NamesError`；传输／HTTP／OOM 停 Strata＋`NamesError`；`build` 块补 `prompt_check` 与 `over_budget_by_usage`。
- 提前到本票据的删除（新 `build_document` 不能再用它们，留着会在 llama-server 上默默建表）：names 自己的 `Session`、`NAMES_SPEC`、`SESSIONS_DIR`、`MAX_STARTS`、`NAMES_SERVER`、`BUILD["model_asset"]`；`test_assets_manifest` 的 names 资产断言随之删。配置键与 smoke 仍留给票据 05。**到票据 04 接上编排之前，`job.py` 仍引用 `names.Session`，产品 names 阶段不可运行（测试用伪 names 模块，不受影响）。**
- 测试：`test_names_table.py` 改请求体与 5 次尝试断言；`test_names_recipes.py` 重写（hash 钉子、v4 重建 hash、运行时身份＝翻译配方）；`test_names_session.py` 重写（真实 `strata.Session`＋伪服务／伪客户端 12 项；`V13ByteExactTests` 5 项导入 v13 `NamesClient`＋`build_one` 比较请求体 JSON 文本与 seed 序列）。`llama_server.py` 模块说明改为"产品只用客户端与显存轮询"。
- 自动检查：`just test` 607 过；`just check` 过；`docs-check` 44 条均为已有。未动 `experiments/`。
- 留给票据 05：`[names] seed` 目前没有"正整数"校验（Strata 只接受正整数 seed，翻译的 seed 有校验），随配置键一起改。

## Answer

完成。产品建表按 Q3 规则在共享 Strata session 上进行，配方 `q3-names-v1`（`d3317926…`），与 `names-strata-v4` 的建表块逐字节相同（重建 hash 相等），请求体与 seed 序列与 v13 逐字节对照通过。
