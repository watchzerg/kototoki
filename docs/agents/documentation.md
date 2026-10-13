# 文档维护规则

本文规定文档放在哪里、谁是权威、怎样随交付同步。新增、移动、删除文档或讨论形成明确结论时按本文执行。读者路由在[文档索引](../INDEX.md)，本文不重复"哪篇回答什么问题"。

## 三态规则

每份文档只属于以下一态，不混写：

- **存量当前正文**：描述同一仓库版本的已实现系统，持续改写，每条规则只有一处权威，其他位置摘要加链接。不按迭代追加"本次增量"章节。
- **本次增量**：说明这次改变什么、验收什么、涉及哪些当前正文。默认由 issue tracker 承载；用户要求 Markdown 时放 `docs/changes/<主题>.md`。吸收进当前正文后删除：删除前确认已实现的规则都已写入当前正文，未实现的范围转回 tracker；票据或模块页的"变更与决策来源"记录吸收位置。
- **历史证据**：调研、实验、验收记录，带时点和适用条件，永不改写、不归档。正文中的"当前""尚未实施"只描述记录时点。

代码是实际行为的证据，当前正文是预期行为依据。两者冲突时就地记录实现差异并明确修代码还是修文档，不把缺陷改写为正常行为，也不把待实现设计写成现状。

## 讨论结论的落点

讨论形成明确结论时，按结论类型落到唯一位置，不另建会议纪要：

| 结论类型 | 落点 |
| --- | --- |
| 术语的定义或取舍 | `GLOSSARY.md` |
| 难以逆转、事后看不出原因、有真实取舍的决定 | `docs/adr/` 新增一条 |
| 已实现行为或结构的澄清 | 所属模块页或模块边界 |
| 尚未实现的需求、范围或计划 | tracker 票据 |
| 评审时反复出现的判断类问题 | `CODING_STANDARDS.md` |
| 工具链、命令、门禁的约定 | `docs/development/` |
| 带时点的比较或实验结果 | `docs/research/` 并登记索引 |

## 权威归属与创建时机

一项信息只有一处权威正文；其他页面摘要并链接。没有实际内容时不建占位页，目录为空时不建目录。

| 信息 | 权威落点 | 创建时机 | 其他页面的责任 |
| --- | --- | --- | --- |
| 跨任务流程约束、按任务读取入口 | `AGENTS.md` | 初始化 | 不复制触发表 |
| 领域术语 | `GLOSSARY.md` | 初始化，第一个术语敲定时填入 | 正文首次出现关键术语时给一句白话解释 |
| diff 评审的判断类标准 | `CODING_STANDARDS.md` | 初始化，随 retro 追加 | 测试专项规则留在 `agents/testing.md`，互链 |
| 冷启动路径、各入口回答什么 | `docs/INDEX.md` | 初始化 | 不含触发表与维护规则 |
| tracker、标签、领域文档约定 | `docs/agents/` 中 Matt setup 产出的三个文件 | Matt setup | 由 `AGENTS.md` 触发表指向，不另建 Agent skills 块 |
| 测试归属、收录、分阶段验证 | `docs/agents/testing.md` | 初始化 | 命令与资源合同在 `development/workflow.md` |
| 系统全貌、模块地图、依赖、不变量 | `docs/architecture/INDEX.md` | 初始化 | README 与文档索引只路由 |
| 职责归属、依赖方向、状态所有者 | `docs/architecture/module-boundaries.md` | 初始化 | 模块页说明如何遵守，偏差就地注明 |
| 某模块的行为规格、实现设计、代码与验证入口 | `docs/architecture/modules/<module>.md` | 该职责首次有可描述的行为和测试时 | 总览只摘要 |
| 跨模块流程 | `docs/architecture/collaborations.md` | 流程涉及三个以上模块时 | 模块页链接参与的流程 |
| 用户可见行为规格 | `docs/specs/<topic>.md` | 行为横跨多个模块或有非开发读者时；否则写在模块页 | 模块页引用不重写 |
| 重要决策的背景、选择与后果 | `docs/adr/NNNN-<slug>.md`，状态写 frontmatter | 第一条 ADR 时 | 当前正文采用最终规则；替代旧决定时双向链接 |
| 调研、实验、验收证据 | `docs/research/`，验收在 `acceptance/` | 索引初始化，文件按需 | 历史证据不冒充当前覆盖 |
| 工具链、命令、门禁、测试分层 | `docs/development/` | 初始化，阶段 3 填入 | 模块页链接测试入口，不复制执行说明 |
| 部署、运行配置、发布与回滚 | `docs/operations/` | 有可部署产物时 | development 链接发布入口 |
| Markdown 形式的增量规格 | `docs/changes/<topic>.md` | 用户要求时 | 吸收后删除 |

## 模块页模板

按稳定职责划分模块，不要求与源码包一一对应。章节可按内容合并，不建空表。

```markdown
# 模块名称

## 定位与阅读
负责与不负责什么；上级总览、依赖模块、相关规格。

## 当前行为规格
入口与前置条件、输入输出、正常流程、状态转换、不变量；失败、取消、重试、恢复及用户可见行为。

## 实现设计
关键协作、状态与资源所有权、事务与时序、外部副作用；必要设计理由及 ADR 链接。

## 接口与依赖
调用者必须知道的语义，以及其他模块负责的规则链接。

## 代码与验证入口
关键源文件与符号、相关测试及覆盖行为、已知限制和未验证范围。

## 变更与决策来源
已吸收的票据、增量规格、ADR、调研；只用于追溯。
```

## 随交付同步

1. 动手前从架构总览找到受影响模块，读其当前正文及本次所需的依赖章节。总览仍是 `<待填>` 而代码已存在时，本次任务先补模块地图中与改动相关的行，再动手。
2. 每个可交付切片完成时，改写受影响模块的完整当前行为与设计；删除失效条款。某职责首次有了可描述的行为和测试，就按模板建模块页并加入模块地图；新增或拆分模块时同步模块边界。
3. 术语变化更新 `GLOSSARY.md`；满足 ADR 条件的决策新增 ADR；使用方式改变时更新 README 或 `operations/`。
4. 交付说明列出已更新文档与验证范围。无文档影响时说明判断，不机械改动。After changing code, config, scripts, or dependencies, check the affected docs (README, `AGENTS.md`, `docs/`) and update only what became inaccurate. No mechanical rewrites or date refreshes.
5. 新增、移动或删除文档时同步 `docs/INDEX.md`、所属目录索引及所有引用；仅当新文档成为某类任务的必读入口时才改 `AGENTS.md` 触发表。有链接检查命令时运行它。

## 待填标记

初始化留下的 `<待填 时机：说明>` 是尚未成形的内容，不另维护列表，剩余清单用下面的命令得到（规则正文里的 `<待填` 字样不含时机前缀，不会命中）：

```sh
grep -rnE '<待填 (初始化|阶段3|首个模块|按需)：' --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.build .
```

时机取值：

| 时机 | 何时可填 |
| --- | --- |
| 初始化 | 项目创建时就能回答，如一句话描述 |
| 阶段3 | 工具链、命令与门禁落地后 |
| 首个模块 | 第一个职责有了可描述的行为和测试后；项目已有代码时读代码填写 |
| 按需 | 说明中的条件出现时 |

填写后删除整个标记；内容尚不存在时保留，不编造。全部标记消失后删除 `AGENTS.md` 中对应的常驻约束。

## 项目约定

本项目在上述规则之外的补充约定（原 `docs/INDEX.md` 的文档约定中与本文不冲突的部分）：

- Keep `lower-kebab-case.md` filenames. Date research, reports, and handoffs when chronology matters:
  `YYYY-MM-DD-topic.md`.
- Give each substantive document a title, status, and scope. Add related links where applicable.
- Use category-appropriate statuses: specs may be draft/accepted/implemented;
  research exploratory/concluded. State limitations and open questions explicitly.
- Research must include source links, access dates, relevant versions, and a
  distinction between observations and inferences. Experiments and evaluation
  reports must include enough model, hardware, configuration, and input details
  to reproduce the results.
- Specs should include scope, exclusions, observable behavior, and acceptance
  criteria.
- ADRs use `NNNN-short-title.md`, starting at `0001`. Status is one of
  proposed/accepted/rejected/superseded. Mark acceptance only when the decision has actually been
  adopted; record the basis. Supersede accepted decisions with a linked new ADR
  rather than rewriting their history.
- Plans and research do not supersede requirements by themselves. For conflicts,
  identify the applicable scope and linked superseding decision rather than assuming
  the newest file overrides every older document.
- Keep private recordings, transcripts, model weights, secrets, and large
  generated outputs outside documentation and Git. Link reproducible procedures
  and permitted artifact locations instead.

## 既有目录

`docs/plans/`、`docs/context/`、`docs/archive/`、`docs/guides/`、`docs/testing/` 是采用本规则前的目录，现有文件按冻结证据规则原位保留并在[文档索引](../INDEX.md#项目特有入口)登记，不再新增文件。新内容按上文落点表放置：计划与进度进 tracker 票据（`.scratch/`），验证与验收记录进 `docs/research/acceptance/`，操作说明进 README 或 `docs/operations/`，评估方法与契约进模块页或 `docs/specs/`，交接文档不进仓库。

## 命名

主题文件用小写连字符，目录入口用 `INDEX.md`，ADR 用四位编号加小写主题，验收记录带日期后缀。源码引用用稳定文件路径与符号名，不用行号。
