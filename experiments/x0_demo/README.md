# X0 可复用 demo

状态：可复用 demo 已实现；当前采纳 newPyannote 基准线，须显式选择 VAD manifest  
最后更新：2026-10-05  
范围：原生 Windows、本机已准备的 Qwen／MMS 环境与资产；持续迭代入口。

后续 session 运行或修改 X0，复用并更新此目录。先读
[X0 契约](../../docs/specs/x0-reusable-demo.md)、
[当前基准线](../../docs/architecture/stt-candidate-pipelines.md)及
[当前采纳决定](../../docs/adr/0003-new-pyannote-baselines.md)。
`experiments/x0_flow/` 保留为历史研究证据；新的 cut-merge recipe 与其 `energy` 策略不同。

与W0共同测试、回归或比较时，先读[标准基线测试指南](../../docs/guides/baseline-testing.md)；本README维护X0具体使用方法。

当前 X0 为 Qwen＋newPyannote＋MMS，无降噪、无人声分离。只吸收适用于 Qwen 的
WhisperX 思路：检测后的源窗口切分合并、逐块独立纯文字识别后对齐，以及明确原生特征输入契约。
本次只更新文档；代码无参数默认仍为 fixed30，须显式传 `--segmentation vad --vad-manifest` 才运行当前基线。

## 运行

在仓库根目录，先独立执行 newPyannote，再用根项目 Python 发起一次 X0 命令；X0 脚本依次启动已配置的
`whisper-latest` 规划子进程、`qwen-hf-final` ASR 子进程及 `whisper-latest` MMS 子进程。
不安装、升级或获取权重，子进程有独立模型生命周期，GPU 锁由父进程持有至全部阶段结束。

```powershell
.local/envs/vad-pyannote-gpu-v1/Scripts/python.exe -m experiments.vad_comparison.vad_stage --audio .local/round2/corpus/audio/hf-ii-window-01.wav --offset 351.402125 --out .local/vad-comparison/baseline-newpyannote-01 --vad-id pyannote-current --model .local/models/vad-comparison/pyannote-segmentation-3.0/pytorch_model.bin --revision e66f3d3b9eb0873085418a7b813d3b369bf160bb --device cuda:0
.venv/Scripts/python.exe -m experiments.x0_demo.run --audio .local/round2/corpus/audio/hf-ii-window-01.wav --offset 351.402125 --out .local/x0-demo/my-newpyannote-01 --segmentation vad --vad-manifest .local/vad-comparison/baseline-newpyannote-01/manifest.json
```

同一输入、offset 的 W0／X0 比较可共用一次新生成的 manifest；不要重复创建上述已存在的 VAD 输出目录。
工具链已激活时可用等价入口 `just x0-demo --audio ... --out .local/x0-demo/my-newpyannote-02 --segmentation vad --vad-manifest ...`。
要复现保留全部音频的低能量实验，在新输出目录使用 `--segmentation cut-merge` 且不传 manifest。

newPyannote 为 pyannote.audio 4.0.7＋segmentation-3.0 powerset，revision 见命令，
onset／offset 0.5、min_duration_on／off 0。采用原生检测，再对源样本区间取并集、
超长区间硬切到最多30秒并按源跨度贪心合并。它没有照搬旧 PyanNet min-cut；Qwen 特征与解码保持原生。
固定30秒与低能量 cut-merge 保留独立历史／对照身份，采用 newPyannote 不等于它普遍改善 X0 质量。

输入须 mono／16 kHz／PCM16 WAV。源文件剪出的窗口通过有限非负 `--offset` 映射源时间。
目录必须是 `.local/x0-demo/` 下的新子目录，已有目录拒绝覆盖。模型、两套解释器及 DLL 目录可通过
`--help` 查看和指定本机路径；`--help` 不需要 NumPy、Torch 或模型。

| recipe | 分段行为 |
| --- | --- |
| `x0-demo-fixed30-v1`，代码无参数默认 `--segmentation fixed30` | 历史基准线／回归身份；固定最多 30 秒及任意样本长度的末尾余段，保留全部音频 |
| `x0-demo-cut-merge-v1`，`--segmentation cut-merge` | 每个非末尾的 5 秒区域以 100 ms 网格计算切点前 100 ms RMS，取最小值，并列取最后切点；加入起点／末尾，再按原音频跨度贪心合并相邻候选段到最多 30 秒 |
| `x0-demo-vad-source-windows-v1`，`--segmentation vad --vad-manifest PATH` | 当前基准线使用 `vad_id=pyannote-current` 的 manifest；通用 recipe 需连同 vad_id、外部 recipe、模型身份区分其他候选 |

cut-merge 在源时间上合并相邻短候选段，保持整数样本连续，无重叠、删除、重复或波形变换。
最后不超过 5 秒的区域直接保留到末尾；不足 5 秒也能运行。候选点没有静音阈值，不判断对白、歌声或音乐。
fixed30／cut-merge 两个 recipe 都无 VAD、降噪或人声分离；当前 newPyannote 基线有 VAD，窗口外样本可被过滤。
原 cut-merge 采纳依据是边界正确性、可维护性和完整音频保留，见[历史 ADR-0002](../../docs/adr/0002-x0-demo-flow.md)，
不要求在少量验证窗口获得更高评分，也不宣称 cut-merge 已证明一般质量收益。

## 当前基准线与独立 VAD manifest 契约

当前 newPyannote 基准线及其他显式 VAD 比较都通过外部冻结 manifest 接入：

```powershell
.venv/Scripts/python.exe -m experiments.x0_demo.run --audio .local/round2/corpus/audio/hf-ii-window-01.wav --offset 351.402125 --out .local/x0-demo/vad-check-01 --segmentation vad --vad-manifest .local/vad-comparison/baseline-newpyannote-01/manifest.json
```

两个参数必须一起使用；manifest 必须为 `schema_version=1`、`status=ok`，包含 `vad_id`、VAD `recipe`、
`metadata`、`stages`（含非负有限的 `vad_load_s`／`vad_inference_s`）、与当前 WAV 内容匹配的 `input`
以及相同 `offset_s`。输入身份至少核对 `file_sha256`、`pcm_sha256`、`sample_rate`、`channels`、`samples`、`duration_s`；
路径可以不同。`chunks` 是按 WAV 本地时间排序、互不重叠的 `{start,end,segments:[[start,end],...]}` 源窗口。
窗口含成对 `start_sample/end_sample` 时直接保留该整数裁剪，秒坐标必须与整数一致；没有整数时与 W0 一样
以秒乘 16000 向下取整并限定到原音频范围。整数窗口须非空且最多 480000 样本。

每个窗口仍裁剪原音频整个跨度，保留窗口内部短间隔，不拼接波形。窗口外样本允许丢弃，
`retained_samples`／`removed_samples` 显式记账；源偏移和总时长仍描述完整输入。候选 VAD 参数、设备及权重身份
由外部 manifest 的 `metadata` 保存，不改变 Qwen native processor 或 MMS 数值配置。
VAD 没有输出窗口时写出空全文与空 units，跳过 Qwen／MMS 模型加载，明确记录 `skipped_no_speech`。

父进程在启动子阶段前将 manifest 原始字节冻结为 `vad-manifest.json` 并记录 SHA256；每阶段重验冻结证据。
`vad_provenance.precomputed_stages` 保留外部 VAD 耗时，`stage_execution.vad` 明确为 `precomputed_external_manifest`。
X0 自身 `stages.wall_s`／`process_costs` 只包含读取 manifest 后的 X0 流程，**不包含外部 VAD 进程成本**；
完整 VAD＋ASR＋MMS 比较须由父比较流程另外累计 VAD 完整进程墙钟，不能把导入当成 X0 中的新 VAD 推理。

## 模型边界与证据

`asr.py` 从历史 `x0_flow/asr.py` 的小 Qwen Adapter 提升而来，复用历史 Qwen 资产身份核验辅助函数。
日语原文转写、CUDA BF16、SDPA、`do_sample=False`、4096 token、batch1；每块独立请求，无前文 conditioning。
采用 Qwen native processor／有效长度，记录实际输入 tensor 形状、设备及生成 token；不移植 Whisper 的
Mel、固定补零、token 提示或 CT2 参数。采纳 WhisperX 可跨模型的 source-window 切分合并、
独立纯文本识别后再对齐和明确特征输入契约；已有等价行为不重复算作新优化。

音频读取与 MMS 直接复用 W0 的 `read_audio`／`MmsAligner`，不复制 MMS 或完整 W0 pipeline。
ASR 与 MMS 都从相同 `start_sample`／`end_sample` 裁剪；秒数只描述这些整数边界，1001 等任意尾样本数不会丢失。
MMS 使用既有 CUDA FP32、jpn adapter、归一化和固定 TF32 策略，不回退 CPU。
完整文字、每个字符、`text_only` 与源时间由后端无关验证守护；OOV／缺失词汇时间保留文字。
CTC nonblank span 不等于声学真实时长。本轮仍固定日语，不实现翻译。

模型与许可来源沿用[环境清单](../../docs/research/2026-10-04-runtime-inventory.md)和
[MMS 记录](../../docs/research/2026-10-04-japanese-ctc-source-verification.md)。
共享 MMS 的移植许可仍由 [W0 THIRD_PARTY_NOTICES](../w0_demo/THIRD_PARTY_NOTICES.txt) 维护，运行时一起冻结。

`source/` 与 `source-manifest.json` 在启动子进程前冻结相关源码；每阶段重验源码及输入身份。
`request.json`／`plan.json` 保存输入 hash、原始 PCM hash、样本数、offset、候选点、合并构成及参数。
`asr.json` 保存新识别全文、token、每窗 float32 PCM hash、实际设备、包／模型／上游实现身份与耗时。
`alignment-evidence.json`／`alignment.json` 保存同次 MMS 全文及 CTC 记录；最终 `result.json`／`transcript.txt`
保存完整结果。JSON 未获时间的字符不会从全文删除。所有私有内容、缓存和临时文件都在新输出目录。
父进程清理临时目录，保留失败证据；控制台仅输出状态、数量、耗时和路径，子进程日志保存在私有目录。

`stages.*_process_wall_s`、`process_costs` 和 `process-costs.json` 记录完整子进程启动至退出成本与计数；
`stages.wall_s` 记录父流程墙钟。内部 `*_load_s`／`*_inference_s` 不是端到端时间。
父进程共用 `.local/gpu.lock`，已有锁时拒绝运行，不能删除活跃锁。

生成达到 4096 token 上限或阶段失败会非零退出，保留 `asr-partial.json`、已完成阶段和 `failure*.json`，
不运行后续推理。MMS 个别段推理失败仍保存完整文字及 `text_only`，最终状态 `partial`、记录失败段，CLI 退出码为 2；
正常 OOV 的 `text_only` 不视作 GPU 推理失败。取消时终止当前子进程并清理临时目录，完整 Windows 取消／OOM 恢复仍需另外验证。

## 测试与后续迭代

```powershell
.venv/Scripts/python.exe -m unittest discover -s experiments/x0_demo -t . -v
.local/envs/whisper-latest/Scripts/python.exe -m unittest discover -s experiments/x0_demo -t . -v
```

测试使用小合成数组或假子阶段，不加载模型。根环境缺 NumPy 时显式跳过数组测试，后端环境补测。
覆盖固定分片和 cut-merge 样本守恒、实际合并、静音／连续音并列规则、奇数尾长、非法窗口、完整文字、
`text_only`、偏移、cap、失败后阶段保留、输出拒绝覆盖及完整子进程成本记账。
VAD 扩展另覆盖输入／偏移不匹配、错序／重叠／超长窗口、manifest 篡改、整数边界浮点往返、
窗口内部间隔保留、删除样本记账、冻结字节、空检测跳过模型及外部成本分离。
真实验证范围见[验证记录](../../docs/testing/2026-10-05-x0-demo-validation.md)；离线测试通过不证明声学准确率。

改行为时更新对应 recipe 身份、边界测试和受影响的文档，新建私有运行目录；保持历史结果与源码身份。
候选切点策略可单独替换，ASR／MMS 共用整数源窗口契约。新的对齐、特征、批量、语言或模型配置需要分别验证。
本页早期两窗验证不自动扩展为 newPyannote 的验收；最新两片整片证据见
[整片报告](../../docs/research/2026-10-05-fullfilm-segmentation-comparison.md)。整片 worker 失败后继续的规则
仅属于该实验，canonical demo 的生成触顶退出策略保持现有实现。
