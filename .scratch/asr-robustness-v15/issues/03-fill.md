# 03 B1：空子段补窗实跑（两条守卫规则）

Status: resolved
Type: research
Stage: B（GPU ≤2 run）
Blocked by: —

权威：研究文档 §4.2、§5；v14 §4.2 B1 与 `experiments/asr_robustness_v14/fill.py`。

## 范围

- `python -m experiments.asr_robustness_v14 fill --rule doc-default`，再 `--rule whisper-or`；产物在 `.local/asr-robustness-v14/03/`。
- 报告每部：≥1 s 空子段数、补解子段数、守卫拦下数、空输出数、采纳字符数、官方 CER 前后（S／D／I）、删除降多少、插入涨多少、GPU 秒数；两条规则并列，附 v14 B0 的 110 参考字上限。
- 不设门，只写净变化与代价。

## 完成标准

- 两条规则的 JSON 报告；§7 一行；§8 第 3 项给用户的裁定材料（一句话：每部降多少、代价多少）。

## 执行记录

- 2026-11-10：`fill --rule doc-default`（GPU 1，墙钟 176.9 s）与 `fill --rule whisper-or`（GPU 1，墙钟 121.2 s）依次运行，开跑前 Get-Process／gpu.lock／nvidia-smi 核对无其他 GPU 作业。stdout／stderr 在 `.local/asr-robustness-v15/03/`，报告在 `.local/asr-robustness-v14/03/`。

## Answer

- 两条规则、两部电影官方 CER 都**升**：doc-default II +0.20 pp（净 +22 编辑）、III +0.14 pp（+16）；whisper-or II +0.18 pp（+19）、III +0.12 pp（+14）。删除降 10–26，但插入涨 19–29、替换涨 5–19。
- 补解 8＋8 个 ≥1 s 空子段只采纳 34–65 字／部，守卫最多拦 1 个；v14 B0 的 110 参考字上限只收回约四分之一。
- 代价：补解 1–31 s／部（含一次模型加载），加整部 align 重跑 ≈105–126 s／批。
- §8 第 3 项材料：B1 在两部上都是净变差，不建议进产品。
