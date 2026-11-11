# 文档索引

本页是文档总入口，只负责路由：说明每个入口回答什么问题，以及没有具体任务时从哪读起。按任务读取的触发表在 [AGENTS.md](../AGENTS.md)，文档分类、权威归属与维护流程在[文档维护规则](agents/documentation.md)，本页不复制。

## 冷启动阅读路径

1. [架构总览](architecture/INDEX.md)：系统由什么组成、模块地图、依赖与不变量。
2. [模块边界](architecture/module-boundaries.md)：职责归属与依赖方向；对照 [GLOSSARY.md](../GLOSSARY.md) 理解术语。
3. 按需打开 `architecture/modules/` 中的模块页，再沿链接进代码与测试。
4. 查当前有效决定与其演进时看[决定索引](adr/INDEX.md)；需要证据与研究轮次时查[调研索引](research/INDEX.md)。

## 入口分工

| 入口 | 回答的问题 |
| --- | --- |
| [README](../README.md) | 怎么安装和使用 |
| [AGENTS.md](../AGENTS.md) | agent 的常驻约束和按任务读取入口 |
| [GLOSSARY.md](../GLOSSARY.md) | 领域术语与基线身份是什么意思 |
| [CODING_STANDARDS.md](../CODING_STANDARDS.md) | diff 评审按什么判断 |
| [架构总览](architecture/INDEX.md) | 系统现在怎样组成与运行 |
| [模块边界](architecture/module-boundaries.md) | 规则归谁、依赖方向与状态所有权 |
| `architecture/modules/` | 某个能力现在完整地怎样工作 |
| `adr/` | 为什么做出重要决定；[决定索引](adr/INDEX.md)汇总当前有效决定与演进链 |
| [待用户裁定事项](pending-decisions.md) | 哪些问题还在等用户裁定，哪些只是未验证 |
| [调研索引](research/INDEX.md) | 比较与验证的证据和适用条件；[决定与探索时间线](research/timeline.md) |
| [规格索引](specs/INDEX.md) | 已接受的行为契约（产品技术设计、W0／X0 demo）与已取代的草案 |
| [开发工作流](development/workflow.md)、[技术选型](development/technology-stack.md) | 怎么开发、构建和验证 |
| [依赖布局与资产清单](development/dependencies.md) | 依赖放在哪、版本由谁锁定、哪个 recipe 安装或编译 |
| [测试设计与验收](agents/testing.md) | 测试怎么写、归哪类、怎么验收 |
| [文档维护规则](agents/documentation.md) | 文档放哪、怎么同步 |
| `agents/` 其余文件 | 工程 skills 的 tracker、标签映射与领域文档约定，以及旧字幕翻译评估流程 |

按需创建的目录：`specs/`、`operations/`、`adr/`、`architecture/modules/`。创建条件见[文档维护规则](agents/documentation.md#权威归属与创建时机)。

## 项目特有入口

以下文档不在标准结构内，按冻结证据规则（见 [AGENTS.md](../AGENTS.md) 常驻约束）原位保留：它们本身是冻结证据，或被冻结文件链接，或其字节被代码按 sha256 校验，移动会让链接或自检失效。当前正文只链接它们，不复制内容。逐篇状态看各目录索引。

| 路径 | 目录索引 | 保留原因 |
| --- | --- | --- |
| `docs/architecture/stt-candidate-pipelines.md` | [架构总览](architecture/INDEX.md) | W0／X0 基线与组件边界的权威表；被 ADR 与调研报告链接 |
| `docs/development/toolchain.md`、`docs/development/windows-nvidia.md` | [开发工作流](development/workflow.md) | 工具链与平台细则的权威正文；被归档与调研文件链接 |
| `docs/development/inference-selection.md` | [测试文档索引](testing/INDEX.md)（被校验名单） | 推理选型原则；`experiments/run_round2.py` 对其字节取 sha256，不得修改 |
| [基线测试指南](guides/baseline-testing.md)、[本地翻译模型资产](guides/local-translation-model-assets.md) | 本行 | 操作指南；被冻结报告大量链接，目录不再新增文件 |
| `docs/specs/*.md` | [规格索引](specs/INDEX.md) | 现行契约与 5 篇已标 superseded 的字幕翻译草案 |
| `docs/plans/*.md` | [计划索引](plans/INDEX.md) | 已完成、已停止或已取代的执行计划；被冻结报告与台账链接，目录冻结 |
| `docs/testing/*.md` | [测试文档索引](testing/INDEX.md) | 活契约、带日期的冻结记录与被代码校验字节的文件混放，逐篇标注能否修改 |
| `docs/context/*.md` | [执行台账索引](context/INDEX.md) | 带日期的接跑台账（冻结证据）；体量大，禁止整读 |
| [`docs/archive/agents/2026-10-09-codex-AGENTS.md`](archive/agents/2026-10-09-codex-AGENTS.md) | 本行 | Codex 时代的 agent 指令归档（冻结证据），只作历史参考 |
| `experiments/**/README*.md`、`experiments/**/*.md`、`experiments/**/THIRD_PARTY_NOTICES.txt` | [experiments 包登记](../experiments/INDEX.md) | 各实验与 demo 包自带的说明、第三方许可声明与参考复核 prompt（`experiments/translation_corpus/*-prompt.md` 属冻结的参考 prompt）；与代码同目录维护 |
| `.scratch/<slug>/` | [tracker 约定](agents/issue-tracker.md) | 计划、票据与执行提示词；结题后整目录冻结 |
