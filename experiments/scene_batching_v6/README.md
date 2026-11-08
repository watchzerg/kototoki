# 第六轮探索：场景感知分批（scene_batching_v6）

实现[v6 研究文档](../../docs/research/2026-10-16-scene-aware-batching-v6.md)的 Q1 离线分析与 Q2 干预实验（已结题，结论见文档 §7）。对照 `b10-joint`，裁判 `claude-opus-5-5-mqm-v1` 不变。

切法本身在 `translation_v3`：`Recipe.gap_split`（`gap-split-v1`，见 [translation_v3 README](../translation_v3/README.md)）。本包只导入 v3／v4 代码，不修改冻结产物；v4 根目录 `.local/translation-evaluation/hy30-flow-v4/` 的集合、参考与 run 只读。

## 命令

仓库根目录运行 `uv run --locked --offline python -X utf8 -m experiments.scene_batching_v6 <命令>`，产物根目录 `.local/scene-batching-v6/`。

| 命令 | 作用 | 资源 |
| --- | --- | --- |
| `status` | 只读：各 run 生成状态、裁判包进度、子集、配额阻塞、GPU 锁 | 离线 |
| `q1` | Q1：少数派／多数派／干净批次对比、批边界自然实验、位置检查 → `q1/q1.json` | 离线，约 30 秒 |
| `generate --recipe R --seed S` | 在 v4 dev 的 seed 场景块上生成（v3 可续跑生成，`.local/gpu.lock`） | **GPU**，约 4.5 分钟 |
| `copy-control --seed S` | 复制 v4 b10-joint run 的 `run.json`＋`scenes/` 为 `b10-joint-ctl__sS__dev` | 离线 |
| `subset --variant R --seed S` | 受影响 cue（批次的目标或邻文与对照不同）与所在 5 条窗口；统计未受影响 cue 译文是否逐字相同 | 离线 |
| `judge --variant R --seed S` | 只判子集窗口：候选与对照副本用相同包组成各判一次；退出码 75 = 配额阻塞 | **Claude 配额** |
| `compare --variant R --seeds S… [--label L]` | 受影响 cue 配对差（作品等权、剧集／电影分开、窗口 bootstrap）、分类别、critical／major+、全集护栏、对照重判噪声、成本 → `summaries/` | 离线 |

两次独立实现的合并估计：`q2.pooled(variant, [[主 seed…], [重复 seed…]])`。

## v7（按静默拼包、停顿标记与两级结构）

[v7 研究文档](../../docs/research/2026-10-16-gap-aware-batching-v7.md)（已结题，结论见 §7.7）复用本包：所有命令加 `--round v7`（`python -m experiments.scene_batching_v6 --round v7 <命令>`），根目录改为 `.local/gap-aware-batching-v7/`。切法与标记在 `translation_v3` 的 `Recipe.gap_pack`／`pause_marks`。与 v6 的差别：

- `subset` 列出受影响 cue（批次目标、邻文或停顿标记与对照不同），但保留覆盖场景的**全部**窗口，所以 `judge` 判全集；全集时包组成与 run 无关，每个 seed 的对照副本只判一次，三个变体共用。
- `judge-control --seed S` 在全集上判对照副本；变体用 `judge --variant R --seed S --candidate-only`，不再碰对照的裁判锁。
- `compare --variant R --seeds S… [--against R2] [--label L]`（`v7.py`）：全集配对 Δ（按类别、分指标）、受影响／未受影响（译文相同的未受影响 cue 即噪声底）两部分、critical／major+、对照重判 − v4 原判、非劣判定（每类 CI90 上界 < 0.05、critical ≤ +0.002）、交付与成本（批大小与可见 cue 分布）→ `summaries/v7-R-vs-R2[-L].json`。`--against` 可换成另一个变体做直接比较。
- `pooled --variant R --seed-sets a,b,c/d,e,f [--against R2]`：两组独立 seed 的配对差取均值。
- `simulate`（`sim7.py`，离线）：dev 与产品 `ja.srt`（`.local/quality-exploration-v5/01/out-w0/`）上的间隔分布与各配方的包大小分布 → `sim/sim.json`。

## v9（通用模型在同一接缝下直接翻译）

[v9 研究文档](../../docs/research/2026-10-21-general-model-translation-v9.md)复用本包：`--round v9`，根目录 `.local/general-model-translation-v9/`，三个臂 `dp10-cut`（Hy-MT2 对照，本轮新生成，无对照副本）、`qwen-narrow`、`qwen-wide`（`v9.py`）。

| 命令 | 作用 | 资源 |
| --- | --- | --- |
| `status` | 同上 | 离线 |
| `check-batches [--seed S]` | 三个臂在整个 dev 上按配方算出的每场景目标 ID 序列必须逐字相同；给 seed 时再核对 run 文件 → `checks/` | 离线 |
| `smoke --recipe R` | Qwen 臂在主 seed 块的 5 个包（剧集 3、电影 2，各取一部作品第一个 ≥6 条的包）上生成一次，保存原始回复 → `smoke/R.json` | **GPU** |
| `generate --recipe R --seed S` | Hy 臂走 v3 compat server，Qwen 臂走 `translation_v3/qwen.py`；可续跑 | **GPU** |
| `judge-run --recipe R --seed S` | 该 run 的全集裁判（包组成只取决于 split，三个臂相同）；退出码 75 = 配额阻塞 | **Claude 配额** |
| `compare9 --variant R [--against R2] --seeds S…` | 全集配对 Δ：accuracy、各 accuracy 类别、fluency 及 grammar／unnatural／register、major+、critical（作品等权、剧集／电影分开、窗口 bootstrap），§5 的 L1 关门与 L2 非劣／改善标志，逐作品 Δ，交付与代价（墙钟、载入、token、生成 tok/s、显存峰值、重试、失败）→ `summaries/v9-R-vs-R2.json` | 离线 |

## v10（Q0 线的广度探索）

[v10 研究文档](../../docs/research/2026-10-21-q0-exploration-v10.md)：`--round v10` 跑 v9 的全部命令（`generate`、`smoke`、`check-batches`、`judge-run`、`compare9`、`analyze9`），根目录改为 `.local/q0-exploration-v10/`；对照是 Q0（`qwen-wide`），A1 复现在重复 seed 20261021–23 上新生成 `qwen-wide` 与 `dp10-cut`。`v10.py`：`copy_control` 把 v9 主 seed 的 Q0 译文（`run.json`＋`scenes/`，不含裁判）复制进 v10 根目录供同期重判。`a2.py`（离线）：`similarity` 逐 cue 算与中文参考的 chrF 与 bge-m3 余弦（CPU），Q0 − H0 配对 Δ、与裁判 Δ 符号的一致率 → `A2/similarity.json`；`blind_sheet` 生成盲序人工阅读表 `A2/blind-sheet.md` 与答案键 `A2/blind-key.json`。`asr10.py`（D 阶段）：HF II／III 产品 w0 `ja.srt` 上各臂 `translate-srt` 的输出约定（`D/zh/<arm>/<film>.s<seed>.zh.srt`）、产品专名表转注入表（`name_tables`）、复用 quality_v5 第 02 步的单元与分桶及 `v5-asr-pairwise-v1` 裁判做"候选 vs 对照"配对（`plan`／`judge`／`estimate`：各桶 Δ＝候选−对照惩罚、CI90、偏好、critical／addition／人名错误），整片不一致率（`inconsistency`），产品时间轴的包与邻文分布（`product_timing`）。`brief10.py`（E1，GPU）：每部作品一次 `work-brief-v1` 简报请求（names 同款 server 值），dev 用 dev 场景拼接、产品用 `ja.srt` → `E/briefs-<kind>.json`。`names10.py`（票据 16，GPU）：用产品 names 阶段的 `build_table`（导入、不改）给每部 dev 作品建表 → `E/dev-name-tables.json`，`injection_tables` 转成 `qwen_options.names` 的条目。

## v11（Q0 产品路线的成分验证）

[v11 研究文档](../../docs/research/2026-10-22-q0-product-route-v11.md)：`--round v11` 跑 v9／v10 的命令，根目录 `.local/q0-product-route-v11/`；v10 产物只读复用。`v11.py`：`copy_run`（`copy-run`／`copy-q0`，从 v10 根目录复制译文供同期重判）；**送裁判前先 diff**——dev 上 `identical_cues` 记录两臂逐字相同的 cue（`checks/`），`copy_identical_packets`（`copy-identical`）把对照已判、且 20 条 cue 全部相同的包的判分原样写进候选的裁判目录（`surface: copied-identical`，成本 0，其余包照常 `judge-run`），`compare11`（`compare11`）在配对统计前把相同 cue 的候选行替换为对照行（Δ＝0），并给出人名相关错误（同一替换口径）与两臂的 dev 不一致率 → `summaries/v11-<variant>-vs-<against>.json`；产品侧 `product <plan|judge|estimate|inconsistency|replace|failures>` 把 `asr10` 绑到 `C/` 与 seed 20261054–56，`plan` 用 `skip_identical=True`：相同单元不进计划、写在 `plan.json` 的 `identical`，`estimate`（`asr10.summarize`）按 Δ＝0 计入（`n`／`n_judged`／`n_identical`，均值与计数只算已判单元）。票据 08 的受影响子集：`affected_positions` 在产品时间轴上找出邻文被截断的包的目标 cue 位置，`split_affected` 把单元（任一 `asr_ids` 落在其中即受影响）分成受影响／未受影响两组，`estimate08`（`product estimate08`）对两组分别 `summarize` 并给出受影响组的 mistranslation／addition／omission／terminology 计数 → `C/judge/<name>/estimate08.json`。`asr10.judge` 在 `judge/<name>/.lock` 上持 `ProcessLock`（同一比较的第二个驱动进程直接退出 0、不判；死进程的锁被替换），两条裁判链可以并存。`asr10` 的根目录与 seed 全部可传参（`delivery_failures` 补了 `seeds`），v10 默认不变。配方：`C/root/recipes/seg10.json`＝`qwen-wide`＋`wide_context.silence_gap` 10 s（hash `14fef2f7…`），`q0-names`（与 v10 D 同内容，hash `18fcac59…`）。`names11.py`（票据 02，离线）：`diagnosis` 对 v10 的 `qwen-names-dev` 与 Q0 同 seed 逐 cue 比较人名相关错误与 wrong-referent，列出新增／修好的 cue 及所涉表条目并按规则预分类（`pre_class`），终类由执行者写在 `A/02-classes.json`、`class_summary` 汇总；`table_reference_agreement` 算 dev 表条目与参考中文的一致率与条目性质（对比产品表）；`nstar_tables`／`product_tables` 按 confidence 过滤注入表，`write_nstar_recipes` 写 N\* 配方（`qwen-names-dev-high` `9c444d3c…`、`q0-names-high` `c10e143a…`）。`seg11.py`（票据 03，离线）：`segment_stats` 在产品 `ja.srt` 与 dev 时间轴上对 G＝5／10／20 s 比较 `qwen-wide` 与截断臂每个包的只读邻文（切包断言相同）：受影响包与 cue 占比、平均可见前后邻文、截断点清单（时间、静默、去掉／保留条数、两侧 30 s 内 cue 数）→ `A/03-segment-stats.json`。

## v12（Strata＋Qwen3.8-Flash-Next 对照 Q1）

[v12 研究文档](../../docs/research/2026-11-08-strata-flash-next-v12.md)：`--round v12`，根目录 `.local/strata-flash-next-v12/`，v11 产物只读复用。`v12.py`：`write_recipes`（`v12-recipes`）由 v11 的 Q1 配方文件只换 `model` 写出 F1 `flash-names-high`（dev `60bd457f…`、产品 `D/root/recipes/` `a2075b25…`）与 F2 `flash-names-high-think`（F1＋`thinking` {budget 1024, min_visible 1}，`903d1cad…`），并把 Q1 配方复制过来（hash 仍为 `9c444d3c…`／`c10e143a…`）；`v12-copy-q1` 复制 Q1 的 3 个 dev run（不带判分，供同期重判）与产品 6 份 SRT（`D/zh/q0-names-high/`）。GPU 入口（附着到已启动的 Strata）：`v12-smoke --pass 1|2`（v11 smoke 的 3 个场景整场，seed 20261011，→ `smoke/pass<k>/`）、`generate --recipe flash-names-high --seed S`、`v12-generate-aa`（A/A 重跑 → `runs-aa/`）、产品用 `translation_v3 --root D/root translate-srt`。离线：`v12-smoke-report`（两遍统计、A/A、可行性门 → `smoke/report.json`）、`v12-stats`（首次格式失败率与类型、交付失败、思考输出、限长停止、超 Q1 预算、每包耗时、显存／内存峰值、server log 事件、墙钟 → `checks/stats-<recipe>.json`）、`v12-aa`、`product12 <plan|judge|estimate|inconsistency|failures|stats>`（`asr10` 绑 `D/` 与 seed 20261054–56）；`copy-identical`／`compare11`／`judge-run` 同 v11。只统计计数，不输出译文。

## v13（专名建表换成 Strata＋Flash-Next，对照现行 27B 建表）

[v13 研究文档](../../docs/research/2026-11-08-names-on-strata-v13.md)：`--round v13`，根目录 `.local/names-on-strata-v13/`，v10／v11／v12 与 `.local/name-consistency-product/` 只读复用。`v13.py`：S1 建表配方的变体 `VARIANTS`（v2 为 C–E 的默认 `CANDIDATE`；v3＝v2＋`response_format: json_schema`＋最多 5 次尝试，Strata 的 502 记为失败尝试；v4＝v2＋最多 5 次；`v13-build --variants v3 v4` 在一次 Strata session 里分别建到 `B3/`、`B4/`）。v2 `names-strata-v2`（`v13-s1`：产品 `BUILD` 去掉 llama.cpp 模型资产、`max_tokens` 改 8192＋context 24576（提示预算 15872 不变；v1 的 4096 截断了 Flash-Next 的表，产物留在 `B/`），加 Strata 身份、"不发 `response_format`"、`enable_thinking: false` 与 `count_tokens` 预算检查，单独成 hash，产品 `BUILD_RECIPE_HASH` 不变）；`NamesClient` 是产品 `build_table`（导入、不改）在 Strata 上的 `chat`／`tokenize` 回调（去掉 `response_format`、加 `model`；`/v1/messages/count_tokens` 分段计数，端点不可用时退回不预检、只记 `usage.prompt_tokens`），逐请求只记计数。GPU 入口自己启停 Strata（`serve`：先核对无 `gpu.lock`、无 llama-server、无 Strata launch、可用内存 ≥52 GiB，再用产品 `kototoki.translate.strata.StrataServer` 启动、核对身份与专家区锁进内存、结束 `--stop` 并核实显存释放）：`v13-build`（产品 2 部各两次、dev 15 部各一次 → `B2/`，可行性门 → `B2/gate.json`）、`v13-dev`（T0／T1 × seed 20261011–13）、`v13-product`（`translate-srt` T0／T1 × 2 部 × seed 20261054–56 → `E/`）。离线：`v13-gate`、`v13-quality`（dev 两臂各跑 `names11.table_reference_agreement`，按作品 bootstrap 一致率差与 high 不一致率差、串名（同表异实体同译名）计数，产品写法重合与 A/A → `C/table-quality.json`）、`v13-recipes`（`write_q2`：任意 `name-table` → Q1 规则 → `strata_recipe_data(..., launch="default")`，即 ADR-0017 的已知缺口）、`v13-stats`、`v13-dev-gate`（`compare11` T1 对 T0 与 §4.4 门）、`product13 <plan|judge|estimate|inconsistency|failures|stats|gate>`。`copy-identical`／`compare11`／`judge-run`／`generate` 同 v11。研究侧 `translation_v3/strata.probe` 的默认启动分支改为从服务日志的 `[strata] drafting:` 行判断起草方式（Strata 总会传 `--mtp`，按参数判断会把 DFlash2 认成 MTP，ADR-0019）；v12 分支与各配方 hash 不变。

## 验证

`uv run --locked --offline python -m unittest experiments.scene_batching_v6.test_v6 experiments.scene_batching_v6.test_v7 experiments.scene_batching_v6.test_v9`（v6 离线 14 项：间隔分类、对比统计、已有配方 hash 不变、gap_split 校验与切批规则、随机场景不变量、受影响 cue 判定；v7 13 项：已有配方与 gsnap5 hash 不变、新字段进 hash 与校验、动态规划与暴力枚举一致、硬边界与小包不变量、小组拆分、邻文规则、标记位置与提示／grammar、生成链路发送标记、受影响 cue 计入标记、非劣判定、模拟计数）。真实数据上的端到端运行记录在研究文档 §7、§9。v9 7 项：cue 指标与未交付、L1 关门与 L2 标志、专名错误规则、代价字段、dev 上三臂目标 ID 相同、smoke 包选取。v10（`test_v10`）：旧配方 hash 不变、`qwen_options` 校验与进 hash、v2 保留 v1 规则与 user 消息、ASR／专名／简报渲染、context 覆盖、thinking 只对长包开与 server 参数、A2 一致率与门、ASR 阶段抽样与区间。v11（`test_v11`，14 项）：旧配方 hash 不变、`wide_context.silence_gap` 校验与 `wide-context-v2` 进 hash、截断规则（切包不变、邻文是原邻文的前后缀、可见邻文内无 ≥G 静默、无静默时与 `qwen-wide` 相同、随机场景不变量）、专名表 `targets` 过滤与 v2 表头、产品计划跳过相同单元且 A／B 侧抽签不变、`summarize` 的 Δ＝0 计入、dev 包 id 与裁判规划一致、相同包复制与相同 cue 替换、`scene_stats` 计数、专名诊断辅助函数、受影响位置与单元划分。v12（`test_v12`，3 项；后端在 `translation_v3/test_strata`，10 项）。v13（`test_v13`，12 项）：产品 `BUILD_RECIPE_HASH` 不变、S1 单独成 hash 且提示预算不变；S1 请求体无 `response_format`、`max_tokens` 8192、带 `enable_thinking: false` 与采样原值；解析失败换 seed＋1 重试、只记计数；`count_tokens` 不可用时的退路；开跑前核对；可行性门；一致率／重合／串名计数；27B 表经 `write_q2` 得到 ADR-0017 的两个 Q2 实例 hash（dev `4c3d0f70…`、产品 `86b61ec9…`），旧配方 hash 不变；dev 与产品门：F1／F2 只比 Q1 多换模型（与思考）、运行统计与可行性门、A/A diff；请求体无 grammar、格式失败换 seed 重试、缓存与超预算只记录、思考包的预算、失败包只留自己的 cue、附着核对与资源／日志事件记录。
