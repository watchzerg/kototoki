# Strata v12–v13：翻译模型与建表模型换成 Strata＋Qwen3.8-Flash-Next

## 状态
concluded。v12 于 2026-11-08 结题，v13 于 2026-11-09 结题。结论是 Q2（[ADR-0017](../../docs/adr/0017-q2-strata-default-launch-baseline.md)）与 Q3（[ADR-0021](../../docs/adr/0021-q3-strata-names-baseline.md)）两条基线的依据；产品已按 [ADR-0019](../../docs/adr/0019-product-translation-q2.md)、[ADR-0022](../../docs/adr/0022-product-names-on-strata.md) 切换。Q3 是现行唯一翻译基线（对照规则见 [ADR-0018](../../docs/adr/0018-q2-sole-translation-baseline.md)，身份见 ADR-0021）。评估方法见本文"测试"一节。

## 时间
2026-11-08 立项（v12、v13 同日起草并经用户裁定）；v12 同日结题，v13 于 2026-11-09 结题。

## 问题
- v12：Q1 的最后一步翻译，把 llama-server＋Qwen3.8-27B 换成 Strata 上的 Qwen3.8-Flash-Next，质量与墙钟如何？
- v13：产品 `names` 阶段的建表，把 27B＋llama-server 换成 Strata Flash-Next，表质量与下游翻译能否非劣？

## 策略
- v12 F1：只换翻译模型与推理引擎，切包、邻文、提示、专名表注入、采样都与 Q1 相同；对照 Q1（沿用 v11 已有译文，dev 对照同期重判）。阶段：smoke 可行性门 → dev 3 seed → 产品 ASR 源 seed 54–56 →（条件触发）有界思考，后者未触发。
- v12 之后用户裁定：直接以"不加参数的 `strata launch`"（DFlash2 草稿器）为 **Q2**，不再单独比较 MTP 与 DFlash2。
- v13 S1：只换建表模型与引擎（Q2 启动方式）；提示 v5、程序兜底、采样与两次尝试规则不变。翻译两臂都用 Q2 规则，只差注入的专名表；阶段：建表可行性门 → dev 表质量非劣 → dev 翻译 3 seed → 产品 ASR 源 seed 54–56。S1 试了 v1（输出上限 4096）、v2（8192）、v3（加 `response_format`）、v4（最多 5 次尝试，即 `names-strata-v4`）。

## 环境与版本
- 引擎：Strata 0.2.12（引擎 build 0.1.58，Windows CUDA 13）；模型 `qwen3.8-flash-next-iq3_s`（ISTA-DASLab `Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S`，约 84 GB）。Strata 是自带 Python 的本地服务，OpenAI 兼容 `/v1/chat/completions`；没有 GBNF、没有 `/apply-template` 与 `/tokenize`（以 `count_tokens` 代替），`top_k` 上限 64，每个请求显式 `enable_thinking: false`。
- v12 F1 用 MTP 草稿层（`kototoki-translate` 预设：32k、parallel 1、vision off）；Q2／Q3 用不加参数的 `strata launch`（DFlash2）。
- 对照：Q1（Qwen3.8-27B UD-IQ3_S，llama.cpp b11669）；v13 对照现行 27B 建表。
- GPU RTX 5080（16.3 GB），整机内存 64 GB。Strata 运行时显存约 16 GB、内存约 61–64 GiB，几乎占满，不能与 llama-server 同驻。

## 测试
- 数据：dev 44 场景、5397 条 cue（剧集与电影，15 部作品，字幕组时间轴）；产品 ASR 源为 2 部日语电影（HF II／III）的产品 w0 `ja.srt`（普查 1728 单元，按日文 CER 分 exact／light／heavy 三桶）。seed：dev 20261011–13，产品 20261054–56。
- **dev 裁判**：`claude-opus-5-5-mqm-v1`（Claude Opus 5.5，effort high，空工具与空 setting 的 CLI 隔离执行，模型身份校验必须是 `claude-opus-5-5`）。盲评：每包 4 个窗口、候选以不透明标识呈现，裁判看得到日文、参考中文与可接受歧义。MQM 只标错误不打总分，严重度 minor 1／major 5／critical 10；accuracy 类为 mistranslation、omission、addition、wrong-referent、negation-number-condition、cue-attribution，fluency 类为 grammar、unnatural、register、terminology-inconsistency。**对照必须与候选同期、同一包组成重判**（重判漂移约 −0.012～−0.018，与候选效应同量级）。
- **产品 ASR 源裁判**：`v5-asr-pairwise-v1`，成对盲评。每个条目给参考日文（前后各 2 条作语境）与盲序 A、B 两份中文，裁判分别列错误（权重同 MQM）并给 A／B／tie 偏好；x 为对照、y 为候选，同 seed 同条目内比较，不需要同期重判。逐字相同的单元不送裁判，按 Δ＝0 计入。
- **统计（dev）**：主终点是每条 cue 的 accuracy 惩罚差，候选减对照（越低越好）；作品内按 cue 平均，类别内作品等权，剧集与电影分开；未交付的 cue 记 10 分并计入 major+ 与 critical。区间是配对 bootstrap：按作品分层，作品内按 5 条 cue 一组的窗口有放回重抽，10000 次，报 CI90。次要：fluency、major+、critical、各错误类别、交付失败、墙钟。作品为聚类单位，三 seed 起才谈质量。
- **统计（产品）**：每个桶算 Δ＝候选惩罚 − 对照惩罚的单元均值，单元有放回重抽 4000 次，报 CI90，另报偏好、人名错误差与整片不一致率。
- **判据**：非劣界 0.05（每类 CI90 上界 < 0.05）；"改善"只在 CI90 上界 < 0 时写；wrong-referent 的非劣要求 CI90 下界 ≤ 0。
- **人名相关错误口径**：数裁判给出的错误中，证据文字命中"人名／名字／姓名／称呼／译名／专名／角色名／昵称／音译"之一者（dev 口径另含"名称／地名"）；产品口径还把 `terminology` 类错误计入。dev 与产品两个口径的计数互不比较；产品口径以单元数归一（如 +0.005 约等于 1728 单元多 9 个）。
- **整片不一致率**：同一作品内人名／专名的写法分歧（alt／(main＋alt)），不是裁判输出，只证明"照表执行"。表质量另用"出现加权一致率"对参考中文量。
- 不开封任何确认集；A/A 重跑量化噪声底。

## 结果
v12（F1＝Strata 翻译，对照 Q1）：

| 项 | 结果 |
| --- | --- |
| 可行性 | 1599 包首次失败 3、交付失败 0；思考完全关闭；同 seed 不复现（A/A 约 44–49% cue 不同） |
| dev accuracy | 剧集 −0.186、电影 −0.126，都显著；15 部作品中 14 部变好 |
| 产品 accuracy | 全体 −0.269，exact／light／heavy −0.133／−0.216／−0.607，都显著 |
| 人名错误（产品） | 79 对 89；差 CI90 上界 +0.0006，字面不过 ≤0 的门，用户裁定为边界噪声 |
| 代价 | 墙钟 −26～−29%；显存 16.1 GB；整机内存 61.6–63.5 GiB |

v13（S1＝Strata 建表，翻译用 Q2 规则，对照 27B 建表）：

| 项 | 结果 |
| --- | --- |
| 可行性（原门首次失败 ≤2／17） | v1–v4 首次失败 5／6／6／4；v4 最多 5 次内 17／17 成功；失败都是写满 8192 token 的失控，`response_format` 无帮助 |
| 表质量（dev） | 一致率 0.706 对 0.652，非劣；条目多 65%；真串名 3 组对 1 组；两次建表写法 Jaccard 仅 0.56／0.48 |
| dev 翻译 | 剧集 wrong-referent +0.042（显著变差，集中在两部表出错的作品）；电影 accuracy −0.049 显著变好 |
| 产品翻译 | 全体 −0.095，light −0.267；人名错误 65 对 78；不一致率 0.023 对 0.042 |

## 结论与去向
- v12：F1 优于 Q1，用户裁定作为新基线候选；同日定为 **Q2**＝Q1 规则＋Strata 不加参数启动（DFlash2）（[ADR-0017](../../docs/adr/0017-q2-strata-default-launch-baseline.md)）。
- v13：按门写"S1 不进"（dev 剧集 wrong-referent 显著变差、Strata 建表单次不稳、两次建表差别大）；用户 2026-11-09 仍采纳 S1 v4 为基线 **Q3**，建表最多 5 次尝试（请求用 seed、seed＋1…，取第一张合格表就停，是可靠性重试而非挑选，[ADR-0008](../../docs/adr/0008-no-multi-translation-selection.md) 不涉及），风险已知并接受（[ADR-0021](../../docs/adr/0021-q3-strata-names-baseline.md)）。产品随后建表切到 Strata，规则与 Q3 一致（[ADR-0022](../../docs/adr/0022-product-names-on-strata.md)）。
- 专名一致性研究线不再提议新轮次。

## 教训
- Strata 无约束解码：长 JSON 输出要靠事后校验加重试；输出上限要给足（Flash-Next 的表约为 27B 的两倍长）。
- 同 seed 不复现是常态（Strata 约 49%，llama-server 约 24%），所有配对比较带噪声底；A/A 重跑应是标配。
- 建表质量决定注入效果；Q3 的产品证据来自单次建表，且只有两部同系列电影、无确认集。
- 字面门被 +0.0006 级别的差距卡住时，要在报告里写明点估计与界，由用户裁定而非静默改判。
- 内存几乎占满：启动前需可用内存 ≥52 GiB，否则引擎退到 mmap 导致每包约 6 倍慢。
- 预算：v12 GPU 约 10 run／裁判约 $115 上限内，v13 GPU 13 run 上限／裁判约 $80 上限。

## 原始材料
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-11-08-strata-flash-next-usage.md`
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-11-08-strata-flash-next-v12.md`
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-11-08-names-on-strata-v13.md`
- `archive/2026-11-18-pre-research-restructure:experiments/scene_batching_v6/`（评估与统计实现：`asr10.py`、`v9.py`；`archive/2026-11-18-pre-research-restructure:experiments/translation_v4/stats4.py`）
