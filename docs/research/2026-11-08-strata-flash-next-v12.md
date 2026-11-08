# 字幕翻译流程第十二轮（v12）：翻译模型换成 Strata＋Qwen3.8-Flash-Next（IQ3_S），对照 Q1

状态：执行中（2026-11-08：01 完成；02 曾因 MTP 草稿层需下载而暂停，用户已裁定 §8 第 4 项为 (a) 允许下载，续跑）。立项：planned（2026-11-08 起草；同日用户裁定立项，**含阶段 E**，预算按 §5 合计 10 run／$115；§8 第 2 项的旧锁已按用户指示删除）。  
范围：只换 Q1 最后一步翻译所用的模型和推理引擎，其余不变：切包、邻文、提示、专名表注入、采样都与 Q1 相同。候选为 Strata 0.2.12（引擎 build 0.1.58）上的 Qwen3.8-Flash-Next GSQ-RCO IQ3_S。对照一律是 **Q1**（[ADR-0016](../adr/0016-q1-translation-baseline.md)）。不改产品 `kototoki/`，不改任何基线身份（新基线由用户在 §8 裁定后另写 ADR），不开封确认集。  
执行载体：tracker 目录 `.scratch/strata-flash-next-v12/`（spec、map、票据；Git 忽略）。**本文是唯一进 Git 的进度与结论记录。**  
先读：[Strata 用法调研](2026-11-08-strata-flash-next-usage.md)全文；[ADR-0016](../adr/0016-q1-translation-baseline.md)；[v11 研究文档](2026-10-22-q0-product-route-v11.md)的 §2.3、§4.0、§5、§7.1；`experiments/translation_v3/qwen.py`（请求、校验、重试）、`recipes.py`（`QWEN_MODEL`、`_check_model`、hash）；`experiments/scene_batching_v6/asr10.py`、`names11.py`、`v11.py`（产品 ASR 源与 dev 设施）。

本文的对照、终点、门与预算在起草时定下（§4、§5）。执行者只补实现细节，例如字段名和 adapter 的结构，并在票据里说明理由。

## 1. 为什么做这一轮

- 用户在本机装好了 Strata 和 Qwen3.8-Flash-Next（IQ3_S）。按供应方说法，这个模型比 Q1 用的 Qwen3.8-27B UD-IQ3_S 更强，而 IQ3_S 量化"与完整模型相当"。本项目没有验证过这两点。
- v9–v11 的经验是，Q 线的提升主要来自模型本身：v9 换 Qwen 后 dev 两类 accuracy 都显著好于 Hy-MT2；提示类改动多数非劣无改善，或者此消彼长。所以换更强的模型是值得测的方向。
- 换引擎带来一个 Q1 没有的风险：Strata **没有 GBNF 语法约束**，ID JSON 的格式只能靠提示和事后校验保证。格式失败会直接变成交付失败，所以它与质量一样是主终点。
- Strata 实测 decode 约 106 tok/s，但内存峰值 51 GB、显存 15.6 GB（见调研 §2）。墙钟和资源占用要一起记录，作为日后是否进产品的依据。

## 2. 已知事实（不要重复）

### 2.1 对照 Q1 与已有材料

- **Q1**＝Q0（`qwen-wide`：dp10-cut 切包、前 20 后 5 只读邻文、可见上限 35、`qwen-joint-v1`、non-thinking、context 16384、采样 0.7／0.8／20／0、presence 0）＋只注入 `confidence: high` 的专名表（`qwen-name-table-v1`，`filter: window`），没有事后替换。
- **Q1 的译文已经存在，本轮不再生成对照**：
  - 产品 ASR 源（HF II／III，seed 20261054–56）：`q0-names-high`，hash `c10e143a…`；配方在 `.local/q0-product-route-v11/C/root/recipes/q0-names-high.json`，译文在 `.local/q0-product-route-v11/C/zh/q0-names-high/`。
  - dev（44 场景、5397 cue，seed 20261011–13）：`qwen-names-dev-high`，hash `9c444d3c…`；配方在 `.local/q0-product-route-v11/recipes/`，run 在 `.local/q0-product-route-v11/runs/qwen-names-dev-high__s*__dev/`。dev 表在 `.local/q0-exploration-v10/E/dev-name-tables.json`。
- v11 的数字（Q1 自身的已知表现）：产品上对 Q0＋替换全体 −0.050［−0.116, +0.020］，人名错误 72，不一致率 0.027；dev 上对 Q0 两类 accuracy 显著变差，原因是 dev 表的错条目（用户已知并接受）。
- 噪声底：同 seed、同 prompt 的 llama-server 输出约有 24% 的单元不同（v11 §8 第 5 项）。

### 2.2 Strata 的约束（详见调研文档）

- 引擎是 Strata 自研的原生引擎，不是 llama-server；`kototoki.llama_server.ManagedServer` 不能启动它。实验代码只能附着到已经运行的服务。
- 没有 GBNF，没有 `/apply-template`、`/tokenize`。
- `top_k` 上限 64；`seed` 须为正整数；每个请求都要显式带 `enable_thinking: false`。
- 运行时几乎占满显存和内存，不能与 llama-server 同时驻留。

### 2.3 评测设施（沿用 v11，不改 profile）

- **产品 ASR 源**：v5 第 02 步的单元与分桶（exact 811、light 510、heavy 407；missed 不判），配对裁判 `v5-asr-pairwise-v1`（x＝对照、y＝候选，同 seed、同一 packet 内比较，不需要同期重判）。普查 1728 单元，一个比较约 $9。`asr10` 已在 v11 参数化了根目录与 seed。
- **dev**：裁判 `claude-opus-5-5-mqm-v1`，全集一套约 $10。**对照必须同期重判**：Q1 的 3 个 dev run 在本轮重新判。裁判看得到参考中文。
- 人名相关错误、不一致率的统计沿用 v11（`names11.py`、`asr10.inconsistency`）。
- 送裁判前先 diff，只判文本不同的单元。两臂模型不同，预计几乎所有单元都不同，但规则照旧。

## 3. 本轮要回答的问题

1. **Q1 可行性**：不用 grammar 时，Flash-Next 能否稳定输出合法的 ID JSON？首次尝试的格式失败率是多少，两次都失败（交付失败）的比例是多少？思考是否完全关闭？同 seed 能否复现？
2. **Q2 dev 质量**：在 dev 3 seed 上，F1 对 Q1 是否两类非劣，有没有哪一类显著改善？
3. **Q3 产品质量**：在产品 ASR 源 seed 54–56 上，F1 对 Q1 是否非劣或改善？人名错误与不一致率如何？
4. **Q4 代价**：整片墙钟、每包延迟、内存与显存峰值，与 Q1 相比如何？
5. **Q5（条件）思考**：若 §8 第 3 项选择开启，Flash-Next 开有界思考相对 F1 有没有增量？
6. **Q6 结论写法**：F1 写三种之一——"优于 Q1，作为 Q 线新基线候选"／"非劣无改善"／"不进，原因 X"。

## 4. 设计

### 4.0 通用规则

- **候选臂 F1**（配方名 `flash-names-high`）：Q1 配方原样，只把模型换成 `qwen3.8-flash-next-iq3_s`（Strata），并做调研 §5 表中的必要改动：不发 `grammar`，不做 `/apply-template` 预算检查，首请求缓存检查只记录不判失败，每个请求带 `enable_thinking: false`。专名表与 Q1 完全相同：产品用 v11 `q0-names-high.json` 里的表，dev 用 v11 `qwen-names-dev-high.json` 里的表。
- **F1 的身份**：新模型 id 与 Strata 身份（`strata --version`、引擎 build、`strata launch --status --output json` 中的 context／drafting／parallel／kv）写进 `qwen.versions()`。旧配方的 hash 必须不变，要有测试保证。
- **Strata 的启动参数固定为**调研 §3 的 `kototoki-translate` 预设：`--context 32k --parallel 1 --vision off --drafting mtp --access local --no-api-key --tune skip`。整轮不改；如果非改不可，写进 §8，不自行调参。
- seed：产品 20261054–56，dev 20261011–13，与 Q1 已有材料逐 seed 配对。
- 区间为 window bootstrap CI90（dev 作品等权，剧集与电影分开；产品沿用 `asr10._boot`），Δ＝F1 − Q1，数值越小越好。
- 非劣界：dev 每类 accuracy CI90 上界 <0.05；产品全体每单元惩罚 CI90 上界 ≤0.05。只有 CI90 上界 <0 时才写"改善"。
- **交付失败的计法**：两次尝试都失败的包，其 cue 在产品比较里按 v11 的 `delivery_failures` 计（交付失败的单元判为候选输），并单独报告数量。不允许为了让 F1 交付而加第三次尝试或改提示。

### 4.1 阶段 A：离线实现（无 GPU）

- **01 实现**：
  - `experiments/translation_v3` 加 Strata 后端：附着式 session（不启动服务；核对 `/v1/models` 和 launch 状态；持有 v3 `gpu.lock`；记录 Strata 身份）、F1 的请求体、无 grammar 的校验与重试路径。
  - 生成 F1 配方的小工具：读 v11 的 Q1 配方，换模型后写到 `.local/strata-flash-next-v12/recipes/`。
  - `scene_batching_v6` 加 `--round v12`（根目录 `.local/strata-flash-next-v12/`）。
  - 离线测试：旧配方 hash 不变；F1 请求体不含 `grammar`／`cache_prompt`、含 `enable_thinking: false`；格式失败走重试。可以用 `strata serve --engine mock` 起假引擎做客户端端到端测试（不占 GPU、不加载模型）。

### 4.2 阶段 B：smoke 与可行性门（GPU，短会话）

- **02 smoke**：
  1. 按调研 §3 先 `--plan`，确认下载量为 0，再启动 `kototoki-translate` 预设。
  2. 跑 dev 的 3 个场景（取 v11 smoke 用过的场景），seed 20261011，跑两遍。
  3. 记录：首次格式失败率、交付失败、`reasoning_tokens`、`reasoning_recoveries`（若暴露）、两遍之间不同的包占比、每包延迟、内存与显存峰值。
- **可行性门（通过才进 C）**：
  - 交付失败为 0；
  - 首次尝试格式失败率 ≤5%；
  - 所有请求的思考输出为空；
  - 没有出现非有限 logits 截断。
- 不通过时不进 C、D。结论写"Strata 路线当前不可用，原因 X"，可能的修复写进 §8，例如改用 `response_format: json_schema`（它会改提示，须另立项）。不在本轮内修。

### 4.3 阶段 C：dev 质量（GPU）

| 票据 | 臂 | 对照 | 终点 | 门 |
| --- | --- | --- | --- | --- |
| **03** | F1 dev 3 seed（20261011–13）；另把 s20261011 再跑一遍，只做 A/A diff，不送裁判 | Q1 的 3 个 dev run，本轮同期重判 | 剧集、电影各自的 accuracy、unnatural、wrong-referent；人名相关错误；dev 不一致率；格式与交付失败；墙钟；A/A 不同单元占比 | **非劣**＝两类 accuracy CI90 上界 <0.05，且两类 wrong-referent CI90 下界 ≤0。**改善**＝非劣，且至少一类 accuracy CI90 上界 <0 |

- **C → D 的阻断**：两类 accuracy 的 CI90 **下界都 >0**（两类都显著变差）时，不跑 D，直接结题。其他情况一律进 D。
- dev 上 Q1 的对照本身带表错误（ADR-0016 后果第 2 条），所以人名错误按"F1 − Q1"报告即可，不另设门。

### 4.4 阶段 D：产品 ASR 源（GPU，seed 20261054–56）

| 票据 | 臂 | 对照 | 终点 | 门 |
| --- | --- | --- | --- | --- |
| **04** | F1 产品三 seed（HF II／III 整片，产品 `name-table.json` 的 high 条目注入，与 Q1 同表） | Q1（v11 `q0-names-high` 的译文） | 全体与 exact／light／heavy 各桶 Δ、人名错误、不一致率、critical／addition、交付失败、墙钟 | **非劣**＝全体 CI90 上界 ≤0.05，且交付失败 0，且人名错误差 CI90 上界 ≤0，且不一致率不高于 Q1 ＋0.01。**改善**＝非劣，且全体 CI90 上界 <0 |

### 4.5 阶段 E：有界思考（条件触发）

- 用户已裁定开启本阶段（§8 第 3 项）。触发条件：C 与 D 的结论至少是非劣。
- **05**：F2＝F1＋思考，每个请求 `enable_thinking: true` 且 `thinking_budget_tokens`＝1024，`max_tokens` 相应加 1024；不需要 v10 的思考前缀 grammar，因为本来就没有 grammar。只跑 dev 3 seed，对照为 F1（同期判）。
- 门：两类 accuracy 至少一类 CI90 上界 <0，另一类上界 <0.05，且墙钟 ≤2× F1。不过门就写"不进"。
- 产品上不跑 E；E 过门时写进 §8，由用户决定是否补产品验证。

## 5. 判定纪律、预算与停止条件

- 判定纪律沿用 v11 §5：两个裁判 profile 不改；剧集与电影分开；dev 对照同期重判；成本与失败随结果一起记；未知值不填 0；专名表、样例、译文属于转写内容，不进 Git 与日志。
- 阶段顺序 A → B → C → D →（E）。B 不过就停；C 的阻断规则见 §4.3。
- **资源互斥**：Strata 运行期间不得有任何 llama-server。每张 GPU 票据开跑前，用 PowerShell `Get-Process` 核实没有 llama-server、没有其他 GPU 作业，也没有其他 Strata 实例，并读 `.local/gpu.lock`；不抢占、不杀进程。票据结束后执行 `strata launch --stop`，并核实显存已释放。
- **预算上限**（GPU run：dev 一个 seed 块记为 1；产品两部整片一个 seed 记为 1）：

  | 阶段 | GPU run | 裁判标价 |
  | --- | --- | --- |
  | A | 0 | $0 |
  | B | smoke（<30 分钟，按次计） | $0 |
  | C | 4（3 seed＋A/A 1） | $65（F1 三套＋Q1 同期重判三套，含余量） |
  | D | 3 | $15 |
  | E（条件） | 3 | $35 |
  | **合计** | **10（不含 E 为 7）** | **$115（不含 E 为 $80）** |

  某阶段超限，就用已有数据给出该阶段的结论。裁判配额耗尽（退出码 75）时转做离线票据，没有可做的就停下，并写明停在哪里。
- **全轮停止条件**：B 的可行性门不过即停；C 两类都显著变差即停（不跑 D）。
- **不做的事**：
  - 改切包、邻文、提示、专名表或采样（只换模型）；调 Strata 的引擎参数或重新调优；
  - 多样本再挑选（ADR-0008），以及加第三次尝试或格式修复重试；
  - 用 `response_format` 或自写约束解码绕开"没有 grammar"的问题；
  - 换量化档（IQ3_XXS、Swift 1.5 等）或换模型；
  - 改 `kototoki/` 或任何 ADR、改基线身份；开封确认集；
  - 用 Flash-Next 重建专名表（建表仍是产品 names 阶段）；
  - 新增方向（想法写进 §8）。
- 无人值守：中途不请求用户裁定，需要裁定的事集中写进 §8。

## 6. 执行载体与记录协议

- tracker：`.scratch/strata-flash-next-v12/{spec.md,map.md,issues/NN-*.md}`，按 [tracker 约定](../agents/issue-tracker.md)。map 写接跑手册、预算台账和 Decisions-so-far。票据清单：

  | NN | 票据 | 阶段 | GPU |
  | --- | --- | --- | --- |
  | 01 | 离线实现：Strata 附着后端、F1 配方工具、`--round v12`、测试 | A | 否 |
  | 02 | smoke 与可行性门 | B | 是（短） |
  | 03 | dev 3 seed＋A/A＋Q1 同期重判 | C | 是 |
  | 04 | 产品 ASR 源 3 seed | D | 是 |
  | 05 | 有界思考（条件触发） | E | 是 |
  | 06 | 结题：§7.1 结论、§8、索引登记 | — | 否 |

- 代码放在 `experiments/translation_v3`（新后端与选项，旧配方 hash 不变）和 `experiments/scene_batching_v6`（`--round v12`）。`kototoki/` 只导入、不改。
- 产物根目录 `.local/strata-flash-next-v12/`。v11 的产物（`.local/q0-product-route-v11/`）只读复用。
- 每完成一张票据，依次做：
  1. 票据写 Answer，状态改为 resolved；
  2. map 的 Decisions-so-far 加一行；
  3. 本文 §7 加一行；
  4. 提交 Git（本文、`docs/research/INDEX.md`、`experiments/` 下本轮代码与 README）。签名失败不绕过，记在 §8 第 0 项。
- 结题时在[调研索引](INDEX.md)的时间线加一行。新基线的身份和 ADR 只在 §8 提出。

## 7. 进度与结论

票据在 `.scratch/strata-flash-next-v12/issues/`（Git 忽略）。数字都能回溯到 `.local/strata-flash-next-v12/` 下的 JSON。每行写明对照。

| 日期 | 票据 | 结果 |
| --- | --- | --- |
| 2026-11-08 | 01 离线实现 | 完成。`translation_v3/strata.py`：F1 请求体不带 `grammar`／`cache_prompt`、每个请求带 `enable_thinking`（思考时加 `thinking_budget_tokens`，`max_tokens`＋预算）；无 `/apply-template`／`/tokenize`，输入长度取 `usage.prompt_tokens`，超 Q1 预算只标记；首请求缓存只记录；格式失败按原规则换 seed＋1 重试一次。附着式 session：持 v3 `gpu.lock`，核对 `strata --version`、`launch --status` 与 run config（本机、模型名、32k、无 vision）、`/v1/models`、`/v1/status`（32k、单并发），固定身份进配方 hash，kv／drafting 等观测值记在 session；会话中采样整机显存／内存峰值。Strata 的 chat 响应**不回** `reasoning_tokens`／`reasoning_recoveries`，改记 `reasoning_content` 字符数，并统计 server log 中"推理循环自救"与"非有限 logits"的行数。Strata 配方上两次都失败的包只让它自己的 cue 未交付（§4.0），场景继续；Hy-MT2／Qwen 配方行为不变。配方：F1 dev `60bd457f…`、F1 产品 `a2075b25…`、F2 `903d1cad…`；Q1 hash 复算不变（`9c444d3c…`、`c10e143a…`），`qwen-wide` 不变。`--round v12`（recipes、copy-q1、smoke、smoke-report、stats、generate-aa、aa、product12）。smoke 取 v11 smoke 5 个场景中的 2 个剧集＋1 个电影整场。测试 `translation_v3` 88 项、`scene_batching_v6` v6–v12 66 项通过；`strata serve --engine mock` 客户端端到端（不占 GPU）走通重试与交付失败路径。GPU 0。 |
| 2026-11-08 | 02 smoke 与可行性门 | **未开跑，停在启动前（§8 第 4 项）。** 开跑前核对通过（无 llama-server／Strata／其他 GPU 作业，无 gpu.lock，显存基线 1.5 GB）。调研 §3 固定参数的 `strata launch --plan` 显示**需下载约 5.2 GB（MTP 草稿层）**：本机 `D:\Strata\Strata-data\` 下没有 `mtp/`（旧 `iq3_s-128k` run config 指向的 `mtp\rt` 不存在），只有 DFlash2 草稿器（823 MB）。按授权"下载量不为 0 即停"，未启动 Strata；改 drafting 会改 §4.0 固定的启动参数，不自行改。03–06 都被 02 阻断，本轮暂停。GPU 0、裁判 $0。 |
| 2026-11-08 | 02 smoke 与可行性门（续跑） | **门通过，进 C。** 用户裁定 §8 第 4 项 (a) 后启动 `kototoki-translate`（首次下载 MTP 草稿层约 5 GB，加载约 60 s），`probe` 核对通过（0.2.12／build 0.1.58、本机、32k、kv int8、MTP spec 4、单并发、无 vision）。v11 smoke 的 2 个剧集＋1 个电影场景整场，seed 20261011，跑两遍各 45 包：首次格式失败 **0／90**、交付失败 0、`reasoning_content` 全空、限长停止 0、server log 推理自救 0、非有限 logits 0、超 Q1 预算 0。每包耗时均值 3.28／3.20 s（p90 3.75／3.65 s），接受输出约 64–65 tok/s，墙钟 149／145 s。峰值显存 16.1 GB，**整机内存峰值 63.5 GiB（共 63.9 GiB）**。同 seed 两遍：包 84%、cue **44%** 文本不同（Q1 的 llama-server 约 24%）。结束后 `strata launch --stop`，显存回到 1.0 GB。GPU：smoke 2 次（不计 run）。 |
| 2026-11-08 | 03 C：dev 3 seed＋A/A＋Q1 同期重判（GPU＋裁判） | **改善：两类 accuracy 都显著变好，进 D。** 对照 **Q1**（`qwen-names-dev-high` `9c444d3c…`，v11 的 3 个 run 复制后同期重判）；候选 F1 `flash-names-high`（`60bd457f…`）s20261011–13 新生成，全集 5397 cue。送裁判前 diff：两臂相同 cue 1041（19%），无整包相同，复制 0 包，相同 cue 按 Δ＝0 计入。accuracy 剧集 **−0.186［−0.231, −0.142］**、电影 **−0.126［−0.173, −0.078］**；wrong-referent 剧集 −0.003［−0.019, +0.012］、电影 −0.010［−0.035, +0.014］（下界都 ≤0）；unnatural 剧集 −0.020［−0.028, −0.011］、电影 −0.008［−0.017, +0.001］；mistranslation 剧集 −0.157、电影 −0.104，addition、omission、major+ 两类都小幅显著下降。15 部中 14 部变好（W06 +0.023）。人名相关错误 78 对 98（剧集 45 对 58、电影 33 对 40）；dev 不一致率 0.014 对 0.017（剧集 0.015 对 0.008 变高，电影 0.014 对 0.025 变低）。交付失败 0；621 包首次失败 1（一包被 Strata 的**重复截断**——同一 token 连续 256 次即以 length 结束——截住，重试后接受；调研未记录这一自动行为，已加入 log 计数），思考输出 0、推理自救 0、非有限 logits 0。墙钟 600–702 s 对 Q1 850–978 s（快约 29%），每包均值约 3.2 s，显存峰值 16.1 GB，整机内存峰值 62.9 GiB。**A/A**（s20261011 重跑）：cue 49%、包 86% 文本不同（Q1 的 llama-server 约 24%）。GPU 4（C 4／4）、裁判 $57.56（F1 $28.12、Q1 $29.43；C $57.56／$65）。 |

### 7.1 结论

**尚无结论（本轮暂停，未结题）。** F1 没有生成任何译文：票据 02 在启动 Strata 之前停下（§7、§8 第 4 项），Q1–Q6 都还没有数据，不能写成三种结论之一。§8 第 4 项裁定后从票据 02 续跑，结题时在这里填写。

## 8. 待用户裁定

开跑前须定：

1. **立项与预算**：已裁定（2026-11-08）。按 §5 立项，含阶段 E，上限 GPU 10 run、裁判 $115。
2. **`.local/gpu.lock` 的旧锁**：已处理（2026-11-08）。锁里记的是 2026-10-23 的一次产品运行（pid 35460），删除前再次核实该进程已不存在，之后按用户指示删除。
3. **阶段 E（有界思考）**：已裁定（2026-11-08）为开，触发条件见 §4.5。

执行中产生的裁定项由执行者追加在下面（第 0 项留给提交签名问题）。

0. **提交签名**：无问题（票据 01、02 记录正常签名提交）。
4. **MTP 草稿层需要下载，票据 02 未能开跑（阻断全轮）**。调研 §3 的固定启动参数含 `--drafting mtp`，`strata launch --plan` 显示要先下载约 5.2 GB 的 MTP 草稿层；本机只有 DFlash2 草稿器（`D:\Strata\Strata-data\dflash2\`，823 MB），旧 run config 引用的 `mtp\rt` 目录不存在（调研 §2 写"现有 run config 用的就是 MTP"，但当时没有核实文件在磁盘上）。可选：
   - (a) **允许下载 MTP 草稿层**（约 5.2 GB，由 `strata launch` 首次启动时下载；之后 `--plan` 应为 0），其余不变，按原计划跑。最贴近立项设计。
   - (b) **改用 `--drafting dflash2`**（`auto` 的 dry-run 同为 DFlash2，下载 0）。需修订 §4.0 的固定参数与 F1 身份（`strata.LAUNCH_FLAGS` 进配方 hash，改代码后重写 F1／F2 配方）；DFlash2 与 MTP 的速度、显存、同 seed 复现性可能不同。
   - (c) **`--drafting off`**：不用投机解码，最慢，但排除草稿器对复现性的影响。同样要修订 §4.0。

   裁定后从票据 02 接着跑：代码与配方已就绪；选 (b)／(c) 时先改 `strata.LAUNCH_FLAGS` 并重写 F1／F2 配方。

   **已裁定（2026-11-08）：(a) 允许下载 MTP 草稿层**，其余参数不变，从票据 02 续跑。
5. **后续（本轮不做）：DFlash2 与 MTP 的代价对比**。本机已有 DFlash2 草稿器，`--drafting auto` 在 Flash-Next 上默认选它；调研 §2 关于"现有配置用 MTP、DFlash2 需另下载"的判断与磁盘实况相反。用户 2026-11-08 同意本轮保持 MTP 跑完（投机解码原理上只影响速度、不改输出分布，但 Strata 的实现未验证；中途换会作废已跑部分并改变 F1 身份）。建议另立小项：同一批包分别用 MTP 与 DFlash2 跑，比较每包耗时、显存／内存峰值（DFlash2 草稿器约多 0.8 GB，而本轮显存峰值已 16.1／16.3 GB、整机内存 63.5／63.9 GiB）、格式失败与 A/A 复现性，再定产品默认用哪个。

## 附：执行提示词（粘贴到新 session）

```text
按 docs/research/2026-11-08-strata-flash-next-v12.md 无人值守执行第十二轮（v12）。先读该文"先读"一行列出的文件和 docs/research/2026-11-08-strata-flash-next-usage.md。
授权：本轮 GPU 作业（Strata 启停：strata launch --plan / --preset kototoki-translate 或文中给定的参数 / --stop；票据 02–04，以及满足 §4.5 触发条件时的 05）与裁判调用，预算以文档 §5 为上限。不得运行 strata update，也不得进行任何会下载文件的 launch（--plan 显示下载量不为 0 时停下，写进 §8）。
规则：中途不问我，需要裁定的事写进 §8；按 §6 的记录协议逐票据提交；每张 GPU 票据开跑前核实没有 llama-server、没有其他 GPU 作业或 Strata 实例，并读 .local/gpu.lock，不抢占、不杀进程；结束后 strata launch --stop。门、对照、预算与"不做的事"以文档为准，不自行修改。子 agent 显式指定 model（默认 sonnet）。
完成标准：§7 每张票据有一行；§7.1 给出 F1 的结论（三种写法之一）；§8 列出待裁定项；调研索引时间线登记。
```
