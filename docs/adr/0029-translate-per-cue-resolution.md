# ADR-0029：产品翻译按条收下、只追问没解决的 cue（`q3-translate-v1`）

状态：已接受（2026-11-17，用户决定，依据 batch-run-fixes 08（`archive/2026-11-18-pre-research-restructure:.scratch/batch-run-fixes/issues/08-short-cue-translation.md`））、已实现（同日）。替代 [ADR-0019](0019-product-translation-q2.md) 第 4 点中的 10→5→1 降级、"单条仍失败只保留日文"与"含空行按解析失败处理"，以及第 5 点的配方名 `q2-degrade-v1`、hash 与 run 目录名。[ADR-0021](0021-q3-strata-names-baseline.md) 的基线 Q3 身份不变。  
范围：产品包 `kototoki/translate/` 的回复判定与失败路径、`kototoki/merge.py` 对未翻译 cue 的输出、编排的计数字段。不改切包、邻文、提示、专名注入、采样、请求形状、每个请求的尝试次数与 Strata 启动方式；首个请求即全部合格的批次，请求体与研究侧仍逐字节相同。

## 决定

1. **结构失败才算这次尝试失败。** 回复被截断（`finish_reason == length`）、HTTP 报超出 context、不是 JSON、不是恰好一个 `translations` 对象，这次尝试失败，换下一个 seed（超出 context 不换，直接终态）。
2. **结构合法即按条判。** 值为非空字符串且不含空行的 cue 收下；缺失（`missing`）、空串或非字符串（`empty`）、含空行（`blank_line`）的 cue 记为未解决；多出的 ID 与 ID 顺序不看，多出的个数只进尝试记录。一条都没收下的尝试计为失败（`unresolved`），换下一个 seed。
3. **只追问没解决的 cue。** 节点是场景内连续的一段待译 cue，初始节点即切包产出的批次，每个节点最多两次尝试（seed、seed＋1）。
   - 某次尝试收下至少 1 条，节点结束；未解决的 cue 按场景顺序切成最大连续段，每段成为子节点 `父ID.1`、`父ID.2`…。
   - 两次都失败时，多于 1 条的节点对半拆成 `父ID.a`／`父ID.b`（奇数条时前半多 1 条）；只有 1 条的节点，该 cue **不出中文**。
   - 子节点用同一条邻文规则、同一专名注入规则，seed 从原 seed 起。子节点必比父节点小，过程必然终止。
4. **不出中文的 cue 只输出日文一行。** 译文映射里它的值为 `None`（JSON `null`），空串仍然非法；合并时该条只有日文一行，不再把日文抄进中文行。原因记为该 cue 最后一次未解决的类别（`missing`／`empty`／`blank_line`），没有按条结果时记失败种类（`parse`／`limit`／`context`）。计数从"回退"改称"未翻译"：`TranslateResult.untranslated_count`、`report.json` 的 `untranslated_cues`、`published.json` 的 `translate_untranslated_cues`、发布行与汇总的 `untranslated cue(s)`。
5. **新配方 `q3-translate-v1`**，`RECIPE_HASH` `865bcd1d06f0cc7af83a02f90d0ff2ae5c1fca012695d28e1dbbe4b4f0325964`（`q2-degrade-v1` 为 `332649cf98662e42cccc31485792104c3ce6303e6cd634ef42ef85839ee9310d`），由 `tests/core/test_translate_recipes.py` 钉住。配方里 `rule`、`validation`、`overflow` 改为新规则的描述，其余字段不变。run 目录 `translate/srt-<sha12>/q3-translate-v1__s<seed>__n<names_sha12>/`，节点日志 `nodes.jsonl` 取代 `degrade.jsonl`，`report.json` 的 schema 为 `kototoki-translate-report-v2`。
6. **不兼容已有产物。** 配方变即翻译身份变，旧 run 目录不再读取，下次运行重译；已发布的字幕按 ADR-0020 照旧跳过，要重做须先删掉。

## 依据

- **首次大批量运行**（2026-11-12～11-15，228 部，`.local/run-notes/translate-rejects.tsv`）：失败尝试 121 次，全部是格式类，没有一次是模型拒绝翻译。其中空值 82 次，全在第 1 次尝试，换 seed 后几乎都通过，只有 1 批两次皆空而拆批；空值没有造成任何回退（唯一的回退是 ID 缺失）。旧规则下一条空值让整批约 10 条全部重来。
- **空串不当合法答案**：空值 cue 多是上一句的碎尾（「した」「でした」「うございました」），但也有实义台词（「何でしょうか?」「を大切にしていきたいなと思ってます」）。直接放行可能悄悄丢台词，所以记为未解决、单独再问。
- **与 ADR-0028 同一原则**：重试只用来对付坏掉的回复；按条取第一个合格译文、不比较不同尝试，不属于 [ADR-0008](0008-no-multi-translation-selection.md) 的"翻译多次再挑选"。
- **只改失败路径**：首个请求即全部合格的批次请求体不变，因此不做翻译质量评估（用户裁定）。

## 未验证

- 未在 GPU 上运行；只有伪客户端离线测试（`just test`、`just test-equivalence`）。
- 追问请求只有未解决的 cue 作待译、其余可见台词作只读邻文，模型在这种窗口下给出的译文质量没有裁判证据；单独再问的碎尾 cue 有多少最终仍不出中文，未知。
