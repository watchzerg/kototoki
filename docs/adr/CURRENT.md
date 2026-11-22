# 现行决定的完整定义

状态：current（活文档；权威是各 ADR 正文，本页与 ADR 冲突时以 ADR 为准并修本页）

2026-11-18 起每个主题只有一篇 ADR，正文就是该主题完整的现行决定。本页是速查：每节给出关键身份（配方 id、hash、模型与启动方式）和权威小节的链接，细则读 ADR。演变过程见[决定索引·演进链](INDEX.md#演进链)。

## 翻译基线 Q3

唯一翻译基线（[0021「唯一基线 Q3」](0021-q3-strata-names-baseline.md#唯一基线-q3)）。新的翻译测试以 Q3 为对照；引用 Q2、Q1、Q0、F1、H0 须写明并说明理由；名称后缀递增须用户裁定（[0021「对照规则」](0021-q3-strata-names-baseline.md#对照规则)）。

- 翻译规则＝Q1 规则（Q0 `qwen-wide`＋只注入 high 条目）＋Q2 两处改动（模型 `qwen3.8-flash-next-iq3_s`、`strata_launch: "default"`），是组配方的规则而非固定 hash（[0021「Q3 翻译规则」](0021-q3-strata-names-baseline.md#q3-翻译规则)）。Q0 recipe_hash `719237b92c45c4d0f19971ece6b0944157c23ad2e33bbfe0644db60aabfcaef7`。
- 切包 `dp10-cut`（`gap-pack-v2`），Q3 与产品共用（[0021「dp10-cut 切包」](0021-q3-strata-names-baseline.md#dp10-cut-切包)）；H0 流程配方 `dp10-cut` `ee72ce6683c89e5a1f83fd7ba99f54f3683966deed0e526c193780ad8c500b70`。
- 建表 `names-strata-v4`，hash `38cb7bcda96534db70fb5823c05330cd212057058c381e88cadf756f26d308d0`；失败后最多 5 次请求，取第一张合格的表（[0021「Q3 建表」](0021-q3-strata-names-baseline.md#q3-建表)、[「Q3 身份」](0021-q3-strata-names-baseline.md#q3-身份)）。
- 服务：Strata 0.2 版本线（实际版本只记录、不进配方身份；Windows 时期证据来自 0.2.12／build 0.1.58），默认启动（IQ3_S、128K、DFlash2、本机 8080），`strata launch --no-tui --model iq3_s`（[0021「Q3 服务与运行顺序」](0021-q3-strata-names-baseline.md#q3-服务与运行顺序)、[0034「Strata 版本」](0034-ubuntu-only-platform.md#strata-版本)）。
- 实例（配方名 `q2-names-s1`）：dev 15 部 `eeba5a711e83547a2969b3132dda7bbe04e46a35b74a810f578100671812fe57`，产品 HF II／III `29fd7a6633dd59843af98e4a15f9d02739201d52a2bf541a2b565b255d763eda`。
- 已知并接受：dev 剧集 wrong-referent 显著变差、两次建表差别大。

### 前任 Q2

Q1 规则＋上述模型与启动，表由当时产品的 27B 建（`BUILD_RECIPE_HASH` `5b8d1b76da757bb26aa3d3fb894c1963935a308b6ef4eb7c75edeaa2d44c9e50`）；只作前任身份（[0021「Q2（前任）」](0021-q3-strata-names-baseline.md#q2前任)）。更早的 Q1、F1、Q0、H0 与旧流程配方见 0021「身份」。

## 产品翻译

配方 `q3-translate-v1`，`RECIPE_HASH` `1372b37146babf6817ffeacf4d0019af5eec319dc19cf7d62a1d5f1f7fde577d`（[0029](0029-translate-per-cue-resolution.md)；runtime 去掉 Strata 版本后的值，[0034「身份」](0034-ubuntu-only-platform.md#身份)）。

- 请求规则即 Q3 翻译规则，正常包请求体与研究侧逐字节相同（[0029「请求规则」](0029-translate-per-cue-resolution.md#请求规则)）；只注入、不替换，建表必开（[「专名注入」](0029-translate-per-cue-resolution.md#专名注入)）。
- 结构失败才换 seed，结构合法即按条收下；只追问未解决的 cue，单条仍失败该 cue 不出中文、只输出日文一行（[「按条收下」](0029-translate-per-cue-resolution.md#按条收下)、[「只追问没解决的 cue」](0029-translate-per-cue-resolution.md#只追问没解决的-cue)、[「不出中文的 cue」](0029-translate-per-cue-resolution.md#不出中文的-cue)）。
- Strata 由产品启停，names 与 translate 共用一个 session；启动前检查、接入检查、专家区须为 `ram`、失败计数见 [「Strata session」](0029-translate-per-cue-resolution.md#strata-session)；基础设施失败重启、`StrataRefused` 不重试见[「基础设施失败」](0029-translate-per-cue-resolution.md#基础设施失败)。
- 身份 `{ja_srt_sha256, recipe_hash, seed, names_sha256}`，run 目录 `translate/srt-<sha12>/q3-translate-v1__s<seed>__n<names_sha12>/`；`[translate]` 只有 `seed`（[「配置与产物」](0029-translate-per-cue-resolution.md#配置与产物)）。

## 产品建表

配方 `q3-names-v3`（`kototoki/names/recipes.py` 的 `BUILD`），hash `bcb9bebc5274d88a5f3737559b4ab77afa7278afc6d6196c77aad07b12acd072`（runtime 去掉 Strata 版本后的值，[0034「身份」](0034-ubuntu-only-platform.md#身份)），由 `tests/core/test_names_recipes.py` 钉住（[0028「建表配方」](0028-names-accept-empty-table.md#建表配方)）。

- 请求体与 seed 序列同 `names-strata-v4`，只有 `max_tokens` 16384、提示预算 32256（context 按 49152 计）与 `retry_on: "malformed"` 不同（[「输出上限与提示预算」](0028-names-accept-empty-table.md#输出上限与提示预算)）。
- 只有回复格式不合格才换 seed，最多 5 次；空表是合法结果；终态失败写空表、照常翻译不注入（[「重试与空表」](0028-names-accept-empty-table.md#重试与空表)）。
- 传输／HTTP／OOM 停 Strata、该片 `names` 文件级失败（[「建表失败」](0028-names-accept-empty-table.md#建表失败)）；session 规则见 0029「Strata session」。

## STT 基线与产品 STT

- **W0**：faster-whisper＋新 Pyannote VAD＋MMS 日语 CTC，须由自有适配层承接 WhisperX 的关键行为；**X0**：Qwen-ASR＋同一 VAD＋同一 MMS（[0003「W0／X0 基线」](0003-new-pyannote-baselines.md#w0x0-基线)）。
- 新 Pyannote＝`pyannote.audio 4.0.7`＋`pyannote/segmentation-3.0`，revision `e66f3d3b9eb0873085418a7b813d3b369bf160bb`；旧 PyanNet W0、fixed30、`cut-merge` 只作历史身份。

### 设备

ASR 与强制对齐只跑 GPU，不回退 CPU；VAD 可用 CPU 或 GPU，产品固定 `cuda:0`（[0003「设备」](0003-new-pyannote-baselines.md#设备)）。

### 产品 STT 引擎

`[stt] engine` = `cross`（默认，[0035「默认引擎」](0035-cross-default-native-whisper-features.md#默认引擎)）｜`w0`｜`x0`。`cross` 配方 `cross-w0-x0-whisper-judge-v1`：Whisper 教师强制打分，d > −1.0 取 x0（[0003「产品 STT 引擎」](0003-new-pyannote-baselines.md#产品-stt-引擎)）。产品 w0 的特征用 faster-whisper 自带的 `FeatureExtractor`，不再用 `mel_filters.npz`（[0035「W0 特征」](0035-cross-default-native-whisper-features.md#w0-特征)）。

## ASR 整窗守卫

只在产品 w0 路径（含 `cross` 的 w0 一路），依次过复读 `repeat-strict`（折叠，仍命中则置空）、语速 > 20 字/秒置空、整窗是已知幻听句置空三条规则；只做后处理，W0 基线身份不变（[0030](0030-asr-window-plausibility-guard.md)）。产品 W0 配方 `w0-faster-whisper-large-v3-fwmel-guard-v3`，W0 `9f2c8ea8dc8f6334b45f6f257e466363acc947d75ad94531aa13bc531c5d09b4`、CROSS `4041dd2496f73aa3e46f17afc2a769c161a94e7d7894a3bc0f48f2d9decb2cf2`（[0035「身份」](0035-cross-default-native-whisper-features.md#身份)）。

## 专名

研究线关闭，重开只由用户明确要求（v13、v15 两次重开均已结束）；产品 `names` 阶段位于 `ja-cues` 与 `translate` 之间，表只经翻译注入、不替换，条目不进日志（[0028「研究线关闭」](0028-names-accept-empty-table.md#研究线关闭)、[「阶段位置」](0028-names-accept-empty-table.md#阶段位置)、[「表的使用与校对」](0028-names-accept-empty-table.md#表的使用与校对)）。

## 其他现行产品决定

### 产品架构

阶段 × 整批推进，每阶段一个子进程，阶段链 `vad` → `asr` → `align`（MMS）→ `cues` → `names` → `translate` → publish；统一 CUDA 12.8、Python 3.14 环境；翻译单元是日文 cue；`kototoki.toml` 驱动、无 CLI；产物带输入身份与配方 hash 续跑（[0007](0007-bilingual-subtitle-pipeline-architecture.md)，Python 版本见 [0036](0036-python-3-14.md)）。

### 输入、工作目录与发布

音频也是输入；`[paths] work_dir`（默认 `.local/work/`）按目标目录分子目录；只发布 `<主名>.ja-zh.srt` 到源文件旁，已存在即跳过；extract 只派生 `audio-16k.wav`，不流复制原始音轨（[0007「输入范围」](0007-bilingual-subtitle-pipeline-architecture.md#输入范围)、[「工作目录」](0007-bilingual-subtitle-pipeline-architecture.md#工作目录)、[「发布」](0007-bilingual-subtitle-pipeline-architecture.md#发布)）。

### 内嵌日文字幕

`[input] use_embedded_subtitles`（默认 `true`）且有可用日文文本字幕轨时不做 STT，从 `names` 起走原链；forced 认 disposition 或标题里的 "forced"；配方 `embedded-ja-subtitle-v2`（[0024](0024-embedded-japanese-subtitles.md)）。

### 产品包边界与失败级别

GPU 锁冲突一律退出码 4、不写逐文件 `failure.json`；产品不为研究侧留代码；`tests/core` 不导入研究代码，等价取值在 core 钉字面量（[0025](0025-product-package-boundaries.md)）；不再有实时对照层（[0031](0031-research-layout-and-lightweight-records.md)）。

### 研究与文档布局

研究一轮一目录 `research/<YYYY-MM>-<slug>/`，在 [research/INDEX.md](../../research/INDEX.md) 登记；README 按 `research/TEMPLATE.md` 填必填项，不写哈希（git commit 除外）、本机绝对路径、逐条明细与执行台账；冻结靠 git 与归档 tag `archive/2026-11-18-pre-research-restructure`；产品不导入 `research/`，研究可以导入产品；（[0031](0031-research-layout-and-lightweight-records.md)）。产品侧计划与票据放 Beads（`bd`），完工后关闭（[0037](0037-beads-issue-tracker.md)）。

### 平台、工具链与外部前置

代码已按此实现，Linux 上的真实模型验收（fetch-models、smoke、小批量）待做。

- 平台：只面向 Ubuntu，不比对 Windows 时期结果，旧数据不迁移（[0034「平台」](0034-ubuntu-only-platform.md#平台)）。
- 工具链：mise 钉 uv 与 just；uv 按 `.python-version`（`3.14`）管解释器、按 `uv.lock` 管依赖，默认布局（[0034「工具链分层」](0034-ubuntu-only-platform.md#工具链分层)、[0036](0036-python-3-14.md)）。
- 外部前置：NVIDIA 驱动、apt 系统 ffmpeg（默认从 PATH 查找，实际版本记入运行日志首行）、Strata 0.2；`assets.toml` 只列 STT 模型，`just install` 只做 `uv sync --locked`（[0034「外部前置」](0034-ubuntu-only-platform.md#外部前置)、[「ffmpeg」](0034-ubuntu-only-platform.md#ffmpeg)）。
- 子进程：`PR_SET_PDEATHSIG`＋独立进程组；长任务用 `systemd-run --user`（[0034「子进程与长任务」](0034-ubuntu-only-platform.md#子进程与长任务)）。

### 方法禁区

不自动选用"翻译多次再挑选"；可靠性重试与按条追问、对半拆分不算在内；边界情况先问（[0008](0008-no-multi-translation-selection.md)）。
