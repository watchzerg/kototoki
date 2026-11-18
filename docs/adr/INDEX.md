# 决定索引

本页回答两个问题：**现在什么决定有效**，以及**它是怎么演变过来的**。

2026-11-18 经用户授权按主题合并：每个主题只保留一篇 ADR，正文改写成该主题完整的现行决定；被并掉的 22 篇（0001、0002、0004–0006、0009–0020、0022、0023、0026、0027、0032）已删除，原文见 Git 历史（提交 807de3e 及之前）与归档 tag `archive/2026-11-18-pre-research-restructure`。旧编号只在本页[演进链](#演进链)与各 ADR 的"沿革"里以纯文本出现。

- 找"当前怎么做"：看[当前有效决定](#当前有效决定)找主题与 ADR；速查关键身份（配方、hash、启动方式）看 [CURRENT.md](CURRENT.md)。
- 找"为什么变成这样"：看[演进链](#演进链)与各 ADR 的"依据""沿革"。
- 要做或要记录一个新决定：按[记录新决定](#记录新决定)的步骤，在同一次提交里改完。

## 当前有效决定

| 主题 | 现行规则 | ADR |
| --- | --- | --- |
| STT 基线、设备与产品 STT 引擎 | W0 为 faster-whisper、X0 为 Qwen-ASR，共用新 Pyannote VAD 与 MMS 日语对齐；ASR 与对齐只跑 GPU；`[stt] engine` 可选 `w0`（默认）、`x0`、`cross` | [0003](0003-new-pyannote-baselines.md) |
| ASR 整窗守卫 | 产品 w0 路径解码后依次过复读折叠、语速 > 20 字/秒、已知幻听句三条规则；W0 基线身份不变 | [0030](0030-asr-window-plausibility-guard.md) |
| 产品架构、输入与发布 | 阶段 × 整批、每阶段一个子进程，配置驱动，按身份与配方 hash 续跑；音频也是输入；工作目录在 `work_dir`；只把 `ja-zh.srt` 发布到源文件旁，已存在即跳过 | [0007](0007-bilingual-subtitle-pipeline-architecture.md) |
| 内嵌日文字幕 | 有可用日文文本字幕轨时跳过 STT，从 `names` 起走原链 | [0024](0024-embedded-japanese-subtitles.md) |
| 翻译基线（唯一）与历史身份 | Q3 是唯一翻译基线，新测试以它为对照；Q2、Q1、Q0、F1、H0 只作前任或历史身份，引用须写明 | [0021](0021-q3-strata-names-baseline.md) |
| 产品翻译 | `q3-translate-v1`：Q3 翻译规则＋按条收下、只追问未解决的 cue；Strata 由产品启停，与建表共用一个 session | [0029](0029-translate-per-cue-resolution.md) |
| 产品建表与专名 | 研究线已结题；`names` 阶段按 `q3-names-v3` 在 Strata 上建表，空表合法，表只经翻译注入 | [0028](0028-names-accept-empty-table.md) |
| 方法禁区 | 不自动选用"翻译多次再挑选"类方法；可靠性重试、按条追问与拆分不算 | [0008](0008-no-multi-translation-selection.md) |
| 产品包边界与失败级别 | GPU 锁冲突进程级结束整批；产品不为研究侧留代码；核心测试不导入研究代码 | [0025](0025-product-package-boundaries.md) |
| 研究与文档布局 | 研究一轮一目录放 `research/`，记录精简，冻结靠 git 与归档 tag；产品不导入 `research/` | [0031](0031-research-layout-and-lightweight-records.md) |
| 资产清单与安装 | `assets.toml` 只列 ffmpeg 与 STT 模型；`just install` 是唯一环境入口；ffmpeg 只锁维护分支 | [0033](0033-ffmpeg-branch-lock.md) |

### 未关闭项

待用户裁定的事项、未验证项与已知限制统一汇总在[待用户裁定事项](../pending-decisions.md)。新发现的不一致或未关闭项写到那一页，不写在本页。

## 演进链

日期是采纳日；带链接的是现存 ADR，纯文本编号已并入括号里的 ADR。

- **STT 基线**：0001（10-04，W0 旧 Pyannote、X0 fixed30）→ 0002（10-05，X0 `cut-merge`）→ 0003（10-05，两路统一新 Pyannote）→ 0007（10-13，进产品，VAD 固定 `cuda:0`）→ 0012（10-19，可选引擎 `cross`）。现行见 [0003](0003-new-pyannote-baselines.md)。
- **ASR 整窗守卫**：0023（11-10 采纳、11-11 实现，复读守卫，`guard-v2`）→ 0030（11-18，加语速与幻听句，`guard-v3`）。现行见 [0030](0030-asr-window-plausibility-guard.md)。
- **翻译模型与流程（H0）**：0004（10-06，Q3_K_M greedy）→ 0005（10-07，APEX-I-Compact，`official30b-cached-v1`）→ 0006（10-11，`b10-joint`）→ 0009／0010（10-17，`dp6-grp` → `dp10-cut`）→ 0015（10-21，命名 H0）→ 0018（11-08，退出基线）→ 0019（11-08，退出产品）。历史身份见 [0021](0021-q3-strata-names-baseline.md)。
- **Q 线基线**：0015（10-21，Q0 `qwen-wide`）→ 0016（11-08，Q1 只注入 high）→ 0017（11-08，Q2 Strata 默认启动）→ 0018（11-08，Q2 唯一基线）→ 0021（11-09，Q3 Strata 建表）。现行见 [0021](0021-q3-strata-names-baseline.md)。
- **产品翻译配方**：0007（10-13，`b10-joint-degrade-v1`）→ 0011（10-18，`dp10-cut-degrade-v1`）→ 0019（11-08，`q2-degrade-v1`，Strata 由产品启停）→ 0022（11-09，与建表共用 session）→ 0029（11-17，`q3-translate-v1`，按条收下）。现行见 [0029](0029-translate-per-cue-resolution.md)。
- **专名与产品建表**：0013（10-19，研究线结题）→ 0014（10-19，进产品 `names` 阶段，27B 建表）→ 0019（11-08，只注入不替换）→ 0022（11-09，切到 Strata，`q3-names-v1`）→ 0026（11-12，放宽输出上限与预算，`q3-names-v2`）→ 0028（11-17，空表合法，`q3-names-v3`）。现行见 [0028](0028-names-accept-empty-table.md)。
- **产品输入、工作目录与发布**：0007（10-13，只扫视频、镜像发布到 `output_dir`）→ 0020（11-08，音频输入、`work_dir`、发布到源文件旁）→ 0024（11-11，内嵌日文字幕跳过 STT）→ 0027（11-17，不再流复制原始音轨）。现行见 [0007](0007-bilingual-subtitle-pipeline-architecture.md)、[0024](0024-embedded-japanese-subtitles.md)。
- **产品包与研究代码的边界**：0007（10-13，产品不导入 `experiments.*`）→ 0014（10-19，共享 `llama_server.py`）→ 0022（11-09，产品不再起 llama-server）→ 0025（11-11，产品不为研究侧留代码，GPU 锁冲突进程级）→ 0031（11-18，删除研究代码，研究改放 `research/`）。现行见 [0025](0025-product-package-boundaries.md)、[0031](0031-research-layout-and-lightweight-records.md)。
- **资产清单**：0032（11-18，去掉 llama.cpp 与 27B，`setup` 并入 `install`）→ 0033（11-18，ffmpeg 只锁维护分支）。现行见 [0033](0033-ffmpeg-branch-lock.md)。
- **方法禁区**：[0008](0008-no-multi-translation-selection.md)（10-16），放弃 v4 `mbr8c` 与 v5 `mbr8s`。

## 全部 ADR

| 编号 | 主题 | 状态 |
| --- | --- | --- |
| [0003](0003-new-pyannote-baselines.md) | STT 基线、设备与产品 STT 引擎 | 有效（并入 0001、0002、0012） |
| [0007](0007-bilingual-subtitle-pipeline-architecture.md) | 产品架构、输入与发布 | 有效（并入 0020、0027） |
| [0008](0008-no-multi-translation-selection.md) | 不自动选用"翻译多次再挑选" | 有效 |
| [0021](0021-q3-strata-names-baseline.md) | 翻译基线 Q3 与历史翻译身份 | 有效（并入 0004、0005、0006、0009、0010、0011、0015、0016、0017、0018） |
| [0024](0024-embedded-japanese-subtitles.md) | 有内嵌日文文本字幕轨的文件跳过 STT | 有效 |
| [0025](0025-product-package-boundaries.md) | 产品包边界与失败级别 | 有效；第 4 点中 `tests/equivalence/` 实时对照层由 0031 替代 |
| [0028](0028-names-accept-empty-table.md) | 产品 names 阶段与专名一致性研究线 | 有效（并入 0013、0014、0022 除第 3–5 点、0026） |
| [0029](0029-translate-per-cue-resolution.md) | 产品翻译（`q3-translate-v1`）与 Strata session | 有效（并入 0019、0022 第 3–5 点） |
| [0030](0030-asr-window-plausibility-guard.md) | ASR 整窗守卫（`guard-v3`） | 有效（并入 0023） |
| [0031](0031-research-layout-and-lightweight-records.md) | 研究按轮次放进 `research/`，记录精简，冻结靠 git | 有效 |
| [0033](0033-ffmpeg-branch-lock.md) | 资产清单与安装，ffmpeg 只锁维护分支 | 有效（并入 0032） |

新 ADR 编号从 0034 起。

## 记录新决定

用户采纳一个决定（换基线、裁定研究结论、改产品行为）后，在**同一次提交**里完成下面几步：

1. **新增 ADR**：`docs/adr/NNNN-<slug>.md`，编号顺延。写清状态、日期，以及替代了哪篇 ADR 的哪个小节；写清身份（配方、hash、入口）、证据，以及未验证的部分。引用其他 ADR 用"ADR-NNNN「小节名」"，不用条目序号。
2. **处理旧 ADR**：默认只在被替代的 ADR 状态行末尾追加"「某小节」自某日起由 ADR-NNNN 替代"，正文不动。只有用户授权合并精简时，才把新决定并入该主题的 ADR 并删除被并掉的文件。
3. **改本页**：在"当前有效决定"里改对应行，在"演进链"的对应链末尾追加一环，在"全部 ADR"里加一行并更新被替代那篇的状态，在页尾"更新记录"加一行；新发现的不一致或未关闭项写进[待用户裁定事项](../pending-decisions.md)，裁定了其中某项时从那一页删行。
4. **改 [CURRENT.md](CURRENT.md)**：把对应小节改成新的关键身份与链接；其中每个 hash 与配方 id 都要能在某篇 ADR 正文里逐字找到。
5. **同步摘要入口**：基线变化时，改 [AGENTS.md](../../AGENTS.md)"现行决定与研究约束"中的基线句（只写基线名）；术语有变化时，改 [GLOSSARY.md](../../GLOSSARY.md)；来自研究轮次的决定，在[研究索引](../../research/INDEX.md#轮次登记)改该轮状态，并在该轮 README 的"结论与去向"注明裁定结果；涉及代码时，按[随交付同步](../agents/documentation.md#随交付同步)更新模块页与 README。

不在本页记录的：研究过程、实验数据、未采纳的候选。这些放在 `research/`。

## 更新记录

"当前有效决定"表的改动日志，新的一行加在最前。

- 2026-11-18（ADR 合并）：按主题合并为 11 篇，删除 22 篇被并掉的 ADR 与跳转页；表改为每主题一行一篇 ADR，CURRENT.md 改为速查页。
- 2026-11-18：ADR-0032 资产清单去掉 llama.cpp 与 27B、`setup` 并入 `install`；ADR-0033 ffmpeg 改锁维护分支。
- 2026-11-18（research-restructure）：ADR-0031 研究与文档布局。
- 2026-11-17／18（batch-run-fixes）：ADR-0027 不再流复制原始音轨；ADR-0028 建表空表合法（`q3-names-v3`）；ADR-0029 产品翻译按条收下（`q3-translate-v1`）；ADR-0030 ASR 整窗守卫加语速与幻听句（`guard-v3`）。
- 2026-11-11／12：ADR-0023 复读守卫实现；ADR-0024 内嵌日文字幕；ADR-0025 产品包边界与失败级别；ADR-0026 建表放宽输出上限与预算。
- 2026-11-09：ADR-0021 唯一基线改为 Q3；ADR-0022 产品建表切到 Strata。
- 2026-11-08：第一次合并精简；ADR-0018 唯一基线 Q2，ADR-0019 产品翻译切到 Q2，ADR-0020 改输入范围、工作目录与发布。
