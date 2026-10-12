# Whisper 框架：冻结 VAD 的最小等价实验

> 2026-10-05 后续开发入口：本文保留同冻结 VAD 的原始对照证据。执行当前 W0 或继续优化流程时复用并更新 [W0 demo](../../experiments/w0_demo/README.md)；独立神经 VAD／MMS 的新增实测见 [demo 验证](../testing/2026-10-05-w0-demo-validation.md)，不把新结果回写为本文已执行的内容。

状态：已完成；支持架构研究的有界行为保留证据，不是正式架构迁移  
最后更新：2026-10-04  
范围：Windows 11／RTX 5080，本机 WhisperX 3.8.6 与 faster-whisper 1.2.1／CTranslate2 4.8.2。

## 可以直接得出的结论

**WhisperX 当前已测识别路径可以由直接使用 faster-whisper 的小适配层保留，
但把它换成未修改的 `transcribe()` 或 `BatchedInferencePipeline` 并不等价。**
同一份冻结 Pyannote score、同一音频分块、同一 large-v3 CT2 权重下，
独立适配层的 17 个块全部与原生 WhisperX 的特征、prompt、生成参数、token、
完整文字、输出分段及平均 logprob 严格相等。
两个窗口的新 WhisperX 输出也与历史 W1 的完整 `original_segments` 严格一致。

这个结论说明当前识别行为具备可复现的替代实现；不说明 17 个块覆盖所有未来
语言、模型、提示词、超长音频及故障条件，也没有证明整个 WhisperX 依赖已可立刻移除。
独立适配层使用了有来源的冻结 Mel filterbank；原型没有独立载入 Pyannote checkpoint，
也没有移植剩余 MMS 桥接基础设施。

## 输入、版本与冻结

实验身份为 `.local/framework-equivalence/v1/`；旧结果及原素材未覆盖。
先验选择两部主参考中按时间最早的 `window-01`，各 300 秒，共 10 分钟。
未按文本、错误或得分筛选窗口。复用 `.local/round2/corpus/manifest.json` 的
16 kHz 单声道 PCM16，原始 FLAC／SRT 不参与写入。

| 输入 | 文件 SHA256 | 源 offset（秒） | 原生 VAD 合并块 |
| --- | --- | ---: | ---: |
| hf-ii-window-01 | `2622236c7c8d7bc8574bc5a73e4a6bf5ec974344b30c452e8df7c7a26536d2eb` | 351.402125 | 8 |
| hf-iii-window-01 | `226a127a7e1c959aa01253f36744f00c4d59ef12502084fe537eede17fd96658` | 366.2666875 | 9 |

实际输入身份及 offset 以私有 `inputs.json` 为权威，正文由该记录核对。
实测 Python 3.13.16、Torch 2.8.0+cu128、Pyannote.audio 4.0.7、RTX 5080 驱动 616.92。
ASR 为 provisioned `faster-whisper-large-v3`，设备 CUDA，FP16，beam5，语言 ja，transcribe，batch1。
模型完整 SHA256、config、安装版本、VAD checkpoint SHA256、Mel asset SHA256、
GPU 采样、当前命令及原型源码身份在 `manifest.json` 和 `wx.json`。
依赖版本没有升级，也没有下载；离线标志与缓存限定在项目内，未做物理断网证明。

Pyannote 只运行一次／窗口，保存 raw score `.npy`、frame grid、精确浮点分块及
构成这些块的语音段；后续 WX／FW 全部使用同一冻结输出。
裁剪遵循 `int(start*16000):int(end*16000)`，保留间隙；输出 start/end 按 WX 四舍五入到
三位小数，MMS 接收这个输出窗口，不能拿圆整后窗口回头代替识别裁剪。

## 三条识别路径

1. 原生 WX：使用原生 `load_model` 与 `transcribe`，GPU VAD 输出冻结后代入，
   捕获实际 preprocess 特征和 CT2 `generate` 参数／token；只用代理观察生成调用。
2. 独立 FW 适配层：新进程仅导入 faster-whisper、Torch／NumPy，重现 WX 的
   30 秒音频零补齐、Torch STFT／Mel、prompt 和 direct CT2 generate；
   `sys.modules` 中没有 `whisperx` 或其子模块。
3. 未修改 FW API 对照：每个同样的块执行标准 `transcribe`，以及通过精确
   `clip_timestamps` 执行 native Batched。都设 ja、beam5、without_timestamps、
   无 VAD、无 word timestamps、温度0；标准 API 显式无 previous conditioning。
   这是诊断对照，不是历史无外部 VAD 的 W0，也不是新质量候选。

生成参数逐项比较的是实际执行调用，不是参数对象里未使用的字段。
WX／适配层均不执行温度回退、no-speech 拒绝或 compression 判断。
输入 token cap 仍为 `max_length=448`；CT2 内部最多生成224 token的限制未调整。
17块实际生成31–80 token，无224触顶；这不证明全片不会触顶。

| 核验项目 | 独立适配层 vs WX |
| --- | ---: |
| 特征逐 bit 相等 | 17/17 |
| prompt 相等 | 17/17 |
| 实际 CT2 kwargs 相等 | 17/17 |
| 生成 token 相等 | 17/17 |
| text、三位小数边界、avg_logprob 整个 segment 相等 | 17/17 |
| 历史 W1 完整 original_segments 相等 | 2/2 窗口 |
| 历史 MMS 实际 align_search_segments 全字典、PCM/file SHA与 offset 相等 | 2/2 窗口 |

标准 API 的同块全文只有7/17相等；native Batched的两窗全文均与WX不同。
两种未修改 API 在本样本得到相同全文，不能扩展成所有分段／时间／失败行为都相同。
追加CPU核验比较了17对特征的实际字节，全部相等，因此表中的“逐bit”有字节检查支持。
沿用项目NFKC／去标点和空白规范化，标准API同块全文变为11/17相等，
II全文差异仍为S/D/I=6/55/3，III为2/0/2；差异并不全是空白或标点。

| 窗口 | WX字符数 | 独立适配层 S/D/I | 标准 API S/D/I | native Batched S/D/I |
| --- | ---: | --- | --- | --- |
| II window-01 | 550 | 0/0/0 | 7/61/9 | 7/61/9 |
| III window-01 | 676 | 0/0/0 | 4/9/24 | 4/9/24 |

这里 S/D/I 是**相对 WX 输出**的单位成本全文编辑差，包含空格和标点，
不是相对真实语音或 SRT 的 CER，不能据此宣布哪个 API 更准确。
没有删去漏字、重复、插入或不可测内容制造等价。
适配层完整文字相等，因而相对 WX 的漏字、重复及分段变化都为零；
对真实日语的既有问题仍然保留，没有因换框架自动修复。

## VAD 后处理独立复现

`vad.py` 重现严格 `>` onset／`<` offset、frame midpoint、超长活动区后半段
最低 score 切点及30秒包络贪心合并；使用 Pyannote 的 timeline，未借用 WX 函数。
两份冻结 raw score 加44个合成／seed20261004随机多轨用例，与安装包的
`Pyannote.merge_chunks` 全部严格一致：46/46。
用例包括75秒连续活动、阈值恰相等、短于0.1秒的活动／间隙及静音。
这也核实 `.1` min-duration 虽在对象配置中声明，却未作用于实际覆盖的 score→merge 路径。

原型对零帧 score 返回空列表，而原生 Binarize 会访问 `timestamps[0]` 抛错；
这是域外额外防护，未包含在46项等价结论中。
VAD checkpoint 的独立加载、内部滑窗执行及未来 Pyannote 变化仍需迁移验证。

## Mel、MMS与证据边界

适配层用的是 WX 安装资产 `mel_filters.npz` 的冻结私有副本，算法及资产来源保留于
`THIRD_PARTY_NOTICES.txt`。faster-whisper 动态生成的128-band矩阵与该资产
最大绝对差 `3.725290298461914e-09`，并非逐 bit 相等。
不能认为两者数值差小就保证生成文字相等；本次使用冻结矩阵保证识别路径相同。
波形补零后 STFT 与短块 STFT 再特征补齐的差异也是需要保留的行为。
本轮没有做分项 GPU 消融将 API 差异全部归因于某一个因素。

**没有新增 MMS GPU 推理。** 两窗在 PCM、offset、识别全文及三位小数窗口上与
既有 `jctc-mms-full-v2` 完全一致；独立适配层的 segment 全字典还与历史 MMS
`native.align_search_segments` 严格一致，实际搜索配置为padding0、nearest。
所以继续调用原有同实现／同配置 MMS 时，
它接收到的输入没有变化。这是输入契约等价的推论，不是独立 aligner 移植的运行证明。
旧时间覆盖、严重偏移、OOV和 text-only 情况因此不能宣称改善，也没有重新计算质量分数。
本轮严格相等的范围只有这两个窗口；不能直接写成十二窗或整片已证明。

## 成本、失败与复现

总串行墙钟151.745秒，含导入、冷加载、两窗新VAD／WX／适配层／标准API／nativeBatch。
WX ASR两窗15.967／9.227秒；独立适配层30.722／8.820秒，首窗含另一次冷特征／CT2初始化。
标准API8.883／8.907秒，nativeBatch7.348／8.008秒。
这些是额外研究运行成本，冷暖状态不同，不能用于性能排名。
没有MMS成本，也不把历史缓存对齐当作本轮新端到端速度。

GPU真实执行成功，输入哈希前后相等。两个ASR子进程均退出0，锁已释放。
旧 Pyannote checkpoint 被 Lightning 在内存中适配，未写回模型。
已有TorchCodec DLL警告未影响传入预解码waveform的实测；Python定位警告也未导致失败。
未安装修复组件，也未执行警告中的checkpoint永久升级命令。

v1 ASR冻结源保存在 `v1/source/`，早期运行脚本从工作目录执行。
运行完成后只收紧目录限制、冻结源调用与取消清理并修正来源说明；不覆盖v1原始源快照。
后处理验证源码另存哈希并记录 `analysis.json`；这些安全改动不构成新GPU结果。

可复现入口见[实验README](../../experiments/framework_equivalence/README.md)；
`summary.json`、`analysis.json`、`vad-equivalence.json` 不含全文，
实际字节／规范化补证见`features-text-check.json`，MMS实际搜索输入补证见`mms-input-check.json`；
`wx.json`／`fw.json`及完整日志仅留在Git忽略的私有目录。
新入口语法编译通过；超出允许目录及已有阶段结果的两次拒绝验证均在推理前以非零退出，
未生成无效输出或覆盖v1。取消清理逻辑经代码核查，未新增GPU取消实测。
相关[实施计划](../plans/whisper-framework-equivalence.md)和
[VAD／对齐源码审计](2026-10-04-whisper-framework-vad-alignment-audit.md)给出更广的边界。
原始上游固定版本代码：
[WhisperX3.8.6](https://github.com/m-bain/whisperX/tree/v3.8.6/whisperx)，
[faster-whisper1.2.1](https://github.com/SYSTRAN/faster-whisper/tree/v1.2.1/faster_whisper)，
[CT2 4.8.2](https://github.com/OpenNMT/CTranslate2/tree/v4.8.2/src)。
源码事实来自本机安装文件，访问／核验日期2026-10-04；质量结论仍以历史报告为准。
