# 11 架构总览与模块边界

Status: resolved
Type: task
Blocked by: 10

范围见 [spec §4 票据 11](../spec.md#11-架构总览与模块边界)。

## 执行记录

- `docs/architecture/INDEX.md` 由主 agent 重写：13,282 → 8,582 字符，最长行 1,321 → 180，147 行。
  - 导语 3 行，不再复述 ADR，现行决定指向 `docs/adr/CURRENT.md`。
  - 模块地图分"产品包"（12 行）与"研究与 demo"（9 行）两张表：模块页、代码路径、80 字以内职责。`#模块地图` 锚点保留（3 处链接）。
  - 新增"按任务找模块页"表（15 行，其中 12 行是产品包常见改动）。
  - 历史实验 README 清单删掉，改指 `experiments/INDEX.md`（票据 05 已逐包登记）。
  - 依赖段删掉带日期的"5 个研究包 27 个文件"计数与已删除设计稿的经过；规则指向模块边界。产品依赖图里 13 条指向基础层的箭头合成一行，图的内容不变。
  - 系统不变量逐条保留，长条目拆短；产品目录位置限制的细节指向批次编排页。
- `docs/architecture/module-boundaries.md` 委派给子 agent（`opus`）：19,491 → 11,078 字符，最长行 1,664 → 476。
  - 只留依赖方向、规则、状态与契约、并发与生命周期、产品包的责任边界与接缝；逐模块职责（原 25 行大表）改成"规则 → 模块页链接"的短条目。
  - 四个被链接的标题（`依赖方向`、`状态与契约`、`并发与生命周期`、`产品包的责任边界`）原样保留。
  - 历史叙述、日期与复述 ADR 的数字删掉，现状规则保留；子 agent 用 AST 扫描 `kototoki/` 的导入并对照
    `tests/core/test_boundaries.py`、`tests/core/test_job.py` 的禁止导入列表逐条核对。
- docstring：`kototoki/` 的 22 个顶层模块与 `kototoki/__init__.py`、`names/__init__.py`、`translate/__init__.py`、`workers/__init__.py`
  共 26 个文件，各在模块 docstring 末尾加一行"模块页：<路径>。"。脚本用 AST 比较确认除 docstring 外语法树不变。
  既有的"规格 §x"引用没有改：技术设计保留了对应的节标题桩（票据 09）。
- `scripts/check_docs.py`：两页从 `BUDGET_WHITELIST` 去掉。白名单只剩 `docs/agents/subtitle-translation-evaluation.md`（字节被代码校验，永久）与 `docs/development/dependencies.md`（§8 第 6 项）。

### 对不上的地方

- 旧模块边界页写"`procs` 只用标准库与 ctypes"；`kototoki/procs.py` 还导入同在基础层的 `kototoki.artifacts`（时间戳与原子写）。不违反分层；新页不写它依赖什么。
  `kototoki/procs.py` 的 docstring 首行仍写"只用标准库与 ctypes"，后文自己说明了取自 `artifacts`，没有改。

## Answer

两页进预算，白名单对应行已删。门：`just docs-check` 通过（497 篇，0 条告警）；`just gate-core` 通过（716 个测试）。
未验证：mermaid 图只改了写法（`A & B --> C`），没有在渲染器里看过。
