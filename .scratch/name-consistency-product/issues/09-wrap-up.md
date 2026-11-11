# 09 收口：文档同步与增量说明吸收

Status: done
Type: task
Blocked by: 08

## 范围

按增量说明 §5 核对每一处是否已随各票交付，补齐遗漏：

- 架构总览：模块地图加 `kototoki/llama_server.py` 与 `kototoki/names/` 两行（或并入翻译行，按模块边界的职责表为准）；产品包依赖图加 `NAMES` 与 `LLAMA` 节点；装配表 `python -m kototoki` 一行提到两个 llama-server 模型。
- 模块边界：职责表、依赖方向、接缝一节与 01 写的预期一致，改为现状措辞。
- 规格 §3.3、§3.4（时间线示意加 names）、§4、§6、§7.1；§11 "跨文件术语一致"保留并注明"单片内一致已由 names 阶段覆盖"。
- README：新增模型的获取（`just fetch-models` 或手动放置）、`[names]`、"改 `name-table.json` 的 `entries` 后重跑只重做替换"的用法、`enabled=false`。
- AGENTS.md：冻结证据一节中专名一致性一条改为"已按 ADR-0014 进产品，`experiments/name_consistency/` 仍冻结、产品不导入"；重任务清单不变（入口已列）。
- GLOSSARY：专名表（name table）、写法（form）、锚定 cue、落点、实体。
- `experiments/name_consistency/README.md` 状态行：加"2026-10-XX 按 ADR-0014 移植进产品 `kototoki/names/`，本目录冻结"。
- `docs/INDEX.md`、调研索引时间线一条。
- 删除 `docs/changes/name-consistency-product.md`，各模块页"变更与决策来源"记录吸收位置与本目录票据。
- `grep -rnE '<待填 (初始化|阶段3|首个模块|按需)：'` 核对无新增标记。
- `just docs-check`：新增与改动文件无断链（与 main 既有 44 处取交集看）。

## 完成标准

- 上列全部完成；`just test`、`just test-full` 全绿；spec 状态改 resolved。

## 文件所有权

上列文档；不改代码。

## Comments


### 2026-10-20 收口（agent，未 commit，仅文档）

- 核对并补齐：架构总览（模块地图与依赖图 06 已有；装配行补上 Qwen3.8／Hy-MT2 两个模型）；模块边界改现状措辞（无遗留"将"）；规格 §1.1、§2、§3.1、§3.3、§3.4、§4、§6、§7.1、§7.3、§10.1／10.2、§11（"跨文件术语一致"保留并注明单片内一致已由 names 阶段覆盖）、§13 与状态行；README（Qwen3.8 获取、`[names]`、第 5 条专名表与"改表重跑"、`enabled=false`）；AGENTS.md 专名一致性一条（仅该条）；GLOSSARY 新增专名表、实体、写法、锚定 cue、落点；`experiments/name_consistency/README.md` 仅加一行；`docs/INDEX.md` ADR-0013 条目注明第 3 条被 ADR-0014 替代；调研索引时间线补 2026-10-19 ADR-0014 裁定一条并在专名线小节加指针。
- 两处矛盾已改：模块页状态行不再说 07／08 "尚未验证"；ADR-0014"证据一节留空位"改为已由验收记录补入。
- 增量说明 `docs/changes/name-consistency-product.md` 已删除（`docs/changes/` 随之为空删除）；其 §7 用户裁定本就在 ADR-0014"决定"一节，无需移植；§3.2 的 `names/transport/attempt-N.*` 未按其实现（实际 `<UTC戳>-<pid>/session-NN/`），已在模块页"变更与决策来源"注明；翻译子系统页补记 ADR-0014；六个模块页的来源一节都有 ADR-0014 与本票据目录。
- 顺带：`kototoki/names/table.py` 模块 docstring 里指向已删设计稿的引用改为 ADR-0014 与模块页（仅注释，无行为变化）。
- 核对：待填标记 `grep` 为 7 处，均为 `docs/development/workflow.md` 在主树与 `.claude/worktrees/*` 副本里的既有那一条（HEAD 同为 1 条），无新增；`scripts/check_docs.py` 44 处，全部在冻结／历史文档外链，与 main 既有一致，改动文件无新增断链；core 583 项全绿。`tests/full` 12 项全绿。
- 未完成：验收判据 ④（用户抽看 `names-apply.json` 的 `changes`）待用户。
