# 调研索引

本目录保存技术比较、实验、验证证据及其限制，按记录时点阅读，永不改写、不归档。结论采纳后更新当前正文或新增 ADR，证据保留原样。验收记录放 `acceptance/`，文件名带日期。

新增文件必须在本页登记，未登记的文件视为不存在。每条登记：主题、结论、适用条件与未覆盖项。

Migrated research is adapted prose, not a copy of the sibling project's task
state, permissions, or assets. Each document records sources and limitations.
Links to `../../../subtitle-edit-fix/` require that sibling checkout; original
experiment artifacts remain there and were not imported. External findings are
attributed to the original investigation dates, not newly verified by migration.

## 决定与探索时间线

按时间倒序记录用户采纳的决定与探索轮次结论；决定本身以 ADR 为准，本节只摘要并链接。

2026-10-19：`cross` 模式 T0 [共驻显存探针](acceptance/2026-10-19-cross-coresidency-probe.md)完成（用户授权的 GPU 作业，同一进程常驻产品 Whisper（CT2 FP16）与 Qwen3-ASR（BF16），HF II／III 全部 402 个 VAD 窗口按 w0 转写 → x0 转写 → Whisper 打分跑一遍，约 23 分钟）：整卡峰值 10688 MiB（含桌面约 2.0 GB），加 1 GB 余量 11712 MiB ≤ 13.5 GB 阈值，**采用共驻**，不需要三段式回退；先 torch 后 CT2 的导入顺序下两份 cuDNN 并存，无 DLL／OOM 问题，两路转写与单独运行逐窗口相同。三步墙钟两部合计 1364 s（打分 40.5 s），约为单独 w0 的 4.4 倍。窗口口径下规范化后相同的窗口只有 10%，改为 x0 的区间 18.5%（研究单元口径 37.7%，增量说明 §5 预期 6–10%），留给 T6 判读。

2026-10-19：[Whisper 与 Qwen 交叉打分裁判](2026-10-19-asr-pair-cross-score.md)测算完成（用户授权的 GPU 作业，先后加载产品 Whisper large-v3 与 Qwen3-ASR，只做教师强制前向，合计约 12 分钟；与 oracle、MMS 实验同一批 1253 个分歧区间）：跨片调参后两部合计 CER，Whisper 单独 16.16% → 14.31%，"两者都同意" 14.23%（无长度项 14.17%），Whisper＋Qwen 之和 14.56%，Qwen 单独 15.09%，加 MMS 不改善；MMS 为 15.40%、oracle 拼接 11.90%，即拿到 oracle 增益的约 43%～47%。替换区间 Whisper AUC 0.77（涉及汉字 0.77，MMS 0.49），加 Qwen 反而降到 0.73。两模型都偏向自己的输出：oracle 判 x0 对时 Whisper 仍偏 w0 52%，判 w0 对时 Qwen 仍偏 x0 57%；Whisper 阈值两片稳定（m ≈ −1），Qwen 不稳。Whisper 分数不含 EOT（`text_token_probs` 限制），插入／删除类判定混有长度偏差。是否采纳待用户裁定（文档 §10），未启动任何合并实现。

2026-10-19：[音频接地裁判候选调研](2026-10-19-acoustic-judge-survey.md)（exploratory，纯桌面调研，未跑模型）：MMS jpn CTC 当初按时间对齐成功率选入，从未评估过文字判别力，无公开日语 CER，词表对分歧区间缺字 1.13%（3.8% 的区间），许可 CC-BY-NC-4.0；预期更优的方向依次为 Whisper `align()`＋Qwen3-ASR 互相教师强制打分、Parakeet-ja CTC 头、盘上的 rs35kh；音素路线只作分流器。名次均为推断，待用户裁定是否做有界 GPU 验证。

2026-10-19：[MMS CTC 声学裁判与 w0 幻觉过滤](2026-10-19-asr-pair-ctc-judge.md)测算完成（用户授权的 GPU 作业，只加载产品 MMS，约 2 分钟；HF II／III，与 oracle 同一批 1253 个分歧区间）：逐区间比较两个整单元假设的 CTC 对数似然、跨片调 λ／m，两部合计 CER 16.16% → 15.40%，只拿到 oracle 拼接增益的 18%；区间准确率 67.1%（全取 w0 为 65.0%）。增益几乎全在删除 w0 多出的字，替换区间判别力接近随机（AUC 0.54／0.48，涉及汉字的 0.47），λ 符号两片相反。w0 单路幻觉过滤：插入单元与正确单元可分（每字 Viterbi AUC 0.975，Whisper avg_logprob 0.914），但丢弃低分单元对 CER 几乎无作用（−0.02 pp，上界 −0.75 pp），并误删单汉字真台词。是否采纳待用户裁定（文档 §8），未启动任何合并或过滤实现。

2026-10-19：[w0／x0 两路 ASR 交叉合并的 oracle 上限](2026-10-19-asr-pair-oracle.md)测算完成（纯 CPU、不跑任何模型，HF II／III）：用参考答案逐单元选更优一路，两部合计 CER 16.16% → 12.46%；逐分歧区间拼接 → 11.90%（编辑量 −26.4%，官方口径折算约 15.25% → 11.0%）。选择增益一半是删掉对方多出的插入字；两路都错占有参考单元的 48%（其中 40% 文本完全相同），字符级 10.3% 的参考字符两路都没对上；30 个分歧区间里 8 个只是表记差异。x0 ASR 墙钟约为 w0 的 2.8 倍。是否开新线、是否测真实选择器待用户裁定（文档 §8），未启动任何合并实现。

2026-10-18：用户裁定**停止换 ASR 模型这条线**（v5 [§8](2026-10-16-quality-exploration-v5.md#8-待用户裁定) 第 3、4 项）：两轮共五个候选（Cohere、Granite、Nemotron、anime-whisper、Qwen3 动漫微调）都不如 w0，10-05 之后也没有新的实质性日语开放权重 ASR；许可未声明的 `efwkjn/whisper-ja-*`／`cohere-asr-ja` 不评测，Qwen3 动漫微调加循环防护也不做。产品 STT 保持 w0（large-v3）。重开前提：出现新的、许可清楚的日语 ASR 模型。STT 侧后续只做稳健性方向（窗口边界、幻觉过滤＋补窗、人名）。

2026-10-18：用户裁定**关闭"翻译批内语序自由"这条线，不立项备选路线**（v8 [§8](2026-10-18-group-reorder-v8.md#8-待用户裁定)、技术设计 §11）：提示级放开与整组合译两种形状都不产生跨行重排，合译还会把 <1 s 停顿内的不同说话人并成一句；翻译保持逐 cue 对应。重开前提是有说话人信息。

2026-10-18：用户裁定把 `dp10-cut` 合并到产品（[ADR-0011](../adr/0011-dp10-cut-product-recipe.md)）：产品翻译配方改为 `dp10-cut-degrade-v1`，切包与邻文同 ADR-0010、降级不变；四个整片 `ja.srt` 离线切包平均每批 7.4–8.3 条、请求 +20–35%、无跨 ≥20 s；已交付影片的翻译身份过期、下次整批重译（用户接受）；质量证据与 ADR-0010 相同（无）。

2026-10-18：[第八轮（v8）同一句话小组内语序重排](2026-10-18-group-reorder-v8.md)结题：票据 02 小样（20 个包、70 个多 cue 组）判定 **Q1 否定**——在 ID JSON grammar 下告知小组并放开逐 ID 归属（`joint-understanding-v2`，另试一次两步式措辞）不产生任何组内重排，重排率 0–6.2% 与严格对严格噪声底无法区分，人工无一例挪内容；两步式措辞还引入邻文泄漏与无中生有。按停止条件结题，未生成对照 run、未裁判；技术设计 §11"提示告知、grammar 不变"的实现形状证伪，是否转"组级输出再程序切回"交用户裁定（§8）。顺带观察：严格逐 ID 模式下模型已把每行译成自足中文，语序自由的收益上限可能不大。同日补做备选路线预检（§7.3，票据 07，GPU 20 次请求）：程序把整组合并为一个源条目让模型整句翻译，模型仍按日文行序输出（可对齐 35 组 0 重排），与逐行拼接的相似度只比两次逐行翻译之间低一档；仅标点切回 94% 可行；但 11／54 组丢失或歪曲信息，8 组把 <1 s 停顿内的不同说话人并成一句。执行者建议不立项备选路线，待用户裁定。

2026-10-18：[第八轮（v8）同一句话小组内语序重排](2026-10-18-group-reorder-v8.md)立项：包、切包、邻文、grammar、裁判全部沿用 `dp10-cut`，只在包内按 R2+（停顿 <1.0 s 且前一行无句末标点）划组、把 `groups` 注入提示并把 joint 提示的逐 ID 归属句改为"组内可按中文语序重新分配"（`joint-understanding-v2`）；唯一变体 `grp1`，对照 dp10-cut 本轮新生成。先判模型是否真的重排（重排率＋人工抽查），再看 accuracy 非劣与 fluency 改善，新增 CPU 读速／占比校验器作显示风险终点。划组规则来自同日的[离线统计](2026-10-18-reorder-group-offline-stats.md)。

2026-10-17：用户裁定把完整 SRT 流程基线改为 `dp10-cut`（[ADR-0010](../adr/0010-dp10-cut-translation-flow-baseline.md)）：每包 ≤10 条、可见 ≤12 条，分级切点（<0.5／<1／<2 s 切分别加 6／3／1 分）、不跨 ≥20 s；[离线模拟](2026-10-17-dynamic-cut-batching-simulation.md)显示平均每包 8.69 条（dev，dp6-grp 7.88）／7.83 条（产品，6.74），现有裁判数据测不出门槛效应，按逻辑推定，未做 GPU 筛选；产品配方不变。

2026-10-17：用户裁定把完整 SRT 流程基线改为 `dp6-grp`（[ADR-0009](../adr/0009-dp6-grp-translation-flow-baseline.md)）：v7 两次合并与 b10-joint 无可分辨差异（剧集 −0.009、电影 +0.003），按 Q4 规则未达"两次都非劣"，用户按逻辑合理与可与语序工作共用边界采纳；产品配方 `b10-joint-degrade-v1` 不变。

2026-10-17：[第七轮（v7）按静默拼包、停顿标记与两级结构](2026-10-16-gap-aware-batching-v7.md)结题：Q1 全局最优切分 `dp6`（跨 ≥10 s 的批 27%→0%）电影侧显著变差（+0.047［+0.0003, +0.095］），wrong-referent 不降，按停止条件中止；Q2 只插停顿标记的 `mark5` 两次都非劣但无改善（合并剧集 +0.008、电影 +0.011，剧集 wrong-referent +0.011），与 dp6 分不出高下，“场景感知”这条线关闭；Q3 由 <1 s 小组拼包的 `dp6-grp` 不劣于 dp6，但相对 b10-joint 只在重复 seed 上非劣；Q4 只有 mark5 满足“非劣即可保留”，执行者建议暂不改默认，交用户裁定（研究文档 §8）。产品时间轴上切分类变体的小包占三分之一。

2026-10-16：[第七轮（v7）按静默拼包、停顿标记与两级结构](2026-10-16-gap-aware-batching-v7.md)立项（proposed，等待 goal 会话执行）：v6 结题后的讨论定下三个变体——全局最优切分（软 2 s／硬 10 s、包 6–12 句、邻文按停顿分档）、不切包只在 ≥5 s 停顿插标记、包由 <1 s 小组拼成；请求数不限、全集裁判并同包重判对照；不做相对门槛。离线模拟显示硬边界 10 s 使请求 +17%、平均 8.3 句，产品时间轴的停顿比研究集长约一倍。

2026-10-16：[第六轮（v6）场景感知分批](2026-10-16-scene-aware-batching-v6.md)立项、执行并结题：Q1 跨场景混批处的错误不以 wrong-referent 为主（少数派一侧的超额是位置混杂），但准随机批边界对比显示跨静默混批让间隔两侧 wrong-referent 多 +0.05–0.09，折合全集约 0.004；Q2 网格吸附变体 `gsnap5`（±2 条吸附到 ≥5 s 静默、跨间隔邻文去掉）在受影响子集上筛选 Δ −0.022、独立 seed +0.001，不复现（合并剧集 −0.038、电影 +0.018），wrong-referent 不变；Q3 形式上满足零成本标准（全集非劣、墙钟 −2.7%），但收益未复现，建议不改 b10-joint 默认，交用户裁定（研究文档 §8）。

2026-10-16：[字幕质量探索第五轮（v5）](2026-10-16-quality-exploration-v5.md)立项、执行并结题：产品中文错误约四分之三来自 ASR（r_all 0.76），但 VAD 召回与两个动漫微调 ASR 都不如当前，产品 STT 保持 w0；翻译侧 8 样本＋bge-m3 语义逐条 MBR（`mbr8s`）在全新剧集确认集上确认（剧集 Δ −0.036、约 −7%，p 0.0004，电影无材料未确认），代价约 6.3 倍翻译墙钟。用户当天裁定放弃 mbr8s 与 v4 的 mbr8c，今后不自动选用"翻译多次再挑选"的方法，除非用户明确要求（[ADR-0008](../adr/0008-no-multi-translation-selection.md)）；更省的 MBR（N＜8、早停）不复现，低温＋MBR 不叠加，按作品术语表提高一致率但准确性变差。第 1 步确认改回 swr 后产品 STT 回到基线（[swr 回归记录](acceptance/2026-10-16-bilingual-pipeline-swr-regression.md)）。

2026-10-15：最终验收后用户裁定：重采样改回默认 swr（票据 10）、修 `DURATION-<lang>` 误判（票据 11）、间隔断句只在跨 VAD 子段时成立（票据 12）；[cue token 边界调研](2026-10-15-cue-token-boundary-study.md)结论为不实现（票据 13）。同日架构评审后阶段链与期望身份收进 `kototoki/plan.py`（票据 14）、翻译 run 键与 `needs_model` 归翻译子系统（票据 15），行为与身份取值不变。

2026-10-15：双语字幕流水线最终验收完成（[验收记录](acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)）：工程行为全部通过；质量回归未达基线，根因为 soxr 重采样影响 Pyannote，待用户裁定；另发现 `DURATION-<lang>` 缺陷与 cue 内切词。

2026-10-14：双语字幕流水线（票据 00–09）实现完成，规格改为 implemented；两部整片 × w0／x0 验收见[验收记录](acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)。用户裁定的产品翻译配方为 `b10-joint-degrade-v1`（字段同 `b10-joint`，只多 10→5→1 降级），重采样改 soxr 28 bit。

2026-10-13：项目进入实现阶段。用户确定第一个产品形态为配置文件驱动的中日双语字幕批量流水线，设计见[技术设计](../specs/bilingual-subtitle-pipeline.md)，架构取舍见 [ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md)：默认 w0、新 Pyannote、MMS、b10-joint；GPU 阶段按"阶段 × 整批"推进；单一 CUDA 12.8 Python 环境（Python 3.13、torch 2.11.0+cu128，与 CTranslate2 共用 DLL，2026-10-14 由 CUDA 13 方案改定），llama.cpp 用官方 CUDA 13.4 构建；回归与容差推迟到实现之后。

2026-10-12：v4 第四轮字幕翻译流程探索已完成，详见 [v4 报告](2026-10-11-hy30-flow-v4-report.md) 和 [v4 台账](../context/2026-10-11-hy30-flow-exploration-v4.md)。**1 个配方通过确认：`mbr8c`**，即每批 8 个样本，逐条用本地 chrF-MBR 选择。确认集上 Δ −0.016（约 4%，集中在剧集），Holm p 0.016，代价是约 6 倍墙钟。`t03`（temperature 0.3）在确认集上未通过。基线 b10-joint 不自动替换；2026-10-16 用户裁定放弃（[ADR-0008](../adr/0008-no-multi-translation-selection.md)）。实现入口为 [translation_v4](../../experiments/translation_v4/README.md)。

2026-10-11：用户采纳 **b10-joint** 作为完整 SRT 流程基线（[ADR-0006](../adr/0006-b10-joint-translation-flow-baseline.md)，入口 `just translation-srt`）；模型和采样仍按 ADR-0005。这是工程选择：b10-joint 在 v3 确认集上没有通过显著性检验。下一轮见 [v4 计划](../plans/hy-mt2-translation-flow-exploration-v4.md)（proposed）。

2026-10-10：v3 第三轮字幕翻译流程探索已完成，[v3 报告](2026-10-10-hy30-flow-v3-report.md)：19 个配方、Claude MQM 裁判、确认集检验，**0 个配方通过确认**；唯一 promising 的 b10-joint 在确认集上未复现。基线 `official30b-cached-v1` 不变，待用户决策。

2026-10-10：字幕翻译流程探索改为[第三轮计划](../plans/hy-mt2-translation-flow-exploration-v3.md)（Claude Opus 5.5 MQM 裁判，重新起跑），[v3 台账](../context/2026-10-10-hy30-flow-exploration-v3.md)维护执行状态，[v1/v2 教训](2026-10-10-hy30-flow-v1-v2-lessons.md)只作为先验使用，[参考 v3 复核](../testing/2026-10-10-reference-v3-audit.md)完成；实现入口为[translation_v3](../../experiments/translation_v3/README.md)；第二轮已停止，下面关于 v2 的条目均为历史记录。

2026-10-08用户选择[第二轮C档字幕流程探索计划](../plans/hy-mt2-translation-flow-exploration-v2.md)：96筛选＋48独立确认，批次大小采用资源宽松的自适应搜索。[新台账](../context/2026-10-08-hy30-flow-exploration-v2.md)记录已冻结的源／参考、评估校准、判定规则及正在执行的候选实验，当前尚未收敛、未替换基线。第一轮仅完成有限局部筛选，不证明1-5-1最优或主要方向充分收敛。

[翻译模式筛选报告](2026-10-07-hy30-flow-optimization-results.md)完成固定 Hy-MT2 APEX 的一轮有界探索：主要低成本方向无可靠胜出方案，完整SRT实验外层及机械验证可用，未替换基线。[起始计划](../plans/hy-mt2-translation-mode-optimization.md)和[探索台账与接跑](../context/2026-10-07-hy30-flow-exploration.md)保留范围、证据及未验证方向。

用户于2026-10-08随后采纳官方30B采样、4096输出与缓存，当前配置为`official30b-cached-v1`，总context8192；见[ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md)和[新配方验证](../testing/2026-10-08-official30b-cached-baseline-validation.md)。历史筛选结论不回写。

[Hy30 四量化大规模报告](2026-10-07-hy30-four-quantization-results.md)汇总旧 83 窗及新增 1,200 窗全量评估、四轮性能和正式长跑；[复现入口](2026-10-07-hy30-four-quantization-results-appendices/reproduction.md)、[方案](../plans/hy30-four-quantization-comparison.md)和[接跑记录](../context/2026-10-06-hy30-four-execution.md)保留命令与历史。用户在交付后明确采纳 APEX-I-Compact，原报告与附录保留当时的结论和 Q3_K_M 冻结统计对照。

配套工具：[独立语料构建与双轮参考复核](../../experiments/translation_corpus/README.md)、[串行 GPU 比较与恢复](../../experiments/translation_four_quantization/README.md)、[全量评估及配对统计](../../experiments/translation_eval/README.md)。

[ADR-0005：字幕翻译 Hy-MT2 30B-A3B APEX-I-Compact 基线](../adr/0005-apex-i-compact-translation-baseline.md)记录当前采纳决定（`hy-mt2-30b-a3b-apex-i-compact`）；执行复用[翻译 demo](../../experiments/translation_demo/README.md)，后续讨论和回归以该固定身份与配方为起点。[ADR-0004](../adr/0004-hy-mt2-translation-baseline.md)保留此前 Q3_K_M 采纳历史，已被新决定取代。

[国会讨论 W0／X0 整段实测](2026-10-05-parliament-baselines.md)记录新增三小时素材的当前基线运行；
字幕准确度未知，仅作参考，与电影主参考分开报告。

[ADR-0003：W0／X0统一采用新Pyannote](../adr/0003-new-pyannote-baselines.md)更新当前组件定义；
ADR-0001／0002中被替代的选择保留历史范围，原生特征及可复用入口原则继续有效。

## 调研

条目格式：`[主题](文件.md)：一句话结论；适用条件或限制`

### STT 组件与基线（2026-10-03 至 2026-10-04）

- [模型与后端候选](2026-10-03-model-backend-candidates.md)：继承自相邻调研的本地 STT 候选短名单；exploratory，未采用任何后端或模型
- [Whisper 与 Qwen 后端契约](2026-10-03-stt-backend-contracts.md)：推理、对齐、文本单元与时间行为的版本绑定观察；绑定当时版本，未验证
- [STT pipeline 设计参考](2026-10-03-stt-pipeline-design.md)：迁入的本地转写流水线设计调研；不是已采纳架构
- [STT 应用对照](2026-10-03-stt-application-comparison.md)：三个相邻应用快照的本地 STT 与时间路径对照；历史比较已结束，实现建议仍属探索
- [时间戳失败案例](2026-10-03-timestamp-failure-cases.md)：相邻项目有界时间调查中观察到的失败机制与工程教训；对 Kototoki 的补救措施未验证
- [Whisper demo 就绪度](2026-10-03-whisper-demo-readiness.md)：faster-whisper large-v3 与 WhisperX 日语对齐的源码核查；原生 GPU 执行当时未验证
- [Qwen 与 Crisp demo 就绪度](2026-10-03-qwen-crisp-demo-readiness.md)：官方 Qwen3-ASR／ForcedAligner 与 CrispASR 在原生 Windows＋RTX 5080 上的来源评审；无本地推理
- [第一轮固定验证结果](2026-10-04-validation-results.md)：验证章 03/14/23 的六配置完整实测并锁定保留候选；严格时间目标均未达标，不含保留测试
- [开发集对比](2026-10-04-dev-comparison.md)：开发五章 13 种配置的验证前观察，跨家族 X0 经官方 CTC 归一化后 0.5 秒确定成功约 49%；均未达严格时间目标，不等于生产推荐
- [固定保留测试结果](2026-10-04-heldout-results.md)：五条预锁路线在 N=620 的描述性结果，W1 确定成功率最高、W0 覆盖最高；五条均未达时间目标，缺人工声学真值
- [整片质量与连续性](2026-10-04-fullfilm-results.md)：W0／W1 各一次完整 7,028 秒整片推理，CER 约 20% 且几乎相同；同片诊断，均未达时间目标
- [最终性能与重复性](2026-10-04-final-performance.md)：两条路线各三次 chapter07 新推理加一次整片，文字与 timed units 的 SHA 完全一致；只证明重复稳定，不证明识别正确
- [实测结论与实施顺序](2026-10-04-stt-demo-conclusions.md)：保留 W0 与 W1 两个方向，尚无配置达到严格时间目标；首轮成绩与单片冻结输入绑定，不替代已采纳的 W0／X0 基线
- [开发／验证／保留集字幕显示分析](2026-10-04-display-analysis.md)：CPU 显示回放核算 SRT 覆盖与短／长 cue；声学同步和人工可读性未验证
- [数字静音预检](2026-10-04-silence-preflight.md)：10 秒全零输入下 W0、Q0 仍产生少量文字，W1 与 Crisp 原生 VAD 输出空；单一合成输入，不代表真实静音稳健性
- [Whisper 执行准备](2026-10-04-whisper-execution.md)：W0／W1 环境、适配器与离线合成测试的执行基线；探索中，不构成正式选型
- [Whisper 后续实现边界](2026-10-04-whisper-engineering-boundaries.md)：W0、W1 与标准 CTC 分支的工程交接与约束；仅用开发证据，无后端采用决定
- [Qwen 执行准备](2026-10-04-qwen-execution.md)：官方 Qwen native HF 的源码、冻结环境与 CUDA 推理核查；历史 Q0 记录，当前 X0 以 X0 demo 为准
- [Crisp 执行准备](2026-10-04-crisp-execution.md)：CrispASR 0.8.41 在原生 Windows 的两种受控流程实测，GPU 可复现；字幕时间未达标
- [W0 与标准 CTC 的有界探索](2026-10-04-w0-ctc-exploration.md)：保留 W0 文字、换用日语 CTC 官方归一化与 forced spans 的锁定后探索；新增单一配置，不能放回原盲测排行榜，不宣称胜出
- [两片主参考复核结果](2026-10-04-two-film-revalidation.md)：II／III 新主参考上五条固定路线复核，保留原实验建议与分数；均未达到严格时间目标
- [模型资产获取记录](2026-10-04-model-assets.md)：七组模型与配套文件已通过内容身份核验；只证明资产就绪，不代表推理或质量通过
- [Subtitle Edit 模型复用](2026-10-04-subtitle-edit-model-reuse.md)：优先复用 Subtitle Edit 已下载资产的本地核验；未新增推理、不改变首轮结论
- [环境与复现清单](2026-10-04-runtime-inventory.md)：原生 Windows 的锁定版本、模型、安装包与恢复入口只读清点；质量结论见各实验报告

### Whisper 框架与 W0／X0 流程（2026-10-04 至 2026-10-05）

- [Whisper 框架架构选择](2026-10-04-whisper-framework-architecture.md)：推荐 faster-whisper＋保行为适配，含维护成本、反证与迁移门槛；不代表正式采用
- [Whisper 冻结 VAD 等价实验](2026-10-04-whisper-framework-experiment.md)：两窗 17 块适配层 ASR 严格一致、46 项 VAD 后处理一致，标准 API 不等价；MMS 复用输入契约证据，未重跑
- [Whisper ASR 源码核验](2026-10-04-whisper-framework-asr-audit.md)：三种生成路径、有效参数、特征处理及安装源码完整性；绑定所核查版本
- [Whisper VAD／MMS 边界核验](2026-10-04-whisper-framework-vad-alignment-audit.md)：原始 VAD 分数到窗口、MMS 自研替换点及残留框架职责
- [X0／WhisperX 源码核查](2026-10-05-x0-whisperx-source-audit.md)：可跨模型的策略、已有等价行为、Whisper 专属逻辑及旧入口 CTC 身份差异
- [X0 吸收 WhisperX 流程](2026-10-05-x0-whisperx-flow.md)：历史两窗三臂 GPU 验证，energy 与 VAD 均有取舍；流程设计采用见 ADR-0002，新 demo 的 cut-merge 不继承 energy 分数

### VAD／分段（2026-10-04 至 2026-10-05）

- [W0＋VAD＋CTC 追加比较](2026-10-04-w0-vad-ctc-follow-up.md)：同十二窗六配置对照，VAD 叠加未提高全分母时间成功，长尾与漏字存在取舍
- [VAD 全景与 W0／X0 分片改进](2026-10-05-vad-landscape.md)：探索性来源调研，VAD 允许 CPU／GPU、对白优先；未更换基线组件，未执行新推理
- [成熟 VAD 来源核查](2026-10-05-established-vad-sources.md)：Silero、Pyannote、FSMN、NeMo、SpeechBrain 的发布、模型身份、语言与 Windows／GPU 边界
- [新兴 VAD 来源核查](2026-10-05-emerging-vad-sources.md)：FireRed、OmniVAD-Kit、TEN 的模型关系、维护记录、许可与部署限制
- [VAD 稳定版本核验](2026-10-05-vad-stable-versions.md)：四候选的官方发布、权重 revision、默认参数与许可；FireRed Beta 例外与 Pyannote 访问门控已区分
- [W0／X0 十组合 VAD 比较](2026-10-05-vad-baseline-comparison.md)：十组合实测与审计完成，1 次 X0＋新 Pyannote 生成上限失败保留；结论保留当时口径，后续采纳见 ADR-0003
- [新 Pyannote CPU／GPU 对照](2026-10-05-pyannote-gpu-comparison.md)：切分与质量一致，新进程 GPU 较慢，单窗模型复用约快 13.1 倍；23 次完成、1 次同窗触顶
- [两片整片分段对照](2026-10-05-fullfilm-segmentation-comparison.md)：新 Pyannote GPU 与 cut-merge 共八组整片运行及独立审计；后续用户已采纳新 Pyannote（ADR-0003）

### ASR 候选与评测素材（2026-10-05）

- [ASR 模型全景与候选优先级](2026-10-05-asr-model-landscape.md)：面向日语、本地 Windows／RTX 5080 的官方来源调研与验证门槛；未改变 W0／X0 基线
- [第一批 ASR 两片整片实测](2026-10-05-asr-candidates-fullfilm.md)：五路线十次运行，Cohere／Nemotron 更快但 CER 落后，Granite 多次重复触顶；保留 W0／X0
- [日语长音频与对应文本来源](2026-10-05-japanese-longform-asr-sources.md)：公开有声书、播客、长篇语料与会议录像的入口、长度与参考质量；来源调研，未下载或纳入正式评测
- [YODAS2 日语元数据与选样](2026-10-05-yodas2-japanese-selection.md)：两子集 32,899 条时长实查、字幕质量陷阱与按包获取方案；后续选定国会讨论
- [国会讨论 W0／X0 整段实测](2026-10-05-parliament-baselines.md)：YODAS2 国会讨论 10,843 秒各一次完整推理；字幕准确度未知，结果仅作参考，X0 附加时间评分中止，不混入电影排名、不据此换基线

### 对齐（2026-10-04）

- [新增组件与对齐器兼容性](2026-10-04-component-augmentation-sources.md)：Demucs、GPU VAD、Qwen FA、Canary 日语限制及现有 wav2vec2 身份的官方来源核查；不代表质量已验证
- [组件增量实测](2026-10-04-component-augmentation-results.md)：分离／VAD 出现回归，W0＋CTC 输入契约修复有时间收益但有覆盖取舍；无新的总体优胜组合
- [日语 CTC 官方来源核验](2026-10-04-japanese-ctc-source-verification.md)：模型身份、blank／tokenizer 契约、日语 adapter 与许可核验；质量结论另见实测
- [Japanese CTC Forced Alignment 外部会话参考](2026-10-04-japanese-ctc-alignment-reference.md)：保留外部会话原始建议的历史身份；官方核验与本机实测见相邻两篇
- [日语 CTC 补充实测](2026-10-04-japanese-ctc-results.md)：MMS 补充 W1／X0、Reazon 补充 X0、假名模型补充 W0 均有证据；保留严重偏移、粒度与许可取舍

### 翻译方法与源码调研（2026-10-04 至 2026-10-06）

- [字幕翻译调研总报告](2026-10-05-subtitle-translation.md)：三个相邻项目源码、上下文与语义映射、JSON／缩批恢复及质量评估；exploratory，未运行翻译实验
- [Subtitle Edit 翻译源码](2026-10-05-translation-subtitleedit.md)：本地快照与固定上游证据下的实际机制与边界
- [VideoLingo 翻译源码](2026-10-05-translation-videolingo.md)：本地快照与固定上游证据下的实际机制与边界
- [pyVideoTrans 翻译源码](2026-10-05-translation-pyvideotrans.md)：本地快照与固定上游证据下的实际机制与边界
- [翻译主流方法与模型契约](2026-10-05-translation-methods.md)：字幕与文档翻译的上下文、语义单元与专用模型一手资料；不构成模型排名或已采纳实现
- [日译中字幕质量评估](2026-10-05-translation-evaluation.md)：评估方法与小规模实验建议；不构成已采纳实现
- [三个本地翻译模型对比](2026-10-05-local-translation-model-comparison.md)：Hy-MT2、TranslateGemma、Tower+ 的输入契约、多段／JSON、字幕约束与部署；来源核查，未进行模型实测
- [Hy-MT2-7B-GGUF 详解](2026-10-05-hy-mt2-7b-local-translation.md)：模板解释、伪代码、证据等级与字幕适用边界；exploratory
- [TranslateGemma-12B 详解](2026-10-05-translategemma-12b-local-translation.md)：输入契约、证据等级与字幕使用边界；exploratory
- [Tower-Plus-9B 详解](2026-10-05-tower-plus-9b-local-translation.md)：本地接口、结构输出与字幕适用性；exploratory
- [Hy-MT2 字幕流程官方资料复核](2026-10-06-hy-mt2-subtitle-flow-review.md)：核查提示、批量协议、采样与验证边界，建议已回写 Hy-MT2 草案；未实施、未运行推理

### 翻译模型与量化比较（2026-10-06 至 2026-10-07）

- [RTX 5080 16 GB 翻译模型量化选择](2026-10-06-translation-5080-quantization.md)：五个指定模型的 GGUF、文件大小与全 GPU／混合运行边界，纠正 30B-A3B Q4 显存预期；exploratory，未实测
- [Hy-MT2 30B-A3B Q4 候选](2026-10-06-hy-mt2-30b-q4-candidates.md)：首次四位 GGUF 来源与容量调查；后续官方 Q4 实测见文内更新链接
- [Hy-MT2 30B-A3B 5080 量化短名单](2026-10-06-hy30-5080-quantization-shortlist.md)：历史 exploratory，固定文件与试验优先级；当前决定见 ADR-0005（APEX-I-Compact）
- [五候选字幕翻译正式比较](2026-10-06-translation-model-comparison-results.md)：三家族五版本固定 test，408/415 语义终分；结论为条件化质量／性能建议，附完整失败成本
- [Hy30 Q3／Q4 实测对照](2026-10-06-hy30-q3-q4-comparison-results.md)：各 83/83 终分，Q4 中位耗时 4.18 倍而质量收益有限且不稳定；当时用户保留 Q3，现行基线见 ADR-0005
- [Hy30 四量化质量、耗时与显存稳定性](2026-10-07-hy30-four-quantization-results.md)：83 旧窗与 1,200 新窗分别报告，含配对不确定性、四轮耗时与 30 分钟长跑；用户随后采纳 APEX-I-Compact，附录见 [四量化附录目录](2026-10-07-hy30-four-quantization-results-appendices/reproduction.md)（含 identity、expanded-quality、formal-stability 等附录与数值 JSON，随母报告登记）

### 翻译流程探索 v1–v4（2026-10-07 至 2026-10-11）

- [Hy30 流程参数核对](2026-10-07-hy30-flow-parameter-check.md)：30B 官方采样与 native HTTP 映射、模板与资源实测边界；仅为参数与接口核对
- [固定 APEX-I-Compact 的 SRT 流程筛选（第一轮）](2026-10-07-hy30-flow-optimization-results.md)：主要低成本方向无确认优势，未替换基线；文首更正指出证据只支持具体配方未过 8 窗筛选，不能据此淘汰整个方向
- [Hy30 流程 v1／v2 经验提炼](2026-10-10-hy30-flow-v1-v2-lessons.md)：对既有证据的提炼，作为 v3 先验；数值来自旧裁判 `gpt-6.1-sol`，与后续 Claude 裁判分数不可比，不是采纳决定
- [Hy30 流程 v3 报告](2026-10-10-hy30-flow-v3-report.md)：19 个配方、Claude MQM 裁判，0 个通过确认，b10-joint 在确认集未复现（后续因工程选择被采纳，见 ADR-0006）；确认集现已开封，再做确认须新建独立确认集
- [Hy30 流程 v4 报告](2026-10-11-hy30-flow-v4-report.md)：`mbr8c`（每批 8 个样本、逐条 chrF-MBR）通过确认，Δ −0.016，约 6 倍墙钟；`t03` 未通过，基线仍为 b10-joint，由用户决定是否替换

### 双语字幕流水线 cue 规则（2026-10-15）

- [cue 间隔断句引入 ASR token 边界](2026-10-15-cue-token-boundary-study.md)：两个引擎的 token 都能稳定映射到窗口字符，但 Whisper 日文 token 接近单字，"同一 token 内不断句"在四部整片只减 12 条 ≤2 字条目且新增 >6 s 条目，不能修复票据 12 的样本；用户裁定不实现，根因归 VAD 召回。只有离线统计，无人工观感

### w0／x0 两路 ASR 交叉合并：oracle 上限、MMS 声学裁判与交叉打分（2026-10-19）

- [oracle 上限测算](2026-10-19-asr-pair-oracle.md)：concluded（纯离线 CPU，待用户裁定是否开新线）。HF II／III 的产品 w0、x0 `ja.srt` 与参考按时间重叠连成三轨单元，逐单元字符级编辑距离：oracle 选择（取更接近参考的一路）两部合计 CER 16.16% → 12.46%，oracle 拼接（逐分歧区间、全局最优）→ 11.90%；增益一半来自删除对方多出的插入字。分歧区间 1253 个（覆盖约 13% 参考字符，无时间集中），两路都错占有参考单元 48%（40% 完全相同），30 个区间人工分类中 8 个仅是表记差异。适用：这两部电影、产品 w0／x0 配置、SRT 显示字幕参考；未覆盖：真实选择器的准确率与成本（未测，也未试任何第三方模型）、译文层收益、剧集。脚本 [`experiments/quality_v5/asr_pair_oracle.py`](../../experiments/quality_v5/asr_pair_oracle.py)
- [MMS CTC 声学裁判与 w0 幻觉过滤](2026-10-19-asr-pair-ctc-judge.md)：concluded（GPU 只做 MMS 前向，待用户裁定）。Part A：每个分歧区间构造只差该区间的两个整单元假设，CTC 前向对数似然（OOV 用常数列 log(1/2268)，区间含 OOV 的 47 个排除），规则 score_x − score_w > m＋λ·Δlen，跨片调参（II λ −0.75／m 16.5，III λ 1.75／m 16.0）：CER 两部合计 16.16% → 15.40%（oracle 拼接 11.90%），改动 82 个区间、54 个与 oracle 一致；w0 多出 AUC 0.71／0.79，替换 0.54／0.48，30 个人工样本只改 1 个，表记差异一个未动。Part B：插入 vs 完全一致的单元，每字 Viterbi AUC 0.975、Whisper 窗口 avg_logprob 0.914，跨片阈值丢弃后 CER 16.16% → 16.14%（上界 15.41%）。适用：这两部电影、产品 w0／x0、MMS `jpn` 原样；未覆盖：读音级打分、逐 cue 过滤、听音核对、剧集与官方整片口径。脚本 [`experiments/quality_v5/asr_pair_ctc_judge.py`](../../experiments/quality_v5/asr_pair_ctc_judge.py)
- [Whisper 与 Qwen 交叉打分裁判](2026-10-19-asr-pair-cross-score.md)：concluded（GPU 只做两个产品 ASR 的教师强制前向，待用户裁定）。同一单元、区间与跨度；Whisper 用 CT2 `align()` 的 `text_token_probs`（sot 前缀，CT2 自动补 notimestamps，不含 EOT），Qwen 用 `apply_transcription_request` 提示后接假设与 `<|im_end|>` 单次前向；SRT 原文只替换区间字符。跨片调参：Whisper 14.31%（λ 0／0.25、m −1）、两者都同意 14.23%、之和 14.56%、Qwen 15.09%、三路加 MMS 14.60%；准确率 72.0%／72.2%（全取 w0 65.0%）。替换 AUC Whisper 0.774、Qwen 0.641、之和 0.733、MMS 0.490；自偏好两边都有（Qwen 更重）；d_W 与 d_Q 的 Spearman 0.38。幻觉角度：每字分数 AUC Whisper 0.976、Qwen 0.974（MMS 0.975），丢弃后 CER 15.92%／16.04%。适用：这两部电影、产品 w0／x0 原样；未覆盖：Whisper 的 EOT 概率、听音核对、剧集与官方整片口径；18 个裁判配置之间的选择没有独立验证集。脚本 [`experiments/quality_v5/asr_pair_cross_score.py`](../../experiments/quality_v5/asr_pair_cross_score.py)
- [音频接地裁判候选调研](2026-10-19-acoustic-judge-survey.md)：exploratory。比较 13 个候选（MMS、rs35kh、Parakeet-ja CTC、Whisper／Qwen 教师强制、音素化、音频 LLM、TTS 似然等）在 oracle 误差构成（71% 替换、同音／表记占多数、一半增益是删插入）上的适用性：声学 CTC 看不出同读异形，交叉打分最有希望；附 §6 本机词表覆盖实测、§5 验证方案与限制。未在本项目数据上测过任何候选的判别力

### 字幕质量探索第五轮（2026-10-16）

- [方案、进度与结论](2026-10-16-quality-exploration-v5.md)：concluded。14 步（含追加的确认步）：swr 基线 → ASR 源 vs 参考源瓶颈定位、一致性指标、可读性、观感抽查 → 自动投向（先 STT）→ VAD 召回、ASR 候选第二轮 → 更省 MBR、语义效用、低温组合、术语表 → mbr8s 剧集确认 → 结题；唯一确认的改进是语义效用 MBR（剧集 −7%，6.3 倍墙钟），用户已裁定放弃（ADR-0008）；其余后续列在第 8 节

### 字幕翻译流程第八轮：同一句话小组内语序重排（2026-10-18）

- [方案、进度与结论](2026-10-18-group-reorder-v8.md)：concluded（Q1 否定，按停止条件结题；Q2–Q4 未执行）。设计：包、切包、邻文、grammar、裁判沿用 `dp10-cut`，只在包内按 R2+（停顿 <1.0 s 且前一行无句末标点）划组、注入 `groups` 并把 joint 提示的逐 ID 归属句改为"组内可按中文语序重新分配"（`joint-understanding-v2`），唯一变体 `grp1`。结果：两次小样 20 包 70 组，重排率主阈值 0.2 下 0–6.2%，在严格对严格噪声底内，人工无一例挪内容；两步式措辞不采纳。保留设施：`grp1` 配方、`batching.sentence_groups`、`reorder_groups/{checks,coverage,sample}.py`；备选路线（组级输出再切回）与产品门槛待裁定（§8）

### 同一句话小组内语序重排：划组规则（2026-10-18）

- [划组规则离线统计](2026-10-18-reorder-group-offline-stats.md)：concluded。`dp10-cut` 包内按"停顿 <门槛，且前一行不以 `。？！?!.` 结尾"划组（R2+）：dev 上门槛 1.0 s 时 78% 的 cue 落在多 cue 小组、4+ 条组覆盖 42%，产品时间轴为 50%／8%；字面全角 `。？！` 在产品上无效（产品句末标点几乎全是半角）；整片小组被切点截断约 11–12%（dev）。脚本 [`experiments/reorder_groups`](../../experiments/reorder_groups/stats.py)。适用：dev 字幕组时间轴与 HF II／III 产品时间轴；未覆盖：无说话人标注、无 GPU 生成与裁判，说话人切换只有文本代理指标

### 字幕翻译批次：上限 10 条的切法与长停顿门槛（2026-10-17）

- [离线模拟](2026-10-17-dynamic-cut-batching-simulation.md)：concluded。上限 10 条时限制平均包大小的主要是"只在 <1 s 小组之间切"，硬边界改短（3／5 s）会让平均值掉到 5 条左右；分级切点＋硬 20 s 平均 8.69（dev）／7.83（产品），68%／95% 的切点落在 ≥1 s 停顿上。适用：dev 字幕组时间轴与 HF II／III 产品时间轴；未覆盖：没有 GPU 生成与裁判，质量为推定；v7 裁判数据按停顿分组测不出门槛效应。被 ADR-0010 采纳。

### 字幕翻译流程第七轮：按静默拼包、停顿标记与两级结构（2026-10-16）

- [方案、进度与结论](2026-10-16-gap-aware-batching-v7.md)：concluded（三个变体都无改善；只有 mark5 满足非劣保留标准，是否保留待裁定）。实现入口 [`scene_batching_v6`](../../experiments/scene_batching_v6/README.md)（`--round v7`）。四个问题：Q1 彻底的按静默拼包（全局最优切分＋按停顿取邻文）是否有用；Q2 问题在切法还是在模型不知道时间（不切包只插停顿标记的对照变体）；Q3 包由 <1 s 小组拼成是否非劣（与语序工作共用边界）；Q4 是否值得成为默认。设计已在 §4 定死，执行者只填惩罚权重、标记文字与 grammar 处理

### 字幕翻译流程第六轮：场景感知分批（2026-10-16）

- [方案、进度与结论](2026-10-16-scene-aware-batching-v6.md)：concluded（Q2 独立 seed 不复现，按停止条件结题；不改默认的建议待裁定）。实现入口 [`scene_batching_v6`](../../experiments/scene_batching_v6/README.md)。三个问题：Q1 跨场景混批处的错误是否以 wrong-referent 为主（离线）；Q2 场景感知切批在只有切法改变的批次上是否降低惩罚、全集是否非劣；Q3 是否值得作为零成本工程默认。立项前的间隔分布与观察性对比数字见 §2

## 验收记录

条目格式：`[主题 日期](acceptance/文件.md)：验收范围与未覆盖项`

- [cross 模式 T0 共驻显存探针 2026-10-19](acceptance/2026-10-19-cross-coresidency-probe.md)：同一进程常驻产品 `WhisperAsr` 与 `QwenAsr`，HF II／III 全部窗口按 ①w0 转写 ②x0 转写 ③Whisper 分歧区间打分（d > −1 取 x0）运行，0.5 s 整卡采样与每阶段 torch 峰值：整卡峰值 10688 MiB，峰值＋1 GB ≤ 13.5 GB，判定共驻；DLL 与导入顺序无问题；PCM、VAD 与 13 个模型文件 SHA 核对通过。未覆盖：产品 worker 路径、重复性与桌面占用变化、三段式回退实测、CER 与听音核对
- [ffmpeg 升级到 9.0 维护分支 2026-10-19](acceptance/2026-10-19-ffmpeg-9.0-upgrade.md)：BtbN `n9.0.2-28-g669f5ab083` 与旧 gyan.dev 构建用产品 extract 代码派生 HF II／III 的 16 kHz WAV，PCM SHA256 逐字节相同且等于基线，补偿记录相同；未重跑整片，只覆盖这两部的 FLAC 立体声音轨

- [双语字幕流水线 swr 回归重测 2026-10-16](acceptance/2026-10-16-bilingual-pipeline-swr-regression.md)：改回 swr 后 HF II／III 各以 w0、x0 整批重跑 `python -m kototoki`：派生 WAV 与基线 PCM 逐字节一致，w0 CER 与 2026-10-05 基线逐项相同（16.81%／13.77%），x0 差 ≤0.15 个百分点；477 个翻译批次降级与回退 0；记录各阶段墙钟与显存峰值。未覆盖：翻译质量评分、失败路径重跑。
- [双语字幕流水线最终验收 2026-10-15](acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)：同一评分器下产品 STT 与 2026-10-05 基线回归（CER 高 0.5–3.5 个百分点，根因为 soxr 派生 WAV 使 Pyannote 少保留语音，GPU 核实）；cue 规则统计与人工抽看；真实环境的无语音、5.1、损坏文件、强杀与残留锁、`force` 覆盖、确定性全部通过；发现 `DURATION-<lang>` 标签缺陷与 cue 内切词。未覆盖：翻译裁判评分、worker 退出码 2 真实路径、6.1／7.1 与广播 `.ts`。
- [双语字幕流水线两部整片 2026-10-14](acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)：Heaven's Feel II／III 各以 w0、x0 整批运行 `python -m kototoki`，12 份 SRT 齐全、STT 零失败、降级与回退 0；记录各阶段墙钟、显存峰值、失败清单与磁盘占用。首轮翻译因桌面占显存低于启动阈值而失败，经进程内临时阈值 14700 MiB 续跑成功。未覆盖：质量与基线回归、真实降级路径、GPU 阶段中途中断、强杀与其他声道布局。
