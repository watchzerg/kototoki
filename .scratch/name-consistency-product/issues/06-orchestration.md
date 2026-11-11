# 06 编排接入：names 阶段、发布时替换、日志与汇总、模块页

Status: done
Type: task
Blocked by: 02, 03, 04, 05

## 背景

把 02–05 接成一条链：编排器在 cues 之后起 Qwen server 对本批建表，翻译之后在发布时做替换。设计见增量说明 §2、§3.1–§3.6。这是唯一的集成票，也是最大的一张；不再拆。

## 范围

- `kototoki/names/__init__.py` 对编排器的接口：
  - `Session(config, on_server_pid=…)`：最小实现（约 30 行，不与翻译共享）：`ensure_started()` 在 server 为 None 或已退出时用 `llama_server.ManagedServer(runtime_root/session-NN, NAMES_SPEC, engine=config.paths.llama_server, model=config.models.names, port=config.names.port, model_cache=…, on_pid=…)` 启动，整批最多启动 3 次（即重启 2 次），超过或 `InfraFailure` 时 `unavailable` 置位；`stop()`／上下文管理器；运行日志根 `.work/names-sessions/<UTC戳>-<pid>/`。
  - `build_document(work_dir, document, session, seed) -> BuildResult`：零条目不起 server；`client = LlamaClient(server.url, timeout=1800, trace_dir=work_dir/"names"/"transport"/"session-NN")`；调 `table.build_table(document, client.chat_completion, client.tokenize, seed)`；HTTP 5xx／连接失败／OOM 文本抛 `NamesError`（编排记该影片失败；server 是否死掉由下一部的 `ensure_started` 判断）。
  - `apply`、`BUILD_RECIPE_HASH`、`APPLY_RECIPE_HASH`、`NamesError` 导出；`test_assets_manifest.py` 补 `names.recipes.BUILD["model_asset"] == assets.toml`。
- `kototoki/job.py`：
  - `names_batch(ctx, batch)`：与 `translate_batch` 同形——`batch = planned("names")` 里 `ja.srt` 非零条目的文件需要模型；有需要时 `ensure_gpu_lock` 并建 `names.Session`（`on_server_pid` 写锁）；逐文件 `srt.read_srt(work/ja.srt)` → `build_document` → 编排用 `artifacts.write_artifact(work/name-table.json, video.plan.identities["names"], payload)`；`build.status != ok` 记 WARNING；异常记该文件 `names` 阶段失败；随后 `advance_or_fail(ctx, video, "names")`。位于 cues 循环之后、`translate_batch` 之前。
  - 发布：`stage == translate` 的文件在拼 `texts` 前，若 `config.names.enabled`：读 `name-table.json` 的 payload，`result = names.apply(table, document, translations)`，`write_artifact(work/names-apply.json, video.plan.identities["names_apply"], {"summary", "changes", "unresolved"})`，`zh`／`ja-zh` 用 `result.translations`；发布行追加替换数；`Summary.name_replacements` 累计并进 `[summary]`。
  - 日志按增量说明 §3.6（条目文字不进日志）；`_translate_module` 旁加 `_names_module`（importlib）。
- `tests/core/test_job.py`：`JobCase` 加伪 `kototoki.names` 模块（`Session`、`build_document`、`apply`、两个 hash、`NamesError`）与伪 `kototoki.names.recipes`；用例：阶段顺序 cues → names → translate（session 进出顺序）、只在有文件需要模型时取锁与建 session、session 建不起来只让需要模型的文件失败且其余照常、`build.status=failed` 空表仍发布、发布时写 `names-apply.json` 且 `zh`／`ja-zh` 是替换后文本、改表（改 `entries`）后重跑只重发布且不建 translate session、`enabled=false` 不出现 names 事件、禁止导入清单仍成立、每文件 `next_stage` 恰一次且每个跑过的阶段 `advance` 恰一次（names 计入）。
- `tests/full/test_job_ffmpeg.py`：伪 names 模块；断言 names session 先于 translate session、两个新文件落盘、`published.json.sources` 含两键。
- 新建 `docs/architecture/modules/name-consistency.md`（按模块页模板，写现状）；批次编排页（流程步骤、锁、日志）、阶段计划页（链与 `sources`）、产物契约页（两个文件名）、配置页（`[names]`）、架构总览模块地图与产品包图同步。

## 完成标准

- `just test`、`just test-full` 全绿。
- `import kototoki.job`／`kototoki.__main__` 后 `sys.modules` 仍无推理包与 `experiments.*`。
- 上列文档就位；模块页"代码与验证入口"如实写：真实 Qwen server 路径（07）与整片（08）未验证。

## 文件所有权

`kototoki/names/__init__.py`、`kototoki/job.py`、`tests/core/test_job.py`、`tests/core/test_assets_manifest.py`（补一条）、`tests/full/test_job_ffmpeg.py`、`tests/fake_names.py`（若需要）、上列模块页与架构总览。

## Comments

### 2026-10-20 实现记录（票据 06）

已实现：

- `kototoki/names/__init__.py`：对编排器导出 `Session`、`build_document`、`apply`、`NamesError`、`BUILD_RECIPE_HASH`、`APPLY_RECIPE_HASH`（另有 `NAMES_SPEC`、`MAX_STARTS`、`ApplyResult`、`BuildResult`）。`NAMES_SPEC` 由 `recipes.NAMES_SERVER` 与 `BUILD["model_asset"]` 拼成（`stage="names"`）。`Session`：首次需要时启动，server 进程已退出时下一部先收尾再重启，整批最多启动 3 次；任何启动失败或启动次数用尽即 `unavailable`。`build_document`：零条目不起 server；`LlamaClient(timeout=1800)`，tokenize 回调取 `len(client.tokenize(text))`；`HTTPError`（按 `explicit_oom` 分 `oom`／`server_error`，消息只带状态码与正文长度）、`URLError`／连接错误／超时 → 停掉 server 并抛 `NamesError`。
- `kototoki/names/recipes.py`：补 `APPLY`（id `names-apply-v1`、规则开关冻结取值、`MIN_SUPPORT`／`MIN_RATIO`／`MIN_SHARE`／`MAX_EXTEND`／`EXTEND_SHARE`、n-gram 范围、`EDGE_STOP`、中文敬称、`BOUNDARY_CHARS`）与 `APPLY_RECIPE_HASH`（`5c795c35…`，`test_names_recipes.py` 钉住）。
- `kototoki/names/apply.py`：删除死常量 `EDGE_WORD_CUES`／`EDGE_WORD_BRANCH`（默认路径不读；`test_names_apply.py` 全绿，行为不变），也不进 `APPLY`。
- `kototoki/job.py`：`names_batch`（与 `translate_batch` 同形，位于 cues 之后、translate 之前）、`apply_names`（发布时读表、替换、写 `names-apply.json`）、`publish` 加 `replacements`、`Summary.name_replacements`、日志按增量说明 §3.6。
- 测试：`test_job.py` 去掉临时的 `[names] enabled = false`，加伪 `kototoki.names`／`kototoki.names.recipes` 与 `NamesTests`（10 例）；改了四处既有断言（阶段顺序加 names session、advance 计数加 names、`[summary]` 行加替换数、第三方日志用例的 "dropped" 字样与建表行冲突改成查 "below root level"）；禁止导入测试另导入 `kototoki.names` 与 `kototoki.translate`。新增 `tests/core/test_names_session.py`（9 例：Session 与 `build_document`）。`test_names_recipes.py` 加 `APPLY` 钉子与 `NAMES_SPEC` 核对，`test_assets_manifest.py` 加模型资产 == `assets.toml`。`tests/full/test_job_ffmpeg.py` 断言 names session 先于翻译 session、两个文件落盘、`sources` 含两键。
- 文档：新建 `docs/architecture/modules/name-consistency.md`；同步批次编排（流程第 7 步 names、第 9 步发布时替换、锁、日志、logger 清单含 `llama_server`）、阶段计划（链、身份表、`sources`）、产物契约（两个文件名）、配置（`[names]`）、架构总览（模块地图新行、翻译行加 `llama_server.py`、产品包图加 names 与 llama_server 中间层）、模块边界（去掉"代码尚未存在／本次增量引入"、过时的 `translate.client` 接缝改为两个 `Session` 的工厂接缝、logger 清单、失败分级、锁、身份）。

与票据的偏差：

1. 交换目录是 `<work_dir>/names/transport/<UTC戳>-<pid>/session-NN/` 而不是 `…/transport/session-NN/`：`LlamaClient` 以 `mkdir(exist_ok=False)` 建 `00001`、`chat-03` 等目录，同一影片在后续运行里重建表（改 seed、上次失败）时会与旧目录撞名；按运行分目录保留旧证据。
2. 传输失败时 `build_document` 主动停掉 server（下一部 `ensure_started` 重启，计入 3 次），而不只靠下一部判断 server 是否已死：刚返回 5xx／OOM 的 server 不可信，与翻译子系统的做法一致。
3. 任何启动失败（不只 `InfraFailure`，也含端口被占、模型／引擎核对不过）都置 `unavailable`：这些在一批之内不会自愈。
4. 包属性 `kototoki.names.apply` 是替换函数，遮住同名子模块；为此 `recipes.py` 改成逐名导入 `apply` 子模块的常量，`test_names_apply.py` 的 `names_apply.isolated_in` 改为直接导入 `isolated_in`。
5. 替换处数取 `names-apply.json` 的 `changes` 条数（与研究期"161 处改动"同一口径）；`[summary]` 行总是带替换数（停用时为 0），发布行只在启用时带。
6. `llama_server.py` 不单独建模块页：其来源与命令行已记在翻译子系统页，names 的 spec 记在新页；模块地图把它列进翻译行的位置。

验证：`python -X utf8 -m unittest discover -s tests/core -t .` 583 例全绿（连跑两次）；`tests/full` 12 例全绿；`import kototoki.job, kototoki.__main__, kototoki.names` 后 `sys.modules` 无推理包与 `experiments.*`，且 `import kototoki.job` 不加载 `kototoki.names`；`scripts/check_docs.py` 仍只有 44 处既有失败，本次改动的文档没有新增坏链。未跑任何 GPU 作业、模型或 `python -m kototoki`。

留给后续：07 的真实 Qwen server smoke（加载、驻留、`/tokenize` 与 chat 请求、显存峰值）；08 的两部整片产品路径验收与等价校验；09 的 README（新模型与"改表重跑"）、GLOSSARY、AGENTS、规格各节、`docs/INDEX.md` 与调研索引，以及吸收并删除 `docs/changes/name-consistency-product.md`（其 §3.2 写的交换目录形状 `names/transport/attempt-N.*` 与实现不同，吸收时以模块页为准）。
