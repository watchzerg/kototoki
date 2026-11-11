# 09 D 离线：ASR 源单元与分桶复用、D1／D2 提示与注入实现

Status: resolved
Type: 离线
Stage: D
Blocked by: 01（A 期间先做，阶段内依赖不跳门：D 的 GPU 票据仍排在 C 之后）

范围、终点与门见研究文档 §4／§5（docs/research/2026-10-21-q0-exploration-v10.md）。

## 执行记录

## Answer

完成（离线）。`experiments/scene_batching_v6/asr10.py`：
- 源：quality_v5 第 01 步产品 w0 `ja.srt`（与第 02 步单元、产品专名表的 `ja_srt_sha256` 一致：HF II `f86279e2…`、HF III `9cdc7a27…`），seed 20261051–53；`translate-srt` 输出到 `D/zh/<arm>/<film>.s<seed>.zh.srt`。
- 评测：直接复用第 02 步的 `units/*.jsonl`（exact 811、light 510、heavy 407、missed 92、inserted 70）与 `asr_source.judge`／`collect`（profile `v5-asr-pairwise-v1` 不改）；x＝对照臂、y＝候选臂，同一条目两侧同 seed，seed 随抽样序号轮换；每个桶的抽样只由桶决定，所以各比较判的是同一批单元（跨比较可配对），A/B 侧每次比较另抽。
- **偏离：不判 missed 桶**。v5 的 missed 是"ASR 无字"，v5 比的是参考源 vs ASR 源；本轮两侧都从 ASR 源翻译，missed 单元两侧都为空，判了只是平局。D0 配额 exact 60、light 80、heavy 80（同 v5）。v5 第 02 步 396 条只花 $2.16，D1／D2 的主终点在 light／heavy 桶，届时可改为普查以收窄区间（票据 11／12 记录）。
- D2 注入表：产品 `name-table.json` 全部 form 平铺为 `{日文写法 → 中文}`（HF II 35、HF III 28 条）；注入按窗口命中过滤（与 v5 `glossary` 先例相同，表里还有 `シンジ → 士郎` 这种表本身的错误，整表注入会把它推给每个包）。
- 产品时间轴（v9 §8 第 6 项，`D/product-timing.json`）：两部各 149／147 包，平均目标 7.4／8.3 条；dp10-cut 平均可见邻文前 0.37–0.41、后 0.05 条（静默门控几乎关掉了邻文），qwen-wide 前 19.5–19.7、后 5.0 条，可见约 32–33 条。
- 测试：`test_v10` 新增 2 项（抽样固定、bootstrap 与人名错误规则），共 9 项通过。
