# 02 `docs/adr/CURRENT.md`

Status: resolved
Type: task
Blocked by: 01

范围见 [spec §4 票据 02](../spec.md#02-docsadrcurrentmd)。

## 执行记录

- 起草委派给子 agent（`opus`，只读仓库，草稿写在仓库外），来源限定为 25 篇 ADR 正文与决定索引现有文字；主 agent 复核后落到 `docs/adr/CURRENT.md`。
- 内容：翻译基线 Q3（对照规则、翻译规则表、建表 `names-strata-v4`、服务与运行、前任 Q2）、产品翻译、产品建表、
  STT 基线与产品 STT（设备、引擎）、ASR 复读守卫、专名、其他现行产品决定（架构、输入与发布、内嵌字幕、包边界、方法禁区），
  以及 0010、0014、0015、0017、0018 五篇仍有效与已被取代的条款表。
- 主 agent 补了两处，来源都是决定索引现有文字：阶段链，以及 v13、v15 两次专名重开的结束。
- 决定索引：现行表每行压成一句话加 `CURRENT.md` 锚点与权威 ADR；"更新于"那段改成页尾"更新记录"；
  "记录新决定"加一步"改 `CURRENT.md`"。"未关闭项"留给票据 06。
- 改前搜过 `experiments/`、`scripts/`、`kototoki/`、`kototoki_eval/`、`tests/`：没有代码校验 `docs/adr/INDEX.md`。
- 触发了"ADR 之间有矛盾"的停止条件 1 项（已发布影片是否重新发布），另有 2 类 ADR 正文过时但状态行未标的情况：
  `CURRENT.md` 只写能确认的部分，三项都记入 spec §8 第 1–3 项，没有自行取舍，也没有改 ADR。

## Answer

门通过：脚本提取 `CURRENT.md` 里全部 40–64 位十六进制串与带连字符的反引号标识，逐个在 `docs/adr/0*.md` 正文里查，缺失 0 个。
`just docs-check` 通过。`CURRENT.md` 在 L2 预算内（≤ 12,000 字符、最长行 < 800）。
