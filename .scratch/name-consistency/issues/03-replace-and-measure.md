# 03 后处理替换与量化

Status: resolved
Type: research

## Answer

- 实现 `experiments/name_consistency/apply_table.py`（子 agent 写、主 agent 审，迭代 6 版：v2 省略形不扩写；v3 统计层候选过形状与特异性过滤、复合词跳过；v4 落点扩到有支持的最长超串；v5 含 `·` 的扩展须覆盖整个复合词、`zh_variants` 也过特异性；v6 消费 `name-table-v2`、按写法锚定、同实体其他写法只在包含关系下作候选、`--min-confidence`），测试 14 项。
- 结果见[离线验证报告](../../../docs/research/2026-10-19-name-consistency-offline-results.md)：四部不一致率降到 0.000–0.113；逐条评审好行 68%（think）／75%（no-think），有害 17%／15%；有害来自表的错名与统计层残字。
- MQM 抽样与整片人工观感**未做**；评审只看改动行。
- 产物 `.local/name-consistency/03-four-v2/`（表、替换输出、`review/`）。

## 范围

- 新脚本 `experiments/name_consistency/apply_table.py`（纯 CPU）：
  1. 定位：日文含表中任一 `ja_variants` 的 cue，标记"译文应含该专名"。
  2. 找落点，两层：先 `zh_variants` 直接命中；再复用 `experiments/quality_v5/consistency.py` 的跨 cue 统计（main／alt 检测，含编辑距离 1 的音译变体）找该 cue 译文里模型实际用的写法。
  3. 命中则整段替换成 `zh`，只在被日文锚定的 cue 内替换；两层都未命中则**不动**，写入 `unresolved.jsonl`（cue 编号、日文、译文）。
  4. 输出新的 `zh.srt` 与 `changes.jsonl`（每处替换的前后文本）。
- 量化：
  - `consistency.py srt --pair` 对替换前后各算一次不一致率（四对 SRT）。注意该指标与表同源的部分：只能证明"照表执行"，表选错译法不会被发现。
  - 准确性：从 `changes.jsonl` 抽样（每部 ≤40 条），用 v3 裁判 profile `claude-opus-5-5-mqm-v1` 对替换前后成对判；替换只动专名，预期 Δ≈0，出现变差要逐条看。裁判配额记录。
  - 专门盯职阶名译成普通名词（ライダー→骑士）的 cue：跨 cue 统计会判为普通名词不计，看 `zh_variants` 是否兜住。
- 人工：随机挑一段 10 分钟整片对照看替换前后观感，记录。

## 完成标准

- 四对 SRT 的不一致率前后表、替换条数、未处理条数与原因分类、裁判抽样 Δ、人工观感记录；写入研究文档并登记索引。
- 结论之一：后处理替换"可进产品候选／需改表或规则／不值得"。进产品另开票并改技术设计。

## 文件所有权

`experiments/name_consistency/`、研究文档。不改 `kototoki/`。

## Blocked by

02
