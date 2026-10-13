# 开发工作流

本文是开发命令、门禁与测试资源合同的权威正文。测试编写规则在[测试设计与验收](../agents/testing.md)。

## 环境

验证目标是原生 Windows（pwsh、RTX 5080）；macOS 未验证。mise、uv、just 由用户安装，版本固定在 `mise.toml`，解释器固定在 `.python-version`；工具分工与依赖变更规则的权威正文是 [Python 工具链](toolchain.md)，平台要求见 [Windows 与 NVIDIA](windows-nvidia.md)。

- 根环境只用于评分、编排与离线测试，没有推理依赖；`just install`（即 `just setup`，`uv sync --locked`）会改环境且可能联网，须先问用户。
- 行尾统一为 LF：`.gitattributes` 的 `* text=auto eol=lf` 让仓库存 LF、任何平台检出也是 LF（优先于 `core.autocrlf`），`.editorconfig` 让编辑器新建 LF 文件；改文件不必再做字节级保护。
- 推理后端是 `.local/envs/` 下的隔离环境，模型在 `.local/models/` 等目录，均已预先配置，没有 recipe 负责创建；使用方式见各 demo README 与[基线测试指南](../guides/baseline-testing.md)。

## 命令与门禁

Use `uv run --locked --offline ...`; the root env has no inference deps, so it cannot run
models. Inspect the real recipe in `justfile` before invoking anything. `just --list` 列出全部 recipe。

- Safe/offline: `just check`, `just test`, `just experiments-test`, `just translation-test`,
  `just translation-flow-test`, `just translation-flow-v2-test`, `just --list`. `just check` 只做 compileall，不等于 lint。
- 重任务（GPU、加载模型，须先问）的清单见 [AGENTS.md](../../AGENTS.md) 常驻约束。

契约 recipe：

| recipe | 当前实现 |
| --- | --- |
| `check-toolchain` | `scripts/check_toolchain.py`：核对 uv、just 与 `mise.toml`、Python 与 `.python-version` 一致；用 `uv run --no-project --no-python-downloads --offline`，不同步环境 |
| `install` | 依赖 `setup`（`uv sync --locked`） |
| `fmt`、`lint`、`typecheck` | 项目尚未选定格式化、lint 与类型检查工具，按契约非零退出并说明原因 |
| `test-full` | 没有自动化 full 测试，按契约非零退出；真实推理按 demo README 手动运行并先经用户批准 |
| `docs-check` | `scripts/check_docs.py`：检查根文档与 `docs/` 的本地链接、锚点、模块页可达性 |
| `gate-core` | `check-toolchain` → `docs-check` → `lint` → `typecheck` → `test`，首错停止；只含产品测试，研究期测试 recipe 不在门禁内 |
| `gate-full` | `gate-core` 后运行 `test-full` |

`gate-core` 目前不可能通过：`lint`、`typecheck` 未接入；`docs-check` 报出的历史链接错误全部位于只读的冻结证据中（指向 `.local/` 或相邻仓库）；`tests/` 为空时 `test` 按 unittest 约定报 NO TESTS RAN 并非零退出（unittest 返回 5，经 pwsh 的 just 显示为 1），第一个产品测试进入后即可通过。研究期测试 recipe 单独运行，作为回归参照。

## 测试分层与资源边界

- core：`tests/` 下的产品 `unittest` 离线测试，`just test` 以 `discover -s tests -t .` 收录（目录需保留 `tests/__init__.py`）；目前为空，等正式代码进入。
- 研究期测试（只读保留，不属于产品门禁）：原 `tests/` 下的 42 个文件已移至 `experiments/tests/`，与各 `experiments/*/test_*.py` 一同由 `just experiments-test` 按目录 discover，翻译相关三个 recipe 按模块列举。根环境没有 NumPy 和 Torch，依赖它们的测试显式跳过，在对应隔离环境中按 demo README 的 discover 命令补测。冻结的 `experiments/translation_flow/test_v2_common_diagnostics.py` 与 `test_v2_confirmation_evaluation.py` 仍 `from tests import …` 引用旧位置，不再可导入；二者已从 `translation-flow-v2-test` 的模块列表移除，文件按冻结证据规则原样保留。
- full：真实模型推理（W0、X0、VAD 阶段、`translation-baseline`、`translation-srt` 的 smoke 或回归），没有自动化测试目录，每次运行须用户批准。
- 独占资源：GPU，由 `.local/gpu.lock` 标记运行中的作业；同一时间一个作业，不抢占、不删除活跃锁，先用 PowerShell `Get-Process` 核实真实进程。llama-server 默认占用 8080 端口。运行产物写入 `.local/` 下的新目录，拒绝覆盖。
- `scripts/with_lock.py`（主机锁）依赖 `fcntl` 与 Python 3.14，原生 Windows 不可用，当前没有 recipe 使用它。

## 发布

<待填 按需：有发布流程时写入或链接 `../operations/`>
