# ADR-0015：翻译分为两条基线——H0（Hy-MT2）与 Q0（Qwen 通用模型）

状态：已接受（2026-10-21）。  
日期：2026-10-21。  
关系：**不替代任何 ADR。** H0 就是 [ADR-0005](0005-apex-i-compact-translation-baseline.md)（模型与采样）＋[ADR-0010](0010-dp10-cut-translation-flow-baseline.md)（研究侧流程 `dp10-cut`）＋[ADR-0011](0011-dp10-cut-product-recipe.md)（产品配方 `dp10-cut-degrade-v1`）的合称，三者内容不变。Q0 是新增的并行基线，来自[第九轮（v9）](../research/2026-10-21-general-model-translation-v9.md)的 `qwen-wide`。[ADR-0008](0008-no-multi-translation-selection.md)（不自动选用"翻译多次再挑选"）对两条线同样适用。  
范围：只给两条翻译基线命名并固定身份，供后续测试选对照。不改产品 `kototoki/`，不做 L3，也不决定产品是否改用 Qwen。

## 决定

用户 2026-10-21 读完 v9 结论后裁定：翻译从此有两条基线，后续探索各自以其中一条为对照。

| 名称 | 一句话 | 模型 | 研究侧配方 | 产品 |
| --- | --- | --- | --- | --- |
| **H0** | 专用翻译模型线 | Hy-MT2 30B-A3B APEX-I-Compact（compat 引擎 b11429），采样 `official30b-cached-v1` | `translation_v3` 内置 `dp10-cut` | 已在产品：`dp10-cut-degrade-v1` |
| **Q0** | 通用模型线 | Qwen3.8-27B UD-IQ3_S（官方 llama.cpp b11669，与产品 `names` 阶段同一模型与 server 参数），采样 0.7／0.8／20／0、`presence_penalty` 0、non-thinking | `translation_v3` 内置 `qwen-wide` | 未进产品 |

命名仿照 STT 的 W0／X0：字母取模型线（H = Hy-MT2，Q = Qwen），0 表示第一版。配方变化时出新配方与新 hash，名称后缀递增（H1、Q1…）须由用户裁定，不自动升级。

## 身份与入口

**H0**

- 研究侧：`experiments/translation_v3` 的 `dp10-cut`，recipe_hash `ee72ce6683c89e5a1f83fd7ba99f54f3683966deed0e526c193780ad8c500b70`。切包、邻文与提示见 ADR-0010。
- 产品：`kototoki/translate/recipes.py` 的 `DP10_CUT_DEGRADE_V1`，hash `086754ca751365c21840742511bf39eaa621b8fc2f5a630372f22661fc86158e`。与研究侧逐字节同请求，只有终态失败改为拆批降级（ADR-0011）。
- 入口：整片 `just translation-srt --srt <ja.srt> --seed <S> --out <chn.srt>`；产品 `python -m kototoki`；dev 对照 `python -m experiments.scene_batching_v6 --round v9 generate --recipe dp10-cut --seed <S>`。

**Q0**

- 配方：`experiments/translation_v3` 的 `qwen-wide`，recipe_hash `719237b92c45c4d0f19971ece6b0944157c23ad2e33bbfe0644db60aabfcaef7`，由 `test_qwen.QwenRecipeTest` 固定。
- 内容：
  - 切包与 H0 的 `dp10-cut` 完全相同，目标 ID 序列逐字一致。
  - 只读邻文换成 `wide-context-v1`：前 20 条、后 5 条，只在场景边界截断，不看静默，可见上限 35。
  - 提示 `qwen-joint-v1`：Hy joint 提示的文字原样拆成 system 与 user 两条 chat 消息。
  - 输出约束与 H0 相同，ID GBNF 作为 `/v1/chat/completions` 的 `grammar` 字段传入。
  - context 16384，输入预算 context − 4096 − 64；两次尝试，第二次 seed＋1。
- 实现：`experiments/translation_v3/qwen.py`。server 生命周期用产品的 `kototoki.llama_server.ManagedServer`，参数从 `kototoki/names/recipes.py` 抄成常量，所以产品改 names 参数不会移动 Q0 的 hash。
- 入口：dev `python -m experiments.scene_batching_v6 --round v9 generate --recipe qwen-wide --seed <S>`，运行文件在 `.local/general-model-translation-v9/`。
- **已知缺口**：`translation_v3 translate-srt`（即 `just translation-srt`）目前总是启动 Hy-MT2 server，**不能跑 Q0**。用 Q0 翻整片 SRT 前，须先让它按 `recipe.model` 选择 `qwen.session_factory`，并补测试。

## 证据（如实记录）

均出自 v9，裁判 profile `claude-opus-5-5-mqm-v1`。数字是每条 cue 的 MQM 惩罚差（Q0 − H0），括号内为 CI90。

- v4 dev 三 seed 合并（44 场景、5397 cue）：accuracy 剧集 −0.058［−0.104, −0.010］、电影 −0.091［−0.152, −0.028］，两类都显著更好。
- 反方向：unnatural（翻译腔）显著变差；墙钟约 3.3 倍，生成 60 tok/s，H0 为 194 tok/s。
- 无邻文泄漏，无交付失败；显存峰值约 13.2 GB，H0 约 15.9 GB。
- **证据只到 dev 筛选**：没有重复 seed 复现，没有隔离确认集，也没有非 LLM 的独立比较。Q0 的优势是筛选级证据，不是确认级证据。
- 产品时间轴没有复算：dev 是字幕组时间轴。

## 后果

- 新的翻译测试要写明对照是 H0 还是 Q0，也可以两个都用。数字只在同一裁判 profile、同一数据集、同一 seed 块之间比较，不与 Codex 时代的 `sol-high-auto-v1` 分数混用。
- 以 Q0 为对照时，两臂的批次目标 ID 序列必须逐字相同；Q0 的切包就是 H0 的切包，可以直接复用 `check-batches`。
- 产品继续用 H0。产品是否改用 Q0、是否与 `names` 共用一个 server、L3 是否进行，都另行裁定，见 v9 §8。
- v3、v4、v5 的确认集已开封，新的确认仍须用全新隔离的集合。
