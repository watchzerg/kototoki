# 07 第五轮：两次建表取一致、称呼词黑名单、再评合并统计

Status: resolved
Type: research
Blocked by: 06

## 范围

用户 2026-10-19 裁定。[第四轮](../../../docs/research/2026-10-19-name-consistency-round4.md)发现错名是采样级不稳定（v4 与 v5 两次建表错的条目不同，都标 high），提示侧校准无效。三件事：

1. **两次建表取一致**：同一提示（v5）、同一模型，不同 seed 建两次；`merge_tables.py` 新模式 `zh-agree`：两张表里能对上的实体（任一写法的日文规范化后相同，或 entity_ja 相同）中文名 zh 一致才保留，写法取并集（同一日文两边 zh 不同则丢该写法），`zh_variants` 并集、confidence 取低；只在一张表里出现的实体丢弃并记录。A = 现有 v5 表（seed 20261019，形状过滤后 `-v5r`），B = 新 seed 20261119（GPU，四部约 4 分钟）。
2. **称呼词程序黑名单**：`build_table.py` normalize 阶段丢掉写法日文命中黑名单的 form（父さん、父様、お父さん、母さん、お母さん、姉さん、お姉ちゃん、兄さん、お兄ちゃん、先輩、先生、あの人、お主 等，含去掉 お／さん 后的词干匹配），实体没有剩余写法则整条丢，记 `meta.dropped_honorific`；`--renormalize` 同样生效。
3. **再评 `--pool-by-target`**：在一致表上开与不开各一档。

评估：四部 × {old_default（第三轮默认，参照）, A（v5r 默认）, B（新 seed 默认）, agree, agree_pool}；覆盖率、Opus 逐行评审新增行、盲序成对判分新增 cue。

## 完成标准

- 一致表的有害率 ≤ old_default（2.5%）且 good 绝对数不明显下降；给出因"只在一张表出现"而丢弃的实体数与由此损失的覆盖。
- agree_pool 有害率 ≤4% 则采纳为默认；否则默认不变。
- 第五轮报告入 `docs/research/`，登记索引。

## 文件所有权

`build_table.py`、`test_build_table.py`（建表 agent）；`merge_tables.py`、`test_merge_tables.py`（替换 agent）；GPU 建表、评估驱动、报告与票据（主 agent）。

## Answer

报告：[第五轮](../../../docs/research/2026-10-19-name-consistency-round5.md)。78 项测试过；表在 `.local/name-consistency/12-round5-tables/`（A `-s20261019`、B `-s20261119`、`agree`、`agree2`），矩阵在 `13-round5/`。

- 取一致：zh 不一致而丢的实体全是至少一边错的，B 的 13 行有害降到 7 行；清不掉提示污染（`シンジ=真嗣` 两个 seed 都有）、写法并集带进的单表错写法（`増健=慎二`、`白=士郎` 1 行）与句子级写法（HF III w0 少 9 行正确改动）。写法回退（`--forms-fallback`）保住 `桜=樱`，覆盖 0.32 → 0.54，不添改动；修了回退实体隐含写法的 bug。
- 称呼词黑名单：丢 父さん／父様／姉さん／先輩，爸爸→时臣 消失，无误丢。
- 完成标准：严格口径（缺姓算有害）两条都不达标（agree2 4.3% > 2.5%，agree2_pool 4.7% > 4%）；第一轮口径（缺姓算 good）两条都达标（2.5%＝2.5% 且 good 146 > 143；3.2% ≤ 4%）。默认维持第三轮配置，口径待用户裁定。
