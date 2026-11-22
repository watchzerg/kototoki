# ADR-0038：研究、跑次与行为规格按 setup-project 目录规范放进 `docs/`

状态：已接受，2026-11-22（用户裁定：路径统一以 setup-project 的规范为准，不以项目旧 ADR 为准），已实现。
替代关系：
- 取代 [ADR-0031](0031-research-layout-and-lightweight-records.md) R1 中"研究一轮一目录放 `research/<YYYY-MM>-<slug>/`、验收记录放 `research/acceptance/`"的部分，以及 R2、R8 中随之写死的路径。R2 的必填项、R3–R6、R8 的检查内容仍有效。
- 取代 [ADR-0037](0037-beads-issue-tracker.md) 第 4 点中"研究轮次放 `research/`"的路径（研究轮次不建 bead 的规定不变）。

范围：研究记录、验收记录、跑次记录与行为规格的存放路径。不改记录的写法、产品代码、配方与基线。

## 决定

1. **研究记录**：一轮一篇 `docs/research/<YYYY-MM>-<slug>.md`（原 `research/<轮次>/README.md`），骨架 `docs/research/TEMPLATE.md`，登记在 `docs/research/INDEX.md`。
2. **验收记录**：`docs/research/acceptance/<主题>-<YYYY-MM-DD>.md`（原 `research/acceptance/<YYYY-MM-DD>-<主题>.md`）。
3. **跑次记录**：`docs/research/runs/<YYYY-MM-DD>-<slug>.md`，索引与骨架为同目录的 `INDEX.md`、`TEMPLATE.md`（原根目录 `runs/`），并从 `docs/research/INDEX.md` 链接。
4. **行为规格**：`docs/behaviors/`（原 `docs/specs/`）。
5. **研究代码**：现有轮次都没有代码；`docs/` 下不放代码，第一个需要代码的轮次立项时再定位置。产品与 `tests/core` 不导入研究代码（Python 包 `research`）的规则不变。
6. 2026-11-22 一次迁完：31 个文件经 `git mv` 移动，全部相对链接改指新路径；`scripts/check_docs.py` 与 `tests/core/test_check_docs.py` 随路径更新。

## 依据

- 用户要求本项目路径统一以 setup-project skill 的标准文档结构为准：所有文档在 `docs/` 下，调研与验收记录在 `docs/research/`。
- 该规范用 `behaviors/` 而不用 `specs/`：Matt 的 implement-spec 与 code-review 把 spec 当增量规格，`docs/specs/` 会被误读。
- 规范没有跑次记录的位置；跑次记录是带时点的运行证据，用户选定归入 `docs/research/runs/`。

## 未验证与已知限制

- 研究记录正文里提到的归档 tag 路径（`archive/2026-11-18-pre-research-restructure:<路径>`）指向旧布局，原样保留。
- ADR-0031 正文按原文保留，其中的 `research/` 路径只作历史。
