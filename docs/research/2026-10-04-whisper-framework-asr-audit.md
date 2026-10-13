# WhisperX 与 faster-whisper 的实际识别路径核验

> 2026-10-05 后续开发入口：本文已核验的特征和独立生成逻辑已移植到 [W0 demo](../../experiments/w0_demo/README.md) 的 `asr.py`。修改当前 W0 的 beam、prompt、特征或解码时复用并更新该模块，按 demo 契约做同块回归；本文源码行号和版本保留原核验身份。

状态：源码核验完成；已交叉读取独立冻结分块实测，架构建议见主报告  
最后更新：2026-10-04  
范围：本机 WhisperX 3.8.6、faster-whisper 1.2.1、CTranslate2 4.8.2 的 ASR；日语、CUDA FP16、large-v3、beam 5、batch 1。VAD 与 MMS 细节另见同任务报告。本记录是研究证据，不采用或迁移正式架构。

## 已经能确定的事

WhisperX 没有另一个识别模型，也没有在底层库里藏一套新识别算法。本机代码通过继承 `faster_whisper.WhisperModel`，保留父类模型加载、tokenizer 和提示词构造，然后改用自己的特征提取、分块组织与直接 CTranslate2 生成路径。它绕过标准 `transcribe` 的时间戳推进、温度回退、静音判定和前文管理。这些行为会改变识别结果，不能把旧 W0/W1 差异仅归因于 Pyannote。

原生 `BatchedInferencePipeline` 已提供相近的无时间戳独立分块生成能力。源码足以排除“WhisperX 必须靠修改 CTranslate2 或 faster-whisper 底层才能实现”的说法，但审计阶段不能仅凭源码证明原生 batched API 的默认特征输入与 WhisperX 完全等价。因此本轮进行了[独立冻结分块验证](2026-10-04-whisper-framework-experiment.md)，而不是再跑旧 W0 对旧 W1 的分数。该实验的自研适配层在 17/17 块上复现特征、prompt、生成 token 及结果；标准 API 仅 7/17 块文字相同，原生 batched 为 0/2 个完整窗口文字相同。全文架构建议见[主报告](2026-10-04-whisper-framework-architecture.md)。

## 版本、模型与文件完整性

本次以 `importlib.metadata` 读取实际安装版本，未导入模型或升级环境。W1 环境为 `.local/envs/whisper-latest`：WhisperX 3.8.6、faster-whisper 1.2.1、CTranslate2 4.8.2；W0 环境的后两项相同。运行证据抽查 `.local/results/r2-hf-iii-window-06-w1-a01/result.json`，其中实际 ASR 为 CUDA:0、float16，batch 1、chunk 30、beam 5、`language=ja`、`task=transcribe`、无 initial prompt、prefix 或 hotwords。当前适配器调用位置为 [run.py](../../experiments/whisper/run.py) 第 172–229 行；输入第 36–50 行读取已冻结 mono 16 kHz PCM16 WAV，除以 32768 得 float32。

两条路径加载同一本地资产 `.local/models/faster-whisper-large-v3`，来自 `Systran/faster-whisper-large-v3` revision `edaa852ec7e145841d8ffdb056a99866b5f0a478`。既有获取清单记录 model.bin SHA256 `69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1`；本次没有重新哈希 3 GB 权重。配置实际为 128 Mel、FFT 400、hop 160、16 kHz、30 秒／3000 帧；对应 config 和 tokenizer 字节已经冻结。

对所有带 RECORD 哈希的 `.py/.pyd/.dll` 检查：WhisperX 16 文件、faster-whisper 9 文件、CTranslate2 28 文件，全部匹配，零差异。再只读获取固定 tag 的官方原始源码，在内存逐字节比较：下面五份源码与安装文件全部一致。W0 环境的 faster-whisper 后三份源码 SHA256 也相同。

| 本机文件（均相对 W1 `Lib/site-packages/`） | SHA256；同时匹配 RECORD 与固定 tag 官方源码 |
| --- | --- |
| `whisperx/asr.py` | `f25d2dfd0cfcbcb6cd2850ba213bf715f92d4369401274e534557448876da565` |
| `whisperx/audio.py` | `b37154608b33369e7ca516862ef2fa0d0bd1e095fa5dd63a2a9014bf5f96ed36` |
| `faster_whisper/transcribe.py` | `5d5ffb00018561d3d529b2c72e1d9f5fff055bea725f3cccc7c6c67f5cc8ffe4` |
| `faster_whisper/feature_extractor.py` | `e403966dbc592a53695eea2aea24fa60bab50ef6755e0076b311f907be7a397c` |
| `faster_whisper/tokenizer.py` | `614a96b6a9660096e4f4e9fbe8860cd75ad250dce8e85a847998a3d6d48165d2` |

CTranslate2 本机 `_ext.cp313-win_amd64.pyd` SHA256 为 `9450d14d9f1e5d7d1d09ce2dd035ccf4121c82d3f2ae22d8f0e1cb7063c3cd29`，`ctranslate2.dll` 为 `34ff1eeefef2330f8abe777ae12b2238718e04503ad6e3bc9b6c9cb5be9fd274`，均匹配安装 RECORD。这是安装后未改动的证据；没有把本机二进制重新编译并对照官方发布二进制，RECORD 本身也不是独立供应链认证。

搜索本机 WhisperX 包对 `faster_whisper`／`ctranslate2` 的引用，识别边界仅见继承、导入和 API 调用，没有发现 monkey patch。结合源码字节比较，当前 ASR 差异来自流程覆写，不能称为底层库 fork。项目已有 CTC patch 属于另一边界，不能混入 ASR 结论。

## 三条路径逐项差异

以下源码缩写都指本机已安装且已核验的文件：`WX` = `whisperx/asr.py`，`WA` = `whisperx/audio.py`，`FW` = `faster_whisper/transcribe.py`，`FE` = `faster_whisper/feature_extractor.py`。行号来自本机文本，官方网页渲染可能折叠空行，因此复核以本机行号和固定 tag 文件为准。

| 项目与源码位置 | 标准 `WhisperModel.transcribe` | 原生 `BatchedInferencePipeline` | WhisperX 自定义路径 | 影响、直接实现难度与证据 |
| --- | --- | --- | --- | --- |
| 模型加载：WX 31、357–364；FW 630–721 | 加载 CT2 模型及 tokenizer | 复用传入的同一 WhisperModel | 继承父类，只换生成与 encode 包装 | 无新增模型或底层权重改造；保留同资产、精度即可。已有 W0/W1 CUDA 实测及源文件核验。 |
| 外部分块：WX 213–235；FW 394–451 | 使用 clip 秒数或自身窗口推进；内置 VAD 是 Silero 路线 | 支持外部 `clip_timestamps=[{start,end}]` 秒数，每块原样裁剪，不自动重新合并 | Pyannote cut/merge 后，每块裁剪首尾间完整连续音频 | 原生 batched 能消费冻结 Pyannote 块；不能改用其内置 Silero 再称公平。VAD 块与源坐标是必须维护的契约。 |
| 长块：WX 159–166；FW 438–443、514–515 | 会继续窗口推进 | 超 30 秒警告，并只取首 3000 Mel 帧 | 依赖上游 cut/merge 保证块长；负 padding 不补齐，也没有在这里再切长块 | 校验 `0 < samples <= 480000` 不能省略。块长越界可能截断或 batch 堆叠失败；少量代码但验证成本中等。 |
| 补齐、特征：WA 140–158；FE 198–230；FW 463–515 | 一次提取整个音频 Mel，再裁剪窗口、补 Mel；全音频 log floor 的范围也不同 | 每块 NumPy STFT；先补 160 波形采样，再去末 Mel 帧、补／裁 Mel 到 3000 | 波形先补零到恰好 480000，再 Torch STFT；去末 STFT 帧，128 Mel | Mel 补零与补零波形后算 Mel 不同，末端边界也不同；小实现不代表可跳过声学验证。需同块特征差与文字实测。 |
| 时间源坐标：WX 215–218、284–285；FW 428–450、134–139 | 原生时间 token／词级时间，按 clip 和 seek 推进 | 外部块按 `int(seconds*16000)` 裁剪，保存块 offset、duration | 同样整数裁剪，输出块边界 round 到毫秒 | MMS 输入不能换成标准 ASR 子段或重排全文；保留整数样本边界与历史毫秒输出，迁移成本低但易出现累计偏移。 |
| 固定语言／任务：WX 365–366、236–254；FW 507–512 | 用户可固定 ja/transcribe | 可固定 ja/transcribe | 当前固定 ja/transcribe | 三者复用 FW Tokenizer；显式 `without_timestamps=True` 的同块诊断提示为 `[50258,50266,50360,50364]`。标准 API 默认和旧 W0 使用时间戳，不含该 no-timestamps 提示。当前固定日语无需语言检测；未开启翻译。 |
| 每块语言检测：WX 393；FW 212–220 | `multilingual=True` 实际每窗口检测 | 同字段实际每块检测并换 language token | 默认 options.multilingual 为 true，但生成函数没有使用此字段；当前 tokenizer 已固定 ja | 参数名相同不等价。原生 batched 迁移应显式 `multilingual=False` 保持日语。源码已确认；当前无自动混语功能收益证据。 |
| 初始提示／prefix／hotwords：WX 47–58；FW 182–191、1532–1565 | 初始提示加空格；prefix 仅首次 seek；前文受 conditioning 管理 | initial_prompt 原样 encode；hotwords 使用；prefix 存入 options 但该生成函数未传给 get_prompt | 每块重新构造固定提示，initial_prompt 加空格，prefix/hotwords 都调用父类 | 当前全部 None，故不构成实测差异。将来启用需定义语义并测试；直接 copy 提示构造较小，不需重写 tokenizer。 |
| 前文：WX 45–58；FW 547、1372–1383 | 真正由 `condition_on_previous_text` 控制跨窗口文本 | 强制存为 false，调用参数不能启用它 | 每次生成 all_tokens 清空；`condition_on_previous_text` 字段未读 | 当前 W0 无前文和两种独立块都关闭；状态管理简单，重要的是不要声称可用未执行的开关。 |
| 生成参数：WX 62–74；FW 222–236、1446–1458 | beam 或 sampling/fallback；可 `max_new_tokens` | 单次 CT2 generate：beam、patience、length/repetition/no-repeat、suppress、首个 temperature、max_new_tokens | 单次 CT2 generate：beam、patience、length/repetition/no-repeat、suppress；忽略 max_new_tokens、temperature/best_of | 当前同 beam5、patience1、penalty1、no-repeat0。WX 不是“batch 大才生效”：batch1 仍走不同流程。适配参数白名单成本低。 |
| 温度／异常文本回退：WX 37–93、378–383；FW 1402–1530、528–532 | 真正按 compression/logprob 触发温度阶梯；静音会停止回退 | 只取首个 temperature；没有阈值回退 | temperatures、compression/logprob 阈值虽有默认值，却没有生成回退 | 不能把标准 transcribe 的功能当成 WX 有效优化。保持 W1 应先复制单次 beam，新增回退另开实验；识别长尾是否改善尚不能推断。 |
| 静音判定：WX 62–93、381；FW 1215–1235 | request no_speech 并按阈值跳过窗口 | request no_speech 仅输出，未按阈值过滤 | 不 request no_speech，不按该字段过滤 | 当前依赖外部 VAD；误判静音、音乐或低声仍是覆盖风险。原生 batched 的字段不自动增加静音过滤。 |
| 抑制 token：WX 70、387；FW 536–539、1886–1907 | Python 把 -1 展开并追加特殊 token | 同标准解析 | 原样传 [-1] 给 CT2，由模型 config 展开 | 本次本地 CPU 核验：CT2 config suppress_ids 与 FW 解析均为 88 个，集合完全一致。这个表面差异在当前模型已消除；未来 checkpoint 必须重验。 |
| 时间戳：WX 55、388、87；FW 283、776、1034–1099 | W0 原有时间 token、word timestamps 改变分段与推进 | 无时间戳提示，但后处理仍调用 `_split_segments_by_timestamps`；word 可选 | 无时间戳提示，解码前过滤所有 token >= eot，再直接取 VAD 块时间 | 对当前无时间 token 输出，batched 一块一段；异常特殊／时间 token 时后处理未必一致，须记录 token trace。直接适配输出映射很小。 |
| 原生词级时间：FW 161–170、1280 附近 | W0 已使用；底层 Whisper attention/DTW | 可选，当前目标应关闭 | 本路径不做原生 word 时间，转交外部 CTC | MMS 同实现比较应都关闭 native word timing，不把两套时间机制混入同一比较。 |
| HF 包装与状态：WX 106–195、256–296 | 无 Transformers Pipeline 包装 | 无该包装 | Torch DataLoader + Transformers PipelineIterator；批后重置 tokenizer／suppress numerals | 包装提供调度便利，未发现额外文字修复。某些临时状态恢复不在 finally；失败后的重用需加固。序列号、取消与清理仍要产品自己维护。 |

## 底层默认值中已经排除的伪差异

1. WhisperX 省略 `sampling_temperature`，CT2 默认 1；原生 batched 默认首温度 0。CT2 4.8.2 `src/decoding.cc` 第 974–979 行在 `sampling_topk==1` 或温度 0 时都选择 `BestSampler`；两者当前 topk=1、beam5，不应把这项单独解释为随机采样差异。
2. `suppress_tokens=[-1]` 在 CT2 4.8.2 `src/models/whisper.cc` 第 282–288 行读模型 `config["suppress_ids"]`，不是“没有抑制”。本机与 FW 展开集合完全相同。
3. no-timestamps prompt 会使 CT2 不添加 timestamp 规则处理器（同文件第 301–311 行）。所以 WX 未传 `max_initial_timestamp_index`、原生 batched 也未传、标准 API 默认传 50 的差异，在正常当前 no-timestamps 提示下不构成时间限制收益。但提示并不等于在包装层绝对拒绝所有异常特殊 token，输出仍须验证。
4. `max_length=448` 是传入上限，CT2 同文件第 267–275 行实际搜索长度为 `min(total_max_length/2, total_max_length-start_step)`，即当前不超过 224 个生成步骤。这是共用 CT2 的隐含约束，不是 WX 的扩大识别能力。密集日语／不良循环可能耗尽上限；不能把块内未转写尾部仅归为 VAD 漏检。

## 维护含义与最小验证缺口

需要保留的是“冻结 VAD 原音频块 → 明确的波形／Mel 契约 → 固定日语无时间戳单次 beam → 同一原文与原块窗口交给 MMS”。这是一组有限流程，源码可完整描述；真正困难的是边界行为的验证，包括 30 秒约束、特征补齐、token 上限、误 VAD 的内容损失和源坐标。继承与直接 CT2 调用本身没有发现难以自行维护的新增识别算法。

审计提出的最小问题是：未修改的标准 API、原生 batched 与精确特征／生成适配层，在同一冻结块是否保留 W1 文本。独立实验现已补齐该问题：两片各 300 秒、共 17 块，适配层 17/17 特征逐元素、prompt、有效 kwargs、token、完整 segment 严格相同；标准 API 仅 7/17 块全文相同，原生 batched 为 0/2 完整窗口全文相同。本审计通过读取 `summary.json`、`analysis.json` 与实验代码核对这些断言，GPU 推理由独立实验执行，不是本审计另跑。它支持在所测固定配置下去除 ASR 框架依赖，同时保留适配契约；未证明所有输入／版本等价，也未通过单变量消融证明文字差异全部由 Mel 导致。两路给同一 MMS 的文本／搜索窗相同属于输入契约证据，本轮没有新增两次 MMS 推理。

新增适配层不意味着摆脱 Torch、Pyannote 或 Transformers：相同 Pyannote 与 MMS 仍需要它们。移除 WhisperX 可能减少 PipelineIterator、NLTK、pandas 与其依赖约束的耦合，但不能把旧 W0 的 24 包与 W1 的 104 包直接当作目标 A/B 部署成本；两边目标都有三个模型组件。WhisperX 本机 metadata 对 Torch／torchaudio `~=2.8.0`、torchvision `~=0.23.0`、torchcodec `<0.8.0` 和 hub `<1.0.0` 的约束，是实际维护边界；自行集成仍需维护相同底层 GPU 兼容性与弃用接口。

## 官方来源与最新版本边界

访问／比对日期均为 2026-10-04。

- [WhisperX v3.8.6 ASR](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/asr.py)、[audio](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/audio.py)：逐字节与上述本机源文件相同。
- [faster-whisper v1.2.1 transcribe](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py)、[特征提取](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/feature_extractor.py)、[tokenizer](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/tokenizer.py)：逐字节与本机相同。
- [CTranslate2 4.8.2 Whisper API](https://opennmt.net/CTranslate2/python/ctranslate2.models.Whisper.html)、[固定版本 Whisper C++](https://github.com/OpenNMT/CTranslate2/blob/v4.8.2/src/models/whisper.cc)、[固定版本 decoding C++](https://github.com/OpenNMT/CTranslate2/blob/v4.8.2/src/decoding.cc)：用于默认值和实际搜索行为核验；版本由本机 metadata/RECORD 绑定，未重新编译二进制。
- [WhisperX releases](https://github.com/m-bain/whisperX/releases)、[faster-whisper releases](https://github.com/SYSTRAN/faster-whisper/releases)：本次官方列表最新 stable 仍分别为 3.8.6 与 1.2.1，已测版本就是此次稳定版本基准。
- [WhisperX 3.8.7rc1](https://github.com/m-bain/whisperX/releases/tag/3.8.7rc1) 为 prerelease，发行说明仅列 Windows AMD64 的 uv CUDA 源标记与 Hugging Face hub 约束放宽；[该 tag 配置](https://github.com/m-bain/whisperX/blob/3.8.7rc1/pyproject.toml) 已另查。未运行或安装 rc，不把其环境改进归入本机质量证据；这也不证明 main 开发分支没有其他改动。

相关证据：[架构建议](2026-10-04-whisper-framework-architecture.md)、[独立等价实验](2026-10-04-whisper-framework-experiment.md)、[VAD／MMS 审计](2026-10-04-whisper-framework-vad-alignment-audit.md)、[既有两片实测](2026-10-04-two-film-revalidation.md)、[环境身份](2026-10-04-runtime-inventory.md)、[当前候选边界](../architecture/stt-candidate-pipelines.md)、[Whisper 实验入口与历史身份](2026-10-04-whisper-execution.md)。
