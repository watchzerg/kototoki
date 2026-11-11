# experiments 包登记

状态：current（研究代码；产品包 `kototoki/` 不导入这里的任何模块）

规则：
- 冻结轮次、回归参照与 Codex 时代历史是只读证据：配方带 sha256 自检，需要改动时新增带版本的文件，不改原文件。
- 加载模型的入口（含“部分入口”）都是重任务，先问用户再运行（见 [AGENTS.md](../AGENTS.md) 的“重任务先问”）。
- 运行 experiments 的 recipe 走 `justfile` 里的 `legacy` 环境；不在此处新建环境。
- 新增包时在本表加一行；状态只取五类之一：可复用入口、回归参照、测试与工具、冻结轮次、Codex 时代历史。
- 复用并更新 `w0_demo`、`x0_demo`；`x0_flow` 与 `qwen` 只作回归参照，不在其上继续开发。

## 可复用入口、回归参照与测试工具

| 包 | 状态 | 对应调研或 ADR | 加载模型 | 说明 |
| --- | --- | --- | --- | --- |
| `w0_demo` | 可复用入口 | [ADR-0003](../docs/adr/0003-new-pyannote-baselines.md)、[W0 契约](../docs/specs/w0-reusable-demo.md) | 是 | W0（VAD、ASR、对齐）的可复用 demo，持续迭代入口。 |
| `x0_demo` | 可复用入口 | [ADR-0002](../docs/adr/0002-x0-demo-flow.md)、[X0 契约](../docs/specs/x0-reusable-demo.md) | 是 | X0（分段、Qwen 输入、MMS）的可复用 demo，持续迭代入口。 |
| `translation_demo` | 可复用入口 | [ADR-0005](../docs/adr/0005-apex-i-compact-translation-baseline.md)、[ADR-0010](../docs/adr/0010-dp10-cut-translation-flow-baseline.md) | 部分入口 | 连接本地 loopback llama.cpp server 的字幕翻译 demo，不自行下载模型。 |
| `translation_v3` | 可复用入口 | [ADR-0010](../docs/adr/0010-dp10-cut-translation-flow-baseline.md)、[v3 报告](../docs/research/2026-10-10-hy30-flow-v3-report.md)、[README](translation_v3/README.md) | 部分入口 | 研究侧翻译配方与 `translate-srt`、裁判入口的所在包（H0 的 `dp10-cut` 与 Q 线配方）；v3 轮次本身的配方与证据冻结。 |
| `x0_flow` | 回归参照 | [X0 分片流程研究](../docs/research/2026-10-05-x0-whisperx-flow.md) | 是 | X0 分片流程隔离原型，只作回归参照。 |
| `qwen` | 回归参照 | [Qwen 实测](../docs/research/2026-10-04-qwen-execution.md) | 是 | 官方 Qwen native HF 实验入口，只作回归参照。 |
| `analysis` | 测试与工具 | — | 未核实 | 早期开发集、整片、留出集的分析与汇总脚本。 |
| `corpus` | 测试与工具 | — | 否 | 早期语料、静音与参考的准备脚本。 |
| `display` | 测试与工具 | — | 否 | 冻结集合的字幕展示回放脚本。 |
| `performance` | 测试与工具 | [基线测试指南](../docs/guides/baseline-testing.md) | 否 | 只读汇总历史 harness manifest 的性能与资源。 |
| `provision` | 测试与工具 | — | 未核实 | 模型获取与范围模型准备脚本。 |
| `tests` | 测试与工具 | — | 否 | evaluator 的单元测试。 |

## 冻结轮次与历史

| 包 | 状态 | 对应调研或 ADR | 加载模型 | 说明 |
| --- | --- | --- | --- | --- |
| `whisper` | 冻结轮次 | [Whisper 实测](../docs/research/2026-10-04-whisper-execution.md) | 是 | 历史无外部 VAD 的 W0 路线，用于复现旧实验。 |
| `crisp` | 冻结轮次 | [Crisp 实测](../docs/research/2026-10-04-crisp-execution.md) | 是 | Crisp 本地实验入口，冻结版本与参数。 |
| `japanese_ctc` | 冻结轮次 | [日语 CTC 结果](../docs/research/2026-10-04-japanese-ctc-results.md) | 是 | 缓存文字的多候选 CTC 对齐补充实验。 |
| `framework_equivalence` | 冻结轮次 | [框架等价实验](../docs/research/2026-10-04-whisper-framework-experiment.md) | 是 | Whisper 框架行为对照原型，当前 W0 开发改用 w0_demo。 |
| `components` | 冻结轮次 | [组件消融结果](../docs/research/2026-10-04-component-augmentation-results.md) | 是 | 单组件消融及 VAD＋CTC 追加实验，未采用新的产品配置。 |
| `vad_comparison` | 冻结轮次 | [VAD 基线比较计划](../docs/plans/vad-baseline-comparison.md) | 是 | 十种 VAD 组合在冻结十二窗上的 W0／X0 比较。 |
| `fullfilm_comparison` | 冻结轮次 | [整片分段比较](../docs/research/2026-10-05-fullfilm-segmentation-comparison.md) | 是 | 两部完整电影的分段策略整片比较。 |
| `asr_candidates` | 冻结轮次 | [ASR 候选整片比较](../docs/research/2026-10-05-asr-candidates-fullfilm.md) | 是 | Cohere、Granite、Nemotron 与 W0／X0 的整片比较。 |
| `quality_v5` | 冻结轮次 | [v5 报告](../docs/research/2026-10-16-quality-exploration-v5.md)、[票据](../.scratch/quality-exploration-v5/) | 部分入口 | 字幕质量第五轮探索的运行辅助与离线分析。 |
| `scene_batching_v6` | 冻结轮次 | [v6 报告](../docs/research/2026-10-16-scene-aware-batching-v6.md)、[票据](../.scratch/scene-batching-v6/) | 部分入口 | 第六轮场景感知分批的离线分析与干预实验。 |
| `reorder_groups` | 冻结轮次 | [v8 报告](../docs/research/2026-10-18-group-reorder-v8.md)、[票据](../.scratch/group-reorder-v8/) | 否 | 同句小组语序重排的划组统计与 v8 离线工具，纯 CPU。 |

| `translation_v4` | 冻结轮次 | [v4 报告](../docs/research/2026-10-11-hy30-flow-v4-report.md)、[ADR-0008](../docs/adr/0008-no-multi-translation-selection.md) | 部分入口 | Hy30 流程第四轮，`mbr8c` 已放弃。 |
| `name_consistency` | 冻结轮次 | [ADR-0013](../docs/adr/0013-name-consistency-closed.md)、[ADR-0014](../docs/adr/0014-name-consistency-in-product.md) | 部分入口 | 专名表建表与生成后替换研究线，已结题，产品只复制不导入。 |
| `asr_robustness_v14` | 冻结轮次 | [v14 报告](../docs/research/2026-11-09-asr-robustness-v14.md)、[票据](../.scratch/asr-robustness-v14/) | 部分入口 | ASR 稳健性第十四轮的运行辅助与离线分析。 |
| `asr_robustness_v15` | 冻结轮次 | [v15 报告](../docs/research/2026-11-10-asr-robustness-v15.md)、[票据](../.scratch/asr-robustness-v15/) | 部分入口 | ASR 稳健性第十五轮，只读复用 v14，结论进产品见 ADR-0023。 |
| `translation_four_quantization` | 冻结轮次 | [四量化方案](../docs/plans/hy30-four-quantization-comparison.md) | 部分入口 | Hy-MT2 30B 四量化串行 GPU 比较的调度入口。 |
| `translation_corpus` | 冻结轮次 | [四量化方案](../docs/plans/hy30-four-quantization-comparison.md) | 否 | hy30-expanded-v1 候选语料构建与参考复核，不做模型推理。 |
| `translation_compat` | 冻结轮次 | [四量化方案](../docs/plans/hy30-four-quantization-comparison.md) | 否 | Hy-MT2 30B GGUF 只读兼容性诊断与 llama.cpp 补丁。 |
| `translation_flow` | Codex 时代历史 | [v2 计划](../docs/plans/hy-mt2-translation-flow-exploration-v2.md)、[v2 台账](../docs/context/2026-10-08-hy30-flow-exploration-v2.md) | 是 | 固定 Hy30 的有界流程实验（含 v2_*），第二轮已停止并冻结。 |
| `translation_eval` | Codex 时代历史 | [评估计划](../docs/plans/translation-model-comparison.md)、[评估流程](../docs/agents/subtitle-translation-evaluation.md) | 否 | `sol-high-auto-v1` 离线评估 harness（packet、校验、汇总）。 |
| `translation_judge` | Codex 时代历史 | [评估流程](../docs/agents/subtitle-translation-evaluation.md)、[比较结果](../docs/research/2026-10-06-translation-model-comparison-results.md) | 否 | `codex exec` 裁判传输层，调用外部服务而非本地模型。 |

## 顶层模块

| 模块 | 说明 | 加载模型 |
| --- | --- | --- |
| `run_experiment.py` | 串行化 GPU 实验并保存复现证据。 | 未核实 |
| `run_round2.py` | 冻结并恢复第二轮本地比较。 | 未核实 |
| `translation_demo_runtime.py` | 启动隔离的本地 llama.cpp 模型并保存运行证据。 | 是 |
| `translation_monitor.py` | 串行翻译运行的离线资源遥测。 | 否 |
| `translation_comparison_report.py` | 确定性比较报告与证据清单。 | 否 |
| `translation_four_performance.py` | 四量化不可变运行的离线性能聚合。 | 否 |
| `translation_four_stats.py` | 四候选确定性统计，只读台账。 | 否 |
| `translation_identical_output_diagnostics.py` | 逐 ID 译文完全相同的评审噪声诊断。 | 否 |
| `translation_terminology_diagnostics.py` | 候选盲的术语范围与字面渲染诊断。 | 否 |
| `translation_reference_judge.py` | 双轮参考复核的 Codex 裁判传输。 | 否 |
| `x0_flow_evaluate.py` | 用既有 evaluator 评估 X0 分片流程两窗研究。 | 否 |
