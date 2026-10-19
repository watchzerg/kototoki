# name_consistency：专名表建表与生成后替换

状态：研究原型（2026-10-19）。票据 `.scratch/name-consistency/`，背景与结论见[方向讨论记录](../../docs/research/2026-10-19-name-consistency-direction.md)与后续研究文档。不属于产品包 `kototoki/`，产品不导入。

## 做什么

同一作品内人名／职阶名等专名在中文译文里写法不一致（产品整片不一致率 0.07–0.25）。思路是把"建表"和"用表"分开：

1. `build_table.py`：通用 LLM（Qwen3.8-27B UD-IQ3_S，经 llama-server）读整份 `ja.srt`（剥时间轴、带 cue 编号，一部电影约 13–15K tokens），输出 `name-table-v2` JSON：每条 `entity_ja`、`zh`（展示用全名）、`forms: [{ja, zh}]`（转写稿里出现的每个日文写法，含 ASR 误识，各配**同粒度**的中文：姓对姓、名对名）、`zh_variants`（同一个词的其他写法）、`kind`、`confidence`、`evidence`。请求带 JSON schema（llama.cpp 转 grammar）与 Qwen 官方 non-thinking 采样；`finish_reason == length` 视为失败；失败重试一次（seed +1）。`--think` 开思考模式（输出上限 8192，服务器需 `--reasoning on --reasoning-budget 4096 -c 24576`）。
2. `apply_table.py`：翻译配方不动，生成后在译文里把专名的变体写法统一成表里的中文。按写法锚定：cue 的日文含某个 `form.ja`（同一实体取最长的）就在该 cue 的译文里找落点，目标是该写法的 `zh`。落点来源：同实体其他写法的中文（仅限包含关系）、`zh_variants`（须通过译文特异性检验）、跨 cue 统计（复用 `experiments/quality_v5/consistency.py`，候选过形状与特异性过滤，落点扩到有支持的最长超串，含 `·` 的扩展须覆盖整个复合词）。目标的真子串视为省略形不扩写，包含目标的串视为已规范不缩写；落点紧邻 `·`／拉丁字母的跳过；都没命中就不动，只记 `unresolved.jsonl`。第二轮加了两条规则：**整个名字**——统计层候选互为子串时只留锚定 cue 最多的一个，扩展要求超串支持不少于原落点一半，最终落点两侧紧邻 `BOUNDARY_CHARS` 之外的汉字就视为没覆盖完整名字，不替换（`boundary`）；**中文名核对**——写法的目标 `zh` 须在同实体的锚定 cue 里出现过（`appears`）、与译者主写法近形（`near`）或是职阶的纯 ASCII 名（`class_ascii`），否则整个写法不动（`unverified_name`，列在 `summary.json` 的 `unverified_forms`）。第二轮证明它误拦的正确名字远多于拦对的错名，用户 2026-10-19 裁定放弃，默认关闭，`--name-check` 只作对照。**当前配置：no-think 建表＋规则一**（[第二轮报告](../../docs/research/2026-10-19-name-consistency-round2.md)）。`--min-confidence` 按表里的 confidence 过滤条目。`measure` 子命令对成对 SRT 算替换前后的不一致率。

## 命令（仓库根目录）

```
python -X utf8 -m experiments.name_consistency.build_table --srt ja.srt --work NAME --out table.json [--url http://127.0.0.1:8081] [--think] [--dry-run]
python -X utf8 -m experiments.name_consistency.apply_table --table table.json --ja ja.srt --zh zh.srt --out-dir DIR [--min-confidence low|medium|high] [--name-check]
python -X utf8 -m experiments.name_consistency.apply_table measure --pair NAME ja.srt zh.srt [--pair ...] --out FILE
```

llama-server 启动参数（探针所用，b11669）：`-c 20480 -np 1 -ngl 99 -b 512 -ub 512 -fa on --jinja --reasoning off|on --no-webui`。16K 上下文不够（提示 13.7K ＋ 输出 4K）。

## 测试

```
.venv/Scripts/python.exe -X utf8 -m unittest experiments.name_consistency.test_build_table experiments.name_consistency.test_apply_table -v
```

离线，不发 HTTP、不加载模型。

## 已知限制

- 模型不可靠的部分靠程序兜底：no-think 下 `zh_variants` 会混入角色真名、`confidence` 全是 high；think 与 no-think 都可能把别的角色并进同一实体（シンジ→士郎）、次要角色的中文名幻觉（ゾウケン、アンリ・マユ）。粒度问题由 v2 的 `forms` 从结构上消除。
- 统计层对单字译法（シロ→"白"）会把前后字带进候选（"叫白"、"如果白"），替换后留残字；音译只命中前缀时同样留残字（"托萨"→"远坂克"）。第二轮的边界规则把这两类改成不替换，但单字译法本身仍常因特异性不足而找不到落点。
- 中文名核对以译者为证据：译者整片都没写对的名字（切嗣、间桐、爱因兹贝伦在 HF II／III 产品译文里一次都没出现）即使模型给对了也会被拦下；这是规则本身的代价，不是 bug，因此已放弃。
- 单字 `form.ja` 会过度锚定。
- 一致性指标与表同源，只能证明"照表执行"；准确性要另看 `changes.jsonl`。
