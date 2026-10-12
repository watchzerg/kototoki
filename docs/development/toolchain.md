# Python Toolchain

状态：轻量工具链及隔离后端环境已建立，实测证据与安装状态分别记录
最后更新：2026-10-05
Scope: Python tooling, dependencies, and development command ownership.

当前W0／X0测试的环境选择、标准命令和结果核验统一见[基线测试指南](../guides/baseline-testing.md)。

## Baseline and ownership

The user has installed mise, uv, and just on the Windows development machine.
Installed tools do not imply that project configuration or recipes exist.
The repository now has a lightweight Python evaluation environment, `uv.lock`,
`mise.toml`, and a `justfile`. Backend environments remain separate experiments;
see [execution record](../context/2026-10-04-demo-execution.md).

- Use mise to select project development tools, including uv and just, once
  project pins are configured. Keep tool versions in mise configuration rather
  than repeating them in prose.
- Use uv to manage the project Python interpreter, virtual environment,
  dependencies, and dependency lock. Keep the interpreter selection in
  `.python-version`, supported Python range and dependencies in `pyproject.toml`,
  and resolved dependencies in `uv.lock` once bootstrapped.
- Use just as the common task entry point once a root `justfile` exists. Keep
  recipes thin; delegate nontrivial portable automation to Python.
- Python applications, tests, and repository scripts should use the uv project
  environment. Avoid depending on system Python or manual venv activation.
- This is a Python project. Bun and frontend tooling are not baseline dependencies.

## Dependency changes

Use uv to add, remove, resolve, and synchronize dependencies; commit the manifest
and lock changes together. Normal setup should consume the committed resolution;
dependency upgrades should be deliberate, separately identifiable changes.
For new selections and deliberate upgrades, apply the latest-stable baseline in
[inference selection principles](inference-selection.md) to supporting components
and development tools as well; retain reproducible version locks after selection.

Choose the Python version after checking the selected inference backend's Windows
and NVIDIA compatibility. Document package sources and platform-specific
dependency selections when adding the backend. Do not transplant CUDA package
versions, indexes, or dependencies from another project.

Keep development dependencies separate from runtime dependencies. Introduce
optional backend-specific groups only when the chosen GPU backend needs them.
Follow [inference selection](inference-selection.md) when evaluating engines,
models, and aligners. Lint, formatting,
type checking, and test tools remain to be selected during bootstrap; the
neighboring repository's selections are references, not existing installations.

## Common task interface

独立 Pyannote GPU 补测使用 `.local/envs/vad-pyannote-gpu-v1/`，与 CPU VAD 环境保持同版本依赖，
仅 Torch／TorchAudio 2.11.0 的构建由 `+cpu` 换为 `+cu128`；未升级 ASR／MMS 环境。
清单与实测边界见[GPU 补测报告](../research/2026-10-05-pyannote-gpu-comparison.md)。

当前 `just test` 覆盖评测器、语料、资产准备、各后端适配器、日语 CTC 映射与批次契约、W0／X0 可复用 demo、显示、实验汇总和性能汇总的离线测试；
可选后端依赖未安装在根环境时，相关测试显式跳过，并在对应固定后端环境单独验证。
`just check` 执行 Python 编译检查，不等同 lint 或类型检查。
实际版本、锁文件范围与离线恢复入口见[环境清单](../research/2026-10-04-runtime-inventory.md)。

运行或开发当前 W0 时，复用并更新 [W0 demo](../../experiments/w0_demo/README.md)；
该说明维护隔离推理环境、已获取资产的复制校验和运行入口。根环境测试与后端数值测试分开执行，
不要把旧 Whisper runner 或重新安装环境当成新 session 的起点。

当前 X0 使用 [X0 demo](../../experiments/x0_demo/README.md) 和 `just x0-demo`，由轻量环境顺序调用既有
Qwen／MMS隔离环境。正常运行不需要同步或升级后端依赖；源码、环境身份和各子进程成本随结果保存。

When implementing the task runner, expose setup, tests, formatting, and static
checks as clear recipes and document implemented commands in the README. Use
`just --list` to discover available recipes; never claim planned recipes already
work. Preserve arguments and nonzero exit codes through every wrapper.

Keep environment setup, model downloads, and inference separate. Routine test
recipes should not upgrade dependencies or acquire model weights. Recipes must
not implicitly commit, push, or publish.

See [Windows and NVIDIA](windows-nvidia.md) for platform requirements and
[validation](../testing/validation.md) for verification boundaries.
