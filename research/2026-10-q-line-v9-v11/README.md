# Q 线 v9–v11：通用模型（Qwen3.8-27B）在同一接缝下翻译，及专名表注入

## 状态
concluded。v9 于 2026-10-21 结题，v10 于 2026-10-22 结题，v11 于 2026-10-23 结题；结论落成 [ADR-0021](../../docs/adr/0021-q3-strata-names-baseline.md)（原 ADR-0015、ADR-0016、ADR-0017，现见「H0（历史）」「Q0（历史）」「Q1 与 F1（历史）」）。Q 线基线后续沿革见 [v12–v13](../2026-11-strata-v12-v13/README.md)。

## 时间
2026-10-21 立项（v9）至 2026-10-23 结题（v11），三轮连续执行。

## 问题
翻译侧此前只在专用 MT（Hy-MT2）之上探索。换成本卡能跑的通用模型 Qwen3.8-27B，在 H0 的切包、邻文与 ID JSON 接缝下，译文质量能否不输并有改善？若能，哪些成分值得加进新基线？

## 策略
- v9：固定 H0 的 `dp10-cut`（切包、邻文位置、joint 语义、ID JSON 输出），只换模型。臂：`qwen-narrow`（同 1＋1 邻文）、`qwen-wide`（前 20＋后 5 只读邻文）；对照 Hy-MT2 `dp10-cut` 同包同期裁判。`qwen-wide` 命名为 Q0。
- v10：六阶段广度探索，对照 Q0。A 重复 seed 复现与盲读表；B 针对自然度的 `qwen-joint-v2` system 提示；C 邻文梯度（前 50／整场景）；D 产品 ASR 源上 Q0 对 H0、ASR 感知提示、专名表注入对生成后替换；E 整片简报；F 有界思考。
- v11：补测专名表注入（先诊断 dev 反向，至多一次修订为只注入 `confidence: high`）、注入叠加 ASR 感知提示、跨段截断 `seg10`。

## 环境与版本
- 翻译模型：`unsloth/Qwen3.8-27B-GGUF` 的 `UD-IQ3_S`（revision `4ca72078`），llama.cpp b11669（win-cuda-13.4）llama-server，GBNF 作 chat grammar，`--reasoning off`；采样为 Qwen 官方 non-thinking（temperature 0.7、top_p 0.8、top_k 20）。
- 对照 H0：Hy-MT2 30B-A3B APEX-I-Compact，冻结 compat 引擎 b11429。
- 裁判：`claude-opus-5-5-mqm-v1`（Opus 5.5 上的 MQM 评审 profile，每包 4 窗，对照在同包组成下同期重判）。
- GPU RTX 5080。显存峰值 Qwen 12.5–13.2 GB（Hy-MT2 15.9 GB）。

## 测试
- dev：v4 起沿用的 44 场景、5397 条 cue（剧集与电影，来自 15 部作品，字幕组时间轴）。主 seed 20261011–13，重复 seed 20261021–23。
- 产品 ASR 源：2 部日语电影（HF II／III）的产品 w0 `ja.srt`，seed 51–53（v10）、54–56（v11），按重叠单元普查（约 1700 单元）。
- 指标：accuracy Δ（每条 cue 的惩罚差，候选减对照，作品等权，窗口 bootstrap CI90；剧集、电影分开）；分项 fluency、wrong-referent、major+ 等；人名相关错误数与整片不一致率。非劣界 0.05，"改善"只在 CI90 上界 < 0 时写。
- 未开封任何确认集；未做人工盲读（用户 2026-10-22 裁定不读，自然度不是首要关注点）。

## 结果
v9（dev 三 seed，5397 cue，对照 H0）：

| 臂 | 剧集 Δ | 电影 Δ | 说明 |
| --- | --- | --- | --- |
| `qwen-wide`（Q0） | −0.058 | −0.091 | 都显著，来自 wrong-referent、mistranslation、major+ |
| `qwen-narrow` | −0.020 | −0.034 | 非劣无改善 |

v9 其他：unnatural 显著变差（约 +0.02／+0.014），墙钟 3.3×；宽邻文对 Qwen 有效（与 v3 对 Hy-MT2 相反）；无泄漏；专名指标无一致方向。

v10/v11（对照写明）：

| 项 | 对照 | 结果 |
| --- | --- | --- |
| Q0 优势复现 | H0 | 剧集 −0.106 复现，电影 −0.012 跨 0；与 v9 合并 −0.082／−0.052 |
| 产品 ASR 源 | H0 | Q0 全体 −0.69/单元，人名错误 22 对 50，不一致率 0.047 对 0.126 |
| `qwen-joint-v2`（压 unnatural） | Q0 | unnatural 降，但剧集 accuracy 显著变差（+0.047／+0.073），关闭 |
| 邻文前 50／整场景 | Q0 | 前 50 非劣无改善；整场景电影 wrong-referent 变差 |
| 整片简报；有界思考 | Q0 | 简报非劣无改善；思考 2.31× 墙钟、无改善，关闭 |
| 专名注入 v10（整表） | Q0＋替换 | ASR 源：不一致率 0.010 对 0.050、人名错误 96 对 142；dev 干净源方向相反 |
| 注入 N\*（只注入 high） | Q0＋替换 | ASR 源新 seed：全体 −0.050（非劣），人名错误 120 → 72；dev 干净源两类 accuracy 显著变差 |
| 注入叠加 ASR 提示；跨段截断 | N\*／Q0 | 都不进（exact 桶显著变差；截断产品全体 +0.104 显著变差） |

## 结论与去向
- 采纳：Q0＝`qwen-wide` 作为通用模型线基线（对 H0 在剧集与电影都显著更好且非劣）；其后（原 ADR-0016，现并入 ADR-0021）采 N\*（Q0＋只注入 high 的专名表）为 Q1，适用范围限产品 ASR 源。H0 基线保持为产品当时实现，直到 [ADR-0029](../../docs/adr/0029-translate-per-cue-resolution.md)（原 ADR-0019）进产品。
- 放弃：自然度提示修订、更宽邻文、整片简报、有界思考、ASR 感知提示、跨段截断；多样本再挑选不做（[ADR-0008](../../docs/adr/0008-no-multi-translation-selection.md)）。
- 未决项留给后续轮次：专名表质量（dev 反向的主因是表条目本身错，且错条目多为 `high`，34% 与参考多数不一致）；确认集未建；同 seed、同提示的 llama-server 输出并不确定（约 24% 的相同提示单元输出不同），所有"同 seed 配对"含一层噪声底。

## 教训
- 通用模型的宽邻文有效，专用 MT 的结论（ctx3 无效）不能外推。
- 注入表的效果完全系于建表质量：表好则注入好，表错则错得更一致；建表质量是注入能否通用的前提。
- 比较两侧文本完全相同时（如注入＋替换对注入），先 diff 再送裁判，可省一次裁判费。
- 思考模式配 grammar 时需给 grammar 加思考前缀（llama.cpp b11669 的 grammar 从第一个生成 token 起生效）。
- 预算：v10 GPU 37 run、裁判约 $288；v11 GPU 16 run、裁判约 $85；v9 GPU 约 10 run、裁判约 $60–100 范围内。

## 原始材料
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-21-general-model-translation-v9.md`
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-21-q0-exploration-v10.md`
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-22-q0-product-route-v11.md`
