# 开发工作流

本文是开发命令、门禁与测试资源合同的权威正文。测试编写规则在[测试设计与验收](../agents/testing.md)。

## 环境

验证目标是原生 Windows（pwsh、RTX 5080）；macOS 未验证。mise、uv、just 由用户安装，版本固定在 `mise.toml`，解释器固定在 `.python-version`；工具分工与依赖变更规则的权威正文是 [Python 工具链](toolchain.md)，平台要求见 [Windows 与 NVIDIA](windows-nvidia.md)。

- 根环境即产品环境：Python 3.13 + 统一 CUDA 12.8 推理栈（torch 2.11.0+cu128 等，版本见[技术选型](technology-stack.md#已选依赖)）。`just install`（即 `just setup`，`uv sync --locked`）会改环境且可能联网，须先问用户。
- 冻结的 `experiments` recipe 不用产品环境，而用 `justfile` 的 `legacy` 解释器（`uv run --no-project --python 3.12`，等同原来无依赖的根环境），保持其原有跳过行为与运行身份。
- 行尾统一为 LF：`.gitattributes` 的 `* text=auto eol=lf` 让仓库存 LF、任何平台检出也是 LF（优先于 `core.autocrlf`），`.editorconfig` 让编辑器新建 LF 文件；改文件不必再做字节级保护。
- 研究期 demo 的推理后端是 `.local/envs/` 下的隔离环境，模型在 `.local/models/` 等目录，均已预先配置，没有 recipe 负责创建；使用方式见各 demo README 与[基线测试指南](../guides/baseline-testing.md)。官方 llama.cpp b11583 在 `.local/tools/llama.cpp/b11583-cuda13.4/`（`identity.json` 记录来源与 SHA256）。

## 命令与门禁

Use `uv run --locked --offline ...` for product code and `{{legacy}}` recipes for frozen experiments.
Inspect the real recipe in `justfile` before invoking anything. `just --list` 列出全部 recipe。

- Safe/offline: `just check`, `just test`, `just test-full`, `just experiments-test`, `just translation-test`,
  `just translation-flow-test`, `just translation-flow-v2-test`, `just --list`. `just check` 只做 compileall，不等于 lint。
- 重任务（GPU、加载模型，须先问）的清单见 [AGENTS.md](../../AGENTS.md) 常驻约束；产品的真实模型验证入口是 `just smoke`。

契约 recipe：

| recipe | 当前实现 |
| --- | --- |
| `check-toolchain` | `scripts/check_toolchain.py`：核对 uv、just 与 `mise.toml`、Python 与 `.python-version` 一致；用 `uv run --no-project --no-python-downloads --offline`，不同步环境 |
| `install` | 依赖 `setup`（`uv sync --locked`） |
| `fmt`、`lint`、`typecheck` | 项目尚未选定格式化、lint 与类型检查工具，按契约非零退出并说明原因 |
| `test` | `unittest discover -s tests/core -t . -v [参数 ...]`：core 层；可追加 unittest 参数（如 `-k 名称片段`）定向运行 |
| `test-full` | `unittest discover -s tests/full -t . -v [参数 ...]`：full 层离线集成测试，不加载模型、不占 GPU、不持锁 |
| `smoke` | 真实模型验证，不属于任何 gate：`scripts/smoke/run_all.py [名称 ...]`，四项环境 smoke（`forced_align`、`vad_pyannote`、`ct2_after_torch`、`llama_stock`）与票据 03 的冻结窗口门禁 `stt_frozen_window`（见 [STT worker](../architecture/modules/stt-workers.md)）及票据 07 的 x0 同窗门禁 `x0_frozen_window`，每项是 `scripts/smoke/<名称>.py`，在独立子进程中以 `--out <dir>` 运行，子进程 PATH 去掉 `whisper-runtime-provisional`、离线变量；运行期间持有 `.local/gpu.lock`，结果写 `.local/smoke/<UTC 时间>/`。**加载模型、独占 GPU，四项 smoke 约 3 分钟（2026-10-14 实测 2.5 分钟），`stt_frozen_window` 约 1–2 分钟（2026-10-14 实测三阶段合计约 65 s，不含首次模型哈希），`x0_frozen_window` 预计 2–3 分钟；每次须先经用户批准** |
| `docs-check` | `scripts/check_docs.py`：检查根文档与 `docs/` 的本地链接、锚点、模块页可达性 |
| `gate-core` | `check-toolchain` → `docs-check` → `lint` → `typecheck` → `test`，首错停止；只含产品测试，研究期测试 recipe 不在门禁内 |
| `gate-full` | `gate-core` 后运行 `test-full`；不加载模型 |

`gate-core` 目前不可能通过：`lint`、`typecheck` 未接入；`docs-check` 报出的历史链接错误全部位于只读的冻结证据中（指向 `.local/` 或相邻仓库）；`test` 与 `test-full` 已有产品测试并可通过（目录若再变空，unittest 报 NO TESTS RAN 并非零退出）。研究期测试 recipe 单独运行，作为回归参照。

## 测试分层与资源边界

分层标准（core 与 full 都不调用真实模型）见[测试设计与验收](../agents/testing.md#分层)；本节是目录、入口与资源合同。

- core：`tests/core/` 下的产品 `unittest` 测试，`just test` 以 `discover -s tests/core -t .` 收录（`tests/__init__.py`、`tests/core/__init__.py` 须保留，模块以 `tests.core.*` 导入）；覆盖产品包 `kototoki/` 的全部模块，各模块的测试清单与覆盖行为见其模块页"代码与验证入口"（[架构总览的模块地图](../architecture/INDEX.md#模块地图)）。进程内或本解释器子进程：GPU 阶段由 `tests/fake_worker.py` 子进程顶替、翻译用伪 server 对象／伪客户端、导入边界用 `sys.executable -c` 子进程核对；不调用外部二进制、不碰网络与 socket、不读真实视频、不加载模型。整套 332 个用例约 36 s（2026-10-18 实测 36.1 s），其中编排测试因启动伪 worker 子进程约 30 s。
- full：`tests/full/` 下的离线集成测试，`just test-full` 以 `discover -s tests/full -t .` 收录；用 ffmpeg（`config.load` 的默认路径）合成秒级小样本：`test_media_ffmpeg`（媒体提取）与 `test_job_ffmpeg`（端到端：真实媒体阶段、fake worker 顶替 GPU 阶段、假翻译 session，检查三份 SRT 发布）。不加载模型、不占 GPU，因此不需要 `.local/gpu.lock`。整套 11 个用例约 3.3 s（2026-10-18 实测）。`gate-full` = `gate-core` + `test-full`。
- `fake_worker.py` 留在 `tests/` 根，供两层共用。`just check` 编译 `kototoki`、`kototoki_eval` 与 `experiments`。
- 研究期测试（只读保留，不属于产品门禁）：`experiments/tests/` 只保留评分器测试 `test_evaluator.py`（守护仍在使用的 `kototoki_eval`；其余 41 个 Codex 时代测试于 2026-10-14 经用户决定删除），与各 `experiments/*/test_*.py` 一同由 `just experiments-test` 按目录 discover，翻译相关三个 recipe 按模块列举。这些 recipe 用 `legacy` 解释器（无 NumPy 和 Torch），依赖它们的测试照旧显式跳过，在对应隔离环境中按 demo README 的 discover 命令补测；它们守护的是冻结代码，不在产品环境中运行，也不随产品依赖升级。冻结的 `experiments/translation_flow/test_v2_common_diagnostics.py` 与 `test_v2_confirmation_evaluation.py` 仍 `from tests import …` 引用旧位置，不再可导入；二者已从 `translation-flow-v2-test` 的模块列表移除，文件按冻结证据规则原样保留。
- 真实模型验证（不是测试，不属于任何 gate）：产品环境的入口是 `just smoke`（`scripts/smoke/`）；研究期 demo（W0、X0、VAD 阶段、`translation-baseline`、`translation-srt`）的 smoke 或回归仍按各 README 手动运行。每次运行都须用户批准。
- 独占资源：GPU，由 `.local/gpu.lock` 标记运行中的作业；同一时间一个作业，不抢占、不删除活跃锁，先用 PowerShell `Get-Process` 核实真实进程。llama-server 默认占用 8080 端口。运行产物写入 `.local/` 下的新目录，拒绝覆盖。
- `scripts/with_lock.py`（主机锁）依赖 `fcntl` 与 Python 3.14，原生 Windows 不可用，当前没有 recipe 使用它。

## 发布

<待填 按需：有发布流程时写入或链接 `../operations/`>
