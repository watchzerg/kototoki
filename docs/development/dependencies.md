# 依赖布局与资产清单

状态：accepted（2026-10-18 评审并由用户裁定）
范围：产品根环境与 `kototoki/` 的依赖放在哪里、版本由谁锁定、由哪个 recipe 安装或编译。不涉及研究期留在本机的隔离环境（`.local/envs/`）。

产品运行所需的 Python 依赖与模型都放进本项目、不进 Git。模型的版本由一份提交进 Git 的**资产清单**（根目录 `assets.toml`）唯一确定，recipe 按清单下载、校验 SHA256 并放到固定位置。NVIDIA 驱动、ffmpeg、Strata 是**外部前置**，由用户安装，项目只在运行时核对（[ADR-0034「外部前置」](../adr/0034-ubuntu-only-platform.md#外部前置)）。`.local/` 只放内容，不承载身份。Python 工具分工见 [Python 工具链](toolchain.md)，命令与门禁见[开发工作流](workflow.md)。

## 布局

| 层 | 内容 | 位置 | 锁定 |
| --- | --- | --- | --- |
| 引导层 | mise、uv、just | 项目外（mise 自身安装工具） | `mise.toml`；唯一不在项目内的一层 |
| Python 依赖 | 解释器、运行时与开发依赖 | 依赖在 `.venv/`；解释器与缓存在 uv 默认的共享目录（[ADR-0034](../adr/0034-ubuntu-only-platform.md)） | `pyproject.toml` + `uv.lock`；开发工具引入时放 `[dependency-groups] dev`，与运行时分开 |
| 模型 | 产品用到的权重 | `.local/models/<dir>/`，现有目录不改名、不迁移 | 清单写 HF repo、revision 与逐文件 SHA256（字段形状沿用研究期资产准备脚本的 `SPECS`） |
| 编译产物 | 当前没有，只定规则 | 源码与构建树 `.local/build/<name>/<version>/`；产物安装到 `.local/tools/<name>/<version>/` | 清单锁源码 git commit 与构建参数 |

Python 依赖的变更：用 uv 增删、解析与同步，manifest 与 lock 一起提交；日常安装只消费已提交的解析结果，升级是单独、可识别的变更；新选型与有意升级按[推理选型原则](inference-selection.md)取最新稳定版，选定后保留可复现的锁定。包来源与平台相关的选择（如 `pytorch-cu128` 显式索引）随引入写进[技术选型](technology-stack.md#已选依赖)；不从别的项目照搬 CUDA 包版本、索引或依赖；只有选定的 GPU 后端需要时才引入后端专属的可选依赖组。

## 资产清单 `assets.toml`

顶层只有 `models` 一张表，键名即资产名。

```toml
[models.<name>]
dir = "…"                            # 相对于 .local/models
repo = "…"                           # HF repo
revision = "…"                       # 固定 commit，不跟随 main
gated = true                         # 可选：须用有权限账户的 HF_TOKEN 获取
[models.<name>.files]                # 模型目录内的相对路径 → 身份
"model.bin" = { sha256 = "…", size = 0 }
```

要点：

- 代码里的模型 SHA 常量保留，用于运行时自校验（`kototoki/plan.py` 的逐文件表）；core 测试断言"代码常量 == 清单"，并核对 `kototoki/config.py` 的默认模型路径，防止漂移。专名建表与翻译的模型由 Strata 管理，不在清单里（[ADR-0029](../adr/0029-translate-per-cue-resolution.md)）。
- 清单是模型身份的唯一权威；其他文档链接清单，不再重列 SHA 表。
- 执行逻辑放 `scripts/assets.py`（只用标准库），recipe 保持薄。

## recipe 职责

| recipe | 做什么 | 备注 |
| --- | --- | --- |
| `just install` | 只做 `uv sync --locked` | 联网、改环境，按 AGENTS 规定先问 |
| `just fetch-models` | 只下载模型 | 几十 GB，不并入 install；先问 |
| `just verify-assets` | 离线核对已下载的模型与清单一致 | 用 `artifacts.verify_model` 的 size+mtime 缓存，快 |
| `just upgrade` | 按下文[升级](#升级)规则把 Python 依赖升到最新稳定版，再跑 core、full 测试与 `verify-assets` | 联网、改环境，先问；`just upgrade-check` 只报告 |
| `just build-<name>` | 需要编译时再按依赖单独建 | **不放进 `just install`**，也不建通用的 `just compile` |

编译不进 install：编译需要编译器／CUDA Toolkit，耗时长，失败模式与下载完全不同；install 应可重复、快速、只消费锁定结果。按"第二个使用者出现再抽象"，现在不建通用编译入口。产品当前没有需要编译的依赖。

## 升级

`just upgrade`（`scripts/upgrade.py`）按选版规则把 Python 依赖升到最新稳定版，`just upgrade-check` 只报告。规则与 2026-10-19 那次手动升级相同：

- **Python**：CUDA 12 锚点 torch、torchaudio、torchcodec、ctranslate2 保持原钉版，升级须人工决定；其余 `==` 钉住的直接依赖先去钉、由 uv 解析出最新稳定版后重新钉版；传递依赖一起升，但跳过主版本升级（首个数字段变化，0.x 看次版本，日历版本号除外），被跳过的列在报告里。上游约束（如 sympy 对 mpmath、torch 对 setuptools 的上限）由 uv 自然遵守。之后 `uv sync --locked`；任何一步失败都还原 `pyproject.toml` 与 `uv.lock`。
- ffmpeg 是系统包，随 apt 升级，不归 `just upgrade`。
- 脚本不写文档：结束时提示同步[技术选型](technology-stack.md#已选依赖)与本页当前实现，并按报告的 `pending` 申请 smoke。

## ffmpeg

- 用 apt 装的系统包（`sudo apt install ffmpeg`；2026-11-20 起，[ADR-0034「ffmpeg」](../adr/0034-ubuntu-only-platform.md#ffmpeg)），裁定时本机为 `8.0.1-3ubuntu2+esm5`。
- 配置 `[paths] ffmpeg`／`ffprobe` 默认是命令名，`config.load` 用 `shutil.which` 在 PATH 上查找，找不到即配置错误；写成路径时按路径使用。
- 实际版本只记在运行日志首行的 `ffmpeg=`；结果有变化时先对照它。下游产物按 `audio-16k.wav` 的内容 hash 判断是否过期，ffmpeg 变了只触发重算。
- 只用默认 swr 重采样，不要求 libsoxr。
- Windows 时期的 BtbN／gyan.dev 构建、`identity.json` 与相关验收记录只作历史（[ADR-0033](../adr/0033-ffmpeg-branch-lock.md)）。

## CUDA 版本说明

[ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md) 定下的 CUDA 12.8 锁定的是 **Python 进程**：CTranslate2 只有 CUDA 12 wheel，而 cuDNN 9 的动态库（`libcudnn*.so.9`）在 CUDA 12 与 13 构建间同名，同一进程只能加载一份。当时的 llama-server 是独立进程，自带 CUDA 13.4 运行时，不受此约束；llama.cpp 已于 2026-11-18 移出清单（[ADR-0033](../adr/0033-ffmpeg-branch-lock.md)）。[选版规则](technology-stack.md#选版规则)里"CUDA 12 为锚点"只约束同一进程内会冲突的组件；ffmpeg 等独立二进制各自取最新稳定版。

## 当前实现

- `assets.toml` 登记：
  - 产品用到的四个模型目录（默认引擎 `cross` 四个都用）：`pyannote-segmentation-3.0`（门控）、`faster-whisper-large-v3`、`qwen3-asr-1.7b-hf`、`mms-1b-all`。
  - `hy-mt2-30b-a3b-apex-i-compact` 的条目已于 2026-11-08 删除（产品翻译不再用它，[ADR-0029](../adr/0029-translate-per-cue-resolution.md)）；研究侧 H0 仍用 `.local/models/translation/` 下已有的文件，路径由各 demo 自己管理，不在清单里。
- llama.cpp 工具与 `qwen3.8-27b-ud-iq3_s` 模型条目已于 2026-11-18 删除（[ADR-0033](../adr/0033-ffmpeg-branch-lock.md)）。
- `scripts/assets.py`：`fetch-models`、`verify` 两个子命令；下载先写 `.partial` 并边下边算 SHA256，一致才改名；一项失败不阻断其余各项，退出码 1。recipe 与命令表见[开发工作流](workflow.md#命令与门禁)。
- 测试（core）：`tests/core/test_assets_manifest.py` 钉住代码常量与默认模型路径 == 清单、清单只有 `models`；`tests/core/test_assets_script.py` 用本地 `file://` URL 覆盖模型下载、SHA 不符清理、门控令牌与离线核对。
- **外部前置：Strata**（产品翻译，[ADR-0029](../adr/0029-translate-per-cue-resolution.md)、[ADR-0021](../adr/0021-q3-strata-names-baseline.md)）：Strata 0.2 版本线（本机 0.2.13.1／build 0.1.59.1）用其安装器装好，`strata` 在 PATH 上（`~/.local/bin/strata`），状态与日志在 `~/.local/state/strata/`，翻译模型 `qwen3.8-flash-next-iq3_s` 在 Strata 自己的数据目录；两者都**不在 `assets.toml` 里**，`install`／`fetch-models`／`verify-assets` 不管它们，由用户安装与维护。产品启动翻译时按 ADR-0021「Q3 服务与运行顺序」核对版本线、端口 8080、run config 与上下文，不符即拒绝运行；0.2 线内升级 Strata 不改配方身份（实际版本只记进 `strata.json`，ADR-0034「Strata 版本」），换版本线或换模型须新决定。运行前须没有别的 Strata launch 在服务，且空闲显存 ≥14000 MiB。
- 真实模型验证（Q2 首用 smoke）`just smoke translate_product`（`scripts/smoke/translate_product.py`）走 Strata 在产品翻译代码上跑合成句，是翻译的分钟级入口。2026-11-08 首用 smoke（`.local/smoke/20261108T104209Z/`）**通过**：合成 12 条、2 包，首次尝试全部接受（格式失败 0、交付失败 0、回退 0），`reasoning_content` 全空，推理自救／非有限 logits／重复截停 0，high 条目注入 1 行生效；Strata 加载 89 s，探测核对 0.2.12／build 0.1.58、DFlash2、kv int8、spec 4；整机显存峰值 16.1 GB、内存峰值 42.9 GiB；`--stop` 后 status 为空、空闲显存 14884 MiB。**每包约 25–31 s（均值 27.8 s，输出约 130 token）**，远慢于 v12 F1（MTP、32k）的约 3.2 s；冷启动后只有 2 包，原因未查明。此前两次失败已修：子进程里 `strata launch --no-tui` 不点名模型以退出码 2 拒绝（改为 `--model iq3_s`）；研究侧 probe 按参数判断起草方式，把默认启动误认成 MTP（改读服务日志）。
- `scripts/upgrade.py`（`just upgrade`／`upgrade-check`）：规则见上文[升级](#升级)。测试（core）`tests/core/test_upgrade_script.py` 覆盖主版本判定、去钉／锚点与 uv 输出解析，不碰网络与 uv。2026-10-19 `just upgrade-check` 实测三项均为最新（跳过 pillow 12→13）；实际升级路径（非 `--check`）尚未端到端运行过，其步骤与同日的手动升级一致。
- `scripts/assets.py` 的真实下载路径（HF）仍未运行过，只由本地伪 URL 覆盖；Ubuntu 上第一次 `just fetch-models` 时验证。
