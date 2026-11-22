# Python Toolchain

状态：current；产品根环境统一 CUDA 12.8，研究期隔离后端环境与研究代码已随 ADR-0031 退出仓库
最后更新：2026-11-22
Scope: Python tooling, dependencies, and development command ownership.

## Baseline and ownership

The user installs mise once; mise provides uv and just. The project
`mise.toml` pins only uv; just comes from the user's global mise config
(ADR-0034, ADR-0040). uv provides the Python interpreter from `.python-version`.
The repository has the product root environment (`pyproject.toml` + `uv.lock`,
CUDA 12.8 inference stack), `mise.toml`, and a `justfile`. Research-era backend
environments under `.local/envs/` are not managed by the repository; their
versions are recorded in the [STT landscape round](../research/2026-10-stt-landscape.md).

- Pin in the project `mise.toml` only tools whose exact version matters to the
  project (currently uv, which shapes `uv.lock` and `--locked` behavior). Keep
  tool versions in mise configuration rather than repeating them in prose.
- Use uv to manage the project Python interpreter, virtual environment,
  dependencies, and dependency lock. Keep the interpreter selection in
  `.python-version`, supported Python range and dependencies in `pyproject.toml`,
  and resolved dependencies in `uv.lock`.
- Use just as the common task entry point (root `justfile`). Keep
  recipes thin; delegate nontrivial portable automation to Python.
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

`just test`、`just test-full` 分别发现 `tests/core/`、`tests/full/` 下的产品测试（分层见[测试分层合同](test-layers.md#分层与资源边界)）；
根环境自票据 01 起是产品环境（Python 3.14，统一 CUDA 12.8：torch／torchaudio 2.11.0+cu128 走显式 `pytorch-cu128` 索引，其余来自 PyPI，版本见[技术选型](technology-stack.md#已选依赖)）；`just smoke` 在其中运行 `scripts/smoke/` 的真实模型验证。
`just check` 执行 Python 编译检查，不等同 lint 或类型检查。
研究期隔离环境的实际版本、锁文件范围与离线恢复入口见[环境清单](../research/2026-10-stt-landscape.md)。

When implementing the task runner, expose setup, tests, formatting, and static
checks as clear recipes and document implemented commands in the README. Use
`just --list` to discover available recipes; never claim planned recipes already
work. Preserve arguments and nonzero exit codes through every wrapper.

Keep environment setup, model downloads, and inference separate. Routine test
recipes should not upgrade dependencies or acquire model weights. Recipes must
not implicitly commit, push, or publish.

See [Ubuntu and NVIDIA](ubuntu-nvidia.md) for platform requirements and
[testing](../agents/testing.md) for verification boundaries.
