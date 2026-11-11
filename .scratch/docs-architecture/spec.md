# 文档架构整理

Status: claimed

本文是这次整理的唯一计划：2026-11-11 文档审计发现的问题（§1）、与用户讨论后确定的决定（§2）、
目标结构（§3）、票据（§4）、门与停止条件（§5）、不做的事（§6）。
进度写 §7，执行中冒出的需要用户裁定的事项写 §8。goal 原文见 [goal-prompt.md](goal-prompt.md)。

字符数均为 Unicode 字符数（不是字节），由 2026-11-11 的脚本统计；标"未核实"的结论来自抽样。

## 1. 审计发现

规则本身没有问题（三态规则、单一权威），`docs-check` 通过（238 篇、2624 个本地链接、0 断链）。
问题集中在两点：活文档不断累积历史；自动检查只查链接。

### 1.1 体量

已跟踪 Markdown 288 篇，约 284 万字符。`docs/research`（145 万）与 `docs/context`（39 万）占 65%。

| 文件 | 字符 | 行 | 最长行 |
| --- | --- | --- | --- |
| `AGENTS.md`（每个 session 常驻） | 7,621 | 76 | 864 |
| `GLOSSARY.md` | 7,766 | 116 | 532 |
| `docs/INDEX.md` | 9,566 | 119 | 406 |
| `docs/adr/INDEX.md` | 13,880 | 139 | 673 |
| `docs/research/INDEX.md` | 47,341 | 318 | 736 |
| `docs/architecture/INDEX.md` | 13,282 | 144 | 1,321 |
| `docs/architecture/module-boundaries.md` | 19,491 | 86 | 1,664 |
| `docs/specs/bilingual-subtitle-pipeline.md` | 51,461 | 510 | 820 |
| `modules/stt-workers.md` | 22,892 | 119 | 1,967 |
| `modules/translation-subsystem.md` | 21,389 | 105 | 2,261 |
| `modules/batch-orchestration.md` | 20,637 | 115 | 1,253 |
| `docs/context/2026-10-08-hy30-flow-exploration-v2.md`（冻结） | 259,807 | 1,314 | 2,860 |

### 1.2 问题清单

1. **索引写成了摘要，改动最频繁。** `docs/research/INDEX.md` 同时装着规则、时间线（约占 55%）、
   主题目录和验收记录，30 天内改了 72 次。它与 `docs/INDEX.md`、`docs/adr/INDEX.md`、`AGENTS.md`
   四个入口文件出现在 252 次提交中的 101 次。
2. **基线身份多处复述，却没有一页完整定义。** Q3 身份在 `AGENTS.md`（单条 1,322 字符）、
   `GLOSSARY.md`、决定索引（3 行，每格 700–1,050 字符）、调研时间线各写一遍。
   还原现行翻译规则要打开 4–6 篇 ADR（0021、0017、0018、0019、0022、0010）；
   部分取代只靠状态行里的"第 N 点由 ADR-X 替代"。
3. **活文档没有重写到现状。** 模块页状态行本身是变更日志；`translation-subsystem.md` 留着
   2026-11-08 的运行记录（描述已不存在的 llama-server 建表），引用不存在的 `kototoki/llama_server.py`；
   数篇引用已删除的 `docs/changes/*`。330 个反引号路径中共 7 个失效。
4. **规则与实际不符。** `documentation.md` 写 `docs/plans/` 不再新增，但 2026-11-09、11-11 新增 3 篇。
   根因：`.scratch/` 被 `.gitignore` 忽略，想留档的计划没有落点。结果是计划、执行提示词、结果、
   待裁定项合订在一个文件里；研究轮次报告（v10、v13、v15 各约 2.6–2.8 万字符）同理。
5. **活文档、冻结证据、失效设计无法区分。**
   - 5 篇 `docs/specs/subtitle-translation-*.md`（draft，2026-10-06/07）仍称 Hy-MT2 为"当前基线"。
   - 现行 Claude 裁判方法只在 `docs/plans/claude-judge-profile.md`（被归为"计划历史"，且无入链）
     和 `experiments/translation_v3/README.md` 里；活文档讲的仍是 Codex 时代流程。
   - `docs/testing/` 混着活契约、带日期冻结记录、被代码按 sha256 校验的文件，没有目录级状态表。
   - `experiments/` 约 38 个包没有状态登记；README 首行是否写状态不一致。
6. **单文档过大、职责混杂。** 技术设计含跨模块契约（§2–6）、配置参考（§10，约 1/4）、
   环境与布局（§7）、草案验收（§9）、里程碑（§12）、评审修订记录（§13）。
   改一个 translate 行为要先读约 4.5–5 万字符（`AGENTS.md`→架构总览→模块边界→模块页）。
7. **巨型冻结文件没有护栏。** v2 台账"只按节读取"只写在 `AGENTS.md`；`docs/INDEX.md` 对
   `docs/context/*.md` 只有一行，不写大小。另一篇 `2026-10-06-hy30-four-execution.md` 5.9 万字符、仅 11 个标题。
8. **待裁定项分散。** 3 篇计划的 §8、约 11 篇调研报告、3 个索引里都有，没有总表。
9. **状态不可机读。** 除 skills 外无 frontmatter；状态行是带日期和链接的自由文本。
   调研 118 篇中 27 篇前 15 行内没有状态行。
10. **`check_docs.py` 的缺口。** 不查索引登记（调研索引漏 13 个附录文件）、不查孤儿、不查大小、
    不查反引号路径、不查 `kototoki/` 模块是否有页面归属；跳过 `docs/archive/`（那里有 16 个断链）；
    不扫 `experiments/**/README.md` 与 `.claude/skills/`。
11. **其他。**
    - `AGENTS.md` 触发表"翻译基线"一行指向 8 篇文档；"运行命令"一行指向 5 篇；有两行是已结题主题。
    - `docs/INDEX.md` 的"既有文档清单"约 65 条，按登记顺序排列、条目内嵌状态散文，部分已过期。
    - `AGENTS.md` 必读的 `docs/testing/validation.md` 被 `experiments/run_round2.py` 取 sha256，
      内容停在 2026-10-05，无法原地更新。
    - 测试分层规则在 `docs/agents/testing.md`、`workflow.md`、`validation.md` 三处，
      `workflow.md` 里还写着会变的用例数与耗时。
    - `kototoki/strata.py`、`guard.py`、`embedded.py`、`judge.py`、`local_client.py` 没有明确的模块页归属（未核实）。
    - `GLOSSARY.md` 基线身份、`CODING_STANDARDS.md` 项目特定、`validation.md` 等有整段英文规则。
    - 孤儿：`docs/plans/claude-judge-profile.md`、四量化附录的 `paired-figure-caption.md`、归档的 Codex AGENTS。

### 1.3 不能动的文件

- 冻结证据：`docs/research/20*`（含附录）、`docs/research/acceptance/*`、`docs/context/*`、
  ADR 正文（只追加状态行）、`docs/plans/*`、`docs/testing/2026-*`、`docs/archive/**`、
  `AGENTS.md` 列出的 Codex 时代翻译裁判链。
- 被代码校验字节的：`docs/testing/evaluation-config-v1.md`、`stt-evaluation.md`、`fatestay-reference.md`、
  `validation.md`，`docs/development/inference-selection.md`，
  `experiments/translation_corpus/reference-review-prompt.md`、`reference-adjudication-prompt.md`。
- 上面这份名单不保证完整：**改任何既有文件前**，先在 `experiments/`、`scripts/`、`kototoki/`、
  `kototoki_eval/`、`tests/` 里搜该文件名，确认没有 sha256 或内容断言。

## 2. 已定决定（用户 2026-11-11）

1. **方案 B：`.scratch/` 纳入 Git，原地不改名。** 它本来就是 Matt skills 的本地票据库；
   忽略规则是本项目 2026-10-12 导入时自己加的，上游没有这个要求。
   纳入后计划写 `.scratch/<slug>/spec.md`，`docs/plans/` 真正不再新增；已有 22 篇原位冻结，不回迁。
2. **不加登记表**（不引入 `manifest.toml`，索引继续手写）。
3. **不加 Stop hook。**
4. 自动维护只靠扩展 `scripts/check_docs.py`（标准库，已在 `gate-core` 内）。
5. 不移动、不改写任何冻结文件；护栏与摘要一律用新文件。

## 3. 目标结构

### 3.1 四层

| 层 | 内容 | 预算 |
| --- | --- | --- |
| L0 常驻 | `AGENTS.md` | ≤ 4,500 字符 |
| L1 路由 | 各目录 `INDEX.md`：每行一句话加链接，不写结论、不写数字 | ≤ 150 行，单行 ≤ 400 字符 |
| L2 活正文 | 模块页、现行定义页、`docs/development/`、`docs/agents/` | ≤ 12,000 字符，单行 ≤ 800 字符 |
| L3 冻结证据 | 调研、台账、ADR 正文、旧计划、已结题票据 | 不限；只经 L1 的一行进入 |

### 3.2 各类内容的唯一落点

| 内容 | 落点 | 状态 |
| --- | --- | --- |
| 计划、票据、执行提示词、验收脚本 | `.scratch/<slug>/` | 进行中可改；结题后整目录冻结 |
| 研究轮次的结果与结论 | `docs/research/` | 冻结 |
| 产品改动的验收记录 | `docs/research/acceptance/` | 冻结 |
| 现行基线与产品配方的完整定义 | `docs/adr/CURRENT.md` | 活 |
| 待用户裁定的事项 | `docs/pending-decisions.md` | 活 |
| 已实现行为 | 模块页 | 活，只写现状 |

## 4. 票据

按编号顺序做；每张一次提交。票据文件建在 `issues/`，写 `Status`、`Type`、`Blocked by`、
`## 执行记录`、`## Answer`。01–08 只新增文件或瘦身入口；09–11 重写活正文，风险更高。

### 01 `.scratch/` 纳入 Git

- 删 `.gitignore` 的 `.scratch/` 行，提交现有全部文件。
- 提交前扫一遍：密钥、连续多行的转写或字幕原文。2026-11-11 预扫结果：无密钥；
  8 个文件 14 处连续假名，都是行内短例（专名写法、单句幻觉样例），与 `docs/research/` 已有做法同一水平，
  按放行处理。若发现连续 3 行以上的对白，该文件先不提交，记 §8。
- 改 `docs/agents/issue-tracker.md`：写明已纳入 Git、结题后整目录冻结、spec 即计划。
- 改 `docs/agents/documentation.md`：三态规则的"本次增量"落点、"既有目录"一节、落点表；
  删掉"计划只能进 tracker 但 tracker 不进 Git"的矛盾。
- 门：`git status` 干净；`.scratch/` 下无 `.py` 以外的非 Markdown 文件。

### 02 `docs/adr/CURRENT.md`

- 内容：翻译基线 Q3、产品翻译、产品建表、STT（W0／X0）、专名、ASR 复读守卫，
  各自的完整现行定义（配方 id、hash、模型与启动方式、权威 ADR 及条款）。
  对 5 篇部分被取代的 ADR（0010、0014、0015、0017、0018）列出仍有效的条款。
- 来源只能是 ADR 正文与决定索引现有文字；逐项对照，不改写含义，不补推断。
- 决定索引的"当前有效决定"表每行压到一句话加权威链接，长内容移到 `CURRENT.md`；
  "更新于"那条变更日志移到页尾独立一节。
- 更新"记录新决定"步骤：新决定同时改 `CURRENT.md`。
- 门：`CURRENT.md` 中每个 hash、配方 id 都能在某篇 ADR 正文里逐字找到。

### 03 瘦身 `AGENTS.md` 与 `GLOSSARY.md`

- `AGENTS.md` 保留：语言、设计与交付、产品不变量、重任务与环境、委派、触发表。
  "冻结证据与基线身份"压成：冻结证据只读；现行决定看 `CURRENT.md`（翻译基线 Q3）；
  `reasoning_effort:no_think` 不批量替换；不自动选用"翻译多次再挑选"（ADR-0008）；
  已开封确认集与已结题研究线不重开。沿革细节下沉到 `CURRENT.md` 或决定索引。
- 触发表合并到约 10 行；"翻译基线"行指向 `CURRENT.md`；已结题主题并成一行指向调研索引；
  测试必读入口改为 `docs/agents/testing.md`（`validation.md` 降为历史补充）。
- 待填标记那条：先跑 `documentation.md#待填标记` 的命令。只剩发布流程那 1 个时，
  常驻条目移到 `documentation.md`，`AGENTS.md` 不再占一条。
- `GLOSSARY.md` 基线身份：每个术语一条，一句定义加链接；整段英文改中文。
- 下沉的每一条规则必须能在目标位置找到，不能丢规则。完成后在 §7 列"原条目 → 新位置"对照表。
- 门：`AGENTS.md` ≤ 4,500 字符；对照表无遗漏。

### 04 拆调研索引

- `docs/research/INDEX.md` 只留：规则（约 10 行）、"按主题的现状"表（约 12 行）、
  "轮次登记"表（轮次、日期、所属线、状态、一句话、报告链接）、子索引与验收记录链接。
- 时间线原文移到 `docs/research/timeline.md`，不在默认阅读路径上。
- 主题目录的长条目分到子索引（建议 `docs/research/topics/` 下 5–6 篇：STT 组件与基线、
  VAD 与对齐、翻译模型与量化、翻译流程 v1–v8、Q 线 v9–v13、ASR 稳健性与专名）。
- 条目文字搬迁时不改含义；每个报告文件在某个索引里恰好登记一次；13 个附录文件补登记。
- 所有指向 `research/INDEX.md#决定与探索时间线` 的活链接改到新位置；
  冻结文件里的旧锚点保留可用（在 INDEX 留同名小节，一句话指向 `timeline.md`）。
- 门：顶层索引 ≤ 150 行、单行 ≤ 400 字符；`docs-check` 通过。

### 05 护栏与状态索引（全部是新文件）

- `docs/context/INDEX.md`：每篇的字符数、标题数、一句用途、"禁止整读，先 grep 标题"；
  对两篇大台账给出节地图（标题列表）。
- `docs/testing/INDEX.md`：每篇标明活契约／冻结记录／被校验（列出校验它的代码路径）／已被取代及后继。
- `docs/plans/INDEX.md`：22 篇的状态（done／stopped／superseded）与对应结果文档，注明本目录冻结。
- `docs/specs/INDEX.md`：技术设计、W0／X0 契约为现行；5 篇 `subtitle-translation-*` 标 superseded。
  这 5 篇确认未被校验后，状态行改为 `superseded`（只改状态行）。
- `experiments/INDEX.md`：每个包的状态（可复用入口／冻结轮次／回归参照／Codex 时代历史）、
  对应调研或 ADR、是否加载模型。
- `docs/INDEX.md`：删"既有文档清单"，"项目特有入口"表改为指向上述目录索引；保留各行的保留原因。
- 门：每个目录索引覆盖本目录全部文件。

### 06 `docs/pending-decisions.md`

- 汇总仍未裁定的事项：主题、提出日期、来源（文件与节）、选项、状态。
- 来源：3 篇新计划 §8、v7–v15 报告的待裁定节、决定索引"未关闭项"。原文不动，只抄录并链接。
- 逐项对照 ADR 与决定索引判断是否已裁定；判断不了的标"待用户确认是否仍开放"，不自行关闭。
- 决定索引"未关闭项"改为指向本页。

### 07 现行翻译评估方法页

- 新建 `docs/agents/translation-evaluation.md`：现行裁判 profile、入口命令、哪些分数不可混用、
  哪些是冻结的 Codex 时代流程。来源：`docs/plans/claude-judge-profile.md`、
  `experiments/translation_v3/README.md`、v5 之后各轮报告的方法节。
- 该 profile 在计划里的状态是 superseded：先核实现行方法到底是什么；核实不了就把矛盾写进 §8，
  页面只写能确认的部分。
- `AGENTS.md` 触发表与 `docs/testing/INDEX.md` 指向它。

### 08 扩展 `scripts/check_docs.py`

新增检查，全部用标准库；每项给出文件与行号：

| 检查 | 级别 |
| --- | --- |
| `docs/` 下每篇 `.md` 至少被一个 `INDEX.md`（或其子索引）链接 | 错误 |
| `experiments/` 每个包目录出现在 `experiments/INDEX.md` | 错误 |
| 预算（§3.1）：`AGENTS.md`、各 `INDEX.md`、L2 活正文 | 错误；现有超标文件记入脚本内白名单并写当前字符数，只许降不许升 |
| 活文档里反引号包住的仓库路径存在 | 错误 |
| `kototoki/` 每个模块或子包出现在某模块页的"代码与验证入口" | 错误 |
| 活文档状态行含 3 个以上日期 | 警告 |
| ADR 文件、决定索引"全部 ADR"表、"编号从 N 起"三者一致 | 错误 |
| 扫描范围加入 `experiments/**/README*.md`、`.scratch/**/*.md` 的链接（不计预算） | 错误 |

- 冻结保护不做成 diff 检查（需要比较基线，复杂度不值）；靠 §1.3 的规则与目录索引里的标注。
- 为新检查写离线单元测试，归 core 层；`docs/development/workflow.md` 同步命令说明。
- `docs/archive/` 继续跳过链接检查，在脚本注释里写明原因。
- 门：`just gate-core` 通过。

### 09 拆技术设计

- `docs/specs/bilingual-subtitle-pipeline.md` 只留跨模块契约：§1.1 配方、§2–6。
- §10 配置参考并入 `modules/config-and-media.md`（超预算就单独成页）。
- §7 中环境、布局、上游版本核实：已在 `docs/development/` 的删掉留链接；不在的搬过去。
- §1.2 已裁定表改为指向 ADR 与 `CURRENT.md`。
- §9、§12、§13 与状态行里的修订历史：原文存为一篇新的冻结记录
  `docs/research/<执行日期>-bilingual-pipeline-spec-history.md`，技术设计里留一行链接。
- §8（内容为"无"）删除；§11 未来方向留一句指向 `pending-decisions.md` 或票据。
- 技术设计与模块页冲突时以代码为准核对，按 `documentation.md` 三态规则处理，不静默取其一。
- 门：技术设计 ≤ 15,000 字符；被删的每一节在 §7 记录去向。

### 10 模块页重写到现状

- 对象：`translation-subsystem`、`stt-workers`、`batch-orchestration`、`name-consistency`、
  `config-and-media`、`stage-plan`、`artifact-contract`。
- 状态行只写 `current` 与权威 ADR；"变更与决策来源"只列链接。
- 带日期的运行记录与验收数字：已在 `docs/research/acceptance/` 或计划里的删掉留链接；
  不在的先存为新的验收记录再删。
- 修掉 7 个失效路径；`workflow.md` 删掉会变的用例数与耗时。
- `kototoki/strata.py` 单独成页；核实 `guard.py`、`embedded.py`、`judge.py`、`local_client.py` 的归属并补上。
- 仍超预算的页按职责拆（候选：翻译子系统拆出 Strata 生命周期；STT worker 按 VAD／ASR／对齐）。
- 只删历史叙述和重复，不删行为规则；每条行为规则对照代码或测试，对不上的记 §8，不改代码。
- 门：票据 08 的预算与路径检查通过，白名单里这几页清零。

### 11 架构总览与模块边界

- `docs/architecture/INDEX.md` 顶部放紧凑模块表：模块、代码路径、页面、80 字以内职责；
  产品页与研究冻结页分两张表；加"任务 → 模块页"表（约 10 行，覆盖产品包常见改动）。
- 导语压到 3 行，删掉复述 ADR 的段落。
- `module-boundaries.md` 只留依赖方向、规则与接缝；逐模块职责与模块表重复的部分删掉。
- 每个 `kototoki/<pkg>/__init__.py`（及顶层主要模块）的 docstring 加一行指向模块页。只改 docstring。
- 门：两页进预算；`just gate-core` 通过。

### 12 收尾

- 跑 `just gate-core`；填 §7（各票据结果、关键文件的前后字符数）；§8 列全待裁定项。
- 更新 `docs/INDEX.md` 冷启动路径与入口分工；本 spec 状态改 `resolved`。

## 5. 门与停止条件

- 每张票据提交前：`just docs-check` 通过（票据 08 之后是扩展后的版本）。
- 09–11 每张提交前：`just gate-core` 通过。
- 全程不占 GPU、不加载模型、不跑 `uv sync|add|lock`、`just setup|install|upgrade`、`just smoke` 与任何 demo。
- 在分支 `docs-architecture` 上工作，不 push。
- 停止并写 §8：要改的文件被代码校验；`CURRENT.md` 的某项在 ADR 之间找到矛盾；
  模块页规则与代码对不上；任何需要改 `kototoki/` 代码逻辑才能过门的情况。
  一张票据停下不影响其余无依赖的票据继续。
- 子 agent：按 `AGENTS.md` 委派规则，`model` 显式指定，默认 `sonnet`；09–11 的核对可用 `opus`。
  写入者文件不重叠；`AGENTS.md`、各 `INDEX.md`、`check_docs.py` 归主 agent。

## 6. 不做的事

- 不移动、不重命名、不改写冻结文件（§1.3）；ADR 只追加状态行。
- 不引入登记表、frontmatter 体系、Stop hook、第三方依赖、CI 配置。
- 不给每一轮研究补摘要卡；不重写旧调研报告的状态行。
- 不改 `.scratch` 的名字；不回迁 `docs/plans/` 的 3 篇新计划。
- 不改 `kototoki/` 的代码逻辑（只改 docstring）；不改测试行为（只为 `check_docs.py` 加测试）。
- 不改 `.claude/skills/` 的内容，除非其中写了与票据 01 矛盾的"票据不进 Git"字样（已查，当前没有）。
- 不开新的研究轮次，不裁定任何待裁定事项。

## 7. 进度与结果

分支 `docs-architecture`，2026-11-11 开始执行。

### 7.1 票据

| 票据 | 状态 | 结果 |
| --- | --- | --- |
| [01](issues/01-scratch-into-git.md) | resolved | `.scratch/` 197 个文件纳入 Git；扫描无密钥、无连续对白；两篇规则已改 |
| [02](issues/02-adr-current.md) | resolved | 新增 `docs/adr/CURRENT.md`（约 8,500 字符）；决定索引的现行表压成每行一句话，变更日志移到页尾"更新记录"；ADR 之间的不一致记 §8 第 1–3 项 |
| [03](issues/03-slim-agents-glossary.md) | resolved | `AGENTS.md` 7,621 → 4,317 字符，触发表 18 → 11 行；`GLOSSARY.md` 基线身份每条一句；"原条目 → 新位置"对照表在票据文件里 |
| [04](issues/04-split-research-index.md) | resolved | 调研索引 47,341 → 4,979 字符；时间线移到 `timeline.md`，条目分到 `topics/` 7 篇子索引；117 篇报告各登记一次，14 篇附录补登记 |
| [05](issues/05-guardrail-indexes.md) | resolved | 新增 `docs/context`、`docs/testing`、`docs/plans`、`docs/specs`、`experiments` 五个索引；5 篇翻译草案状态行标 superseded；`docs/INDEX.md` 9,566 → 2,980 字符 |
| [06](issues/06-pending-decisions.md) | resolved | 新增 `docs/pending-decisions.md`：未裁定 2 项、待确认是否仍开放 9 行、已裁定对照 15 行；决定索引"未关闭项"改为指向该页 |
| [07](issues/07-translation-evaluation.md) | resolved | 新增 `docs/agents/translation-evaluation.md`（5,875 字符）：现行是两个 Claude 裁判 profile；核实不了的 5 点记 §8 第 5 项 |
| [08](issues/08-extend-check-docs.md) | resolved | `check_docs.py` 新增登记、预算、反引号路径、模块归属、ADR 编号 5 类错误检查与状态行告警，扫描 253 → 486 篇；15 个单元测试；`just gate-core` 通过 |
| [09](issues/09-split-tech-design.md) | resolved | 技术设计 51,461 → 12,336 字符；配置参考拆成 `modules/config-reference.md`，历史原文存为冻结记录；与代码对不上的 7 处记在票据文件，需用户知道的记 §8 第 6 项 |
| [10](issues/10-rewrite-module-pages.md) | resolved | 7 篇模块页重写到现状并进预算（如翻译子系统 21,389 → 11,858、STT worker 22,892 → 9,080、批次编排 20,637 → 11,993）；拆出 Strata session、STT ASR、运行日志与进程 3 篇新页；3 篇冻结记录保存移出的原文；与代码对不上的 12 处记在票据文件，§8 第 7 项 |

## 8. 待用户裁定

1. **已发布影片在翻译身份变化后会不会重新发布（票据 02）。** ADR-0019 第 5 点写"已发布影片因 `sources` 不再匹配，下次整批运行重新翻译并发布"，
   ADR-0010 第 9 点写"配方 hash 变化即该影片 translate 阶段身份过期，整批运行时重译并重新发布"；ADR-0020 第 4 点写
   "源文件旁已有 `<主名>.ja-zh.srt` 即跳过该文件，不进任何阶段"。0019 与 0020 同为 2026-11-08 采纳，状态行没有互相说明，
   只有 ADR-0022"影响"一节写了"已发布的影片按 ADR-0020 跳过"。`CURRENT.md` 只写了 0020 的"已存在即跳过"。
   请裁定：是否在 0019、0010 的状态行追加"重新发布由 ADR-0020 第 4 点替代"。
2. **v15 重开的结论没有进 ADR 正文（票据 02）。** ADR-0014 状态行仍写"是否进产品待 v15 结题后另立 ADR"；
   "2026-11-11 用户裁定该替换不进产品"只在决定索引与（整理前的）`AGENTS.md` 里。`CURRENT.md` 引决定索引写了这一句。
   请裁定：是否在 0014 状态行追加这次裁定。
3. **几篇 ADR 正文里已过时、但状态行没有标出的句子（票据 02）。** `CURRENT.md` 都没有采用这些句子，只在此列出：
   - ADR-0021 正文"产品 `BUILD_RECIPE_HASH`（`5b8d1b76…`）不变"在 0022 之后不成立；`q3-names-v1` 的 hash 没有写进任何 ADR（0022 只说由测试钉住），`CURRENT.md` 因此没写这个 hash。
   - ADR-0007 第 4 点、ADR-0008"约束"一节仍称产品配方为 `dp10-cut-degrade-v1`（0019 已替代）。
   - ADR-0015 第 3 点的 `kototoki.llama_server.ManagedServer` 与"与产品 names 阶段同一模型与 server 参数"（0025、0022 之后不成立）；第 2 点"H0 链在发布时跑专名替换"。
   - ADR-0014 第 2 点的替换子项、第 4 点末句"替换阶段异常使该影片 publish 失败"、第 10 点前半句（随 0019 删除替换而失效）。
   - ADR-0017 第 2 点的对照对象（经 0018 第 2 点、0021 改为 Q3），状态行没说。
   请裁定：是否逐篇在状态行追加说明（只追加，不改正文）。
4. **`docs/pending-decisions.md` 里 9 行"待用户确认是否仍开放"（票据 06）。** 来源报告写着待裁定，但没有 ADR 或决定索引的明确裁定：
   v5 §8 第 1–2 项、v6 第 1–3 项、v7 第 3–4 项、v9 第 3 与 6 项、v10 第 5 项、v11 第 2 项与第 5 项、v14 第 11 项、声学裁判线后续。
   请逐项确认是否仍开放；确认关闭的从该页删行。
5. **现行翻译评估方法里核实不了或没有定论的地方（票据 07）。** `docs/agents/translation-evaluation.md` 只写了能确认的部分：
   - 裁判提示从 prompt-v1 改到 prompt-v2 时 profile 名没变（`experiments/translation_v3/README.md`），而 v3 计划 §4.2 写"提示一变就是新版本"。
     有没有哪一轮把两版提示的分数放在一起比过，没有查到。
   - `v5-asr-pairwise-v1` 没有 profile hash 与版本字段，只在报告里记系统提示的 sha256；这算不算足够的版本身份，没有定过。
   - 备用执行面（子 agent 读导出包）固定不了具体模型（Agent 工具只接受别名）；有没有哪一轮真的用它评过分，没有查到。
   - 新轮次没有可复用入口：`experiments.scene_batching_v6` 的 `--round` 只到 v13，v15 另建了包。
   - "人名相关错误"的关键词表在 `experiments/scene_batching_v6/asr10.py` 与 `experiments/scene_batching_v6/v9.py` 里不一样，页面没有指定用哪个。
   请裁定：这几点是否需要定规矩（例如成对 profile 补版本身份、指定人名错误口径），还是保持现状。
6. **技术设计拆分时发现的、文档之外的过时文字（票据 09）。** 文档侧已按代码改好，下面几处不在本次可改范围内：
   - `kototoki.toml.example` 的 `[stt] engine` 注释写 `# w0 | x0`，代码还接受 `cross`。
   - `scripts/upgrade.py` 的输出文字与 `docs/development/dependencies.md` 里写"规格 §7.2 的配置示例"；§7.2 已拆出，原来那里也没有配置示例。
     改脚本输出属于改代码，没有动；文档那一句是在描述脚本输出，也没有单独改。
   - `docs/development/dependencies.md` 有一行超过 800 字符（表格里的长单元格），不在票据 09–11 的对象里，
     现记在 `check_docs.py` 的白名单里封顶（`workflow.md` 的长行已在票据 10 拆开）。
   请裁定：是否另开一张小票据改示例文件注释、脚本输出文字，并把这行长单元格拆开。
7. **模块页重写时发现的规则与代码不一致（票据 10）。** 页面都已按代码写或改成中立说法，全部 12 处见
   [票据 10](issues/10-rewrite-module-pages.md#规则与代码对不上的地方)；其中两处是"旧文档写的规则代码没有做"，哪边算对需要裁定：
   - 旧产物契约页写"判定为已有字幕而跳过时删除 `failure.json`"；`kototoki/job.py` 扫描到已有字幕时直接跳过，旧的 `failure.json` 留在工作目录。
   - 旧批次编排页写"只有翻译重启与放弃两行把异常首行截到 200 字符"；代码在批次尝试失败行、`Strata refused` 行、names 尝试行也截断。
   请裁定：这两处是按代码现状定规则（页面补写明），还是改代码。
