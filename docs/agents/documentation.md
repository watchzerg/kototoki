# 文档维护规则

本文规定文档放在哪里、谁是权威、怎样随交付同步。新增、移动、删除文档或讨论形成明确结论时按本文执行。读者路由在[文档索引](../INDEX.md)，本文不重复"哪篇回答什么问题"。

## 三态规则

每份文档只属于以下一态，不混写：

- **存量当前正文**：描述同一仓库版本的已实现系统，持续改写，每条规则只有一处权威，其他位置摘要加链接。不按迭代追加"本次增量"章节。
- **本次增量**：说明这次改变什么、验收什么、涉及哪些当前正文。产品侧的增量由 issue tracker（Beads）承载：计划是 `epic`，票据是它的子 issue，执行提示词与验收脚本写进 bead（[tracker 约定](issue-tracker.md)）。进行中可改；完工时把已实现的规则写入当前正文、未实现的范围另开 bead，然后关闭。研究轮次的计划写在 `docs/research/<轮次>.md` 里，不建 bead。
- **研究记录**：调研、实验、验收与跑次记录，放 `docs/research/`（[ADR-0038](../adr/0038-setup-project-doc-layout.md)），带时点和适用条件，按 [ADR-0031](../adr/0031-research-layout-and-lightweight-records.md) 精简书写（R2、R3）。冻结靠 git：结题后状态写 `concluded`／`stopped`，修错、修链接、精简随时可以做，原始材料从归档 tag `archive/2026-11-18-pre-research-restructure` 或 git 历史取；代码不对文档做 sha256 自检。正文中的"当前""尚未实施"只描述记录时点。

代码是实际行为的证据，当前正文是预期行为依据。两者冲突时就地记录实现差异并明确修代码还是修文档，不把缺陷改写为正常行为，也不把待实现设计写成现状。

## 取舍原则

当前正文只写读代码得不到的内容，让读者不必通读源码就能判断改动落在哪、要守住什么：

- **保留**：职责与边界、规则与不变量、跨文件的时序与失败收敛、状态与资源归谁、必要的设计理由。
- **不写**：目录树、源文件清单、依赖版本表、逐函数翻译源码、逐个测试覆盖了什么、测试用例名与数量、票据流水、里程碑编号、commit SHA。这些内容代码、锁文件和 tracker 里已有，抄进正文只会过时。
- **不重复**：一条规则只在归属页完整表述，其他页面一句摘要加链接；发现两处表述时合并到归属页，不各自修补。
- **写法**：已实现与已验证分开陈述；尚无内容的章节写一句白话说明，不留空、不编造。

## 讨论结论的落点

讨论形成明确结论时，按结论类型落到唯一位置，不另建会议纪要：

| 结论类型 | 落点 |
| --- | --- |
| 术语的定义或取舍 | `GLOSSARY.md` |
| 难以逆转、事后看不出原因、有真实取舍的决定 | `docs/adr/` 新增一条，并按[决定索引·记录新决定](../adr/INDEX.md#记录新决定)同步 `docs/adr/INDEX.md` |
| 已实现行为或结构的澄清 | 所属模块页或模块边界 |
| 尚未实现的产品需求、范围或计划 | Beads 的 spec（`epic`）与票据；研究轮次的计划写在轮次目录 |
| 评审时反复出现的判断类问题 | `CODING_STANDARDS.md` |
| 工具链、命令、门禁的约定 | `docs/development/` |
| 带时点的比较或实验结果 | `docs/research/<YYYY-MM>-<slug>.md` 并在 [docs/research/INDEX.md](../research/INDEX.md) 登记 |
| 产品批量运行的结果与观察到的问题 | `docs/research/runs/<日期>-<slug>.md` 并在 [docs/research/runs/INDEX.md](../research/runs/INDEX.md) 登记；问题转 `run-finding` bead（[批量运行与跑次记录](production-runs.md)） |

## 权威归属与创建时机

一项信息只有一处权威正文；其他页面摘要并链接。没有实际内容时不建占位页，目录为空时不建目录。

| 信息 | 权威落点 | 创建时机 | 其他页面的责任 |
| --- | --- | --- | --- |
| 跨任务流程约束、按任务读取入口 | `AGENTS.md` | 初始化 | 不复制触发表 |
| 领域术语 | `GLOSSARY.md` | 初始化，第一个术语敲定时填入 | 正文首次出现关键术语时给一句白话解释 |
| diff 评审的判断类标准 | `CODING_STANDARDS.md` | 初始化，随 retro 追加 | 测试专项规则留在 `agents/testing.md`，互链 |
| 冷启动路径、各入口回答什么 | `docs/INDEX.md` | 初始化 | 不含触发表与维护规则 |
| tracker、标签、领域文档约定 | `docs/agents/` 中 Matt setup 产出的三个文件 | Matt setup | 由 `AGENTS.md` 触发表指向，不另建 Agent skills 块 |
| 测试归属、收录、分阶段验证 | `docs/agents/testing.md` | 初始化 | 命令在 `development/workflow.md`，分层与资源合同在 `development/test-layers.md` |
| 系统全貌、模块地图、依赖、不变量 | `docs/architecture/INDEX.md` | 初始化 | README 与文档索引只路由 |
| 职责归属、依赖方向、状态所有者 | `docs/architecture/module-boundaries.md` | 初始化 | 模块页说明如何遵守，偏差就地注明 |
| 某模块的行为规格、实现设计、代码与验证入口 | `docs/architecture/modules/<module>.md` | 该职责首次有可描述的行为和测试时 | 总览只摘要 |
| 跨模块流程 | `docs/architecture/collaborations.md`；超出[体量预算](#体量预算与拆页)时一个流程一页放 `collaborations/` | 流程涉及三个以上模块时 | 只写顺序、等待点与失败收敛；模块页链接参与的流程 |
| 用户可见行为规格 | `docs/behaviors/<topic>.md` | 行为横跨多个模块或有非开发读者时；否则写在模块页 | 模块页引用不重写 |
| 重要决策的背景、选择与后果 | `docs/adr/NNNN-<slug>.md`，状态写 frontmatter | 第一条 ADR 时 | 当前正文采用最终规则；替代旧决定时双向链接 |
| 调研、实验、验收与跑次证据 | `docs/research/<YYYY-MM>-<slug>.md`，验收在 `docs/research/acceptance/`，跑次在 `docs/research/runs/`，登记在 `docs/research/INDEX.md` | 立项时 | 研究记录不冒充当前覆盖 |
| 工具链、命令、门禁、测试分层 | `docs/development/` | 初始化，阶段 3 填入 | 模块页链接测试入口，不复制执行说明 |
| 部署、运行配置、发布与回滚 | `docs/operations/` | 有可部署产物时 | development 链接发布入口 |
| 产品侧计划、票据、执行提示词、验收脚本 | Beads（`bd`） | 立项时 | 完工后结论写进模块页或 ADR，关闭 bead；当前正文可引用 bead ID |

## 模块页模板

按稳定职责划分模块，不要求与源码包一一对应。`modules/` 直接子级的每一页，六个二级标题全部必备且按序，不增不减；某节尚无内容时写一句白话说明（如"本模块没有对外接口"），不删节。节内可自由用三级标题。

```markdown
---
covers:
  - src/<module>/**
---
# 模块名称

## 定位与阅读
开头三项：负责什么；不负责什么（附归属页链接）；何时读本页。其后列上级总览、依赖模块、相关规格。

## 当前行为规格
入口与前置条件、输入输出、正常流程、状态转换、不变量；失败、取消、重试、恢复及用户可见行为。用户可见的部分按行为规格模板的四个标题作三级小节。

## 实现设计
关键协作、状态与资源所有权、事务与时序、外部副作用；必要设计理由及 ADR 链接。

## 接口与依赖
调用者必须知道的语义，以及其他模块负责的规则链接。

## 代码与验证入口
入口文件与符号、从哪条命令或哪个测试目录验证、已知限制和未验证范围。不列源文件清单、测试用例名与数量。

## 变更与决策来源
已吸收的 ADR、调研、增量规格与票据编号；只用于追溯，不写过程流水。没有时写"本页没有吸收的决策或调研"。
```

页首 `covers` 列出本页描述的源码，供 `just docs-affected` 按改动提示该看哪页；它是机器读的范围声明，不是给读者的源文件清单。每项是相对仓库根的 glob，`**` 跨目录，匹配到目录时算其下全部文件；frontmatter 只写 `covers:` 与其下的 `- 项`。只认领本页真正描述的范围，`src/**` 这类宽泛范围会让每次改动都命中本页，提示随之失效。拆页后由描述该源码的子页认领。代码移动或删除时同步改，每项至少匹配一个现存文件。

## 行为规格模板

`docs/behaviors/` 直接子级的每一页，四个二级标题全部必备且按序，不增不减；模块页“当前行为规格”里用户可见的部分用同一骨架。它从用户视角描述系统做什么、之后能观察到什么，让读者不看代码也能判断一个行为是否符合描述。它是功能描述，不是测试用例：不写测试步骤编号、测试数据或通过判定，可观察结果只写文档层面能承诺的事实。

```markdown
# 行为主题

## 场景与前提
谁在什么情况下使用；进入前系统应处于的状态（数据、登录态、配置）。

## 操作与可观察结果
按用户操作分三级小节：用户做什么；随后在界面或命令输出、持久化数据、文件与外部副作用上能观察到什么。

## 边界与错误情况
输入边界；失败、取消、重试时用户看到什么、系统留下什么。

## 相关模块
实现它的模块页，每项一个链接加一句职责；跨模块流程链接 `collaborations.md`。
```

行为规格不出现锁、表与列名、内部诊断码等实现细节，这些写在模块页。多个主题共有的行为只在一个页面完整表述，其余页面只写差异并链接。

## 体量预算与拆页

预算约束的是单个任务必须读入的量，不是文档总量。`docs/research/` 与 `docs/adr/` 豁免，其余文档：

- 单页不超过 16 KB。
- 一行（一段或一个列表项）、一个表格单元格不超过 400 字符。

超限时 `docs-check` 失败。不设逐页豁免，只能按[取舍原则](#取舍原则)精简，或拆页：

- **模块页**：原路径保留为枢纽页，六节俱全，只留定位、子页表（子页与何时读）和各子页共用的接口与依赖；子页放同名子目录 `modules/<module>/<topic>.md`，首句写"`<模块>` 的子页：…"，分节自由，末尾保留"代码与验证入口"。
- **行为规格**：同样保留原路径为枢纽页，子页放 `behaviors/<topic>/`；两个子页说法冲突时以谁为准，写在枢纽页。
- **跨模块流程**：`collaborations.md` 保留为流程表，每个流程一页放 `collaborations/`。
- 其他页面按读者任务拆成并列的页，在原页面留链接。

拆页或移动后改全部引用，不留重定向页；历史证据里的引用只改链接目标。

## 随交付同步

1. 动手前从架构总览找到受影响模块，读其当前正文及本次所需的依赖章节。总览仍是 `<待填>` 而代码已存在时，本次任务先补模块地图中与改动相关的行，再动手。
2. 每个可交付切片完成时，改写受影响模块的完整当前行为与设计；删除失效条款。某职责的行为首次被测试覆盖，就按模板建模块页并加入模块地图，不以"还不够成熟"推迟；新增或拆分模块时同步模块边界。用户可见功能新增、移除、改名，或其行为规格换了位置时，同步功能地图的对应行。
3. 术语变化更新 `GLOSSARY.md`；满足 ADR 条件的决策新增 ADR 并登记索引；调研结论被正文吸收或被取代时更新调研索引的状态；使用方式改变时更新 README 或 `operations/`。
4. 完成前运行 `just docs-affected`（改动已提交时传基准，如 `just docs-affected main`），对标为"本次未修改"的页逐一判断：需要就更新，不需要就在交付说明写明判断。它只提示，不属于门禁。交付说明列出已更新文档与验证范围。无文档影响时说明判断，不机械改动。
5. 新增、移动或删除文档时同步 `docs/INDEX.md`、所属目录索引及所有引用；仅当新文档成为某类任务的必读入口时才改 `AGENTS.md` 触发表。完成后运行 `just docs-check`。
6. 每次交付前按[待填标记](#待填标记)的命令搜索剩余标记：标记注明的时机已到，或本次任务产生了对应内容，就填写并删除标记；否则原样保留，不编造。

## 自动检查

`just docs-check`（`scripts/check_docs.py`）属于 `gate-core`，检查下列各项，任何一项不符即失败。规则正文只写在本文，脚本只实现；调整规则时两处同步改。

- 本地链接的目标存在，章节锚点可解析。
- 根目录四份文档与 `docs/` 下全部 Markdown 都能从 `AGENTS.md` 沿链接到达。
- `docs/adr/` 与 `docs/research/` 下每个文件都被本目录 `INDEX.md` 直接链接。
- [体量预算](#体量预算与拆页)。
- [模块页](#模块页模板)与[行为规格](#行为规格模板)的二级标题骨架。
- 页首 `covers` 的每项至少匹配一个现存文件。

它查不出正文过时：正文与代码是否一致仍靠[随交付同步](#随交付同步)（含 `docs-affected` 的提示）与 code-review，或定期运行 `/docs-audit` 抽页对照源码核对。

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

填写后删除整个标记；内容尚不存在时保留，不编造。

## 项目约定

本项目在上述规则之外的补充约定（原 `docs/INDEX.md` 的文档约定中与本文不冲突的部分）：

- Keep `lower-kebab-case.md` filenames. 研究轮次 `YYYY-MM-<slug>.md`，验收记录 `<topic>-<YYYY-MM-DD>.md`，跑次记录 `YYYY-MM-DD-<slug>.md`（[ADR-0038](../adr/0038-setup-project-doc-layout.md)）。
- Give each substantive document a title, status, and scope. Add related links where applicable.
- Use category-appropriate statuses: specs may be draft/accepted/implemented;
  research exploratory/concluded. State limitations and open questions explicitly.
- Research must include source links, access dates, relevant versions, and a
  distinction between observations and inferences. Experiments and evaluation
  records state the model, engine version, hardware and the kind and size of the
  test data (R2); they do not carry file hashes, local absolute paths or per-item
  detail (R3).
- ADRs use `NNNN-short-title.md`, starting at `0001`. Status is one of
  proposed/accepted/rejected/superseded. Mark acceptance only when the decision has actually been
  adopted; record the basis. Supersede accepted decisions with a linked new ADR
  rather than rewriting their history; on the old ADR only append to the status line
  (fixing links in an ADR body is allowed, ADR-0031).
  `docs/adr/INDEX.md` is the one living page: update its current-decisions table,
  evolution chain and ADR list in the same commit as the new ADR.
- Plans and research do not supersede requirements by themselves. For conflicts,
  identify the applicable scope and linked superseding decision rather than assuming
  the newest file overrides every older document.
- Keep private recordings, transcripts, model weights, secrets, and large
  generated outputs outside documentation and Git. Link reproducible procedures
  and permitted artifact locations instead.

## 命名

主题文件用小写连字符，目录入口用 `INDEX.md`，ADR 用四位编号加小写主题，验收记录带日期后缀。源码引用用稳定文件路径与符号名，不用行号。
