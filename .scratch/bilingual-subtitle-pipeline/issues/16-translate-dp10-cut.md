# 16 产品翻译配方合并 dp10-cut 切包

Status: done
Type: task
Blocked by: 09, 15（已完成）

## 背景

研究侧完整 SRT 流程基线自 2026-10-17 起为 `dp10-cut`（[ADR-0010](../../../docs/adr/0010-dp10-cut-translation-flow-baseline.md)），产品包仍用 `b10-joint-degrade-v1`（固定 10 条一批、前后各 1 条邻文、不看时间戳）。ADR-0010 把"是否同步到产品"留作另行裁定；2026-10-18 用户裁定合并，并接受已交付影片因身份变化而重译的代价（[ADR-0011](../../../docs/adr/0011-dp10-cut-product-recipe.md)）。

## 范围

- `kototoki/translate/recipes.py`：`Recipe` 加 `gap_pack` 字段（None 时不进 `recipe`，有值时 `versions["gap_pack"] = "gap-pack-v2"`，与 v3 `spec()` 相同），新增 `DP10_CUT`（hash 须等于 v3 `ee72ce66…`）与产品配方 `DP10_CUT_DEGRADE_V1`（只差 `overflow`），`PRODUCT`／`RECIPE_HASH` 改指；`B10_JOINT`、`B10_JOINT_DEGRADE_V1` 保留并钉住。
- `kototoki/translate/batching.py`：`Cue` 带 `start`／`end`（秒，`start_ms / 1000`，与 v3 `translate-srt` 相同）；从 `experiments/translation_v3/batching.py` 复制 `silence`、`gap_pack_cuts`（只留 `group_gap=None` 分支）与邻文规则（`neighbours`）；`build_batches` 按 `recipe.gap_pack` 选切法。
- `kototoki/translate/degrade.py`：子批次改用 `batching.neighbours`，拆法不变。
- 不做：迁移旧 run、兼容开关、`Batch.record()` 加字段、`generate.py` 逻辑改动、任何提示／grammar／采样改动。

## 完成标准

- `just test` 全绿；`b10-joint`、`b10-joint-degrade-v1`、`dp10-cut` 三个 hash 钉子不变／等于 v3，新产品 hash 钉住；产品 `build_batches` 与 v3 `dp10-cut` 在不均匀停顿与随机场景上切包、邻文、提示、请求逐字节相同；gap-pack 规则用例（暴力枚举等价、切点挪向长停顿、≥20 s 必切、短包只在短段、邻文门槛、可见上限、缺时间戳）移植自 `experiments/scene_batching_v6/test_v7.py`，不导入 experiments。
- 两部整片现有 `ja.srt` 的离线切包统计记入 ADR-0011；`translate.plan` 对它们返回 `needs_model=True`，旧目录保留。
- 一部影片经 `python -m kototoki` 真实翻译（GPU 重任务，执行前另问），记录批次数、降级与回退计数、墙钟。
- 文档随交付同步：ADR-0011；翻译子系统模块页；模块边界；规格 §1.2、§6、裁定表；GLOSSARY；AGENTS.md；技术选型；架构总览；调研索引时间线。

## 文件所有权

`kototoki/translate/{recipes,batching,degrade}.py`、`tests/test_translate_recipes.py`、`tests/test_translate_degrade.py`、`tests/test_translate.py`（`document()` 加 20 s 停顿）、上列文档。

## Comments

- 2026-10-18 建票并实施（直接在 main 上开发）。用户裁定：接受已交付影片重译，不加开关；验证做到一部影片真实运行。
  - 实现：新产品 hash `086754ca…158e`；`dp10-cut` 移植 hash 与 v3 一致。`tests/test_translate.py` 的 `document()` 改为每 10 条之间留 20 s 停顿，使 dp10-cut 在续跑与降级测试里仍切出 10 条一批，批次机制用例只改邻文期望（跨 20 s 停顿的邻文不可见）。
  - 自动检查：`just test` 342 个用例通过；`kototoki/` 不导入 `experiments.*`。
  - 离线统计（四个 `ja.srt`）：平均每批 7.4–8.3 条、请求数 +20–35%、跨 ≥10 s 的批 44–55% → 19–24%、无跨 ≥20 s、切点在 ≥1 s 停顿 92–97%、<6 条的批 9–24%，见 ADR-0011 表。
  - 真实运行（用户裁定跑 `w0.toml` 两部）：日志 `.local/bilingual-fullfilm-08/driver-w0-dp10cut.out`。out-w0 的 STT 产物是 10-14 的，票据 10–12 已让 vad／asr／align／ja-cues 身份过期，所以整条链重跑（vad 83 s、asr 294 s、align 97 s），总墙钟 3593 s，退出码 0，2 部发布。翻译：HF III 1219 条／147 批／200 s，HF II 1099 条／149 批／2906 s；两部各 1 个 session、请求数 = 批次数、降级 0、回退 0。HF II 第 96 批起生成约 4 tok/s（之前约 175）直到结束，server 峰值显存 15955 MiB，请求形状正常；疑为显存触顶回落系统内存，未验证、未复现，与配方无关的可能性最大。旧 run 目录 `b10-joint-degrade-v1__s20261008` 保留。
  - Status 改 done：完成标准三项全部达成；慢化现象另议（不属本票）。
