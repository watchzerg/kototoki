# 03 翻译 H0 线轮次记录

Status: ready-for-agent
Type: task
Blocked by: 01

## 范围

做法与完成标准同 [02](02-research-stt.md)，目录为：

- `research/2026-10-translation-model-selection/`：方法与工具调研、候选模型比较、Hy-MT2 量化（Q3／Q4、四量化及附录）、旧 Codex 裁判流程（`docs/agents/subtitle-translation-evaluation.md`）与 Claude 裁判 profile。旧裁判流程只写"裁判身份、评分口径、为何弃用"，不保留其字节锁与 prompt 全文。
- `research/2026-10-translation-flow-v1-v4/`：v1–v4（含 v2 中止原因与 v1/v2 教训）。确认集的结论（哪些集合已开封）写成一句话，交给 05 放进 `research/INDEX.md` 的研究方法约束。
- `research/2026-10-quality-v5/`
- `research/2026-10-batching-v6-v8/`：v6 场景分批、v7 静默拼包与动态切包模拟、v8 语序重排。

## 额外注意

- ADR-0004／0005／0006／0008／0009／0010 的依据在这些轮次里：README 的"结论与去向"必须能让人从 ADR 回链过来看懂为什么。
- `experiments/translation_corpus/*-prompt.md`（参考复核 prompt）不迁；README 里一句话说明用途并给 tag 路径。
