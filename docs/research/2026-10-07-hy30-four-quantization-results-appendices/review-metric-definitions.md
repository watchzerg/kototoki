# 复评分变化的计数口径

| 候选 | 任一字段变化（含空分） | 两端均有数字的任一字段变化 | 语义数值变化/语义可比窗 | evaluation 条件标志 |
| --- | --- | --- | --- | --- |
| i1-Q3_K_M | 51 | 51 | 42/1199 | 51 |
| i1-Q3_K_L | 79 | 75 | 60/1195 | 77 |
| APEX-I-Compact | 60 | 59 | 44/1198 | 59 |
| Q3_K_M 基线 | 65 | 64 | 47/1197 | 64 |

前两列逐字段比较 semantic／naturalness；第一列还计入 null 与数字之间的变化。第三列只比较两端均有语义数字的窗口。末列是 chosen／reviewed 条件下的流程标志；没有 chosen 的未决裁决不一定设置该标志。这四列不能相互替代或相加。

i1-Q3_K_L 的四个额外窗口分别为：两项分数 2→null、语义 null→2、语义保持 null 而自然度 2→null、语义 null→3，因此为 79／75；其中两个未决窗口没有 chosen，流程标志计为 77。旧回归基线的 5／4 来自一窗语义 null→4，旧集仍单独呈现。

[逐窗数值与窗口 ID 证据](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-expanded-quality-audit-v1/metric-definition-reconciliation-v1.json>)；此处只转写既有元数据核对，不新增评分。
