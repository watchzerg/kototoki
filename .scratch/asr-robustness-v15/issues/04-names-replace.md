# 04 C3：HF III Q3 建表、C3a 规则替换、C3b Flash-Next 表内替换、Opus 抽看

Status: resolved
Type: research
Stage: C（GPU ≤2 run：预计 1 个 Strata session；Opus ≤$3）

权威：研究文档 §4.3、§4.0、§5；ADR-0014 第 2 点规则一；ADR-0022（产品建表配方 `q3-names-v1`）。

## 范围

- 在一个 Strata session 内：先用 `kototoki.names.build_document` 按产品配方为 HF III 建 Q3 表（最多 5 次，取第一张合格表；5 次都不合格则两部都用 27B 旧表并记 §8），再跑 C3b。
- C3a（离线）：high 条目按 `zh` 分组，组内以转写出现最多的写法为规范写法整串替换；落点不得是更长表内写法的一部分；单字写法不替换。
- C3b：提示 `ja-names-v1`，包、邻文、采样、seed、守卫同 v14 §4.3；程序约束——diff 之外逐字相同且所有替换片段都是表内写法，否则整条回退并计数。
- 评估：两部单元 CER（S／D／I，对照分母）、改动 cue 数、改好／改坏／无影响、人名命中率（定义写明）、有害率；与 v14 C2 v2 在 HF II 同表下并列。Opus 抽 30 条（改好／改坏各半）写错误类型。
- 记墙钟、每包耗时、显存／内存峰值、提议／采纳／回退数。

## 完成标准

- `.local/asr-robustness-v15/04/` 下建表产物、C3a／C3b 的 `ja.srt`、changes、eval、Opus 笔记；§7 一行；是否触发 05 写明（两部都不升且有害率 ≤10%）。

## 执行记录

- 2026-11-10：`names_replace.py` 实现（分组、C3a、C3b 守卫、Strata session、评估、抽样；29 项离线测试）。开跑前核对：可用内存 37.8 GiB（<52），无 Strata／llama-server／gpu.lock；不启动 Strata。`names-rules`（c3a、c3a-oldtable、附录 c3a-entity、c3a-entity-oldtable）、`names-eval`、`names-sample`（23 条：改好 12／改坏 11 全部）、Opus 抽看（≈90K token）。
- 2026-11-10 补跑：用户重启机器后要求接着跑完。核对无 Strata／llama／gpu.lock，可用内存 54.0 GiB，`--plan` 下载 0；`names-build`（session-01／run-01）→ `names-rules` → `names-eval` → `names-sample`（30 条：c3a 8、c3b 22）→ Opus 抽看（≈100K token）。旧 C3a 笔记／抽样／评估备份为 `opus-notes-c3a.json`、`sample-c3a.json`、`eval-pre-rerun.json`。结束后 Strata 已停、显存 961 MiB。

## Answer

- 离线部分：C3a（§4.3 频次规则）HF II Δ0（12／11／16，有害率 28%，命中率 65→75%）；HF III 旧表 −11（有害率 16%）。附录头写法变体 HF II −26（−0.24 pp，有害率 19%）、HF III 旧表 −14（有害率 17%）。Opus：改坏＝惯例不一致 5＋规范写法本身错 5＋换错实体 1。频次规则把 ASR 习惯性误写选成规范——写进研究文档 §8 第 10 项。
- 首次未执行：HF III Q3 建表、C3b（Strata 不可启动，§8 第 9 项给了补跑命令）。
- 补跑（2026-11-10，重启后，GPU 1 run／墙钟 303.5 s，专家区在内存）：HF III Q3 表 1 次请求合格（23 条／high 19）；其上 C3a −28（有害率 17.1%）、头写法 −51（−0.45 pp，有害率 23.0%）；C3b HF II Δ0（31／21／9，有害率 34.4%，提议 196／采纳 61）、HF III +4（26／19／11，有害率 33.9%，提议 173／采纳 56）；命中率 → 75–76%。Opus 30 条：C3b 能纠正同音误写，但把称呼扩成表内全名、换掉已对写法，改坏约六成是真实损伤。**05 不触发**（`trigger_05.eligible` 为空，有害率 16–34% 都 >10%）。数字全文在研究文档 §7 "04 补跑"行。
