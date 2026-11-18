# 翻译流程探索 v1–v4：固定 Hy-MT2 30B 后，批次、上下文、提示与采样有没有可确认的改进

## 状态
concluded（v1、v3、v4 按各自停止条件结题）；v2 stopped（2026-10-10 中止，不续跑）。整体结论：没有配方在确认集上"全面"优于基线，只有 v4 的 `mbr8c` 通过确认但被 ADR-0008 放弃；`b10-joint` 因工程理由被采纳为流程基线。

## 时间
v1 2026-10-07；v2 2026-10-08 起、2026-10-10 中止；v3 2026-10-10；v4 2026-10-11。

## 问题
模型固定为 Hy-MT2 30B-A3B APEX-I-Compact（H0，见 [model-selection](../2026-10-translation-model-selection/README.md)）后，日文 SRT 到中文 SRT 的整片流程里，批次大小、前后只读邻文、提示、术语与审校、输出协议、采样、多候选选择，哪些能在独立确认集上稳定改善质量或速度？

## 策略
基线 C0：每批 5 条目标 cue、前后各 1 条只读邻文、ID JSON 加 GBNF、官方采样与前缀缓存。

- v1（8 窗＋3 个固定 seed 的小筛选）：批次与邻文、协议、术语、自审等低成本方向的具体配方，对 C0 无确认优势；文首更正：证据只说明"所测配方未过筛选"，不能淘汰整个方向。
- v2（96 筛选窗＋48 独立确认窗，裁判 `gpt-6.1-sol`）：批次大小 b1–b80 与 token 分批、邻文 ctx0–ctx8、非 JSON 协议（id-text、flex、ordered）、语义单元规划再映射（F5）、术语（F6）、背景风格（F7）、全量审校（F8）、有界空白 grammar 等；没有配方到确认级门槛，确认窗从未开封。
- v3（19 个配方，裁判换为 Claude MQM，重新起跑）：单因素 B／T（批大小、token 分批）、X（邻文）、J（joint 提示：先共同理解可见台词与跨条目的条件、否定、指代，再分别表达各 ID）、P（术语预分析）、R（选择性审校）、W（有界空白 grammar），再加组合 `b10-joint`（每批 10 条目标＋joint 提示）。
- v4（新 dev／确认集）：方向 1 重建量尺，方向 2 采样（t0、`t03`＝temperature 0.3、top_p 0.9），方向 3 多候选选择（`mbr8c`＝每批 8 样本、逐条 chrF-MBR；按批 MBR；N=3），方向 4 译文上下文（注入前 10／30 条自己的译文）。对照为 `b10-joint`。

## 环境与版本
- 模型、引擎与 GPU 同 [model-selection](../2026-10-translation-model-selection/README.md)：APEX-I-Compact（`alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF` @ 312cce86）、llama.cpp b11429 兼容 loader（CUDA 13.4）、RTX 5080 16 GB；总 context 8192、输出上限 4096、最大输入 4032 tokens、49/49 层 GPU。
- 裁判：v1／v2 为 `gpt-6.1-sol`（high，codex-cli），v3／v4 为 `claude-opus-5-5-mqm-v1`（Opus 5.5，effort high，CLI 盲评，每包同一 run 的 4 个窗口，提示词 v2）。两套分数不可比。
- 参考：字幕组中文经 LLM 复核修订；v3 前用 Opus 5.5 复核了 144 窗（720 条评分 cue，只改 6 条，置信度 high 585／medium 135）；v4 dev／confirm 参考同样经 Opus 5.5 复核（改动约 4–5%）。

## 测试
- v1：4 部作品、8 个开发窗（40 条评分 cue），扩为 120 cue 的连续 SRT 片段做完整流程；不是全片。
- v2：34 个场景（4297 cue）、96 筛选窗＋48 确认窗（源区间与筛选集隔离），每配方 3 seed；旧裁判盲重复噪声：语义逐对翻转率 16.7%，自然度 48/48 全为 2 分（天花板）。
- v3：同一 96 筛选窗（screen-a／b 两半组）＋20 场景 48 窗的确认集，3 seed；主终点为 accuracy 惩罚均值（minor 1、major 5、critical 10，越低越好），先 seed 平均，再作品等权、剧集电影各半；冻结的判定规则：MDE 0.05、非劣界 0.05、critical 不得增加、风险窗 major+ 上界 0.10。校准：参考自检 accuracy 0.004，合成扰动检出率 0.95，重复噪声 SE 约 0.02–0.03。
- v4：dev 44 场景／5397 cue（11 部剧集、4 部电影），封存确认集 55 场景／5996 cue，每场景 3 seed；每条 cue 都评分，bootstrap 在作品内按 5 条窗口重抽；确认用 Holm 校正。

## 结果
| 轮次 | 配方 | 结果 |
| --- | --- | --- |
| v1 | 低成本方向的具体配方 | 8 窗筛选无确认优势，基线不变 |
| v2 | b10／b20／b40、token400、joint 等 | 剧集常 +0.1 至 +0.5、电影跨零，半组间常不复现；ordered 协议电影 −0.157；F5 成本最高 |
| v3 | 13 个单因素 | 0 个 promising；组合 `b10-joint` 筛选 Δ −0.093［−0.124, −0.054］ |
| v3 确认 | `b10-joint` vs C0 | Δ −0.012［−0.053, +0.033］，Holm p 0.31，未通过；剧集 +0.072 劣、电影 −0.097 |
| v3 工程 | `b10-joint` 整片 | 墙钟约 −7%、请求数减半、fluency 更好、critical 不增；1993 条电影与 387 条剧集整片完整交付 |
| v4 | `t03` | dev −0.021（复现 −0.0225），确认 −0.004（p 0.32），未通过 |
| v4 | `mbr8c` | dev −0.021（复现 −0.024），确认 −0.016，Holm p 0.016，通过；剧集 −0.035、电影 +0.002；GPU 8 倍、墙钟约 6.2 倍 |
| v4 | 译文上下文 tctx10／30 | 术语不一致 22 → 5／8，指代错误 455 → 491／499，总体无可检出效应 |

v4 回溯：v3 的作品聚类 bootstrap 把 SE 低估约 2.5 倍（0.018 对作品内窗口重抽 0.044）；v3 的 15 个筛选候选 |z| 均值 0.83，与全零效应期望 0.80 一致，筛选好、确认差主要是赢家诅咒加低估的噪声。

## 结论与去向
- 基线始终是 C0（`official30b-cached-v1`）；v3 没有配方通过确认，`b10-joint` 在确认集未复现。用户出于工程理由（更快、请求数减半、整片完整交付）采纳 `b10-joint` 为流程基线，即原 [ADR-0006](../../docs/adr/0006-b10-joint-translation-flow-baseline.md)（已并入 [ADR-0010](../../docs/adr/0010-dp10-cut-translation-flow-baseline.md)，该 ADR 记录了 `b10-joint` 的来源与 `dp10-cut` 的后继）。
- v4 `mbr8c` 通过确认但约 6 倍墙钟，且属"翻译多次再挑选"：用户放弃，规则见 [ADR-0008](../../docs/adr/0008-no-multi-translation-selection.md)（v5 的 `mbr8s` 同一结论，见 [quality-v5](../2026-10-quality-v5/README.md)）。`t03` 不采纳。
- 不建议再投入：有界空白 grammar（空白循环约每 1400 个场景 run 出现 1 次，重试即可）、场景术语表、选择性审校（墙钟 +64%、critical 为 C0 的 4 倍）、只调邻文、b20 以上批次、token 500 级分批。
- 后继：批次切法见 [batching-v6-v8](../2026-10-batching-v6-v8/README.md)，产品翻译配方沿革见 [ADR-0010](../../docs/adr/0010-dp10-cut-translation-flow-baseline.md)。
- 确认集状态：v2 的 48 窗确认集从未开封（v2 中止）；v3、v4 的确认集均已开封，不得再用于确认，新的确认须用全新隔离的集合（供 `research/INDEX.md` 研究方法约束引用）。

## 教训
v2 为什么停：（1）旧裁判 `gpt-6.1-sol` 已不可用，换裁判后所有旧分数不可比；（2）整套"参考／裁判隔离"被实现成多层签字与 sha256 自校验链（约 4.2 万行代码，`summaries/` 达上千项），GPU 常因路径、标记、哈希字段不一致而停队列，是流程脆弱而非科学问题；（3）到交接时仍没有任何配方达确认级门槛。用户于 2026-10-10 决定不续跑，新开 v3，只复用数据资产与先验。

v1／v2 先验：
- 零候选是合法结局；批次、邻文、联合理解的收益几乎只出现在剧集，电影多跨零，同一配方在两个半组间常不复现，必须按剧集／电影分层并要求独立复现。
- 风险窗的严重错误（major／critical）必须与均分并列做主终点；大批次减少误译，但带来跨 cue 指代错误。
- 4096 输出触顶在所有批大小都会出现，是 JSON 字符串外的空白循环，与输入长度基本无关，同请求重试通常成功；批次越大并不明显更快，生成 token 数主导耗时（速度收益上限约 10–15%）。
- 自然度 0–2 有天花板，只能检出退化；语义 0–4 粗糙，旧裁判盲重复语义翻转率 16.7%，须用错误列表式（MQM）评分。
- 容量边界：8192 context、输出预留 4096，输入上限 4032 tokens，显存余量仅 100–260 MiB，不要加 context 或并行槽位。
- 评测工程：只保留三条真正重要的隔离（翻译只见日文、确认窗封存、候选盲评），砍掉多重封签；作品和窗口的异质性大于配方效应，筛选后必须换内容确认（只换 seed 的复现不能预测回落）。

## 原始材料
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-07-hy30-flow-optimization-results.md`、`2026-10-07-hy30-flow-parameter-check.md`
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-10-hy30-flow-v1-v2-lessons.md`
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-10-hy30-flow-v3-report.md`、`2026-10-11-hy30-flow-v4-report.md`
- `archive/2026-11-18-pre-research-restructure:docs/plans/hy-mt2-translation-flow-exploration-v2.md`（v2、v3、v4 计划同目录）
- `archive/2026-11-18-pre-research-restructure:docs/testing/2026-10-10-reference-v3-audit.md`
- `docs/architecture/modules/translation-srt-flow.md`（v3 配方与 `translate-srt` 入口）
