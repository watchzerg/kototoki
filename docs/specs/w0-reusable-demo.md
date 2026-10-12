# W0 可复用 demo 契约

状态：demo 已实现；已采纳 newPyannote 基准线，代码默认参数迁移尚未实施  
最后更新：2026-10-05  
范围：隔离实验入口；不切换正式后端、不升级既有环境。

## 行为

唯一持续迭代入口为 `experiments/w0_demo/`，对应[当前 W0 基准线](../architecture/stt-candidate-pipelines.md)。
输入已准备的 mono／16 kHz／PCM16 WAV 和非负源偏移；保留源文件与日语全文。
输出私有 JSON、全文及身份／运行耗时。原生 WhisperX 字幕 cue 不属于兼容契约；显示层复用现有 `experiments/display/replay.py`。

当前采纳 W0 为 faster-whisper＋newPyannote＋MMS，无降噪、无人声分离，依据见
[ADR-0003](../adr/0003-new-pyannote-baselines.md)。使用现有独立 VAD 阶段新生成 manifest，
再显式传 `--vad-manifest`；无此参数的代码默认仍是旧 `w0-pyannote-mms-v1`，仅作历史复现。
当前身份为 `w0-pyannote-current-mms-v1`，须同时记录外部 VAD recipe、权重与设备。

- VAD 返回原音频坐标中的有序、不重叠、最长30秒窗口。当前 newPyannote 使用 segmentation-3.0 powerset 原生检测，onset／offset 0.5、min_duration_on／off 0；区间转为整数样本并取并集，超长区间每480000样本硬切，再按源跨度贪心合并。窗口内部静音保留，窗口外音频可被过滤，不拼接波形。旧 checkpoint／0.5与0.363迟滞阈值／min-cut 只属于冻结 PyanNet 路径，不能将其逐项等价结论迁移到新模型。
- ASR 逐窗口裁剪，补零到30秒，用冻结 Mel 资产、Torch STFT 和独立无时间戳提示调用 faster-whisper／CTranslate2。固定日语、large-v3、CUDA FP16、beam5、batch1；不串联前文。
- MMS 接收完整 ASR 字符串和同一窗口，显式归一化、加载并校验 jpn adapter，CUDA FP32 前向及标准 CUDA CTC 解码。所有字符必须有映射，缺少词汇／时间证据的字符保留为 `text_only`。
- ASR／MMS 必须使用 GPU，发生错误不转 CPU。当前 newPyannote 使用独立 CUDA 环境；CPU VAD 按选择原则允许，但须明确另记设备及验证。空语音跳过 ASR／MMS；模型按阶段释放，避免三个模型同时驻留。
- VAD、ASR、CTC 耗时分别记录；本入口每次重新 ASR／CTC，冻结 VAD 回放要校验音频 hash 与源偏移。
  `--vad-manifest` 与 `--frozen-vad` 互斥，接入独立 VAD 进程的窗口、参数及成本；当前基线须显式使用新 Pyannote manifest。复用旧 manifest 只计作隔离回归。
- 独立使用已获取的 newPyannote／Mel 资产；旧 PyanNet／Mel 复制入口保留，当前只需要其中 Mel。推理期间不导入 WhisperX、不联网获取资产。
- MMS 前向明确使用旧独立运行的 cuDNN TF32 开／matmul TF32 关，并在退出时恢复状态；记录实际配置，避免 VAD 的全局设置泄漏改变结果。

## 可替换边界

`pipeline.py` 的 `Vad`、`Asr`、`Aligner` Interface 用于测试与替换。
VAD 有实际 Pyannote 和冻结窗口两个 Adapter；独立 manifest 由冻结 Adapter 回放，保留原 VAD 的设备、参数及新推理证据。
本进程元数据明确 `fresh_inference=false`；原参数保存在 `origin_metadata`，不将外部执行写成本进程新 VAD。
新 VAD 接收相同 PCM，返回相同源坐标契约。
切换 VAD 不应复制 runner、ASR 或 CTC；修改识别／对齐时直接更新对应模块及回归测试。
历史 `framework_equivalence` 等实验用于证据，不成为新运行的隐式依赖。

MMS由W0与[X0 demo](x0-reusable-demo.md)共享。新增可选的成对整数 `start_sample/end_sample`，
严格校验范围及与秒坐标的一致性，再按整数裁剪；X0用它保留任意尾段的全部样本。
历史 PyanNet W0 不传这两个字段时继续原秒坐标裁剪，保留其 recipe 的数值行为。
独立 manifest 可传整数边界，W0 ASR 按它们裁剪，识别分段保留未舍入秒坐标及相同整数边界，交给 MMS。

## 独立 VAD manifest

manifest 须含 `schema_version=1`、`status=ok`、`input`、`offset_s`、安全的小写 `vad_id`、
非空 `recipe`、`metadata`、`stages` 与 `chunks`。输入内容身份完整匹配 WAV／PCM SHA256、
采样率、通道、样本数及秒时长；路径不同不影响相同内容，若提供 `representation` 也须一致。
源偏移须有限、非负且相同。窗口有序、不重叠，裁剪长度为1至480000样本；每个窗口的 `segments`
为有序、不重叠、完全位于该窗口的秒坐标二元组。可选整数边界须成对、有界且与秒坐标一致。
内部静音保留，不串接组成语音段。

runner 使用 `w0-{vad_id}-mms-v1` 实验身份，复制 manifest 并保存其来源 hash；运行期间来源变化即失败。
原成本 `stages` 至少包含有限非负 `vad_load_s`／`vad_inference_s`，完整保存在 `precomputed_vad.stages`，
同时链接输入身份和偏移。本进程 `stages` 保留窗口回放及实际 ASR／MMS 时间，另记录 manifest 读取成本。
外部 VAD 及输入成本不在 runner 墙钟内，完整端到端比较由父流程记录进程成本，避免重算或漏算。

## 验收

1. 无模型离线测试覆盖坐标、完整文字、失败保留、空语音和阶段生命周期。
2. 两片既有 window-01 上，真实 Pyannote、ASR 的块／全文／特征／token 与冻结研究逐项对照。
3. 新 MMS GPU 推理与旧同窗 MMS 的全文、字符区间、时间覆盖及解码记录对照；任何差异明确解释。
4. 保存独立运行身份及源码；旧素材、历史结果和默认后端保持原状态。

上面两窗验收属于旧 PyanNet demo 的复用起点，不等于 newPyannote 已逐项保留旧 VAD 行为。
新 Pyannote 的两片整片证据见[整片报告](../research/2026-10-05-fullfilm-segmentation-comparison.md)，
其中复用 ASR／MMS 的同窗验收与整片评分分别记录；整片失败后继续不属于本 demo 的新能力。
历史证据见[验证记录](../testing/2026-10-05-w0-demo-validation.md)，
使用与后续修改流程见[demo 说明](../../experiments/w0_demo/README.md)。
