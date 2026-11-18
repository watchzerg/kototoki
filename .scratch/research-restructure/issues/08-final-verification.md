# 08 总验收

Status: resolved
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

## Answer

1. `git diff --stat archive/2026-11-18-pre-research-restructure -- kototoki/` 为空：通过。
2. `just gate-core` 与 `just test-full` **未运行**：`.venv` 不存在，要先 `just setup`（改环境、联网）。按用户要求须先问，本次没有执行。能用系统 Python 跑的部分已经跑过：`scripts/check_docs.py` 通过，`tests.core.test_check_docs` 与 `tests.core.test_boundaries` 共 22 项通过，`compileall scripts tests` 通过。
3. `research/` 下 16 个轮次目录都有 README，并在 `research/INDEX.md` 登记；`research/acceptance/` 的 8 篇都已登记（`check_docs.py` 也会检查这一点）。
4. 指向已删路径的链接只剩 tag 形式（`check_docs.py` 的链接与路径检查通过）；`research/` 中没有 64 位十六进制串；`research/`、`docs/`、`tests/` 中没有未登记白名单的盘符路径。历史 ADR 正文里还留着当时的入口命令（例如 `python -m experiments.…`）：ADR 只改链接，这些没有改写。
5. 跟踪的文件从 1166 个减到 250 个，总字节从 18,329,519 减到 2,237,170（约 −88%），比较基准是归档 tag 与本次最终提交。
6. 抽查三条 ADR：0010 → flow v1–v4、batching v6–v8；0021 → Strata v12–v13；0023 → ASR 稳健性 v14–v15。三条链接都能打开，各 README 的"结论与去向"能说明决定依据。遗留问题：ADR-0023 状态行里的"§8 第 7 项"是旧研究文档的节号，新 README 里没有这一节（指的是 A 方案进产品）。
7. spec 已改为 `Status: resolved`，进度表已补全；按 R7，本目录等用户确认后再删。
8. 已在本地 main 提交。`git push` 被 `.claude/settings.json` 的 deny 规则拦截，归档 tag 与 main 都要用户自己 push。
