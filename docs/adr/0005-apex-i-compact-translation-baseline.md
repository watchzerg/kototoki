# ADR-0005：H0 翻译模型、采样与引擎（APEX-I-Compact）

状态：已接受。合并整理于 2026-11-08（并入 ADR-0004、ADR-0005 的有效条款；历次变更见[决定索引·演进链](INDEX.md#演进链)，原文见 Git 历史）。自 2026-11-08 起 H0 不再是基线（[ADR-0018](0018-q2-sole-translation-baseline.md)），本篇只作产品当前翻译实现与历史对照的身份。  
范围：H0 翻译线的模型、采样、context、运行时参数与引擎。切包、提示与产品配方见 [ADR-0010](0010-dp10-cut-translation-flow-baseline.md)；H0 与 Q 线的关系见 [ADR-0015](0015-two-translation-baselines.md)。STT 仍保留原语言。

## 决定

1. 模型：Hy-MT2 30B-A3B APEX-I-Compact，candidate `hy-mt2-30b-a3b-apex-i-compact`。发布者 `alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF`，文件 `Hy-MT2-30B-A3B-APEX-I-Compact.gguf`，revision `312cce865e03a0718e36cfd1077e6307957aef72`，15,035,838,080 bytes，SHA256 `8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a`。本机路径与资产清单见[资产指南](../../research/2026-10-translation-model-selection/README.md)。
2. 采样 `official30b-cached-v1`：temperature 0.7、top_p 1.0、禁用 top_k、repetition_penalty 1.0、最大输出 4096、`cache_prompt:true`。本机 native HTTP 字段为 `top_k:0`、`repeat_penalty:1.0`、`n_predict:4096`（`max_tokens` 是 `n_predict` 的别名；`repetition_penalty` 须写作 `repeat_penalty`）。显式禁用附加过滤：min_p 0、frequency／presence_penalty 0、dynatemp_range 0、mirostat 0、samplers=[temperature]。seed 20261006，相同请求最多两次。
3. 总 context 8192，与 4096 输出上限分开；输入加输出及余量超限时拒绝，不截断源文。
4. 模板与交付：Hy30 原生模板及 `reasoning_effort:no_think`；提示基础 `V2-native-adapted`，交付 `native-target-json-gbnf-v3`、`token-ids-v1`。每窗内容独立，仅输入日文 context 与目标 IDs；前缀 KV 复用，不加跨窗对话历史，参考答案与裁判反馈保持隔离。
5. 运行时参数：GPU layers 99、flash attention on、fit off、单槽、batch 256、ubatch 128、线程 8／8、KV f16。
6. 引擎：
   - 研究侧（`archive/2026-11-18-pre-research-restructure:experiments/*`、`just translation-baseline`）使用 llama.cpp b11429／CUDA 13.4 兼容 loader：`.local/translation-evaluation/20261006-v1/hy30-compat/runtime/llama-server.exe` 及同目录 `identity.json`，不以 stock 引擎替代；兼容修正只处理 GGUF 偏置张量命名，权重不改。
   - 产品（`kototoki/`）使用官方 llama.cpp `win-cuda-13.4` 构建，现行版本 b11669（`.local/tools/llama.cpp/b11669-cuda13.4/`，版本与 SHA256 锁在 `assets.toml`），以[技术选型](../development/technology-stack.md)为准；产品架构见 [ADR-0007](0007-bilingual-subtitle-pipeline-architecture.md)。
7. 入口：`just translation-baseline --inputs <输入.jsonl> --output-dir <新的输出目录>`（逐窗 demo，完整示例见 demo README（`archive/2026-11-18-pre-research-restructure:experiments/translation_demo/README.md`））。通用 `translation-demo`／Python CLI 仍须显式选择 candidate。
8. 历史对照身份（不再是基线）：`legacy-greedy-v1`（temperature 0、输出 1024、context 4096、cache 关闭）与 GrahLnn Q3_K_M（`hy-mt2-30b-a3b-q3-k-m`）。

## 依据

- 用户阅读[四量化实测报告](../../research/2026-10-translation-model-selection/README.md)后选定 APEX-I-Compact，复现入口见[附录](../../research/2026-10-translation-model-selection/README.md)。
- 官方 30B 采样与缓存是用户的配置选择，不是"采样更优"或"缓存质量无损"的结论；验证见新配方采纳检查（`archive/2026-11-18-pre-research-restructure:docs/testing/2026-10-08-official30b-cached-baseline-validation.md`）。
- 对 Q3_K_M 只有小幅正向自动评分信号：APEX 剧集六项校正区间下界仅略高于零，电影敏感性区间跨零，是用户结合质量、完整交付和成本作出的工程选择。四轮完整交付，30 分钟长跑通过。

## 约束与未关闭项

- RTX 5080 长跑整卡采样峰值 15,723 MiB、最低空闲 255 MiB，余量小；不自动降配置或回退 CPU。
- 新旧窗口都已参与选型，不能再称未见保留集；变更模型、量化、引擎或采样须建新配方与新输出目录，评价遵循评估入口（`archive/2026-11-18-pre-research-restructure:docs/testing/translation-model-evaluation.md`）。
- 研究侧引擎（b11429）与产品引擎（b11669）并存，研究侧是否同步升级未裁定。
