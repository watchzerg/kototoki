# 01 离线实现：Strata 附着后端、F1 配方工具、--round v12、测试

Status: resolved
Type: 离线
Stage: A
Blocked by: —

范围、终点与门见研究文档 §4.1（docs/research/2026-11-08-strata-flash-next-v12.md）。

## 执行记录

- 2026-11-08 读完 v12 文档、Strata 调研、ADR-0016、v11 §2.3/§4.0/§5/§7.1 与 qwen/recipes/asr10/names11/v11 代码；读 Strata 安装件源码确认：`launch --status --output json` 给出 name/profile/state/port/host/config（run config 路径）；`/v1/status` 有 context、concurrency、engine、machine（整机显存/内存）；chat 响应只有 `usage`（含 `prompt_tokens_details.cached_tokens`）与 `timings`，**不回 reasoning_tokens／reasoning_recoveries**——这两项只出现在 server log（`runtime/launch-<preset>.server.log` 的 "repeated reasoning detected"、"logits became non-finite" 行）；`thinking_budget_tokens` 是请求顶层字段。
- 实现（理由见下）：
  - `translation_v3/strata.py`（新）：F1 请求体（无 `grammar`／`cache_prompt`，带 `model`、`enable_thinking`；思考时 `thinking_budget_tokens` 与 `max_tokens`＋预算）、无 grammar 的 `run_step`（输入长度取 `usage.prompt_tokens`，超 Q1 预算只标记；首请求缓存只记录；格式失败换 seed＋1 重试一次）、`probe`（版本、launch 状态与 run config、`/v1/models`、`/v1/status` 对固定身份核对，观测值不含 key）、`session_factory`（持 v3 gpu.lock 附着、写 `strata.json`、每 5 s 采样 `/v1/status` 峰值、统计 server log 事件 → `resources.json`）。
  - `qwen.py`：`versions`／`fixed`／`run_step`／`session_factory` 按模型分派到 strata；抽出 `option_versions`（Qwen 路径输出不变）。`recipes.py`：`STRATA_MODEL`，`_check_model` 接受两个模型。`generate.py`：session 记录加 `strata` 键；**Strata 配方上两次都失败的包只让自己的 cue 未交付，场景继续**（§4.0 "其 cue"；Hy-MT2／Qwen 配方行为不变，有测试）。dev 统计里失败场景仍按整场景未交付计（沿用 v9 口径，保守）。
  - 身份设计：固定值（Strata 0.2.12、build 0.1.58、预设名、§3 启动参数、context 32768）进 `qwen.versions()` 即配方 hash；运行时才知道的 kv／drafting／args 记在 session 身份，不进 hash（否则 hash 随机器状态变）。
  - `scene_batching_v6/v12.py`＋`--round v12` 命令（recipes、copy-q1、smoke、smoke-report、stats、generate-aa、aa、product12）。
  - smoke 场景：v11 smoke 用的是 5 个场景各 1 包；§4.2 要"3 个场景"，取其中 2 个剧集＋1 个电影整场（`F2-W01_E022-S00127`、`F2-W02_E014-S00084`、`F2-M01-S00001`），覆盖两类。
- 配方：F1 dev `60bd457f…`、F1 产品 `a2075b25…`、F2 `903d1cad…`；Q1 hash 复算不变（`9c444d3c…`、`c10e143a…`），`qwen-wide` `719237b9…` 不变。Q1 dev 3 run 与产品 6 份 SRT 已复制到 v12 根目录（只读来源）。
- 测试：`translation_v3` 88 项（新增 `test_strata` 10）、`scene_batching_v6` v6–v12 66 项（新增 `test_v12` 3）全过。
- mock 引擎端到端（`strata serve --engine mock`，端口 18089，scratchpad 里的 run config 副本，不占 GPU）：附着客户端对真实 Strata HTTP 层发请求，mock 回的是非 JSON 文本 → parse 失败 → seed＋1 重试 → 交付失败记录，路径正常；mock 响应无 `timings`，故 `cache_n` 回退到 `prompt_tokens_details.cached_tokens`。mock 已停止并核实端口关闭。
- 另：`strata` 在 PATH 上是 PowerShell 脚本，Python／Git Bash 调用需 `bin/strata.cmd`（`strata.strata_cmd()`）。

## Answer

完成。Strata 附着后端、F1／F2 配方工具、`--round v12` 与离线测试已就绪；旧配方 hash 不变（测试与复算）。reasoning_tokens／reasoning_recoveries 不在 HTTP 响应里，改由 `reasoning_content` 字符数与 server log 行数记录。
