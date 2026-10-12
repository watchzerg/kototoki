# Hy30 字幕流程第三轮探索计划：Claude 裁判下的重新起跑

日期：2026-10-10。状态：**已执行完毕**（2026-10-10，已收敛，0 个确认配方，基线不变），见[v3 报告](../research/2026-10-10-hy30-flow-v3-report.md)和[v3 台账](../context/2026-10-10-hy30-flow-exploration-v3.md)。
范围：固定 Hy-MT2 30B-A3B APEX-I-Compact（[ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md)），寻找更好的 `jpn.srt → chn.srt` 完整流程与参数。不换模型、不换量化、不并入 STT 里程碑、不自动替换基线。
相关：[v1/v2 教训与先验](../research/2026-10-10-hy30-flow-v1-v2-lessons.md)、[v2 计划（历史）](hy-mt2-translation-flow-exploration-v2.md)、[参考 v3 复核](../testing/2026-10-10-reference-v3-audit.md)、[实验入口](../../experiments/translation_v3/README.md)。

## 1. 为什么重新起跑，而不是续跑 v2

决定：**新开 v3，复用 v2 的数据资产与经验，不复用其分数、裁判和流程管理体系。**

| 考量 | 续跑 v2 | 新开 v3（采用） |
| --- | --- | --- |
| 裁判 | `gpt-6.1-sol` 已不可用；换裁判后所有旧分数不可比，C0 和每个候选都要重判 | 一开始就用新裁判，C0 与候选同一量尺 |
| 代码 | 约 4.2 万行，大量 sha256 自校验、ROOT／SAFE／custodian 签署链；改一处就要新建一套授权 | 精简的新包，状态完全由文件推导，可中断、可幂等续跑 |
| 证据 | F2 末组未知、fresh C0 未评、多个入口停在“已签未执行” | 已有方向结论作为先验，用于取舍与排序，不作为数值证据 |
| 隔离与可信度 | 规则正确但执行成本极高 | 保留真正重要的隔离：参考／裁判与翻译准备分离、确认集封存、候选盲评 |

v2 的全部目录、台账和冻结结果原样保留，作为历史证据。v3 不写入 v2 目录，不修改 v2 代码。

## 2. 复用与不复用

**复用（只读）**

- 源数据：`.local/translation-evaluation/hy30-flow-v2-20261008/source/screening-qualified-v1/`，34 个场景、4297 条台词、96 个筛选窗（screen-a 48、screen-b 48；每窗 5 条评分 cue）。确认集为 48 窗，源区间与筛选集隔离，其 model-input 位于 `evaluation-only/reference-v1/model-input/confirmation.jsonl`。
- 参考：`reference-v1`（144 窗、720 条评分 cue）经 Opus 5.5 复核后形成 **reference-v3**，带逐条置信度与可接受歧义说明（见[参考复核](../testing/2026-10-10-reference-v3-audit.md)）。
- 生成运行时：Hy30 原生模板、ID JSON grammar、token-ids 传输、解析器（`experiments/translation_demo/adapters.py`、`client.py`），以及资产清单与驻留校验函数。这些只被导入，不修改。
- C0 配置：与 v2 完全相同，见第 3 节。

**不复用**

- 旧裁判结果和数值（Sol/high），包括 v16 矩阵中的全部 Δ。
- v2 的 custody／签署／授权链与运行器。
- 已生成的 v2 译文：它们缺少 v3 的完整运行记录，且部分配置身份复杂，统一在 v3 下重新生成。

## 3. 固定基线 C0

与 v2 的 `C0-official-cached` 相同：

- Hy-MT2 30B-A3B APEX-I-Compact，SHA256 `8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a`，使用兼容引擎 `.local/translation-evaluation/20261006-v1/hy30-compat/runtime/llama-server.exe`（b11429／CUDA 13.4）。
- temperature 0.7、top_p 1、top_k 0、min_p 0、repeat_penalty 1、samplers 仅 temperature；`n_predict` 4096；`cache_prompt` true；总 context 8192；单槽；99 层全 GPU；f16 KV；threads 8/8；batch 256／ubatch 128；flash on；fit off；no_think。
- 批大小 5 条，每侧 1 条只读邻文，原 JSON 提示（`adapters.render("hy-mt2-30b", …)`）加 ID grammar，保留源 cue 时间。
- 每个 run 使用新启动的服务器，从空缓存开始，按场景源顺序翻译全部 34 个场景。
- 质量比较用 3 个 seed：20261008、20261009、20261010。

超出 context 时不截断源文、不回退 CPU、不自动缩批；记录为失败。

## 4. 评测：`claude-opus-5-5-mqm-v1`

### 4.1 方法

用 MQM 式错误标注，不用 0–4 总分。v2 的教训是：0–4 档位太粗，单窗翻档率约 17%；自然度 0–2 均值约 1.9，接近天花板，区分不了候选。MQM 改为列出具体错误：

- **裁判**：`claude-opus-5-5`，effort `high`。首选执行面是 `claude -p --safe-mode --tools "" --no-session-persistence --system-prompt <固定提示> --json-schema <schema>`，在空临时目录中运行，并记录 `modelUsage` 里实际返回的模型。如果 CLI 未登录，改用备用执行面：goal 会话派 `model: opus` 的子 agent，读取导出的待评包，写回结果。两种执行面在结果里分别记录，同一对比较只用一种执行面的结果。
- **盲评**：任务包里不含 recipe、seed、运行名，候选只用随机 run 哈希标识。每个裁判调用只看**同一个 run 的** 4 个窗口（打包可节省配额），不同候选绝不同包。
- **每窗输入**：评分 cue 前后各 8 条日文上下文；每条评分 cue 的日文、reference-v3 中文、参考置信度与可接受歧义；候选对这些评分 cue 的译文。参考只作为辅助，以日文源文为准；对参考标为 low 或列出歧义的 cue，不能因候选选择了另一种合理理解而判错。
- **输出（JSON schema 强制）**：每条评分 cue 给出 `errors[]`，每条错误包含 `category`、`severity`（minor／major／critical）和 `evidence_zh`。
  - accuracy 类：mistranslation、omission、addition、wrong-referent、negation-number-condition、cue-attribution。
  - fluency／style 类：grammar、unnatural、register、terminology-inconsistency。
  - 另外给出 `no_error: true` 的显式确认。
- **计分**：MQM 惩罚为 minor 1、major 5、critical 10。
  - 主终点：每条评分 cue 的 **accuracy 惩罚**均值，越低越好。
  - 次要指标：major＋critical 的出现率、fluency 惩罚、交付失败率、完整流程墙钟。

### 4.2 校准（S0，必须先于任何候选比较）

1. **参考自检**：把 reference-v3 本身当作候选送评（screen-a 48 窗）。accuracy 惩罚应接近 0；被判 major 的条目要逐条回看，排查参考错误或裁判过严。
2. **合成灵敏度**：从 C0 seed 20261008 的 screen-a 输出中，程序化构造四类已知错误：否定翻转、数字改动、删去关键信息、相邻 cue 内容互换，共约 40 处。检出率目标 ≥ 90%，误报写入记录。
3. **重复噪声**：同一份 C0 seed 20261008 的 96 窗输出重新打乱打包、再判一次。计算逐窗主终点差的分布，由此得到最小可检出差 `MDE = 2 × SE(配对差)`，以及 major 判定的翻转率。
4. 根据 1–3 的结果冻结 `decision-policy-v3.json`，包括 MDE、非劣界、critical 规则。**冻结前不得查看任何候选成绩。**

如果检出率低于 80%，或者 MDE 大到连 C0 的 3 个 seed 之间都无法分辨，就停下来修改裁判提示，作为 `…-mqm-v2` 新版本重新校准，不带着坏量尺继续。

## 5. 数据角色与隔离

- **主会话（goal 会话的主 agent）是方法开发者**：可以看 screen-a／screen-b 的聚合指标和单条错误类别统计；不读确认集的参考与裁判原文；不把参考或裁判反馈用于设计提示、术语或场景卡。
- **翻译准备**（术语表、场景卡、源文规划）只读日文。
- **确认集 48 窗**：锁定候选之前不生成、不评测。锁定后一次性评测，候选不得再修改；改了就失去确认资格。
- **复核过参考的 agent**（三个 Opus 分片）不参与候选设计。

## 6. 方向与先验

数值证据详见[教训文档](../research/2026-10-10-hy30-flow-v1-v2-lessons.md)，下表只给出 v3 的取舍。“v2 信号”都基于旧裁判，仅作为排序依据。

v1/v2 的总体结论：

- 两轮都没有配方通过确认，确认集从未开封。
- 收益几乎只出现在剧集代表窗，电影代表窗在 0 附近。
- screen-b 常常复现不了 screen-a 的收益；b3、b20、ctx0、ctx3 等在风险窗新增了严重错误。
- 作品之间的差异大于配方效应。

因此 v3 以**风险窗的 major／critical** 作为与均分并列的门槛。“零候选”也是合法结局。

| ID | 方向 | v2 信号（旧裁判） | v3 处理 |
| --- | --- | --- | --- |
| W | 有限空白语法 `bws` | 4096 触顶由 JSON 外空白循环导致，与批大小无关；每 200–3600 批约 1 次，重试多能通过 | S1 第一个候选，属于工程项。若非劣且失败更少，后续候选都在它之上构建，并以 `bws` 作为新对照（通过 `bws` 对 C0 的结果衔接） |
| B | 批大小（条数）：b10、b20、b40 | b20 剧集为正，但风险窗新增 major；b40 耗时略省；b60 电影退化；b80 首批输入 4211 tokens，超出 4032 上限 | 高优先级。重点看风险窗严重错误。b3、b1 降级：b1 耗时约 1.8 倍 |
| T | 按源 token 目标分批：tok300、tok400、tok500 | token400 剧集代表 +0.36，电影约 0，B 半组风险窗为负，自然度略降；token600 电影退化 | 高优先级复测 |
| X | 邻文：ctx0、ctx3、非对称 ctx3-1（前 3 后 1） | ctx0／ctx3 风险窗有新增严重错误；完整 96 窗结果未出 | 高优先级 |
| J | 联合理解提示：只把“每值独立理解”改为跨 cue 共同理解 | F3 风险窗有新增严重错误 | 中 |
| P | 场景级源文预分析（术语／人物，只读日文）后注入 | F6 术语耗时约 825 秒（C0 约 715 秒）；辅助输出 4096 时超容量，改成 2048 才能运行；质量未出 | 中；辅助输出预算固定为 2048 |
| R | 风险触发的选择性自审校（否定、条件） | F8 全量审校约为 2 倍耗时，质量未出 | 低到中；只测选择性触发 |
| N | 非 JSON 协议（id-text 系列） | ordered 版电影代表窗 −0.16，三个 seed 均负；flex 版有布局失败 | 不再测，除非出现新的机制性理由 |
| S | 语义单元：规划→联合翻译→拆回 | −0.52／−0.50；structured 资格只交付了 37/54 批 | 不再测 |

具体组成详见[教训文档](../research/2026-10-10-hy30-flow-v1-v2-lessons.md)。容量约束：总 context 8192，输出预留 4096，余量 64，所以输入上限是 4032 tokens。显存最低空闲只有约 107–260 MiB，不加 KV，也不开并行槽。耗时参考：C0 一次 34 场景运行约 12 分钟。

新增假设必须写明：要消除什么不确定性、预期机制是什么，以及会读哪些失败样例来判断。

## 7. 流程

| 阶段 | 内容 | 退出条件 |
| --- | --- | --- |
| S0 | 参考 v3 冻结；C0 三个 seed 生成；裁判校准（4.2）；冻结决策规则 | `decision-policy-v3.json` 冻结 |
| S1 | 单因素筛选：每个候选先跑 screen-a 48 窗 × 3 个 seed，与 C0 配对 | 判为 promising 的扩到 96 窗；其余记录结论 |
| S2 | 有希望单项的局部细化（插点）与有机制依据的组合（≤ 4 个组合） | 1–3 个完整配方可以锁定 |
| S3 | 确认集 48 窗 × 3 个 seed，锁定配方对 C0 | 确认判定（7.1） |
| S4 | 选 1 部电影和 1 集剧集整片翻译：机械完整性、耗时、显存；语义只看确认结果 | 交付稳定 |
| S5 | 中文报告：候选表、代价、风险、适用场景；不自动替换基线 | 用户决策 |

### 7.1 统计与判定

- 每窗先在 3 个 seed 上取均值，再按作品等权汇总；剧集和电影分别报告，总览两类各占 50%。代表窗与风险窗分开报告，风险窗不并入总体均值。
- 区间：按作品聚类做配对 bootstrap，10000 次，seed 固定 `v3-bootstrap-20261010`；系列关系（如 SAO）按系列聚类。
- 每次比较都同时报告**逐作品 Δ**。如果收益只由单部作品带来，即去掉这一部后不再满足判定，就不能判为 promising。
- **promising**（screen-a）：总体 Δ ≤ −MDE；任一类别都不比 C0 差超过非劣界；critical 不增加；风险窗的 major＋critical 不显著增加。
- **淘汰**：在 96 窗上总体 Δ ≥ 0，或某类别劣于非劣界并且三个 seed 方向一致。
- **证据不足**：其余情况。可以扩到 96 窗，或者记录后搁置。
- **确认通过**：确认集上总体 Δ 的 95% 区间上界 < 0；两个类别都满足非劣界；critical 不增加；最多 3 个配方，使用 Holm 校正。
- 数值阈值以 `decision-policy-v3.json` 为准。

## 8. 恢复、配额与 GPU

- **状态即文件**：每个 run 的每个场景完成后，原子写入 `scenes/<scene>.json`；每个裁判包完成后，原子写入 `judge/<packet>.json`。`status` 命令直接从文件推导剩余工作，没有额外的“进行中”状态需要人工清理。
- **生成中断**：重启后在新服务器上只补未完成的场景。该 run 标记 `resumed=true`，其墙钟不进入性能比较，质量结果照常使用。
- **裁判配额耗尽**：识别 CLI 的限额或 429 类错误后，写 `judge-blocked.json`（时间与原文），以退出码 75 退出。已完成的包不会重跑。配额恢复后再执行同一命令即可续跑。
- **生成与裁判解耦**：GPU 生成不消耗 Claude 配额，可以在后台长跑；配额耗尽期间生成照常推进。
- **GPU 独占**：生成前检查端口与 `.local/gpu.lock`（v3 运行时自行写入和释放，带 PID）；发现他人进程时不抢占、不杀进程。
- 全部产物写在 `.local/translation-evaluation/hy30-flow-v3/`，具体结构见[实验入口](../../experiments/translation_v3/README.md)。

## 9. 台账

[v3 台账](../context/2026-10-10-hy30-flow-exploration-v3.md)每完成一个候选追加一条：假设、唯一变化、结果（Δ、区间、类别、critical）、判定、下一步。所有尝试都要记录，失败也计入；未知值不填 0。台账保持简短；数字以 `summaries/` 下的 JSON 为准。

## 10. 收敛与停止

满足以下全部条件即停止：

- B／T／X 方向的主要趋势和转折已检查。
- J／P／R 方向各完成有界筛选，或有明确阻碍。
- 有希望的配方已经过确认集检验，或明确没有候选值得确认。
- 报告诚实给出 0 个、1 个或若干个候选。

只因资源或外部原因停下时，写“尚未收敛”。
