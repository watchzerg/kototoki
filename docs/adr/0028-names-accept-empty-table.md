# ADR-0028：产品 names 阶段与专名一致性研究线

状态：已接受。2026-11-18 按主题合并（用户授权）：并入 ADR-0013、ADR-0014、ADR-0022（第 3–5 点的 Strata session 与生命周期并入 [ADR-0029](0029-translate-per-cue-resolution.md)）、ADR-0026，原文见 git 历史（提交 807de3e 及之前）。  
范围：专名一致性研究线的状态，以及产品包 `kototoki/names/` 的 `names` 阶段：阶段位置、建表配方 `q3-names-v3`、重试与空表、失败、表的使用与隐私。Strata session 的持有与启停见 ADR-0029「Strata session」；基线 Q3 的建表 `names-strata-v4` 见 [ADR-0021](0021-q3-strata-names-baseline.md)。

## 决定

### 研究线关闭

1. 专名一致性研究线已结题：不开新轮次，不提议"再调一轮规则"类改动，agent 不得自行重启；重开只由用户明确要求。
2. 两次由用户明确要求的重开都已结束：v13 产出 Q3 的 Strata 建表配方（ADR-0021）；v15 在日文转写侧做"只按专名表写法替换"，用户 2026-11-11 裁定不进产品。
3. 研究代码已随 [ADR-0031](0031-research-layout-and-lightweight-records.md) 删除（归档 tag `archive/2026-11-18-pre-research-restructure`）；产品不导入研究代码。

### 阶段位置

1. `names` 阶段位于 `ja-cues` 与 `translate` 之间，每部影片把整份 `ja.srt`（剥时间轴）一次送入，产物 `name-table.json`（schema `name-table-v2`）。建表必开，没有开关。
2. 模型是 Strata 上的 `qwen3.8-flash-next-iq3_s`，与翻译共用一个 Strata session（见 ADR-0029「Strata session」）；任何阶段不起 llama-server、不加载 27B。配置键 `[names] model`、`[names] port`、`[paths] llama_server` 已删除，写了即按未知键报错。

### 建表配方

1. 配方 `q3-names-v3`（`kototoki/names/recipes.py` 的 `BUILD`，`BUILD_RECIPE_HASH` 由 `tests/core/test_names_recipes.py` 钉住）。表身份 `{ja_srt_sha256, recipe_hash, seed}`；配方一变旧表全部失效重建，不迁移旧产物。
2. 请求体与 seed 序列以基线 `names-strata-v4` 为准，只有 `max_tokens` 不同：提示 `build-table-prompt-v5`、no-think、采样 0.7／0.8／20／min_p 0／`presence_penalty` 1.5、程序兜底（zh 形状过滤、称呼词黑名单、evidence<3 的 person 降为 medium、日文写法形状过滤）、`[names] seed` 20261019；请求不带 `response_format`，带 `chat_template_kwargs.enable_thinking: false` 与 `model`，非流式。
3. 尝试：请求依次用 seed、seed＋1、…、seed＋4，最多 5 个，取第一张合格的表即停，不在多张表里挑选（[ADR-0008](0008-no-multi-translation-selection.md)）。
4. 与 `names-strata-v4` 的差别只有四项：`max_tokens`、context、提示预算三个值（见[输出上限与提示预算](#输出上限与提示预算)）与建表块的 `retry_on: "malformed"`；另不含研究侧说明字段与 `model_asset`。三项换回 v4 的值、去掉 `retry_on` 后拼回 v4 的形状，hash 等于 `38cb7bcd…`（测试钉住）。

### 输出上限与提示预算

1. `max_tokens` 16384。
2. 提示预算 32256 = context 49152 − `max_tokens` − 512；`CONTEXT_SIZE` 49152 只用于算预算、不随请求发出（Strata 实际上下文 131072）。
3. 预算检查走 `/v1/messages/count_tokens`：system 与 user 两段各作一条 user 消息计数再相加；超预算（`too_long`）不发请求、写空表。该端点不可用时该片不再预检、计数按 0，只记录 `usage.prompt_tokens`，超预算只标记不失败，日志一行 WARNING。

### 重试与空表

1. 只有回复格式不合格才换 seed：截断（`finish_reason == length`）、不是 JSON、顶层不是对象、`entries` 不是列表。
2. 空表是合法结果：`entries` 为空列表或条目在归一中全被丢弃，都接受为空表，`build.status = ok`，`dropped_*` 照常记录，日志是普通的 done 行。
3. 终态失败写空表、影片照常翻译、不注入：5 次回复格式都不合格为 `build.status = failed`，超预算为 `too_long`。

### 建表失败

建表请求遇到传输失败、HTTP 错误、OOM：停掉 Strata，该影片 `names` 阶段文件级失败（`failure.json`）。启动失败的累计上限、`StrataRefused` 使两个阶段都失败等 session 规则见 ADR-0029「Strata session」。

### 表的使用与校对

1. 表只经翻译注入使用（只取 `confidence: high` 的写法，见 ADR-0029「专名注入」），没有发布时替换。
2. 表在工作目录里，可人工校对；改到注入行即翻译身份变，删掉该片 `*.ja-zh.srt` 再运行即重译。重建（改 `ja.srt`、改 `[names] seed`、配方变）覆盖手改，不做保护。
3. 不跨文件（多集）共享表。

### 专名隐私

专名表条目是转写内容，只在工作目录，不进日志，日志只记计数。

## 身份

| 身份 | 值 | 状态 |
| --- | --- | --- |
| `q3-names-v3` | `bcb9bebc5274d88a5f3737559b4ab77afa7278afc6d6196c77aad07b12acd072` | 现行（2026-11-20 起 runtime 去掉 Strata 版本，[ADR-0034](0034-ubuntu-only-platform.md#身份)） |
| `q3-names-v3`（Windows 时期） | `d57ed0c6715f63fcb32bb034db03decf02650215af62c13ba95ae7bcdbcf33d7` | 历史（2026-11-17 – 11-20） |
| `q3-names-v2` | `2dbd324e5ee847d0a0171840d4a064cd6b45a3df4c2123b7075cfe1a38b379ba` | 历史（2026-11-12 – 11-17） |
| `q3-names-v1` | `d3317926ee3b3096277faa9a5fbc0879d562336fb1fe89bf0ebd04c5b0be6b17` | 历史（2026-11-09 – 11-12；v15 C 臂用过） |
| 27B＋llama-server 建表 `BUILD_RECIPE_HASH` | `5b8d1b76da757bb26aa3d3fb894c1963935a308b6ef4eb7c75edeaa2d44c9e50` | 历史（切到 Strata 之前的产品建表；Q2 的表由它建，见 ADR-0021） |
| 基线 `names-strata-v4` | `38cb7bcda96534db70fb5823c05330cd212057058c381e88cadf756f26d308d0` | 基线 Q3 的建表，定义在 ADR-0021 |

## 依据

- 研究线结题（[name-consistency](../research/2026-10-name-consistency.md)）：六轮把规则层改动都试过，剩余误差在规则层之外（次要角色的表内错名、一次性音译覆盖不到）；冻结配置在 HF II／III 上 good 89%、有害 2.5%。没有 MQM 与整片人工评估，用户知悉后接受。
- 切到 Strata（2026-11-09）：基线 Q3 的表由 Strata 建、产品仍由 27B 建，两者不一致；切换后产品只剩 Strata 一种推理服务，也去掉了"停 llama-server → 启 Strata"的交接（11-08 专家区退到 mmap 的起因之一）。v13 已在一个 session 里先建表再翻译，内存峰值 60.4–62.4 GiB（[strata-v12-v13](../research/2026-11-strata-v12-v13.md)）。
- 放宽上限与预算（2026-11-12，[产品全流程验收](../research/acceptance/product-fullflow-acceptance-2026-11-12.md)）：两部 HF 提示占旧预算 83%、92%，约 1340 条 cue 以上会 `too_long`；HF III 在 8192 处截断两次。验证：Black Panther（1655 条）提示 20059 token，新预算下建成；HF III 第 4 次 11047 token 成功。收益有限、失败成本翻倍，用户看过结果后保留 16384。
- 空表合法（2026-11-17）：结构合法的回复就是有效回答，对它换 seed 等于抽到非空为止、按内容挑结果，与 ADR-0008 冲突；"非空"要求只是从动画素材的研究脚本原样移植。首次大批量运行（[跑次记录](../research/runs/2026-11-12-first-full-batch.md)）不合格尝试 59 次中空列表 45 次，6 个文件 5 次全失败。

## 未验证与已知限制

- Q3 建表的已知风险（dev 剧集 wrong-referent 显著变差、两次建表写法差别大）见 ADR-0021，用户已知并接受。
- 写满输出上限的回复可能是生成失控而非表长：一次失败尝试约 105 s，最坏 5 次约 9 分钟；`maxItems: 80` 既不约束解码也不在解析时校验。
- 未验证：表质量与注入后的翻译质量、超过 2 万 token 提示的建表质量；`q3-names-v3` 未在 GPU 上重跑，5 次全空的 6 个文件是否确实没有专名未人工核对。
- 接受空表的已知影响：首次大批量运行中另有 9 个文件换 seed 后得到 1–7 条，按本规则得空表；其中 1 个含 1 条 high，注入行少一行。用户已知并接受。
- `count_tokens` 退路、5 次都失败、`StrataRefused` 等失败路径只经伪服务测试。

## 沿革

- 2026-10-19 ADR-0013：研究线结题，冻结配置，不进产品。
- 2026-10-19 ADR-0014：进产品 `names` 阶段（27B＋llama-server 建表，发布时替换，`[names] enabled`）。
- 2026-11-08 ADR-0019：删除发布时替换与开关，表只经注入使用，建表必开（现见 ADR-0029）。
- 2026-11-09 ADR-0021：基线 Q3 的表改由 Strata 建（`names-strata-v4`）。
- 2026-11-09 ADR-0022：产品建表切到 Strata Flash-Next（`q3-names-v1`，最多 5 次），与翻译共用 session。
- 2026-11-10／11 v15 重开：日文转写侧表内替换，用户裁定不进产品。
- 2026-11-12 ADR-0026：`max_tokens` 16384、提示预算 32256（`q3-names-v2`）。
- 2026-11-17 ADR-0028：只在格式不合格时重试，空表合法（`q3-names-v3`）。
- 2026-11-18 ADR-0031 删除研究代码；ADR-0032 删除 llama.cpp 与 27B 清单条目（现见 [ADR-0033](0033-ffmpeg-branch-lock.md)）。
