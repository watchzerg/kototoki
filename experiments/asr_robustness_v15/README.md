# ASR 稳健性第十五轮（asr_robustness_v15）

[v15 研究文档](../../docs/research/2026-11-10-asr-robustness-v15.md)各票据的运行辅助与离线分析脚本。方案、判定纪律与结论都在研究文档；执行票据在 `.scratch/asr-robustness-v15/`（Git 忽略）。产物写 `.local/asr-robustness-v15/<票据>/`；B1 补窗直接用 v14 的 `fill` 入口，产物在 `.local/asr-robustness-v14/03/`。

本包只导入 `experiments.asr_robustness_v14.*`（只读复用，不改）、`kototoki.*`、`kototoki_eval`、`experiments.quality_v5.asr_source`，不改产品代码。转写内容只在内存里处理，写盘的报告只含计数与指标；被标记窗口文字、判读输入等只写 `.local/`，不进 Git 与日志。

| 模块 | 票据 | 作用 | 资源 |
| --- | --- | --- | --- |
| `common.py` | — | 复用 v14 `common`（两部影片对照目录、读写、官方／单元口径 CER、`gpu.lock`、显存采样）；本轮产物根目录；`segments_and_traces` | 离线 |
| `inventory.py` | 01 | 盘点所有仍在盘上的 w0 `asr.json`：产品（HF II／III）、VAD 变体、整片 demo、窗口 demo、国会；身份（配方 hash、窗数、PCM sha256） | 离线 |
| `repeat.py` | 01／02 | 显式重复检测器（定义见模块文档）：规范化文本上的相邻重复 tandem（周期 ≥ `min_period`）与非相邻复现 recurring（子串 ≥ `min_length`），按规则参数各算一份；`collapse` 折叠被标记的 tandem 区段（保留第一个单元） | 离线 |
| `scan.py` | 01 | A3：逐窗四信号（压缩比、触顶、`avg_logprob`、重复检测），规则候选 `doc-default`／`whisper-or`／`repeat`／`repeat-or-cr2.4`／`repeat-loose`／`repeat-strict` 的标记统计；被标记窗口文字与重叠参考写 `01/flagged/`（供 Opus）；`judge_rules` 合并判读算安全网判据 | 离线 |
| `actions.py` | 02 | A4：对选中规则标记的窗口做置空／折叠／`no_repeat_ngram_size=5` 单次补解＋折叠三种动作，写产品形状 `asr.json`，一次产品 `align` 批，官方 CER（S／D／I） | GPU（补解＋align） |
| `names_replace.py` | 04 | C3：按 `zh` 分组的专名表（规范写法＝对照转写里出现最多的写法）；C3a 纯规则整串替换（最长优先、更长表内写法内部不替换、单字与歧义写法不用）；C3b Flash-Next 提示 `ja-names-v1` ＋表内 diff 守卫（`table_guard`）；HF III 在同一 Strata session 内用产品 `kototoki.names.build_document` 建 Q3 表；单元口径评估、人名命中率、有害率、Opus 抽样 | 建表与 C3b GPU（Strata）；C3a 与评估离线 |

从仓库根目录运行：`.venv/Scripts/python.exe -X utf8 -m experiments.asr_robustness_v15 <子命令>`。

| 子命令 | 票据 | 作用 |
| --- | --- | --- |
| `scan [--group G]` | 01 | 盘点、四信号、规则统计，写被标记窗口供判读（离线） |
| `safety-net [--judgements P]` | 01 | 合并 Opus 判读（`01/flagged/judgements.json`），算每条规则的误报与安全网判据（离线） |
| `actions --rule R [--film F]` | 02 | 三种动作的官方 CER（GPU，先问） |
| `names-build [--film F] [--skip-build]` | 04 | HF III Q3 建表＋两部 C3b（GPU：一个 Strata session，先问） |
| `names-rules [--film F]` | 04 | C3a 纯规则替换（离线；HF III 另出 27B 旧表对照 `c3a-oldtable`） |
| `names-eval [--film F]` | 04 | C3a／C3b 单元口径评估、人名命中率、有害率、05 触发判断（离线） |
| `names-sample` | 04 | 抽 30 条改动（改好／改坏各半）供 Opus 抽看（离线） |

## 重复检测器（票据 01 定义）

在 `kototoki_eval.schema.normalize` 规范化（NFKC、去标点与空白）后的文本上：

- **tandem**：周期 p 的单元连续重复 copies 次；只计 p ≥ `min_period`（2，排除 `ああ` 这类单字呼喊的 p = 1 解释，但同一字符连写 ≥ 2 × `min_copies` 个时仍以 p = 2 计入）；取 run 最长的区段，coverage = run 字数／规范化字数。
- **recurring**：长度 ≥ `min_length`（3）的子串不重叠出现 ≥ `min_count` 次，取覆盖最大者。
- 规则：`repeat`（6 份／覆盖 ≥0.5）、`repeat-loose`（4／0.4）、`repeat-strict`（10／0.5）。安全网判据（研究文档 §4.1）下选中 `repeat-strict`。

## 表内替换（票据 04 定义）

- 分组：high 条目的 `entity_ja` 与 `forms[].ja` 按各自 `zh` 分组；同一写法出现在两个 `zh` 组里即歧义、整个不用；单字写法不参与。规范写法＝组内在对照 `ja.srt` 里出现最多的写法，并列取条目 `entity_ja`，再并列取先列出的。
- C3a：每条 cue 上找全部表内写法（长度 ≥2）的出现，最长优先、再靠左优先取不重叠命中，非规范写法整串换成规范写法；短写法落在更长表内写法内部的命中自然丢弃。
- C3b 守卫：before→after 字符 diff，间隔 ≤2 字的改动区段合并，每个区段可向两侧等同上下文对称扩展，after 侧片段必须正好是一个表内写法，否则整条回退（`rejected_not_table`）；纯删除回退（`rejected_deletion`）；v14 的编辑比 ≤0.5 守卫仍在前面。
- 人名命中率：参考单元文字（规范化）里每次出现规范写法，候选单元文字也含它的比例。

## 结论（2026-11-10 结题）

A 选中 `repeat-strict`＋折叠并建议进产品；B1 两部都净变差；C3a 在 §4.3 的频次规则下 HF II Δ0、改取表头写法（附录 `c3a-entity`）后 −26 编辑；C3b 与 HF III Q3 建表首次因可用内存 <52 GiB 未跑，重启后同日用 `names-build` 补跑：HF III Q3 表一次建成（23 条／high 19），其上 C3a −28、头写法 −51；C3b 两部无收益（HF II Δ0、HF III +4，有害率 34%）；05 按条件不触发。数字、口径与待裁定项见[研究文档](../../docs/research/2026-11-10-asr-robustness-v15.md) §7、§7.1、§8。产物在 `.local/asr-robustness-v15/`（不进 Git）。

## 验证

离线，无 GPU／模型／网络：

- `.venv/Scripts/python.exe -X utf8 -m unittest discover -s experiments/asr_robustness_v15 -t . -p 'test_*.py' -v`
- `uv run --no-project --no-python-downloads --offline --python 3.12 python -m unittest discover -s experiments/asr_robustness_v15 -t . -p 'test_*.py' -v`（即 `just experiments-test` 使用的无第三方包旧环境）
