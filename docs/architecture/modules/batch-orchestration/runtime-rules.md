---
covers:
  - kototoki/job.py
---
# 批次编排子页：运行时规则

`批次编排` 的子页：GPU worker 调度、无语音与近乎无声、两把锁、`failure.json` 清理与运行日志的挂接。

**GPU worker 调度、崩溃与重启**：GPU 阶段每批启动一个 worker 子进程（`run_gpu_stage`），按文件隔离崩溃并为其后文件重启；命令、jobs、子进程环境与崩溃判定见[运行日志与进程原语](../run-logging-and-processes/worker-subprocess.md#worker-子进程)。失败文件退出后续阶段，批次继续。

**无语音**：`vad.json` 的 `chunks` 为空列表时跳过 asr／align／ja-cues／names／翻译，直接发布零条目 `ja-zh.srt`。

**近乎无声**（batch-run-fixes 04）：asr 前 `speech_gate` 查 `vad.json` 的 `accounting.speech_samples`，不足参照时长 1%（`MIN_SPEECH_RATIO`）记 `vad` 失败。

**锁**（原语见[运行日志与进程原语](../run-logging-and-processes/process-primitives.md#进程原语)）：

- GPU 锁是 `config.gpu_lock`（仓库内 `.local/gpu.lock`），第一个需要 GPU 的阶段前获取，持有到翻译结束；names 阶段只在有文件的 `ja.srt` 有 cue 时才取，翻译阶段只在有文件 `needs_model` 时才取（全部 run 已完成或零条目时整批不占 GPU）。
- 锁文件记录编排器 pid 与创建时间，以及运行中的 worker 与 Strata 服务的 pid。
- 两把锁都是持有者存活即拒绝、残留锁默认拒绝，`KOTOTOKI_BREAK_STALE_LOCK=1` 时移除残留锁；GPU 锁取不到时抛 `GpuLocked`、整批退出码 4（见入口）。

**`failure.json` 清理**：该文件本次成功发布后、以及发布期发现源文件旁已有同名字幕而按已存在跳过时删除；重跑时不看 `failure.json`，只按产物身份决定从哪个阶段继续，新的失败覆盖旧记录。

## 运行日志

编排持有运行日志的目的地（`<work root>/run-<UTC戳>.log`、控制台、`run-<戳>-<stage>.stderr.log`）；挂接、行格式、级别与内容规则见[运行日志与进程原语](../run-logging-and-processes/run-log.md#运行日志)。

## 代码与验证入口

- 代码与测试入口见[主流程](flow.md#代码与验证入口)。
