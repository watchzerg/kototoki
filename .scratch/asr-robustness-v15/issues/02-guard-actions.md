# 02 A4：置空／折叠重复／补解三种动作的官方 CER，产品化草案

Status: resolved
Type: research
Stage: A（GPU ≤2 run：align 批）
Blocked by: 01

权威：研究文档 §4.1 A4 与"产品化草案"、§4.0、§5。

## 范围

- 对 01 选中规则在两部电影上标记的窗口做三种动作：置空（复用 v14 `guard.blank_align`）、折叠重复（与 01 的检测器一致，折叠后仍过守卫）、`no_repeat_ngram_size=5` 单次补解后折叠（复用 v14 `decode.W0Decoder`）。全部变体写产品形状 `asr.json`，一次 `align` 批处理，官方 CER（S／D／I）。
- 被改窗口的前后文字交 Opus 读感（与 01 合用预算）。
- 写产品化草案进研究文档 §8：阶段位置、`fail_window` 或替换写法、配方 id 与 `guard` 字段、配方 hash 测试、`cross` 规则是否够用、ADR-0023 要点、验收片。不实现（除非 §8 第 2 项预批准，另开 07）。

## 完成标准

- `.local/asr-robustness-v15/02/` 下三种动作的 CER 报告与对齐产物；§7 一行写选中的动作与理由；§8 草案成段。

## 执行记录

- 2026-11-10：`actions --rule repeat-strict`（GPU 1，墙钟 264.9 s；首次因输出目录不存在重定向失败未启动，重跑一次）。开跑前核对无 gpu.lock／llama-server／Strata。Opus 读感一窗三变体（≈12K token）。

## Answer

- repeat-strict 在产品样本只标 HF III 第 51 窗；HF II 三变体 CER 与对照逐项相同（零命中、零副作用）。
- HF III 第 51 窗：置空 −40 编辑（13.4150%）、折叠 −42（13.3973%）、补解＋折叠 −37（13.4414%）。Opus：折叠 > 补解 > 置空。**选折叠**（仍命中则置空）。
- 产品化草案已写入研究文档 §8 第 8 项（阶段位置、`guard` 配方字段与新 id、hash 重钉、cross 规则够用、ADR-0023 要点、验收）。
