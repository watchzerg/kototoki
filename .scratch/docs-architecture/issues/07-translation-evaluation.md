# 07 现行翻译评估方法页

Status: resolved
Type: task
Blocked by: 05

范围见 [spec §4 票据 07](../spec.md#07-现行翻译评估方法页)。

## 执行记录

- 核实与起草委派给子 agent（`opus`，只读仓库，没有运行任何裁判或 GPU 入口），主 agent 复核后落到
  `docs/agents/translation-evaluation.md`（5,875 字符，最长行 401）。
- 先核实了"现行方法到底是什么"：
  - `docs/plans/claude-judge-profile.md` 自己的状态行写 superseded（2026-10-10）：它设计的 `claude-opus-5-5-auto-v1` 从未使用，
    被 v3 计划 §4 的 MQM profile 取代。所以它不是现行方法，新页面只把它列为迁移分析。这是过时描述，不是矛盾。
  - 现行有**两个** profile：`claude-opus-5-5-mqm-v1`（dev 集，定义在 `experiments/translation_v3/judge.py`）与
    `v5-asr-pairwise-v1`（产品 ASR 源成对评审，定义在 `experiments/quality_v5/asr_source.py`）。v12、v13 两轮都写"两个裁判 profile 不改"，v15 只用后者。
- 页面内容：两个 profile 与共用执行面、模型身份检查、入口命令、统计口径、对照与确认集规则、不可混用的分数、冻结的 Codex 时代流程、来源。
  每条都有文件依据（子 agent 报告给了逐条的文件位置）；页面里的反引号路径都存在。
- 指向它的入口：`AGENTS.md` 触发表加一行（加后 `AGENTS.md` 仍在预算内）、`docs/testing/INDEX.md`、`docs/INDEX.md`。
  这也补上了票据 03 对照表里"旧评估方法与现行裁判 profile"的落点。
- 没有改 `docs/agents/subtitle-translation-evaluation.md`（被代码取 sha256 并读取）。
- 核实不了或没有定论的 5 点写进 spec §8 第 5 项，页面没有替它们下结论。

## Answer

完成。`just docs-check` 通过。`docs/plans/claude-judge-profile.md` 原先没有任何入链，现在由计划索引与本页链接。
