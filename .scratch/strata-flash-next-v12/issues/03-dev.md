# 03 dev 3 seed＋A/A＋Q1 同期重判

Status: resolved
Type: GPU
Stage: C
Blocked by: 02

范围、终点与门见研究文档 §4.3（docs/research/2026-11-08-strata-flash-next-v12.md）。

## 执行记录

- 2026-11-08 核对：无 llama-server／Strata，无锁，显存 1.0 GB；`--plan` 下载量 0；启动 `kototoki-translate`（不再下载）。Q1 3 个 dev run（v11 复制、不带判分）先同期重判（12:26–12:57，均 exit 0）。
- GPU 链（`logs/gen-queue.sh`）：F1 s20261011／12／13 各 702／600／689 s（Q1 同 seed 938／850／978 s），A/A 重跑 s20261011（`runs-aa/`，约 11 分钟）。GPU 4 run。
- 判分链（`logs/judge-queue.sh`）：每个 F1 seed 在 run 完成且同 seed 的 Q1 判完后先 `copy-identical`（两臂相同 cue 1041／5397，没有整包相同，复制 0 包），再 `judge-run`。裁判合计 $57.56（F1 $28.12：9.63／8.71／9.79；Q1 $29.43：10.00／9.12／10.32），无配额中断。脚本末尾 `[ $code -eq 75 ]` 为假使链返回 1，不是失败。
- `compare11`（相同 cue 按 Δ＝0）→ `summaries/v11-flash-names-high-vs-qwen-names-dev-high.json`。
- 运行统计（`checks/stats-flash-names-high.json`）：621 包，首次失败 1（s11 一包 `limit`），重试后接受；交付失败 0；思考输出 0；超 Q1 预算 0；log 推理自救 0、非有限 logits 0。每包均值 3.14–3.25 s（p90 ≤3.70 s，最大 6.82 s）。显存峰值约 16.1 GB，整机内存峰值 62.5–62.9 GiB。
- 那一包 `limit` 的原因：server log 记 "the reply repeated one token ... 256 times in a row: ended as length"，即 Strata 的**重复截断**（`repeat_stop_tokens`）——调研未记的第三种自动行为；输出 541 token 处被截。已把这一模式加进 `strata.LOG_EVENTS`（`repeat_stops`），04 起计数。
- A/A（`checks/aa-flash-names-high-s20261011.json`）：218 包中 188 包（86%）、1844 cue 中 912 个（**49%**）文本不同。
- 结束后 `strata launch --stop`，显存 964 MiB，无残留进程，无锁。

## Answer

**改善（两类都显著）。** 对照 Q1（`qwen-names-dev-high`，同期重判），F1 `flash-names-high`（`60bd457f…`）3 seed、5397 cue：accuracy 剧集 −0.186［−0.231, −0.142］、电影 −0.126［−0.173, −0.078］；wrong-referent 剧集 −0.003［−0.019, +0.012］、电影 −0.010［−0.035, +0.014］（下界都 ≤0）；unnatural 剧集 −0.020［−0.028, −0.011］、电影 −0.008［−0.017, +0.001］；mistranslation、addition、omission、major+ 两类都显著下降。15 部中 14 部变好（W06 +0.023）。人名相关错误 78 对 98；dev 不一致率 0.014 对 0.017（剧集 0.015 对 0.008 变高、电影 0.014 对 0.025 变低）。交付失败 0，首次格式失败 1／621。墙钟比 Q1 快约 29%。A/A cue 不同 49%。C → D 不阻断。
