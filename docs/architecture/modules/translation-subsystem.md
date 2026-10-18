# 翻译子系统与双语合并

状态：current（票据 05 交付，2026-10-14；票据 09 加入三级降级与回退报告，2026-10-14；票据 16 把产品配方换成 `dp10-cut-degrade-v1`，按停顿切包，2026-10-18，[ADR-0011](../../adr/0011-dp10-cut-product-recipe.md)）。降级只经伪 server／伪客户端离线验证；旧配方与编排器的真实联调见[两部整片验收](../../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)（四个文件 468 批，降级与回退均为 0）；新配方的真实运行见票据 16。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md) §3.3、§4、§6，[模块边界](../module-boundaries.md#产品包的责任边界)）中 `ja.srt → 译文` 与 `ja.srt + 译文 → ja-zh.srt` 两步：受管 llama-server 的生命周期、`dp10-cut` 切包与 joint 批次请求、按批次落盘与续跑、基础设施失败的重启、批次终态失败的三级降级与回退报告，以及中日两行合并。不负责：GPU 锁与 Job Object（[批次编排](batch-orchestration.md)）、`zh.srt`／`ja-zh.srt` 的写出与发布（编排器）、工作目录 `.work/<id>/` 本身的位置（[产物契约](artifact-contract.md)）、任何时间换算。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。v3 实验侧的同名流程见[完整 SRT 翻译流程](translation-srt-flow.md)，本模块是其产品移植，不导入它。

## 当前行为规格

**对编排器的接口**（`kototoki.translate`）：

- `Session(config, on_server_pid=None)`：上下文管理器，整批影片共用。第一次真正需要请求模型时才启动 llama-server（已全部完成的影片不启动）；`on_server_pid(pid)` 在 server 进程一启动（加载之前）、`on_server_pid(None)` 在进程结束后回调，供编排器写进 GPU 锁；退出时总是停掉 server。
- `plan(work_dir, document, config) -> TranslatePlan`：`document` 是 `srt.read_srt` 读出的 `ja.srt`。只读、不写文件，返回 `run_dir`（`<work_dir>/translate/srt-<sha12>/<配方名>__s<seed>/`，`relative` 为相对工作目录的 posix 串，发布记录的 `translate_dir` 即它）、`identity`（`{ja_srt_sha256, recipe_hash, seed}`，[阶段计划](stage-plan.md)的 translate 身份由此取得，不再自算）、`needs_model`（零条目文档或 `run.json` 已记 `complete` 时为 False；编排器据此决定要不要取 GPU 锁、建 `Session`）与 `document`。`run.json` 已存在但配方 hash／seed／来源不符时抛 `ValueError`，消息含"删除该目录可重译"。
- `translate_document(plan, session) -> TranslateResult`：`plan` 来自上一条；`needs_model` 为 False 时 `session` 可为 `None`，只读回已完成的 run（run 记为完成而批次文件缺失即抛 `TranslateError`，不起 server）。返回 `translations`（cue id → 译文，精确覆盖全部 cue；回退的 cue 为日文原文）、`fallback_count`（回退为日文的 cue 数，编排器写进 `published.json` 的 `translate_fallback_cues` 并在控制台汇总）与 `report`（即 `report.json` 的内容）。基础设施失败用尽重启时抛 `TranslateError`（编排器记为该文件翻译失败）；模型或引擎缺失等配置问题按原异常抛出。
- `RECIPE_HASH`：产品翻译配方 `dp10-cut-degrade-v1` 的 hash `086754ca…158e`，进编排器的翻译身份。该配方字段与 v3 `dp10-cut` 相同（`gap_pack` 即 ADR-0010 的全部参数），只把 `fixed.overflow` 由 `recorded-failure-no-truncation-no-auto-shrink` 换成 `degrade-10-5-1-keep-source`，因而另算 hash。`dp10-cut`（v3 原 hash `ee72ce66…c500b70`）、`b10-joint`（`2ba68054…0969a`）与 2026-10-14..18 的产品配方 `b10-joint-degrade-v1`（`994c0d03…95fe`）保留并钉住，后者是旧 run 目录的身份对照。

**请求**：每部影片是一个场景，cue ID 用 `srt.py` 的 `<sha8>-cue-<n>` 别名，cue 带 `ja.srt` 的起止秒。切包按 `dp10-cut`（[ADR-0010](../../adr/0010-dp10-cut-translation-flow-baseline.md)，`batching.gap_pack_cuts`）：整个场景用动态规划取总惩罚最低的切法，每批待译 ≤10 条；每批代价 = (条数 − 10)² ＋ 批内每个 ≥2 s 停顿按秒数计 1 分，<6 条加 1000 分，批内有 ≥20 s 停顿不可行；内部切点按停顿分级加罚（<0.5 s 加 6、<1 s 加 3、<2 s 加 1，缺时间戳按无停顿）。只读邻文（`batching.neighbours`）：前一条在停顿 <5 s 时可见，后一条只在停顿 <1 s 时可见，可见总数不超过 12 条。停顿只取自 `ja.srt` 自身的时间轴、只比较长短，不是时间换算。提示、grammar、采样（`official30b-cached-v1`、seed 取 `[translate] seed`）与 completion 请求与 v3 `dp10-cut`／`b10-joint` 逐字节相同。每个请求先 `/tokenize`，输入超过 4032 token 即判 `context`，不截断；同一请求最多 2 次。批次级的缩小只经下面的降级发生。

**失败分类**（沿用 v3 `run_step`）：

| 种类 | 来源 | 处理 |
| --- | --- | --- |
| `oom`、`server`（传输）、`server_error`、`cache`、`server_start` | HTTP 500／OOM 文本、连接失败、`tokens_evaluated` 不符、server session 首个 completion 的 `timings.cache_n != 0`、server 加载期退出／超时／空闲显存不足 | 停掉 server，同一次调用内启动新 session 重做；最多重启 2 次，仍失败抛 `TranslateError` |
| `context`、`limit`、`parse` | 输入超预算、`stop_type == "limit"` 或 `truncated`、JSON／ID 校验失败、译文含空行（会让 SRT 断块；v3 校验之外新增） | 批次终态：按下节降级，不重启 server、不使该影片失败 |
| 其他异常 | 非 JSON 响应、写盘失败等 | 该 session 记 `stop_reason = session_error: …`，停掉 server，原样上抛 |

**降级**（`degrade.py`，规格 §6）：批次终态失败后拆成前后两半 `父ID.a`／`父ID.b`（奇数条前半多 1 条），仍失败的半批拆成单条 `父ID.a.1`…，单条仍失败则该 cue 的译文 = 日文原文（回退，原因取该单条的失败种类）；只有 1 条的批次失败即回退。子批次与原批次用同一条邻文规则（`batching.neighbours`）、同一 seed，提示、grammar、采样与请求由同一组函数构造（测试逐字节对照）。降级中每个节点（含失败的原批次）的结果一出来就追加到 `degrade.jsonl`；降级途中的基础设施失败照常重启 server，新 session 从未记录的节点继续，已记录的节点不再请求。整个批次完成后写成 `batches.jsonl` 的一行（带 `degrade.nodes` 与 `degrade.fallback`），回退由此对该配方 hash 与 seed 是终态：重跑同一命令不再尝试，要重试须改 `[translate] seed`（另起 run）；`force` 不触发重译。

**session**：一个 server 进程即一个 session。`cache_n == 0` 校验在每个 session 的首个 completion 做一次（之后的影片复用 KV 前缀属正常）。每次重启都是新 session：影片 `run.json` 的 `sessions[]` 新增一项、`cache_state` 重置、写过批次或遇到基础设施失败的 session 超过一个时 `resumed = true`。server 启动失败（`server_start`）不新增 `sessions[]` 项，记入 `server_start_failures[]`；端口被占、模型核对失败、驻留校验失败等按原异常抛出，不重试。server 启动前用 `nvidia-smi memory.free` 轮询，达到 14700 MiB 才启动（整片实测 server 自身约 14800 MiB，整片验收中 server 加载后桌面占用由约 1236 降到约 597 MiB、翻译正常；2026-10-15 用户裁定由 14900 下调），120 s 超时按 `server_start` 失败处理并写明最后读数。某部影片的重启额度全部耗在 `server_start` 上（GPU 被占或 server 起不来）时，`Session` 记为不可用，本批其余影片直接抛 `TranslateError`，不再逐片等待；混有其他种类的失败不触发这一点。

**run 目录与续跑**：`translate/srt-<sha12>/<配方名>__s<seed>/`，键由本子系统的 `plan` 唯一决定（`batching.source_key` 给出 `srt-<sha12>`，同时是场景 ID）：`ja.srt` 变化换 `srt-<sha12>`，配方名或 seed 变化换子目录，旧目录都保留。配方**内容**变了而名字未变（hash 不符）不自动另开目录，`plan` 拒绝并提示删除该目录（票据 15 裁定维持此规则：零迁移、与 v3 "同名配方内容不同拒绝续跑"一致；候选方案"目录名含 hash 自动另开"会让现有整片 run 全部失效，未采纳）：

- `run.json`：只含该影片；配方、hash、seed、来源（`ja.srt` SHA256、场景 ID、cue ID 列表）、`sessions[]`（引擎身份摘要、`server_session` 指向的运行日志目录、写入批次数、停止原因、基础设施失败与证据、缓存校验结果、墙钟）、`server_start_failures[]`、`resumed`、`completion`。已存在且配方／seed／来源不符时报错（同名配方改了 hash 属此情形；票据 09 用新配方名因而另起目录）。
- `batches.jsonl`：每完成一批追加一行并 fsync，随即重写 `run.json`（进程被强杀时 `sessions[]` 仍反映已写批次）（批次计划字段、译文、请求与逐次尝试记录、所属 session；降级完成的批次不带顶层请求，改为 `degrade`：各节点（`nodes[0]` 是原批次）的 ID、层级、状态、失败种类、尝试次数与完整请求记录，以及回退 cue 的 ID、原因、错误与累计尝试次数）。续跑时末尾不完整的一行截掉，其余行须与批次计划一致，从第一个未写入的批次继续。
- `degrade.jsonl`：降级中各节点的结果（`parent_index`、`level`、译文或失败种类与错误），每个节点完成即追加；续跑时同样截掉不完整的末行，只取未完成批次的节点，行须属于批次计划且不重复。
- `scene.json`：全部批次完成后才写出（cue 位置、批次、全部译文、降级树 `degradation`、`fallback_ids`、按节点计的请求／尝试与 token 统计）；部分完成的影片没有该文件。
- `report.json`：完成时写出（零条目也写）：`completion`、计数（批次、降级批次、回退 cue、降级请求数）、每个降级批次的节点摘要与回退 ID、回退 cue 清单（ID、原因、错误、尝试次数）。
- `transport/session-NN/`：逐请求原始交换（请求 JSON、原始响应、传输记录）；`infra-failures/`：基础设施失败时该批次（或降级节点）的尝试记录。
- server 运行日志（`server.log`、`stdout.log`、`engine.json`、`engine-final.json`）在 `<output_dir>/.work/translate-sessions/<UTC戳>-<pid>/session-NN/`（时间戳与运行日志 `run-<UTC戳>.log` 同一基准，带 `Z` 后缀），被整批影片共用。llama-server 的 stderr 送 `DEVNULL`，不另存：`-lv 4` 下它与 `--log-file` 的 `server.log` 逐字节相同（2026-10-19 审计 B-14，此前每 session 多存一份 6 MB 的 `stderr.log`）；驻留证据与 OOM 文本从 `server.log`／`stdout.log` 解析（`loader_logs`）。`engine-final.json` 记峰值显存、`server_exit_code` 与 `server_stop`：`terminated`（退出时由编排正常终止，Windows 上 `terminate()` 让退出码固定为 1，不是故障）、`killed`（15 s 内未退出而强杀）、`exited`（进程已自行退出，退出码才是它自己的）、`None`（未启动）（审计 C-6）。

零条目 `ja.srt`：写 `run.json`（完成），返回空译文，不启动 server、不请求模型。

**日志**：经 `kototoki.translate.*` logger 发事件，写进编排的运行日志（[批次编排：运行日志](batch-orchestration.md#运行日志)）：session 起止、llama-server 加载完成与每批一行（cue 数、输出 token、tok/s、cache，取不到的字段省略）为 INFO；等空闲显存超过 30 s、server 重启、降级拆批与单条回退为 WARNING；加载失败与用尽重启放弃为 ERROR。`StepFailed` 的 HTTP 错误与 server error 消息只含状态码／kind 与正文长度，不嵌入响应正文（正文留在 `transport/…/response.raw`）；这两条消息也是 `run.json`、`batches.jsonl`、`degrade.jsonl`、`report.json` 中对应 `error` 字段的取值，在这两条路径上随之变短（字段与配方 hash 不变）。

**server**：stock llama.cpp（`[paths] llama_server`，同目录必须有 `identity.json`，且 `llama-server.exe` 与同目录全部 DLL 的 SHA256 等于其 `runtime_file_sha256`，经 size+mtime 缓存，目录里出现未登记的 DLL 也拒绝），命令行与 v3 冻结 C0 相同（ctx 8192、单槽、99 层、f16 KV、`--cache-ram 8192`、`--fit off`、`-lv 4`）。启动前检查端口空闲（被占时列出正在运行的 llama-server pid）、模型文件名与大小等于冻结资产 APEX-I-Compact、SHA256 经 `artifacts.verify_model`（size+mtime 缓存在 `.work/cache/model-verification.json`）。加载后从日志解析驻留证据，必须全部层在 GPU、有 CUDA model buffer，否则拒绝。

**合并**（`kototoki.merge.merge(ja_document, zh_translations) -> srt_text`）：纯函数；沿用日文 cue 的编号与时间行，每条两行，中文在上、日文在下；中文与日文内的换行都替换为空格，保证每条恰好两行；回退为日文的条目两行相同，照常输出。译文须精确覆盖全部 cue（缺失、多余、空串抛 `IncompleteTranslationError`）；零条目文档得到空串。

## 实现设计

移植来源与取舍（产品包不导入 `experiments.*`，只复制）：

| 文件 | 来源 | 取舍 |
| --- | --- | --- |
| `recipes.py` | `translation_v3/recipes.py` | 只留 `b10-joint`／`dp10-cut` 字段与 joint 提示；`Recipe.spec()` 结构不变以保持原 hash（`gap_pack` 为 None 时不进 `recipe`）；去掉 terms／review／多样本／类别路由／配方文件与 `gap_pack` 校验（配方是常量）；新增 `overflow` 字段（进 `fixed`，与 v3 位置相同）与产品配方 |
| `degrade.py` | 新增（v3 实验不缩批） | 拆分规则、降级树与回退、`report.json` 内容；不导入 `generate`，由其传入请求函数与降级日志；邻文经 `batching.neighbours` |
| `adapters.py` | `translation_demo/adapters.py` | 只留 `hy-mt2-30b` 用到的 `render`、`id_grammar`、`translations`、`strict_json` |
| `batching.py` | `translation_v3/batching.py`、`data.py` | 按条数分批与 gap-pack-v2 切包（`silence`、`gap_pack_cuts` 只留 `group_gap=None` 分支、邻文规则并为 `neighbours`）；不搬 `gap_split`、`pause_marks`、`groups`、token 分批；`Scene`／`Cue`（带秒）由 `ja.srt` 构造，`source_key` 是 `srt-<sha12>` 的唯一出处（原 `data.py` 并入，票据 15） |
| `generate.py` | `translation_v3/generate.py` | `run_step` 判定不变；`Session` 取代 v3 每次运行新开 server 的 session factory；按批次追加落盘；同调用内重启 |
| `server.py` | `translation_v3/server.py`、`translation_demo_runtime.py`、`translation_demo/run.py` | 去掉 `GpuLock`；模型路径来自配置，资产清单文件改为冻结资产常量；`validate_residency` 去掉"允许 CPU 卸载"开关；新增空闲显存轮询 |
| `client.py` | `translation_demo/client.py` | 原样 |
| `procs.py` | `translation_v3/procs.py` | 只留 `list_llama_servers`；锁归编排器，Job Object 已由编排器 `contain_children` 覆盖 llama-server |

v3 的 `common.py` 不单独移植：哈希、原子写与模型核对用 `kototoki.artifacts`，路径来自 `kototoki.config`。

## 接口与依赖

依赖标准库、`kototoki.artifacts`、`kototoki.config`（只读 `paths.output_dir`、`paths.llama_server`、`models.translate`、`translate.port`／`seed`）、`kototoki.srt`。编排器只导入包顶层的 `Session`、`translate_document` 与 `kototoki.merge`，[阶段计划](stage-plan.md)延迟导入包顶层的 `plan` 取 `TranslatePlan`（翻译身份与 `needs_model`）；`RECIPE_HASH` 也在包顶层导出，当前只有测试使用；`server`、`client`、`batching`、`generate`、`procs` 是内部实现。内部接缝：`Session(server_factory=..., client_factory=...)` 只供测试替换 server 与 HTTP 客户端。

## 代码与验证入口

- 代码：`kototoki/translate/`、`kototoki/merge.py`。
- 测试（core，`just test`）：`tests/core/test_translate_degrade.py`（拆分与邻文、三级降级与单条回退及子批次请求字节、单条批次直接回退、超出 context 进入降级、续跑复用已记录节点并截掉写了一半的行、已记录的单条失败续跑时直接回退、降级中途 OOM 重启、原批次 OOM 不进降级、回退终态与改 seed 重试、空场景报告、计划外的降级行报错、经编排器写进 `published.json` 的回退计数）；`tests/core/test_translate.py`（伪 server／伪客户端：正常（首个请求与按冻结配方构造的请求逐字节相同）、损坏的中间行报错、每批后 `run.json` 已记批次数、意外异常记 `session_error` 并停 server、译文空行按解析失败、整批共用一个 session、按批次续跑与截掉写了一半的行、全部完成不启动 server、OOM 重启即新 session、两次重启后放弃、缓存校验失败、空场景、`ja.srt` 变化换目录、seed 变化另起 run、显存轮询超时、server 起不来时本批其余影片直接失败、混合失败不标记不可用、启动失败后成功）；`tests/core/test_translate_recipes.py`（v3 `b10-joint`、`dp10-cut` hash 钉子、两个产品配方的 hash 钉子与“只差 `overflow`”、提示／grammar／请求 SHA256 钉子、`b10-joint` 与 `dp10-cut`（不均匀停顿与随机场景）与冻结 v3 函数逐字节对照、gap-pack-v2 规则（暴力枚举等价、切点挪向长停顿、≥20 s 必切、短包只在被硬切夹出的短段、邻文门槛与可见上限、缺时间戳、均匀场景 8/8/7 而非 10/10/3））；`tests/core/test_translate_server.py`（stock 加载日志驻留解析、显存轮询、OOM 识别、冻结命令行、模型核对、引擎文件 SHA 核对、`engine-final.json` 的 `server_stop` 标注、stderr 送 `DEVNULL` 且 `loader_logs` 不读残留的 `stderr.log`）；`test_translate.py` 另断言 session 目录名为 UTC 戳带 `Z` 加 pid；`tests/core/test_merge.py`。
- 真实模型验证（占 GPU，须用户批准，不属于任何 gate）：`just smoke translate_product`（`scripts/smoke/translate_product.py`）在真实 llama-server 与 APEX 模型上走 `plan` → `Session` → `translate_document`（产品配方 `dp10-cut-degrade-v1`、默认 seed），输入是脚本内置的 12 条中性合成日语短句、第 6 条后 20 s 停顿，切成 6/6 两批；通过条件是全部 cue 有非空译文、无回退、至少两批；结果只记计数、哈希、耗时、冷加载、驻留与显存峰值。**未运行、待用户批准**。整片的产品翻译运行证据见 2026-10-14 至 10-16 的整片验收与 ADR-0011 的 2026-10-18 运行。
- 真实运行（2026-10-14，票据 05 完成标准第二项）：HF II 的 W0 对齐结果按默认 `[cues]` 切出 1112 条 `ja.srt`，stock b11583 单 session 112 批全部一次通过（无重试、无触顶），`zh.srt` 覆盖 1112/1112，`ja-zh.srt` 1112 条且每条恰好两行。墙钟 176 s（含模型 SHA 首次全量核对 16.7 s、冷加载 7.1 s）；输入 75408、输出 19272 token；首个请求 `cache_n == 0`；启动前空闲 15112 MiB，会话峰值 15687 MiB（桌面基线约 880 MiB，即 server 自身约 14800 MiB）。输出只写在仓库外的会话临时目录。
- 真实运行：[两部整片验收](../../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)——经编排器整批翻译四个文件，降级批次 0、回退 cue 0、无重启。
- 离线切包（2026-10-18，票据 16）：四个整片 `ja.srt` 上 `dp10-cut-degrade-v1` 平均每批 7.4–8.3 条、请求数比 `b10-joint-degrade-v1` 多 20–35%、无批次跨 ≥20 s 停顿、92–97% 的切点落在 ≥1 s 停顿、<6 条的批 9–24%，见 [ADR-0011](../../adr/0011-dp10-cut-product-recipe.md)。
- 真实运行（2026-10-18，票据 16）：`dp10-cut-degrade-v1` 经编排器整批翻译 HF II／III（w0）：147＋149 批全部一次接受，降级 0、回退 0、无重启；HF III 翻译 200 s，HF II 第 96 批起生成速度跌到约 4 tok/s、共 2906 s，server 峰值显存 15955 MiB，疑为下面"已知限制"的显存漂移触顶，未验证。
- 未验证：真实数据上的降级路径（两个配方整片都未触发）；`dp10-cut-degrade-v1` 的质量（没有裁判证据，与 ADR-0010 相同）；HF II 慢化的原因。已知限制：桌面程序占用较多显存（空闲低于 14700 MiB）时翻译会等满 3×120 s 后失败，需先释放显存；整片验收时桌面占用 0.6–1.2 GB 漂移，首轮即因此失败。

## 变更与决策来源

票据 `.scratch/bilingual-subtitle-pipeline/issues/05-translate-and-merge.md`、`09-translate-degrade.md`、`15-translate-run-key.md`（run 键、身份与 `needs_model` 归本子系统的 `plan`；`data.py` 并入 `batching.py`）、`16-translate-dp10-cut.md`（产品配方合并 dp10-cut 切包）；规格 §1.2（含第三轮裁定表）、§3.3、§4、§5.2、§6、§7.3；[ADR-0005](../../adr/0005-apex-i-compact-translation-baseline.md)、[ADR-0006](../../adr/0006-b10-joint-translation-flow-baseline.md)、[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0010](../../adr/0010-dp10-cut-translation-flow-baseline.md)、[ADR-0011](../../adr/0011-dp10-cut-product-recipe.md)；stock 引擎的 `run_step` 假设与驻留日志由票据 01 smoke #4 验证。

2026-10-18 吸收增量说明《依赖入项目与测试分层调整》（`docs/changes/local-dependencies-and-test-layers.md`，已删除）：新增真实模型验证 `just smoke translate_product`（未运行）；`MODEL_ASSET` 由 core 测试钉住等于 `assets.toml`。

2026-10-19 架构审计小修集合：票据 `.scratch/architecture-review/issues/01-small-fixes.md`（B-14 stderr 去重与 UTC 目录名、C-6 `server_stop`）；旧 session 目录（本地时间戳、含 `stderr.log`）原样保留，不迁移。
