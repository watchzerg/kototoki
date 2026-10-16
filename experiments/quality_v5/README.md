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
| `mbr_semantic.py` | 08 | 同一批 mbr8 样本，逐条 MBR 的效用换成本地 bge-m3 embedding 余弦，写伪 run（如 `mbr8s`）并统计与 chrF 选择不同的比例 | GPU（embedding，秒级） |
| `diff_judge.py` | 08 | 候选 run 只判计分 cue 与同 seed 基准 run 不同的窗口，其余窗口复制基准判分（合成包文件标 `copied_from`），之后 v4 `compare` 照常读取 | Claude 配额（退出码 75 可续跑） |
| `diversity.py` | 09 | 多样本 run 里每条 cue 的样本两两 chrF 均值与"全部样本相同"占比（样本多样性） | 离线 |

从仓库根目录运行：`.venv/Scripts/python.exe -X utf8 -m experiments.quality_v5.<模块> ...`（各模块文件头有命令示例）。

## 验证

`.venv/Scripts/python.exe -X utf8 -m unittest discover -s experiments/quality_v5 -t . -p 'test_*.py'`（离线，无 GPU／模型／网络）。
