# 当前架构总览

仓库有一个产品包 `kototoki/`（双语字幕批量流水线，入口 `python -m kototoki`）；研究按轮次记录在 `docs/research/`（[研究索引](../research/INDEX.md)），产品不导入研究代码。
本页是理解当前系统的入口："当前"指同一仓库版本已实现的结构，不代表全部环境已验收。现行决定与基线身份看 [CURRENT.md](../adr/CURRENT.md)，本页不复述。
阅读顺序：本页 → [模块边界](module-boundaries.md) → 受影响的模块页 → 源码与测试。

## 模块地图

每个模块一篇完整的当前说明，模板见[文档维护规则](../agents/documentation.md#模块页模板)；逻辑职责不要求与源码包一一对应。

### 产品包

| 模块页 | 代码 | 职责 |
| --- | --- | --- |
| [批次编排](modules/batch-orchestration.md) | `kototoki/__main__.py`、`kototoki/job.py` | 唯一入口：扫描、阶段 × 整批调度、续跑、锁、发布到源文件旁 |
| [运行日志、进程原语与 worker 子进程](modules/run-logging-and-processes.md) | `kototoki/logs.py`、`kototoki/procs.py` | 运行日志格式与规则、锁文件与子进程随编排器退出、GPU worker 启动与崩溃判定 |
| [阶段计划](modules/stage-plan.md) | `kototoki/plan.py` | 阶段链、各阶段产物与输入、模型清单、期望身份、下一个要跑的阶段 |
| [产物契约](modules/artifact-contract.md) | `kototoki/artifacts.py`、`kototoki/workers/protocol.py`、`kototoki/srt.py` | 工作目录与产物身份、匹配跳过、原子替换、失败与发布记录、worker `--jobs` 协议 |
| [配置、配方与媒体提取](modules/config-and-media.md) | `kototoki/config.py`、`kototoki/recipes.py`、`kototoki/media.py`、`kototoki/embedded.py` | 读配置、配方常量与 `recipe_hash`、选音轨与派生 WAV、内嵌字幕抽取与清洗 |
| [配置参考](modules/config-and-media/reference.md) | `kototoki/config.py`、`kototoki.toml.example` | `kototoki.toml` 的全部键、默认值、校验，哪些键进产物身份 |
| [STT worker](modules/stt-workers.md) | `kototoki/workers/`、`kototoki/vad.py`、`kototoki/align.py`、`kototoki/schema.py` | GPU worker 壳的共用规则（jobs、模型核对、身份、失败分级）、VAD 与对齐 |
| [STT ASR](modules/stt-asr.md) | `kototoki/asr_whisper.py`、`kototoki/asr_qwen.py`、`kototoki/judge.py`、`kototoki/guard.py` | w0／x0 逐窗转写、cross 交叉打分裁判、w0 整窗守卫（复读、语速、已知幻听句） |
| [日文 cue](modules/japanese-cues.md) | `kototoki/cues.py` | 字符时间回填并切成日文 cue；时间轴上唯一加 `offset_s` 的地方 |
| [Strata 服务与共享 session](modules/strata-session.md) | `kototoki/strata.py`、`kototoki/local_client.py` | Strata 起停、身份核对、专家区检查、整批共用的 session 与启动额度、回环客户端 |
| [专名一致性](modules/name-consistency.md) | `kototoki/names/` | 在共享 session 上把整份 `ja.srt` 一次建成专名表；失败写空表照常翻译 |
| [翻译子系统](modules/translation-subsystem.md) | `kototoki/translate/` | 产品翻译配方：切包、请求、专名注入、按批次续跑、按条追问未解决的 cue |
| [双语合并](modules/translation-subsystem/bilingual-merge.md) | `kototoki/merge.py` | 译文与 `ja.srt` 合并为中日两行 `ja-zh.srt` 文本：中上日下、换行替换、译文覆盖校验 |

## 按任务找模块页

| 任务 | 从这里继续 |
| --- | --- |
| 改配置键、默认值或校验 | [配置参考](modules/config-and-media/reference.md) → [配置、配方与媒体提取](modules/config-and-media.md) |
| 改音轨选择、WAV 派生或内嵌字幕路径 | [配置、配方与媒体提取](modules/config-and-media.md) |
| 改 VAD 分窗、对齐或 worker 的 jobs 约定 | [STT worker](modules/stt-workers.md) → [worker `--jobs` 协议与退出码](modules/artifact-contract/worker-protocol.md) |
| 改 w0／x0 转写、cross 裁判或整窗守卫 | [STT ASR](modules/stt-asr.md) |
| 改日文 cue 的切分与显示规则 | [日文 cue](modules/japanese-cues.md) |
| 改翻译配方或失败路径 | [翻译子系统](modules/translation-subsystem.md) |
| 改双语合并 | [双语合并](modules/translation-subsystem/bilingual-merge.md) |
| 改专名建表 | [专名一致性](modules/name-consistency.md) |
| 改 Strata 起停、显存检查或 session | [Strata 服务与共享 session](modules/strata-session.md) |
| 加阶段、改产物身份或跳过判定 | [阶段计划](modules/stage-plan.md) → [工作目录布局与产物身份](modules/artifact-contract/layout-and-identity.md) |
| 改调度、续跑、锁或发布 | [批次编排](modules/batch-orchestration.md) |
| 改日志、进程锁或 worker 启动 | [运行日志、进程原语与 worker 子进程](modules/run-logging-and-processes.md) |
| 跨模块改动、移动或改名产品符号 | [模块边界](module-boundaries.md) → [跨模块流程](collaborations.md) |

## 依赖与装配

产品包 `kototoki/`（进程边界用虚线）：

```mermaid
flowchart TB
  MAIN["python -m kototoki"] --> JOB["job（编排）"]
  JOB -->|线程池直接调用| MEDIA["media（ffmpeg）"]
  JOB -->|直接调用| CUES["cues（纯函数）"]
  JOB -->|直接调用| EMB["embedded（纯函数，内嵌字幕清洗）"]
  JOB -->|直接调用| MERGE["merge（纯函数）"]
  JOB -->|next_stage / advance，期望身份| PLAN["plan（阶段计划）"]
  JOB -->|持有共享 session| ST["strata（中间层）"]
  JOB -->|传入 session| NM["names/（专名）"]
  JOB -->|传入 session| TR["translate/（子系统）"]
  JOB -.->|子进程：--jobs 文件 + 退出码| WK["workers.vad / workers.asr / workers.align"]
  WK -->|身份、模型清单| PLAN
  PLAN -.->|translate.plan（延迟导入）| TR
  PLAN -.->|names.recipes 建表 hash（延迟导入）| NM
  WK --> VAD["vad"]
  WK --> ASR["asr_whisper ／ asr_qwen"]
  WK --> ALIGN["align"]
  TR --> ST
  NM --> ST
  TR --> LS["local_client（中间层，客户端）"]
  NM --> LS
  ST --> LS
  ST -->|strata CLI 与 HTTP| STRATA["Strata（外部服务）"]
  MEDIA & CUES & EMB & MERGE & PLAN & TR & NM & ST & LS & WK & VAD & ASR & ALIGN --> BASE
  BASE["基础层：config · recipes · artifacts · srt · workers/protocol · schema · logs · procs · judge · guard"]
```

依赖只允许向下。硬规则、责任边界与接缝在[模块边界](module-boundaries.md#依赖方向)：产品代码不导入研究代码，研究可以导入产品符号。

装配入口（全部从仓库根目录启动，加载模型的都是 GPU 重任务）：

| 入口 | 解释器 | 模块 |
| --- | --- | --- |
| `python -m kototoki [kototoki.toml]`；默认配置的便捷入口 `mise run subtitles <目录>`（`scripts/subtitles.py`，写只含 `input_dir` 的配置到 `.local/run-configs/` 再调同一入口；测试 `tests/core/test_subtitles_script.py`） | 根 `.venv`；GPU 阶段以同一解释器起子进程 worker；建表与翻译共用本机 Strata（须预先安装并备好模型） | [批次编排](modules/batch-orchestration.md) |

产品入口的用法见仓库 [README](../../README.md#双语字幕流水线)。

## 系统不变量

- 产品入口：工作目录 `work_dir` 按产物身份续跑与原地替换；最终只发布源文件旁的 `ja-zh.srt`，已存在即跳过、没有覆盖开关。目录位置的限制见[批次编排](modules/batch-orchestration.md)。
- 产品产物的跳过与续跑只看产物身份（上游 SHA256、配方 hash、模型 SHA256，不含绝对路径）。见[工作目录布局与产物身份](modules/artifact-contract/layout-and-identity.md)。
- ASR 与 MMS 只在 CUDA 上运行，失败不回退 CPU；产品 VAD 固定 `cuda:0`。见 [STT worker](modules/stt-workers.md)。
- 识别全文的每个字符在 `units` 中恰好出现一次；缺时间的字符保留为 `text_only`，不删除、不伪造时间。
- 识别窗口以 VAD 产物的源坐标为准，ASR 与 MMS 用同一组整数样本坐标裁剪。见 [STT worker](modules/stt-workers.md)。
- 产品时间轴：派生 WAV 的 sample 0 等于输入 0 秒（`offset_s` 恒为 0），各阶段 JSON 一律 WAV 本地秒，cue 时间只在日文 cue 加一次 offset。见[模块边界：产品包的责任边界](module-boundaries.md#产品包的责任边界)。
- 推理期间不联网、不下载；模型由资产清单 `assets.toml` 锁定并预先放在 `.local/models/`（[依赖布局与资产清单](../development/dependencies.md)）。
- 同一时刻只有一个持 `.local/gpu.lock` 的 GPU 作业；不抢占、不删除活跃锁。见[模块边界：并发与生命周期](module-boundaries.md#并发与生命周期)。
- 运行身份（recipe、recipe_hash、模型 SHA256）随结果记录；改变行为须另建身份，不复用旧分数。

重要取舍见[决定索引](../adr/INDEX.md)，证据见[研究索引](../research/INDEX.md)；两者不覆盖当前正文。
