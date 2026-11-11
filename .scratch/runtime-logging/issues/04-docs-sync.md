# 04 文档随交付同步

Status: resolved
Type: task
Blocked by: 01, 02, 03

## 范围

按[随交付同步](../../../docs/agents/documentation.md#随交付同步)，以 [spec.md](../spec.md) §3 与 01–03 的实际实现为准（以代码为准，不照抄规格里尚未实现的东西）：

- `docs/architecture/module-boundaries.md`"产品包的责任边界"的**日志**条改为 spec §3.2 措辞。
- `docs/architecture/modules/batch-orchestration.md`：**日志**段扩为"运行日志"小节，作为权威：框架（标准库 logging，不用 structlog 的理由一句）、logger 命名、级别含义、行格式、文件位置、内容原则（spec §3.6 六条）、子进程噪声抑制变量、stderr 告警计数行。
- `docs/architecture/modules/stt-workers.md`：壳的 stderr 日志与 `captureWarnings` 一句；`translation-subsystem.md`：经 `kototoki.translate` logger 发批次进度／重启／降级一句；两处链接到批次编排的"运行日志"节。
- `docs/specs/bilingual-subtitle-pipeline.md` §4 目录树：`run-<戳>.log`、`run-<戳>-<stage>.stderr.log` 两行注释。
- `README.md` 第 12 条补一句日志在哪、级别是什么。
- `CODING_STANDARDS.md`：日志一句（不进日志的内容、告警用级别不用措辞）。
- `docs/development/technology-stack.md`：`structlog` 旁注明"2026-10-18 评估后未采用，产品用标准库 logging"。
- `docs/architecture/INDEX.md` 批次编排一行若提及日志则对齐措辞。

## 完成标准

`just docs-check` 通过；每处改动只摘要并链接权威节，不复制正文；不新建文件。

## 文件所有权

上列文档。

## Comments

- 2026-10-18 文档同步完成（Opus 5.5，未提交，未改任何 .py）：
  - `docs/architecture/modules/batch-orchestration.md`：**日志**段改为"当前行为规格"末尾的 `### 运行日志` 小节（权威）：框架（标准库 logging，structlog 未采用及理由）、root handler 挂接与复原、级别、行格式与三级示例、两类文件与 stderr 告警计数、内容规则（按实现：失败行只带异常类型＋traceback；无通用 200 字符截断，只有翻译重启／放弃行截首行；翻译"意外异常"行无 traceback）、`QUIET_ENV`、`__main__` 早期错误、未验证项；GPU worker 调度段提及 `QUIET_ENV`；代码与测试入口加 `logs.py`、`_run_logging`、`RunLogTests`；变更来源加本组票据。
  - `docs/architecture/module-boundaries.md`：**日志**条改为新措辞（另注 `gpu.main` 只把子进程日志写 stderr）；基础层清单加 `logs`；归属表批次编排行加 `kototoki/logs.py`。
  - `docs/architecture/INDEX.md`：分层图基础层加 `logs`；批次编排行写"运行日志（目的地与格式）"并加 `kototoki/logs.py`。
  - `docs/architecture/modules/stt-workers.md`：进度条改由 `QUIET_ENV` 关闭；壳经 `gpu.main` 写 stderr（`RunFormatter`、`captureWarnings`）及记录内容，链接运行日志节。
  - `docs/architecture/modules/translation-subsystem.md`：新增**日志**段：`kototoki.translate.*` 事件与级别，`StepFailed` HTTP／server error 消息不再含响应正文及其对 run.json 等 `error` 字段的影响。
  - `docs/specs/bilingual-subtitle-pipeline.md` §4 目录树加两行；`README.md` 输出条加一句；`CODING_STANDARDS.md` 加日志一条；`docs/development/technology-stack.md` structlog 旁注未采用。
  - 自动检查：`just docs-check` 退出码 1，44 条错误全部位于本次未改动的冻结／历史文件（`docs/archive/agents/2026-10-09-codex-AGENTS.md`、`docs/research/2026-10-03-*`、`docs/research/2026-10-05-translation-pyvideotrans.md`、`docs/testing/{fatestay-reference,stt-evaluation}.md`，链接指向仓库外或已移走的路径），HEAD 上同样失败；本次改动的页面与新增锚点 `#运行日志` 无报错。
  - 未验证：同 01–03（真实 GPU 运行下 stderr 无进度条、tok/s 是否出现）。

