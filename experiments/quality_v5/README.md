# 字幕质量探索第五轮（quality_v5）

[v5 研究文档](../../docs/research/2026-10-16-quality-exploration-v5.md)各步骤的运行辅助与离线分析脚本。方案、判定纪律与结论都在研究文档；执行票据在 `.scratch/quality-exploration-v5/`（Git 忽略）。产物写 `.local/quality-exploration-v5/<票据编号>/`。

本包只导入 v3／v4 与 `kototoki_eval` 的函数，不修改它们；不改 `kototoki/` 产品代码。

| 模块 | 票据 | 作用 | 资源 |
| --- | --- | --- | --- |
| `telemetry_run.py` | 01 | 运行一条命令（如 `python -m kototoki`），旁路 0.5 s 采样整卡显存，按产品日志切阶段，写 `driver-result.json` | 随被测命令 |

从仓库根目录运行：`.venv/Scripts/python.exe -X utf8 -m experiments.quality_v5.<模块> ...`（各模块文件头有命令示例）。

## 验证

`.venv/Scripts/python.exe -X utf8 -m unittest discover -s experiments/quality_v5 -t . -p 'test_*.py'`（离线，无 GPU／模型／网络）。
