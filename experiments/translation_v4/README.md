# Hy30 字幕流程第四轮探索（translation_v4）

实现[v4 计划](../../docs/plans/hy-mt2-translation-flow-exploration-v4.md)：先提高量尺精度（新开发集、新封存确认集、冻结判定规则），再探索采样、多候选选择、译文上下文。对照 `b10-joint`（ADR-0006）。执行状态以 [v4 台账](../../docs/context/2026-10-11-hy30-flow-exploration-v4.md) 和 `status` 命令为准。

与 v3 的关系：本包**导入** `experiments.translation_v3` 的生成、裁判、统计函数。为 v4 需要，v3 包做了向后兼容的扩展：
- `recipes.Recipe` 新增 `sampling`（覆盖 temperature／top_p／top_k／min_p／samplers）、`target_context`（注入本场景前 K 条自己的译文，日+中，只读）、`candidates` + `selector`（每批 N 个样本，本地 chrF-MBR 选择，`mbr.py`）。这些字段取默认值时不进入 `spec()`，v3 全部配方 hash 不变（`test_v4.RecipeFieldsTest` 用 v3 run 记录的 hash 固定）。
- `judge.CliBackend` 可传入别的系统提示和 schema（默认仍是裁判 profile），供参考复核复用 CLI 执行面。

v2 冻结代码、translation_judge／translation_eval 链不导入也不修改。

## 命令

从仓库根目录运行 `uv run --locked --offline python -X utf8 -m experiments.translation_v4 <命令>`。默认根目录 `.local/translation-evaluation/hy30-flow-v4/`。

| 命令 | 作用 | 资源 |
| --- | --- | --- |
| `status` | 只读：集合与参考复核进度、policy／锁定状态、GPU 锁、队列、各 run 生成与裁判进度、建议下一步。**接跑先运行它** | 离线 |
| `review --set dev\|confirm [--parallel K]` | 每场景一次 `claude -p`（Opus），复核字幕组中文为参考并标置信度；只复核缺失场景；confirm 不打印内容 | **Claude 配额**；退出码 75 = 阻塞 |
| `freeze-reference --set S` | 合并复核结果为 `evaluation-only/S/reference/cues.jsonl` + `freeze.json` | 离线 |
| `queue add --recipe R [--set dev] [--replicate]`／`queue list` | 加生成任务（默认该集合的 3 个 seed） | 离线 |
| `run-queue`、`generate --recipe R --seed S --set dev` | 生成；dev 的每个 seed 只跑它所在场景块；confirm 需要 `locked-candidates.json` | **GPU** |
| `judge --run RUN [--half A B]` | 盲评（profile `claude-opus-5-5-mqm-v1` 不变）；只评缺失包 | **Claude 配额** |
| `compare --candidate R [--half A] [--set dev] [--candidate-replicate] [--control-replicate]` | 配对统计与判定，写 `summaries/`。policy 冻结前只允许 `--calibration`（对照重复 seed 或 c0）。两个 `--*-replicate` 用 dev 重复 seed 做锁定前复现；两者同时使用时，候选和对照都与筛选用的 run 无关 | 离线 |
| `calibrate reference\|synthetic\|repeat\|aa\|bridge\|power [--judge]` | 校准（只用对照和 c0）；`power` 根据 A/A 和 bridge 计算 MDE 表 | 离线（`--judge` 时消耗 Claude 配额） |
| `confirm` | 对 `locked-candidates.json` 中的 Holm 家族在 confirm 集做单侧检验并做 Holm 校正，写 `summaries/confirm-holm.json`；只输出聚合结果。**只运行一次** | 离线 |

集合由 `build_sets.py` 构建（一次性，内容不同则拒绝覆盖），盘点在 `inventory.py`，v3 数据的回溯方差分解在 `retro.py`，校准在 `calibrate.py`，MDE 在 `power.py`。判定规则由 `python -m experiments.translation_v4.freeze_policy <root>` 写入，只写一次，已存在时拒绝覆盖。多候选 run 的选择变体（N、选择器）用 `derive.py` 离线派生：派生 run 带有对应真实配方的 hash，锁定后可在 confirm 集上真实生成。

## 量尺设计（R1 回溯分析的结论）

- 每条 cue 都评分；裁判窗口按场景连续切成 5 条一组，每侧 8 条日文上下文；包内 4 窗，与 v3 相同。
- dev：每个场景只用 1 个 seed，3 个 seed 分到作品内平衡的 3 个场景块；分 A／B 两半，两阶段筛选。confirm：每个场景跑全部 3 个 seed。
- 统计：每条 cue 的 accuracy 惩罚（minor 1／major 5／critical 10）；作品内按 cue 平均，类别内作品等权，剧集与电影各 50%；不可交付场景的 cue 记 10 分、major+、critical。区间用作品内分层、按 5 条窗口重抽的 bootstrap（R1：配对 Δ 的 cue 级 ICC 约为 0；半集里每部作品只有 1–2 个场景，此时按场景重抽会退化），同时报告按场景重抽的 SE 作对照。v3 的作品簇 bootstrap 在每类只有 3–6 簇时，会把 SE 低估约 2.5 倍。
- 判定规则见冻结的 `decision-policy-v4.json`。

## 验证

`uv run --locked --offline python -m unittest experiments.translation_v4.test_v4 experiments.translation_v4.test_stats4 -v`（离线，无 GPU／模型／网络），以及 v3 全套 `unittest discover -s experiments/translation_v3`。
