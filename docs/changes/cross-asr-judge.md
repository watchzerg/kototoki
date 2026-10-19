# 产品 STT 增加 `cross` 模式：x0 转写＋Whisper 交叉打分裁判

状态：draft（2026-10-19）。本次增量说明：写明这次改什么、验收什么、涉及哪些当前正文；按[文档维护规则](../agents/documentation.md#三态规则)吸收进当前正文后删除。  
范围：产品包 `kototoki/` 的 asr 阶段新增一种引擎取值 `cross`，在同一 worker 进程内用 w0（Whisper）与 x0（Qwen3-ASR）各转写一遍，再由 Whisper 对两路分歧区间打分合并，产出与现有同构的 `asr.json`。默认引擎仍为 `w0`。  
不做：不改阶段链，不改 align／cues／translate 的接口，不改 MMS 与翻译阶段的显存模型，不把 `cross` 设为默认，不做剧集或新材料确认（用户 2026-10-19 裁定直接产品化，确认推迟）。

## 1. 决定与依据

用户裁定（2026-10-19）：按"Whisper 与 Qwen 在同一 asr worker 内共驻、逐文件转写两路再由 Whisper 打分合并、阶段链不动"的架构实施到生产代码。

依据是三份同日研究（都在 HF II／III 两部电影、单元口径上）：

| 证据 | 数字 | 文档 |
| --- | --- | --- |
| 合并的理论上限 | 两部合计 CER 16.16% → 11.90%（oracle 拼接） | [oracle 上限](../research/2026-10-19-asr-pair-oracle.md) |
| MMS CTC 当裁判 | → 15.40%，替换区间 AUC 0.49，长度项符号两片相反 | [MMS 裁判](../research/2026-10-19-asr-pair-ctc-judge.md) |
| Whisper 单独当裁判 | → **14.31%**（拿到上限增益 43%），替换区间 AUC 0.774，参数两片几乎相同（λ 0／0.25，m −1） | [交叉打分](../research/2026-10-19-asr-pair-cross-score.md) |
| 叠加 Qwen 或 MMS | 之和 14.56%、三路 14.60%，都不如 Whisper 单独；"两者都同意"14.23%，差距在选裁判噪声内且多一个模型 | 同上 |
| 为什么 Whisper 能判自己 | 生成走岔路与判断两句话哪句更配音频是两件事；自偏好（52%）是稳定偏置，阈值 −1 吸收 | 同上 §1 |
| 候选调研 | MMS 是顺手选的；交叉打分排第一（推断），今已实测 | [裁判选型调研](../research/2026-10-19-acoustic-judge-survey.md) |

要打的折扣（验收时对照）：8 个纯表记样本里 Whisper 改了 6 个，计入 CER 但不影响译文；Whisper 分数不含结束符，多字少字类区间有"越短越占便宜"的偏差；研究是 cue 并集的单元口径，产品是 VAD 窗口口径，数字会有差异。

## 2. 设计

### 2.1 流程形态

阶段链不变：probe → extract → vad → asr → align → ja-cues → translate → merge。`cross` 只改变 asr 阶段内部：

```
python -m kototoki.workers.asr --jobs batch.json   (engine = cross)
  启动：加载 Whisper（CT2 fp16）→ 加载 Qwen（bf16）→ 两者常驻到进程退出
  逐文件：
    ① Whisper 转写全部窗口            → asr-w0.json（完整 asr.json 结构）
    ② Qwen 转写全部窗口               → asr-x0.json（完整 asr.json 结构）
    ③ 裁判：逐窗口找分歧区间，Whisper 对每个区间的两个假设打分，按规则选择
                                       → asr-judge.json（审计）＋ asr.json（合并结果，与现有同构）
```

- **为什么放在 asr 阶段内而不是新阶段**：裁判需要两路文本和 Whisper 同时在手；独立阶段意味着再加载一次 Whisper，plan.py 的阶段链、身份与"下一个要跑的阶段"都要改；放在 asr 内部则 align 及之后的阶段只看到 `asr.json`，接口不变。
- **为什么逐文件三步而不是整批三步**：保留现有"worker 逐文件增量写结果、文件级失败只跳过该文件"的语义；两模型常驻后，逐文件不多付加载开销。
- **常驻省下的只是一次 Whisper 重载（3–7 s／批）**，不是本方案的收益来源；收益来自 x0 提供第二份答案。
- **显存预算**（整卡峰值，含桌面 0.5–1.5 GB，来自[swr 回归](../research/acceptance/2026-10-16-bilingual-pipeline-swr-regression.md)与[交叉打分](../research/2026-10-19-asr-pair-cross-score.md)）：

  | 项 | 单独实测 MiB | 说明 |
  | --- | ---: | --- |
  | asr w0 转写 | 5265 | |
  | asr x0 转写 | 5420 | |
  | Whisper 打分 | 5903 | 空闲 1452 |
  | Qwen 打分 | 6945 | torch 分配 4229 |
  | **两者共驻（T0 实测）** | **10688** | 同进程、两部片三步，[探针记录](../research/acceptance/2026-10-19-cross-coresidency-probe.md)；加 1 GB 余量 11712 < 13824，采用共驻 |
  | align（MMS fp32） | 8515 | 不能与上两者共驻，保持独立阶段 |
  | translate（Hy-MT2） | 15648 | 启动要求空闲 ≥ 14700，必须独占 |

  共驻峰值阈值：探针实测峰值加 1 GB 余量仍 ≤ 13.5 GB 才采用共驻（T0 已通过，2026-10-19）；否则回退为"Whisper 整批转写 → 卸载 → Qwen 整批转写 → 卸载 → Whisper 整批打分"的三段式（多付一次 Whisper 加载，每批几秒），回退方案不改产物与接口。
- **DLL 与进程**：asr worker 已规定先 `import torch` 再导入 `ctranslate2`／`faster_whisper`；`cross` 在同一进程里同时持有 CT2 与 torch 的 CUDA 显存，这是本方案唯一的新进程形态，T0 探针一并验证。

### 2.2 裁判算法（窗口级）

两路共用同一份 `vad.json`，窗口一一对应，窗口 ≤ 30 s（`MAX_WINDOW_SAMPLES`），Whisper 的 30 s 上限天然满足。

1. **规范化与原文映射**：对窗口的 w0、x0 文本做规范化（复制 `kototoki_eval.schema.normalize` 的规则到 `kototoki/judge.py`，产品包不导入 `kototoki_eval`），保留规范化字符到原文位置的偏移映射。
2. **分歧区间**：规范化文本做字符级编辑距离对齐，非匹配操作的极大连续段为一个区间（相隔至少一个匹配字符才分开），同研究脚本 `disagreement_intervals`。
3. **假设构造**：x0 原文先去掉与非 ASCII 字符相邻的空白（Qwen 会在日文字符间输出空格；只清 x0，w0 原文不动，规则写进配方）；hyp_w ＝ w0 窗口原文；hyp_x ＝ 只把该区间按偏移映射换成 x0 原文字符，其余（含 w0 标点）不动；映射失败回退到规范化文本（两假设总用同一形式）。同研究主口径 raw。
4. **Whisper 打分**：`features()` 建 mel（右补零到 30 s），`model.encode` 一次，编码复制成批后调用 `Whisper.align(encoder, start_sequence, text_tokens, num_frames)`；start_sequence 为 `tokenizer.sot_sequence`（`<|startoftranscript|><|ja|><|transcribe|>`，CT2 自动接 `<|notimestamps|>`，等价于产品无时间戳、无 initial prompt 的提示；直接传含 `<|notimestamps|>` 的产品提示会被重复接一次，研究 §3 已验证）；分数 ＝ Σ log `text_token_probs`（不含 EOT）。一个窗口的 hyp_w 与全部 hyp_x 放进同一批（批上限 16），编码只算一次。
5. **判定规则**（写进配方 `CROSS`，不做配置项）：d ＝ score(hyp_x) − score(hyp_w)；**d > m 时取 x0，否则保持 w0**，m ＝ −1，λ ＝ 0（无长度项；研究的 Whisper 单独裁判 λ 为 0／0.25，无长度项版本 m −1／−1.5，取 −1）。
6. **多区间**：同一窗口的区间各自独立判定（每次只翻转一个区间、其余保持 w0），然后把全部被接受的翻转一起应用。与研究的"单独翻转后合并"口径一致，保证测得的数字可对照。
7. **守卫**：两路规范化后相同的窗口直接取 w0、不打分（研究中约一半单元相同，省一半打分）；合并结果为空而 w0 非空时保持 w0（裁判不删整窗）；x0 窗口失败（`failed_windows`）时该窗口取 w0、不裁判；w0 窗口失败时沿用现有语义，窗口仍记失败、不以 x0 替代（是否替代留作后续裁定，见 §7）。打分本身抛错（如 `align` 返回数量不符的 `RuntimeError`）时该窗口取 w0、记一条 warning 并计数，不作为窗口级失败，也不中断文件。
8. **不做**：不做幻觉过滤（研究显示 CER 收益 ≤ 0.24 pp 且误删单汉字真台词）；不叠加 Qwen 或 MMS 分数；不做长度项。

### 2.3 产物、身份与配方

- `asr.json`：结构不变，`engine` 为 `"cross"`，`original_segments` 为合并文本，`asr_traces` 取 w0 的 trace 并在 `metadata` 里记两路模型与裁判统计；`failed_windows` 为 w0 的失败窗口。align 阶段原样消费。
- 新增产物（同目录 `.work/<id>/`）：`asr-w0.json`、`asr-x0.json`（各自完整的 `asr.json` 结构，engine 分别为 w0／x0，可直接用 `kototoki_eval` 评分）、`asr-judge.json`（每窗口：两路原文、分歧区间、每区间 score_w／score_x／d／决定；文件级汇总：窗口数、相同窗口数、分歧区间数、改为 x0 的区间数、打分墙钟）。三者只作审计与离线复算，不参与 `is_current` 判定；asr 阶段的产物契约只认 `asr.json`。
- **身份**：`asr_identity("cross", …)` ＝ PCM SHA256 ＋ `vad.json` SHA256 ＋ `recipe_hash(CROSS)` ＋ 两路模型文件 SHA256（w0 模型＋mel 资产＋x0 模型）。`CROSS` 配方字典嵌入 `W0`、`X0` 两个配方与裁判参数（m、λ、文本形式、start_sequence 约定、批上限），一个 hash 覆盖全部；任一子配方变化即身份变化。
- **配置**：`[stt] engine = "cross"`；`ENGINES` 增加 `"cross"`；需要 `[asr.w0]` 与 `[asr.x0]` 两节（默认值已存在）；不新增配置项。
- **日志**：每文件一行 `[asr] <id>: cross windows N, identical K, intervals M, switched S, score X.Xs`；不记任何窗口文字（产品不变量）。

### 2.4 不变量核对

本地运行（无新外部服务）；ASR 与打分只跑 GPU；保留原语言（只在两路日文间选择，不改写）；权重、转写不进 Git 与日志（新增产物都在 `.work/`，日志只记计数）。

## 3. 自审修订

对 2026-10-19 讨论稿的 review，改了以下几点：

1. **相同窗口不打分**：约一半窗口两路规范化后相同，直接取 w0，打分量减半。
2. **一窗一批**：hyp_w 与该窗口全部 hyp_x 放进同一个 `align()` 批，编码只算一次；批上限 16，超出分批。
3. **失败窗口语义写死**：x0 失败取 w0；w0 失败不以 x0 替代（保持现有失败记账），避免引入研究没覆盖的行为；是否替代留作后续裁定。
4. **空结果守卫**：裁判不能把非空窗口合并成空。
5. **共驻有阈值与回退**：探针峰值加 1 GB 余量 ≤ 13.5 GB 才共驻，否则三段式回退，产物与接口不变。
6. **审计产物独立于身份**：`asr-w0/x0/judge.json` 不参与 `is_current`，避免给产物契约加分支；但保留它们使 CER 研究可以零 GPU 复算。
7. **长度项去掉**：研究里 λ 0 与 0.25 差别在噪声内，无长度项版本同样有效；少一个参数少一处过拟合。
8. **多区间口径与研究一致**：独立判定再合并，而不是顺序贪心，否则产品数字无法对照研究数字。
9. **默认不变**：`w0` 仍是默认与基线身份；`cross` 是可选模式，验收通过后由用户决定是否改默认（改默认需新 ADR）。

## 4. 实施票据

按 tracker 约定建 `.scratch/cross-asr-judge/`（spec 链接本文）；每张票一个文件所有者，写入者互不重叠。

| 票 | 内容 | 文件所有权 | 依赖 | 完成标准 |
| --- | --- | --- | --- | --- |
| T0 共驻显存探针（GPU，先问） | 同一进程加载 Whisper＋Qwen，对 HF II／III 全部窗口按 ①②③ 跑一遍（可用研究脚本的打分器拼装），`telemetry_run.py` 采样整卡峰值，记录加载、转写、打分墙钟；核对 CT2 与 torch 共驻无 DLL／OOM 问题 | `experiments/quality_v5/coresidency_probe.py`、`docs/research/acceptance/2026-10-xx-cross-coresidency-probe.md` | 无 | 峰值与阈值判定写入记录；决定共驻或回退 |
| T1 文档先行 | 模块边界（ASR 接缝三个适配器、新产物归属）、模块页 `stt-workers`、`stage-plan`、`artifact-contract`、`config-and-media`，技术设计 §1.1／§2／§3／§4／§10，ADR-0012（proposed），GLOSSARY 加 `cross` | 上述文档 | 无（与 T0 并行） | 接口形状定稿，用户过目 |
| T2 裁判纯逻辑 | `kototoki/judge.py`：normalize 复制、`align_ops`、`disagreement_intervals`、原文偏移映射、`compose`、`decide`、窗口级 `judge_window`、汇总；从 `experiments/quality_v5` 搬运，不导入 experiments | `kototoki/judge.py`、`tests/core/test_judge.py` | 无 | 离线测试覆盖：相同窗口、单／多区间、映射失败回退、空结果守卫、m 边界；与研究脚本在合成样例上结果一致 |
| T3 Whisper 打分 | `kototoki/asr_whisper.py` 增加 `score(audio, chunk, texts) -> list[float]`（编码一次、批 align、Σ log probs）；冻结窗口门禁 | `kototoki/asr_whisper.py`、`tests/core/test_asr_whisper.py`、`scripts/smoke/stt_frozen_window.py` | 无 | 伪模型离线测试；smoke 在冻结窗口上：产品转写文本的分数高于打乱文本，且与产品 avg_logprob 差 < 0.5 nat |
| T4 配方、配置、计划、产物名 | `recipes.CROSS`、`config.ENGINES`、`plan.ASR_RECIPES`／`model_files`／`asr_identity`、`artifacts` 新文件名常量 | `kototoki/recipes.py`、`config.py`、`plan.py`、`artifacts.py` 及对应 `tests/core/test_*.py` | 无 | 配方 hash 钉子测试；`cross` 需要两路模型文件；身份含两路 SHA |
| T5 worker cross 路径 | `kototoki/workers/asr.py`：`start` 按 engine 加载一或两个适配器；`compute` 的 cross 分支按 ①②③ 写四个产物；日志行 | `kototoki/workers/asr.py`、`tests/core/test_stt_workers.py`、`tests/fake_worker.py` | T2、T3、T4 | 伪适配器离线测试：产物齐全、x0 失败窗口取 w0、w0 失败窗口记失败、`asr.json` 通过 `validate_transcript` |
| T6 产品路径验收（GPU，先问） | HF II／III 以 `engine = cross` 整批运行 `python -m kototoki`，`kototoki_eval` 评分，telemetry 采样；翻译阶段照常启动 | `docs/research/acceptance/2026-10-xx-cross-asr-acceptance.md` | T5、T0 | 见 §5 |
| T7 收口 | ADR-0012 状态按验收结果改 accepted／rejected；模块页"变更与决策来源"记录；`just docs-check` 交集无新增报错；本文吸收后删除；研究索引登记验收记录 | 文档 | T6 | 当前正文不再引用本文 |

并行建议：T0、T1、T2、T3、T4 互不重叠，可同时开；T5 等三者；T6 需用户授权 GPU。

## 5. 验证与验收

- **离线**（每票随交付）：`just test`（core）全部通过；"编排器不 import torch"断言不变；新增用例按[测试设计](../agents/testing.md)归位。
- **smoke**：`just smoke` 增加 Whisper 打分冻结窗口项（T3）。
- **T0 探针**：共驻峰值 ＋ 1 GB ≤ 13.5 GB；无 DLL 加载错误；打分墙钟与研究同量级（两部约 90 s）。
- **T6 产品路径验收**（官方整片口径，对照 w0 基线 II 16.81%、III 13.77%）：
  - 两部 CER 都低于 w0，两部合计降幅 ≥ 1.0 pp（研究单元口径 −1.85 pp，扣除口径与表记差异后的保守线）；达不到则记录差异，由用户裁定是否仍采用。
  - `asr-x0.json` 的失败窗口数与单独 x0 运行一致（0）；`asr-judge.json` 汇总与 T0 探针同口径对照：相同窗口约 41／402，分歧区间约 1084，改为 x0 约 18.5%（研究的单元口径为 37.7%，口径不同不直接比）。
  - asr 阶段整卡峰值 ≤ T0 阈值；worker 退出后翻译阶段按现有轮询正常启动；12 份 SRT 齐全。
  - 墙钟：asr 阶段约为 w0 的 4.4 倍（T0 探针两部合计 w0 374.6 s＋x0 948.7 s＋打分 40.5 s ＝ 1364 s）；记录实际值。
- **未覆盖**（验收记录写明）：译文层收益（需 v5 第 2 步裁判，外部推理，另行裁定）；剧集与新材料确认；数值确定性；w0 失败窗口以 x0 替代。

## 6. 文档同步清单

| 文档 | 改什么 |
| --- | --- |
| `docs/architecture/module-boundaries.md` | ASR 接缝改为三个适配器写同一种 `asr.json`；`asr-w0/x0/judge.json` 归产物契约；裁判纯逻辑归基础层 `judge` |
| `docs/architecture/modules/stt-workers.md` | cross 的加载、逐文件三步、守卫、失败语义、日志行、显存预算与回退 |
| `docs/architecture/modules/stage-plan.md` | `cross` 的 asr 身份构成与模型文件清单 |
| `docs/architecture/modules/artifact-contract.md` | 三个新产物名与"不参与 is_current" |
| `docs/architecture/modules/config-and-media.md` | `stt.engine` 取值与 `CROSS` 配方 |
| `docs/specs/bilingual-subtitle-pipeline.md` | §1.1 固定配方、§2 asr 行、§3.2 显存行（STT 内共驻的例外）、§4 产物、§10 配置 |
| `docs/adr/0012-cross-asr-judge.md`（新） | 决定、范围、依据、代价、不采纳的替代（MMS 裁判、Qwen 叠加、幻觉过滤、独立阶段） |
| `GLOSSARY.md` | `cross`：产品 STT 引擎取值，w0＋x0 转写、Whisper 交叉打分裁判 |
| `docs/research/INDEX.md` | 登记 T0、T6 的验收记录 |
| `AGENTS.md` | 重任务清单不变（入口仍是 `python -m kototoki`）；无需改动 |

## 7. 风险与开放问题

- **共驻只测过一次**：T0 探针通过（峰值 10688 MiB），但峰值复现性、桌面占用变化与 WDDM 换出未观察；三段式回退未实测。
- **窗口口径与单元口径的差异**：产品数字可能偏离研究的 −1.85 pp；验收线取 −1.0 pp。
- **结束符偏差**：Whisper `align()` 拿不到 EOT 概率，"w0 多出"类区间偏向删除；研究数字已包含该偏差，产品保持一致，不另修。
- **表记改动**：桜／さくら 这类改动计入 CER 但不影响译文；译文层收益未测。
- **w0 失败窗口是否以 x0 替代**：研究未覆盖，本期不做，列为后续裁定。
- **是否改默认**：验收通过后由用户裁定，需新 ADR；按项目惯例应先在全新隔离材料上确认。
- **成本**：asr 阶段墙钟约 4.4 倍（T0 探针两部电影 1364 s，含打分 40.5 s），整批约 +115%；用户已接受。

## 8. 相关文档

[oracle 上限](../research/2026-10-19-asr-pair-oracle.md)、[MMS 裁判](../research/2026-10-19-asr-pair-ctc-judge.md)、[交叉打分](../research/2026-10-19-asr-pair-cross-score.md)、[裁判选型调研](../research/2026-10-19-acoustic-judge-survey.md)、[技术设计](../specs/bilingual-subtitle-pipeline.md)、[ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[模块边界](../architecture/module-boundaries.md)、[STT workers](../architecture/modules/stt-workers.md)。
