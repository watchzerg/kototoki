# 技术选型

本文是工具链、运行时与依赖政策的权威正文；模块页不各自维护版本清单。选型理由满足 ADR 条件时写 ADR 并在此链接。

## 运行时与工具链

- Python 3.12（`.python-version` 固定补丁版本，`pyproject.toml` 要求 `>=3.12,<3.13`）；`[tool.uv] package = false`，根项目不打包。
- mise 固定 uv 与 just 的版本（`mise.toml`），并设置 `UV_CACHE_DIR`、`UV_PYTHON_INSTALL_DIR` 指向 `.local/`、`UV_PYTHON_PREFERENCE=managed`、`PYTHONUTF8=1`。
- uv 管理解释器、根环境与 `uv.lock`；just 是任务入口，Windows 下用 pwsh 执行 recipe。
- 推理后端在 `.local/envs/` 下的隔离环境中运行，不受根 lock 管理；翻译使用本地 llama.cpp 兼容引擎。
- 工具分工与依赖变更规则见 [Python 工具链](toolchain.md)。

## 依赖政策

只在当前需求需要时引入依赖，先用标准库和已选工具。新增依赖用 `uv add`，提交更新后的 `uv.lock`，不手改 lock；不引入预发布版本。uv 版本由 `mise.toml` 固定。升级集中进行并跑完整门禁。

需要相应能力时优先选用：`typer`（CLI）、`pydantic-settings`（配置）、`fastapi` + `uvicorn`（HTTP 服务）、`httpx`（HTTP 客户端）、`beautifulsoup4` + `lxml`（HTML 解析）、`sqlalchemy` 2.x + `psycopg` 3 + `alembic`（关系数据库）、`structlog`（结构化日志）。不要仅因清单存在而安装。

## 已选依赖

- 根项目 `dependencies = []`：评分、编排与翻译客户端只用标准库。
- 推理组件按 [推理选型原则](inference-selection.md) 选择，当前采纳：faster-whisper（W0）、Qwen-ASR（X0）、新 Pyannote segmentation-3.0（VAD）、MMS-1b-all CTC 对齐，见 [ADR-0001](../adr/0001-two-stt-baselines.md)、[ADR-0003](../adr/0003-new-pyannote-baselines.md)；翻译模型 Hy-MT2 30B-A3B APEX-I-Compact 见 [ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md)、流程见 [ADR-0006](../adr/0006-b10-joint-translation-flow-baseline.md)。
- 隔离环境的实际版本清单见 [环境清单](../research/2026-10-04-runtime-inventory.md)。
