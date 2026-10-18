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

- 代码里的模型 SHA 常量保留，用于运行时自校验（`kototoki/plan.py` 的逐文件表、`kototoki/translate/server.py` 的 `MODEL_ASSET`）；core 测试断言"代码常量 == 清单"，并核对 `kototoki/config.py` 默认路径里的 ffmpeg 与 llama.cpp 版本号，防止三处漂移。
- 清单是模型与二进制身份的唯一权威；其他文档链接清单，不再重列 SHA 表。
- 执行逻辑放 `scripts/assets.py`（只用标准库），recipe 保持薄。

## recipe 职责

| recipe | 做什么 | 备注 |
| --- | --- | --- |
| `just install` | `uv sync --locked`，再按清单安装 `tools`（ffmpeg、llama.cpp） | 联网、改环境，按 AGENTS 规定先问 |
| `just fetch-models` | 只下载模型 | 几十 GB，不并入 install；先问 |
| `just verify-assets` | 离线核对已装内容与清单一致 | 用 `artifacts.verify_model` 的 size+mtime 缓存，快 |
| `just build-<name>` | 需要编译时再按依赖单独建 | **不放进 `just install`**，也不建通用的 `just compile` |

编译不进 install：编译需要 MSVC／CUDA Toolkit，耗时长，失败模式与下载完全不同；install 应可重复、快速、只消费锁定结果。按"第二个使用者出现再抽象"，现在不建通用编译入口。产品当前没有需要编译的依赖（llama.cpp 用官方 stock 二进制；b11429 补丁版只属于冻结研究）。

## ffmpeg

- 清单的第一条 ffmpeg 记录是本机既有的 gyan.dev full build `2026-10-01-git-0b01ed76aa`：两个可执行文件原样复制到 `.local/tools/ffmpeg/2026-10-01-git-0b01ed76aa/bin/`，不下载、不换构建；`kototoki/config.py` 与 `kototoki.toml.example` 的默认路径指向这里。原因：派生 WAV 与基线 `hf-ii-full.wav` 逐字节一致的证据（[规格 §7](../specs/bilingual-subtitle-pipeline.md)、[swr 回归验收](../research/acceptance/2026-10-16-bilingual-pipeline-swr-regression.md)）都绑定在这个构建上，换构建等于新的 ffmpeg 身份。原始压缩包没有保留，清单不写它的 SHA256，因此这条记录不能经 `install-tools` 重新下载安装。
- 冻结的 `experiments/corpus/prepare.py`、`experiments/corpus/prepare_round2.py`、`experiments/fullfilm_comparison/corpus.py` 写死了项目外的 ffmpeg 路径，按冻结证据规则不改；那份项目外安装因此保留，只是产品不再依赖它。

升级 ffmpeg 是单独步骤：

1. 在清单登记新版本（版本、URL、压缩包 SHA256、`strip` 与文件 SHA256），来源优先 BtbN（GitHub 带日期 tag 的 release，URL 长期稳定）；gyan.dev 的 git 快照包不保证长期可下载。
2. `just install` 下载安装到新的版本目录。
3. 用新构建重跑派生 WAV 逐字节核对，方法同 2026-10-16 swr 回归验收：两部影片的 PCM SHA256 对照基线语料清单。
4. 核对通过才改 `kototoki/config.py`、`kototoki.toml.example` 的默认路径，并新增验收记录；不通过则新构建不得成为默认。

## CUDA 版本说明

[ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md) 定下的 CUDA 12.8 锁定的是 **Python 进程**：CTranslate2 只有 CUDA 12 wheel，而 cuDNN 9 的 DLL 在 CUDA 12 与 13 构建间同名，同一进程只能加载一份。llama-server 是独立进程，自带 CUDA 13.4 运行时 DLL，与 Python 进程没有 DLL 交集；官方 13.4 构建原生含 sm_120 内核，因此同一决定保留了 `win-cuda-13.4` 构建（见[规格 §7.2](../specs/bilingual-subtitle-pipeline.md#72-环境一个统一的-cuda-128-环境)）。选版规则里"CUDA 12 为锚点"只约束同一进程内会冲突的组件；ffmpeg、llama.cpp 等独立二进制各自取最新稳定版。

## 当前实现

清单、`scripts/assets.py` 与上表 recipe 随后续提交落地；落地前产品仍按原路径运行。
