# 01 离线实现：配方字段、qwen-joint-v1、Qwen 请求与 server 接入、宽邻文、核对与比较工具

Status: resolved
Type: task

## 目标

按研究文档 §4.3 实现两个 Qwen 臂与驱动、比较工具，证明已有配方 hash 不变，三臂批次目标 ID 相同。不加载模型、不占 GPU。

## 执行记录

- 2026-10-21 claimed（主会话，主 checkout）。
- `translation_v3/recipes.py`：`Recipe.model`（唯一值 `qwen3.8-27b-ud-iq3_s`，须与 `prompt="qwen-joint"` 同用，不与 terms／review／sampling／target_context／多样本／glossary／pause_marks／groups／路由组合）、`Recipe.wide_context`（`{"max_visible": n}`，`wide-context-v1`）；`V4_DEFAULTS` 加两者，默认值不进 `spec()`。带 `model` 时 `versions.model` 记模型、资产 SHA、引擎版本、server 参数、提示版本＋system 文字 sha、请求形状、seed 步长，`fixed` 换成 Qwen 采样与 context。内置 `qwen-narrow`（`d878d2d1…`）、`qwen-wide`（`719237b9…`）。
- `translation_v3/batching.py`：`wide_context` 只替换邻文规则（按条数到场景边界、不看静默，超上限先去后句）；切包函数不读邻文字段，所以目标 ID 由构造保证相同。
- `translation_v3/qwen.py`（新，约 230 行，与 v3 其余部分只共享常量与校验，按 §6 放独立文件）：提示渲染、请求体、chat 步骤、Qwen 的 `ServerSpec` 与 session 工厂。
- `translation_v3/generate.py::translate_scene`：`recipe.model` 时走 `qwen.run_step`，其余路径不变。
- `scene_batching_v6`：`--round v9`（根 `.local/general-model-translation-v9/`），`v9.py` 提供 `generate`（按配方派发 server）、`check-batches`、`smoke`、`judge-run`、`compare9`。
- 测试：`translation_v3/test_qwen.py` 16 项、`scene_batching_v6/test_v9.py` 6 项。全套：translation_v3 78、scene_batching_v6 37、translation_v4 19、reorder_groups 23，全部通过。
- 离线核对 `check-batches`：dev 44 场景、621 包，三个臂目标 ID 序列逐字相同（`.local/general-model-translation-v9/checks/batches-offline.json`）；可见条数 narrow 与对照相同（≤12），wide 最多 35。

## 实现细节的取值与理由

| 细节 | 取值 | 理由 |
| --- | --- | --- |
| `qwen-joint-v1` 措辞 | 不改一字：Hy joint 提示的任务文字从"【只读日文上下文】"处拆开，之前全部进 system，之后（只读上下文 JSON＋待译 JSON）进 user | §4.2 要求"最小改写"；零改写最便于把差异归因于模型；测试断言 system＋"\n"＋user 是 Hy 原生提示的子串 |
| 输出约束 | 把对照的 ID GBNF 原文作为 chat completions 的 `grammar` 字段 | 与对照逐字同一约束；json_schema 要经 llama.cpp 转换，生成的 grammar 与对照不同（空白、字符集）。是否被 server 执行在 02 用输出顺序与日志核实 |
| 校验 | `recipes.parse_translation`（与对照同一段代码）＋键顺序检查 | grammar 保证顺序；若 chat 端点未执行 grammar，顺序检查能抓到 |
| 输入预算 | `/apply-template` 渲染后 `/tokenize` 计数，上限 context − 4096 − 64（narrow 4032、wide 12224）；并与 `usage.prompt_tokens` 对比、不一致记录不失败 | 与对照"超预算记失败、不截断"同义；计的是模型实际看到的 chat 提示 |
| 重试 | 两次，第二次 seed＋1；记 `seed` | §4.2 与 names 相同 |
| 两次都失败 | 场景终态失败，按对照同一 harness 规则计未交付（accuracy 10、major+、critical） | 实验包里的 dp10-cut 本就没有拆批降级（降级只在产品 `dp10-cut-degrade-v1`）；两臂同规则才配对 |
| 宽邻文实现位置 | `batching._neighbours` 在 `wide_context` 时提前返回（条数规则）；不看静默门槛 | §4.1"场景边界截断"；dp10-cut 的静默门槛（前 <5 s、后 <1 s）会把前 20 条大半截掉，与本臂目的不符 |
| 宽邻文上限 | `max_visible` 35（=20＋10＋5，实际不触发） | "可见上限随之放开" |
| 模型与 server 身份 | 从 `kototoki/names/recipes.py` 抄成 `qwen.py` 常量（资产、b11669、99 层、`-b 512 -ub 512 -fa on --jinja --reasoning off`、min_free 13000 MiB、载入 180 s） | 产品以后改 names 参数不应移动 v9 的 hash；server 生命周期仍用产品 `ManagedServer` |
| GPU 锁与进程 | v3 `GpuLock`＋`KillOnCloseJob`（在 `on_pid` 回调里挂进 job） | 产品 `ManagedServer` 不带锁与 job；与 Hy 臂同一 `.local/gpu.lock` 规则 |
| 首请求缓存校验 | `timings.cache_n == 0`，否则记 cache 基础设施失败 | 与对照相同；chat 端点是否返回 `timings.cache_n` 在 02 核实 |
| 端口 | 8080（两种 server 串行） | 同对照 |
| 专名错误抽取（§4.4） | 03 实现：裁判注释含人名／称呼关键词（wrong-referent 中涉及人名的、以及注释提到"人名／名字／称呼／译名"的错误）计数 | 不新建裁判 profile；方法随数字写进 03 |

## 预算台账（开始时）

GPU run 0／10；裁判标价 $0／$100。

## Answer

**实现完成，已有配方 hash 全部不变**（18 个旧内置配方——17 个 v8 前的加 `grp1`——固定在 `test_qwen.QwenRecipeTest`；`dp10-cut` 仍为 `ee72ce66…`）；新内置 `qwen-narrow` `d878d2d1…`、`qwen-wide` `719237b9…`。dev 44 场景 621 包上三个臂的目标 ID 序列逐字相同。离线测试 22 项新增，四个实验包全套 157 项通过。未做任何 GPU 运行。待 02 核实：chat 端点是否执行 `grammar`、是否返回 `timings.cache_n`、`/apply-template` 计数与 `usage.prompt_tokens` 是否一致。
