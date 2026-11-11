# 02 建表：从整片 ja.srt 抽多对一专名表

Status: resolved
Type: prototype

## Answer

- 实现 `experiments/name_consistency/build_table.py`（子 agent 写，主 agent 审），测试 19 项。请求走 `/v1/chat/completions`，带 `response_format: json_schema`、Qwen non-thinking 采样、`seed 20261019`（重试 +1）、`finish_reason == length` 视为失败。
- 提示迭代四版（记录在 `PROMPT_VERSION`）：v1 贪心循环；v2 加采样与 schema 后成功但 `zh_variants` 混入角色真名、`ja_variants` 混入别的角色；v3／v3b 加"同一个词的不同写法"、"同一对象"、粒度规则并把示例换成 EVA 以免泄露 Fate 答案，**no-think 下粒度规则不被执行**；v4 改 schema `name-table-v2`：每个日文写法带同粒度的中文（`forms: [{ja, zh}]`），从结构上消除粒度问题。
- 八张 v2 表（4 部 × think／no-think）：think 每部 16–26 条、32–44 个写法，confidence 出现 medium／low；no-think 13–17 条、全部 high（无区分度），HF III x0 还把作品猜成 FGO。think 遵从规则明显更好（マスター／サーヴァント 收进来、コトミネ→言峰 粒度正确、`zh_variants` 不混真名）。
- 仍存在的模型错误（think 也有）：把 シンジ（慎二）并进士郎；ゾウケン 的中文名错（言峰绮礼／佐仓惣一郎）；アンリ・マユ 译名幻觉；偶发 遠坂桜（应为間桐）。属 IQ3_S 的知识与判断上限，提示改不动。
- 产物：`.local/name-consistency/02-four/`（v1 schema 表）、`.local/name-consistency/03-four-v2/`（v2 表与替换结果）。

## 范围

- 新脚本 `experiments/name_consistency/build_table.py`（离线部分可不依赖模型）：
  - 读 `ja.srt`，剥时间轴，输出"编号\t日文"行；整片一次放进提示（HF 两部 10.9K–12.1K 字符，预估 8K–12K tokens，16K 上下文足够，不分块）。
  - 提示：只收人名、角色名、职阶名／称号等固定专名；剔除作品名片段与普通名词；不收称呼词。每条输出 `{"canonical_ja", "ja_variants": [...], "zh", "zh_variants": [...], "evidence": [cue 编号]}`，`ja_variants` 含 ASR 可能写错的形式，`zh_variants` 含模型可能用的其他中文写法（音译变体、英文原名）。要求 JSON 输出；用 grammar 或后验校验。
  - 通过 llama-server HTTP 调用（复用项目已有的客户端形状），记录请求与响应、tok/s；输出 `table.json`。
- 在四份 `ja.srt`（HF II／III × w0／x0）上各建一次，同一部两路的表应基本一致，差异记录。
- 先 no-think；有余力再跑一次 think 对比条目差异，不作结论。

## 判定（人工）

- 对照 v5 第 4 步在产品整片上标出的术语清单（`consistency.py srt` 输出）：表是否覆盖了那些不一致项；是否把 ASR 误识（東坂、四郎、萨克 的日文源）归到正确的人名；中文译法是否为通行写法。
- 记录错条目（作品名片段、普通名词）的数量。

## 文件所有权

`experiments/name_consistency/`（新目录）、本票执行记录。不改 `kototoki/`。

## Blocked by

- 01（真实输出；提示与解析可先用伪客户端写好并加单元测试）。
