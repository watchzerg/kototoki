# 字幕质量探索第五轮（quality_v5）

[v5 研究文档](../../docs/research/2026-10-16-quality-exploration-v5.md)各步骤的运行辅助与离线分析脚本。方案、判定纪律与结论都在研究文档；执行票据在 `.scratch/quality-exploration-v5/`（Git 忽略）。产物写 `.local/quality-exploration-v5/<票据编号>/`。

本包只导入 v3／v4 与 `kototoki_eval` 的函数，不修改它们；不改 `kototoki/` 产品代码。

| 模块 | 票据 | 作用 | 资源 |
| --- | --- | --- | --- |
| `telemetry_run.py` | 01 | 运行一条命令（如 `python -m kototoki`），旁路 0.5 s 采样整卡显存，按产品日志切阶段，写 `driver-result.json` | 随被测命令 |
| `asr_source.py` | 02 | 参考源与 ASR 源翻译按时间对齐成单元、按日文 CER 分桶；成对盲评 profile `v5-asr-pairwise-v1` 与校准；分桶外推 ASR 带来的中文错误占比 | 离线；`judge` 消耗 Claude 配额（退出码 75＝配额耗尽，可续跑） |
| `readability.py` | 03 | 中文 CPS、行长、显示时长、每条行数、中日长度比的分布与超阈值占比；`v4ref` 子命令给字幕组参考的同口径基准 | 离线 |
| `spot_check.py` | 05 | 人工观感抽查表：每部开头／中段最密处／结尾各 2 分钟，列产品中文、ASR 日文与参考日文 | 离线 |
| `consistency.py` | 04 | 跨批一致性指标：同一作品内人名／专名的中文译法一致率（v4 run 或成对 SRT）；`precision` 子命令抽样送 Opus 核对精确率 | 离线（`precision` 消耗少量 Claude 配额） |

从仓库根目录运行：`.venv/Scripts/python.exe -X utf8 -m experiments.quality_v5.<模块> ...`（各模块文件头有命令示例）。

## 验证

`.venv/Scripts/python.exe -X utf8 -m unittest discover -s experiments/quality_v5 -t . -p 'test_*.py'`（离线，无 GPU／模型／网络）。
