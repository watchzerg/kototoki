# 模块页拆出的历史记录：STT worker、阶段计划与产物契约（2026-11-11）

状态：concluded（冻结记录：2026-11-11 模块页重写时移出的带日期运行记录与验收数字，原文未改）

来源页：[STT worker](../../architecture/modules/stt-workers.md)（ASR 部分现在在 [STT ASR](../../architecture/modules/stt-asr.md)）。以下各段原样摘自该页 2026-11-11 重写前的对应小节；相对链接、版本号与"当时的产品翻译"等描述均为当时状态。其余被删的带日期内容已在别处有记录，不在此重复：cross 成本与质量见 [cross 产品路径验收](2026-10-19-cross-asr-acceptance.md) 与 [ADR-0012](../../adr/0012-cross-asr-judge.md)，产品 CER 回归见[最终验收](2026-10-15-bilingual-pipeline-final-acceptance.md)，冻结窗口门禁的首跑要点与 x0 窗口 0 的裁定见票据 `.scratch/bilingual-subtitle-pipeline/issues/03-stt-workers.md`、`07-x0-engine.md`，2026-11-11 的 `accepted_difference` 放行见 [`docs/plans/asr-repeat-guard.md`](../../plans/asr-repeat-guard.md)。

## STT worker · 当前行为规格 · ASR x0（transformers 5.19 对照）

transformers 5.19 下用研究期 trace 的 token 解码，8 窗文字、原始输出与检测语言与 5.18 记录全等。

## STT worker · 当前行为规格 · cross 引擎（显存与共驻）

- **显存与共驻**（整卡峰值，含桌面；单独值来自 [swr 回归](../../research/acceptance/2026-10-16-bilingual-pipeline-swr-regression.md)与[交叉打分](../../research/2026-10-19-asr-pair-cross-score.md)，共驻值为实测）：

  | 项 | 峰值 MiB | 说明 |
  | --- | ---: | --- |
  | asr w0 转写（单独） | 5265 | |
  | asr x0 转写（单独） | 5420 | |
  | Whisper 打分（单独） | 5903 | 空闲 1452 |
  | **两者共驻（T0 探针）** | **10688** | 同进程、两部片三步，桌面约 2.0 GB；加 1 GB 余量 11712 < 13824 |
  | **cross asr 阶段（T6 产品路径）** | **10030** | 桌面约 0.86 GB，出现在第二部打分阶段附近；按探针的桌面占用折算约 11.2 GB，加余量仍 ≤ 13.5 GB |
  | align（MMS fp32） | 8445–8515 | 不能与上两者共驻，保持独立阶段 |
  | translate（Hy-MT2，当时的产品翻译；2026-11-08 起为 Strata，要求空闲 ≥ 14000，同样独占） | 15648–15721 | 启动要求空闲 ≥ 14700，必须独占；asr 退出后整卡回到约 0.85 GB，翻译照常启动 |

  **共驻的采用依据**：ADR-0012 决策时以探针实测的共驻峰值加 1 GB 余量 ≤ 13.5 GB 为采用共驻的前提（已通过）；当时的备选"Whisper 整批转写 → 卸载 → Qwen 整批转写 → 卸载 → Whisper 整批打分"三段式没有实现，运行时不看显存、不会回退，产品只有共驻这一种路径。

## STT worker · 代码与验证入口（冻结窗口门禁，2026-10-14）

- 冻结窗口门禁（真实模型验证，占 GPU，须用户批准）：`just smoke stt_frozen_window`（`scripts/smoke/run_all.py` 持锁并以 `python scripts/smoke/stt_frozen_window.py --out <dir>` 启动，结果写 `.local/smoke/<UTC>/stt_frozen_window.json`；没有 `.local/gpu.lock` 时脚本拒绝运行；不属于任何测试层与 gate）。2026-10-14 首次运行（接入 test-full 之前的手动版本，产物 `.local/stt-gate/20261014T070454Z/`；RTX 5080、torch 2.11.0+cu128、torchaudio 2.11.0+cu128、transformers 5.19.0、pyannote.audio 4.0.7、faster-whisper 1.2.1、CTranslate2 4.8.3；输入 `hf-ii-window-01.wav` 300 s；对照 `.local/w0-demo/pyannote-gpu-v1-w0-pyannote-current-hf-ii-window-01/`，其 VAD 来自同为 torch 2.11 的 `vad-pyannote-gpu-v1` 环境，ASR／MMS 来自 torch 2.8 的 `whisper-latest` 环境）：8 个窗口整数边界全等；8 窗文字逐字符相等且 token 序列全等（549 字）；549 个 unit 字符范围与状态全等（25 个 `text_only`），1048 个起止时间与对照（减去其 `offset_s` 351.402125）全等，最大差 0。耗时：VAD 加载 21.2 s／推理 1.4 s，ASR 加载 3.0 s／推理 6.9 s，MMS 加载 14.1 s／推理 2.8 s。
- x0 冻结窗口门禁（真实模型验证，占 GPU，须用户批准）：`just smoke x0_frozen_window`（`run_all.py` 持锁并以 `python scripts/smoke/x0_frozen_window.py --out <dir>` 启动；与 `stt_frozen_window` 共用同目录脚本里的 `child_env`、`run_stage`、`compare`），与 `stt_frozen_window` 同法同标准，ASR 取 `x0`，对照 `.local/x0-demo/pyannote-gpu-v1-x0-pyannote-current-hf-ii-window-01/`（ASR 来自 torch 2.14.1+cu130／transformers 5.18 的 `qwen-hf-final` 环境，MMS 来自 torch 2.8）；没有 `.local/gpu.lock` 时拒绝运行。2026-10-14 运行两次（`.local/smoke/20261014T082609Z/`、`20261014T082759Z/`，两次产物逐字节相同；torch 2.11.0+cu128、transformers 5.19.0）：8 窗整数边界全等；7 窗文字与 token 全等，窗口 0 的 38 个 token 中第 2 个不同（一个汉字被另一个汉字替换，字数不变），2026-10-14 用户裁定接受为环境差异（BF16 近平局在 torch 2.11+cu128 与对照的 2.14.1+cu130 之间翻转），票据 07 完成；587 个 unit 字符范围与状态全等（47 个 `text_only`），1080 个起止时间与对照全等，最大差 0；无触顶窗口。整轮约 95 s。Qwen 加载不用研究期的 `device_map`（需要产品环境没有的 accelerate），改为加载后整体 `.to("cuda:0")`。
