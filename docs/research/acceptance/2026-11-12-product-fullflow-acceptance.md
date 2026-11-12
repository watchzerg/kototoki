# 产品全流程验收：两部整片强制走 ASR

日期：2026-11-12（日志 UTC 07:59–08:30）  
代码：main `31782b2`（运行日志补缺票据 10 结题后），本次未改任何代码、参数、提示或配方  
产物：`.local/acceptance-20261112/`（Git 忽略：`kototoki.toml`、`input/`（源 MKV 硬链接与发布字幕）、`work/`、`run.out`、`rerun1.out`、`rerun2.out`、`backup/`）

## 范围

只验工程行为：能否从头跑通、各阶段与中间产物是否齐全且结构自洽、日志里有没有异常过程行为（拒答、截断、降级、重启、残留进程或锁）。**不评字幕质量。**

原计划是两部已知电影加随机两集剧集。剧集来源（扫描记录里的 `Y:\`、`Z:\` 网络盘，以及旧的 `D:/movie/石纪元/`）当时都不可用，经用户同意只跑两部电影。

## 输入与运行

| 项 | 值 |
| --- | --- |
| 影片 | HF II（`8d2f3e76dd0c`）、HF III（`fb2e0da74018`），源 MKV 硬链接到 `input/`，字幕不写进 `D:/movie` |
| 配置 | `paths.input_dir`、`paths.work_dir` 在验收目录内；`[input] use_embedded_subtitles = false`（两部 MKV 都带日文文本字幕轨，不关掉会跳过 STT）；`stt.engine = "w0"`；其余取默认（`[translate] seed = 20261008`、`[names] seed = 20261019`） |
| 命令 | `PYTHONUTF8=1 .venv/Scripts/python.exe -m kototoki .local/acceptance-20261112/kototoki.toml`（仓库根目录） |
| 前置核对 | 无 `.local/gpu.lock`，`strata launch --status` 为空，`nvidia-smi` 已用 1001 MiB |

## 结论

- 退出码 0，`[summary] 2 file(s): 2 published (0 no speech, 0 from embedded subtitles) … 0 failed … 0 fallback cue(s)`，总耗时 1686 s（约 28 分钟）。
- 全部阶段 `0 failed`；翻译 296 个批次 `finish_reason` 全是 `stop`，降级 0、回退 0、Strata 重启 0；日志里没有模型拒答。
- 运行结束后 GPU 锁与工作根锁已释放，Strata `stop ok`、`status_empty: true`，显存回到 15203 MiB 空闲。
- 运行日志文件与控制台输出逐行相同。
- 续跑：原命令重跑时两部都在扫描阶段跳过（`2 with subtitles`，未取 GPU 锁）；移走 HF II 的字幕再跑，`[plan] resume at: translate 1`，`extract (reused)`、`translate (resumed)` 用时 0.0 s、未启动 Strata，重新发布的字幕与原字幕 SHA256 相同（`4123a31e…`）。

## 阶段数字

| 阶段 | HF II | HF III | 墙钟 |
| --- | --- | --- | --- |
| extract | 117.1 min，16 kHz 单声道 16 bit | 122.1 min | 43.7 s |
| vad | 195 窗 | 207 窗 | 69.8 s（模型加载 37.2 s） |
| asr（w0） | 0 失败，0 守卫 | 0 失败，1 窗被复读守卫折叠 | 307.9 s |
| align | 1 窗对齐失败，417 个 text-only unit | 1 窗对齐失败，658 个 text-only unit | 102.7 s |
| cues | 1099 cue，5 个回退 unit，0 未渲染字符 | 1217 cue，12 个回退 unit，0 未渲染字符 | 0.3 s |
| names | 21 条（high 15、medium 6），第 1 次成功 | 30 条（high 20、medium 8、low 2），第 3 次成功 | 238.6 s（含 Strata 启动 80.5 s） |
| translate | 149 批，0 降级，0 回退 | 147 批，0 降级，0 回退 | 905.7 s |

Strata 会话：`iq3_s-128k`（dflash2，experts 放在内存），采样峰值 GPU 15955 MiB、内存 61.0 GiB，`reasoning_recoveries`、`nonfinite_logits`、`repeat_stops` 都是 0。

## 产物校验（非语义）

每部影片的检查项（脚本只输出计数，不打印内容）：

- `probe`、`vad`、`asr`、`align`、`ja-cues`、`name-table`、`published` 都可解析，带 `identity`；`vad`、`asr`、`align` 的 `offset_s == 0`；没有残留 `failure.json`。
- `ja.srt` 的 SHA256 等于 `ja-cues.json` 的 `ja_srt_sha256`，条数相同。
- 最终 `<主名>.ja-zh.srt` 按 `kototoki.srt.parse_srt` 严格解析通过；UTF-8 无 BOM、LF；SHA256 与 `published.json` 一致；条数等于 `ja.srt`；每条都是两行（中文在上）；日文行和时间轴与 `ja.srt` 逐条相同；无空行、无重叠；末条结束时间在音频时长内。
- `translate/report.json`：`state: complete`，批次与 cue 数齐全。

按启发式标出、经人工确认不是问题的行：

| 标记 | HF II | HF III | 判定 |
| --- | --- | --- | --- |
| 中文行像拒答（`抱歉`、`我不能` 等） | 0 | 2 | 都是台词本身的正常译法，不是模型拒答 |
| 中文行与日文行相同 | 8 | 6 | 汉字词（如"解放""最近"）、单字、英文咏唱与片尾英文 |
| 中文行含假名 | 3 | 0 | 1 个人名保留片假名，2 条是片尾歌词的混排；属质量范畴，本次不评 |

## 过程中的观察

1. **建表回复超出预算（HF III）**：第 1、2 次尝试都在 8192 completion token 处被截断（`finish_reason=length`，约 2.08 万字符），按设计拒绝解析并换 seed 重试，第 3 次成功（4931 token）。原始回复的统计表明这**不是复读循环**：两次截断时分别已列出 49、63 个不同实体，成功那次列了 37 个，是模型列得太全，撑满了输出预算。11-09 的 Q3 产品运行在 HF II 上成功那次也用了 7766 token。按现在的输出量，整片建表贴着 8192 上限，两次失败多花了约 100 s。是否调整由用户决定（专名研究线已结题，本次不提新轮次）。
2. **复读守卫（HF III asr 第 51 窗）**：`repeat-strict` 折叠一次（周期 2、22 份、删去 63 字），worker stderr 记 WARNING，属 [ADR-0023](../../adr/0023-asr-repeat-guard.md) 的设计行为。
3. **对齐失败窗口（两部各 1 窗）**：窗口只有 2–3 帧 log-probs，CTC 报 `targets length is too long`，按设计回退成文字插值。HF II 的数字（195 窗、1 失败、417 text-only）与[运行日志模块页](../../architecture/modules/run-logging-and-processes.md)里的示例行相同。
4. **同种子建表结果不同**：HF II 用 seed 20261019 第一次就成功（21 条）；11-09 同一 seed 第一次是 JSON 尾逗号失败，重试后才成功（25 条）。说明同种子不保证可重复（DFlash2 推测解码），与验收无关，只做记录。
5. worker stderr 里另有两条 torch glog 行（`triton not found`、`Redirects are currently not supported`），按设计不计入告警数。

## 未覆盖

- 剧集（短时长、片头片尾结构、同目录多文件）；x0 与 cross 引擎；内嵌字幕路径。
- 字幕质量、STT 与基线的回归、翻译评分。
- 失败、中断、强杀路径。

## ADR-0026 验证与内嵌字幕补漏（同日追加）

用户根据观察 1 决定放宽建表的输出上限与提示预算（[ADR-0026](../../adr/0026-names-output-and-prompt-budget.md)，`q3-names-v2`：`max_tokens` 16384、提示预算 32256），实现后重跑验证。离线门禁：`just check`、`just test`（744）、`just test-full`、`just test-equivalence` 全过，`experiments/scene_batching_v6` 的 81 个研究测试全过（v13 各变体 hash 不变）。

### HF III 重建表（输出上限）

删掉 HF III 的字幕后重跑原配置（HF II 已有字幕，跳过）：`[plan] resume at: names 1`，建表、翻译、发布，退出码 0，非语义产物校验同前全过。

| 尝试 | seed | 结果 | completion token |
| --- | --- | --- | --- |
| 1 | 20261019 | 截断（`length`），回复 42215 字符 | 16384 |
| 2 | 20261020 | 截断（`length`），回复 41378 字符 | 16384 |
| 3 | 20261021 | 正常结束但 JSON 缺逗号 | 12908 |
| 4 | 20261022 | 成功：保留 40 条、丢弃 101 条 | 11047 |

- **16K 截断仍是生成失控**：第 1 次回复列了 135 个实体（不同的 134 个），其中 `other` 类 101 个、`low` 置信度 73 个，四段分布均匀——模型一直罗列低价值条目、不收尾，与 v13 记录的"失控"一致。放宽上限救不回这类回复，只让每次失败尝试从约 50 s 变成约 100 s。本次建表 364 s（8192 时为 129 s）。
- **放宽确实救回了一次**：第 4 次 11047 token 的合格表在 8192 下会被截断。但它的原始条目 141 个，超过 schema 的 `maxItems: 80`（解析器不校验条目数），丢弃 101 条后剩 40 条。
- **同 seed 不可重复**：seed 20261021 在 8192 时 4931 token 成功，这次 12908 token、JSON 错误（DFlash2 推测解码，生成本就不确定）。
- 新旧两张表：high 实体 14 个相同、旧表独有 6 个、新表独有 9 个，high 写法相同 32 条（旧 54、新 50）；两张表来自不同 seed，不能据此比质量。翻译 147 批全部 `stop`，降级与回退 0。

### Black Panther（提示预算；内嵌字幕路径）

`.local/acceptance-20261112/bp/`，默认配置（`use_embedded_subtitles = true`）。

- **发现并修复的缺陷**：首跑选中 31 号字幕轨（标题 `ja--forced--`，224 条，只有外语对白）。两条 jpn 轨的 `disposition:forced` 都是 0，forced 只写在标题里，产品只看 disposition。修复：`media.parse_probe` 的 `forced` 改为"disposition 标了 forced，或标题含 forced（不分大小写）"，`EMBEDDED` 配方 id 升为 `embedded-ja-subtitle-v2`（hash `351da4b1…`），新增单测；ADR-0024 状态行追加补漏说明。
- **修复后重跑**：选中 32 号轨（`Japanese`），1655 条，清洗丢弃 0；工作目录没有音频与 STT 产物。建表提示 **20059 token**（旧预算 15872 下会 `too_long` 写空表），第 2 次成功（第 1 次 JSON 尾逗号），46 条，5150 completion token；翻译 207 批全部完成，降级与回退 0；退出码 0，锁与 Strata 正常释放。
- 非语义校验：1655 条全部两行，日文与时间轴与 `ja.srt` 逐条相同，SHA256 与 `published.json` 一致，无 BOM、无 CR。有 5 处时间重叠，与 `ja.srt` 相同，来自源字幕轨本身。疑似拒答命中 1 条，是台词（"为了安全，我不能说"）。
- 提示估算校准：（20059 − 1100）／1655 ≈ 11.5 token／cue，与按 HF 两部估的 11 相符。

### 结论

- **提示预算放宽有效**：对白密的长片（Black Panther 2 万 token）从必然空表变为正常建表。
- **输出上限放宽收效有限**：救回了 1 次 11K token 的合格表，但主要失败形态是无限罗列，16K 下依旧截断，失败成本翻倍。是否保留 16384、退回 8192，或另加"条目数超 80 即停"之类的措施，留给用户裁定。
- **用户裁定（2026-11-12）**：看过上述结果后，保留 `max_tokens` 16384。
