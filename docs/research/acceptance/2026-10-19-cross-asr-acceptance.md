# cross 模式 T6：产品路径整批验收

状态：concluded（2026-10-19）  
范围：[ADR-0012](../../adr/0012-cross-asr-judge.md)（增量说明已吸收进 ADR-0012 与模块页）§5 的 T6 验收线；票据 `.scratch/cross-asr-judge/issues/07-t6-acceptance.md`。用户授权的 GPU 作业：HF II／III 以 `[stt] engine = "cross"` 整批运行一次 `python -m kototoki`（含 align、translate），其余只用 `kototoki_eval`（CPU）离线评分。  
代码：main `0db8941`（T0–T5 已合入），本次未改产品代码  
产物：`.local/cross-acceptance/`（`cross.toml`、`out-cross/` 整片输出与 `.work/`、`telemetry-cross/` 遥测、`eval/` 评分、`scripts/` 两个离线分析脚本及其输出 `judge-compare.txt`／`phases.txt`），Git 忽略

## 结论

| 验收线（§5） | 实测 | 判定 |
| --- | --- | --- |
| 两部 CER 都低于 w0 | II 16.81% → **15.93%**（−0.88 pp）；III 13.77% → **12.75%**（−1.01 pp） | 通过 |
| 两部合计降幅 ≥ 1.0 pp | 合计 15.25% → **14.30%**，降 **0.95 pp**（编辑量 3375 → 3165，−210；达线需 −222） | **未达**，差 0.05 pp（约 12 处编辑），按 §5 记录差异、由用户裁定是否仍采用 |
| `asr-x0.json` 失败窗口与单独 x0 运行一致（0） | 两部 x0 失败窗口 0／0；`asr-x0.json` 的 CER 与 S／D／I 与 swr 单独 x0 逐项相同 | 通过 |
| 裁判统计与 T0 探针同口径对照 | 窗口 402、相同 41、分歧区间 1084、改为 x0 200（18.5%）、x0 失败 0、打分出错 0，与探针**逐项相同**；1084 个区间的决定与 d 逐个相同（max \|Δd\| 0），402 个窗口的合并文本相同 | 通过 |
| asr 阶段整卡峰值 ≤ T0 阈值 | 10030 MiB（空闲 865 MiB），加 1 GB 为 11054 MiB ≤ 13824 MiB | 通过 |
| worker 退出后翻译阶段正常启动 | asr 结束后整卡回到 851 MiB；llama-server 启动前空闲 15120 MiB ≥ 14700，7.1 s 加载完成 | 通过 |
| SRT 齐全 | 一次 cross 整批的完整产物为 2 部 × `ja`／`zh`／`ja-zh` ＝ 6 份（票据写的"12 份"是以往 w0、x0 两次整批合计的口径），三份 cue 数一致，`published.json` 两份，SHA256 与输出文件一致 | 通过 |
| 墙钟（记录实际值） | asr 阶段 1211.6 s，为 swr 回归 w0 asr（323.4 s）的 3.75 倍（§5 估 4.4 倍）；整批 1754.8 s | 记录 |

- **总判定**：工程行为与设计全部吻合，裁判在产品 worker 路径上与 T0 探针逐区间一致；质量线一条通过（两部都降）、一条差 0.05 pp 未达（合计 −0.95 pp）。是否仍采用 `cross`、ADR-0012 改 accepted 还是 rejected，留给用户裁定（T7）。
- **增益构成**：两部合计替换 −82、插入 −175、删除 **+47**。删除增加与 §7"结束符偏差（w0 多出类区间偏向删除）"的预期方向一致；插入减少是主要收益来源，与 oracle 研究"一半增益来自删掉多出的字"一致。
- **口径差**：研究单元口径 −1.85 pp（16.16% → 14.31%），产品官方整片口径 −0.95 pp，约为研究的一半。§1 列出的折扣（表记改动计入 CER、窗口口径与单元口径不同）在本次数字里都在，没有分别量化。
- **发现两处与验收线无关的日志问题**（只记录，未修）：见"异常与发现"。

## 输入与运行

| 项 | 值 |
| --- | --- |
| 输入 | `.local/bilingual-fullfilm-08/input/`（HF II／III 的 `.mkv` 硬链接，只读），与 swr 回归相同 |
| 配置 | `.local/cross-acceptance/cross.toml`：由 `.local/quality-exploration-v5/01/w0.toml` 复制，只改 `stt.engine = "cross"` 与 `paths.output_dir`（新目录 `out-cross`），其余取默认 |
| 命令 | `.venv/Scripts/python.exe -X utf8 -m experiments.quality_v5.telemetry_run --out .local/cross-acceptance/telemetry-cross -- .venv/Scripts/python.exe -X utf8 -m kototoki .local/cross-acceptance/cross.toml` |
| 运行时间 | 2026-10-19 06:34:53–07:04:08 UTC（1754.8 s），退出码 0 |
| 前置核对 | `Get-Process` 无 python／llama 进程；`nvidia-smi` compute 列表只有桌面 C+G 进程；无 `.local/gpu.lock`；空闲整卡 860 MiB（遥测首样本 865 MiB） |
| 结束核对 | 无残留 python／llama 进程，`.local/gpu.lock` 与输出目录锁均已由产品释放，整卡回到 593 MiB |
| 身份核对 | 两部 PCM SHA256 等于基线（II `ee4e2da3…604f`、III `e8e841fd…3ab6`）；`asr.json` 身份含 13 个模型文件（Whisper 5、mel 资产 1、Qwen 7），配方 `cross-w0-x0-whisper-judge-v1`（recipe_hash `ab9f4532…`） |

遥测：`telemetry_run.py` 照常 0.5 s 采样整卡显存（3160 个样本），但它按旧日志格式（行首 `[ t s]`）切阶段，运行日志改造（`7559cc6`）后行首多了 UTC 时间戳，`driver-result.json` 的 `phases` 为空。阶段墙钟与峰值改用 `.local/cross-acceptance/scripts/phases.py` 离线切分：正则接受时间戳前缀，编排器起点取各行"UTC − 相对秒"的最大值（UTC 截到整秒，偏差 < 1 s），样本按相对秒归入阶段，口径与 `telemetry_run.summarize` 相同。

## STT（离线评分）

评分器与口径同 swr 回归：`python -m kototoki_eval <参考> <transcript> --output`，参考 `.local/fullfilm-comparison/fullfilm-v1/corpus/references/hf-{ii,iii}-full.json`（`srt_display`）。cross 行评产品 `align.json`（与 swr 回归评的文件相同；`ja.srt` 由它生成）；另评了 `asr.json`，文本指标与 `align.json` 逐项相同。`kototoki_eval` 可以直接评 `asr.json` 结构（有 `schema_version` 与完整 `text`，无 units 时只出文本指标），所以 w0／x0 行直接评同一次运行写出的 `asr-w0.json`／`asr-x0.json`；先用 swr 回归的 w0 `asr.json` 验证过这种评法（文本指标与它的 `align.json` 评分逐项相同）。时间指标只有 `align.json` 有。

| 路线／电影 | CER | S／D／I | 候选字符 | 可测 | 半秒确定成功 | 条件 E p95／p99 s | >2 s／>5 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 基线 w0／II（swr 产品） | 16.81% | 876／676／260 | 10,365 | 645 | 580 | 0.702／7.371 | 15／9 |
| 本次 `asr-w0.json`／II | 16.81% | 876／676／260 | 10,365 | — | — | — | — |
| 本次 `asr-x0.json`／II | 18.27% | 1105／645／220 | 10,356 | — | — | — | — |
| **cross／II** | **15.93%** | 815／700／202 | 10,283 | 650 | 583 | 0.700／9.686 | 17／11 |
| 基线 w0／III（swr 产品） | 13.77% | 777／444／342 | 11,251 | 690 | 595 | 0.729／7.960 | 16／10 |
| 本次 `asr-w0.json`／III | 13.77% | 777／444／342 | 11,251 | — | — | — | — |
| 本次 `asr-x0.json`／III | 14.99% | 1005／485／212 | 11,080 | — | — | — | — |
| **cross／III** | **12.75%** | 756／467／225 | 11,111 | 691 | 598 | 0.701／6.020 | 17／9 |

两部合计（ΣS＋D＋I ／ Σ参考字符，参考 10,781＋11,353＝22,134）：

| 路线 | 编辑量 | 合计 CER | 对 w0 |
| --- | ---: | ---: | ---: |
| w0 | 3375 | 15.25% | — |
| x0 | 3672 | 16.59% | +1.34 pp |
| **cross** | **3165** | **14.30%** | **−0.95 pp** |

读法：同一次运行里两路单独结果与 swr 回归逐项相同（w0 与 2026-10-05 基线也相同），说明共驻、逐文件三步不改变单路转写。cross 的条件时间误差 p95 与 w0 持平（0.70 s）；p99 II 升（7.4 → 9.7 s）、III 降（8.0 → 6.0 s）；>2 s 条数 15 → 17、16 → 17，>5 s 条数 9 → 11、10 → 9；可测条数与半秒成功数略增（II 645 → 650、580 → 583，III 690 → 691、595 → 598）。起止偏移中位数同基线（起点约 +0.10 s，终点约 −0.31／−0.37 s）。

## 裁判统计与 T0 探针对照

| 项 | HF II | HF III | 合计 | T0 探针 |
| --- | ---: | ---: | ---: | ---: |
| 窗口 | 195 | 207 | 402 | 402 |
| 规范化后相同（不打分） | 26 | 15 | 41 | 41 |
| 打分窗口 | 169 | 192 | 361 | 361 |
| 分歧区间 | 537 | 547 | 1084 | 1084 |
| 改为 x0 的区间 | 98 | 102 | 200（18.5%） | 200 |
| 有改动的窗口 | 75 | 79 | 154 | 154 |
| 含多个区间的窗口／单窗最多区间 | 134／10 | 143／9 | 277 | 277 |
| 回退规范化文本／空结果守卫 | 0／0 | 0／0 | 0／0 | 0／0 |
| w0 失败／x0 失败／打分出错 | 0／0／0 | 0／0／0 | 0／0／0 | 0／0／0 |
| 打分墙钟 s | 19.3 | 21.4 | 40.7 | 40.5 |

按区间类型（产品 `by_kind`，II＋III）：替换 145／856（16.9%）、w0 多出 46／154（29.9%）、x0 多出 9／74（12.2%）。

逐窗口对照（`scripts/judge_compare.py` 读产品 `asr-judge.json`、`asr.json` 与探针 `judge-<film>.jsonl`）：402 个窗口的 w0 原文、x0 原文、合并文本全部相同；1084 个区间的决定全部相同，d 的最大差为 0。产品 `kototoki/judge.py`＋`WhisperAsr.score` 与探针的研究打分路径在这两部上数值等价（探针记录"未验证"中的一项由此补上）。

## 各阶段墙钟与显存峰值

墙钟取产品日志；显存为整卡采样峰值（含桌面，本次空闲约 0.86 GB，探针时约 2.0 GB）。swr 列取 [swr 回归](2026-10-16-bilingual-pipeline-swr-regression.md)。

| 阶段 | cross 墙钟 s | cross 峰值 MiB | swr w0 墙钟 s | swr w0 峰值 MiB | swr x0 墙钟 s | swr x0 峰值 MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| scan＋extract | 24.8 | 866 | 16.4 | — | 21.2 | — |
| vad | 35.4 | 1897 | 93.1 | 1969 | 32.4 | 1506 |
| asr | 1211.6 | 10030 | 323.4 | 5265 | 903.0 | 5420 |
| align | 97.5 | 8445 | 96.1 | 8515 | 95.8 | 8060 |
| translate | 384.9 | 15721 | 360.3 | 15648 | 367.6 | 15547 |
| 总计 | 1754.8 | 15721 | 890.3 | 15648 | 1420.8 | 15547 |

asr 阶段内部（`asr.json` 的 `stages`，秒）：

| 项 | HF II | HF III | 合计 | T0 探针合计 |
| --- | ---: | ---: | ---: | ---: |
| 加载 Whisper＋Qwen（每批一次） | | | 6.3 | 9.4 |
| ① w0 转写 | 134.6 | 151.4 | 286.0 | 374.6 |
| ② x0 转写 | 412.4 | 451.3 | 863.7 | 948.7 |
| ③ Whisper 打分 | 19.3 | 21.4 | 40.7 | 40.5 |
| ①＋②＋③ | 566.3 | 624.1 | 1190.4 | 1363.7 |

- asr 阶段 1211.6 s ＝ 三步 1190.4 s ＋ worker 启动、导入、模型核对与加载约 21 s；为 swr w0 asr 阶段的 3.75 倍，比探针推算的 4.4 倍少，主要因为本次 w0 转写没有探针里 II 的约 80 s 冷启动差（本次 II 134.6 s，与 swr 单独运行 133.4 s 相当），x0 转写也比探针快约 9%。差异来源没有分离。
- asr 峰值 10030 MiB 出现在第二部（II）打分阶段附近（相对 1257.7 s）；减去空闲 865 MiB，进程约 9165 MiB，比探针（10688 − 2001 ＝ 8687 MiB）多约 480 MiB，来源未分离（可能是桌面占用估算误差或产品打分批与探针不同的缓存增长）。按探针的桌面占用 2.0 GB 折算约 11.2 GB，加 1 GB 仍 ≤ 13.5 GB。
- vad 比 swr w0 快约 58 s，与 swr 记录里"w0 是第一个 GPU 阶段冷启动"的解释一致（本次 swr x0 为 32.4 s）。
- 翻译峰值 15721 MiB，比 swr 高约 73 MiB；翻译配方已从 swr 时的 `b10-joint-degrade-v1` 换为 `dp10-cut-degrade-v1`（[ADR-0011](../../adr/0011-dp10-cut-product-recipe.md)），翻译墙钟与 swr 不直接可比。

## 输出与翻译

| 电影 | cue（三份 SRT 一致） | 翻译批次 | 降级批次 | 回退 cue | 降级请求 | 末次调用重启 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| II | 1093 | 148 | 0 | 0 | 0 | 0 |
| III | 1193 | 145 | 0 | 0 | 0 | 0 |

- run 键 `dp10-cut-degrade-v1__s20261008`；数字取各自 `translate/.../report.json`（`completion.state` 为 `complete`），与运行日志一致。票据里"477 个翻译批次"是 swr 回归时 `b10-joint` 配方 w0＋x0 两次运行的合计口径，本次配方与路线都不同，批次总数为 293。
- 汇总行：`2 video(s): 2 published (0 no speech), 0 up to date, 0 failed, 0 blocked, 0 unstable, 0 fallback cue(s)`。
- cue 数比 swr w0（1099／1219）少 6／26，来自合并文本变化后断句不同，未单独分析。

## 改为 x0 的区间抽查（15 个）

从 200 个改为 x0 的区间里用 `random.Random(20261019)` 无放回抽 15 个（`scripts/judge_compare.py`），只列区间字符，供人工过目；未听音。

| 电影 | 窗口 | 类型 | w0 区间 | x0 区间 | d |
| --- | ---: | --- | --- | --- | ---: |
| II | 18 | 替换 | サクラ | 桜 | −0.54 |
| II | 24 | 替换 | 奴 | やつ | −0.55 |
| II | 65 | w0 多出 | 邪 | （空） | −0.91 |
| II | 82 | 替换 | ひとりひとり | 一人一人 | −0.00 |
| II | 116 | 替换 | オレ | 俺 | 0.10 |
| II | 151 | w0 多出 | ウ | （空） | −0.20 |
| II | 159 | 替换 | サクラ | 桜 | −0.55 |
| II | 164 | 替换 | 昨日 | 夕べ | −0.12 |
| II | 175 | 替换 | じいさま | 爺様 | −0.00 |
| III | 45 | 替换 | は | も | −0.66 |
| III | 78 | w0 多出 | ー | （空） | 0.08 |
| III | 83 | 替换 | 敗 | 破 | −0.03 |
| III | 103 | 替换 | 分 | わ | −0.53 |
| III | 173 | 替换 | とお | 通 | 0.05 |
| III | 174 | w0 多出 | うっうわっうっうわっ | （空） | 8.03 |

读法（未听音，只按文字）：15 个里 6 个是纯表记改动（サクラ／桜 ×2、ひとりひとり／一人一人、オレ／俺、じいさま／爺様、とお／通），与 §1"Whisper 改了 8 个纯表记样本中的 6 个"一致，计入 CER 但不影响译文；3 个是删掉 w0 的单字或长音（邪、ウ、ー），1 个删掉一串喘息拟声（d 8.03，唯一的大正差）；其余 5 个是词义层面的替换（奴／やつ、昨日／夕べ、は／も、敗／破、分／わ），对错需要听音。其余 14 个的 d 都在 −1 与 0.2 之间，即多数切换落在阈值附近。

## 异常与发现

- **cross 每文件日志行没有写出**（设计 §2.3 的 `[asr] <id>: cross windows N, identical K, …`）：运行日志与 `run-…-asr.stderr.log` 里都没有。原因：worker 以 `python -m kototoki.workers.asr` 运行，模块内 `logging.getLogger(__name__)` 的名字是 `__main__`，不在 `kototoki.workers.gpu.main` 设为 INFO 的 `kototoki` logger 之下，root 默认 WARNING，INFO 行被丢弃。WARNING 及以上不受影响（align 的告警以 `[__main__]` 出现）。vad、align worker 用同样写法，INFO 行同样丢失。只影响日志，计数都在 `asr-judge.json`／`asr.json` 的 `metadata.judge` 里；本票不改 `kototoki/`，留给后续修复。
- **align 两个窗口失败**（II 窗口 182、III 窗口 188，`targets length is too long for CTC`，log_probs 只有 2／3 帧）：这两个 VAD 窗口只有 51 ms／84 ms，文本是 w0 原文（裁判未改），swr 回归的 w0 `align.json` 在同两个窗口有完全相同的 `failure` 记录，只是当时的日志格式不把它报成告警。与 cross 无关的既有行为。
- **`telemetry_run.py` 切阶段失效**：见"输入与运行"末段；只影响实验脚本的自动汇总，本次已离线补算。
- `vad.json` 的 SHA256 与探针记录不同（II `434e5d09…` 对 `029e3cf9…`）：逐字段核对只有 `stages`（加载与推理墙钟）不同，`chunks` 相同，属于新跑一次 vad 的正常差异。

## 自动检查

- 产品运行自身：退出码 0；`published.json` 记录的三份 SHA256 与输出目录的 6 份 SRT 一致；三份 SRT 的 cue 数一致；`asr.json` 通过 align 阶段消费（align 成功、身份链完整）。
- 离线：`kototoki_eval` 对 8 个文件评分（cross `align.json`／`asr.json`、`asr-w0.json`、`asr-x0.json` × 2 部）＋2 个 swr `asr.json` 校验评分；`judge_compare.py` 断言窗口数与探针相同并逐区间对照。
- 本票未改代码，未跑 `just test`。

## 未覆盖／未验证

- 合计降幅未达 1.0 pp 的原因没有拆分：没有区分"表记改动计入 CER"与"真实识别改进"各占多少，也没有把产品窗口口径换算到研究单元口径重算。
- 译文层收益（需 v5 第 2 步裁判，外部推理，另行裁定）；剧集与新材料确认；数值确定性（只跑一次，但与探针逐区间相同，说明在这两部上可复现）；w0 失败窗口以 x0 替代（本次 w0 无失败窗口，未触发）。
- 15 个抽查区间没有听音；对错未判。
- asr 峰值比探针多约 480 MiB 的来源、墙钟比探针快的来源没有分离。
- 三段式回退未实测（共驻已通过，未触发）。
- WDDM 共享显存换出没有单独采集；asr 峰值远低于 16 GB，翻译 15721 MiB 与以往一致。

## 复现命令

```pwsh
# 前置：无 .local/gpu.lock，无 python／llama 进程
.venv/Scripts/python.exe -X utf8 -m experiments.quality_v5.telemetry_run --out .local/cross-acceptance/telemetry-cross -- .venv/Scripts/python.exe -X utf8 -m kototoki .local/cross-acceptance/cross.toml

# 评分（每部、每个 transcript 一次；<id> II＝8d2f3e76dd0c，III＝fb2e0da74018）
.venv/Scripts/python.exe -X utf8 -m kototoki_eval .local/fullfilm-comparison/fullfilm-v1/corpus/references/hf-ii-full.json .local/cross-acceptance/out-cross/.work/8d2f3e76dd0c/align.json --output .local/cross-acceptance/eval/cross-align-hf-ii.json
#   同法评 asr.json、asr-w0.json、asr-x0.json 与 III

# 裁判对照与 15 区间抽样、阶段切分（Git 忽略的离线脚本）
.venv/Scripts/python.exe -X utf8 .local/cross-acceptance/scripts/judge_compare.py
.venv/Scripts/python.exe -X utf8 .local/cross-acceptance/scripts/phases.py
```
