# 01 离线实现：配方字段、提示版本、划组、重排率与校验器、注入覆盖

Status: resolved
Type: task

## 目标

按研究文档 §4 实现 `grp1`（`translation_v3` 配方字段、`joint-understanding-v2`、`groups` 注入）、把划组抽成共用函数、实现 §4.4 重排率与 §4.5 显示校验器、证明已有配方 hash 不变，并统计 dev 与产品上的注入覆盖与 token 增量。不加载模型、不占 GPU。

## 执行记录

- 2026-10-18 claimed（side session，worktree `pensive-jemison-72ee36`）。
- 划组：`translation_v3/batching.py` 新增 `line_tail`、`ends_sentence`、`sentence_joined`、`sentence_groups`（R2+：停顿 <gap 严格小于，重叠算相连，缺时间戳按无停顿；前一行去掉行尾空白与 `」』）)】〕"'”’` 后不以 `。？！?!.` 结尾；`…`、`、` 不算句末；不设上限）。`reorder_groups/stats.py` 的 R2+ 改为调用它（`tail` 也复用 `line_tail`）；改前改后 `stats.py --json` 与 Markdown 输出逐字节相同。
- 配方：`Recipe.groups`（`{"gap": 秒}`，须 `prompt="joint"`）；`V4_DEFAULTS` 加 `groups: None`，默认值不进 `spec()`。`versions.groups = [group-reorder-v1, 句末字符, 右括号集合, 键名, sha(注入文字), joint-understanding-v2, sha(v2 文字)]`。`Batch.groups` 记录本包 ≥2 条的小组（目标 ID），批记录多一个 `groups`。内置 `grp1 = replace(dp10-cut, groups={"gap": 1.0})`，hash `5aaf3e776bd39cf4fe718fc5016ece54f71685181af695e0c2f9cfb9a8792eaa`。
- 提示：有 ≥2 条小组的批次把 `JOINT_INSTRUCTION` 换成 `JOINT2_INSTRUCTION`，并用 `recipes.inject()` 在 assistant 标记前加一行 `以下是待译条目中属于同一句话的 ID 分组：{"groups": [[...], ...]}`；无此类小组的批次与 `dp10-cut` 逐字相同（`coverage.py` 对 dev／产品全部批次断言过）。grammar 不变。`generate.py` 把 `batch.groups` 传给 `render_translation`。
- 测试：`test_recipes.GroupReorderTest`（5 项：17 个旧内置配方 hash 全部固定、grp1 与 dp10-cut 批次相同且 grammar 相同、R2+ 规则、批次小组与提示、字段校验）。`reorder_groups/test_checks.py`（6 项）、`test_coverage.py`（2 项）。全套：translation_v3 62、reorder_groups 14、scene_batching_v6 31、translation_v4 19，全部通过。
- 噪声底（用已有 run，离线）：同 seed 的两个严格配方之间（v4 `c0` 对 `b10-joint` 按 b10-joint 包划组；v7 `b10-joint-ctl` 对 `dp6-grp` 按 dp6-grp 包划组；各 seed 20261011–13），结果 `.local/group-reorder-v8/01/noise/`。
- 覆盖：`python -m experiments.reorder_groups.coverage --validate <3 个 run>` → `.local/group-reorder-v8/01/coverage.json`。

## 实现细节的取值与理由

| 细节 | 取值 | 理由 |
| --- | --- | --- |
| 字段形状 | `groups: {"gap": 1.0}` | 门槛是 §4.6 登记的唯一可变量（1.5／2.0 s 变体），放进字段即进 hash；规则其余部分是常量并版本化 |
| 提示开关 | 不新增 `prompt` 取值，由 `groups` 决定逐批换句 | §4.1"单条小组不注入、不提示"：无多 cue 组的批次必须与对照逐字相同，按批切换比整轮换提示更贴合 |
| 提示最终措辞 | 在 §4.2 草稿上加两处："只调语序、不改含义"（覆盖第四点）；"未列入 groups 的 ID 各自单独成组"（注入只列 ≥2 条的组，单条 ID 需要说明归属） | 其余与草稿相同；02 小样允许再调一次 |
| 注入格式 | `以下是待译条目中属于同一句话的 ID 分组：` ＋ `{"groups": [["id", ...], ...]}`（`ensure_ascii=False`，与 terms／target_context 同款） | 与已有注入一致，键名与提示里的 "groups" 对应 |
| 重排率主阈值 | 0.2（同时报 0.1／0.2／0.3） | 严格对严格噪声底：≥0.1 为 22–30%（改写噪声）、≥0.2 为 1.6–6%、≥0.3 为 0–2%；0.2 让噪声降到个位数，同时两行组里约一成字数挪动即可越过 |
| 读速阈值 | 9 字/秒（字数去空白与标点） | Netflix 简体中文字幕规范的成人节目上限（儿童 7）；本仓库没有自己的规范。严格配方在 dev 上超过者 0.4–2.2%，阈值不至于全标或全不标 |
| 占比偏差 | 组内每条 |字数占比 − 时长占比| 的最大者 ≥0.3 记失衡组 | §4.5 指定 0.3；取"最大者"使一组只计一次 |
| token 计数 | 离线 BPE：GGUF 文件头的 `tokenizer.ggml.*` ＋ llama.cpp `hunyuan-dense` 预分词，用 `tokenizers` 重建 | 已有方式是服务器 `/tokenize`，需要加载模型；离线重建对 3 个已有 run 的 617 条 `/tokenize` 交换记录逐 ID 一致（617/617） |

## Answer

**实现完成，已有配方 hash 全部不变**（17 个旧内置配方固定在测试里；`dp10-cut` 仍为 `ee72ce66…`），`grp1` hash `5aaf3e77…`，未做任何 GPU 运行。

注入覆盖（`dp10-cut` 切包，`.local/group-reorder-v8/01/coverage.json`）：

| 集合 | 包 | 注入包 | 注入包占比 | 多 cue 组覆盖的 cue | 每注入包 Δtoken 均值（joint 句＋groups 行） | groups 行 p50／p90／max | 输入 token 均值 dp10-cut → grp1 | 整体增幅 | grp1 最大输入 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev | 621 | 602 | 96.9% | 78.0% | 168（77＋91） | 95／125／138 | 661 → 824 | +24.7% | 1186 |
| dev 剧集 | 395 | 382 | 96.7% | 80.2% | 176（77＋99） | 106／128／138 | 680 → 850 | +25.0% | 1186 |
| dev 电影 | 226 | 220 | 97.3% | 74.2% | 155（77＋78） | 81／99／109 | 629 → 780 | +24.0% | 1021 |
| 产品 | 296 | 249 | 84.1% | 50.3% | 150（77＋73） | 70／104／138 | 583 → 709 | +21.6% | 1040 |

- 多 cue 组覆盖的 cue 与离线统计（dev 78%、产品 50%）一致。所有批次远低于输入上限 4032。
- joint 句 v1→v2 固定 +77 token；`groups` 行随组数与 ID 长度变化（dev 的 cue ID 形如 `F2-W01_E001-J00236`，单个 ID 约 10 token）。

重排率噪声底（严格对严格，同 seed，dev，各 3 seed）：≥0.1 为 22–30%、≥0.2 为 1.6–6%、≥0.3 为 0–2%；逐字不同的多 cue 组 85–94%（作为上界几乎没有区分力）。显示校验在严格配方上：读速 p50 4.4–4.8、p90 6.3–7.3、p99 8.4–11.7 字/秒，>9 字/秒 0.4–2.2%；失衡组 0–2.5%。

## 留给后续票据

- 02 需先给 `scene_batching_v6` 加 `--round v8`（根 `.local/group-reorder-v8/`）。
- "单条组 cue 逐字相同"：有组包换了 joint 句，单条组不保证相同；`checks.py` 把单条组按所在包有无多 cue 组分开报。无组包只占 dev 3%、产品 16%。
