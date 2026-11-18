# 决定索引

本页回答两个问题：**现在什么决定有效**，以及**它是怎么演变过来的**。

2026-11-08 经用户授权做过一次合并精简：每个主题只保留一篇现行 ADR，正文只写仍有效的决定。被并掉的编号（0001、0002、0004、0006、0009、0011、0013、0016）只留两行跳转页，原文见 Git 历史（提交 f139e17 及之前）。历史摇摆只在本页的[演进链](#演进链)里体现。

- 找"当前怎么做"：看 [当前有效决定](#当前有效决定)找主题与权威 ADR，完整定义（配方、hash、仍有效的条款）看 [CURRENT.md](CURRENT.md)。
- 找"为什么变成这样"：看 [演进链](#演进链)，再按链接读当时的 ADR。
- 要做或要记录一个新决定：按 [记录新决定](#记录新决定) 的步骤，在同一次提交里改完。

## 当前有效决定

每行只给一句话和权威出处；配方 id、hash、参数与启动方式的完整定义在 [CURRENT.md](CURRENT.md)。

| 主题 | 现行规则 | 权威出处 |
| --- | --- | --- |
| STT 基线 | W0 为 faster-whisper、X0 为 Qwen-ASR，两路共用新 Pyannote VAD 与 MMS 日语对齐；旧 PyanNet、fixed30、cut-merge 只作历史身份。见 [CURRENT·STT 基线](CURRENT.md#stt-基线与产品-stt) | [0003](0003-new-pyannote-baselines.md) |
| 设备 | ASR 与强制对齐只跑 GPU、不回退 CPU；VAD 可用 CPU 或 GPU，产品固定为 GPU。见 [CURRENT·设备](CURRENT.md#设备) | [0003](0003-new-pyannote-baselines.md)、[0007](0007-bilingual-subtitle-pipeline-architecture.md) |
| 产品 STT 引擎 | `[stt] engine` 可选 `w0`（默认）、`x0`、`cross`（Whisper 交叉打分裁判）；改默认须新 ADR 并在全新隔离素材上确认。见 [CURRENT·产品 STT 引擎](CURRENT.md#产品-stt-引擎) | [0012](0012-cross-asr-judge.md) |
| 产品架构 | 阶段 × 整批推进、每阶段一个子进程，配置文件驱动，按身份与配方 hash 续跑。见 [CURRENT·产品架构](CURRENT.md#产品架构)、[输入、工作目录与发布](CURRENT.md#输入工作目录与发布) | [0007](0007-bilingual-subtitle-pipeline-architecture.md)、[0020](0020-media-inputs-work-dir-and-side-by-side-publish.md)、[0027](0027-no-original-audio-copy.md) |
| 翻译基线（唯一） | Q3 是唯一翻译基线，新测试都以它为对照；引用前任或历史身份（Q2、Q1、Q0、F1、H0）须写明并说明理由；新增后缀命名须用户裁定。见 [CURRENT·翻译基线 Q3](CURRENT.md#翻译基线-q3) | [0021](0021-q3-strata-names-baseline.md)；对照规则见 [0018](0018-q2-sole-translation-baseline.md)；H0／Q0 身份见 [0015](0015-two-translation-baselines.md) |
| 产品翻译 | 产品配方 `q3-translate-v1`＝Q3 翻译规则＋按条收下、只追问未解决的 cue，单条仍失败不出中文；Strata 由产品启停并与建表共用一个 session。见 [CURRENT·产品翻译](CURRENT.md#产品翻译) | [0019](0019-product-translation-q2.md)、[0022](0022-product-names-on-strata.md)、[0029](0029-translate-per-cue-resolution.md) |
| 翻译基线 Q3：身份 | Q2 翻译规则不变，专名表改由同一 Strata 实例上的 Flash-Next 按 `names-strata-v4` 建，失败换 seed 重试、取第一张合格的表。见 [CURRENT·翻译基线 Q3](CURRENT.md#翻译基线-q3) | [0021](0021-q3-strata-names-baseline.md)、[0017](0017-q2-strata-default-launch-baseline.md) |
| 翻译基线 Q2（前任）：身份 | Q1 配方规则＋Strata Flash-Next 默认启动，表由当时的产品 27B 建；只作前任身份。见 [CURRENT·前任 Q2](CURRENT.md#前任-q2) | [0017](0017-q2-strata-default-launch-baseline.md) |
| 方法禁区 | 不自动选用"翻译多次再挑选"类方法：不提议、不列候选、不在无人值守时执行；可靠性重试、按条追问与拆分不算，边界情况先问。见 [CURRENT·方法禁区](CURRENT.md#方法禁区) | [0008](0008-no-multi-translation-selection.md) |
| 专名一致性 | 研究线已结题，重开只由用户明确要求（v13、v15 两次重开均已结束）；产品 `names` 阶段按 `q3-names-v3` 建表，表只经翻译注入、不替换。见 [CURRENT·专名](CURRENT.md#专名)、[产品建表](CURRENT.md#产品建表) | [0014](0014-name-consistency-in-product.md)、[0019](0019-product-translation-q2.md)、[0021](0021-q3-strata-names-baseline.md)、[0022](0022-product-names-on-strata.md)、[0026](0026-names-output-and-prompt-budget.md)、[0028](0028-names-accept-empty-table.md) |
| ASR 整窗守卫 | 产品 w0 路径在 `asr` 阶段解码后依次过三条规则：`repeat-strict` 折叠复读（仍命中则置空）、语速 > 20 字/秒置空、整窗是已知 Whisper 幻听句置空；只做后处理，W0 基线身份不变。见 [CURRENT·ASR 整窗守卫](CURRENT.md#asr-整窗守卫) | [0023](0023-asr-repeat-guard.md)、[0030](0030-asr-window-plausibility-guard.md) |
| 内嵌日文字幕 | 开关开着且有可用日文文本字幕轨时跳过 STT，字幕轨抽取清洗后从 `names` 起走原链；失败回到 STT。见 [CURRENT·内嵌日文字幕](CURRENT.md#内嵌日文字幕) | [0024](0024-embedded-japanese-subtitles.md) |
| 产品包边界与失败级别 | GPU 锁冲突一律进程级结束整批；产品不为研究侧留代码；核心测试不导入研究代码，等价取值在 core 钉字面量（不再有实时对照层）。见 [CURRENT·产品包边界与失败级别](CURRENT.md#产品包边界与失败级别) | [0025](0025-product-package-boundaries.md)、[0031](0031-research-layout-and-lightweight-records.md) |
| 研究与文档布局 | 研究一轮一目录放 `research/`，记录只写策略、版本、测试与结论，不写哈希、本机路径与明细；冻结靠 git 与归档 tag，不靠字节锁；产品不导入 `research/`。见 [CURRENT·研究与文档布局](CURRENT.md#研究与文档布局) | [0031](0031-research-layout-and-lightweight-records.md) |
| 资产清单与安装 | `assets.toml` 只列产品用到的二进制（ffmpeg）与 STT 模型，llama.cpp 与 27B 已移出；`just install` 同步环境并安装清单里的工具，没有单独的 `setup`；ffmpeg 只锁维护分支，实际版本记在 `identity.json` 与运行日志首行。见 [CURRENT·资产清单与安装](CURRENT.md#资产清单与安装) | [0032](0032-drop-llama-cpp-assets.md)、[0033](0033-ffmpeg-branch-lock.md) |

### 未关闭项

待用户裁定的事项、未验证项与已知限制统一汇总在[待用户裁定事项](../pending-decisions.md)（2026-11-11 起；本节原有条目原文移到那里）。新发现的不一致或未关闭项写到那一页，不写在本页。

## 演进链

每条链按时间排列，箭头表示"被替代或被扩展"。日期是采纳日。标"（已合并）"的编号只剩跳转页，当时的全文见 Git 历史（提交 f139e17 及之前）。

- **STT 基线**：
  1. [0001](0001-two-stt-baselines.md)（已合并）（10-04）：W0 用旧 Pyannote，X0 不用 VAD、固定 30 s 分片；10-05 放宽 VAD 设备限制。
  2. → [0002](0002-x0-demo-flow.md)（已合并）（10-05）：X0 demo 与 cut-merge。
  3. → [0003](0003-new-pyannote-baselines.md)（10-05）：两路统一改用新 Pyannote。
  4. → [0007](0007-bilingual-subtitle-pipeline-architecture.md)（10-13／14）：进产品，VAD 固定 `cuda:0`。
  5. → [0012](0012-cross-asr-judge.md)（10-19）：增加可选引擎 `cross`，默认仍 w0。
  6. → [0023](0023-asr-repeat-guard.md)（11-10 采纳，11-11 实现）：产品 w0 路径加整窗复读守卫（`repeat-strict`＋折叠），产品 W0 配方换 id；基线身份不变。
  7. → [0030](0030-asr-window-plausibility-guard.md)（11-18）：守卫加语速（> 20 字/秒）与已知幻听句两条置空规则，产品 W0 配方 `guard-v3`；基线身份不变。
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
  5. → [0029](0029-translate-per-cue-resolution.md)（11-17）：`q3-translate-v1`，回复结构合法即按条收下，只追问未解决的 cue，结构失败才对半拆，单条仍失败不出中文（取代 10→5→1 降级与保留日文）。
- **产品输入、工作目录与发布**：
  1. [0007](0007-bilingual-subtitle-pipeline-architecture.md)（10-13）：只扫视频；`<output_dir>/.work/`；三份 SRT 镜像发布到 `output_dir`，按 `published.json` 判定覆盖、`force`。
  2. → [0020](0020-media-inputs-work-dir-and-side-by-side-publish.md)（11-08）：音频也作输入；`[paths] work_dir`（默认 `.local/work/`）按目标目录分子目录；只发布 `ja-zh.srt` 到源文件旁，已存在即跳过；删 `output_dir` 与 `force`。
  3. → [0024](0024-embedded-japanese-subtitles.md)（11-11）：有可用的内嵌日文文本字幕轨的文件不做 STT，`ja.srt` 取自字幕轨，从 `names` 起走原链；其余文件不变。
  4. → [0027](0027-no-original-audio-copy.md)（11-17）：视频输入也不再流复制原始音轨（`audio.<ext>`），extract 只派生 `audio-16k.wav`；派生命令与 PCM 身份不变。
- **方法禁区**：[0008](0008-no-multi-translation-selection.md)（10-16），放弃 v4 `mbr8c` 与 v5 `mbr8s`。0012、0014–0017 都确认它仍适用。
- **专名一致性**：
  1. [0013](0013-name-consistency-closed.md)（已合并）（10-19）：结题，冻结配置，不进产品。
  2. → [0014](0014-name-consistency-in-product.md)（10-19 同日）：替代第 3 条，进产品 `names` 阶段。
  3. → 该阶段产出的表在 [0016](0016-q1-translation-baseline.md)（已合并） 起用于 Q 线注入。
  4. → [0019](0019-product-translation-q2.md)（11-08）：产品只注入、不替换，建表必开。
  5. → [0022](0022-product-names-on-strata.md)（11-09）：产品建表切到 Strata Flash-Next（`q3-names-v1`，与 Q3 的 `names-strata-v4` 逐字节一致，最多 5 次请求），names 与翻译共用一个 Strata session，产品不再起 llama-server、不加载 27B。
  6. → [0026](0026-names-output-and-prompt-budget.md)（11-12）：产品建表 `max_tokens` 8192 → 16384、提示预算 15872 → 32256（`q3-names-v2`），其余与 `names-strata-v4` 相同。
  7. → [0028](0028-names-accept-empty-table.md)（11-17）：产品建表只在回复格式不合格时换 seed，空表是合法结果（`q3-names-v3`）。
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
  5. → [0031](0031-research-layout-and-lightweight-records.md)（11-18）：删除 `experiments/`、`kototoki_eval/` 与 `tests/equivalence/`；研究改放 `research/<轮次>/`，可以导入产品、产品不导入研究；等价取值只在 core 钉字面量。
  6. → [0032](0032-drop-llama-cpp-assets.md)（11-18）：研究侧不再有使用者，资产清单去掉 llama.cpp 与 27B；`setup` 并入 `install`。→ [0033](0033-ffmpeg-branch-lock.md)（11-18）：钉住的 BtbN 构建被上游删除，ffmpeg 改为只锁维护分支。

## 全部 ADR

| 编号 | 主题 | 状态 |
| --- | --- | --- |
| [0003](0003-new-pyannote-baselines.md) | STT 基线 W0／X0（新 Pyannote） | 有效（并入 0001、0002） |
| [0005](0005-apex-i-compact-translation-baseline.md) | H0 翻译模型、采样与引擎 | 有效（并入 0004） |
| [0007](0007-bilingual-subtitle-pipeline-architecture.md) | 双语字幕流水线架构 | 有效；第 3 点的翻译引擎由 0019 替代、建表引擎由 0022 替代；第 7、9、10 点的工作目录、输出目录锁与发布由 0020 替代；第 7、8 点的原始音轨流复制由 0027 替代 |
| [0008](0008-no-multi-translation-selection.md) | 不自动选用"翻译多次再挑选" | 有效 |
| [0010](0010-dp10-cut-translation-flow-baseline.md) | H0 翻译流程与产品配方（`dp10-cut`／`dp10-cut-degrade-v1`） | 部分有效（并入 0006、0009、0011）：切包规则仍是 Q2 的切包；第 6、7 点产品配方由 0019 替代 |
| [0012](0012-cross-asr-judge.md) | 产品 STT 可选引擎 `cross` | 有效 |
| [0014](0014-name-consistency-in-product.md) | 专名一致性（研究线结题＋进产品） | 部分有效（并入 0013）：替换、开关与 `names_apply` 由 0019 替代；第 3 点的建表模型与 llama-server 由 0022 替代；第 10 点对基线的建表由 0021 替代 |
| [0015](0015-two-translation-baselines.md) | 翻译两条基线：H0 与 Q 线 | 部分有效：两条基线安排由 0018 替代，H0／Q0 身份与测试规则仍有效 |
| [0017](0017-q2-strata-default-launch-baseline.md) | Q 线基线 Q2（含 Q1 规则） | 部分有效（并入 0016）：第 1 点由 0021 替代（基线改为 Q3），Q1／Q2 规则、服务与接入检查仍有效 |
| [0018](0018-q2-sole-translation-baseline.md) | 唯一翻译基线 Q2 | 部分有效：第 1 点由 0021 替代（唯一基线改为 Q3）；第 3 点"产品当前实现"由 0019 替代 |
| [0019](0019-product-translation-q2.md) | 产品翻译切到 Q2 | 有效；第 2 点中的 llama-server 建表与"不同时驻留"由 0022 替代；第 4 点的降级与第 5 点的配方名、hash 由 0029 替代 |
| [0020](0020-media-inputs-work-dir-and-side-by-side-publish.md) | 音频输入、工作目录移出目标目录、双语字幕发布到源文件旁 | 有效 |
| [0021](0021-q3-strata-names-baseline.md) | 唯一翻译基线 Q3（Q2 规则＋Strata 建表，最多 5 次请求） | 有效 |
| [0022](0022-product-names-on-strata.md) | 产品建表切到 Strata（对齐 Q3；names 与翻译共用一个 Strata session） | 有效；第 6 点中 `llama_server.py`"不挪不删"与第 1 点中"由 `tests/core/` 导入 v13 对照"由 0025 替代；第 1、2 点中的 `max_tokens`、context／预算与配方名 `q3-names-v1` 由 0026 替代；第 1 点中把空表算作失败的部分由 0028 替代；第 6 点中保留 llama.cpp 与 27B 清单条目由 0032 替代 |
| [0023](0023-asr-repeat-guard.md) | ASR 阶段整窗复读守卫（`repeat-strict`＋折叠） | 已接受，2026-11-11 已实现；第 4 点配方 id／hash 与第 5 点"不管插入套话"由 0030 替代 |
| [0024](0024-embedded-japanese-subtitles.md) | 有内嵌日文文本字幕轨的文件跳过 STT | 已接受，2026-11-11 已实现；2026-11-12 真实片源（Black Panther）运行通过，forced 判定补认标题（`embedded-ja-subtitle-v2`） |
| [0025](0025-product-package-boundaries.md) | 产品包边界与失败级别（GPU 锁冲突进程级、产品不为研究侧留代码、核心测试不导入研究代码） | 已接受（2026-11-11）；第 4 点中 `tests/equivalence/` 实时对照层由 0031 替代 |
| [0026](0026-names-output-and-prompt-budget.md) | 产品建表放宽输出上限与提示预算（`q3-names-v2`） | 已接受，2026-11-12 已实现；第 3 点配方名与 hash 由 0028 替代 |
| [0027](0027-no-original-audio-copy.md) | 不再流复制原始音轨 | 已接受，2026-11-17 已实现 |
| [0028](0028-names-accept-empty-table.md) | 产品建表只在回复格式不合格时重试，空表是合法结果（`q3-names-v3`） | 已接受，2026-11-17 已实现 |
| [0029](0029-translate-per-cue-resolution.md) | 产品翻译按条收下、只追问未解决的 cue（`q3-translate-v1`） | 已接受，2026-11-17 已实现 |
| [0030](0030-asr-window-plausibility-guard.md) | ASR 整窗守卫加语速与已知幻听句两条规则（`guard-v3`） | 已接受，2026-11-18 已实现 |
| [0031](0031-research-layout-and-lightweight-records.md) | 研究按轮次放进 `research/`，记录精简，冻结靠 git | 已接受（2026-11-18） |
| [0032](0032-drop-llama-cpp-assets.md) | 资产清单去掉 llama.cpp 与 27B，`install` 并入环境同步 | 已接受，2026-11-18 已实现 |
| [0033](0033-ffmpeg-branch-lock.md) | ffmpeg 只锁维护分支，实际版本记在安装目录与运行日志 | 已接受，2026-11-18 已实现 |

跳转页：0001、0002 → 0003；0004 → 0005；0006、0009、0011 → 0010；0013 → 0014；0016 → 0017。新 ADR 编号从 0034 起。

## 记录新决定

用户采纳一个决定（换基线、裁定研究结论、改产品行为）后，在**同一次提交**里完成下面几步：

1. **新增 ADR**：`docs/adr/NNNN-<slug>.md`，编号顺延。写清状态、日期，以及替代了哪篇 ADR 的哪一点；写清身份（配方、hash、入口）、证据，以及未验证的部分。
2. **处理旧 ADR**：默认只在被替代的 ADR 状态行末尾追加"某点自某日起由 ADR-NNNN 替代"，正文不动。只有用户授权合并精简时，才把旧篇改成跳转页、把有效条款并入新篇。
3. **改本页**：在"当前有效决定"里改对应行（一句话加权威链接）并在页尾"更新记录"加一行；在"演进链"的对应链末尾追加一环；在"全部 ADR"里加一行并更新被替代那篇的状态；新发现的不一致或未关闭项写进[待用户裁定事项](../pending-decisions.md)，裁定了其中某项时从那一页删行。
4. **改 [CURRENT.md](CURRENT.md)**：把对应小节改写成新的完整现行定义（配方 id、hash、模型与启动方式、权威条款），并更新"部分被取代的 ADR 仍有效的条款"表；其中每个 hash 与配方 id 都要能在某篇 ADR 正文里逐字找到。
5. **同步摘要入口**：基线变化时，改 [AGENTS.md](../../AGENTS.md)"现行决定与研究约束"中的基线句（只写基线名，定义在 CURRENT.md）；术语有变化时，改 [GLOSSARY.md](../../GLOSSARY.md)；来自研究轮次的决定，在[研究索引](../../research/INDEX.md#轮次登记)改该轮状态，并在该轮 README 的"结论与去向"注明裁定结果；涉及代码时，按[随交付同步](../agents/documentation.md#随交付同步)更新模块页与 README。

不在本页记录的：研究过程、实验数据、未采纳的候选。这些放在 `research/`。

## 更新记录

"当前有效决定"表的改动日志，新的一行加在最前。

- 2026-11-18：ADR-0032 资产清单去掉 llama.cpp 与 27B、`setup` 并入 `install`，新增"资产清单与安装"行；ADR-0033 ffmpeg 改锁维护分支。
- 2026-11-18（research-restructure）：ADR-0031 研究与文档布局，新增"研究与文档布局"行；"产品包边界与失败级别"行去掉实时对照层并加 0031。
- 2026-11-17／18（batch-run-fixes，均采纳并实现）：ADR-0030 ASR 整窗守卫加语速与已知幻听句两条规则（`w0-faster-whisper-large-v3-guard-v3`，票 09，11-18），"ASR 复读守卫"行改名为"ASR 整窗守卫"并加 0030；ADR-0029 产品翻译按条收下、只追问未解决的 cue（`q3-translate-v1`，票 08），"产品翻译"行改配方名与规则并加 0029；ADR-0028 产品建表空表不再重试（`q3-names-v3`，票 07），"专名一致性"行改配方名并加 0028；ADR-0027 不再流复制原始音轨（票 05），"产品架构"行加 0027。
- 2026-11-11（文档架构整理）：表压成每行一句话，完整定义移到 [CURRENT.md](CURRENT.md)；spec §8 的 7 项由用户委托 agent 裁定（结果见该 spec §9）：ADR-0007、0008、0010、0014、0015、0017、0019、0021 状态行追加过时条款的说明，现行表各行不变。
- 2026-11-11：ADR-0025：GPU 锁冲突一律进程级、产品不为研究侧留代码、核心测试不导入研究代码，同日采纳；同日 ADR-0024：有内嵌日文文本字幕轨的文件跳过 STT，采纳并实现；ADR-0023（11-10 采纳）的 ASR 复读守卫已实现并验收；11-12 ADR-0026：产品建表放宽 `max_tokens` 与提示预算（`q3-names-v2`），采纳并实现。
- 2026-11-09：ADR-0021 把唯一基线改为 Q3；同日 ADR-0022 把产品建表切到 Strata，names 与翻译共用一个 Strata session。
- 2026-11-08：合并精简；同日 ADR-0018 定唯一基线 Q2，ADR-0019 把产品翻译切到 Q2，ADR-0020 改输入范围、工作目录与发布。
