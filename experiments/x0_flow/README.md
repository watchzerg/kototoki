# X0 分片流程隔离原型

状态：探索性原型；真实推理验证范围由本轮研究报告维护  
最后更新：2026-10-05  
范围：原生 Windows、既有离线环境与权重；比较 Qwen 分片流程，不更改正式 X0／W0 基准线。

后续运行和开发请使用[当前X0 demo](../x0_demo/README.md)。本目录保留历史三臂代码和结果身份；
新demo的cut-merge不同于这里的energy，不继承历史评分，也不包含VAD分支。

本目录复用 [W0 demo](../w0_demo/README.md) 的 `read_audio`、`FrozenVad`、`PyannoteVad`、
`run_pipeline` 完整文字与源时间验证及 `MmsAligner`，不复制 MMS 或整个 W0 pipeline。
模型路径、GPU 前向、jpn adapter、FP32、TF32 和 CTC 行为沿用同一个对齐器。
Qwen 部分以小 Adapter 保持历史 `run_qwen.py` 的 native Transformers processor／generate 路径：
日语、BF16、SDPA、`do_sample=False`、4096 token、batch1，各窗独立，无前文 conditioning。
保留 Qwen 自有特征处理和有效长度，不迁入 Whisper 的 Mel、补零或解码选项。

| 变体 | 音频保留与切点 |
| --- | --- |
| `fixed30` | 无 VAD，固定30秒及末尾余段；新的 X0＋MMS 对照 |
| `energy` | 保留全部样本；从每块30秒上限之前5秒内，以100ms网格计算切点之前100ms RMS，选最小值；并列取最接近上限的切点；最长30秒，末尾余段不再搜索 |
| `pyannote` | 原样复用 W0 已测 Pyannote 检测、min-cut 与30秒跨度合并；滤去窗口外音频，保留窗内静音；另立实验身份 |

`energy` 是独立、受30秒上限约束的建议策略，并非 WhisperX 或旧 Qwen wrapper 的严格移植。
它没有静音阈值，也不区分说话、歌声、音乐。所有变体没有降噪或人声分离。
Pyannote 的原始秒坐标在 Qwen 与 MMS 间原样保留，二者裁剪同一整数样本范围；
不采用 W0 Whisper Adapter 为展示导出分段时的三位小数舍入。

## 分阶段运行

Transformers 5.18 的 Qwen 环境与既有 MMS／Pyannote 环境分开运行。先在仓库根目录执行计划，再 ASR，再 MMS：

```powershell
.local/envs/whisper-latest/Scripts/python.exe -m experiments.x0_flow.run plan --audio .local/round2/corpus/audio/hf-ii-window-01.wav --offset 351.402125 --variant fixed30 --out .local/x0-flow/my-run/fixed30
.local/envs/qwen-hf-final/Scripts/python.exe -m experiments.x0_flow.run asr --run .local/x0-flow/my-run/fixed30
.local/envs/whisper-latest/Scripts/python.exe -m experiments.x0_flow.run align --run .local/x0-flow/my-run/fixed30
```

另以 `--variant energy` 或 `pyannote` 创建新输出目录。CLI `--help` 列出本地模型及 DLL 参数。
输入须 mono／16 kHz／PCM16 WAV，源偏移有限非负；推理离线，不获取权重，不改变源音频。
极少数末尾整数样本数无法同时满足继承的 W0 秒坐标上界及 `int(seconds*16000)` 精确裁剪，
会明确拒绝，不能静默丢失样本；本轮300秒窗口无该限制。
`--frozen-vad` 仅接受同输入 hash 与偏移的 W0 结果；冻结检测成本不作为真实 VAD 成本。

计划目录必须是 `.local/x0-flow/` 下的新子目录。各阶段拒绝覆盖已经完成的输出。
`plan.json` 保存输入与 PCM hash、offset、精确样本边界、保留／移除样本数、切点依据和 VAD 参数；
`source/` 与源码 hash 冻结全部相关实现，后续阶段拒绝源码或输入变化。
`asr.json` 保存新 ASR 全文、token、每窗音频 hash、设备、特征形状、有效参数、权重／上游实现身份与耗时；
`result.json` 以共享 pipeline 验证完整文字、每个字符及源时间坐标，保存新的 MMS 记录与环境／模型身份。
完整文本与私有结果只在 `.local`；控制台只输出计数、阶段耗时和路径。
ASR 结果跨进程传递是同次新运行的阶段衔接，不视为跨实验复用缓存。

GPU 阶段沿用共享 `.local/gpu.lock`；锁文件中的既有 W0 recipe 标签只是共享锁实现的标识，
结果的真实 recipe 为 `x0-flow-v1`。若锁已存在，检查对应进程，不能删除活跃锁。
`stages.total_pipeline_s` 是三个阶段内部耗时之和；外部进程启动、模型文件最终 hash 等成本
由外层实验 driver 的完整进程计时记录，不能把内部计时当端到端墙钟。
ASR／MMS 都必须 CUDA GPU；失败不回退 CPU。当前 Pyannote Adapter 沿用 CUDA，
并不代表项目禁止未来采用 CPU VAD。

## 本轮评分

预登记方案见[最小验证](../../docs/plans/x0-whisperx-flow.md)，结论及限制见
[研究报告](../../docs/research/2026-10-05-x0-whisperx-flow.md)。两片各 window-01 的三臂结果齐备后运行：

```powershell
.venv/Scripts/python.exe -m experiments.x0_flow_evaluate --study .local/x0-flow/pilot-v1 --out .local/x0-flow/pilot-v1/evaluation-v1
```

使用新输出目录，复用既有全文／完整分母评分及 round2 边界规则，不做两窗 bootstrap。
评分前后核验音频／参考身份，逐段核对实际 GPU、ASR PCM hash 与 MMS 搜索样本范围；
生成触顶不算合格执行，完整输出仍保留。汇总含漏字、插字、字面重复候选、时间覆盖、严重偏移和外部进程成本。
字面重复不自动等于误识别，保留真实歌声也不算 VAD 误报。

## 离线测试

```powershell
.venv/Scripts/python.exe -m unittest discover -s experiments/x0_flow -t . -v
.local/envs/whisper-latest/Scripts/python.exe -m unittest discover -s experiments/x0_flow -t . -v
```

根环境没有 NumPy 时显式跳过音频数组测试；后端环境完成样本守恒、30秒边界、低能量切点、
并列规则、短尾段、完整文字、text_only 与源偏移契约。测试不加载模型；真实推理与质量结论另记。
本目录尚未接入根 `just test`；可直接按上述命令独立运行。
