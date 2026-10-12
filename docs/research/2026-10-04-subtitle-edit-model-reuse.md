# Subtitle Edit 已有模型复用清单

状态：本地资产核验完成；未新增模型推理或改变首轮结论  
日期：2026-10-04  
范围：用户要求优先复用 Subtitle Edit 下载资产，并检查规划候选是否需要预下载。

## 结果与下载决定

已在 `C:/Users/watch/AppData/Roaming/Subtitle Edit/` 找到并核验14个STT/aligner主权重，
合计33,177,547,393字节，全部大小及SHA256与发布仓库固定revision的LFS身份一致。
CT2目录现有配置/tokenizer/词表也按上游Git blob或LFS身份核验，全部一致。
本轮只获取小型上游元数据，没有下载、复制、移动或改写这些大权重，也没有改Subtitle Edit环境。

规划优先候选的权重已经齐备，因此本次不启动新的大文件下载。后续直接采用登记的只读外部路径，
推理前再次校验hash；需要隔离修改配置时应另建项目副本，不能在Subtitle Edit目录就地打补丁。
模型资产可复用不等于当前Kototoki适配器无需修改或GPU质量已经通过。

## 优先复用资产

CT2根目录为 `SpeechToText/Purfview-Faster-Whisper-XXL/_models/`，GGUF根目录为 `CrispASR/models/`，
均相对上述Subtitle Edit目录。大小为主权重的十进制GB。

| 本地资产 | 大小 | 发布仓库与固定revision | 用途 |
| --- | ---: | --- | --- |
| `faster-whisper-large-v2/` | 3.087 | [Systran/faster-whisper-large-v2](https://huggingface.co/Systran/faster-whisper-large-v2/tree/f0fe81560cb8b68660e564f55dd99207059c092e) | 规划内large-v2候选，CT2配套运行文件齐全 |
| `faster-whisper-large-v3/` | 3.087 | [Systran/faster-whisper-large-v3](https://huggingface.co/Systran/faster-whisper-large-v3/tree/edaa852ec7e145841d8ffdb056a99866b5f0a478) | 与首轮已用模型字节身份相同，无需新增副本 |
| `faster-whisper-anime.ja/` | 0.768 | [quantumcookie/anime-whisper-ct2-int8](https://huggingface.co/quantumcookie/anime-whisper-ct2-int8/tree/7e132355e4f7f15640efe9bdebe13ee55fafe02e) | Whisper日语动漫微调的INT8 CT2转换，非large-v3同权重量化 |
| `qwen3-asr-1.7b-ja-anime-q8_0.gguf` | 2.507 | [cstr/qwen3-asr-1.7b-ja-anime-GGUF](https://huggingface.co/cstr/qwen3-asr-1.7b-ja-anime-GGUF/tree/1906c1f812b598d5e9dae091c79656d73b41ec28) | 已安装的Qwen日语动漫候选；已补足以前未完成的上游hash核验 |
| `qwen3-asr-1.7b-q8_0.gguf` | 2.507 | [cstr/qwen3-asr-1.7b-GGUF](https://huggingface.co/cstr/qwen3-asr-1.7b-GGUF/tree/674df5d44b50a63e7102a18895ed20e3f91de301) | 基础Qwen量化对照，低于动漫候选优先级 |
| `qwen3-asr-1.7b-f16.gguf` | 4.705 | 同上revision | 首轮已经校验并复制使用，不重复获取 |
| `qwen3-forced-aligner-0.6b-q8_0.gguf` | 0.986 | [cstr/qwen3-forced-aligner-0.6b-GGUF](https://huggingface.co/cstr/qwen3-forced-aligner-0.6b-GGUF/tree/1ec5110602ccab18c878ddebedab0891e290a95c) | 可选FA量化对照；已有FA f16，不为预取同时改变ASR与FA |

`anime.ja`来源由本机Subtitle Edit源码的实际下载定义解析，并由当前发布文件身份确认。
用户原标签`1.7b-amine-q8_0`仍保留；根据已安装文件，最可能对应上述Qwen `ja-anime`，
这项映射不等同用户另行确认，也不默默替换原标签。

Whisper动漫CT2目录已含model/config/tokenizer/vocabulary/preprocessor五个文件。上游还有五个
HF辅助JSON，本地未包含；当前CT2运行资产不因缺少这些额外文件而判为损坏，也未为此重下权重。
Subtitle Edit源码另有该转换的alignment heads兼容处理；未来词级时间实验必须核对它与两层decoder
的对应关系，不能只见权重齐全便宣称可直接用冻结large-v3适配器运行。

## 其余核验及格式边界

- Crisp日语CTC Q4_K：`cstr/wav2vec2-large-xlsr-53-japanese-GGUF`
  @`16c3b21fe7858426806f4bf795578497e0b5dad2`，231,505,920字节。
- Crisp Canary CTC Q8：`cstr/canary-ctc-aligner-GGUF`
  @`2b22dc9aff585bc8368a5228173c8afe22c155b7`，666,894,464字节。
  仅登记存在及字节身份，未确定后续日语实验价值或GPU兼容性。
- `SpeechToText/Cpp/Models/anime.ja.bin` 是
  `Aratako/anime-whisper-ggml`@`35b467f144c62a3ab2d84bfbb517d6af5135444a`
  的`ggml-anime-whisper-q5_0.bin`，537,819,875字节；不是CT2模型。
- 同目录`large-v2.bin`及`large.bin`分别匹配
  `ggerganov/whisper.cpp`@`5359861c739e955e79d9a303bcbc70fb988958b1`
  的`ggml-large-v2.bin`、`ggml-large-v3.bin`。`large.bin`的真实身份由hash确认，不凭别名猜测。
- `Qwen3ASR/models/`中的同名f16/q8文件分别为4,705,307,456与3,200,764,736字节，
  匹配`FlippyDora/qwen3-asr-1.7b-GGUF`@`f58b129e5f10f5d45440548b481900a5b3715956`。
  它们与Crisp/cstr同名权重不同，不能交换使用或冒充同一个精度实验。
- 发现的翻译模型、声纹模型和附带处理资产不在本次STT优先预取范围；未因此扩展实验或下载。

首轮官方Qwen HF ASR/FA、PyTorch日语CTC等七组项目资产仍保持原路径、原revision与原清单。
GGUF/whisper.cpp格式不能替代HF safetensors或CT2模型，不因本机存在“同家族”文件而混用。
此前已复用的资产和下载原因见[首轮资产记录](2026-10-04-model-assets.md)。

## 复用登记与证据

- 私有全路径与文件身份：`.local/analysis/subtitle-edit-reuse-r1/catalog.json`。
- 后续候选读取入口：`.local/analysis/subtitle-edit-reuse-r1/reuse-plan.json`；引用现有文件，未建立可被误写的硬链接。
- 各发布者`*-source.json`保留2026-10-04 API原始响应及固定revision；本机扫描见
  `.local/manifests/subtitle-edit-inventory-2026-10-04.json`。
- 本地下载来源依据：相邻`subtitleedit/src/libuilogic/AudioToText/WhisperPurfviewFasterWhisperModel.cs`、
  `WhisperCppModel.cs`及`src/ui/Features/Video/SpeechToText/Engines/`下Crisp/Qwen/aligner定义。
- 原始核验脚本：`.local/analysis/audit-subtitle-edit-models.py`；主体先锁元数据，再只读hash。
  Cpp large与Crisp日语CTC的补充行保留在同一catalog及独立source快照。

当前重查入口已纳入这两组补充，使用新目录以保护旧证据：

```powershell
uv run --locked --offline python .local/analysis/audit-subtitle-edit-models.py --output .local/analysis/subtitle-edit-reuse-r2
```

这里的`uv --offline`限制环境解析，不阻止脚本查询发布者元数据；该资产核查不是离线推理。

后续运行应读取`reuse-plan.json`中的绝对路径，并与catalog的SHA再次核对；Subtitle Edit以后可能
更新其文件，不能假定外部路径永远不变。首轮冻结推理与评分清单未修改，本次没有新增质量样本。
