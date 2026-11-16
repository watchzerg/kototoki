# 08 单字与语气词 cue 的翻译失败

Status: needs-triage
Type: task
Blocked by: —

## 现象

全批翻译 228/228 完成，单批失败尝试共 121 次、分布在 73 个文件，全部是格式类，没有一次是模型拒绝翻译（对全部 39283 个回复做过拒绝措辞扫描）：

| 分类 | 次数 |
| --- | --- |
| 某 cue 译文为空串（`empty_value`） | 82 |
| ID 集合不符（缺失/多出） | 25 |
| 回复不是 JSON 或被截断 | 12 |
| 其他 | 2 |

- `empty_value` 几乎全是单字或单假名 cue（例：「い」「た」「ら」「服」），模型给了空串。校验 `Empty or invalid translation`（`kototoki/translate/recipes.py` 约 165 行）判整批失败 → 换 seed 重试 → 再失败则拆批（本批拆了 3 次）。
- 最终只剩 1 个文件的 2 条 cue 回退为日文：「ああああああ」，模型丢掉了该 ID。

## 原因

- 单字 cue 多是断句切碎的半个词或语气词，单独看没有可译内容，模型倾向给空。
- 校验对"空译文"零容忍，一个 cue 为空就让整批（约 6–10 个 cue）重来。

## 影响

- 质量影响很小（最终几乎全部译出），主要是多余的请求和耗时；拆批路径也更复杂。

## 候选方向（待讨论）

- 对纯语气词、单假名或极短 cue：允许空译文时原样保留日文或沿用某种规则，不判失败。
- 或在送翻译前把这类 cue 排除、直接透传。
- 或只让该 cue 失败、其余 cue 照收（局部回退，而非整批重试）。
- **涉及翻译基线 Q3 的行为**，方向需用户决定；任何改动都要按[翻译评估方法](../../../docs/agents/translation-evaluation.md)评估，不得引入"翻译多次再挑选"（ADR-0008）。

## 证据

- `.local/run-notes/translate-rejects.tsv`（每次失败尝试的分类、cue、回复与 exchange 路径；不进 Git）。
- 汇总脚本 `.local/run-notes/translate_rejects.py`（注意：它没覆盖拆批节点，拆批的 3 次要看 `batches.jsonl` 的 `degrade.nodes`）。
- 台账 §D1 与"第 3 次运行结果"。

## Comments
