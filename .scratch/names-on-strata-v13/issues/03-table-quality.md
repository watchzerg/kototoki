# 03 表质量（dev 对参考、产品描述）

Status: resolved
Type: 离线
Stage: C
Blocked by: 02

范围、终点与门见研究文档 §4.3（docs/research/2026-11-08-names-on-strata-v13.md）。

## 执行记录

- 2026-11-09 用户放行 v4（§8 第 8 项 (a)）；`CANDIDATE = "v4"`，`v13-quality` 读 `B4/`，日志 `logs/quality-v4.log`，产物 `C/table-quality.json`、`C/{27b,s1}/02-table-agreement.json`。串名逐条看过（只在本地看，不写名字）。

## Answer

**S1 v4 dev 表非劣（未达改善），不阻断 D、E。** 一致率 Δ +0.054 [−0.032, +0.132]，high 不一致率 Δ −0.046 [−0.121, +0.033]；条目多 65%，真串名 3 组对 27B 1 组；产品表 A/A 写法 Jaccard 0.56／0.48。详见研究文档 §7。

以下为旧答案（v2 时未跑）：

S1 v2 同样不过门，未跑：票据 02 可行性门不过，按研究文档 §4.2／§5"B 不过就停"，阶段 C 不执行。GPU 0、裁判 $0。
