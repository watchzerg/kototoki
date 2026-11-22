# Ubuntu 与 NVIDIA

状态：现行约束（[ADR-0034](../adr/0034-ubuntu-only-platform.md)）；推理后端兼容矩阵未定
最后更新：2026-11-22
范围：平台、进程与路径写法、本机 GPU 就绪检查。

## 平台

只面向 Ubuntu（x86_64、NVIDIA GPU，本机为 RTX 5080），不支持 Windows 与 macOS。2026-11 从原生 Windows 迁来，Windows 时期的验收与跑次只作历史，不作对照（ADR-0034「平台」）。

正式部署的最低显存、驱动与运行库要求尚未确定。遵循[推理选型原则](inference-selection.md)：ASR／强制对齐要求 GPU，VAD 可用 CPU 或 GPU；研究期 Pyannote CUDA 实测不证明 CPU VAD 已通过。研究期 W0 demo 的两窗证据见 [STT demo 轮次](../research/2026-10-stt-demo-w0-x0.md)。

## 进程与路径

- recipe 走 just 默认的 sh，shell 片段保持很小；文件系统与进程操作写在 Python 里。
- 子进程用参数列表，文本显式指定 UTF-8。路径是字节序列：测试覆盖空格与非 ASCII 名，`:`、`\` 等都是合法文件名字符，不按 Windows 规则拒绝或改写。
- Python 子进程用运行中的解释器（`sys.executable`），留在同一项目环境。
- 子进程收尾用 PDEATHSIG 与进程组（[运行日志与进程](../architecture/modules/run-logging-and-processes.md)）；长任务用 `systemd-run --user`（[开发工作流](workflow.md#长任务与-worktree)）。
- 不写死用户目录或数据盘路径，文档与测试里也不写 `/home`、`/data`、`/mnt`、`/media` 下的本机路径（没有机械检查）。

## GPU 就绪与失败

采用或升级推理后端前，核实它在 Linux x86_64 上的 wheel 与所需 Python、驱动、CUDA 运行库组合，记录核实过的组合与来源；只有后端确实需要时才要求系统 CUDA toolkit。本项目的 CUDA 运行库来自 `nvidia-*-cu12` wheel（[技术选型](technology-stack.md)）。

能看到 GPU 或 `nvidia-smi` 成功不等于后端能推理：要在指定设备上加载模型并跑一小段转写，记录实际设备与精度，以及缺运行库、显存不足等失败。

ASR 或强制对齐无法在 GPU 上运行时，报告可操作的错误，不回退 CPU。分别核验各阶段的实际设备。VAD 可使用 CPU 或 GPU；记录所选设备及实测成本，不将 CPU VAD 视为不支持的配置。

## 本机环境排查

诊断安装问题前先查当前 shell 的命令解析：mise 由用户安装，uv、just 由 mise 提供，不同会话继承的 PATH 可能不同。先看可执行文件／shim 的解析与项目的工具选择，再考虑重装；不为项目配置问题改动全机配置。
