# 技术选型

本文是工具链、运行时与依赖政策的权威正文；模块页不各自维护版本清单。选型理由满足 ADR 条件时写 ADR 并在此链接。

## 运行时与工具链

- Python 3.13（`.python-version` 固定 3.13.16，`pyproject.toml` 要求 `>=3.13,<3.14`）；根项目即产品项目 `kototoki`，`[tool.uv] package = false` 不打包，`environments` 只解析 `sys_platform == 'win32'`。
- mise 固定 uv 与 just 的版本（`mise.toml`），并设置 `UV_CACHE_DIR`、`UV_PYTHON_INSTALL_DIR` 指向 `.local/`、`UV_PYTHON_PREFERENCE=managed`、`PYTHONUTF8=1`。
- uv 管理解释器、根环境与 `uv.lock`；just 是任务入口，Windows 下用 pwsh 执行 recipe。
- 产品推理在根环境（统一 CUDA 12.8）中运行；产品翻译（2026-11-08 起，[ADR-0019](../adr/0019-product-translation-q2.md)）与专名建表（2026-11-09 起，[ADR-0022](../adr/0022-product-names-on-strata.md)）都用独立安装的 Strata 0.2.12／build 0.1.58（`%LOCALAPPDATA%\Strata`，模型 `qwen3.8-flash-next-iq3_s` 在 Strata 数据目录），由产品用 `strata launch --no-tui --model iq3_s`／`--stop` 自动启停、整批一个 session；它是外部前置，不在 `assets.toml` 里，由用户维护（见[依赖布局](dependencies.md)）。产品不再起 llama-server；官方 llama.cpp b11669 `win-cuda-13.4` 构建（`.local/tools/llama.cpp/b11669-cuda13.4/`，含 `identity.json`；版本与文件 SHA256 锁在 `assets.toml`；2026-10-19 由 b11583 升级）只供研究侧 demo，与 Python 进程没有 DLL 交集。选型依据见[双语字幕流水线规格 §7.2](../specs/bilingual-subtitle-pipeline.md#72-环境一个统一的-cuda-128-环境)与 [ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md)。
- 产品媒体提取调用 ffmpeg／ffprobe 子进程（路径在 `kototoki.toml` 的 `[paths]`，默认 `.local/tools/ffmpeg/n9.0.2-28-g669f5ab083/bin/`），派生 WAV 用默认 swr 重采样（2026-10-15 由 soxr 改回，票据 10），不要求 libsoxr；构建为 BtbN win64 gpl `n9.0.2-28-g669f5ab083`（9.0 维护分支，2026-10-19 由 gyan.dev `2026-10-01-git-0b01ed76aa` 升级，派生 WAV 逐字节核对见[验收记录](../research/acceptance/2026-10-19-ffmpeg-9.0-upgrade.md)），版本、来源与文件 SHA256 锁在 `assets.toml`，升级步骤见[依赖布局与资产清单](dependencies.md#ffmpeg)。
- 产品翻译配方为 `q2-degrade-v1`（`kototoki/translate/recipes.py`，[ADR-0019](../adr/0019-product-translation-q2.md)）：Q2 规则（[ADR-0017](../adr/0017-q2-strata-default-launch-baseline.md)、[ADR-0018](../adr/0018-q2-sole-translation-baseline.md)）加批次终态失败的 10→5→1 拆批降级；切包同 `dp10-cut`，见 [GLOSSARY](../../GLOSSARY.md)。H0（Hy-MT2＋`dp10-cut`）只留在研究侧。
- 研究期 demo 的推理后端仍在 `.local/envs/` 下的隔离环境中运行，不受根 lock 管理；冻结的 `experiments` recipe 用 Python 3.12 的无依赖历史解释器（`justfile` 的 `legacy`）。
- 工具分工与依赖变更规则见 [Python 工具链](toolchain.md)。

## 依赖政策

只在当前需求需要时引入依赖，先用标准库和已选工具。新增依赖用 `uv add`，提交更新后的 `uv.lock`，不手改 lock；不引入预发布版本。uv 版本由 `mise.toml` 固定。升级集中进行并跑完整门禁。

需要相应能力时优先选用：`typer`（CLI）、`pydantic-settings`（配置）、`fastapi` + `uvicorn`（HTTP 服务）、`httpx`（HTTP 客户端）、`beautifulsoup4` + `lxml`（HTML 解析）、`sqlalchemy` 2.x + `psycopg` 3 + `alembic`（关系数据库）、`structlog`（结构化日志；2026-10-18 评估后未采用，产品用标准库 logging，见[批次编排的运行日志节](../architecture/modules/batch-orchestration.md#运行日志)）。不要仅因清单存在而安装。

## 已选依赖

- 根项目运行时依赖（`uv lock` 于 2026-10-14 解析、2026-10-19 小范围升级，按[选版规则](../specs/bilingual-subtitle-pipeline.md#72-环境一个统一的-cuda-128-环境)：CUDA 12 与 Python 3.13 为锚点，其余取最新稳定版）：

  | 包 | 版本 | 来源 |
  | --- | --- | --- |
  | torch／torchaudio | 2.11.0+cu128 | `pytorch-cu128` 显式索引（`[tool.uv.sources]`）；cu128 索引止于 2.11.0 |
  | torchcodec | 0.17.0 | PyPI（cu128 索引没有 0.17.0；与本机 `vad-pyannote-gpu-v1` 相同） |
  | transformers | 5.20.1 | PyPI（2026-10-19 由 5.19.0 升级；真实模型验证待跑） |
  | pyannote.audio | 4.0.7 | PyPI |
  | faster-whisper／ctranslate2 | 1.2.1／4.8.3 | PyPI；ASR 进程须先 `import torch`。实测（票据 01 smoke #3）：cuBLAS／cudart 与 cuDNN 子库来自 torch（cuDNN 9.19），但 CT2 wheel 自带并显式加载 `cudnn64_9.dll`（9.10 调度器），同进程两份调度器并存；W0 冻结窗口 token 与特征逐一一致 |
  | numpy | 2.5.4 | PyPI |

  传递依赖以 `uv.lock` 为准；2026-10-19 用 `uv lock --upgrade-package` 只升了 pyannote-core 6.1.0、pyannote-metrics 4.2.0、pyannote-pipeline 4.1.0 与 certifi、filelock、fonttools、httpx2／httpcore2、sqlalchemy，其余保持原解析（mpmath 受 sympy `<1.4`、setuptools 受 torch `<82` 约束）。测试只用标准库 `unittest`，没有开发依赖组。
- 评分、编排与翻译客户端仍只用标准库。
- 推理组件按 [推理选型原则](inference-selection.md) 选择，当前采纳：faster-whisper（W0）、Qwen-ASR（X0）、新 Pyannote segmentation-3.0（VAD）、MMS-1b-all CTC 对齐，见 [ADR-0003](../adr/0003-new-pyannote-baselines.md)；翻译为 Q2（Strata 上的 Qwen3.8-Flash-Next IQ3_S，切包 `dp10-cut`），基线见 [ADR-0018](../adr/0018-q2-sole-translation-baseline.md)、产品见 [ADR-0019](../adr/0019-product-translation-q2.md)；此前的 Hy-MT2 30B-A3B APEX-I-Compact（[ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md)）只作历史对照。
- 隔离环境的实际版本清单见 [环境清单](../research/2026-10-04-runtime-inventory.md)。
