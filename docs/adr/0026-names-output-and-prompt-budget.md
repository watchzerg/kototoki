# ADR-0026：产品建表放宽输出上限与提示预算（`q3-names-v2`）

状态：已接受（2026-11-12，用户决定，依据[产品全流程验收](../research/acceptance/2026-11-12-product-fullflow-acceptance.md)的观察 1）、已实现（同日）。替代 [ADR-0022](0022-product-names-on-strata.md) 第 1 点中"`max_tokens` 8192、context 24576（提示预算 15872）"与"请求体与 v13 逐字节一致"中的 `max_tokens` 一项，以及第 2 点配方名 `q3-names-v1` 与"相同：…`max_tokens` 8192、context 24576 与预算 15872"。[ADR-0021](0021-q3-strata-names-baseline.md) 的基线 Q3（`names-strata-v4`）身份不变。  
范围：产品包 `kototoki/names/` 的三个常量与配方名。不改提示、schema、采样、归一规则、尝试次数、seed 序列、请求形状与 Strata 启动方式。

## 决定

1. **输出上限 `max_tokens` 8192 → 16384。**
2. **提示预算 15872 → 32256。** 计算用的上下文 `CONTEXT_SIZE` 24576 → 49152；预算仍是 context − `max_tokens` − 512。`CONTEXT_SIZE` 只用于算预算、不随请求发出；Strata 实际上下文是 131072（ADR-0017 的接入检查核对）。
3. **新配方 `q3-names-v2`**，`BUILD_RECIPE_HASH` `2dbd324e5ee847d0a0171840d4a064cd6b45a3df4c2123b7075cfe1a38b379ba`（`q3-names-v1` 为 `d3317926ee3b3096277faa9a5fbc0879d562336fb1fe89bf0ebd04c5b0be6b17`）。与 `names-strata-v4`（`38cb7bcd…`）相比，建表块只差这三项；把它们换回 8192／24576／15872 后拼回 v4 的形状，hash 仍等于 `38cb7bcd…`（`tests/core/test_names_recipes.py`、`tests/equivalence/test_names.py`）。请求体只有 `max_tokens` 不同，其余与 v13 逐字节相同。
4. **旧表失效重建。** 配方变即表身份变，已有 `name-table.json` 下次运行时重建；注入行变了则翻译身份变，已发布字幕仍须删掉 `.ja-zh.srt` 才重译。不迁移旧产物。

研究侧 `experiments/scene_batching_v6/v13.py` 原从产品读 `PROMPT_BUDGET`，改为钉住自己的 `S1_PROMPT_BUDGET = 15872`（机械改动，S1 各变体的 hash 不变；ADR-0025 允许研究侧导入行随产品符号机械改）。v13 调用的产品 `build_table` 预检从此按 32256 判，只影响超过 15872 的提示，v13 的输入里没有。

## 依据

- **输入侧贴边**：两部 HF 的提示 13240、14535 token，占旧预算 83%、92%。按两点粗估（约 1.1K 固定＋每条 cue 约 11 token），超过约 1340 条 cue 就会 `too_long` 写空表，换 seed 无用；对白密的电影可能超。新预算约可容纳 2800 条 cue。
- **输出侧截断**：2026-11-12 验收中 HF III 第 1、2 次建表都在 8192 处截断（已列出 49、63 个不同实体，不是同一串的循环），第 3 次成功（4931 token、37 个实体）；11-09 HF II 成功的一次用了 7766 token。
- **为什么不用满 128K**：v13 只验证过 1.3–1.5 万 token 的提示；更长输入下的表质量没有证据。超出新预算仍按既有规则写空表、照常翻译。
- **只救失败、不改成功**：同 seed 下，原本在 8192 内结束的回复不受输出上限影响。

## 已知风险

v13 把写满 8192 token 的回复归为"生成失控"（正常回复最长 6356 token，失控回复约 2 万字符不收尾，server log 的重复截停为 0），见[第十三轮](../research/2026-11-08-names-on-strata-v13.md) §7。若是失控而非"表确实长"，16384 只会让一次失败尝试从约 50 s 拖到约 105 s，最坏 5 次约 9 分钟。`maxItems: 80` 既不约束解码（不发 `response_format`），解析时也不校验条目数。

## 验证

实现后的验证记在[产品全流程验收](../research/acceptance/2026-11-12-product-fullflow-acceptance.md)的"ADR-0026 验证与内嵌字幕补漏"一节：

- 提示预算：Black Panther（内嵌字幕 1655 条）提示 20059 token，旧预算下会写空表，新预算下第 2 次建成（46 条，5150 token）。
- 输出上限：HF III 前两次在 16384 处仍截断，属无限罗列（第 1 次 135 个实体、`low` 73 个）；第 4 次 11047 token 成功（8192 下会截断），建表 364 s（此前 129 s）。放宽输出上限的收益有限、失败成本翻倍；用户 2026-11-12 看过结果后裁定保留 16384。

## 未验证

- 表质量（与参考的一致率）、注入后的翻译质量：本次只看建表是否成功、用了多少 token。
- 超过 2 万 token 提示的建表质量；超过 16384 的输出是否还会出现。
