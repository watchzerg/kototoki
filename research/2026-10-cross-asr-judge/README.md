# 两路 ASR 交叉合并：oracle 上限、声学裁判与交叉打分

## 状态
concluded。三轮离线测算与一次裁判选型调研均在 2026-10-19 当天结题；结论进入产品可选引擎 `cross`（[ADR-0012](../../docs/adr/0012-cross-asr-judge.md)，默认仍是 `w0`）。

## 时间
2026-10-19 立项并结题（四份报告同日完成）。产品路径验收与共驻探针见 `../acceptance/`。

## 问题
产品 w0（faster-whisper large-v3）与 x0（Qwen3-ASR-1.7B）的错误并不重合：能否用一个"裁判"在两路文本的分歧区间上挑出更好的一路，把整体 CER 压下来？理论上限多高，哪种裁判最值得做？

## 策略
1. oracle 上限：用参考答案在每个分歧区间选更接近的一路，只算上界，不跑模型。
2. MMS CTC 声学裁判：对两个整单元假设做 CTC 前向对数似然，规则 `score_x − score_w > m + λ·Δlen`，跨片调参；另测"w0 幻觉过滤"（按每字声学分数丢弃低分单元）。
3. 交叉打分：Whisper 用 CT2 `align()` 教师强制给两个假设打分，Qwen 用一次前向取 token 对数概率；比较 Whisper 单独、Qwen 单独、两者之和、两者都同意、再加 MMS。
4. 裁判候选调研：纯桌面调研，对 13 个候选（MMS、Parakeet-ja CTC、rs35kh、音素化、音频 LLM、TTS 似然等）按适用性排序，没有实测。

## 环境与版本
- w0：faster-whisper 1.2.1＋ctranslate2 4.8.3，large-v3（CT2，FP16），新 Pyannote VAD（ADR-0003）。
- x0：`Qwen/Qwen3-ASR-1.7B-hf` revision `bcd2b5b7`，transformers 5.20.1，BF16、SDPA。
- MMS：`mms-1b-all` 的 `jpn` adapter（产品对齐用的同一份权重，CC-BY-NC-4.0）。
- GPU RTX 5080；各实验先后加载单个模型，不同时驻留。

## 测试
- 数据：2 部日语电影整片（HF II／III），产品 w0／x0 输出的 SRT 显示字幕，对照人工参考 SRT；时间重叠的 cue 连成"单元"，两路文本在单元内字符级对齐，非匹配的极大连续段为一个分歧区间（共 1253 个，覆盖约 13% 参考字符）。
- 指标：单元口径 CER（NFKC、去标点与空白后的字符级编辑距离，两部合计）；区间准确率（对 oracle 选择）、AUC；跨片调参（II 调参用于 III，反之亦然）。单元口径与产品官方整片口径相差约 1 pp，官方数字只作对照。
- 裁判：无外部裁判，参考答案即标准；30 个分歧区间做过人工分类。

## 结果
两部合计，w0 基线 CER 16.16%（单元口径）：

| 方案 | CER | 备注 |
| --- | --- | --- |
| oracle 选择／oracle 拼接 | 12.46%／11.90% | 上界；一半增益来自删掉对方多出的插入字 |
| MMS CTC 裁判 | 15.40% | 只拿到 oracle 拼接增益的 18%；替换区间 AUC 0.49 |
| Qwen 单独打分 | 15.09% | 自偏好重，阈值两片不稳 |
| Whisper＋Qwen 之和 | 14.56% | 不优于 Whisper 单独 |
| 两者都同意 | 14.23% | 比 Whisper 单独多省 19 处编辑，但 Qwen 阈值不稳 |
| **Whisper 单独打分** | **14.31%** | 拿到 oracle 拼接增益的 43%；替换区间 AUC 0.774；阈值两片几乎相同 |

其他要点：
- 两路都错的单元占有参考单元的 48%（字符级约 10.3% 无论如何救不回）；30 个人工样本里 8 个只是表记差异（桜／さくら），对翻译几乎无影响却全计入增益。
- w0 幻觉过滤：插入单元与完全一致单元的每字分数可分（AUC 约 0.975），但低分单元混着单字真台词，丢弃后 CER 只从 16.16% 到 16.14%（上界 15.41%）。
- 成本：Whisper 打分整次约 252 s、整卡峰值约 5.9 GB；Qwen 整次约 458 s、约 6.9 GB。
- 调研结论：MMS 是"顺手"而非最优，声学 CTC 看不出同读异形；交叉打分排第 1，风险是自偏好。

## 结论与去向
- 采纳：Whisper 教师强制打分作裁判（d > −1.0 取 x0），以可选引擎 `cross` 进产品，默认保持 `w0`（[ADR-0012](../../docs/adr/0012-cross-asr-judge.md)）。产品路径验收（官方整片口径）合计 CER 15.25% → 14.30%（−0.95 pp，差预设 1.0 pp 线 0.05 pp，用户知悉后仍采用），共驻显存探针整卡峰值 10688 MiB，见 [cross 产品验收](../acceptance/2026-10-19-cross-asr-acceptance.md)与[共驻探针](../acceptance/2026-10-19-cross-coresidency-probe.md)。
- 放弃：MMS 裁判、Qwen 当裁判、多路叠加。声学裁判线（Parakeet-ja 试装等）与换 ASR 模型线不继续。
- 未覆盖：译文层收益（需外部裁判）、听音核对、剧集与新材料；Whisper 的 EOT 概率；18 个裁判配置之间没有独立验证集。

## 教训
- 自偏好是交叉打分的主要风险：每个模型都偏爱自己的输出，Qwen 更重；阈值（−1 nat）实质上在吸收它。
- 分数不含结束符，多字少字类区间有"越短越占便宜"的偏差。
- 一半的 oracle 增益是删插入字而不是改对内容，合并线的收益要拆开看，不要只看总 CER。

## 原始材料
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-19-asr-pair-oracle.md`
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-19-asr-pair-ctc-judge.md`
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-19-asr-pair-cross-score.md`
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-19-acoustic-judge-survey.md`
