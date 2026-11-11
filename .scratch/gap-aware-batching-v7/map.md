# 地图

## 接跑手册（每次启动从这里开始）

1. 读[研究文档](../../docs/research/2026-10-16-gap-aware-batching-v7.md) §7 进度，找到第一张未 resolved 且 Blocked by 已全部 resolved 的票据；读它的 `## 执行记录`。
2. 只读核对 GPU（启动任何生成前必做）：PowerShell `Get-Process | ? ProcessName -match 'llama|python'`、`nvidia-smi`，读 `.local/gpu.lock`。锁被存活 PID 持有、或有不明 llama-server 时不要启动新作业、不要杀进程，转做离线票据。
3. 状态以文件为准：`P = uv run --locked --offline python -X utf8 -m experiments.scene_batching_v6 --round v7`；`P status` 看生成与裁判进度。生成与裁判都可续跑（已完成的场景／包跳过）。
4. 命令：`P generate --recipe R --seed S`（GPU，约 5 分钟）；`P copy-control --seed S`；`P subset --variant R --seed S`；`P judge --variant R --seed S --parallel 4`（候选＋对照副本，全集；对照已判的包跳过）；`P compare --variant R --seeds S1 S2 S3 [--against R2] [--label L]`；`P pooled --variant R --seed-sets a,b,c/d,e,f`；`P simulate`（离线）。
5. 裁判（`claude -p`）退出码 75 = 配额耗尽：不要循环重试；转离线票据，没有可做的就停下，在票据执行记录写明停在哪里。
6. 每完成一张票据：票据写 Answer 并 resolved → 本文 Decisions-so-far 加一行 → 研究文档 §7 更新 → 提交 Git（研究文档与 `experiments/` 下本轮代码）。
7. 需要用户裁定的事项写研究文档 §8，不中途停下。

## Notes

- 2026-10-16 开始执行（goal 会话，无人值守）。
- v4 dev 每个 seed 覆盖一个场景块：主 seed 20261011–13 合起来覆盖整个 dev 一次，重复 seed 20261021–23 再一次。v4 b10-joint 两组都已生成；本轮复制译文后在全集重判。
- 生成与裁判可以并行（裁判只用网络与少量 CPU）；墙钟因此略受干扰，在成本里注明。

## Decisions-so-far

- 2026-10-16 [01](issues/01-offline-impl-sim.md)：`gap_pack`／`pause_marks` 已实现，已有 hash 不变；软边界 1 分／秒、小包惩罚 1000、标记 `{"pause": "此处约N秒无台词"}`。dev：dp6 请求 1.17×、平均 8.3、跨 ≥10 s 0%、跨 ≥5 s 22%；mark5 带标记的批 49%；dp6-grp 1.24×、7.9。产品时间轴 dp6／dp6-grp 的 <6 句包 34–35%（>10%，进 §8）。
- 2026-10-16 [02](issues/02-dp6-screen.md)：dp6 主 seed 全集：电影 +0.047［+0.0003, +0.095］显著变差、剧集 −0.011［−0.045, +0.023］、总 +0.018；wrong-referent 不降（+0.010）；变差不集中在小包。触发 §5 停止条件，dp6 停止（不做重复 seed）。对照重判漂移 −0.018，同时重判有必要。
- 2026-10-16 [03](issues/03-mark5-screen.md)：mark5 主 seed 全集非劣：剧集 +0.014［−0.009, +0.037］、电影 +0.017［−0.010, +0.044］；剧集 wrong-referent +0.016［+0.002, +0.031］上升；与 dp6 直接比较总 −0.003［−0.032, +0.026］。进入 05 复现。
- 2026-10-17 [04](issues/04-dp6grp-screen.md)：dp6-grp 主 seed：剧集 −0.002［−0.036, +0.031］、电影 +0.029［−0.017, +0.075］（不满足非劣但不显著变差，照常复现）；相对 dp6 总 −0.004［−0.027, +0.018］，两侧非劣（Q3 筛选成立）。
- 2026-10-17 [05](issues/05-replicate.md)：重复 seed：mark5 剧集 +0.001、电影 +0.006，两次都非劣（合并 +0.008／+0.011）；dp6-grp 剧集 −0.017、电影 −0.022 非劣，但主 seed 电影未达非劣（合并 −0.009／+0.003）。无任何改善在两次上都为负。对照重判漂移主 −0.018、重复 +0.015。
- 2026-10-17 [06](issues/06-q4-close.md)：Q4 只有 mark5 满足非劣保留标准（无改善）；dp6、dp6-grp 不满足。场景感知线关闭；选择交研究文档 §8。结题。

## Fog

- mark5 的标记是否会被模型当作台词（grammar 只允许目标 ID，输出上不可能；理解上的影响只能看分数）。
- 产品时间轴上小包比例远高于 dev（见 01），dev 上的质量结论能否外推到产品。
