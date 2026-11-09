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

从仓库根目录运行：`.venv/Scripts/python.exe -X utf8 -m experiments.asr_robustness_v15 <子命令>`。

| 子命令 | 票据 | 作用 |
| --- | --- | --- |
| `scan [--group G]` | 01 | 盘点、四信号、规则统计，写被标记窗口供判读（离线） |
| `safety-net [--judgements P]` | 01 | 合并 Opus 判读（`01/flagged/judgements.json`），算每条规则的误报与安全网判据（离线） |
| `actions --rule R [--film F]` | 02 | 三种动作的官方 CER（GPU，先问） |

## 重复检测器（票据 01 定义）

在 `kototoki_eval.schema.normalize` 规范化（NFKC、去标点与空白）后的文本上：

- **tandem**：周期 p 的单元连续重复 copies 次；只计 p ≥ `min_period`（2，排除 `ああ` 这类单字呼喊的 p = 1 解释，但同一字符连写 ≥ 2 × `min_copies` 个时仍以 p = 2 计入）；取 run 最长的区段，coverage = run 字数／规范化字数。
- **recurring**：长度 ≥ `min_length`（3）的子串不重叠出现 ≥ `min_count` 次，取覆盖最大者。
- 规则：`repeat`（6 份／覆盖 ≥0.5）、`repeat-loose`（4／0.4）、`repeat-strict`（10／0.5）。安全网判据（研究文档 §4.1）下选中 `repeat-strict`。

## 验证

离线，无 GPU／模型／网络：

- `.venv/Scripts/python.exe -X utf8 -m unittest discover -s experiments/asr_robustness_v15 -t . -p 'test_*.py' -v`
- `uv run --no-project --no-python-downloads --offline --python 3.12 python -m unittest discover -s experiments/asr_robustness_v15 -t . -p 'test_*.py' -v`（即 `just experiments-test` 使用的无第三方包旧环境）
