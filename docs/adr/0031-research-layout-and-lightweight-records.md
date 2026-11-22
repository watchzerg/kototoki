# ADR-0031：研究按轮次放进 `research/`，记录精简，冻结靠 git

状态：已接受（2026-11-18，用户批准计划 `archive/2026-11-18-pre-research-restructure:.scratch/research-restructure/spec.md`）。替代 [ADR-0025](0025-product-package-boundaries.md) 第 4 点中"实时对照搬到 `tests/equivalence/`、由 `just test-equivalence` 运行并入 `gate-full`"的部分（`tests/core` 不导入研究代码、核心测试钉字面量的部分仍有效）；取代此前 `AGENTS.md` 与[文档维护规则](../agents/documentation.md)中"冻结的历史证据只读、字节不可改、代码对文档做 sha256 自检"的规则。R7 中 `.scratch/` 存放产品侧计划与票据的部分自 2026-11-22 起由 ADR-0037 替代。R1 及 R2、R8 中的路径（`research/`、`research/acceptance/`）自 2026-11-22 起由 [ADR-0038](0038-setup-project-doc-layout.md) 替代，改为 `docs/research/`。R8 中由 `scripts/check_docs.py` 承担的检查自 2026-11-22 起由 [ADR-0039](0039-setup-project-docs-check.md) 替代（不再有机械检查）。
范围：研究、计划、验收记录的存放位置与写法，旧研究代码与评估包的去留，文档检查规则。不改任何产品代码、配方、基线与产品行为。

## 背景

- 研究材料散在四处：`docs/research/`（结论）、`docs/plans/` 与 `.scratch/`（计划）、`docs/context/`（执行台账）、`experiments/`（代码）。同一轮的东西要跨目录拼起来才能读懂。
- 记录过重：逐窗数据、样本文件的 sha256、字节锁、本机绝对路径、执行台账占了大部分篇幅；部分文档被代码按 sha256 自检，修一个错字也要走"新增带版本文件"。
- 研究依赖的 `.local` 数据已离机，`experiments/` 多数入口写死本机路径，已不可运行；`kototoki_eval/` 只剩 `experiments/` 一个使用者，产品用的是自己的副本。

## 决定

1. **归档 tag**：重组前的 HEAD 打 tag `archive/2026-11-18-pre-research-restructure`。旧材料一律写成 `archive/2026-11-18-pre-research-restructure:<路径>` 引用，主分支不保留兼容层或重定向页。
2. **删除旧研究代码与旧文档目录**：`experiments/`、`kototoki_eval/`、`tests/equivalence/`（及 `just test-equivalence`；`gate-full` 改为 `gate-core` 加 `test-full`），`docs/research/`、`docs/plans/`、`docs/context/`、`docs/testing/`、`docs/guides/`、`docs/archive/` 与已 superseded 的规格，内容先提炼进轮次记录或现行正文。`experiments/w0_demo/THIRD_PARTY_NOTICES.txt` 原样移到仓库根。`research/_lib/` 等第一次有跨轮复用的研究工具时再建。
3. **R1 一轮一目录**：研究的计划、代码、结论放在 `research/<YYYY-MM>-<slug>/`，立项时在 `research/INDEX.md` 登记一行；产品验收记录放 `research/acceptance/`，一次一篇。
4. **R2 轮次 README 必填项**（`research/TEMPLATE.md`）：状态、时间、问题、策略、环境与版本、测试、结果、结论与去向；教训与原始材料可选。正文约 150 行以内，结果表约 10 行以内。
5. **R3 不写进研究记录**：文件或样本的哈希（git commit SHA 除外）、本机绝对路径、逐窗或逐条明细与大段日志、字幕或转写原文（短例外）、执行台账与接跑步骤。
6. **R4 冻结靠 git**：结题即把状态写成 `concluded`／`stopped`；修错、修链接、精简随时可以做，需要原始材料从归档 tag 或 git 历史取。代码不得对文档做 sha256 自检。ADR 正文同样可以修链接，决定内容不改，替代关系仍按[记录新决定](INDEX.md#记录新决定)追加。
7. **R5 依赖方向**：产品永不导入 `research/`；研究可以导入产品。研究数据经仓库根 `data.toml`（逻辑名 → 相对数据根的路径）与环境变量 `KOTOTOKI_DATA` 定位，第一个需要数据的新轮次建立；代码与文档不写本机绝对路径。
8. **R6 规则移植**：研究结论进产品后，产品实现是唯一权威；后续研究直接调用产品实现，不保留研究侧副本，因此不再有 equivalence 对照层。需要钉住的取值在 core 测试里以字面量钉住，注释写来源（归档 tag 路径或 ADR）。
9. **R7 `.scratch/<slug>/`** 只放产品侧进行中的计划与票据；完工时把持久结论写进模块页或 ADR，然后删除该目录。研究轮次的计划写在轮次目录里。
10. **R8 机械检查**：`scripts/check_docs.py` 检查 `research/*/README.md` 的必填标题；`research/`、`docs/`、`tests/` 不出现盘符绝对路径（测试中显式标注的虚构路径白名单除外）；`research/` 不出现 64 位十六进制串；`tests/core/test_boundaries.py` 检查 `kototoki/` 不导入 `research`。

## 依据

- 历史记录的价值在结论与依据，不在字节；git 与归档 tag 已能完整追溯原文。
- 数据离机后旧实验不能复跑，保留代码只增加维护面；需要时从 tag 取回。
- equivalence 层的对照对象被删除，等价规则已由 core 的字面量钉住。

## 后果

- 旧材料只能从归档 tag 追溯；现行文档里指向旧路径的链接改为新轮次目录或 tag 路径。
- `kototoki/` 中有注释写"复制自 `experiments/…`"，本次不改产品代码，这些路径指归档 tag，下次因其他原因改到这些文件时顺手更新（见 [research/INDEX.md](../research/INDEX.md)）。
- 已结题的 `.scratch/<slug>/` 在确认结论已进 ADR、模块页或轮次记录后删除；进行中的保留。

## 未验证

- 删除旧代码后没有重新运行任何研究脚本或真实模型验证（本决定不涉及推理行为）。
