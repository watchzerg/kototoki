# 08 第六轮：换提示示例、写法层一致规则、日文写法形状过滤，再评合并统计

Status: resolved
Type: research
Blocked by: 07

## 范围

用户 2026-10-19 裁定：缺姓算有害，第五轮默认不变；开第六轮。[第五轮](../../../docs/research/2026-10-19-name-consistency-round5.md)剩余有害行来自三处：提示污染（EVA 示例让两个 seed 都给 `シンジ=真嗣`）、写法并集带进单表错写法（`増健=慎二`、`白=士郎` 1 行）、句子级写法拆散锚定 cue（HF III w0 少 9 行）。三件事：

1. **提示 v6**：示例作品与人名改为虚构的（不与任何真实作品、真实角色同名或近音），仍覆盖同样的 ASR 误识类型与"相近名字不合并"的规则；其余规则不动。两个 seed（20261019、20261119）重建四部 no-think 表（GPU，每 seed 约 4 分钟）。
2. **日文写法形状过滤**（`build_table.py` normalize，`--renormalize` 同样生效）：写法 ja 含空白（汉字之间的空白去掉后合法则保留）、标点、数字、ASCII，或在含汉字／片假名的写法里夹有平假名（允许的敬称后缀 さん／くん／ちゃん／さま 与前缀 お 除外）则丢弃，记 `meta.dropped_ja_shape`；全平假名写法（しろ）保留；entity_ja 不合格则换成第一个合格写法的日文，没有则整条丢。
3. **写法层一致规则**（`merge_tables.py --mode zh-agree --form-agree`）：只在一张表里出现的写法，其 zh 必须已出现在对方表同一实体的写法 zh 或实体 zh 里才保留（拦 `増健=慎二`、`エミア・キリツグ=卫宫切嗣`，放过 `白=士郎`、`素郎=士郎`），记 `meta.dropped_form_unverified`。

评估：四部 × {old_default, v6A, v6B, agree3（zh-agree＋写法回退＋写法层一致）, agree3_pool, 以及 agree3 不开写法层一致的对照}；覆盖率、Opus 逐行评审新增行、盲序成对判分新增 cue；核对 `シンジ=真嗣` 是否消失、句子级写法是否清零。

## 完成标准

- 一致表有害率（缺姓算有害）≤ old_default（2.5%）且 good 不明显下降；agree3_pool ≤4% 则采纳为默认；否则默认不变。
- 第六轮报告入 `docs/research/`，登记索引。

## 文件所有权

`build_table.py`、`test_build_table.py`（建表 agent）；`merge_tables.py`、`test_merge_tables.py`（合并 agent）；GPU 建表、评估驱动、报告与票据（主 agent）。

## Answer

报告：[第六轮](../../../docs/research/2026-10-19-name-consistency-round6.md)。102 项测试过；表在 `.local/name-consistency/14-round6-tables/`，矩阵在 `15-round6/`。

- 提示 v6（虚构示例）：退步。`シンジ=真嗣` 消失，但写法更常挂错实体（イリア→凛 12 行、セイマー→士郎 3 行）、输出罗马字，两个 seed 一起错的 `シンジ=时臣`、`増健=雁夜` 新出现；A 6.5%、B 16.3%、一致表 7.1%。
- 日文写法形状过滤：有效无害，HF III w0 第五轮丢的 9 行回来。保留。
- 写法层一致规则：严格版、子串版都没拦下任何有害行；严格版丢 3 行 good。
- 完成标准未达到（agree3s 7.1%、agree3s_pool 5.5%），默认不变。另发现跨表配对太松（伊莉雅配上凛）是 good 下降主因。
