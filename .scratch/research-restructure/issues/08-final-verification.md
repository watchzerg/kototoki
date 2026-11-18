# 08 总验收

Status: ready-for-agent
Type: task
Blocked by: 06, 07

## 检查清单

1. `git diff --stat archive/2026-11-18-pre-research-restructure -- kototoki/` 为空。
2. `just gate-core` 通过；`just test-full` 通过或说明未跑原因。
3. `research/INDEX.md` 登记了每个轮次目录，每个目录有 README；`research/acceptance/` 每篇已登记。
4. grep 全仓库（排除 `.git`）：
   - 指向已删除路径的链接只剩 tag 路径形式；
   - `research/` 无 64 位十六进制串；`research/`、`docs/`、`tests/` 无未白名单的盘符绝对路径。
5. 文件数与体积对比（`git ls-files | wc -l` 与总字节），写进 spec 进度。
6. 抽查三条 ADR（建议 0010、0021、0023）：从 ADR 的链接能走到对应轮次 README，并读懂决定依据。
7. 更新 spec：`Status: resolved`，进度表补全；按 R7 本目录保留到用户确认后再删。
8. 直接在 `main` 上提交并 push（用户要求：不建分支、不开 PR）；最后一次提交信息里列出删除范围、新规范和已知遗留。

## 汇报给用户

区分：已实现、自动检查结果、未验证项（smoke 未跑、产品注释遗留路径、memory 待更新）。
