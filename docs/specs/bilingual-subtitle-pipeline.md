# 中日双语字幕批量生产流水线：技术设计

状态：implemented（只含跨模块契约；配置参考、环境与历史记录已拆出，见文末"拆出的内容"）  
日期：2026-10-13  
范围：第一个正式产品形态，命令行工具，输入一批日语视频或音频，在源文件旁输出中日双语 SRT。不含 UI、流式、打包、非日语输入。本文只写跨模块契约（阶段链、调度、产物、cue 交界、失败语义）；各模块的完整行为以[架构总览][arch]中的模块页为准，依赖方向与接缝见[模块边界][mb]，取舍见 [ADR-0007][adr7]。

## 1. 目标与边界

- 输入：`input_dir` 下（递归）的本地视频或音频文件（扩展名见[配置参考][cfg]，视频还是音频由 ffprobe 判定）。音频默认视为日语对白。
- 输出（每个输入）：写在源文件所在目录的 `<stem>.ja-zh.srt`（ADR-0007「发布」）；`ja.srt`、译文等中间产物留在工作目录（§4）。源文件旁已有 `<stem>.ja-zh.srt` 即跳过该文件。
- 入口 `python -m kototoki [kototoki.toml]` 只读一份配置文件，没有其他命令行参数；影响模型行为的解码／采样／提示常量是配方常量，留在代码里，不进配置文件（[配置参考][cfg]）。
- 产品不变量继续生效：本地运行、ASR／CTC／翻译只跑 GPU 不回退 CPU、保留日语原文、音频与转写不进 Git 与日志。

### 1.1 固定配方（写死，不做配置项）

| 阶段 | 固定选择 | 依据 |
| --- | --- | --- |
| 音频分离 | 模型输入直接从输入容器按绝对流索引解码，带时间戳对齐（WAV 的 sample 0 即输入 0 秒，`offset_s` 恒为 0）、按声道布局下混单声道、重采样 16 kHz、PCM16 WAV；不流复制原始音轨（§2.1） | 两套 demo 与整片证据的输入身份是 16 kHz 单声道 PCM16；时间戳以输入容器为准，见 §2.2；[ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md) |
| VAD 与分窗 | Pyannote `segmentation-3.0`（revision `e66f3d3b…`），powerset 原生检测，onset／offset 0.5，`source-span-merge-v1`：≤30 s、整数样本坐标、保留块内间隙 | [ADR-0003](../adr/0003-new-pyannote-baselines.md) |
| ASR `w0`（默认） | faster-whisper large-v3（CT2 FP16），固定日语，beam 5，batch 1，逐窗独立、无前文、无时间戳 token，移植的 Whisper 特征链；解码之后过整窗守卫（复读 `repeat-strict`、语速、已知幻听句，§6），产品配方 id `w0-faster-whisper-large-v3-guard-v3` | [W0 契约](../../research/2026-10-stt-demo-w0-x0/README.md)、[ADR-0030](../adr/0030-asr-window-plausibility-guard.md) |
| ASR `x0` | Qwen3-ASR-1.7B-hf，CUDA BF16、SDPA、greedy、`max_new_tokens` 4096，原生 processor | [X0 契约](../../research/2026-10-stt-demo-w0-x0/README.md) |
| ASR `cross`（可选） | 同一 asr worker 内常驻 w0 与 x0：逐文件先 w0、再 x0 转写，由 Whisper 对两路的分歧区间做教师强制打分并合并（阈值 −1.0、无长度项），输出与 `w0`／`x0` 同构的 `asr.json`；阶段链不变 | [ADR-0003](../adr/0003-new-pyannote-baselines.md)、[产品路径验收](../../research/acceptance/2026-10-19-cross-asr-acceptance.md) |
| 强制对齐 | MMS-1b-all `jpn` adapter，CUDA FP32，窗口归一化，字符级 CTC 对齐，`text_only` 记账 | [STT worker](../architecture/modules/stt-workers.md) |
| 日文字幕切分 | 从字符 units 组 cue，规则数值来自配置文件（§5.2） | [日文 cue](../architecture/modules/japanese-cues.md)（起点是研究期的显示契约，见 [STT demo 轮次](../../research/2026-10-stt-demo-w0-x0/README.md)） |
| 翻译 | Q2 规则：Strata 上的 `qwen3.8-flash-next-iq3_s`（Strata 0.2.12／build 0.1.58，`strata launch --no-tui --model iq3_s`，DFlash2），chat completions、无 grammar、思考关闭、采样 0.7／0.8／20，提示 `qwen-joint-v1`；切包 `dp10-cut`（每批待译 ≤10 条），只读邻文 `wide-context-v1`；`confidence: high` 的专名注入；每个请求节点最多两次（seed、seed+1）；产品配方 `q3-translate-v1` | [ADR-0029](../adr/0029-translate-per-cue-resolution.md)、[ADR-0021](../adr/0021-q3-strata-names-baseline.md) |
| 专名建表（必开） | `ja-cues` 与 `translate` 之间的 GPU 阶段 `names`：在与翻译共用的 Strata 上把整份 `ja.srt` 一次送入，取回 `name-table-v2` 专名表并归一，回复格式不合格才依次换 seed、最多 5 次请求，空表直接接受（配方 `q3-names-v3`，与 Q3 的 `names-strata-v4` 只差输出上限 16384、提示预算 32256 与空表不重试）；表只经翻译注入（只注入出现在该批可见台词里的 `confidence: high` 写法），没有发布时替换 | [ADR-0028](../adr/0028-names-accept-empty-table.md)、[ADR-0029](../adr/0029-translate-per-cue-resolution.md)、[专名一致性][names] |
| 双语合并 | 同一 cue 编号与时间，两行：中文在上、日文在下；中文就是翻译结果；未翻译的 cue 只有日文一行（ADR-0029） | 用户裁定 |

### 1.2 已裁定

设计阶段（2026-10-13／14）的裁定表原文见历史记录（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`）；现行规则以[现行决定](../adr/CURRENT.md)、[决定索引](../adr/INDEX.md)与各 ADR（ADR-0007 起）为准。

## 2. 阶段分解

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
| translate | `ja.srt`＋`name-table.json` → 翻译 run 目录 | GPU（独占） | [翻译子系统与双语合并][tr] |
| merge | `ja.srt`＋译文 → `ja-zh.srt`（发布到源文件旁） | CPU | 同上 |

**内嵌日文字幕**（[ADR-0024](../adr/0024-embedded-japanese-subtitles.md)）：`[input] use_embedded_subtitles`（默认 `true`）开着且文件有可用的日文文本字幕轨时，该文件不经 extract、vad、asr、align、ja-cues，改走：

```
probe ──► 抽轨＋清洗（CPU，写 ja.srt 与 ja-embedded.json）──► names ──► translate ──► merge
```

选轨、抽取与清洗规则（配方 `recipes.EMBEDDED`，id `embedded-ja-subtitle-v1`）见[配置、配方与媒体提取][media]；是否采用与回退见[批次编排][orch]。不做：外挂字幕文件、位图字幕 OCR、按内容判断语言、假名注音处理、按 ASS 样式过滤卡拉 OK 行与屏幕字。

### 2.1 不流复制原始音轨

视频输入与音频输入一样，extract 只派生 `audio-16k.wav`，不再把原始音轨流复制为 `audio.<ext>`（[ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md)「输入范围」）：源文件留在原地，工作目录不交付，副本只是重复数据；复制要多读一遍源文件，还曾因坏包让可出字幕的文件整片失败。

### 2.2 时间轴与下混

- **时间零点只在媒体模块定义**：模型输入直接从输入容器解码（容器带时间戳，裸码流不带），`aresample=async=1:first_pts=0` 补齐起始静音（AAC 声明采样率与容器时间戳不符时先按真实采样率纠正，规则见[配置、配方与媒体提取](../architecture/modules/config-and-media.md)），WAV 的 sample 0 即输入 0 秒，因此 `offset_s` 恒为 0；音轨 `start_time` 只进 `probe.json` 作诊断，下游阶段只传 `offset_s = 0`。
- 时长校验、按声道布局的 `pan` 常量（进 `MEDIA` 配方 hash、禁止削波）与重采样器（ffmpeg 默认 swr）见[配置、配方与媒体提取][media]；swr／soxr 的频谱对比与改回 swr 的经过见[历史记录][hist-26]。

## 3. 调度模型：CPU 流水线 + GPU 分阶段批处理

### 3.1 结论

- **CPU 阶段（probe、extract、ja-cues、merge）与 GPU 阶段分开**：extract 用线程池（`[run] extract_workers`）先跑完整批，GPU 阶段再开始，不做流式投喂。
- **GPU 阶段按"阶段 × 整批"推进**：加载 VAD → 跑完本批 → 卸载；ASR、MMS 同理；然后启动 Strata → 为本批全部 `ja.srt` 建专名表 → 不停，翻译本批全部 SRT → `strata launch --stop`。产品只有 Strata 一个服务进程，不起 llama-server；没有批次切分参数。
- 每个 GPU 阶段在**独立子进程**中执行（一个阶段一个子进程）：进程退出即释放显存，崩溃不拖垮编排器。worker 逐文件增量写结果；单文件异常记失败并继续（退出码 1），CUDA 粘性错误退出码 2；worker 异常退出时编排器把正在处理的文件记该阶段失败，再为其后的文件重启 worker，重启按文件计。编排器本身不加载模型、不 import torch（§7.1）。细节见[批次编排][orch]。

### 3.2 为什么这样选

任一时刻只有一个模型驻留（翻译峰值占满 16 GB 整卡），加载开销每阶段每批一次，代价是首个结果要等整批 STT 结束；理由见 [ADR-0007][adr7]，原对比表在[历史记录][hist-26]。唯一例外是 `cross` 的 asr 阶段内 Whisper 与 Qwen 同进程共驻（显存门槛与回退见 [STT worker][stt]）。

### 3.3 GPU 内部顺序与并发

- GPU 阶段严格串行，由 `.local/gpu.lock` 保护（不抢占、不杀进程；破残留锁只认一次性的 `KOTOTOKI_BREAK_STALE_LOCK=1`）。只有编排器获取它：在第一个有文件要跑的 GPU 阶段前获取，持有到翻译结束；names、translate 只在有文件需要模型时才取锁、起 Strata。锁文件记录编排器、当前 worker 与 Strata 的 pid。
- 同一 `input_dir` 同时只允许一个编排器：启动即取 `<work root>/lock`，已被占用则退出码 3。任何阶段撞 GPU 锁都是进程级冲突：整批以退出码 4 结束、不写逐文件 `failure.json`，已完成的产物保留，可续跑（ADR-0025）。
- 不在 GPU 阶段内做多文件并发：W0 契约是 batch 1、逐窗独立，并发只会争抢算力与显存。
- names 与 translate 共用编排持有的一个 Strata session（[ADR-0029](../adr/0029-translate-per-cue-resolution.md)「Strata session」）：第一次真正需要模型时启动，两阶段之间不停，整批结束、出错或中断时 `strata launch --stop`。启动前核对没有别人的 launch、空闲显存足够、身份符合 ADR-0021「Q3 服务与运行顺序」；Strata 起不来或被拒绝（`StrataRefused`）时本批其余需要模型的影片在两个阶段都直接失败。见[专名一致性][names]、[翻译子系统][tr]。

## 4. 产物：中间产物与最终产物

最终产物只有写在源文件旁的双语字幕（`<input_dir>/S1/ep01.mkv` → `<input_dir>/S1/ep01.ja-zh.srt`），其余全在工作目录（ADR-0007「工作目录」）。`[paths] work_dir` 下有共用的 `cache/` 与每个目标目录一个工作根 `<work_dir>/<input_dir 末段名>-<绝对路径 sha12>/`（下称 `<work root>`）；每个输入的工作目录 `<work root>/<id>/`，`<id>` 是相对路径（含扩展名）SHA256 的前 12 位。目标目录改名或移动后对应不上旧工作根，从头重跑。路径、身份与原子写的权威正文是[产物契约][art]。

```
<work_dir>/
  cache/                 HF_HOME／TORCH_HOME 与 model-verification.json，各目标目录共用
  <input_dir 末段名>-<sha12>/    <work root>
    lock、input.json、index.json、jobs-<stage>.json
    strata-sessions/     names 与翻译共用的 Strata session 证据
    run-<戳>.log、run-<戳>-<stage>.stderr.log
    <id>/
      probe.json、audio-16k.wav、extract.log
      vad.json、asr.json（cross 另有 asr-w0.json、asr-x0.json、asr-judge.json，只作审计）、align.json
      ja-cues.json 或 ja-embedded.json（内嵌字幕路径）、ja.srt
      name-table.json、names/transport/…
      translate/srt-<sha12>/<配方名>__s<seed>__n<表sha12>/   翻译 run，可续跑
      publish/<stem>.ja-zh.srt   发布字幕的工作目录副本
      published.json       审计记录，不参与是否发布的判定
      failure.json         任一阶段失败时写
```

规则：

- **每个产物带输入身份与配方 hash**；身份匹配即跳过，不匹配时原地原子替换（`translate/` 按键另开目录，旧目录保留）。输入文件身份 = 相对路径＋大小＋修改时间＋ffprobe 指纹；派生产物身份 = 上游产物 SHA256＋配方 hash＋模型文件 SHA256＋影响输出的配置键；绝对路径不参与身份。组成规则在[产物契约][art]，各阶段的期望身份在[阶段计划][plan]。
- **坐标系**：`vad.json`、`asr.json`、`align.json` 一律 WAV 本地秒／整数样本，顶层带 `offset_s`（产品恒为 0）；offset 只在 ja-cues 阶段加一次，cue 时间即最终 SRT 时间。
- 所有产物保留，不自动删除。
- **发布**：merge 阶段写一份副本到工作目录 `publish/`，再原子写到源文件旁（临时文件在目标目录内，工作目录与输入可在不同卷），成功后写 `published.json`。扫描时源文件旁已有 `<stem>.ja-zh.srt`（只看文件名）即跳过该文件；要重做就删掉这份字幕，中间产物按身份续跑。主名相同的两个输入争用同一字幕路径时，相对路径排序靠后的那个在扫描阶段失败。
- **专名表可人工校对**：跳过只比 `identity`，改 `entries` 不触发重建；改到会被注入的条目会改变 `names_sha256` 与翻译身份，删掉该片的 `*.ja-zh.srt` 后再运行即重译；只改 medium／low 条目不触发重译（[专名一致性][names]）。
- 工作目录之外只写源文件旁的双语字幕；控制台只输出进度、计数与耗时；专名表条目是转写内容，日志只记计数。

## 5. 日文 cue：STT 与翻译的交界

### 5.1 翻译输入为什么是 `ja.srt`

逐条翻译日文 cue，每条中文直接继承那条日文的编号与时间，双语合并只是拼接；翻译 ASR 窗口的整段日文需要把中文切回各句时间，没有可靠方法（[ADR-0007][adr7]）。因此**cue 切分质量同时决定日文字幕可读性与翻译上下文**。

### 5.2 切分规则

键与默认值见[配置参考][cfg]；规则顺序、无时间字符的回填（`time_source`）、毫秒取整见[日文 cue][cues]。双语合并把中文内的换行替换为空格，保证 `ja-zh.srt` 每条恰好两行（未翻译的 cue 只有日文一行；[翻译子系统与双语合并][tr]）。

## 6. 失败、部分结果与续跑

- **文件级隔离**：一个文件在某阶段失败，写 `failure.json`，该文件退出后续阶段，批次继续；最终汇总打印失败清单，退出码非零。
- **内嵌字幕不可用**（ADR-0024）：抽取失败或清洗后零条目，记一行 WARNING，该文件回到 STT 链，不写 `failure.json`，结果不缓存。
- **无语音**：VAD 结果为空时跳过 ASR／对齐／翻译，直接发布零条目 `ja-zh.srt` 并告警。
- **抽取质量门**（batch-run-fixes 04）：视频输入解码时长超过参照时长 1.5 倍判 extract 失败；VAD 语音时长不足参照时长 1% 判 vad 失败。两者都写 `failure.json`。
- **ASR 失败窗口**（w0／x0／cross 同一表示）：x0 生成触顶、w0 整窗守卫置空（复读折叠后仍命中、语速 > 20 字/秒、整窗是已知幻听句；[ADR-0030](../adr/0030-asr-window-plausibility-guard.md)），都只把该窗 `text` 置空、原因与原文记入 `failed_windows`，不进对齐、cue 与翻译，不让整部影片失败（[STT worker][stt]、[产物契约][art]）。
- **Strata 基础设施失败与批次终态**（ADR-0029「基础设施失败」）：OOM、服务崩溃／断开、传输错误、Strata 起不来属基础设施失败，同一调用内重启 Strata，最多 2 次；生成触顶、结构校验失败、超出 context、一条都没收下是该次尝试失败，两次都失败即节点终态，进入拆分；`StrataRefused` 不重试，本批其余需要模型的影片直接失败。
- **按条解决**（产品规则，配方另名 `q3-translate-v1`，ADR-0029）：回复结构合法即按条收下，缺失、空串、含空行的 cue 按最大连续段再问；两次都失败的节点对半拆，单条仍失败该 cue 不出中文，双语字幕里只有日文一行；未翻译清单写 `report.json` 并在汇总给出未翻译数。可靠性重试、按条追问与拆分都不是"翻译多次再挑选"（ADR-0008）。见[翻译子系统][tr]。
- **专名建表失败**（ADR-0028「建表失败」）：超预算或 5 次回复格式都不合格写空表（模型回空表不算失败，ADR-0028）（`build.status` 为 `too_long`／`failed`），记 WARNING，影片照常翻译与发布；Strata 起不来、OOM、HTTP 或传输失败是该影片 `names` 阶段的文件级失败（[专名一致性][names]）。
- **续跑**：重跑同一命令即可，已完成的产物按身份跳过；翻译按批次增量落盘，中断后从未完成的批次继续。未翻译的 cue 对该身份是终态；要重试须改 `[translate] seed`（另起 run 目录、整片重译）；要重做已发布的文件须先删掉其 `.ja-zh.srt`（ADR-0007「发布」）。

## 7. 进程、环境与依赖

### 7.1 进程模型

```
python -m kototoki kototoki.toml  (编排器：唯一持有 .local/gpu.lock；不 import torch)
 ├─ ThreadPool → ffmpeg/ffprobe 子进程（CPU 队列）
 ├─ python -m kototoki.workers.{vad,asr,align} --jobs <work root>/jobs-<stage>.json  (每阶段一个子进程；asr 引擎取 jobs 的 config.engine)
 ├─ Strata（strata launch）+ 进程内 HTTP 客户端：先逐片建专名表，再循环翻译
 └─ 进程内 ja-cues / merge
```

- worker 之间只通过 `<work root>/<id>/` 下的 JSON 交接，每阶段重验输入身份；编排器与 worker 用同一解释器（`sys.executable`）。
- 所有 worker 与 Strata CLI 子进程放进 KILL_ON_JOB_CLOSE Job Object；Strata 服务由 `strata launch` 在后台启动、不在 Job Object 内，靠 session 退出时的 `--stop` 收尾，编排器被强杀时它可能残留，下次运行拒绝，须手动 `strata launch --stop`。
- 编排器为 worker 设置离线环境（`HF_HUB_OFFLINE=1`、`HF_HOME`／`TORCH_HOME` 指向 `<work_dir>/cache/` 等）与 `PYTHONUTF8=1`。ASR worker 先 `import torch` 再导入 CTranslate2；"编排器不 import torch"有测试。细节见[批次编排][orch]与 [STT worker][stt]。

### 7.2–7.4 环境、代码布局、上游版本

当前环境、版本、选版规则与 CUDA 说明见[技术选型](../development/technology-stack.md)与[依赖布局与资产清单](../development/dependencies.md)；当前文件布局见[架构总览][arch]；原文（含 2026-10-13 上游版本核实表）见历史记录（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`）。

## 10. 配置文件 `kototoki.toml`

见[配置参考][cfg]。

## 11. 未来方向

未裁定事项与未来方向见[待裁定事项](../pending-decisions.md)与 `.scratch/next-directions/issues/` 的票据；本节原文见历史记录（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`）。

## 拆出的内容

2026-11-11 文档架构整理（票据 09）把下列内容移出本文：

| 原章节 | 去向 |
| --- | --- |
| 状态行修订历史、§1.2、§8、§9、§11、§12、§13 | 历史记录原文（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`） |
| §2 的单片成本列、§2.2 重采样经过、§3.2 对比表、§3.4 时间线 | 历史记录原文（同上，"原第 2 至 6 节中移出的原文"一节）；理由见 [ADR-0007][adr7] |
| §2 各阶段细则、§2.1、§2.2 时长校验与下混 | [配置、配方与媒体提取][media]、各模块页 |
| §4、§6 的逐模块细则 | [产物契约][art]、[阶段计划][plan]、[批次编排][orch]、[翻译子系统][tr]、[专名一致性][names] |
| §5.2 规则表 | [配置参考][cfg]、[日文 cue][cues] |
| §7.1 的 DLL 与导入细节 | [STT worker][stt]、[批次编排][orch] |
| §7.2–§7.4 | [技术选型](../development/technology-stack.md)、[依赖布局与资产清单](../development/dependencies.md)；原文在历史记录（同上） |
| §10 | [配置参考][cfg] |

[arch]: ../architecture/INDEX.md
[mb]: ../architecture/module-boundaries.md
[adr7]: ../adr/0007-bilingual-subtitle-pipeline-architecture.md
[cfg]: ../architecture/modules/config-reference.md
[media]: ../architecture/modules/config-and-media.md
[stt]: ../architecture/modules/stt-workers.md
[cues]: ../architecture/modules/japanese-cues.md
[names]: ../architecture/modules/name-consistency.md
[tr]: ../architecture/modules/translation-subsystem.md
[orch]: ../architecture/modules/batch-orchestration.md
[plan]: ../architecture/modules/stage-plan.md
[art]: ../architecture/modules/artifact-contract.md
