# 地图

## 接跑手册

1. 读计划 §7，找第一张未 resolved 且 Blocked by 全部 resolved 的票据。状态以文件为准。
2. 顺序：01 纯函数 → 02 配方与 worker 接入 → 03 文档同步 → 04 GPU 验收。
3. 每完成一张：票据写 Answer 并标 resolved；本文 Decisions-so-far 加一行；计划 §7 加一行；Git 提交（中文）。
4. GPU 只在 04：开跑前 `Get-Process`（无 llama-server、Strata、其他 GPU 作业）、读 `.local/gpu.lock`；不杀进程。

## Notes

- 票据拆法沿用计划 §4，一处调整：配方块、新 id 与重钉 hash 从 02 提前到 01（`guard.RULE` 取自配方块，理由见票据 01）。接口形状的文档（模块边界一行、STT worker 页"接口与依赖"）随 01 先改；行为与产物的文档在 03。
- `just docs-check` 在 main 上本就失败（冻结外链），只看新增条目。

## Decisions-so-far

- 2026-11-11 立项：按计划 §3 执行，tracker 建在本目录。
- 2026-11-11 01：`kototoki/guard.py`、配方块与新 hash 完成（[票据](issues/01-guard-module.md)）。
- 2026-11-11 02：worker 接入 w0 与 cross 完成，离线门禁全绿（[票据](issues/02-recipe-and-worker.md)）。
- 2026-11-11 03：技术设计、STT worker 页、产物契约、阶段计划页同步完成（[票据](issues/03-docs.md)）；ADR 状态行与决定索引挪到 04 收尾。
- 2026-11-11 04：GPU 验收第 1、2 项通过，smoke 只跑 STT 六项（五过一旧差异）；计划改 done（[票据](issues/04-gpu-acceptance.md)）。

## Fog

- `just smoke` 不带参数会跑 `llama_stock`、`translate_product`、`names_product`（起 llama-server／Strata），与"不启动 Strata、不起 llama-server"冲突：04 时只跑 STT 相关项并写 §8。
- `experiments/asr_robustness_v14/test_offline.py` 钉着产品 W0 的旧 hash（研究期测试，不在门禁内、不可改）：02 后它会失败，写 §8。
