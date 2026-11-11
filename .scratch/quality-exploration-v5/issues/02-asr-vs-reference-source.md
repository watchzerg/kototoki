# 02 瓶颈定位：ASR 源 vs 参考源翻译对比

Status: resolved
Type: research
Blocked by: 01

## 范围

- 目标：量化产品中文字幕的错误里有多少是 ASR 带进来的，给出 STT 侧与翻译侧各自的收益上限估计。
- 输入：01 的产品 `ja.srt`／`zh.srt`（w0，两部）；参考日文 SRT（`docs/testing/fatestay-reference.md` 登记的 II／III 文件，只读）。
- 生成：用 `just translation-srt`（b10-joint）翻译参考日文 SRT，3 个 seed；产品 ASR 源若只有 1 个 seed，补到 3 个（同配方）。产物在 `.local/quality-exploration-v5/02/`。
- 测量设计见研究文档 §5"对第 2 步的测量提示"：机械层按时间对齐、逐 cue 日文 CER 分桶；裁判层新建版本化成对偏好 profile（盲序、输出偏好与错误列表），先做对照 vs 对照盲重复校准，再对各桶抽样判分。设计改动要写理由。
- 隐私：裁判只收日文源与两个中文候选，不发音视频。

## 完成标准

- 校准结果（盲重复一致率、同一候选两次判分的偏好率应接近 50%）。
- 按桶的偏好率与错误类型表；"ASR 带来的中文错误占比"的区间估计；与 v4 `mbr8c` 干净源收益（约 4–7%）并列。
- 新 profile 名称、提示文本 sha256、调用次数与配额记录。
- Answer 写明两侧收益上限与建议，不做裁定。

## 文件所有权

新脚本 `experiments/quality_v5/`（含离线测试）；研究文档 §6／§7。不修改 v3／v4／冻结代码。

## 执行记录

- 2026-10-16 claimed。假设：产品中文字幕的错误有相当一部分来自 ASR；量化为"ASR 带来的中文错误占比"r。唯一变化：翻译的日文来源（参考日文 SRT vs 产品 w0 ASR 的 `ja.srt`），配方、入口与 seed 相同。
  - 生成：两侧都用 `just translation-srt` 的同一入口（`experiments.translation_v3 translate-srt --recipe b10-joint`，因 `--root` 是顶层参数，直接调用 legacy 解释器，等价于 `just translation-srt`），独立 root `.local/quality-exploration-v5/02/v3root`，seed 20261051／52／53。产品自带的 `zh.srt`（seed 20261008，产品实现）不进配对，两侧都用同一实现以免混入实现差异。脚本 `.local/quality-exploration-v5/02/run_translations.sh`，日志 `run-log.txt`。参考 SRT 使用前 SHA256 与登记一致（II `8366d17a…`、III `7c778cbd…`），结束后复核。
  - 机械层（`experiments/quality_v5/asr_source.py units`）：参考 cue（`fullfilm-v1` 参考 JSON 的 spans，与 SRT 1:1）与产品 cue 按时间重叠连成单元（连通分量），逐单元日文 CER（`kototoki_eval.schema.normalize` 同口径）；分桶 exact（0）、light（≤0.25）、heavy（>0.25）、missed（ASR 无字）、inserted（参考无字，不判，只计数）。阈值 0.25 在看任何裁判结果前固定。
  - 裁判层：新 profile `v5-asr-pairwise-v1`（Opus 5.5，复用 v3 `CliBackend`），每条给参考日文＋前后各 2 单元日文语境＋盲序 A／B 中文，输出两侧错误列表（类别、minor 1／major 5／critical 10）与偏好；8 条一包。条目：main（参考源 vs ASR 源，seed 轮换）按桶抽样；校准 calib-same（同一译文两份，应平局、惩罚相等）、calib-seed（参考源 seed k vs k+1，偏好应近 50%）、calib-repeat（main 的一部分原样重判，测一致率）。
  - 估计：r_all ＝ Σ_b N_b·mean(py−px)_b ／ Σ_b N_b·mean(py)_b（N_b 为两部单元数，b ∈ exact／light／heavy／missed），桶内按条目 bootstrap；另报只算 light＋heavy＋missed 的 r_text（exact 桶的差异来自 cue 切分与采样，归 STT 侧但不是识别错误）。
  - 与设计提示的差异：用 MQM 式错误列表的惩罚差而不只是偏好率，因为偏好率不能直接换算成"错误占比"；偏好率仍报告作交叉检查。

## Answer

**产品中文字幕的错误约四分之三来自 STT 侧。** 同一 b10-joint 入口分别翻译参考日文与产品 w0 ASR 日文（各 3 seed），按时间对齐成 1820 个可判单元并按日文 CER 分桶，新 profile `v5-asr-pairwise-v1`（Opus）盲评 396 条（含 136 条校准）：ASR 带来的中文错误占比 **r_all ＝ 0.76（CI90 0.70–0.82）**，只算识别错误桶的 r_text ＝ 0.68（0.60–0.76）；两部方向一致（II 0.70、III 0.81）。校准通过：同一译文两份 100% 平局，参考源 seed 对 seed 偏好 14% 对 17%、平均差 −0.08，重判胜负一致 90%。成本：生成 12 run 约 32 分钟 GPU，裁判 50 次调用 $2.16。

| 侧 | 收益上限（相对产品总惩罚） | 依据 |
| --- | --- | --- |
| STT 侧（识别、漏检、cue 切分） | 至多约 76%（ASR 完美时）；heavy＋missed 两桶占 ASR 多出惩罚的约 66% | 本票 r_all；按桶外推 |
| 翻译侧（干净源上的配方改进） | 约 1%：v4 `mbr8c` 在干净源上改善约 4%（电影约 0%），只作用于剩下的 24% | v4 §5 |

建议（不裁定）：按研究文档 §3 投向规则，r ≥ 40%，06 应先做 STT 侧（11 → 12）。STT 侧里最集中的是 heavy 与 missed 两桶（人名误识、漏检整句），VAD 召回（11）直接对应 missed，ASR 候选（12）对应 heavy；翻译侧仍按顺序做，但在本产品输入上的可见收益上限很小，适合关注一致性（10）而非准确性。

## Comments

- 2026-10-16 建票。
- 2026-10-16 生成：12 个 run 全部完成（`run-log.txt`），每个 150–180 s，参考源与 ASR 源各 3 seed × 2 部。首次批量因本会话 shell 未经 mise 激活、legacy 解释器 3.12 找不到而全部 exit 2（`run-log.failed-no-mise-env.txt`），补上 mise.toml 的 UV 环境变量后重跑；III 参考源 3 个 run 因 MSYS 把 `/d/movie/...` 带直撇号的路径转换错（`D:\d\movie\...`）exit 1，改用 `D:/movie/...` 路径补跑（`run_translations_fix.sh`）。这些都是工程失败，未进入模型。参考 SRT 使用后 SHA256 复核不变。
- 2026-10-16 单元（`units/hf-{ii,iii}.jsonl`）：

  | 桶 | II 单元 | III 单元 | 合计 | 参考字符 II／III |
  | --- | ---: | ---: | ---: | --- |
  | exact | 393 | 418 | 811 | 4092／4355 |
  | light（≤0.25） | 235 | 275 | 510 | 4250／5342 |
  | heavy（>0.25） | 221 | 186 | 407 | 2132／1546 |
  | missed | 61 | 31 | 92 | 307／110 |
  | inserted（不判） | 26 | 44 | 70 | — |

- 2026-10-16 判分计划（看任何裁判结果前固定）：main exact 60、light 80、heavy 80、missed 40；calib-same 32、calib-seed 64、calib-repeat 40；抽样 seed 20261016；共 396 条、50 包。先试 2 包核对输出与成本，再全量。
- 2026-10-16 判分：试 2 包（$0.048／$0.054，17–20 s）后全量，50 包全部一次成功，无阻塞，合计 $2.16、约 15 分钟（`judge/packet-*.json`，`judge.log`）。profile `v5-asr-pairwise-v1`，系统提示 sha256 `e226cbe5…`，模型身份只有 `claude-opus-5-5`。
- 2026-10-16 校准（`estimate.json`）：calib-same 32 条全部平局、两侧惩罚全部相等；calib-seed 64 条偏好 x 14.1%／y 17.2%／平局 68.8%，平均惩罚差 −0.08（px 0.70）；calib-repeat 40 条胜负一致 90%，Δ 的平均绝对差 0.68 分。
- 2026-10-16 主结果（每桶 main 条目；惩罚为每单元 MQM 权重和）：

  | 桶 | 判 n／总单元 | 参考源 px | ASR 源 py | 偏好 参考源／ASR 源／平 |
  | --- | --- | ---: | ---: | --- |
  | exact | 60／811 | 0.43 | 0.82 | 25%／10%／65% |
  | light | 80／510 | 0.53 | 2.25 | 50%／9%／41% |
  | heavy | 80／407 | 0.64 | 3.96 | 66%／13%／21% |
  | missed | 40／92 | 0.23 | 4.20 | 98%／0%／3% |

  r_all ＝ 0.764（CI90 0.699–0.822，CI95 0.685–0.833）；r_text（只算 light＋heavy＋missed）＝ 0.682（CI90 0.603–0.759）。分电影（`estimate-per-film.json`）：II r_all 0.70（CI90 0.59–0.80）、r_text 0.59；III 0.81（0.73–0.87）、0.75。按单元数外推的总惩罚：参考源约 900、ASR 源约 3810（约 4.2 倍）。
  - ASR 源侧错误类型：heavy 桶误译 major 24／critical 12、术语 major 7；missed 桶 32 条 major 漏译；exact 桶也比参考源多（0.82 对 0.43，术语 major 3 对 1），来自 cue 切分与批次语境不同。110 条 major 以上 ASR 源错误的说明里 22 条涉及人名（遠坂→东坂、士郎→四郎、さくら→萨克、マキリ→真理）。
  - 一致性指标对照（`consistency/s*.json`，04 的指标，三 seed 平均）：参考源 II 0.137、III 0.075；ASR 源 II 0.193、III 0.102。ASR 让人名摇摆约多 0.04，但两部的职阶名摇摆在参考源上已经存在（翻译侧）。注意两侧术语集合由各自日文抽取，不完全相同。
  - inserted 70 个单元（ASR 多出的语音或幻觉）不判分，不计入 r。
