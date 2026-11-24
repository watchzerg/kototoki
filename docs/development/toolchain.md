# Python Toolchain

状态：current；产品根环境统一 CUDA 12.8，研究期隔离后端环境与研究代码已随 ADR-0031 退出仓库
最后更新：2026-11-24
Scope: Python tooling, dependencies, and development command ownership.

## Baseline and ownership

The user installs mise once; mise provides uv, manages project environment
variables (`[env]` + gitignored `mise.local.toml`), and serves as the task
runner (ADR-0034, ADR-0041). `mise.toml` pins only uv, with `mise.lock` locking
the exact version and checksums. uv provides the Python interpreter from
`.python-version`. The repository has the product root environment
(`pyproject.toml` + `uv.lock`, CUDA 12.8 inference stack), `mise.toml`,
`mise.lock`, and `mise-tasks/`. Research-era backend environments under
`.local/envs/` are not managed by the repository; their versions are recorded
in the [STT landscape round](../research/2026-10-stt-landscape.md).

- Pin in the project `mise.toml` only tools whose exact version matters to the
  project (currently uv, which shapes `uv.lock` and `--locked` behavior), and
  only to the precision that matters (uv is pinned to a minor version, `0.13`,
  with `mise.lock` locking the resolved build; `mise run check-toolchain`
  matches by version prefix). Keep tool versions in mise configuration rather
  than repeating them in prose.
- Manage shared environment defaults in `mise.toml` `[env]` and machine-local
  or secret overrides (such as `HF_TOKEN`) in gitignored `mise.local.toml`.
  Keep per-worker offline/cache variables and one-shot overrides
  (`KOTOTOKI_BREAK_STALE_LOCK`) out of `mise.toml`.
- Use uv to manage the project Python interpreter, virtual environment,
  dependencies, and dependency lock. Keep the interpreter selection in
  `.python-version`, supported Python range and dependencies in `pyproject.toml`,
  and resolved dependencies in `uv.lock`.
- Use mise tasks as the common task entry point: put stack tasks under
  `mise-tasks/uv/` and aggregate public contract tasks in root `mise.toml`.
  Keep shell tasks thin; delegate nontrivial automation to Python.
- Python applications, tests, and repository scripts should use the uv project
  environment. Avoid depending on system Python or manual venv activation.
- This is a Python project. Bun and frontend tooling are not baseline dependencies.

## Dependency changes

依赖的四层布局、版本锁定、Python 依赖变更规则与安装／编译 recipe 的权威正文是[依赖布局与资产清单](dependencies.md)。

Lint, formatting, type checking, and test tools remain to be selected during bootstrap; the
neighboring repository's selections are references, not existing installations.

## Common task interface

独立 Pyannote GPU 补测使用 `.local/envs/vad-pyannote-gpu-v1/`，与 CPU VAD 环境保持同版本依赖，
仅 Torch／TorchAudio 2.11.0 的构建由 `+cpu` 换为 `+cu128`；未升级 ASR／MMS 环境。
清单与实测边界见[GPU 补测报告](../research/2026-10-vad-comparison.md)。

`mise run test`、`mise run test-full` 分别运行 `tests/core/`、`tests/full/` 下的全部产品测试，定向筛选调用 `mise run uv:test`、`mise run uv:test-full`（分层见[测试分层合同](test-layers.md#分层与资源边界)）；
根环境自票据 01 起是产品环境（Python 3.14，统一 CUDA 12.8：torch／torchaudio 2.11.0+cu128 走显式 `pytorch-cu128` 索引，其余来自 PyPI，版本见[技术选型](technology-stack.md#已选依赖)）；`mise run smoke` 在其中运行 `scripts/smoke/` 的真实模型验证。
`mise run check` 执行 Python 编译检查，不等同 lint 或类型检查。
研究期隔离环境的实际版本、锁文件范围与离线恢复入口见[环境清单](../research/2026-10-stt-landscape.md)。

When implementing tasks, expose setup, tests, formatting, and static checks as
clear mise tasks and document implemented commands in the README. Use
`mise tasks` to discover available tasks; never claim planned tasks already
work. Preserve arguments and nonzero exit codes through every wrapper.

Keep environment setup, model downloads, and inference separate. Routine test
tasks should not upgrade dependencies or acquire model weights. Tasks must not
implicitly commit, push, or publish.

See [Ubuntu and NVIDIA](ubuntu-nvidia.md) for platform requirements and
[testing](../agents/testing.md) for verification boundaries.
