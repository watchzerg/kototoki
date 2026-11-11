把产品 `kototoki/` 的翻译从 H0 切到唯一基线 Q2（ADR-0018、ADR-0017）。不做兼容、不保留 H0：产品里不留 Hy-MT2 后端、H0 配方、开关或迁移垫片；旧 `.work` 产物身份不匹配就按 `is_current` 重跑。

## 已定决定（不再询问）
1. Strata 由产品自动启停：names 阶段整批建表（llama-server）→ 停 server、确认显存释放 → translate 阶段执行不加参数的 `strata launch`，用 probe 核对 ADR-0017 的身份，不符就拒绝 → 整批结束或出错都执行 `strata launch --stop` 并核实显存释放。两者不得同时驻留；不需要翻译时不启动 Strata；编排被中断时也要 stop。
2. 删除发布时专名替换（`names/apply.py`、`names-apply.json`、APPLY 配方、`names_apply` 身份键）和 `[names] enabled` 开关，建表必开。表按 Q2 规则注入（只取 `confidence: high`，规则见 ADR-0017），表内容进翻译身份：手改表会触发重译，写进文档。
3. 失败路径：正常包请求与研究 Q2 逐字节一致（不用 grammar、思考关闭、两次尝试 seed／seed＋1）；两次都失败后按 10→5→1 拆批，单条仍失败只保留日文并计入回退报告。新产品配方新 hash。
4. 授权 GPU 验证：离线测试全过后，跑 Q2 首用 smoke 和一部产品整片。遵守 `.local/gpu.lock`，用 `Get-Process` 核实，不抢占。其他重任务不跑；改环境的命令（uv、just install）先问。

## 参照
- 按 AGENTS.md 任务表读：模块边界、受影响模块页（translation-subsystem、name-consistency、stage-plan、batch-orchestration、artifact-contract）、`docs/specs/bilingual-subtitle-pipeline.md`、测试与验证文档、CODING_STANDARDS。
- Q2 研究实现（只读，产品不得导入 `experiments.*`，需要就复制）：`experiments/translation_v3/{qwen,strata}.py`、`experiments/scene_batching_v6/v12.py::strata_recipe_data`、`names11.py::product_tables`；Strata 用法见 `docs/research/2026-11-08-strata-flash-next-usage.md`。

## 顺序
1. 先写 ADR-0019（产品切到 Q2，替代 ADR-0007 的翻译引擎、ADR-0010 产品配方、ADR-0014 的替换与开关），按决定索引"记录新决定"同步；先改模块边界与模块页，再写代码。
2. 切包沿用 `dp10-cut`，邻文换成 `wide-context-v1`（前 20／后 5）。
3. Strata 后端写成具体实现，不抽象通用后端协议；伪客户端测试。
4. 删掉产品里所有 H0 代码、资产清单与测试；`assets.toml`、`justfile`、`scripts/smoke/` 里产品用的 Hy-MT2 部分改为 Q2（研究侧仍需要的条目保留）；`llama_server.py` 只剩 names 使用时按最小设计重新判断其位置。`experiments/` 不动。
5. 按"随交付同步"更新文档、`kototoki.toml` 示例、依赖文档；检查待填标记。

## 验收
- `tests/core` 全过，含：禁止导入守门；产品请求与研究 Q2 逐字节一致（测试可导入 experiments 作参照）；降级与保留日文；Strata 未就绪／probe 不符／中途断开；不同时驻留；改表使翻译失效。
- `kototoki/` 无 Hy-MT2、APEX、`dp10-cut-degrade-v1`、`names_apply` 残留。
- smoke 记录内存与显存峰值、格式失败、交付失败、每包耗时；内存溢出或失败率明显高于 v12 F1（1599 包失败 0）就停下报告，不自改配方。
- 一部产品整片端到端跑 `python -m kototoki`，核对显存释放、双语 SRT 完整、回退计数。
- 完成报告区分已实现、自动检查、GPU 结果、未验证项。

## 不做
不改 Q2 配方、模型、提示、启动配置；不做多次翻译再挑选；不跑裁判、不开封确认集；不推送、不开 PR；分功能提交，中文提交信息。
