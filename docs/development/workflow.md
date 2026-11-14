# 开发工作流

本文是开发命令、门禁与测试资源合同的权威正文。测试编写规则在[测试设计与验收](../agents/testing.md)。

## 环境

验证目标是原生 Windows（pwsh、RTX 5080）；macOS 未验证。mise、uv、just 由用户安装，版本固定在 `mise.toml`，解释器固定在 `.python-version`；工具分工与依赖变更规则的权威正文是 [Python 工具链](toolchain.md)，平台要求见 [Windows 与 NVIDIA](windows-nvidia.md)。

- 根环境即产品环境：Python 3.13 + 统一 CUDA 12.8 推理栈（torch 2.11.0+cu128 等，版本见[技术选型](technology-stack.md#已选依赖)）。`just install`（`just setup` 即 `uv sync --locked`，再按清单安装 ffmpeg、llama.cpp）与 `just fetch-models` 会改环境且可能联网，须先问用户。
- 冻结的 `experiments` recipe 不用产品环境，而用 `justfile` 的 `legacy` 解释器（`uv run --no-project --python 3.12`，等同原来无依赖的根环境），保持其原有跳过行为与运行身份。
- 行尾统一为 LF：`.gitattributes` 的 `* text=auto eol=lf` 让仓库存 LF、任何平台检出也是 LF（优先于 `core.autocrlf`），`.editorconfig` 让编辑器新建 LF 文件；改文件不必再做字节级保护。
- 研究期 demo 的推理后端是 `.local/envs/` 下的隔离环境，模型在 `.local/models/` 等目录，均已预先配置，没有 recipe 负责创建；使用方式见各 demo README 与[基线测试指南](../guides/baseline-testing.md)。产品用的 ffmpeg 与研究侧用的官方 llama.cpp 在 `.local/tools/<name>/<version>/`（各带 `identity.json`），模型在 `.local/models/`；二者的版本与 SHA256 由资产清单 `assets.toml` 锁定，布局见[依赖布局与资产清单](dependencies.md)。

## 命令与门禁

Use `uv run --locked --offline ...` for product code and `{{legacy}}` recipes for frozen experiments.
Inspect the real recipe in `justfile` before invoking anything. `just --list` 列出全部 recipe。

- Safe/offline: `just check`, `just test`, `just test-full`, `just test-equivalence`, `just experiments-test`, `just translation-test`,
  `just translation-flow-test`, `just translation-flow-v2-test`, `just --list`. `just check` 只做 compileall，不等于 lint。
- 重任务（GPU、加载模型，须先问）的清单见 [AGENTS.md](../../AGENTS.md) 常驻约束；产品的真实模型验证入口是 `just smoke`。

契约 recipe：

| recipe | 当前实现 |
| --- | --- |
| `check-toolchain` | `scripts/check_toolchain.py`：核对 uv、just 与 `mise.toml`、Python 与 `.python-version` 一致；用 `uv run --no-project --no-python-downloads --offline`，不同步环境 |
| `install` | 依赖 `setup`（`uv sync --locked`），再 `scripts/assets.py install-tools`：按 `assets.toml` 安装 `tools`；已装且一致时只补缺失的 `identity.json`，否则下载 zip（缓存于 `.local/downloads/<name>/`）、解出清单文件并核对；没有压缩包 SHA256 的记录拒绝安装。联网、改环境，须先问 |
| `fetch-models` | `scripts/assets.py fetch-models`：按清单从 HF 固定 revision 下载缺失或不符的模型文件，门控模型取 `HF_TOKEN`；几十 GB、联网，须先问 |
| `verify-assets` | `scripts/assets.py verify`：离线核对 tools 与 models（大小、SHA256 经 size+mtime 缓存 `.local/cache/assets-verify.json`，tools 还要求 `identity.json`） |
| `upgrade` | `scripts/upgrade.py [组件 ...]` 后接 `test`、`test-full`、`verify-assets`：按[选版规则](dependencies.md#升级)把 Python 依赖、llama.cpp、ffmpeg 升到最新稳定版，报告写 `.local/upgrade/<UTC>/report.json`；脚本用 `uv run --no-project`，自身调用 `uv lock`／`uv sync`。联网、改环境与 `assets.toml`，须先问；不跑 smoke |
| `upgrade-check` | `scripts/upgrade.py --check`：只报告可升级项与被跳过的传递依赖主版本升级，不改文件；联网查询 PyPI 与 GitHub |
| `fmt`、`lint`、`typecheck` | 项目尚未选定格式化、lint 与类型检查工具，按契约非零退出并说明原因；不在任何 gate 内 |
| `test` | `unittest discover -s tests/core -t . -v [参数 ...]`：core 层；可追加 unittest 参数（如 `-k 名称片段`）定向运行 |
| `test-full` | `unittest discover -s tests/full -t . -v [参数 ...]`：full 层离线集成测试，不加载模型、不占 GPU、不持锁 |
| `test-equivalence` | `unittest discover -s tests/equivalence -t . -v [参数 ...]`：产品与研究实现的实时等价对照（导入 `experiments.*`，[ADR-0025](../adr/0025-product-package-boundaries.md)），不加载模型、不占 GPU、不持锁 |
| `smoke` | 真实模型验证，不属于任何 gate：`scripts/smoke/run_all.py [名称 ...]` 在独立子进程中逐项运行，加载模型、独占 GPU，每次须先经用户批准；细节见表下 |
| `docs-check` | `scripts/check_docs.py`：链接与锚点（根文档、`docs/`、`experiments/INDEX.md` 与各包 README、`.scratch/`）、模块页可达性；登记（`docs/` 每篇被某个 `INDEX.md` 或子索引链接、`experiments/` 每个包在 `experiments/INDEX.md`、`kototoki/` 每个模块在某篇模块页的"代码与验证入口"、ADR 文件与决定索引一致）；预算（`AGENTS.md`、各 `INDEX.md`、活正文的字符数与行长）；活文档里反引号包住的仓库路径存在。状态行含 3 个以上日期只告警。不检查 `docs/archive/` 归档件的链接，指向仓库之外的相对链接只计数。超标的既有文件记在脚本的 `BUDGET_WHITELIST`，只许降不许升；检查本身的单元测试在 `tests/core/test_check_docs.py` |
| `gate-core` | `check-toolchain` → `docs-check` → `check` → `test`，首错停止；只含产品测试，研究期测试 recipe 不在门禁内 |
| `gate-full` | `gate-core` 后运行 `test-full` 与 `test-equivalence`；不加载模型 |

`smoke` 的细节：

- 各项是 `scripts/smoke/<名称>.py`，列在 `scripts/smoke/run_all.py` 的 `SMOKES`，省略名称时按其顺序全跑；每项在独立子进程中以 `--out <dir>` 运行，子进程 PATH 去掉 `whisper-runtime-provisional`、设离线变量；运行期间持有 `.local/gpu.lock`，结果写 `.local/smoke/<UTC 时间>/`；每项打印开始行与结束行（PASS／FAIL、耗时、`.log` 路径），中途异常或 Ctrl+C 时先回收子进程再删锁，汇总照常打印；父进程输出编不了的字符转义，重定向到非 UTF-8 也不崩溃。
- 其中包括：三项环境 smoke（`forced_align`、`vad_pyannote`、`ct2_after_torch`；llama-server 的 `llama_stock` 随产品不再用 llama.cpp 于 2026-11-14 移除）；冻结窗口门禁 `stt_frozen_window`（见 [STT worker](../architecture/modules/stt-workers.md)）与 x0 同窗门禁 `x0_frozen_window`。
- Q2 首用 smoke `translate_product`：产品 `kototoki.translate` 的 plan → Session → `translate_document`，经 Strata 自动启停与外部前置的 Strata 0.2.12／build 0.1.58，产品配方 `q2-degrade-v1`；只记计数、哈希与耗时，见[翻译子系统](../architecture/modules/translation-subsystem.md)；运行前须没有别的 Strata launch 在服务。
- 产品专名 smoke `names_product`：产品 `kototoki.names` 的 `names_identity` → 共享 `strata.Session` → `build_document` → `write_artifact`，在产品自动启停的 Strata 上按 Q3 规则建表（配方 `q3-names-v1`，ADR-0022），输入为脚本内置的 12 条合成日语短句；通过条件含专家区锁进内存、`build.status == ok`、至少一条 person、全程无 llama-server、`--stop` 后显存释放；只记计数、哈希、耗时与资源峰值，见[专名一致性](../architecture/modules/name-consistency.md)。
- 各项实测耗时记在对应的验收记录与计划里（如[架构整理计划](../plans/architecture-cleanup.md) §7），不写在本页。

门禁边界：`lint`、`typecheck` 在选定工具前不进门禁，由 `check`（`compileall` 覆盖 `kototoki`、`kototoki_eval`、`experiments`、`scripts`、`tests`）代替；`docs-check` 不把归档件与指向相邻仓库的链接计为错误；`test` 与 `test-full` 的目录若变空，unittest 报 NO TESTS RAN 并非零退出。研究期测试 recipe 单独运行，作为回归参照。

## 测试分层与资源边界

分层标准（core 与 full 都不调用真实模型）见[测试设计与验收](../agents/testing.md#分层)；本节是目录、入口与资源合同。

- core：`tests/core/` 下的产品 `unittest` 测试，`just test` 以 `discover -s tests/core -t .` 收录（`tests/__init__.py`、`tests/core/__init__.py` 须保留，模块以 `tests.core.*` 导入）；覆盖产品包 `kototoki/` 的全部模块，各模块的测试清单与覆盖行为见其模块页"代码与验证入口"（[架构总览的模块地图](../architecture/INDEX.md#模块地图)）。进程内或本解释器子进程：GPU 阶段由 `tests/fake_worker.py` 子进程顶替、翻译用伪 server 对象／伪客户端、导入边界用 `sys.executable -c` 子进程核对；不调用外部二进制、不碰网络与 socket、不读真实视频、不加载模型。
- full：`tests/full/` 下的离线集成测试，`just test-full` 以 `discover -s tests/full -t .` 收录；用项目内 ffmpeg（`config.load` 的默认路径，`assets.toml` 锁定）合成秒级小样本：`test_media_ffmpeg`（媒体提取）与 `test_job_ffmpeg`（端到端：真实媒体阶段、fake worker 顶替 GPU 阶段、假翻译 session，检查发布结果）。不加载模型、不占 GPU，因此不需要 `.local/gpu.lock`。
- equivalence：`tests/equivalence/` 下产品实现与研究实现的实时对照（复读守卫 ↔ `asr_robustness_v15` 的 `repeat`、裁判 ↔ `quality_v5`、建表 ↔ `scene_batching_v6.v13`、翻译配方 ↔ `translation_v3`／`scene_batching_v6`），`just test-equivalence` 以 `discover -s tests/equivalence -t .` 收录；只有这一层导入 `experiments.*`。core 里的同类断言钉字面量或 sha256（注释写来源与日期），研究代码改动不会让 `just test` 失败；`tests/core` 有一条 AST 边界测试，要求 `kototoki/` 不导入 `experiments`、`kototoki_eval`，`tests/core` 自身不导入 `experiments`（[ADR-0025](../adr/0025-product-package-boundaries.md)）。不加载模型、不占 GPU。`gate-full` = `gate-core` + `test-full` + `test-equivalence`。
- `fake_worker.py` 留在 `tests/` 根，供两层共用。`just check` 编译 `kototoki`、`kototoki_eval`、`experiments`、`scripts` 与 `tests`。
- 研究期测试（只读保留，不属于产品门禁）：`experiments/tests/` 只保留评分器测试 `test_evaluator.py`（守护仍在使用的 `kototoki_eval`），与各 `experiments/*/test_*.py` 一同由 `just experiments-test` 按目录 discover，翻译相关三个 recipe 按模块列举。这些 recipe 用 `legacy` 解释器（无 NumPy 和 Torch），依赖它们的测试照旧显式跳过，在对应隔离环境中按 demo README 的 discover 命令补测；它们守护的是冻结代码，不在产品环境中运行，也不随产品依赖升级。冻结的 `experiments/translation_flow/test_v2_common_diagnostics.py` 与 `test_v2_confirmation_evaluation.py` 仍 `from tests import …` 引用旧位置，不再可导入；二者已从 `translation-flow-v2-test` 的模块列表移除，文件按冻结证据规则原样保留。
- 真实模型验证（不是测试，不属于任何 gate）：产品环境的入口是 `just smoke`（`scripts/smoke/`）；研究期 demo（W0、X0、VAD 阶段、`translation-baseline`、`translation-srt`）的 smoke 或回归仍按各 README 手动运行。每次运行都须用户批准。
- 独占资源：GPU，由 `.local/gpu.lock` 标记运行中的作业；同一时间一个作业，不抢占、不删除活跃锁，先用 PowerShell `Get-Process` 核实真实进程。产品只起 Strata（建表与翻译共用一个 session），固定占用 127.0.0.1:8080，且同一时间只允许一个 Strata launch；研究侧的 llama-server 默认也用 8080，不能与 Strata 同时运行。运行产物写入 `.local/` 下的新目录，拒绝覆盖。
- `scripts/with_lock.py`（主机锁）依赖 `fcntl`，原生 Windows 不可用，当前没有 recipe 使用它。

## 发布

<待填 按需：有发布流程时写入或链接 `../operations/`>
