按 `.scratch/docs-architecture/spec.md` 完成文档架构整理。

- 先读该 spec 全文，再读 `docs/agents/documentation.md` 与 `docs/agents/issue-tracker.md`。
- 在分支 `docs-architecture` 上按 §4 的票据 01–12 顺序执行：每张票据在 `issues/` 建文件，过了该票据的门再提交，一张一次提交，不 push。
- 遵守 §5 的门与停止条件、§6 不做的事、§1.3 不能动的文件；改任何既有文件前先搜代码里有没有对它的 sha256 或内容断言。
- 不占 GPU、不加载模型、不改环境。
- 进度与结果写 spec §7，需要我裁定的事项写 §8；某张票据触发停止条件时记下原因，继续做其余不依赖它的票据。

完成标准：票据 01–12 全部 resolved 或在 §8 写明停下的原因；`just gate-core` 通过；`AGENTS.md` ≤ 4,500 字符；spec §7 列出关键文件整理前后的字符数。
