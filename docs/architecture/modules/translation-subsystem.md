# 翻译子系统与双语合并

状态：current（票据 05 交付，2026-10-14）；三级降级与产品配方 `b10-joint-degrade-v1` 由票据 09 加入，届时 `fallback_count` 才可能非 0。只经伪 server／伪客户端离线验证，真实整片运行见票据 Comments。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md) §3.3、§4、§6，[目标架构](../bilingual-pipeline-architecture.md)"翻译子系统""合并"行）中 `ja.srt → 译文` 与 `ja.srt + 译文 → ja-zh.srt` 两步：受管 llama-server 的生命周期、`b10-joint` 批次请求、按批次落盘与续跑、基础设施失败的重启，以及中日两行合并。不负责：GPU 锁与 Job Object（[批次编排](batch-orchestration.md)）、`zh.srt`／`ja-zh.srt` 的写出与发布（编排器）、run 目录的位置（[产物契约](artifact-contract.md) `translate_run_dir`）、任何时间换算。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。v3 实验侧的同名流程见[完整 SRT 翻译流程](translation-srt-flow.md)，本模块是其产品移植，不导入它。

## 当前行为规格

**对编排器的接口**（`kototoki.translate`）：

- `Session(config, on_server_pid=None)`：上下文管理器，整批影片共用。第一次真正需要请求模型时才启动 llama-server（已全部完成的影片不启动）；`on_server_pid(pid)` 在启动后、`on_server_pid(None)` 在停止后回调，供编排器写进 GPU 锁；退出时总是停掉 server。
- `translate_document(document, run_dir, session, config) -> TranslateResult`：`document` 是 `srt.read_srt` 读出的 `ja.srt`，`run_dir` 是 `translate/srt-<sha12>/`。返回 `translations`（cue id → 译文，精确覆盖全部 cue）、`fallback_count`（本票恒为 0）与 `report`（run 的完成状态）。失败抛 `TranslateError`（编排器记为该文件翻译失败）；模型或引擎缺失等配置问题按原异常抛出。
- `RECIPE_HASH`：产品翻译配方 hash，进编排器的翻译身份。当前等于 v3 `b10-joint` 原 hash `2ba68054…0969a`。

**请求**：每部影片是一个场景，cue ID 用 `srt.py` 的 `<sha8>-cue-<n>` 别名；按源顺序每批 10 条、前后各 1 条只读邻文；提示、grammar、采样（`official30b-cached-v1`、seed 取 `[translate] seed`）与 completion 请求与 v3 `b10-joint` 逐字节相同。每个请求先 `/tokenize`，输入超过 4032 token 即判 `context`，不截断不缩批；同一请求最多 2 次。

**失败分类**（沿用 v3 `run_step`）：

| 种类 | 来源 | 处理 |
| --- | --- | --- |
| `oom`、`server`（传输）、`server_error`、`cache`、`server_start` | HTTP 500／OOM 文本、连接失败、`tokens_evaluated` 不符、server session 首个 completion 的 `timings.cache_n != 0`、server 加载期退出／超时／空闲显存不足 | 停掉 server，同一次调用内启动新 session 重做；最多重启 2 次，仍失败抛 `TranslateError` |
| `context`、`limit`、`parse` | 输入超预算、`stop_type == "limit"` 或 `truncated`、JSON／ID 校验失败、译文含空行（会让 SRT 断块；v3 校验之外新增） | 批次终态：写 `terminal-failures/` 证据并抛 `TranslateError`，批次不落盘，server 留给下一部影片；重跑同一命令会再试（票据 09 改为三级降级） |
| 其他异常 | 非 JSON 响应、写盘失败等 | 该 session 记 `stop_reason = session_error: …`，停掉 server，原样上抛 |

**session**：一个 server 进程即一个 session。`cache_n == 0` 校验在每个 session 的首个 completion 做一次（之后的影片复用 KV 前缀属正常）。每次重启都是新 session：影片 `run.json` 的 `sessions[]` 新增一项、`cache_state` 重置、写过批次或遇到基础设施失败的 session 超过一个时 `resumed = true`。server 启动失败（`server_start`）不新增 `sessions[]` 项，记入 `server_start_failures[]`；端口被占、模型核对失败、驻留校验失败等按原异常抛出，不重试。server 启动前用 `nvidia-smi memory.free` 轮询，达到 14300 MiB 才启动，120 s 超时按 `server_start` 失败处理并写明最后读数。

**run 目录与续跑**：`<run_dir>/<配方名>__s<seed>/`（配方或 seed 变化即另一个 run，`ja.srt` 变化由产物契约换成新的 `srt-<sha12>`，旧目录都保留）：

- `run.json`：只含该影片；配方、hash、seed、来源（`ja.srt` SHA256、场景 ID、cue ID 列表）、`sessions[]`（引擎身份摘要、`server_session` 指向的运行日志目录、写入批次数、停止原因、基础设施失败与证据、缓存校验结果、墙钟）、`server_start_failures[]`、`resumed`、`completion`。已存在且配方／seed／来源不符时报错（同名配方改了 hash 属此情形；票据 09 用新配方名因而另起目录）。
- `batches.jsonl`：每完成一批追加一行并 fsync，随即重写 `run.json`（进程被强杀时 `sessions[]` 仍反映已写批次）（批次计划字段、译文、请求与逐次尝试记录、所属 session）。续跑时末尾不完整的一行截掉，其余行须与批次计划一致，从第一个未写入的批次继续。
- `scene.json`：全部批次完成后才写出（cue 位置、批次、全部译文、token 统计）；部分完成的影片没有该文件。
- `transport/session-NN/`：逐请求原始交换（请求 JSON、原始响应、传输记录）；`infra-failures/`、`terminal-failures/`：失败批次的尝试记录。
- server 运行日志（`server.log`、`engine.json`、`engine-final.json`，含峰值显存）在 `<output_dir>/.work/translate-sessions/<时间戳>-<pid>/session-NN/`，被整批影片共用。

零条目 `ja.srt`：写 `run.json`（完成），返回空译文，不启动 server、不请求模型。

**server**：stock llama.cpp（`[paths] llama_server`，同目录必须有 `identity.json`），命令行与 v3 冻结 C0 相同（ctx 8192、单槽、99 层、f16 KV、`--cache-ram 8192`、`--fit off`、`-lv 4`）。启动前检查端口空闲（被占时列出正在运行的 llama-server pid）、模型文件名与大小等于冻结资产 APEX-I-Compact、SHA256 经 `artifacts.verify_model`（size+mtime 缓存在 `.work/cache/model-verification.json`）。加载后从日志解析驻留证据，必须全部层在 GPU、有 CUDA model buffer，否则拒绝。

**合并**（`kototoki.merge.merge(ja_document, zh_translations) -> srt_text`）：纯函数；沿用日文 cue 的编号与时间行，每条两行，中文在上、日文在下；中文与日文内的换行都替换为空格，保证每条恰好两行；回退为日文的条目两行相同，照常输出。译文须精确覆盖全部 cue（缺失、多余、空串抛 `IncompleteTranslationError`）；零条目文档得到空串。

## 实现设计

移植来源与取舍（产品包不导入 `experiments.*`，只复制）：

| 文件 | 来源 | 取舍 |
| --- | --- | --- |
| `recipes.py` | `translation_v3/recipes.py` | 只留 `b10-joint` 字段与 joint 提示；`Recipe.spec()` 结构不变以保持原 hash；去掉 terms／review／多样本／类别路由／配方文件 |
| `adapters.py` | `translation_demo/adapters.py` | 只留 `hy-mt2-30b` 用到的 `render`、`id_grammar`、`translations`、`strict_json` |
| `batching.py`、`data.py` | `translation_v3` | 只留按条数分批；`Scene`／`Cue` 由 `ja.srt` 构造 |
| `generate.py` | `translation_v3/generate.py` | `run_step` 判定不变；`Session` 取代 v3 每次运行新开 server 的 session factory；按批次追加落盘；同调用内重启 |
| `server.py` | `translation_v3/server.py`、`translation_demo_runtime.py`、`translation_demo/run.py` | 去掉 `GpuLock`；模型路径来自配置，资产清单文件改为冻结资产常量；`validate_residency` 去掉"允许 CPU 卸载"开关；新增空闲显存轮询 |
| `client.py` | `translation_demo/client.py` | 原样 |
| `procs.py` | `translation_v3/procs.py` | 只留 `list_llama_servers`；锁归编排器，Job Object 已由编排器 `contain_children` 覆盖 llama-server |

v3 的 `common.py` 不单独移植：哈希、原子写与模型核对用 `kototoki.artifacts`，路径来自 `kototoki.config`。

## 接口与依赖

依赖标准库、`kototoki.artifacts`、`kototoki.config`（只读 `paths.output_dir`、`paths.llama_server`、`models.translate`、`translate.port`／`seed`）、`kototoki.srt`。编排器只导入包顶层的 `Session`、`translate_document`、`RECIPE_HASH` 与 `kototoki.merge`；`server`、`client`、`batching`、`generate`、`procs` 是内部实现。内部接缝：`Session(server_factory=..., client_factory=...)` 只供测试替换 server 与 HTTP 客户端。

## 代码与验证入口

- 代码：`kototoki/translate/`、`kototoki/merge.py`。
- 测试（core，`just test`）：`tests/test_translate.py`（伪 server／伪客户端：正常（首个请求与按冻结配方构造的请求逐字节相同）、损坏的中间行报错、每批后 `run.json` 已记批次数、意外异常记 `session_error` 并停 server、译文空行按解析失败、整批共用一个 session、按批次续跑与截掉写了一半的行、全部完成不启动 server、OOM 重启即新 session、两次重启后放弃、缓存校验失败、空场景、`ja.srt` 变化换目录、seed 变化另起 run、显存轮询超时、启动失败后成功、批次终态失败）；`tests/test_translate_recipes.py`（v3 `b10-joint` hash 钉子、提示／grammar／请求 SHA256 钉子、与冻结 v3 函数逐字节对照）；`tests/test_translate_server.py`（stock 加载日志驻留解析、显存轮询、OOM 识别、冻结命令行、模型核对）；`tests/test_merge.py`。
- 未验证：真实 llama-server 下的整片运行、墙钟与显存峰值（票据 05 完成标准第二项，GPU 重任务，待用户确认后运行）；显存阈值 14300 MiB 在桌面占用较高时是否过严。

## 变更与决策来源

票据 `.scratch/bilingual-subtitle-pipeline/issues/05-translate-and-merge.md`；规格 §1.2（含第三轮裁定表）、§3.3、§4、§5.2、§6、§7.3；[ADR-0005](../../adr/0005-apex-i-compact-translation-baseline.md)、[ADR-0006](../../adr/0006-b10-joint-translation-flow-baseline.md)、[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)；stock 引擎的 `run_step` 假设与驻留日志由票据 01 smoke #4 验证。
