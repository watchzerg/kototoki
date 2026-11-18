# 01 归档 tag 与规范落地

Status: ready-for-agent
Type: task

## 范围

1. 确认工作区干净、与 origin 同步；在当前 HEAD 打 `archive/2026-11-18-pre-research-restructure`，`git push origin <tag>`。
2. 新增 `docs/adr/0031-research-layout-and-lightweight-records.md`（accepted，日期写执行当天）：背景（研究散在四处、字节锁与哈希过重、数据离机后旧实验不可运行）、决定（spec 的 D1–D9 与 R1–R8）、后果（旧材料只能从 tag 追溯、产品注释遗留路径）。同一提交更新 `docs/adr/INDEX.md` 的 ADR 列表与演进链（"冻结证据只读"相关规则被取代）；`CURRENT.md` 若列了文档规则也同步。
3. 建 `research/INDEX.md`（先放规则节、空的轮次登记表与"研究方法约束"节）与 `research/TEMPLATE.md`（R2 的必填标题，每节一行说明）。
4. 改权威规则文档，使其与 R1–R8 一致，删除失效条款：
   - `AGENTS.md`：重写"冻结证据与现行决定"一节（保留现行决定、Q3 唯一基线、不自动多次翻译挑选、已结题研究线不重开；删除字节保护、sha256 自检、Codex 裁判链、确认集细节——后者移到 `research/INDEX.md`）；"重任务先问"删去 `experiments.*` 与 `x0-demo`、`translation-*` 等将删除的入口；按任务读取表删掉 W0／X0 demo 行，"调研"行指向 `research/INDEX.md`；大目录提示删掉 `docs/research/*appendices`。
   - `docs/agents/documentation.md`：三态规则中"历史证据永不改写"改为 R4；落点表与权威归属表中调研、计划条目改为 `research/`；删除"既有目录"一节（ticket 05 删目录后已无对象）；`.scratch` 条目按 R7。
   - `docs/agents/issue-tracker.md`：完工目录按 R7 删除，不再冻结；研究轮次不用 `.scratch`。
   - `docs/agents/testing.md`：删除 equivalence 层；写明规则移植按 R6。
   - `.claude/skills/*`：grep "冻结｜frozen｜sha256｜docs/research｜experiments"，凡把旧规则写进流程的就地改成新规则（只改规则语句，不重写 skill）。

## 完成标准

- tag 在 origin 上可见。
- 上述文件中不再出现"冻结证据只读""不得修改（被代码校验）"一类要求；`AGENTS.md` 仍控制在现有篇幅内。
- 本票据不删除任何旧目录（留给 05、06）；`just docs-check` 此时可能因链接未改而报错，记录即可，不为此改旧文件。
