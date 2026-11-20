# 技术选型

本文是工具链、运行时与依赖政策的权威正文；模块页不各自维护版本清单。选型理由满足 ADR 条件时写 ADR 并在此链接。

## 运行时与工具链

- Python 3.13（`.python-version` 写 `3.13`，补丁版本由 uv 决定；`pyproject.toml` 要求 `>=3.13,<3.14`）；根项目即产品项目 `kototoki`，`[tool.uv] package = false` 不打包，`environments` 只解析 `sys_platform == 'linux'`（[ADR-0034](../adr/0034-ubuntu-only-platform.md)）。
- mise 只固定 uv 与 just 的版本（`mise.toml`，没有 `[env]`）；一次性准备：`mise trust && mise install`，shell 里激活 mise（[ADR-0034「工具链分层」](../adr/0034-ubuntu-only-platform.md#工具链分层)）。
- uv 管理解释器、根环境与 `uv.lock`，用默认布局：解释器在 uv 共享目录，依赖在 `.venv/`；just 是任务入口。
- 产品推理在根环境（统一 CUDA 12.8）中运行；产品翻译（2026-11-08 起，[ADR-0029](../adr/0029-translate-per-cue-resolution.md)）与专名建表（2026-11-09 起，[ADR-0028](../adr/0028-names-accept-empty-table.md)）都用独立安装的 Strata 0.2 版本线（本机 0.2.13.1／build 0.1.59.1，`strata` 在 PATH 上，模型 `qwen3.8-flash-next-iq3_s` 在 Strata 数据目录），由产品用 `strata launch --no-tui --model iq3_s`／`--stop` 自动启停、整批一个 session；它是外部前置，不在 `assets.toml` 里，由用户维护（见[依赖布局](dependencies.md)）。产品不起 llama-server，清单里也不再有 llama.cpp（[ADR-0033](../adr/0033-ffmpeg-branch-lock.md)）。选型依据见 [ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md) 与下文[选版规则](#选版规则)。
- 产品媒体提取调用 ffmpeg／ffprobe 子进程：用 apt 装的系统包，配置默认从 PATH 查找（[ADR-0034「ffmpeg」](../adr/0034-ubuntu-only-platform.md#ffmpeg)）；派生 WAV 用默认 swr 重采样（2026-10-15 由 soxr 改回，票据 10），不要求 libsoxr；实际版本记在运行日志首行，见[依赖布局与资产清单](dependencies.md#ffmpeg)。Windows 时期的 BtbN 构建与验收记录只作历史。
- 产品翻译配方为 `q3-translate-v1`（`kototoki/translate/recipes.py`，[ADR-0029](../adr/0029-translate-per-cue-resolution.md)）：Q2 规则（[ADR-0021](../adr/0021-q3-strata-names-baseline.md)）加回复按条收下、只追问未解决的 cue；切包同 `dp10-cut`，见 [GLOSSARY](../../GLOSSARY.md)。H0（Hy-MT2＋`dp10-cut`）只留在研究侧。
- 工具分工与依赖变更规则见 [Python 工具链](toolchain.md)。

## 依赖政策

只在当前需求需要时引入依赖，先用标准库和已选工具。新增依赖用 `uv add`，提交更新后的 `uv.lock`，不手改 lock；不引入预发布版本。uv 版本由 `mise.toml` 固定。升级集中进行并跑完整门禁。

需要相应能力时优先选用：`typer`（CLI）、`pydantic-settings`（配置）、`fastapi` + `uvicorn`（HTTP 服务）、`httpx`（HTTP 客户端）、`beautifulsoup4` + `lxml`（HTML 解析）、`sqlalchemy` 2.x + `psycopg` 3 + `alembic`（关系数据库）、`structlog`（结构化日志；2026-10-18 评估后未采用，产品用标准库 logging，见[批次编排的运行日志节](../architecture/modules/batch-orchestration.md#运行日志)）。不要仅因清单存在而安装。

### 选版规则

用户 2026-10-14 明确：CUDA 12 与 Python 3.13 是固定锚点；被它们限制的组件随之锁定（torch／torchaudio／torchcodec 取 cu128 索引上的最新版本，CTranslate2 取 CUDA 12 wheel 的最新版本）；不受影响的组件一律取最新稳定版（transformers、pyannote.audio、faster-whisper、numpy 等），以 `uv lock` 当日的最新稳定版为准并记录。锚点的依据：CTranslate2 只有 CUDA 12 wheel，cuDNN 9 的 DLL 在 CUDA 12 与 13 构建间同名、同一进程只能加载一份（[ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md)，另见[依赖布局的 CUDA 版本说明](dependencies.md#cuda-版本说明)）；Python 3.15 没有 CTranslate2／torchaudio／torchcodec 的 wheel，3.14 的边角依赖未核。

- Linux 上复核锚点（2026-11-20）：
  - CTranslate2 的 Linux wheel 在运行时加载 `libcublas.so.12`，最新的 4.9.0 也是如此，仍然没有 CUDA 13 构建。
  - ASR worker 在同一个进程里同时用 CTranslate2 解码、用 torch 做 GPU 运算。cuDNN 9 在 CUDA 12 与 13 两种构建下同名（`libcudnn*.so.9`），同一个进程只能加载其中一份。
  - 因此 torch 不能单独换到 CUDA 13。RTX 5080（sm_120）在 cu128 的 torch 上已经完整可用，换 CUDA 13 也没有收益。
- torchcodec 用 CPU 构建（`pytorch-cpu` 索引的 `0.17.0+cpu`），不跟 torch 取 CUDA 构建：
  - 产品里只有 pyannote 依赖 torchcodec，而且只在给它传文件路径时才用它解码。产品的 VAD 给 pyannote 传的是已经读进内存的波形（`{'waveform', 'sample_rate'}`），所以 torchcodec 只需要能导入，不参与解码，用不到 GPU 解码能力。
  - 它的 CUDA 构建要和 torch 的 CUDA 版本对上才能导入：PyPI 上的 Linux wheel 按 CUDA 13 构建（依赖 `libnvrtc.so.13`），和 torch cu128 装在一起导入就会失败；cu128 索引上只到 0.11.1，比钉住的 0.17.0 旧。
  - CPU 构建不依赖任何 CUDA 库，与 torch 的 CUDA 版本无关；它和 PyPI 版是同一个版本号，以后升级只需跟着升版本号，不再受 CUDA 锚点牵制。
- 不需要本地安装 CUDA toolkit：所有组件用 wheel／二进制自带的运行时。
- CTranslate2 wheel 在 sm_120 上靠 PTX JIT（只嵌 sm_86 PTX、无 sm_120 SASS；`CUDA_DISABLE_PTX_JIT=1` 时解码失败）：冷启动首窗解码约 27 s，二次启动约 5 s（2026-10-14 实测）。
- 升级即新身份：torch、CTranslate2 等推理组件的版本变化会轻微改变数值，必须在冻结输入上与基线成绩回归后才算接上基线。

## 已选依赖

- 根项目运行时依赖（迁到 Ubuntu 后 2026-11-20 删掉旧 lock 重新解析，只解析 Linux；直接依赖版本不变，传递依赖取当日最新稳定版；按[选版规则](#选版规则)：CUDA 12 与 Python 3.13 为锚点）：

  | 包 | 版本 | 来源 |
  | --- | --- | --- |
  | torch／torchaudio | 2.11.0+cu128 | `pytorch-cu128` 显式索引（`[tool.uv.sources]`）；cu128 索引止于 2.11.0 |
  | torchcodec | 0.17.0+cpu | `pytorch-cpu` 显式索引；为什么用 CPU 构建见[选版规则](#选版规则) |
  | transformers | 5.20.1 | PyPI（2026-10-19 由 5.19.0 升级；真实模型验证待跑） |
  | pyannote.audio | 4.0.7 | PyPI |
  | faster-whisper／ctranslate2 | 1.2.1／4.8.3 | PyPI；ASR 进程须先 `import torch`。Linux 上 torch 经 `nvidia-*-cu12` wheel 带来 cuBLAS／cuDNN 9.19 等运行库；CT2 按 soname 复用这一份，由 smoke `ct2_after_torch` 核对，尚待首跑（ADR-0034「未验证与已知限制」）。Windows 时期 smoke 的 DLL 结论只作历史 |
  | numpy | 2.5.5 | PyPI |

  传递依赖以 `uv.lock` 为准（mpmath 受 sympy `<1.4`、setuptools 受 torch `<82` 约束）。改 `environments` 后不能只 `uv lock`：uv 会沿用旧 lock 里按旧平台记下的依赖元数据，torch 的 `nvidia-*` 依赖就这样被漏掉（2026-11-20 实测），须删 lock 重新解析或对相关包 `--upgrade-package`。测试只用标准库 `unittest`，没有开发依赖组。
- 评分、编排与翻译客户端仍只用标准库。
- 推理组件按 [推理选型原则](inference-selection.md) 选择，当前采纳：faster-whisper（W0）、Qwen-ASR（X0）、新 Pyannote segmentation-3.0（VAD）、MMS-1b-all CTC 对齐，见 [ADR-0003](../adr/0003-new-pyannote-baselines.md)；翻译按基线 Q3 规则（Strata 上的 Qwen3.8-Flash-Next IQ3_S，切包 `dp10-cut`），基线与历史身份（含此前的 Hy-MT2 30B-A3B APEX-I-Compact）见 [ADR-0021](../adr/0021-q3-strata-names-baseline.md)、产品见 [ADR-0029](../adr/0029-translate-per-cue-resolution.md)。
- 隔离环境的实际版本清单见 [环境清单](../../research/2026-10-stt-landscape/README.md)。
