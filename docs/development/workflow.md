# 开发工作流

本文是开发命令、门禁与测试资源合同的权威正文。测试编写规则在[测试设计与验收](../agents/testing.md)。

## 环境

只面向 Ubuntu（x86_64、RTX 5080，[ADR-0034](../adr/0034-ubuntu-only-platform.md)）。mise、uv、just 由用户安装，版本固定在 `mise.toml`，解释器固定在 `.python-version`；工具分工与依赖变更规则的权威正文是 [Python 工具链](toolchain.md)，平台要求见 [Ubuntu 与 NVIDIA](ubuntu-nvidia.md)。

- 根环境即产品环境：Python 3.14 + 统一 CUDA 12.8 推理栈（torch 2.11.0+cu128 等，版本见[技术选型](technology-stack.md#已选依赖)）。`just install`（`uv sync --locked`）与 `just fetch-models` 会改环境且可能联网，须先问用户。
- 行尾统一为 LF：`.gitattributes` 的 `* text=auto eol=lf` 让仓库存 LF、任何平台检出也是 LF（优先于 `core.autocrlf`），`.editorconfig` 让编辑器新建 LF 文件；改文件不必再做字节级保护。
- ffmpeg 是 apt 系统包，从 PATH 调用；模型在 `.local/models/`（清单锁 revision 与 SHA256），布局见[依赖布局与资产清单](dependencies.md)。

## 长任务与 worktree

- **长任务用 `systemd-run --user` 启动**（ADR-0034「子进程与长任务」）：整批运行与 smoke 可能超过 Claude Code 后台任务的 2 小时上限（到点连进程树被杀，2026-11-12 因此留下陈旧锁）。写法：
  `systemd-run --user --unit=kototoki-<名字> --same-dir --collect just subtitles <目录>`（`--same-dir` 沿用当前目录，`--collect` 失败后也清掉单元）。单元不继承当前 shell 的环境，PATH 取 user manager 的（`systemctl --user show-environment`），本机已含 mise shims 与 `~/.local/bin`，`just`、`strata` 都能解析（2026-11-20 核实）。
  - 看进度：产品自己的 `run-*.log`，或 `journalctl --user -u kototoki-<名字> -f`；看状态 `systemctl --user status kototoki-<名字>`。
  - 停止：`systemctl --user stop kototoki-<名字>`，整个 cgroup（编排器、worker、ffmpeg）一起收尾；Strata 服务由 `strata launch` 另起，不在其中，用 `strata launch --status` 核对。
  - 不信任工具的"已停止"，用 `ps -p <pid>`／`pgrep -f <脚本名>` 核实真实进程；多步编排链每一步幂等（产物已在则跳过、加锁），不另起替代链；要改变后续行为时改被调用的子脚本或入口，不改正在运行的脚本文件。
  - 交互调试可以用 tmux。
- **worktree 没有 `.venv`**：在 worktree 里 `uv run`／`just test` 会试图新建环境（联网、改环境）。在 worktree 根目录用主仓库的解释器跑测试：`<主仓库>/.venv/bin/python -m unittest discover -s tests/core -t .`（`package = false`，`kototoki` 从 cwd 导入）。并行票据各用一个 worktree、文件集合不相交。
- **核对 worktree 基底**：Agent 工具的 `isolation: worktree` 可能从落后的提交建 worktree（2026-10-19 因此在合回时覆盖了较新的改动）。开工前核对 `git log -1`，或自己用 `git worktree add --detach <path> HEAD`；合回用 `git diff <基底>` 出补丁、在主仓库 `git apply --3way`。

## 命令与门禁

Use `uv run --locked --offline ...` for product code.
Inspect the real recipe in `justfile` before invoking anything. `just --list` 列出全部 recipe。

- Safe/offline: `just check`, `just test`, `just test-full`, `just docs-check`, `just --list`. `just check` 只做 compileall，不等于 lint。
- 重任务（GPU、加载模型，须先问）的清单见 [AGENTS.md](../../AGENTS.md) 常驻约束；产品的真实模型验证入口是 `just smoke`。

契约 recipe：

| recipe | 当前实现 |
| --- | --- |
| `check-toolchain` | `scripts/check_toolchain.py`：核对 uv、just 与 `mise.toml`、Python 与 `.python-version` 一致；用 `uv run --no-project --no-python-downloads --offline`，不同步环境 |
| `install` | `uv sync --locked`。ffmpeg、Strata 等外部前置由用户安装，不归它。联网、改环境，须先问 |
| `fetch-models` | `scripts/assets.py fetch-models`：按清单从 HF 固定 revision 下载缺失或不符的模型文件，门控模型取 `HF_TOKEN`；几十 GB、联网，须先问 |
| `verify-assets` | `scripts/assets.py verify`：离线核对模型（大小、SHA256 经 size+mtime 缓存 `.local/cache/assets-verify.json`） |
| `upgrade` | `scripts/upgrade.py` 后接 `test`、`test-full`、`verify-assets`：按[选版规则](dependencies.md#升级)把 Python 依赖升到最新稳定版，报告写 `.local/upgrade/<UTC>/report.json`；脚本用 `uv run --no-project`，自身调用 `uv lock`／`uv sync`。联网、改环境，须先问；不跑 smoke |
| `upgrade-check` | `scripts/upgrade.py --check`：只报告可升级项与被跳过的传递依赖主版本升级，不改文件；联网查询 PyPI |
| `fmt`、`lint`、`typecheck` | 项目尚未选定格式化、lint 与类型检查工具，按契约非零退出并说明原因；不在任何 gate 内 |
| `test` | `unittest discover -s tests/core -t . -v [参数 ...]`：core 层；可追加 unittest 参数（如 `-k 名称片段`）定向运行 |
| `test-full` | `unittest discover -s tests/full -t . -v [参数 ...]`：full 层离线集成测试，不加载模型、不占 GPU、不持锁 |
| `smoke` | 真实模型验证，不属于任何 gate：`scripts/smoke/run_all.py [名称 ...]` 在独立子进程中逐项运行，加载模型、独占 GPU，每次须先经用户批准；细节见表下 |
| `docs-check` | `scripts/check_docs.py`：链接与锚点（根文档、`docs/`、`research/`、`.scratch/`）、模块页可达性；登记（`docs/` 每篇被某个 `INDEX.md` 链接、`research/` 每个轮次 README 与验收记录在 `research/INDEX.md`、`kototoki/` 每个模块在某篇模块页的"代码与验证入口"、ADR 文件与决定索引一致）；预算（`AGENTS.md`、各 `INDEX.md`、活正文的字符数与行长）；活文档里反引号包住的仓库路径存在；研究记录（[ADR-0031](../adr/0031-research-layout-and-lightweight-records.md) R8）：轮次 README 与验收记录的必填标题、`research/` 无 64 位十六进制串、`research/`／`docs/`／`tests/` 无盘符绝对路径（测试虚构路径在 `ALLOWED_ABSOLUTE_PATHS` 登记）。状态行含 3 个以上日期只告警。指向仓库之外的相对链接只计数。超标的既有文件记在脚本的 `BUDGET_WHITELIST`，只许降不许升；检查本身的单元测试在 `tests/core/test_check_docs.py` |
| `gate-core` | `check-toolchain` → `docs-check` → `check` → `test`，首错停止 |
| `gate-full` | `gate-core` 后运行 `test-full`；不加载模型 |

`smoke` 的细节：

- 各项是 `scripts/smoke/<名称>.py`，列在 `scripts/smoke/run_all.py` 的 `SMOKES`，省略名称时按其顺序全跑；每项在独立子进程中以 `--out <dir>` 运行，子进程设离线变量；运行期间持有 `.local/gpu.lock`，结果写 `.local/smoke/<UTC 时间>/`；每项打印开始行与结束行（PASS／FAIL、耗时、`.log` 路径），中途异常或 Ctrl+C 时先回收子进程再删锁，汇总照常打印。
- 共三项。`ct2_after_torch`：合成音频上用产品的特征与解码函数跑一次 faster-whisper，核对 CT2 复用的 CUDA 库全部来自 `site-packages/nvidia/`。VAD、ASR、对齐的其余真实路径由小批量 `just subtitles` 覆盖；对照研究期冻结窗口的门禁（`stt_frozen_window` 等五项）随 ADR-0034「不比对 Windows 结果」于 2026-11-20 删除。
- Q2 首用 smoke `translate_product`：产品 `kototoki.translate` 的 plan → Session → `translate_document`，经 Strata 自动启停与外部前置的 Strata（当时 0.2.12／build 0.1.58，Windows），产品配方 `q3-translate-v1`；只记计数、哈希与耗时，见[翻译子系统](../architecture/modules/translation-subsystem.md)；运行前须没有别的 Strata launch 在服务。
- 产品专名 smoke `names_product`：产品 `kototoki.names` 的 `names_identity` → 共享 `strata.Session` → `build_document` → `write_artifact`，在产品自动启停的 Strata 上按 Q3 规则建表（配方 `q3-names-v3`，ADR-0028「建表配方」），输入为脚本内置的 12 条合成日语短句；通过条件含专家区锁进内存、`build.status == ok`、至少一条 person、全程无 llama-server、`--stop` 后显存释放；只记计数、哈希、耗时与资源峰值，见[专名一致性](../architecture/modules/name-consistency.md)。
- 各项实测耗时记在对应的验收记录里（[研究索引·验收记录](../../research/INDEX.md#验收记录)），不写在本页。

门禁边界：`lint`、`typecheck` 在选定工具前不进门禁，由 `check`（`compileall` 覆盖 `kototoki`、`scripts`、`tests`）代替；`docs-check` 不把指向相邻仓库的链接计为错误；`test` 与 `test-full` 的目录若变空，unittest 报 NO TESTS RAN 并非零退出。

## 测试分层与资源边界

分层标准（core 与 full 都不调用真实模型）见[测试设计与验收](../agents/testing.md#分层)；本节是目录、入口与资源合同。

- core：`tests/core/` 下的产品 `unittest` 测试，`just test` 以 `discover -s tests/core -t .` 收录（`tests/__init__.py`、`tests/core/__init__.py` 须保留，模块以 `tests.core.*` 导入）；覆盖产品包 `kototoki/` 的全部模块，各模块的测试清单与覆盖行为见其模块页"代码与验证入口"（[架构总览的模块地图](../architecture/INDEX.md#模块地图)）。进程内或本解释器子进程：GPU 阶段由 `tests/fake_worker.py` 子进程顶替、翻译用伪 server 对象／伪客户端、导入边界用 `sys.executable -c` 子进程核对；不调用外部二进制、不碰网络与 socket、不读真实视频、不加载模型。
- full：`tests/full/` 下的离线集成测试，`just test-full` 以 `discover -s tests/full -t .` 收录；用系统 ffmpeg（`config.load` 默认从 PATH 查找）合成秒级小样本：`test_media_ffmpeg`（媒体提取）与 `test_job_ffmpeg`（端到端：真实媒体阶段、fake worker 顶替 GPU 阶段、假翻译 session，检查发布结果）。不加载模型、不占 GPU，因此不需要 `.local/gpu.lock`；经 `scripts/with_lock.py` 持主机级锁（默认 `~/.cache/gate-full.lock`，`flock`）串行，不同 worktree 同时跑不互相干扰。
- 没有产品与研究实现的实时对照层：研究直接调用产品实现；core 里需要钉住的取值以字面量钉，注释写来源（ADR 或归档 tag 路径）；`tests/core/test_boundaries.py` 以 AST 扫描要求 `kototoki/` 不导入 `research`，`tests/core` 自身不导入 `research`（[ADR-0031](../adr/0031-research-layout-and-lightweight-records.md)、[ADR-0025](../adr/0025-product-package-boundaries.md)）。`gate-full` = `gate-core` + `test-full`。
- `fake_worker.py` 留在 `tests/` 根，供两层共用。`just check` 编译 `kototoki`、`scripts` 与 `tests`。
- 真实模型验证（不是测试，不属于任何 gate）：入口是 `just smoke`（`scripts/smoke/`），每次运行都须用户批准。
- 独占资源：GPU，由 `.local/gpu.lock` 标记运行中的作业；同一时间一个作业，不抢占、不删除活跃锁，先用 `ps -p <pid>`／`pgrep` 核实真实进程。产品只起 Strata（建表与翻译共用一个 session），固定占用 127.0.0.1:8080，且同一时间只允许一个 Strata launch；llama-server 默认也用 8080，不能与 Strata 同时运行。运行产物写入 `.local/` 下的新目录，拒绝覆盖。

## 发布

<待填 按需：有发布流程时写入或链接 `../operations/`>
