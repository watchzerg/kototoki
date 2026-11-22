# 规格索引

状态：current

本目录只存放现行行为规格；已取代的旧规格在归档 tag 里（[ADR-0031](../adr/0031-research-layout-and-lightweight-records.md)）。

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| [bilingual-subtitle-pipeline.md](bilingual-subtitle-pipeline.md) | 现行 | 产品包 `kototoki/` 双语字幕流水线的用户可见行为（输入输出、发布与重做、续跑、失败时看到什么）；跨模块流程（阶段链、调度、产物交接、失败收敛）见[跨模块流程](../architecture/collaborations.md)，配置见[配置参考](../architecture/modules/config-and-media/reference.md)，拆出的历史原文见拆分记录（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`）。 |
| [bilingual-subtitle-pipeline/fixed-recipes.md](bilingual-subtitle-pipeline/fixed-recipes.md) | 现行 | 上页的子页：各阶段写死、不做配置项的模型与配方。 |
