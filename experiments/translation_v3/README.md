# Hy30 字幕流程第三轮探索（translation_v3）

实现[v3 计划](../../docs/plans/hy-mt2-translation-flow-exploration-v3.md)：固定 Hy-MT2 30B-A3B APEX-I-Compact，在新的 Claude MQM 裁判（`claude-opus-5-5-mqm-v1`）下比较完整 `jpn.srt → chn.srt` 流程配方。执行状态以 [v3 台账](../../docs/context/2026-10-10-hy30-flow-exploration-v3.md) 和 `status` 命令为准。

当前采纳的完整 SRT 流程基线是内置配方 `dp10-cut`（2026-10-17 起，[ADR-0010](../../docs/adr/0010-dp10-cut-translation-flow-baseline.md)），`just translation-srt` 即 `translate-srt --recipe dp10-cut`；前任 `dp6-grp`（ADR-0009）、`b10-joint`（ADR-0006）保留为内置配方。产品包 `kototoki/` 不导入本包，其配方 `dp10-cut-degrade-v1`（[ADR-0011](../../docs/adr/0011-dp10-cut-product-recipe.md)）是移植。

与 v2 的关系：v2 的代码（`experiments/translation_flow/v2_*`）、目录和结果全部冻结，本包不写入、不修改。v3 只**导入**纯函数：`translation_demo.adapters`（原生模板、ID grammar、解析器）、`translation_demo.client`（loopback 客户端与原始交换记录）、`translation_demo.run`（资产清单、OOM 识别）、`translation_demo_runtime`（驻留证据与校验）、`translation_flow.srt`（SRT 读写）。v2 分数、裁判和 custody 体系不复用。

## 命令

从仓库根目录运行（`uv run --locked --offline python -m experiments.translation_v3 <命令>`，或 `.venv/Scripts/python.exe -X utf8 -m experiments.translation_v3 <命令>`）。默认根目录 `.local/translation-evaluation/hy30-flow-v3/`，可用 `--root` 改。

| 命令 | 作用 | 资源 |
| --- | --- | --- |
| `status` | 只读文件，输出各 run 生成进度、各裁判 profile 进度、`judge-blocked.json`、GPU 锁、队列、建议下一步。**接跑时先运行它** | 离线 |
| `freeze-reference [--force]` | 合并 `reference-review/shard-*.jsonl` 与 reference-v1 元数据，写 `reference-v3/windows.jsonl` 与 `freeze.json`（sha256、计数）；缺任何评分 cue 即失败；内容不变时重复执行只报告已冻结 | 离线 |
| `generate --recipe R --seed S [--scope screening\|confirmation] [--retry-failed]` | 生成一个 run，run id 为 `<recipe>__s<seed>__<scope>` | **GPU**，约 12 分钟／C0 run |
| `queue add --recipe R --seed S1 S2 … [--scope …]`／`queue list` | 维护 `queue.json` | 离线 |
| `run-queue [--break-stale-lock]` | 顺序执行队列中未完成的生成任务，已完成的跳过，可随时中断重跑 | **GPU** |
| `judge --run RUN [--backend cli\|export\|ingest] [--split …] [--replicate N] [--max-packets N] [--parallel K]` | 盲评；只评缺失的包 | **Claude 配额**（cli） |
| `calibrate reference\|synthetic\|repeat [--run RUN 或前缀] [--split …]` | S0 校准：建立参考自检／合成错误伪 run，或在评完后写报告到 `calibration/` | 离线（评审另算） |
| `compare --candidate PREFIX [--candidate …] --control c0 --split screen-a\|screen-b\|screening\|confirmation` | 配对统计与判定，写 `summaries/compare-*.json` | 离线 |
| `translate-srt --srt PATH --recipe R --seed S --out PATH` | S4 整片交付：完整覆盖校验、保留原 cue 编号与时间；不覆盖已有输出 | **GPU** |

确认集：`locked-candidates.json` 格式为 `{"recipes": [{"name": "…", "recipe_hash": "…"}]}`。`generate --scope confirmation`、确认 run 的 `judge`（cli／export／ingest 全部执行面）都核对名字和 `recipe_hash`，配方一改即失去确认资格。确认包导出到单独的 `judge-queue-confirmation/`，结果放 `judge-inbox-confirmation/`（放错收件箱会被拒收）；`status` 只计数，不输出内容。`compare` 在 `decision-policy-v3.json` 冻结前拒绝查看非 control 候选（C0 对 C0 的校准比较允许）。

## 配方

`recipes.py` 中的 `Recipe` 不可变，`recipe_hash` 覆盖全部影响生成的字段与提示常量版本。固定项（不可配置）：C0 官方采样（temperature 0.7、top_p 1、top_k 0、min_p 0、repeat_penalty 1、samplers 仅 temperature、seed）、`n_predict` 4096、`cache_prompt` true、ctx 8192、保护 64 tokens（最大输入 4032 tokens）、每请求最多 2 次相同尝试。超预算记为失败，不截断、不自动缩批。

内置：`c0`（5 条／前后各 1 条只读邻文／原 JSON 提示）、`b3`／`b10`／`b20`、`tok300`／`tok400`／`tok500`（按 `/tokenize` 单条源 token 数打包，计数缓存在 run 的 `token-counts.json`）、`ctx0`、`ctx3`、`ctx3-1`（前 3 后 1）、`joint`（只替换“每个值独立”那句，文字与 v2 `joint-json` 相同，版本 `joint-understanding-v1`）、`terms`（每场景一次只读日文的术语预分析：输入只列逐行日文、不带 cue ID 以节省 token，输出 `{source, translation}`；只保留在 ≥2 条台词中逐字出现的词，证据 cue ID 由程序按原文匹配得出；注入证据 cue 可见的批次）、`review`（目标日文含否定／条件标记时做第二遍审校，同一 grammar）、`bws`（C0 + 有限空白 grammar：`ws ::= [ \t\n\r]?`，与 v2 finite-whitespace 修订同形，用于测量 4096 token 空白循环）。`b10-joint`（每批 10 条＋joint 提示；2026-10-11 至 10-16 的完整 SRT 流程基线，见 [ADR-0006](../../docs/adr/0006-b10-joint-translation-flow-baseline.md)；hash `2ba68054…`；v3–v7 的对照）。`dp6-grp`（`b10-joint`＋`gap_pack`：<1 s 小组、软 2 s 每秒 1 分、硬 10 s、6–12 条、小包惩罚 1000、邻文前 <5 s／后 <1 s；2026-10-17 短暂作为基线，见 [ADR-0009](../../docs/adr/0009-dp6-grp-translation-flow-baseline.md)；hash `ae473cdc…`）。`dp10-cut`（`b10-joint`＋`gap_pack` v2：不用小组、`cut_penalty` [[0.5, 6], [1.0, 3], [2.0, 1]]、软 2 s 每秒 1 分、硬 20 s、6–10 条、小包惩罚 1000、邻文前 <5 s／后 <1 s、可见 ≤12；**2026-10-17 起为采纳的完整 SRT 流程基线**，未做 GPU 筛选，见 [ADR-0010](../../docs/adr/0010-dp10-cut-translation-flow-baseline.md)；hash `ee72ce66…` 由 `AdoptedBaselineTest` 固定；`just translation-srt` 即 `translate-srt --recipe dp10-cut`）。`grp1`（v8 候选：`dp10-cut`＋`groups` `{"gap": 1.0}`，见下文“同一句话小组”；未做 GPU 运行；hash `5aaf3e77…`）。

组合：写 `<root>/recipes/<name>.json`，如 `{"name": "tok400-ctx3", "base": "tok400", "context_before": 3, "context_after": 3}`。名字不能含 `__`；同名但内容不同的已有 run 会被拒绝续跑。

按类别路由：组合配方可加 `category_overrides`，例如 `{"name": "route", "base": "b10", "category_overrides": {"animation_movie": {"batch_count": 5}}}`：剧集场景用基础字段，电影场景用覆盖后的字段。路由信息进入 `recipe_hash`（`versions.routed`）；不带该字段的配方 hash 不变。场景类别取自源清单；`translate-srt` 对路由配方必须给 `--category`，否则在加载模型前报错。

场景感知切法（v6，[研究文档](../../docs/research/2026-10-16-scene-aware-batching-v6.md)）：组合配方可加 `gap_split`，键为 `snap`、`max`、`cut_gap`、`context_gap`、`max_visible`，例如 `{"name": "gsnap5", "base": "b10-joint", "gap_split": {"snap": 2, "max": 12, "cut_gap": 5.0, "context_gap": 5.0, "max_visible": 12}}`。保留 `batch_count` 的切点网格，每个网格点在 ±snap 条内挪到最大的 ≥cut_gap 秒静默处（任何批不超过 max 条）；只读邻文只在静默 < context_gap 时才取，可见条数超过 max_visible 时先去后邻文。批数与纯计数分批相同。版本 `gap-split-v1` 进 `recipe_hash`；不带该字段的配方 hash 不变。

按静默拼包与停顿标记（v7，[研究文档](../../docs/research/2026-10-16-gap-aware-batching-v7.md)）：`gap_pack` 键为 `min`、`max`、`soft_gap`、`hard_gap`、`soft_weight`、`small_penalty`、`group_gap`、`group_max`、`context_both_below`、`context_before_below`、`max_visible`，以 `batch_count` 为目标包大小，对每个场景用动态规划取总惩罚最低的切法（(大小−目标)²＋包内每个 ≥soft_gap 的间隔按秒乘 soft_weight＋小于 min 时加 small_penalty；含 ≥hard_gap 间隔或超过 max 条不可行）；`group_gap` 非空时只在该门槛以下连续 cue 组成的小组边界切（超过 group_max 的组等分为 ⌈n/目标⌉ 份）。邻文：前句在停顿 < context_before_below 时可见，后句在 < context_both_below 时可见，超过 max_visible 先去后句。`pause_marks`（`{"min_gap": 秒}`）在只读上下文列表里每个可见的 ≥min_gap 静默处插入 `{"pause": "此处约N秒无台词"}`，待译 JSON 与 grammar 不变，场景文件的批记录多一个 `pauses`。可选键 `cut_penalty`（ADR-0010，`[[below_seconds, penalty], ...]`，below 递增）给每个内部切点加分：取第一个 below 大于切点处静默的档位（缺时间戳取第一档），≥最后一档不加；带它时版本为 `gap-pack-v2`。版本 `gap-pack-v1`／`gap-pack-v2`、`pause-mark-v1` 进 `recipe_hash`；不带这两个字段的配方 hash 不变。`gap_pack` 与 `gap_split` 互斥。

同一句话小组（v8，[研究文档](../../docs/research/2026-10-18-group-reorder-v8.md)）：`groups`（`{"gap": 秒}`，需 `prompt` 为 `joint`）在每个包的目标 cue 内按 R2+ 划组（`batching.sentence_groups`）：相邻两条停顿 < gap（重叠也算、缺时间戳按无停顿）且前一行去掉行尾空白与右括号／引号后不以 `。？！?!.` 结尾即同组，`…`、`、` 不算句末，不设大小上限、不跨包、只读邻文不入组。含 ≥2 条小组的批次把 joint 句换成 `joint-understanding-v2`（同组各值合起来表达一句话、可按中文语序在组内重新分配、每个值非空且长度与原文大致相称、不同组之间仍逐 ID 归属），并在 assistant 标记前注入一行 `以下是待译条目中属于同一句话的 ID 分组：{"groups": [["id1","id2"], ...]}`（只列 ≥2 条的组、只含目标 ID）；场景文件的批记录多一个 `groups`。没有这种小组的批次与不带该字段的配方逐字相同。grammar、采样、切包、邻文不变。版本 `group-reorder-v1`（句末字符、右括号集合、注入文字与 `joint-understanding-v2` 文字的 hash）进 `recipe_hash`；不带该字段的配方 hash 不变（`test_recipes.GroupReorderTest` 固定全部 17 个旧内置配方的 hash）。

通用模型臂（v9，[研究文档](../../docs/research/2026-10-21-general-model-translation-v9.md)）：`model`（唯一取值 `qwen3.8-27b-ud-iq3_s`）须与 `prompt: "qwen-joint"` 同用，且不与 terms／review／sampling／target_context／多样本／glossary／pause_marks／groups／路由组合。生成走 `qwen.py`：`qwen-joint-v1` 把 Hy-MT2 joint 提示的任务文字原样拆成 chat 的 system（只读上下文之前的全部说明）与 user（只读上下文＋待译 JSON），经 `/v1/chat/completions`（`--jinja`、`--reasoning off`、`enable_thinking: false`）发送，`grammar` 字段即对照的 ID GBNF 原文；输入预算在 server 渲染后的 chat 提示上量（`/apply-template`＋`/tokenize`，上限 context − 4096 − 64）；Qwen 官方 non-thinking 采样（0.7／0.8／20／0、presence_penalty 0）、`cache_prompt`、最多两次（第二次 seed＋1）；校验仍是 `parse_translation` 再加 ID 顺序。server 用产品 `kototoki.llama_server.ManagedServer`（names 同款参数：官方 b11669、99 层、`-b 512 -ub 512 -fa on --jinja --reasoning off`，context 8192／宽邻文 16384），外加 v3 GPU 锁与 Job Object；模型与 server 身份抄在 `qwen.py` 常量里，产品改动不移动 v9 hash。`wide_context`（`{"max_visible": n}`，版本 `wide-context-v1`）只替换邻文规则：按 `context_before／context_after` 条数取到场景边界、不看静默，超过 n 先去后句；切包不变。内置 `qwen-narrow`（`dp10-cut`＋Qwen，hash `d878d2d1…`）、`qwen-wide`（再加前 20＋后 5、`max_visible` 35，hash `719237b9…`）。两个字段的默认值不进 `spec()`（`test_qwen.QwenRecipeTest` 固定 18 个旧内置配方的 hash）；带 `model` 时 `fixed` 换成 Qwen 的采样与 context。

v10 选项（[研究文档](../../docs/research/2026-10-21-q0-exploration-v10.md)）：`qwen_options`（只能与 `model` 同用，默认 `None` 不进 `spec()`）每个键改一件事，未出现的键保持 `qwen-joint-v1` 行为——`system`（`qwen-joint-v2`：v1 规则全文原样保留，前加译者角色、后加字幕自然度要求）、`asr`（`qwen-asr-aware-v1`：system 末尾加一段"源文是语音识别稿"）、`names`（`{"filter": "window"|"all", "tables": {work_id: [{source, translation}]}}`，`qwen-name-table-v1`，按窗口命中或整表追加到 system）、`brief`（`{work_id: 文本}`，`qwen-work-brief-v1`，追加到 system）、`context`（覆盖 context 大小，≥16384）、`thinking`（`{"budget": N, "min_visible": K}`：server 改 `--reasoning on --reasoning-budget N`，目标 ≥K 条的包 `enable_thinking: true`、`max_tokens` 加 N，ID grammar 前加自由思考前缀 `thought-prefix-v1`——否则 grammar 从第一个 token 起约束、模型不思考；其余包与 v1 相同）。user 消息不变；文本的 sha256 进 `versions.model.options`。`translate-srt` 对带 `model` 的配方改用 `qwen.session_factory`，`--work-id` 给 names／brief 选该部作品。

v11 选项（[研究文档](../../docs/research/2026-10-22-q0-product-route-v11.md)）：`wide_context` 可加 `silence_gap`（秒，>0）：只读邻文从包的首尾向外取，遇到 ≥silence_gap 的静默即停（包内的静默不影响，缺时间戳按无静默），再按条数与 `max_visible` 截；切包不变。带该键时版本为 `wide-context-v2`，不带时仍为 v1、hash 不变。`qwen_options.names.filter` 新增 `targets`：只注入写法出现在**待译 cue** 里的条目（不看只读邻文），并改用 `qwen-name-table-v2` 表头（多一句"只在原文出现该写法的位置使用，不要把代词、称呼或省略的主语改成名字"）；`window`／`all` 仍用 v1 表头。

C0 等价性：`test_recipes` 证明 v3 的 C0 prompt、grammar 和完整 completion 请求（序列化字节）与 v2 `v2_recipes.render_window("c0")`／`completion_request` 一致，批次划分与 `v2_prepare.pack_scene` 一致。

## 目录布局（根目录下）

```
reference-review/shard-*.jsonl     Opus 复核分片（输入）
reference-v3/windows.jsonl, freeze.json
runs/<recipe>__s<seed>__<scope>/
  run.json                         配方 JSON＋hash、seed、源哈希、代码哈希、sessions（引擎／模型身份、墙钟、停止原因）、completion、resumed
  scenes/<scene_id>.json           每场景原子写：译文、批次与位置（first/mid/last/single）、每请求尝试（tokens、timings、stop_type、stopped_limit、失败输出空白比例、原始交换路径）、失败
  token-counts.json                token 配方的单条计数缓存
  runtime/session-NN/              服务器日志、engine.json、engine-final.json（驻留、显存峰值）
  transport/session-NN/            全部 HTTP 原始请求／响应
  judge/<profile>[@repN]/packets.json, p<hash>.json, p<hash>.error.json, .lock（每 run 裁判锁）
  infra-failures/<scene>--session-NN.json   基础设施失败的证据（不是场景终态）
deliveries/<recipe>__s<seed>__srt-<sha12>/   translate-srt 的 run
judge-queue/<packet>.md, judge-inbox/<packet>.json   export／ingest 备用执行面（不含 run 名）
judge-queue-confirmation/, judge-inbox-confirmation/  确认集专用（status 只计数）
judge-blocked.json                 配额／登录阻塞记录
queue.json, recipes/, calibration/, summaries/, cache/model-verification.json
decision-policy-v3.json, locked-candidates.json      人工冻结
```

`.local/gpu.lock` 记录持有者 pid＋进程创建时间、run id，服务器启动后补记 `server_pid`＋创建时间；存活判断同时核对创建时间（防 PID 复用；旧格式锁只看 pid）。存活持有者在时拒绝启动（退出码 3），绝不杀进程；死进程留下的锁会报告，确认后加 `--break-stale-lock`。非 v3 格式的锁一律拒绝。llama-server 放进带 KILL_ON_JOB_CLOSE 的 Windows Job Object，Python 被强杀时服务器随之退出。`status` 列出不归存活 v3 进程所有的 llama-server（`orphan_llama_servers`），只报告、不处理。

## 恢复与配额语义

- **生成**：每个 session 新启动服务器（空缓存），首个 completion 必须 `timings.cache_n == 0`。服务器成功启动后才把 session 记入 run.json（锁或端口失败不留记录）。只有上下文超限、输出上限、解析／grammar 失败（重试后）是场景终态（`failed`），跳过不重做，`--retry-failed` 可重做。OOM、传输／服务器错误、缓存校验失败属于基础设施失败：不写场景文件，只在 `sessions[].infra_failure` 记录并把证据写到 `infra-failures/`，随即停止该 session；下次 `generate`／`run-queue` 自动重做（旧版写成 failed 的同类场景文件也按未完成处理）。实际干活的 session 超过一个即 `resumed: true`、`performance_comparable: false`，墙钟不进性能比较。原子写在 Windows 遇到 PermissionError 时最多重试 20 次。
- **模型校验**：加载前对 GGUF 全量 SHA256，结果按路径＋大小＋mtime 缓存于 `cache/model-verification.json`，并记入 run。
- **裁判**：每包 4 窗、同一 run；打包用固定种子按 split 洗牌（与 run 无关，所以各候选的包组成相同；`--replicate N` 换种子用于重复噪声）。包内只有不透明的候选哈希。CLI 执行面：`claude -p --safe-mode --model claude-opus-5-5 --effort high --tools "" --strict-mcp-config --setting-sources "" --no-session-persistence --output-format json --system-prompt … --json-schema …`，在空临时目录运行，提示经 stdin，输出按 UTF-8 解码；优先读 `structured_output`。若 CLI 拒绝空的 `--setting-sources`，自动改用 `project`（空目录无项目设置）并记录。`modelUsage` 中每个 `outputTokens>0` 的模型都必须是 `claude-opus-5-5`，否则该包记错误、不重试；完整 `modelUsage`、费用与耗时都记录。每个 run／profile 有裁判锁 `judge/<profile>/.lock`（pid＋创建时间）：存活进程持有时退出码 3，死进程的锁自动替换并记录，防止两个裁判进程重复花配额。
- **裁判提示 prompt-v2**（profile 名不变，`prompt_version` 与哈希记入 profile）：解释参考置信度（high 可信／medium 只是一种合理理解／low 不得据参考判错）；同一问题只记一次；跨 cue 断句不同但信息完整不算 cue-attribution；人名称呼的通行译法、句末标点、省略语气词不算错；给出严重度锚点；每窗附上评分段前后各 1 条相邻 cue 的候选译文（标“不评分”），避免把移到邻条的内容误判为漏译。429、额度／限额文字或未登录 → 写 `judge-blocked.json`，退出码 **75**，不标记包失败；配额恢复后重跑同一命令即可。529／超时／无效输出等暂时错误退避重试，最多 3 次，之后写 `<packet>.error.json`（下次仍会重试）。
- **备用执行面**：`judge --backend export` 写 `judge-queue/<packet>.md`（系统提示＋schema＋任务包）；子 agent 把 JSON 写入 `judge-inbox/<packet>.json`；`judge --backend ingest` 用同一校验收录，记录 `surface: export-ingest`。`compare` 拒绝混用执行面。

## 统计

MQM 惩罚 minor 1／major 5／critical 10；accuracy 类为主终点（每条评分 cue 惩罚均值）。覆盖按所比较 split 的全部预期窗口计算：每个 seed 中每窗要么已评，要么不可交付（所在场景终态失败：每条评分 cue 记 accuracy 10、计入 major+ 与 critical）；其他情况（未评、生成未完）判 insufficient 并列出缺失窗口；两侧必须是同一组 ≥3 个 seed（`required_seeds`）。每窗先对各 seed 取均值，再按作品等权得到剧集、电影两类，总览各占 50%；代表窗与风险窗分开，总览只用代表窗。配对 Δ = 候选 − C0。bootstrap 10000 次、种子 `v3-bootstrap-20261010`，键全部排序（与 PYTHONHASHSEED 无关）；按作品分层重抽，若给了 `series_clusters` 则按系列重抽、系列内作品仍等权；点估计始终按作品等权。输出逐作品 Δ 表与逐一剔除作品（LOO）的重判。promising 需同时满足：总体 Δ ≤ −MDE；两类都不劣于非劣界；代表窗与风险窗的 critical 都不增加；风险窗 Δ major+ 率的 bootstrap 上界 ≤ `risk_major_margin`；候选交付失败率不高于 C0＋`delivery_margin`（默认 0）；每个 LOO 仍满足前两条。确认集用 Holm 校正。`decision-policy-v3.json` 必填 `mde`、`noninferiority_margin`、`risk_major_margin`，可选 `delivery_margin`、`required_seeds`、`series_clusters`、`holm_alpha`、`critical_rule: no_increase`。校准：`calibrate reference`（参考自检）、`calibrate synthetic --run c0__s20261008__screening`（否定翻转、数字改动、删关键信息、相邻 cue 互换约 40 处；真值清单只存在 `calibration/synthetic/`，不在 run 目录）、`calibrate repeat --run c0`（默认 screening 96 窗；对有 `--replicate` 重评的各 seed 取逐窗差的均值，按与判定相同的作品等权／类别 50:50 聚合，以聚类 bootstrap 的标准差为 SE，建议 MDE = 2·SE，并给出 major 翻转率）。

## 验证范围

已验证（离线）：`uv run --locked --offline python -m unittest discover -s experiments/translation_v3 -t . -p "test_*.py" -v`（78 项，含类别路由与基线 hash 固定、v9 的 `test_qwen`，约 3–4 秒；含 PYTHONHASHSEED 子进程、Job Object 子进程）覆盖 C0 等价、配方哈希与组合、批次与位置、伪客户端下的生成／续跑／OOM／缓存校验／重试／上下文超限／术语与审校、包盲化与校验、基础设施失败不落终态并自动重做、锁／端口失败不记 session、伪 subprocess 下的 CLI 成功／配额 75／未登录／暂时错误／modelUsage 检查／`--setting-sources` 回退、并发裁判锁、确认集门禁与分开的导出目录、export／ingest、prompt-v2 与相邻 cue、合成扰动、不可交付窗口记 critical、split 覆盖与 seed 不齐、风险窗／critical／LOO／交付门槛、跨哈希种子的 bootstrap 确定性、判定尺度上的 MDE、状态推导与孤儿服务器、PID 复用、原子写重试、Job Object 杀子进程、GPU 锁与模型校验缓存。另用真实冻结数据离线核对：34 场景／4297 cue／96 窗、确认集 20 场景／48 窗、reference-v3 计数（144 窗、720 cue、修改 6、high 585／medium 135、带歧义 185）、裁判上下文日文与模型输入一致、34 个场景的 C0 批次与 v2 完全相同。

未验证：新的 Job Object／锁逻辑下的真实 llama-server 启动（首个真实 C0 run 用的是加这些改动之前的代码）、真实 `claude` 调用（`--strict-mcp-config`、空 `--setting-sources` 是否被接受、错误文本与限额字段以探针观察为准，正则可能需补充）、`translate-srt` 端到端、`terms`／`review` 提示的实际效果与 token 预算（筛选集最长场景的术语提示约 3200 字符，预计低于 4032 token，但未实测；超限会记为场景失败）。
