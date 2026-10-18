# 依赖入项目与测试分层调整

状态：reviewed（2026-10-18 评审并由用户裁定，见[已决定项](#已决定项)；未开始实施）
日期：2026-10-18
范围：产品根环境与 `kototoki/` 的依赖布局、版本锁定、安装与编译 recipe；产品测试的 core／full 分层与真实模型调用边界。不涉及冻结的 `experiments/` 及其隔离环境（`.local/envs/`）。

本文是增量说明：实施完成并吸收进当前正文（见[涉及的当前正文](#涉及的当前正文)）后删除。

## 目标

1. 产品运行所需的全部依赖（含 ffmpeg）放进本项目、不进 Git，纳入统一的版本锁定与安装入口。
2. 任何测试（含 `gate-full`）都不调用真实模型；真实模型验证改为单独入口，每次须用户批准。
3. core 是轻量测试，可起本解释器子进程但不调用外部二进制；full 是集成测试，可用少量合成短素材或 mock，但不调用真实模型。
4. 定下需要编译的依赖放在哪里、由哪个 recipe 负责。

## 现状

| 类别 | 位置 | 版本锁定 |
| --- | --- | --- |
| Python 依赖 | `.venv/`；uv 缓存 `.local/cache/root-uv`，解释器 `.local/tools/python`（`mise.toml` 的 `[env]`） | `pyproject.toml` + `uv.lock` |
| uv、just | mise 安装在用户目录 | `mise.toml` |
| llama.cpp | `.local/tools/llama.cpp/b11583-cuda13.4/` | 目录内 `identity.json` 记录各文件 SHA256；手动下载 |
| ffmpeg／ffprobe | `D:/bin/`，在项目外；本机为 gyan.dev full build `2026-10-01-git-0b01ed76aa` | 无。派生 WAV 与基线 `hf-ii-full.wav` 逐字节一致的证据（规格 §7、[swr 回归验收](../research/acceptance/2026-10-16-bilingual-pipeline-swr-regression.md)）都由这个构建产生 |
| 产品模型 | `.local/models/…` | SHA256 写在代码常量中：`kototoki/plan.py` 的逐文件表（VAD、W0、X0、MMS）与 `kototoki/translate/server.py` 的 `MODEL_ASSET`（翻译 GGUF）；文档侧另有两份表格（[语料与模型资产](../architecture/modules/corpus-and-assets.md)、[本地翻译模型资产](../guides/local-translation-model-assets.md)）；下载脚本散在 `.local/downloads/`，不进 Git |
| 需编译的依赖 | 产品当前没有（llama.cpp 用官方 stock 二进制；b11429 补丁版只属于冻结研究） | — |

可借用的先例：冻结的 `experiments/provision/acquire_models.py` 用 `SPECS`（HF repo、revision、逐文件 SHA256）驱动下载并写 `.local/manifests/model-<name>.json`。代码不复用，清单字段形状照搬。

测试现状：`just test`（`gate-core`）只发现 `tests/test_*.py`，不加载模型；`test_job` 用 `tests/fake_worker.py` 子进程顶替 GPU 阶段、翻译用假 session，`test_media_ffmpeg` 调用 `D:/bin` 的真实 ffmpeg 合成秒级素材，`test_stt_workers` 与 `test_job` 各有一条用 `sys.executable -c` 子进程验证导入边界（ADR-0007 第 8 条"编排器与 worker 壳不 import torch"）。整套 333 例约 36 s，其中编排测试因伪 worker 子进程约 30 s。`just test-full` 运行 `scripts/smoke/run_all.py` 的 6 项，全部加载真实模型、占 GPU。

产品翻译的真实运行证据：整片验收（2026-10-14 至 10-16 三份记录）与 [ADR-0011](../adr/0011-dp10-cut-product-recipe.md) 的 2026-10-18 两部影片运行，都经 `python -m kototoki` 走产品 `kototoki.translate`。缺的是**分钟级 smoke 入口**：现有 `llama_stock` smoke 用的是 `experiments.translation_v3` 的 session 与 recipe，不碰产品翻译代码。

### CUDA 版本说明

[ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md) 定下的 CUDA 12.8 锁定的是 **Python 进程**：CTranslate2 只有 CUDA 12 wheel，而 cuDNN 9 的 DLL 在 CUDA 12 与 13 构建间同名，同一进程只能加载一份。llama-server 是独立进程，自带 CUDA 13.4 运行时 DLL，与 Python 进程没有 DLL 交集；官方 13.4 构建原生含 sm_120 内核，因此同一决定保留了 `win-cuda-13.4` 构建（见[规格 §7.2](../specs/bilingual-subtitle-pipeline.md#72-环境一个统一的-cuda-128-环境)）。选版规则里"CUDA 12 为锚点"只约束同一进程内会冲突的组件；ffmpeg、llama.cpp 等独立二进制各自取最新稳定版。

## 方案一：依赖布局与版本锁定

除 Python 包外，所有依赖的版本由一份提交进 Git 的**资产清单**（根目录 `assets.toml`）唯一确定；`just` recipe 按清单下载、校验 SHA256 并放到固定位置。`.local/` 只放内容，不承载身份。

### 四层布局

| 层 | 内容 | 位置 | 锁定 |
| --- | --- | --- | --- |
| 引导层 | mise、uv、just | 项目外（mise 自身安装工具） | `mise.toml`；唯一不在项目内的一层 |
| Python 依赖 | 运行时与开发依赖 | `.venv/`，缓存 `.local/cache/root-uv` | `pyproject.toml` + `uv.lock`；开发工具引入时放 `[dependency-groups] dev`，与运行时分开 |
| 下载的二进制 | ffmpeg、llama.cpp | 安装到 `.local/tools/<name>/<version>/`；原始压缩包缓存在 `.local/downloads/<name>/` | 清单写版本、URL、压缩包 SHA256 与解压后关键文件 SHA256；安装时生成 `identity.json`（沿用现有 llama.cpp 格式） |
| 模型 | 产品用到的权重 | `.local/models/<name>/`，现有目录不改名 | 清单写 HF repo、revision 与逐文件 SHA256（字段同 `acquire_models.SPECS`） |
| 编译产物 | 当前没有，只定规则 | 源码与构建树 `.local/build/<name>/<version>/`；产物安装到 `.local/tools/<name>/<version>/` | 清单锁源码 git commit 与构建参数；产物同样生成 `identity.json` |

要点：

- **ffmpeg 的第一条清单记录是现有构建**：把 `D:/bin` 的 gyan.dev `2026-10-01-git-0b01ed76aa` 复制到 `.local/tools/ffmpeg/<version>/bin/`，记录 `ffmpeg.exe`、`ffprobe.exe` 的 SHA256，不下载、不换构建；`kototoki/config.py` 与 `kototoki.toml.example` 的默认路径改指这里。原因：派生 WAV 与基线逐字节一致的证据绑定在这个构建上，换构建等于新的 ffmpeg 身份。
- **升级 ffmpeg 是单独步骤**：登记新版本、下载安装后，必须重跑派生 WAV 逐字节核对（方法同 2026-10-16 swr 回归验收：两部影片的 PCM SHA256 对照基线语料清单），通过才改默认路径。来源优先 BtbN（GitHub 带日期 tag 的 release，URL 长期稳定）；gyan.dev 的 git 快照包不保证长期可下载。
- 代码里的模型 SHA 常量保留，用于运行时自校验；新增一条 core 测试断言"代码常量 == 清单"，覆盖 `plan.py` 的逐文件表、`server.py` 的 `MODEL_ASSET`，以及 `config.py` 默认路径里的 ffmpeg 与 llama.cpp 版本号，防止三处漂移。
- 清单成为模型与二进制身份的唯一权威后，[语料与模型资产](../architecture/modules/corpus-and-assets.md)与[本地翻译模型资产](../guides/local-translation-model-assets.md)里的 SHA 表格改为链接清单，不再重列（guide 属既有目录，只改引用不新增内容）。
- 执行逻辑放 `scripts/assets.py`，recipe 保持薄（符合[工具链](../development/toolchain.md)约定）。
- 冻结的 `experiments/corpus/prepare.py`、`experiments/corpus/prepare_round2.py`、`experiments/fullfilm_comparison/corpus.py` 写死了 `D:/bin`，按冻结证据规则不改；`D:/bin` 因此保留，只是产品不再依赖它。

### recipe 职责

| recipe | 做什么 | 备注 |
| --- | --- | --- |
| `just install` | `uv sync --locked`，再按清单安装 `tools`（ffmpeg、llama.cpp） | 联网、改环境，按 AGENTS 规定先问 |
| `just fetch-models` | 只下载模型 | 几十 GB，不并入 install；先问 |
| `just verify-assets` | 离线核对已装内容与清单一致 | 用 `artifacts.verify_model` 现有的 size+mtime 缓存，快 |
| `just build-<name>` | 需要编译时再按依赖单独建 | **不放进 `just install`**，也不建通用的 `just compile` |

编译不进 install 的理由：编译需要 MSVC／CUDA Toolkit，耗时长，失败模式与下载完全不同；install 应可重复、快速、只消费锁定结果。按"第二个使用者出现再抽象"，现在不建通用编译入口。

## 方案二：测试不调用真实模型

写入 [测试设计与验收](../agents/testing.md) 的"分层"：

- core 与 full 都**不加载模型权重、不推理、不占 GPU**。
- 例外：体积很小、可在 CPU 运行的产品模型可进 full（当前唯一候选是产品 VAD 用的 pyannote segmentation-3.0，`pytorch_model.bin` 约 5.9 MB）。每个须用户单独批准，批准记录写进 testing.md。须注明：产品 VAD 设备固定为 `cuda:0`（ADR-0007），CPU 测试走的是另一条设备路径，不能当作 GPU 路径的证据。
- 允许：项目内 ffmpeg 合成的秒级素材、fake worker 子进程、本地伪 HTTP server、mock。
- 真实模型调用不再称为测试，改称**真实模型验证**，入口 `just smoke`，持有 `.local/gpu.lock`，每次须用户批准，不属于任何 gate。

连锁变化：

- 现有 `just test-full` 的 6 项（`forced_align`、`vad_pyannote`、`ct2_after_torch`、`llama_stock` 四个环境 smoke，`stt_frozen_window`、`x0_frozen_window` 两个冻结窗口门禁）整体移到 `just smoke`。
- `tests/stt_frozen_window.py`、`tests/x0_frozen_window.py` 移到 `scripts/smoke/`；`x0_frozen_window` 从 `tests.stt_frozen_window` 导入的 `AUDIO`、`LOCAL`、`child_env`、`compare`、`run_stage` 随之改路径；`run_all.py` 的 `MODULES` 映射与 docstring（现自称 `just test-full` 入口）同步改。
- testing.md 第 2 条"需要真实接线证明的行为放 full，不为进入 core 而 mock 掉待验证边界"改为指向真实模型验证：需要真实模型证明的行为进 `just smoke`，不为进入测试而 mock 掉待验证边界；"implement-spec 项目覆盖规则"里"本 ticket 的 full 测试可用 `just test-full` 定向运行"按新的 full 语义（离线集成，不占 GPU、无锁）改写，真实模型验证不属于 ticket 门禁。
- [validation](../testing/validation.md) 的 "Real model smoke test" 一行指向 `just smoke`。
- AGENTS.md"重任务先问"清单去掉 `just test-full`、`just gate-full`，加入 `just smoke`。

## 方案三：core／full 新边界

| 层 | 内容 | 硬性要求 | 入口 |
| --- | --- | --- | --- |
| core | 轻量测试 | 进程内或本解释器（`sys.executable`）子进程；不碰网络与 socket、不调用外部二进制；可用临时文件；整套单机约半分钟 | `just test`，属于 `gate-core` |
| full | 集成测试 | 可调用项目内 ffmpeg 合成素材、起伪 server、用 mock；不调用真实模型、不占 GPU，因此不需要 gpu.lock | `just test-full`；`gate-full = gate-core + test-full` |

core 允许子进程是用户 2026-10-18 的裁定：伪 worker 子进程与导入边界测试（ADR-0007 第 8 条不变量）留在快门禁里，代价是 core 约 30 s 而不是几秒。

目录拆为 `tests/core/` 与 `tests/full/`，与 recipe、gate 名称一一对应。现有文件归属：

- 移到 full：`test_media_ffmpeg`（唯一调用外部二进制的测试）。
- 留在 core：其余全部，包括 `test_job`（伪 worker 子进程、假 session）、`test_stt_workers`（含导入守卫子进程）、ASR 测试（进程内伪造 torch）。
- full 新增端到端测试：**扩展 `test_job` 的接缝**，把媒体阶段从假实现换成项目内 ffmpeg 合成的数秒素材，GPU 阶段仍由 fake worker 顶替、翻译仍用假 session，检查三份 SRT 发布。不经 `python -m kototoki` 子进程、不起伪 llama-server：`translate/server.py` 的 `check_model` 断言 GGUF 大小等于 15 GB，`check_engine` 核对引擎目录全部 DLL 的 SHA，伪 server 走不过这两关，而仓库里也没有现成的伪 HTTP server。
- 产品翻译 smoke（`kototoki.translate` 在真实 llama-server 上跑几批）加进 `just smoke`，补上分钟级入口；整片运行证据已存在，见现状。

## 涉及的当前正文

实施时按[随交付同步](../agents/documentation.md#随交付同步)改写：

- 新建 `docs/development/dependencies.md`（四层布局、清单格式、recipe 职责、ffmpeg 升级步骤、CUDA 版本说明），登记 [文档索引](../INDEX.md)；AGENTS.md"调整依赖、工具版本"一行加链接；[工具链](../development/toolchain.md)只留一句并链接。
- [测试设计与验收](../agents/testing.md)：分层、真实模型禁令与小模型例外、第 2 条与 implement-spec 规则的改写。
- [开发工作流](../development/workflow.md)："测试分层与资源边界"与"命令与门禁"（其中"当前实现"表只在对应 recipe 落地时改）。
- [validation](../testing/validation.md)：真实模型验证入口。
- AGENTS.md：重任务清单。
- 模型身份权威移交清单：[语料与模型资产](../architecture/modules/corpus-and-assets.md)、[本地翻译模型资产](../guides/local-translation-model-assets.md)。
- 提到 `D:/bin` 的产品文档：README、[技术选型](../development/technology-stack.md)、[开发工作流](../development/workflow.md)、[规格](../specs/bilingual-subtitle-pipeline.md)、[配置与媒体模块页](../architecture/modules/config-and-media.md)。
- 受影响模块页的"代码与验证入口"（测试路径变化；[STT worker](../architecture/modules/stt-workers.md) 的 `just test-full stt_frozen_window` 改为 `just smoke`）。
- 代码与测试：`kototoki/config.py` 默认路径、`kototoki.toml.example`，`tests/test_config.py`、`tests/test_media.py`、`tests/test_media_ffmpeg.py`，`scripts/smoke/run_all.py`，`justfile`。

## 验收标准

- 清单覆盖 ffmpeg、llama.cpp 与产品用到的全部模型；`just verify-assets` 在本机通过；"代码常量 == 清单"测试通过。
- 产品代码、示例配置与产品文档不再引用 `D:/bin`；ffmpeg 仍是 `2026-10-01-git-0b01ed76aa` 构建，派生 WAV 基线证据不需要重跑。
- `just test` 只运行 `tests/core/`，不调用外部二进制、不碰网络。
- `just test-full` 只运行 `tests/full/`，不加载模型、不占 GPU，包含端到端测试。
- `just smoke` 可运行原 6 项并新增产品翻译 smoke；运行仍须用户批准。
- 上述文档已改写，`just docs-check` 通过。

## 实施顺序

1. 改规则正文（testing.md 分层与禁令、dependencies.md 的布局与清单格式）；描述现状的命令表与入口行不在此步改。
2. 拆测试目录并调整 recipe（`test`、`test-full`、`smoke`、`gate-full`），新增端到端 full 测试；同步 workflow.md 命令表、validation.md、AGENTS.md 与模块页。
3. 加资产清单、`scripts/assets.py` 与 recipe；ffmpeg 入项目（复制现有构建，不下载）；模型身份权威移交清单。
4. 新增产品翻译 smoke（运行前先问）。

## 已决定项

2026-10-18 评审后用户裁定：

1. 资产清单放根目录 `assets.toml`，与 `mise.toml`、`pyproject.toml` 并列。
2. 真实模型验证 recipe 叫 `just smoke`，与 `scripts/smoke/` 同名。
3. 现有模型目录保持原名、不迁移。
4. ffmpeg 第一条记录登记现有 gyan.dev 构建；以后升级优先 BtbN，并重跑逐字节核对。
5. core 可起本解释器子进程；只禁外部二进制、网络与 socket。
