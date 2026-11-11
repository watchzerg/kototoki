按 `docs/plans/product-names-on-strata.md` 把产品 `kototoki/` 的 names 建表切到基线 Q3（ADR-0021）：在 Strata 上用 Qwen3.8-Flash-Next 建表，规则与 `names-strata-v4` 逐字节一致（最多 5 次请求、取第一张合格的表）；names 与 translate 共用同一个 Strata session，整批只启动一次，产品不再启动 llama-server、不再加载 27B。计划文档是你的全部上下文：其中 §3 的决定、§5 的门与授权、§6 不做的事，以文档为准，不自行修改。

授权：只在 §4 第 6 张票据（GPU 验证）里运行 `just smoke names_product`（改为走 Strata 之后）和一部产品整片 `python -m kototoki`（HF-II，W0，全新工作目录与输出位置）；运行时由产品或 smoke 自己执行 `strata launch --no-tui --model iq3_s`／`--stop`。不得运行 `strata update`，也不得进行任何会下载文件的 launch（`--plan` 显示下载量不为 0 时停下）；不得启动 llama-server；不得运行改环境的命令（`uv sync|add|lock`、`just setup|install|upgrade`），需要时停下写进 §8。

规则：
- 中途不问我，需要裁定的事写进计划文档 §8。
- 按 `.scratch/q3-product-switch/` 建 spec、map、票据（tracker 约定见 `docs/agents/issue-tracker.md`），逐票据提交，每张票据完成后在计划文档 §7 加一行。
- 先写 ADR-0022 并改模块边界与模块页，再写代码（AGENTS.md）。
- 每次 GPU 运行前核实：没有 llama-server、没有其他 GPU 作业或 Strata 实例（`Get-Process`），读 `.local/gpu.lock`，可用内存 ≥52 GiB；不抢占、不杀进程、不关我的程序。Strata 启动后确认专家区全部锁进内存，退到 mmap 就停下写进 §8。结束后核实 `strata launch --status` 为空、显存已释放。
- 产品代码不得导入 `experiments.*`，测试可以导入它作逐字节对照。不改 `experiments/`、冻结证据与 ADR-0021 正文。
- 子 agent 显式指定 model（默认 sonnet，不用 Fable），写入者文件互不重叠。
- 不推送、不开 PR；提交信息用中文，不绕过签名，签名失败就停下写进 §8。
- 结束时计划文档状态改为 done（或写明停在哪里），完成报告区分已实现、自动检查、GPU 结果、未验证项。
