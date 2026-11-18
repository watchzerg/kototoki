# 翻译模型选择：从方法调研到 Hy-MT2 30B-A3B APEX-I-Compact（H0）

## 状态
concluded。用户阅读四量化实测后选定 APEX-I-Compact 作为当时的翻译模型与采样配置（H0）；2026-11-08 起 H0 不再是基线，翻译只有一条基线 Q3，本轮只作历史对照与身份来源。

## 时间
2026-10-05 立项（方法与模型调研），2026-10-06 五候选与 Q3／Q4 实测，2026-10-07 四量化实测并采纳，2026-10-08 改为官方 30B 采样配方 `official30b-cached-v1`；同日结题。

## 问题
本地（RTX 5080 16 GB、原生 Windows）做日语到简体中文字幕翻译，选哪个模型、哪个量化、什么采样与运行配置：质量、整卡显存余量和耗时怎么取舍？

## 策略
- 方法与源码调研（只读、未运行翻译）：Subtitle Edit、VideoLingo、pyVideoTrans 的翻译机制，以及字幕与文档翻译的上下文、语义单元、JSON 恢复、日中质量评估方法；结论是"按语义单元组织、前后只读邻文、按 ID 校验、显示与时间另行处理"，是工程综合而非已证明的最优。
- 三个本地专用翻译模型的输入契约调研：Hy-MT2、TranslateGemma、Tower+；Hy-MT2 官方资料复核后建议带显式上下文、每窗独立请求、完整冻结采样配置。
- 五候选固定 test 比较（A Hy-MT2 7B Q8_0、B Tower+ 9B Q8_0、C Hy-MT2 30B-A3B Q3_K_M、D TranslateGemma 12B Q8_0、E TranslateGemma 27B Q3_K_L；D、E 另加 Tower+ 做源跨度映射）。
- Hy30 Q3_K_M 对官方 Q4_K_M 实测对照（原 ADR-0004 的依据，现并入 ADR-0021「H0（历史）」）。
- Hy30 四量化比较：Q3_K_M 基线、i1-Q3_K_M、i1-Q3_K_L、APEX-I-Compact，新增 1,200 窗主集＋旧 83 窗回归＋四轮正式性能＋30 分钟长跑。
- 官方 30B 采样与前缀缓存配方（`official30b-cached-v1`）：用户的配置选择，只验证交付，不做质量比较。

## 环境与版本
- GPU：RTX 5080 16 GB，原生 Windows 11，驱动 616.92 至 617.14，CPU Ryzen 7 5800X3D。
- 引擎：研究侧 llama.cpp b11429（CUDA 13.4），Hy-MT2 30B-A3B 另用兼容 loader（只修 GGUF 偏置张量命名，权重不改）；产品后来改用官方 llama.cpp win-cuda-13.4 构建（当前 b11669）。
- 模型（repo @ 短 revision）：
  - Hy-MT2 7B Q8_0：`tencent/Hy-MT2-7B-GGUF` @ ab847266
  - Tower-Plus-9B Q8_0：`mradermacher/Tower-Plus-9B-GGUF` @ 79d27e5f
  - TranslateGemma 12B Q8_0：`bullerwins/translategemma-12b-it-GGUF` @ d7d1d8cc；27B Q3_K_L：`bullerwins/translategemma-27b-it-GGUF` @ 648ab470
  - Hy-MT2 30B-A3B Q3_K_M（社区转换）：`GrahLnn/Hy-MT2-30B-A3B-4bit-GGUF` @ 4ae77871
  - Hy-MT2 30B-A3B 官方 Q4_K_M：`tencent/Hy-MT2-30B-A3B-GGUF` @ fd3dcbb6
  - Hy-MT2 30B-A3B APEX-I-Compact：`alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF` @ 312cce86，约 15.0 GB
  - Hy-MT2 30B-A3B i1-Q3_K_M／i1-Q3_K_L：`mradermacher/Hy-MT2-30B-A3B-i1-GGUF` @ c36beb0d
- 运行配方：Hy30 原生模板加 `no_think`（Hy-MT2 chat-template token）、`V2-native-adapted` 提示、ID JSON 加 GBNF grammar、token-ids 传输（先 `/tokenize` 再以 token 数组请求 `/completion`）、GPU layers 99、flash attention on、fit off、单槽、batch 256／ubatch 128、KV f16、线程 8。
- 逐窗运行时（`translation_demo`）：外层启动并独占一个 loopback llama-server，核对实际 offload 层数，部分 CPU offload 须显式许可否则中止；内层每窗至多两次相同请求，超出 context 记失败而不截断，截断、非法 JSON、错漏重复 ID 都记失败。
- 采样：五候选与四量化用 temperature 0、seed 20261006、context 4096、输出上限 1024（`legacy-greedy-v1`）；采纳后的 `official30b-cached-v1` 为 temperature 0.7、top_p 1.0、禁用 top_k、repeat_penalty 1.0、输出上限 4096、`cache_prompt:true`、context 8192。

## 测试
- 数据：外部维护的翻译评估库（日文源、字幕组中文参考，经 LLM 复核修订），15 部作品（11 部动画剧集、4 部动画电影）。固定 test 为 83 窗／414 个计分 ID；四量化另新增 1,200 窗／6,000 ID 主集（剧集 880 窗、电影 320 窗），旧 83 窗只作 test-informed 回归。翻译只看日文，参考与裁判不进入翻译。
- 指标：语义 0–4、自然度 0–2；先在作品内取窗口均值，再在类别内作品等权；缺分按 0／4 给上下界（不是置信区间）；配对 bootstrap 以作品为簇。性能记录完整集墙钟、整卡采样显存峰值与最低空闲、四轮重复和 30 分钟固定窗口长跑。
- 旧裁判（Codex 流程）：身份 `gpt-6.1-sol`（high，经 codex-cli 的 fresh 调用），profile `sol-high-auto-v1`：每窗全新主评，按作品固定 20% 抽样加风险窗做盲复评，分歧一次有界裁决。弃用原因：该模型后来不可达；参考库与裁判同家族、没有人工金标准、返回模型身份未暴露；字节锁与多层封签使流程脆弱。旧分数不与后续裁判混算。
- Claude 裁判：先设计了 `claude-opus-5-5-auto-v1` 迁移 profile（保持旧 rubric 与汇总规则，只换裁判，并做校准与基线重锚定），2026-10-10 被取代，改用 MQM 式标注 profile `claude-opus-5-5-mqm-v1`（minor 1／major 5／critical 10 的 accuracy 惩罚，见 [flow-v1-v4](../2026-10-translation-flow-v1-v4/README.md)）。
- 参考复核 prompt 不迁移：用途是让复核者只改有日文依据的明确语义问题并给置信度，路径见"原始材料"。

## 结果
五候选（语义 0–4；缺分时为下界–上界）：

| 候选 | 剧集语义 | 电影语义 | 整卡峰值 MiB | 完整 runtime 秒（83 窗） |
| --- | ---: | ---: | ---: | ---: |
| C Hy30 Q3_K_M | 3.333 | 3.192 | 15,271 | 71.7 |
| A Hy-MT2 7B Q8_0 | 3.124–3.185 | 3.067 | 9,227 | 105.2 |
| B Tower+ 9B Q8_0 | 2.533 | 2.292 | 11,838 | 116.9 |
| D TranslateGemma 12B＋映射 | 2.124–2.197 | 1.925–2.258 | 13,709 | 111.0（另加映射 111.1） |
| E TranslateGemma 27B＋映射 | 2.318–2.512 | 2.108–2.442 | 15,671 | 146.7（另加映射 104.4） |

Hy30 Q3_K_M 对官方 Q4_K_M（同一 83 窗，各 83/83 终分）：

| 项 | Q3_K_M（全 GPU 49/49） | Q4_K_M（GPU 38/49） |
| --- | ---: | ---: |
| 三轮生成耗时中位 | 57.3 s | 239.6 s（4.18 倍） |
| 剧集／电影语义 | 3.382／3.233 | 3.379／3.450（电影配对区间 −0.167 至 0.550，跨零） |
| major 错误涉及窗口 | 20/83 | 20/83 |

四量化（新增主集，作品等权语义差，对 Q3_K_M 基线；基线四轮都在同一窗交付失败，因此没有有效加速倍率）：

| 候选 | 剧集差［95% CI］ | 电影差 | 主集墙钟（1,200 窗） | 最低空闲显存 |
| --- | --- | --- | --- | --- |
| i1-Q3_K_M | +0.035［−0.009, 0.080］ | −0.028 | 约 952 s | 约 916 MiB |
| i1-Q3_K_L | +0.063［0.031, 0.089］ | −0.003 | 993–5,247 s（有慢尾） | 80 MiB |
| APEX-I-Compact | +0.043［0.010, 0.080］ | +0.069，校正与系列敏感性后跨零 | 约 1,008 s | 255 MiB（30 分钟长跑） |

## 结论与去向
- 五候选：Hy-MT2 30B-A3B Q3_K_M 质量与速度居首但整卡余量小，Hy-MT2 7B Q8_0 显存余量最大；Tower+ 与两个 TranslateGemma 都明显落后，TranslateGemma 还要多一道映射并有覆盖损失。结论是条件化建议，不是统计显著的排名。
- Q3／Q4：Q4 慢 4.18 倍而收益不稳定（主要来自部分 offload），用户保留 Q3_K_M，即原 ADR-0004（现并入 [ADR-0021](../../docs/adr/0021-q3-strata-names-baseline.md#h0历史)「H0（历史）」）。
- 四量化：APEX-I-Compact 只有小幅正向自动评分信号（剧集校正区间下界仅略高于零，电影跨零），i1-Q3_K_L 的剧集收益更强但显存余量极小且有 30 分钟慢尾，i1-Q3_K_M 无稳定收益。用户结合质量、四轮完整交付与成本，作出工程选择：采纳 APEX-I-Compact，见 [ADR-0021](../../docs/adr/0021-q3-strata-names-baseline.md#h0历史)「H0（历史）」（原 ADR-0005）。采样配方 `official30b-cached-v1` 是用户配置选择，不是"采样更优"或"缓存无损"的结论；采纳检查只验证交付（短输出、49/49 层 GPU、整卡峰值约 15.8 GiB）。
- 流程层面的后续见 [flow-v1-v4](../2026-10-translation-flow-v1-v4/README.md)、[quality-v5](../2026-10-quality-v5/README.md)、[batching-v6-v8](../2026-10-batching-v6-v8/README.md)；H0 的命名与退位见 [ADR-0021](../../docs/adr/0021-q3-strata-names-baseline.md#唯一基线-q3)「唯一基线 Q3」（原 ADR-0015、ADR-0018）。产品翻译换用 Strata 上的模型，Hy-MT2 不再用于产品。

## 教训
- 旧窗口与新窗口都已参与选型，不能再称未见保留集；换模型、量化、引擎或采样都要建新配方。
- 同家族参考加同家族裁判可能共享偏差；作品少、相邻窗口相关，只报条件化选择，不宣称显著优胜。
- 模型大小与量化同时变化时，差异不能归因于单一因素；整卡显存峰值含其他进程，余量小就不要再加 context 或并行槽位。
- 基线自身交付失败要如实记录，失败会话不取得速度资格。

## 原始材料
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-06-translation-model-comparison-results.md`
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-06-hy30-q3-q4-comparison-results.md`
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-07-hy30-four-quantization-results.md`（含 `2026-10-07-hy30-four-quantization-results-appendices/`）
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-05-subtitle-translation.md`、`2026-10-05-translation-methods.md`、`2026-10-05-translation-evaluation.md`
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-05-local-translation-model-comparison.md`、`2026-10-06-translation-5080-quantization.md`、`2026-10-06-hy-mt2-subtitle-flow-review.md`
- `archive/2026-11-18-pre-research-restructure:docs/testing/2026-10-08-official30b-cached-baseline-validation.md`
- `archive/2026-11-18-pre-research-restructure:docs/plans/claude-judge-profile.md`
- `archive/2026-11-18-pre-research-restructure:docs/guides/local-translation-model-assets.md`（模型来源、revision 与下载方式）
- `docs/architecture/modules/translation-runtime.md`
- `archive/2026-11-18-pre-research-restructure:experiments/translation_corpus/`（参考复核 prompt，仅作用途说明）
