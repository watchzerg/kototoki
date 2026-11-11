# 14 mbr8s 剧集确认

Status: resolved
Type: research
Blocked by: 08, 10

## 范围

- 08 的语义选择 `mbr8s` 在 dev 与独立重复 seed 上都复现（vs b10-joint −0.035／−0.038），按研究文档 §3 "筛选与确认分离"需要在冻结前不读的全新确认集上单侧检验。09、10 的 dev 结果出来后锁定 Holm 家族（只放复现通过的候选），再建确认集。
- 确认集：电影已被 v4 confirm 用尽，只能建剧集确认集（`experiments/quality_v5/confirm_set.py`：v2／v3 与 v4 dev／confirm 都没碰过的整集，11 部各 2 集、每集 120 条，2640 条）。确认结论只覆盖剧集，电影注明未确认。
- 流程沿用 v4：`confirm_set.py` 建集 → `review --set confirm`（Opus 复核字幕组中文为参考，不打印内容）→ `freeze-reference` → `locked-candidates.json`（家族、对照、生成用基准配方 mbr8 与 hash）→ 真实生成 b10-joint 与 mbr8 的 confirm 3 seed → 离线派生 mbr8s（与真实早停／选择等价：串行生成确定，07 探针已验证）→ 全判 → `confirm`（单侧＋Holm，只运行一次）。
- 判定规则沿用评测根里冻结的 `decision-policy-v4.json`（alpha_confirm 0.05）。

## 预算

- 生成：confirm 3 seed × {b10-joint, mbr8}（mbr8 约 2400 s／seed）。
- 裁判：b10-joint 与 mbr8s 各 3 run 全判（预计约 800 包）；与 08 合计不超过 v4 单方向用量。
- 参考复核：22 个场景的 Opus 调用。

## 完成标准

- 确认集 manifest、参考冻结记录；Holm 结果（Δ、SE、p、调整后 p）；剧集与电影的确认范围说明；成本。

## 文件所有权

`experiments/quality_v5/`、评测根 `.local/quality-exploration-v5/07/root/`（sets/confirm、evaluation-only/confirm、locked-candidates.json）；研究文档。

## 执行记录

- 2026-10-16 14:55 claimed（08、10 已结题；09、10 都没有复现候选，家族只有 mbr8s）。先锁定再建集：评测根写 `locked-candidates.json`——候选 mbr8s（伪 run，配方／hash 同 mbr8c `701c04a4…`）、生成用 mbr8（`role: generator`）、对照 b10-joint；`holm_family: [mbr8s]`，alpha_confirm 0.05，policy sha256 记入；未锁定的 07／09／10 变体与原因一并记录。

- 2026-10-16 14:57 建集（`confirm_set.py`，锁定之后）：22 段、2640 条，11 部剧集各 2 集 240 条；seed 块 840／960／840，A／B 半区各 1320；参考复核输入 8 个分片（`evaluation-only/confirm`，不打印）。
- 2026-10-16 14:58 并行启动：Opus 参考复核 `review --set confirm --parallel 3`（`14/review.log`）；GPU 核对（无 gpu.lock，两个 python 进程是复核本身，整卡 473 MiB）后真实生成 confirm 3 seed（20261031–33）：先 b10-joint，再 mbr8（`14/gen.sh`、`14/gen-log.txt`）。

- 2026-10-16 参考复核完成：22 场景、0 错误、未阻塞；`freeze-reference --set confirm` 冻结 `evaluation-only/confirm/reference/cues.jsonl`（sha256 `d8b3a806…`；置信度 high 2410／medium 228／low 2，带歧义标注 813 条）。
- 2026-10-16 b10-joint confirm seed 20261031 生成 410 s。串联脚本 `14/judge_chain.sh`：b10-joint 每个 seed 生成完即判；mbr8 三个 seed 生成完后用 `mbr_semantic --scope confirm --base mbr8` 派生 mbr8s，再判（`14/judge-log.txt`）。

- 2026-10-16 生成：b10-joint confirm 3 seed 各 410–412 s；mbr8 confirm 3 seed 各 2566–2612 s（无失败场景）。mbr8s 派生：与 chrF 逐条选择不同的 cue 20.4–22.9%，embedding 2.7–3.3 s。
- 2026-10-16 18:09 裁判完：6 run、798 包（每 run 133 包、976–1032 s），无错误、无阻塞。
- 2026-10-16 18:12 第一次 `confirm`：v4 `stats4.aggregate_sums` 在缺一类时 `overall` 为 None，判定门槛 TypeError，**未写结果、未打印任何分数**（只运行一次的检验没有被消耗）。新增 `experiments/quality_v5/confirm_series.py`：运行时把 `overall` 改为"有值类别的均值"（单类即剧集值），其余照 v4 原样，再运行 `confirm`（唯一一次出结果）。
- 2026-10-16 18:15 结果（`summaries/confirm-holm.json`）：剧集 Δ **−0.0356**，SE 0.0101，CI90 [−0.052, −0.019]，单侧 p 0.0004，Holm p 0.0004（家族 1 个），reject；critical Δ −0.001，major+ Δ −0.005，交付失败 0／0；11 部里 10 部为负（W03 +0.010），leave-one-work-out 全负。门槛 `category_noninferior` 为 false——v4 要求每个类别都有值，电影为 None；其余门槛全过。v4 判定字面为 `not_confirmed`；按锁定文件里预先写明的"只含剧集"范围，剧集上全部条件成立。
- 2026-10-16 一致率（confirm，每 seed 对比）：Δ −0.011／−0.020／+0.021，平均约 −0.004，无变化。

## Answer

**结论：`mbr8s`（8 样本＋bge-m3 语义逐条 MBR）在全新封存的剧集确认集上确认有效：剧集 Δ −0.036（CI90 −0.052 到 −0.019，单侧 p 0.0004，Holm 后不变），安全门槛全过；电影没有确认材料，未确认。**

| 项 | 值 |
| --- | --- |
| 确认集 | 22 段、2640 条，11 部剧集各 2 个 v2／v3／v4 都没碰过的整集；参考 Opus 复核后冻结（sha256 `d8b3a806…`） |
| 剧集 Δ（vs b10-joint） | −0.0356（SE 0.0101，CI90 −0.052 到 −0.019；惩罚 0.487 → 0.451，约 −7%） |
| p／Holm | 0.0004／0.0004，reject |
| 安全门槛 | critical −0.001、major+ −0.005、风险上界合格、交付失败 0／0、leave-one-work-out 全负；`category_noninferior` 因电影为 None 字面不过 |
| 作品 | 10／11 为负（W03 +0.010） |
| 一致率 | 无变化（平均约 −0.004） |
| 成本 | 生成 6.3 倍（2557–2599 s vs 410–411 s／seed）；裁判 798 包（约 $80）；参考复核 22 次 Opus 调用 |

- 与 v4 的关系：v4 确认的 mbr8c（chrF）在 v4 确认集上 Δ −0.016（剧集约 −7%、电影无收益）；本轮 dev 上 mbr8s 比 mbr8c 再好 0.014（dev 与重复 seed 都复现）。本确认没有同时测 mbr8c，两者在确认集上的差未直接检验。
- 进产品需要的事（列 §8，不自动做）：v3 配方加语义选择器字段（目前只接受 chrF）、bge-m3 权重与依赖的供给、6 倍翻译墙钟的取舍（07 的并行槽位可省约 25%，质量未验证）、ADR。
- 产物：`experiments/quality_v5/confirm_set.py`、`confirm_series.py`；评测根 `sets/confirm`、`evaluation-only/confirm`、`locked-candidates.json`、`summaries/confirm-holm.json`；日志 `.local/quality-exploration-v5/14/`。

## Comments

- 2026-10-16 建票（执行 08 时追加）：08 是本轮唯一复现通过的候选，07 已备好剧集确认集脚本；为满足 §3 的确认纪律单列一张，不改 08 的结论。
