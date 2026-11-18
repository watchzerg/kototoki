# 专名一致性（建表；译法经翻译注入使用）

状态：current；权威决定：[ADR-0028](../../adr/0028-names-accept-empty-table.md)、[ADR-0021](../../adr/0021-q3-strata-names-baseline.md)、[ADR-0029](../../adr/0029-translate-per-cue-resolution.md)（部分被取代）、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责双语字幕流水线中专名译法的统一：GPU 阶段 `names` 在 Strata 上用 `qwen3.8-flash-next-iq3_s`（思考关闭）为每部影片的 `ja.srt` 建一张专名表（`name-table.json`）。表由翻译子系统在翻译时按 Q2 规则注入（只取 `confidence: high` 的写法，见[翻译子系统](translation-subsystem.md#当前行为规格)）；本模块不知道注入规则，也没有发布时的替换。建表规则照抄基线 Q3 的 `names-strata-v4`（提示 v5、程序兜底全开、5 次尝试），不调参；完整定义见[决定定义：产品建表](../../adr/CURRENT.md#产品建表)。

不负责：阶段链与身份（[阶段计划](stage-plan.md)的 `names_identity`）；产物写出、GPU 锁与日志落地（[批次编排](batch-orchestration.md)）；Strata 的启停、身份核对、共享 session 与客户端（[Strata 服务与共享 session](strata-session.md)）；翻译本身。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**阶段位置**：`… ─► ja-cues ─► names ─► translate ─► publish`。names 在 translate 之前，两者共用同一个 Strata session：第一次真正需要模型时启动（可能就在 names），两阶段之间不停，整批结束才停止。建表必开：阶段链恒含 names。

**建表**（`build_document(work_dir, document, session, seed) -> BuildResult`，`session` 是编排传入的共享 `kototoki.strata.Session`）：

- 零条目 `ja.srt`：不碰 session（可为 `None`），返回 `status = ok` 的空表（`attempts = 0`）。
- 否则 `session.ensure_started()` 取运行中的 Strata（必要时启动），以 `session.client(<work_dir>/names/transport/<session.label>, timeout=1800)` 建客户端；交换目录因此是 `<work_dir>/names/transport/<UTC戳>-<pid>/session-NN/`。
- 整份 `ja.srt` 渲染成"SRT 编号<TAB>文本"一次送入（cue 内换行替换为空格，时间轴丢弃）。
- 预算检查走 `/v1/messages/count_tokens`：system 与 user 两段各作一条 user 消息计数再相加，超过 32256（49152 − 16384 − 512；49152 只用于算预算、不随请求发出，ADR-0028「输出上限与提示预算」）时不请求，返回 `too_long` 空表。
- 否则请求 `/v1/chat/completions`；只有回复格式不合格（截断 `finish_reason == "length"`、非 JSON、顶层不是对象、`entries` 不是列表）才换 seed 重试（ADR-0028，配方 `retry_on: "malformed"`）：`entries` 为空列表、或条目在归一中全被丢弃，都接受为 `status = ok` 的空表（`dropped_*` 照常记录）。重试依次用 seed、seed＋1、…、seed＋4，最多 5 个请求，取第一张合格的表即停（`table.ATTEMPTS = 5`）。仍失败返回 `failed` 空表（原因取最后一次错误的首行，`meta.attempt` 为 5）。
- 成功时 payload 为 `name-table-v2`：`work_guess`、`entries[]`、`meta`（实际 seed 与尝试序号、`dropped_shape`／`dropped_honorific`／`dropped_ja_shape`、`prompt_tokens`／`completion_tokens`、秒数）、`build`（`status`、`reason`，以及 `build_document` 补上的 `prompt_check`——`count_tokens` 或 `skipped (<错误>)`——与 `over_budget_by_usage`）。
- **请求体**（`table._request_body`）：`messages`、采样 temperature 0.7／top_p 0.8／top_k 20／`min_p` 0／`presence_penalty` 1.5、`seed`、`max_tokens` 16384、`chat_template_kwargs.enable_thinking: false`、非流式、`model`；无 `response_format`。除 `max_tokens`（v13 为 8192，ADR-0028「输出上限与提示预算」）外与研究侧 v13 `NamesClient.chat` 逐字节相同。`seed` 由配置保证为正整数。
- **`count_tokens` 退路**：该端点返回 HTTP／传输错误或响应形状不符（没有整数 `input_tokens`）时，该影片内不再预检、计数按 0，运行日志一行 WARNING；每部影片一个客户端，下一部重新尝试该端点。此时只记录回复的 `usage.prompt_tokens`，超预算只在 `build.over_budget_by_usage` 标记、不失败；不得因此放宽预算。
- 传输层失败（`HTTPError`、`URLError`、连接错误、超时）：`session.stop()` 停掉 Strata（下一部需要模型的影片再启动），抛 `NamesError`。HTTP 错误的消息只带状态码、分类（`oom`／`server_error`）与正文长度，正文留在交换目录。
- `ensure_started()` 抛 `StrataRefused`（含共享 session 已不可用）或 `InfraFailure`（启动失败）时包成 `NamesError`。共享 session 不可用后，本批其余有 cue 的影片直接 `NamesError`，翻译阶段同样直接失败（[共享 session](strata-session.md#当前行为规格)）。

**失败与降级**：

| 情况 | 结果 |
| --- | --- |
| 超预算（`too_long`）、5 次回复格式都不合格（`failed`） | 写空表（`build.status` 记原因），运行日志一行 WARNING，影片照常翻译与发布（空表不注入） |
| Strata 起不来或被拒绝、OOM、HTTP 错误、传输失败 | 该影片在 `names` 阶段文件级失败（`failure.json`）；重跑同一命令对它再建表 |

**表可人工校对，也是译法的唯一入口**：

- 翻译按 Q2 规则注入表里 `confidence: high` 的实体，每个 `forms[]` 一行（[翻译子系统](translation-subsystem.md#当前行为规格)）。
- `name-table.json` 的跳过只比 `identity` 块（`ja_srt_sha256`、`BUILD` 配方 hash、`[names] seed`）；用户改 `entries`（改错名、删条目、调 `confidence`）不触发重建。
- 改到会被注入的条目（`high` 的实体或其写法）会改变注入行的哈希 `names_sha256`，翻译身份随之变化；删掉该片源文件旁的 `*.ja-zh.srt` 后再运行即重译并重新发布（ADR-0007「发布」：字幕已存在的文件一律跳过）。只改 medium／low 条目不触发重译。
- `ja.srt`、建表配方或 seed 变化会重建并覆盖手改，不做保护。

**日志**（经编排写进运行日志，[批次编排：运行日志](batch-orchestration.md#运行日志)）：

- `[names] start: N file(s)`；`[names] end: N done, M failed, T.Ts`。
- Strata 的启动、等显存与内存、接入检查、停止来自 `kototoki.strata`，前缀 `[strata]`。
- 每部一行 `[names] done <相对路径>: E entries (D dropped), P prompt tok, C completion tok, T.Ts`，第 2 次及以后的尝试才成功时追加 `, attempt n/5`（上限取包顶层导出的 `ATTEMPTS`）；零条目为 `no cues, empty table`；终态失败为 WARNING `build failed (<原因>), empty table`。
- 每次不合格的尝试（回复被截断、非 JSON、`entries` 不是列表）在该行之前各记一行 WARNING `[names] attempt n/5 failed (seed S): <错误首行>; finish …, C completion tok, reply N char(s)`（来自 `kototoki.names.table`）。
- `count_tokens` 不可用时一行 WARNING。
- 传输失败、HTTP 错误或 OOM 停掉 Strata 前一行 WARNING `[names] stopping Strata after <HTTP 状态 (类别) | 传输异常类型>`（来自包顶层）。
- Strata 不可用之后其余影片的 FAILED 行不带 traceback（原因已由 `[strata]` ERROR 行记过一次），行尾带异常消息首行。
- 条目文字、`work_guess`、提示与回复正文不进日志，只在工作目录。

## 实现设计

- **配方与身份**：`BUILD`（配方 `q3-names-v3`）一个字典，含提示 v5 的 sha256、采样、schema sha256、`max_tokens` 16384、`reasoning off`、context 49152 与预算 32256、归一规则与常量、`attempts` 5、`seed_step` 1 与 `retry_on`（`malformed`）、模型、运行时身份（Strata 版本、引擎 build、默认启动及其解析值、kv `int8`，常量来自 `kototoki.strata`，与翻译配方的 `runtime` 取值相同）、请求形状。hash 用 `kototoki.recipes.recipe_hash`（`BUILD_RECIPE_HASH`，测试钉住）。
- 与 Q3 的 `names-strata-v4` 相同的是模型、运行时身份、请求形状与建表块中除 `max_tokens`／context／预算以外的各项（这三项由 [ADR-0028](../../adr/0028-names-accept-empty-table.md) 放宽，v4 为 8192／24576／15872）；另有 [ADR-0028](../../adr/0028-names-accept-empty-table.md) 新增的 `retry_on`（v4 把空表当不合格），不含研究侧的说明字段与 llama.cpp 的 `model_asset`，所以 hash 不同。测试把三项换回 v4 的值、去掉 `retry_on` 后核对 v4 的 hash。
- 表的身份 `{ja_srt_sha256, recipe_hash: BUILD, seed}` 由[阶段计划](stage-plan.md)计算，以 `names` 键进 `published.json.sources`（审计记录）。表的内容经翻译身份的 `names_sha256` 影响译文。
- **资源所有权**：Strata session 的证据在共用的 `<work root>/strata-sessions/`（[Strata 服务与共享 session](strata-session.md)）。每部影片的原始交换在 `<work root>/<id>/names/transport/<UTC戳>-<pid>/session-NN/`（`count-NN` 为两段提示的计数请求，`chat-NN` 为建表请求），按运行分目录，重建时不与旧交换撞名。本模块不取 GPU 锁、不写 `name-table.json`（编排写）、不启停 Strata（只调 `ensure_started()`／`stop()`）。
- **移植来源**：`table.py` 来自 `archive/2026-11-18-pre-research-restructure:experiments/name_consistency/build_table.py`（`SYSTEM_PROMPT` 逐字节相同，去掉 CLI、思考模式与重归一）；Strata 回调与 5 次尝试来自 `archive/2026-11-18-pre-research-restructure:experiments/scene_batching_v6/v13.py`；只复制不导入；研究代码已删除（[ADR-0031](../../adr/0031-research-layout-and-lightweight-records.md)），产品实现是唯一权威。

## 接口与依赖

- 编排以普通导入使用 `kototoki.names`，只用：`build_document(work_dir, document, session | None, seed) -> BuildResult`（`payload`、`attempts`、`seconds`、`status` ∈ `ok | failed | too_long`）、`NamesError` 与 `BUILD_RECIPE_HASH`。包顶层只导出这几项与 `BuildResult`。
- [阶段计划](stage-plan.md)延迟导入 `kototoki.names.recipes` 取该 hash。翻译子系统不导入本模块，只读它写出的 `name-table.json`（经 `plan` 传入内容）。
- 依赖：基础层（`artifacts`、`srt`、`recipes`）、中间层 `kototoki.strata`（`Session`、`StrataRefused`、身份常量；经 `ensure_started()`、`stop()`、`label`、`client()` 使用，不碰 `ordinal`、`runtime_root`、`client_factory`）与 `kototoki.local_client`（`InfraFailure`、`explicit_oom`）。
- 不导入 torch、推理模块、翻译子系统与研究代码（`tests/core/test_job.py` 的禁止导入测试连同 `kototoki.names` 一起守门）。不读配置（`seed` 由编排与阶段计划读）。

## 代码与验证入口

- 代码：`kototoki/names/__init__.py`（`build_document`、`NamesError`、`_TokenCounter`）、`kototoki/names/table.py`（`SYSTEM_PROMPT`、`USER_TEMPLATE`、`build_messages`、`parse_reply`、归一函数、`build_table`、`BuildResult`）、`kototoki/names/recipes.py`（`BUILD`、`BUILD_RECIPE_HASH`）；编排侧 `kototoki/job.py` 的 `names_batch`。
- 测试（core，`just test`）：
  - `tests/core/test_names_table.py`：渲染（`USER_TEMPLATE` 的 sha256 与一个固定的 cue 渲染输出各钉一条）、解析与归一、上限、zh 形状、称呼词黑名单、提示 v5、日文写法形状、confidence 降级、`build_table` 的请求体、预算、5 次尝试与 `too_long`／`failed` 空表、空回复与条目全被丢弃都一次接受、零条目。
  - `tests/core/test_names_recipes.py`：提示与 schema 的 sha256、`BUILD` hash 钉子、改值即改 hash、与 v13 `s1_recipe("v4")` 的逐项对应钉成字面量、运行时身份等于翻译配方。
  - `tests/core/test_names_session.py`：伪 Strata session／伪客户端：正常建表、首次不合格后换 seed 成功、5 次都失败写空表且恰好 5 个请求、`count_tokens` 退路、超预算不发送、传输失败与 HTTP 错误抛 `NamesError` 并停 Strata（停之前一行 WARNING）、被拒与启动失败抛 `NamesError`、零条目不碰 session；与 v13 一致的请求体与 seed 序列钉成 sha256。
  - `tests/core/test_job.py` 的 `NamesTests`：阶段顺序与锁里的 Strata pid、表与 `sources` 的 `names` 键、终态失败空表照常发布并记 WARNING、session 不可用只让有 cue 的影片失败、建表异常只影响该影片且重跑恢复、零条目不取锁不启动；`RunLogTests` 另测重试成功的 done 行带 attempt、Strata 不可用后其余 FAILED 行不带 traceback。
- `tests/full/test_job_ffmpeg.py`：共享 session 在 names 阶段启动、翻译后退出，`sources` 含 `names`。
- 真实模型验证（占 GPU，须用户批准，不属于任何 gate）：`just smoke names_product`（`scripts/smoke/names_product.py`）在产品自动启停的 Strata 上走 `plan.names_identity` → 共享 `Session` → `build_document` → `write_artifact`（默认 seed）。
  - 输入是脚本内置的 12 条合成日语短句（同一人名的正确写法与一处 ASR 式误写、一个职阶名、其余中性）。
  - 通过条件：`expert_arena` 为 `ram`、`build.status == ok`、表至少一条 person、全程没有 llama-server 进程、停止后 status 为空且显存释放、无异常；结果只记计数、哈希、耗时与资源峰值。
  - 运行记录：Strata 路径见 `archive/2026-11-18-pre-research-restructure:docs/plans/product-names-on-strata.md` §7；27B 时期见 [2026-10-20 验收记录](../../../research/acceptance/2026-10-20-name-consistency-product.md)。
- 未验证：产品写出的表尚未人工抽看；注入后的译文质量只有研究侧 Q2／Q3 证据；x0 输出、其他作品与剧集、`too_long`／`failed`、`count_tokens` 退路与 Strata 起不来等失败路径的真实运行；同一 seed 下建表的可重复性（见 [ADR-0028](../../adr/0028-names-accept-empty-table.md)「未验证与已知限制」）。

## 变更与决策来源

- [ADR-0028](../../adr/0028-names-accept-empty-table.md)、[ADR-0029](../../adr/0029-translate-per-cue-resolution.md)、[ADR-0021](../../adr/0021-q3-strata-names-baseline.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)
- 归档 tag 中的 .scratch/name-consistency-product/（01–09）、.scratch/names-on-strata-v13/、.scratch/q3-product-switch/、.scratch/architecture-cleanup/、.scratch/runtime-logging-gaps/
- `archive/2026-11-18-pre-research-restructure:docs/plans/product-names-on-strata.md`、`archive/2026-11-18-pre-research-restructure:docs/plans/architecture-cleanup.md`
- [2026-10-20 专名一致性进产品验收记录](../../../research/acceptance/2026-10-20-name-consistency-product.md)
