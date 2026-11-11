# 02 诊断 dev 注入反向，定 N*

Status: resolved
Type: 离线
Stage: A
Blocked by: 01

范围、终点与门见研究文档 §4／§5（docs/research/2026-10-22-q0-product-route-v11.md）。

## 执行记录

- 输入（只读 v10）：`runs/qwen-names-dev__s20261011__dev` 与 `runs/qwen-wide__s20261011__dev`（B 期间同期重判）的译文与判分；`E/dev-name-tables.json`（15 张表、201 条、298 个注入 form）。代码 `experiments/scene_batching_v6/names11.py`；产物 `.local/q0-product-route-v11/A/02-{diagnosis,classes,class-summary,table-agreement}.json`（含转写内容，不进 Git）。
- **判据**（执行者补）：
  - 人名相关错误＝裁判 evidence 命中 `v9.NAME_ERROR`（与 v10 票据 16 的 35 对 25 同口径；本次复核 cand 35＝剧集 22＋电影 13，ctrl 25＝17＋8）；指代错误＝category `wrong-referent`（cand 31＝剧集 12＋电影 19，ctrl 27＝18＋9）。
  - 按 cue 比较两臂该类错误数：候选多＝"新增"，候选少＝"修好"。新增 cue 39 个（人名 28、指代 15、重叠 4）；修好 cue 30 个（人名 18、指代 12）。
  - 每个新增 cue 取其新增错误的成因归一类：(a) 候选用了表的中文而该条目本身错（映射到别的人物、漏字、丢敬称、凭空人名）；(b) 条目是该名字的可辨音译／译法，只是与参考字幕组惯例不同；(c) 条目对，模型把名字用到原文没有该写法的位置或别的人身上；(d) 无表条目参与、或两臂文本相同（裁判噪声）。程序先按规则预分（`pre_class`：c?／ab?／d／m?），再逐条读记录定终类（`02-classes.json` 每条带一句理由）。
- **结果**（`02-class-summary.json`）：(a) **22**、(d) 14、(b) 2、(c) 1 → **(a) 占多数**（56%）。按类别：电影 (a) 11／(d) 7；剧集 (a) 11／(d) 7／(b) 2／(c) 1。按种类：人名新增 (a) 17／(d) 9／(b) 2；指代新增 (a) 8／(d) 6／(c) 1。
  - 肇事条目（不进 Git，只记形态）：M01 一条把配角（姓＋名两个 form）映射成本系列主角名（6 个 cue，占电影指代新增 11 个中的 6 个）；M02 一条把配角映射成女主名、一条凭空人名、一条误读；W08 一条姓氏漏首字（11 个 cue）；W11 一条把本名映射成角色名；M04 一个 form 人名残缺；M01 一个 form 丢敬称。(b) 两例是同一公会名的音译与惯用意译之差。(c) 唯一一例是两个正确条目被套错人。
  - **(a) 的 22 个 cue 里 19 个所涉条目是 `confidence: high`**，只有 3 个（medium）会被"只注入 high"过滤掉。这意味着 §4.1 规则 (a) 规定的修订对 dev 反向的主因基本无效（预计 B 门仍难通过）；规则是立项时写定的，照做，并把这一点记进 §8。
  - 反方向：注入修好的 cue 人名 18、指代 12（其中预分 d 的 4＋5 个与表无关）。净值人名 +10 与 v10 一致。
- **表与参考中文的一致率**（`02-table-agreement.json`，201 条中 198 条在 dev 日文里出现；"一致"＝该 cue 参考中文含条目 zh／form zh／zh_variants 之一）：出现加权一致率 0.65；按条目多数一致 125、多数不一致 73。按 confidence：high 117 条中 40 条多数不一致（34%）、medium 73 中 26（36%）、low 8 中 7——**confidence 几乎不预测正确性**。按 kind：person 118 中 47 不一致（40%）、other 25 中 14。按作品：W04 0.05、M02 0.38、M01 0.41、W01 0.46、W11 0.48 最差；M04 0.93、W06 0.95、W08 0.87（W08 的高一致率是因为"户川"是"小户川"的子串——子串匹配高估了一致率，但不影响分类，分类按裁判与原文逐条看）。
- **条目性质对比**：dev 表 201 条（person 59%、high 60%、片假名 form 44%）；产品表 HF-II 20 条（person 75%、high 70%、片假名 57%）、HF-III 15 条（person 67%、high 87%、片假名 75%）。产品两部是 Fate 系列正篇、主角名在模型先验里稳定；dev 的两部电影是 SAO 外传电影，出事的全是配角被映射成本系列主角名——作品知名反而带来串名风险；dev 表由场景拼接文档建表（上下文比整片少），也可能加剧。产品表没有人工中文参考，一致率无法同口径算。
- **决定（§4.1 规则 (a)）**：N\*＝`qwen-name-table-v2`＝v1 注入方式（`filter: window`、v1 表头不变）＋**只注入 `confidence: high` 条目**（过滤在建注入表时做：`names11.nstar_tables("high")`／`product_tables("high")`）。配方已写：dev `recipes/qwen-names-dev-high.json`（hash `9c444d3c…`，15 部作品 190 个 form，原 298）；产品 `C/root/recipes/q0-names-high.json`（hash `c10e143a…`，HF-II 28／HF-III 26 个 form，原 35／28）。01 做的 `targets` 开关本轮不用。
- 自动检查：`test_v11` 加 `pre_class`／`_entries_hit`／`_zh_present` 3 项。未验证：N\* 的真实生成（04 的 smoke）。

## Answer

(a) 表条目错占多数（22／39），N\*＝v1 注入＋只注入 `confidence: high` 的条目（`qwen-names-dev-high` `9c444d3c…`、`q0-names-high` `c10e143a…`）。但 (a) 的 22 个 cue 中 19 个所涉条目本身就是 high，confidence 不预测条目正确性（high 条目 34% 与参考多数不一致），修订预计难以消除 dev 反向；表质量问题同样影响产品的生成后替换——记入 §8。
