按 `docs/plans/architecture-cleanup.md` 完成产品包 `kototoki/` 的架构整理：把 2026-11-11 review 找到的问题逐张票据修掉（GPU 锁冲突统一成退出码 4、worker 协议读侧收进 `protocol.py`、身份 hash 补洞、Strata 额度只归 `Session`、拆 `llama_server.py`、`cross` 路径改组合、`job.py` 瘦身、offset 只在 cue 加、核心测试不再导入研究代码），最后跑一次 `just smoke` 验证。这是一次不改输出的整理：除 `MEDIA` 外任何配方 hash 都不得变，`asr.json`、`align.json`、专名表与翻译产物的字节不变。计划文档是你的全部上下文：§2 的事实不用重新调查（行号以当前源码为准），§3 的决定、§5 的门与授权、§6 不做的事，以文档为准，不自行修改。

完成标准：计划 §4 的 10 张票据全部 resolved，§5 的离线验收逐票据通过，`just smoke` 全部项通过，计划状态改为 done 并在 §7 写完成报告；或者命中 §5 的停止条件，停在当时的票据并在 §8 写明原因。

授权：只在票据 10 运行一次 `just smoke`（全部项），运行时由 smoke 自己执行 `strata launch --no-tui --model iq3_s`／`--stop`。不得运行 `python -m kototoki` 整片、任何 demo 或 `experiments.*` 的加载模型入口；不得运行 `strata update`，也不得进行任何会下载文件的 launch（`--plan` 显示下载量不为 0 时停下）；不得启动 llama-server；不得运行改环境的命令（`uv sync|add|lock`、`just setup|install|upgrade`），需要时停下写进 §8。

规则：
- 中途不问我，需要裁定的事写进计划文档 §8。
- 先在当前 `embedded-japanese-subtitles` 的提交之上新建分支 `architecture-cleanup`，全部工作在这个分支上。
- 按 `.scratch/architecture-cleanup/` 的 spec、map 建票据（tracker 约定见 `docs/agents/issue-tracker.md`），逐票据提交，每张票据完成后在计划文档 §7 加一行。
- 先写 ADR-0025 并改模块边界与模块页（票据 01），再写代码（AGENTS.md）。
- 票据 03 第一步先钉住 MEDIA、VAD、MMS、CUES、EMBEDDED 的 hash；之后任何一个不该变的 hash 或产物字节变了，停下写进 §8，不改钉住的值来让测试通过。
- 产品代码不得导入 `experiments.*`。研究代码只允许两种改动：产品符号移动或改名时改导入行；接收从产品搬出去的 llama-server 生命周期代码及其测试。不改研究代码的行为，不改冻结证据与既有 ADR 正文（旧 ADR 只追加状态行）。基线 Q3 的实现（`experiments/translation_v3/strata.py`、`experiments/scene_batching_v6/v13.py`）改完导入后，其离线测试必须仍通过。
- `just gate-core` 按契约不可能通过：逐项跑 `check-toolchain`、`docs-check`、`test`；`docs-check` 在 main 上本就有 44 处冻结外链失败，只看新增条目。
- GPU 运行前核实：没有 llama-server、没有其他 GPU 作业或 Strata 实例（`Get-Process`），读 `.local/gpu.lock`，可用内存 ≥52 GiB；不抢占、不杀进程、不关我的程序。结束后核实 `strata launch --status` 为空、显存已释放。
- 子 agent 显式指定 model（默认 sonnet，复杂设计或细微 debug 用 opus，不用 Fable），写入者文件互不重叠；并行票据各用独立 worktree。
- 不推送、不开 PR；提交信息用中文，不绕过签名，签名失败就停下写进 §8。
- 结束时完成报告区分已实现、自动检查、GPU 结果、未验证项。
