# 文档索引

本页是文档总入口，只负责路由：说明每个入口回答什么问题，以及没有具体任务时从哪读起。按任务读取的触发表在 [AGENTS.md](../AGENTS.md)，文档分类、权威归属与维护流程在[文档维护规则](agents/documentation.md)，本页不复制。

## 冷启动阅读路径

1. [现行决定](adr/CURRENT.md)：现在生效的基线身份与产品决定，一页读完；术语对照 [GLOSSARY.md](../GLOSSARY.md)。
2. [架构总览](architecture/INDEX.md)：模块表（模块、代码路径、职责）、按任务找模块页、依赖与不变量。
3. [模块边界](architecture/module-boundaries.md)：依赖方向、规则与接缝；再按需打开 `architecture/modules/` 中的模块页，沿链接进代码与测试。
4. 决定的沿革看[决定索引](adr/INDEX.md)，等用户裁定的事项看[待用户裁定事项](pending-decisions.md)；需要证据与研究轮次时查[研究索引](../research/INDEX.md)，只读命中主题的轮次。

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
| [现行决定](adr/CURRENT.md) | 现在生效的决定与基线身份的完整定义 |
| `adr/` | 为什么做出重要决定；[决定索引](adr/INDEX.md)列全部 ADR 与演进链 |
| [待用户裁定事项](pending-decisions.md) | 哪些问题还在等用户裁定，哪些只是未验证 |
| [研究索引](../research/INDEX.md) | 比较、实验与验收的记录和适用条件：研究规则、按主题的现状、轮次登记与验收记录 |
| [规格索引](specs/INDEX.md) | 现行的行为契约（产品技术设计） |
| [开发工作流](development/workflow.md)、[技术选型](development/technology-stack.md) | 怎么开发、构建和验证 |
| [依赖布局与资产清单](development/dependencies.md) | 依赖放在哪、版本由谁锁定、哪个 recipe 安装或编译 |
| [测试设计与验收](agents/testing.md) | 测试怎么写、归哪类、怎么验收 |
| [文档维护规则](agents/documentation.md) | 文档放哪、怎么同步 |
| [翻译评估方法](agents/translation-evaluation.md) | 新的翻译对比用什么裁判、统计口径与对照规则 |
| [tracker 约定](agents/issue-tracker.md)、[标签映射](agents/triage-labels.md)、[领域文档规则](agents/domain.md) | 工程 skills 的票据、标签与领域文档约定 |

按需创建的目录：`specs/`、`operations/`、`adr/`、`architecture/modules/`。创建条件见[文档维护规则](agents/documentation.md#权威归属与创建时机)。

## 项目特有入口

以下文档不在标准结构内：

| 路径 | 目录索引 | 说明 |
| --- | --- | --- |
| [工具链](development/toolchain.md)、[Windows 与 NVIDIA](development/windows-nvidia.md)、[推理选型原则](development/inference-selection.md) | 本行；[开发工作流](development/workflow.md)摘要并链接 | 工具链、平台与推理选型的权威正文 |
| `research/` | [研究索引](../research/INDEX.md) | 研究轮次（一轮一目录）与产品验收记录（[ADR-0031](adr/0031-research-layout-and-lightweight-records.md)） |
| `.scratch/<slug>/` | [tracker 约定](agents/issue-tracker.md) | 进行中的产品侧计划、票据与执行提示词；完工后删除 |

重组前的旧材料（旧调研报告、计划、执行台账、测试记录、操作指南与研究代码）只在归档 tag `archive/2026-11-18-pre-research-restructure` 里。
