# 字幕翻译流程第九轮探索（v9）：通用模型（Qwen3.8-27B）在同一接缝下直接翻译——方案、进度与结论

状态：concluded（2026-10-21 立项并执行完毕；结论见 §7.1，待裁定事项见 §8）  
范围：固定流程基线 **dp10-cut**（[ADR-0010](../adr/0010-dp10-cut-translation-flow-baseline.md)：切包、只读邻文、joint 提示、ID JSON grammar、降级逻辑），只换**翻译模型**——用产品 names 阶段已在用的通用模型 `unsloth/Qwen3.8-27B-GGUF` `UD-IQ3_S`（[ADR-0014](../adr/0014-name-consistency-in-product.md)）代替 Hy-MT2 30B-A3B APEX-I-Compact（[ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md)）翻译同样的包；另加一个"同模型、更宽只读邻文"的臂。不换量化、不换切包、不改输出结构、不做自由文本翻译、不做重排、不注入专名表、不改裁判、不改产品、不自动替换任何基线。  
执行载体：tracker 目录 `.scratch/general-model-translation-v9/`（spec、map、票据；Git 忽略）。**本文是唯一进 Git 的进度与结论记录。**  
先读：[v7 研究文档](2026-10-16-gap-aware-batching-v7.md) §2.1（裁判漂移、同包重判、噪声底）与 §4.6（评测设计）、[v8 研究文档](2026-10-18-group-reorder-v8.md) §2.4（容量、确认集、hash 不变规则）与 §6（记录协议）、[v5 §3](2026-10-16-quality-exploration-v5.md) 判定纪律、[translation_v3 README](../../experiments/translation_v3/README.md) 配方段、[scene_batching_v6 README](../../experiments/scene_batching_v6/README.md) 的 v7 命令、[专名一致性第一轮报告](2026-10-19-name-consistency-offline-results.md) §1（Qwen IQ3_S 在本机的显存、速度、贪心无限重复）、`kototoki/names/{table,recipes}.py`（Qwen 的 server 参数与采样）。

本文与 v7／v8 的分工相同：臂、接口、评测设计、预算与停止条件已在 2026-10-21 的讨论中定下（§4、§5），执行者只填实现细节（Qwen 提示的最终措辞、请求形状、宽邻文的实现位置、"明显更差"阈值之外的统计细节）并在票据里说明理由。

## 1. 为什么做这一轮

- **这是翻译侧唯一没测过的大变量。** 2026-10-06 的[五候选比较](2026-10-06-translation-model-comparison-results.md)全是专用 MT（Hy-MT2 7B／30B、Tower+ 9B、TranslateGemma 12B／27B）；[10-05 的方法调研](2026-10-05-subtitle-translation.md)末段建议过"一条通用指令模型路线"，之后没有执行。v3–v8 全部是 Hy-MT2 之上的流程探索。"Hy-MT2 比通用模型好"在本仓库里是未经验证的默认。
- **通用模型已经在产品里。** ADR-0014 起 `names` 阶段加载 Qwen3.8-27B 建专名表，llama-server 模块、资产、显存与速度数字都已有；本轮的边际成本只有翻译提示与评测。
- **先验并不乐观，所以定位是"有界地关闭问题"。** 不利面：本卡只能跑 IQ3_S（3-bit 稠密 27B；Hy-MT2 APEX-I-Compact 是 15 GB 的 MoE，比特数更高）；Qwen 生成 51–53 tok/s，Hy-MT2 产品里约 175 tok/s，整片翻译 200 s → 估 600–700 s；v5 测得产品中文错误约四分之三来自 ASR，翻译侧上限有限。有利面：世界知识（专名、作品语境、ASR 误识纠正）、指令遵循与结构化输出（names 阶段已验证）、长上下文（整片 13–15K tokens 可行，Hy-MT2 输入上限 4032 tokens）。预期：accuracy 大概率不超过 Hy-MT2，fluency 与专名处理可能更好，最可能的结局是"不输太多但慢 3 倍"。无论结果如何，都要留下一条可引用的结论，之后的质量讨论不再绕回这里。

## 2. 已知事实（不要重复）

### 2.1 基线侧

- **dp10-cut 没有任何 GPU run 和裁判分数**（ADR-0010 按逻辑推定采纳，v8 同样）。本轮 Hy-MT2 对照必须新生成；它只用于与本轮候选配对，不回头与 b10-joint 比较。
- Hy-MT2 臂的全部身份不变：`translation_v3` 的冻结 compat 引擎（b11429）、APEX-I-Compact、`official30b-cached-v1` 采样、context 8192、输入上限 4032 tokens、`joint-understanding-v1`、ID JSON grammar（每个目标 ID 按原顺序各出现一次、非空）、`cache_prompt`、相同请求最多两次。
- v3 的结论"宽只读邻文（ctx3）无效""批次转折点在 10 附近""输出 ID 越多 wrong-referent 越多"都只针对 Hy-MT2（v3 报告 §149 自述），不能推到通用模型；但"wrong-referent 随**输出 ID 数**增长，而非随只读邻文增长"这一机制是本轮宽邻文臂不增大输出包的依据。
- 固定 seed 与 `cache_prompt` 下，包组成未变的批输出与对照逐字相同（v6 §2.1）。本轮三个臂的**包组成（目标 ID 集合与顺序）必须完全相同**，配对才成立。
- 对照必须在与候选相同的包组成下同期重判（分数漂移 −0.012 与候选效应同量级，v7 §2.1）；裁判 `claude-opus-5-5-mqm-v1`，每包 4 窗、同一 run、包组成与 run 无关。
- dev 集：v4 根目录 `.local/translation-evaluation/hy30-flow-v4/` 的 44 场景、5397 条（6 部剧集、4 部电影），只读复用；主 seed 20261011–13，重复 seed 20261021–23。
- v3、v4、v5（剧集）确认集已开封；电影确认集材料已被 v4 用尽，**新的确认只能建剧集隔离集**（v5 §7 盘点）。本轮不建确认集（§5）。
- `translation_v3.Recipe` 加字段必须保持已有配方 hash 不变（默认值不进 `spec()`，`test_recipes.AdoptedBaselineTest`）。冻结的 C0／joint 提示文本不改。
- 产品 `kototoki/` 的翻译配方为 `dp10-cut-degrade-v1`；本轮只在实验包评测，是否进产品另行裁定（§8）。

### 2.2 Qwen 侧（来自 names 阶段，可直接复用的身份与数字）

- 资产：`assets.toml` 的 `qwen3.8-27b-ud-iq3_s`（`unsloth/Qwen3.8-27B-GGUF`，revision `4ca72078…`，文件 `Qwen3.8-27B-UD-IQ3_S.gguf`，12,040,883,104 bytes，SHA256 `d847e2c1…`），本机 `.local/models/glossary-v1/`，已下载并校验。
- 引擎：产品官方 llama.cpp 构建（`assets.toml` 登记 b11669 win-cuda-13.4），经 `kototoki/llama_server.py` 的 `ManagedServer`／`ServerSpec` 启动；names 的 server 参数 `layers 99`、`-b 512 -ub 512 -fa on --jinja --reasoning off`、context 20480、`min_free_mib 13000`。
- 采样（Qwen 官方 non-thinking）：`temperature 0.7、top_p 0.8、top_k 20、min_p 0`；names 另加 `presence_penalty 1.5`，原因是第一轮发现**贪心解码会无限重复**。
- 显存与速度：IQ3_S 峰值 13.4–13.9 GB（桌面约 1 GB 之外），提示 2024 tok/s、生成 51–53 tok/s；整片 13–15K tokens 提示下峰值不升。
- 结构化输出：names 用 `/v1/chat/completions` 的 `response_format: json_schema`，两次 attempt、seed 递增；全部一次接受。
- Hy-MT2 与 Qwen 各占 12–15 GB，**不能共驻**；两个 llama-server 串行，`.local/gpu.lock` 规则照旧。

### 2.3 产品时间轴与研究集时间轴不同

同 v7 §2.3：本轮全部在 dev 集（字幕组时间轴）上比较；产品时间轴上的包更小、停顿更多，Qwen 的相对表现是否相同不在本轮范围，§8 列为未覆盖。

## 3. 本轮要回答的问题

1. **Q1 同接口下换模型**：同样的 dp10-cut 包、同样的 1＋≤10＋1 可见范围、同样的 ID JSON 输出，Qwen3.8-27B IQ3_S 相对 Hy-MT2 的全集 accuracy（剧集、电影分开）是明显更差、非劣，还是更好；fluency、wrong-referent、mistranslation、omission、cue-attribution 各自的方向。
2. **Q2 同模型下放宽只读邻文**：Qwen 从 1＋1 邻文放大到前 20＋后 5 条（输出包不变）之后，相对 Qwen 窄邻文臂的 accuracy 与 wrong-referent 方向；只读邻文内容是否泄漏进译文。
3. **Q3 代价**：每 run 墙钟与生成 tok/s、提示 token 量、显存峰值、JSON 不合规／重试／降级次数、交付完整性，与 Hy-MT2 对照并列。
4. **Q4 该怎么写结论**：按 §5 的判定规则给出三种之一——"Qwen 在本接口下明显更差，线关闭"／"非劣但无改善，不值 3 倍墙钟，线关闭，重开条件 X"／"某臂在某类别或某维度显著更好且 accuracy 非劣，建议进入 L3（重复 seed＋剧集确认集），交用户裁定"。

成功的定义是**四个问题都有带区间或明确计数的答案**；Q1 若两个 Qwen 臂都在 L1 门被关闭，Q2 只报 smoke 与单 seed 数字即可。

## 4. 已定的设计（2026-10-21 讨论结论，执行者不再重选）

### 4.1 三个臂

| 臂 | 模型／引擎 | 切包与输出 | 只读邻文 | 提示 |
| --- | --- | --- | --- | --- |
| `dp10-cut`（对照） | Hy-MT2 APEX-I-Compact，compat 引擎，不变 | dp10-cut | 前 1＋后 1 | `joint-understanding-v1`，不变 |
| `qwen-narrow` | Qwen3.8-27B UD-IQ3_S，官方 b11669 构建 | **与对照完全相同的包**，同 ID JSON 契约 | 前 1＋后 1 | `qwen-joint-v1`（§4.2） |
| `qwen-wide` | 同上 | 同上 | **前 20＋后 5**（场景边界截断；可见条数上限随之放开，只对本臂） | 同上 |

- 一轮**只有这两个候选臂**，不追加（不扫邻文网格，不试其他量化、其他通用模型、其他采样）。
- 宽邻文是"切包之后再附加邻文"：切包算法仍按 dp10-cut 的参数（含 `max_visible 12`）决定目标 ID；邻文范围与可见上限只在渲染阶段对 `qwen-wide` 放开。执行者必须核对三个臂每个场景的批次目标 ID 序列逐字相同，不同则是实现错误，不是结果。
- 只读邻文仍然只读：grammar 的目标 ID 集合不变，邻文不进输出。

### 4.2 Qwen 的提示与请求：`qwen-joint-v1`

- 形状：chatml `system`＋`user` 两段，经 `--jinja` 模板渲染，`--reasoning off`（不出思考段）。**内容是 Hy-MT2 joint 提示的最小改写**：把 C0／joint 提示里的任务说明、JSON 输入结构（只读 `context` 与待译 `translate` 两组条目、ID、日文）、共同理解与逐 ID 归属句、"保留原文歧义和信息揭示顺序"原样搬到 system／user；不加额外角色设定、示例、风格要求或专名表。执行者定最终措辞并版本化进 `recipe_hash`。
- 输出契约与对照相同：每个目标 ID 按原顺序各出现一次、值非空。执行者在"把现有 GBNF grammar 原样传给 chat completions"与"等价的 `response_format: json_schema`"之间二选一并在票据说明理由；无论哪种，校验（ID 全集、顺序、非空、无多余键）与对照共用同一段代码。
- 采样：Qwen 官方 non-thinking `temperature 0.7、top_p 0.8、top_k 20、min_p 0`，`presence_penalty 0`；seed 与 run seed 相同，`cache_prompt true`，相同请求最多两次（第二次 seed＋1，与 names 相同），两次都失败按 dp10-cut 的降级规则处理并计数。
- context：`qwen-narrow` 8192、`qwen-wide` 16384（前 20＋后 5 邻文加 ≤10 条目标远在预算内）；`n_predict` 4096 与对照相同。显存峰值记录在每个 session 的 `engine-final.json`。
- **允许的唯一一次调整**只在 smoke 票据里（§5）：若出现无限重复或空白循环，把 `presence_penalty` 改为 1.5（names 的值）；若出现思考段、日文原样照抄、英文或繁体，修 system 提示一次。调整后的版本进 hash，筛选不再改。

### 4.3 实现落点

- `translation_v3`：`Recipe` 加 `model: str | None = None`（`None` 不进 `spec()`，旧 hash 不变；值 `"qwen3.8-27b-ud-iq3_s"`），`prompt` 新值 `"qwen-joint"`，宽邻文用现有 `context_before／context_after` 加一个只对渲染生效的可见上限覆盖（字段名由执行者定，默认值不进 hash）。Qwen 的 server 启动走 `kototoki/llama_server.py`（与 names 同款 `ServerSpec`），Hy-MT2 仍走 `translation_v3/server.py`；session 记录两种引擎各自的身份（引擎 SHA、模型 SHA、命令行）。
- 内置配方：`qwen-narrow`、`qwen-wide`，都以 `dp10-cut` 为 base。
- 驱动、同包重判、配对比较复用 `experiments/scene_batching_v6`（`--round v9`，根目录 `.local/general-model-translation-v9/`；`judge-control`、`judge --candidate-only`、`compare --against`、`pooled` 原样可用）。
- 离线测试随同交付：已有配方 hash 不变；`qwen-joint-v1` 渲染快照；请求形状（采样字段、schema／grammar、seed）；三个臂的批次目标 ID 相同；宽邻文的截断与可见上限。
- 冻结代码只导入不修改；`kototoki/` 只被导入（`llama_server`），不改。

### 4.4 终点

- **主终点**：全集 accuracy Δ（每条 cue 的惩罚差，候选 − 对照；剧集、电影分开，作品等权，窗口 bootstrap CI90），`qwen-narrow` 对 `dp10-cut`、`qwen-wide` 对 `dp10-cut`、`qwen-wide` 对 `qwen-narrow` 三组配对。
- **分项**：fluency（grammar、unnatural、register 分开）；wrong-referent、mistranslation、omission、cue-attribution、negation-number-condition；critical、major+。
- **专名（次要）**：裁判注释里涉及人名／称呼的错误计数（执行者从错误注释按关键词抽取，方法写进票据，不新建裁判 profile）；若 dev 集按作品可算，用 `experiments/name_consistency/apply_table.py measure` 的不一致率口径各报一次（不做替换）。
- **泄漏检查（`qwen-wide`）**：译文里出现只读邻文独有的实体或数字而目标日文没有的 cue 比例，执行者定检测规则（可先用邻文 cue 的中文参考做字符串重叠）并对命中项人工读 20 条分类（真泄漏／合理补全／误报）。
- **人工阅读**：主 seed 上 `qwen-narrow` 与 `dp10-cut` 配对差绝对值最大的 20 个包（剧集、电影各 10），执行者逐包读并归类"Qwen 更好／Hy 更好／各有问题／裁判争议"，比例进 §7，不引用原文到本文。
- **代价**：每 run 墙钟、载入时间、生成 tok/s（从 server 日志或 completion 计时）、提示与输出 token 总量、显存峰值、重试与降级次数、交付失败。

## 5. 判定纪律、预算与停止条件

- 判定纪律沿用 [v5 §3](2026-10-16-quality-exploration-v5.md)：对照固定 dp10-cut（本轮新生成）；裁判 `claude-opus-5-5-mqm-v1` 不改；三 seed 起谈质量；作品为聚类单位；剧集与电影分开；筛选与确认分离；成本与失败随结果一起记；未知值不填 0；隐私边界不变。
- **票据顺序与门**：
  1. **01 离线实现**（无 GPU）：§4.3 全部代码与测试；三臂批次相同的核对脚本；预算与接跑手册进 map。
  2. **02 smoke（GPU，≤10 分钟）**：dev 里任取 5 个包（剧集 3、电影 2），`qwen-narrow` 与 `qwen-wide` 各渲染并生成一次，人工检查 JSON 合规、无思考段、无重复循环、无日文照抄、语言为简体中文、邻文未进输出。本票允许 §4.2 的那一次调整。不合规且调整一次后仍不合规 → 该臂关闭。
  3. **03 L1 门（GPU＋裁判）**：主 seed 20261011 生成三臂各 1 run（Hy 约 5 分钟，Qwen 各约 17 分钟，另加载入），全集裁判三套（约 90 包／套，约 $30 标价），三组配对。**关门规则**（对每个 Qwen 臂独立判）：剧集与电影两类 accuracy Δ 的 CI90 下界都 > 0（两类都显著变差），**或**任一类 CI90 下界 > 0.05（超出非劣界的显著变差）且另一类无显著改善 → 该臂关闭。两个 Qwen 臂都关闭 → 结题。
  4. **04 L2 筛选（GPU＋裁判）**：未关闭的臂与对照补 seed 20261012、20261013（每 seed 对照 1 run＋存活臂各 1 run），全集裁判，三 seed 合并。非劣界 0.05（每类 CI90 上界 < 0.05）；"改善"只在每类 CI90 上界 < 0 时写。
  5. **05 结题**：§7 表、§8 待裁定；索引登记；tracker 收尾。
- **预算上限**：GPU dev run 总数 ≤ 10（含 smoke 折算 1 个）；裁判标价 ≤ $100；Claude 配额耗尽（退出码 75）时转离线票据或停下。超出上限即以现有数据结题并注明。
- **不做的事（本轮明确排除，列入 §8 的重开条件）**：自由文本输出与译后回填／重切时间轴；跨 cue 重排或合并（v8 已关闭，重开前提是说话人信息）；把专名表注入 Qwen 提示（ADR-0013／0014 冻结线的边界，等 Qwen 裸翻译非劣后另立项）；提示搜索（smoke 之后不改提示）；更高比特量化（本卡放不下）、其他通用模型、思考模式；任何多样本再挑选方法（ADR-0008）；重复 seed 复现与确认集（L3，须用户另行批准）；改产品。
- 无人值守原则同 v5：中途不请求用户裁定，需要裁定的事项集中到 §8；GPU 票据按 tracker 顺序跑，`.local/gpu.lock` 规则照旧，启动前用 `Get-Process` 核实无其他 llama-server／GPU 作业。

## 6. 执行载体与记录协议

- tracker：`.scratch/general-model-translation-v9/{spec.md,map.md,issues/NN-*.md}`，按 [tracker 约定](../agents/issue-tracker.md)；map 含接跑手册（GPU 只读核对、状态以文件为准、配额处理、每票提交）。票据顺序见 §5。
- 代码：`experiments/translation_v3`（配方字段、`qwen-joint-v1`、Qwen 请求与 server 接入）、`experiments/scene_batching_v6`（`--round v9`）；新文件放这两处，不新建实验包，除非 Qwen 请求代码超过一屏且与 v3 其余部分无关（届时 `experiments/translation_v3/qwen.py`）。
- 产物根目录 `.local/general-model-translation-v9/`；复用 `.local/translation-evaluation/hy30-flow-v4/` 的集合与参考只读。
- 每完成一张票据：票据写 Answer 并 resolved → map 的 Decisions-so-far 加一行 → 本文 §7 更新 → 提交 Git。结题时在[调研索引](INDEX.md)的时间线加一行并更新本文的索引条目；若结论涉及[技术设计](../specs/bilingual-subtitle-pipeline.md)或 ADR，只在 §8 提出，不自行改。

## 7. 进度与结论

票据在 `.scratch/general-model-translation-v9/issues/`（Git 忽略），数字均可回溯到 `.local/general-model-translation-v9/` 下的 JSON。区间为 CI90，Δ 为每条 cue 的惩罚差（候选 − 对照）。

| 日期 | 票据 | 结果 |
| --- | --- | --- |
| 2026-10-21 | 01 离线实现 | 完成。`translation_v3`：`Recipe.model`（`qwen3.8-27b-ud-iq3_s`，须配 `prompt="qwen-joint"`）与 `wide_context`（`wide-context-v1`，渲染期按条数取邻文到场景边界、不看静默）；`qwen.py`：`qwen-joint-v1` 为 Hy joint 提示任务文字**原样**拆成 system（说明）／user（只读上下文＋待译 JSON），对照的 ID GBNF 原文作 chat completions 的 `grammar`，预算在 `/apply-template` 渲染结果上计（context − 4096 − 64），校验共用 `parse_translation` 再加键顺序，两次失败按同一 harness 计场景未交付；server 用产品 `ManagedServer`（names 同款参数）加 v3 GPU 锁与 Job Object。`scene_batching_v6 --round v9`（`v9.py`：派发生成、`check-batches`、`smoke`、`judge-run`、`compare9`）。18 个旧内置配方 hash 不变（`dp10-cut` `ee72ce66…`），新 `qwen-narrow` `d878d2d1…`、`qwen-wide` `719237b9…`；dev 44 场景 621 包三臂目标 ID 序列逐字相同；离线测试新增 22 项，四个实验包 157 项全部通过。 |
| 2026-10-21 | 02 smoke（GPU） | 通过，**不调整**（`presence_penalty` 0、`qwen-joint-v1` 不变，hash 不变）。主 seed 块 5 个包（剧集 3、电影 2）× 两臂：10／10 第一次接受，键顺序正确，无思考段（`reasoning_content` 空）、无重复循环、无日文照抄、简体中文、只读邻文未进输出；一次 grammar 探针证实 chat 端点执行 GBNF `grammar`；`/apply-template` 计数与 `usage.prompt_tokens` 相等，首请求 `cache_n` 0。实测载入约 5 s、生成 59.5 tok/s、显存峰值 13128／13513 MiB。观感：两臂都有个别专名错（wide 把一处主角名、一处配角名写错，narrow 正确）。计 1 个 GPU run。 |
| 2026-10-21 | 03 L1 门（GPU＋裁判） | **两个 Qwen 臂都未关门，且单 seed 上两类都显著更好。** 主 seed 块（14 场景、1844 cue、218 包）三臂各 1 run，批次目标 ID 逐字相同，全部一次交付、无重试；全集裁判 3×93 包、$29.72。accuracy Δ（对照水平剧集 0.507、电影 0.489）：narrow 剧集 −0.091［−0.176, −0.008］、电影 −0.178［−0.271, −0.086］；wide −0.162［−0.243, −0.081］、−0.160［−0.252, −0.073］；wide − narrow 剧集 −0.071［−0.138, −0.005］、电影 +0.018［−0.052, +0.089］。下降的是 mistranslation、addition、wrong-referent（电影）、major+、critical；**unnatural 上升**（narrow 剧集 +0.040［+0.022, +0.059］），cue-attribution 三臂均 0。专名相关裁判错误 24／29／28 条（对照／narrow／wide），不一致率 0.048／0.044／0.039。泄漏：wide 标记率 3.4%／4.2% 不高于对照 4.0%／4.9%（同一检测），wide 独有 19 条人工分为真泄漏 0、合理补全 4、误报 15。人工阅读 |Δ| 最大 20 包：Qwen 更好 17、Hy 更好 2、裁判争议 1（裁判方向与阅读一致 19／20）；Hy 失分集中在极性反转、主语指代、方言与片假名误读，Qwen 的问题是翻译腔。代价：墙钟 294／847／913 s（2.9×／3.1×），生成 194／60／60 tok/s，输入 token 141K／150K／293K，显存峰值 15875／12740／13249 MiB，载入 5–8 s。累计 GPU 4 run、裁判 $29.72。 |
| 2026-10-21 | 04 L2 筛选（GPU＋裁判） | 两臂与对照补 seed 20261012、20261013（6 个 run，全部一次交付、无重试，三臂目标 ID 逐字相同），全集裁判 6 套；三 seed 合并覆盖整个 dev（44 场景、5397 cue、15 部作品），对照水平剧集 0.418、电影 0.424。**qwen-wide − dp10-cut：剧集 −0.058［−0.104, −0.010］、电影 −0.091［−0.152, −0.028］**（两类都显著改善，约 −14%／−21%；15 部作品中 12 部为负）；qwen-narrow − dp10-cut：−0.020［−0.067, +0.029］、−0.034［−0.097, +0.031］（非劣、无改善）；qwen-wide − qwen-narrow：−0.038［−0.074, −0.002］、−0.057［−0.108, −0.006］。wide 的改善来自 wrong-referent（−0.035／−0.038，都显著）、mistranslation（总览 −0.034 显著）、addition、major+（−0.009／−0.011，都显著）；critical、negation-number-condition 无差；**unnatural +0.019／+0.014 显著变差**、电影 omission +0.011 变差、cue-attribution 电影 +0.003。专名相关裁判错误每千 cue 对照 12.3／19.7、narrow 18.4／20.7、wide 14.3／16.6，不一致率无一致方向。泄漏标记率 wide 3.5%／4.0% 不高于对照 3.6%／4.4%。代价（三 run 合计）：墙钟 824／2517／2695 s（narrow 3.05×、wide 3.27×），生成 194／60／60 tok/s，输入 token 411K／439K／847K，显存峰值 15.9／12.7／13.2 GB。单 seed 的 L1 效应（−0.09～−0.18）补满后回落约一半。累计 GPU 10／10 run、裁判 9 套 816 包 $87.41。 |
| 2026-10-21 | 05 结题 | 结论按 §3 Q4 第三种写法（§7.1）；§8 已填；索引登记。提交签名（1Password）全程报错，改动暂存未提交（§8 第 0 项）。 |

### 7.1 结论

**Q4：`qwen-wide`（Qwen3.8-27B UD-IQ3_S，前 20＋后 5 只读邻文）在 dp10-cut 同一接口下，剧集与电影的 accuracy 都显著好于 Hy-MT2 且非劣，建议进入 L3（重复 seed 20261021–23 复现＋新建剧集隔离确认集），交用户裁定。** `qwen-narrow` 非劣但无改善。

- **Q1 同接口换模型**：同包、同 1＋1 邻文、同 ID JSON 下，Qwen 与 Hy-MT2 的 accuracy 非劣（剧集 −0.020、电影 −0.034，区间跨 0）。方向：wrong-referent（电影）与 addition 显著更好，mistranslation、negation-number-condition 无差；fluency 中 **unnatural 显著变差**（剧集 +0.030、电影 +0.014），grammar 无差，register 略好；omission 电影小幅变差；cue-attribution 两臂都几乎为 0。人工阅读（主 seed，|Δ| 最大 20 包）17 包 Qwen 更好、2 包 Hy 更好、1 包裁判争议：Hy 的失分集中在极性反转、主语／指代错、方言与片假名误读，Qwen 的问题是翻译腔与生硬直译。
- **Q2 放宽只读邻文**：对 Qwen 有效——wide 相对 narrow 两类都显著改善（−0.038／−0.057），主要是 mistranslation，unnatural 也略降；omission 剧集 +0.006。这与 v3 在 Hy-MT2 上"ctx3 无效"相反，说明那条结论确实只适用于 Hy-MT2。邻文没有泄漏进译文：同一检测下 wide 的标记率不高于对照，主 seed 上 wide 独有的 19 条命中人工分类为真泄漏 0、合理补全 4、误报 15。
- **Q3 代价**：墙钟 3.05×（narrow）／3.27×（wide），生成 60 对 194 tok/s；wide 输入 token 约 2 倍，但 prefill 很快，墙钟只比 narrow 多 7%。显存峰值 12.5–13.2 GB，低于 Hy-MT2 的 15.9 GB（余量更大）。JSON 不合规、重试、降级、交付失败全部为 0（9 个 run、1962 次请求）；smoke 证实 chat 端点执行 GBNF grammar。
- **专名（次要）**：名称相关裁判错误在 wide 与对照之间无一致方向（剧集略多、电影略少），不一致率同样无一致方向——世界知识的预期优势在本轮数据上没有显现。
- **局限**：只有 dev 筛选（三 seed 各覆盖一个场景块，每场景一次实现），没有重复 seed 与确认集；裁判是 LLM（`claude-opus-5-5-mqm-v1`），通用 LLM 的译文风格是否被同类裁判偏爱没有独立检验——人工阅读支持方向，但只看了 20 包且由子 agent 读、主会话抽查 1 包；L1 单 seed 的效应量补满后回落约一半，L3 的复现很可能继续收缩；产品时间轴未覆盖（§2.3）。

## 8. 待用户裁定

立项时的默认立场：没有任何臂在 accuracy 上非劣且某维度显著改善，就不进入 L3，线关闭，重开条件是新的本卡可跑的通用模型或更高比特量化。本轮 `qwen-wide` 满足"非劣且显著改善"，所以默认立场不适用，以下交用户裁定：

0. **Git 提交未完成**：01 起每次提交都因签名报错（`1Password: failed to fill whole buffer`），执行者没有绕过签名。本轮全部代码与文档（`experiments/translation_v3/{recipes,batching,generate,qwen,test_qwen}.py`、README，`experiments/scene_batching_v6/{__main__,v9,test_v9}.py`、README，本文与 INDEX.md）已暂存或在工作区，请解锁 1Password 后提交（`.claude/settings.json` 的改动不属于本轮）。
1. **是否进入 L3**：重复 seed 20261021–23 上 `qwen-wide` 与 dp10-cut 各 3 run（GPU 6 run、裁判约 $60）独立复现；复现成立后新建剧集隔离确认集（电影确认材料已被 v4 用尽，电影只能以 dev 证据为准）。执行者建议进入：效应两类都显著、作品层面 12／15 为负、人工阅读方向一致，但单 seed 到三 seed 已回落一半，需要复现确认不是裁判风格偏好。可考虑在 L3 加一次非 LLM 或人工的盲比较，回答"同类裁判偏爱通用模型译文"的疑问（需新建版本化 profile，v5 §3）。
2. **3.3 倍翻译墙钟是否可接受**：产品整片翻译约 200 s（ADR-0011）→ 估 650 s；names 阶段已加载同一模型，若翻译也用 Qwen，可省去 Hy-MT2 的加载并与 names 共用一个 server（显存 13 GB，余量好于 Hy 的 15.9 GB），但这是产品架构变化，需单独设计。
3. **unnatural 上升**：Qwen 的翻译腔是稳定的反方向信号（三 seed 两类都显著）。若进入 L3，是否允许一次针对自然度的提示修订（本轮按 §5 禁止提示搜索）——默认不允许，先复现。
4. **是否立项"专名表注入 Qwen 提示"**：本轮专名指标无一致方向；ADR-0013／0014 的冻结线边界不变，建议等 L3 结论后再议。
5. **自由文本／重排路线**：本轮不涉及，保持关闭（v8 结论）。
6. **产品时间轴复算**：dev 是字幕组时间轴；若进入产品，需在产品 `ja.srt` 上复算包大小分布与 wide 邻文的实际条数（离线即可）。
7. **是否改动基线或产品**：本轮不改 ADR-0005／0010／0011 与 `kototoki/`；采纳与否只在 L3 之后讨论。
