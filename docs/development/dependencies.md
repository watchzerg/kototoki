# 依赖布局与资产清单

状态：accepted（2026-10-18 评审并由用户裁定）
范围：产品根环境与 `kototoki/` 的依赖放在哪里、版本由谁锁定、由哪个 recipe 安装或编译。不涉及冻结的 `experiments/` 及其隔离环境（`.local/envs/`）。

产品运行所需的全部依赖都放进本项目、不进 Git。除 Python 包外，所有依赖的版本由一份提交进 Git 的**资产清单**（根目录 `assets.toml`）唯一确定；recipe 按清单下载、校验 SHA256 并放到固定位置。`.local/` 只放内容，不承载身份。Python 工具分工见 [Python 工具链](toolchain.md)，命令与门禁见[开发工作流](workflow.md)。

## 四层布局

| 层 | 内容 | 位置 | 锁定 |
| --- | --- | --- | --- |
| 引导层 | mise、uv、just | 项目外（mise 自身安装工具） | `mise.toml`；唯一不在项目内的一层 |
| Python 依赖 | 运行时与开发依赖 | `.venv/`，缓存 `.local/cache/root-uv`，解释器 `.local/tools/python`（`mise.toml` 的 `[env]`） | `pyproject.toml` + `uv.lock`；开发工具引入时放 `[dependency-groups] dev`，与运行时分开 |
| 下载的二进制 | ffmpeg、llama.cpp | 安装到 `.local/tools/<name>/<version>/`；原始压缩包缓存在 `.local/downloads/<name>/` | 清单写版本、URL、压缩包 SHA256 与解压后关键文件 SHA256；安装时在安装目录生成 `identity.json`（沿用 llama.cpp 的格式） |
| 模型 | 产品用到的权重 | `.local/models/<dir>/`，现有目录不改名、不迁移 | 清单写 HF repo、revision 与逐文件 SHA256（字段形状同冻结的 `experiments/provision/acquire_models.py` 的 `SPECS`，代码不复用） |
| 编译产物 | 当前没有，只定规则 | 源码与构建树 `.local/build/<name>/<version>/`；产物安装到 `.local/tools/<name>/<version>/` | 清单锁源码 git commit 与构建参数；产物同样生成 `identity.json` |

Python 依赖的变更：用 uv 增删、解析与同步，manifest 与 lock 一起提交；日常安装只消费已提交的解析结果，升级是单独、可识别的变更；新选型与有意升级按[推理选型原则](inference-selection.md)取最新稳定版，选定后保留可复现的锁定。包来源与平台相关的选择（如 `pytorch-cu128` 显式索引）随引入写进[技术选型](technology-stack.md#已选依赖)；不从别的项目照搬 CUDA 包版本、索引或依赖；只有选定的 GPU 后端需要时才引入后端专属的可选依赖组。

## 资产清单 `assets.toml`

顶层两张表：`tools` 与 `models`，键名即资产名。

```toml
[tools.<name>]                       # 安装到 .local/tools/<name>/<version>/
version = "…"
source = "…"                         # 发布页
[[tools.<name>.archives]]            # 下载到 .local/downloads/<name>/<archive name>，校验后解压
name = "…"
url = "…"
sha256 = "…"                         # 缺省表示未知：install-tools 拒绝从它安装
strip = "…"                          # 可选：压缩包内要去掉的路径前缀
[tools.<name>.files]                 # 安装目录内的相对路径 → 身份；只解压并安装这些文件
"bin/ffmpeg.exe" = { sha256 = "…", size = 0 }

[models.<name>]
dir = "…"                            # 相对于 .local/models
repo = "…"                           # HF repo；缺省表示没有可下载来源（source 说明来处）
revision = "…"                       # 固定 commit，不跟随 main
gated = true                         # 可选：须用有权限账户的 HF_TOKEN 获取
[models.<name>.files]                # 模型目录内的相对路径 → 身份
"model.bin" = { sha256 = "…", size = 0 }
```

要点：

- 代码里的模型 SHA 常量保留，用于运行时自校验（`kototoki/plan.py` 的逐文件表）；core 测试断言"代码常量 == 清单"，并核对 `kototoki/config.py` 默认路径里的 ffmpeg 版本号，防止三处漂移。专名建表与翻译的模型由 Strata 管理，不在清单里（[ADR-0019](../adr/0019-product-translation-q2.md)、[ADR-0022](../adr/0022-product-names-on-strata.md)）。
- 清单是模型与二进制身份的唯一权威；其他文档链接清单，不再重列 SHA 表。
- 执行逻辑放 `scripts/assets.py`（只用标准库），recipe 保持薄。

## recipe 职责

| recipe | 做什么 | 备注 |
| --- | --- | --- |
| `just install` | `uv sync --locked`，再按清单安装 `tools`（ffmpeg、llama.cpp） | 联网、改环境，按 AGENTS 规定先问 |
| `just fetch-models` | 只下载模型 | 几十 GB，不并入 install；先问 |
| `just verify-assets` | 离线核对已装内容与清单一致 | 用 `artifacts.verify_model` 的 size+mtime 缓存，快 |
| `just upgrade` | 按下文[升级](#升级)规则把 Python 依赖、llama.cpp、ffmpeg 升到最新稳定版，再跑 core、full 测试与 `verify-assets` | 联网、改环境与清单，先问；`just upgrade-check` 只报告 |
| `just build-<name>` | 需要编译时再按依赖单独建 | **不放进 `just install`**，也不建通用的 `just compile` |

编译不进 install：编译需要 MSVC／CUDA Toolkit，耗时长，失败模式与下载完全不同；install 应可重复、快速、只消费锁定结果。按"第二个使用者出现再抽象"，现在不建通用编译入口。产品当前没有需要编译的依赖（llama.cpp 用官方 stock 二进制；b11429 补丁版只属于冻结研究）。

## 升级

`just upgrade [python] [llama.cpp] [ffmpeg]`（省略即全部；`scripts/upgrade.py`）按选版规则把可升级的组件升到最新稳定版，`just upgrade-check` 只报告。规则与 2026-10-19 那次手动升级相同：

- **Python**：CUDA 12 锚点 torch、torchaudio、torchcodec、ctranslate2 保持原钉版，升级须人工决定；其余 `==` 钉住的直接依赖先去钉、由 uv 解析出最新稳定版后重新钉版；传递依赖一起升，但跳过主版本升级（首个数字段变化，0.x 看次版本，日历版本号除外），被跳过的列在报告里。上游约束（如 sympy 对 mpmath、torch 对 setuptools 的上限）由 uv 自然遵守。之后 `uv sync --locked`；任何一步失败都还原 `pyproject.toml` 与 `uv.lock`。
- **llama.cpp**：GitHub 最新稳定版（`releases/latest`，如 v0.7.0）的 `nightly-tag.txt` 指向的构建；CUDA 主版本与清单现有记录相同，取其中最高的 `win-cuda-*-x64` 与同版本 cudart。产品不再用 llama.cpp（[ADR-0022](../adr/0022-product-names-on-strata.md)），产品配置里没有它的默认路径，升级只改清单与安装目录，供研究侧使用。
- **ffmpeg**：BtbN 最新带日期 tag 的 autobuild 中最高维护分支的 win64 gpl 构建（上游不打正式发布点的包）。按下文 [ffmpeg](#ffmpeg) 的升级步骤，用产品 extract 代码在 `--films` 目录（默认 `.local/bilingual-fullfilm-08/input/`）的每部 `.mkv` 上与当前默认构建对照派生 WAV，样本数、PCM SHA256、补偿记录与告警全部相同才切换默认路径；否则清单还原，新版本目录留在 `.local/tools/ffmpeg/` 不用。
- 两种二进制都用 GitHub asset digest 作为压缩包 SHA256（缺失即拒绝），清单块由脚本重写，逐文件 SHA256 从压缩包算出；默认路径改 `kototoki/config.py` 与 `kototoki.toml.example`。
- 脚本不写文档：结束时提示同步[技术选型](technology-stack.md#已选依赖)、本页当前实现，ffmpeg 升级补验收记录，并按报告的 `pending` 申请 smoke。

## ffmpeg

- 当前记录（2026-10-19 起）是 BtbN win64 gpl 构建 `n9.0.2-28-g669f5ab083`（9.0 维护分支，当时最新稳定版为 9.0.2；tag `autobuild-2026-10-18-13-01`），安装在 `.local/tools/ffmpeg/n9.0.2-28-g669f5ab083/bin/`，`kototoki/config.py` 与 `kototoki.toml.example` 的默认路径指向这里。按下面的升级步骤核对：两部影片的派生 WAV 与旧构建、与基线语料逐字节一致（[验收记录](../research/acceptance/2026-10-19-ffmpeg-9.0-upgrade.md)）。
- 此前的第一条记录是本机既有的 gyan.dev full build `2026-10-01-git-0b01ed76aa`（原样复制、原始压缩包未保留，不能经 `install-tools` 重装）；它的安装目录仍留在 `.local/tools/ffmpeg/`，[swr 回归验收](../research/acceptance/2026-10-16-bilingual-pipeline-swr-regression.md)等既往证据绑定在它上面。
- 冻结的 `experiments/corpus/prepare.py`、`experiments/corpus/prepare_round2.py`、`experiments/fullfilm_comparison/corpus.py` 写死了项目外的 ffmpeg 路径，按冻结证据规则不改；那份项目外安装因此保留，只是产品不再依赖它。

升级 ffmpeg 是单独步骤（`just upgrade ffmpeg` 自动完成 1–4 步，验收记录仍需补写）：

1. 在清单登记新版本（版本、URL、压缩包 SHA256、`strip` 与文件 SHA256），来源优先 BtbN（GitHub 带日期 tag 的 release，URL 长期稳定）；gyan.dev 的 git 快照包不保证长期可下载。
2. `just install` 下载安装到新的版本目录。
3. 用新构建重跑派生 WAV 逐字节核对，方法同 2026-10-16 swr 回归验收：两部影片的 PCM SHA256 对照基线语料清单。
4. 核对通过才改 `kototoki/config.py`、`kototoki.toml.example` 的默认路径，并新增验收记录；不通过则新构建不得成为默认。

## CUDA 版本说明

[ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md) 定下的 CUDA 12.8 锁定的是 **Python 进程**：CTranslate2 只有 CUDA 12 wheel，而 cuDNN 9 的 DLL 在 CUDA 12 与 13 构建间同名，同一进程只能加载一份。llama-server 是独立进程，自带 CUDA 13.4 运行时 DLL，与 Python 进程没有 DLL 交集；官方 13.4 构建原生含 sm_120 内核，因此同一决定保留了 `win-cuda-13.4` 构建（原设计见[技术设计历史记录 §7.2](../research/2026-11-11-bilingual-pipeline-spec-history.md#72-环境一个统一的-cuda-128-环境)）。[选版规则](technology-stack.md#选版规则)里"CUDA 12 为锚点"只约束同一进程内会冲突的组件；ffmpeg、llama.cpp 等独立二进制各自取最新稳定版。

## 当前实现

- `assets.toml` 登记：
  - `tools.ffmpeg`（`n9.0.2-28-g669f5ab083`，压缩包 SHA256 与 GitHub digest 一致，只装 `bin/ffmpeg.exe`、`bin/ffprobe.exe`）。
  - `tools."llama.cpp"`（`b11669-cuda13.4`，稳定版 v0.7.0 的 `nightly-tag.txt` 指向的构建；两个 zip 的 SHA256 与 GitHub digest 一致，55 个文件即两个 zip 的全部成员；cudart 包与 b11583 的同一 SHA256。2026-10-19 由 b11583 升级；2026-11-08 起产品只有 names 建表用它，2026-11-09 起建表也换 Strata、**产品不再用 llama.cpp**（[ADR-0022](../adr/0022-product-names-on-strata.md)），条目只供研究侧；旧版本目录 `b11583-cuda13.4` 保留，`llama_stock` smoke 仍指向它）。
  - 产品用到的五个模型目录：`pyannote-segmentation-3.0`（门控）、`faster-whisper-large-v3`、`w0-assets`（只含 `mel_filters.npz`，来自 whisperx 3.8.6 包内 assets，没有 HF 来源，`fetch-models` 不负责）、`qwen3-asr-1.7b-hf`、`mms-1b-all`，以及只供研究侧的 `qwen3.8-27b-ud-iq3_s`（见下一条）。
  - `hy-mt2-30b-a3b-apex-i-compact` 的条目已于 2026-11-08 删除（产品翻译不再用它，[ADR-0019](../adr/0019-product-translation-q2.md)）；研究侧 H0 仍用 `.local/models/translation/` 下已有的文件，路径由各 demo 自己管理，不在清单里。
- `qwen3.8-27b-ud-iq3_s`：目录 `glossary-v1`，来源 `unsloth/Qwen3.8-27B-GGUF`（revision `4ca72078…`），单个 gguf（12040883104 字节）。2026-11-09 前是产品 names 阶段的建表模型（配置键 `[names] model`，已删除，[ADR-0022](../adr/0022-product-names-on-strata.md)）；现只供研究侧（Q0 翻译、v13 前的建表对照），条目与 `fetch-models` 行为保留，产品代码不再引用它。
- `scripts/assets.py`：`install-tools`、`fetch-models`、`verify` 三个子命令，压缩包只支持 zip，下载先写 `.partial` 并边下边算 SHA256，一致才改名；一项失败不阻断其余各项，退出码 1。recipe 与命令表见[开发工作流](workflow.md#命令与门禁)。
- 测试（core）：`tests/core/test_assets_manifest.py` 钉住代码常量与默认路径版本号 == 清单；`tests/core/test_assets_script.py` 用本地 `file://` URL 与临时 zip 覆盖下载、`strip`、只解清单文件、`identity.json`、压缩包缓存复用、无 SHA 与非 zip 拒绝、SHA 不符清理、门控令牌、无来源模型与离线核对。
- **外部前置：Strata**（产品翻译，[ADR-0019](../adr/0019-product-translation-q2.md)、[ADR-0017](../adr/0017-q2-strata-default-launch-baseline.md)）：Strata 0.2.12／engine build 0.1.58 安装在 `%LOCALAPPDATA%\Strata`（`terminal\current\bin\strata.cmd`），翻译模型 `qwen3.8-flash-next-iq3_s` 在 Strata 自己的数据目录；两者都**不在 `assets.toml` 里**，`install`／`fetch-models`／`verify-assets` 不管它们，由用户安装与维护。产品启动翻译时按 ADR-0017 核对版本、端口 8080、run config 与上下文，不符即拒绝运行；升级 Strata 或换模型等于换翻译身份，须新决定。运行前须没有别的 Strata launch 在服务，且空闲显存 ≥14000 MiB。
- 真实模型验证（Q2 首用 smoke）`just smoke translate_product`（`scripts/smoke/translate_product.py`）走 Strata 在产品翻译代码上跑合成句，是翻译的分钟级入口。2026-11-08 首用 smoke（`.local/smoke/20261108T104209Z/`）**通过**：合成 12 条、2 包，首次尝试全部接受（格式失败 0、交付失败 0、回退 0），`reasoning_content` 全空，推理自救／非有限 logits／重复截停 0，high 条目注入 1 行生效；Strata 加载 89 s，探测核对 0.2.12／build 0.1.58、DFlash2、kv int8、spec 4；整机显存峰值 16.1 GB、内存峰值 42.9 GiB；`--stop` 后 status 为空、空闲显存 14884 MiB。**每包约 25–31 s（均值 27.8 s，输出约 130 token）**，远慢于 v12 F1（MTP、32k）的约 3.2 s；冷启动后只有 2 包，原因未查明。此前两次失败已修：子进程里 `strata launch --no-tui` 不点名模型以退出码 2 拒绝（改为 `--model iq3_s`）；研究侧 probe 按参数判断起草方式，把默认启动误认成 MTP（改读服务日志）。
- `scripts/upgrade.py`（`just upgrade`／`upgrade-check`）：规则见上文[升级](#升级)。测试（core）`tests/core/test_upgrade_script.py` 覆盖主版本判定、去钉／锚点、uv 输出解析、清单块重写往返、默认路径切换、release 选取与缺 digest 拒绝，不碰网络与 uv。2026-10-19 `just upgrade-check` 实测三项均为最新（跳过 pillow 12→13）；实际升级路径（非 `--check`）尚未端到端运行过，其步骤与同日的手动升级一致。
- 2026-10-19 `just verify-assets` 在本机全部通过。2026-10-19 升级时压缩包是手动 curl 到 `.local/downloads/<name>/` 的，`install-tools` 只走了缓存复用与解压，`scripts/assets.py` 自身的真实下载路径（GitHub、HF）仍未运行过，只由本地伪 URL 覆盖。
