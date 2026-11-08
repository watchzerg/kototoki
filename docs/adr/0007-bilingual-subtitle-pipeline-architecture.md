# ADR-0007：中日双语字幕流水线的产品架构

状态：已接受，已实现。合并整理于 2026-11-08（吸收 2026-10-14 评审修订与 ADR-0011、ADR-0012、ADR-0014 带来的阶段与配方变化；历次变更见[决定索引·演进链](INDEX.md#演进链)，原文见 Git 历史）。第 3 点中"翻译用独立进程的官方 llama.cpp"自 2026-11-08 起由 [ADR-0019](0019-product-translation-q2.md) 替代（翻译改用产品自动启停的 Strata；建表仍用 llama.cpp）。  
范围：产品包 `kototoki/` 的工程架构。模型与配方身份不在此决定：STT 见 [ADR-0003](0003-new-pyannote-baselines.md)、[ADR-0012](0012-cross-asr-judge.md)，翻译见 [ADR-0005](0005-apex-i-compact-translation-baseline.md)、[ADR-0010](0010-dp10-cut-translation-flow-baseline.md)，专名见 [ADR-0014](0014-name-consistency-in-product.md)。完整设计见[技术设计](../specs/bilingual-subtitle-pipeline.md)与[架构总览](../architecture/INDEX.md)。

## 决定

1. **GPU 阶段按"阶段 × 整批"推进，每阶段一个子进程。** 阶段链为 `vad` → `asr` → `align`（MMS）→ `cues` → `names` → `translate`（`kototoki/plan.py` 的 `STAGES`），publish 是终态。加载一个模型跑完整批再卸载；CPU 阶段（ffmpeg 提取、cue 切分、合并）是独立队列，可与 GPU 并行。不提供批次切分参数。
2. **翻译单元是日文 cue，不是 ASR 窗口文本。** 翻译输入固定为 `ja.srt`，每条中文继承日文 cue 的编号与时间，与日文一一对应。
3. **一个统一的 CUDA 12.8 Python 环境**：Python 3.13、torch 2.11.0+cu128、torchaudio 2.11.0、torchcodec 0.17.0、transformers 5.19、pyannote.audio 4.0.7、faster-whisper 1.2.1／CTranslate2 4.8.3，由根 `pyproject.toml` 经 uv 管理（Torch 走显式 cu128 索引）。选版规则：CUDA 12 与 Python 3.13 是锚点，受其限制的组件一起锁定，其余取最新稳定版。翻译与建表用独立进程的官方 llama.cpp `win-cuda-13.4` 构建，与 Python 进程无 DLL 交集，不打兼容补丁；版本以[技术选型](../development/technology-stack.md)为准。
4. **翻译失败降级**：批次终态失败时 10→5→1 拆批重试；单条仍失败则该条保留日文并写入报告，整片照常交付。产品配方名与参数以 [ADR-0010](0010-dp10-cut-translation-flow-baseline.md) 为准（现为 `dp10-cut-degrade-v1`）。
5. **设备**：ASR 与强制对齐只跑 GPU，不回退 CPU；VAD 固定 `cuda:0`，不设配置键，破除死锁用一次性环境变量。
6. **配置文件驱动，无 CLI**：入口 `python -m kototoki`，输入／输出／模型目录、并发、cue 显示规则、翻译 seed、`[stt] engine`、`[names]` 等放 `kototoki.toml`；解码、采样、提示、窗口等影响模型行为的常量留在代码里作为配方常量，改动即新配方 hash。
7. **产物与续跑**：每个视频一个工作目录，所有中间产物（原始编码音轨流复制、16 kHz WAV、VAD／ASR／对齐 JSON、cue JSON、专名表、翻译 run）全部保留并带输入身份与配方 hash；产物匹配即跳过；身份不匹配的中间产物原地替换；翻译 run 目录按 `ja.srt` 的 SHA256 分键保留。无时间字符在 cue 阶段不插值、不整窗回退，对齐证据不改写。
8. **时间轴**：模型输入 WAV 直接从视频容器按绝对流索引解码，用 `aresample=async=1:first_pts=0` 补齐起始静音，使 sample 0 对齐视频 0 秒；`offset_s` 恒为 0，音轨 `start_time` 只作诊断记录；各阶段产物使用本地坐标，cue 阶段只加一次 offset。流复制的原始音轨只作归档。下混按声道布局（单声道直通、双声道 0.5/0.5、5.1 以上标准矩阵含中置）；重采样用 ffmpeg 默认 swr（soxr 会使 Pyannote 少保留约 10% 语音、CER 高于基线）。
9. **锁与进程**：只有编排器持有 `.local/gpu.lock`，worker 与 llama-server 不取锁并进入 KILL_ON_JOB_CLOSE Job Object；编排器不 import torch。编排器另持 `<output_dir>/.work/lock` 防止同一输出目录并发；worker 崩溃按文件隔离重启。
10. **发布**：`zh.srt`、`ja-zh.srt` 与日文 SRT 一起发布；对照 `published.json` 的 SHA256 判定是否可覆盖，被用户改动的文件只在 `force` 时覆盖，并在扫描阶段提前判定。

## 依据

- 翻译峰值显存 15.7–15.8 GB 占满整卡，任何共驻方案都不可行；分阶段批处理把每个模型的加载开销摊到整批，代价是首个结果要等整批 STT 结束，用户接受。
- 以 cue 为翻译单元，因为翻译的质量证据与续跑逻辑都建立在 cue ID 一一对应之上；基于窗口文本需要未解决的中文→时间回映射。
- 统一 CUDA 12：CTranslate2 只有 CUDA 12 wheel，且其 cuDNN 9 DLL 与 CUDA 13 构建同名、同进程只能加载一份；4.8.3 Windows wheel 在 sm_120 上靠驱动 JIT。单 venv 混装 cu12／cu13 取决于 DLL 搜索顺序，不可靠。
- 产品不再依赖 WhisperX（它绑死 transformers 4.x 与 Torch 2.8）；torchaudio `forced_align` 在本机 2.11.0+cu128 存在；Python 3.15 缺 CT2／torchaudio／torchcodec wheel。
- 升级 Torch／CT2／llama.cpp 会改变数值，等于新身份。

## 约束与未关闭项

- 根环境含 Torch 等推理依赖；三个历史环境保留供复现；产品包从 `experiments/` 复制并精简实现，不导入历史包，历史目录冻结。
- **重新评估 CUDA 版本的触发条件**：CT2 发布 CUDA 13 wheel；某必需组件要求 torch > 2.11；整片验收显示 ASR 阶段是墙钟瓶颈。届时形态是给 ASR worker 一个独立 cu12 侧车 venv，或改用 HF Whisper，不采用单 venv 混装。
- 未采用：逐文件全流程调度、翻译基于 ASR 窗口文本、Python 3.14／3.15、CT2 源码构建、soxr 重采样、批内语序自由、跨文件术语一致（后两者登记为未来方向）。
- "CT2 共用 torch DLL"只证明同版本可共存；不加 DLL 目录能否解析以干净 PATH 下的 smoke 为准。
