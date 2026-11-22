---
covers:
  - kototoki/judge.py
---
# STT ASR 子页：cross 引擎与裁判

`STT ASR` 的子页：可选 `cross` 引擎的加载、逐文件三步、裁判规则与审计产物。

## cross 引擎

`engine = "cross"`（[ADR-0003](../../../adr/0003-new-pyannote-baselines.md)，可选）：同一 asr worker 进程内 w0 与 x0 各转写一遍，再由 Whisper 对两路的分歧区间做教师强制打分并合并，写出与 `w0`／`x0` 同构的 `asr.json`；阶段链不变，align 及之后只看到 `asr.json`。

- **加载**：`models` 同时需要 `w0`、`x0`，模型核对两路的全部文件。`start` 按 `ENGINE_PARTS` 次序先加载 `WhisperAsr`（CT2 fp16）再加载 `QwenAsr`（bf16），两者常驻到进程退出，分别记加载耗时；仍先 `import torch` 再导入 CT2。
- **共驻**：产品只有两模型同进程共驻这一种路径，运行时不看显存、不回退。
- **逐文件三步**：① Whisper 转写全部窗口，过整窗守卫（同 w0 引擎），得 `asr-w0.json`；② Qwen 转写全部窗口，得 `asr-x0.json`；③ 裁判，得 `asr-judge.json` 与合并结果 `asr.json`。两路共用同一份 `vad.json`，窗口一一对应。
- `compute_cross` 把四个产物作为 `(path, identity, payload)` 序列返回，`gpu.file_processor` 查一次 CUDA 后依次写出三个审计产物、最后写 `asr.json`；中途失败时没有新的 `asr.json`，阶段整段重算。

**裁判**（纯逻辑在 `kototoki/judge.py`：整文件 `judge_file`，单窗 `judge_window`；打分由 `WhisperAsr.score` 提供，经壳作为回调传入）：

1. 两路文本规范化（NFKC，去 Unicode 标点与空白）后做字符级编辑距离对齐，非匹配操作的极大连续段为一个**分歧区间**（相隔至少一个匹配字符才分开）。
2. 每个区间构造两个假设：hyp_w 为 w0 窗口原文，hyp_x 只把该区间按偏移映射换成 x0 原文字符、其余（含 w0 标点）不动；映射失败时两假设一并退回规范化文本。
3. 进入裁判前 x0 原文先经 `judge.clean_x0` 去掉与非 ASCII 字符相邻的空白（两侧都是 ASCII 时保留一个空格；只清 x0，w0 原文不动）。
4. Whisper 教师强制打分：特征同 `transcribe`（Mel 补零到 3000 帧），`encode` 只算一次，编码复制成批后调用 `Whisper.align`，`start_sequence` 取 `tokenizer.sot_sequence`，CT2 自动接 `<|notimestamps|>`；分数为 Σ log `text_token_probs`（不含结束符，空文本得 0）；一个窗口的 hyp_w 与全部 hyp_x 同批（hyp_w 只打一次），批上限 16。
5. 判定：d ＝ score(hyp_x) − score(hyp_w)，**d > −1.0 取 x0，否则保持 w0**；没有长度项，阈值是 `CROSS` 配方常量，不是配置项。多个区间各自独立判定，再把全部被接受的翻转一起应用。

**裁判的逐窗规则**（按顺序）：

- w0 窗口失败（含被整窗守卫置空）：窗口仍记失败，不以 x0 替代（`decision = w0_failed`）。
- x0 窗口失败（含触顶）：取 w0，不裁判（`x0_failed`）。
- 两路规范化后相同：取 w0，不打分（`identical`）。
- 原文无法规范化：取 w0（`guard = normalize_failed`）；合并结果为空而 w0 非空：保持 w0（`guard = empty_result`）。
- 打分抛 `RuntimeError`／`ValueError`（如 `align` 返回数量不符）：取 w0，记一条 WARNING（只记窗口序号、异常类型与消息），计入 `score_error`，不作为窗口级失败、不中断文件。
- 被守卫折叠的窗口照常裁判，hyp_w 与 `w0_text` 都是折叠后的文字。x0 那一路不过守卫：x0 自己的复读只有在裁判选中它时才会进合并结果。
- 不做：幻觉过滤、叠加 Qwen 或 MMS 分数、长度项。

**产物**：

- `asr.json`：`engine` 为 `"cross"`，`original_segments` 取 w0 的段结构、文字换成合并文本，`asr_traces` 取 w0 的 trace，`failed_windows` 为 w0 的失败窗口。
- `metadata` 为 `{w0, x0, judge}`（两路适配器的 metadata，与裁判配方 id、margin、批上限、文本形式、文件级计数）；`stages` 含 `load_s`、`load_w0_s`、`load_x0_s`、`inference_w0_s`、`inference_x0_s`、`score_s`。
- 三个审计产物写在同一工作目录，不参与 `is_current`（见[产物契约](../artifact-contract.md)）：
  - `asr-w0.json`／`asr-x0.json`：各自完整的 `asr.json` 结构，`engine` 分别为 `w0`／`x0`，身份按单引擎计算（只含该路模型文件），可直接离线评分。
  - `asr-judge.json`：身份同 cross 的 `asr.json`；`offset_s`（照抄 `vad.json`）、`windows`、`summary`。
  - `windows` 每窗口：`index`、`identical`、`text_form`、`guard`、`w0_text`、`x0_text`、逐区间的 `w`／`x`／`kind`／`score_w`／`score_x`／`d`／`switched`、`decision`（`identical`／`judged`／`w0_failed`／`x0_failed`／`score_error`）。
  - `summary`：`windows` 为全部窗口；`identical`／`scored`／`normalized_form`／`intervals`／`switched`／`guards`／`by_kind` 只统计进入裁判的窗口；另有 `w0_failed`／`x0_failed`／`score_error` 与打分墙钟 `score_s`。
- **日志**：进度行另带 `identical`、`intervals`、`switched`、`x0_failed`、`score_error` 计数，运行日志的 `[asr] done` 行照抄；stderr 每文件一行 `[asr] <id>: cross windows N, identical K, intervals M, switched S, x0_failed X, score_error E, guarded G, w0 X.Xs, x0 X.Xs, score X.Xs`，不记窗口文字；两路各自的失败窗口另有 WARNING 行（前缀 `w0 `／`x0 `，只记序号与 reason）。

## 裁判与打分接口

- `WhisperAsr.score(audio, chunk, texts, max_batch=16) -> list[float]`：对同一窗口音频编码一次，为每个候选文本返回 Σ log `text_token_probs`（不含结束符；空文本得 0 且不送入 `align`；全部为空时不运行编码器；超过 `max_batch` 分批；返回数量不符抛 `RuntimeError`）。
- `kototoki.judge.judge_window(...)`：纯函数，输入一个窗口的两路文本与打分函数，返回合并文本与该窗口的审计记录。
- `kototoki.judge.judge_file(...)`：整文件纯函数，输入两路逐窗文本与各自的失败窗口、打分回调与 `CROSS` 参数，输出合并文本、逐窗记录（`window_record`）与计数；`clean_x0`、`normalize` 也在 `judge`。
- `judge` 属基础层，只依赖标准库，不导入 torch、研究代码与任何推理模块；打分函数由壳传入。

## 代码与验证入口

- 代码：`kototoki/judge.py`；`WhisperAsr.score` 在 `kototoki/asr_whisper.py`，cross 的壳在 `kototoki/workers/asr.py`（[枢纽页](../stt-asr.md#代码与验证入口)）。
- `tests/core/test_asr_whisper.py` 的 `score`：伪模型按输入顺序累加 log 概率；空文本得 0 且不送入 `align`。
- `tests/core/test_judge.py`：分歧区间的种类与下标、`compose`；原文假设保留 w0 标点、映射失败回退规范化；`d` 恰在边界时保持 w0；相同窗口不打分；单区间记录与多区间合并；空结果守卫；`clean_x0`；`judge_file` 的逐窗决策（identical／judged／w0_failed／x0_failed／score_error）与计数。
- `tests/core/test_stt_workers.py` 的 cross：四个产物齐全且身份分别按单引擎／cross 计算、偏好 x0 的区间被切换、x0 触顶窗口记失败、w0 失败窗口仍记失败且不打分、`failed_windows` 与审计记录正确。
- 测试精简（2026-11-22）后不再有测试覆盖：
  - 裁判：编辑对齐的相邻区间与末尾插入、半角浊音簇映射、两路空文本、批切分与 `max_batch`、数量不符抛错、不可规范化文本保持 w0、`summarize` 计数、与研究脚本合成样例的 sha256 钉子、`judge` 属基础层的导入边界。
  - cross 壳：margin 边界、守卫只走 w0 路径且裁判看守卫后文字、打分出错与数量不符取 w0 且日志不含文字、w0 之后失败则四个产物都不写、先 Whisper 后 Qwen 的加载与两路模型身份拆分、四个 cross 产物与单引擎 `asr.json` 的字节 sha256 钉子、合并结果被对齐消费。
  - `score`：log 概率下限钳位、概率与结果数量不符抛错、编码一次与每批至多 16、起始序列。
- 真实模型验证与未验证项见[枢纽页](../stt-asr.md#代码与验证入口)。
