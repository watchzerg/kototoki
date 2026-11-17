# 07 专名表把空列表判为不合格

Status: resolved
Type: task
Blocked by: —

## 现象

6 个文件的专名表请求，模型 5 次（5 个 seed）都回复空列表（回复约 35 字符、12 token），每次都判不合格：`entries must be a non-empty list`。最后按设计写空表、照常翻译。另有 17 个文件重试 2–5 次才成功（原因未逐一核对）。

## 原因

- `kototoki/names/table.py` 约 305 行：校验要求 `entries` 非空，空列表直接 `ValueError`，进入重试。
- 影片里确实没有专名时，空列表本来就是正确答案。

## 影响

- 结果不变（最终都是空表），但每个这样的文件多发 4 次请求；专名阶段整批耗时 3603 s，其中一部分是这种无效重试。

## 候选方向（待讨论）

- 回复结构合法、`entries` 为空列表时直接接受为空表。
- 要核实：当初为什么要求非空（是否用来挡模型偷懒或格式退化）；改后是否影响专名配方的 hash 与已有研究结论（专名研究线已结题，只改产品侧校验）。

## 方案（2026-11-17 用户裁定）

原则：**格式不合格才重试，内容不挑。** 结构合法的回复就是有效回答；对有效回答换 seed 重试等于按内容挑结果，与"取第一张合格的表"的原意冲突。不考虑已跑产物的兼容。

| 回复 | 处理 |
| --- | --- |
| 截断（`finish_reason == length`）、非 JSON、顶层不是对象、`entries` 不是列表 | 重试（不变） |
| `entries` 为空列表 | 接受为空表，`status = ok` |
| `entries` 非空但条目全被程序兜底丢弃（缺字段、zh 形状、称呼词、日文写法形状） | 同样接受为空表，`dropped_*` 照常记录 |

改动：

- `kototoki/names/table.py`：`parse_reply` 只在 `entries` 不是列表时抛 `ValueError`；删去"非空"与 `no valid entries after validation` 两处抛错。`build_table` 不改。终态 `failed` 只剩真正的格式失败。
- 日志：空表的 done 行即 `0 entries (D dropped), …`（INFO），不再有 attempt WARNING 与 `build failed`。
- 配方：`BUILD["build"]` 加显式字段（如 `"retry_on": "malformed"`），配方名升为 **`q3-names-v3`**（用户已裁定），hash 随之变；`tests/core/test_names_recipes.py` 拼回 `names-strata-v4`（`38cb7bcd…`）时多换回这一项。
- 决定记录：新 ADR（0028）写明产品与 `names-strata-v4` 的这处差异与理由；更新 CURRENT.md"产品建表"节（配方名、hash、差别列表）与决定索引。
- 文档：模块页 `docs/architecture/modules/name-consistency.md`（重试条件、失败语义、日志行），技术设计里对应的描述同步。
- 测试：`test_names_table.py` 空列表改为接受且只发 1 个请求，补"条目全被丢弃也接受"；`test_names_session.py` 里"5 次都失败"的伪回复换成非 JSON 等真正坏格式。
- 不跑 GPU 验证；`just test` 通过即可。

## 结果（2026-11-17）

- 实现：`parse_reply` 只在格式不合格时抛错；配方 `q3-names-v3`（`retry_on: "malformed"`），hash `d57ed0c6…`；决定记录 [ADR-0028](../../../docs/adr/0028-names-accept-empty-table.md)，CURRENT.md、决定索引、模块页、技术设计、配置参考、README 同步。
- 研究侧：`experiments/scene_batching_v6/v13.py` 的 `s1_recipe` 去掉产品独有的 `retry_on` 再取建表块（机械改动，S1 hash 不变），`test_v13.py` 更新产品 hash 钉子。
- 自动检查：`just test` 772 项通过；`just test-equivalence` 14 项通过；`experiments.scene_batching_v6.test_v13` 15 项通过；`scripts/check_docs.py` 本票无新增错误（`run-logging-and-processes.md`、`translation-subsystem.md` 两处字数超预算是既有问题）。
- 未验证：未在 GPU 上真实运行；5 次全空的 6 个文件是否确无专名未人工核对。

## 证据

- 运行日志 `run-20261112T141709Z.log` 的 `[names]` 段。
- 台账 §C4 与"需关注番号清单"的 names 行。

## Comments

- 2026-11-17 日志核对（`run-20261112T141709Z.log` 与 212 个工作目录的 `name-table.json`）：
  - "非空"要求原样移植自研究脚本 `experiments/name_consistency/build_table.py`（动画素材），ADR、研究文档与模块页均无记载理由。
  - 不合格尝试共 59 次：空列表 45、截断 8、条目全被丢弃 5、JSON 语法错 1。5 次全失败的 6 个文件都以空列表为主。
  - 空回复 12 token、命中前缀缓存，每次重试约 0.2 s；6 个文件的无效重试合计约 5 s，"影响"一节高估了耗时。
  - "结果不变"只对这 6 个成立：另有 9 个文件先回空列表、换 seed 后得到 1–7 条，其中 1 个含 1 条 high（会注入翻译），其余 8 个只有 medium／low。按新方案这些文件会得到空表，用户已接受。
