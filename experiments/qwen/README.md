# 官方 Qwen native HF 实验入口

状态：适配器和冻结环境已完成，开发片段 ASR/FA 原生 CUDA 推理已验证；
字幕时间质量仍在筛选，整片稳定性、重复性和独立保留测试尚未验证。  
日期：2026-10-04。用途仅为本地 STT 选型实验。

当前X0（Qwen＋新Pyannote＋MMS）的持续运行和开发入口为[X0 demo](../x0_demo/README.md)。
本目录保留Q0及历史X0实验；`run_cross.py`的旧默认对齐器不能视为当前MMS基线。

版本与来源见[执行核查](../../docs/research/2026-10-04-qwen-execution.md)。不加载旧版
`qwen-asr` wrapper，不接受网络模型 ID，不自动下载模型。ASR 和 FA 顺序驻留 GPU；
音频和 nagisa 文本处理使用 CPU，神经网络推理强制 CUDA。

```powershell
& .local/envs/qwen-hf-final/Scripts/python.exe experiments/qwen/run_qwen.py `
  --audio .local/audio/dev.wav --output .local/results/q0-dev.json `
  --asr-model .local/models/qwen3-asr-1.7b-hf `
  --aligner-model .local/models/qwen3-forcedaligner-0.6b-hf --offset 0
```

输入必须是已明确解码的 mono 16 kHz WAV。默认单窗口，FA 输入上限 300 秒。
`--window-seconds 120` 是适配器显式连续切窗诊断，保留每窗输入样本范围和 PCM 哈希，
没有 overlap、参考字幕辅助切窗或去重。native Transformers helper 本身没有 VAD，
也没有原 `qwen-asr` wrapper 的长输入切窗；因此不能将此切窗诊断称为原 wrapper 默认流程。

默认语言 `ja`、BF16、SDPA、greedy、batch 1、`max_new_tokens=4096`，记录 token
上限是否达到。BF16 和 SDPA 是本轮显式选择；完整有效 generation config 在运行记录中保存。
`--attention eager` 和 `--dtype float16` 是有依据时的单因素诊断。
`--alignment-only .local/text/frozen.txt` 仅供固定文字 FA 诊断，结果不能计作独立 ASR。

输出路径必须尚不存在，防止覆盖旧实验记录。模型权重每次核对冻结的 SHA256，配套配置、
tokenizer 和 template 的哈希另存；文件完整性核查耗时单独记录。
输出保留完整文字、native FA API 输出、修正前 timestamp class ID、修正数量、CUDA
参数/输入/输出设备和峰值显存。API 时间经过上游 LIS 修正，标为 `time_source=api`。
缺失或无法映射的文字保留为 `text_only`，不生成虚假字时间。此入口暂不生成字幕 cue，
统一 writer 由主实验工具处理。总耗时从 Python 依赖导入后开始，冷启动进程耗时需要外层记录。

离线、无需 GPU 的映射验证：

```powershell
& .local/envs/qwen-hf-final/Scripts/python.exe -m unittest discover -s experiments/qwen -p test_adapter.py -v
```

环境为 Python 3.13.16；62 个包已按 [hashlock](requirements.lock) 安装，
`uv pip check` 通过。完整安装列表见 [installed-requirements.txt](installed-requirements.txt)，
CPU 导入、synthetic 日语分词和 processor 预处理证据见 [environment.json](environment.json)。
恢复环境时固定上述 Python，在独立环境运行：

```powershell
uv pip sync --python .local/envs/qwen-hf-final/Scripts/python.exe `
  experiments/qwen/requirements.lock --require-hashes --index-strategy unsafe-best-match
```

现有 README、AGENTS 和既有开发文档已复核；共享项目状态和索引由主 agent 维护。

## 缓存 Q0 文字交给 WhisperX CTC 的诊断桥接

`export_ctc_input.py` 验证已完成 Q0 的模型/config 身份、原 WAV 与 float32 PCM
哈希、每个原 ASR 窗口的 PCM 和 CUDA 参数/输入/输出证据，然后保留所有窗口文字，
将原样本范围转为相对音频秒数。这里的范围是 ASR 输入窗口，不是声学时间预测；
不读取参考 SRT，不使用已经失败的 Qwen FA 时间，也不改变识别文字。

```powershell
& .local/envs/qwen-hf-final/Scripts/python.exe experiments/qwen/export_ctc_input.py `
  --asr-result .local/results/q0-ch01-cuda-window30-r1/result.json `
  --audio .local/audio/chapter-01.wav --offset 10 `
  --output .local/analysis/qwen/q0-ch01-window30-to-ctc.json
```

现有 W1 consumer 的 `input.pcm_sha256` 是原始 PCM16 bytes 哈希，Q0 使用 decoded
float32 bytes 哈希。桥接明确保留两个身份：前者按 W1 合约保存，后者放在
`input.float32_pcm_sha256`，并验证 PCM16/32768 与 Q0 解码 float32 逐样本相等。
原 WAV SHA256、Q0 result SHA256、模型 revision/config、CUDA 证据与 exporter SHA256
均保留在 provenance。缓存 ASR 不计为新 ASR 推理或性能；CTC 推理由统一 GPU 队列
另行执行。生成 cap 命中的源结果被拒绝用于工程比较，已有输出不会覆盖。

桥接的身份检查已通过；真实 chapter-01/02/05/07/17
的 Q0 30 秒结果已分别导出 8/3/10/10/14 个窗口并通过身份核验。
CTC 组合的质量仍需实际推理和统一评测，不能依据导出成功宣称时间目标达标。

```powershell
& .local/envs/qwen-hf-final/Scripts/python.exe -m unittest discover -s experiments/qwen -p 'test_*.py'
```

统一 `just test` 的标准库环境执行 13 项映射、模式和流水线测试；缺少 NumPy/SoundFile
时明确跳过 7 项桥接测试。以上 Qwen 固定环境命令完整执行 20 项，跳过不计作桥接验证通过。

## 新 ASR 与 CTC 的完整串行入口

`run_qwen.py --asr-only` 使用同样的冻结 ASR 参数、固定窗口和 CUDA 检查，省去 Qwen
FA 的目录校验、哈希、加载及推理。保留完整文字和原输入窗口；其字符单元为
`text_only`，时间为 null，`alignment_status=not_requested_asr_only`，不能拿输入窗口
当字幕时间。`--asr-only` 与 `--alignment-only` 互斥；兼容保留 `--aligner-model` 参数，
ASR-only 不访问该目录。默认不加此参数仍为完整 Q0 流程。

主 agent 的 chapter-07 真实运行证明 ASR-only 与旧完整 Q0 的全文、每窗文字、样本
边界和音频身份一致，实际 models/devices 只有 ASR。并行 CPU 工作下两次全进程耗时
不支持速度改善结论，这里只记录流程等价性。

`run_cross.py` 在一次外层 GPU harness 内顺序执行新 ASR-only、导出和 WhisperX
normalized standard CTC。它没有内层 GPU 锁或采样器，不自行下载模型，也不调参。

```powershell
uv run --locked --offline python experiments/qwen/run_cross.py `
  --audio .local/audio/chapter-07.wav --offset 1438.427 `
  --output .local/results/x0-fresh-ch07-r1/result.json `
  --dll-dir .local/tools/whisper-runtime-provisional
```

实际实验应由项目的 `experiments/run_experiment.py` 外层排队/采样器调用以上命令。
Qwen/Whisper 解释器和模型均有项目本地默认值，亦可用 `--qwen-python`、
`--whisper-python`、`--asr-model`、`--ctc-model` 等明确指定。ASR 固定 ja、BF16、SDPA、
greedy、batch 1、30 秒、4096 token；CTC 固定零 padding、原生 nearest 插值和
normalization/standard forced token spans，沿用既有选定配置。

每个新输出旁生成 `result-stages/`，保存实际执行的 Qwen/Whisper 源码副本、哈希、
阶段输出和日志。CTC 消费的是同次运行新 ASR 的导出；导出自身仍诚实标为组件缓存。
最终结果标为 `fresh_end_to_end`，同时明确阶段复用和 ASR/CTC CUDA 证据链接。
每阶段墙钟含独立进程冷启动；流水线墙钟还含导出、源码复制及校验，不用历史阶段
耗时相加冒充新运行。内部墙钟不含最终结果序列化及入口启动，完整进程速度以外层
harness 为准。失败或 token cap 会终止后续阶段，保留已有输出，不能覆盖同名运行。

入口同时核验模型 forward、归一化后的实际输入和 standard CTC 解码器输入/输出为
CUDA，且各阶段 segment 记录一一对应。CTC helper 捕获的任何解码失败均标为
`alignment_failure`，即使子进程退出码为 0，也不能记作完整成功；保留原 ASR、桥接、
CTC JSON 和日志，不回退。空或不含字母/数字的识别文字在没有 forward 时明确记为
`no_forward_empty_or_nonlexical_text`，不宣称执行了对齐；有文字内容却缺少 forward
则失败。这些检查已只读核验既有五章组件结果的 8/3/10/10/14 组实际 CUDA 记录。

5 项假 subprocess 测试验证源身份异常时停止、CTC 失败保留前序证据、成功时实际
调用源码副本，以及成功退出码中的解码失败/设备错误和空文字例外。

主 GPU 队列的 `x0-fresh-ch07-r1` 已完成真实端到端探针，CPU 独立取证保存于
`.local/analysis/qwen/x0-fresh-probe/evidence-r1.json`（SHA256
`e6235a896cf85d53aaab4c5b285db0398e0337478a7cf87911f7c4fb0b4d7612`）。7 个执行源码
副本及三阶段输出 SHA256 均吻合运行记录。新 ASR 与原 `q0-ch07-cuda-window30-r1`
的完整文字、音频身份、10 窗样本范围/offset/PCM/原始 decode/559 个生成 token 及
CUDA 证据逐项相同，唯一新增配置字段为 `asr_only=true`，models/devices 只有 ASR。
新 CTC 与原缓存组件实验的完整评测输入、units、cues、native_evaluation、全部
decoder/normalization 记录及模型身份完全相同；10 组 forward、归一化输入和
decoder 输入/输出均为 CUDA，没有解码失败或 generation cap。

因此相同 scoring-v2 规则下质量与该旧开发结果等价：637 个参考字符 S/D/I=77/9/18，
CER 16.33%；可测 40/62，条件 E-P95/P99=1.269/1.555 s，完整分母 <500 ms
35/62（不确定性上界 39/62）。这是基于完整评测输入逐项相等的分数等价证明，
不是新执行的评分或新增独立样本；SRT 仍非人工声学真值。

这次真实全进程墙钟为 65.214 s，内部流水线为 64.584 s；独立子进程 ASR/导出/CTC
分别为 52.749/0.268/11.486 s。ASR generate 累计 40.577 s、加载 2.831 s，
ASR peak allocated/reserved 为 4,346,934,784/4,594,860,032 字节；CTC 加载
3.935 s、对齐 3.722 s。ASR 和对齐阶段都是本次新推理，CTC 输入的组件复用指向
同次生成的 ASR，不能将它误记成历史缓存 ASR。旧组件的 14.715 s 全进程时间只含
CTC，不可当作端到端速度；这次仅一章、CPU/网络准备可能并行，不支持速度提升、
整片连续性或正式性能稳定性结论。未读取验证或保留集结果。
