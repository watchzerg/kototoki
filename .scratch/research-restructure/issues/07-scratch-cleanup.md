# 07 .scratch 清理

Status: resolved
Type: task
Blocked by: 05

## 范围

逐个检查 `.scratch/` 下的目录（本目录 `research-restructure` 除外）：

1. 读 `spec.md` 的 `Status` 与各票据状态。
2. **进行中或有未完成票据**（已知：`batch-run-fixes` 为 in-progress，`cross-asr-judge` 显示 ready-for-agent，`next-directions` 无 spec）：保留不动，在本票据 `## Answer` 中列出并说明其状态，由用户决定后续。
3. **已结题**：确认持久结论已在 ADR、模块页、`docs/pending-decisions.md` 或 02–04 的轮次 README 中；缺的就补到对应现行正文（只补结论，不搬过程）；然后删除目录。
4. 删除后修正所有链接到这些目录的地方（模块页的"变更与决策来源"改为 ADR 或 tag 路径）。

## 完成标准

- `.scratch/` 只剩进行中目录与本目录。
- 全仓库 grep `.scratch/<已删目录名>` 只剩 tag 路径形式。

## Answer

**删除（21 个，均已结题，内容都在归档 tag 中）**：architecture-cleanup、asr-repeat-guard、asr-robustness-v14、asr-robustness-v15、bilingual-subtitle-pipeline、docs-architecture、gap-aware-batching-v7、general-model-translation-v9、group-reorder-v8、name-consistency、name-consistency-product、names-on-strata-v13、q0-exploration-v10、q0-product-route-v11、q2-product-switch、q3-product-switch、quality-exploration-v5、runtime-logging、runtime-logging-gaps、scene-batching-v6、strata-flash-next-v12。它们的票据都是 resolved、done 或 wontfix。研究线的结论已在 02–04 的轮次 README 与 ADR 中，产品线的结论已在 ADR 与模块页中；抽查了 bilingual-subtitle-pipeline 13（裁定不实现），已由 `research/2026-10-cue-token-boundary/` 与 `japanese-cues.md` 覆盖。没有需要补写的结论。删除前确认这些目录全部受 git 跟踪，没有未跟踪或被忽略的文件。

**保留（交用户决定）**：
- `batch-run-fixes`：spec 是 `in-progress`，9 张票据都已 resolved。是否结题由用户决定。
- `cross-asr-judge`：01–08 都已完成，但 spec 状态还是过期的 `ready-for-agent`，票据 08 写着"代码修复与提交由主 agent 处理"。结论已进 ADR-0012 与交叉打分轮次 README，可以结题删除，等用户确认。
- `next-directions`：两张 `needs-triage` 票据（ASR 稳健性第三轮、说话人分离），是候选方向。
- `architecture-review`：唯一的票据 01（小修集合）已 resolved，但 2026-10-19 审计报告里还有不少没有转成票据、也没登记到 `docs/pending-decisions.md` 的发现：A-2、A-4～A-10、B-4、B-5、B-7、B-8、B-11、B-12、B-15、C-3、C-7～C-9。其中 A-1 已由 ADR-0023 解决；C-1、C-2 针对 llama-server 时代，可能已经过时。删除会丢掉这些未处理的发现，所以先保留，由用户决定转成票据还是放弃。

**改链**：现行文档里指向已删目录的反引号路径，每行第一处改为"归档 tag 中的 .scratch/…"纯文本，同一行后续的改为纯路径；`docs/pending-decisions.md` 的 docs-architecture 链接改为 tag 路径；`next-directions` 两张票据只改了失效链接（指向新轮次 README 与 `research/INDEX.md`），内容未动。改链涉及 ADR-0014 正文中的一处路径。

**检查**：`check_docs.py` 全部通过（126 篇，1318 个本地链接；仅 1 条既有告警，`japanese-cues.md` 状态行日期多）。
