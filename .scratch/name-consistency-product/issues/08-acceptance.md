# 08 产品路径验收：两部整片重跑、不一致率与等价校验

Status: done
Type: research
Blocked by: 06, 07

## 背景

用户 2026-10-19 裁定：验收只看总体正向，不做 Opus 逐行评审、不设比例线。冻结基准（ADR-0013）是研究脚本在 v4 提示表上的结果，产品用 v5 提示建新表，数字不要求一致。GPU 重任务，与 07 的 smoke 共用一次用户批准。

## 范围

1. 前置核对：GPU 空闲、无 `.local/gpu.lock`、无残留 llama-server；`.local/bilingual-fullfilm-08/w0.toml` 指向的两部整片工作目录仍在。运行前把两部当前的最终 `zh.srt` 复制到 `.local/name-consistency-product/before/`（替换前基线；发布会原地替换）。
2. `python -m kototoki .local/bilingual-fullfilm-08/w0.toml`：预期 STT 产物按身份跳过、翻译 run 读回不起 Hy-MT2、names 建表 2 部、重新发布。记录：退出码、names 阶段墙钟（加载、每部秒数、prompt／completion tokens）、启动前空闲与峰值显存（`names-sessions/…/engine-final.json`）、`names-apply.json` 的 `totals`。
3. **总体正向**判据：
   - ① 退出码 0，两部 `build.status == ok`，`cues_changed > 0`。
   - ② 不一致率：`python -X utf8 -m experiments.name_consistency.apply_table measure --pair HF-II before/zh.srt ja.srt --pair HF-II-after <发布的 zh.srt> ja.srt …`（CPU，研究脚本只读使用），两部替换后都不高于替换前。
   - ③ 等价校验：对产品写出的 `name-table.json`（去掉 `identity` 块后即 `name-table-v2`）用 `python -X utf8 -m experiments.name_consistency.apply_table --table … --ja ja.srt --zh before/zh.srt --out-dir …`（默认参数）跑一遍，`zh.replaced.srt` 与产品发布的 `zh.srt` 逐字节相同（只允许行尾差异；不同即 04 的移植有差异，回到 04 修）。
   - ④ 用户抽看两部 `names-apply.json` 的 `changes`（agent 列出改动最密的 5 分钟片段位置）。
4. 验收记录 `docs/research/acceptance/2026-10-XX-name-consistency-product.md`（模型、引擎、配置、输入、上述数字、文件位置 `.local/name-consistency-product/`），登记调研索引；ADR-0014 "证据"一节补产品路径数字；模块页"真实运行"一行。

## 完成标准

- 四条判据的结果如实写入验收记录；①②③ 全满足且用户看过 ④ 即通过，进入 09。任一不满足：报告给用户等待裁定，不调参、不换提示（ADR-0013 第 1 条）。

## 文件所有权

`docs/research/acceptance/2026-10-XX-name-consistency-product.md`、`docs/research/INDEX.md`、`docs/adr/0014-*.md`（证据一节）、`docs/architecture/modules/name-consistency.md`（真实运行一行）；`.local/name-consistency-product/`（不进 Git）。

## Comments

2026-10-20（agent）：执行完毕，判据 ①②③ 满足，④ 待用户抽看。用户授权的一次 GPU 运行（无重跑）：`python -m kototoki .local/bilingual-fullfilm-08/w0.toml` 退出码 0、117 s；STT 与翻译按身份跳过（未起 Hy-MT2），names 105.9 s（HF II 49.5 s／13240＋2382 tok，HF III 40.5 s／14609＋1844 tok），启动前空闲 15029 MiB、整机峰值 13445 MiB，无 WARNING／重试／重启。① 两表 `ok`（attempt 1，20／15 条），`cues_changed` 55／32。② 不一致率 0.151 → 0.135、0.121 → 0.094（term 集合 14 → 11、12 → 11）。③ 研究脚本输出与发布 `zh.srt` 逐字节相同（`95bcb9dc…`、`34b8067b…`，未归一行尾），totals、逐实体统计、unresolved 也相同。④ 最密 5 分钟：HF II 0:13:46–0:18:46（8 cue，Rider 7）、HF III 1:04:52–1:09:52（10 cue）。验收记录 `docs/research/acceptance/2026-10-20-name-consistency-product.md`，已登记调研索引、补 ADR-0014 证据一节与模块页"真实运行"；产物在 `.local/name-consistency-product/`。未改任何代码与参数。

