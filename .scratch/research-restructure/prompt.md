# 执行提示词（新 session 粘贴使用）

按 `.scratch/research-restructure/spec.md` 执行"研究与文档精简重组"，票据在同目录 `issues/`，按编号与依赖顺序推进。

要求：

- 先读 spec 全文（尤其"不做的事"与"已定决定"），再读 `AGENTS.md` 与 `docs/agents/documentation.md`。spec 是用户批准的计划，按它执行，不逐步再问；遇到 spec 未覆盖、且会删除内容或改变现行决定的情况，停下来问用户。
- 不改 `kototoki/` 下任何文件；不跑 GPU、模型、smoke、demo。
- 门禁需要的 `just setup` 会改环境并联网：执行前问用户一次。
- 02、03、04 可并行委派子 agent（`model: sonnet`，各自只写自己的 `research/<目录>/README.md`，不改 `research/INDEX.md`）；主 agent 审阅每篇是否满足 R2、R3 再合并。其余票据由主 agent 完成。
- 直接在 `main` 上工作：不建分支、不开 PR。每完成一张票据：在票据里写 `## Answer`、改 `Status: resolved`，在 spec 的"进度"追加一行，单独提交（提交信息写中文，说明票据号）并 push 到 `origin main`。
- 最后按 08 验收并 push，向用户汇报：已实现、自动检查结果、未验证项。
