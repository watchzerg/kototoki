# ADR-0016：Q 线基线改为 Q1（Q0＋只注入 high 的专名表）

状态：已接受（2026-11-08）；"Q 线当前基线是 Q1"一点同日起由 [ADR-0017：Q2](0017-q2-strata-default-launch-baseline.md) 替代，Q1 的身份定义不变（Q2 沿用）。  
日期：2026-11-08。  
部分替代：[ADR-0015](0015-two-translation-baselines.md) 中"Q 线当前基线是 Q0"这一点。ADR-0015 的 H0 部分、Q0 的身份定义（`qwen-wide`，hash `719237b9…`）以及"新测试须写明对照"的规则**全部保持不变**；Q0 保留为可引用的历史身份。[ADR-0008](0008-no-multi-translation-selection.md) 对 Q1 同样适用。  
范围：只给 Q 线换基线并固定 Q1 的身份。不改产品 `kototoki/`（产品继续用 H0），不决定产品是否改用 Q 线，不开封确认集。

## 决定

用户 2026-11-08 读完[第十一轮（v11）](../research/2026-10-22-q0-product-route-v11.md)结论后裁定，采用 §8 第 1 项选项 (a) 的变体：

- Q 线的当前基线从 Q0 改为 **Q1＝Q0＋N\***，N\* 指专名表注入，只注入 `confidence: high` 的条目。
- **不按输入来源区分**：产品 ASR 源和 dev 干净源一律用同一条规则，保持简单。v11 候选清单写的适用范围是"仅产品 ASR 源"，这一限定不采纳。
- 以后新的 Q 线测试默认以 Q1 为对照；要对比旧结果时也可以用 Q0，但须写明。

## 身份

Q1 不是一个固定 hash，而是**一条组配方的规则**：对每个输入，先按产品 `names` 阶段建表，再按下面的规则拼出该输入的 Q1 配方。表的内容会进 `recipe_hash`，所以不同输入的 Q1 hash 不同。

- **基础配方**：Q0，即 `experiments/translation_v3` 内置的 `qwen-wide`，切包、邻文、提示与采样都不变（见 ADR-0015）。
- **建表**：产品 `kototoki/names` 的建表（[ADR-0014](0014-name-consistency-in-product.md)），提示 `build-table-prompt-v5`，当前 `BUILD_RECIPE_HASH` 为 `5b8d1b76da757bb26aa3d3fb894c1963935a308b6ef4eb7c75edeaa2d44c9e50`，与产品是同一模型、同一参数。建表的输入就是待翻译的那份日语。
- **注入**：`qwen_options.names = {"filter": "window", "tables": {work_id: rows}}`，表头用 `qwen-name-table-v1`。`rows` 的取法如下：
  - 只取表里 `confidence: high` 的实体；
  - 每个实体的每个 `forms[]` 都取一行 `{source: form.ja, translation: form.zh}`；
  - 按 `ja` 去重，跳过 `ja` 或 `zh` 为空的写法。
  - 这套取法就是 `experiments/scene_batching_v6/names11.py` 里的 `product_tables("high")` 和 `nstar_tables("high")`。
- **没有事后替换**：Q1 的译文直接作为结果，不再跑 `names` 替换。v10 已测过，注入后再替换与只注入的输出逐字节相同。
- **v11 用过的实例**：产品 HF II／III 上是 `q0-names-high`，hash `c10e143a65c50277daede28a2f3d3e79adc0db53b1db6a4398e0c9f6720f30e8`（`.local/q0-product-route-v11/C/root/recipes/`）；dev 15 部作品上是 `qwen-names-dev-high`，hash `9c444d3c…`（`.local/q0-product-route-v11/recipes/`），dev 表在 `.local/q0-exploration-v10/E/dev-name-tables.json`。
- **入口**：整片用 `python -m experiments.translation_v3 translate-srt --recipe <Q1 配方> --work-id <id> --seed <S> …`，Qwen 配方会自动启动 Qwen server；dev 用 `python -m experiments.scene_batching_v6 --round v11 generate --recipe qwen-names-dev-high --seed <S>`。
- **已知缺口**：给一份新的 SRT 生成 Q1 配方目前没有通用入口。现有的两个函数都把来源写死了：`product_tables` 只读 `asr10.FILMS`，`nstar_tables` 只读 v10 的 dev 表。在新输入上跑 Q1 之前，须先补一个"给定 name-table.json → 写出 Q1 配方"的小工具，并补测试。

## 证据（如实记录）

均出自 v10 与 v11，裁判 profile 不变：产品配对用 `v5-asr-pairwise-v1`，dev 用 `claude-opus-5-5-mqm-v1`。Δ＝候选 − 对照，数值越小越好，括号内为 CI90。

- **产品 ASR 源**（v11 票据 06，seed 20261054–56，HF II／III，对照 Q0＋替换）：
  - 全体 −0.050［−0.116, +0.020］，非劣；
  - 人名相关错误从 120 降到 72，差值 CI90 为［−0.036, −0.020］；
  - 不一致率 0.027 对 0.050；
  - heavy 桶 +0.005［−0.147, +0.160］，不确定；
  - 墙钟约 +4%，交付失败 0。
- **dev 干净源**（v11 票据 04，3 seed，对照 Q0，同期重判）：**护栏未过**。
  - accuracy：剧集 +0.043［+0.002, +0.085］，电影 +0.070［+0.028, +0.112］，两类都显著变差；
  - 电影 wrong-referent +0.062；
  - 人名错误 97 对 87；
  - 一致性有改善：不一致率 0.017 对 0.038。
  - 票据 02 的诊断：变差主要来自 dev 表本身的错条目，而这些错条目多数标的是 high。
- **局限**：
  - 产品证据只有两部同系列电影；
  - "只注入 high"与"整表注入"没有在同一组 seed 上直接比较过；
  - 没有确认集；
  - 同 seed、同 prompt 的 llama-server 输出约有 24% 的单元不同，所以配对比较里含一层噪声底（v11 §8 第 5 项）。

## 后果

- Q 线测试的默认对照换成 Q1。报告里写清用的是哪个输入的 Q1 实例和它的 hash；dev 上的 Q1 对照仍须同期重判。
- **用户已知并接受**：Q1 在 dev 干净源上比 Q0 差，原因是表质量。所以在 dev 上以 Q1 为对照时，对照本身的人名和指代错误偏多。Q1 的质量直接取决于产品建表质量；建表质量线是否另立项，仍按 v11 §8 第 4 项待裁定。
- 产品继续用 H0。产品是否改用 Q 线（v10、v11 §8 第 3 项）、A/A 噪声底要不要测（v11 §8 第 5 项），都仍未裁定。
- 将来如果 Q 线进入产品，Q1 链里没有替换阶段，而 H0 链仍要替换。这一差异须在那时的 ADR 里写清。
