# 05 删除 llama-server 路径与配置键、smoke 改走 Strata、依赖文档

Status: resolved
Type: task
Blocked by: 04

范围、终点与门见计划 §4 第 5 张票据（docs/plans/product-names-on-strata.md）。

- 删 `NAMES_SERVER`、`NAMES_SPEC`、names `Session`、`BUILD["model_asset"]`、配置键 `[names] model`／`port`、`[paths] llama_server`。
- 改 `kototoki.toml.example`、config 与资产清单测试；`scripts/smoke/names_product.py` 改走 Strata；依赖布局、技术选型、开发工作流文档。

## 执行记录

- 2026-11-09 `NAMES_SERVER`／`NAMES_SPEC`／names `Session`／`BUILD["model_asset"]` 已在票据 03 删除（见其记录）；本票据删配置键：`kototoki/config.py` 去掉 `DEFAULTS["paths"]["llama_server"]`、`PATH_KEYS` 的 `llama_server`、`DEFAULTS["names"]` 只剩 `seed`、`MODEL_KEYS` 的 `("names","model")`、`Paths.llama_server`、`Models.names`、`NamesConfig.port`；`[names] seed` 与 `[translate] seed` 同样校验为 `0 < seed < 2**31`（Strata 只接受正整数）；模块说明同步。写了旧键的配置按未知键报错，无兼容垫片。
- `kototoki.toml.example`：删 `llama_server` 行与 `[names]` 的 `model`／`port`，首部注释改为"建表与翻译共用的 Strata"并注明 llama.cpp 与 27B 只供研究侧。
- 测试：`test_config.py` 的 `NamesConfig(seed=…)`、路径键循环去 `llama_server`、`test_names_model_is_relative_to_models_root` 换成 `test_names_has_only_a_seed`（断言 `Models`／`Paths` 没有旧属性）、未知键用例加 `[names] model`／`port`／`[paths] llama_server`、类型用例加 `[names] seed` 0／-3；`test_assets_manifest.py` 去掉 names 模型默认路径与 `llama_server` 默认路径断言（改为断言键不存在，27B 条目仍在清单供研究侧），`PurePosixPath` 导入随之删除。
- `scripts/smoke/names_product.py` 重写为与 `translate_product` 同形：`strata.Session(cfg)` → `names.build_document` → `write_artifact` → `name_rows`；证据取工作根 `strata-sessions/` 下的 `strata.json`／`resources.json`／`strata-final.json`；通过条件：`expert_arena == "ram"`、`released`、`build.status == ok`、至少一条 person、表 current、前后均无 llama-server 进程（`list_llama_servers()`）；记录 `prompt_check`、配方名／哈希、模型、注入行数。只做了导入检查，真实运行留给票据 06。
- `scripts/upgrade.py`：llama.cpp 升级说明与 `pending` 改为"产品不用 llama.cpp（ADR-0022）"；`switch_default_paths("llama.cpp", …)` 在产品配置里已无匹配、照常返回空列表，无需改逻辑。
- 文档：依赖布局（模型 SHA 常量、llama.cpp 升级步骤、工具与模型目录清单、27B 条目改为研究侧）、技术选型（Strata 为建表与翻译共用，llama.cpp 只供研究侧）、开发工作流（工具目录说明、`names_product` smoke 描述、端口说明）。README、技术设计、模块页在票据 01／03 已改。
- 自动检查：`just test` 609 过；`tests.full.test_job_ffmpeg` 3 过；`tests.core.test_upgrade_script` 过；`just check` 过；`docs-check` 44 条均为已有；smoke 脚本 `import names_product` 通过。

## Answer

完成。产品配置里不再有 llama-server 路径与 names 的模型／端口键，`[names]` 只剩正整数 `seed`；`names_product` smoke 改走共享 Strata session；依赖、选型、工作流文档改为"llama.cpp 与 27B 只供研究侧"。
