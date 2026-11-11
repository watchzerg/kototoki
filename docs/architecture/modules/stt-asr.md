# STT ASR：w0／x0 引擎、cross 裁判与复读守卫

状态：current；权威决定：[ADR-0003](../../adr/0003-new-pyannote-baselines.md)、[ADR-0012](../../adr/0012-cross-asr-judge.md)、[ADR-0023](../../adr/0023-asr-repeat-guard.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责 asr 阶段的内容：两个推理适配器（w0 = faster-whisper large-v3，x0 = Qwen3-ASR-1.7B-hf）、可选的 `cross` 引擎（同一进程两路转写＋Whisper 教师强制打分裁判）、w0 的整窗复读守卫，以及 ASR 壳 `workers/asr.py` 如何组合它们写出 `asr.json`。

worker 壳的共用规则（jobs、模型核对、身份、写产物、失败分级、日志配置）、VAD 与对齐见 [STT worker](stt-workers.md)。现行引擎取值、`cross` 配方与守卫规则的完整定义见[现行决定](../../adr/CURRENT.md)（"产品 STT 引擎""ASR 复读守卫"两节）；配方常量见[配置、配方与媒体提取](config-and-media.md)。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**引擎与模型键**：`config.engine` 取 `w0`（默认）、`x0` 或 `cross`。加载哪些适配器、读哪些模型键按 `plan.ENGINE_PARTS`：w0 只读 `w0`／`w0_mel_assets`，x0 只读 `x0`，cross 三者都读；`recipe_hash` 分别为 `recipes.W0`、`X0`、`CROSS` 的 hash。`W0` 含 `guard` 块（ADR-0023），`CROSS` 嵌套 `W0` 与 `X0`。

**`asr.json`**（三种引擎同构）：`schema_version`、`engine`、`offset_s`、`input`、`chunks`（照抄 `vad.json`）、`original_segments`（与窗口一一对应：`text`、秒与整数样本、`avg_logprob`）、`asr_traces`、`failed_windows`、保留文本 `text`、`metadata`、`stages`。

- `asr_traces` 是引擎自有的诊断：w0 为 tokens、prompt、解码参数、特征 SHA256，被复读守卫改动的窗口另有 `guard`。
- x0 为 tokens、`generated_tokens`、`token_limit_reached`、原始输出、检测语言、输入设备与形状证据、PCM SHA256 与逐窗耗时。
- 解码抛 `RuntimeError` 的失败窗口 trace 为 `null`。

**ASR w0**（`asr_whisper.WhisperAsr`）：

- 模块顶层先 `import torch` 再 `import ctranslate2`、`faster_whisper`，cuDNN 子库因此来自 torch，CT2 自带的 `cudnn64_9.dll` 与之并存；不设私有 DLL 目录与 PATH。
- 特征链与解码参数同 W0 契约，参数取自 `recipes.W0`；mel 资产 SHA256 不符、模型不在 CUDA float16 上即失败。
- 窗口输入要求整数样本（`schema.validate_windows`）。
- 单窗解码抛 `RuntimeError` 时该窗文字为空、trace 为 `null` 并作为失败窗口返回，壳用 `protocol.fail_window` 记入 `failed_windows`，继续下一窗。

**ASR x0**（`asr_qwen.QwenAsr`），参数取自 `recipes.X0`：

- CUDA BF16、SDPA，加载后整体 `.to("cuda:0")`；原生 `AutoProcessor.apply_transcription_request`（强制日语、16 kHz、不补到 30 s）、greedy、`max_new_tokens` 4096、batch 1、逐窗独立无前文。
- CUDA 不可用、参数或输入张量不在 CUDA 上即失败。
- 触顶（生成 token 数达到 4096）的窗口：段内保留截断文字、trace 照常记录，并以原因 `token_limit_reached: generated <n> tokens` 作为失败窗口返回；壳经 `protocol.fail_window` 把该窗 `text` 置空、截断文字移入 `failed_windows`，不进对齐、cue 与翻译（[技术设计](../../specs/bilingual-subtitle-pipeline.md) §6）。
- 单窗生成抛 `RuntimeError` 的处理同 w0。段结构与 w0 相同，`avg_logprob` 为 `null`。

### w0 复读守卫

[ADR-0023](../../adr/0023-asr-repeat-guard.md)；纯逻辑 `kototoki/guard.py`，壳内 `workers.asr.apply_guard`。w0 转写返回之后、组装文档之前，壳对每个**未失败**的窗口调用 `guard.apply`：

- 规则 `repeat-strict`，在规范化文本（`judge.normalize`：NFKC、去标点与空白）上判定：周期 ≥2 字的单元相邻重复 ≥10 份（同一字符连写按周期 2 计），或 ≥3 字的子串不重叠出现 ≥10 次；且重复部分覆盖该窗规范化文字 ≥50%（覆盖率四舍五入到 4 位小数）。
- 参数在 `recipes.W0["guard"]`，不是配置项。无法规范化的文字（跨簇 NFKC 组合）按不命中处理。
- 折叠（`action: collapse`）：在原文上保留覆盖最多的那段相邻重复的第一个单元，删掉其后各次重复所占的原文区间（含夹在其中的标点），其余照抄。
- 被折叠的段 `text` 换成折叠后的文字，`avg_logprob` 与 trace 里的 tokens 仍是解码原值（因此 tokens 与 `text` 不再对应）。
- 置空（`action: blank`）：折叠后仍命中，或只有非相邻复现命中（没有可折叠的区段）时，该窗作为失败窗口追加，原因 `guard:repeat-strict`，经 `protocol.fail_window` 把原文移入 `failed_windows`、段文字置空，不进对齐、cue 与翻译。
- 两种情况都在该窗 trace 写 `guard = {rule, action, period, copies, removed_raw_chars}`；置空时后三项描述被放弃的折叠，没有可折叠区段时为 `null`／`null`／0。
- 只做后处理：不重解码、不温度回退，不看压缩比与 `avg_logprob`。解码抛错的失败窗口不过守卫。x0 引擎不过守卫。
- 进度行与每文件 INFO 行带守卫改动的窗口数（`guarded_windows`／`N guarded`，折叠与置空都算；进度行的计数由编排抄进运行日志的 `[asr] done` 行）；每个被折叠的窗口一行 WARNING（窗口号、周期、份数、删去字符数），被置空的窗口走失败窗口的 WARNING 行；都不含文字。
- 范围有限：低压缩比的插入套话不在守卫范围（ADR-0023）。

### cross 引擎

`engine = "cross"`（[ADR-0012](../../adr/0012-cross-asr-judge.md)，可选）：同一 asr worker 进程内 w0 与 x0 各转写一遍，再由 Whisper 对两路的分歧区间做教师强制打分并合并，写出与 `w0`／`x0` 同构的 `asr.json`；阶段链不变，align 及之后只看到 `asr.json`。

- **加载**：`models` 同时需要 `w0`、`w0_mel_assets`、`x0`，模型核对两路的全部文件。`start` 按 `ENGINE_PARTS` 次序先加载 `WhisperAsr`（CT2 fp16）再加载 `QwenAsr`（bf16），两者常驻到进程退出，分别记加载耗时；仍先 `import torch` 再导入 CT2。
- **共驻**：产品只有两模型同进程共驻这一种路径，运行时不看显存、不回退。
- **逐文件三步**：① Whisper 转写全部窗口，过复读守卫（同 w0 引擎），得 `asr-w0.json`；② Qwen 转写全部窗口，得 `asr-x0.json`；③ 裁判，得 `asr-judge.json` 与合并结果 `asr.json`。两路共用同一份 `vad.json`，窗口一一对应。
- `compute_cross` 把四个产物作为 `(path, identity, payload)` 序列返回，`gpu.file_processor` 查一次 CUDA 后依次写出三个审计产物、最后写 `asr.json`；中途失败时没有新的 `asr.json`，阶段整段重算。

**裁判**（纯逻辑在 `kototoki/judge.py`：整文件 `judge_file`，单窗 `judge_window`；打分由 `WhisperAsr.score` 提供，经壳作为回调传入）：

1. 两路文本规范化（NFKC，去 Unicode 标点与空白）后做字符级编辑距离对齐，非匹配操作的极大连续段为一个**分歧区间**（相隔至少一个匹配字符才分开）。
2. 每个区间构造两个假设：hyp_w 为 w0 窗口原文，hyp_x 只把该区间按偏移映射换成 x0 原文字符、其余（含 w0 标点）不动；映射失败时两假设一并退回规范化文本。
3. 进入裁判前 x0 原文先经 `judge.clean_x0` 去掉与非 ASCII 字符相邻的空白（两侧都是 ASCII 时保留一个空格；只清 x0，w0 原文不动）。
4. Whisper 教师强制打分：mel 右补零到 30 s，`encode` 只算一次，编码复制成批后调用 `Whisper.align`，`start_sequence` 取 `tokenizer.sot_sequence`，CT2 自动接 `<|notimestamps|>`；分数为 Σ log `text_token_probs`（不含结束符，空文本得 0）；一个窗口的 hyp_w 与全部 hyp_x 同批（hyp_w 只打一次），批上限 16。
5. 判定：d ＝ score(hyp_x) − score(hyp_w)，**d > −1.0 取 x0，否则保持 w0**；没有长度项，阈值是 `CROSS` 配方常量，不是配置项。多个区间各自独立判定，再把全部被接受的翻转一起应用。

**裁判的逐窗规则**（按顺序）：

- w0 窗口失败（含被复读守卫置空）：窗口仍记失败，不以 x0 替代（`decision = w0_failed`）。
- x0 窗口失败（含触顶）：取 w0，不裁判（`x0_failed`）。
- 两路规范化后相同：取 w0，不打分（`identical`）。
- 原文无法规范化：取 w0（`guard = normalize_failed`）；合并结果为空而 w0 非空：保持 w0（`guard = empty_result`）。
- 打分抛 `RuntimeError`／`ValueError`（如 `align` 返回数量不符）：取 w0，记一条 WARNING（只记窗口序号、异常类型与消息），计入 `score_error`，不作为窗口级失败、不中断文件。
- 被守卫折叠的窗口照常裁判，hyp_w 与 `w0_text` 都是折叠后的文字。x0 那一路不过守卫：x0 自己的复读只有在裁判选中它时才会进合并结果。
- 不做：幻觉过滤、叠加 Qwen 或 MMS 分数、长度项。

**产物**：

- `asr.json`：`engine` 为 `"cross"`，`original_segments` 取 w0 的段结构、文字换成合并文本，`asr_traces` 取 w0 的 trace，`failed_windows` 为 w0 的失败窗口。
- `metadata` 为 `{w0, x0, judge}`（两路适配器的 metadata，与裁判配方 id、margin、批上限、文本形式、文件级计数）；`stages` 含 `load_s`、`load_w0_s`、`load_x0_s`、`inference_w0_s`、`inference_x0_s`、`score_s`。
- 三个审计产物写在同一工作目录，不参与 `is_current`（见[产物契约](artifact-contract.md)）：
  - `asr-w0.json`／`asr-x0.json`：各自完整的 `asr.json` 结构，`engine` 分别为 `w0`／`x0`，身份按单引擎计算（只含该路模型文件），可直接用 `kototoki_eval` 评分。
  - `asr-judge.json`：身份同 cross 的 `asr.json`；`offset_s`（照抄 `vad.json`）、`windows`、`summary`。
  - `windows` 每窗口：`index`、`identical`、`text_form`、`guard`、`w0_text`、`x0_text`、逐区间的 `w`／`x`／`kind`／`score_w`／`score_x`／`d`／`switched`、`decision`（`identical`／`judged`／`w0_failed`／`x0_failed`／`score_error`）。
  - `summary`：`windows` 为全部窗口；`identical`／`scored`／`normalized_form`／`intervals`／`switched`／`guards`／`by_kind` 只统计进入裁判的窗口；另有 `w0_failed`／`x0_failed`／`score_error` 与打分墙钟 `score_s`。
- **日志**：进度行另带 `identical`、`intervals`、`switched`、`x0_failed`、`score_error` 计数，运行日志的 `[asr] done` 行照抄；stderr 每文件一行 `[asr] <id>: cross windows N, identical K, intervals M, switched S, x0_failed X, score_error E, guarded G, w0 X.Xs, x0 X.Xs, score X.Xs`，不记窗口文字；两路各自的失败窗口另有 WARNING 行（前缀 `w0 `／`x0 `，只记序号与 reason）。

## 实现设计

壳内一个辅助函数 `workers.asr.transcribe` 承担"转写 → 计时 → 守卫 → 记失败 → 组文档"，单引擎的 `compute` 与 `cross` 的两路都用它；守卫是否生效只在这一处按"这一路是不是 w0"（`plan.ENGINE_PARTS` 的部件名）决定。

`cross` 不新增推理模块，壳 `workers/asr.py` 同时持有 `WhisperAsr` 与 `QwenAsr`，两路的模型身份按 `plan.model_files(..., engine=part)` 拆分。

## 接口与依赖

- `WhisperAsr.score(audio, chunk, texts, max_batch=16) -> list[float]`：对同一窗口音频编码一次，为每个候选文本返回 Σ log `text_token_probs`（不含结束符；空文本得 0 且不送入 `align`；全部为空时不运行编码器；超过 `max_batch` 分批；返回数量不符抛 `RuntimeError`）。
- `kototoki.judge.judge_window(...)`：纯函数，输入一个窗口的两路文本与打分函数，返回合并文本与该窗口的审计记录。
- `kototoki.judge.judge_file(...)`：整文件纯函数，输入两路逐窗文本与各自的失败窗口、打分回调与 `CROSS` 参数，输出合并文本、逐窗记录（`window_record`）与计数；`clean_x0`、`normalize` 也在 `judge`。
- `judge` 属基础层，只依赖标准库，不导入 torch、`experiments`、`kototoki_eval` 与任何推理模块；打分函数由壳传入。
- `kototoki.guard` 属基础层，只导入 `recipes` 与 `judge.normalize`。`guard.RULE` 是规则名加五个参数（取自 `recipes.W0["guard"]`）；`guard.check(text) -> bool` 判断是否命中。
- `guard.apply(text) -> (new_text, record | None)`：未命中返回原文与 `None`；命中返回记录 `{rule, action, period, copies, removed_raw_chars}`，`action` 为 `collapse` 时 `new_text` 是折叠后的文字，为 `blank` 时调用方应把该窗置空（`new_text` 仍是原文）。
- 守卫只处理字符串；改写段文字、写 trace 与失败窗口记账在壳 `workers/asr.py`。

## 代码与验证入口

- 代码：`kototoki/asr_whisper.py`、`kototoki/asr_qwen.py`、`kototoki/judge.py`、`kototoki/guard.py`、`kototoki/workers/asr.py`（共用壳 `kototoki/workers/gpu.py` 见 [STT worker](stt-workers.md)）。
- `tests/core/test_asr_whisper.py`：导入顺序（伪模块）、逐窗失败；`score`（伪模型：按输入顺序累加 log 概率、空文本得 0 且不送入 `align`、分批）。
- `tests/core/test_asr_qwen.py`（伪 processor／模型）：配方生成参数、只取 prompt 之后的 token、触顶窗口保留截断文字并返回失败、`RuntimeError` 窗口、模型不在 CUDA 即失败；经壳串到对齐与 `build_cues`：触顶窗口置空、截断文字进 `failed_windows`、不进 cue；x0 模型文件清单与配方 hash。
- `tests/core/test_judge.py`：规范化、编辑对齐与分歧区间、偏移映射、原文假设与规范化回退、相同窗口不打分、`d > m` 边界、多区间合并、空结果守卫、批切分、数量不符抛错、`clean_x0`、`judge_file` 的逐窗决策（w0 失败优先于 x0 失败、打分出错、窗口记录、计数）；与研究脚本合成样例的结果钉成 sha256。
- `tests/core/test_guard.py`：10 份命中 9 份不命中、覆盖率边界、单字连写按周期 2、标点夹在重复之间时的原文区间、只有非相邻复现或折叠后仍命中即置空、无法规范化不命中、`guard.RULE` 等于配方块、不导入 torch／`experiments`；一组构造文本上的命中与折叠结果钉成 sha256。
- `tests/core/test_stt_workers.py` 的 ASR 部分：
  - 守卫：折叠改写段文字并写 trace、置空进 `failed_windows`、已失败窗口不过守卫、x0 引擎不受影响、cross 的裁判拿到守卫后的 w0 文字而 x0 那一路不过守卫。
  - `cross`：四个产物齐全且身份分别按单引擎／cross 计算、边界 d 保持 w0、偏好 x0 的区间被切换、w0 失败窗口仍记失败、x0 失败窗口取 w0、打分出错与数量不符取 w0 且日志不含文字、w0 那一路之后失败时四个产物都不写、合并结果被对齐消费。
  - 加载：先 Whisper 后 Qwen 并拆分两路模型身份、单引擎只加载自己的部件（`CrossStartupTest`）。
  - 字节：四个 cross 产物与单引擎 `asr.json` 钉成 sha256（`AsrArtifactBytesTest`，`time.perf_counter` 固定）。
- 与研究实现的实时对照在 `tests/equivalence/`（`just test-equivalence`，属 `gate-full`）：守卫 ↔ `experiments.asr_robustness_v15.repeat`、裁判 ↔ `experiments.quality_v5`。
- 打分门禁（真实模型验证，占 GPU，须用户批准，不属于任何测试层与 gate）：`just smoke whisper_score`（`scripts/smoke/whisper_score.py`）；取冻结窗口的前几个 VAD 窗口，产品转写文本的分数须比字符打乱文本至少高 20 nat、空文本恰为 0、每 token 分数与产品 `avg_logprob` 差 < 0.5 nat；规则写在脚本头部。
- 冻结窗口门禁 `stt_frozen_window`／`x0_frozen_window` 见 [STT worker](stt-workers.md#代码与验证入口)。
- 未验证：显存紧张的机器上 `cross` 共驻能否放下（没有回退路径）、w0 失败窗口以 x0 替代（不做）、数值确定性、译文层收益与新材料确认；x0 触顶的真实路径。

## 变更与决策来源

- [ADR-0003](../../adr/0003-new-pyannote-baselines.md)、[ADR-0012](../../adr/0012-cross-asr-judge.md)、[ADR-0023](../../adr/0023-asr-repeat-guard.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)、[现行决定](../../adr/CURRENT.md)
- 研究：[交叉打分](../../research/2026-10-19-asr-pair-cross-score.md)、[v15](../../research/2026-11-10-asr-robustness-v15.md)
- 验收：[cross 共驻探针](../../research/acceptance/2026-10-19-cross-coresidency-probe.md)、[cross 产品路径验收](../../research/acceptance/2026-10-19-cross-asr-acceptance.md)、[两部整片验收](../../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)、[最终验收](../../research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)
- 票据：`.scratch/bilingual-subtitle-pipeline/`（`issues/03-stt-workers.md`、`issues/07-x0-engine.md`）、`.scratch/cross-asr-judge/`、`.scratch/asr-repeat-guard/`
- 计划：[`docs/plans/asr-repeat-guard.md`](../../plans/asr-repeat-guard.md)、[`docs/plans/architecture-cleanup.md`](../../plans/architecture-cleanup.md)
- 历史记录：[模块页拆出的历史记录](../../research/acceptance/2026-11-11-module-page-history-stt-plan-artifacts.md)
- 来源代码：`experiments/w0_demo/asr.py`、`experiments/x0_demo/asr.py`、`experiments/qwen/run_qwen.py`、`experiments/asr_robustness_v15/repeat.py`、`experiments/quality_v5`
