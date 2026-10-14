# 技术选型

本文是工具链、运行时与依赖政策的权威正文；模块页不各自维护版本清单。选型理由满足 ADR 条件时写 ADR 并在此链接。

## 运行时与工具链

- Python 3.13（`.python-version` 固定 3.13.16，`pyproject.toml` 要求 `>=3.13,<3.14`）；根项目即产品项目 `kototoki`，`[tool.uv] package = false` 不打包，`environments` 只解析 `sys_platform == 'win32'`。
- mise 固定 uv 与 just 的版本（`mise.toml`），并设置 `UV_CACHE_DIR`、`UV_PYTHON_INSTALL_DIR` 指向 `.local/`、`UV_PYTHON_PREFERENCE=managed`、`PYTHONUTF8=1`。
- uv 管理解释器、根环境与 `uv.lock`；just 是任务入口，Windows 下用 pwsh 执行 recipe。
- 产品推理在根环境（统一 CUDA 12.8）中运行；翻译使用独立进程的官方 llama.cpp b11583 `win-cuda-13.4` 构建（`.local/tools/llama.cpp/b11583-cuda13.4/`，含 `identity.json`），与 Python 进程没有 DLL 交集。选型依据见[双语字幕流水线规格 §7.2](../specs/bilingual-subtitle-pipeline.md#72-环境一个统一的-cuda-128-环境)与 [ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md)。
- 研究期 demo 的推理后端仍在 `.local/envs/` 下的隔离环境中运行，不受根 lock 管理；冻结的 `experiments` recipe 用 Python 3.12 的无依赖历史解释器（`justfile` 的 `legacy`）。
- 工具分工与依赖变更规则见 [Python 工具链](toolchain.md)。

## 依赖政策

只在当前需求需要时引入依赖，先用标准库和已选工具。新增依赖用 `uv add`，提交更新后的 `uv.lock`，不手改 lock；不引入预发布版本。uv 版本由 `mise.toml` 固定。升级集中进行并跑完整门禁。

需要相应能力时优先选用：`typer`（CLI）、`pydantic-settings`（配置）、`fastapi` + `uvicorn`（HTTP 服务）、`httpx`（HTTP 客户端）、`beautifulsoup4` + `lxml`（HTML 解析）、`sqlalchemy` 2.x + `psycopg` 3 + `alembic`（关系数据库）、`structlog`（结构化日志）。不要仅因清单存在而安装。

## 已选依赖

- 根项目运行时依赖（`uv lock` 于 2026-10-14 解析，按[选版规则](../specs/bilingual-subtitle-pipeline.md#72-环境一个统一的-cuda-128-环境)：CUDA 12 与 Python 3.13 为锚点，其余取最新稳定版）：

  | 包 | 版本 | 来源 |
  | --- | --- | --- |
  | torch／torchaudio | 2.11.0+cu128 | `pytorch-cu128` 显式索引（`[tool.uv.sources]`）；cu128 索引止于 2.11.0 |
  | torchcodec | 0.17.0 | PyPI（cu128 索引没有 0.17.0；与本机 `vad-pyannote-gpu-v1` 相同） |
  | transformers | 5.19.0 | PyPI |
  | pyannote.audio | 4.0.7 | PyPI |
  | faster-whisper／ctranslate2 | 1.2.1／4.8.3 | PyPI；ASR 进程须先 `import torch`。实测（票据 01 smoke #3）：cuBLAS／cudart 与 cuDNN 子库来自 torch（cuDNN 9.19），但 CT2 wheel 自带并显式加载 `cudnn64_9.dll`（9.10 调度器），同进程两份调度器并存；W0 冻结窗口 token 与特征逐一一致 |
  | numpy | 2.5.4 | PyPI |

  传递依赖以 `uv.lock` 为准。测试只用标准库 `unittest`，没有开发依赖组。
- 评分、编排与翻译客户端仍只用标准库。
- 推理组件按 [推理选型原则](inference-selection.md) 选择，当前采纳：faster-whisper（W0）、Qwen-ASR（X0）、新 Pyannote segmentation-3.0（VAD）、MMS-1b-all CTC 对齐，见 [ADR-0001](../adr/0001-two-stt-baselines.md)、[ADR-0003](../adr/0003-new-pyannote-baselines.md)；翻译模型 Hy-MT2 30B-A3B APEX-I-Compact 见 [ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md)、流程见 [ADR-0006](../adr/0006-b10-joint-translation-flow-baseline.md)。
- 隔离环境的实际版本清单见 [环境清单](../research/2026-10-04-runtime-inventory.md)。
