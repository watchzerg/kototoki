# 17 翻译耗时构成与不改输出的提速项

Status: needs-triage
Type: research
Blocked by: —

## 来源

[2026-10-19 审计报告](../2026-10-19-report.md) §1 C-3（报告时判断：已核实）。报告基于 commit 12e4ff6 与当时的真实运行；本票据建于 2026-11-18，现状没有重新核实。

## 问题

翻译 384.9 s：decode 273.5 s（71%）、prompt eval 83.2 s、server 间隙 9 s、客户端 19 s；起 session 前另有 16.4 s（模型 SHA 首次全量 8.6 s＋冷加载 6.6 s）。`--cache-ram 8192` 的 290 次查找 0 命中。

## 证据（报告时）

`batches.jsonl`、`server.log`。

## 报告建议

不改输出的：`--cache-ram 0`、模型校验缓存放到 `.local` 共享。会改输出的（需研究）：`-b/-ub 512`、`-np>1`、投机解码、KV 量化。

## 分诊

先对照当前代码确认问题是否还在，再决定修、只补文档，还是 wontfix。 报告针对 llama-server 时期的翻译；产品翻译与建表已改在 Strata 上（ADR-0029、ADR-0028），先确认这一条是否仍适用，不适用就 wontfix。

## Comments
