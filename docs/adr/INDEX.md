# 决定索引

本页回答两个问题：**现在什么决定有效**，以及**它是怎么演变过来的**。

2026-11-08 经用户授权做过一次合并精简：每个主题只保留一篇现行 ADR，正文只写仍有效的决定。被并掉的编号（0001、0002、0004、0006、0009、0011、0013、0016）只留两行跳转页，原文见 Git 历史（提交 f139e17 及之前）。历史摇摆只在本页的[演进链](#演进链)里体现。

- 找"当前怎么做"：看 [当前有效决定](#当前有效决定)。表里每一行给出现行规则，以及权威 ADR 的哪一条。
- 找"为什么变成这样"：看 [演进链](#演进链)，再按链接读当时的 ADR。
- 要做或要记录一个新决定：按 [记录新决定](#记录新决定) 的步骤，在同一次提交里改完。
- 研究轮次的过程与裁定时间线在[调研索引·决定与探索时间线](../research/INDEX.md#决定与探索时间线)。本页只收采纳的决定。

## 当前有效决定

更新于 2026-11-11（ADR-0025：GPU 锁冲突一律进程级、产品不为研究侧留代码、核心测试不导入研究代码，同日采纳；同日 ADR-0024：有内嵌日文文本字幕轨的文件跳过 STT，采纳并实现；ADR-0023 的 ASR 复读守卫已实现并验收）。此前 2026-11-10（ADR-0023 采纳）、2026-11-09（ADR-0021 把唯一基线改为 Q3；同日 ADR-0022 把产品建表切到 Strata，names 与翻译共用一个 Strata session）。2026-11-08 合并精简；同日 ADR-0018 定唯一基线 Q2，ADR-0019 把产品翻译切到 Q2，ADR-0020 改输入范围、工作目录与发布。

| 主题 | 现行规则 | 权威出处 |
| --- | --- | --- |
| STT 基线 | **W0**：faster-whisper＋新 Pyannote VAD＋MMS `jpn` CTC。须用自有适配层移植 WhisperX 的切分合并与独立解码。**X0**：Qwen-ASR＋同一 VAD＋MMS。新 Pyannote＝`pyannote.audio 4.0.7`＋`pyannote/segmentation-3.0`（rev `e66f3d3b…`）。旧 PyanNet W0、fixed30、cut-merge 只作历史身份 | [0003](0003-new-pyannote-baselines.md) |
| 设备 | ASR 与强制对齐只跑 GPU，不回退 CPU；VAD 可用 CPU 或 GPU（产品固定 `cuda:0`） | [0003](0003-new-pyannote-baselines.md)、[0007](0007-bilingual-subtitle-pipeline-architecture.md) |
| 产品 STT 引擎 | `[stt] engine` = `w0`（默认）｜`x0`｜`cross`（`cross-w0-x0-whisper-judge-v1`，Whisper 交叉打分，d > −1.0 取 x0）。改默认须新 ADR，并在全新隔离素材上确认 | [0012](0012-cross-asr-judge.md) |
| 产品架构 | GPU 阶段按"阶段 × 整批"推进，每阶段一个子进程。阶段链为 `vad` → `asr` → `align`（MMS）→ `cues` → **`names`** → `translate` → publish。单一 CUDA 12.8 Python 3.13 环境；建表与翻译用同一个由产品自动启停的 Strata session，整批只启动一次，产品不起 llama-server。`kototoki.toml` 驱动，无 CLI。视频与音频都是输入（ffprobe 判定，音频不做流复制）。工作目录在 `[paths] work_dir`（默认 `.local/work/`）下按目标目录分子目录，每片一个工作目录，按身份与配方 hash 续跑；只发布 `<主名>.ja-zh.srt` 到源文件旁，已存在即跳过该文件 | [0007](0007-bilingual-subtitle-pipeline-architecture.md)；names 阶段见 [0014](0014-name-consistency-in-product.md)；翻译服务见 [0019](0019-product-translation-q2.md)；建表服务与共享 Strata session 见 [0022](0022-product-names-on-strata.md)；输入、工作目录与发布见 [0020](0020-media-inputs-work-dir-and-side-by-side-publish.md) |
| 翻译基线（唯一） | **Q3** 是唯一翻译基线，新的翻译测试都以 Q3 为对照；引用 Q2、Q1、Q0、F1、H0 时须写明并说明理由。Q2 是前任身份；H0 不再是基线，只作历史对照的身份（身份见 0005、0010）。新增后缀命名须用户裁定 | [0021](0021-q3-strata-names-baseline.md)；对照规则沿用 [0018](0018-q2-sole-translation-baseline.md) 第 2、4 点；H0／Q0 身份见 [0015](0015-two-translation-baselines.md) |
| 产品翻译 | 产品配方 `q2-degrade-v1`（`332649cf…`）＝ Q2 规则＋失败包按 10→5→1 降级、单条仍失败保留日文。切包 `dp10-cut`、邻文 `wide-context-v1`，请求与研究侧 Q2 逐字节相同。Strata 由产品启停（`strata launch --no-tui --model iq3_s`，接入检查同 ADR-0017），session 与 names 建表共用（0022），整批结束或出错都 `--stop` 并核实显存。翻译身份含注入行 SHA：手改表的 high 条目即重译 | [0019](0019-product-translation-q2.md) |
| **翻译基线 Q3：身份** | Q2 的翻译规则不变，只换注入表的来源：表由同一个 Strata 实例上的 Flash-Next 建，建表配方 `names-strata-v4`（`38cb7bcd…`）＝产品 `BUILD` 去掉 llama.cpp 资产、`max_tokens` 8192＋context 24576（预算 15872）、不发 `response_format`、`enable_thinking: false`、`count_tokens` 预算检查，失败后依次换 seed 最多 5 次请求，取第一张合格的表（不挑选）。同一 session 先建表再翻译，不起 llama-server。产品自 0022 起按同一规则建表（配方 `q3-names-v1`）。dev 剧集 wrong-referent 显著变差、两次建表差别大，用户已知并接受 | [0021](0021-q3-strata-names-baseline.md) |
| 翻译基线 Q2（前任）：身份 | Q1 的配方规则不变：`qwen-wide`，加产品 `names` 建表中 `confidence: high` 的专名注入，不做事后替换。模型换为 Strata 0.2.12 上的 `qwen3.8-flash-next-iq3_s`，服务用不加参数的 `strata launch`（DFlash2）。配方带 `strata_launch: "default"`，不用 grammar。每个输入一个实例。质量证据来自 v12 F1；Q2 的启动配置本身未跑过翻译 | [0017](0017-q2-strata-default-launch-baseline.md)（含 Q1 规则）；Q0 身份见 [0015](0015-two-translation-baselines.md) |
| 方法禁区 | 不自动选用"翻译多次再挑选"（MBR、best-of-N、多次投票及更省的变体）：不提议、不列候选、不在无人值守时执行。两次可靠性重试与 10→5→1 降级不算在内。边界情况先问 | [0008](0008-no-multi-translation-selection.md) |
| 专名一致性 | 研究线已结题，不开新轮次，建表配置冻结（no-think、提示 v5；v13 由用户明确要求重开，产出 Q3 的 Strata 建表配方；2026-11-10 用户再次明确要求在 v15 重开，范围限日文转写侧的表内写法替换；2026-11-11 用户裁定该替换不进产品，这次重开结束）。产品 `names` 阶段在与翻译共用的 Strata session 上用 Flash-Next 建表（配方 `q3-names-v1`，请求与 seed 序列与 Q3 的 `names-strata-v4` 逐字节一致，最多 5 次请求），必开，不起 llama-server；表只经翻译注入（high 条目）使用，没有发布时替换；表可手改，改到注入行即重译 | [0014](0014-name-consistency-in-product.md)；替换与开关的删除见 [0019](0019-product-translation-q2.md)；基线的建表见 [0021](0021-q3-strata-names-baseline.md)；产品建表与共享 session 见 [0022](0022-product-names-on-strata.md) |
| ASR 复读守卫 | 产品 w0 路径（含 `cross` 的 w0 那一路；x0 不过守卫）在 `asr` 阶段解码后过守卫：规则 `repeat-strict`（规范化文本上周期 ≥2 的相邻重复 ≥10 份，或 ≥3 字子串不重叠出现 ≥10 次，且覆盖 ≥50%），动作折叠（保留第一个单元），折叠后仍命中则按 `failed_windows` 置空（原因 `guard:repeat-strict`），trace 记 `guard`。只做后处理，不重解码；W0 基线身份不变，产品 W0 配方 id `w0-faster-whisper-large-v3-guard-v2`（2026-11-11 实现，旧 `asr.json` 重算） | [0023](0023-asr-repeat-guard.md) |
| 内嵌日文字幕 | `[input] use_embedded_subtitles`（默认 `true`）开着且文件有可用的日文文本字幕轨（语言相符、`subrip`／`ass`／`ssa`／`mov_text`／`webvtt`、非 forced；多条取 default 再取索引最小）时，该文件不做 STT：probe → ffmpeg 抽轨转 SRT＋清洗（去标签、多行并一行、丢空条目／绘图指令／重复、按时间排序）写 `ja.srt` 与 `ja-embedded.json` → `names` → `translate` → publish，不提取音频。抽取失败或零条目回到 STT 链并告警。配方 `embedded-ja-subtitle-v1`。不读外挂字幕、不做位图 OCR、不检测内容语言、不过滤听障说明 | [0024](0024-embedded-japanese-subtitles.md) |
| 产品包边界与失败级别 | 任何阶段撞 `.local/gpu.lock` 都以退出码 4 结束整批，不写逐文件 `failure.json`，已完成的 CPU 产物保留。产品不为研究侧导入方保留代码：`kototoki/llama_server.py` 拆掉，产品剩 `kototoki/local_client.py`（`LlamaClient`、`InfraFailure`、`explicit_oom`），llama-server 进程生命周期代码在 `experiments/translation_v3/llama_server.py`。产品符号移动或改名时同一提交里机械改研究侧导入行（Q3 实现的离线测试须仍通过）。`tests/core` 不导入 `experiments.*`：等价钉字面量／sha256，实时对照在 `tests/equivalence/`（`just test-equivalence`，属 `gate-full`） | [0025](0025-product-package-boundaries.md) |

### 未关闭项

合并时已把各 ADR 的过时措辞改为现行事实。仍然成立的未关闭项：

- **引擎并存**：H0 研究侧仍用 compat loader b11429，产品用官方 llama.cpp（现行 b11669，以[技术选型](../development/technology-stack.md)为准）。研究侧是否同步升级，未裁定（[0005](0005-apex-i-compact-translation-baseline.md)）。
- **W0／X0 demo 的 CLI 旧默认**：省略参数时仍落到旧 PyanNet／fixed30，须显式选择新 Pyannote（[0003](0003-new-pyannote-baselines.md)）。
- ~~产品与基线 Q3 不一致~~（2026-11-09 提出，同日由 [0022](0022-product-names-on-strata.md) 关闭：产品建表切到 Strata，规则与 Q3 逐字节一致；翻译仍是 `q2-degrade-v1`＝Q2 规则＋降级）。
- **未裁定或未验证**：
  - Q2 在产品里曾每包约 16 s（v12 F1 的 6 倍），原因是启动时整机内存不够放下专家区、引擎退到 mmap；专家锁进内存后整片重跑每包约 3.1 s（2026-11-08，[翻译子系统模块页](../architecture/modules/translation-subsystem.md#代码与验证入口)）；产品已改为启动前等可用内存、ready 后确认专家全部锁进内存、退到 mmap 即拒绝（[0019](0019-product-translation-q2.md)），因此需要约 52 GiB 可用内存；同 seed 跨 Strata 启动不可复现；产品进程被强杀时 Strata 可能留在后台，须手动 `strata launch --stop`；
  - 给新 SRT 生成 Q1／Q2／Q3 翻译配方已有 `v13.write_q2`；用 Q3 规则建表的通用入口自 0022 起是产品的 names 阶段（研究侧 v13 仍只覆盖固定输入）；Q3 的产品结果只来自一次建表，同一部片两次建表写法 Jaccard 只有 0.56／0.48（[0021](0021-q3-strata-names-baseline.md)）；
  - `cross` 尚未在新素材上确认（[0012](0012-cross-asr-judge.md)）；
  - 音频输入未用真实音频文件跑过整条链；音频时长偏短只告警，损坏的音频文件会出不完整字幕（[0020](0020-media-inputs-work-dir-and-side-by-side-publish.md)）；
  - 内嵌日文字幕路径只用合成片段验证过：没有用真实片源跑过，ASS 的卡拉 OK／屏幕字噪声未知，Strata 对人工字幕输入的建表与翻译未做真实模型验证（[0024](0024-embedded-japanese-subtitles.md)）。

## 演进链

每条链按时间排列，箭头表示"被替代或被扩展"。日期是采纳日。标"（已合并）"的编号只剩跳转页，当时的全文见 Git 历史（提交 f139e17 及之前）。

- **STT 基线**：
  1. [0001](0001-two-stt-baselines.md)（已合并）（10-04）：W0 用旧 Pyannote，X0 不用 VAD、固定 30 s 分片；10-05 放宽 VAD 设备限制。
  2. → [0002](0002-x0-demo-flow.md)（已合并）（10-05）：X0 demo 与 cut-merge。
  3. → [0003](0003-new-pyannote-baselines.md)（10-05）：两路统一改用新 Pyannote。
  4. → [0007](0007-bilingual-subtitle-pipeline-architecture.md)（10-13／14）：进产品，VAD 固定 `cuda:0`。
  5. → [0012](0012-cross-asr-judge.md)（10-19）：增加可选引擎 `cross`，默认仍 w0。
  6. → [0023](0023-asr-repeat-guard.md)（11-10 采纳，11-11 实现）：产品 w0 路径加整窗复读守卫（`repeat-strict`＋折叠），产品 W0 配方换 id；基线身份不变。
- **翻译模型与采样（H0）**：
  1. [0004](0004-hy-mt2-translation-baseline.md)（已合并）（10-06）：Q3_K_M，greedy，上下文 4096。
  2. → [0005](0005-apex-i-compact-translation-baseline.md)（10-07）：APEX-I-Compact；10-08 改为 `official30b-cached-v1`。
  3. → [0007](0007-bilingual-subtitle-pipeline-architecture.md)（10-14）：产品引擎换成官方 llama.cpp。
  4. → [0015](0015-two-translation-baselines.md)（10-21）：命名为 H0。
  5. → [0018](0018-q2-sole-translation-baseline.md)（11-08）：不再是基线，只作产品当前实现与历史对照。
  6. → [0019](0019-product-translation-q2.md)（11-08 同日）：产品也不再用，只剩历史对照身份。
- **翻译流程（切包与提示）**：
  1. [0005](0005-apex-i-compact-translation-baseline.md) 的 C0（每包 5 条目标，前后各 1 条邻文）。
  2. → [0006](0006-b10-joint-translation-flow-baseline.md)（已合并）（10-11）：`b10-joint`，即 10 条目标＋joint 提示。
  3. → [0009](0009-dp6-grp-translation-flow-baseline.md)（已合并）（10-17）：`dp6-grp`。
  4. → [0010](0010-dp10-cut-translation-flow-baseline.md)（10-17 同日）：`dp10-cut`，提示不变。
- **产品翻译配方**：
  1. [0007](0007-bilingual-subtitle-pipeline-architecture.md)（10-13）：`b10-joint-degrade-v1`。
  2. → [0011](0011-dp10-cut-product-recipe.md)（已合并）（10-18）：`dp10-cut-degrade-v1`。
  3. → [0019](0019-product-translation-q2.md)（11-08）：`q2-degrade-v1`，即 Q2 规则＋降级；Strata 由产品启停，删除发布时替换与 `[names] enabled`。
  4. → [0022](0022-product-names-on-strata.md)（11-09）：配方不变；Strata session 改为与 names 建表共用，生命周期下沉到 `kototoki/strata.py`。
- **产品输入、工作目录与发布**：
  1. [0007](0007-bilingual-subtitle-pipeline-architecture.md)（10-13）：只扫视频；`<output_dir>/.work/`；三份 SRT 镜像发布到 `output_dir`，按 `published.json` 判定覆盖、`force`。
  2. → [0020](0020-media-inputs-work-dir-and-side-by-side-publish.md)（11-08）：音频也作输入；`[paths] work_dir`（默认 `.local/work/`）按目标目录分子目录；只发布 `ja-zh.srt` 到源文件旁，已存在即跳过；删 `output_dir` 与 `force`。
  3. → [0024](0024-embedded-japanese-subtitles.md)（11-11）：有可用的内嵌日文文本字幕轨的文件不做 STT，`ja.srt` 取自字幕轨，从 `names` 起走原链；其余文件不变。
- **方法禁区**：[0008](0008-no-multi-translation-selection.md)（10-16），放弃 v4 `mbr8c` 与 v5 `mbr8s`。0012、0014–0017 都确认它仍适用。
- **专名一致性**：
  1. [0013](0013-name-consistency-closed.md)（已合并）（10-19）：结题，冻结配置，不进产品。
  2. → [0014](0014-name-consistency-in-product.md)（10-19 同日）：替代第 3 条，进产品 `names` 阶段。
  3. → 该阶段产出的表在 [0016](0016-q1-translation-baseline.md)（已合并） 起用于 Q 线注入。
  4. → [0019](0019-product-translation-q2.md)（11-08）：产品只注入、不替换，建表必开。
  5. → [0022](0022-product-names-on-strata.md)（11-09）：产品建表切到 Strata Flash-Next（`q3-names-v1`，与 Q3 的 `names-strata-v4` 逐字节一致，最多 5 次请求），names 与翻译共用一个 Strata session，产品不再起 llama-server、不加载 27B。
- **Q 线基线**：
  1. [0015](0015-two-translation-baselines.md)（10-21）：**Q0**＝Qwen3.8-27B＋`qwen-wide`（`719237b9…`），来自 v9。
  2. → [0016](0016-q1-translation-baseline.md)（已合并）（11-08）：**Q1**＝Q0＋只注入 high 条目的专名表，来自 v11。
  3. → [0017](0017-q2-strata-default-launch-baseline.md)（11-08 同日）：**Q2**＝Q1 规则＋Strata Flash-Next，不加参数启动、DFlash2。v12 的 F1 是同一规则下 MTP 启动的候选。
  4. → [0018](0018-q2-sole-translation-baseline.md)（11-08 同日）：Q2 成为唯一翻译基线，H0 退出基线。
  5. → [0019](0019-product-translation-q2.md)（11-08 同日）：产品翻译切到 Q2。
  6. → [0021](0021-q3-strata-names-baseline.md)（11-09）：**Q3**＝Q2 翻译规则＋Strata Flash-Next 建表（`names-strata-v4`，最多 5 次请求），来自 v13；产品建表同日由 0022 切换。
- **产品包与研究代码的边界**：
  1. [0007](0007-bilingual-subtitle-pipeline-architecture.md)（10-13）：产品包不导入 `experiments.*`，历史实现只复制。
  2. → [0014](0014-name-consistency-in-product.md)（10-19）：翻译与建表两个使用者出现，llama-server 生命周期抽成共享的 `kototoki/llama_server.py`。
  3. → [0022](0022-product-names-on-strata.md)（11-09）：产品不再起 llama-server，`ManagedServer` 等只剩研究侧使用者，留在原文件；等价由 `tests/core/` 导入 v13 守门。
  4. → [0025](0025-product-package-boundaries.md)（11-11）：产品不为研究侧留代码（`llama_server.py` 拆成产品的 `local_client.py` 与 `experiments/translation_v3/llama_server.py`），研究侧导入行随产品符号机械改，`tests/core` 不导入 `experiments.*`、实时对照移到 `tests/equivalence/`；GPU 锁冲突一律进程级（退出码 4）。

## 全部 ADR

| 编号 | 主题 | 状态 |
| --- | --- | --- |
| [0003](0003-new-pyannote-baselines.md) | STT 基线 W0／X0（新 Pyannote） | 有效（并入 0001、0002） |
| [0005](0005-apex-i-compact-translation-baseline.md) | H0 翻译模型、采样与引擎 | 有效（并入 0004） |
| [0007](0007-bilingual-subtitle-pipeline-architecture.md) | 双语字幕流水线架构 | 有效；第 3 点的翻译引擎由 0019 替代、建表引擎由 0022 替代；第 7、9、10 点的工作目录、输出目录锁与发布由 0020 替代 |
| [0008](0008-no-multi-translation-selection.md) | 不自动选用"翻译多次再挑选" | 有效 |
| [0010](0010-dp10-cut-translation-flow-baseline.md) | H0 翻译流程与产品配方（`dp10-cut`／`dp10-cut-degrade-v1`） | 部分有效（并入 0006、0009、0011）：切包规则仍是 Q2 的切包；第 6、7 点产品配方由 0019 替代 |
| [0012](0012-cross-asr-judge.md) | 产品 STT 可选引擎 `cross` | 有效 |
| [0014](0014-name-consistency-in-product.md) | 专名一致性（研究线结题＋进产品） | 部分有效（并入 0013）：替换、开关与 `names_apply` 由 0019 替代；第 3 点的建表模型与 llama-server 由 0022 替代；第 10 点对基线的建表由 0021 替代 |
| [0015](0015-two-translation-baselines.md) | 翻译两条基线：H0 与 Q 线 | 部分有效：两条基线安排由 0018 替代，H0／Q0 身份与测试规则仍有效 |
| [0017](0017-q2-strata-default-launch-baseline.md) | Q 线基线 Q2（含 Q1 规则） | 部分有效（并入 0016）：第 1 点由 0021 替代（基线改为 Q3），Q1／Q2 规则、服务与接入检查仍有效 |
| [0018](0018-q2-sole-translation-baseline.md) | 唯一翻译基线 Q2 | 部分有效：第 1 点由 0021 替代（唯一基线改为 Q3）；第 3 点"产品当前实现"由 0019 替代 |
| [0019](0019-product-translation-q2.md) | 产品翻译切到 Q2 | 有效；第 2 点中的 llama-server 建表与"不同时驻留"由 0022 替代 |
| [0020](0020-media-inputs-work-dir-and-side-by-side-publish.md) | 音频输入、工作目录移出目标目录、双语字幕发布到源文件旁 | 有效 |
| [0021](0021-q3-strata-names-baseline.md) | 唯一翻译基线 Q3（Q2 规则＋Strata 建表，最多 5 次请求） | 有效 |
| [0022](0022-product-names-on-strata.md) | 产品建表切到 Strata（对齐 Q3；names 与翻译共用一个 Strata session） | 有效；第 6 点中 `llama_server.py`"不挪不删"与第 1 点中"由 `tests/core/` 导入 v13 对照"由 0025 替代 |
| [0023](0023-asr-repeat-guard.md) | ASR 阶段整窗复读守卫（`repeat-strict`＋折叠） | 已接受，2026-11-11 已实现 |
| [0024](0024-embedded-japanese-subtitles.md) | 有内嵌日文文本字幕轨的文件跳过 STT | 已接受，2026-11-11 已实现（真实片源与真实模型验证未做） |
| [0025](0025-product-package-boundaries.md) | 产品包边界与失败级别（GPU 锁冲突进程级、产品不为研究侧留代码、核心测试不导入研究代码） | 已接受（2026-11-11），实现见计划 `architecture-cleanup` §7 |

跳转页：0001、0002 → 0003；0004 → 0005；0006、0009、0011 → 0010；0013 → 0014；0016 → 0017。新 ADR 编号从 0026 起。

## 记录新决定

用户采纳一个决定（换基线、裁定研究结论、改产品行为）后，在**同一次提交**里完成下面几步：

1. **新增 ADR**：`docs/adr/NNNN-<slug>.md`，编号顺延。写清状态、日期，以及替代了哪篇 ADR 的哪一点；写清身份（配方、hash、入口）、证据，以及未验证的部分。
2. **处理旧 ADR**：默认只在被替代的 ADR 状态行末尾追加"某点自某日起由 ADR-NNNN 替代"，正文不动。只有用户授权合并精简时，才把旧篇改成跳转页、把有效条款并入新篇。
3. **改本页**：
   - 在"当前有效决定"里改对应行和"更新于"日期；
   - 在"演进链"的对应链末尾追加一环；
   - 在"全部 ADR"里加一行，并更新被替代那篇的状态；
   - 新发现的不一致或未关闭项写进"未关闭项"。
4. **同步摘要入口**：
   - 基线变化时，改 [AGENTS.md](../../AGENTS.md)"冻结证据与基线身份"中的基线句；
   - 术语有变化时，改 [GLOSSARY.md](../../GLOSSARY.md)；
   - 来自研究轮次的决定，在[调研索引时间线](../research/INDEX.md#决定与探索时间线)加一行，并在该轮文档的待裁定项下注明裁定结果；
   - 涉及代码时，按[随交付同步](../agents/documentation.md#随交付同步)更新模块页与 README。

不在本页记录的：研究过程、实验数据、未采纳的候选。这些放在 `docs/research/`。
