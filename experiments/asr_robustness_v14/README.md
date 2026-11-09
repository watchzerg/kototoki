# ASR 稳健性第十四轮（asr_robustness_v14）

[v14 研究文档](../../docs/research/2026-11-09-asr-robustness-v14.md)各步骤的运行辅助与离线分析脚本。方案、判定纪律与结论都在研究文档；执行票据在 `.scratch/asr-robustness-v14/`（Git 忽略）。产物写 `.local/asr-robustness-v14/<票据>/`。

本包只导入 `kototoki.*` 与 `experiments.quality_v5.asr_source`（以及 `kototoki_eval`），不修改它们，也不改产品代码。转写内容只在内存里处理，写盘的报告只含计数与指标；转写文本不进 Git 与日志。

| 模块 | 票据 | 作用 | 资源 |
| --- | --- | --- | --- |
| `common.py` | 01 | 路径、两部影片（HF II／HF III）的产品形状对照目录、读写工具、参考字幕、官方与单元口径 CER、研究侧身份、`gpu.lock` 与显存采样 | 离线（采样函数调 `nvidia-smi`） |
| `workers.py` | 01 | 写 jobs 文件，并以产品子进程环境运行 `kototoki.workers.{vad,asr,align}`，记墙钟与显存峰值 | 运行 worker 时占 GPU |
| `inputs.py` | 01 | HF II 对照产物身份与官方 CER 核实；HF III 用产品 worker 重算（1 次 GPU run）；产品默认规则建 `ja.srt` | `verify-hf-ii` 离线；`reproduce-hf-iii` GPU |
| `signals.py` | 01 | A0：每个窗口的压缩比、触顶、`avg_logprob`，对参考的逐窗 CER 与置空收益估计，按阈值规则统计被标记窗口 | 离线 |
| `gaps.py` | 01 | B0：VAD 子段落字统计、空子段与参考覆盖、对照删除项按位置分类 | 离线 |
| `guard.py` | 02 | A1／A2：幻觉守卫。A1 把被标记窗口的字符从 `align.json` 的 `text`／`units` 删掉（其余 unit 时间不变）并评官方 CER；A2 对同批窗口加 `no_repeat_ngram_size=5` 单次补解，仍触阈值即置空；`gate` 给出 §4.0 的门 | `blank` 离线；`redecode` GPU |
| `fill.py` | 03 | B1：每个时长 ≥1 s 的空子段单独作窗口、w0 同配方解一次，过 A0 守卫后按时间插入所在窗口的段文字（`insert_position`／`merge_fill`），再经产品 `align` 评官方 CER | GPU |
| `correct.py` | 04 | C1／C2：Strata 上 Flash-Next 只读前后文修正日文错字（C2 另注入 `confidence: high` 专名表），程序守卫编辑比 ≤0.5；提示 `ja-correct-v1` 与收紧的修订 `ja-correct-v2`（§4.3 允许的一次修订）；单元口径评估与改动分类 | 校正 GPU（Strata）；评估离线 |
| `decode.py` | 02／03 | GPU 公共部分：持有产品 `WhisperAsr` 单次解码、写研究侧产品形状 `asr.json`；`signal_of`、`models_sha256` 为纯函数 | 解码 GPU；纯函数离线 |

从仓库根目录运行：`.venv/Scripts/python.exe -X utf8 -m experiments.asr_robustness_v14 <子命令>`。

| 子命令 | 票据 | 作用 |
| --- | --- | --- |
| `verify-hf-ii` | 01 | HF II 对照产物身份与官方 CER |
| `reproduce-hf-iii` | 01 | HF III 产品 STT 重算（GPU，先问） |
| `signals [--film F]` | 01 | A0 守卫信号、逐窗 CER、阈值表 |
| `gaps [--film F]` | 01 | B0 空子段统计与删除项定位 |
| `blank --rule R` | 02 | A1 被标记窗口置空的离线模拟 |
| `redecode --rule R` | 02 | A2 问题窗口单次补解（GPU） |
| `fill --rule R` | 03 | B1 空子段补窗重解码（GPU） |
| `correct --arms c1,c2 --prompt P` | 04 | C1／C2 Strata 后校正（GPU） |
| `correct-eval --run R` | 04 | 校正结果的单元口径评估与改动分类（离线） |
| `correct-sample --run R` | 04 | 抽 30 条改动供 Opus 抽看（离线） |

## 验证

离线，无 GPU／模型／网络：

- `.venv/Scripts/python.exe -X utf8 -m unittest discover -s experiments/asr_robustness_v14 -t . -p 'test_*.py' -v`
- `uv run --no-project --no-python-downloads --offline --python 3.12 python -m unittest discover -s experiments/asr_robustness_v14 -t . -p 'test_*.py' -v`（即 `just experiments-test` 使用的无第三方包旧环境）
