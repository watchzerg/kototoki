# W0／X0 标准基线测试指南

状态：demo评估阶段的临时基线测试入口  
最后更新：2026-10-05  
范围：后续模型或session运行、回归、比较当前W0／X0；使用已配置的本机离线环境。

本指南由CLAUDE.md、README和文档索引直接路由。项目定型后可由正式运行／测试说明替代，并同步清理这些入口链接。

## 选择标准入口

开始基线测试时，先按本表阅读demo使用说明、契约和验证记录，再检查实际代码与本机资产。
组件定义由[当前基准线](../architecture/stt-candidate-pipelines.md)维护；每套demo的README维护详细参数、资产准备和修改方法。

| 测试身份 | 标准实现与使用说明 | 契约 | 已有验证 |
| --- | --- | --- | --- |
| W0，`w0-pyannote-current-mms-v1` | [W0 demo](../../experiments/w0_demo/README.md)，显式 `--vad-manifest` | [W0契约](../specs/w0-reusable-demo.md) | [W0验证与证据边界](../testing/2026-10-05-w0-demo-validation.md)、[最新整片报告](../research/2026-10-05-fullfilm-segmentation-comparison.md) |
| X0，`x0-demo-vad-source-windows-v1`＋`vad_id=pyannote-current` | [X0 demo](../../experiments/x0_demo/README.md)，显式 `--segmentation vad --vad-manifest` | [X0契约](../specs/x0-reusable-demo.md) | [X0验证与证据边界](../testing/2026-10-05-x0-demo-validation.md)、[最新整片报告](../research/2026-10-05-fullfilm-segmentation-comparison.md) |

当前 W0 为 faster-whisper＋newPyannote＋MMS；X0 为 Qwen＋newPyannote＋MMS。
两条都不降噪、不做人声分离，保留日语原文；采纳依据见[ADR-0003](../adr/0003-new-pyannote-baselines.md)。
本次仅更新文档，代码无参数默认仍分别为旧 PyanNet 和 fixed30。
仅写“W0／X0”时指当前采纳组合；执行必须使用下方显式 manifest 命令，不能用无参数默认冒充当前基线。

**X0只吸收逻辑合理且适用于Qwen的WhisperX流程。** 逐块独立纯文字识别、再交给共用MMS对齐已具备等价行为；
特征使用Qwen原生processor及有效长度／mask契约。无需重复实现已有行为，也不照搬Whisper的Mel、补齐或token。
当前两条基线采用适配 segmentation-3.0 powerset 的原生检测＋源跨度切分合并，保留窗口内部静音，
允许过滤窗口外音频；超长原区间硬切，并非旧 PyanNet 的 min-cut 逐项移植。Whisper 特征与无时间戳 token 仅属于 W0；
X0 保持 Qwen 原生输入。旧 fixed30 没有执行可变语音段切分合并；低能量 `cut-merge` 为独立无 VAD 对照，
保留全部样本，不是 newPyannote 流程或直接 WhisperX 移植。早期流程依据保留于[ADR-0002](../adr/0002-x0-demo-flow.md)。

## 运行一次新的基线

1. 阅读[选型约束](../development/inference-selection.md)与[素材规则](../testing/fatestay-reference.md)。
   预先固定同一输入WAV、源偏移、参考和比较范围；记录既有样本接触历史。
2. 检查demo README指定的解释器、模型及资产已在本机。正常测试离线运行；缺少资产时按说明报告缺项，
   环境恢复与模型获取单独处理。根环境不具备全部推理依赖，W0和X0使用的解释器不同。
3. 在仓库根目录先新运行独立 newPyannote VAD，再顺序执行对应 demo；同输入的两条路线可共用这份新 manifest。
   输入必须为mono／16kHz／PCM16 WAV；其他格式先制作独立副本，保留原素材。
   示例为已准备的300秒片段；自己的输入使用其真实源偏移，完整源文件通常为0。

```powershell
.local/envs/vad-pyannote-gpu-v1/Scripts/python.exe -m experiments.vad_comparison.vad_stage --audio .local/round2/corpus/audio/hf-ii-window-01.wav --offset 351.402125 --out .local/vad-comparison/baseline-newpyannote-01 --vad-id pyannote-current --model .local/models/vad-comparison/pyannote-segmentation-3.0/pytorch_model.bin --revision e66f3d3b9eb0873085418a7b813d3b369bf160bb --device cuda:0

.local/envs/whisper-latest/Scripts/python.exe -m experiments.w0_demo.run --audio .local/round2/corpus/audio/hf-ii-window-01.wav --offset 351.402125 --out .local/w0-demo/baseline-check-01 --vad-manifest .local/vad-comparison/baseline-newpyannote-01/manifest.json

.venv/Scripts/python.exe -m experiments.x0_demo.run --audio .local/round2/corpus/audio/hf-ii-window-01.wav --offset 351.402125 --out .local/x0-demo/baseline-check-01 --segmentation vad --vad-manifest .local/vad-comparison/baseline-newpyannote-01/manifest.json
```

每次使用新的输出目录；已存在时改用新身份，不覆盖旧产物。两条共用`.local/gpu.lock`，串行推理；已有锁先确认进程，保留活跃锁。
工具链激活后X0也可用`just x0-demo`；W0使用上面的已验证后端入口，当前没有`just w0-demo`配方。
完整基线须有新的外部 VAD 和 ASR／MMS 推理证据。newPyannote 环境、权重、许可与门控见
[GPU 补测](../research/2026-10-05-pyannote-gpu-comparison.md)和[版本核验](../research/2026-10-05-vad-stable-versions.md)。
其 manifest 记录 `pyannote-current-source-span-merge-v1`、CUDA、模型 revision 和输入／整数窗口身份。
W0 的 `--frozen-vad`、复用已有 manifest 或缓存 ASR 都属于隔离回归，须单独标识。
完整端到端成本另计外部 VAD 完整进程墙钟加 demo 成本；manifest 回放时间不能冒充新 VAD 或完整路线耗时。

## 检查与评分

完成的判断不只是进程退出：核对`result.json`、全文、分段、全部字符units／text_only、ASR trace、
`alignment_records`中的失败、输入／模型／源码身份及实际GPU。X0还要检查阶段记录、生成触顶和`partial`状态；
W0也要逐段检查MMS失败，不能仅凭顶层状态判定全部对齐成功。缺失或失败产物留在完整测试分母中。

两套demo的`result.json`直接遵循[评测器契约](../testing/evaluator-contract.md)。
用对应完整参考进行新评分，例如：

```powershell
.venv/Scripts/python.exe -m kototoki_eval .local/round2/corpus/references/hf-ii-window-01.json .local/x0-demo/baseline-check-01/result.json --output .local/x0-demo/baseline-check-01/evaluation.json
```

评测方法见[质量与性能评估](../testing/stt-evaluation.md)；显示层按[显示契约](../testing/demo-display-contract.md)重放。
比较全文S／D／I、重复、完整分母的时间覆盖与严重偏移，并报告加载和端到端成本。
保留text_only、失败与重试；不能删除难例后只比较成功子集。早期两窗 demo 验证属于旧 PyanNet／fixed30／cut-merge；
当前 newPyannote 已有两片[整片证据](../research/2026-10-05-fullfilm-segmentation-comparison.md)，
含极短窗口 MMS 失败。该证据不代表其他作品、新版本或严格声学时间目标已通过，也未测整片 fixed30。
旧`experiments/performance`面向历史harness manifest，不能把当前demo的`result.json`直接当作旧manifest；
当前耗时从demo阶段记录读取，跨进程计时以X0的`process_costs`与父流程墙钟为准。

## 修改与历史复现

四种新增 VAD 的十组合对照使用[独立实验入口](../../experiments/vad_comparison/README.md)和
[冻结计划](../plans/vad-baseline-comparison.md)。W0 的 `--vad-manifest` 与 X0 的
`--segmentation vad --vad-manifest` 只导入带输入身份与整数源窗口的外部检测证据；
这些比较的“原基线”身份仍为冻结旧 PyanNet／fixed30；它们不等于此次采纳的当前 newPyannote 基线。
预计算 VAD 成本与 demo 内实际 ASR／MMS 成本分别记录，不把窗口回放称为新 VAD 推理。

两部完整电影的新Pyannote／cut-merge对照使用[整片实验入口](../../experiments/fullfilm_comparison/README.md)
和[整片计划](../plans/fullfilm-segmentation-comparison.md)。它复用当前ASR／MMS适配器，整片一次切分、
逐阶段模型驻留，并记录失败分段后继续后续输入；300秒区间仅用于评分，不作为采样或推理重置点。
该实验单独提供全量与同家族失败区间并集排除结果。当前采纳取舍见 ADR-0003；
canonical demo 的无参数默认及失败策略仍保持现有代码，整片 worker 的失败后继续不能写为 demo 已迁移。

修改当前W0／X0时更新对应demo模块与测试；MMS共用`experiments/w0_demo/alignment.py`，同时检查两条契约。
分段、模型、解码或数值行为变化要另建配方／运行身份，冻结实际配置与源码。根`just test`包含两套demo离线测试，
可选依赖跳过按README在固定后端补测；推理变更再做本机模型验证，更新相应验证记录和索引。

`experiments/whisper/`、`qwen/run_cross.py`、`framework_equivalence/`、`japanese_ctc/`、`x0_flow/`及旧批量harness
用于各自历史轮次或专门组件实验。复现历史时使用其冻结配置、源码与旧身份；测试当前基线时使用本页标准demo。
旧W0曾是不带VAD／CTC的Whisper，旧X0曾默认Jonatas对齐；名称相同不代表同一组合。历史分数、命令和结果保持原身份。
旧 `w0-pyannote-mms-v1` 通过不传 `--vad-manifest`／`--frozen-vad` 复现，旧 `x0-demo-fixed30-v1`
通过 `--segmentation fixed30` 且不传 manifest 复现。低能量对照用 `--segmentation cut-merge`；
这些无 VAD／旧 VAD 运行必须明确标为历史或对照，不能沿用当前基线名称。
