# 14 F1 有界思考

Status: resolved
Type: GPU
Stage: F
Blocked by: 13

范围、终点与门见研究文档 §4／§5（docs/research/2026-10-21-q0-exploration-v10.md）。

## 执行记录

- 实现：`qwen_options.thinking = {budget, min_visible}`。server `--reasoning on --reasoning-budget N`；目标条数 ≥ min_visible 的包 `enable_thinking: true`、`max_tokens` 加 N、预算检查同步；其余包请求与 v1 相同。配方 `qwen-think`（budget 1024、min_visible 10、context 20480，hash `826ba214…`）。
- 第一次 smoke（每包都开）5／5 失败：ID grammar 从第一个生成 token 起约束，模型直接输出 JSON、根本不思考；模板已预填 `<think>`，server 把整段 JSON 归入 `reasoning_content`，content 为空。探针（单次 server 会话）确认三种写法都可行：grammar 前加自由思考前缀 `thought "</think>" ws answer`（`thought ::= [^<]*`；字面量、token 写法结果相同），budget sampler 到点强制 `</think>`。采用 `thought-prefix-v1`。第二次 smoke 5／5 首次接受。
- 附带：思考模式下 Qwen3.8 模板在 system 前注入一行 "Reasoning effort is set to xhigh…"（模板默认，未改）。
- 19:50–20:25 生成 s20261011（218 包，69 包思考），20:37 判完。

## Answer

**关闭。** 对照 Q0（B 期间同日重判），1 seed（s20261011，1844 cue）：
- accuracy 剧集 +0.010［−0.033, +0.053］、电影 −0.012［−0.045, +0.021］——无改善；unnatural +0.010／+0.008（跨 0）；wrong-referent 剧集 −0.017［−0.045, +0.007］；剧集 critical +0.003［+0.001, +0.005］小幅显著变差。
- 只看思考包的 cue（点估计，无区间）：accuracy 剧集 +0.051（370 cue）、电影 +0.013（320），wrong-referent 剧集 −0.043；非思考包 −0.010／−0.017（与 Q0 请求相同，属随机差）。
- 代价：69／218 包思考，**全部用满 1024 token 预算被强制截断**；思考包平均 22.3 s 对非思考 3.8 s；墙钟 2113 对 913 s（**2.31×**），输出 token 2.6×。重试、失败 0。
- 门：墙钟 >1.5× 且 accuracy 无改善 → 关闭。重开条件：能在预算内完成思考的更短思考（或更大预算的代价可接受），且有理由认为长包上的指代改善不以 accuracy 为代价。
- 预算：F GPU 1＋smoke／探针短会话 3 次（合计约 5 分钟），裁判 $9.68／$20。
