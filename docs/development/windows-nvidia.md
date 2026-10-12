# Windows and NVIDIA Development

Status: accepted constraints; inference backend and compatibility matrix pending
Last updated: 2026-10-05
Scope: platform priorities, portable automation, and local GPU readiness.

## Platform priorities

Windows is the primary development and runtime target because the intended local
inference machine uses an NVIDIA RTX 5080. Validate the main execution path on native
Windows. macOS portability is desirable where practical, but support remains
unverified until exercised. WSL, Docker, Bash, and macOS-specific tooling are not
implicit prerequisites.

正式部署的最低显存、驱动／runtime 要求和完整兼容矩阵尚未确定。
当前 W0 的已测环境、模型和 Python 版本已有 [两窗原生 Windows 证据](../testing/2026-10-05-w0-demo-validation.md)。
恢复该环境或修改 W0 运行逻辑时，复用并更新 [W0 demo](../../experiments/w0_demo/README.md)，保留其本地资产和进程 DLL 加载方式。
遵循[推理选择原则](inference-selection.md)：ASR／强制对齐要求 GPU，VAD 可使用 CPU 或 GPU；
当前 demo 的 Pyannote CUDA 实测不证明新 CPU VAD 已通过。macOS 推理后端尚未选定。

## Portable commands and processes

- A shared just recipe name does not by itself make its implementation portable.
  Configure platform shells explicitly where needed and keep shell-specific
  operations small. Use Python for shared filesystem and process automation.
- Use `pathlib`, explicit text encodings, and argument lists for subprocesses.
  Exercise paths containing spaces and non-ASCII characters.
- Keep child Python processes in the same project environment; use the running
  interpreter when launching Python workers.
  X0 demo有明确例外：Qwen与MMS的已验证Transformers版本不同，使用参数指定的两个既有隔离环境，
  由轻量环境统一持有GPU锁、顺序启动并等待子进程结束；运行身份记录实际解释器和依赖。
  不为合并环境而升级依赖，入口见[X0 demo](../../experiments/x0_demo/README.md)。
- If adding multiprocessing, make worker startup safe for spawn and protect
  executable entry points. Avoid initializing models or spawning workers at import.
- Test cancellation, process cleanup, and temporary-file lifetimes on Windows
  when those features are introduced. POSIX signal handling and permissions
  alone do not establish equivalent Windows behavior.
- Avoid hardcoded drive letters, user-profile paths, or assumptions that symlinks
  and Unix commands are available on another checkout.

## GPU readiness and failure behavior

Before adopting or upgrading an inference backend, verify its published Windows
support and compatible Python, driver, and runtime requirements. Record the
verified combination and source links; require a system CUDA toolkit only if the
backend actually needs it.

A visible GPU or successful driver query does not prove that the selected backend
can execute inference. Verify model loading and a short transcription on the
requested device. Record the actual device and precision used, along with failures
such as unavailable runtime libraries or insufficient VRAM.

ASR 或强制对齐无法在 GPU 上运行时，报告可操作的错误，不回退 CPU。
分别核验各阶段的实际设备。VAD 可使用 CPU 或 GPU；记录所选设备及实测成本，
不将 CPU VAD 视为不支持的配置。

## Local environment troubleshooting

Check command resolution in the active shell before diagnosing an installation.
The user reports mise, uv, and just are installed; an inherited PATH may differ
between sessions. Inspect executable/shim resolution and project tool selection
before proposing reinstallation. Do not overwrite machine-wide configuration to
compensate for a project setup issue.
