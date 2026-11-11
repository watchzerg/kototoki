# 测试文档索引

状态：current（本目录不再新增文件；下表标明每篇能否修改）

当前测试规则（分层、收录）见 [../agents/testing.md](../agents/testing.md)，命令与门禁见 [../development/workflow.md](../development/workflow.md)；现行翻译评估方法见 [../agents/translation-evaluation.md](../agents/translation-evaluation.md)。本目录是历史契约与记录，不是当前测试规则的入口。

类别含义：

- **活契约**：描述仍在使用的评测接口或素材规则，可按[随交付同步](../agents/documentation.md#随交付同步)修改。
- **冻结记录**：带时点的验收或审查记录，永不改写。
- **被校验**：代码对其字节计算 sha256 或把它纳入冻结快照，改一个字节就会破坏校验，不得修改。
- **已被取代**：不再用于当前工作，仅作历史参照。

| 文件 | 类别 | 校验代码或后继 | 说明 |
| --- | --- | --- | --- |
| [2026-10-04-corpus-freeze.md](2026-10-04-corpus-freeze.md) | 冻结记录 | 无 | FateStay 语料冻结、开发／验证／保留划分与时间映射的记录。 |
| [2026-10-04-evaluator-audit.md](2026-10-04-evaluator-audit.md) | 冻结记录 | 无 | `kototoki_eval` 与实验入口的独立合成审查记录。 |
| [2026-10-04-media-matching.md](2026-10-04-media-matching.md) | 冻结记录 | 无 | 四部电影音视频与字幕的低成本核验记录。 |
| [2026-10-05-w0-demo-validation.md](2026-10-05-w0-demo-validation.md) | 冻结记录 | 无（仅 `experiments/w0_demo/README.md` 链接） | 旧 PyanNet W0 demo 的两窗回归验证记录。 |
| [2026-10-05-x0-demo-validation.md](2026-10-05-x0-demo-validation.md) | 冻结记录 | 无（仅 `experiments/x0_demo/README.md` 链接） | X0 demo（fixed30／cut-merge）的两窗 GPU 验证记录。 |
| [2026-10-07-apex-baseline-adoption-validation.md](2026-10-07-apex-baseline-adoption-validation.md) | 冻结记录 | 无（仅 `experiments/translation_demo/README.md` 链接） | `just translation-baseline` 入口采纳 APEX-I-Compact 时的验证记录。 |
| [2026-10-08-official30b-cached-baseline-validation.md](2026-10-08-official30b-cached-baseline-validation.md) | 冻结记录 | 无（仅 `experiments/translation_demo/README.md` 链接） | 官方 30B 采样与缓存配置的采纳检查记录。 |
| [2026-10-10-reference-v3-audit.md](2026-10-10-reference-v3-audit.md) | 冻结记录 | 无 | 参考译文 v3 的复核、修正与置信度记录。 |
| [demo-analysis-contract.md](demo-analysis-contract.md) | 活契约 | 无 | `experiments/analysis` 描述性汇总的输入清单、失败记账与隐私输出接口。 |
| [demo-display-contract.md](demo-display-contract.md) | 活契约 | 无 | 从规范化结果离线回放 SRT 与字幕显示诊断的契约。 |
| [evaluation-config-v1.md](evaluation-config-v1.md) | 被校验 | `experiments/analysis/build_heldout.py` 与 `experiments/analysis/build_validation.py` 比对冻结 sha256；`experiments/analysis/development_selection.py` 记录其 sha256 | 第一轮 STT 筛选的决策规则与晋级配置。 |
| [evaluator-contract.md](evaluator-contract.md) | 活契约 | 无 | `kototoki_eval` 的连续文字、内容时间与完整分母的结果契约。 |
| [fatestay-reference.md](fatestay-reference.md) | 被校验 | `experiments/run_round2.py` 把它纳入冻结源快照并记录 sha256 | 四部电影日语评估参考的来源、身份与素材保护规则。 |
| [stt-evaluation.md](stt-evaluation.md) | 被校验 | `experiments/run_round2.py` 同上 | STT 质量与性能评估的方法与首轮状态。 |
| [subtitle-timing-benchmark.md](subtitle-timing-benchmark.md) | 活契约 | 无 | 以时间同步为优先的字幕评估标准，区分文字、内容时间与显示质量。 |
| [translation-model-evaluation.md](translation-model-evaluation.md) | 被校验 | `experiments/translation_four_quantization/__main__.py` 纳入冻结源快照并记录 sha256；已被取代，后继 [../agents/translation-evaluation.md](../agents/translation-evaluation.md) | 冻结的 Codex 时代翻译评估方法（`sol-high-auto-v1`），当前工作改用后继文档。 |
| [validation.md](validation.md) | 被校验 | `experiments/run_round2.py` 纳入冻结源快照并记录 sha256 | 2026-10-05 前的验证边界约定，内容停在该日，当前测试规则见 [../agents/testing.md](../agents/testing.md)。 |
| [yodas2-parliament-reference.md](yodas2-parliament-reference.md) | 活契约 | 无 | YODAS2 国会讨论素材的获取身份与使用边界。 |

本目录之外同样被校验字节、不得修改的文档：`docs/development/inference-selection.md`（`experiments/run_round2.py`）、`docs/agents/subtitle-translation-evaluation.md`（`experiments/translation_four_quantization/__main__.py` 取 sha256，`experiments/translation_eval/runner.py` 读取）、`experiments/translation_corpus/reference-review-prompt.md` 与 `experiments/translation_corpus/reference-adjudication-prompt.md`。名单不保证完整：改任何既有文档前先搜代码。
