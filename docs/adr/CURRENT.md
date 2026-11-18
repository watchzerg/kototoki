# 现行决定的完整定义

状态：current（活文档；权威仍是各 ADR 正文，本页与 ADR 冲突时以 ADR 为准并修本页）

本页把分散在多篇 ADR 里、相互部分取代的现行规则合成一份完整定义：翻译基线、产品翻译与建表、STT、专名、ASR 整窗守卫及其他现行产品决定。
只写现状；演变过程见[决定索引·演进链](INDEX.md#演进链)。条款号写作"0017 身份"表示该 ADR 的无编号小节。

## 翻译基线 Q3

唯一翻译基线（[0021](0021-q3-strata-names-baseline.md) 第 1 点）。Q3＝Q2 的翻译规则不变，只换注入表的来源（0021 第 2 点）。

**对照规则**

- 新的翻译测试都以 Q3 为对照；引用 Q2、Q1、Q0、F1、H0 须写明并说明理由（0021 第 1 点；[0018](0018-q2-sole-translation-baseline.md) 第 2 点，改为针对 Q3）。
- 切包与 `dp10-cut` 逐字一致，`check-batches` 可用；数字只在同一裁判 profile、同一数据集、同一 seed 块之间比较；配方变即新配方与新 hash，名称后缀递增须用户裁定（0018 第 4 点）。
- [0008](0008-no-multi-translation-selection.md) 适用；v3、v4、v5 确认集已开封，新的确认须用全新隔离的集合（0018 第 5 点、0021 约束）。

**翻译（Q1 规则＋Q2 两处改动，[0017](0017-q2-strata-default-launch-baseline.md) 身份）**

| 项 | 取值 |
| --- | --- |
| 基础配方 | Q0＝`qwen-wide`，recipe_hash `719237b92c45c4d0f19971ece6b0944157c23ad2e33bbfe0644db60aabfcaef7`（[0015](0015-two-translation-baselines.md) 第 3 点）；切包、邻文、提示、采样都不变 |
| 切包 | 与 `dp10-cut` 完全相同（0015 第 3 点；[0010](0010-dp10-cut-translation-flow-baseline.md) 第 2–3 点） |
| 邻文 | `wide-context-v1`：前 20、后 5 条，只在场景边界截断，不看静默，可见上限 35（0015 第 3 点） |
| 提示 | `qwen-joint-v1`：Hy joint 提示原样拆成 system 与 user 两条消息（0015 第 3 点） |
| 注入 | 表头 `qwen-name-table-v1`，`filter: window`；只取 `confidence: high` 实体，每个 `forms[]` 一行 `{source: form.ja, translation: form.zh}`，按 `ja` 去重，跳过空写法；不做事后替换；不按输入来源区分（0017 身份） |
| 模型 | `qwen3.8-flash-next-iq3_s`；`qwen_options` 加 `strata_launch: "default"`（0017 身份） |
| 采样与请求 | temperature 0.7、top_p 0.8、top_k 20，seed 步长不变；chat completions，不用 grammar，思考关闭；每包两次（seed、seed＋1），两次都失败只空出该包的 cue（0017 身份） |

**建表 `names-strata-v4`**（0021 身份），hash `38cb7bcda96534db70fb5823c05330cd212057058c381e88cadf756f26d308d0`：

- 以产品 `BUILD` 为底不变：提示 `build-table-prompt-v5`、schema `name-table-v2`、no-think；采样 0.7／0.8／20／min_p 0／presence_penalty 1.5；程序兜底；`[names] seed` 20261019；整片 `ja.srt` 一次送入。
- 改动：去掉 llama.cpp 模型资产；`max_tokens` 8192、context 24576、提示预算 15872；`attempts: 5`。
- 请求：模型 `qwen3.8-flash-next-iq3_s`；不发 `response_format`；`chat_template_kwargs.enable_thinking: false`；预算用 `/v1/messages/count_tokens` 把 system、user 分别计数再相加。
- 运行时身份进 hash：Strata 0.2.12、引擎 build 0.1.58、默认启动（`strata.DEFAULT_RESOLVED`）、KV `int8`。
- 失败后请求依次用 seed … seed＋4，取第一张合格的表即停，不挑选（0021 第 3 点）。

**服务与运行**

- Strata 0.2.12、build 0.1.58；默认启动解析为 IQ3_S、上下文 128K、DFlash2、本机 8080（0017 身份）。启动命令 `strata launch --no-tui --model iq3_s`，与默认启动计划逐行相同（[0019](0019-product-translation-q2.md) 第 2 点）。
- 接入检查：版本、8080 上唯一 ready 的本机实例、run config 模型名与 `--max-context 131072`、DFlash2、`/v1/models`、`/v1/status` 原生上下文 131072，不符即拒绝（0017 身份）；DFlash2 从服务日志 `[strata] drafting:` 行判断（0019 第 2 点）。
- 运行顺序：核对无 llama-server、无别的 launch 或 GPU 作业、可用内存 ≥52 GiB → 启动并接入检查、确认专家区全部锁进内存 → 建表 → 翻译 → `strata launch --stop` 并核实显存释放；全程不起 llama-server、不加载 27B（0021 身份）。
- 实例（配方名 `q2-names-s1`）：dev 15 部 `eeba5a711e83547a2969b3132dda7bbe04e46a35b74a810f578100671812fe57`，产品 HF II／III `29fd7a6633dd59843af98e4a15f9d02739201d52a2bf541a2b565b255d763eda`；任意表可用 `v13.write_q2` 组出翻译配方（0021 身份）。
- 已知并接受：dev 剧集 wrong-referent 显著变差、两次建表差别大（0021 第 4 点）。

### 前任 Q2

Q1 规则＋上表模型与启动，表由产品当时的 27B 建表（`BUILD_RECIPE_HASH` `5b8d1b76da757bb26aa3d3fb894c1963935a308b6ef4eb7c75edeaa2d44c9e50`），先用 llama-server 建表、停掉后再启 Strata（0017 身份）。只作前任身份（0021 第 1 点）。

## 产品翻译

配方 `q3-translate-v1`，`RECIPE_HASH` `865bcd1d06f0cc7af83a02f90d0ff2ae5c1fca012695d28e1dbbe4b4f0325964`（[0029](0029-translate-per-cue-resolution.md) 第 5 点；此前 `q2-degrade-v1`，[0019](0019-product-translation-q2.md) 第 5 点）。

- 规则即 Q2：切包 `dp10-cut`（`gap-pack-v2`，参数同 0010 第 2–3 点）、`wide-context-v1`、`qwen-joint-v1`、`qwen-name-table-v1`（`window`）、模型与采样同上；正常包请求体与研究侧逐字节相同（0019 第 1 点）。
- 回复判定：截断、超出 context、非 JSON、不是恰好一个 `translations` 对象为结构失败，换 seed（超出 context 不换）；结构合法即按条判，非空且不含空行的收下，缺失、空串、含空行的未解决，多出 ID 与顺序不看；一条都没收下也算失败（0029 第 1、2 点）。
- 追问：每个节点（初始即批次）最多两次；收下至少 1 条后，未解决的 cue 按最大连续段再问；两次都失败的节点对半拆，单条仍失败该 cue 不出中文，合并时只输出日文一行，计入未翻译报告（0029 第 3、4 点）。
- 基础设施失败：停掉 Strata 重启，同调用内最多重启 2 次；`StrataRefused` 不重试（0019 第 4 点、[0022](0022-product-names-on-strata.md) 第 5 点）。
- Strata：启动前 `--status` 为空、空闲显存 ≥14000 MiB、可用内存 ≥52 GiB（等满 180 s 仍不够只记 WARNING）；接入检查同上；专家区须为 `ram`（日志有 `expert arena: locked` 且无 mmap 记录），否则拒绝；整批结束、出错或中断时 `--stop` 并核实（0019 第 2 点）。session 与建表共用（0022 第 3 点）。
- 身份 `{ja_srt_sha256, recipe_hash, seed, names_sha256}`；run 目录 `translate/srt-<sha12>/q3-translate-v1__s<seed>__n<names_sha12>/`；改到注入行即重译（0019 第 3 点、0029 第 5 点）。
- 配置：`[translate]` 只有 `seed`（正整数），端口固定 8080（0019 第 6 点）。

## 产品建表

配方 `q3-names-v3`（`kototoki/names/recipes.py` 的 `BUILD`，hash `d57ed0c6715f63fcb32bb034db03decf02650215af62c13ba95ae7bcdbcf33d7`，由 `tests/core/test_names_recipes.py` 钉住）（[0028](0028-names-accept-empty-table.md) 第 3 点；此前 `q3-names-v2`，[0026](0026-names-output-and-prompt-budget.md) 第 3 点；`q3-names-v1`，[0022](0022-product-names-on-strata.md) 第 2 点）。

- 请求体与 seed 序列与 `names-strata-v4` 一致（提示 v5、schema、采样、无 `response_format`、`enable_thinking: false`、`count_tokens` 预检），只有 `max_tokens` 为 16384（v4 为 8192）；最多 5 个请求，取第一张合格的表（0022 第 1 点；0026 第 1 点）。只有回复格式不合格（截断、非 JSON、顶层不是对象、`entries` 不是列表）才换 seed；`entries` 为空或条目全被归一丢弃都接受为空表，`build.status = ok`（0028 第 1、2 点）。
- 提示预算 32256（context 按 49152 计，只用于算预算；v4 为 24576／15872）（0026 第 2 点）。
- 与 `names-strata-v4` 的差别：上述三项、建表块的 `retry_on: "malformed"`（v4 把空表当不合格重试）、不含研究侧说明字段与 `model_asset`；三项换回 v4 的值、去掉 `retry_on` 后 hash 等于 `38cb7bcd…`（0022 第 2 点；0026 第 3 点；0028 第 3 点）。
- `count_tokens` 不可用时该片不再预检、计数按 0、只记 WARNING；5 次回复格式都不合格写 `build.status = failed` 的空表，照常翻译、不注入（0022 第 1 点；0028 第 2 点）。
- 表身份 `{ja_srt_sha256, recipe_hash, seed}`（0022 第 2 点）。
- 与翻译共用一个 Strata session，整批只启动一次，任何阶段不起 llama-server、不加载 27B；生命周期在 `kototoki/strata.py`（0022 第 3、4 点）。
- 失败：传输／HTTP／OOM 停 Strata、该片 `names` 文件级失败；启动失败整批累计 3 次即 `unavailable`；`StrataRefused` 使两个阶段其余影片都失败（0022 第 5 点）。

## STT 基线与产品 STT

- **W0**：faster-whisper＋新 Pyannote VAD＋MMS 日语 CTC；须由自有适配层承接 WhisperX 的切分合并、独立无时间戳解码与特征处理（[0003](0003-new-pyannote-baselines.md) 第 1 点）。
- **X0**：Qwen-ASR＋同一 VAD＋同一 MMS，保留 Qwen 原生 processor 与解码（0003 第 2 点）。
- 新 Pyannote＝`pyannote.audio 4.0.7`＋`pyannote/segmentation-3.0`，revision `e66f3d3b9eb0873085418a7b813d3b369bf160bb`（0003 第 3 点）；窗口 ≤30 秒、MMS `jpn` adapter（0003 第 4 点）。
- 旧 PyanNet W0、fixed30、`cut-merge` 只作历史身份；demo CLI 省略参数落到旧默认，须显式选新 Pyannote（0003 第 7 点、约束）。

### 设备

ASR 与强制对齐只跑 GPU，不回退 CPU；VAD 可用 CPU 或 GPU（0003 第 5 点），产品固定 `cuda:0`（[0007](0007-bilingual-subtitle-pipeline-architecture.md) 第 5 点）。

### 产品 STT 引擎

`[stt] engine` = `w0`（默认）｜`x0`｜`cross`；改默认须新 ADR 并在全新隔离材料上确认（[0012](0012-cross-asr-judge.md) 第 1 点）。`cross` 配方 `cross-w0-x0-whisper-judge-v1`：Whisper 教师强制打分，d > −1.0 取 x0（0012 第 2 点）；守卫、共驻与审计产物见 0012 第 3–5 点。

## ASR 整窗守卫

[0023](0023-asr-repeat-guard.md)、[0030](0030-asr-window-plausibility-guard.md)，只在产品 w0 路径（含 `cross` 的 w0 一路）。每个未失败的窗口依次过三条规则，都在规范化文本（NFKC、去标点与空白）上判定；后两条看复读处理后（可能已折叠）的文字，第一个置空的规则生效（0030 第 1 点）。

- 复读 `repeat-strict`：周期 ≥2 的相邻重复 ≥10 份，或 ≥3 字子串不重叠出现 ≥10 次，且覆盖 ≥50%（0023 第 1 点）；折叠只保留第一个单元，仍命中则置空（0023 第 2 点）。
- 语速 `speech-rate`：规范化字数 ÷ 窗口时长 > 20 字/秒即置空（0030 第 2 点）。
- 已知幻听句 `hallucination-phrase`：整窗规范化文字等于 `ご視聴ありがとうございました`、`チャンネル登録よろしくお願いします`、`byH` 之一即置空（0030 第 3 点）。
- 置空按 `failed_windows` 记，原因 `guard:<规则名>`；只做后处理，不重解码（0023 第 3 点）。不用 `no_speech_prob`／`avg_logprob` 规则（0030 第 6 点）。
- 产品 W0 配方 `w0-faster-whisper-large-v3-guard-v3`，W0 `6a47318c7732534270f64d14bb5da9830a79fdcae9f6d84e01a309532d62403b`、CROSS `bd5bc55527a539beab598e98f687f1bcbbcc6c23b3ba3a823fd3e9dfb46338e3`（0030 状态行）。W0 基线身份不变（0023 状态行）。

## 专名

- 研究线关闭，不开新轮次、agent 不自行重启，重开只由用户明确要求（[0014](0014-name-consistency-in-product.md) 第 1 点）；研究代码已随 [0031](0031-research-layout-and-lightweight-records.md) 删除，产品不导入研究（0014 第 9 点）。
- 产品 `names` 阶段位于 `ja-cues` 与 `translate` 之间，整片 `ja.srt` 一次送入，产物 `name-table.json`（0014 第 3 点）；建表方式见[产品建表](#产品建表)。
- 建表必开；表只经翻译注入（high 条目），没有发布时替换；手改表改到注入行即重译（0019 第 3 点）。
- 条目只在工作目录，不进日志，日志只记计数（0014 第 8 点）。
- 两次由用户明确要求的重开都已结束：v13 产出 Q3 的 Strata 建表配方；v15 的日文转写侧表内写法替换，用户 2026-11-11 裁定不进产品（[决定索引](INDEX.md#当前有效决定)"专名一致性"行）。

## 其他现行产品决定

### 产品架构

阶段 × 整批推进，每阶段一个子进程，阶段链 `vad` → `asr` → `align`（MMS）→ `cues` → `names` → `translate` → publish（[决定索引](INDEX.md#演进链)；names 见 0014 第 3 点）；单一 CUDA 12.8、Python 3.13 环境；翻译单元是日文 cue；`kototoki.toml` 驱动、无 CLI；产物带输入身份与配方 hash 续跑（0007 第 1、2、6、7 点）。

### 输入、工作目录与发布

音频也是输入；`[paths] work_dir`（默认 `.local/work/`）按目标目录分子目录；只发布 `<主名>.ja-zh.srt` 到源文件旁，已存在即跳过（[0020](0020-media-inputs-work-dir-and-side-by-side-publish.md) 第 1–4 点）；视频输入也不流复制原始音轨，extract 只派生 `audio-16k.wav`（[0027](0027-no-original-audio-copy.md) 第 1–2 点）。

### 内嵌日文字幕

`[input] use_embedded_subtitles`（默认 `true`）且有可用日文文本字幕轨时不做 STT，从 `names` 起走原链；forced 认 disposition 或标题里的 "forced"；配方 `embedded-ja-subtitle-v2`（[0024](0024-embedded-japanese-subtitles.md) 第 1–5 点及其状态行 2026-11-12 补漏）。

### 产品包边界与失败级别

GPU 锁冲突一律退出码 4、不写逐文件 `failure.json`；产品不为研究侧留代码；`tests/core` 不导入研究代码，等价取值在 core 钉字面量（[0025](0025-product-package-boundaries.md) 第 1–4 点）。不再有实时对照层（[0031](0031-research-layout-and-lightweight-records.md) 第 2、8 点）。

### 研究与文档布局

研究一轮一目录 `research/<YYYY-MM>-<slug>/`，在 [research/INDEX.md](../../research/INDEX.md) 登记；README 按 `research/TEMPLATE.md` 填必填项，不写哈希（git commit 除外）、本机绝对路径、逐条明细与执行台账；冻结靠 git 与归档 tag `archive/2026-11-18-pre-research-restructure`，代码不对文档做 sha256 自检；产品不导入 `research/`，研究可以导入产品；`.scratch/<slug>/` 只放进行中的产品侧计划，完工后删除（[0031](0031-research-layout-and-lightweight-records.md) 第 1–10 点）。

### 资产清单与安装

`assets.toml` 只列产品用到的二进制（ffmpeg）与 STT 模型；llama.cpp 工具与 Qwen3.8-27B 条目已删除，`scripts/upgrade.py` 只升 `python` 与 `ffmpeg`；`just install` 先 `uv sync --locked` 再安装清单里的工具，没有单独的 `setup`（[0032](0032-drop-llama-cpp-assets.md) 第 1–3 点）。研究需要清单外的二进制或模型时由该轮自行记录与准备（第 4 点）。

### 方法禁区

不自动选用"翻译多次再挑选"；可靠性重试与按条追问、对半拆分不算在内；边界情况先问（[0008](0008-no-multi-translation-selection.md) 第 1–2 点、范围；0029 依据）。

## 部分被取代的 ADR 仍有效的条款

| ADR | 仍有效 | 已被取代 |
| --- | --- | --- |
| [0010](0010-dp10-cut-translation-flow-baseline.md) | 第 2–3 点（切包，Q2／Q3 与产品沿用）；第 1、4、5、8 点作 H0 与对照身份（`dp10-cut` `ee72ce6683c89e5a1f83fd7ba99f54f3683966deed0e526c193780ad8c500b70`） | 第 6、7 点（产品配方 `dp10-cut-degrade-v1` 与 run 目录）→ 0019 |
| [0014](0014-name-consistency-in-product.md) | 第 1、2（建表配置）、8、9 点；第 3 点的阶段位置；第 4 点的空表规则 | 第 3 点发布时替换、第 5、6、7 点 → 0019；第 3 点建表模型、llama-server 与串行驻留 → 0022；第 10 点对基线的建表 → 0021 |
| [0015](0015-two-translation-baselines.md) | 第 2 点（H0 身份）、第 3 点（Q0 身份）、第 4 点其余测试规则、第 6、7 点 | 第 1 点、第 4 点"写明 H0 还是 Q2"、第 5 点基线含义 → 0018 |
| [0017](0017-q2-strata-default-launch-baseline.md) | 第 3 点；身份节的 Q1 规则、Q2 两处改动、服务、请求、接入检查、配方身份（均为 Q3 组成部分） | 第 1 点 → 0021；第 2 点对照对象经 0018 第 2 点扩展、再由 0021 改为 Q3 |
| [0018](0018-q2-sole-translation-baseline.md) | 第 2、4 点（改为针对 Q3）、第 3 点"H0 不再是基线"、第 5 点 | 第 1 点 → 0021；第 3 点"产品当前的翻译实现" → 0019 |
| [0019](0019-product-translation-q2.md) | 第 1–3、6 点；第 4 点的基础设施失败与 `StrataRefused` | 第 2 点 llama-server 建表与不同时驻留 → 0022；第 4 点 10→5→1 降级、单条保留日文与空行判失败，第 5 点配方名、hash 与 run 目录名 → 0029 |
| [0022](0022-product-names-on-strata.md) | 第 1 点其余（提示、采样、请求形状、预检、seed 序列与 5 次尝试）、第 3–5 点 | 第 1 点 `max_tokens` 8192、context 24576／预算 15872，第 2 点配方名 `q3-names-v1` → 0026；第 6 点与第 1 点"由 `tests/core/` 导入 v13 对照" → 0025；第 1 点把空表算作失败 → 0028；第 6 点保留 llama.cpp 与 27B 清单条目 → 0032 |
| [0023](0023-asr-repeat-guard.md) | 第 1–3 点；第 4 点的 `guard` 块与 hash 级联 | 第 4 点配方 id 与 hash、第 5 点"不管低压缩比的插入套话" → 0030 |
| [0025](0025-product-package-boundaries.md) | 第 1–3 点；第 4 点中 `tests/core` 不导入研究代码与钉字面量 | 第 4 点 `tests/equivalence/` 实时对照层与 `just test-equivalence` → 0031 |
| [0026](0026-names-output-and-prompt-budget.md) | 第 1、2、4 点 | 第 3 点配方名 `q3-names-v2` 与 hash → 0028 |
