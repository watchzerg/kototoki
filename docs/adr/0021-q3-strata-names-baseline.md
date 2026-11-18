# ADR-0021：翻译基线 Q3（Q2 规则，专名表改由 Strata Flash-Next 建，最多 5 次尝试）

状态：已接受（2026-11-09，用户决定）。替代 [ADR-0017](0017-q2-strata-default-launch-baseline.md) 第 1 点（当前基线为 Q2）、[ADR-0018](0018-q2-sole-translation-baseline.md) 第 1 点（唯一基线为 Q2）；ADR-0018 第 2、4 点的规则改为针对 Q3。[ADR-0014](0014-name-consistency-in-product.md) 第 10 点中"Q 线用产品 `names` 建表注入"对基线不再成立：Q3 的表由 Strata 建。产品已于 2026-11-09 按 [ADR-0022](0022-product-names-on-strata.md) 切换：在与翻译共用的 Strata session 上按同一规则建表。正文"产品 `BUILD_RECIPE_HASH`（`5b8d1b76…`）不变"自 2026-11-09 [ADR-0022](0022-product-names-on-strata.md) 起不成立：产品建表配方改为 `q3-names-v1`，其 hash 由 `tests/core/test_names_recipes.py` 钉住（2026-11-11 标注，用户委托 agent 裁定）。  
范围：研究与测试用哪条翻译基线、它的表怎么建。不改产品 `kototoki/`（产品仍是 `q2-degrade-v1`＋27B 建表，ADR-0014、ADR-0019），不决定产品何时切换，不开封确认集。

## 决定

1. 翻译只保留**一条基线：Q3**。以后新的翻译测试都以 Q3 为对照；引用 Q2、Q1、Q0、F1 或 H0 作对照时须写明，并说明理由。Q2 保留为前任身份。
2. **Q3＝Q2 的翻译规则不变，只换注入表的来源**：表由 Strata 上的 Qwen3.8-Flash-Next 建（建表配方 `names-strata-v4`），不再用 Qwen3.8-27B＋llama-server。建表和翻译用同一个 Strata 实例，同一 session 里先建表、再翻译。
3. **建表失败后最多重试到第 5 次请求**：请求依次用 seed、seed＋1、…、seed＋4，取第一张合格的表就停，不在多张表里挑选。这是失败后的可靠性重试，不是"多次生成再挑选"，[ADR-0008](0008-no-multi-translation-selection.md) 继续适用。
4. 用户采纳时已知并接受下面"依据"中列出的风险：dev 剧集的 wrong-referent 显著变差、两次建表差别大。

## 身份

**建表配方 `names-strata-v4`**（`archive/2026-11-18-pre-research-restructure:experiments/scene_batching_v6/v13.py` 的 `s1_recipe("v4")`），hash `38cb7bcda96534db70fb5823c05330cd212057058c381e88cadf756f26d308d0`：

- 以产品 `BUILD`（`kototoki/names/recipes.py`）为底，以下几项不变：提示 `build-table-prompt-v5`、schema `name-table-v2`、no-think；采样 temperature 0.7／top_p 0.8／top_k 20／min_p 0／presence_penalty 1.5；程序兜底；`[names] seed` 20261019；整片 `ja.srt` 一次送入。
- 改动：
  - 去掉 llama.cpp 的模型资产；
  - `max_tokens` 8192，context 24576，提示预算仍为 15872；
  - 最多 5 次请求（`attempts: 5`），规则见决定第 3 点。
- 请求形状：
  - 模型为 `qwen3.8-flash-next-iq3_s`；
  - 不发 `response_format`；
  - 显式带 `chat_template_kwargs.enable_thinking: false`；
  - 提示预算用 `/v1/messages/count_tokens` 把 system 与 user 两段分别计数再相加。
- 运行时身份进 hash：Strata 0.2.12、引擎 build 0.1.58、默认启动（`strata.DEFAULT_RESOLVED`）、KV `int8`。
- 建表入口是产品的 `kototoki.names.table.build_table`（导入、不改），`chat`／`tokenize` 两个回调接到 Strata（`v13.NamesClient`）。产品 `BUILD_RECIPE_HASH`（`5b8d1b76…`）不变。

**翻译**：与 Q2 完全相同，只是注入的表换了。规则见 [ADR-0017](0017-q2-strata-default-launch-baseline.md)：
- `qwen-wide`；
- 只注入 `confidence: high` 实体的全部写法，`filter: window`，表头 `qwen-name-table-v1`；
- `strata_recipe_data(..., launch="default")`；
- 不用 grammar，每包两次尝试。

任意一张 `name-table` 都能用 `v13.write_q2` 组出 Q3 的翻译配方，ADR-0017 列出的"给定表 → 写出 Q1／Q2 配方"缺口由此补上。v13 输入上的实例（配方名 `q2-names-s1`）：dev 15 部 `eeba5a711e83547a2969b3132dda7bbe04e46a35b74a810f578100671812fe57`；产品 HF II／III `29fd7a6633dd59843af98e4a15f9d02739201d52a2bf541a2b565b255d763eda`。两份配方都在 `.local/names-on-strata-v13/` 下：dev 的在 `recipes/`，产品的在 `E/root/recipes/`。表在 `B4/`。

**运行顺序**：
1. 核对没有 llama-server、没有别的 Strata launch 或 GPU 作业，可用内存 ≥52 GiB。
2. `strata launch --no-tui --model iq3_s`，按 ADR-0017／ADR-0019 做接入检查，确认专家区全部锁进内存。
3. 建表。
4. 翻译。
5. `strata launch --stop`，核实显存已释放。

全程不启动 llama-server，也不加载 27B。v13 的入口是 `python -m experiments.scene_batching_v6 v13-build`（建表）和 `v13-dev`／`v13-product`（翻译）。它们自己启停 Strata，但只覆盖 v13 的固定输入。

## 依据

证据来自[第十三轮（v13）](../../research/2026-11-strata-v12-v13/README.md)。下面的 Δ＝Q3−Q2，越小越好，括号内为 CI90。两臂翻译规则相同，都在本轮新生成，只差注入的表。

- **可行性**：17 部全部建成，最多用到第 3 次请求，JSON 语法错误 0；失败的 6／25 个请求都是写满 8192 token 的失控。首次请求失败 4／17，不过立项时的"≤2／17"，用户放宽为"5 次内全部建成"。思考全部关闭。
- **表质量（dev 15 部，与参考中文比）**：非劣，未达改善。
  - 出现加权一致率 0.706 对 0.652，Δ +0.054 [−0.032, +0.132]；
  - high 不一致率 Δ −0.046 [−0.121, +0.033]；
  - 条目 331 对 201；
  - 真串名 3 组对 1 组。
- **dev 翻译（3 seed）**：
  - 电影：accuracy −0.049 [−0.085, −0.014]，wrong-referent −0.043 [−0.065, −0.020]，四部都变好。
  - 剧集：wrong-referent **+0.042 [+0.021, +0.067]**，accuracy +0.021 [−0.006, +0.051]，按 v13 §4.4 不过非劣门。变差集中在两部：W08 +0.195（表把同一人物拆成两条），W11 +0.090（表里有一组真串名）。
  - 人名相关错误 64 对 78，不一致率 0.012 对 0.018。
- **产品 ASR 源（HF II／III，seed 20261054–56）**：
  - 全体 −0.095 [−0.159, −0.031]，light 桶 −0.267 [−0.412, −0.116]；
  - 人名错误 65 对 78，不一致率 0.023 对 0.042；
  - 交付失败：Q3 为 0，Q2 为 6 个 cue。
- **代价**：
  - 建表：dev 15 部合计 544 s，27B 为 468 s。一次成功的请求中位 18 s，每次失控约 25–50 s。
  - 翻译墙钟两臂相同。
  - 资源：显存峰值 16.0 GB，整机内存峰值 60.4–62.4 GiB（共 63.9）。
  - 不再需要 llama-server、27B 权重，也省掉两种服务之间的交接。

## 约束与未关闭项

- **dev 剧集风险已知**：表出错（拆条、串名）的作品，wrong-referent 会显著变差。能否在注入前用程序规则拦下这类条目，还没有研究（v13 §8 第 10 项 (b)）。
- **两次建表差别大**：Strata 同 seed 不复现。同一部片建两次，日文写法集合的 Jaccard 只有 0.56／0.48。产品 ASR 源的结果只来自一次建表，没有在另一次建表上复现。基线的表按身份缓存，建一次就固定，但不同时间、不同机器建出的表不保证相同。
- **单次请求不稳定**：约 1／4 的建表请求会失控。连续 5 次都失控的情形在 v13 里没有出现。那时规则与产品 `build_table` 相同：写空表，翻译照常进行、不注入。按独立事件估算概率约千分之一，但失控可能集中在难的作品上，实际可能更高。
- **产品与基线不一致**：产品仍用 27B＋llama-server 建表（ADR-0014、ADR-0019），注入规则同 Q2。要把产品切到 Q3，须另写 ADR 并改 `kototoki/`，至少包括：
  - names 阶段改走 Strata、复用翻译的 Strata session；
  - 建表 5 次尝试；
  - 删除 llama.cpp 与 27B 资产。
- **新输入的建表没有通用入口**：`v13-build` 只覆盖 v13 的固定输入。给一份新的 SRT 用 Q3 建表，还要补一个小入口（读 `ja.srt` → `build_one` → `name-table.json`），再接 `write_q2`。
- [ADR-0008](0008-no-multi-translation-selection.md) 继续适用。v3、v4、v5 的确认集已开封，新的确认仍须用全新隔离的集合。
