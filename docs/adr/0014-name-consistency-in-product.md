# ADR-0014：专名一致性——研究线已结题，冻结配置已移植进产品 `names` 阶段

状态：已接受。合并整理于 2026-11-08（并入 ADR-0013 的有效条款；历次变更见[决定索引·演进链](INDEX.md#演进链)，原文见 Git 历史）。  
范围：专名一致性（日文侧建专名表＋生成后程序替换）的研究线状态、冻结的最佳配置，以及它在产品包 `kototoki/` 中的 `names` 阶段与发布时替换。

## 决定

1. **研究线关闭。** 不再开新轮次，不再提议"再调一轮规则"类的改动；agent 不得自行重启。重开只由用户明确要求，且只值得做两个未测方向之一：① 一次性音译的模糊匹配（按读音或编辑距离；目标士郎覆盖 ≥60% 且有害率不涨，做不到就关）；② 更好的"表可人工校对"形态。两者都不由本 ADR 授权。
2. **最佳已知配置冻结，产品照抄、不调参。** 任何参数改动都是新配方，须另有决定。
   - 建表：no-think（Qwen 官方 non-thinking 采样，`--reasoning off`）、提示 `build-table-prompt-v5`、seed 20261019；程序兜底全开（zh 形状过滤、称呼词黑名单、evidence<3 的 person 降为 medium、日文写法形状过滤）。
   - 替换：规则一（落点必须覆盖整个名字，否则不动）＋孤立单字；`--name-check`、`--pool-by-target`、`--bigram-isolation`、`--iterate`、`--weak-name-check`、`--min-confidence`、`merge_tables.py` 的各种合并开关都不用、不进产品。
3. **阶段位置：`ja-cues` 与 `translate` 之间。** 模型是 `unsloth/Qwen3.8-27B-GGUF` 的 `Qwen3.8-27B-UD-IQ3_S.gguf`，经 llama-server 加载，每部影片把整份 `ja.srt`（剥时间轴）一次送入，按 JSON schema 取回专名表，产物 `name-table.json`。两个 llama-server 模型各占 12–15 GB，必须串行：先建表再翻译，translate 仍是最后一个 GPU 阶段，发布紧随其后。替换不是阶段，是发布时由编排器调用的纯函数，只写审计文件 `names-apply.json`。
4. **建表终态失败写空表，影片照常发布。** 提示超预算、回复两次尝试仍不合格时，写 `build.status` 为 `too_long`／`failed` 的空表，记 WARNING，翻译与发布照常。server 起不来、OOM、传输失败是该影片 `names` 阶段的文件级失败。替换阶段异常使该影片 `publish` 失败（异常只能是表损坏，用户应当看到错误）。
5. **`[names] enabled` 默认 `true`。** 取 `false` 时阶段链跳过 names；从 `true` 改 `false` 同样触发重新发布（去掉替换）。
6. **`published.json.sources` 含 `names`（表的身份）与 `names_apply`（审计产物的身份）两个键。** 表或审计产物的身份变化会使已发布结果过期，下次整批运行重新发布，不重译、不起 Hy-MT2。用户改过且非 `force` 的最终文件照常被发布前置判定挡住。
7. **表可人工校对。** 表是 `.work/<id>/` 里的产物：用户改 `name-table.json` 的 `entries`（改错名、删条目）后重跑，只重做替换与发布。机制是 `is_current` 只比较 `identity` 块，手改不触发重建；文件 sha256 变化使 `names_apply` 身份变化，`published.json` 不再匹配。重建（改 `ja.srt`、改 `[names] seed`、`BUILD` 配方变化）会覆盖手改，不做保护。
8. **隐私。** 专名表条目是转写内容，只在工作目录，不进日志，日志只记计数。
9. **研究目录继续冻结。** `experiments/name_consistency/`（101 项离线测试）只读，产品只复制、不导入；冻结证据（六份报告、`.local/name-consistency/` 的表与矩阵、`.scratch/name-consistency/` 的票据）需要改动时新增带版本的文件。
10. **与翻译基线的关系。** H0 链在发布时跑这套替换（配方见 [ADR-0015](0015-two-translation-baselines.md)）；Q 线直接用 `names` 建表注入、不做替换（[ADR-0017](0017-q2-strata-default-launch-baseline.md)）。[ADR-0008](0008-no-multi-translation-selection.md) 不涉及：建表每部只一次请求，不是翻译多次再挑选。

## 依据

- 研究期（冻结基准为四张 v4 提示 no-think 表，HF II／III × w0／x0）：合计 161 处改动，逐行判 good 89%、有害 2.5%；盲序成对判分偏好替换后 88／平局 20／偏好原译 3；整片通读略好读、无新错、覆盖不全。六轮报告见[调研索引](../research/INDEX.md#翻译后审校与人名专名一致性2026-10-19已结题adr-0013)。
- 六轮把规则层改动都试过，第三轮之后默认未再动：规则一 82%／4%，孤立单字 89%／2.5%；规则二（中文名核对）、二字组（有害 20%）、迭代、交集、两次建表取一致、`--pool-by-target`、虚构示例提示 v6 均无净收益。
- 剩余误差在规则层之外：次要角色的表内错名（27B IQ3 的知识错）、一次性音译覆盖不到、边角残字。
- 提示 v5 与 v4 的差别落在采样噪声内；v5 样本的额外有害行（爸爸→时臣）已由称呼词黑名单堵住。
- 没有 MQM 抽样与整片人工观感评估；用户知悉后接受以上证据水平作为进产品依据。
- 产品路径验收（[验收记录](../research/acceptance/2026-10-20-name-consistency-product.md)）：HF II／III w0 整批重跑退出码 0，新表第一次尝试即 `ok`（20／15 条，建表 49.5／40.5 s，整机显存峰值 13445 MiB），替换 55／32 个 cue；`apply_table measure` 不一致率 0.151 → 0.135、0.121 → 0.094；研究脚本 `apply_table` 默认参数在产品表上的输出与产品发布的 `zh.srt` 逐字节相同。
- 建表每部约 1 分钟 GPU。

## 约束与未关闭项

- 验收判据 ④（用户抽看 `names-apply.json` 的 `changes`）尚未做；判据 ①②③ 已满足。
- `ManagedServer` 由翻译（Hy-MT2）与建表（Qwen3.8）共用，位于中间层 `kototoki/llama_server.py`（见[模块边界](../architecture/module-boundaries.md#产品包的责任边界)）；翻译 `Session` 不共享，names 每部只一个请求，用自写的最小 session。
- `assets.toml` 登记 Qwen3.8-27B-UD-IQ3_S（12.0 GB）；`kototoki.toml` 的 `[names]` 节驱动阶段。
- 不做：注入提示版、跨文件（多集）共享表、UI。
