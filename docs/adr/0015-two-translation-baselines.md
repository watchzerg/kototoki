# ADR-0015：翻译两条基线——H0 与 Q 线

状态：已接受。合并整理于 2026-11-08（并入 ADR-0016 的有效条款；历次变更见[决定索引·演进链](INDEX.md#演进链)，原文见 Git 历史）。第 1 点（两条基线）、第 4 点中"对照写明 H0 还是 Q2"、第 5 点的基线含义自 2026-11-08 起由 [ADR-0018](0018-q2-sole-translation-baseline.md) 替代：唯一基线为 Q2，H0 身份只作产品当前实现与历史对照。第 3 点的 `kototoki.llama_server.ManagedServer` 与"与产品 names 阶段同一模型与 server 参数"在 [ADR-0022](0022-product-names-on-strata.md)、[ADR-0025](0025-product-package-boundaries.md) 之后不成立（产品建表改用 Strata，该模块已拆到研究侧）；第 2 点"H0 链在发布时跑专名替换"随 [ADR-0019](0019-product-translation-q2.md) 不成立（2026-11-11 标注，用户委托 agent 裁定）。  
范围：给两条翻译基线命名并固定身份，供后续测试选对照。不决定产品是否改用 Q 线。

## 决定

1. 翻译有两条基线，后续探索各自以其中一条为对照：

   | 名称 | 一句话 | 模型与采样 | 配方 | 产品 |
   | --- | --- | --- | --- | --- |
   | **H0** | 专用翻译模型线 | Hy-MT2 30B-A3B APEX-I-Compact，采样 `official30b-cached-v1`（[ADR-0005](0005-apex-i-compact-translation-baseline.md)） | 研究侧 `dp10-cut`（[ADR-0010](0010-dp10-cut-translation-flow-baseline.md)） | 已在产品：`dp10-cut-degrade-v1` |
   | **Q 线** | 通用模型线，当前基线 **Q2** | 见 [ADR-0017](0017-q2-strata-default-launch-baseline.md) | Q0 基础配方＋专名表注入＋Strata 启动配置 | 未进产品 |

2. **H0 身份。**
   - 研究侧：`archive/2026-11-18-pre-research-restructure:experiments/translation_v3` 的 `dp10-cut`，recipe_hash `ee72ce6683c89e5a1f83fd7ba99f54f3683966deed0e526c193780ad8c500b70`。
   - 产品：`kototoki/translate/recipes.py` 的 `DP10_CUT_DEGRADE_V1`，hash `086754ca751365c21840742511bf39eaa621b8fc2f5a630372f22661fc86158e`。与研究侧逐字节同请求，只有终态失败改为 10→5→1 拆批降级，单条仍失败时保留日文。
   - 入口：整片 `just translation-srt --srt <ja.srt> --seed <S> --out <chn.srt>`；产品 `python -m kototoki`；dev 对照 `python -m experiments.scene_batching_v6 --round v9 generate --recipe dp10-cut --seed <S>`。
   - H0 链在发布时跑专名替换（[ADR-0014](0014-name-consistency-in-product.md)）。
3. **Q0 身份（Q 线的基础配方，Q1／Q2 在它之上构建）。**
   - 配方：`archive/2026-11-18-pre-research-restructure:experiments/translation_v3` 的 `qwen-wide`，recipe_hash `719237b92c45c4d0f19971ece6b0944157c23ad2e33bbfe0644db60aabfcaef7`，由 `test_qwen.QwenRecipeTest` 固定。
   - 模型：Qwen3.8-27B UD-IQ3_S（官方 llama.cpp b11669，与产品 `names` 阶段同一模型与 server 参数）；采样 temperature 0.7、top_p 0.8、top_k 20、min_p 0、`presence_penalty` 0，non-thinking。
   - 切包与 H0 的 `dp10-cut` 完全相同，目标 ID 序列逐字一致。
   - 只读邻文为 `wide-context-v1`：前 20 条、后 5 条，只在场景边界截断，不看静默，可见上限 35。
   - 提示 `qwen-joint-v1`：Hy joint 提示的文字原样拆成 system 与 user 两条 chat 消息；输出约束与 H0 相同，ID GBNF 作为 `/v1/chat/completions` 的 `grammar` 字段传入。
   - context 16384，输入预算 context − 4096 − 64；两次尝试，第二次 seed＋1。
   - 实现 `archive/2026-11-18-pre-research-restructure:experiments/translation_v3/qwen.py`，server 生命周期用 `kototoki.llama_server.ManagedServer`，参数从 `kototoki/names/recipes.py` 抄成常量，所以产品改 names 参数不会移动 Q0 的 hash。`translate-srt` 对 Qwen 配方用 `qwen.session_factory`。
   - 入口：dev `python -m experiments.scene_batching_v6 --round v9 generate --recipe qwen-wide --seed <S>`，运行文件在 `.local/general-model-translation-v9/`。
4. **测试规则。**
   - 新的翻译测试写明对照是 H0 还是 Q2，也可以两个都用；引用 Q1、Q0、F1 时也写明。
   - 两臂的批次目标 ID 序列必须逐字相同；Q 线的切包就是 H0 的切包，可以直接复用 `check-batches`。
   - 数字只在同一裁判 profile、同一数据集、同一 seed 块之间比较，不与 Codex 时代的 `sol-high-auto-v1` 分数混用。
   - 配方变化时出新配方与新 hash；名称后缀递增（H1、Q3…）须由用户裁定，不自动升级。
5. 产品继续用 H0；产品是否改用 Q 线，另行裁定。
6. [ADR-0008](0008-no-multi-translation-selection.md)（不自动选用"翻译多次再挑选"）对两条线同样适用。
7. v3、v4、v5 的确认集已开封，新的确认仍须用全新隔离的集合。

## 依据

- 命名仿照 STT 的 W0／X0：字母取模型线（H = Hy-MT2，Q = Qwen），数字表示版本。
- Q0 的证据出自[第九轮（v9）](../../research/2026-10-q-line-v9-v11/README.md)，裁判 profile `claude-opus-5-5-mqm-v1`；数字是每条 cue 的 MQM 惩罚差（Q0 − H0），括号内为 CI90：
  - v4 dev 三 seed 合并（44 场景、5397 cue）：accuracy 剧集 −0.058［−0.104, −0.010］、电影 −0.091［−0.152, −0.028］，两类都显著更好；
  - 反方向：unnatural（翻译腔）显著变差；墙钟约 3.3 倍，生成 60 tok/s，H0 为 194 tok/s；
  - 无邻文泄漏，无交付失败；显存峰值约 13.2 GB，H0 约 15.9 GB。

## 约束与未关闭项

- Q0 的证据只到 dev 筛选：无重复 seed 复现、无隔离确认集、无非 LLM 的独立比较；产品时间轴没有复算（dev 是字幕组时间轴）。
- Q 线进产品需要外部服务后端与不用 grammar 时的失败路径，见 [ADR-0017](0017-q2-strata-default-launch-baseline.md)。
