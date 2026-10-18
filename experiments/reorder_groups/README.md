# 同一句话小组内语序重排：划组规则离线统计（reorder_groups）

纯 CPU、不加载模型、不占 GPU。在 `dp10-cut` 的包内按停顿门槛与句末标点划"同一句话小组"，统计小组大小、被切点截断的比例、行尾标点与门槛敏感性。结论与口径见[研究文档](../../docs/research/2026-10-18-reorder-group-offline-stats.md)。

只导入 `translation_v3`（`dp10-cut`、`build_batches`）与 `scene_batching_v6.sim7`（dev 与产品 `ja.srt` 的加载），不修改它们。`.local/` 里的 dev 集与产品 `ja.srt` 只读。

```bash
PYTHONPATH=. python -X utf8 -m experiments.reorder_groups.stats --local-root <有 .local 的 checkout>/.local [--json <输出.json>]
python -X utf8 -m unittest experiments.reorder_groups.test_stats
```

标准输出为 Markdown 表格；`--json` 写完整结果（放 `.local/` 下，不入库）。
