# 首轮 STT demo 模型资产与可恢复下载

状态：资产获取已完成；七组模型与配套文件均已通过内容身份核验  
最后更新：2026-10-04  
范围：模型获取、来源冻结、完整性与离线文件准备；不代表 GPU 推理或质量评测已经通过。

## 冻结来源

2026-10-04 访问各模型卡及 Hugging Face 固定 revision 的 `?blobs=true` API。
获取程序为 `experiments/provision/acquire_models.py`，仅使用 Python 标准库。
每个模型的 API 原始快照保存在 `.local/manifests/model-<名称>-source.json`；
完成清单保存在 `.local/manifests/model-<名称>.json`，记录每个文件 URL、大小、
本地 SHA256、上游 LFS SHA256 或 Git blob、来源以及下载/复用方式。
`complete: true` 表示资产核验完成，不能据此推断模型能够正确运行。

| 本地目录名称 | 发布者与模型 | 固定 revision | 主权重大小（字节） | 许可 |
| --- | --- | --- | ---: | --- |
| faster-whisper-large-v3 | [Systran/faster-whisper-large-v3](https://huggingface.co/Systran/faster-whisper-large-v3) | `edaa852ec7e145841d8ffdb056a99866b5f0a478` | 3087284237 | MIT |
| qwen3-asr-1.7b-hf | [Qwen/Qwen3-ASR-1.7B-hf](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf) | `bcd2b5b7f32b480ab5790554cfa8347f246a14f3` | 4076193080 | Apache-2.0 |
| qwen3-forcedaligner-0.6b-hf | [Qwen/Qwen3-ForcedAligner-0.6B-hf](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf) | `c07281df297b9905d24a508279258cccf987a064` | 1835545960 | Apache-2.0 |
| wav2vec2-large-xlsr-53-japanese | [jonatasgrosman/wav2vec2-large-xlsr-53-japanese](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-japanese) | `cf031e020336460d15a417eba710bbc5bb43be9a` | 1271531927 | Apache-2.0 |
| crisp-qwen3-asr-1.7b-f16 | [cstr/qwen3-asr-1.7b-GGUF](https://huggingface.co/cstr/qwen3-asr-1.7b-GGUF) | `674df5d44b50a63e7102a18895ed20e3f91de301` | 4704800576 | Apache-2.0 |
| crisp-qwen3-forced-aligner-0.6b-f16 | [cstr/qwen3-forced-aligner-0.6b-GGUF](https://huggingface.co/cstr/qwen3-forced-aligner-0.6b-GGUF) | `1ec5110602ccab18c878ddebedab0891e290a95c` | 1841707200 | Apache-2.0 |
| crisp-silero-v6.2.0 | [ggml-org/whisper-vad](https://huggingface.co/ggml-org/whisper-vad) | `9ffd54a1e1ee413ddf265af9913beaf518d1639b` | 885098 | MIT |

主权重 SHA256：

| 文件 | SHA256 |
| --- | --- |
| CT2 `model.bin` | `69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1` |
| Qwen HF ASR `model.safetensors` | `2db53c7d81bd9b8cbc6a074e89be2c968a0d373fb4ee68bb1b1e14f7042dfee1` |
| Qwen HF FA `model.safetensors` | `00568245ceca5af1991d28562a75fe1ddc9bfeb041c27fda66947ea05c47fb86` |
| 日语 CTC `pytorch_model.bin` | `4f6821dcd79770fcd4c11487c4ee5c040b3a7e1863425224014ba5ea8fbc1b67` |
| Crisp ASR `qwen3-asr-1.7b-f16.gguf` | `ac6c58f9cb0f2bb22290319cde01b0e25a2c1f1ee69aa2f1a9265f29a8bfc9d7` |
| Crisp FA `qwen3-forced-aligner-0.6b-f16.gguf` | `35bd243939212f675652d36de061bedf09daee9a7af2a866f47e57be148a8578` |
| Crisp VAD `ggml-silero-v6.2.0.bin` | `2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987` |

## 转换与接口边界

Systran 模型卡记录其来源为 `openai/whisper-large-v3`，CT2 转换保存 FP16。
运行时精度仍须由 backend 记录，文件 FP16 不证明实际算子采用 FP16。
Qwen `-hf` 模型卡记录 Transformers 原生接口；`processor_config.json`、
tokenizer、chat template、配置及权重必须来自同一固定 revision。
旧 non-HF wrapper 的配置与权重不能因为名字相似而替代当前 `-hf` 文件。

Crisp 的 GGUF 模型卡记录由 non-HF Qwen checkpoint 转换、未再训练；模型卡未冻结
原始转换所用 checkpoint revision。当前清单冻结的是发布后的 GGUF 字节身份。
原生 HF 与 GGUF 来源家族相同并不证明张量逐一等价，仍需实测对照。
日语 CTC 模型卡要求 16 kHz，记录微调语料 Common Voice 6.1、CSS10、JSUT；
本轮只取 PyTorch 权重，不获取另一套 Flax 权重。

## 已核验的本地复用

首轮之后按用户要求扩大盘点，Subtitle Edit中large-v2、Whisper anime.ja、Qwen动漫Q8等
额外候选也已核验，采用外部只读路径登记而非重新下载；见
[Subtitle Edit 模型复用](2026-10-04-subtitle-edit-model-reuse.md)。以下七组清单保持首轮历史范围不变。

- CT2 的全部运行文件从本机 Hugging Face 缓存中的同一固定 revision 读取，
  先按上游内容身份验证，再复制至项目 `.local/models/faster-whisper-large-v3`，
  复制后再次验证。原缓存没有被修改。
- Crisp ASR f16 从本机 Subtitle Edit 的 CrispASR 模型目录读取；Crisp FA f16 从
  相邻 `subtitle-edit-fix/models/diagnostic` 读取。两者均经当前固定 revision 的
  LFS SHA256 核验，复制后再次核验，避免约 6.55 GB 重复网络下载。
- Crisp Silero v6.2.0 的 885098 字节文件由固定 URL 下载并经上游 SHA256 核验。
- 本机旧 Qwen non-HF ASR 是不同分片、不同大小；旧 FA 内容身份也与当前 HF FA
  不同。它们未被冒充为当前 HF 模型，不跳过所需下载。

## 下载与恢复入口

在仓库根目录、根项目 uv 环境已就绪后执行：

```powershell
uv run --no-sync python experiments/provision/acquire_models.py
```

此命令固定顺序为 CT2、Qwen HF ASR、Qwen HF FA、日语 CTC、Crisp ASR、Crisp FA、
Crisp VAD。已经存在且核验通过的文件可直接复用。只恢复某条路线可多次传入
`--only`，例如：

```powershell
uv run --no-sync python experiments/provision/acquire_models.py --only qwen3-asr-1.7b-hf --only qwen3-forcedaligner-0.6b-hf --only wav2vec2-large-xlsr-53-japanese
```

不完整文件保留为同目录 `*.partial`。恢复使用 HTTP `Range`；必须返回正确起点
的 `206 Content-Range`，拒绝静默从头覆盖。每次传输最多尝试 5 次，退避为
5/10/20/40 秒，连接读取超时 90 秒。完成后核对字节数及上游内容身份，再改为正式文件名。
若完整文件发生 hash 不符，会保留问题文件并报错，需要诊断来源后另行处理，
不会把它写入完成清单。模型获取不加载 GPU、不访问私有媒体，也不启动推理。
某个模型重试耗尽后，程序保存 `model-<名称>-failure.json` 并继续其他已选模型，
最后以非零退出码报告未完成项；恢复仍按单个文件的部分数据续传。

2026-10-04 已实际中断 Qwen HF ASR 下载并保留约 230 MB 部分文件，重新启动后
HTTP Range 恢复成功，后续累计字节数持续增长，没有重新从零下载。
早期单连接吞吐约 1–1.5 MiB/s，仅为下载观测，不是推理性能。

本轮为了尽早验证 WhisperX，随后将 HF ASR 暂停于 1043333120 字节，先获取日语 CTC。
用户授权尝试同一文件的有限并行 Range 后，新增 `experiments/provision/range_models.py`。
它保留现有顺序下载的前缀，按剩余字节分成 2–4 个互不重叠区间；每段独立保存，
恢复时必须验证准确的起止范围与总长度，最终按顺序拼接并核验完整上游 SHA256。
仅在完整核验后写正式权重和模型完成清单。分块状态位于
`.local/downloads/models/<模型名>/range-state.json`；不能同时用顺序下载命令改写同一模型前缀。

CTC 的双连接 16 MiB/连接探针实际传输 33554432 字节，18.25 秒，合计 1.75 MiB/s，
高于之前约 1.25 MiB/s 的单连接观测，因此保留双连接方案继续传输；后续短时合计
约 2.7 MiB/s。该结果只证明此次网络传输有收益，不能作为稳定网络速率保证。
探针文件会继续续传，不重新获取已有字节。CTC 原顺序前缀 325058560 字节保持不变。
CTC 的后续正式双连接传输新增 912918935 字节，耗时 306.953 秒，平均 2.836 MiB/s；
最终拼接得到 1271531927 字节且通过上游完整 SHA256 核验，相关模型清单已标记完成。
之后在同一 HF ASR 文件上用 4 连接、每连接 16 MiB 探针实际取得 67108864 字节，
26.609 秒，合计 2.405 MiB/s；相对该文件早先约 1.2 MiB/s 单连接有收益。
本轮继续采用 4 连接恢复 HF ASR；两种连接数的观测来自不同文件和时段，未据此宣布
普适最优连接数，也未继续网络参数全排列。
HF ASR 的后续正式四连接传输新增 2965751096 字节，耗时 655.735 秒，平均
4.313 MiB/s。最终拼接得到 4076193080 字节且通过上游完整 SHA256 核验。
最后 HF FA 四连接传输新增 1835545960 字节，耗时 311.594 秒，平均 5.618 MiB/s；
全文件大小与 SHA256 核验通过，processor/tokenizer/chat template 等也已核验。

七组资产最终合计 16844694989 字节，清单索引
`.local/manifests/model-assets-index.json` 中 `all_ready: true`。运行清单
`.local/manifests/model-download-run.json` 已标记完成；当前没有活动的模型下载。
原部分前缀和分块文件仍保留用于审计与恢复，不计入上述正式资产大小。
资产完成只消除了模型获取的阻塞；GPU、整片稳定性与质量证据由实验运行记录负责。

恢复已创建的分块下载（读取原状态和原区间）：

```powershell
uv run --no-sync python experiments/provision/range_models.py --model wav2vec2-large-xlsr-53-japanese --connections 2
```

离线获取逻辑验证入口：

```powershell
uv run --no-sync python experiments/provision/test_acquire_models.py
uv run --no-sync python experiments/provision/test_range_models.py
```

已通过 5 项小型合成数据检查：正确续传、拒绝忽略 Range 的响应、拒绝损坏权重、
验证普通 Git blob 文件、重复核验保留原获取来源。真实本地复制与真实网络续传也有
上述清单/部分文件证据。
另有 2 项离线分块检查通过：完整拼接保留原前缀且核验全文件 SHA256、拒绝不准确的
Content-Range。测试曾暴露极短模拟传输在 Windows 计时粒度内耗时为零，已修复统计除零；
真实网络探针不受该测试计时问题影响。

所有资产与清单保留在 Git 忽略的 `.local`。模型本身不提交到 Git；实验使用入口
由 README 和对应后端的 demo 文档说明。
