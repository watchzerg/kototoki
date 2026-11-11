# 12 ASR 候选第二轮

Status: resolved
Type: research
Blocked by: 11

## 范围

- 先调研（只读、联网搜索）2026-10-05 之后发布的日语 ASR 候选，列表、许可、原生接口、显存估计，写进执行记录。
- 按研究文档 §3 下载预授权条件筛选（许可允许本地使用、单模型 ≤ 10 GB、累计 ≤ 30 GB、显存 ≤ 16 GB），最多 3 个候选自行下载到 `.local/models/`，依赖放独立 `.local/envs/` 环境，不改根环境与 lockfile；超出条件的只记录。
- 然后按 `experiments/asr_candidates/README.md` 的流程：短窗 GPU 资格确认 → 两部整片 → 同一评分器 CER，与当前 w0／x0 并列。

## 完成标准

- 候选列表与筛选依据；每个候选的 CER、墙钟、显存；是否超过 w0／x0。是否换基线写入研究文档 §8 待用户裁定。

## 文件所有权

`experiments/asr_candidates/` 扩展；研究文档。下载按预授权条件，不改根环境。

## 执行记录

- 2026-10-16 claimed。调研委派 sonnet 子 agent（只读联网），本会话再用 HF API 逐个核对许可、revision 与文件大小。结论：
  - 2026-10-05 之后没有新的实质性日语开放权重 ASR，只有已有模型的格式转换（GGUF／ONNX／CoreML）。Qwen 官方仍只有 Qwen3-ASR 0.6B／1.7B。
  - 第一轮之后值得测的是动漫／游戏语音领域微调。作者自报的视觉小说语音 CER（`efwkjn` BENCH.md 与各模型卡；不是电影，不能直接预测本片排名，第一轮 Cohere／Granite／Nemotron 已有前车之鉴）：

    | 候选（revision） | 许可（HF API） | 下载 | 接口 | 自报证据 | 预授权 |
    | --- | --- | ---: | --- | --- | --- |
    | `jaykwok/Qwen3-ASR-1.7B-JA-Anime-Galgame-hf`（`368788ce…`） | apache-2.0 | 4.14 GB | 同 x0（Transformers Qwen3-ASR） | 作者 800 条小测：12.85% 对基础 1.7B 14.37%；Nekopara 28.0 → 22.8 | 通过 |
    | `litagin/anime-whisper`（`22e2008a…`） | mit | 3.03 GB | Transformers Whisper（kotoba-whisper-v2.0 蒸馏底座） | 5 部未训练视觉小说平均 13.0% 对 large-v3 16.5%；会转写语气声与喘息 | 通过 |
    | `efwkjn/whisper-ja-1.5B`、`-760M`、`whisper-ja-anime-v0.3`、`cohere-asr-ja`（及 CT2 转换 `TransWithAI/whisper-ja-1.5B-ct2`） | **无声明** | 1.5–4.9 GB | Whisper／Cohere | BENCH.md 上最好（nekopara 21 对 large-v3 62） | **不通过**：许可无法核实，只记录 |
    | `neosophie/Qwen3-ASR-1.7B-JA` | apache-2.0 | 4.09 GB | 同 x0 | 无公开 CER | 通过，但无证据，不选 |
    | `kotoba-tech/kotoba-whisper-v2.0` | apache-2.0 | 1.52 GB | Transformers Whisper | 自报不如 large-v3（18.8 对 16.5） | 通过，但是 anime-whisper 的底座，不重复 |
    | reazonspeech-nemo-v2、parakeet-tdt_ctc-0.6b-ja | apache-2.0／cc-by-4.0 | 2.5 GB | NeMo | 自报在动漫语音上不如 large-v3 | 通过，不选 |
    | Fun-ASR-Nano-2512、Voxtral-Mini-4B | apache-2.0 | 2.0／8.9 GB | FunASR／Transformers | BENCH 上弱 | 不选 |

  - 选 2 个（预授权上限 3 个、累计 7.2 GB）：Qwen3 动漫微调（与 x0 同接口，测领域微调能否改善 x0）、anime-whisper（Whisper 家族里唯一许可清楚的动漫领域模型）。第 3 个名额不用：剩余通过条件的候选都没有优于 large-v3 的证据。
- 2026-10-16 做法：`experiments/quality_v5/asr_round2.py` 在 01 产品 w0 工作目录的同一份 `vad.json` 窗口上逐窗独立转写（Qwen 复用产品 `kototoki.asr_qwen.QwenAsr` 只换 checkpoint；anime-whisper 用 Transformers FP16 greedy、`no_repeat_ngram_size=5`、无初始 prompt），写产品形状 `asr.json`，再用产品 `kototoki.workers.align` 对齐、`kototoki_eval` 评分，与 01 的 w0／x0 并列。依赖用根 `.venv` 已有的 transformers 5.19（不装新包，不建新环境）。下载脚本 `.local/quality-exploration-v5/12/download.py` 按固定 revision 下载到 `.local/models/asr-candidates-v5/` 并写 ready manifest（全部文件 SHA256）。
- 2026-10-16 下载：hf_xet 通道停滞（60 s 内 0 KB），停掉后设 `HF_HUB_DISABLE_XET=1` 走 HTTPS 重下，约 7 MB／s。`asr-candidates-v5/qwen3-asr-anime-galgame-hf`（3.9 GB）与 `anime-whisper`（3.03 GB，11 文件），ready manifest 含全部文件 SHA256。本轮累计下载 7.2 GB（≤30 GB）。
- 2026-10-16 短窗资格确认（II 前 8 窗，GPU 前核对：无 python／llama 进程、无 gpu.lock、显存 296 MiB）：
  - Qwen3 动漫微调：CUDA BF16，峰值 4531 MiB；人名明显更好（"セイバー" 对 w0 的 "セイマー"，"佐倉"）；第 4 窗生成循环到 4096 token 上限，按产品规则置空记失败窗，8 窗耗时 231 s（循环窗占大头）。
  - anime-whisper：CUDA FP16，峰值 1498 MiB，8 窗 7 s；但第 5 窗（约 30 s 长窗）前半句后幻觉出无关整句（"中を見ることはできません。今回の建物の到来…"），第 4 窗只出 "…っ!"，模型卡说明训练数据是短句，长窗是风险。
  - 两个都能在本机原生 Windows＋CUDA 跑通，进入整片。
- 2026-10-16 整片：`12/run_candidate.sh`，两部 → 产品对齐 worker → `kototoki_eval`；先 anime-whisper 后 Qwen 微调。
- 2026-10-16 整片结果（`12/run-log.txt`、`12/runs/*/eval-*.json`；对齐 94／100 s，全部退出码 0）：

| 路线 | II CER（S／D／I） | III CER（S／D／I） | 可测 II／III | ASR 墙钟（两部） | 显存峰值 | 失败窗 |
| --- | --- | --- | --- | --- | --- | --- |
| w0（01 产品） | **16.81%**（876／676／260） | **13.77%**（777／444／342） | 645／690 | 323 s | 5265 MiB（整卡） | 0 |
| x0（01 产品） | 18.27%（1105／645／220） | 14.99%（1005／485／212） | 622／672 | 903 s | 5420 MiB（整卡） | 0 |
| anime-whisper | 29.42%（1346／1392／434） | 25.35%（1226／968／684） | 565／594 | 146 s | 1498 MiB（分配） | 0 |
| Qwen3 动漫微调 | 21.71%（1030／1054／257） | 20.29%（915／1118／271） | 606／598 | 7766 s | 4534 MiB（分配） | 13＋20 |

  - anime-whisper：窗内措辞常比 w0 准（"際限" 对 w0 "再現"、"マトウ・サクラ"），但 9／195 个长窗输出不到 w0 的一半，删除翻倍，插入也多（转写语气声、喘息——模型卡写明的特性，参考字幕不收）。
  - Qwen3 动漫微调：替换比 x0 少（II 1030 对 1105、III 915 对 1005），人名更准；但 33 个窗口（II 13、III 20）生成循环到 4096 token 上限，按产品规则置空，这些窗口里 x0 原有 390／633 字，因此删除大增；循环窗多是安静或情绪化片段（抽泣、笑声、"…"），每个约 200 s，使墙钟变成 x0 的 8.6 倍。即使把这些字全部按 x0 算回，II 约 18.1%、III 约 14.8%，也只与 x0 持平，仍不如 w0。
- 2026-10-16 参考 SRT 复核：HF II `8366d17a…`、HF III `7c778cbd…` 未变。

## Answer

**两个候选都不如当前 w0（也不如 x0），不建议换基线。** 调研结论是 2026-10-05 之后没有新的实质性日语开放权重 ASR；在 §3 预授权条件下选了两个动漫领域微调，在产品同一窗口、同一对齐与评分器上整片比较：

| 路线 | II CER（S／D／I） | III CER（S／D／I） | 可测 II／III | ASR 墙钟（两部） | 显存峰值 | 失败窗 |
| --- | --- | --- | --- | --- | --- | --- |
| w0（01 产品） | **16.81%**（876／676／260） | **13.77%**（777／444／342） | 645／690 | 323 s | 5265 MiB（整卡） | 0 |
| x0（01 产品） | 18.27%（1105／645／220） | 14.99%（1005／485／212） | 622／672 | 903 s | 5420 MiB（整卡） | 0 |
| anime-whisper | 29.42%（1346／1392／434） | 25.35%（1226／968／684） | 565／594 | 146 s | 1498 MiB（分配） | 0 |
| Qwen3 动漫微调 | 21.71%（1030／1054／257） | 20.29%（915／1118／271） | 606／598 | 7766 s | 4534 MiB（分配） | 13＋20 |

- anime-whisper（MIT）在 ≤30 s 长窗上漏句与幻觉，CER 高约 12 pp。
- Qwen3 动漫微调（Apache-2.0）替换少、人名准，但在安静／情绪化窗口生成循环（33 窗触顶），既丢字又慢（ASR 7766 s）；不加循环防护时不可用，即使理想化也只到 x0 水平。
- 作者自报 BENCH 上最强的 `efwkjn/whisper-ja-*`／`cohere-asr-ja` 没有声明许可，按预授权条件未下载，只记录；是否接受这类许可不明的权重归用户裁定（写入研究文档 §8）。
- 成本：下载 7.2 GB；GPU 约 2 小时 20 分（Qwen 微调占 2 小时 10 分）。

## Comments

- 2026-10-16 建票。
