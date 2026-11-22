# Issue tracker: Beads

本仓库产品侧的 spec 与票据存放在 Beads 中，tracker 操作使用 `bd` CLI（issue 前缀 `kototoki`）。引用 issue 时使用完整 bead ID（如 `kototoki-e8t.3`）。决定见 [ADR-0037](../adr/0037-beads-issue-tracker.md)。

## 常规操作

- 创建：`bd create "<title>" --body-file <path> --type <type> --json`
- 读取：`bd show <id> --json`
- 列出：`bd list --json`；包含已关闭条目时使用 `bd list --all --json`
- 查找可执行工作：`bd ready --json`
- 领取：`bd update <id> --claim --json`
- 更新状态：`bd update <id> --status <status> --json`
- 添加或删除标签：`bd update <id> --add-label <label> --json` 或 `bd update <id> --remove-label <label> --json`
- 读取评论：`bd comments <id> --json`
- 添加评论：`bd comments add <id> "<comment>"`
- 关闭：`bd close <id> --reason "<reason>" --json`

不要用 `bd edit`（会打开编辑器，阻塞 agent）。

Beads `status` 表示生命周期，`type` 表示工作类型，triage label 表示处理路径。五个 triage label 见 [triage-labels.md](triage-labels.md)。

## 约定

- Spec 用 `epic`：描述写范围、票据、门禁与未决问题；长篇附件（如审计报告原文）放 `--notes`。票据用 `--parent <epic-id>` 挂在 spec 下。
- 类型：实现类用 `task`／`bug`／`feature`，调研类用 `spike`。
- 执行提示词与验收脚本写进 bead 的描述、`--design` 或评论，不另建目录。
- 正文里的仓库链接从仓库根目录写（`docs/...`、`research/...`）。
- 面向人的 spec、票据和评论用简体中文。
- 完工时把持久结论写进模块页或 ADR，再关闭 bead；后续工作开新 bead。当前正文可以引用 bead ID。
- 研究轮次不用 Beads：计划、代码与结论放 `research/<YYYY-MM>-<slug>/`（见 `research/INDEX.md`）。
- 隐私规则与仓库其他部分相同：不写密钥、录音、转写或字幕原文（简短示例除外）。
- `docs/specs/` 中已接受的规格对其范围仍有权威；spec 链接过去，不复制需求。

## Skill operations

- "Publish to the issue tracker" 表示使用 `bd create` 创建 bead。
- "Fetch the relevant ticket" 表示读取 `bd show <id> --json` 和 `bd comments <id> --json`。
- 自动化调用使用 `--json` 输出。

## Wayfinding operations

- map 使用 `epic` 类型和 `wayfinder:map` label，Notes、Decisions-so-far、Fog 写在描述里。
- 子 ticket 使用对应的 Beads 类型和 `wayfinder:<type>` label，并通过 `--parent <map-id>` 关联 map。
- 阻塞关系使用 `bd dep <blocker-id> --blocks <blocked-id>`。
- 查询未分配且没有 active blocker 的子 ticket：`bd ready --parent <map-id> --unassigned --json`。
- 领取 ticket 使用原子操作 `bd update <ticket-id> --claim --json`。
- 解决：答案写进评论，关闭 bead，并把摘要与 bead ID 追加到 map 描述的 Decisions-so-far。
