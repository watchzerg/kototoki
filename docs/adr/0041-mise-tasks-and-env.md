# ADR-0041：由 mise 统一管理工具、环境变量与 task，移除 just

状态：已接受，2026-11-24（用户裁定），已实现。
替代关系：
- 取代 [ADR-0040](0040-project-mise-pins-uv-only.md) 全文（不再依赖全局 `just`）；
- 取代 [ADR-0034](0034-ubuntu-only-platform.md)「工具链分层」第 1 点中有关 `just` 与 `mise trust` 的条款，以及第 4 点中对 `just` 的核对。

范围：项目工具链入口、项目环境变量管理、命令封装与 `mise.lock`。

不改：Python 解释器由 uv 按 `.python-version`（`3.14`）管理、依赖由 `pyproject.toml` + `uv.lock` 管理、外部前置（NVIDIA 驱动、apt 系统 `ffmpeg`、Strata 0.2）、产品子进程隔离环境与配方身份。

## 决定

1. **mise 统一承担工具、环境变量与 task**，彻底移除 `just` 与根目录 `justfile`：
   - **工具**：项目 `mise.toml` 的 `[tools]` 继续只钉对版本敏感的 `uv = "0.13"`，并提交 `mise.lock` 锁住精确版本与校验和；`mise run` 自动按 `mise.toml` 与 `mise.lock` 提供工具，不再依赖 shell 激活或额外安装 `just`。
   - **环境变量**：项目公共默认值（`PYTHONUTF8 = "1"`、`HF_HUB_DISABLE_TELEMETRY = "1"`、`PYANNOTE_METRICS_ENABLED = "0"`）写在 `mise.toml` 的 `[env]`；本机私有或敏感覆盖（如门控模型下载用的 `HF_TOKEN`、可选的 `GATE_LOCK_FILE` 与 `STRATA_RUNTIME_DIR`）写在已被 `.gitignore` 忽略的 `mise.local.toml`。离线开关、动态 `<work_dir>/cache/` 的 `HF_HOME`/`TORCH_HOME` 以及一次性破死锁开关 `KOTOTOKI_BREAK_STALE_LOCK=1` 不放进 `mise.toml`，仍由产品编排／smoke 脚本按子进程注入或单次调用传入。
   - **task**：遵循兄弟项目（`setup-project`）的多 stack 布局——7 个标准 Python stack task 放在 `mise-tasks/uv/` 下（可执行 file task），由根 `mise.toml` 的公开契约 task 以 `depends = ["uv:<name>"]` 聚合；项目特有命令（`check`、`docs-check`、`docs-affected`、`gate-core`、`gate-full`、`upgrade-check`、`fetch-models`、`verify-assets`、`smoke`）定义在根 `mise.toml`，需要解析调用目录或顺序编排的 `subtitles`、`upgrade` 放在 `mise-tasks/` 下。
2. **门禁与定向参数**：
   - `mise run gate-core` 并行执行 `check-toolchain`、`docs-check`、`check`、`test`（`lint`、`typecheck` 未选定工具前不进门禁）；`mise run gate-full` 先过 `gate-core` 再在主机锁内运行 `test-full`。
   - mise 中只有 `depends` 的公开聚合 task 会忽略命令行附加参数，因此定向运行测试直接调用 `mise run uv:test -k <名称片段>` 与 `mise run uv:test-full -k <名称片段>`。
3. **无需 `mise trust`**：`mise.toml` 保持纯静态 `[tools]`、`[env]`、`[tasks]`，不使用 Tera 模板、hooks 或 `_.file`；`mise-tasks/subtitles` 通过环境变量 `MISE_ORIGINAL_CWD` 解析调用目录相对路径。

## 身份

不涉及任何配方身份。

## 依据

- 兄弟项目已统一由 `just` 迁到 `mise`（工具＋环境变量＋task 一体化），减少宿主工具数量并统一跨仓库操作体验。
- `mise.local.toml` 替代手工 export 或 `.env`，兼顾敏感变量隔离与免 `mise trust`。
- `systemd-run --user` 长任务直接调用系统 PATH 中的 `mise run subtitles <目录>`，自动注入 `[tools]` 与 `[env]`，不再依赖 user manager PATH 里的 mise shims 解析 `just`。
