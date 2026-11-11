# Q 线 v9–v13（通用模型翻译与 Strata）

状态：current（子索引；条目是登记时的摘要，结论以报告正文与[决定索引](../../adr/INDEX.md)为准）

条目格式：`[主题](文件.md)：一句话结论；适用条件或限制`。条目文字自[调研索引](../INDEX.md) 2026-11-11 拆分时原样搬来，新报告在对应小节追加一条。

## 字幕翻译流程第九轮：通用模型在同一接缝下直接翻译（2026-10-21）

- [方案、进度与结论](../2026-10-21-general-model-translation-v9.md)：concluded（建议 L3，待裁定）。固定 dp10-cut 的切包、邻文位置、joint 语义与 ID JSON 输出，只换模型为 Qwen3.8-27B UD-IQ3_S（b11669、`--reasoning off`、`qwen-joint-v1` 为 Hy joint 文字原样拆成 system／user、GBNF 作 chat grammar），臂 `qwen-narrow`／`qwen-wide`（前 20＋后 5 只读邻文），对照 Hy-MT2 dp10-cut 同包同期裁判。结果（dev 三 seed、5397 cue）：wide 剧集 −0.058、电影 −0.091（都显著，来自 wrong-referent、mistranslation、major+），narrow 非劣无改善，宽邻文对 Qwen 有效（与 v3 对 Hy-MT2 的 ctx3 结论相反）；unnatural 显著上升、墙钟 3.3×、显存 13 GB；专名指标无一致方向；无泄漏。保留设施：`translation_v3/qwen.py`、`Recipe.model`／`wide_context`、`scene_batching_v6 --round v9`。未覆盖：重复 seed、确认集、产品时间轴、非 LLM 裁判

## 字幕翻译流程第十轮：Q0 通用模型线突破 H0 接缝的广度探索（2026-10-21）

- [方案、进度与结论](../2026-10-21-q0-exploration-v10.md)：concluded（2026-10-22 结题，待用户裁定 §8；唯一候选成分为 ASR 源专用的专名表注入 `q0-names`）。对照 Q0（`qwen-wide`），六个阶段：A 重复 seed 复现＋非 LLM 佐证与盲读表；B `qwen-joint-v2` 针对自然度的 system 提示；C 邻文梯度（前 50／整场景）与输出包 10→15；D 在 HF II／III 产品 `ja.srt` 上做 Q0 对 H0 基线、ASR 感知提示、专名表注入对替换（复用 v5 第 02 步分桶与 `v5-asr-pairwise-v1`）；E 每部一次请求的整片简报；F 有界思考。每臂有对照、终点与门，预算 GPU 50 run／裁判 $450，A 不复现则全轮停止；不组合、不锁定候选，结题交候选成分清单。不做：多样本、语序重排、成本线、其他模型、改产品、开确认集

## 字幕翻译流程第十一轮：Q0 产品路线的成分验证（2026-10-22）

- [方案、进度与结论](../2026-10-22-q0-product-route-v11.md)：concluded（2026-10-23 结题，待用户裁定 §8；唯一候选成分为产品 ASR 源专用的专名表注入 N\*＝`q0-names-high`，dev 护栏未过）。原计划：v10 结题后的补测：专名表注入（诊断 dev 反向、至多一次修订、dev 3 seed 护栏、产品新 seed 复现）、注入＋`qwen-asr-aware-v1` 的增量、跨段截断 `seg10`；过门成分≥2 时组合对 Q0＋替换检查。预算 GPU 19 run／裁判 $125。新基线身份交用户裁定。

## 字幕翻译流程第十二轮：Strata＋Qwen3.8-Flash-Next 对照 Q1（2026-11-08）

- [Strata 用法调研](../2026-11-08-strata-flash-next-usage.md)：基于本机 Strata 0.2.12（引擎 build 0.1.58）的随包文档与服务端源码，整理启停命令、HTTP 字段，以及接到 Q1 翻译步的差异。结论：可以通过 OpenAI 兼容的 `/v1/chat/completions` 附着调用；但**没有 GBNF**，也没有 `/apply-template`、`/tokenize`；运行时内存约 51 GB、显存约 15.6 GB，不能与 llama-server 同时驻留。未跑 GPU，未验证项列在文末。
- [方案（v12）](../2026-11-08-strata-flash-next-v12.md)：concluded（2026-11-08 结题；用户裁定 F1 为 Q 线新基线候选，基线仍是 Q1；§8 第 5 项 DFlash2 对比为后续）；立项为 2026-11-08 用户裁定，含有界思考阶段。候选 F1 只换翻译模型，对照 Q1，复用 v11 已有的 Q1 译文。阶段依次为：smoke 可行性门（格式失败与交付失败）→ dev 3 seed → 产品 ASR 源 seed 54–56 →（条件触发）有界思考。预算 GPU 10 run／裁判 $115。

## 专名建表第十三轮：Strata＋Qwen3.8-Flash-Next 对照 27B 建表（2026-11-08）

- [方案（v13）](../2026-11-08-names-on-strata-v13.md)：concluded（2026-11-09 结题；S1 v1–v4 都不过原可行性门，放行 v4 后 C–E：表非劣、产品与 dev 电影翻译更好，但 dev 剧集 wrong-referent 显著变差，S1 不进，建表维持 27B；2026-11-09 用户仍采纳 S1 v4 为基线 Q3，ADR-0021）。候选 S1 只换建表模型与引擎（Strata Flash-Next，Q2 启动方式），对照现行 27B 表；翻译两臂都用 Q2 规则、只差注入的表。阶段：建表可行性门 → dev 表质量非劣 → dev 翻译 3 seed → 产品 ASR 源 seed 54–56。预算 GPU 13 run／裁判 $80。
