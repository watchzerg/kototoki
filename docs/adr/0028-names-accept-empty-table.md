# ADR-0028：产品建表只在回复格式不合格时重试，空表是合法结果（`q3-names-v3`）

状态：已接受（2026-11-17，用户决定，依据 batch-run-fixes 07（`archive/2026-11-18-pre-research-restructure:.scratch/batch-run-fixes/issues/07-names-empty-list.md`））、已实现（同日）。替代 [ADR-0022](0022-product-names-on-strata.md) 第 1 点"失败后依次换 seed""5 次都失败"中把空表算作失败的部分（沿用自 v13，回复无有效条目即不合格），以及 [ADR-0026](0026-names-output-and-prompt-budget.md) 第 3 点的配方名与 hash。[ADR-0021](0021-q3-strata-names-baseline.md) 的基线 Q3（`names-strata-v4`）身份不变。  
范围：产品包 `kototoki/names/` 的回复判定与配方。不改提示、schema、采样、归一规则、尝试次数、seed 序列、请求形状、输出上限与提示预算。

## 决定

1. **只有格式不合格才换 seed 重试。** 回复被截断（`finish_reason == length`）、不是 JSON、顶层不是对象、`entries` 不是列表，这几种照旧重试，最多 5 个请求。
2. **空表是合法结果。** `entries` 为空列表，或条目在归一中全被丢弃（缺字段、zh 形状、称呼词、日文写法形状），都直接接受为空表：`build.status = ok`，`dropped_*` 照常记录，运行日志是普通的 `0 entries (D dropped)` done 行，不再记 attempt WARNING 或 `build failed`。终态 `failed` 只剩 5 次回复格式都不合格的情况。
3. **新配方 `q3-names-v3`**，`BUILD_RECIPE_HASH` `d57ed0c6715f63fcb32bb034db03decf02650215af62c13ba95ae7bcdbcf33d7`（`q3-names-v2` 为 `2dbd324e5ee847d0a0171840d4a064cd6b45a3df4c2123b7075cfe1a38b379ba`）。建表块新增 `retry_on: "malformed"`。与 `names-strata-v4`（`38cb7bcd…`）相比，建表块差 ADR-0026 的三项和这一项：三项换回 v4 的值、去掉 `retry_on` 后拼回 v4 的形状，hash 仍等于 `38cb7bcd…`（`tests/core/test_names_recipes.py`、`archive/2026-11-18-pre-research-restructure:tests/equivalence/test_names.py`）。请求体不变。
4. **不兼容已有产物。** 配方变即表身份变，已有 `name-table.json` 下次运行时重建；不迁移。

研究侧 `archive/2026-11-18-pre-research-restructure:experiments/scene_batching_v6/v13.py` 的 `s1_recipe` 原样取产品 `BUILD["build"]`，现改为去掉 `retry_on` 再取，属机械改动，S1 各变体的 hash 不变（同 ADR-0026 先例）。v13 调用的是产品的 `build_table`，此后按本决定接受空表；v13 已结题，不再重跑。

## 依据

- **原则**：结构合法的回复就是对"列出专名"的有效回答。对有效回答换 seed 重试，等于抽到非空为止、按内容挑结果，和"取第一张合格的表"（ADR-0008：不挑选）的原意冲突。重试只用来对付坏掉的回复。
- **"非空"要求的来源**：原样移植自研究脚本 `archive/2026-11-18-pre-research-restructure:experiments/name_consistency/build_table.py`。研究阶段用的是动画素材，专名多，空回复基本就是失败。ADR、研究文档和模块页都没有记载其他理由。
- **首次大批量运行的观察**（2026-11-12，`run-20261112T141709Z.log`）：不合格尝试 59 次，其中空列表 45 次、截断 8 次、条目全被丢弃 5 次、JSON 语法错 1 次。6 个文件 5 次全失败、以空列表为主，写了 `failed` 空表。空回复 12 token、命中前缀缓存，每次重试约 0.2 s，省下的时间可以忽略；本决定改的是语义，不是效率。

## 已知影响

同一批数据中，另有 9 个文件先回空列表、换 seed 后得到 1–7 条。按本决定它们会得到空表：其中 8 个只有 medium／low 条目（不注入翻译，译文不变），1 个含 1 条 `confidence: high`，那个文件的注入行会少一行。用户裁定时已知晓并接受。

## 未验证

- 未在 GPU 上重跑；只有离线测试（`just test`、`just test-equivalence`、v13 研究测试）。
- 5 次全空的 6 个文件是否确实没有专名，未人工核对转写。
