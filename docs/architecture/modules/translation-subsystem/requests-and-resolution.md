---
covers:
  - kototoki/translate/recipes.py
  - kototoki/translate/batching.py
  - kototoki/translate/resolve.py
---
# 翻译子系统子页：请求、失败分类与按条解决

`翻译子系统` 的子页：Q2 请求规则（切包、邻文、提示、专名注入、请求体、校验）、失败分类与按条解决（追问与拆分）。

**请求**（Q2 规则）：每部影片是一个场景，cue ID 用 `srt.py` 的 `<sha8>-cue-<n>` 别名，cue 带 `ja.srt` 的起止秒。

- **切包**（`batching.gap_pack_cuts`，`gap-pack-v2`）：整个场景用动态规划取总惩罚最低的切法，每批待译 ≤10 条。
  - 每批代价 = (条数 − 10)² ＋ 批内每个 ≥2 s 停顿按秒数计 1 分；<6 条加 1000 分；批内有 ≥20 s 停顿不可行。
  - 内部切点按停顿分级加罚：<0.5 s 加 6、<1 s 加 3、<2 s 加 1，缺时间戳按第一档。
  - 停顿只取自 `ja.srt` 自身的时间轴、只比较长短，不是时间换算。
- **只读邻文**（`batching.neighbours`，`wide-context-v1`）：前 20 条、后 5 条，只按条数取到场景边；可见总数（含待译）超过 35 条时先去后邻、再去前邻。追问与拆分的子节点用同一规则。
- **提示**（`recipes.messages`，`qwen-joint-v1`）：两条 chat messages。system 是 joint 任务文本，该批有注入行时末尾追加 `qwen-name-table-v1` 的 header 与 `日文 → 中文` 逐行；user 是只读日文上下文（JSON）加待译 JSON `{"translations": {id: 日文}}`。文字与研究侧 `archive/2026-11-18-pre-research-restructure:experiments/translation_v3/qwen.py::messages` 逐字节相同。
- **专名注入**（`recipes.name_rows`、`names_for_window`）：取 `name-table.json` 里 `confidence: high` 的实体，每个 `forms[]` 一行，按 `ja` 去重，跳过 `ja` 或 `zh` 为空的写法；某批只注入日文写法出现在该批可见台词（含只读邻文）里的行。表为空时不注入，翻译照常。只改 medium／low 条目不改变注入行。
- **请求体**（`recipes.request_body`）：chat completions，无 grammar，思考关闭，`temperature 0.7、top_p 0.8、top_k 20`，`max_tokens` 4096，非流式，`seed` 取 `[translate] seed`（须为正整数）。同一节点最多两次：seed、seed＋1。批次的请求体与研究侧 `strata.request_body(qwen.messages(…))` 逐字节相同。
- **校验**（`recipes.parse_translation`）：严格 JSON（重复键拒绝）、恰好一个 `translations` 对象，否则抛 `ValueError`；再按条判：非空且无空行的收下，其余记为 `missing`／`empty`／`blank_line`；多出的 ID（记数 `extra_ids`）与顺序不看。
- 每个 Strata session 首个 completion 的 `cache_n` 只记录，不据此判失败；输入 token 超过 Q1 预算（12224）只记 `over_q1_budget`，不判失败。

**失败分类**（`generate.run_step` 与 `translate_document`）：

| 种类 | 来源 | 处理 |
| --- | --- | --- |
| `oom`、`server`、`server_error`、`server_start` | HTTP 正文为 OOM 文本／其他 HTTP 错误、连接失败或超时、响应带 `error`、Strata 起不来（`InfraFailure`） | 停掉 Strata，同一次调用内启动新 session 重做 |
| `context`、`limit`、`parse`、`unresolved` | 超出 context、`finish_reason == "length"`、空回复、结构校验失败、一条都没收下 | 该次尝试失败；两次都失败即节点终态（下节），不重启 |
| `StrataRefused` | 见 [Strata 服务与共享 session](../strata-session.md#当前行为规格) | 不重试 |
| 其他异常 | 非 JSON 响应、写盘失败等 | 记 `stop_reason = session_error: …`，停掉 Strata，原样上抛 |

- 基础设施失败同一次调用内最多重启 2 次（`generate.MAX_RESTARTS`），仍失败抛 `TranslateError`。`oom`、`server` 与 `context` 不做第二次尝试。
- 启动失败的额度归 `Session`（整批累计 3 次即不可用）；本子系统只在每轮开始时读 `session.unavailable`：非空即抛 `TranslateError`，消息带其原因。
- `StrataRefused`：停掉 Strata，抛 `TranslateError`；共享 session 已被 `Session` 置为不可用，本批其余需要模型的影片在 names 与翻译都直接失败。

**按条解决**（`resolve.py`，ADR-0029）：节点是场景内连续的一段待译 cue，初始节点即批次，每个节点最多两次尝试。

- 收下至少 1 条即结束（`accepted`，有未解决时 `partial`）；未解决的 cue 按最大连续段成为子节点 `父ID.1`…（`runs`）。
- 两次都失败：多于 1 条对半拆成 `父ID.a`／`.b`（`halves`）；单条则译文为 `None`（不出中文），原因取最后一次的按条类别或失败种类。
- 子节点的邻文、注入同原批次，seed 从原 seed 起。
- 首个请求即全收的批次不写节点日志；其余节点一出结果即追加到 `nodes.jsonl`，重启后已记录的不再请求。批次完成写成 `batches.jsonl` 一行（带 `resolution`）。未翻译对该配方 hash、seed 与注入行是终态；要重试须改 `[translate] seed`；要重做已发布的文件须先删掉其 `.ja-zh.srt`。
- 按条取第一个合格译文、不比较尝试，不是"翻译多次再挑选"（ADR-0008）。

## 代码与验证入口

- 代码：`kototoki/translate/recipes.py`、`batching.py`、`resolve.py`（`generate.py` 的 `run_step` 见[运行目录子页](run-directory.md#代码与验证入口)）。
  - `tests/core/test_translate_recipes.py`：`RECIPE_HASH` 与名称；随机场景上的批次、窗口与请求体（含 seed＋1）合成一条 sha256 钉子；注入行规则（只收 `confidence: high`、形式去重）；逐条判定的解析；宽上下文只数 cue、不计停顿；gap-pack-v2 的 DP 与暴力一致、硬间隔必切、均匀场景偏好均匀批次。
  - `tests/core/test_translate_resolve.py`：子节点的邻文规则、未翻译 cue 按段追问、仍为空的 cue 留作未翻译、结构失败对半拆到单条、超出 context 一次后对半拆、续跑复用已记节点、未翻译对该配方与 seed 为终态、`published.json` 的未翻译计数。
  - 测试精简（2026-11-22）后不再有测试覆盖：
    - 配方与请求：提示文本与请求体形状的字面量钉子；注入行的窗口过滤、`names_sha256` 只随条目、空表被拒、结构严格校验；场景 id、cue id 与时间随 ja.srt、可见上限先丢后侧；无注入时为朴素 Q2 system message；停顿处切点移向更长停顿。
    - 追问与解析：单条批不拆而留作未翻译、记录的单条失败续跑时重建为未翻译、节点日志行落在计划之外被拒、空场景写空报告；对半拆、被拒请求与追问中基础设施失败的日志与重启。
- `tests/core/test_translate.py` 的重启、第二次尝试与失败分类用例见[运行目录子页](run-directory.md#代码与验证入口)。
