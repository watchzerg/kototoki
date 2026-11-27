---
covers:
  - kototoki/logs.py
  - kototoki/procs.py
  - kototoki/job.py
  - kototoki/workers/protocol.py
---
# 运行日志、进程原语与 worker 子进程

状态：current；权威决定：[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责三块基础设施：

- 产品运行日志的目的地、行格式、级别与内容规则（`kototoki/logs.py` 的格式，挂接在 `job._run_logging`）
- 进程原语——进程存活与身份、子进程随编排器退出、O_EXCL 锁文件（`kototoki/procs.py`）
- 编排启动 GPU worker 子进程的命令、环境与崩溃判定（`job._launch`、`job.run_gpu_stage`、`workers/protocol.classify_launch`）。

流程中何时取哪把锁、哪些文件进哪个阶段归[批次编排](batch-orchestration.md)；worker 内部归 [STT worker](stt-workers.md)；各模块具体写哪些日志行见各自模块页。模块边界只规定日志目的地与格式归编排（[责任边界](../module-boundaries.md#产品包的责任边界)），本页是这些规则的正文。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

### 子页

| 子页 | 何时读 |
| --- | --- |
| [运行日志](run-logging-and-processes/run-log.md) | 改日志目的地、行格式、级别、内容规则，或各阶段日志行时 |
| [进程原语](run-logging-and-processes/process-primitives.md) | 改进程身份、锁文件（`ProcessLock`）或子进程随编排器退出（`contained`）时 |
| [worker 子进程](run-logging-and-processes/worker-subprocess.md) | 改 worker 的命令、jobs、子进程环境、进度事件转日志或崩溃重启时 |

## 当前行为规格

行为规格按主题写在各子页，见上方子页表。

## 实现设计

实现设计随各子页的行为规格一并描述，跨子页共用的依赖见下节。

## 接口与依赖

`workers/protocol` 的 jobs 读写与 `classify_launch` 是编排与 worker 之间的协议（[产物契约](artifact-contract.md)、[STT worker](stt-workers.md)）。`logs` 只依赖标准库；`procs` 只依赖标准库与基础层 `artifacts`（锁内容的时间戳与原子改写）。二者属基础层，与流水线无关。使用方：`kototoki.job`（`RunFormatter`、`ProcessLock`、`LockError`、`contained`）、`kototoki.media` 与 `kototoki.strata`（`contained`）、`kototoki.workers.gpu`（`RunFormatter`）。

## 代码与验证入口

代码与验证入口写在各子页末尾：[运行日志](run-logging-and-processes/run-log.md#代码与验证入口)、[进程原语](run-logging-and-processes/process-primitives.md#代码与验证入口)、[worker 子进程](run-logging-and-processes/worker-subprocess.md#代码与验证入口)。

## 变更与决策来源

- [ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)
- 已完成票据（见归档 tag）：runtime-logging（设计与实跑核对）、runtime-logging-gaps、architecture-review 01、architecture-cleanup（进程原语下沉）
- [技术选型](../../development/technology-stack.md)（`structlog` 未采用）
