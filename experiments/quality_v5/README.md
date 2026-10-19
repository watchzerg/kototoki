# 字幕质量探索第五轮（quality_v5）

[v5 研究文档](../../docs/research/2026-10-16-quality-exploration-v5.md)各步骤的运行辅助与离线分析脚本。方案、判定纪律与结论都在研究文档；执行票据在 `.scratch/quality-exploration-v5/`（Git 忽略）。产物写 `.local/quality-exploration-v5/<票据编号>/`。

本包只导入 v3／v4 与 `kototoki_eval` 的函数，不修改它们；不改 `kototoki/` 产品代码。

| 模块 | 票据 | 作用 | 资源 |
| --- | --- | --- | --- |
| `telemetry_run.py` | 01 | 运行一条命令（如 `python -m kototoki`），旁路 0.5 s 采样整卡显存，按产品日志切阶段，写 `driver-result.json` | 随被测命令 |
| `asr_source.py` | 02 | 参考源与 ASR 源翻译按时间对齐成单元、按日文 CER 分桶；成对盲评 profile `v5-asr-pairwise-v1` 与校准；分桶外推 ASR 带来的中文错误占比 | 离线；`judge` 消耗 Claude 配额（退出码 75＝配额耗尽，可续跑） |
| `readability.py` | 03 | 中文 CPS、行长、显示时长、每条行数、中日长度比的分布与超阈值占比；`v4ref` 子命令给字幕组参考的同口径基准 | 离线 |
| `spot_check.py` | 05 | 人工观感抽查表：每部开头／中段最密处／结尾各 2 分钟，列产品中文、ASR 日文与参考日文 | 离线 |
| `vad_sweep.py` | 11 | Pyannote 重叠平均分数每部缓存一次（`scores`，GPU）；离线扫 onset／offset／min duration／两端 pad 并以参考字幕时间轴筛选（`screen`）；选中参数物化成产品 `vad.json` 与 asr／align jobs 文件（`materialize`），整片后汇总 CER 与重建 cue（`report`） | `scores` GPU 约 16 s／部；其余离线 |
| `asr_round2.py` | 12 | ASR 候选在产品当前 VAD 窗口上逐窗独立转写（Qwen3-ASR 系复用产品 `QwenAsr`；Transformers Whisper 系 FP16 greedy），写产品形状 `asr.json` 与对齐 jobs，交给产品对齐 worker 与 `kototoki_eval` | GPU；模型需先按 ready manifest 供给 |
| `consistency.py` | 04 | 跨批一致性指标：同一作品内人名／专名的中文译法一致率（v4 run 或成对 SRT）；`precision` 子命令抽样送 Opus 核对精确率 | 离线（`precision` 消耗少量 Claude 配额） |
| `mbr_cheap.py` | 07 | 从 v4 `mbr8` 的 8 样本 run 离线派生逐条 MBR 的 N＝4、6（`derive`，带真实配方 hash）；按样本共识度模拟早停并写伪 run（`early-stop`）；统一口径的 N／早停成本表（`cost`） | 离线 |
| `parallel_probe.py` | 07 | 运行时把 llama-server 改为 `-np P`、同批样本并发请求，再调用 v4 `generate`；比较串行与并行的墙钟与输出 | GPU |
| `confirm_set.py` | 07 | 按 v4 `build_sets` 规则建 v5 剧集确认集：只取 v2／v3 与 v4 dev／confirm 都没碰过的整集（电影已无余量）；写入评测根 `sets/confirm` | 离线 |
| `confirm_series.py` | 14 | 在只含剧集的确认集上运行 v4 `confirm`：运行时让 `overall` 取有值类别的均值（v4 缺一类时为 None），其余照 v4 原样 | 离线（只运行一次） |
| `mbr_semantic.py` | 08 | 同一批 mbr8 样本，逐条 MBR 的效用换成本地 bge-m3 embedding 余弦，写伪 run（如 `mbr8s`）并统计与 chrF 选择不同的比例 | GPU（embedding，秒级） |
| `diff_judge.py` | 08 | 候选 run 只判计分 cue 与同 seed 基准 run 不同的窗口，其余窗口复制基准判分（合成包文件标 `copied_from`），之后 v4 `compare` 照常读取 | Claude 配额（退出码 75 可续跑） |
| `diversity.py` | 09 | 多样本 run 里每条 cue 的样本两两 chrF 均值与"全部样本相同"占比（样本多样性） | 离线 |
| `glossary.py` | 10 | 第一遍译文 → 每部作品人名／专名的多数票译法 → 写带 `glossary` 字段的配方（v3 `Recipe.glossary`，每批只注入上下文里出现的条目） | 离线 |
| `asr_pair_ctc_judge.py` | — | MMS CTC 声学裁判：`emit` 对 w0／x0 分歧单元与 w0 单元的音频跨度做产品 MMS 前向并缓存发射矩阵；`analyze` 逐分歧区间比较 CTC 对数似然、跨片调 λ／m 并算合并 CER，另做 w0 单路幻觉过滤的特征、AUC 与丢弃阈值（见 [研究文档](../../docs/research/2026-10-19-asr-pair-ctc-judge.md)） | `emit` GPU 约 2 分钟（持有 `.local/gpu.lock`）；`analyze` 离线约 15 s |
| `asr_pair_cross_score.py` | — | 交叉打分裁判：`score-whisper`／`score-qwen` 各加载一个产品 ASR 模型，对 MMS 实验的同一批分歧单元跨度做教师强制（Whisper `align()` 的 `text_token_probs`；Qwen 单次前向 log_softmax），给 w0 文本与只替换一个区间的假设打分；`analyze` 组合 d_W／d_Q／缓存的 MMS d_M，跨片调参、算准确率、AUC、自偏好与合并 CER（见 [研究文档](../../docs/research/2026-10-19-asr-pair-cross-score.md)） | `score-*` GPU（持有 `.local/gpu.lock`，一次一个模型）；`analyze` 离线 |
| `coresidency_probe.py` | cross T0 | 同一进程常驻产品 `WhisperAsr` 与 `QwenAsr`，HF II／III 逐文件按 Whisper 转写 → Qwen 转写 → Whisper 对分歧区间打分（d > −1 取 x0）跑全部 VAD 窗口；0.5 s `nvidia-smi` 按阶段采样整卡显存并记 torch 峰值，按"峰值＋1 GB ≤ 13.5 GB"判定共驻或三段式回退（见 [验收记录](../../docs/research/acceptance/2026-10-19-cross-coresidency-probe.md)） | GPU 约 25 分钟（持有 `.local/gpu.lock`） |

从仓库根目录运行：`.venv/Scripts/python.exe -X utf8 -m experiments.quality_v5.<模块> ...`（各模块文件头有命令示例）。

## 验证

`.venv/Scripts/python.exe -X utf8 -m unittest discover -s experiments/quality_v5 -t . -p 'test_*.py'`（离线，无 GPU／模型／网络）。
