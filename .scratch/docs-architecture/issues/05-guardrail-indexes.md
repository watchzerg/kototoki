# 05 护栏与状态索引

Status: resolved
Type: task
Blocked by: 04

范围见 [spec §4 票据 05](../spec.md#05-护栏与状态索引全部是新文件)。

## 执行记录

- 5 个新索引由 3 个子 agent（`sonnet`，只读仓库，草稿写在仓库外）起草，主 agent 复核后落盘：
  - `docs/context/INDEX.md`：8 篇台账的字符数、标题数、用途、对应计划与报告；"禁止整读，先 grep 标题"；
    `2026-10-06-hy30-four-execution.md` 与 `2026-10-08-hy30-flow-exploration-v2.md` 的节地图（行号区间）。
  - `docs/testing/INDEX.md`：18 篇逐篇标活契约／冻结记录／被校验，并写出校验它的代码路径；另列目录外被校验的文档。
  - `docs/plans/INDEX.md`：22 篇的状态（19 done、1 stopped、1 superseded；v4 计划自己的状态行仍写 proposed，按台账与报告判 done）与结果文档。
  - `docs/specs/INDEX.md`：技术设计、W0／X0 契约为现行，5 篇 `subtitle-translation-*` 为 superseded。
  - `experiments/INDEX.md`：33 个包与 11 个顶层模块的状态、对应调研或 ADR、是否加载模型。
- 主 agent 的改动：`testing/INDEX.md` 去掉行号（源码引用不用行号）；`experiments/INDEX.md` 把 `translation_v3` 从"冻结轮次"改为
  "可复用入口"（`just translation-srt` 与裁判入口仍在用），并补上"`x0_flow` 与 `qwen` 只作回归参照"（票据 03 从 `AGENTS.md` 下沉的规则）；
  `context/INDEX.md` 补"v2 先验只取 v1/v2 教训"。
- 新发现的被校验文件（不在 spec §1.3 名单里）：`docs/testing/translation-model-evaluation.md` 与
  `docs/agents/subtitle-translation-evaluation.md` 都被 `experiments/translation_four_quantization/__main__.py` 纳入冻结源快照并取 sha256。两篇都没有动。
- 5 篇 `docs/specs/subtitle-translation-*.md`：搜过 `experiments/`、`scripts/`、`kototoki/`、`kototoki_eval/`、`tests/`、`justfile`、`pyproject.toml`，
  没有代码引用或校验它们（`.local/` 下未跟踪的清单没有查）。只在状态行前加了 `superseded（2026-11-11 标注…）；原状态 draft；`，其余字节未变。
- `docs/INDEX.md` 9,566 → 2,980 字符：删"既有文档清单"（约 65 条）；"项目特有入口"表加"目录索引"列并保留各行的保留原因；
  两篇 `docs/guides/` 与归档的 Codex AGENTS 在该表直接链接。
- `experiments/INDEX.md` 里"是否加载模型"一列是按 grep 与 README 的快速判断，`analysis`、`provision`、`run_experiment.py`、`run_round2.py` 标"未核实"。

## Answer

门通过：脚本核对 `docs/context`、`docs/plans`、`docs/testing`、`docs/specs` 四个目录的每个 `.md` 都被本目录索引链接；
`experiments/` 的每个包目录与顶层模块都出现在 `experiments/INDEX.md`。各索引都在 150 行、单行 400 字符以内。`just docs-check` 通过。
