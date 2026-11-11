# 06 `docs/pending-decisions.md`

Status: resolved
Type: task
Blocked by: 05

范围见 [spec §4 票据 06](../spec.md#06-docspending-decisionsmd)。

## 执行记录

- 汇总委派给子 agent（`sonnet`，只读仓库），主 agent 复核后落到 `docs/pending-decisions.md`（7,492 字符）。
- 来源：`docs/plans/` 3 篇新计划的 §8、v5–v15 报告的待裁定节（spec 写 v7–v15，v5、v6 的待裁定节也还开着，一并收了）、
  10-19 交叉合并与专名各篇、决定索引原"未关闭项"、其他 `.scratch/*/spec.md` 与 `map.md`（没有新增项）。原文都没有动。
- 分类结果：
  - 未裁定 2 项：H0 研究侧引擎是否同步升级；`lint`／`typecheck` 选哪个工具。
  - 待用户确认是否仍开放 9 行：v6 第 1–3 项、v7 第 3–4 项、v9 第 3 与 6 项、v10 第 5 项、v11 第 2 项、v11 第 5 项、
    v14 第 11 项、声学裁判线后续、v5 第 1–2 项。来源写着待裁定，但找不到 ADR 或决定索引的明确裁定，没有自行关闭。
  - 已裁定（仅供对照）15 行，每行写了裁定出处。
- 决定索引"未关闭项"：原有条目原文移到 `pending-decisions.md` 的"未验证与已知限制"一节（只改了相对链接），
  决定索引该节改为一句指向；小节标题保留，因为 ADR-0022 与一篇冻结计划链接这个锚点。"记录新决定"的对应步骤同步。
- 本次整理自己的 §8 在该页单列一节并链接回 spec。
- `docs/INDEX.md` 入口分工加一行。

## Answer

完成。`just docs-check` 通过。没有裁定任何事项，也没有给建议。9 行"待用户确认是否仍开放"需要用户逐项确认。
