# name_consistency：专名表建表与生成后替换

状态：研究原型（2026-10-19）。票据 `.scratch/name-consistency/`，背景与结论见[方向讨论记录](../../docs/research/2026-10-19-name-consistency-direction.md)与后续研究文档。不属于产品包 `kototoki/`，产品不导入。

## 做什么

同一作品内人名／职阶名等专名在中文译文里写法不一致（产品整片不一致率 0.07–0.25）。思路是把"建表"和"用表"分开：

1. `build_table.py`：通用 LLM（Qwen3.8-27B UD-IQ3_S，经 llama-server）读整份 `ja.srt`（剥时间轴、带 cue 编号，一部电影约 13–15K tokens），输出 `name-table-v2` JSON：每条 `entity_ja`、`zh`（展示用全名）、`forms: [{ja, zh}]`（转写稿里出现的每个日文写法，含 ASR 误识，各配**同粒度**的中文：姓对姓、名对名）、`zh_variants`（同一个词的其他写法）、`kind`、`confidence`、`evidence`。请求带 JSON schema（llama.cpp 转 grammar）与 Qwen 官方 non-thinking 采样；`finish_reason == length` 视为失败；失败重试一次（seed +1）。`--think` 开思考模式（输出上限 8192，服务器需 `--reasoning on --reasoning-budget 4096 -c 24576`）。 提示 v5（第四轮）把 `confidence` 改成可操作判据：high 只给能说出角色身份、确定通行译名且名字出现 ≥3 条 cue 的条目，次要角色与 ASR 碎片拼出的名字给 medium；程序兜底把 evidence 少于 3 条 cue 的 person 条目从 high 降为 medium（`confidence_note`）。称呼词、祷词不收，相近名字的不同角色不合并。normalize 还做 zh 形状过滤（只许 CJK、间隔号、ASCII 字母，1–12 字；不合规的实体／写法／变体丢弃并记 `meta.dropped_shape`）；`--renormalize OLD --out NEW` 对已保存的原始回复按当前规则重算，不重跑模型。第五轮加称呼词程序黑名单（`HONORIFIC_JA`：父さん、父様、姉さん、先輩、あの人、お前 等，NFKC 后剥一个前缀 お／ご 与一个后缀 さん／さま／様／ちゃん／くん／君 再比词干）：命中的写法在 normalize 阶段丢弃并记 `meta.dropped_honorific`，写法丢光的实体整条丢；`--seed N` 指定采样 seed（默认 20261019，重试 +1），`meta.seed` 记录实际 seed。第六轮：提示 v6 的示例全部换成虚构作品与人名（不再出现 EVA、Fate 的名字）；日文写法形状过滤（`_clean_ja`：只许汉字、假名、长音符、间隔号，含汉字或片假名的写法里平假名只许是前缀 お／ご 或敬称后缀，汉字之间的空白去掉、其他空白丢弃，1–20 字），不合格的写法记 `meta.dropped_ja_shape`，entity_ja 不合格则换成第一个合格写法。[第四轮](../../docs/research/2026-10-19-name-consistency-round4.md)证明这些不能让模型"自信的错名"变得可过滤：有害条目全是 high，错名随采样变化。
2. `apply_table.py`：翻译配方不动，生成后在译文里把专名的变体写法统一成表里的中文。按写法锚定：cue 的日文含某个 `form.ja`（同一实体取最长的）就在该 cue 的译文里找落点，目标是该写法的 `zh`。落点来源：同实体其他写法的中文（仅限包含关系）、`zh_variants`（须通过译文特异性检验）、跨 cue 统计（复用 `experiments/quality_v5/consistency.py`，候选过形状与特异性过滤，落点扩到有支持的最长超串，含 `·` 的扩展须覆盖整个复合词）。目标的真子串视为省略形不扩写，包含目标的串视为已规范不缩写；落点紧邻 `·`／拉丁字母的跳过；都没命中就不动，只记 `unresolved.jsonl`。第二轮加了两条规则：**整个名字**——统计层候选互为子串时只留锚定 cue 最多的一个，扩展要求超串支持不少于原落点一半，最终落点两侧紧邻 `BOUNDARY_CHARS` 之外的汉字就视为没覆盖完整名字，不替换（`boundary`）；**中文名核对**——写法的目标 `zh` 须在同实体的锚定 cue 里出现过（`appears`）、与译者主写法近形（`near`）或是职阶的纯 ASCII 名（`class_ascii`），否则整个写法不动（`unverified_name`，列在 `summary.json` 的 `unverified_forms`）。第二轮证明它误拦的正确名字远多于拦对的错名，用户 2026-10-19 裁定放弃，默认关闭，`--name-check` 只作对照。第三轮（[报告](../../docs/research/2026-10-19-name-consistency-round3.md)）加了四个开关：**孤立单字**（默认开，`--no-isolated-singles` 关）——单字译法（白）的特异性只按孤立出现统计，扩展超串首尾不得是边界字，一次补上 51 处 白→士郎 且全部正确；`--pool-by-target`（同实体同目标的写法合并统计并把二字组放进候选池，有害率 8%，错源是表里的错名，修表后再评）；`--bigram-isolation`（单字孤立按语料二字组判断，产生"士郎郎""Rider手"，不采纳）；`--iterate N`（跑到不动点，无效）。`merge_tables.py` 对两张 v2 表取交集（去掉了全部 7 条已知错映射但实体砍掉一半，不采纳）。第四轮加 `--weak-name-check`（非 high 条目的 zh 在译文里一次都不出现就整条跳过；在 v5 表上与 `--min-confidence high` 输出相同，都拦不住有害行），并修了扩展吞前置修饰词（笨蛋伊莉亚、如果白；默认输出不变）。**当前配置：no-think 建表（v4 提示的四张表）＋规则一＋孤立单字**（[第五轮](../../docs/research/2026-10-19-name-consistency-round5.md)用户裁定缺姓算有害、一致表不替换；[第六轮](../../docs/research/2026-10-19-name-consistency-round6.md)的提示 v6 是退步，是否回退到 v5 示例待裁定）。`--min-confidence` 按表里的 confidence 过滤条目。`measure` 子命令对成对 SRT 算替换前后的不一致率。

## 命令（仓库根目录）

```
python -X utf8 -m experiments.name_consistency.build_table --srt ja.srt --work NAME --out table.json [--url http://127.0.0.1:8081] [--think] [--seed N] [--dry-run]
python -X utf8 -m experiments.name_consistency.apply_table --table table.json --ja ja.srt --zh zh.srt --out-dir DIR [--min-confidence low|medium|high] [--no-isolated-singles] [--pool-by-target] [--bigram-isolation] [--iterate N] [--weak-name-check] [--name-check]
python -X utf8 -m experiments.name_consistency.build_table --renormalize OLD.json --out NEW.json
python -X utf8 -m experiments.name_consistency.merge_tables --a think.json --b nothink.json --out both.json
python -X utf8 -m experiments.name_consistency.merge_tables --mode zh-agree [--forms-fallback] [--form-agree [--form-agree-substring]] --a seedA.json --b seedB.json --out agree.json
python -X utf8 -m experiments.name_consistency.apply_table measure --pair NAME ja.srt zh.srt [--pair ...] --out FILE
```

llama-server 启动参数（探针所用，b11669）：`-c 20480 -np 1 -ngl 99 -b 512 -ub 512 -fa on --jinja --reasoning off|on --no-webui`。16K 上下文不够（提示 13.7K ＋ 输出 4K）。

## 测试

```
.venv/Scripts/python.exe -X utf8 -m unittest experiments.name_consistency.test_build_table experiments.name_consistency.test_apply_table experiments.name_consistency.test_merge_tables -v
```

离线，不发 HTTP、不加载模型。

## 已知限制

- 模型不可靠的部分靠程序兜底：no-think 下 `zh_variants` 会混入角色真名、`confidence` 全是 high；think 与 no-think 都可能把别的角色并进同一实体（シンジ→士郎）、次要角色的中文名幻觉（ゾウケン、アンリ・マユ）。粒度问题由 v2 的 `forms` 从结构上消除。
- 统计层对单字译法（シロ→"白"）会把前后字带进候选（"叫白"、"如果白"），替换后留残字；音译只命中前缀时同样留残字（"托萨"→"远坂克"）。第二轮的边界规则把这两类改成不替换，但单字译法本身仍常因特异性不足而找不到落点。
- 中文名核对以译者为证据：译者整片都没写对的名字（切嗣、间桐、爱因兹贝伦在 HF II／III 产品译文里一次都没出现）即使模型给对了也会被拦下；这是规则本身的代价，不是 bug，因此已放弃。
- 单字 `form.ja` 会过度锚定。
- 不幂等：统计层依赖整片语料，替换后统计变化，第二遍还会再改少量（四部共 9 处，都正确）。
- 覆盖率：锚定 cue 中目标名出现的比例 0.62–0.80（第三轮默认），士郎约 40%；剩余是每 cue 都不同的一次性音译（艾米亚希罗／埃米亚希罗），统计方法覆盖不到。
- no-think 表里的错名（HF III x0 的 `アンリマユ→安赫尔`、`マトウ増健→间桐慎二`，HF II x0 的 `造剣→言峰绮礼` 等）是当前剩余有害行的主要来源。第四轮试了提示侧的置信度校准：错名换了一批（时臣、真嗣、安徒生·麦）而没有减少，且都标 high。第五轮两次建表按实体中文名取一致（`merge_tables.py --mode zh-agree --forms-fallback`）清掉了采样级错名，但清不掉提示污染（EVA 示例让两个 seed 都给 `シンジ=真嗣`）、写法并集带进的单表错写法（`増健=慎二`）与句子级写法（拆散锚定 cue、削弱统计）。第六轮：句子级写法由 `_clean_ja` 解决；换成虚构示例的提示 v6 反而让模型更常把写法挂错实体（`イリア` 挂到凛、`セイマー` 挂到士郎、两个 seed 都给 `シンジ=时臣`），有害率升到 7%；写法层一致规则（`--form-agree`）只校验中文是否被认可，拦不住挂错实体的写法；跨表实体配对只要任一写法相同就配，会把伊莉雅配上凛而整条丢掉。
- `merge_tables.py --mode zh-agree`：两张表的实体按 entity_ja 或任一写法的规范化日文配对，zh 完全相同才保留，写法取并集（同一日文两边 zh 不同只丢该写法），对不上或 zh 不同的实体记 `meta.dropped_unmatched`／`dropped_zh_disagree`；`--forms-fallback` 让 zh 不同的配对只留两边日文、中文都相同的写法，回退实体的 entity_ja 与 zh 取第一个共同写法的（否则 `apply_table` 的隐含写法会拼出错映射），记 `meta.kept_forms_only`。`--form-agree`：只在一张表出现的写法，其 zh 必须已是实体 zh 或对方表同一实体某写法的 zh 才保留，否则记 `meta.dropped_form_unverified`；`--form-agree-substring` 另接受 zh 是实体 zh 的 ≥2 字子串的写法（`stats.kept_form_substring`）。
- 一致性指标与表同源，只能证明"照表执行"；准确性要另看 `changes.jsonl`。
