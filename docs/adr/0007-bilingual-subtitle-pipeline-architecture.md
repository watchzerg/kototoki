# ADR-0007：中日双语字幕流水线的产品架构

状态：已接受（用户于 2026-10-13 讨论中逐项裁定）；已实现（2026-10-14，票据 00–09，见[技术设计](../specs/bilingual-subtitle-pipeline.md)与[架构总览](../architecture/INDEX.md)）；决定 4 中的产品翻译配方 2026-10-18 起由 [ADR-0011：dp10-cut-degrade-v1](0011-dp10-cut-product-recipe.md) 替代，三级降级仍有效  
日期：2026-10-13  
范围：第一个正式产品形态的工程架构。模型与配方身份不在此决定：STT 沿用 [ADR-0003](0003-new-pyannote-baselines.md)，翻译沿用 [ADR-0005](0005-apex-i-compact-translation-baseline.md)／[ADR-0006](0006-b10-joint-translation-flow-baseline.md)。完整设计见[技术设计](../specs/bilingual-subtitle-pipeline.md)。

## 背景

仓库此前只有 demo 与实验入口：W0／X0 各自一个进程、三个互斥的 Python 环境、翻译另有 llama-server 运行时。用户要求进入实现阶段：一个批量工具，从日语视频生产日文、中文与双语 SRT，直接使用已采纳的基线，不做多种可选配置。约束是 RTX 5080 的 16 GB 显存、原生 Windows，以及用户对较新 NVIDIA／Python 组件的偏好。

## 决定

1. **GPU 阶段按"阶段 × 整批"推进，每阶段一个子进程。** 加载 VAD 跑完整批卸载，再 ASR、再 MMS，最后 llama-server 翻译整批。CPU 阶段（ffmpeg 提取、cue 切分、合并）是独立队列，可与 GPU 并行。第一版不提供批次切分参数。
2. **翻译单元是日文 cue，不是 ASR 窗口文本。** 翻译输入固定为 `ja.srt`，每条中文继承日文 cue 的编号与时间；本期批内 10 条与中文一一对应。
3. **一个统一的 CUDA 12.8 Python 环境**（2026-10-14 用户决定，替代此前"CUDA 13＋CTranslate2 侧车"方案）：Python 3.13、torch 2.11.0+cu128、torchaudio 2.11.0、torchcodec 0.17.0、transformers 5.19、pyannote.audio 4.0.7、faster-whisper 1.2.1／CTranslate2 4.8.3，由根 `pyproject.toml` 经 uv 管理（Torch 走显式 cu128 索引）。CTranslate2 只有 CUDA 12 wheel，且 cuDNN 9 的 DLL 文件名在 CUDA 12 与 13 构建间相同、同进程只能加载一份；与其让 w0 worker 不 import torch 并用 NumPy 重写特征，不如整体用 CUDA 12，让 CT2 直接共用 torch 自带的 CUDA 12 DLL，这一共存方式已由现有 `whisper-latest` 环境长期验证。代价是 torch 停在 cu128 索引的最后版本 2.11.0 而非 2.14.1。用户随后明确选版规则：CUDA 12 与 Python 3.13 是锚点，受其限制的组件一起锁定，其余组件取最新稳定版。llama.cpp 是独立进程、与 Python 进程无 DLL 交集，使用官方 b11583 win-cuda-13.4 构建（原生含 sm_120 内核），不再打 Hy-MT2 兼容补丁（本机 APEX GGUF 已是上游张量命名）；这一条**替代 [ADR-0005](0005-apex-i-compact-translation-baseline.md) 中"继续使用 b11429 兼容 loader、不以 stock 引擎替代"的条款**（用户 2026-10-14 确认），模型、采样与提示身份不变。
4. **翻译失败降级**：批次终态失败时 10→5→1 拆批重试；单条仍失败则该条保留日文并写入报告，整片照常交付。这与 v3 实验"不缩批、不截断"的身份规则不同，产品以交付完整性优先；因为 `b10-joint` 的 recipe hash 包含溢出策略，产品配方另名 `b10-joint-degrade-v1`，提示、grammar、采样与请求字节保持不变并以测试固定。
5. **配置文件驱动，第一版无 CLI**：输入／输出／模型目录、并发、cue 显示规则、翻译 seed 放 `kototoki.toml`（VAD 设备第一版固定 `cuda:0`，不设键；破除死锁用一次性环境变量而非配置项）；解码、采样、提示、窗口等影响模型行为的常量留在代码里作为配方常量，改动即新配方 hash。
6. **产物与续跑**：每个视频一个工作目录，所有中间产物（原始编码音轨流复制、16 kHz WAV、VAD／ASR／对齐 JSON、cue JSON、翻译 run）全部保留并带输入身份与配方 hash；产物匹配即跳过；三份最终 SRT 一起发布。无时间字符在 cue 阶段插值或整窗回退，对齐证据不改写。
7. **时间轴**：模型输入 WAV 直接从视频容器按绝对流索引解码，用 `aresample=async=1:first_pts=0` 补齐起始静音，使 sample 0 对齐视频 0 秒；`offset_s` 恒为 0，音轨 `start_time` 只作诊断记录（2026-10-14 第三轮修订：原"`start_time` 作为 `offset_s` 贯穿全链"与补齐静音叠加会双重计时，且 ffmpeg 已平移容器起点，绝对 `start_time` 不是正确的偏移）；各阶段产物使用本地坐标，cue 阶段只加一次 offset。流复制的原始音轨只作归档（2026-10-14 修订：裸码流容器丢时间戳）。
8. **锁与进程**：只有编排器持有 `.local/gpu.lock`，worker 与 llama-server 不取锁并进入 KILL_ON_JOB_CLOSE Job Object；编排器不 import torch。编排器另持 `<output_dir>/.work/lock` 防止同一输出目录并发；worker 崩溃按文件隔离重启。
9. **产物替换与发布**：身份不匹配的中间产物原地替换；翻译 run 目录按 `ja.srt` 的 SHA256 分键保留；三份最终 SRT 对照 `published.json` 的 SHA256 判定是否可覆盖，被用户改动的文件只在 `force` 时覆盖，并在扫描阶段提前判定。

## 依据与取舍

- 翻译峰值显存 15.7–15.8 GB 已占满整卡，任何共驻方案都不可行；分阶段批处理同时把每个模型的加载开销摊到整批。代价是首个结果要等整批 STT 结束，用户接受。
- 以 cue 为翻译单元是因为 b10-joint 的全部质量证据与续跑逻辑都建立在 cue ID 一一对应之上；基于窗口文本翻译需要未解决的中文→时间回映射。
- 统一环境的前提是产品不再依赖 WhisperX（它绑死 transformers 4.x 与 Torch 2.8）。子 agent 于 2026-10-13 核实：torchaudio 的 `forced_align` 未被移除；CTranslate2 是唯一 CUDA 12 组件；Python 3.15 缺 CT2／torchaudio／torchcodec wheel 故不可用。源码构建 CT2 对 CUDA 13 无文档，这也是不走"CUDA 13＋自建 CT2"的原因之一。
- 升级 Torch／CT2／llama.cpp 会改变数值，等于新身份。用户决定本期只做工程架构，回归与容差推迟到实现之后另议。
- 2026-10-14 用户在评审后裁定：下混按声道布局（单声道直通、双声道 0.5/0.5、5.1 以上标准矩阵含中置）；重采样保持 ffmpeg 默认 swr 以便与基线证据逐字节对照；产品翻译配方命名 `b10-joint-degrade-v1`。
- 2026-10-15 备注：重采样曾于 2026-10-14 改为 soxr 28 bit，最终验收发现 Pyannote 因此少保留约 10% 语音、CER 高于基线，用户裁定改回默认 swr（票据 10），上一条"保持默认 swr"重新成立。
- 2026-10-14 两轮评审（主 agent 自审、独立 Opus 评审）核实：torch wheel 与 CUDA 12 cuDNN 的 DLL 同名；现有 W0 `setup_runtime` 同时修改 PATH；旧语料准备拒绝非立体声与非零 `start_time`；v3 `Recipe.spec()` 含 `overflow` 字段；v3 session 要求首个请求 `cache_n == 0` 且按整个场景落盘。修订见规格 §13。
- 2026-10-14 第三轮独立评审核实：W0 `setup_runtime` 在 `whisper-latest` 里同样把私有 DLL 目录加进 PATH，因此"CT2 共用 torch DLL"只被证明为同版本可共存，不加目录能否解析留给 01 smoke 在干净 PATH 下验证；v3 `run_generation` 在 `sources`／`scene_ids` 变化时拒绝而非重建，故翻译 run 目录按 `ja.srt` SHA 分键；`forced_align` 在本机 torchaudio 2.11.0+cu128 存在。全部修订见规格 §1.2 第三轮表与 §13。
- 2026-10-14 复议"cu12 与 cu13 并存"（用户问能否按社区方案混用；来源 OpenNMT/CTranslate2#1933 与 PyTorch 2.11 转 cu130 的公告，访问 2026-10-14）。本机核实：CT2 4.8.3 Windows wheel 只嵌入 `.target sm_86` 的 PTX、无 sm_120 SASS，在 5080 上全靠驱动 JIT（01 smoke #3 禁用 JIT 即失败）；社区"soname 不同可并存"只对 cuBLAS／cudart 成立，cuDNN 9 的两种构建同名，单 venv 混装取决于 DLL 搜索顺序，不可靠；w0 的 torch 特征链只用 `stft` 与矩阵乘、不碰 cuDNN，是该进程里唯一的减轻因素。结论：维持 CUDA 12.8。换 CUDA 13 今天只换来 torch 2.14，没有组件需要它；CT2 在 sm_120 上的性能问题与 CUDA 版本无关（#1933 报告自建 sm_120 后 FP16 提速约 4 倍，对本工作负载 UNVERIFIED：GEMM 走 cuBLAS 12.8 的原生 sm_120 内核，CT2 自有 PTX 内核只是轻量算子）。**重新评估的触发条件**：CT2 发布 CUDA 13 wheel；某必需组件要求 torch >2.11；整片验收显示 ASR 阶段是墙钟瓶颈。届时的可靠形态是给 ASR worker 一个独立的 cu12 侧车 venv（第二份 lockfile、解释器路径配置键，W0 身份不变，只需重验搬到新 torch 的 VAD／对齐／x0），或改用 HF Whisper；不采用单 venv 混装。

## 后果

- 根环境从此含 Torch 等推理依赖，demo 时代"根环境无推理依赖"的约定失效；三个历史环境保留供复现。
- `experiments/` 中因缺 NumPy／Torch 而跳过的离线测试将在根环境实际运行。
- 产品包 `kototoki/` 从 `experiments/` 复制并精简实现，不导入历史包；历史目录保持冻结。
- 被否决或推迟：逐文件全流程调度、翻译基于 ASR 窗口文本、Python 3.14／3.15、CUDA 13 Python 环境＋CT2 侧车（方案 A）、单 venv 混装 cu12／cu13 库（2026-10-14 复议）、CT2 源码构建、用 HF transformers Whisper 替换 CT2（它是日后解除 CUDA 12 锁定的路径）、soxr 重采样、批内语序自由（1+5+1）、跨文件术语一致。后四者登记为未来方向。
