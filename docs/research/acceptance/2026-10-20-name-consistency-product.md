# 专名一致性产品路径验收：两部整片重跑

日期：2026-10-20（运行于本地时间 00:28–00:30，日志 UTC 2026-10-19 16:28–16:30）  
票据：专名一致性进产品 08（`.scratch/name-consistency-product/issues/08-acceptance.md`，Git 忽略）；决定见 [ADR-0014](../../adr/0014-name-consistency-in-product.md)，冻结配置见 [ADR-0013](../../adr/0013-name-consistency-closed.md)  
代码：main `d5f0933` 加票据 02–07 的未提交工作树（产品 `kototoki/names/`、`kototoki/llama_server.py` 与编排接入）；本票据未改任何代码、参数、提示或配方  
产物：`.local/name-consistency-product/`（Git 忽略，清单见文末）

## 结论

- **判据 ①②③ 全部满足**；判据 ④（用户抽看 `changes`）的位置清单在下文，待用户看过。
- ① 退出码 0；两部 `name-table.json` 的 `build.status == "ok"`（都是第一次尝试成功）；`cues_changed` HF II 55、HF III 32。
- ② `apply_table measure` 不一致率：HF II 0.151 → 0.135，HF III 0.121 → 0.094，两部都下降。
- ③ 研究脚本 `apply_table`（默认参数）在产品表上跑同一份替换前 `zh.srt`，`zh.replaced.srt` 与产品发布的 `zh.srt` **逐字节相同**（未做任何行尾归一）；`summary.totals`、逐实体 `summary.entries`、`unresolved` 也全同，`changes` 只差产品多一个 `cue_id`、少一个研究期的 `pass` 字段。
- 工程行为符合预期：STT 产物按身份跳过、翻译 run 读回（0.1 s，未起 Hy-MT2，`translate-sessions/` 无新目录）、names 建表 2 部后重新发布；整次运行 117 s，无 WARNING、无重试、无 server 重启。

## 输入与运行

| 项 | 值 |
| --- | --- |
| 输入 | `.local/bilingual-fullfilm-08/w0.toml`（只写 `paths.input_dir`、`paths.output_dir`、`stt.engine = "w0"`，`[names]` 取默认：`enabled = true`、`seed = 20261019`、`port = 8081`） |
| 影片 | HF II（工作目录 `8d2f3e76dd0c`，1099 cue）、HF III（`fb2e0da74018`，1219 cue）；`ja.srt` 与上次发布相同（`f86279e2…`、`9cdc7a27…`），翻译 run 为 `dp10-cut-degrade-v1__s20261008` |
| 命令 | `.venv\Scripts\python.exe -X utf8 -m kototoki .local/bilingual-fullfilm-08/w0.toml`（仓库根目录，PowerShell） |
| 模型 | `unsloth/Qwen3.8-27B-GGUF` 的 `Qwen3.8-27B-UD-IQ3_S.gguf`（revision `4ca72078…`，12,040,883,104 字节，sha256 `d847e2c1…`，本次重新计算核对，7.6 s） |
| 引擎 | llama.cpp `b11669-cuda13.4`（`620d2225c`），`-c 20480`、`--reasoning off`，66／66 层驻留 GPU（CUDA0 模型缓冲 10617 MiB） |
| 配方 | 提示 `build-table-prompt-v5`，`BUILD` recipe hash `5b8d1b76…`，`APPLY` recipe hash `5c795c35…` |
| 前置核对 | 无 `.local/gpu.lock`，`Get-Process llama-server` 无结果，`nvidia-smi` 已用 947 MiB、空闲 15031 MiB（桌面基线） |
| 替换前基线 | 运行前把两部最终 `zh.srt`、`ja.srt`、`ja-zh.srt` 与 `published.json` 复制到 `before/<HF-II／HF-III>/`；`zh.srt` sha256 与旧 `published.json` 记录一致（`910b9ead…`、`89cecf81…`） |

## 运行数字

| 项 | 值 |
| --- | --- |
| 退出码 | 0（`[summary] 2 video(s): 2 published … 0 failed …, 87 name replacement(s)`） |
| 整次墙钟 | 117.3 s（scan＋extract 10.1 s，names 105.9 s，translate 读回 0.1 s，publish 0.7 s） |
| names 阶段 | 取锁到 server 就绪 14.5 s（含模型 sha256 核对 7.6 s、冷加载 5.6 s）；HF III 40.5 s、HF II 49.5 s |
| 启动前空闲显存 | 15029 MiB |
| 整机显存峰值 | 13445 MiB（`engine-final.json` 的 `peak_device_memory_mib`，含约 0.95 GiB 桌面基线），与 07 smoke 的 13444 MiB 相同：整片提示约 13–15K tokens 下峰值不升 |
| server 收尾 | `server_stop = terminated`（编排在阶段结束时停掉），`server.log` 无 error／warn／OOM |

| 影片 | prompt tok | completion tok | 建表秒数 | attempt | 条目（丢弃） | kind × confidence | forms |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: |
| HF II | 13240 | 2382 | 49.5 | 1 | 20（形状 10、称呼词 1、日文写法形状 4） | person high 9／medium 5／low 1，org high 3，place high 1，other high 1 | 37 |
| HF III | 14609 | 1844 | 40.5 | 1 | 15（形状 7、称呼词 0、日文写法形状 3） | person high 8／medium 2，org high 2，other high 2，class high 1 | 28 |

"丢弃"是程序兜底删掉的字段或写法（日志里的 `dropped`）：zh 形状过滤删的全是罗马字 `zh_variants`；HF II 的称呼词黑名单删了 `父さん`（挂在 遠坂時臣 下，正是研究期"爸爸→时臣"有害行的来源）。

## 替换审计（`names-apply.json` 的 `summary.totals`）

| 影片 | anchored | replaced_stat | replaced_variant | already_canonical | partial_canonical | not_found | overlap | compound | boundary | cues_changed | 有替换的实体 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HF II | 214 | 55 | 0 | 108 | 0 | 24 | 8 | 0 | 19 | 55 | 6 |
| HF III | 190 | 32 | 0 | 83 | 31 | 32 | 0 | 1 | 11 | 32 | 8 |

全部替换来自统计层（变体层 0）；HF III 有 2 处按规则一扩展（`extended_from`）。按目标写法分：HF II 士郎 17、Rider 17、伊莉雅 9、Archer 5、Saber 3、间桐 3、卫宫士郎 1；HF III 士郎 15、Rider 6、爱因兹贝伦 3、凛 2、Saber 2、言峰 2、Assassin 1、切嗣 1。

`published.json.sources` 两部都新增 `names`（`{ja_srt_sha256, recipe_hash, seed}`）与 `names_apply`（上游 `name-table.json` 的 sha256 加 `APPLY` hash）两键；`translate` 身份不变。发布后的 `zh.srt` sha256：HF II `95bcb9dc…`、HF III `34b8067b…`。

## 判据

### ① 运行与建表

满足：退出码 0；两部 `build.status == "ok"`、`reason` 为空、`meta.attempt == 1`；`cues_changed` 55／32 > 0。

### ② 不一致率（`apply_table measure`）

命令：`python -X utf8 -m experiments.name_consistency.apply_table measure --pair <名> <ja.srt> <zh.srt> … --out .local/name-consistency-product/measure.json`（替换前用 `before/`，替换后用 `after/` 里的发布文件）。

| 影片 | 状态 | terms | main | alt | missing | 不一致率 | 有异写的 term |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HF II | 替换前 | 14 | 73 | 13 | 24 | 0.151 | 3 |
| HF II | 替换后 | 11 | 64 | 10 | 23 | **0.135** | 3 |
| HF III | 替换前 | 12 | 58 | 8 | 19 | 0.121 | 4 |
| HF III | 替换后 | 11 | 58 | 6 | 17 | **0.094** | 3 |

满足：两部都下降。读法限制：`measure` 的 term 集合由数据自动选出，替换后集合缩小（14 → 11、12 → 11），比率不是同一组 term 上的严格前后对比（第二轮报告 §1 已记录同一问题）。剩余异写里 マスター（大师／御主／master）、シンジ（真士／真司）、トウサカ（托萨克／东坂）替换前后不变；HF II 的 ライダー 异写从 5 处降到 2 处，HF III 的 セイバー 异写消失。

### ③ 与研究脚本逐字节等价

做法：每部把产品 `name-table.json` 去掉 `identity` 块写成 `equiv/<影片>/table.json`，运行 `python -X utf8 -m experiments.name_consistency.apply_table --table equiv/<影片>/table.json --ja before/<影片>/ja.srt --zh before/<影片>/zh.srt --out-dir equiv/<影片>/`（默认参数）。

| 影片 | 研究脚本 `zh.replaced.srt` | 产品发布 `zh.srt` | 逐字节 | totals | summary.entries | changes | unresolved |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HF II | `95bcb9dc…` | `95bcb9dc…` | 相同 | 相同 | 相同 | 55 条相同¹ | 51 条相同 |
| HF III | `34b8067b…` | `34b8067b…` | 相同 | 相同 | 相同 | 32 条相同¹ | 44 条相同 |

¹ 比较时去掉产品多出的 `cue_id` 与研究期 `--iterate` 用的 `pass` 字段，其余字段与顺序全同。

满足：未做行尾归一，原始字节即相同。票据 04 的移植在这两部整片上与研究脚本默认路径一致。

### ④ 用户抽看 `changes`（待用户）

按 `ja.srt` 时间轴取改动 cue 最密的 5 分钟片段：

| 影片 | 片段 | 片段内改动 cue | 片段内目标写法 |
| --- | --- | --- | --- |
| HF II | 0:13:46–0:18:46 | 8／55：#117、#123、#134、#140、#141、#143、#152、#159 | Rider 7、间桐 1 |
| HF III | 1:04:52–1:09:52 | 10／32：#720、#721、#722、#729、#731、#733、#741、#744、#749、#755 | 士郎 4、凛 2、Saber 2、Rider 1、切嗣 1 |

每 10 分钟改动数：HF II 0–10 分 9、10–20 分 10、20–30 分 3、30–40 分 8、40–50 分 5、60–70 分 9、70–80 分 5、90–100 分 4、100–110 分 2；HF III 0–10 分 2、10–20 分 1、20–30 分 1、40–50 分 5、50–60 分 7、60–70 分 10、70–80 分 4、90–100 分 1、110–120 分 1。逐条前后对照在 `after/<影片>/names-apply.json` 的 `changes`（`index` 为 SRT 编号，`zh_before`／`zh_after`），专名表在同目录 `name-table.json`。

## 未覆盖

- 改动的逐行好坏没有评审（用户裁定不做 Opus 评审，只看 ④ 抽看）；表里条目是否有错名（研究期见过的次要角色知识错）未人工核对。
- 只测了 w0 两部；x0 输出、剧集、其他作品与失败路径（`too_long`／`failed` 空表、server 起不来）没有真实运行，失败路径只有离线测试。
- 只运行一次，未测同一 seed 下建表的可重复性。

## 文件位置

`.local/name-consistency-product/`：`run.out`（运行输出与墙钟）、`session/`（本次运行日志 `run-20261019T162812Z.log` 与 `engine-final.json`）、`before/<影片>/`（替换前三份 SRT 与旧 `published.json`）、`after/<影片>/`（发布后三份 SRT、`name-table.json`、`names-apply.json`、`published.json`）、`measure.json`／`measure.out`（判据 ②）、`equiv/<影片>/`（判据 ③ 的表与研究脚本输出）、`equiv/equiv-and-windows.out`（判据 ③ 比较与 ④ 片段）、`scripts/`（两个统计脚本）。原始工作目录在 `.local/bilingual-fullfilm-08/out-w0/.work/`（server 日志在 `names-sessions/20261019T162823Z-24420/session-01/`）。
