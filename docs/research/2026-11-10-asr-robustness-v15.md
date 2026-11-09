# ASR 稳健性第十五轮（v15）：A 守卫进产品的选型、B1 补窗实跑、C3 表内专名替换

状态：draft（2026-11-10 起草；用户已就 v14 §7.1 的三臂口头裁定方向，§8 开跑前事项确认后改 planned）。
范围：接 [v14](2026-11-09-asr-robustness-v14.md) 的三个后续。**A**：幻觉／重复守卫按“安全网”而不是“降 CER”立项，选出规则与动作并给出产品化形状草案；**B**：B1 空子段补窗实跑，只报数不设门，降多少由用户裁定；**C**：把 v14 的自由后校正收窄为“只允许按专名表替换”（C3），在日文转写侧量 CER、人名命中与有害率，并（条件触发）量对翻译的连带影响。w0 模型、VAD 参数、MMS 对齐仍不换；产品 `kototoki/`、ADR、基线身份本轮不改，产品化只在 §8 提草案。
执行载体：tracker 目录 `.scratch/asr-robustness-v15/`（spec、map、票据；Git 忽略）。**本文是唯一进 Git 的进度与结论记录。**
先读：[v14 研究文档](2026-11-09-asr-robustness-v14.md) §2、§4、§7、§7.1、§8；[ADR-0014](../adr/0014-name-consistency-in-product.md)（第 1 点的两个未测方向、第 2 点的替换规则一）、[ADR-0019](../adr/0019-product-translation-q2.md)、[ADR-0022](../adr/0022-product-names-on-strata.md)；[STT worker 模块页](../architecture/modules/stt-workers.md)；[模块边界](../architecture/module-boundaries.md)；代码 `experiments/asr_robustness_v14/`（全部）、`kototoki/workers/{asr,protocol}.py`、`kototoki/recipes.py`、`kototoki/names/{__init__,table,recipes}.py`、`kototoki/strata.py`、`experiments/quality_v5/asr_source.py`。

本文的对照、终点、判据与预算在起草时定下（§4、§5）。执行者只补实现细节（字段名、脚本结构），并在票据里写明理由。

## 1. 为什么做这一轮

- v14 结题（2026-11-09）：A 不进、B 不进、C 有效但不够，都是按“两部 CER 都降且合计 ≥0.3 pp”的门判的。用户 2026-11-10 看过结论后裁定（记在 v14 §8 第 12 项）：
  - **A 要加安全网**。守卫的价值不在平均 CER，而在拦住偶发但很难看的整窗复读；HF II 零命中零副作用、HF III 一窗 −41 编辑，说明保守阈值没有代价。具体做法由执行者选，值得再投入一轮研究测试。
  - **B1 实跑**，看能降多少，由用户按数字拍板，不写死 0.3 pp。
  - **C 收窄成“只允许按专名表替换”并量一下**，可以重开 ADR-0014 关闭的研究线（第 1 点方向 ①“一次性音译的模糊匹配”的日文侧版本）。
- v14 的证据边界：两部电影 3375 处编辑里，后处理能触达的只有幻觉窗 ≈40、空子段 ≤110、专名／同音字 ≈44。本轮不指望大幅降 CER，目标是把这三块各自做实：A 给产品一个可靠的安全网，B 给用户一个实测数字，C 给专名线一个日文侧的量化答案。
- 专名表已经带着误识别写法：Q3 产品表的 `forms[].ja` 里混有 ASR 听错的变体（HF III 表：遠坂↔父坂、セイバー↔セイマー、間桐臓硯↔雑賢），这是 C3 能“只按表替换”的直接依据。
- 架构评估 A-1（2026-10-19）记录 ATKD-089 一片 388 窗里 36 窗压缩比 >2.4、涉及 14% 的 cue，但该运行的 `asr.json` 可能已清理（输出目录只剩 SRT）；守卫的误报率只能在仍存在的 w0 产物上量。

## 2. 已知事实（不要重复）

- 对照、量尺、输入材料与 Strata 约束全部沿用 v14 §2（HF II 产品整片 `.local/q3-product-fullfilm/work/input-7c924c80249b/8d2f3e76dd0c/`，HF III 重算产物 `.local/asr-robustness-v14/01/hf-iii/fb2e0da74018/`，官方 II 16.81%（S 876／D 676／I 260）、III 13.77%（S 777／D 444／I 342），单元口径 II 17.90%（1930 编辑／10781 参考字）、III 14.58%（1655／11353））。
- v14 已有的离线事实：两部 402 窗里压缩比 >2.4 只有 III 第 51 窗（3.83，重复循环，94 字），无触顶，`avg_logprob` <−1.0 的 3 窗都是 2–4 字短输出；置空第 51 窗 −41 编辑，`no_repeat_ngram_size=5` 补解成 38 字 −38 编辑（仍有错字）；放宽到压缩比 >1.8／logprob <−0.8 在 HF II 多错 48 处。空子段（≥0.5 s）II 57／III 47，≥1 s 各 8，覆盖参考字符 72.5／37.4；直接落在空子段里的删除项占 6.3%。v14 C2 v2（专名表＋收紧提示）单元口径 II −12／III −32 编辑，Opus 抽看两次都指出收益只来自读音不变或近音的专名／同音修正。
- v14 代码可直接复用：`experiments/asr_robustness_v14/{common,signals,gaps,decode,guard,fill,correct,workers}.py`；`fill.py` 的 B1（单次补窗、按时间插入、过守卫）已实现未运行，CLI `python -m experiments.asr_robustness_v14 fill --rule <rule>`，产物写 `.local/asr-robustness-v14/03/`。
- 产品协议：`kototoki.workers.protocol.fail_window(asr, chunk_index, reason)` 把窗口文字置空并记 `failed_windows`，`align`、cue、翻译都不消费失败窗口；w0 目前只在抛异常时调用它，x0 的 `token_limit` 规则已在 `kototoki/recipes.py` 记为配方字段。ASR 配方 `W0` 的 id 是 `w0-faster-whisper-large-v3-v1`，任何改判定或改输出的变体都是新配方 id，产品配方 hash 有测试守着。
- 产品 `names` 阶段（ADR-0022）：与翻译共用的 Strata session 上用 Flash-Next 按 Q3 规则建表（配方 `q3-names-v1`，`kototoki/names/`），表只经翻译注入（high 条目）使用；没有发布时替换（ADR-0019 删除）。表 schema `name-table-v2`：`entries[].{entity_ja, kind, confidence, zh, forms[].{ja, zh}, zh_variants, evidence}`，`forms` 没有“规范写法／误识写法”的标记。
- ADR-0014 第 2 点的替换规则一：落点必须覆盖整个名字，否则不动；孤立单字规则；其余合并开关都不进产品。它是中文侧的字符串替换，本轮在日文侧借用其纪律。
- 评测设施（沿用 v13 §2.3）：产品 ASR 源的配对裁判 `v5-asr-pairwise-v1`（`experiments/quality_v5/asr_source.py`；x＝对照、y＝候选，同 seed、同 packet），一套两部约 $2.5（v13 阶段 E 6 套 $15）；人名错误与不一致率沿用 `asr10`（`experiments/scene_batching_v6/asr10.py`）与 `experiments/quality_v5/consistency.py`。

## 3. 本轮要回答的问题

1. **A 守卫**：在所有还找得到的 w0 产物上，哪条规则（压缩比／触顶／logprob／显式重复检测）能拦住已知的复读窗而**零误报**？对被拦窗口，置空、折叠重复、`no_repeat` 补解三种动作哪种整片 CER 最好、最不难看？进产品应放在哪一步、配方 id 与 ADR 要点是什么？
2. **B1 补窗**：空子段单独重解并过守卫后，两部删除降了多少、插入涨了多少、净 CER 变化多少（S／D／I）？守卫拦下多少补解？
3. **C3 表内替换**：只允许把转写里的片段换成专名表登记的写法时，（a）纯规则版与（b）Flash-Next 判定版各改了多少 cue，两部单元 CER、人名命中率、有害率各多少？与 v14 C2 v2 相比，去掉改写后收益保住了多少？（条件触发）用修正后的日文翻译，配对裁判下中文是否更好？
4. **建议**：A 的产品化草案（含“不建议”也要写明理由）；B 与 C 只给数字与解读，进不进产品由用户裁定。

## 4. 设计

### 4.0 通用规则

- **对照与口径**同 v14 §4.0：产品 w0 当前输出；A、B 写产品形状 `asr.json` 经产品 `align`，用官方口径；C3 只改 `ja.srt`，用单元口径并报告对照的单元口径分母。数字带 S／D／I，未知值不填 0。
- **判据**：本轮**不设统一的 0.3 pp 门**。A 用安全网判据（§4.1）；B、C3 只报数（§4.2、§4.3）并给执行者解读，“进不进产品”写进 §8 由用户裁定。
- **身份**：改判定或改输出的变体都是新配方 id（`w0-faster-whisper-large-v3-guard-v2`、`...-fill-v1`、`ja-names-replace-v1`），研究侧只在 `metadata.experiment` 记，不改 `kototoki/recipes.py`。
- **不多次解码再挑选**（[ADR-0008](../adr/0008-no-multi-translation-selection.md)）：补解只解一次、无条件采用或按守卫置空；C3b 每包只请求一次（解析失败重试一次 seed＋1 不算挑选）。
- **复用不改**：v14 的包只导入；需要新逻辑写在新包 `experiments/asr_robustness_v15/`。B1 直接用 v14 的 `fill` 入口。

### 4.1 A：守卫选型与产品化草案

- **A3 规则扫描（离线；Opus ≤$3）**：盘点所有仍存在的 w0 `asr.json`（至少 HF II／III 产品与 `.local/fullfilm-comparison/` 下的 w0 整片运行；ATKD-089 的若还在也纳入；同一部电影不同 VAD 参数的运行算作独立样本但分开报告）。每窗算四个信号：压缩比（zlib）、触顶、`avg_logprob`、**显式重复检测**（执行者定义并写明，例如“某个 ≥3 字的子串连续出现 ≥3 次且覆盖 ≥50% 文字”或“最小周期 p 的重复覆盖率”）。规则候选：v14 的 doc-default、whisper-or，加重复检测单独一条与“重复检测 或 压缩比 >2.4”一条。报告每条规则在每个样本上标记的窗数、字数。所有被任一规则标记的窗口（预计几十个）由 Opus（`opus`，只读）逐窗判“幻觉／复读 ／ 正常语音（含真实重复台词）／ 无法判断”，一句话理由；逐窗文字只写 `.local`，文档只记计数。**安全网判据**：规则必须拦住 HF III 第 51 窗，且在全部样本上对“正常语音”窗零标记；多条规则满足时取标记最多的那条（召回优先）。没有规则满足则 A 的结论为“只能以 doc-default 作保守安全网”，把误报窗列进 §8。
- **A4 动作比较（GPU ≤2 run：align 批）**：对选中规则标记的窗口（两部电影上）分别做三种动作——(i) 置空（v14 已有），(ii) **折叠重复**：保留第一个重复周期之前的文字、删除其后的重复（执行者定义，与 A3 的检测器一致；折叠后仍过守卫），(iii) `no_repeat_ngram_size=5` 单次补解后再折叠。全部变体的 `asr.json` 一次 `align` 批处理。报告官方 CER（S／D／I）与被改窗口的 Opus 读感（可并入 A3 的抽看预算）。动作取“CER 不劣于置空且文字更可读”的那种；拿不准就取置空。
- **产品化草案（只写 §8，不实现）**：阶段位置（`kototoki/workers/asr.py` w0 解码之后、`align` 之前，用 `fail_window(reason="guard:<rule>")` 或替换文字并记 trace）；配方 `W0` 新增 `guard` 字段与新 id；`cross` 引擎对 w0 失败窗口的既有规则（`w0_failed_window: stays failed`）是否够用；产品配方 hash 测试要改哪些；需要的 ADR 要点（ADR-0023 候选）；验收用哪部片（建议 HF III 第 51 窗＋全量回归 CER 不变）。若用户在 §8 第 2 项预批准，执行者在票据 02 后另开票据 07 实现并走产品验收；默认不实现。

### 4.2 B：B1 补窗实跑

- 直接运行 v14 的 `fill`：规则先 `doc-default`（最保守），再 `whisper-or`，各 1 GPU run（每次含 `align`）。只补 ≥1 s 的空子段（II 8／III 8），短于 1 s 的记数。
- 报告每部：补解子段数、守卫拦下数、空输出数、采纳字符数、官方 CER 前后（S／D／I）、删除降了多少、插入涨了多少；两条规则并列。再报一个上限参照：v14 B0 的 110 参考字（0.5 pp）。
- 不设门。执行者只写“净变化多少、代价多少（每部 GPU 秒数）”，进不进产品由用户按 §8 第 3 项裁定。

### 4.3 C3：只按专名表替换

- **表**：HF II 用 Q3 产品表（high 20）；HF III 不再用 27B 旧表，改在本轮 Strata session 里用产品配方 `q3-names-v1`（`kototoki.names.build_document`，最多 5 次请求取第一张合格表）为 HF III 建一张 Q3 表，两部口径一致（这也顺手回答 v14 §8 第 8 项）。旧表只作对照附录。
- **C3a 纯规则版（离线）**：对每个 `confidence: high` 的条目，把 `entity_ja` 与 `forms[].ja` 按 `zh` 分组——同一 `zh` 的几种日文写法视为同一指称、同一粒度（遠坂／トウサカ／父坂 → 远坂），组内以**转写里出现最多的写法**为规范写法，其余写法在 `ja.srt` 里整串替换成它；`zh` 不同的写法（シロウ 士郎 vs エミヤシロウ 卫宫士郎）不互换。借 ADR-0014 规则一的纪律：落点不得是更长表内写法的一部分；单字写法不替换。报告每部改动 cue 数、单元 CER 前后、改好／改坏／无影响、人名命中率（参考里含表内规范写法的单元中候选也含该写法的比例，执行者定义并写明）、有害率（改坏 cue／改动 cue）。
- **C3b Flash-Next 判定版（GPU：1 个 Strata session，与 HF III 建表共用）**：提示 `ja-names-v1`：给出按实体分组的全部 high 写法，任务是“只把转写里听错的专名片段换成表里的写法，别的字一个不动”，输出 `{id: 文字}` 只列有改动的 cue；包、邻文、采样、seed、守卫同 v14 §4.3。**程序约束**：对每个改动算 before→after 的字符 diff，只有当所有被替换／插入的片段都是表内写法、且 diff 之外的字符逐字相同时才采纳，其余整条回退并计数（`rejected_not_table`）。报告同 C3a，再加提议数、采纳数、回退数、每包耗时、墙钟、显存／内存峰值。Opus（`opus`，只读）抽 30 条改动（改好／改坏各半）写一句错误类型，≤$3。
- **C3 与 v14 C2 v2 对比**：同一张表（HF II）下三者的 Δ编辑并列；HF III 因表不同只列新表数字并注明。
- **C3 翻译影响（条件触发，票据 05，GPU 6 run，裁判 ≤$15）**：触发条件——C3a 或 C3b 在两部电影的单元 CER 都不升且有害率 ≤10%。取其中 Δ编辑更好的一个变体的 `ja.srt`，用产品翻译配方 `q2-degrade-v1`＋同一张 Q3 表（ADR-0019／0022 的产品路径，`kototoki.translate`），seed 20261054–56 各翻一次；对照是同 seed 下对照 `ja.srt` 的翻译，本轮新生成。配对裁判 `v5-asr-pairwise-v1`：全体与 exact／light／heavy 各桶 Δ、人名错误（`asr10` 口径）、不一致率、critical／addition、交付失败、墙钟。只判文本不同的单元，相同按 Δ＝0 计。结论写“非劣／改善／变差”（用 v13 §4.5 的 CI90 写法），不设进产品的门。

### 4.4 顺序与关系

- 01（A3 离线＋Opus）→ 02（A4 GPU）；03（B1）独立；04（C3：建表＋C3a＋C3b＋Opus）→ 05（翻译影响，条件触发）→ 06 结题。GPU 票据互斥，CT2／torch 作业与 Strata 不同时跑。
- A、B 不叠加（v14 §4.4 的叠加只在两者都要进产品时做，本轮都没到那一步）。

## 5. 判定纪律、预算与停止条件

- 判定纪律、资源互斥、Strata 启停核对全部同 v14 §5（`Get-Process`、`.local/gpu.lock`、内存 ≥52 GiB、`--plan` 下载 0、专家区 `ram`、`--stop` 后核实显存释放）。转写、参考、校正输出、被标记窗口文字都不进 Git 与日志。
- **预算上限**（GPU run：一次 worker 整批或一次 Strata session 记 1）：

  | 票据 | GPU run | 其他 |
  | --- | --- | --- |
  | 01 A3 规则扫描 | 0 | Opus ≤$3（被标记窗判读，可与 02 合用） |
  | 02 A4 动作比较（align 批） | ≤2 | — |
  | 03 B1 两条规则 | ≤2 | — |
  | 04 C3（HF III 建表＋C3b 一个 session）、Opus 抽看 | ≤2（预计 1） | Opus ≤$3 |
  | 05 C3 翻译影响（两臂 × 3 seed，条件触发） | ≤6 | 裁判 ≤$15 |
  | 06 结题 | 0 | — |
  | **合计** | **≤12** | **≤$21** |

  某票据超限，用已有数据写结论。
- **停止条件**：A3 没有任何规则在全部样本上零误报 → A4 只跑 doc-default 的三种动作（结论写“保守安全网”）；C3a 与 C3b 在两部都不降或有害率 >10% → 05 不跑；Strata 建 HF III 表 5 次都不合格 → C3 两部都用 27B 旧表并在 §8 注明。
- **不做的事**：
  - 换 ASR 模型或 checkpoint；改 VAD 参数、onset／offset 或分窗；改 MMS 对齐；对正常窗口重解码或温度回退；多次解码再挑选；
  - C3b 开思考、`response_format`、换模型或量化、调 Strata 引擎参数；C3 之外的自由改写（v14 C 已量过，不再跑）；表之外的替换；
  - 改 `kototoki/`（除非 §8 第 2 项预批准票据 07）、任何 ADR、基线身份、`experiments/quality_v5/` 与 `experiments/asr_robustness_v14/` 的既有脚本（只导入；v14 的 bug 修复允许但要写进 §7）；开封确认集；
  - 跑 `cross`、`x0`；05 之外的翻译；新增方向（想法写进 §8）。
- 无人值守：中途不请求用户裁定，需要裁定的事集中写进 §8。

## 6. 执行载体与记录协议

- tracker：`.scratch/asr-robustness-v15/{spec.md,map.md,issues/NN-*.md}`，按 [tracker 约定](../agents/issue-tracker.md)。票据清单：

  | NN | 票据 | 臂 | GPU |
  | --- | --- | --- | --- |
  | 01 | A3：w0 产物盘点、四信号与重复检测器、规则候选的标记统计、Opus 判读被标记窗 | A | 0 |
  | 02 | A4：置空／折叠／补解三种动作的官方 CER；产品化草案写 §8 | A | ≤2 |
  | 03 | B1：`fill --rule doc-default`、`fill --rule whisper-or`，官方 CER 与删除／插入分解 | B | ≤2 |
  | 04 | C3：HF III Q3 建表；C3a 规则替换；C3b Flash-Next 表内替换；单元 CER、人名命中、有害率；Opus 抽看 | C | ≤2 |
  | 05 | C3 翻译影响（条件触发）：两臂 × 3 seed，配对裁判 | C | ≤6 |
  | 06 | 结题：§7.1、§8、索引登记 | — | 0 |
  | 07 | （仅 §8 第 2 项预批准时）A 守卫实现进产品：新配方 id、`fail_window` 路径、配方 hash 测试、HF III 验收、ADR-0023 草稿 | A | ≤1 |

- 代码放 `experiments/asr_robustness_v15/`（新包，带 README 与离线测试，接 `just experiments-test`）。只导入 `experiments.asr_robustness_v14.*`、`kototoki.asr_whisper`、`kototoki.workers.{asr,align,protocol}`、`kototoki.strata`、`kototoki.names`、`kototoki.translate`（05）、`kototoki_eval`、`experiments.quality_v5.asr_source`、`experiments.scene_batching_v6.asr10`。
- 产物根目录 `.local/asr-robustness-v15/<票据编号>/`；B1 产物按 v14 入口落在 `.local/asr-robustness-v14/03/`，本文引用即可。
- 每完成一张票据，依次做：票据写 Answer 并 resolved；map 的 Decisions-so-far 加一行；本文 §7 加一行；提交 Git（本文、`docs/research/INDEX.md`、`experiments/asr_robustness_v15/`）。签名失败不绕过，记在 §8 第 0 项。
- 结题时在[调研索引](INDEX.md)的时间线加一行。产品化与 ADR 只在 §8 提出（票据 07 除外）。

## 7. 进度与结论

（执行者填写：每张票据一行，含日期、提交、测试结果、GPU 数字；最后写 §7.1。）

### 7.1 结论

（执行者填写：A 给出选中的规则＋动作与产品化草案；B 与 C3 给数字与解读；回答 §3 的四个问题。）

## 8. 待用户裁定

开跑前须定：

1. **立项与预算**：按 §5 立项，上限 GPU 12 run、Opus 与裁判 $21。
2. **是否预批准票据 07**（A 守卫实现进产品，改 `kototoki/workers/asr.py` 与 `kototoki/recipes.py`，起草 ADR-0023）。建议：**否**，先看 01／02 的选型结果再批；若批准，执行者在 02 结束后按 §4.1 草案直接实现并走 HF III 验收，ADR 仍由用户裁定后落稿。
3. **B1 的裁定口径**：执行者只报“两部各降多少编辑、插入涨多少、每部多少 GPU 秒”，用户据此决定进不进产品；若用户想要一个预设的最低值，请在此写明。
4. **C3 的翻译影响阶段（票据 05）**是否要做：6 GPU run、裁判 ≤$15，只在 C3 两部都不升时触发。建议：做。
5. **HF III 改用 Q3 建表**（与 HF II 同口径，顺手补 v14 §8 第 8 项）。建议：是。
6. **重开 ADR-0014 研究线的范围**：仅限本轮 C3（日文转写侧、表内写法替换、以表的 `zh` 分组定指称）；中文侧替换（ADR-0019 已删）不重做。

结题后须定（执行者在结论里给出建议）：

7. A 是否进产品（配方 id、ADR-0023、验收片）；B 是否进产品；C3 是否进产品（阶段位置应在 `names` 建表之后、`translate` 之前，是新阶段还是并入 `names`）。

执行中产生的裁定项由执行者追加在下面（第 0 项留给提交签名问题）。

## 附：执行提示词（粘贴到新 session）

```text
按 docs/research/2026-11-10-asr-robustness-v15.md 无人值守执行第十五轮（v15）。先读该文"先读"一行列出的文件。开始前把本文状态改为 planned，并在 docs/research/INDEX.md 的"决定与探索时间线"加一行"2026-11-10：用户裁定立项 v15"（§8 第 1–6 项按用户批示填写裁定结果）。
授权：本轮 GPU 作业——票据 02、03 的 CT2／torch worker 作业，票据 04（与 05，若触发）的 Strata 启停（strata launch --plan / strata launch --no-tui --model iq3_s / strata launch --stop）与产品翻译配方——与 ≤$21 的 Opus 判读、抽看和配对裁判，预算以文档 §5 为上限。不得运行 strata update，不得进行任何会下载文件的 launch（--plan 下载量不为 0 时停下，写进 §8）；不得启动 llama-server；不得下载任何模型权重。
规则：中途不问我，需要裁定的事写进 §8；按 §6 的记录协议逐票据提交；每张 GPU 票据开跑前用 Get-Process 核实没有 llama-server、Strata 或其他 GPU 作业，读 .local/gpu.lock，不抢占、不杀进程、不关我的程序；Strata 开跑前确认可用内存 ≥52 GiB，启动后确认专家区全部锁进内存，退到 mmap 就停下写进 §8，结束后 strata launch --stop 并核实显存释放。判据、预算与"不做的事"以文档为准，不自行修改。不改 kototoki/（票据 07 未预批准）、ADR、基线身份与 experiments/quality_v5/、experiments/asr_robustness_v14/ 的既有脚本；不换模型、不改 VAD 参数、不做多次解码再挑选。子 agent 用 Agent 工具显式指定 model（默认 sonnet，复杂设计或统计升级 opus，不用 Fable）。
完成标准：§7 每张票据有一行；§7.1 给出 A 的选型与产品化草案、B 与 C3 的数字与解读，回答 §3 的四个问题；§8 列出待裁定项与建议；调研索引时间线登记结题行。
```
