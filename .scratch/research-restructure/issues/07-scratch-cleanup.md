# 07 .scratch 清理

Status: ready-for-agent
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
