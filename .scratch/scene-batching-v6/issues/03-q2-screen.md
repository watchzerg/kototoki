# 03 Q2 筛选：dev 主 seed

Status: resolved
Type: research
Blocked by: 02

## 范围

- 每个变体在 dev 主 seed 20261011／12／13 各生成 1 个 run（每个 run 只含该 seed 的场景块）。生成前按 map 接跑手册核对 GPU。
- 实测切法未变的批次输出是否与对照逐字相同。
- 裁判：受影响子集窗口，候选 run 与对照副本 run 用相同包组成各判一次。
- 主终点：受影响 cue 的配对 Δ accuracy（作品内平均→作品等权，剧集／电影分开，窗口重抽 CI90）；分类别 Δ（wrong-referent、mistranslation、negation-number-condition）；全集 Δ 作非劣护栏（未变 cue 取对照值）。
- 记录墙钟、请求数、每批可见 cue 数分布、显存峰值、交付失败。

## 预算

变体 ≤2 个（≤6 个 run）；裁判只判子集。

## 文件所有权

`experiments/scene_batching_v6/`；产物 `.local/scene-batching-v6/`。

## 执行记录

- 2026-10-16 假设：`gsnap5` 降低受影响 cue 的 accuracy 惩罚，主要通过 wrong-referent。唯一变化：`gap_split`。GPU 核对：无 `.local/gpu.lock`、无 llama／python 进程、显存占用 661 MiB。命令：`uv run --locked --offline python -X utf8 -m experiments.scene_batching_v6 generate --recipe gsnap5 --seed S`（S = 20261011／12／13，顺序执行），日志 `.local/scene-batching-v6/logs/gen-gsnap5-S.log`。
- 2026-10-16 生成完成，3 个 run 均 complete、无失败、未续跑。墙钟 gsnap5／对照：274.9／275.9、243.2／250.6、272.9／280.8 s（合计 791.0／807.2，−2.0%；裁判未并发）；请求数 189／172／193 与对照相同；输出 token 108805／108911；可见 cue 上限 12／12，均值 10.9／11.6；显存峰值 15769–15820／15784–15793 MiB。
- 切法未变的批输出与对照**逐字相同**：未受影响 cue 893／893、956／956、985／985（§4 的前提成立）。受影响 cue 951、707、905 条，其中译文也相同的 387、278、367 条（约 40%）。受影响窗口 190、141、181（共 512 窗，每臂约 128 包）。子集文件 `.local/scene-batching-v6/subsets/gsnap5__s*.json`。
- 裁判：`... -m experiments.scene_batching_v6 judge --variant gsnap5 --seed S --parallel 3`，候选与对照副本 `b10-joint-ctl__sS__dev` 用相同包组成，日志 `logs/judge-gsnap5-S.log`。
- 2026-10-16 裁判完成：每臂 130 包（48＋36＋46），错误 0，未遇配额阻塞（批处理脚本最后的 `[ $rc -ne 0 ] && break` 让 shell 返回 1，不是裁判失败）。比较：`... -m experiments.scene_batching_v6 compare --variant gsnap5 --seeds 20261011 20261012 20261013` → `.local/scene-batching-v6/summaries/q2-gsnap5.json`（窗口单位、作品内分层 bootstrap 10000 次，种子沿用 v4）。
- 噪声底：受影响但译文逐字相同的 1032 条，Δ +0.005［−0.008, +0.016］；对照重判 − v4 原判（同一译文、不同包组成与时间）−0.012［−0.028, +0.004］。所以本设计里裁判噪声对配对差的影响小。

## Answer

**方向成立（剧集），机制不是 wrong-referent。** 在 2563 条受影响 cue 上（剧集 1540、电影 1023），`gsnap5` − b10-joint 的 accuracy 惩罚差：

| 指标 | 剧集 | 电影 | 总（50:50） |
| --- | --- | --- | --- |
| accuracy | **−0.048［−0.097, −0.001］** | +0.005［−0.043, +0.052］ | −0.022［−0.055, +0.012］，p(Δ≥0)=0.15 |
| wrong-referent | −0.001［−0.022, +0.020］ | −0.007［−0.032, +0.017］ | −0.004［−0.020, +0.012］ |
| mistranslation | −0.048［−0.092, −0.004］ | +0.022［−0.024, +0.070］ | −0.013［−0.044, +0.020］ |
| negation-number-condition | −0.007［−0.022, +0.002］ | −0.005［−0.024, +0.009］ | −0.006［−0.017, +0.003］ |
| 全集护栏（5397 条，未受影响记 0） | −0.019［−0.042, +0.003］ | +0.003［−0.022, +0.028］ | −0.008［−0.025, +0.008］ |

- 对照水平（受影响子集）0.406，候选 0.384（−5%）。译文变了的 1531 条上 Δ −0.034（剧集 −0.076［−0.162, +0.003］，电影 +0.009）。
- 交付失败 0／0；墙钟 −2.0%，请求数相同，可见 cue 上限 12 不变，显存峰值不变（15.8 GiB）。
- 与 Q1 的对照：Q1 预期的收益来自 wrong-referent，但实测 wrong-referent 几乎不变，剧集的改善在 mistranslation。可能的解释是去掉跨场景邻文与混批后词义消歧受到的干扰变少，但这是事后解释，未检验。
- 判定：受影响子集总 Δ < 0，剧集区间不含 0，电影持平，全集非劣。按 §4"方向成立再用独立 seed 复现"，进入 04。
