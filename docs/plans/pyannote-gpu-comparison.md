# 新 Pyannote CPU／GPU 对照补测

状态：执行与分析完成；23次完成、1次同窗生成上限失败  
日期：2026-10-05  
范围：用户要求将新版 Pyannote 改为 GPU 后重测；原十组合结果保持独立。

2026-10-05 后续采用：用户在整片比较后明确采用 W0／X0 新 Pyannote＋MMS 基线，见[ADR-0003](../adr/0003-new-pyannote-baselines.md)。本页仅保留已完成 CPU／GPU 补测的冻结范围；结果不自动换默认的限制是当时实验边界，后续用户采用另有依据。canonical demo 的执行默认仍待迁移。

## 冻结范围

沿用[十组合计划](vad-baseline-comparison.md)的十二个已接触窗口：总计60分钟、6544参考字符、590条参考字幕。
W0、X0 各重新执行十二窗 ASR／MMS；每窗新版 Pyannote GPU 检测一次，两条路线共享其整数源窗口。
使用同一 `pyannote.audio 4.0.7`、`segmentation-3.0` revision
`e66f3d3b9eb0873085418a7b813d3b369bf160bb`、参数及切分合并代码；设备设为 `cuda:0`、FP32。
GPU VAD 环境独立建立，目标保持 Python 3.12.15、Torch／TorchAudio 2.11.0，仅替换 CPU／CUDA 构建。
实际依赖差异随 provision 清单和结果保存。Whisper、Qwen、MMS 的既有环境和参数不变。

新身份为 `.local/vad-comparison/pyannote-gpu-v1/`。
登记保留原八条路线的96次历史结果作为参考，明确记录来源登记 SHA256；只新执行两条 Pyannote 路线的24次测试。
历史 CPU 新 Pyannote 的24次尝试仍从原登记读取，不能用 GPU 结果覆盖。
初始化脚本为 `.local/vad-comparison/prepare-pyannote-gpu-v1.py`。

## 检查和比较

1. 独立 GPU 环境验证实际 CUDA 可用；先对 II window-01 执行 VAD 资源测量，再执行完整批次，共用 GPU 锁。
2. 对比全部十二窗 CPU／GPU 的整数裁剪边界、原始语音段及保留样本数。
3. 完整分母计分：CER、S／D／I、0.5秒成功数、条件长尾与失败。X0 上次触顶窗口必须纳入。
   如仍触发4096-token上限，保留部分输出和失败身份，不调整上限重跑来替代失败。
4. 区分 VAD 推理、加载、完整进程与 VAD＋ASR＋MMS 重构串行成本。
   单窗资源指标分列进程 RAM 和 Torch allocator 显存；不将整卡采样当模型独占显存。
5. 核验源码快照、模型、依赖、输入与 VAD／ASR／MMS 同源裁剪，原参考产物不变。

首窗 GPU 冷进程推理实测慢于既有 CPU 后，增加一项解释性补测：主批次结束后，
CPU／GPU 各加载一次同一模型，在同一 II window-01 连续检测三次，保留首次和两次模型复用耗时。
不调参、不重做 ASR、不替换主批次成绩；用于区分首次调用开销和驻留模型的执行成本。

本次是既有样本上的单次设备对照，没有新盲测或人工声学时间标签；不凭短时差异认定稳定吞吐提升。
结果不会自动切换默认 W0／X0 配方。

## 结果入口

[最终报告](../research/2026-10-05-pyannote-gpu-comparison.md)记录完整结果。
十二窗检测和23组完整输出与 CPU 一致，X0 同窗再次触顶；模型复用补测中 GPU 后两次平均约0.201秒、CPU约2.627秒。
每窗新进程的批次没有模型复用优势。评分、产物核验与独立子 agent 复核均已完成，失败按完整分母保留。
