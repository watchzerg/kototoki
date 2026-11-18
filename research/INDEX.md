# 研究索引

状态：current（研究轮次的登记页与规则入口）

## 规则

规则的权威是 [ADR-0031](../docs/adr/0031-research-layout-and-lightweight-records.md)，这里只列执行要点：

- **一轮一目录（R1）**：研究的计划、代码、结论放在 `research/<YYYY-MM>-<slug>/`，立项时在下面的[轮次登记](#轮次登记)加一行。产品验收记录放 [acceptance/](acceptance/)，一次一篇。
- **必填项（R2）**：README 按 [TEMPLATE.md](TEMPLATE.md) 填写；正文约 150 行以内。
- **不写进记录（R3）**：文件或样本的哈希（git commit SHA 除外）、本机绝对路径、逐窗或逐条明细与大段日志、字幕或转写原文（短例外）、执行台账与接跑步骤。
- **冻结靠 git（R4）**：结题把状态写成 `concluded`／`stopped`；修错、修链接、精简随时可以做。原始材料从归档 tag `archive/2026-11-18-pre-research-restructure` 或 git 历史取。代码不对文档做 sha256 自检。
- **依赖方向（R5）**：产品永不导入 `research/`；研究可以导入产品。研究数据经仓库根 `data.toml`（逻辑名 → 相对数据根的路径）与环境变量 `KOTOTOKI_DATA` 定位，第一个需要数据的新轮次建立该文件。跨轮复用的工具第二个使用者出现时才建 `research/_lib/`。
- **规则移植（R6）**：研究结论进产品后，产品实现是唯一权威，后续研究直接调用产品实现；需要钉住的取值在 `tests/core` 里以字面量钉。
- 采纳的结论写成 ADR（[记录新决定](../docs/adr/INDEX.md#记录新决定)）；现行规则看 [CURRENT.md](../docs/adr/CURRENT.md)，不从轮次记录推断。

## 研究方法约束

- 翻译只有一条基线 **Q3**，新测试以它为对照；引用 Q2、Q1、Q0、F1、H0 时写明（[CURRENT·翻译基线 Q3](../docs/adr/CURRENT.md#翻译基线-q3)）。新的翻译对比、裁判与统计口径按[翻译评估方法](../docs/agents/translation-evaluation.md)。
- 不自动选用"翻译多次再挑选"类方法（[ADR-0008](../docs/adr/0008-no-multi-translation-selection.md)）。
- 已结题的研究线不重开，重开只由用户明确要求；专名一致性研究线不提议新轮次（[CURRENT·专名](../docs/adr/CURRENT.md#专名)）。
- 确认集一经开封不再用于确认：v3、v4、v5 的确认集已开封，新的确认用全新隔离的集合。
- 翻译流程第二轮（v2）已停止，作业不恢复，只取 v1／v2 的教训作先验。

## 轮次登记

状态取值：`active`、`concluded`（已结题）、`stopped`（中止）。一句话只写去向，数字看各轮 README。

| 目录 | 时间 | 状态 | 一句话 |
| --- | --- | --- | --- |
