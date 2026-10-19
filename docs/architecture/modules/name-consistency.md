# 专名一致性（建表与发布时替换）

状态：current（2026-10-20 票据 06 接入编排；建表、替换与配方由票据 03、04 移植，[ADR-0014](../../adr/0014-name-consistency-in-product.md) 进产品）。离线由伪 server／伪客户端与伪 names 模块测试；真实 Qwen server 路径（票据 07 smoke，2026-10-20 通过）与两部整片产品路径（票据 08 验收，判据 ①②③ 满足、④ 待用户抽看）已在真机验证，详见下文“代码与验证入口”。

## 定位与阅读

负责双语字幕流水线中专名译法的统一：GPU 阶段 `names` 用 Qwen3.8-27B（no-think）为每部影片的 `ja.srt` 建一张专名表（`name-table.json`），发布前用一个纯函数按表替换译文里同一专名的各种写法（审计文件 `names-apply.json`）。配置照抄 [ADR-0013](../../adr/0013-name-consistency-closed.md) 冻结的最佳已知配置（提示 v5、程序兜底全开；替换规则一＋孤立单字），不调参。不负责：阶段链与身份（[阶段计划](stage-plan.md)的 `names_identity`／`names_apply_identity`）、产物写出、GPU 锁与日志落地（[批次编排](batch-orchestration.md)）、llama-server 的进程与身份核对（共享的 `kototoki/llama_server.py`，来源与命令行拼装见[翻译子系统](translation-subsystem.md)）、翻译本身。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)；设计与验收依据见 [ADR-0014](../../adr/0014-name-consistency-in-product.md) 与[验收记录](../../research/acceptance/2026-10-20-name-consistency-product.md)。

## 当前行为规格

**阶段位置**：`… ─► ja-cues ─► names ─► translate ─► [替换] ─► publish`。names 在 translate 之前：两个 llama-server 模型各 12–15 GB，必须串行；先建表再翻译，translate 仍是最后一个 GPU 阶段。`[names] enabled = false` 时链跳过 names、发布不替换，行为与接入前相同。

**建表**（`build_document(work_dir, document, session, seed) -> BuildResult`）：

- 零条目 `ja.srt`：不起 server，返回 `status = ok` 的空表（`attempts = 0`）。
- 否则 `session.ensure_started()` 取运行中的 server，以 `LlamaClient(server.url, timeout=1800, trace_dir=<work_dir>/names/transport/<UTC戳>-<pid>/session-NN)` 调 `table.build_table`：整份 `ja.srt` 渲染成"SRT 编号<TAB>文本"一次送入；system 与 user 两段经 `/tokenize` 计数之和超过预算（20480 − 4096 − 512）时不请求，返回 `too_long` 空表；否则最多两次 `/v1/chat/completions`（第二次 seed+1），回复截断或解析／校验失败即重试，仍失败返回 `failed` 空表（原因取最后一次错误的首行）。成功时 payload 为 `name-table-v2`：`work_guess`、`entries[]`、`meta`（实际 seed 与 attempt、`dropped_shape`／`dropped_honorific`／`dropped_ja_shape`、`prompt_tokens`／`completion_tokens`、秒数）、`build`（`status`、`reason`）。
- 传输层失败（`HTTPError`、`URLError`、连接错误、超时）：停掉当前 server（下一部影片再启动），抛 `NamesError`；HTTP 错误的消息只带状态码、分类（`oom`／`server_error`）与正文长度，正文留在交换目录。

**Session**（整批共用）：首次需要时启动；server 进程已退出时下一部影片 `ensure_started` 先收尾再重启；整批最多启动 3 次（重启 2 次）。任何一次启动失败（显存不足、加载失败或超时、端口被占、模型或引擎核对不过）即置 `unavailable`，本批其余需要模型的影片直接 `NamesError`，不再尝试启动；用尽 3 次同样置位。每部影片只有一个请求，不做同调用内重启。`on_server_pid` 在 server 启动后以 pid、停止后以 None 回调，编排据此写 GPU 锁的 `server_pid`。

**替换**（`apply(table, document, translations) -> ApplyResult`）：纯 CPU 纯函数，输入 `cue id → 译文`，输出覆盖全部 cue 的新译文与审计记录（`changes`、`unresolved`、`summary`）。cue 的日文里最长的 `form.ja` 锚定该 cue，在该 cue 译文里找落点（同实体其他写法的中文 → 过特异性检验的 `zh_variants` → 跨 cue 统计），整段替换成该写法的 `zh`；统计层落点按规则一扩展到整个名字，单字候选只数孤立出现；落点重叠、紧邻复合名连接符或不在词边界上时不动，记 `unresolved`。译文等于日文原文的 cue（翻译回退）不参与。表的 `schema` 不是 `name-table-v2` 或缺 `entries` 抛 `ValueError`；空表原样返回。

**失败与降级**（[ADR-0014](../../adr/0014-name-consistency-in-product.md) 第 3 条）：

| 情况 | 结果 |
| --- | --- |
| 超预算（`too_long`）、两次尝试都失败（`failed`） | 写空表（`build.status` 记原因），运行日志一行 WARNING，影片照常翻译与发布（不替换） |
| server 起不来、OOM、HTTP 错误、传输失败 | 该影片在 `names` 阶段文件级失败（`failure.json`）；重跑同一命令对它再建表 |
| `apply` 抛异常（表被改坏） | 该影片 `publish` 阶段失败，不发布半成品 |

**表可人工校对**：`name-table.json` 的跳过只比 `identity` 块（`ja_srt_sha256`、`BUILD` 配方 hash、`[names] seed`）。用户改 `entries`（改错名、删条目）不触发重建，但文件 SHA256 变了，`names_apply` 身份随之变化，下次运行只重做替换与发布（翻译 run 已完成，不起 Hy-MT2）。`ja.srt`、建表配方或 seed 变化会重建并覆盖手改，不做保护。

**日志**（经编排写进运行日志，[批次编排：运行日志](batch-orchestration.md#运行日志)）：`[names] start: N file(s)`；server 加载、加载失败与等显存三条来自共享的 `kototoki.llama_server` logger，前缀 `[names]`（`NAMES_SPEC.stage`）；每部一行 `[names] done <相对路径>: E entries (D dropped), P prompt tok, C completion tok, T s`（零条目为 `no cues, empty table`；终态失败为 WARNING `build failed (<原因>), empty table`）；`[names] end: … s`；发布行追加 `, R name replacement(s)`，`[summary]` 末尾加 `N name replacement(s)`（R 为 `names-apply.json` 的 `changes` 条数）。条目文字、`work_guess`、提示与回复正文不进日志，只在工作目录。

## 实现设计

- **server 配置**：`NAMES_SPEC`（`ServerSpec`）由 `recipes.NAMES_SERVER`（candidate `qwen3.8-27b-ud-iq3_s`、repo／revision、99 层、`-c 20480`、`-b 512 -ub 512 -fa on --jinja --reasoning off`、空闲显存阈值 13000 MiB、加载超时 180 s）与 `BUILD["model_asset"]`（文件名、大小、sha256）拼成；`ManagedServer` 另加 `--no-webui --log-file … -lv 4`。模型路径 `[names] model`（默认 `glossary-v1/Qwen3.8-27B-UD-IQ3_S.gguf`，相对 `models_root`）、端口 `[names] port`（默认 8081，与翻译的 8080 分开）。
- **配方与身份**：`BUILD`（提示 v5 的 sha256、采样、schema sha256、`max_tokens`、`reasoning off`、上下文与预算、归一规则与常量、两次尝试与 seed 步长、模型资产）与 `APPLY`（id `names-apply-v1`、规则开关的冻结取值、`MIN_SUPPORT`／`MIN_RATIO`／`MIN_SHARE`／`MAX_EXTEND`／`EXTEND_SHARE`、n-gram 范围、`EDGE_STOP`、中文敬称、`BOUNDARY_CHARS`）两个字典，hash 用 `kototoki.recipes.recipe_hash`。表的身份 `{ja_srt_sha256, recipe_hash: BUILD, seed}`；`names-apply.json` 的身份 `derived_identity(upstream={name-table.json: sha256}, recipe_hash=APPLY)`；两者由[阶段计划](stage-plan.md)计算并进 `published.json.sources` 的 `names`／`names_apply` 键。
- **资源所有权**：server 运行日志在 `<output_dir>/.work/names-sessions/<UTC戳>-<pid>/session-NN/`（`server.log`、`stdout.log`、`engine.json`、`engine-final.json`，与 `translate-sessions/` 同形）；每部影片的原始交换在 `<work_dir>/names/transport/<UTC戳>-<pid>/session-NN/`（`00001`、`00002` 为两段提示的 `/tokenize`，`chat-NN` 为建表请求），按运行分目录，重建时不与旧交换撞名。本模块不取 GPU 锁、不写 `name-table.json`／`names-apply.json`（编排写）。
- **移植来源**：`table.py` 来自 `experiments/name_consistency/build_table.py`（`SYSTEM_PROMPT` 逐字节相同，去掉 CLI、思考模式与重归一）；`apply.py` 来自 `experiments/name_consistency/apply_table.py` 的默认路径加 `experiments/quality_v5/consistency.py` 中被用到的片段，研究期开关与 `measure` 已删，默认行为逐字节保留；研究期只在多遍迭代中使用的 `EDGE_WORD_CUES`／`EDGE_WORD_BRANCH` 未移植。只复制不导入。
- **命名**：包属性 `kototoki.names.apply` 是替换函数，遮住同名子模块；子模块的其他名字用 `from kototoki.names.apply import …` 取（`recipes` 也这样逐名导入）。

## 接口与依赖

编排以 `importlib` 导入 `kototoki.names`，只用：`Session(config, *, on_server_pid=None)`（上下文管理器，`ensure_started()`、`stop()`、`unavailable`；`server_factory`／`client_factory` 只供测试）、`build_document(work_dir, document, session | None, seed) -> BuildResult`（`payload`、`attempts`、`seconds`、`status` ∈ `ok | failed | too_long`）、`apply(table, document, translations) -> ApplyResult`（`translations`、`changes`、`unresolved`、`summary`）、`NamesError`，以及 `BUILD_RECIPE_HASH`／`APPLY_RECIPE_HASH`。[阶段计划](stage-plan.md)延迟导入 `kototoki.names.recipes` 取两个 hash。

依赖基础层（`artifacts`、`config`、`srt`、`recipes`）与中间层 `kototoki.llama_server`（`ManagedServer`、`ServerSpec`、`LlamaClient`、`explicit_oom`）；不导入 torch、推理模块、翻译子系统与 `experiments.*`（`tests/core/test_job.py` 的禁止导入测试连同 `kototoki.names` 一起守门）。只读配置的 `paths.output_dir`、`paths.llama_server`、`models.names`、`names.port`（`seed`、`enabled` 由编排与阶段计划读）。

## 代码与验证入口

- 代码：`kototoki/names/__init__.py`（`Session`、`build_document`、`NamesError`、`NAMES_SPEC`、`MAX_STARTS`）、`kototoki/names/table.py`（`SYSTEM_PROMPT`、`build_messages`、`parse_reply`、归一函数、`build_table`、`BuildResult`）、`kototoki/names/apply.py`（`apply`、`ApplyResult`、`apply_pass` 与统计层）、`kototoki/names/recipes.py`（`BUILD`、`APPLY`、两个 hash、`NAMES_SERVER`）；编排侧 `kototoki/job.py` 的 `names_batch`、`apply_names`。
- 测试（core，`just test`）：`tests/core/test_names_table.py`（渲染、解析与归一、上限、zh 形状、称呼词黑名单、提示 v5、日文写法形状、confidence 降级、`build_table` 的请求体、预算、两次尝试与 `too_long`／`failed` 空表、零条目）；`tests/core/test_names_apply.py`（研究期默认路径用例：变体层、已规范、统计层与扩展、未命中、重叠、复合名、特异性过滤、孤立单字、回退 cue 跳过）；`tests/core/test_names_recipes.py`（提示与 schema 的 sha256、`BUILD`／`APPLY` hash 钉子、改值即改 hash、`NAMES_SPEC` 与常量一致）；`tests/core/test_names_session.py`（伪 server／伪客户端：session 目录名、整批共用一个 server 与退出后重启、最多 3 次启动、启动失败即 unavailable、`_managed_server` 传 `NAMES_SPEC` 与配置、零条目不起 server、交换目录与超时、HTTP OOM 与传输失败抛 `NamesError` 并停 server）；`tests/core/test_assets_manifest.py`（模型资产等于 `assets.toml`）；`tests/core/test_job.py` 的 `NamesTests`（伪 names 模块：阶段顺序与锁里的 server pid、表与 `sources` 两键、发布用替换后的 `zh`／`ja-zh` 并写审计文件、改表只重发布、session 建不起来只让有 cue 的影片失败、建表异常只影响该影片且重跑恢复、终态失败空表照常发布并记 WARNING、改坏表即发布失败、零条目不取锁不建 session、启用后不重译、停用不留痕迹且切换会重新发布）；`tests/full/test_job_ffmpeg.py`（names session 先于翻译 session、两个文件落盘、`sources` 含两键）。
- 真实模型验证（占 GPU，须用户批准，不属于任何 gate）：`just smoke names_product`（`scripts/smoke/names_product.py`）在真实 llama-server 与 Qwen3.8-27B-UD-IQ3_S 上走 `plan.names_identity` → `Session` → `build_document` → `write_artifact` → `apply`（默认配置与 seed）；输入是脚本内置的 12 条合成日语短句（同一人名的正确写法与一处 ASR 式误写、一个职阶名、其余中性）与一份人名中文写法不一致的人工译文；通过条件是驻留校验通过、`build.status == ok`、表至少一条 person、`apply` 至少改一个 cue 且改后含该人名的 cue 只剩一种写法、无异常；结果只记计数、哈希、耗时、冷加载、空闲显存与峰值显存。2026-10-20 运行通过（约 21 s）：server 驻留 66/66 层在 GPU、冷加载 5.6 s、启动前空闲显存 15029 MiB、整机显存峰值 13444 MiB（含约 1.3 GiB 的桌面基线，server 自身约 12.2 GiB）；建表一次成功（`attempts` 1、prompt 1655／completion 299 tokens、请求 6.1 s）得 2 条 person（人名与职阶名都被标为 person，这是模型对 kind 的判断，不影响替换）；`apply` 3 处替换（统计层）、2 处 `boundary` 未动，含该人名的 6 个 cue 的写法由 2 种变成 1 种。`min_free_mib` 初值 13000 相对 server 约 12.2 GiB 的占用有约 0.8 GiB 余量，12 GB 模型加 20480 上下文的 KV 与计算缓冲在加载时一次分配，峰值与提示长度关系不大，维持不变。首次运行时译文里的人名有三种写法、相邻写法共享前两字，`apply` 的统计层把共享的"艾米"当作省略形不替换（算法按设计工作），已改成两种互不相邻的写法后通过；脚本的人工译文因此刻意避开"单次出现的写法"与"落点紧邻汉字"两种 `apply` 本就不动的情形。
- 真实运行（占 GPU，须用户批准）：2026-10-20 票据 08 验收以 `.local/bilingual-fullfilm-08/w0.toml` 整批重跑 HF II／III（[验收记录](../../research/acceptance/2026-10-20-name-consistency-product.md)）：退出码 0，STT 与翻译按身份跳过（未起 Hy-MT2），names 阶段 105.9 s（模型 sha256 核对 7.6 s、冷加载 5.6 s，建表 49.5／40.5 s，prompt 13240／14609、completion 2382／1844 tokens），启动前空闲显存 15029 MiB、整机峰值 13445 MiB（与 smoke 相同，整片提示不抬高峰值）；两表第一次尝试即 `ok`（20／15 条），替换 55／32 个 cue；不一致率 0.151 → 0.135、0.121 → 0.094；研究脚本 `apply_table` 默认参数在产品表上的输出与发布的 `zh.srt` 逐字节相同，`totals`、逐实体统计与 `unresolved` 也相同。
- 未验证：产品写出的表与 `changes` 尚未人工抽看（验收判据 ④ 待用户）；x0 输出、其他作品与剧集、`too_long`／`failed` 与 server 起不来等失败路径的真实运行、同一 seed 下建表的可重复性。名表的质量证据仍只有研究期四部整片（ADR-0014 记录）。

## 变更与决策来源

[ADR-0013](../../adr/0013-name-consistency-closed.md)（研究线结题与冻结配置）、[ADR-0014](../../adr/0014-name-consistency-in-product.md)（进产品）；票据 `.scratch/name-consistency-product/`（01–09）：02（共享 llama-server）、03（建表与配方）、04（替换）、05（配置、阶段计划与产物常量）、06（编排接入与本页）、07（smoke）、08（产品路径验收，[验收记录](../../research/acceptance/2026-10-20-name-consistency-product.md)）、09（收口）。

2026-10-20 吸收增量说明《专名一致性进产品》（`docs/changes/name-consistency-product.md`，已删除）：设计与取舍写入上文与 [ADR-0014](../../adr/0014-name-consistency-in-product.md)，用户裁定（6 条）在 ADR-0014“决定”一节；增量说明 §3.2 的 `names/transport/attempt-N.*` 未按其实现，实际为 `names/transport/<UTC戳>-<pid>/session-NN/`，以本页“实现设计”为准。
