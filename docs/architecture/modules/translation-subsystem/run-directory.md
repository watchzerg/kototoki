---
covers:
  - kototoki/translate/generate.py
---
# 翻译子系统子页：session、run 目录与日志

`翻译子系统` 的子页：Strata session 记录、run 目录内容与续跑规则、运行日志。

**session 记录**：一次 Strata 启动即一个 session（[共享 session](../strata-session.md)）。

- 每次取得运行中的服务，影片 `run.json` 的 `sessions[]` 新增一项：`server_session` 记 `session.label`，`engine` 记服务的启动身份。逐请求交换写在 run 目录的 `transport/session-NN/`（NN 为该影片 `sessions[]` 的序号）（`session.client(trace_dir, timeout=600)`）。
- 首个 completion 的 `cache_n` 记录（`cache_reset`）归本子系统（`generate._cache_state`），按共享 `Session` 对象及其 `label` 分开；同一 session 上的后续影片沿用，重启即重新开始。
- Strata 启动失败（`server_start`）不新增 `sessions[]` 项，记入 `server_start_failures[]`。
- 写过批次或遇基础设施失败的 session 多于一个时 `resumed = true`。
- 没有影片需要模型时不启动 Strata。

**run 目录与续跑**：键只由 `plan` 决定（`batching.source_key` 给出 `srt-<sha12>`，即场景 ID）。

- `ja.srt` 变化换 `srt-<sha12>`；配方名、seed 或注入行变化换子目录；旧目录都保留。
- 手改 `name-table.json` 后是否换 `names_sha12`、重译该片，见[专名一致性](../name-consistency.md)。
- 配方内容变了而名字未变（hash 不符）不自动另开目录，`plan` 拒绝并提示删除该目录。

目录内容：

- `run.json`：只含该影片。配方、hash、seed、`names`（注入行 SHA256 与行数）、来源（`ja.srt` SHA256、场景 ID、cue ID 列表）、`sessions[]`（启动身份摘要、`server_session`、写入批次数、停止原因、基础设施失败与证据、缓存记录、墙钟）、`server_start_failures[]`、`resumed`、`completion`。
- `batches.jsonl`：每完成一批追加一行并 fsync，随即重写 `run.json`（进程被强杀时 `sessions[]` 仍反映已写批次）。行含批次计划字段、译文（不出中文为 `null`）、请求与逐次尝试记录、所属 session；追问过的批次改带 `resolution`（各节点的状态、未解决的 cue 与请求记录，`nodes[0]` 是原批次；未翻译 cue 的原因与尝试次数）。续跑时末尾不完整的一行截掉，其余行须与批次计划一致（中间行损坏即报错），从第一个未写入的批次继续。
- `nodes.jsonl`：节点结果；续跑时同样截掉不完整的末行，只取未完成批次的节点，行须属于批次计划、不重复、目标与深度与重算一致。
- `scene.json`：全部批次完成后才写出（cue 位置、批次、全部译文、`resolution`、`untranslated_ids`、按节点计的请求／尝试与 token 统计）；部分完成的影片没有该文件。
- `report.json`（`kototoki-translate-report-v2`）：完成时写出（零条目也写）：`completion`、计数、追问过的批次的节点摘要、未翻译 cue 清单。
- `transport/session-NN/`：逐请求原始交换；`infra-failures/`：基础设施失败时该批次（或节点）的尝试记录。

零条目 `ja.srt`：写 `run.json`（完成）与 `report.json`，返回空译文，不启动 Strata、不请求模型。

**日志**：logger `kototoki.translate.*`，写进运行日志（[运行日志](../run-logging-and-processes/run-log.md#运行日志)）。Strata 启停与核实由 `[strata]` 记（[Strata session](../strata-session.md)）。

- INFO：session 起止（start 行带相对路径）；每批一行（cue 数、输出 token、tok/s、cache，取不到的省略；追问过的批次只有请求数与未翻译数）。编排的 done 行见[运行日志](../run-logging-and-processes/run-log.md#运行日志)。
- WARNING：Strata 重启；节点有未解决的 cue；节点拆分；未翻译 cue（ID 与原因）；每次失败的尝试各一行 `[translate] batch <ID> attempt n/2 failed (<kind>): <错误首行>; seed, finish, tok, reply 字符数, exchange <交换目录>`，第二次尝试被接受时也留下第一次的失败。
- ERROR：用尽重启放弃、`StrataRefused`、意外异常（批次已知时带批次 ID）。
- HTTP 错误与 server error 的消息只含状态码／kind 与正文长度，不嵌入响应正文（正文留在 `transport/…/response.raw`）。校验消息为固定文本（`Duplicate JSON key` 不带键名）。提示、译文与响应正文不进日志。

## 代码与验证入口

- 代码：`kototoki/translate/generate.py`（`run_step`、按批次落盘、续跑、session 记录与日志；`translate_document` 拆为私有的 `_open_translation`（打开与核对 run）、`_register_session`（启动 Strata 并登记 session）、`_translate_pending`（批次循环）、`_run_session`（异常分流与收尾））；Strata 与客户端见 [Strata 服务与共享 session](../strata-session.md#代码与验证入口)。
  - `tests/core/test_translate.py`：伪服务／伪客户端：正常翻译全部 cue、第二次尝试用 seed＋1、注入行只进匹配的包、整批只起一个 Strata session、续跑从第一个未写批次继续并截掉写了一半的行、全部完成不启动 Strata、run 目录按 ja.srt、配方、seed 与名表分键、注入行变化另起 run 而其余条目不重译、OOM 重启为新 session、基础设施失败重启两次后放弃、ja.srt 变化用新目录并保留旧目录。
  - 测试精简（2026-11-22）后不再有测试覆盖：
    - session 与日志：session 目录名为 UTC 时间戳加 pid、`cache_n` 每 session 只记一次、断连后重启续跑、意外异常记录并停 Strata、每批落盘先于调用结束；日志不含台词与 HTTP 响应正文、每批一行进度、重启 WARNING 与放弃 ERROR、失败尝试行的截断与路径。
    - 失败与续跑：中间行损坏即拒绝、完整 run.json 下批次不全时失败而不启动 Strata、另一配方 hash 的 run 被拒、`StrataRefused` 与启动额度耗尽不重试且不等待、混合失败不标记不可用、显存轮询超时算基础设施失败、全空行回复对半拆、多出的 ID 被忽略并记录、长度停止算上限失败、空场景不写不请求、换 seed 用独立 run。
- 真实模型验证与未验证项见[枢纽页](../translation-subsystem.md#代码与验证入口)。
