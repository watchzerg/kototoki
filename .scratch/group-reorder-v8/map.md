# 地图

## 接跑手册（每次启动从这里开始）

1. 读[研究文档](../../docs/research/2026-10-18-group-reorder-v8.md) §7 进度，找到第一张未 resolved 且 Blocked by 已全部 resolved 的票据；读它的 `## 执行记录`。
2. GPU 票据（02、03、05）启动前须用户确认（AGENTS.md"重任务先问"），并只读核对 GPU：PowerShell `Get-Process | ? ProcessName -match 'llama|python'`、`nvidia-smi`，读 `.local/gpu.lock`。锁被存活 PID 持有、或有不明 llama-server 时不要启动新作业、不要杀进程，转做离线票据。
3. 离线命令（worktree 里没有 `.local/` 时加 `--local-root D:/AI_Projects/kototoki/.local`）：
   - 重排率与显示校验：`PYTHONPATH=. python -X utf8 -m experiments.reorder_groups.checks --set dev --recipe grp1 --control <dp10-cut run> --candidate <grp1 run> --json .local/group-reorder-v8/<票据>/checks-s<seed>.json`
   - 注入覆盖与 token：`python -m experiments.reorder_groups.coverage --validate <run>`（01 已跑，结果 `.local/group-reorder-v8/01/coverage.json`）
4. 生成与裁判沿用 `experiments.scene_batching_v6`（`generate`／`subset`／`judge`／`compare`／`pooled`）；它目前只有 `--round v6|v7`，02 先加 `--round v8`（根 `.local/group-reorder-v8/`，配方用内置 `dp10-cut`、`grp1`）。
5. 裁判（`claude -p`）退出码 75 = 配额耗尽：不要循环重试；转离线票据，没有可做的就停下，在票据执行记录写明停在哪里。
6. 每完成一张票据：票据写 Answer 并 resolved → 本文 Decisions-so-far 加一行 → 研究文档 §7 更新 → 提交 Git（研究文档与 `experiments/` 下本轮代码）。
7. 需要用户裁定的事项写研究文档 §8。

## Notes

- 2026-10-18 票据 01 由 side session 在 worktree `pensive-jemison-72ee36` 执行（离线，未占 GPU）；本 tracker 写在该 worktree 的 `.scratch/`（Git 忽略），接跑前确认它在要用的 checkout 里。
- v4 dev 每个 seed 覆盖一个场景块（主 seed 20261011–13 合起来覆盖整个 dev 一次），所以不同 seed 之间不能逐条配对；重排率只在同 seed 的对照与候选之间算。
- v7 02 观察到：切包未变的 cue 也有约三分之一译文与对照不同（前面批次改变后 KV 缓存复用长度不同）。本轮"单条组 cue 应逐字相同"在有组包里本来就不成立（prompt 换了 joint 句），无组包里也可能因缓存复用出现少量差异；03 先报数再查因。

## Decisions-so-far

- 2026-10-18 [01](issues/01-offline-impl.md)：`Recipe.groups`（`group-reorder-v1`）、`joint-understanding-v2`、内置 `grp1`（`5aaf3e77…`）已实现，17 个旧内置配方 hash 不变；划组抽到 `batching.sentence_groups`，`stats.py` 输出逐字节不变。重排率主阈值 0.2（严格对严格噪声底 ≥0.2 为 1.6–6%），读速阈值 9 字/秒。dev 97% 的包注入（cue 78%），产品 84%（cue 50%）；每个注入包输入 +168（dev）／+150（产品）token，整体 +25%／+22%，最大 1186 ≪ 4032。
- 2026-10-18 [02](issues/02-sample-observe.md)：Q1 否定。小样 A（10 包、38 组，v2 措辞）与小样 B（10 包、16 组，v2 与两步式措辞三臂）重排率主阈值 0.2 下 0–6.2%，在噪声底内；人工 70 组无一例挪内容；两步式措辞引入邻文泄漏与无中生有，不采纳，`grp1` hash 不变。按 §5 停止条件结题，03–06 不执行，备选路线交 §8。
- 2026-10-18 [07](issues/07-merge-probe.md)：备选路线预检（GPU 20 次请求，0 失败）。整组合并为一个源条目后模型仍按行序输出（可对齐 35 组 0 重排），相似度 p50 0.73／0.77 vs 逐行之间 0.85／0.82；仅标点切回 94% 可达 ≤0.3；但 11／54 组丢信息或歪曲，8 组把不同说话人并成一句。建议不立项（§8 第 1 项）。
- 2026-10-18 用户裁定：关闭语序重排这条线，不立项备选路线；已记入研究文档 §8 与技术设计 §11。本 tracker 关闭。

## Fog

- 无组包占比很低（dev 3%、产品 16%），"单条组 cue 逐字相同"的核对只能在很少的包上做，噪声底主要靠子集 Δ。
- 注入使每包输入 token 增加约四分之一（dev 的 cue ID 很长，`groups` 行本身平均 91 token）；KV 缓存按 context 8192 预分配，显存峰值不应变化，墙钟预期略增，03 实测。
- 模型是否把 `groups` 行当作要输出的内容：grammar 只允许目标 ID，输出上不可能；理解上的影响只能看 Q1／Q2。
