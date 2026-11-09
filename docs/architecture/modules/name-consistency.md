# 专名一致性（建表；译法经翻译注入使用）

状态：current（2026-10-20 票据 06 接入编排；建表与配方由票据 03、04 移植，[ADR-0014](../../adr/0014-name-consistency-in-product.md) 进产品；2026-11-08 起没有发布时替换，表只经翻译注入使用，建表必开，[ADR-0019](../../adr/0019-product-translation-q2.md)；**2026-11-09 起在与翻译共用的 Strata session 上用 Qwen3.8-Flash-Next 按基线 Q3 的规则建表，产品不再起 llama-server**，[ADR-0022](../../adr/0022-product-names-on-strata.md)）。离线由伪 Strata session／伪客户端与伪 names 模块测试，并与研究侧 v13 的实现逐字节对照；Strata 路径的真实运行（smoke 与一部整片）结果记在 ADR-0022 所指[计划](../../plans/product-names-on-strata.md)的 §7。27B＋llama-server 时期的真机验证（2026-10-20 smoke 与两部整片）保留在下文"代码与验证入口"作历史记录。

## 定位与阅读

负责双语字幕流水线中专名译法的统一：GPU 阶段 `names` 在 Strata 上用 `qwen3.8-flash-next-iq3_s`（思考关闭）为每部影片的 `ja.srt` 建一张专名表（`name-table.json`）；表由翻译子系统在翻译时按 Q2 规则注入（只取 `confidence: high` 的写法，见[翻译子系统](translation-subsystem.md#当前行为规格)），本模块不知道注入规则，也没有发布时的替换。建表规则照抄基线 Q3 的 `names-strata-v4`（[ADR-0021](../../adr/0021-q3-strata-names-baseline.md)；提示 v5、程序兜底全开、5 次尝试），不调参。不负责：阶段链与身份（[阶段计划](stage-plan.md)的 `names_identity`）、产物写出、GPU 锁与日志落地（[批次编排](batch-orchestration.md)）、Strata 的启停、身份核对与共享 session（中间层 `kototoki/strata.py`，细则见[翻译子系统](translation-subsystem.md#当前行为规格)"Strata 生命周期"）、翻译本身。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)；设计与验收依据见 [ADR-0014](../../adr/0014-name-consistency-in-product.md)、[ADR-0019](../../adr/0019-product-translation-q2.md)、[ADR-0022](../../adr/0022-product-names-on-strata.md) 与[验收记录](../../research/acceptance/2026-10-20-name-consistency-product.md)（27B 时期）。

## 当前行为规格

**阶段位置**：`… ─► ja-cues ─► names ─► translate ─► publish`。names 在 translate 之前，两者共用同一个 Strata session：第一次真正需要模型时启动（可能就在 names），两阶段之间不停，整批结束才 `--stop`（[批次编排](batch-orchestration.md)流程第 7–9 步）。建表必开：没有 `[names] enabled`，阶段链恒含 names。

**建表**（`build_document(work_dir, document, session, seed) -> BuildResult`，`session` 是编排传入的共享 `kototoki.strata.Session`）：

- 零条目 `ja.srt`：不碰 session，返回 `status = ok` 的空表（`attempts = 0`）。
- 否则 `session.ensure_started()` 取运行中的 Strata（必要时启动），以 `session.client_factory(server.url, timeout=1800, trace_dir=<work_dir>/names/transport/<UTC戳>-<pid>/session-NN)` 建客户端，用 Strata 回调调 `table.build_table`：整份 `ja.srt` 渲染成"SRT 编号<TAB>文本"一次送入；预算检查走 `/v1/messages/count_tokens`，system 与 user 两段各作一条 user 消息计数再相加，超过 15872（24576 − 8192 − 512）时不请求，返回 `too_long` 空表；否则请求 `/v1/chat/completions`，回复截断（`finish_reason == "length"`）或解析／校验失败即换 seed 重试：请求依次用 seed、seed＋1、…、seed＋4，最多 5 个请求，取第一张合格的表即停（`build_table` 两次一组；外层在结果为 `failed` 且还有请求额度时以 seed＋2k 再调一次，第 6 次尝试不发请求，与 v13 `build_one` 相同），仍失败返回 `failed` 空表（原因取最后一次错误的首行）。成功时 payload 为 `name-table-v2`：`work_guess`、`entries[]`、`meta`（实际 seed 与总尝试数、`dropped_shape`／`dropped_honorific`／`dropped_ja_shape`、`prompt_tokens`／`completion_tokens`、秒数）、`build`（`status`、`reason`、预算检查方式）。
- **请求体**与研究侧 v13 `NamesClient.chat` 逐字节相同：`_request_body` 的输出去掉 `response_format`，补 `model` 并把 `max_tokens` 改为 8192；`chat_template_kwargs.enable_thinking: false`、采样 0.7／0.8／20／`min_p` 0／`presence_penalty` 1.5、非流式、`seed` 为正整数。
- **`count_tokens` 退路**（同 v13）：该端点返回 HTTP／传输错误或响应形状不符（没有整数 `input_tokens`）时，本 session 内不再预检、计数按 0，运行日志一行 WARNING，只记录回复的 `usage.prompt_tokens`，超预算只在 `build` 里标记、不失败；不得因此放宽预算。
- 传输层失败（`HTTPError`、`URLError`、连接错误、超时）：`session.stop()` 停掉 Strata（下一部需要模型的影片再启动），抛 `NamesError`；HTTP 错误的消息只带状态码、分类（`oom`／`server_error`）与正文长度，正文留在交换目录。`ensure_started()` 抛 `StrataRefused`（身份不符、已有别的 launch、专家区退到 mmap）或启动失败整批累计 3 次时共享 session 已置 `unavailable`，本模块把它包成 `NamesError`；此后本批其余有 cue 的影片直接 `NamesError`，翻译阶段同样直接失败。

**失败与降级**（[ADR-0014](../../adr/0014-name-consistency-in-product.md) 第 3 条，建表引擎按 [ADR-0022](../../adr/0022-product-names-on-strata.md)）：

| 情况 | 结果 |
| --- | --- |
| 超预算（`too_long`）、5 次尝试都失败（`failed`） | 写空表（`build.status` 记原因），运行日志一行 WARNING，影片照常翻译与发布（空表不注入） |
| Strata 起不来或被拒绝、OOM、HTTP 错误、传输失败 | 该影片在 `names` 阶段文件级失败（`failure.json`）；重跑同一命令对它再建表 |

**表可人工校对，也是译法的唯一入口**：翻译按 Q2 规则注入表里 `confidence: high` 的实体，每个 `forms[]` 一行（[翻译子系统](translation-subsystem.md#当前行为规格)）。`name-table.json` 的跳过只比 `identity` 块（`ja_srt_sha256`、`BUILD` 配方 hash、`[names] seed`），用户改 `entries`（改错名、删条目、调 `confidence`）不触发重建。**改到会被注入的条目（`high` 的实体或其写法）会改变注入行的哈希 `names_sha256`，翻译身份随之变化；删掉该片源文件旁的 `*.ja-zh.srt` 后再运行即重译并重新发布（ADR-0020：字幕已存在的文件一律跳过）；只改 medium／low 条目不触发重译。** `ja.srt`、建表配方或 seed 变化会重建并覆盖手改，不做保护。ADR-0022 换了配方 hash，此前的所有表在下次运行时重建（已发布影片因源文件旁有字幕而跳过）。

**日志**（经编排写进运行日志，[批次编排：运行日志](batch-orchestration.md#运行日志)）：`[names] start: N file(s)`；Strata 的启动、等显存与内存、接入检查、停止来自中间层 `kototoki.strata` logger，前缀 `[strata]`；每部一行 `[names] done <相对路径>: E entries (D dropped), P prompt tok, C completion tok, T s`（零条目为 `no cues, empty table`；终态失败为 WARNING `build failed (<原因>), empty table`）；每次不合格的尝试（回复被截断、非 JSON、无有效条目）在该行之前各记一行 WARNING `[names] attempt n/2 failed (seed S): <错误首行>; finish …, C completion tok, reply N char(s)`（来自 `kototoki.names.table`，每组两次计数）；`count_tokens` 不可用时一行 WARNING；`[names] end: … s`。条目文字、`work_guess`、提示与回复正文不进日志，只在工作目录。

## 实现设计

- **配方与身份**：`BUILD`（配方 `q3-names-v1`：提示 v5 的 sha256、采样、schema sha256、`max_tokens` 8192、`reasoning off`、context 24576 与预算 15872、归一规则与常量、`attempts` 5 与 `seed_step` 1、模型 `qwen3.8-flash-next-iq3_s`、运行时身份（Strata 0.2.12、引擎 build 0.1.58、`launch: default` 及其解析值、kv `int8`，取值与翻译配方 `q2-degrade-v1` 的 `runtime` 相同，常量来自中间层 `kototoki.strata`）、请求形状（无 `response_format`、`enable_thinking: false`））一个字典，hash 用 `kototoki.recipes.recipe_hash`（`BUILD_RECIPE_HASH`，测试钉住）。与 Q3 的 `names-strata-v4`（`38cb7bcd…`）相同的是建表块、模型、运行时身份与请求形状；不同的是不含研究侧的说明字段（`prompt_budget_check`、`retries` 文字）与 llama.cpp 的 `model_asset`，所以 hash 不同。表的身份 `{ja_srt_sha256, recipe_hash: BUILD, seed}`，由[阶段计划](stage-plan.md)计算，以 `names` 键进 `published.json.sources`（审计记录）。表的内容经翻译身份的 `names_sha256` 影响译文（见上）。ADR-0019 删除了 `APPLY` 配方、`names-apply.json` 与 `names_apply` 身份键；ADR-0022 删除了 `NAMES_SERVER`、`NAMES_SPEC`、names 自己的 `Session` 与 `BUILD["model_asset"]`。
- **Strata 回调**：`chat(messages, seed)` 与 `tokenize(text)` 两个回调接到共享 session 的客户端（`LlamaClient`，`/v1/chat/completions` 与 `/v1/messages/count_tokens`），带请求额度（5 个请求）与 `count_tokens` 退路；请求体变换、额度与退路的写法与 `experiments/scene_batching_v6/v13.py` 的 `strata_body`、`NamesClient` 相同（复制，不导入；等价由测试导入 v13 对照）。
- **资源所有权**：Strata session 的证据在共用的 `<work root>/strata-sessions/<UTC戳>-<pid>/session-NN/`（归中间层，见[翻译子系统](translation-subsystem.md#当前行为规格)）；每部影片的原始交换在 `<work root>/<id>/names/transport/<UTC戳>-<pid>/session-NN/`（`count-NN` 为两段提示的计数请求，`chat-NN` 为建表请求），按运行分目录，重建时不与旧交换撞名。本模块不取 GPU 锁、不写 `name-table.json`（编排写）、不启停 Strata（只调 `ensure_started()`／`stop()`）。
- **移植来源**：`table.py` 来自 `experiments/name_consistency/build_table.py`（`SYSTEM_PROMPT` 逐字节相同，去掉 CLI、思考模式与重归一）；Strata 回调与 5 次尝试来自 `experiments/scene_batching_v6/v13.py`；只复制不导入。研究期的替换实现（`apply_table.py`）已于 ADR-0019 从产品删除，研究侧 `experiments/name_consistency/` 仍冻结。
- **命名**：`kototoki.names` 包顶层只导出 `build_document`、`NamesError`、`BUILD_RECIPE_HASH` 与 `BuildResult`。

## 接口与依赖

编排以 `importlib` 导入 `kototoki.names`，只用：`build_document(work_dir, document, session | None, seed) -> BuildResult`（`payload`、`attempts`、`seconds`、`status` ∈ `ok | failed | too_long`；`session` 是编排持有的共享 `kototoki.strata.Session`，零条目时可为 `None`）、`NamesError`，以及 `BUILD_RECIPE_HASH`。[阶段计划](stage-plan.md)延迟导入 `kototoki.names.recipes` 取该 hash。翻译子系统不导入本模块，只读它写出的 `name-table.json`（经 `plan` 传入内容）。

依赖基础层（`artifacts`、`config`、`srt`、`recipes`）与中间层 `kototoki.strata`（`StrataRefused`、Strata 身份常量；共享 `Session` 由编排传入）、`kototoki.llama_server`（`LlamaClient`、`explicit_oom`）；不导入 torch、推理模块、翻译子系统与 `experiments.*`（`tests/core/test_job.py` 的禁止导入测试连同 `kototoki.names` 一起守门）。不读配置（`seed` 由编排与阶段计划读）。

## 代码与验证入口

- 代码：`kototoki/names/__init__.py`（`build_document`、`NamesError`、Strata 回调与请求额度）、`kototoki/names/table.py`（`SYSTEM_PROMPT`、`build_messages`、`parse_reply`、归一函数、`build_table`、`BuildResult`）、`kototoki/names/recipes.py`（`BUILD`、`BUILD_RECIPE_HASH`）；编排侧 `kototoki/job.py` 的 `names_batch`。
- 测试（core，`just test`）：`tests/core/test_names_table.py`（渲染、解析与归一、上限、zh 形状、称呼词黑名单、提示 v5、日文写法形状、confidence 降级、`build_table` 的请求体、预算、两次尝试与 `too_long`／`failed` 空表、零条目）；`tests/core/test_names_recipes.py`（提示与 schema 的 sha256、`BUILD` hash 钉子、改值即改 hash、与 v13 `s1_recipe("v4")` 逐项对照、运行时身份等于翻译配方）；`tests/core/test_names_session.py`（伪 Strata session／伪客户端：正常建表、首次不合格后换 seed 成功、5 次都失败写空表且恰好 5 个请求、`count_tokens` 不可用的退路、传输失败与 HTTP OOM 抛 `NamesError` 并停 Strata、`StrataRefused`／不可用的 session 抛 `NamesError`、零条目不碰 session、交换目录与超时；与 v13 `NamesClient`＋`build_one` 的请求体与 seed 序列逐字节对照，测试导入 `experiments.scene_batching_v6.v13`）；`tests/core/test_job.py` 的 `NamesTests`（伪 names 与伪 strata 模块：阶段顺序与锁里的 Strata pid、表与 `sources` 的 `names` 键、终态失败空表照常发布并记 WARNING、session 不可用只让有 cue 的影片失败、建表异常只影响该影片且重跑恢复、零条目不取锁不启动）；`tests/full/test_job_ffmpeg.py`（共享 session 在 names 阶段启动、翻译后退出，`sources` 含 `names`）。已删除：`test_names_apply.py`（替换）；`test_assets_manifest.py` 里 names 模型资产的断言随 `model_asset` 一起删除。
- 真实模型验证（占 GPU，须用户批准，不属于任何 gate）：`just smoke names_product`（`scripts/smoke/names_product.py`）在产品自动启停的 Strata 上走 `plan.names_identity` → 共享 `Session` → `build_document` → `write_artifact`（默认 seed）；输入是脚本内置的 12 条合成日语短句（同一人名的正确写法与一处 ASR 式误写、一个职阶名、其余中性）；通过条件是 `expert_arena` 为 `ram`、`build.status == ok`、表至少一条 person、全程没有 llama-server 进程、`--stop` 后 status 为空且显存释放、无异常；结果只记计数、哈希、耗时与资源峰值。Strata 路径的运行结果记在 ADR-0022 所指计划的 §7。**历史记录（27B＋llama-server，2026-10-20）**：server 驻留 66/66 层在 GPU、冷加载 5.6 s、启动前空闲显存 15029 MiB、整机显存峰值 13444 MiB；建表一次成功（prompt 1655／completion 299 tokens、请求 6.1 s）得 2 条 person；当时的 `apply` 替换 3 处（已删除）。
- 真实运行（历史记录，27B＋llama-server，含已删除的发布时替换）：2026-10-20 票据 08 验收以 `.local/bilingual-fullfilm-08/w0.toml` 整批重跑 HF II／III（[验收记录](../../research/acceptance/2026-10-20-name-consistency-product.md)）：退出码 0，names 阶段 105.9 s（建表 49.5／40.5 s，prompt 13240／14609、completion 2382／1844 tokens），两表第一次尝试即 `ok`（20／15 条），替换 55／32 个 cue；不一致率 0.151 → 0.135、0.121 → 0.094。2026-11-08 Q2 整片两次运行建表 20 条（注入行 28）。Q3 规则（Flash-Next、5 次尝试）在研究侧 v13 的建表记录见 [ADR-0021](../../adr/0021-q3-strata-names-baseline.md)。
- 未验证：Strata 路径的产品运行（smoke 与整片）在计划 §7 记录前只经伪服务测试；产品写出的表尚未人工抽看；注入后的译文质量只有研究侧 Q2／Q3 证据；x0 输出、其他作品与剧集、`too_long`／`failed`、`count_tokens` 退路与 Strata 起不来等失败路径的真实运行；同一 seed 下建表的可重复性（v13 观测同一部片两次建表写法 Jaccard 0.56／0.48）。

## 变更与决策来源

[ADR-0014](../../adr/0014-name-consistency-in-product.md)（研究线结题与冻结配置、进产品）；票据 `.scratch/name-consistency-product/`（01–09）：02（共享 llama-server）、03（建表与配方）、04（替换）、05（配置、阶段计划与产物常量）、06（编排接入与本页）、07（smoke）、08（产品路径验收，[验收记录](../../research/acceptance/2026-10-20-name-consistency-product.md)）、09（收口）。

2026-10-20 吸收增量说明《专名一致性进产品》（`docs/changes/name-consistency-product.md`，已删除）：设计与取舍写入上文与 [ADR-0014](../../adr/0014-name-consistency-in-product.md)，用户裁定（6 条）在 ADR-0014"决定"一节；增量说明 §3.2 的 `names/transport/attempt-N.*` 未按其实现，实际为 `names/transport/<UTC戳>-<pid>/session-NN/`，以本页"实现设计"为准。

2026-11-08 产品翻译切到 Q2（[ADR-0019](../../adr/0019-product-translation-q2.md)）：删除发布时专名替换（`names/apply.py`、`names-apply.json`、`APPLY` 配方与 `names_apply` 身份键、`[names] enabled`）；表只经翻译注入使用，手改会被注入的条目即重译。

2026-11-09 产品建表切到 Strata（[ADR-0022](../../adr/0022-product-names-on-strata.md)，计划 `docs/plans/product-names-on-strata.md`，tracker `.scratch/q3-product-switch/`）：建表改在与翻译共用的 Strata session 上用 Flash-Next 按 Q3 规则做（配方 `q3-names-v1`，5 次尝试，`count_tokens` 预算检查），删除 names 的 llama-server session、`NAMES_SERVER`／`NAMES_SPEC`、`BUILD["model_asset"]` 与配置键 `[names] model`／`port`、`[paths] llama_server`；上文已按此改写，27B 时期的验证结果保留为历史记录。
