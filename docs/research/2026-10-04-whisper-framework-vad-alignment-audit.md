# Whisper 框架选择：VAD 与 MMS 对齐边界核验

> 2026-10-05 后续开发入口：继续实现本文的 VAD／MMS 边界时，复用并更新 [W0 demo](../../experiments/w0_demo/README.md) 的 `vad.py`／`alignment.py`。独立加载、对齐及 TF32 状态隔离已完成 [两窗回归](../testing/2026-10-05-w0-demo-validation.md)；下文仍是原审计时的调用链，旧原生 cue 不在新 demo 兼容范围内。

状态：本机固定版本源码审计已完成；迁移等价性仍须由隔离实验验证  
最后更新：2026-10-04  
范围：WhisperX 3.8.6 的 Pyannote 分段，以及 Kototoki 当前 MMS 日语对齐；不改变正式后端，不新增 GPU 推理。

相关入口：[当前候选](../architecture/stt-candidate-pipelines.md)、[MMS 实测](2026-10-04-japanese-ctc-results.md)、[CTC 来源核验](2026-10-04-japanese-ctc-source-verification.md)、[环境清单](2026-10-04-runtime-inventory.md)。本文是框架决策的子审计，不单独决定 A／B。

## 审计结论

WhisperX 确实提供了影响识别的 VAD 分段策略：原始分数经过迟滞阈值、长语音最低分切分、按源时间跨度贪心合并。不能把这几步简化为“装上 Pyannote 就一样”。但它们是明确的流程代码，神经网络和滑窗聚合主要由 Pyannote 实现；源码没有显示需要 fork Pyannote 才能得到这些行为。

当前 MMS 质量证据已经包含 Kototoki 自己的模型加载、adapter 校验、逐窗口音频归一化和标准 CUDA CTC 解码。WhisperX 的原生 trellis 时间并不是当前最终评分的字符时间。保留框架也不能免除这些自研责任。框架仍在提供字符提取、窗口裁剪、wildcard、原生句子／cue 处理；这些行为能够描述和测试，但尚不能仅凭源码宣布替代后的全部输出完全相同。

## 版本与身份：实际检查了什么

本次通过 `.local/envs/whisper-latest/Scripts/python.exe -B` 读取 installed distribution metadata 和受信任的已安装 VAD checkpoint 元数据，未执行模型 forward。结果为 WhisperX **3.8.6**、faster-whisper **1.2.1**、Pyannote Audio **4.0.7**、Torch／TorchAudio **2.8.0+cu128**、Transformers **4.57.6**。本文全部行号取自本次本机文件；升级后需重新核验。

VAD 文件为 `.local/envs/whisper-latest/Lib/site-packages/whisperx/assets/pytorch_model.bin`，17,719,103 字节，SHA256 `0b5b3216d60a2d32fc086b47ea8c67589aaeb26b7e07fcbe620d6d0b83e209ea`。checkpoint 记录 `pyannote.audio.models.segmentation.PyanNet.PyanNet`、单声道 16 kHz、训练窗口 5 秒、`warm_up=(0,0)`、3 个 speaker 类别、多标签且非 powerset。它不能被称为 `segmentation-3.0` 或当前任意 Pyannote checkpoint。旧训练版本元数据是 checkpoint 的历史身份，不是本机 runtime 版本。

关键 installed source SHA256：

| 文件（相对上述 site-packages） | SHA256 |
| --- | --- |
| `whisperx/vads/pyannote.py` | `65575744a07c2366847b33c14ba56a1e5e07234a4f6d7008d2e271f134413003` |
| `whisperx/vads/vad.py` | `f901c04d208abf64107ea88404c36341394c7f0b705f78210abe25bd4f25ae87` |
| `whisperx/alignment.py` | `cc3607dcc25e592ae218f74a6ca644d6ce1c77d9cee4672f01c751da8feb9aa7` |

另读取了 `.local/results/jctc-mms-full-v2-*/result.json` **24 份**：W1／X0 各12窗，共230个对齐 segment，全部调用 `ok`、无记录的标准 CTC 解码失败、搜索 padding 均为0、日语输出词表2268。全部结果记录最终 `lm_head.weight`／`bias` 与日语 adapter 完全相同。调用成功不代表字词都获得有效时间，更不代表严重偏移消失；质量与失败分母仍以原报告为准。本次读取没有输出私有台词。

## VAD：流程表与隐含约束

以下 `WX/` 指本机 `whisperx/`，`PA/` 指本机 `pyannote/audio/`。

| 行为 | 实际路径／源码位置 | 实际影响 | 直接实现与验证成本 | 现有证据 |
| --- | --- | --- | --- | --- |
| checkpoint 获取 | `WX/vads/pyannote.py:21-47`：默认读取 package 内资产，`Model.from_pretrained(local_path)`；不存在即失败 | 不需要在正常转写中下载新 VAD；换 checkpoint 会改变原始分数 | 低代码复杂度；须单独固定资产来源、hash和加载兼容性 | 文件hash、checkpoint CPU元数据及旧GPU forward记录 |
| 输入 | `experiments/whisper/run.py:36-50` 校验mono16kHz PCM16，转换float32／32768；`WX/vads/pyannote.py:244-245` 增加channel轴 | 当前 VAD 收到已解码数组；没有框架降噪／分离 | 保留输入hash、采样率、channel、dtype；不应改用未经核验的文件解码路径 | 固定实验 manifest及代码 |
| Pyannote 模型与滑窗 | `PA/core/model.py:97` 的 Audio downmix；`PA/core/inference.py:117-165,244-278,349-367`：默认训练窗、步长、尾端补零、Hamming聚合和裁剪；`PA/pipelines/voice_activity_detection.py:111-114` max-over-speaker | 5秒窗口、默认0.5秒步长；三speaker概率先max再聚合；保留模型frame坐标 | 使用现有Pyannote Inference即可，无需自己重写神经模型和聚合；需冻结分数和sliding-window参数验证 | checkpoint元数据和已安装代码；本轮未单独跑滑窗 |
| 音频归一化 | `PA/models/blocks/sincnet.py:52,171` 的 `InstanceNorm1d`／forward | 归一化是checkpoint内模型的行为；与MMS显式feature extractor归一化不同 | 保留同模型即可；不要额外添加整段normalize并称等价 | 本机模型代码 |
| 参数字段与有效参数 | `WX/vads/pyannote.py:42-47` instantiate onset=.5、offset=.363、min_duration_on/off=.1；但 `VoiceActivitySegmentation.apply:199-230` 直接返回分数 | 父类 `_binarize` 没有在此apply执行；**0.1秒最短段／填缝没有进入实际最终分段** | 极易误复现；标准VoiceActivityDetection直接调用会走另一条行为 | 固定版本源码调用链 |
| 实际迟滞 | `WX/vads/pyannote.py:254` 创建 `Binarize(max_duration=chunk_size,onset,offset)`；`:132,151,163` 使用严格`>`／`<` | 当前阈值 .500／.363；实际min duration、pad均默认0；阈值相等不触发切换 | 中等行为复杂度；测试阈值相等、首帧、尾端、短speech、短gap、空speech | W1旧运行使用默认值；无独立等价复验 |
| 长语音切分 | `WX/vads/pyannote.py:140-149` 在持续段超过30秒时，在当前保存分数后半段寻找第一个argmin并切分 | 不只是整齐30秒切窗；选择较低语音置信度边界 | 可直接复现；要保留队列更新、并列最小值、frame.middle、`>`判断和最终尾端 | 固定代码；效果无法由旧W0/W1分数单独归因 |
| 相邻语音合并 | `WX/vads/vad.py:32-50` 若新段end减curr_start超过30秒才flush；否则合并 | ASR裁剪是合并段的完整源区间，**内部静音保留**；不是将speech拼接去静音；speaker_idxs不进入输出 | 算法小但语义重要；测试长gap／跨界／相邻长段／最后chunk；保持源坐标 | 源码及历史ASR segment |
| 空speech | `WX/vads/pyannote.py:260-262` 返回[]；调用端按这些窗口生成 | 无ASR块；空结果与加载失败需分开 | 低；须验证空音频、数字静音与VAD漏检记账 | 已有静音报告，不构成公平框架实验 |
| ASR裁剪与坐标 | `WX/asr.py:213-235` 使用int(start/end×16000)裁剪；`:281-287` 将VAD start/end round到3位作为ASR segment | 分数原始边界用于ASR采样；返回的3位小数边界随后决定当前MMS裁剪。两者可能有不到1ms差异 | 必須保存未舍入窗口与返回窗口；不可用返回的round边界重新生成mel后宣称完全相同 | 固定实现；迁移时需要数组hash证明 |

`Pyannote.__init__`（`WX/vads/pyannote.py:235-238`）没有把传入的onset／offset kwargs交给`load_vad_model`。实际阈值仍由`WX/asr.py:230-235`的最终merge使用，所以本轮默认配置不受影响；如果独立迁移只看 pipeline 内参数，会错认外部override行为。

长段 min-cut 是需要保留的重要行为，但没有证据说明它复杂到只能靠 WhisperX 维护。验证它时应冻结原始分数及frame网格，比较二值段、merge窗口、source samples和ASR结果；只冻结最终窗口能够验证ASR公平性，不能证明自己复现了分段。

## MMS：哪些已经由 Kototoki 接管

| 边界 | 当前实际实现／位置 | 原生WhisperX的职责或限制 | 迁移时必须保留 |
| --- | --- | --- | --- |
| 固定文字 | `experiments/japanese_ctc/run.py:31-47,305-310` 校验ASR全文等于original_segments串接，PCM／file hash／offset及finite界限，deepcopy | MMS实验复用同上游ASR，不重新识别；W0／W1原ASR及窗口仍不同 | 相同完整文字、分段及search窗口是公平对照先决条件；不能只匹配CER |
| 日语身份 | `japanese_ctc/run.py:98-118` processor target_lang=jpn，base model target_lang=None，再load_adapter(jpn)，float32／eval／CUDA | stock `WX/alignment.py:101-112` 不选择MMS jpn；不能仅指定模型路径就得到正确adapter | 固定revision `3d33597edbdaaba14a8e858e2c8caa76e3cec0cd`、2268词表、blank0、adapter校验；`verify_mms_head:80-95` 比较head真实tensor |
| tokenizer | `WX/alignment.py:157-185` 保留原文位置，字母lower，strip首尾空白；ja不将space换`|`；已知字符字典查找，非空白OOV成wildcard | 当前MMS选择`whisperx-char`，**不调用native tokenizer.tokenize做多字piece分词** | exact character／token映射、空白及OOV责任；tokenization变化是新实验 |
| search窗口 | `whisper/run.py:269-270` 每个ASR segment两端扩padding并clamp；MMS已测padding0；`WX/alignment.py:242-252` int采样、少于400右补零 | W1的search是3位小数VAD返回segment；W0另有own-word-envelope bridge。原native word/cue不是公平窗口 | segment start/end、int量化、pad到400和duration／frames比例；不引入参考字幕边界 |
| 音频归一化 | `whisper/ctc_audio.py:20-51,53-73` 官方feature extractor逐窗归一化，pre-hook验证native切片hash并替换 | stock HF forward `WX/alignment.py:260` 直接吃raw waveform；没有官方feature extractor处理 | valid-sample mean／variance+1e-7、排除右补零统计，恢复pad0、raw／normalized hash。MMS配置return_attention_mask=true，**当前模型未传mask**，迁移必须先保持此baseline |
| model forward | `japanese_ctc/run.py:126-145` 检查全部parameters CUDA FP32及forward输入输出 | 仍由Transformers模型生成logits；WhisperX负责log_softmax及转CPU（alignment.py:256-265） | forward dtype/device、logits／emission hash及同步成本；移除CPU往返要作为可验证变化 |
| blank／wildcard | `WX/alignment.py:267-283` 从`[pad]`／`<pad>`取blank；若有OOV，新增max nonblank列 | wildcard可让缺词表目标经过路径，但不能算该字有真实词汇时间 | MMS loader明确blank一致；OOV需要路径但最终单位text_only，不能把wildcard时间冒充成功 |
| native trellis | `WX/alignment.py:285-296,425-490` 原生trellis／backtrack仍执行；`whisper/ctc_forced.py:101-105` 先调用native，再observer | 当前并未彻底替换native计算；它用于原生aligned／cue兼容结果，非最终评分unit时间 | 若只保留标准CTC单位，可摆脱该计算；但需显式限定native cues变化，不能笼统说输出全等 |
| 标准CUDA CTC | `whisper/ctc_forced.py:17-60` 调用TorchAudio forced_align，token序列／count及设备校验，merge非blank；`derived_segments:62-81` 以原位置构造时间 | 已由Kototoki接管；与native“advance token＋blank stay”路径不同 | 相同emission、targets、blank、重复token约束、time ratio及3位round；RuntimeError／ValueError记录而不CPU回退 |
| 最终输出 | `whisper/run.py:350-358` 原生evaluation留存，最终units换成derived；`evaluation:53-100` 单调映射、源offset、所有原文字保留 | 原生Pandas／NLTK句切／nearest插值仍产生cues；字符units取本项目decoder证据 | 原全文、失败与缺时间保留。**当前cues仍是native aligned cues**；需要单独验证字符时间与显示输出，而非仅全文／units |

frame到秒沿用“search区间duration／emission frame数”，它不是重新估计声学frame中心，也没有去除wav2vec2感受野偏移。小于400补零窗口仍用原search duration计算比例。上述是已测行为；迁移时可提出改良，但不能同时修改后声称保留W1。

所有被排除的原字符仍进全文，OOV／标准decoder失败不生成词汇时间。旧MMS结果24次调用成功只能说明没有显式阶段／decoder故障；原报告保留W1约12.207秒、X0约31.292秒的极端偏移。本审计不重算分数，也不将内容删除当作修复。

## 依赖、失败处理与维护风险

“移除WhisperX”不等于移除Torch、Pyannote、Transformers、MMS或CUDA CTC。这两个候选组合的核心模型与设备约束相同。真实收益可能来自减少框架绑定和运行时hook，而非大幅减少神经依赖。

保留现状也有明确代价：`SegmentNormalizer`用forward顺序与切片hash绑定WhisperX 3.8.6；`capture_forced`暂时替换module级`backtrack`，先执行native path，再标准CUDA decoder。它们适合串行隔离实验；未来同进程并发或上游调用链变化会要求重新验证。原native alignment还需要CPU trellis、Pandas和NLTK；即使最终单位不用原生句切，当前代码仍运行它。日语没有专门Punkt模型而fallback英文；`WX/alignment.py:189-196` 会在缺资源时尝试下载，项目`whisper/run.py:252`提前要求本地英文资源以便离线失败。独立字符对齐实现可以不引入这些资源，但完整旧cue等价另有成本。

TorchAudio 2.8 `forced_align`弃用／2.9移除的责任对两条方案都存在；它是项目自己选用的替换边界，WhisperX不能代为保住此API。MMS许可CC-BY-NC-4.0同样是组合共同约束，不是框架优劣证据。

本次CPU metadata读取出现TorchCodec DLL／FFmpeg导入警告；固定路径预加载waveform因此无需该decoder。仅据这条警告不能说W1 VAD不能运行，也不能推断修复安装是本任务所需。独立Pyannote封装应继续使用已验证内存音频接口。

维护难度判断：VAD迟滞／min-cut／merge是有界中等行为复杂度；难点是边界语义及冻结验证，不是代码长度。MMS原文映射／OOV／缺证据保存也为中等复杂度；当前代码已承担多数责任。若坚持无变化复现native句子cues，则增加Pandas／NLTK插值和句切兼容成本；如果只将现有标准unit契约作为产品时间接口，这部分可能不必作为长期架构责任，但必须明示输出契约选择。

## 最小必要验证与未决点

源码已经证明需要复现哪些VAD和MMS行为；尚不能证明不同ASR路径在相同块上给出同样文字。因此架构主实验应先冻结一份raw Pyannote scores及未舍入合并窗口；两条ASR从同源sample slice开始，先比较mel、prompt、有效CT2参数、generated tokens／全文，再送同一MMS实现。然后用raw scores对独立VAD复刻逐边界对照，避免神经VAD差异混入框架效果。

MMS验证应分别比较normalized input、adapter/head、emission、target、standard CTC path、原文单位／time-only失败集合，以及native cues。先保持不传model attention_mask、padding0、同frame比例；这些疑点可以作为后续单变量改善，不能混入框架迁移证明。全分母漏字、重复、time覆盖和最大偏移需保留；不必仅为本文纯源码审计重新推理两片全60分钟。

本文未验证独立VAD复刻、独立MMS实现或改换ASR入口的实测等价性；这几项由框架主研究的隔离实验补齐。本机checkpoint来源hash可证明资产身份，但本次未重新从发布wheel验证该模型的独立许可或来源链，沿用[环境清单](2026-10-04-runtime-inventory.md)边界。

## 源码与复核入口

核验／访问日期均为2026-10-04。主证据是上述固定installed source及本地实验记录；上游链接用于定位对应发布源码，网页本身不证明本机执行。

- [WhisperX v3.8.6 Pyannote 源码](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/vads/pyannote.py)：本次打开并确认同名264行发布文件。
- [WhisperX v3.8.6 merge实现](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/vads/vad.py)、[对齐实现](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/alignment.py)：本次主要读取本机对应文件，行号以installed版为准。
- [MMS固定revision模型卡](https://huggingface.co/facebook/mms-1b-all/blob/3d33597edbdaaba14a8e858e2c8caa76e3cec0cd/README.md)：模型／许可既有核验见CTC来源报告，本次核对本地acquisition与运行身份。尝试网页打开固定preprocessor_config返回工具内部错误，预处理结论来自本地已固定文件及实际代码。
- [TorchAudio 2.8 CTC教程](https://docs.pytorch.org/audio/2.8/tutorials/ctc_forced_alignment_api_tutorial.html)：本次访问复核弃用边界。
- 项目源码：[MMS loader／cached runner](../../experiments/japanese_ctc/run.py)、[W1调用链与输出映射](../../experiments/whisper/run.py)、[音频归一化](../../experiments/whisper/ctc_audio.py)、[标准解码](../../experiments/whisper/ctc_forced.py)。

本文新增文档，不更改实验、默认配置、README候选身份或AGENTS约束。文档索引由框架主研究统一更新，避免并发修改。
