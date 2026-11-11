# 04 第二轮：统计层落点"整个名字"规则与人物中文名校验

Status: resolved
Type: research
Blocked by: 03

## 范围

用户 2026-10-19 裁定开第二轮，针对[第一轮报告](../../../docs/research/2026-10-19-name-consistency-offline-results.md) §3.4 的两类有害改动：

1. **统计层落点必须是整个名字，否则不动。** 候选在嵌套家族里按锚定 cue 内出现次数最高者取基底（允许单字译法），扩展只接受出现次数不低于基底一半的超串；最终落点两侧若紧邻不属于"允许边界"集合的汉字，视为没覆盖完整名字，不替换，记 `unresolved: boundary`。
2. **人物中文名校验。** 每个写法的目标 `zh` 要有译文证据：在该实体任一写法锚定的 cue 里出现过、或与译者多数写法是近形变体（编辑距离 ≤1 或共享 ≥50% 字符）；`kind=class` 且目标为 ASCII（Saber／Rider）豁免。无证据的写法跳过，记 `unresolved: unverified_name`，summary 记录核验来源。

表复用 `03-four-v2` 的八张（think／no-think 各四），不重建，隔离脚本改动的效果。评审沿用第一轮六档，并补整片抽查：每部取一段连续 cue 对照替换前后。

## 完成标准

- 有害率目标 ≤5%，同时 good 的绝对数不明显下降；给出因两条规则各自放弃的处数。
- 整片抽查记录；第二轮报告入 `docs/research/` 并登记。

## 文件所有权

`experiments/name_consistency/apply_table.py`、`test_apply_table.py`（子 agent）；报告与票据（主 agent）。

## Answer

报告：[第二轮](../../../docs/research/2026-10-19-name-consistency-round2.md)。脚本 v7（38 项测试过），八张表 × {nocheck, check} 输出在 `.local/name-consistency/04-round2/`，评审在其 `review/`。

- 规则一：有害率 think 17% → 8%、no-think 15% → 4%，拦下 91／63 处；少掉的 132 行里有害 49、good 76。残字只剩"爱爱因兹贝伦"、"我士郎"各 1 处，新代价是相邻句"半改"。
- 规则二：拦下 152／165 处 cue，被拦写法 103 个里 73 个是正确名字；从改动里减掉 26／13 行，其中有害只 5／3 行。译者整片从未写对 卫宫士郎／切嗣／间桐／爱因兹贝伦，证据必然为空；拦不住 シンジ=士郎。不建议按现形式采用。
- 完成标准：有害 ≤5% 在 no-think nocheck（4%）与两组 check 档达到，但 good 绝对数都明显下降（no-think 120 → 91），双目标未同时满足。
- 未查明：think 比第一轮少掉的 12 行（影→黑影、骑士→骑阶）未记录在 unresolved。
