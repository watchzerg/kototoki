# 阶段链与调度

[跨模块流程](../collaborations.md)的子页：一个批次从 probe 到发布的阶段顺序、CPU 与 GPU 的调度、GPU 内部的等待点，以及进程、环境与依赖（原技术设计 §2、§3、§7）。用户可见行为见[中日双语字幕批量生产流水线](../../behaviors/bilingual-subtitle-pipeline.md)；各阶段写死的模型与配方见[固定配方](../../behaviors/bilingual-subtitle-pipeline/fixed-recipes.md)。

## 阶段分解

每个输入经过 9 个阶段（names 恒在链上）；每阶段只读上一阶段的文件产物，写自己的产物，互不导入对方的运行时状态。阶段链与各阶段期望身份由[阶段计划][plan]唯一给出。

```
probe ──► extract ──► vad ──► asr ──► align ──► ja-cues ──► names ──► translate ──► merge
 CPU       CPU       GPU*    GPU     GPU        CPU        GPU        GPU         CPU
```

| 阶段 | 输入 → 产物 | 设备 | 模块页 |
| --- | --- | --- | --- |
| probe | 视频／音频 → `probe.json`（音轨选择、`has_video`、参照时长、字幕流清单） | CPU | [配置、配方与媒体提取][media] |
| extract | 输入 → `audio-16k.wav`、`extract.log` | CPU | 同上 |
| vad | `audio-16k.wav` → `vad.json` | GPU*（VAD 允许 CPU，第一版固定 `cuda:0`） | [STT worker][stt] |
| asr | `audio-16k.wav`＋`vad.json` → `asr.json`（`cross` 另写三份审计文件） | GPU | 同上 |
| align | `audio-16k.wav`＋`asr.json` → `align.json` | GPU | 同上 |
| ja-cues | `align.json` → `ja.srt`＋`ja-cues.json` | CPU | [日文 cue][cues] |
| names | `ja.srt` → `name-table.json` | GPU（与 translate 共用一个 Strata session） | [专名一致性][names] |
| translate | `ja.srt`＋`name-table.json` → 翻译 run 目录 | GPU（独占） | [翻译子系统][tr] |
| merge | `ja.srt`＋译文 → `ja-zh.srt`（发布到源文件旁） | CPU | [双语合并][merge] |

**内嵌日文字幕**（[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)）：`[input] use_embedded_subtitles`（默认 `true`）开着且文件有可用的日文文本字幕轨时，该文件不经 extract、vad、asr、align、ja-cues，改走：

```
probe ──► 抽轨＋清洗（CPU，写 ja.srt 与 ja-embedded.json）──► names ──► translate ──► merge
```

选轨、抽取与清洗规则见[配置、配方与媒体提取][media]；是否采用与回退见[批次编排][orch]。

### 不流复制原始音轨

视频输入与音频输入一样，extract 只派生 `audio-16k.wav`，不再把原始音轨流复制为 `audio.<ext>`（[ADR-0007][adr7]「输入范围」）：源文件留在原地，工作目录不交付，副本只是重复数据；复制要多读一遍源文件，还曾因坏包让可出字幕的文件整片失败。

### 时间轴与下混

- **时间零点只在媒体模块定义**：模型输入直接从输入容器解码（容器带时间戳，裸码流不带），`aresample=async=1:first_pts=0` 补齐起始静音（AAC 声明采样率与容器时间戳不符时先按真实采样率纠正，规则见[配置、配方与媒体提取][media]），WAV 的 sample 0 即输入 0 秒，因此 `offset_s` 恒为 0；音轨 `start_time` 只进 `probe.json` 作诊断，下游阶段只传 `offset_s = 0`。
- 时长校验、按声道布局的 `pan` 常量（进 `MEDIA` 配方 hash、禁止削波）与重采样器（ffmpeg 默认 swr）见[配置、配方与媒体提取][media]；swr／soxr 的频谱对比与改回 swr 的经过见历史记录（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`）。

## 调度模型：CPU 流水线 + GPU 分阶段批处理

### 结论

- **CPU 阶段（probe、extract、ja-cues、merge）与 GPU 阶段分开**：extract 用线程池（`[run] extract_workers`）先跑完整批，GPU 阶段再开始，不做流式投喂。
- **GPU 阶段按"阶段 × 整批"推进**：加载 VAD → 跑完本批 → 卸载；ASR、MMS 同理；然后启动 Strata → 为本批全部 `ja.srt` 建专名表 → 不停，翻译本批全部 SRT → `strata launch --stop`。产品只有 Strata 一个服务进程，不起 llama-server；没有批次切分参数。
- 每个 GPU 阶段在**独立子进程**中执行（一个阶段一个子进程）：进程退出即释放显存，崩溃不拖垮编排器。worker 逐文件增量写结果；单文件异常记失败并继续；退出码、启动失败与按文件重启的规则见[worker `--jobs` 协议与退出码](../modules/artifact-contract/worker-protocol.md)。编排器本身不加载模型、不 import torch（[进程模型](#进程模型)）。细节见[批次编排][orch]。

### 为什么这样选

任一时刻只有一个模型驻留（翻译峰值占满 16 GB 整卡），加载开销每阶段每批一次，代价是首个结果要等整批 STT 结束；理由见 [ADR-0007][adr7]，原对比表在历史记录（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`）。唯一例外是 `cross` 的 asr 阶段内 Whisper 与 Qwen 同进程共驻（显存门槛与回退见 [STT worker][stt]）。

### GPU 内部顺序与并发

- GPU 阶段严格串行，由 `.local/gpu.lock` 保护；只有编排器获取它：取放时机、锁文件内容与残留锁规则见[批次编排运行时规则](../modules/batch-orchestration/runtime-rules.md)与[运行日志与进程][run-proc]；Strata 在第一次请求模型时启动。
- 同一 `input_dir` 同时只允许一个编排器：启动即取 `<work root>/lock`，已被占用则退出码 3。撞 GPU 锁是进程级冲突，整批结束但可续跑（规则见[批次编排运行时规则](../modules/batch-orchestration/runtime-rules.md)，ADR-0025）。
- 不在 GPU 阶段内做多文件并发：W0 契约是 batch 1、逐窗独立，并发只会争抢算力与显存。
- names 与 translate 共用编排持有的一个 Strata session（[ADR-0029](../../adr/0029-translate-per-cue-resolution.md)「Strata session」）：第一次真正需要模型时启动，两阶段之间不停，整批结束、出错或中断时 `strata launch --stop`。启动前的核对与失败额度见 [Strata session](../modules/strata-session.md#当前行为规格)。见[专名一致性][names]、[翻译子系统][tr]。

## 进程、环境与依赖

### 进程模型

```
python -m kototoki kototoki.toml  (编排器：唯一持有 .local/gpu.lock；不 import torch)
 ├─ ThreadPool → ffmpeg/ffprobe 子进程（CPU 队列）
 ├─ python -m kototoki.workers.{vad,asr,align} --jobs <work root>/jobs-<stage>.json  (每阶段一个子进程；asr 引擎取 jobs 的 config.engine)
 ├─ Strata（strata launch）+ 进程内 HTTP 客户端：先逐片建专名表，再循环翻译
 └─ 进程内 ja-cues / merge
```

- worker 之间只通过 `<work root>/<id>/` 下的 JSON 交接，每阶段重验输入身份；编排器与 worker 用同一解释器（`sys.executable`）。
- 所有 worker、ffmpeg 与 Strata CLI 子进程随编排器退出（启动方式与进程组见[运行日志与进程][run-proc]）；Strata 服务由 `strata launch` 在后台启动、不受其约束，靠 session 退出时的 `--stop` 收尾，编排器被强杀时它可能残留，下次运行拒绝，须手动 `strata launch --stop`。
- 编排器为 worker 设置离线环境与 `PYTHONUTF8=1`（变量清单见[运行日志与进程][run-worker]）。ASR worker 先 `import torch` 再导入 CTranslate2；"编排器不 import torch"有测试。细节见[批次编排][orch]与 [STT worker][stt]。

### 环境、代码布局、上游版本

当前环境、版本、选版规则与 CUDA 说明见[技术选型](../../development/technology-stack.md)与[依赖布局与资产清单](../../development/dependencies.md)；当前文件布局见[架构总览](../INDEX.md)；原文（含 2026-10-13 上游版本核实表）见历史记录（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`）。

[adr7]: ../../adr/0007-bilingual-subtitle-pipeline-architecture.md
[media]: ../modules/config-and-media.md
[stt]: ../modules/stt-workers.md
[cues]: ../modules/japanese-cues.md
[names]: ../modules/name-consistency.md
[tr]: ../modules/translation-subsystem.md
[merge]: ../modules/translation-subsystem/bilingual-merge.md
[orch]: ../modules/batch-orchestration.md
[orch-spec]: ../modules/batch-orchestration/runtime-rules.md
[plan]: ../modules/stage-plan.md
[run-proc]: ../modules/run-logging-and-processes/process-primitives.md#进程原语
[run-worker]: ../modules/run-logging-and-processes/worker-subprocess.md#worker-子进程
