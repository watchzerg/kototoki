# 文档索引

本页是文档总入口，只负责路由：说明每个入口回答什么问题，以及没有具体任务时从哪读起。按任务读取的触发表在 [AGENTS.md](../AGENTS.md)，文档分类、权威归属与维护流程在[文档维护规则](agents/documentation.md)，本页不复制。

## 冷启动阅读路径

1. [现行决定](adr/CURRENT.md)：现在生效的基线身份与产品决定，一页读完；术语对照 [GLOSSARY.md](../GLOSSARY.md)。
2. [架构总览](architecture/INDEX.md)：模块表（模块、代码路径、职责）、按任务找模块页、依赖与不变量。
3. [模块边界](architecture/module-boundaries.md)：依赖方向、规则与接缝；再按需打开 `architecture/modules/` 中的模块页，沿链接进代码与测试。
4. 决定的沿革看[决定索引](adr/INDEX.md)，等用户裁定的事项看[待用户裁定事项](pending-decisions.md)；需要证据与研究轮次时查[研究索引](research/INDEX.md)，只读命中主题的轮次。

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
| [研究索引](research/INDEX.md) | 比较、实验与验收的记录和适用条件：研究规则、按主题的现状、轮次登记与验收记录 |
| [行为规格索引](behaviors/INDEX.md) | 用户可见的行为契约 |
| [跨模块流程](architecture/collaborations.md) | 阶段链、产物交接与失败收敛怎样跨模块进行 |
| [开发工作流](development/workflow.md) | 该跑哪个 mise task、各 gate 含哪些检查、长任务与 worktree 怎么启动、smoke 怎么运行 |
| [技术选型](development/technology-stack.md) | Python、CUDA、torch、Strata 等运行时与已选依赖的版本与选型政策 |
| [依赖布局与资产清单](development/dependencies.md) | 依赖放在哪、版本由谁锁定、哪个 recipe 安装或编译 |
| [测试设计与验收](agents/testing.md) | 测试怎么写、归哪类、怎么验收 |
| [测试分层合同](development/test-layers.md)、[本地验收环境](development/local-acceptance.md) | 测试各层的目录、入口与资源边界；真实环境验收的环境契约（`/prune-tests`、`/acceptance` 按路径读写，不改名不移动） |
| [文档维护规则](agents/documentation.md) | 文档放哪、怎么同步 |
| [翻译评估方法](agents/translation-evaluation.md) | 新的翻译对比用什么裁判、统计口径与对照规则 |
| [批量运行与跑次记录](agents/production-runs.md)、[跑次索引](research/runs/INDEX.md) | 替用户跑产品批量时怎么跑、跑完记什么、问题怎么转票据；历次运行的记录 |
| [tracker 约定](agents/issue-tracker.md) | 用 `bd` 创建、读取、领取和关闭票据，spec、wayfinding 的写法 |
| [标签映射](agents/triage-labels.md) | triage 的 canonical role 对应哪个 Beads label |
| [领域文档规则](agents/domain.md) | 起名、写票据或提议时怎样使用 GLOSSARY 与 ADR，遇到冲突怎么处理 |

按需创建的目录：`behaviors/`、`operations/`、`adr/`、`architecture/modules/`。创建条件见[文档维护规则](agents/documentation.md#权威归属与创建时机)。

## 项目特有入口

以下文档不在标准结构内：

| 路径 | 目录索引 | 说明 |
| --- | --- | --- |
| [工具链](development/toolchain.md) | 本行；[开发工作流](development/workflow.md)摘要并链接 | mise 与 uv 的分工、依赖变更入口与 task 接口约定 |
| [Ubuntu 与 NVIDIA](development/ubuntu-nvidia.md) | 本行；[开发工作流](development/workflow.md)摘要并链接 | 平台前提、子进程与路径写法、GPU 就绪核查与失败处理 |
| [推理选型原则](development/inference-selection.md) | 本行；[开发工作流](development/workflow.md)摘要并链接 | 选择或对比 STT 引擎、模型、精度与对齐器时的约束与候选 |
| `research/runs/` | [跑次索引](research/runs/INDEX.md) | 产品批量运行一次一篇的记录（[批量运行与跑次记录](agents/production-runs.md)） |
| Beads（`bd`） | [tracker 约定](agents/issue-tracker.md) | 产品侧计划、票据与执行提示词；完工后关闭 |

重组前的旧材料（旧调研报告、计划、执行台账、测试记录、操作指南与研究代码）只在归档 tag `archive/2026-11-18-pre-research-restructure` 里。
