# ADR-0005：字幕翻译采用 APEX-I-Compact 基线

状态：已接受。  
日期：2026-10-07。  
配方更新：2026-10-08，用户明确采纳官方30B采样、4096输出上限和提示缓存。  
替代：[ADR-0004 的 Q3_K_M 采纳决定](0004-hy-mt2-translation-baseline.md)。

用户在阅读[四量化实测报告](../research/2026-10-07-hy30-four-quantization-results.md)后明确决定：翻译流程的模型基线改为 **Hy-MT2 30B-A3B APEX-I-Compact**，candidate 为 `hy-mt2-30b-a3b-apex-i-compact`。后续字幕翻译 demo、优化和回归以此为基准；GrahLnn Q3_K_M 留作历史对照。该决定仅适用于独立翻译流程，STT 仍保留原语言。

## 采用身份与入口

- 发布者：`alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF`；文件 `Hy-MT2-30B-A3B-APEX-I-Compact.gguf`。
- revision：`312cce865e03a0718e36cfd1077e6307957aef72`；文件大小 15,035,838,080 bytes；SHA256：`8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a`。本机路径与资产清单见[资产指南](../guides/local-translation-model-assets.md)。
- 引擎继续使用已验证的 llama.cpp b11429／CUDA 13.4 兼容 loader：`.local/translation-evaluation/20261006-v1/hy30-compat/runtime/llama-server.exe` 及同目录 `identity.json`，不以 stock 引擎替代。
- 基线入口为 `just translation-baseline --inputs <输入.jsonl> --output-dir <新的输出目录>`；完整 PowerShell 示例由 [demo README](../../experiments/translation_demo/README.md)维护。通用 `translation-demo`／Python CLI 仍显式选择 candidate，历史脚本不会被重定向。
- 当前采用 `official30b-cached-v1`：temperature 0.7、top_p 1.0、禁用top_k、repetition_penalty 1.0、最大输出4096、`cache_prompt:true`。本机native HTTP字段为`top_k:0`、`repeat_penalty:1.0`、`n_predict:4096`。当前引擎也接受`max_tokens`作为`n_predict`别名；其请求解析会将`top_k:-1`归到0（禁用），本项目显式发送0。`repetition_penalty`需改用本机字段`repeat_penalty`；这是接口表达差异，不是官方采样策略不可用。
- 显式禁用附加过滤：min_p0、frequency／presence_penalty0、dynatemp_range0、mirostat0、samplers=[temperature]。总context8192，与4096输出上限分开；输入加输出及余量超限时拒绝，不截断源文。seed20261006、相同请求最多两次。
- 提示与交付继续使用`V2-native-adapted`、`native-target-json-gbnf-v3`、`token-ids-v1`、Hy30 `no_think`。GPU layers99、flash attention on、fit off、单槽、batch256、ubatch128、线程8／8、KV f16。每窗内容独立，仅输入日文context与目标IDs；前缀KV复用不添加跨窗对话历史，参考和裁判反馈保持隔离。

## 2026-10-08 配方采纳

用户在阅读有界筛选结果并讨论采样波动、缓存收益后，明确要求采用官方30B建议及缓存。
这是用户的配置选择，不是把此前小样本结果改写成“官方参数稳定更好”或“缓存质量无损”。
当前完整SRT准备入口同样默认官方采样、缓存开启及输出4096；显式旧计划与B0保留。
验证见[新配方采纳检查](../testing/2026-10-08-official30b-cached-baseline-validation.md)。

2026-10-07的temperature0／输出1024／context4096／cache关闭配方保留为`legacy-greedy-v1`历史对照。
原采纳smoke、四量化报告、有界筛选报告及其结果不重跑、不改分。新基线结果使用新目录及配方身份。

## 采纳理由与已知代价

新增剧集的自动评分有小幅正向信号，四轮均完整交付，四款比较中的正式 30 分钟长跑也通过。新增 1,200 窗的四轮墙钟中位数为 1,007.925 秒，旧 83 窗为 59.454 秒。原 Q3 基线四轮同窗失败，因此报告中的有效相对基线倍率仍为 NA；本次采纳不改变历史比较的统计基准或结果。

APEX 的剧集六项校正区间下界仅略高于零，电影系列敏感性区间跨零，旧电影回归方向也相反。采纳是用户结合质量、完整交付和成本作出的工程选择，不是全面质量显著优胜的结论。RTX 5080 正式长跑整卡采样峰值 15,723 MiB、最低空闲 255 MiB，shared 84 MiB；余量较小。49/49 层 offload 与分配计数不证明持续物理驻留，不自动降低配置或回退 CPU。

## 历史与后续回归

四量化报告及其附录、原始 `.local` 产物、匿名键、分数和冻结 SHA 保持原样；其中“基线”仍指实验时的 GrahLnn Q3_K_M。当前采纳身份由本 ADR 维护，历史报告中的“等待用户决定”是交付当时的状态。

以 `.local/translation-evaluation/hy30-four-20261006/` 内 APEX 的正式运行作为已验证起点，精确身份与重放边界见[复现入口](../research/2026-10-07-hy30-four-quantization-results-appendices/reproduction.md)。后续变更新建配方／冻结／输出目录，保留失败；旧 83 窗和新增 1,200 窗都已参与本次选择，不能再称未见的选型保留集。评价继续遵循[评估入口](../testing/translation-model-evaluation.md)。
