# VAD、对齐与 cue 规则

状态：current（子索引；条目是登记时的摘要，结论以报告正文与[决定索引](../../adr/INDEX.md)为准）

条目格式：`[主题](文件.md)：一句话结论；适用条件或限制`。条目文字自[调研索引](../INDEX.md) 2026-11-11 拆分时原样搬来，新报告在对应小节追加一条。

## VAD／分段（2026-10-04 至 2026-10-05）

- [W0＋VAD＋CTC 追加比较](../2026-10-04-w0-vad-ctc-follow-up.md)：同十二窗六配置对照，VAD 叠加未提高全分母时间成功，长尾与漏字存在取舍
- [VAD 全景与 W0／X0 分片改进](../2026-10-05-vad-landscape.md)：探索性来源调研，VAD 允许 CPU／GPU、对白优先；未更换基线组件，未执行新推理
- [成熟 VAD 来源核查](../2026-10-05-established-vad-sources.md)：Silero、Pyannote、FSMN、NeMo、SpeechBrain 的发布、模型身份、语言与 Windows／GPU 边界
- [新兴 VAD 来源核查](../2026-10-05-emerging-vad-sources.md)：FireRed、OmniVAD-Kit、TEN 的模型关系、维护记录、许可与部署限制
- [VAD 稳定版本核验](../2026-10-05-vad-stable-versions.md)：四候选的官方发布、权重 revision、默认参数与许可；FireRed Beta 例外与 Pyannote 访问门控已区分
- [W0／X0 十组合 VAD 比较](../2026-10-05-vad-baseline-comparison.md)：十组合实测与审计完成，1 次 X0＋新 Pyannote 生成上限失败保留；结论保留当时口径，后续采纳见 ADR-0003
- [新 Pyannote CPU／GPU 对照](../2026-10-05-pyannote-gpu-comparison.md)：切分与质量一致，新进程 GPU 较慢，单窗模型复用约快 13.1 倍；23 次完成、1 次同窗触顶
- [两片整片分段对照](../2026-10-05-fullfilm-segmentation-comparison.md)：新 Pyannote GPU 与 cut-merge 共八组整片运行及独立审计；后续用户已采纳新 Pyannote（ADR-0003）

## 对齐（2026-10-04）

- [新增组件与对齐器兼容性](../2026-10-04-component-augmentation-sources.md)：Demucs、GPU VAD、Qwen FA、Canary 日语限制及现有 wav2vec2 身份的官方来源核查；不代表质量已验证
- [组件增量实测](../2026-10-04-component-augmentation-results.md)：分离／VAD 出现回归，W0＋CTC 输入契约修复有时间收益但有覆盖取舍；无新的总体优胜组合
- [日语 CTC 官方来源核验](../2026-10-04-japanese-ctc-source-verification.md)：模型身份、blank／tokenizer 契约、日语 adapter 与许可核验；质量结论另见实测
- [Japanese CTC Forced Alignment 外部会话参考](../2026-10-04-japanese-ctc-alignment-reference.md)：保留外部会话原始建议的历史身份；官方核验与本机实测见相邻两篇
- [日语 CTC 补充实测](../2026-10-04-japanese-ctc-results.md)：MMS 补充 W1／X0、Reazon 补充 X0、假名模型补充 W0 均有证据；保留严重偏移、粒度与许可取舍

## 双语字幕流水线 cue 规则（2026-10-15）

- [cue 间隔断句引入 ASR token 边界](../2026-10-15-cue-token-boundary-study.md)：两个引擎的 token 都能稳定映射到窗口字符，但 Whisper 日文 token 接近单字，"同一 token 内不断句"在四部整片只减 12 条 ≤2 字条目且新增 >6 s 条目，不能修复票据 12 的样本；用户裁定不实现，根因归 VAD 召回。只有离线统计，无人工观感

## 双语字幕流水线技术设计的历史原文（2026-11-11）

- [技术设计拆分时移出的原文](../2026-11-11-bilingual-pipeline-spec-history.md)：concluded（冻结原文）。原状态行修订历史、§1.2 裁定表、§2–§6 移出的成本表与重采样对比、§7.2–§7.4 环境与上游版本核实、§8、§9 验收草案、§11 未来方向、§12 里程碑、§13 评审修订记录；其中的版本与"当前"只描述各自记录时点
