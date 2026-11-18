# 03 翻译 H0 线轮次记录

Status: resolved
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

## Answer

由子 agent（sonnet）撰写、主 agent 审阅（R2 必填标题齐全、59–91 行；无哈希、盘符路径与配方 hash；保留模型 repo＋量化＋8 位 revision、llama.cpp 版本与 GPU；结论能从 ADR-0004／0005／0006／0008／0009／0010 回链）。供 05 登记：

| 目录 | 时间 | 状态 | 一句话 |
| --- | --- | --- | --- |
| `2026-10-translation-model-selection` | 2026-10-05 – 10-08 | concluded | 五候选中 Hy30 Q3_K_M 质量与速度居首，Q4 慢 4.18 倍而收益不稳；四量化后用户按工程取舍采纳 APEX-I-Compact（H0），采样配方 `official30b-cached-v1` |
| `2026-10-translation-flow-v1-v4` | 2026-10-07 – 10-11 | concluded（v2 stopped） | v3 没有配方通过确认，`b10-joint` 按工程理由采纳；v4 只有 `mbr8c` 通过确认但约 6 倍墙钟，被 ADR-0008 放弃 |
| `2026-10-quality-v5` | 2026-10-16 | concluded | 产品中文错误约 76% 来自 ASR，STT 侧无可采纳改动，翻译侧唯一确认的 `mbr8s` 被放弃（ADR-0008） |
| `2026-10-batching-v6-v8` | 2026-10-16 – 10-18 | concluded | 吸附、按静默拼包、停顿标记、按小组拼包、组内语序重排都无可复现收益；`dp10-cut` 由离线模拟与用户裁定采纳，没有 GPU 质量证据 |

确认集（交 05 写入研究方法约束）：v3 的 48 窗确认集、v4 的 55 场景确认集、v5 的剧集确认集已开封；v2 的确认窗因中止从未开封；v6–v8 没有开封确认集。

来源吸收：映射表本线来源全部吸收，另吸收研究侧模块页 translation-runtime、translation-srt-flow 与 `docs/guides/local-translation-model-assets.md`。只一句带过：三个专用模型详解与三个应用源码调研、Q4 候选与量化短名单、`hy-mt2-translation-mode-optimization` 计划；旧 Codex 裁判流程（`docs/agents/subtitle-translation-evaluation.md`、`docs/specs/subtitle-translation-*`、`docs/archive/`）只写裁判身份、评分口径与弃用原因；参考复核 prompt 只写用途并给 tag 路径。丢弃逐窗、逐作品大表与失败成本明细（R3）。

已知差异：ADR-0005 写产品当时的 llama.cpp 为 b11669，旧模块页写 b11583；README 采用 ADR 的说法。
