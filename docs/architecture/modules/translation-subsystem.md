# 翻译子系统与双语合并

状态：current（票据 05 交付，2026-10-14；票据 09 加入三级降级与回退报告，2026-10-14；票据 16 产品配方 `dp10-cut-degrade-v1`，2026-10-18；**2026-11-08 起产品翻译即 Q2**，配方 `q2-degrade-v1`，Strata 自动启停，[ADR-0019](../../adr/0019-product-translation-q2.md)）。Q2 路径只经伪服务／伪客户端离线验证，**真实运行未做**（见"代码与验证入口"）。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md) §3.3、§4、§6，[模块边界](../module-boundaries.md#产品包的责任边界)）中 `ja.srt → 译文` 与 `ja.srt + 译文 → ja-zh.srt` 两步：Strata 服务的启停与身份核对、`dp10-cut` 切包与 Q2 请求、专名注入、按批次落盘与续跑、基础设施失败的重启、批次终态失败的 10→5→1 降级与回退报告，以及中日两行合并。不负责：GPU 锁与 Job Object（[批次编排](batch-orchestration.md)）、`zh.srt`／`ja-zh.srt` 的写出与发布（编排器）、专名表的建表（[专名一致性](name-consistency.md)）、工作目录 `.work/<id>/` 本身的位置（[产物契约](artifact-contract.md)）、任何时间换算。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。研究侧同名规则见 `experiments/translation_v3/{qwen,strata}.py` 与[完整 SRT 翻译流程](translation-srt-flow.md)，本模块是 Q2 的产品移植，不导入它们。

## 当前行为规格

**对编排器的接口**（`kototoki.translate`）：

- `Session(config, on_server_pid=None)`：上下文管理器，整批影片共用一个 Strata session。第一次真正需要请求模型时才启动 Strata（已全部完成的影片不启动）；`on_server_pid(pid)` 在服务 ready 后以 `strata launch --status` 报告的 pid 回调（报告里没有 pid 时不回调）、`on_server_pid(None)` 在停止后回调，供编排器写进 GPU 锁；退出（含异常与被中断）时总是 `stop`。`unavailable` 非空表示 Strata 本批不可用，其余需要模型的影片直接失败。
- `plan(work_dir, document, name_table, config) -> TranslatePlan`：`document` 是 `srt.read_srt` 读出的 `ja.srt`，`name_table` 是该影片 `name-table.json` 的内容（[阶段计划](stage-plan.md)的 `translate_plan` 读出传入）。只读、不写文件，返回 `run_dir`（`<work_dir>/translate/srt-<sha12>/q2-degrade-v1__s<seed>__n<names_sha12>/`，`relative` 为相对工作目录的 posix 串，发布记录的 `translate_dir` 即它）、`identity`（`{ja_srt_sha256, recipe_hash, seed, names_sha256}`，阶段计划的 translate 身份由此取得）、`needs_model`（零条目文档或 `run.json` 已记 `complete` 时为 False；编排器据此决定要不要取 GPU 锁、建 `Session`）、`document` 与 `names`（注入行）。`run.json` 已存在但配方 hash／seed／注入行／来源不符时抛 `ValueError`，消息含"删除该目录可重译"。
- `translate_document(plan, session) -> TranslateResult`：`plan` 来自上一条；`needs_model` 为 False 时 `session` 可为 `None`，只读回已完成的 run（run 记为完成而批次文件缺失即抛 `TranslateError`，不起 Strata）。返回 `translations`（cue id → 译文，精确覆盖全部 cue；回退的 cue 为日文原文）、`fallback_count`（回退为日文的 cue 数，编排器写进 `published.json` 的 `translate_fallback_cues`、发布日志行与控制台汇总）与 `report`（即 `report.json` 的内容）。基础设施失败用尽重启或 Strata 被拒绝时抛 `TranslateError`（编排器记为该文件翻译失败）。
- `RECIPE_HASH`：产品翻译配方 `q2-degrade-v1` 的 hash `332649cf…310d`，进翻译身份，由 `tests/core/test_translate_recipes.py` 钉住。配方字典 `RECIPE`（`recipes.py`）含：切包 `gap-pack-v2`（`dp10-cut` 参数）、邻文 `wide-context-v1`、提示 `qwen-joint-v1`（system／user 文本的 sha256）、专名注入 `qwen-name-table-v1`（header sha256、过滤 `window`、取行规则）、模型 `qwen3.8-flash-next-iq3_s`、Strata 版本与解析后的启动配置（ADR-0017）、请求形状与采样、两次尝试的 seed 步长、首次 `cache_n` 只记录、输入预算只记录、校验规则、溢出策略 `degrade-10-5-1-keep-source`。注入行的**内容**不进配方 hash，进翻译身份的 `names_sha256`。

**请求**（Q2 规则，[ADR-0017](../../adr/0017-q2-strata-default-launch-baseline.md)、[ADR-0019](../../adr/0019-product-translation-q2.md)）：每部影片是一个场景，cue ID 用 `srt.py` 的 `<sha8>-cue-<n>` 别名，cue 带 `ja.srt` 的起止秒。

- **切包**按 `dp10-cut`（[ADR-0010](../../adr/0010-dp10-cut-translation-flow-baseline.md)，`batching.gap_pack_cuts`，参数同前）：整个场景用动态规划取总惩罚最低的切法，每批待译 ≤10 条；每批代价 = (条数 − 10)² ＋ 批内每个 ≥2 s 停顿按秒数计 1 分，<6 条加 1000 分，批内有 ≥20 s 停顿不可行；内部切点按停顿分级加罚（<0.5 s 加 6、<1 s 加 3、<2 s 加 1，缺时间戳按无停顿）。停顿只取自 `ja.srt` 自身的时间轴、只比较长短，不是时间换算。
- **只读邻文**（`batching.neighbours`，`wide-context-v1`）：前 20 条、后 5 条，只按条数取到场景边（不再看停顿）；可见总数（含待译）超过 35 条时先去后邻、再去前邻。降级的子批次用同一规则。
- **提示**（`recipes.messages`，`qwen-joint-v1`）：chat messages 两条。system 是 joint 任务文本，该批有专名注入行时末尾追加 `qwen-name-table-v1` 的 header 与 `日文 → 中文` 逐行（见下）；user 是只读日文上下文（JSON）加待译 JSON `{"translations": {id: 日文}}`。文字与研究侧 `experiments/translation_v3/qwen.py::messages` 逐字节相同。
- **专名注入**：`recipes.name_rows(table)` 取该影片 `name-table.json` 里 `confidence: high` 的实体，每个 `forms[]` 一行 `{ja → zh}`，按 `ja` 去重，跳过空写法；某批只注入日文写法出现在该批可见台词（含只读邻文）里的行。表为空（建表终态失败）时不注入，翻译照常。只改 medium／low 条目不改变注入行。
- **请求体**（`recipes.request_body`）：chat completions，不用 grammar，思考关闭（`chat_template_kwargs.enable_thinking = false`），`temperature 0.7、top_p 0.8、top_k 20`，`max_tokens` 4096，非流式，`seed` 取 `[translate] seed`（须为正整数）。同一批最多两次：seed、seed＋1。正常批的请求体与研究侧 `strata.request_body(qwen.messages(…))` 逐字节相同（测试对照）。
- **校验**（`recipes.parse_translation`）：严格 JSON（重复键拒绝）、恰好一个 `translations` 对象、ID 集合与顺序同待译、值非空；产品另拒绝含空行的译文（会让 SRT 断块，按解析失败处理）。
- 首个请求的 `cache_n` 只记录，不据此判失败；输入 token 超过 Q1 预算（12224）只记 `over_q1_budget`，不判失败（Strata 的 context 是 131072）。

**失败分类**（沿用 `run_step`，去掉 grammar 与预算端点分支）：

| 种类 | 来源 | 处理 |
| --- | --- | --- |
| `oom`、`server`（传输／连接断开）、`server_error`、`server_start` | HTTP 报 OOM 文本／5xx、连接失败或超时、响应 `error`、Strata 起不来（`strata launch` 失败、等 ready 超时、空闲显存不足） | 停掉 Strata，同一次调用内启动新 session 重做；最多重启 2 次，仍失败抛 `TranslateError` |
| `context`、`limit`、`parse` | HTTP 报超出 context、`finish_reason == "length"`、空回复、JSON／ID／空行校验失败 | 批次终态（`context` 不再重试第二次）：按下节降级，不重启、不使该影片失败 |
| `StrataRefused` | 已有别的 launch 在服务；版本、端口、run config、`/v1/models`、原生 context 与 ADR-0017 不符 | 不重试：`Session.unavailable` 置位，本批其余需要模型的影片直接失败，已启动的 Strata 随即停掉 |
| 其他异常 | 非 JSON 响应、写盘失败等 | 该 session 记 `stop_reason = session_error: …`，停掉 Strata，原样上抛 |

**降级**（`degrade.py`，规格 §6）：批次终态失败（两次尝试都失败）后拆成前后两半 `父ID.a`／`父ID.b`（奇数条前半多 1 条），仍失败的半批拆成单条 `父ID.a.1`…，单条仍失败则该 cue 的译文 = 日文原文（回退，原因取该单条的失败种类）；只有 1 条的批次失败即回退。子批次与原批次用同一条邻文规则、同一 seed、同一专名注入规则。降级中每个节点（含失败的原批次）的结果一出来就追加到 `degrade.jsonl`；降级途中的基础设施失败照常重启 Strata，新 session 从未记录的节点继续，已记录的节点不再请求。整个批次完成后写成 `batches.jsonl` 的一行（带 `degrade.nodes` 与 `degrade.fallback`），回退由此对该配方 hash、seed 与注入行是终态：重跑同一命令不再尝试，要重试须改 `[translate] seed`（另起 run）；`force` 不触发重译。研究侧 Q2 对失败的包只空出该包，产品的 10→5→1 是唯一差别（[ADR-0019](../../adr/0019-product-translation-q2.md) 第 4 点）；它与两次可靠性尝试都不是"翻译多次再挑选"（[ADR-0008](../../adr/0008-no-multi-translation-selection.md)）。

**Strata 生命周期**（`strata.StrataServer`，一个 session 一次进入／退出）：

1. 进入：`strata launch --status --output json` 必须没有正在服务的 launch，否则 `StrataRefused`（不抢占、不替别人停）；`nvidia-smi` 轮询到空闲显存 ≥ 14000 MiB（names 的 llama-server 已释放；120 s 超时按 `server_start` 失败处理）；执行 `strata launch --no-tui --model iq3_s`（不带参数的 `strata launch` 只能在终端里走向导，子进程里不点名模型时以退出码 2 拒绝；`--model iq3_s` 就是默认选择：2026-11-08 本机两者的 `--plan` 逐行相同，只差前者多一行"未点名模型"的提示，即 ADR-0017 的 Q2 启动配置，DFlash2）；轮询到唯一一个 `ready` 的 launch（300 s）。
2. 身份核对（`strata.probe`）：`strata --version` 为 0.2.12／build 0.1.58，launch 在 `127.0.0.1:8080`，run config 的 `model_name` 为 `qwen3.8-flash-next-iq3_s`、`--max-context 131072`、DFlash2 起草，`/v1/models` 含该模型，`/v1/status` 的原生 context 为 131072。不符即 `StrataRefused`，并停掉刚启动的服务。
3. 运行中：`ResourceSampler` 每 5 s 从 `/v1/status` 取整机显存与内存峰值；服务日志只计事件数（推理循环自救、logits 非有限、单 token 重复截停），不复制日志。
4. 退出：`strata launch --stop`，再核实 `--status` 为空、空闲显存回到 14000 MiB；核实失败只记 ERROR 与 `strata-final.json`，不抛出（退出路径上不盖住原异常）。产品进程被强杀时 Strata 可能留在后台，下次运行因 status 非空而拒绝，须手动 `strata launch --stop`。
5. 证据：`<output_dir>/.work/translate-sessions/<UTC戳>-<pid>/session-NN/` 下 `strata.json`（接入时观察到的身份，不含 API key）、`resources.json`（显存／内存峰值、日志事件计数）、`strata-final.json`（停止与显存释放核实）。

**session**：一次 Strata 进入／退出即一个 session。首个 completion 的 `cache_n` 只在每个 session 记录一次（`run.json` 的 `cache_reset`）。每次重启都是新 session：影片 `run.json` 的 `sessions[]` 新增一项、`cache_state` 重置、写过批次或遇到基础设施失败的 session 超过一个时 `resumed = true`。Strata 启动失败（`server_start`）不新增 `sessions[]` 项，记入 `server_start_failures[]`。某部影片的重启额度全部耗在 `server_start` 上时，`Session` 记为不可用，本批其余影片直接抛 `TranslateError`，不再逐片等待；混有其他种类的失败不触发这一点。Strata 与 names 的 llama-server 不同时驻留（[模块边界：并发与生命周期](../module-boundaries.md#并发与生命周期)）；没有影片需要模型时不启动。

**run 目录与续跑**：`translate/srt-<sha12>/q2-degrade-v1__s<seed>__n<names_sha12>/`，键由本子系统的 `plan` 唯一决定（`batching.source_key` 给出 `srt-<sha12>`，同时是场景 ID）：`ja.srt` 变化换 `srt-<sha12>`，配方名、seed 或注入行变化换子目录，旧目录都保留。**手改 `name-table.json` 里会被注入的条目（`confidence: high` 的实体或其 `forms`）即换 `names_sha12`，下次运行重译该片；只改 medium／low 条目不会。** 配方**内容**变了而名字未变（hash 不符）不自动另开目录，`plan` 拒绝并提示删除该目录（零迁移）。旧 `dp10-cut-degrade-v1` 的 run 目录原样留在工作目录、不再读取：已发布影片因 `sources` 不再匹配，下次整批运行重新翻译并发布。

- `run.json`：只含该影片；配方、hash、seed、`names`（注入行 SHA256 与行数）、来源（`ja.srt` SHA256、场景 ID、cue ID 列表）、`sessions[]`（Strata 身份摘要 `candidate`／`strata`／`cold_load_seconds`／`free_vram_mib_before_start`、`server_session` 指向的运行日志目录、写入批次数、停止原因、基础设施失败与证据、缓存记录、墙钟）、`server_start_failures[]`、`resumed`、`completion`。已存在且配方／seed／注入行／来源不符时报错。
- `batches.jsonl`：每完成一批追加一行并 fsync，随即重写 `run.json`（进程被强杀时 `sessions[]` 仍反映已写批次）（批次计划字段、译文、请求与逐次尝试记录、所属 session；降级完成的批次不带顶层请求，改为 `degrade`：各节点（`nodes[0]` 是原批次）的 ID、层级、状态、失败种类、尝试次数与完整请求记录，以及回退 cue 的 ID、原因、错误与累计尝试次数）。续跑时末尾不完整的一行截掉，其余行须与批次计划一致，从第一个未写入的批次继续。
- `degrade.jsonl`：降级中各节点的结果，每个节点完成即追加；续跑时同样截掉不完整的末行，只取未完成批次的节点，行须属于批次计划且不重复。
- `scene.json`：全部批次完成后才写出（cue 位置、批次、全部译文、降级树、`fallback_ids`、按节点计的请求／尝试与 token 统计）；部分完成的影片没有该文件。
- `report.json`：完成时写出（零条目也写）：`completion`、计数（批次、降级批次、回退 cue、降级请求数）、每个降级批次的节点摘要与回退 ID、回退 cue 清单。
- `transport/session-NN/`：逐请求原始交换（请求 JSON、原始响应、传输记录）；`infra-failures/`：基础设施失败时该批次（或降级节点）的尝试记录。

零条目 `ja.srt`：写 `run.json`（完成），返回空译文，不启动 Strata、不请求模型。

**日志**：经 `kototoki.translate.*` logger 发事件，写进编排的运行日志（[批次编排：运行日志](batch-orchestration.md#运行日志)）：session 起止、Strata ready／停止与每批一行（cue 数、输出 token、tok/s、cache，取不到的字段省略）为 INFO；Strata 重启、降级拆批与单条回退为 WARNING；用尽重启放弃、`StrataRefused`、停止未核实为 ERROR。`StepFailed` 的 HTTP 错误与 server error 消息只含状态码／kind 与正文长度，不嵌入响应正文（正文留在 `transport/…/response.raw`）。提示、译文与响应正文不进日志。

**合并**（`kototoki.merge.merge(ja_document, zh_translations) -> srt_text`）：纯函数；沿用日文 cue 的编号与时间行，每条两行，中文在上、日文在下；中文与日文内的换行都替换为空格，保证每条恰好两行；回退为日文的条目两行相同，照常输出。译文须精确覆盖全部 cue（缺失、多余、空串抛 `IncompleteTranslationError`）；零条目文档得到空串。

## 实现设计

移植来源与取舍（产品包不导入 `experiments.*`，只复制）：

| 文件 | 来源 | 取舍 |
| --- | --- | --- |
| `recipes.py` | `experiments/translation_v3/{qwen,strata}.py`、`names11.product_tables`、v9 `wide-context-v1` | Q2 规则写成常量：提示、注入行与过滤、请求体、校验、配方字典与 hash；与研究侧逐字节对照由测试钉住；新增的校验（拒绝空行）与降级字段使它另算 hash（`q2-degrade-v1`） |
| `strata.py` | `experiments/translation_v3/strata.py::probe` 的 `"default"` 分支 | 产品新增启停：`strata launch --status`／`--no-tui --model iq3_s`／`--stop`、空闲显存与 status 核实、资源采样；只有这一个实现，不抽后端协议 |
| `degrade.py` | 新增（研究侧 Q2 只空出失败的包） | 拆分规则、降级树与回退、`report.json` 内容；不导入 `generate`，由其传入请求函数与降级日志；邻文经 `batching.neighbours` |
| `batching.py` | `translation_v3/batching.py`、`data.py` | gap-pack-v2 切包（`silence`、`gap_pack_cuts` 只留 `group_gap=None` 分支）、`wide-context-v1` 邻文；`Scene`／`Cue`（带秒）由 `ja.srt` 构造，`source_key` 是 `srt-<sha12>` 的唯一出处 |
| `generate.py` | `translation_v3/strata.py::run_step`、`generate.py` | `run_step` 判定不变（去掉思考分支）；`Session` 取代研究侧"执行者先启动服务"；按批次追加落盘；同调用内重启 Strata |

`kototoki/llama_server.py` 不再是翻译的服务层：翻译只用其中的 `LlamaClient`（本机回环 HTTP，含 `chat_completion` 与逐请求 trace）、`wait_for_free_vram`／`nvidia_smi`、`InfraFailure` 与 `explicit_oom`。已删除：`adapters.py`（Hy30 原生模板与 ID grammar）、`server.py`（`TRANSLATE_SPEC`、`MODEL_ASSET`、`MIN_FREE_MIB` 14700）、H0 配方 `dp10-cut-degrade-v1` 及其 `/tokenize` 预算、`[translate] model`／`port`。

## 接口与依赖

依赖标准库、`kototoki.artifacts`、`kototoki.config`（只读 `paths.output_dir`、`translate.seed`）、`kototoki.srt` 与中间层 `kototoki.llama_server`（`LlamaClient`、`InfraFailure`、`nvidia_smi`、`wait_for_free_vram`、`explicit_oom`）；外部依赖是 Strata CLI 与本机 8080 服务（安装与模型由用户维护，见[依赖布局](../../development/dependencies.md)）。不导入 `names`（只读它写出的表内容，由 `plan` 传入）、`experiments.*`。编排器只导入包顶层的 `Session`、`translate_document` 与 `kototoki.merge`，[阶段计划](stage-plan.md)延迟导入包顶层的 `plan` 取 `TranslatePlan`；`RECIPE_HASH` 也在包顶层导出；`recipes`、`strata`、`batching`、`degrade`、`generate` 是内部实现。内部接缝：`Session(server_factory=..., client_factory=...)` 只供测试替换服务（须有 `url`、`identity` 与上下文管理器协议）与 HTTP 客户端。

## 代码与验证入口

- 代码：`kototoki/translate/`（`recipes.py`、`strata.py`、`generate.py`、`batching.py`、`degrade.py`）、`kototoki/merge.py`；共享的 `kototoki/llama_server.py`（客户端部分）。
- 测试（core，`just test`）：`tests/core/test_translate.py`（伪服务／伪客户端走完整流程：正常、续跑与截掉写了一半的行、全部完成不启动 Strata、基础设施失败重启即新 session 与放弃、`StrataRefused` 不重试且置 unavailable、注入行变化另起 run、空场景等）；`tests/core/test_translate_degrade.py`（拆分与邻文、10→5→1 降级与单条回退、超出 context 进入降级、续跑复用已记录节点、回退终态、经编排器写进 `published.json` 的回退计数）；`tests/core/test_translate_recipes.py`（`RECIPE_HASH` 钉子、提示／注入／请求体与研究侧逐字节对照、gap-pack-v2 规则）；`tests/core/test_llama_server.py`（共享模块：客户端、显存轮询、OOM 识别、names 用的命令行拼装）；`tests/core/test_merge.py`。`tests/core/test_translate_strata.py`（伪 CLI：已有 launch 时拒绝且不替别人停、等 names 释放显存、`probe` 各项不符即停并拒绝、未就绪／启动失败／被中断都 `--stop`、停止未确认或显存未释放只记 ERROR）。已删除：`test_translate_server.py`（H0 命令行）。
- 真实模型验证（占 GPU，须用户批准，不属于任何 gate）：Q2 首用 smoke（`just smoke translate_product`，`scripts/smoke/translate_product.py`，改为走 Strata）。**未运行。**
- Q2 启动配置首用与整片端到端：ADR-0017 建议的 smoke（整机内存与显存峰值、首次格式失败、交付失败、每包耗时）与一部整片的端到端运行。**未运行，结果待用户补记。**
- 未验证：Strata 自动启停与身份核对的真实运行（含停止后显存回到 14000 MiB、强杀残留的拒绝路径）；降级路径只经伪客户端；Strata 的请求不复现（同 seed 约半数 cue 不同，ADR-0017），重跑不保证同一译文；`q2-degrade-v1` 在产品里的质量没有独立裁判证据（沿用 ADR-0017 的 v12 F1 证据）。已知限制：空闲显存低于 14000 MiB（桌面程序占用较多）时翻译等满 120 s 后按 `server_start` 失败。

## 变更与决策来源

票据 `.scratch/bilingual-subtitle-pipeline/issues/05-translate-and-merge.md`、`09-translate-degrade.md`、`15-translate-run-key.md`（run 键、身份与 `needs_model` 归本子系统的 `plan`；`data.py` 并入 `batching.py`）、`16-translate-dp10-cut.md`（产品配方合并 dp10-cut 切包）；规格 §1.2（含第三轮裁定表）、§3.3、§4、§5.2、§6、§7.3；[ADR-0005](../../adr/0005-apex-i-compact-translation-baseline.md)、[ADR-0010](../../adr/0010-dp10-cut-translation-flow-baseline.md)、[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0010](../../adr/0010-dp10-cut-translation-flow-baseline.md)；stock 引擎的 `run_step` 假设与驻留日志由票据 01 smoke #4 验证。

2026-10-18 吸收增量说明《依赖入项目与测试分层调整》（`docs/changes/local-dependencies-and-test-layers.md`，已删除）：新增真实模型验证 `just smoke translate_product`（未运行）；`MODEL_ASSET` 由 core 测试钉住等于 `assets.toml`。

2026-10-19 架构审计小修集合：票据 `.scratch/architecture-review/issues/01-small-fixes.md`（B-14 stderr 去重与 UTC 目录名、C-6 `server_stop`）；旧 session 目录（本地时间戳、含 `stderr.log`）原样保留，不迁移。

2026-10-19 专名一致性进产品（[ADR-0014](../../adr/0014-name-consistency-in-product.md)）：票据 `.scratch/name-consistency-product/issues/02-shared-llama-server.md`：`server.py` 的通用部分与 `client.py`、`procs.py` 抽到 `kototoki/llama_server.py`（第二个使用者是专名建表），翻译行为不变；`Session` 不动，只把 `_managed_server` 改为传 `TRANSLATE_SPEC`。

2026-11-08 产品翻译切到 Q2（[ADR-0019](../../adr/0019-product-translation-q2.md)）：配方 `dp10-cut-degrade-v1` 换成 `q2-degrade-v1`（Strata 上的 `qwen3.8-flash-next-iq3_s`、chat completions、`wide-context-v1`、`qwen-joint-v1`、专名注入），Strata 由 `strata.py` 自动启停，翻译身份加 `names_sha256`；删除 `adapters.py`、`server.py`（`TRANSLATE_SPEC`、`MODEL_ASSET`）、H0 的 grammar 与 `/tokenize` 预算、`[translate] model`／`port`；上文各章已按 Q2 改写，旧描述不再保留。
