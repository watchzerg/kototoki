# 翻译方法、模型与量化

状态：current（子索引；条目是登记时的摘要，结论以报告正文与[决定索引](../../adr/INDEX.md)为准）

条目格式：`[主题](文件.md)：一句话结论；适用条件或限制`。条目文字自[调研索引](../INDEX.md) 2026-11-11 拆分时原样搬来，新报告在对应小节追加一条。

## 翻译方法与源码调研（2026-10-04 至 2026-10-06）

- [字幕翻译调研总报告](../2026-10-05-subtitle-translation.md)：三个相邻项目源码、上下文与语义映射、JSON／缩批恢复及质量评估；exploratory，未运行翻译实验
- [Subtitle Edit 翻译源码](../2026-10-05-translation-subtitleedit.md)：本地快照与固定上游证据下的实际机制与边界
- [VideoLingo 翻译源码](../2026-10-05-translation-videolingo.md)：本地快照与固定上游证据下的实际机制与边界
- [pyVideoTrans 翻译源码](../2026-10-05-translation-pyvideotrans.md)：本地快照与固定上游证据下的实际机制与边界
- [翻译主流方法与模型契约](../2026-10-05-translation-methods.md)：字幕与文档翻译的上下文、语义单元与专用模型一手资料；不构成模型排名或已采纳实现
- [日译中字幕质量评估](../2026-10-05-translation-evaluation.md)：评估方法与小规模实验建议；不构成已采纳实现
- [三个本地翻译模型对比](../2026-10-05-local-translation-model-comparison.md)：Hy-MT2、TranslateGemma、Tower+ 的输入契约、多段／JSON、字幕约束与部署；来源核查，未进行模型实测
- [Hy-MT2-7B-GGUF 详解](../2026-10-05-hy-mt2-7b-local-translation.md)：模板解释、伪代码、证据等级与字幕适用边界；exploratory
- [TranslateGemma-12B 详解](../2026-10-05-translategemma-12b-local-translation.md)：输入契约、证据等级与字幕使用边界；exploratory
- [Tower-Plus-9B 详解](../2026-10-05-tower-plus-9b-local-translation.md)：本地接口、结构输出与字幕适用性；exploratory
- [Hy-MT2 字幕流程官方资料复核](../2026-10-06-hy-mt2-subtitle-flow-review.md)：核查提示、批量协议、采样与验证边界，建议已回写 Hy-MT2 草案；未实施、未运行推理

## 翻译模型与量化比较（2026-10-06 至 2026-10-07）

- [RTX 5080 16 GB 翻译模型量化选择](../2026-10-06-translation-5080-quantization.md)：五个指定模型的 GGUF、文件大小与全 GPU／混合运行边界，纠正 30B-A3B Q4 显存预期；exploratory，未实测
- [Hy-MT2 30B-A3B Q4 候选](../2026-10-06-hy-mt2-30b-q4-candidates.md)：首次四位 GGUF 来源与容量调查；后续官方 Q4 实测见文内更新链接
- [Hy-MT2 30B-A3B 5080 量化短名单](../2026-10-06-hy30-5080-quantization-shortlist.md)：历史 exploratory，固定文件与试验优先级；当前决定见 ADR-0005（APEX-I-Compact）
- [五候选字幕翻译正式比较](../2026-10-06-translation-model-comparison-results.md)：三家族五版本固定 test，408/415 语义终分；结论为条件化质量／性能建议，附完整失败成本
- [Hy30 Q3／Q4 实测对照](../2026-10-06-hy30-q3-q4-comparison-results.md)：各 83/83 终分，Q4 中位耗时 4.18 倍而质量收益有限且不稳定；当时用户保留 Q3，现行基线见 ADR-0005
- [Hy30 四量化质量、耗时与显存稳定性](../2026-10-07-hy30-four-quantization-results.md)：83 旧窗与 1,200 新窗分别报告，含配对不确定性、四轮耗时与 30 分钟长跑；用户随后采纳 APEX-I-Compact，附录见 [四量化附录目录](../2026-10-07-hy30-four-quantization-results-appendices/reproduction.md)（含 identity、expanded-quality、formal-stability 等附录与数值 JSON，随母报告登记）

## Hy30 四量化报告的附录

上面"Hy30 四量化质量、耗时与显存稳定性"一条的附录文件（冻结；同目录另有图与 JSON 数值证据）：

- [background-overlap-appendix](../2026-10-07-hy30-four-quantization-results-appendices/background-overlap-appendix.md)
- [expanded-quality-appendix](../2026-10-07-hy30-four-quantization-results-appendices/expanded-quality-appendix.md)
- [formal-stability-appendix](../2026-10-07-hy30-four-quantization-results-appendices/formal-stability-appendix.md)
- [formal-stability-background-appendix](../2026-10-07-hy30-four-quantization-results-appendices/formal-stability-background-appendix.md)
- [formal-stability-plot-navigation](../2026-10-07-hy30-four-quantization-results-appendices/formal-stability-plot-navigation.md)
- [identity-appendix](../2026-10-07-hy30-four-quantization-results-appendices/identity-appendix.md)
- [methods-accounting-appendix](../2026-10-07-hy30-four-quantization-results-appendices/methods-accounting-appendix.md)
- [paired-figure-caption](../2026-10-07-hy30-four-quantization-results-appendices/paired-figure-caption.md)
- [performance-cost-appendix](../2026-10-07-hy30-four-quantization-results-appendices/performance-cost-appendix.md)
- [performance-numeric-appendix](../2026-10-07-hy30-four-quantization-results-appendices/performance-numeric-appendix.md)
- [plot-navigation](../2026-10-07-hy30-four-quantization-results-appendices/plot-navigation.md)
- [regression-quality-appendix](../2026-10-07-hy30-four-quantization-results-appendices/regression-quality-appendix.md)
- [reproduction](../2026-10-07-hy30-four-quantization-results-appendices/reproduction.md)
- [review-metric-definitions](../2026-10-07-hy30-four-quantization-results-appendices/review-metric-definitions.md)
