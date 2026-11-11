# 03 VAD／ASR(w0)／对齐三个 worker

Status: done
Type: task
Blocked by: 01, 02

## 范围

- 架构（[目标架构](../../../docs/architecture/bilingual-pipeline-architecture.md)"VAD""ASR 引擎""对齐"行）：推理模块的接口是"加载一次、按窗口推理"的两个方法，输入输出是内存对象与 WAV 本地坐标，只依赖基础层且互不导入，不读写产物、不判断跳过、不打印；文件读写、身份、进度与 `failed_windows` 记账全在 `workers/<stage>.py` 薄壳，薄壳经 `protocol.run_worker` 组装，每个 `__main__` 十行以内。ASR worker 按 `config.engine` 选择适配器（本票只有 `asr_whisper`，07 加 `asr_qwen`），两个适配器写出同一种 `asr.json`。
- `kototoki/vad.py`：复制 `CurrentPyannoteVad` 与 `chunk_intervals`，内存波形输入，设备固定 `cuda:0`，适配 pyannote 4.0.7；worker 写 `vad.json`（输入身份、`offset_s`、整数样本窗口、segments、stages，坐标为 WAV 本地）。不加 FFmpeg PATH：01 smoke #2（2026-10-14）实测导入与内存波形推理全程不加载任何 FFmpeg DLL。
- `kototoki/asr_whisper.py`：复制 `w0_demo/asr.py`，torch 特征链不变；去掉私有 DLL 目录与 PATH 逻辑；模块内**显式先 `import torch` 再导入 `ctranslate2`／`faster_whisper`**，并有导入顺序测试（伪模块记录导入次序）。01 smoke #3：CT2 会按全路径加载自带的 `cudnn64_9.dll`（9.10 调度器），与 torch 的 9.19 并存，用户已接受，不要尝试拦截；CT2 在 sm_120 上依赖 PTX JIT，首次解码约 27 s、之后约 5 s；worker 写 `asr.json`，窗口失败按协议 `failed_windows` 记账。
- `kototoki/align.py`：复制 `alignment.py`，版本断言放宽到 torchaudio ≥2.10 并记录实际版本；字典只取 id < `model.config.vocab_size` 的词表项（transformers 5.19 的 `Wav2Vec2CTCTokenizer` 多出 added token `|`＝2268，超出模型 2268 类，01 smoke #1；不过滤会改变 `character_targets` 对 `|` 的处理）；`map_records` 继续用 `offset_s` 参数（产品传 0，不另加）；worker 写 `align.json`（现有 `result.json` 结构，`validate_transcript` 通过）。
- worker 共同：离线环境变量（`HF_HOME`／`TORCH_HOME` 指向 `<output_dir>/.work/cache/`，由编排器传入）、`PYTHONUTF8=1`；按 `workers/protocol.py` 增量写结果、单文件失败继续、CUDA 粘性错误退出码 2。

## 完成标准

- 冻结窗口（`.local/round2/corpus/audio/hf-ii-window-01.wav`）三阶段结果与现有同窗结果对照：窗口整数边界一致；ASR 文字逐字符一致（不一致即不通过）；units 覆盖全文、时间在源范围内，每个 unit 起止与现有结果差 ≤20 ms（1 帧）。文字不一致阻塞本票；时间超差另开票分析，**不阻塞 05／06**。
- 模块页：VAD 阶段、W0 pipeline、MMS 对齐改指向产品代码（或新建产品模块页并让旧页指向它）。

## 文件所有权

`kototoki/vad.py`、`asr_whisper.py`、`align.py`、`schema.py`、`workers/vad.py`、`workers/asr.py`、`workers/align.py`、对应测试。

## Comments

- 2026-10-13 建票，依据规格 §12。
- 2026-10-14 按两轮评审修订（规格 §13）。
- 2026-10-14 整体 CUDA 12.8 后取消无 torch worker 要求。
- 2026-10-14 第三轮评审：导入顺序与测试；FFmpeg PATH 视 smoke #2；`offset_s` 不再加；门禁加 ±20 ms 容差且时间差不阻塞后续票。
- 2026-10-14 票据 01 回写：VAD 不加 FFmpeg PATH；CT2 自带 cuDNN 调度器并存已被接受；MMS 字典按模型类数过滤 `|`。依据 `.local/smoke/20261014T045328Z/`。
- 2026-10-14 实施（分支 `feat/bilingual-03`，worktree `D:/AI_Projects/kototoki-03`）：推理模块 `kototoki/vad.py`、`asr_whisper.py`、`align.py` 与基础层 `schema.py`；worker 壳 `workers/{vad,asr,align}.py`，三壳共用的入口、读 WAV、模型 SHA256 核对、CUDA 守卫与写产物放新文件 `workers/gpu.py`（用户裁定，不改 00 的 `protocol.py`）。core 测试 5 个文件；冻结窗口门禁 `python -m tests.stt_frozen_window`（full）首次运行全等：8 窗整数边界、8 窗文字与 token、549 个 unit 的范围／状态／1048 个起止时间（最大差 0），产物 `.local/stt-gate/20261014T070454Z/`。模块页 [STT worker](../../../docs/architecture/modules/stt-workers.md)；旧 VAD／W0／MMS 页加指针。
- 与旧 experiments 的差别（以规格为准）：`asr.json`／`align.json` 产物形状为新定；`MmsAligner` 字典按模型类数过滤、TorchAudio ≥2.10；ASR 单窗 `RuntimeError` 记为失败窗口而非整片失败；去掉 `FrozenVad`、legacy 秒窗口（ASR 只收整数样本窗口）与私有 DLL 目录。规格 §7.1 两处与架构页不一致已改：引擎取 jobs `config.engine`（无 `--engine`），离线环境由编排器设置。
- 接口细节（供 06 使用）：jobs `config` 需要 `models`（`Config.models` 同名键）、`model_cache`，ASR 另需 `engine`；`recipe_hash` 必须等于 worker 自己的配方 hash。壳模块导入不加载 torch，06 可直接调用 `workers.<stage>.identity`／`model_files`／`recipe_hash` 与 `gpu.verify_models` 计算期望身份；`audio-16k.wav` 的 upstream 值是 PCM 数据块 SHA256（与 `Extract` 记录的一致）。
- 顺手修复：main 上 `docs/architecture/INDEX.md` 与目标架构页末段残留的 02／04 合并冲突标记（两侧内容都保留）。
- 遗留：真实 CUDA 粘性错误与窗口级 OOM 只有伪对象测试；冻结窗口门禁在 torch 2.11 下 MMS 结果与 torch 2.8 记录全等，整片未验证（08）。06 设置 worker 环境时需像 smoke 一样从 PATH 去掉 `whisper-runtime-provisional`（本机 PATH 上存在该私有 DLL 目录）。
- 2026-10-14 用户裁定：门禁接入 `just test-full`（经用户同意改 01 的 `scripts/smoke/run_all.py`，门禁脚本改为由其持锁启动、`--out` 输出，不再自取锁）；jobs `config` 约定认可；模型期望 SHA256 留在各 worker 壳。接入后的 `just test-full stt_frozen_window` 尚未实跑。
