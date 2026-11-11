# 地图

## 接跑手册（每次启动从这里开始）

1. 读[研究文档](../../docs/research/2026-10-16-scene-aware-batching-v6.md) §7 进度，找到第一张未 resolved 且 Blocked by 已全部 resolved 的票据；读它的 `## 执行记录`。
2. 只读核对 GPU（启动任何生成前必做）：PowerShell `Get-Process | ? ProcessName -match 'llama|python'`、`nvidia-smi`，读 `.local/gpu.lock`。锁被存活 PID 持有、或有不明 llama-server 时不要启动新作业、不要杀进程，转做离线票据。
3. 状态以文件为准：本轮 run 在 `.local/scene-batching-v6/runs/`，用 `uv run --locked --offline python -X utf8 -m experiments.scene_batching_v6 status` 查看生成与裁判进度；不以文字记录为准。生成与裁判都可续跑（已完成的场景／包跳过）。
4. 裁判（`claude -p`）退出码 75 = 配额耗尽：不要循环重试；转离线票据（统计、记录），没有可做的就停下，在票据执行记录写明停在哪里。
5. 每完成一张票据：票据写 Answer 并 resolved → 本文 Decisions-so-far 加一行 → 研究文档 §7 更新 → 提交 Git（只含研究文档、`experiments/` 下本轮代码与必要的 `translation_v3` 改动）。
6. 需要用户裁定的事项写研究文档 §8，不中途停下。

## Notes

- 2026-10-16 立项并开始执行（goal 会话，无人值守）。
- v4 dev 的每个 seed 只覆盖一个场景块（`translation_v4.gen.seed_block`）：主 seed 20261011–13 合起来覆盖整个 dev 一次，重复 seed 20261021–23 再覆盖一次。b10-joint 两组都已生成并全部裁判。
- 裁判窗口是按场景连续切的 5 条 tile（v4 `reference.windows`）；包内 4 窗，打包按 split 固定种子洗牌。子集裁判时包组成会与 v4 全集不同，所以对照也在同一子集、同一包组成上重判（本轮根目录下的对照副本 run），避免包组成与时间漂移混入。

## Decisions-so-far

- 2026-10-16 [01](issues/01-q1-error-distribution.md)：少数派一侧的超额不在 wrong-referent（份额不高、dev／confirm 方向反），是位置混杂；准随机批边界对比显示批内跨间隔让间隔两侧 cue 的 wrong-referent 多 +0.05–0.09（dev／confirm／c0 三臂区间均不含 0），全集折算约 0.004。继续 Q2，只做一个主变体，目标是"不跨间隔"而非缩批。
- 2026-10-16 [02](issues/02-scene-split-impl.md)：顺序弹性切法会让后续批全部平移（受影响 55–90%），改为网格吸附；唯一主变体 `gsnap5`（±2 条吸附到 ≥5 s 静默、跨 ≥5 s 邻文去掉，`f58afa33…`），批数不变，跨 ≥10 s 批 27%→20%，受影响 cue 约 48%；已有 hash 不变有测试。
- 2026-10-16 [03](issues/03-q2-screen.md)：dev 主 seed，受影响 2563 条：accuracy Δ 总 −0.022［−0.055, +0.012］，剧集 −0.048［−0.097, −0.001］，电影 +0.005；wrong-referent 不变（−0.004），剧集改善在 mistranslation；全集护栏 −0.008［−0.025, +0.008］；墙钟 −2%，交付失败 0。方向成立，进入 04 复现。
- 2026-10-16 [04](issues/04-q2-replicate.md)：重复 seed 独立配对不复现：受影响子集 Δ 总 +0.001［−0.036, +0.038］（剧集 −0.029、电影 +0.031）；合并两次 总 −0.010［−0.040, +0.019］，剧集 −0.038［−0.078, −0.000］，电影 +0.018；wrong-referent 不变。触发 §5 停止条件二，结题。
- 2026-10-16 [05](issues/05-q3-close.md)：Q3 形式上满足零成本标准（全集非劣、critical 不增、交付 0 失败、墙钟 −2.7%），但质量收益未复现、电影两次偏正；建议暂不改默认，交用户裁定（研究文档 §8）。结题。

## Fog

- ~~固定 seed 与 `cache_prompt` 下切法未变的批次输出是否逐字相同~~ 03 实测：2834／2834 条逐字相同。
