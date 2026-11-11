# 翻译子系统与双语合并

状态：current；权威决定：[ADR-0019](../../adr/0019-product-translation-q2.md)、[ADR-0017](../../adr/0017-q2-strata-default-launch-baseline.md)、[ADR-0010](../../adr/0010-dp10-cut-translation-flow-baseline.md)、[ADR-0022](../../adr/0022-product-names-on-strata.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)、[ADR-0008](../../adr/0008-no-multi-translation-selection.md)

## 定位与阅读

负责双语字幕流水线中 `ja.srt → 译文` 与 `ja.srt + 译文 → ja-zh.srt` 两步：`dp10-cut` 切包与 Q2 请求、专名注入、按批次落盘与续跑、基础设施失败的重启、批次终态失败的 10→5→1 降级与回退报告，以及中日两行合并。配方的完整定义见[决定定义：产品翻译](../../adr/CURRENT.md#产品翻译)；跨模块契约见[技术设计](../../specs/bilingual-subtitle-pipeline.md) §3.3、§4、§6。

不负责：

- Strata 的启停、身份核对、共享 session 与本机客户端（[Strata 服务与共享 session](strata-session.md)）；
- GPU 锁、Job Object、`ja-zh.srt` 的写出与发布（[批次编排](batch-orchestration.md)；`zh.srt` 不发布，ADR-0020）；
- 专名表的建表（[专名一致性](name-consistency.md)）；工作目录本身的位置（[产物契约](artifact-contract.md)）；任何时间换算。

上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。研究侧同名规则在 `experiments/translation_v3/{qwen,strata}.py` 与[完整 SRT 翻译流程](translation-srt-flow.md)；本模块是 Q2 的产品移植，不导入它们。

## 当前行为规格

**对编排器的接口**（`kototoki.translate`）：

- `plan(work_dir, document, name_table, config) -> TranslatePlan`：只读、不写文件。`document` 是 `srt.read_srt` 读出的 `ja.srt`，`name_table` 是该影片 `name-table.json` 的内容（[阶段计划](stage-plan.md)的 `translate_plan` 读出传入）。返回：
  - `run_dir`：`<work_dir>/translate/srt-<sha12>/q2-degrade-v1__s<seed>__n<names_sha12>/`；`relative` 是相对工作目录的 posix 串，即发布记录的 `translate_dir`；
  - `identity`：`{ja_srt_sha256, recipe_hash, seed, names_sha256}`，阶段计划的 translate 身份由此取得；
  - `needs_model`：零条目文档或 `run.json` 已记 `complete` 时为 False，编排器据此决定是否取 GPU 锁、启动 Strata；
  - `document` 与 `names`（注入行）。
  - `run.json` 已存在但配方 hash／seed／注入行／来源不符时抛 `ValueError`，消息提示删除该目录即可重译。
- `translate_document(plan, session, *, relative) -> TranslateResult`：`session` 是编排传入的共享 `kototoki.strata.Session`，`relative` 是输入目录内相对路径（只进日志）；`needs_model` 为 False 时可为 `None`，只读回已完成的 run（记为完成而批次文件缺失即抛 `TranslateError`，不启动 Strata）。返回：
  - `translations`：cue id → 译文，精确覆盖全部 cue，回退的 cue 为日文原文；
  - `fallback_count`：回退为日文的 cue 数，编排器写进 `published.json` 的 `translate_fallback_cues`、发布日志行与控制台汇总；
  - `report`：即 `report.json` 的内容。
  - 基础设施失败用尽重启、Strata 被拒绝或已不可用时抛 `TranslateError`（编排器记为该文件翻译失败）。
- `RECIPE_HASH`：配方 `q2-degrade-v1` 的 hash，进翻译身份，由 `tests/core/test_translate_recipes.py` 钉住。注入行的内容不进配方 hash，进身份的 `names_sha256`。

**请求**（Q2 规则）：每部影片是一个场景，cue ID 用 `srt.py` 的 `<sha8>-cue-<n>` 别名，cue 带 `ja.srt` 的起止秒。

- **切包**（`batching.gap_pack_cuts`，`gap-pack-v2`）：整个场景用动态规划取总惩罚最低的切法，每批待译 ≤10 条。
  - 每批代价 = (条数 − 10)² ＋ 批内每个 ≥2 s 停顿按秒数计 1 分；<6 条加 1000 分；批内有 ≥20 s 停顿不可行。
  - 内部切点按停顿分级加罚：<0.5 s 加 6、<1 s 加 3、<2 s 加 1，缺时间戳按第一档。
  - 停顿只取自 `ja.srt` 自身的时间轴、只比较长短，不是时间换算。
- **只读邻文**（`batching.neighbours`，`wide-context-v1`）：前 20 条、后 5 条，只按条数取到场景边；可见总数（含待译）超过 35 条时先去后邻、再去前邻。降级的子批次用同一规则。
- **提示**（`recipes.messages`，`qwen-joint-v1`）：两条 chat messages。system 是 joint 任务文本，该批有注入行时末尾追加 `qwen-name-table-v1` 的 header 与 `日文 → 中文` 逐行；user 是只读日文上下文（JSON）加待译 JSON `{"translations": {id: 日文}}`。文字与研究侧 `experiments/translation_v3/qwen.py::messages` 逐字节相同。
- **专名注入**（`recipes.name_rows`、`names_for_window`）：取 `name-table.json` 里 `confidence: high` 的实体，每个 `forms[]` 一行，按 `ja` 去重，跳过 `ja` 或 `zh` 为空的写法；某批只注入日文写法出现在该批可见台词（含只读邻文）里的行。表为空时不注入，翻译照常。只改 medium／low 条目不改变注入行。
- **请求体**（`recipes.request_body`）：chat completions，不用 grammar，思考关闭（`chat_template_kwargs.enable_thinking = false`），`temperature 0.7、top_p 0.8、top_k 20`，`max_tokens` 4096，非流式，`seed` 取 `[translate] seed`（须为正整数）。同一批最多两次：seed、seed＋1。正常批的请求体与研究侧 `strata.request_body(qwen.messages(…))` 逐字节相同。
- **校验**（`recipes.parse_translation`）：严格 JSON（重复键拒绝）、恰好一个 `translations` 对象、ID 集合与顺序同待译、值非空；另拒绝含空行的译文（会让 SRT 断块）。
- 每个 Strata session 首个 completion 的 `cache_n` 只记录，不据此判失败；输入 token 超过 Q1 预算（12224）只记 `over_q1_budget`，不判失败。

**失败分类**（`generate.run_step` 与 `translate_document`）：

| 种类 | 来源 | 处理 |
| --- | --- | --- |
| `oom`、`server`、`server_error`、`server_start` | HTTP 正文为 OOM 文本／其他 HTTP 错误、连接失败或超时、响应带 `error`、Strata 起不来（`InfraFailure`） | 停掉 Strata，同一次调用内启动新 session 重做 |
| `context`、`limit`、`parse` | HTTP 报超出 context、`finish_reason == "length"`、空回复、校验失败 | 批次终态：按下节降级，不重启、不使该影片失败 |
| `StrataRefused` | 见 [Strata 服务与共享 session](strata-session.md#当前行为规格) | 不重试 |
| 其他异常 | 非 JSON 响应、写盘失败等 | 记 `stop_reason`，停掉 Strata，原样上抛 |

- 基础设施失败同一次调用内最多重启 2 次（`generate.MAX_RESTARTS`），仍失败抛 `TranslateError`。`oom`、`server` 与 `context` 不做第二次尝试。
- 启动失败的额度归 `Session`（整批累计 3 次即不可用）；本子系统不写 `session.unavailable`，只在每轮开始时读：非空即抛 `TranslateError`，消息带 `Session` 写下的原因（启动额度耗尽或被拒）。
- `StrataRefused`：停掉 Strata，抛 `TranslateError`；共享 session 已被 `Session` 置为不可用，本批其余需要模型的影片在 names 与翻译都直接失败。
- 其他异常记 `stop_reason = session_error: …`。

**降级**（`degrade.py`）：

- 批次终态失败（两次尝试都失败）后拆成前后两半 `父ID.a`／`父ID.b`（奇数条前半多 1 条）；仍失败的半批拆成单条 `父ID.a.1`…；单条仍失败则该 cue 的译文 = 日文原文（回退，原因取该单条的失败种类）。只有 1 条的批次失败即回退。
- 子批次与原批次用同一条邻文规则、同一 seed、同一专名注入规则。
- 每个节点（含失败的原批次）的结果一出来就追加到 `degrade.jsonl`。降级途中的基础设施失败照常重启 Strata，新 session 从未记录的节点继续，已记录的节点不再请求。
- 整个批次完成后写成 `batches.jsonl` 的一行（带 `degrade.nodes` 与 `degrade.fallback`）。回退由此对该配方 hash、seed 与注入行是终态：重跑同一命令不再尝试；要重试须改 `[translate] seed`（另起 run）；要重做已发布的文件须先删掉其 `.ja-zh.srt`。
- 研究侧 Q2 对失败的包只空出该包，10→5→1 是产品唯一的差别（ADR-0019 第 4 点）；它与两次可靠性尝试都不是"翻译多次再挑选"（ADR-0008）。

**session 记录**：一次 Strata 启动即一个 session（[共享 session](strata-session.md)）。

- 每次取得运行中的服务，影片 `run.json` 的 `sessions[]` 新增一项：`server_session` 记 `session.label`，`engine` 记服务的启动身份。逐请求交换写在 run 目录的 `transport/session-NN/`（NN 为该影片 `sessions[]` 的序号），目录经 `session.client(trace_dir, timeout=600)` 传入。
- 首个 completion 的 `cache_n` 记录（`cache_reset`）归本子系统（`generate._cache_state`），按共享 `Session` 对象及其 `label` 分开；同一 session 上的后续影片沿用同一份记录，每次重启重新开始。
- Strata 启动失败（`server_start`）不新增 `sessions[]` 项，记入 `server_start_failures[]`。
- 写过批次或遇到基础设施失败的 session 超过一个时 `resumed = true`。
- 没有影片需要模型时不启动 Strata。

**run 目录与续跑**：`translate/srt-<sha12>/q2-degrade-v1__s<seed>__n<names_sha12>/`，键只由 `plan` 决定（`batching.source_key` 给出 `srt-<sha12>`，同时是场景 ID）。

- `ja.srt` 变化换 `srt-<sha12>`；配方名、seed 或注入行变化换子目录；旧目录都保留。
- 手改 `name-table.json` 里会被注入的条目（`confidence: high` 的实体或其 `forms`）即换 `names_sha12`，下次运行重译该片；只改 medium／low 条目不会。
- 配方内容变了而名字未变（hash 不符）不自动另开目录，`plan` 拒绝并提示删除该目录。

目录内容：

- `run.json`：只含该影片。配方、hash、seed、`names`（注入行 SHA256 与行数）、来源（`ja.srt` SHA256、场景 ID、cue ID 列表）、`sessions[]`（启动身份摘要 `candidate`／`strata`／`cold_load_seconds`／启动前空闲显存与可用内存、`server_session`、写入批次数、停止原因、基础设施失败与证据、缓存记录、墙钟）、`server_start_failures[]`、`resumed`、`completion`。
- `batches.jsonl`：每完成一批追加一行并 fsync，随即重写 `run.json`（进程被强杀时 `sessions[]` 仍反映已写批次）。行含批次计划字段、译文、请求与逐次尝试记录、所属 session；降级完成的批次不带顶层请求，改为 `degrade`：各节点（`nodes[0]` 是原批次）的 ID、层级、状态、失败种类、尝试次数与完整请求记录，以及回退 cue 的 ID、原因、错误与累计尝试次数。续跑时末尾不完整的一行截掉，其余行须与批次计划一致（中间行损坏即报错），从第一个未写入的批次继续。
- `degrade.jsonl`：降级各节点的结果，每个节点完成即追加；续跑时同样截掉不完整的末行，只取未完成批次的节点，行须属于批次计划且不重复。
- `scene.json`：全部批次完成后才写出（cue 位置、批次、全部译文、降级树、`fallback_ids`、按节点计的请求／尝试与 token 统计）；部分完成的影片没有该文件。
- `report.json`：完成时写出（零条目也写）：`completion`、计数（批次、降级批次、回退 cue、降级请求数）、每个降级批次的节点摘要与回退 ID、回退 cue 清单。
- `transport/session-NN/`：逐请求原始交换；`infra-failures/`：基础设施失败时该批次（或降级节点）的尝试记录。

零条目 `ja.srt`：写 `run.json`（完成）与 `report.json`，返回空译文，不启动 Strata、不请求模型。

**日志**：logger `kototoki.translate.*`，写进运行日志（[运行日志](run-logging-and-processes.md#运行日志)）。Strata 启停与核实由 `[strata]` 记（[Strata session](strata-session.md)）。

- INFO：session 起止（start 行带相对路径）；每批一行（cue 数、输出 token、tok/s、cache，取不到的省略；降级批次只有 cue 数、请求数与回退数）。编排的 done 行见[运行日志](run-logging-and-processes.md#运行日志)。
- WARNING：Strata 重启；降级拆批；单条回退（列出回退的 cue ID 与原因）；每次失败的尝试各一行 `[translate] batch <ID> attempt n/2 failed (<kind>): <错误首行>; seed, finish, tok, reply 字符数, exchange <交换目录>`，第二次尝试被接受时也留下第一次的失败。
- ERROR：用尽重启放弃、`StrataRefused`、意外异常（批次已知时带批次 ID）。
- HTTP 错误与 server error 的消息只含状态码／kind 与正文长度，不嵌入响应正文（正文留在 `transport/…/response.raw`）。校验消息为固定文本（`Duplicate JSON key` 不带键名）。提示、译文与响应正文不进日志。

**合并**（`kototoki.merge.merge(ja_document, zh_translations) -> srt_text`）：纯函数；沿用日文 cue 的编号与时间行，每条两行，中文在上、日文在下；中文与日文内的换行都替换为空格，保证每条恰好两行；回退为日文的条目两行相同，照常输出。译文须精确覆盖全部 cue（缺失、多余、空串抛 `IncompleteTranslationError`）；零条目文档得到空串。

## 实现设计

移植来源与取舍（产品包不导入 `experiments.*`，只复制）：

- `recipes.py`：来自 `experiments/translation_v3/{qwen,strata}.py`、`names11.product_tables` 与 v9 `wide-context-v1`。Q2 规则写成常量（提示、注入、请求体、校验、配方 hash），与研究侧逐字节对照由测试钉住。产品新增的校验（拒绝空行）与降级字段使它另算 hash（`q2-degrade-v1`）。Strata 身份常量从 `kototoki.strata` 取。
- `batching.py`：来自 `translation_v3/batching.py` 与 `data.py`。gap-pack-v2 切包只留 `group_gap=None` 分支；`Scene`／`Cue`（带秒）由 `ja.srt` 构造；`source_key` 是 `srt-<sha12>` 的唯一出处。
- `degrade.py`：产品新增。拆分规则、降级树与回退、`report.json` 内容；不导入 `generate`，由其传入请求函数与降级日志写入函数；邻文经 `batching.neighbours`。
- `generate.py`：来自 `translation_v3/strata.py::run_step` 与 `generate.py`。`run_step` 判定不变（去掉思考分支）；共享 `Session` 取代研究侧"执行者先启动服务"；按批次追加落盘；同调用内重启 Strata；按 session 记 `cache_state`。

## 接口与依赖

- 依赖：标准库、`kototoki.artifacts`、`kototoki.config`（只读 `translate.seed`）、`kototoki.srt`、中间层 `kototoki.strata`（`Session`、`StrataRefused`、身份常量）与 `kototoki.local_client`（`InfraFailure`、`explicit_oom`）。共享 `Session` 经 `ensure_started()`、`stop()`、`label`、`client()`、`unavailable` 使用（[Strata 服务与共享 session](strata-session.md#接口与依赖)）。
- 不导入 `names`（只读它写出的表内容，由 `plan` 传入）与 `experiments.*`。
- 编排器只导入包顶层的 `translate_document` 与 `kototoki.merge`；[阶段计划](stage-plan.md)延迟导入包顶层的 `plan` 取 `TranslatePlan`；包顶层还导出 `RECIPE_HASH`、`TranslateError`、`TranslateResult`。`recipes`、`batching`、`degrade`、`generate` 是内部实现。
- 外部依赖：Strata 本机 8080 服务（安装与模型由用户维护，见[依赖布局](../../development/dependencies.md)）。

## 代码与验证入口

- 代码：`kototoki/translate/`（`__init__.py`、`recipes.py`、`generate.py`、`batching.py`、`degrade.py`）、`kototoki/merge.py`。Strata 与客户端见 [Strata 服务与共享 session](strata-session.md#代码与验证入口)。
- 测试（core，`just test`）：
  - `tests/core/test_translate.py`：伪服务／伪客户端：正常、第二次尝试用 seed＋1、注入行只进匹配的包、续跑与截掉写了一半的行、中间行损坏即拒绝、全部完成不启动 Strata、基础设施失败重启即新 session 与放弃、`StrataRefused` 与启动额度耗尽不重试、`cache_n` 每 session 只记一次、注入行变化另起 run、空场景、日志不含台词与响应正文等。
  - `tests/core/test_translate_degrade.py`：拆分与邻文、10→5→1 降级与单条回退、超出 context 进入降级、续跑复用已记录节点、回退终态、经编排器写进 `published.json` 的回退计数。
  - `tests/core/test_translate_recipes.py`：`RECIPE_HASH` 钉子；提示、注入与请求体与研究侧输出逐字节相同的结果钉成字面量或 sha256；gap-pack-v2 规则；`confidence: high` 的注入规则对真实 `translate.plan` 断言。
  - `tests/core/test_merge.py`：中文在上日文在下、换行替换为空格、回退条目两行相同、零条目得空串、缺失／多余／空串抛错。
- 与研究侧 `translation_v3`／`scene_batching_v6` 的实时对照：`tests/equivalence/test_translate_recipes.py`（`just test-equivalence`，属 `gate-full`）。
- 真实模型验证（占 GPU，须用户批准，不属于任何 gate）：`just smoke translate_product`（`scripts/smoke/translate_product.py`，走产品自动启停的 Strata）。运行记录：[Q2 首用 smoke 与整片（含 mmap 诊断）](../../research/acceptance/2026-11-11-module-page-history-translation-names.md)；与建表共用 session 的整片见 [`docs/plans/product-names-on-strata.md`](../../plans/product-names-on-strata.md) §7。
- 未验证：降级路径只经伪客户端；Strata 的请求不复现（同 seed 跨启动约半数 cue 不同，ADR-0017），重跑不保证同一译文；`q2-degrade-v1` 在产品里的质量没有独立裁判证据（沿用 ADR-0017 的 v12 F1 证据）。

## 变更与决策来源

- [ADR-0005](../../adr/0005-apex-i-compact-translation-baseline.md)、[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0008](../../adr/0008-no-multi-translation-selection.md)、[ADR-0010](../../adr/0010-dp10-cut-translation-flow-baseline.md)、[ADR-0011](../../adr/0011-dp10-cut-product-recipe.md)、[ADR-0017](../../adr/0017-q2-strata-default-launch-baseline.md)、[ADR-0019](../../adr/0019-product-translation-q2.md)、[ADR-0022](../../adr/0022-product-names-on-strata.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)
- `.scratch/bilingual-subtitle-pipeline/issues/`（05、09、15、16）、`.scratch/architecture-review/issues/01-small-fixes.md`、`.scratch/name-consistency-product/issues/02-shared-llama-server.md`、`.scratch/q2-product-switch/`、`.scratch/q3-product-switch/`、`.scratch/architecture-cleanup/`
- [`docs/plans/product-names-on-strata.md`](../../plans/product-names-on-strata.md)、[`docs/plans/architecture-cleanup.md`](../../plans/architecture-cleanup.md)
- [技术设计历史原文](../../research/2026-11-11-bilingual-pipeline-spec-history.md)、[模块页拆出的历史记录](../../research/acceptance/2026-11-11-module-page-history-translation-names.md)
