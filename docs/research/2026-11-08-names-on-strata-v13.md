# 专名建表第十三轮（v13）：建表模型换成 Strata＋Qwen3.8-Flash-Next，对照现行 27B 建表

状态：planned（2026-11-08 起草；同日用户裁定立项，预算按 §5）。本轮重开已结题的专名研究线（[ADR-0014](../adr/0014-name-consistency-in-product.md)），由用户明确要求。
范围：只换产品 `names` 阶段建表所用的模型和推理引擎，其余不变：提示 v5、程序兜底、采样、预算、两次尝试规则都与现行 `BUILD` 配方相同。候选为 Strata 0.2.12（引擎 build 0.1.58）上的 Qwen3.8-Flash-Next IQ3_S，启动方式与 Q2 相同（不加参数的 `strata launch`，子进程里写作 `strata launch --no-tui --model iq3_s`，DFlash2）。对照一律是现行建表（Qwen3.8-27B UD-IQ3_S，llama-server）。翻译一律用 **Q2** 规则（[ADR-0017](../adr/0017-q2-strata-default-launch-baseline.md)），两臂只差注入的专名表。不改产品 `kototoki/`，不改任何 ADR 或基线身份（§8 由用户裁定后另写 ADR），不开封确认集。
执行载体：tracker 目录 `.scratch/names-on-strata-v13/`（spec、map、票据；Git 忽略）。**本文是唯一进 Git 的进度与结论记录。**
先读：[ADR-0014](../adr/0014-name-consistency-in-product.md)、[ADR-0017](../adr/0017-q2-strata-default-launch-baseline.md)、[ADR-0019](../adr/0019-product-translation-q2.md)；[专名一致性模块页](../architecture/modules/name-consistency.md)；[Strata 用法调研](2026-11-08-strata-flash-next-usage.md)；[v12 研究文档](2026-11-08-strata-flash-next-v12.md)的 §2、§4.0、§5、§6、§7；[v11 研究文档](2026-10-22-q0-product-route-v11.md)的 §7 票据 02 与 §8 第 4 项；代码 `kototoki/names/table.py`（`build_table`）、`kototoki/names/recipes.py`、`experiments/translation_v3/strata.py`、`experiments/scene_batching_v6/{names10,names11,asr10,v12}.py`。

本文的对照、终点、门与预算在起草时定下（§4、§5）。执行者只补实现细节（字段名、adapter 结构），并在票据里写明理由。

## 1. 为什么做这一轮

- 产品里 names 和 translate 用两套推理服务：建表用 llama-server 跑 27B，翻译用 Strata 跑 Flash-Next。统一到 Strata 后可以去掉 27B 权重、llama.cpp 运行时和 `ManagedServer` 启停代码，两阶段共用一个 Strata session，也消掉"停 llama-server → 等显存、等内存释放 → 启 Strata"这一步交接。2026-11-08 整片变慢的起因之一就在这一步。
- 建表配置是 ADR-0014 冻结的研究结论，换模型会改变注入行，也就是 Q2 的一个输入。所以要先证明 Flash-Next 建的表**不差**，再谈切换。
- v11 已经证明效果完全取决于建表质量：表对，注入后人名错误减少；表错，注入会放大错误（dev 表 high 条目 34% 与参考多数不一致）。v12 证明 Flash-Next 在翻译上明显强于 27B，但建表（实体抽取、写法覆盖、confidence 判断）没有测过。

## 2. 已知事实（不要重复）

### 2.1 对照（现行 27B 建表）与已有材料

- **现行 `BUILD` 配方**（`kototoki/names/recipes.py`，`BUILD_RECIPE_HASH`）：提示 `build-table-prompt-v5`、schema `name-table-v2`，no-think，采样 temperature 0.7／top_p 0.8／top_k 20／min_p 0／presence_penalty 1.5，`max_tokens` 4096，context 20480，提示预算＝20480−4096−512（system＋user 两段 token 之和），`response_format: json_schema`，两次尝试（seed、seed＋1），`[names] seed` 默认 20261019。整片 `ja.srt` 一次送入（剥时间轴、带 cue 编号）。
- **对照的表已经存在，本轮不再用 27B 建表**：
  - 产品 ASR 源（HF-II／HF-III）：`.local/name-consistency-product/after/{HF-II,HF-III}/name-table.json`（产品 names 阶段建出；v11、v12 用的就是它，HF-II 20 条、HF-III 15 条，high 写法 28／26）。
  - dev（15 部作品、44 场景）：`.local/q0-exploration-v10/E/dev-name-tables.json`（v10 用产品 `build_table` 按场景拼接建表，seed 20261019，15／15 `ok`，201 条）。
- v11 票据 02 的 dev 表质量数字（对照自身）：表与参考中文的一致率，出现加权 0.65；198 条中 73 条多数不一致；high 117 条中 40 条（34%）不一致；confidence 几乎不预测正确性。方法在 `names11.table_reference_agreement`。

### 2.2 Strata 的约束（详见调研文档与 v12）

- 没有 GBNF，没有 `/apply-template`、`/tokenize`。能"渲染模板并计 token"的只有 Anthropic 方言的 `/v1/messages/count_tokens`。
- `response_format` 的 `json_object`／`json_schema` 是"提示＋事后校验"：会改动 messages，失败即报错、不重试。所以它不是约束解码，开了等于换提示。
- `top_k` 上限 64；`seed` 须为正整数；每个请求显式带 `enable_thinking: false`。
- 同 seed 跨启动不可复现（v12 A/A：cue 49% 不同）。表按身份缓存，建一次即固定，但两次建表可能不同。
- 运行时显存约 16 GB、专家区常驻内存约 47 GiB，启动前要约 52 GiB 可用内存（ADR-0019），不能与 llama-server 同时驻留。
- 子进程里不加参数的 `strata launch` 会走交互向导、以退出码 2 拒绝；`strata launch --no-tui --model iq3_s` 与不加参数的计划逐行相同（产品 `kototoki/translate/strata.py` 就这样启动）。`strata` 在 PATH 上是 PowerShell 脚本，Python／Git Bash 要调 `strata.cmd`。
- chat 响应不回 reasoning token 数；思考是否发生要看 server log（v12 票据 01 的做法），本轮也看 `message.reasoning_content` 是否为空。

### 2.3 评测设施（沿用 v11／v12，不改 profile）

- 产品 ASR 源：v5 第 02 步的单元与分桶（exact 811、light 510、heavy 407），配对裁判 `v5-asr-pairwise-v1`（x＝对照、y＝候选，同 seed、同一 packet 内比较）。人名错误、不一致率沿用 `asr10`。
- dev：裁判 `claude-opus-5-5-mqm-v1`，一套约 $10；两臂都是本轮新生成，同期判。人名相关错误沿用 `v9.NAME_ERROR` 口径。
- 送裁判前先 diff，只判文本不同的单元；相同单元按 Δ＝0 计入。

## 3. 本轮要回答的问题

1. **Q1 可行性**：现行建表配方原样搬到 Strata（不用 `response_format`）能否稳定建出合法的表？`ok`／`failed`／`too_long` 的分布，首次尝试解析失败率，思考是否完全关闭？采样参数（尤其 `presence_penalty`、`min_p`）Strata 是否接受？`/v1/messages/count_tokens` 能否替代 `/tokenize` 做预算检查？
2. **Q2 表质量**：在 dev 上，Flash-Next 表与参考中文的一致率是否不差于 27B 表？high 条目的错误率呢？产品两部片子的表与 27B 表有多大差异，同 seed 重建是否稳定？
3. **Q3 翻译质量（dev）**：Q2 翻译分别注入两种表，Flash-Next 表是否两类非劣？
4. **Q4 翻译质量（产品 ASR 源）**：同上，在 seed 54–56 上是否非劣？人名错误与不一致率如何？
5. **Q5 代价**：每部建表耗时、显存与内存峰值，与 27B 建表相比如何？
6. **Q6 结论写法**：S1 写三种之一——"可替代 27B 建表，且更好"／"可替代（非劣）"／"不进，原因 X"。

## 4. 设计

### 4.0 通用规则

- **候选臂 S1**（建表配方名 `names-strata-v1`）：现行 `BUILD` 配方原样，只做以下必要改动：
  - 模型换为 Strata 上的 `qwen3.8-flash-next-iq3_s`，启动方式同 Q2；
  - **不发 `response_format`**：与 v12 同理，它会改提示；格式完全靠提示 v5 本身的说明加 `parse_reply` 事后校验，失败按现行规则换 seed＋1 重试一次；
  - 每个请求带 `enable_thinking: false`；
  - 预算检查：`tokenize` 回调改用 `/v1/messages/count_tokens`，对 system、user 两段各数一次再相加，预算数值不变（20480−4096−512）。该端点不可用或口径对不上时，退回"不预检、只用 `usage.prompt_tokens` 事后记录、超预算标记"，并在票据写明；不得因此放宽预算。
- **建表入口**：直接调用产品 `kototoki.names.table.build_table(document, chat, tokenize, seed)`（导入、不改），`chat`／`tokenize` 两个回调接到 Strata。dev 表的场景拼接方式与 v10 `names10.py` 完全相同。
- **S1 的身份**：Strata 身份（`strata --version`、引擎 build、launch 状态中的 context／drafting／kv）与"不发 `response_format`"一起写进 S1 配方并参与 hash；现行 `BUILD_RECIPE_HASH` 必须不变，要有测试保证。
- **翻译**：两臂都用 Q2 规则（`qwen-wide`＋只注入 `confidence: high` 的专名表，`qwen-name-table-v1`，`filter: window`；模型同 Q2，启动同 Q2），只换注入的表。Q2 配方用现成的 `scene_batching_v6/v12.py` `strata_recipe_data(q1, …, launch="default")` 组出（`qwen_options.strata_launch: "default"`，附着与身份核对已在 `translation_v3/strata.py` 实现；ADR-0017 指出的缺口"给定 `name-table.json` → 写出 Q1 配方"本轮在 01 补上）。对照臂 T0＝Q2＋27B 表，候选臂 T1＝Q2＋S1 表，**两臂都在本轮新生成**（Strata 不可复现，且 v12 F1 是 MTP 启动，不是 Q2 身份）。
- seed：建表用 `[names] seed` 20261019（与对照相同）；翻译 dev 用 20261011–13，产品用 20261054–56，两臂逐 seed 配对。
- 区间为 window bootstrap CI90（dev 作品等权、剧集与电影分开；产品沿用 `asr10._boot`；表质量按作品重抽），Δ＝候选 − 对照。
- **交付失败**：翻译两次尝试都失败的包，其 cue 在产品比较里按 v11 的 `delivery_failures` 计（判候选输），单独报告数量。不加第三次尝试、不改提示。

### 4.1 阶段 A：离线实现（无 GPU）

- **01 实现**：
  - 建表的 Strata 回调：`chat`（请求体按现行 `_request_body`，去掉 `response_format`、加 `enable_thinking: false` 与 `model`），`tokenize`（`/v1/messages/count_tokens`），附着式 session 沿用 v12（核对 `/v1/models` 与 launch 状态、持 v3 `gpu.lock`、记录 Strata 身份与资源峰值）。
  - 给定任意 `name-table.json`（dev 按作品、产品按片）写出 Q1／Q2 配方的小工具（ADR-0017 的已知缺口；现有 `product_tables`／`nstar_tables` 只读固定来源）；`scene_batching_v6` 加 `--round v13`（根目录 `.local/names-on-strata-v13/`），含 dev 建表、产品建表、表质量统计、两臂翻译、比较。
  - 离线测试：`BUILD_RECIPE_HASH`、Q1 与 v12 各配方 hash 不变，用 27B 表组出的 Q2 配方与 v12 规则逐字段一致；S1 建表请求体不含 `response_format`、含 `enable_thinking: false`；解析失败走重试；可用 `strata serve --engine mock` 做客户端端到端（不占 GPU、不加载模型）。

### 4.2 阶段 B：建表与可行性门（GPU，短）

- **02 建表**：
  1. 先 `strata launch --plan`，确认下载量为 0，再启动（Q2 启动方式）。
  2. 产品 HF-II、HF-III 各建表**两次**（同 seed 20261019，第二次只做 A/A 稳定性比较，正式使用第一次的表）；dev 15 部各建表一次。
  3. 记录：每部的 `build.status`、尝试次数、首次解析失败、`reasoning_content` 字符数、prompt／completion token、耗时、显存与内存峰值；采样参数是否被接受（被拒或被静默忽略都要记）；count_tokens 与 `usage.prompt_tokens` 的差。
- **可行性门（通过才进 C）**：
  - 17 部全部 `ok`（对照在这 17 部上全是 `ok`）；
  - 首次尝试解析失败 ≤2／17；
  - 所有请求的思考输出为空；
  - 采样参数全部被接受（任一被拒即不过门：改采样属于改配方，不在本轮）。
- 不过门时停在这里，结论写"Strata 建表当前不可用，原因 X"，可能的修复（如开 `response_format`、调采样）写进 §8，本轮不修。

### 4.3 阶段 C：表质量（离线，无 GPU、无裁判）

| 票据 | 比较 | 终点 | 门 |
| --- | --- | --- | --- |
| **03** | dev：S1 表对 27B 表，均用 `names11.table_reference_agreement` 与参考中文比 | 出现加权一致率；high 条目不一致率；条目数、high 数、种类分布；"配角映射成主角名""姓氏漏字"这类串名条目数（按 v11 票据 02 的判据逐条看） | **非劣**＝出现加权一致率差 CI90 下界 ≥ −0.05，且 high 不一致率差 CI90 上界 ≤ +0.05。**改善**＝非劣，且一致率差 CI90 下界 >0 |
| | 产品：S1 表对 27B 表（无参考，只作描述） | 条目与 high 写法数；与 27B 表的 ja→zh 写法重合率；A/A 两次建表的写法重合率 | 无门 |

- **C → D／E 的阻断**：一致率差的 CI90 **上界 <0**（显著变差）时，不跑 D、E，直接结题。其他情况一律进 D 与 E。

### 4.4 阶段 D：dev 翻译（GPU）

| 票据 | 臂 | 对照 | 终点 | 门 |
| --- | --- | --- | --- | --- |
| **04** | T1＝Q2＋S1 dev 表，3 seed（20261011–13） | T0＝Q2＋27B dev 表，同 3 seed，本轮新生成、同期判 | 剧集、电影各自的 accuracy、unnatural、wrong-referent；人名相关错误；dev 不一致率；交付失败；墙钟 | **非劣**＝两类 accuracy CI90 上界 <0.05，且两类 wrong-referent CI90 下界 ≤0。**改善**＝非劣，且至少一类 accuracy CI90 上界 <0 |

### 4.5 阶段 E：产品 ASR 源翻译（GPU，seed 20261054–56）

| 票据 | 臂 | 对照 | 终点 | 门 |
| --- | --- | --- | --- | --- |
| **05** | T1＝Q2＋S1 产品表（HF-II／III 整片，只注入 high） | T0＝Q2＋27B 产品表，同 seed，本轮新生成 | 全体与 exact／light／heavy 各桶 Δ、人名错误、不一致率、critical／addition、交付失败、墙钟 | **非劣**＝全体 CI90 上界 ≤0.05，且交付失败 0，且人名错误差 CI90 上界 ≤ +0.005（约 1728 单元中多 9 个），且不一致率不高于对照 ＋0.01。**改善**＝非劣，且全体 CI90 上界 <0 |

- 人名错误的界写成 +0.005 而不是 v12 的 ≤0：本轮问的是"能否替代"，是非劣检验；v12 的 ≤0 在非劣意义上过严，已被用户认定为边界噪声。
- D 与 E 互不阻断，顺序先 D 后 E。

## 5. 判定纪律、预算与停止条件

- 判定纪律沿用 v11 §5、v12 §5：两个裁判 profile 不改；剧集与电影分开；同期判；成本与失败随结果一起记；未知值不填 0；专名表、样例、译文都是转写内容，不进 Git 与日志。
- 阶段顺序 A → B → C → D → E。B 不过就停；C 的阻断规则见 §4.3。
- **资源互斥**：本轮不需要 llama-server（对照表已存在）。每张 GPU 票据开跑前，用 PowerShell `Get-Process` 核实没有 llama-server、没有其他 GPU 作业、没有其他 Strata 实例，并读 `.local/gpu.lock`；不抢占、不杀进程。启动前确认可用内存 ≥52 GiB，不够就停下，写进 §8（不关用户的程序）。票据结束后执行 `strata launch --stop`，并核实显存已释放。Strata 启动后须确认专家区全部锁进内存（引擎日志 `expert arena: locked` 且没有退到 mmap，判法同 `kototoki/translate/strata.py`）；退到 mmap 时停掉，写进 §8。
- **预算上限**（GPU run：dev 一个 seed 块记为 1；产品两部整片一个 seed 记为 1；建表整批记为 1）：

  | 阶段 | GPU run | 裁判标价 |
  | --- | --- | --- |
  | A | 0 | $0 |
  | B | 1（建表 19 次，预计 <30 分钟） | $0 |
  | C | 0 | $0 |
  | D | 6（两臂各 3 seed） | $65（6 套，含余量） |
  | E | 6（两臂各 3 seed） | $15 |
  | **合计** | **13** | **$80** |

  某阶段超限，就用已有数据给出该阶段的结论。裁判配额耗尽（退出码 75）时转做离线票据，没有可做的就停下，写明停在哪里。
- **全轮停止条件**：B 可行性门不过即停；C 显著变差即停（不跑 D、E）。
- **不做的事**：
  - 改提示 v5、程序兜底、采样、`max_tokens`、预算、两次尝试规则；开 `response_format` 或自写约束解码；开思考；
  - 改翻译（Q2 规则）或注入规则（只注入 high）；
  - 多次建表再挑选、多样本翻译再挑选（ADR-0008）；A/A 的第二次建表只用于稳定性比较，不得替换正式表；
  - 换量化档、换模型、调 Strata 引擎参数或重新调优；
  - 改 `kototoki/`、任何 ADR 或基线身份；改 `experiments/name_consistency/`（冻结，只读）；开封确认集；
  - 用 27B 重新建表；
  - 产品化（names 与 translate 共用 session、删 llama.cpp 依赖）：本轮只回答"表能否替代"，产品改动在 §8 裁定后另做；
  - 新增方向（想法写进 §8）。
- 无人值守：中途不请求用户裁定，需要裁定的事集中写进 §8。

## 6. 执行载体与记录协议

- tracker：`.scratch/names-on-strata-v13/{spec.md,map.md,issues/NN-*.md}`，按 [tracker 约定](../agents/issue-tracker.md)。map 写接跑手册、预算台账和 Decisions-so-far。票据清单：

  | NN | 票据 | 阶段 | GPU |
  | --- | --- | --- | --- |
  | 01 | 离线实现：建表 Strata 回调、任意表→Q2 配方、`--round v13`、测试 | A | 否 |
  | 02 | 建表与可行性门（产品 2×2、dev 15） | B | 是（短） |
  | 03 | 表质量（dev 对参考、产品描述） | C | 否 |
  | 04 | dev 翻译 T1／T0 各 3 seed＋同期判 | D | 是 |
  | 05 | 产品 ASR 源翻译 T1／T0 各 3 seed＋配对判 | E | 是 |
  | 06 | 结题：§7.1 结论、§8、索引登记 | — | 否 |

- 代码放在 `experiments/scene_batching_v6`（`--round v13`、建表 Strata 回调、任意表→Q2 配方）；若须改 `experiments/translation_v3`，旧配方 hash 不变。`kototoki/` 只导入、不改。
- 产物根目录 `.local/names-on-strata-v13/`。`.local/name-consistency-product/`、`.local/q0-exploration-v10/`、`.local/quality-exploration-v5/`、`.local/q0-product-route-v11/`、`.local/strata-flash-next-v12/` 只读复用。
- 每完成一张票据，依次做：
  1. 票据写 Answer，状态改为 resolved；
  2. map 的 Decisions-so-far 加一行；
  3. 本文 §7 加一行；
  4. 提交 Git（本文、`docs/research/INDEX.md`、`experiments/` 下本轮代码与 README）。签名失败不绕过，记在 §8 第 0 项。
- 结题时在[调研索引](INDEX.md)的时间线加一行。产品切换与基线的处理只在 §8 提出。

## 7. 进度与结论

票据在 `.scratch/names-on-strata-v13/issues/`（Git 忽略）。数字都能回溯到 `.local/names-on-strata-v13/` 下的 JSON。每行写明对照。

| 日期 | 票据 | 结果 |
| --- | --- | --- |

### 7.1 结论

（结题时填写：S1 的结论按 §3 Q6 的三种写法之一，并逐问回答 Q1–Q5。）

## 8. 待用户裁定

开跑前须定：

1. **立项与预算**：已裁定（2026-11-08）。按 §5 立项，上限 GPU 13 run、裁判 $80。

结题后须定（执行者在结论里给出建议）：

2. **产品是否把建表切到 Strata**：若 S1 结论为"可替代"或"更好"，另写 ADR 替代 ADR-0014 的建表模型与 ADR-0019 的"两种服务不同时驻留"做法；names 与 translate 共用一个 Strata session，删除 llama.cpp 依赖与 27B 资产。
3. **Q2 基线的处理**：S1 表改变了 Q2 的注入输入。可选：(a) Q2 定义不变，只是表的来源换成 Strata 建表（写进新 ADR）；(b) 另立新基线名。

执行中产生的裁定项由执行者追加在下面（第 0 项留给提交签名问题）。

0. **提交签名**：

## 附：执行提示词（粘贴到新 session）

```text
按 docs/research/2026-11-08-names-on-strata-v13.md 无人值守执行第十三轮（v13）。先读该文"先读"一行列出的文件。
授权：本轮 GPU 作业（Strata 启停：strata launch --plan / strata launch --no-tui --model iq3_s / strata launch --stop；票据 02、04、05）与裁判调用，预算以文档 §5 为上限。不得运行 strata update，也不得进行任何会下载文件的 launch（--plan 显示下载量不为 0 时停下，写进 §8）；不得启动 llama-server。
规则：中途不问我，需要裁定的事写进 §8；按 §6 的记录协议逐票据提交；每张 GPU 票据开跑前核实没有 llama-server、没有其他 GPU 作业或 Strata 实例，读 .local/gpu.lock，确认可用内存 ≥52 GiB，不抢占、不杀进程、不关我的程序；Strata 启动后确认专家区全部锁进内存，退到 mmap 就停下写进 §8；结束后 strata launch --stop 并核实显存释放。门、对照、预算与"不做的事"以文档为准，不自行修改。不改 kototoki/、ADR、基线身份与 experiments/name_consistency/。子 agent 显式指定 model（默认 sonnet）。
完成标准：§7 每张票据有一行；§7.1 给出 S1 的结论（三种写法之一）并回答 Q1–Q5；§8 列出待裁定项与建议；调研索引时间线登记。
```
