# 批量运行与跑次记录

本文规定 agent 替用户跑产品批量（`python -m kototoki`、`just subtitles`）时怎么跑、原始产物在哪、跑完写什么记录、发现的问题怎么转成票据。运行日志的格式归[运行日志与进程原语](../architecture/modules/run-logging-and-processes.md#运行日志)，工作目录布局归[批量编排](../architecture/modules/batch-orchestration.md)，本文不重复。

## 跑之前

1. 先问：产品入口占 GPU、加载模型、可能跑数小时（AGENTS.md 常驻约束）。用户说"跑这批"即视为同意本次运行。
2. 用 `ps -p <pid>`／`pgrep` 核实没有别的 GPU 作业；`.local/gpu.lock` 存在时不抢占、不杀进程。
3. 可能超过 2 小时的运行不用 Bash 的后台运行（2 小时上限会连进程树杀掉），用 `systemd-run --user` 启动（写法见[开发工作流](../development/workflow.md#长任务与-worktree)），看产品自己的 `run-*.log` 监控进度。
4. 记下 `git rev-parse --short HEAD` 与 `git status --short` 是否为空：运行日志不记 commit，这两项只能由跑次记录补上。

## 原始产物：留在本地，不进 Git

不改默认位置。运行日志与中间产物都在工作根 `<paths.work_dir>/<输入目录末段名>-<sha12>/` 下（默认 `paths.work_dir = .local/work`；配置改了就按配置找）：

- `run-<UTC戳>.log`：运行日志，权威副本；首行带 `engine=` 与 `ffmpeg=`。
- `run-<UTC戳>-<stage>.stderr.log`：各阶段 worker 的 stderr。
- `index.json`：工作 id ↔ 输入内相对路径；`<id>/failure.json`：失败文件的失败记录。
- Strata 证据在 `strata-sessions/`。

这些文件含影片文件名与转写，只在本机分析时读，不复制进仓库。

## 跑次记录：一跑一篇，进 Git

每次批量运行结束（含中断与整批失败）后写一篇，复制 [runs/TEMPLATE.md](../../runs/TEMPLATE.md) 的骨架到 `runs/<YYYY-MM-DD>-<slug>.md`，并在 [runs/INDEX.md](../../runs/INDEX.md) 登记一行。同一天多次运行在 slug 上区分（如 `batch-2`）。

匿名规则（`scripts/check_docs.py` 拦截一部分，其余靠遵守）：

- **不写影片文件名、输入目录名、工作根目录名**，也不写含它们的路径与日志原文。
- 输入集用工作根目录名末尾的 `sha12` 指代，单个文件用工作 id（`index.json` 的键，12 位）指代；对照只在本机的 `index.json` 里。
- 不写字幕、转写、译文、专名表条目原文，不写本机绝对路径，不写 64 位哈希（commit 短 SHA 可以）。

内容只写元数据、计数与观察：版本身份、各阶段的 done／failed／耗时、按类型归并的告警与失败、资源峰值、观察到的问题。日志行要引用时只留级别、阶段与异常类型，去掉路径。

写成后不再改写结论；只允许修错、补问题的去向。

## 问题转票据

记录的"问题"一节每条都要有去向，三选一：

- **票据**：写进 `.scratch/run-findings/issues/<NN>-<slug>.md`（[tracker 约定](issue-tracker.md)），票据里写来源跑次（`runs/` 下的文件名）与涉及的工作 id；同一问题已有票据时追加 `## Comments`，不重复开票。目录不存在时先建 `spec.md`，范围写"批量运行中发现的问题"并列出票据；全部票据 resolved 后按 tracker 约定删除整个目录，下次发现问题再新建，编号接着 git 历史里用过的最大号，不复用，免得记录里的 `run-findings NN` 指向两张票。
- **不处理**：写明理由（预期行为、输入本身的问题、已知限制）。
- **待观察**：写明再出现几次或在什么条件下转票据。

记录里提到票据用纯文本（如 `run-findings 03`），不用链接：票据目录完工后会删除。修复落地后用下一次运行验证，验证结论写在新的跑次记录里，并在票据里回填。

## 跑次之间的对比

对比两次结果前先看两篇记录的版本一节：commit、engine、配置差异、`ffmpeg=` 任一不同，都要在结论里说明。续跑复用的派生 WAV 可能来自更早的 ffmpeg 构建（[ADR-0033](../adr/0033-ffmpeg-branch-lock.md)）。
