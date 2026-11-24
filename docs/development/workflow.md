# 开发工作流

本文是开发命令与门禁的权威正文；测试分层与资源合同在[测试分层合同](test-layers.md)。测试编写规则在[测试设计与验收](../agents/testing.md)。

## 环境

只面向 Ubuntu（x86_64、RTX 5080，[ADR-0034](../adr/0034-ubuntu-only-platform.md)）。用户只装 mise，mise 统一承担工具（`mise.toml` 钉 `uv`、`mise.lock` 锁精确版本）、环境变量（`[env]` 与本机私有 `mise.local.toml`）与 task（`mise-tasks/uv/` + 根 `mise.toml`，[ADR-0041](../adr/0041-mise-tasks-and-env.md)）；解释器由 uv 按 `.python-version` 提供；工具分工与依赖变更规则的权威正文是 [Python 工具链](toolchain.md)，平台要求见 [Ubuntu 与 NVIDIA](ubuntu-nvidia.md)。

- 根环境即产品环境：Python 3.14 + 统一 CUDA 12.8 推理栈（torch 2.11.0+cu128 等，版本见[技术选型](technology-stack.md#已选依赖)）。`mise run install`（`uv sync --locked`）与 `mise run fetch-models` 会改环境且可能联网，须先问用户。
- 环境变量：项目公共默认值（`PYTHONUTF8`、`HF_HUB_DISABLE_TELEMETRY`、`PYANNOTE_METRICS_ENABLED`）在 `mise.toml` 的 `[env]`；本机私有或敏感值（如门控模型下载用的 `HF_TOKEN`、可选的 `GATE_LOCK_FILE` 与 `STRATA_RUNTIME_DIR`）写进被 Git 忽略的 `mise.local.toml`。配置无模板与 hook，无需 `mise trust`。
- 行尾统一为 LF：`.gitattributes` 的 `* text=auto eol=lf` 让仓库存 LF、任何平台检出也是 LF（优先于 `core.autocrlf`），`.editorconfig` 让编辑器新建 LF 文件；改文件不必再做字节级保护。
- ffmpeg 是 apt 系统包，从 PATH 调用；模型在 `.local/models/`（清单锁 revision 与 SHA256），布局见[依赖布局与资产清单](dependencies.md)。

## 长任务与 worktree

- **长任务用 `systemd-run --user` 启动**（ADR-0034「子进程与长任务」）：整批运行与 smoke 可能超过 Claude Code 后台任务的 2 小时上限（到点连进程树被杀，2026-11-12 因此留下陈旧锁）。写法：
  `systemd-run --user --unit=kototoki-<名字> --same-dir --collect mise run subtitles <目录>`（`--same-dir` 沿用当前目录，`--collect` 失败后也清掉单元）。单元不继承当前 shell 的环境，PATH 取 user manager 的（`systemctl --user show-environment`），`/usr/bin/mise` 在系统 PATH 内，`mise run` 会自行注入 `[tools]` 与 `[env]`；`strata` 来自 `~/.local/bin`（本机 user manager PATH 已含）。
  - 看进度：产品自己的 `run-*.log`，或 `journalctl --user -u kototoki-<名字> -f`；看状态 `systemctl --user status kototoki-<名字>`。
  - 停止：`systemctl --user stop kototoki-<名字>`，整个 cgroup（编排器、worker、ffmpeg）一起收尾；Strata 服务由 `strata launch` 另起，不在其中，用 `strata launch --status` 核对。
  - 不信任工具的"已停止"，用 `ps -p <pid>`／`pgrep -f <脚本名>` 核实真实进程；多步编排链每一步幂等（产物已在则跳过、加锁），不另起替代链；要改变后续行为时改被调用的子脚本或入口，不改正在运行的脚本文件。
  - 交互调试可以用 tmux。
- **worktree 没有 `.venv`**：在 worktree 里 `uv run`／`mise run test` 会试图新建环境（联网、改环境）。在 worktree 根目录用主仓库的解释器跑测试：`<主仓库>/.venv/bin/python -m unittest discover -s tests/core -t .`（`package = false`，`kototoki` 从 cwd 导入）。并行票据各用一个 worktree、文件集合不相交。
- **核对 worktree 基底**：Agent 工具的 `isolation: worktree` 可能从落后的提交建 worktree（2026-10-19 因此在合回时覆盖了较新的改动）。开工前核对 `git log -1`，或自己用 `git worktree add --detach <path> HEAD`；合回用 `git diff <基底>` 出补丁、在主仓库 `git apply --3way`。

## 命令与门禁

Use `uv run --locked --offline ...` for product code.
Inspect the real task in `mise.toml` or `mise-tasks/` before invoking anything. `mise tasks` 列出全部 task。

- Safe/offline: `mise run check`, `mise run test`, `mise run test-full`, `mise run docs-check`, `mise tasks`. `mise run check` 只做 compileall，不等于 lint。
- 定向参数：公开聚合 task（只有 `depends`）忽略附加参数，定向筛选直接调用 stack task：`mise run uv:test -k 名称片段`、`mise run uv:test-full -k 名称片段`。
- 重任务（GPU、加载模型，须先问）的清单见 [AGENTS.md](../../AGENTS.md) 常驻约束；产品的真实模型验证入口是 `mise run smoke`。

契约与项目 task：

| task | 当前实现 |
| --- | --- |
| `check-toolchain` | 聚合 `uv:check-toolchain`（`scripts/check_toolchain.py`）：核对 `mise.toml` 钉住的工具（uv）与 `.python-version` 一致；用 `uv run --no-project --no-env-file --no-python-downloads --offline`，不同步环境 |
| `install` | 聚合 `uv:install`（`uv sync --locked`）。ffmpeg、Strata 等外部前置由用户安装，不归它。联网、改环境，须先问 |
| `fetch-models` | `scripts/assets.py fetch-models`：按清单从 HF 固定 revision 下载缺失或不符的模型文件，门控模型取 `HF_TOKEN`（可配在 `mise.local.toml`）；几十 GB、联网，须先问 |
| `verify-assets` | `scripts/assets.py verify`：离线核对模型（大小、SHA256 经 size+mtime 缓存 `.local/cache/assets-verify.json`） |
| `upgrade` | `mise-tasks/upgrade`：运行 `scripts/upgrade.py` 后依次执行 `test`、`test-full`、`verify-assets`；按[选版规则](dependencies.md#升级)升级 Python 依赖，报告写 `.local/upgrade/<UTC>/report.json`。联网、改环境，须先问；不跑 smoke |
| `upgrade-check` | `scripts/upgrade.py --check`：只报告可升级项与被跳过的传递依赖主版本升级，不改文件；联网查询 PyPI |
| `fmt`、`lint`、`typecheck` | 聚合 `uv:fmt`、`uv:lint`、`uv:typecheck`：项目尚未选定工具，按契约非零退出并说明原因；不在任何 gate 内 |
| `check` | `compileall -q kototoki scripts tests`：Python 编译检查，暂代静态检查进 `gate-core` |
| `test` | 聚合 `uv:test`（`unittest discover -s tests/core -t . -v`）：全部 core 测试；定向传参用 `mise run uv:test -k 名称片段` |
| `test-full` | 聚合 `uv:test-full`（经 `scripts/with_lock.py` 持主机锁运行 `unittest discover -s tests/full -t . -v`）：全部 full 离线集成测试，不加载模型、不占 GPU；定向传参用 `mise run uv:test-full -k 名称片段` |
| `subtitles <目录>` | `mise-tasks/subtitles`：按调用目录（`MISE_ORIGINAL_CWD`）解析路径并经 `scripts/subtitles.py` 运行默认配置产品流水线；占 GPU、加载模型，须先问 |
| `smoke [名称 ...]` | 真实模型验证，不属于任何 gate：`scripts/smoke/run_all.py [名称 ...]` 在独立子进程中逐项运行，加载模型、独占 GPU，每次须先经用户批准；细节见表下 |
| `docs-check` | `python3 scripts/check_docs.py`（[ADR-0039](../adr/0039-setup-project-docs-check.md)）：本地链接与锚点、全量可达、`docs/adr/` 与 `docs/research/` 登记索引、体量预算、模块页与行为规格骨架、`covers` 有匹配；规则见[文档维护规则·自动检查](../agents/documentation.md#自动检查) |
| `docs-affected [base]` | `python3 scripts/check_docs.py --affected`：列出相对 `base`（默认 `HEAD`）的改动命中页首 `covers` 的文档页，标出本次未修改的；只提示，总是成功，不在任何 gate 内 |
| `gate-core` | 并行运行 `check-toolchain`、`docs-check`、`check`、`test`，任一失败即失败 |
| `gate-full` | `gate-core` 通过后在主机锁内运行 `test-full`；不加载模型 |

`smoke` 的细节：

- 各项是 `scripts/smoke/<名称>.py`，列在 `scripts/smoke/run_all.py` 的 `SMOKES`，省略名称时按其顺序全跑；每项在独立子进程中以 `--out <dir>` 运行，子进程设离线变量；运行期间持有 `.local/gpu.lock`，结果写 `.local/smoke/<UTC 时间>/`；每项打印开始行与结束行（PASS／FAIL、耗时、`.log` 路径），中途异常或 Ctrl+C 时先回收子进程再删锁，汇总照常打印。
- 共三项。`ct2_after_torch`：合成音频上用产品的特征与解码函数跑一次 faster-whisper，核对 CT2 复用的 CUDA 库全部来自 `site-packages/nvidia/`。VAD、ASR、对齐的其余真实路径由小批量 `mise run subtitles` 覆盖；对照研究期冻结窗口的门禁（`stt_frozen_window` 等五项）随 ADR-0034「不比对 Windows 结果」于 2026-11-20 删除。
- Q2 首用 smoke `translate_product`：产品 `kototoki.translate` 的 plan → Session → `translate_document`，经 Strata 自动启停与外部前置的 Strata（当时 0.2.12／build 0.1.58，Windows），产品配方 `q3-translate-v1`；只记计数、哈希与耗时，见[翻译子系统](../architecture/modules/translation-subsystem.md)；运行前须没有别的 Strata launch 在服务。
- 产品专名 smoke `names_product`：产品 `kototoki.names` 的 `names_identity` → 共享 `strata.Session` → `build_document` → `write_artifact`，在产品自动启停的 Strata 上按 Q3 规则建表（配方 `q3-names-v3`，ADR-0028「建表配方」），输入为脚本内置的 12 条合成日语短句；通过条件含专家区锁进内存、`build.status == ok`、至少一条 person、全程无 llama-server、`--stop` 后显存释放；只记计数、哈希、耗时与资源峰值，见[专名一致性](../architecture/modules/name-consistency.md)。
- 各项实测耗时记在对应的验收记录里（[研究索引·验收记录](../research/INDEX.md#验收记录)），不写在本页。

门禁边界：`lint`、`typecheck` 在选定工具前不进门禁，由 `check`（`compileall` 覆盖 `kototoki`、`scripts`、`tests`）代替；`docs-check` 把指向仓库之外的链接计为错误；`test` 与 `test-full` 的目录若变空，unittest 报 NO TESTS RAN 并非零退出。

## 测试分层与资源边界

测试目录、收录入口与资源合同的权威正文在[测试分层合同](test-layers.md#分层与资源边界)。

## 发布

<待填 按需：有发布流程时写入或链接 `../operations/`>
