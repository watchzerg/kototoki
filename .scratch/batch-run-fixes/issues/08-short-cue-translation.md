# 08 单字与语气词 cue 的翻译失败

Status: resolved
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

## 方案（2026-11-17 用户裁定）

原则：**成败按条判，只重试没解决的条。** 不考虑历史 ADR 条款与已翻译影片的兼容（旧 run 目录因配方 hash 变化失效，重跑即重译）。

核对结论（定方案的依据）：82 次空值全在第 1 次尝试，换 seed 后几乎都过，只有 SSNI-282 b0138 两次皆空而拆批；空值没有造成任何回退（AP-739 的 2 条回退是 ID 缺失）。空值 cue 多是上一句的碎尾（「した」「でした」「うございました」），但也有实义台词（「何でしょうか?」「を大切にしていきたいなと思ってます」），因此**空串不当合法答案直接放行**，而是记为未解决、单独再问。

### 规则

一个**节点**是场景内连续的一段待译 cue（`batching.Batch`），初始节点即切包产出的批次；每个节点最多 2 次尝试（seed、seed＋1），子节点 seed 从原 seed 重新开始（同现行降级）。

| 回复 | 处理 |
| --- | --- |
| 结构失败：截断（`finish_reason == length`）、HTTP 超出 context、非 JSON、不是恰好一个 `translations` 对象 | 该次尝试失败 |
| 结构合法 | 按条判：值为非空字符串且不含空行的 cue **收下**；缺失、空串、非字符串、含空行的 cue 记为**未解决**；多出的 ID 忽略（只记数） |

- 某次尝试收下至少 1 条：本节点结束；未解决的 cue 按场景顺序切成**最大连续段**，每段成为一个子节点（按 `batching.neighbours` 取只读邻文）。
- 某次尝试结构失败，或结构合法但一条都没收下：计为失败，用下一个 seed；2 次都失败时，节点多于 1 条则**对半拆**（同现行 `a`／`b` 规则，奇数前半多 1），只有 1 条则该 cue **不出中文**。
- 每个子节点必然比父节点小，过程必然终止；只做按条取第一个合格译文，不比较不同尝试，不属于 ADR-0008 的"翻译多次再挑选"。
- 正常一次通过的批次请求体不变（与研究侧逐字节相同，`just test-equivalence` 照旧钉住）。

### 未翻译的 cue

- 译文映射里值为 `null`（Python `None`），表示"该 cue 没有中文"；空串仍然非法。覆盖校验照旧要求 ID 精确覆盖。
- 合并时这类 cue 只输出日文一行（不再把日文抄进中文行）；`srt.validate_translations` 允许 `None`，仍拒绝空串与空行。
- `report.json`、`batches.jsonl`、运行日志与 `[summary]` 的"回退"改称并统计为**未翻译 cue**（ID、原因、尝试次数）；原因取该 cue 最后一次未解决的类别（`missing`／`empty`／`blank_line`／结构失败的 `error_kind`）。多出 ID 的次数只进记录。

### 改动范围

- `kototoki/translate/recipes.py`：`parse_translation` 拆成"结构校验（抛错）"与"按条判（返回收下的译文与未解决 ID＋原因）"；配方名 **`q3-translate-v1`**（用户裁定），`RECIPE` 的 `validation`、`overflow` 换成新规则的显式描述，hash 随之变；模块 docstring 改写。
- `kototoki/translate/degrade.py`：10→5→1 拆分树换成上面的节点规则（文件名可随职责改名，由实现者定，同步模块页）；续跑日志（`degrade.jsonl`）按新节点结构，旧 run 目录不兼容。
- `kototoki/translate/generate.py`：单次尝试的接受／失败判定、run 目录名、报告与日志行；`kototoki/merge.py`、`kototoki/srt.py`、`kototoki/job.py`（`fallback_cues` 计数与 `published.json` 的 `translate_fallback_cues` 字段改名为未翻译计数）。
- 决定记录：新 ADR-0029 取代 ADR-0019 第 4 点（降级）与第 5 点的配方名、hash；CURRENT.md"产品翻译"节、决定索引、README、`kototoki/strata.py` 注释中的配方名同步。Q3 基线本身（研究侧规则）不变。
- 文档：先改模块页 `docs/architecture/modules/translation-subsystem.md`（失败语义、产物字段）与模块边界（如 `translations` 值类型变化跨模块），再改技术设计 `docs/specs/bilingual-subtitle-pipeline.md` 对应节；其余引用 `q2-degrade-v1` 的现行文档（`docs/development/workflow.md`、`technology-stack.md`、`strata-session.md`、`docs/testing/translation-model-evaluation.md`、`docs/pending-decisions.md`）逐个核对。冻结文档（研究报告、验收、plans、旧 ADR 正文）不改。
- 测试：按条收下、空串／缺失／空行进子节点、多出 ID 忽略、零收下计失败、两次结构失败对半拆、单条两次失败不出中文、合并只输出日文一行、`None` 与空串的区分、续跑；更新钉 hash 的测试（`tests/core/test_translate_recipes.py` 等）。
- 不做翻译评估（只改失败路径，正常请求体不变）；不跑 GPU 验证；`just test`、`just test-equivalence` 通过即可。

## 结果（2026-11-17）

- 实现：`recipes.parse_translation` 分成结构校验（抛错）与按条判（返回 `Parsed`）；`kototoki/translate/degrade.py` 换成 `resolve.py`（`runs`、`halves`、`translate_resolving`、`build_report`），节点日志 `nodes.jsonl`，`report.json` schema `kototoki-translate-report-v2`；`run_step` 零收下计 `unresolved` 失败；`TranslateResult.untranslated_count`；`merge.merge` 对 `None` 只输出日文一行（`srt.validate_translations` 不变，研究侧仍按原语义使用）；编排 `Summary.untranslated_cues`、`published.json` 的 `translate_untranslated_cues`、发布行与汇总改为 `untranslated cue(s)`；smoke 脚本 `translate_product.py` 同步字段。
- 配方 `q3-translate-v1`，hash `865bcd1d…`；决定记录 [ADR-0029](../../../docs/adr/0029-translate-per-cue-resolution.md)（ADR-0019 状态行追加替代说明），CURRENT.md、决定索引、模块页（翻译子系统、批次编排、运行日志、Strata session、模块边界、架构总览）、技术设计、GLOSSARY（"回退 cue"改为"未翻译 cue"）、README、开发工作流、技术栈同步。
- 实现时补的细节：ID 顺序不再校验（按条收下后无意义）；子节点 ID 为连续段 `.1`、`.2`…与对半 `.a`／`.b`；节点日志行核对目标与深度。
- 自动检查：`just test` 778 项通过；`just test-equivalence` 14 项通过；`scripts/check_docs.py` 只剩既有的 `run-logging-and-processes.md` 超字数（12227，比改前 12235 少），本票改到的其余页都在预算内。
- 未验证：未在 GPU 上运行；追问窗口（只有未解决的 cue 作待译）下的译文质量、碎尾 cue 单独再问后仍不出中文的比例都未知。研究侧 `experiments/asr_robustness_v15/translate_impact.py`（已结题）仍读 `fallback_count`，不再运行，未改。

## 证据

- `.local/run-notes/translate-rejects.tsv`（每次失败尝试的分类、cue、回复与 exchange 路径；不进 Git）。
- 汇总脚本 `.local/run-notes/translate_rejects.py`（注意：它没覆盖拆批节点，拆批的 3 次要看 `batches.jsonl` 的 `degrade.nodes`）。
- 台账 §D1 与"第 3 次运行结果"。

## Comments
