# 04 L2 筛选：存活臂与对照补 seed 20261012、20261013，三 seed 合并

Status: resolved
Type: task
Blocked by: 03

## 执行记录

- 2026-10-21 claimed。两个 Qwen 臂都存活，补 6 个 run（2 seed × 3 臂），GPU 预算正好用满（10／10）。启动前 GPU 空闲、无锁。6 个 run 全部 complete、单 session、无重试、无失败；`check-batches --seed 20261012|20261013` 三臂目标 ID 逐字相同。
- 全集裁判 6 套（93／97／… 包），未遇配额阻塞；三 seed 累计 9 套 816 包，标价 $87.41（≤ $100）。
- `compare9 --seeds 20261011 20261012 20261013 --label l2` 三组配对 → `summaries/v9-*-l2.json`；`analyze9 names|leak --seeds 三个` → `summaries/v9-names-s20261011-20261012-20261013.json`、`v9-leak-s…json`。
- 三个 seed 合起来覆盖整个 dev 一次：44 场景、5397 cue（剧集 3415、电影 1982），15 部作品。

## 结果（三 seed 合并；Δ = 候选 − 对照，CI90）

| 配对 | 剧集 accuracy Δ | 电影 accuracy Δ | 总览 | 非劣（上界 <0.05） | 改善（上界 <0） |
| --- | --- | --- | --- | --- | --- |
| qwen-narrow − dp10-cut | −0.020［−0.067, +0.029］ | −0.034［−0.097, +0.031］ | −0.027［−0.066, +0.014］ | 两类是 | 否 |
| qwen-wide − dp10-cut | −0.058［−0.104, −0.010］ | −0.091［−0.152, −0.028］ | −0.074［−0.113, −0.035］ | 两类是 | **两类是** |
| qwen-wide − qwen-narrow | −0.038［−0.074, −0.002］ | −0.057［−0.108, −0.006］ | −0.048［−0.079, −0.016］ | 两类是 | 两类是 |

对照水平：剧集 0.418、电影 0.424（L1 单 seed 的 0.507／0.489 与 −0.09～−0.18 的效应在补满三 seed 后都回落，单 seed 高估）。

分项（wide 对对照，剧集／电影）：wrong-referent −0.035［−0.058, −0.013］／−0.038［−0.067, −0.008］，addition −0.004／−0.007（电影显著），major+ −0.009／−0.011（都显著），mistranslation −0.020／−0.048（总览显著），critical 无差，negation-number-condition 无差；**omission 电影 +0.011［+0.004, +0.019］变差**；cue-attribution 电影 +0.003（首次非零，极小）；**unnatural +0.019／+0.014 显著变差**，fluency 总分剧集 +0.012 显著变差，grammar、register 无差。narrow 对对照：wrong-referent（电影）、addition 改善，unnatural +0.030／+0.014、omission 电影 +0.006 变差。wide 对 narrow：mistranslation 两类显著改善，unnatural 剧集改善，omission 剧集 +0.006 变差。

逐作品（wide − 对照）：15 部中 12 部 Δ < 0；正的是 W07 +0.082、W10 +0.064、M04 +0.011。

专名：名称相关裁判错误（剧集／电影）对照 42／39、narrow 63／41、wide 49／33（每千 cue：对照 12.3／19.7、narrow 18.4／20.7、wide 14.3／16.6）；不一致率（类别均值）对照 0.064／0.003、narrow 0.052／0.019、wide 0.048／0.029——剧集略好、电影变差，无一致方向。

泄漏：wide 标记率 3.5%／4.0%，对照 3.6%／4.4%、narrow 3.3%／3.6%（同一检测）；wide 独有命中 53 条（主 seed 的 19 条已人工分类：真泄漏 0），不另读。

代价（三 run 合计）：墙钟 Hy 824 s、narrow 2517 s（3.05×）、wide 2695 s（3.27×）；生成 194／60／60 tok/s；输入 token 411K／439K／847K，输出 109K／130K／131K；显存峰值 Hy 15.9 GB、narrow 12.5–12.7 GB、wide 13.0–13.2 GB；载入 6–8 s／5 s；重试、降级、交付失败、`prompt_tokens` 不一致全部为 0。

## 预算

GPU run 10／10；裁判 $87.41／$100。

## Answer

**`qwen-wide` 在 accuracy 上两类都显著好于 dp10-cut（剧集 −0.058、电影 −0.091，约 −14%／−21%），符合 §5"改善"的写法；`qwen-narrow` 非劣但无改善。** 改善来自 wrong-referent、mistranslation、major+；代价是 unnatural 显著上升、电影 omission 小幅上升、墙钟 3.3 倍。宽邻文对 Qwen 有效（与 Hy-MT2 的 v3 ctx3 结论相反），且无泄漏证据。单 seed 的 L1 效应量明显高估。
