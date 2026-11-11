# 04 GPU 验收（计划 §5）

Status: resolved
Type: task
Blocked by: 03

范围与终点见计划 §4 票据 04（docs/plans/asr-repeat-guard.md）。

## 执行记录

- 2026-11-11：preflight 干净（无 llama-server／Strata／python，无 gpu.lock）。`acceptance.py` 跑 asr＋align：HF III 第 51 窗 collapse 94 → 31 字，CER 13.3973%（769／448／304）；HF II 零命中，CER 16.8073%（876／676／260）与对照相同；其余窗口全等。
- smoke：首次尝试因管道下 cp1252 打印崩溃（第一项后中断）；`PYTHONUTF8=1` 重跑 STT 六项：四项通过，两项冻结窗口启动即 `TypeError`（过期的 `work_root(out)` 调用）；修一行后重跑：`stt_frozen_window` 通过，`x0_frozen_window` 窗口 0 文字不同（已接受的旧差异）。`llama_stock`／`translate_product`／`names_product` 未跑（会起 llama-server／Strata）。
- 2026-11-11 补跑：用户授权后跑 `llama_stock`／`translate_product`／`names_product`，三项通过；Strata 已停、显存释放。
- 2026-11-11 用户裁定把 x0 窗口 0 的已接受差异写进 `x0_frozen_window.py` 判定；重跑通过。smoke 九项全部通过。
- 收尾：ADR-0023 状态行、决定索引、调研索引、文档索引、计划 §7／§8 与状态。

## Answer

三项全部通过，未触发停止条件；过程与裁定在计划 §8 第 2–4 项。
