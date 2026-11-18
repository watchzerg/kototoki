# ADR-0021：翻译基线 Q3 与历史翻译身份

状态：已接受。2026-11-18 按主题合并（用户授权）：并入 ADR-0004、ADR-0005、ADR-0006、ADR-0009、ADR-0010、ADR-0011、ADR-0015、ADR-0016、ADR-0017、ADR-0018，原文见 git 历史（提交 807de3e 及之前）。  
范围：研究与测试用哪条翻译基线、它的翻译规则与建表配方、`dp10-cut` 切包规则（Q3 与产品共用），以及引用时须写明的前任与历史身份（Q2、Q1、Q0、F1、H0、C0、`b10-joint`、`dp6-grp` 与两个旧产品配方）。产品翻译配方 `q3-translate-v1` 见 [ADR-0029](0029-translate-per-cue-resolution.md)，产品建表配方 `q3-names-*` 见 [ADR-0028](0028-names-accept-empty-table.md)，本篇不重复定义。

## 决定

### 唯一基线 Q3

1. 翻译只保留一条基线：**Q3**。Q3＝Q2 的翻译规则不变，只换注入表的来源：表由 Strata 上的 Qwen3.8-Flash-Next 按 `names-strata-v4` 建，不再用 Qwen3.8-27B＋llama-server；建表与翻译用同一个 Strata 实例，同一 session 里先建表、再翻译。
2. Q2 是前任身份；Q1、Q0、F1、H0 及更早的流程配方只作历史对照身份（见[身份](#身份)），不再是基线，产品也不再使用。
3. 用户采纳时已知并接受：dev 剧集的 wrong-referent 显著变差、两次建表差别大（见[依据](#依据)）。

### 对照规则

1. 新的翻译测试都以 Q3 为对照；引用 Q2、Q1、Q0、F1 或 H0 作对照须写明并说明理由。
2. 各臂的批次目标 ID 序列必须逐字相同；切包即 [dp10-cut 切包](#dp10-cut-切包)，`check-batches` 照常可用。
3. 数字只在同一裁判 profile、同一数据集、同一 seed 块之间比较，不与 Codex 时代的 `sol-high-auto-v1` 分数混用。
4. 配方变化即出新配方与新 hash；名称后缀递增（Q4、H1…）须由用户裁定，不自动升级。
5. [ADR-0008](0008-no-multi-translation-selection.md) 适用。v3、v4、v5 的确认集已开封，新的确认须用全新隔离的集合。

### Q3 翻译规则

Q3 的翻译是**一条组配方的规则**，不是固定 hash：对每个输入先按 Q1 规则拼出配方，再做 Q2 的两处改动。

1. 基础配方 Q0＝`qwen-wide`：切包同 [dp10-cut 切包](#dp10-cut-切包)；只读邻文 `wide-context-v1`（前 20、后 5 条，只在场景边界截断，不看静默，可见上限 35）；提示 `qwen-joint-v1`（Hy joint 提示原样拆成 system 与 user 两条 chat 消息）。
2. 注入（Q1 规则）：`qwen_options.names = {"filter": "window", "tables": {work_id: rows}}`，表头 `qwen-name-table-v1`；`rows` 只取 `confidence: high` 实体，每个 `forms[]` 一行 `{source: form.ja, translation: form.zh}`，按 `ja` 去重，跳过 `ja` 或 `zh` 为空的写法；不做事后替换；不按输入来源（产品 ASR 源、dev 干净源）区分。
3. Q2 两处改动：`model` 为 `qwen3.8-flash-next-iq3_s`；`qwen_options` 加 `strata_launch: "default"`。
4. 采样与请求：temperature 0.7、top_p 0.8、top_k 20，seed 步长不变；chat completions，不用 grammar，思考关闭；每包最多两次（seed、seed＋1），两次都失败只空出该包的 cue，整片照常交付。

### Q3 建表

1. 建表配方 `names-strata-v4`（身份见 [Q3 身份](#q3-身份)），整片 `ja.srt` 一次送入。
2. 失败后最多到第 5 次请求：seed、seed＋1、…、seed＋4，取第一张合格的表即停，不在多张表里挑选。这是可靠性重试，不是"多次生成再挑选"。5 次都不合格时写空表，翻译照常、不注入。

### dp10-cut 切包

Q3 与产品翻译共用的切包规则（`gap-pack-v2`；研究侧配方 `dp10-cut`，产品实现 `kototoki/translate/batching.py` 的 `gap_pack_cuts`，同一 SRT 上逐字节相同）：

1. 每个场景（整片 SRT 是一个场景）用动态规划取总惩罚最低的切法，任意两条之间都可切。每包代价＝(条数 − 10)²＋包内每个 ≥2 s 停顿按秒数计分；<6 条的包加 1000 分；超过 10 条或包内有 ≥20 s 停顿不可行。
2. 分级切点：在 <0.5 s 的停顿处切加 6 分，<1 s 加 3 分，<2 s 加 1 分，≥2 s 不加；缺时间戳按无停顿（加 6 分）。停顿取自 `ja.srt` 自身时间轴，只比较长短。每批待译 ≤10 条。

### Q3 服务与运行顺序

1. 服务：Strata 0.2.12，引擎 build 0.1.58；默认启动在本机解析为模型 IQ3_S、上下文 128K、图片读取器放 CPU、并发按显卡自适配、草稿器 DFlash2（不用 MTP）、只允许本机、端口 8080。启动命令 `strata launch --no-tui --model iq3_s`（与默认启动计划逐行相同）。
2. 接入检查（`strata.probe(port, "default")`）：版本、8080 上只有一个 ready 的本机实例、run config 的模型名与 `--max-context 131072`、草稿器 DFlash2、`/v1/models`、`/v1/status` 原生上下文 131072，不符即拒绝；不检查 preset 名，不限制并发数。每次运行在 `runtime/session-NN/strata.json` 另记实际 run config 与并发数。
3. 运行顺序：核对没有 llama-server、没有别的 Strata launch 或 GPU 作业、可用内存 ≥52 GiB → 启动并做接入检查、确认专家区全部锁进内存 → 建表 → 翻译 → `strata launch --stop` 并核实显存已释放。全程不启动 llama-server、不加载 27B。

## 身份

### Q3 身份

- 建表 `names-strata-v4`（`archive/2026-11-18-pre-research-restructure:experiments/scene_batching_v6/v13.py` 的 `s1_recipe("v4")`），hash `38cb7bcda96534db70fb5823c05330cd212057058c381e88cadf756f26d308d0`。以当时产品 `BUILD` 为底：提示 `build-table-prompt-v5`、schema `name-table-v2`、no-think；采样 temperature 0.7／top_p 0.8／top_k 20／min_p 0／presence_penalty 1.5；程序兜底；`[names] seed` 20261019。改动：去掉 llama.cpp 模型资产；`max_tokens` 8192、context 24576、提示预算 15872；`attempts: 5`。请求：模型 `qwen3.8-flash-next-iq3_s`，不发 `response_format`，显式带 `chat_template_kwargs.enable_thinking: false`，提示预算用 `/v1/messages/count_tokens` 把 system、user 分别计数再相加。运行时身份进 hash：Strata 0.2.12、build 0.1.58、默认启动（`strata.DEFAULT_RESOLVED`）、KV `int8`。产品 `q3-names-v3` 与它的差别见 [ADR-0028](0028-names-accept-empty-table.md)。
- 翻译配方的 `recipe_hash` 记录"默认启动"及解析出的取值（`strata.DEFAULT_RESOLVED`）。任意一张 `name-table` 可用 `v13.write_q2` 组出 Q3 翻译配方；v13 输入上的实例（配方名 `q2-names-s1`）：dev 15 部 `eeba5a711e83547a2969b3132dda7bbe04e46a35b74a810f578100671812fe57`，产品 HF II／III `29fd7a6633dd59843af98e4a15f9d02739201d52a2bf541a2b565b255d763eda`。

### Q2（前任）

Q1 规则＋[Q3 翻译规则](#q3-翻译规则)第 3 点的两处改动，规则实现 `v12.py` 的 `strata_recipe_data(q1, name, comment, launch="default")`；表由当时产品的 27B＋llama-server 建（`BUILD_RECIPE_HASH` `5b8d1b76da757bb26aa3d3fb894c1963935a308b6ef4eb7c75edeaa2d44c9e50`），先建表、停掉 llama-server 后再启 Strata。v11 输入上的实例（只算出 hash）：产品 HF II／III `86b61ec93da4ad38fc0ff709bb973a8b659660ab6dc1b3be08f068b91be908b7`（由 `q0-names-high` 得到），dev 15 部 `4c3d0f70a94e43207dbe439893284d078993a041bf5ebb3dd378aefeb42b0499`（由 `qwen-names-dev-high` 得到）。

### Q1 与 F1（历史）

- **Q1**＝Q0＋[Q3 翻译规则](#q3-翻译规则)第 2 点的注入，表由当时产品 27B 建表；取法即 `names11.py` 的 `product_tables("high")`／`nstar_tables("high")`。实例：产品 HF II／III `q0-names-high` `c10e143a65c50277daede28a2f3d3e79adc0db53b1db6a4398e0c9f6720f30e8`；dev 15 部 `qwen-names-dev-high` `9c444d3c…`。
- **F1**：v12 候选，规则同 Q2，启动配置为 `kototoki-translate` 预设（上下文 32K、并发 1、关闭图片读取器、草稿器 MTP）。

### Q0（历史）

`archive/2026-11-18-pre-research-restructure:experiments/translation_v3` 的 `qwen-wide`，recipe_hash `719237b92c45c4d0f19971ece6b0944157c23ad2e33bbfe0644db60aabfcaef7`（`test_qwen.QwenRecipeTest` 固定）。模型 Qwen3.8-27B UD-IQ3_S（llama.cpp b11669）；采样 0.7／0.8／20、min_p 0、`presence_penalty` 0，non-thinking；ID GBNF 作为 `/v1/chat/completions` 的 `grammar` 字段；context 16384，输入预算 context − 4096 − 64；两次尝试，第二次 seed＋1。切包、邻文、提示同 [Q3 翻译规则](#q3-翻译规则)第 1 点。

### H0（历史）

- 模型：Hy-MT2 30B-A3B APEX-I-Compact，candidate `hy-mt2-30b-a3b-apex-i-compact`；`alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF` 的 `Hy-MT2-30B-A3B-APEX-I-Compact.gguf`，revision `312cce865e03a0718e36cfd1077e6307957aef72`，15,035,838,080 bytes，SHA256 `8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a`。
- 采样 `official30b-cached-v1`：temperature 0.7、top_p 1.0、禁用 top_k（`top_k:0`）、`repeat_penalty` 1.0、`n_predict` 4096、`cache_prompt:true`；min_p、frequency／presence_penalty、dynatemp_range、mirostat 均 0，samplers=[temperature]；seed 20261006，相同请求最多两次。总 context 8192，超限拒绝、不截断源文。
- 模板与交付：Hy30 原生模板及 `reasoning_effort:no_think`；提示基础 `V2-native-adapted`，交付 `native-target-json-gbnf-v3`、`token-ids-v1`；每窗独立，前缀 KV 复用，无跨窗对话历史。运行时：GPU layers 99、flash attention on、fit off、单槽、batch 256、ubatch 128、线程 8／8、KV f16。引擎：llama.cpp b11429／CUDA 13.4 兼容 loader（只修 GGUF 偏置张量命名）。
- 流程配方 `dp10-cut`（`gap-pack-v2`，字段 `gap_pack` 加 `cut_penalty`），recipe_hash `ee72ce6683c89e5a1f83fd7ba99f54f3683966deed0e526c193780ad8c500b70`：切包同 [dp10-cut 切包](#dp10-cut-切包)；提示 `joint-understanding-v1`（先共同理解全部可见台词及跨条目的条件、否定、指代和语气，再分别表达各源 ID），ID JSON grammar（无界空白），保护 64 tokens；只读邻文为前一条在停顿 <5 s 时可见、后一条只在停顿 <1 s 时可见，可见 ≤12 条。
- 历史对照：`legacy-greedy-v1`（temperature 0、输出 1024、context 4096、cache 关闭）；GrahLnn Q3_K_M（`hy-mt2-30b-a3b-q3-k-m`）。
- 入口（`just translation-baseline`、`just translation-srt`、`translate-srt --recipe dp10-cut`）与研究代码只在归档 tag `archive/2026-11-18-pre-research-restructure` 中。

### 历史流程与产品配方

- C0：v3 内置的更早配方（每包 5 条目标，前后各 1 条邻文）。
- `b10-joint`（每批 10 条目标按源顺序、前后各 1 条邻文，joint 提示）`2ba680540f055b2ae0c8122faa3ba537418eb12720a552f53c3aa5b652d0969a`。
- `dp6-grp`（`gap-pack-v1`）`ae473cdce915b16379a838cec15fc53e444d24686cd36c706e5f9d379ba2061e`。
- 旧产品配方（llama.cpp 上的 H0）：`b10-joint-degrade-v1` `994c0d03ac4c91fec437285b66f597c19ff28f09c2ecad5b0e9541437ca795fe`（2026-10-13..18）；`dp10-cut-degrade-v1`（`DP10_CUT_DEGRADE_V1`）`086754ca751365c21840742511bf39eaa621b8fc2f5a630372f22661fc86158e`（2026-10-18..11-08，run 目录 `translate/srt-<sha12>/dp10-cut-degrade-v1__s<seed>/`）。两者与对应研究配方同请求，只把批次终态失败改为 10→5→1 拆批、单条仍失败保留日文。

## 依据

- **Q3**（[v13](../../research/2026-11-strata-v12-v13/README.md)，Δ＝Q3−Q2，CI90）：17 部全部建成，最多用到第 3 次请求，失败请求都是写满 8192 token 的失控；表质量非劣未达改善（出现加权一致率 0.706 对 0.652）；dev 电影 accuracy −0.049［−0.085, −0.014］，剧集 wrong-referent **+0.042［+0.021, +0.067］**（集中在表拆条、串名的两部）；产品 ASR 源全体 −0.095［−0.159, −0.031］，交付失败 Q3 为 0、Q2 为 6 个 cue；翻译墙钟相同，不再需要 llama-server、27B 与服务交接。
- **Q2／F1**（[v12](../../research/2026-11-strata-v12-v13/README.md)，对照 Q1）：F1 在 dev 两类与产品 ASR 源三桶都显著改善，1599 包交付失败 0，墙钟快 26–29%；Q2 与 F1 规则相同、只换为默认启动，Q3 的 v13 结果即在该启动上取得。
- **Q1**（[v11](../../research/2026-10-q-line-v9-v11/README.md)）：产品 ASR 源上相对 Q0＋替换非劣、人名相关错误 120 降到 72；dev 干净源上比 Q0 差，用户已知并接受。
- **Q0**（v9，裁判 `claude-opus-5-5-mqm-v1`）：相对 H0，dev accuracy 剧集 −0.058、电影 −0.091，均显著；翻译腔变差，墙钟约 3.3 倍。命名仿 W0／X0：H＝Hy-MT2，Q＝Qwen。
- **单基线**：用户 2026-11-08 决定不再维持两条基线，省掉每次跑两臂的 GPU 与裁判成本。
- **dp10-cut**：用户读[离线切法模拟](../../research/2026-10-batching-v6-v8/README.md)后裁定，**没有 GPU 质量证据**；相对 `b10-joint` 请求数多约 20–35%，跨 ≥10 s 停顿的批由约 50% 降到约 20%，无批跨 ≥20 s 停顿。`b10-joint` 确认集未通过（[v3](../../research/2026-10-translation-flow-v1-v4/README.md)），`dp6-grp` 与之无可分辨差异，均为工程选择。
- **H0**：用户读[四量化实测](../../research/2026-10-translation-model-selection/README.md)后选定 APEX-I-Compact；`official30b-cached-v1` 是配置选择，不是"采样更优"的结论。

## 未验证与已知限制

- 表出错（拆条、串名）的作品 wrong-referent 显著变差；注入前能否用程序规则拦下这类条目未研究。
- Strata 同 seed 不复现：同一部片建两次表，日文写法集合 Jaccard 只有 0.56／0.48；产品 ASR 源结果只来自一次建表。基线表按身份缓存，但不同时间、机器建出的表不保证相同。
- 约 1／4 的建表请求会失控；连续 5 次失控在 v13 未出现，独立估算约千分之一，难的作品上可能更高。
- 基线 Q3 的研究入口（v13）只在归档 tag 中、只覆盖 v13 固定输入；在新输入上需要基线本身（而非产品配方）时须另补入口。
- `dp10-cut` 在产品时间轴上 <6 条的包占 9–24%（被 ≥20 s 停顿夹出的短段）。

## 沿革

- 2026-10-06 ADR-0004：H0 前身，Hy-MT2 30B-A3B Q3_K_M、greedy、context 4096（`legacy-greedy-v1`）。
- 2026-10-07 ADR-0005：改用 APEX-I-Compact；10-08 采样改为 `official30b-cached-v1`。流程为 C0。
- 2026-10-11 ADR-0006：流程基线 `b10-joint`；10-13 产品配方 `b10-joint-degrade-v1`（[ADR-0007](0007-bilingual-subtitle-pipeline-architecture.md)）。
- 2026-10-17 ADR-0009：流程基线 `dp6-grp`；同日 ADR-0010 改为 `dp10-cut`，提示不变。
- 2026-10-18 ADR-0011：产品配方 `dp10-cut-degrade-v1`。
- 2026-10-21 ADR-0015：命名 H0，设 Q 线基础配方 Q0（`qwen-wide`），两条基线并存。
- 2026-11-08 ADR-0016：Q 线基线 Q1（Q0＋只注入 high）；同日 ADR-0017：Q2（Flash-Next 默认启动、DFlash2）；同日 ADR-0018：只保留基线 Q2，H0 退出基线；同日 ADR-0019：产品切到 Q2，H0 退出产品。
- 2026-11-09 ADR-0021：唯一基线改为 Q3（`names-strata-v4` 建表，最多 5 次请求）；产品建表同日切到 Strata（现见 [ADR-0028](0028-names-accept-empty-table.md)）。
- 2026-11-18：按主题合并上述 ADR 为本篇。
