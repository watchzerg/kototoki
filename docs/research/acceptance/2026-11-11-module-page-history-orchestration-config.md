# 模块页拆出的历史记录：批次编排、配置与媒体、开发工作流（2026-11-11）

状态：concluded（冻结记录：2026-11-11 模块页重写时移出的带日期运行记录与验收数字，原文未改）

文档架构整理票据 10（`.scratch/docs-architecture/`）把下列模块页与开发工作流重写到现状时，移出了带日期的运行记录、实测耗时与用例数。下面各节逐字保存原文（提交 75d7074 时的内容，只改了相对链接以适应新位置），只供追溯；现行规则以各页正文为准。

## 批次编排（`docs/architecture/modules/batch-orchestration.md`）

### 原状态行

状态：current（2026-11-11 加内嵌日文字幕路径，[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)，只用伪媒体与 ffmpeg 合成片段测过；票据 06 交付，2026-10-14；票据 14 把阶段链与期望身份拆到[阶段计划](../../architecture/modules/stage-plan.md)，票据 15 把翻译阶段的取锁改为按需，2026-10-15）；GPU worker 按 [STT worker](../../architecture/modules/stt-workers.md)（票据 03、07）的 jobs 约定调用，翻译与合并见[翻译子系统与合并](../../architecture/modules/translation-subsystem.md)（票据 05、09），专名建表见[专名一致性](../../architecture/modules/name-consistency.md)（2026-10-20 专名票据 06 接入）；2026-11-08 起翻译走 Strata、没有发布时替换（[ADR-0019](../../adr/0019-product-translation-q2.md)）；2026-11-09 起 names 建表也走 Strata，两阶段共用一个由编排持有的 Strata session，产品不再起 llama-server（[ADR-0022](../../adr/0022-product-names-on-strata.md)）。离线由伪 worker、伪专名与伪翻译模块测试；真实 worker、ffmpeg 与 llama-server 下的两部整片 × w0／x0 整批运行，以及翻译失败后重跑时 STT 产物按身份全部跳过的续跑，已在[两部整片验收](../../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)中通过；names 阶段已有真实运行（专名票据 07、08，含当时的发布时替换，已删除）；Q2 的 Strata 自动启停编排已于 2026-11-08 整片运行；共用 session 的真实运行结果记在 ADR-0022 所指计划的 §7。2026-11-11 起按 [ADR-0025](../../adr/0025-product-package-boundaries.md) 与计划 [`architecture-cleanup`](../../plans/architecture-cleanup.md) 先行改写本页接口（GPU 锁冲突一律进程级、worker 协议读侧收进 `protocol.classify_launch`、进程原语移到 `kototoki/procs.py`、四个子系统改为普通导入、`ja.srt` 新鲜度归阶段计划），代码随该计划的票据 02–09 落地，实现结果见计划 §7。

### 当前行为规格 › 运行日志 › 真实运行核对

- **真实运行核对**（2026-10-18，3.5 h 整片 w0，记录见 `.scratch/runtime-logging/spec.md` Comments）：运行日志与控制台逐行相同且全部符合行格式；asr／align worker stderr 为空，vad 只剩 pyannote 的 TF32 `ReproducibilityWarning`（本格式）与 torch 自挂 handler 的一行 `W… triton not found`（非本格式、不计数），无进度条；llama-server 的 `timings` 带 `predicted_per_second`，批次行均出现 tok/s 与 cache；日志与 stderr 不含 cue 文字或译文。该次核对发现的两处缺口已于 2026-10-19 补上：媒体告警改由编排写成 WARNING 行（此前只在 `probe.json`），extract 补齐 `start`／逐文件 `done`／`end` 三件套；补后未再做真实运行。

## 配置、配方与媒体提取（`docs/architecture/modules/config-and-media.md`）

### 代码与验证入口 › 真实视频

- 真实视频（2026-10-14，ffmpeg 2026-10-01 gyan.dev full build，不进 Git）：Heaven's Feel II（mkv，FLAC 立体声）产出三份产物（112448683 样本；默认 swr 下 PCM SHA256 `ee4e2da3…` 与基线 `hf-ii-full.wav` 一致，票据 02 与票据 10 改回后各核对一次；2026-10-14 至 10-15 的 soxr 版为 `c203f952…`，说明零点补齐与下混未改变样本，差异只来自重采样器，对比数据见规格 §2.2），视频流时长取自 `DURATION-eng`（该文件没有精确 `DURATION`）；Black Panther（mkv，12 条音轨，选中 jpn E-AC-3 `5.1(side)`）产出 `audio.eac3`、`audio-16k.wav`、`extract.log`。

### 代码与验证入口 › 未验证与已知限制

- 未验证：广播 `.ts`（音轨绝对 `start_time`、PTS 回绕、音频先于视频的负延迟）只按 ffmpeg 默认零点推理，没有真实样本；`6.1`／`7.1` 常量无真实样本（5.1(side) ac3 真实片段已在[最终验收](../../research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)通过）；cue 时间等于视频时间目前只在 WAV 样本层断言（`sample / 16000 + offset_s`），cue 侧只由[日文 cue](../../architecture/modules/japanese-cues.md)的离线测试断言 offset 只加一次；整片验收只核对了三份 SRT 时间一致，没有与视频画面对时。日本广播双单声道（主／副音声）按双声道处理，是已知限制。已知限制：`pan` 保证下混本身不削波，但其后的降采样滤波（48 kHz→16 kHz，swr 与 soxr 都会）对满幅方波这类信号会过冲到 −32768（合成测试因此用 16 kHz 源单独验证下混系数）；真实素材实测（2026-10-14）：HF II 派生 WAV 1.12 亿样本中 swr 版 1 个、soxr 版 2 个样本到满幅；Black Panther（swr 版）峰值 31073、无削波。

## 开发工作流（`docs/development/workflow.md`）

### 命令与门禁 › `verify-assets` 行

| recipe | 当前实现 |
| --- | --- |
| `verify-assets` | `scripts/assets.py verify`：离线核对 tools 与 models（大小、SHA256 经 size+mtime 缓存 `.local/cache/assets-verify.json`，tools 还要求 `identity.json`）；2026-10-18 本机首次 21.7 s（约 27 GB 全量哈希），缓存命中后 0.7 s |

### 命令与门禁 › `smoke` 行

| recipe | 当前实现 |
| --- | --- |
| `smoke` | 真实模型验证，不属于任何 gate：`scripts/smoke/run_all.py [名称 ...]`，四项环境 smoke（`forced_align`、`vad_pyannote`、`ct2_after_torch`、`llama_stock`）与票据 03 的冻结窗口门禁 `stt_frozen_window`（见 [STT worker](../../architecture/modules/stt-workers.md)）及票据 07 的 x0 同窗门禁 `x0_frozen_window`，以及 Q2 首用 smoke `translate_product`（产品 `kototoki.translate` 的 plan → Session → `translate_document`，经 Strata 自动启停与外部前置的 Strata 0.2.12／build 0.1.58，产品配方 `q2-degrade-v1`；只记计数、哈希与耗时，见[翻译子系统](../../architecture/modules/translation-subsystem.md)；**未运行、待用户批准**，耗时与结果待补；运行前须没有别的 Strata launch 在服务）和产品专名 smoke `names_product`（产品 `kototoki.names` 的 `names_identity` → 共享 `strata.Session` → `build_document` → `write_artifact`，在产品自动启停的 Strata 上按 Q3 规则建表（配方 `q3-names-v1`，ADR-0022），输入为脚本内置的 12 条合成日语短句；通过条件含专家区锁进内存、`build.status == ok`、至少一条 person、全程无 llama-server、`--stop` 后显存释放；只记计数、哈希、耗时与资源峰值，见[专名一致性](../../architecture/modules/name-consistency.md)；27B＋llama-server 时期 2026-10-20 实测约 21 s；Strata 路径 2026-11-09 实测 87.5 s，其中 Strata 启动约 78 s、建表 5.9 s），每项是 `scripts/smoke/<名称>.py`，在独立子进程中以 `--out <dir>` 运行，子进程 PATH 去掉 `whisper-runtime-provisional`、离线变量；运行期间持有 `.local/gpu.lock`，结果写 `.local/smoke/<UTC 时间>/`。**加载模型、独占 GPU，四项 smoke 约 3 分钟（2026-10-14 实测 2.5 分钟），`stt_frozen_window` 约 1–2 分钟（2026-10-14 实测三阶段合计约 65 s，不含首次模型哈希），`x0_frozen_window` 预计 2–3 分钟；每次须先经用户批准** |

### 测试分层与资源边界 › core 与 full

- core：`tests/core/` 下的产品 `unittest` 测试，`just test` 以 `discover -s tests/core -t .` 收录（`tests/__init__.py`、`tests/core/__init__.py` 须保留，模块以 `tests.core.*` 导入）；覆盖产品包 `kototoki/` 的全部模块，各模块的测试清单与覆盖行为见其模块页"代码与验证入口"（[架构总览的模块地图](../../architecture/INDEX.md#模块地图)）。进程内或本解释器子进程：GPU 阶段由 `tests/fake_worker.py` 子进程顶替、翻译用伪 server 对象／伪客户端、导入边界用 `sys.executable -c` 子进程核对；不调用外部二进制、不碰网络与 socket、不读真实视频、不加载模型。整套 349 个用例约 36 s（2026-10-18 实测 35.9 s），其中编排测试因启动伪 worker 子进程约 30 s。
- full：`tests/full/` 下的离线集成测试，`just test-full` 以 `discover -s tests/full -t .` 收录；用项目内 ffmpeg（`config.load` 的默认路径，`assets.toml` 锁定）合成秒级小样本：`test_media_ffmpeg`（媒体提取）与 `test_job_ffmpeg`（端到端：真实媒体阶段、fake worker 顶替 GPU 阶段、假翻译 session，检查三份 SRT 发布）。不加载模型、不占 GPU，因此不需要 `.local/gpu.lock`。整套 11 个用例约 3.3 s（2026-10-18 实测）。
