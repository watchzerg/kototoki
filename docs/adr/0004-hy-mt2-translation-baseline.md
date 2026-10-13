# ADR-0004：字幕翻译采用 Hy-MT2 30B-A3B Q3_K_M 基线

状态：历史决定；2026-10-07 被 [ADR-0005：APEX-I-Compact 基线](0005-apex-i-compact-translation-baseline.md)替代。下文保留 2026-10-06 的采纳理由与配方，“当前基线”均指当时状态。  
日期：2026-10-06。  
依据：用户在五候选完整固定 test 比较后明确采纳，并在 Q3／官方 Q4 追加对照及整片耗时估算后再次确认保留 Q3。

字幕翻译的当前基线为 **Hy-MT2 30B-A3B Q3_K_M**（candidate：`hy-mt2-30b-a3b-q3-k-m`）。后续翻译优化、方案讨论和质量／性能回归以此为基准，复用[本地字幕翻译 demo](../../experiments/translation_demo/README.md)，其余候选保留为对照。该决定适用于独立字幕翻译流程；音频转写仍保留原语言，翻译尚未接入 STT 产品流程。

## 基线身份与配方

- 权重：`GrahLnn/Hy-MT2-30B-A3B-4bit-GGUF` 的 `Hy-MT2-30B-A3B-Q3_K_M.gguf`，revision `4ae7787177f6d4f2d54ec2d543d9fe5f9114d1c9`，SHA256 `9398dedb6f783963f0e9b7fc6ecb16a0158a92aa9a4c0a25eab29ba9704c19d5`；本地位置见[资产指南](../guides/local-translation-model-assets.md)。
- 引擎：llama.cpp b11429／CUDA 13.4，使用本轮 `hy30-compat/runtime/` 的兼容 loader 和 `identity.json`。兼容修正只处理 GGUF 偏置张量命名，权重不改；运行必须显式传入引擎及身份文件，默认 stock 引擎不能替代该身份。
- 已验证起点：`V2-native-adapted`、`native-target-json-gbnf-v3`、`token-ids-v1`；完整冻结日文窗口、原计分 IDs、每窗独立上下文，无跨窗记忆、参考答案、裁判反馈或辅助修订。Hy30 使用自身原生模板及 `reasoning_effort:no_think`，无需 TG 式辅助映射。
- 冻结参数：temperature 0、seed 20261006、输出上限 1024、context 4096、最多两次相同请求；GPU layers 99、flash attention on、fit off、单槽、batch 256、ubatch 128。精确命令、运行身份与源码见[复现入口](../../.local/translation-evaluation/20261006-v1/reproduction.md)及 `freeze.json`。

## 选择理由与边界

[正式比较报告](../research/2026-10-06-translation-model-comparison-results.md)中，该版本原生交付及语义终分均为 83/83；剧集／电影语义均值分别为 3.333／3.192（0–4，类别内作品等权），本机 83 窗口生成阶段约 57.57 秒。它在本轮质量均值和生成速度上最有利，用户据此选作后续基准。

代价是兼容 loader 与较高显存需求：RTX 5080 整卡每秒采样峰值为 15,271 MiB，非模型独占峰值；Hy7 是更省显存的历史对照。自动评分、有限作品数、整个比较的缺分及两项其他候选原始响应追溯例外仍按报告保留。采纳不等于跨作品显著优胜、人工准确率或音画同步验收。

## Q4 追加对照后的再次确认

2026-10-06，[Q3／官方 Q4 对照](../research/2026-10-06-hy30-q3-q4-comparison-results.md)完成相同 83 窗口／414 条待译字幕的评估，两者各 83/83 语义终分。Q3 全 GPU 与 Q4 部分 offload（38/49 层 GPU）的三轮生成中位数分别为 57.32／239.59 秒，Q4 耗时为 4.18 倍。剧集语义基本持平，电影样本 Q4 均分较高但配对区间跨零；两者 major 错误涉及窗口均为 20/83，尚未证明稳定的全面质量优势。

用户据此明确确认：**继续保留 Q3_K_M 基线，官方 Q4_K_M 仅作对照**。对假设含 1,500–2,000 条字幕的两小时电影，按当前窗口配方线性估算，Q4 多耗时约 660–881 秒（11–15 分钟）；这只用于时间预算，不是整片实测或服务承诺，计算方法和边界由上述报告维护。模型身份、原始基线配方及原始对照目录保持不变。

## 后续优化约定

以本轮冻结运行 `20261006-v1/test-v1/hy-mt2-30b-a3b-q3-k-m/` 为原始对照。修改模型／量化、引擎、模板、上下文、映射或恢复策略时建立新配方与新输出目录，保留原基线及全部失败记录；先在 smoke/dev 验证。当前 test 已用于比较，后续依据其表现优化必须明确为 test-informed 新实验，不能再次称为未用于调优的 test。评价继续遵循[翻译评估入口](../testing/translation-model-evaluation.md)及已采纳的 `sol-high-auto-v1`。

本 ADR 记录采纳决定和运行入口，不修改推理代码或 CLI 默认值；CLI 仍要求显式 `--candidate`。新的生产集成、整片流程或默认参数迁移需独立实现与验证。
