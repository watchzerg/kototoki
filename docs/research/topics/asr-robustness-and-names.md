# ASR 交叉合并、稳健性与专名一致性

状态：current（子索引；条目是登记时的摘要，结论以报告正文与[决定索引](../../adr/INDEX.md)为准）

条目格式：`[主题](文件.md)：一句话结论；适用条件或限制`。条目文字自[调研索引](../INDEX.md) 2026-11-11 拆分时原样搬来，新报告在对应小节追加一条。

## w0／x0 两路 ASR 交叉合并：oracle 上限、MMS 声学裁判与交叉打分（2026-10-19）

- [oracle 上限测算](../2026-10-19-asr-pair-oracle.md)：concluded（纯离线 CPU，待用户裁定是否开新线）。HF II／III 的产品 w0、x0 `ja.srt` 与参考按时间重叠连成三轨单元，逐单元字符级编辑距离：oracle 选择（取更接近参考的一路）两部合计 CER 16.16% → 12.46%，oracle 拼接（逐分歧区间、全局最优）→ 11.90%；增益一半来自删除对方多出的插入字。分歧区间 1253 个（覆盖约 13% 参考字符，无时间集中），两路都错占有参考单元 48%（40% 完全相同），30 个区间人工分类中 8 个仅是表记差异。适用：这两部电影、产品 w0／x0 配置、SRT 显示字幕参考；未覆盖：真实选择器的准确率与成本（未测，也未试任何第三方模型）、译文层收益、剧集。脚本 [`experiments/quality_v5/asr_pair_oracle.py`](../../../experiments/quality_v5/asr_pair_oracle.py)
- [MMS CTC 声学裁判与 w0 幻觉过滤](../2026-10-19-asr-pair-ctc-judge.md)：concluded（GPU 只做 MMS 前向，待用户裁定）。Part A：每个分歧区间构造只差该区间的两个整单元假设，CTC 前向对数似然（OOV 用常数列 log(1/2268)，区间含 OOV 的 47 个排除），规则 score_x − score_w > m＋λ·Δlen，跨片调参（II λ −0.75／m 16.5，III λ 1.75／m 16.0）：CER 两部合计 16.16% → 15.40%（oracle 拼接 11.90%），改动 82 个区间、54 个与 oracle 一致；w0 多出 AUC 0.71／0.79，替换 0.54／0.48，30 个人工样本只改 1 个，表记差异一个未动。Part B：插入 vs 完全一致的单元，每字 Viterbi AUC 0.975、Whisper 窗口 avg_logprob 0.914，跨片阈值丢弃后 CER 16.16% → 16.14%（上界 15.41%）。适用：这两部电影、产品 w0／x0、MMS `jpn` 原样；未覆盖：读音级打分、逐 cue 过滤、听音核对、剧集与官方整片口径。脚本 [`experiments/quality_v5/asr_pair_ctc_judge.py`](../../../experiments/quality_v5/asr_pair_ctc_judge.py)
- [Whisper 与 Qwen 交叉打分裁判](../2026-10-19-asr-pair-cross-score.md)：concluded（GPU 只做两个产品 ASR 的教师强制前向，待用户裁定）。同一单元、区间与跨度；Whisper 用 CT2 `align()` 的 `text_token_probs`（sot 前缀，CT2 自动补 notimestamps，不含 EOT），Qwen 用 `apply_transcription_request` 提示后接假设与 `<|im_end|>` 单次前向；SRT 原文只替换区间字符。跨片调参：Whisper 14.31%（λ 0／0.25、m −1）、两者都同意 14.23%、之和 14.56%、Qwen 15.09%、三路加 MMS 14.60%；准确率 72.0%／72.2%（全取 w0 65.0%）。替换 AUC Whisper 0.774、Qwen 0.641、之和 0.733、MMS 0.490；自偏好两边都有（Qwen 更重）；d_W 与 d_Q 的 Spearman 0.38。幻觉角度：每字分数 AUC Whisper 0.976、Qwen 0.974（MMS 0.975），丢弃后 CER 15.92%／16.04%。适用：这两部电影、产品 w0／x0 原样；未覆盖：Whisper 的 EOT 概率、听音核对、剧集与官方整片口径；18 个裁判配置之间的选择没有独立验证集。脚本 [`experiments/quality_v5/asr_pair_cross_score.py`](../../../experiments/quality_v5/asr_pair_cross_score.py)
- [音频接地裁判候选调研](../2026-10-19-acoustic-judge-survey.md)：exploratory。比较 13 个候选（MMS、rs35kh、Parakeet-ja CTC、Whisper／Qwen 教师强制、音素化、音频 LLM、TTS 似然等）在 oracle 误差构成（71% 替换、同音／表记占多数、一半增益是删插入）上的适用性：声学 CTC 看不出同读异形，交叉打分最有希望；附 §6 本机词表覆盖实测、§5 验证方案与限制。未在本项目数据上测过任何候选的判别力

## 翻译后审校与人名／专名一致性（2026-10-19，已结题：ADR-0013）

本线 2026-10-19 由用户裁定结题（[ADR-0013](../../adr/0013-name-consistency-closed.md)）：最佳已知配置冻结，不再开新轮次。同日用户另行裁定进产品（[ADR-0014](../../adr/0014-name-consistency-in-product.md)，产品实现见[专名一致性](../../architecture/modules/name-consistency.md)），本目录冻结。下列报告全部只读。

- [第六轮：换提示示例、写法层一致规则、日文写法形状过滤](../2026-10-19-name-consistency-round6.md)：concluded（GPU 只做建表；用户裁定回退提示到 v5 并结题）。`build_table.py` 提示 v6（虚构示例）＋ `_clean_ja` 日文写法形状过滤；`merge_tables.py --form-agree [--form-agree-substring]`。四部 × 八变体（旧默认、A、B、agree_nf、agree3、agree3_pool、agree3s、agree3s_pool）的覆盖率、逐行评审（新增 47 行）与统计在 §3：旧默认仍最优（89%／2.5%），v6 一致表 85%／7.1%，pool 86%／5.5%。提示 v6 退步、形状过滤保留、写法规则无效。适用：同第一轮；未覆盖：v5 提示＋形状过滤、按实体名配对、写法读音校验
- [第五轮：两次建表取一致、称呼词黑名单](../2026-10-19-name-consistency-round5.md)：concluded（GPU 只做一次建表，第六轮已做：用户裁定缺姓算有害、默认不变）。`build_table.py` 称呼词黑名单＋`--seed`，`merge_tables.py --mode zh-agree [--forms-fallback]`；四部 × 七变体（旧默认、A、B、agree、agree_pool、agree2、agree2_pool）的覆盖率、逐行评审（新增 29 行）、成对判分（14 条）与取一致统计四张表在 §3。实体层取一致有效，剩余有害来自提示污染、写法并集与句子级写法；agree2 163 行 90%／4.3%（缺姓算 good 2.5%），agree2_pool 190 行 88%／4.7%（3.2%）。适用：同第一轮；未覆盖：写法层一致、日文写法形状过滤、换提示示例
- [第四轮：建表侧压错名](../2026-10-19-name-consistency-round4.md)：concluded（GPU 只做建表，第五轮已做）。提示 v5（confidence 判据、称呼词／祷词不收、不合并相近角色）＋ evidence<3 降级 ＋ zh 形状过滤 ＋ `--renormalize`；`apply_table.py` v9 加 `--weak-name-check` 并修扩展吞前置修饰。四部 × 六变体全量判定在 §3.1：旧表默认 89%／2.5% 仍最优，v5 表 83%／5.4%，v5＋pool 81%／8.2%；有害条目全是 high，两种过滤都无效；错名随建表采样变化。适用：同第一轮；未覆盖：两次建表取一致、称呼词黑名单、think 下的 v5
- [第三轮：补覆盖与修表](../2026-10-19-name-consistency-round3.md)：concluded（纯 CPU，待用户裁定第四轮）。`apply_table.py` v8 四个开关＋`merge_tables.py`，四部 × 六变体矩阵：覆盖率、Opus 逐行评审（新增 166 行）与盲序成对判分（141 条）三张表在 §3。采纳孤立单字为默认（161 行 89%／2%，士郎约 40%）；`--bigram-isolation`（73%／20%）、`--iterate`（无效）、交集表（实体砍半）不采纳；`--pool-by-target`（84%／8%，错源是表错）修表后再评。适用：同第一轮；未覆盖：建表侧修错名、扩展吞前置修饰、一次性音译
- [第二轮："整个名字"规则与中文名校验](../2026-10-19-name-consistency-round2.md)：concluded（纯 CPU，待用户裁定）。`apply_table.py` v7 在第一轮八张表上各跑 nocheck（规则一）／check（规则一＋二）两档，Opus 逐行评审：think 141 行好 78%／有害 8%、115 行 84%／5%；no-think 111 行 82%／4%、98 行 83%／1%；规则一拦 91／63 处，规则二拦 152／165 处（其中正确写法 116／127 处）；仍有害的行按实体列在 §3.3；一致性指标因词条集合缩小而不可比（§1）。适用：同第一轮；未覆盖：重建表、已知译名表、confidence 收窄、think 少掉的 12 行。§6 补充：成对判分与整片通读证明被改动 cue 内准确性不降，缺口在覆盖率（士郎未覆盖）与表错
- [离线验证报告（第一轮）](../2026-10-19-name-consistency-offline-results.md)：concluded（GPU 只做建表，待用户裁定第二轮与是否进产品）。Qwen3.8-27B UD-IQ3_S 在本机可用（峰值 13.9 GB、提示 2024 tok/s）；v2 表＋替换脚本在 HF II／III × w0／x0 上不一致率 0.074–0.250 → 0.000–0.113，逐条评审好行 68%（think）／75%（no-think）、有害 17%／15%；错误来源为模型错名与统计层残字；think vs no-think、v1 vs v2 schema 的对比表在 §3。适用：这两部电影、产品 w0／x0 输出；未覆盖：冷门作品、剧集、MQM、整片观感、多 seed。实现 [`experiments/name_consistency`](../../../experiments/name_consistency/README.md)
- [方向讨论记录](../2026-10-19-name-consistency-direction.md)：exploratory。回顾 Hy-MT2 自审（v2 F8、v3 `review`、`terms`）均负、v5 第 10 步注入术语表一致率 0.041 → 0.002 但准确性 +0.022 的证据，约定"通用模型从日文侧建多对一专名表 → 翻译不动 → 生成后按日文锚定逐 cue 程序替换"的策略与两层落点规则（预列中文变体、跨 cue 统计），注入只作第二版再试；记录整片 `ja.srt` 规模（1099–1263 条、10.9K–12.1K 字符）与上下文预估。适用：产品流水线"阶段 × 整批"形状；未覆盖：任何实测、建表模型选择、称呼词

## ASR 稳健性第十四轮：w0 模型不变的幻觉守卫、漏句补窗与日文后校正（2026-11-09）

- [方案（v14）](../2026-11-09-asr-robustness-v14.md)：concluded（2026-11-09 起草、立项、同日结题；A 不进、B 不进、C 有效但不够：v2 C2 两部都降但合计 0.20 pp <0.3 pp；GPU 4 run、Opus <$2）。三条臂：A w0 幻觉／重复守卫（压缩比、触顶、低置信窗口置空或单次补解），B 窗内无字 VAD 子段补窗重解码，C Strata 上 Flash-Next 只读邻文的日文转写后校正；量尺 HF II／III 官方与单元口径日文 CER，门为两部都降且合计 ≥0.3 pp。不换模型、不改 VAD 参数、不多次解码挑选；`cross` 不在范围（ADR-0012 已接受）。预算 GPU 6 run／Opus $5。

## ASR 稳健性第十五轮：守卫安全网选型、B1 补窗实跑、表内专名替换（2026-11-10）

- [方案（v15）](../2026-11-10-asr-robustness-v15.md)：concluded（2026-11-10 起草、立项、同日结题；A 选中 `repeat-strict`＋折叠并建议进产品，B1 净变差不进，C3 在频次规则下 Δ0、头写法变体 −26 编辑，C3b／HF III Q3 表首次因可用内存不足未跑、重启后同日补跑：HF III Q3 表上头写法 −51 编辑，C3b 两部无收益；翻译影响经用户裁定实跑，头写法变体非劣、无可测改善；A 已裁定进产品（ADR-0023，待实现）；GPU 5 run、Opus 与裁判 ≈$11）。接 v14 三臂的后续：A 按“安全网”判据选守卫规则与动作（零误报＋拦住已知复读窗），给产品化草案；B1 空子段补窗实跑只报数；C3 把后校正收窄为“只允许按专名表写法替换”（规则版与 Flash-Next 判定版），条件触发量翻译影响。不设统一 0.3 pp 门。预算 GPU 12 run／$21。
