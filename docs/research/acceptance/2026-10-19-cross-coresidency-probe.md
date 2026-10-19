# cross 模式 T0：Whisper 与 Qwen 同进程共驻显存探针

状态：concluded（2026-10-19）  
范围：[增量说明 `cross-asr-judge`](../../changes/cross-asr-judge.md) §2.1 的流程形态与显存阈值、§5 的 T0 标准；票据 `.scratch/cross-asr-judge/issues/01-t0-coresidency-probe.md`。用户授权的 GPU 作业：同一进程加载产品 `kototoki.asr_whisper.WhisperAsr`（CT2 FP16）与 `kototoki.asr_qwen.QwenAsr`（BF16 SDPA），不加载 MMS 或其他模型，不调用 `python -m kototoki` 或 `kototoki.workers.*`。  
产物：`.local/quality-exploration-v5/cross-coresidency-probe/`（`samples.csv`、`summary.json`、`judge-hf-ii.jsonl`、`judge-hf-iii.jsonl`、`console.log`、`model-cache.json`），Git 忽略  
代码：[`experiments/quality_v5/coresidency_probe.py`](../../../experiments/quality_v5/coresidency_probe.py)，测试 `experiments/quality_v5/test_coresidency_probe.py`

## 结论

- **采用共驻**：整卡峰值 10688 MiB（含桌面，空闲 2001 MiB），加 1 GB 余量为 11712 MiB，低于 13.5 GB（13824 MiB）阈值，余 2112 MiB；按十进制 GB（13.5×10⁹ B＝12875 MiB、余量 954 MiB）也通过，余 1233 MiB。三段式回退不需要。
- **无 DLL／CUDA 问题**：先 `import torch`，再 `kototoki.asr_whisper`（torch → ctranslate2 → faster_whisper），再 `kototoki.asr_qwen`（transformers）；两模型常驻约 23 分钟，跑完两部 402 个窗口与 1084 个分歧区间的打分，无异常、无 OOM、无失败窗口，控制台只有 torch 的 `Redirects are currently not supported` 提示。进程里同时加载了 torch 的 `cudnn64_9.dll`（9.19）与 CT2 自带的 `cudnn64_9.dll`，与 `asr_whisper.py` 文件头记录的已接受状态一致。
- **共驻不改变转写结果**：两部全部窗口的 w0 与 x0 文本与 v5 第 1 步单独运行的 `asr.json` 逐窗口相同（195／195、207／207，两路都是）。
- **与设计假设不同、需要在 T5／T6 注意的两点**（只陈述数据）：窗口口径下两路规范化后相同的窗口只有 10%（41／402），不是研究单元口径的"约一半"，打分量没有减半，但打分本身两部合计只有 40.5 s；改为 x0 的区间占分歧区间的 18.5%（200／1084），而 §5 写的预期是"约 6–10%"，研究单元口径下 Whisper 单独裁判是 473／1253＝37.7%，探针落在两者之间（口径见"裁判统计"）。

## 环境与前置核对

| 项 | 值 |
| --- | --- |
| 硬件与驱动 | RTX 5080 16303 MiB，WDDM，驱动 617.42 |
| 软件 | Python 3.13.16，torch 2.11.0+cu128（CUDA 12.8，cuDNN 9.19.0），ctranslate2 4.8.3，faster-whisper 1.2.1，transformers 5.20.1，tokenizers 0.23.3，numpy 2.5.4 |
| 运行时间 | 2026-10-19 05:09:14–05:32:40 UTC（约 23.4 分钟） |
| 前置核对 | 启动时脚本以 `Get-CimInstance Win32_Process` 核对：没有其他 python／llama-server 进程，`nvidia-smi` compute 列表里没有 python／llama，没有 `.local/gpu.lock`。准备阶段另一个会话在跑离线 `tests/core` 单元测试（不占 GPU），探针启动时已经结束 |
| GPU 锁 | 运行期间持有 `.local/gpu.lock`（产品 `kototoki.job.ProcessLock` 格式，`job` 为 `cross-coresidency-probe`），结束后已释放（`gpu_lock_released: true`，文件已不存在） |
| 工作树状态 | 运行时工作树里有并行票据（T3／T4）未提交的产品改动：`kototoki/asr_whisper.py` 新增 `WhisperAsr.score`（探针没有调用，打分用研究脚本 `WhisperScorer` 的同一路径）、`kototoki/recipes.py` 新增 `CROSS`、`kototoki/plan.py` 的 `model_files` 改写（探针用它取 w0、x0 的模型文件清单）。`transcribe`、`generate`、`features` 与 `W0`／`X0` 配方没有改动，转写结果与单独运行逐窗口相同 |
| 采样 | 旁路线程每 0.5 s 调用 `nvidia-smi --query-gpu=memory.used`，按当前阶段打标签，共 2567 个样本；每个阶段开始时 `torch.cuda.reset_peak_memory_stats()`，结束时读取 `max_memory_allocated`／`max_memory_reserved`（CT2 的显存 torch 统计不到） |

## 输入与身份核对

| 项 | HF II | HF III |
| --- | --- | --- |
| 工作目录 | `.local/quality-exploration-v5/01/out-w0/.work/8d2f3e76dd0c/` | `…/fb2e0da74018/` |
| PCM SHA256（`kototoki.workers.gpu.read_wav`） | `ee4e2da3…604f`，等于基线 | `e8e841fd…3ab6`，等于基线 |
| `vad.json` SHA256（`read_input_artifact` 核对上游 PCM） | `029e3cf9…61e5` | `36fa7131…a3be` |
| 窗口数／音频时长 | 195／7028 s | 207／7325 s |

模型目录按产品 `kototoki.config.DEFAULTS` 解析（`.local/models/faster-whisper-large-v3`、`w0-assets`、`qwen3-asr-1.7b-hf`），加载前用产品 `plan.model_files` 与 `workers.gpu.verify_models` 逐文件核对 SHA256，13 个文件全部等于产品期望值（`model.bin` `69f74147…`、`mel_filters.npz` `7450ae70…`、`model.safetensors` `2db53c7d…`，完整清单在 `summary.json`）。适配器 `metadata`：Whisper `cuda`／`float16`；Qwen `Qwen/Qwen3-ASR-1.7B-hf` revision `bcd2b5b7…`、`bfloat16`、`sdpa`。

## 各阶段整卡峰值与 torch 峰值

整卡值含桌面（空闲阶段 1983–2001 MiB，比设计 §2.1 记的 0.5–1.5 GB 高）。torch 列为空表示该阶段 torch 的 CUDA 尚未初始化（Whisper 的显存全部在 CT2 里，torch 统计不到）。

| 阶段 | 墙钟 s | 样本 | 整卡峰值 MiB | 整卡最低 MiB | torch 峰值分配 MiB | torch 峰值保留 MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| idle（加载前） | 3.0 | 6 | 2001 | 1983 | — | — |
| import（torch、ctranslate2、faster_whisper、transformers） | 18.5 | 33 | 2021 | 1964 | 0 | 0 |
| verify-models（SHA256） | 5.0 | 9 | 2138 | 2002 | 0 | 0 |
| load-whisper | 4.9 | 8 | 3595 | 2221 | 0 | 0 |
| load-qwen | 5.0 | 8 | 9906 | 5995 | 3888 | 3892 |
| hf-ii ① w0 转写 | 214.9 | 389 | 10462 | 9606 | 3888 | 3892 |
| hf-ii ② x0 转写 | 472.9 | 867 | 10471 | 9594 | 4124 | 4662 |
| hf-ii ③ Whisper 打分 | 19.3 | 35 | 10657 | 10464 | 3937 | 4662 |
| hf-iii ① w0 转写 | 159.7 | 292 | 10645 | 10440 | 3897 | 4662 |
| hf-iii ② x0 转写 | 475.8 | 872 | 10443 | 10432 | 4124 | 4662 |
| hf-iii ③ Whisper 打分 | 21.7 | 40 | **10688** | 10434 | 3934 | 4662 |
| after-free（释放 Qwen 后，只剩 Whisper） | 3.0 | 6 | 5848 | 5843 | 9 | 62 |

- 两模型常驻、推理期间整卡在 9594–10688 MiB 之间；减去空闲 2001 MiB，进程本身约 8.7 GB。设计 §2.1 按单独峰值相加估的"约 11.5 GB"偏保守。
- 峰值出现在打分阶段：Whisper `align()` 用 CT2 显存，打分时编码复制成批（torch 张量，最多 16 条）。
- 释放 Qwen（`del`＋`gc.collect()`＋`torch.cuda.empty_cache()`）后 torch 保留降到 62 MiB，整卡回到 5848 MiB；比刚加载完 Whisper 时（3595 MiB）高约 2.2 GB，是 CT2 推理期间缓存分配器增长的部分加上 torch 的 CUDA 上下文。三段式回退里"只有 Whisper"的阶段大约是这个水平。
- Qwen 适配器自己记录的 `peak_allocated_bytes` 4323945984（4124 MiB）、`peak_reserved_bytes` 4888461312（4662 MiB），与上表 x0 阶段一致；研究期单独打分为分配 4229 MiB、整卡 6945 MiB。

## 加载与墙钟

| 项 | HF II s | HF III s | 合计 s |
| --- | ---: | ---: | ---: |
| import torch | | | 4.1 |
| import `kototoki.asr_whisper`（ctranslate2、faster_whisper） | | | 1.5 |
| import `kototoki.asr_qwen`（transformers） | | | 12.8 |
| 加载 `WhisperAsr` | | | 4.9 |
| 加载 `QwenAsr` | | | 4.5 |
| ① w0 转写全部窗口 | 214.9 | 159.7 | 374.6 |
| ② x0 转写全部窗口 | 472.9 | 475.8 | 948.7 |
| ③ Whisper 打分 | 19.2 | 21.2 | 40.5 |
| ①＋②＋③ | 707.0 | 656.7 | 1363.7 |

- 对照 swr 回归里单独运行的 asr 推理墙钟（w0 133.4／174.6 s，x0 424.4／459.5 s）：本次 w0 II 慢 81 s、III 快 15 s，x0 慢 11%／4%。II 的 w0 是进程里第一次 CT2 解码，含 sm_120 PTX JIT 冷启动（`asr_whisper.py` 记录约 27 s）；其余差异来源没有分离（可能是 CPU 负载或共驻本身），未验证。
- 三步合计约为单独 w0 推理（308 s）的 4.4 倍；设计 §7 的估算是 3.8 倍（约 1226 s）。打分 40.5 s 与研究同量级（研究 Part A 两部 89.8 s，且跨度不同），满足 §5"打分墙钟与研究同量级"。

## 裁判统计（窗口级，m −1，无长度项）

规则与设计 §2.2 一致：规范化后相同的窗口取 w0、不打分；其余窗口用 `asr_pair_oracle.disagreement_intervals` 求区间，hyp_w＝w0 窗口原文，每区间一个只替换该区间的 raw hyp_x；一窗一次 encode，hyp_w 与全部 hyp_x 同批 `align()`（`sot_sequence` 前缀，CT2 自动接 `<|notimestamps|>`），分数＝Σ log `text_token_probs`；d > −1 取 x0，各区间独立判定后一起应用；合并为空而 w0 非空时保持 w0。逐窗口决定（两路原文、区间、score_w／score_x／d／决定、合并文本）写在 `judge-<film>.jsonl`，供 T6 产品验收对照。

| 项 | HF II | HF III | 合计 |
| --- | ---: | ---: | ---: |
| 窗口 | 195 | 207 | 402 |
| 规范化后相同（不打分） | 26 | 15 | 41（10.2%） |
| 打分窗口 | 169 | 192 | 361 |
| 分歧区间 | 537 | 547 | 1084 |
| 含多个区间的窗口 | 134 | 143 | 277 |
| 单窗最多区间 | 10 | 9 | — |
| 打分序列（去重） | 706 | 739 | 1445 |
| 改为 x0 的区间 | 98（18.2%） | 102（18.6%） | 200（18.5%） |
| 有改动的窗口 | 75 | 79 | 154 |
| d 中位数 | −4.27 | −3.81 | — |
| raw 回退规范化文本 | 0 | 0 | 0 |
| 空结果守卫触发 | 0 | 0 | 0 |
| w0／x0 失败窗口 | 0／0 | 0／0 | 0／0 |
| 打分失败窗口 | 0 | 0 | 0 |

- 单窗区间数加 hyp_w 都不超过 16，没有触发分批。
- 与研究不同的地方：研究是 cue 并集单元（平均更短）、跨度外扩 0.2 s，1253 个区间里 Whisper 单独裁判改了 473 个（37.7%）；这里是 ≤ 30 s 的 VAD 窗口整窗打分，区间更少、改动比例约一半。§5 写的"约 6–10%"与研究数字也对不上，T6 判读这一条时需要先确认预期口径。本探针不算 CER。

## 自动检查

- `experiments/quality_v5` 全部 101 项测试通过（原 95 项＋新 6 项：阈值两种口径与边界、阶段样本归属与每阶段 torch 峰值重置、失败／相同窗口不打分、多区间独立判定后一起应用与 m 边界、空结果守卫）。`-t .` 与不加 `-t` 两种 discover 方式都通过。
- 运行时断言：PCM SHA 等于基线；`vad.json` 上游 PCM 一致；模型文件 SHA256 等于产品期望值；`text_token_probs` 长度等于文本 token 数（`WhisperScorer._align`）；raw 合并结果规范化后必须等于 `compose` 拼接结果，否则退回规范化文本（未触发）。
- 共驻结果与单独运行结果逐窗口相同（见结论）。

## 未验证

- 只跑了一次；峰值的重复性、桌面占用变化（本次空闲约 2.0 GB）对余量的影响没有测。共驻余量 2.1 GB 是按今天的桌面占用算的。
- 墙钟差异（II w0 慢 81 s、x0 慢 4–11%）的来源没有分离：没有在同一时刻单独跑一次 w0／x0 对照。
- 产品 `WhisperAsr.score`（T3 新增）没有在这次作业里调用；它与探针所用打分路径的等价性只靠读代码，没有数值对照。
- 产品 worker 路径（`kototoki.workers.asr` 的 cross 分支、jobs、产物写出）没有跑；本探针用研究脚本的打分器在产品适配器上拼装。
- 三段式回退没有实测，只记录了释放 Qwen 后"只剩 Whisper"的整卡残留（5848 MiB），没有重新加载。
- 没有算 CER，没有听音核对改动；窗口口径改动比例与研究、与 §5 预期的差异留给 T6。
- WDDM 显存换出（共享内存）行为没有单独观察；本次峰值远低于 16 GB，未见换出迹象，但没有采集共享显存计数。
