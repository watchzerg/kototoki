# 技术选型

本文是工具链、运行时与依赖政策的权威正文；模块页不各自维护版本清单。选型理由满足 ADR 条件时写 ADR 并在此链接。

## 运行时与工具链

- Python 3.13（`.python-version` 固定 3.13.16，`pyproject.toml` 要求 `>=3.13,<3.14`）；根项目即产品项目 `kototoki`，`[tool.uv] package = false` 不打包，`environments` 只解析 `sys_platform == 'win32'`。
- mise 固定 uv 与 just 的版本（`mise.toml`），并设置 `UV_CACHE_DIR`、`UV_PYTHON_INSTALL_DIR` 指向 `.local/`、`UV_PYTHON_PREFERENCE=managed`、`PYTHONUTF8=1`。
- uv 管理解释器、根环境与 `uv.lock`；just 是任务入口，Windows 下用 pwsh 执行 recipe。
- 产品推理在根环境（统一 CUDA 12.8）中运行；产品翻译（2026-11-08 起，[ADR-0019](../adr/0019-product-translation-q2.md)）与专名建表（2026-11-09 起，[ADR-0022](../adr/0022-product-names-on-strata.md)）都用独立安装的 Strata 0.2.12／build 0.1.58（`%LOCALAPPDATA%\Strata`，模型 `qwen3.8-flash-next-iq3_s` 在 Strata 数据目录），由产品用 `strata launch --no-tui --model iq3_s`／`--stop` 自动启停、整批一个 session；它是外部前置，不在 `assets.toml` 里，由用户维护（见[依赖布局](dependencies.md)）。产品不起 llama-server，清单里也不再有 llama.cpp（[ADR-0032](../adr/0032-drop-llama-cpp-assets.md)）。选型依据见 [ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md) 与下文[选版规则](#选版规则)。
- 产品媒体提取调用 ffmpeg／ffprobe 子进程（路径在 `kototoki.toml` 的 `[paths]`，默认 `.local/tools/ffmpeg/9.0/bin/`），派生 WAV 用默认 swr 重采样（2026-10-15 由 soxr 改回，票据 10），不要求 libsoxr；构建为 BtbN win64 gpl 9.0 维护分支（2026-10-19 由 gyan.dev `2026-10-01-git-0b01ed76aa` 升级，派生 WAV 逐字节核对见[验收记录](../../research/acceptance/2026-10-19-ffmpeg-9.0-upgrade.md)；2026-11-18 起只锁分支，[ADR-0033](../adr/0033-ffmpeg-branch-lock.md)），实际版本记在安装目录的 `identity.json` 与运行日志首行，升级步骤见[依赖布局与资产清单](dependencies.md#ffmpeg)。
- 产品翻译配方为 `q3-translate-v1`（`kototoki/translate/recipes.py`，[ADR-0029](../adr/0029-translate-per-cue-resolution.md)、[ADR-0019](../adr/0019-product-translation-q2.md)）：Q2 规则（[ADR-0017](../adr/0017-q2-strata-default-launch-baseline.md)、[ADR-0018](../adr/0018-q2-sole-translation-baseline.md)）加回复按条收下、只追问未解决的 cue；切包同 `dp10-cut`，见 [GLOSSARY](../../GLOSSARY.md)。H0（Hy-MT2＋`dp10-cut`）只留在研究侧。
- 工具分工与依赖变更规则见 [Python 工具链](toolchain.md)。

## 依赖政策

只在当前需求需要时引入依赖，先用标准库和已选工具。新增依赖用 `uv add`，提交更新后的 `uv.lock`，不手改 lock；不引入预发布版本。uv 版本由 `mise.toml` 固定。升级集中进行并跑完整门禁。

需要相应能力时优先选用：`typer`（CLI）、`pydantic-settings`（配置）、`fastapi` + `uvicorn`（HTTP 服务）、`httpx`（HTTP 客户端）、`beautifulsoup4` + `lxml`（HTML 解析）、`sqlalchemy` 2.x + `psycopg` 3 + `alembic`（关系数据库）、`structlog`（结构化日志；2026-10-18 评估后未采用，产品用标准库 logging，见[批次编排的运行日志节](../architecture/modules/batch-orchestration.md#运行日志)）。不要仅因清单存在而安装。

### 选版规则

用户 2026-10-14 明确：CUDA 12 与 Python 3.13 是固定锚点；被它们限制的组件随之锁定（torch／torchaudio／torchcodec 取 cu128 索引上的最新版本，CTranslate2 取 CUDA 12 wheel 的最新版本）；不受影响的组件一律取最新稳定版（transformers、pyannote.audio、faster-whisper、numpy 等），以 `uv lock` 当日的最新稳定版为准并记录。锚点的依据：CTranslate2 只有 CUDA 12 wheel，cuDNN 9 的 DLL 在 CUDA 12 与 13 构建间同名、同一进程只能加载一份（[ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md)，另见[依赖布局的 CUDA 版本说明](dependencies.md#cuda-版本说明)）；Python 3.15 没有 CTranslate2／torchaudio／torchcodec 的 wheel，3.14 的边角依赖未核。

- 不需要本地安装 CUDA toolkit：所有组件用 wheel／二进制自带的运行时。
- CTranslate2 wheel 在 sm_120 上靠 PTX JIT（只嵌 sm_86 PTX、无 sm_120 SASS；`CUDA_DISABLE_PTX_JIT=1` 时解码失败）：冷启动首窗解码约 27 s，二次启动约 5 s（2026-10-14 实测）。
- 升级即新身份：torch、CTranslate2 等推理组件的版本变化会轻微改变数值，必须在冻结输入上与基线成绩回归后才算接上基线。

## 已选依赖

- 根项目运行时依赖（`uv lock` 于 2026-10-14 解析、2026-10-19 小范围升级，按[选版规则](#选版规则)：CUDA 12 与 Python 3.13 为锚点，其余取最新稳定版）：

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
- 隔离环境的实际版本清单见 [环境清单](../../research/2026-10-stt-landscape/README.md)。
