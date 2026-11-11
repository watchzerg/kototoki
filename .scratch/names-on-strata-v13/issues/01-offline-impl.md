# 01 离线实现：建表 Strata 回调、任意表→Q2 配方、--round v13、测试

Status: resolved
Type: 离线
Stage: A
Blocked by: —

范围、终点与门见研究文档 §4.1（docs/research/2026-11-08-names-on-strata-v13.md）。

## 执行记录

- 2026-11-08：`experiments/scene_batching_v6/v13.py`、`test_v13.py`、`__main__.py`（`--round v13`）、README；`experiments/translation_v3/strata.py` 的 `probe` 默认启动分支。
- 实现细节（执行者补充，理由）：
  - S1 配方 `names-strata-v1`＝产品 `BUILD` 去掉 `model_asset`（llama.cpp 的 GGUF，不适用）＋`model`＋Strata 身份（0.2.12／build 0.1.58、`launch: default`、`DEFAULT_RESOLVED`、kv `int8`）＋请求改动（`response_format: null`、`enable_thinking: false`）＋预算检查方式；hash `91671bd9…`。kv 写进身份是因为 §4.0 要求 launch 状态中的 kv 参与 hash；值取 2026-11-08 两次 Q2 smoke 的观测，运行时不符即拒绝。
  - `count_tokens` 把每段文本作为一条 user 消息计数，含少量模板 token；票据 02 记录它与 `usage.prompt_tokens` 的差。
  - Strata 启停用产品 `StrataServer`（导入、不改）：它已实现 `--no-tui --model iq3_s` 启动、ADR-0017 接入检查、专家区未锁进内存即停掉并拒绝、`--stop` 与显存释放核实；外面加一层开跑前核对（无 `gpu.lock`、无 llama-server、无 Strata、可用内存 ≥52 GiB，任一不满足即退出，不杀不停任何进程），因为 `StrataServer` 的内存等待只告警。
  - **研究侧 probe 的缺陷**：`translation_v3/strata.probe(..., "default")` 按 run config 参数判断起草方式，而 Strata 总会传 `--mtp`，会把默认启动（DFlash2）认成 MTP 并拒绝（产品在 ADR-0019 已改读服务日志，研究侧未改，Q2 规则在研究侧从未跑过）。改为默认分支读服务日志最后一行 `[strata] drafting:`（复用产品 `drafting_from_log`）；v12 分支不变。测试同步改为注入 `drafting_of`。
  - 未做 `strata serve --engine mock` 端到端：Windows 上后台 Bash 起的前台服务杀不掉（会占住 8080 挡住后续票据）；客户端逻辑用伪 `post` 覆盖，`count_tokens` 的真实形状在票据 02 实测（有退路）。

## Answer

完成。S1 hash `91671bd91aaee390e286f4fe8b2a22c5859785f78e69fa5d82abce9689227fc8`，产品 `BUILD_RECIPE_HASH` 仍为 `5b8d1b76…`（测试钉住）。任意表→Q2：`write_q2`／`q2_data`；用 27B 表组出的 Q2 配方与 ADR-0017 记录的两个实例 hash 逐一相同（dev `4c3d0f70…`、产品 `86b61ec9…`），注入表与 `nstar_tables("high")`／`product_tables("high")` 逐字段相同。测试：`scene_batching_v6` v6–v13 78 项、`translation_v3` 90 项、`tests.core` names／strata 26 项通过。GPU 0。
