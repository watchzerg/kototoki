# ADR-0037：产品侧计划与票据改用 Beads

状态：已接受，2026-11-22（用户裁定），已实现。
替代关系：
- 取代 [ADR-0031](0031-research-layout-and-lightweight-records.md) R7 中"`.scratch/<slug>/` 放产品侧进行中的计划与票据、完工后删除目录"的部分（研究轮次不用 tracker 的规定不变）。

范围：产品侧的 spec、票据、执行提示词与验收脚本存放在哪里。不改研究布局、产品代码、配方与基线。

## 决定

1. 产品侧的 spec 与票据存进 Beads（`bd` CLI，issue 前缀 `kototoki`）：spec 是 `epic`，票据是它的子 issue；规则见 [tracker 约定](../agents/issue-tracker.md)。
2. 删除 `.scratch/`；docs-check 不再扫描它。
3. 已有票据全部迁入（2026-11-22）：`.scratch/architecture-review/` 成为 `kototoki-e8t`（spec 为描述、2026-10-19 审计报告原文在 notes、21 张票为子 issue），`next-directions` 两张票为 `kototoki-11g`、`kototoki-671`，`ubuntu-port` 探查票为 `kototoki-mf4`。原 `resolved` 的票迁入后关闭，其余保留原 triage 状态作 label。
4. 研究轮次仍按 [ADR-0031](0031-research-layout-and-lightweight-records.md) 放 `research/`（路径自 2026-11-22 起由 [ADR-0038](0038-setup-project-doc-layout.md) 改为 `docs/research/`），不建 bead；完工的持久结论仍写进模块页或 ADR，再关闭 bead。

## 依据

- 用户在相邻项目（grok-media-saver）已采用 Beads，要求本仓库统一。
- Beads 提供原子领取、阻塞依赖与 `bd ready` 查询，Markdown 票据要靠约定手工维护。

## 未验证与已知限制

- 迁移时票据正文原样保留（含原 `## Comments` 段），相对链接改成仓库根路径；迁移前的编辑历史只在 git 中。
