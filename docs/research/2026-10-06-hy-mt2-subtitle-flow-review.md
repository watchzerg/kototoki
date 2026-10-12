# Hy-MT2 字幕翻译流程复核

状态：exploratory；官方资料核验与工程建议，未运行模型。  
最后更新：2026-10-06。  
范围：复核 [Hy-MT2 流程提案](../specs/subtitle-translation-hy-mt2.md)，重点为日语→简体中文的请求组织、上下文和本地解码。共同约束见[共同设计](../specs/subtitle-translation-common.md)；已有模板与资产分析见[专项研究](2026-10-05-hy-mt2-7b-local-translation.md)。本报告不改变 STT 里程碑，也不将建议视为已采纳能力。

后续处理：2026-10-06 按用户要求，以下建议已整合回流程提案，作为可调整的设计选项和实验起点；尚未实施。下文保留复核时的判断，当前流程设计以提案为准。

## 判断与官方证据

流程整体合理。合并完整语义单元、保留程序映射、使用原生模板、新请求携带显式上下文、将显示时间另行处理，都适合作为验证起点。提案已明确多 ID 未验证，并包含严格校验和有界恢复；优化重点是降低首轮条件数量、证明批量收益，以及完整冻结后端实际采样配置。

| 已核验事实 | 对当前提案的意义 | 一手来源 |
| --- | --- | --- |
| 官方提供术语、背景、风格、分隔符及结构保持范式 | 组合提示有依据，但不是官方字幕批量接口 | [GitHub 任务示例](https://github.com/Tencent-Hunyuan/Hy-MT2#hy-mt2-translation-task-instruction-examples-chinese-english-comparison)、[GGUF 模型卡](https://huggingface.co/tencent/Hy-MT2-7B-GGUF) |
| 7B 单 user 模板为 startoftext＋正文＋extra_0；发布配置 top_p 为 0.8，仓库推荐 0.6 | 原生包装与显式参数应保持；不能默认两者相同 | [模板](https://huggingface.co/tencent/Hy-MT2-7B/blob/main/chat_template.jinja)、[发布配置](https://huggingface.co/tencent/Hy-MT2-7B/blob/main/generation_config.json)、[部署推荐](https://github.com/Tencent-Hunyuan/Hy-MT2#inference-and-deployment) |
| IFMTBench 单约束／多约束分数：7B 89.73／72.67；30B 90.20／75.94 | 复杂条件值得单独评估；不同子集不能证明长 prompt 导致退化 | [报告 v1，表 4](https://arxiv.org/html/2605.22064v1#S3.T4) |
| 7B BF16／Q4_K_M 的 IFMTBench 为 83.14／75.11；FLORES 中文双向为 89.17／88.96 | 通用翻译与指令遵循必须分测；不能外推本机 Q8 或 30B Q3 | [报告 v1，表 5](https://arxiv.org/html/2605.22064v1#S3.T5) |
| 官方 JSON 验证只比较类型、键集合、数组长度；IFMTBench 含连续评分 | 其总分不是“JSON 成功率”；不能代替 ID 与台词归属验收 | [验证源码](https://github.com/Tencent-Hunyuan/Hy-MT2/blob/main/IFMTBench/eval/rule_validators.py)、[评分说明](https://github.com/Tencent-Hunyuan/Hy-MT2/tree/main/IFMTBench#constraint-types) |

## 建议按优先级验证

1. **把单单元纯文本作为正常模式。** 多单元 JSON 应作为可选吞吐／连贯性优化。先固定同一分段和可用原文信息，比对逐单元纯文本与 2／4 单元 JSON；逐单元也可看相同邻文，避免把“额外上下文收益”误认为“批量收益”。优先比较严重错意、串段和含恢复总耗时；没有收益就保留纯文本路径。

2. **压缩模型职责，并提前验证结构协议。** 示例一次叠加背景、标题、术语、前后文和格式要求，适合作为后续组合压力测试。首轮仅保留目标语言、待译正文及输出要求；随后先测纯文本／JSON，再逐项增加局部上下文、命中术语、可信背景；全文预分析和 compact 放在最后。短提示更好的说法是工程假设，须与原提示配对实测；程序承担的来源哈希、时间绑定、覆盖记账不必反复让模型执行。

3. **语法约束优先锁定不可变骨架。** 可实验由程序为本批生成 GBNF，固定数组位置与 ID，仅让正文字符串自由生成。当前引用的 llama.cpp v0.5.0 文档明确标记 `prefixItems` 有问题、`uniqueItems` 不支持；只设 ID `enum` 不能保证唯一或顺序。必须检查实际 grammar 并验证错误样例。若改用 ID 键控对象，须另立协议，不能静默放宽当前数组顺序契约；约束仍不证明内容归属。[grammar 文档](https://github.com/ggml-org/llama.cpp/blob/v0.5.0/grammars/README.md#json-schemas--gbnf)

4. **冻结实际采样链。** llama.cpp v0.5.0 CLI 的 `min_p` 默认 0.05、重复惩罚窗口默认 64，`top_k` 禁用值为 0，默认链把 temperature 放在后面。仅填写 Hy-MT2 四个数值仍可能留下额外过滤。首轮显式关闭未选用的 `min_p`，记录 seed、sampler 顺序、惩罚范围及服务实际配置；30B 的 -1 按后端禁用语义适配。CLI 与接口文档部分默认值也不同，应以实际生效值为准。数值相同不证明跨后端采样等价。[server 文档](https://github.com/ggml-org/llama.cpp/blob/v0.5.0/tools/server/README.md#sampling-params)

5. **用疑点决定上下文扩展。** 保持现有只读规则；在轻量模式先供直接相关邻文，再对省略主语、指代或敬称歧义扩大范围。标题、剧情背景和已译句对分别做增量对照，统计消歧收益与补写情节／提前揭示的代价。官方背景范式允许参考资料，未证明本项目固定前后句数、自动摘要或滚动记忆更优。

6. **给语义复核指定执行者。** 提案第 5 节要求审查错意与串段，但尚未定义实现方式。规则用于标记数字、术语、复制和结构疑点；首轮以抽样双语人工复核校准，覆盖跨句否定、重复短句、换说话人、后文揭示和同形人名。辅助模型审校须另测误报／漏报并记成本；不能将“自动检查通过”直接写成人工语义审定。

## 本轮边界

以上建议均未在 RTX 5080 上验证。4096 窗口、输出 1536、最多 4 个单元是待测起点；本报告没有证据要求立刻改大窗口、换模型或增加分析阶段。未安装引擎、未读取大权重内嵌模板、未执行推理或上传字幕。初次复核仅记录建议，随后按用户要求回写 spec；回写仍是设计更新，收益留待 demo 配方验证。

全部外部来源访问于 **2026-10-06**。GitHub／模型卡使用访问日 `main`，模板与 generation config 页面标示文件提交短 ID `f1f6b69`；论文固定 arXiv `2605.22064v1`，llama.cpp 文档固定 `v0.5.0`，并不声明本机已安装该版本。首次实验还须冻结完整 revision、GGUF 哈希与引擎构建。
