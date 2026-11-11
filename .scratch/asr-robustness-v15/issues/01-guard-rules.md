# 01 A3：w0 产物盘点、四信号与重复检测器、规则候选统计、Opus 判读

Status: resolved
Type: research
Stage: A（离线；Opus ≤$3）
Blocked by: —

权威：研究文档 §4.1 A3、§5。

## 范围

- 盘点所有仍存在的 w0 `asr.json`（HF II／III 产品形状，`.local/fullfilm-comparison/` 下的 w0 整片运行，ATKD-089 若在），按电影与 VAD 参数分组登记身份（recipe hash、窗数）。
- 实现显式重复检测器（定义写进 README），逐窗算压缩比、触顶、`avg_logprob`、重复检测；规则候选 doc-default／whisper-or／repeat／repeat-or-cr2.4 的逐样本标记窗数与字数。
- 所有被任一规则标记的窗口交 Opus（`opus`，只读）判"幻觉／复读 ／ 正常语音 ／ 无法判断"；逐窗文字只写 `.local`。
- 新包 `experiments/asr_robustness_v15/` 与离线测试。

## 完成标准

- `.local/asr-robustness-v15/01/` 下有盘点表、逐规则统计、Opus 判读 JSON；研究文档 §7 一行写明哪些规则满足"拦住 HF III 第 51 窗且正常语音零标记"，选中哪条（召回优先），没有满足的就写保守安全网结论。

## 执行记录

- 2026-11-10：新包 `experiments/asr_robustness_v15/`（common／inventory／repeat／scan／actions／test_offline）。`scan` 盘点 101 样本／5618 窗；被标记并集先 230 窗／121 唯一文字交 Opus（子 agent，≈109K token），重复检测器改为按规则参数各算一份后并集 241 窗／124 唯一文字，补判 11 窗／4 唯一文字（≈82K token，全部 unsure）。`safety-net` 选中 repeat-strict。
- 发现：ATKD-089 的 `asr.json` 不在盘上（只剩 SRT），只按两部电影＋ `.local/fullfilm-comparison/` 与 VAD 变体、国会样本扫描。

## Answer

- 安全网判据下**只有 repeat-strict** 满足（拦住 HF III 第 51 窗、全部样本零正常标记）：17 窗＝16 幻觉＋1 无法判断，召回 16/78。doc-default 误报 1、repeat 13、repeat-loose 40、whisper-or 6。选中 **repeat-strict** 进 02。
- whisper-or 独有的 58 个幻觉是低压缩比短套话，任何重复／压缩比规则都拦不住；这是 A 的召回上限，写进 §7.1。
- 阈值敏感性：份数 ≥9 零误报，8 起出现正常窗；默认 10 份保留。
- 数字与路径：`.local/asr-robustness-v15/01/{inventory,scan,safety-net,sensitivity}.json`，判读 `01/flagged/judgements.json`。
