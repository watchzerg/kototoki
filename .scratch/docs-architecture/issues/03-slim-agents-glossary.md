# 03 瘦身 `AGENTS.md` 与 `GLOSSARY.md`

Status: resolved
Type: task
Blocked by: 02

范围见 [spec §4 票据 03](../spec.md#03-瘦身-agentsmd-与-glossarymd)。

## 执行记录

- `AGENTS.md` 7,621 → 4,317 字符（76 → 65 行，最长行 864 → 382）。保留语言、设计与交付、产品不变量、重任务与环境、委派原文；
  "冻结证据与基线身份"改名"冻结证据与现行决定"并压成 5 条；触发表 18 行并成 11 行。
- 待填标记：按 `documentation.md#待填标记` 的命令搜索（排除 `.scratch/`），只剩 `docs/development/workflow.md` 的发布流程 1 个。
  常驻条目移到 `documentation.md`"随交付同步"第 6 步，"待填标记"一节同步改写。
- `GLOSSARY.md` 7,766 → 5,238 字符：基线身份每个术语一句定义加 ADR 链接，W0、X0 与页尾 CLI 旧默认一句由英文改中文；
  "Translation baseline"并入 **H0**（列入 `_Avoid_`）。其余小节未动。
- 决定索引"记录新决定"里对 `AGENTS.md` 小节名的引用同步改名。
- 改前搜过代码：`AGENTS.md`、`GLOSSARY.md` 只被 `scripts/check_docs.py` 当作必须存在的文件，另有
  `experiments/translation_judge/test_runner.py` 断言某临时目录里没有 `AGENTS.md`，都不校验内容。

### 原条目 → 新位置

| 原 `AGENTS.md` 条目 | 新位置 |
| --- | --- |
| 待填标记的交付前搜索 | `docs/agents/documentation.md` 随交付同步第 6 步、待填标记一节 |
| 冻结的历史证据只读、Codex 裁判链身份 | 留在 `AGENTS.md`（补了 `docs/plans/*`、已结题 `.scratch/` 与"先搜代码断言"） |
| `reasoning_effort:no_think` | 留在 `AGENTS.md` |
| 现行决定以决定索引为准；唯一基线 Q3；引用 Q2、Q1、Q0、F1、H0 时写明 | 留在 `AGENTS.md`（一句），定义在 `docs/adr/CURRENT.md#翻译基线-q3` |
| Q3 身份细节（Q2 规则、`qwen-wide`＋high 注入、Flash-Next IQ3_S、不加参数 `strata launch`、DFlash2、`names-strata-v4`、最多 5 次请求、不起 llama-server） | `CURRENT.md` "翻译基线 Q3" |
| 前任 Q2、Q1、Q0 的一句身份 | `CURRENT.md` "前任 Q2"与翻译规则表；`GLOSSARY.md` 基线身份 |
| H0 不再是基线、只作历史对照 | `CURRENT.md` 条款表（0018 行）；`GLOSSARY.md` **H0** |
| 产品翻译 `q2-degrade-v1`、建表 `q3-names-v1`、共用 Strata session、不加载 27B、表只注入不替换 | `CURRENT.md` "产品翻译""产品建表""专名" |
| 不自动选用"翻译多次再挑选" | 留在 `AGENTS.md`；`mbr8c`、`mbr8s` 已放弃在决定索引演进链"方法禁区" |
| 专名一致性研究线结题、产品替换已删、`experiments/name_consistency/` 冻结、v15 重开与 2026-11-11 裁定 | `AGENTS.md` 留一句"不提议新轮次"；细节在 `CURRENT.md` "专名" |
| v3、v4、v5 确认集已开封 | 留在 `AGENTS.md`；`CURRENT.md` 对照规则 |
| v2 已停止、台账只按节读、作业不恢复、先验只取 v1/v2 教训 | 留在 `AGENTS.md`（一句）；节地图在票据 05 的 `docs/context/INDEX.md` |
| 触发表：产品包 `kototoki/` 一行 | 并入"设计、修改、实现或 review 代码"一行 |
| 触发表：review 代码质量 | 并入同一行（`CODING_STANDARDS.md`） |
| 触发表：测试必读 `validation.md` | 入口只留 `docs/agents/testing.md`（该页已链接 `validation.md`） |
| 触发表：运行命令一行的 5 篇 | `workflow.md` 加"按需读 `docs/development/` 的对应页" |
| 触发表：读取票据、分类票据两行 | 并成一行 |
| 触发表：查当前有效决定、用户采纳或变更决定、W0／X0／翻译基线身份、翻译基线（8 篇 ADR）四行 | 并成一行，指向 `CURRENT.md` 与"记录新决定" |
| 触发表：查研究轮次、翻译流程探索历史 v3–v8、旧翻译评估三行 | 并入"调研"一行，指向调研索引；v3／v4 的报告、台账与包在调研索引登记；旧评估方法与现行裁判 profile 由票据 07 的 `docs/agents/translation-evaluation.md` 接手 |
| 触发表：测试 W0／X0、运行或修改 W0／X0 两行 | 并成一行；"`x0_flow` 与 `qwen` 只作回归参照"移到票据 05 的 `experiments/INDEX.md` |
| 触发表：选择 STT 引擎、接续旧任务 | 原样保留 |

## Answer

门通过：`AGENTS.md` 4,317 字符（≤ 4,500）；上表逐条核对，没有丢规则。两处依赖后续票据的落点（`experiments/INDEX.md`、
`translation-evaluation.md`）在票据 05、07 完成时核对。`just docs-check` 通过。
