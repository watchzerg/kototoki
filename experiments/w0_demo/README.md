# W0 可复用 demo

状态：可复用 demo 已实现；当前采纳 newPyannote 基准线，须显式传入 manifest  
最后更新：2026-10-05  
范围：本地 Windows／RTX 5080，已配置离线环境；持续迭代用的 W0 实验入口。

**后续 session 修改 W0 时，复用和更新此目录。** 替换 VAD、调整分段、识别或 MMS 时，先读
[实现契约](../../docs/specs/w0-reusable-demo.md)及[当前基准线](../../docs/architecture/stt-candidate-pipelines.md)，
更新对应模块和测试；每次实验新建输出身份。历史 `framework_equivalence`、`whisper` 和 `japanese_ctc`
目录是冻结证据，不应复制出另一套常用 W0 流程。

与X0共同测试、回归或比较时，先读[标准基线测试指南](../../docs/guides/baseline-testing.md)；本README维护W0具体使用方法。

当前 W0 为 faster-whisper＋newPyannote＋MMS，无降噪、无人声分离，保留已移植的
WhisperX 切分合并思路、逐块独立无时间戳解码与 Whisper 特征处理。采纳决定见
[ADR-0003](../../docs/adr/0003-new-pyannote-baselines.md)。本次只更新文档，代码无参数默认仍加载旧 PyanNet；
测试当前基准线必须使用下方 newPyannote manifest 命令。

## 已移植的行为

| 模块 | 职责与保持的行为 |
| --- | --- |
| `vad_candidates.py`／`vad.py` | 当前 newPyannote 由独立阶段加载 segmentation-3.0 powerset，原生检测后按源跨度合并到30秒，再通过冻结窗口 Adapter 回放；`vad.py` 另保留旧 PyanNet onset 0.5／offset 0.363＋min-cut 历史路径 |
| `asr.py` | 原窗口按样本裁剪，补零到30秒，冻结128通道 Mel 资产与 Torch STFT；逐块独立提示、无时间戳、无前文 conditioning，直接调用 faster-whisper／CTranslate2 |
| `alignment.py` | 独立 MMS jpn adapter 与 head 校验，窗口归一化，标准 CUDA CTC，OOV／失败保留全文及 text_only，映射源时间 |
| `pipeline.py` | VAD／ASR／Aligner 边界、按阶段释放 GPU 模型、完整文字与坐标契约校验 |
| `run.py` | 私有输出、离线环境、GPU 锁、耗时、输入／模型／源码身份、冻结 VAD 与独立 VAD manifest 回放 |

这不是未修改的 faster-whisper `transcribe()`。无降噪、人声分离、说话人标注；固定日语转写，
large-v3／CUDA FP16／beam5／batch1，MMS CUDA FP32。WhisperX 中未实际执行的温度回退、
静音阈值等参数不作为本 demo 的能力；移植依据见[差异审计](../../docs/research/2026-10-04-whisper-framework-asr-audit.md)。

## 首次准备与运行

使用已经配置的 `.local/envs/whisper-latest`，不安装或升级。现有环境版本与模型身份见
[框架研究](../../docs/research/2026-10-04-whisper-framework-architecture.md)。首次从已经取得的本机资产
复制旧 PyanNet 和 Mel 文件；当前 newPyannote 仅复用其中 Mel，旧 checkpoint 用于历史回归。
脚本只读本地文件并校验固定 SHA256，目标已存在时拒绝覆盖：

```powershell
.venv/Scripts/python.exe -m experiments.w0_demo.prepare_assets --source .local/envs/whisper-latest/Lib/site-packages/whisperx/assets
```

ASR 此后只读独立的 `.local/models/w0-assets/` Mel，不导入 WhisperX。newPyannote 使用已供给的
`.local/models/vad-comparison/pyannote-segmentation-3.0/pytorch_model.bin` 与
`.local/envs/vad-pyannote-gpu-v1/`；许可、门控及环境证据见
[版本核验](../../docs/research/2026-10-05-vad-stable-versions.md)和
[GPU 补测](../../docs/research/2026-10-05-pyannote-gpu-comparison.md)。模型获取和许可沿用
[环境清单](../../docs/research/2026-10-04-runtime-inventory.md)与[MMS 记录](../../docs/research/2026-10-04-japanese-ctc-source-verification.md)。
代码移植许可见 [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt)；checkpoint 的独立许可来源仍沿用已有未核验边界。

在仓库根目录执行，输入必须是已准备的16 kHz／单声道／PCM16 WAV。其他格式先制作独立副本，保留原素材；
源文件中剪出的窗口用 `--offset` 记录其起点：

```powershell
.local/envs/vad-pyannote-gpu-v1/Scripts/python.exe -m experiments.vad_comparison.vad_stage --audio .local/round2/corpus/audio/hf-ii-window-01.wav --offset 351.402125 --out .local/vad-comparison/baseline-newpyannote-01 --vad-id pyannote-current --model .local/models/vad-comparison/pyannote-segmentation-3.0/pytorch_model.bin --revision e66f3d3b9eb0873085418a7b813d3b369bf160bb --device cuda:0
.local/envs/whisper-latest/Scripts/python.exe -m experiments.w0_demo.run --audio .local/round2/corpus/audio/hf-ii-window-01.wav --offset 351.402125 --out .local/w0-demo/my-newpyannote-01 --vad-manifest .local/vad-comparison/baseline-newpyannote-01/manifest.json
```

newPyannote 为 pyannote.audio 4.0.7＋segmentation-3.0 powerset，onset／offset 0.5、
min_duration_on／off 0。原生检测区间转为整数源样本并取并集，超长区间每480000样本硬切，
再按源跨度贪心合并到最多30秒；保留窗口内部静音，允许过滤窗口外音频，不拼接波形。
这是适配新模型的切分合并流程，不能称为旧 PyanNet min-cut 的逐项等价移植。
以上两阶段都须新运行才算完整基线推理；已有 manifest 的回放仅属于隔离回归。

CLI `--help` 列出模型、资产和 DLL 目录参数。输出目录必须是 `.local/w0-demo/` 下的新路径。全部转写在本机私有输出中，控制台只输出数量与耗时。
`result.json` 包含全文、字符时间／text_only、分段、CTC 记录、ASR trace、有效参数与身份；`transcript.txt` 保存完整原文。
按需用现有 `experiments/display/replay.py` 生成显示层结果；本 demo 不复刻旧 WhisperX 原生 cue，
未获词汇时间的内容保留在全文／JSON，不能为提高覆盖指标删除它们。CTC nonblank span 仍不是声学真实时长。

第二次可使用 `--frozen-vad <先前的result.json>`，校验音频与 offset 后复用窗口，重新执行 ASR 和 MMS。
冻结 VAD 成本与真实 VAD 不可混比；新 ASR／MMS 时间分别保存在 `stages`。GPU 锁与历史实验共用 `.local/gpu.lock`，
发现现有锁先确认进程状态，不能随意删除活跃锁。

独立 VAD 比较可用 `--vad-manifest <manifest.json>` 接入本轮单独运行的 VAD 窗口，与 `--frozen-vad` 互斥。
代码无参数默认的旧 PyanNet 路径仍写 `w0-pyannote-mms-v1`，仅供历史复现；当前 newPyannote
manifest 路径写 `w0-pyannote-current-mms-v1`，其他 manifest 使用 `w0-{vad_id}-mms-v1` 身份。
manifest 必须为 `schema_version=1`、`status=ok`，包含完整输入内容身份（WAV／PCM SHA256、采样率、通道、样本数、时长）、
相同 `offset_s`、`vad_id`、`recipe`、`chunks`、原 VAD `metadata` 及 `stages`。
`stages` 至少记录 `vad_load_s`／`vad_inference_s`，所有成本为有限非负值；输入路径可变化，内容身份必须相同。
窗口须有序、不重叠，保留整个源时间跨度及内部静音；`segments` 记录窗口内的组成语音段，不将它们拼接成新波形。
可选成对整数 `start_sample/end_sample` 必须与秒坐标一致，ASR 与 MMS 使用相同整数边界；省略时保持旧秒坐标裁剪。

runner 将 manifest 复制为输出目录的 `vad-manifest.json`，保存来源 SHA256、原 VAD 参数与源身份。
本进程只回放窗口，`effective_parameters.vad.fresh_inference=false`；原进程的新推理证据保存在 `origin_metadata`。
`stages.vad_s`／`vad_load_s` 是实际回放成本，原 VAD 及输入阶段成本放在 `precomputed_vad.stages`。
它们不包含于 runner 的 `wall_s`，完整组合成本须由父流程计入独立 VAD 进程及 ASR／MMS 进程，不能将回放耗时当作新 VAD 性能。

MMS 前向显式固定 cuDNN TF32 开启、matmul TF32 关闭，退出后恢复调用者设置。
这是旧 MMS 独立运行的数值配置；防止 Pyannote 的全局 TF32 修改影响后续对齐。
模型参数及输入保持 FP32，不能把它误写为“所有内核都禁止 TF32”。调用者的全局 deterministic 要求保持不变并记录。
当前 newPyannote 基线使用上述独立 CUDA 环境；旧 PyanNet 默认也使用 CUDA。独立 manifest 可承载
CPU／GPU VAD 的原设备证据，须单独记录，不继承旧 PyanNet 的 CUDA 等价结论。

## 后续修改与验收

[X0 demo](../x0_demo/README.md)也复用本目录的MMS实现。它传入可选整数样本窗口以完整保留尾段；
W0旧 PyanNet 秒坐标路径保留历史行为；当前 newPyannote manifest 的整数窗口传递给共享对齐器。
共享对齐器变更需同时检查两条路径，接口见[契约](../../docs/specs/w0-reusable-demo.md)。

1. 在此目录实现新 VAD Adapter，满足 `segment(audio)` 的原时间窗口契约；ASR 和 MMS 使用同一个 runner。需要变更契约时同步改 spec。
2. 为变化的行为使用独立 recipe 身份；独立 VAD manifest 由 runner 生成实验身份，默认 recipe 仅在默认行为改变时更新。
   文档采纳与代码默认分开记录。保留旧运行的源码／模型／输入清单；所有新产物另建目录，不改写历史 W0／W1 成绩。
3. 先在同一冻结 VAD 上比较 ASR 特征、prompt、token、全文和边界；再比较新 VAD 分段；MMS 配置固定。记录漏字、重复、text_only、时间覆盖及严重偏移。
4. 用 `just test` 或项目 Python 的 `unittest discover -s experiments/w0_demo -t .` 跑离线测试；推理变化再用已有本地资产跑 GPU 回归。
5. 记录证据，更新本说明、spec、当前基准线及 docs/INDEX；仅通过小样本时明确范围，不能自动宣布整片或正式后端迁移完成。

首次独立 demo 的验证结果见[验证记录](../../docs/testing/2026-10-05-w0-demo-validation.md)。
最新 newPyannote 两片整片证据见[整片报告](../../docs/research/2026-10-05-fullfilm-segmentation-comparison.md)；
该实验复用 canonical ASR／MMS，但逐段失败后继续的规则属于整片入口，不代表 demo 失败策略已改。
