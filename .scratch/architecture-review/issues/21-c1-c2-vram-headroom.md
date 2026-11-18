# 21 翻译时显存余量不足与运行中慢化

Status: needs-triage
Type: research
Blocked by: —

## 来源

[2026-10-19 审计报告](../2026-10-19-report.md) §1 C-1、C-2（报告时判断：C-1 推测、C-2 已核实）。报告基于 commit 12e4ff6 与当时的真实运行；本票据建于 2026-11-18，现状没有重新核实。

## 问题

C-1：HF II 从第 96 批起降到 4 tok/s，最可能是运行中显存触顶，被 WDDM 换出到系统内存（整片翻译 200 s 变 2900 s）。C-2：server 约 14.8–15.0 GB＋保留 325 MiB，桌面只剩约 1 GB，14700 阈值依赖 WDDM 驱逐桌面显存。

## 证据（报告时）

`server.log`、`server.py` 的 `MIN_FREE_MIB` 与显存遥测。

## 报告建议

C-1：落盘显存时间序列并加生成速度 watchdog（约 40 行），或在 NVIDIA 控制面板设 Prefer No Sysmem Fallback。C-2：KV 改 q8_0 或 ctx 降到 4096，会动配方，需研究。

## 分诊

先对照当前代码确认问题是否还在，再决定修、只补文档，还是 wontfix。 报告针对 llama-server 时期的翻译；产品翻译与建表已改在 Strata 上（ADR-0029、ADR-0028），先确认这一条是否仍适用，不适用就 wontfix。

## Comments
