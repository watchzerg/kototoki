# ADR-0014：专名一致性（建表＋生成后替换）进产品，冻结配置原样移植

状态：已接受（2026-10-19）。依据见下文"证据与用户裁定"：第一轮 §5 第 3 条的进产品条件（MQM 抽样、整片人工观感）**没有补做**，用户 2026-10-19 知悉后仍裁定进产品。  
日期：2026-10-19（提出与接受同日）。  
关系：**只替代 [ADR-0013](0013-name-consistency-closed.md) 的第 3 条（"不进产品"）。** 第 1 条（研究线关闭、不开新轮次）与第 2 条（最佳已知配置冻结）继续有效：产品实现只照抄冻结配置，不调参。翻译基线与产品配方（[ADR-0010](0010-dp10-cut-translation-flow-baseline.md)、[ADR-0011](0011-dp10-cut-product-recipe.md)）不变；[ADR-0008](0008-no-multi-translation-selection.md) 不涉及（建表每部只一次请求，不是翻译多次再挑选）。  
范围：产品包 `kototoki/` 新增 `names` 阶段（GPU 建表）与发布时的 CPU 替换。不做：注入提示版、模糊匹配、合并多张表、`--pool-by-target` 等任何非默认开关、跨文件（多集）共享表、UI；`experiments/name_consistency/` 不改、不被产品导入。

## 决定

用户 2026-10-19 裁定直接集成到产品代码，验收只看总体正向，其余按推荐：

1. **照抄冻结配置，不调参。** 建表：no-think（Qwen 官方 non-thinking 采样，`--reasoning off`）、提示 v5、seed 20261019、程序兜底全开（zh 形状、称呼词黑名单、evidence<3 的 person 降级、日文写法形状）；替换：`apply_table.py` 默认参数（规则一＋孤立单字），其余开关不进产品。任何参数改动都是新配方，须另有决定。
2. **阶段位置：`ja-cues` 与 `translate` 之间。** 模型是 `unsloth/Qwen3.8-27B-GGUF` 的 `Qwen3.8-27B-UD-IQ3_S.gguf`，经 llama-server 加载，每部影片把整份 `ja.srt`（剥时间轴）一次送入、按 JSON schema 取回专名表，产物 `name-table.json`。两个 llama-server 模型各占 12–15 GB，必须串行；先建表再翻译，translate 仍是最后一个 GPU 阶段，发布紧随其后。替换不是阶段，是发布时由编排器调用的纯函数，只写审计文件 `names-apply.json`。
3. **建表终态失败写空表，影片照常发布。** 提示超预算、回复两次尝试仍不合格时，写 `build.status` 为 `too_long`／`failed` 的空表，记 WARNING，翻译与发布照常；表是观感优化，不该让整部影片没有字幕。server 起不来、OOM、传输失败则是该影片 `names` 阶段的文件级失败。替换阶段异常使该影片 `publish` 失败（异常只能是表损坏，用户应当看到错误）。
4. **`[names] enabled` 默认 `true`。** 取 `false` 时阶段链跳过 names，行为与本决定之前完全相同；从 `true` 改 `false` 同样触发重新发布（去掉替换）。
5. **已交付影片下次整批运行建表并重新发布，不重译。** `published.json.sources` 新增 `names`（表的身份）与 `names_apply`（审计产物的身份）两个键，旧发布因此过期；翻译身份不变，不起 Hy-MT2。每部约 1 分钟 GPU。不迁移、不加兼容开关；用户改过且非 `force` 的最终文件照常被发布前置判定挡住。用户已接受这一代价（与 ADR-0011 换配方同类）。
6. **"表可人工校对"形态（ADR-0013"后果与后续"的方向 ②）。** 表是 `.work/<id>/` 里的产物：用户改 `name-table.json` 的 `entries`（改错名、删条目）后重跑，只重做替换与发布。机制是 `is_current` 只比较 `identity` 块，手改不触发重建；文件 sha256 变化使 `names_apply` 身份变化，`published.json` 不再匹配。无额外代码。重建（改 `ja.srt`、改 `[names] seed`、`BUILD` 配方变化）会覆盖手改，不做保护。
7. **验收只看总体正向，不做 Opus 评审、不设比例线。** 四条判据（两部整片产品路径，GPU 作业另行批准）：① 退出码 0，两部表 `build.status == ok`；② 用研究脚本 `apply_table measure`（CPU）算替换前后不一致率，两部都下降；③ 等价校验：对产品写出的 `name-table.json` 用研究脚本 `apply_table`（默认参数）跑同一份替换前 `zh.srt`，输出与产品发布的 `zh.srt` 逐字节相同；④ 用户抽看 `names-apply.json` 的 `changes`。

## 证据与用户裁定

证据水平如实记录，全部来自研究期（冻结基准为第一轮的四张 v4 提示 no-think 表，不是产品将用的 v5 新表）：

- 四部（HF II／III × w0／x0）合计 **161 处改动**，Opus 逐行判 good **89%**、有害 **2.5%**。
- 盲序成对判分：偏好替换后 **88**／平局 **20**／偏好原译 **3**。
- 四部整片通读：略好读、无新错、覆盖不全。
- **没有 MQM 抽样。** 逐行与成对判分都是研究期方法，不是翻译质量的 MQM 评分。
- 提示 v5 与 v4 的差别落在采样噪声内；v5 样本的额外有害行（爸爸→时臣）已由称呼词黑名单堵住（[ADR-0013](0013-name-consistency-closed.md#决定)，各轮报告见[调研索引](../research/INDEX.md#翻译后审校与人名专名一致性2026-10-19已结题adr-0013)）。
- 剩余误差来自规则层之外：表里的错名（27B IQ3 对次要角色的知识错）、一次性音译覆盖不到、边角残字。产品里它们仍会存在，只是靠"表可人工校对"提供出口。

用户裁定：**第一轮 §5 第 3 条的进产品条件（补 MQM 抽样与整片人工观感）没有补做，用户接受以上证据水平作为进产品的依据。** 这是用户的权限；本 ADR 的作用是把它留痕，并保证产品与冻结配置一致。

产品路径数字（票据 08，2026-10-20，[验收记录](../research/acceptance/2026-10-20-name-consistency-product.md)）：HF II／III w0 整批重跑退出码 0，STT 与翻译按身份跳过；产品用 v5 提示新建的两张表第一次尝试即 `ok`（20／15 条，建表 49.5／40.5 s，整机显存峰值 13445 MiB），替换 55／32 个 cue（全部统计层）；`apply_table measure` 不一致率 0.151 → 0.135、0.121 → 0.094；研究脚本 `apply_table` 默认参数在产品表上的输出与产品发布的 `zh.srt` 逐字节相同（判据 ①②③ 满足）。`changes` 抽看（判据 ④）：待用户。

## 不采纳的替代

- **不进产品、停在研究 demo**（ADR-0013 第 3 条原决定）：用户已另行裁定。
- **产品里调参或补规则**（再开一轮、模糊匹配、`--pool-by-target`、注入提示版）：违反 ADR-0013 第 1、2 条；预期收益不超过冻结默认。
- **失败即整部影片失败**：为观感优化牺牲字幕交付，与翻译"单条仍失败保留日文"的精神相反。
- **names 排在 translate 之后**：translate 不再是最后一个 GPU 阶段，发布前多一次 GPU 往返。
- **names 放进 translate 阶段内部**：两个模型、两个 server、两套身份，混在一起使 `needs_model` 与重跑形态都变复杂。

## 后果与后续

- **共享 llama-server 模块出现。** `ManagedServer` 从此有第二个使用者（翻译 Hy-MT2、建表 Qwen3.8），按[模块边界](../architecture/module-boundaries.md#产品包的责任边界)"第二个使用者出现再抽接缝"的规则，新增 `kototoki/llama_server.py`（中间层）；翻译 `Session` 不共享，names 每部只一个请求，自写最小 session。
- **新模型与新阶段**：`assets.toml` 登记 Qwen3.8-27B-UD-IQ3_S（12.0 GB）；`kototoki.toml` 增 `[names]` 节；`published.json.sources` 与 `STAGE_ARTIFACTS` 加项。
- **研究目录继续冻结。** `experiments/name_consistency/` 的代码、报告与表保持只读，产品只复制、不导入；该目录 README 状态行改为"已移植进产品，本目录冻结"。移植正确性以验收的等价校验（判据 ③）为证据。
- **隐私**：专名表条目是转写内容，只在工作目录，不进日志，日志只记计数。
- **产品路径验收已补入证据**：票据 08 的数字已写入上文“证据与用户裁定”一节，完整记录见[验收记录](../research/acceptance/2026-10-20-name-consistency-product.md)；判据 ④（用户抽看 `names-apply.json` 的 `changes`）仍待用户。
- 若之后要提高精度，仍只剩 ADR-0013 列的两条路（模糊匹配、人工校对的更好形态），须用户明确要求，不由本 ADR 授权。
