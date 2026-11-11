# 02 smoke：5 个包上两个 Qwen 臂各生成一次并人工检查

Status: resolved
Type: task
Blocked by: 01

## 目标

研究文档 §5 第 2 条：dev 任取 5 个包（剧集 3、电影 2），`qwen-narrow` 与 `qwen-wide` 各渲染并生成一次，人工检查 JSON 合规、无思考段、无重复循环、无日文照抄、简体中文、邻文未进输出。允许 §4.2 的一次调整。

## 执行记录

- 2026-10-21 claimed。启动前 `Get-Process` 无 llama／python 进程，`nvidia-smi` 空闲 14569 MiB，无 `.local/gpu.lock`。
- 包选取（`v9.smoke_batches`，主 seed 块，每类取前几部作品各自第一个 ≥6 条目标的包）：`F2-W01_E022-S00127`（10 条）、`F2-W02_E014-S00084`（8）、`F2-W03_E001-S00001`（8）、`F2-M01-S00001`（9）、`F2-M02-S00486`（8）。
- `smoke --recipe qwen-narrow`：载入 5.2 s，5 包墙钟 42 s，5／5 第一次接受；输入 576–756 token（`/apply-template` 计数与 `usage.prompt_tokens` 逐包相等），输出 166–241 token，生成 59.4–59.8 tok/s；首请求 `timings.cache_n == 0`；`reasoning_content` 全空；显存峰值 13128 MiB（启动前空闲 14569）。
- `smoke --recipe qwen-wide`：载入 5.1 s，墙钟 26 s，5／5 第一次接受；输入 749–906 token，生成 59.5–59.8 tok/s；显存峰值 13513 MiB。5 个包中 4 个是场景第一包（前邻文 0 条），宽邻文在 smoke 里主要表现为后 5 条；L1 的整块 run 会覆盖前 20 条的情况。
- grammar 探针（`smoke/grammar-probe.json`，一次请求）：对"用一句话介绍东京"施加只允许 `{"translations":{"a":"[甲乙丙]+"}}` 的 grammar，输出 `{"translations":{"a":"甲"}}`——chat 端点确实执行 `grammar` 字段（server 日志的 sampler chain 不列 grammar，所以用探针核实）。
- 人工逐条阅读 2×43 条：
  - JSON 合规：10／10 包，键顺序与目标 ID 相同，无多余键、无空值。
  - 思考段：无（`reasoning_content` 空，content 以 `{` 开头）。
  - 重复循环：无（输出 token 与目标条数成比例，finish_reason 全为 stop）。
  - 日文照抄：无。narrow 把一段咒语片假名写成拉丁转写（`Speræ Ieptum Refelmus`），wide 写成中文音译；人名 `アーチャー` 两臂都写 `Archer`、`ベータ` 写 `Beta`——拉丁字母专名，不是日文也不是英文句子，不触发调整。
  - 简体中文：是，未见繁体字。
  - 邻文进输出：无（narrow 的后邻文 `その手の人間は…`、`仕事か` 均未出现在译文里；wide 的后 5 条同样未出现）。
  - 质量观感（不作判定，只记录）：两臂都有专名错（`フリーレン` 在 wide 里写成"菲伦"、`アルゴ` 写成"爱丽丝"，narrow 正确）；`キー坊によろしくナ` 两臂都译错；其余通顺。
- 结论：两个臂都合规，**不调整**：`presence_penalty` 保持 0，system 提示保持 `qwen-joint-v1`，hash 不变（`d878d2d1…`／`719237b9…`）。此后提示不再改。

## 预算

smoke 折 1 个 GPU run（两个臂＋一次探针，合计 GPU 墙钟约 1.5 分钟）。台账：GPU run 1／10；裁判 $0／$100。

## Answer

**两个 Qwen 臂 smoke 全部合规，不使用 §4.2 的那次调整。** 10 个包第一次接受，无思考段、无重复、无日文照抄、简体中文、邻文未进输出；chat 端点执行 GBNF `grammar`（探针证实），`/apply-template` 计数与 server 计数一致，首请求缓存为空。实测：载入约 5 s，生成 59.5 tok/s（Hy-MT2 产品约 175 tok/s），显存峰值 13.1／13.5 GB。
