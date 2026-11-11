# 02 建表与可行性门（产品 2×2、dev 15）

Status: resolved
Type: GPU
Stage: B
Blocked by: 01

范围、终点与门见研究文档 §4.2（docs/research/2026-11-08-names-on-strata-v13.md）。

## 执行记录

- 2026-11-08 22:53 开跑前核对：无 llama-server、无 Strata launch（`--status` 为空）、无 `.local/gpu.lock`；显存已用 1116 MiB、空闲 14862 MiB；两个 python 进程是工具 harness 的 stdin 脚本（共约 20 MB，非 GPU 作业）。**可用内存 48.8 GiB < 52 GiB**：进程里没有大户（claude 进程共约 3 GB、驱动非分页池 4.6 GB），按规则不关任何程序，后台每分钟复查、最多等 60 分钟。
- `strata launch --no-tui --model iq3_s --plan`：IQ3_S 128K、图片读取器在 CPU、并发按卡适配、DFlash2、本机 8080、tune skip，**"Nothing to download"**（DFlash2 草稿器已在本机，前几次 smoke 已用）。
- 采样参数（Strata 0.1.58 `serve/server.py` 把请求采样转成引擎参数的那段）：`top_p` <1 生效、`top_k` 1–64 原值、`min_p` 只在 (0,1] 生效（0＝引擎自己的"关"，与 llama.cpp 的 0 等价）、`presence_penalty` 非 0 生效且窗口默认 64（llama-server 默认 `repeat_last_n` 也是 64）、正整数 `seed` 生效。`/v1/messages/count_tokens` 渲染与真实请求相同的提示后计数，模型不运行。
- 22:56 可用内存仍 48.6 GiB；用户叫停（内存不足，重启机器）。**未启动 Strata、未建任何表、未写 gpu.lock**，GPU run 0。重启后从本票据接跑：先重做开跑前核对（可用内存 ≥52 GiB），再 `uv run --locked --offline python -m experiments.scene_batching_v6 --round v13 v13-build`（`--plan` 已核实下载量为 0，重启后再看一次）。
- 23:02（重启后）开跑前核对：无 llama-server、无 Strata、无 `gpu.lock`，显存已用 1334 MiB，可用内存 52.5 GiB（`serve` 自检时 52.6）；`--plan` 仍为 "Nothing to download"。
- 23:03 `v13-build`（`logs/build.log`）：`StrataServer` 启动并核对通过（0.2.12／build 0.1.58、DFlash2、kv int8、spec 4），**专家区 `ram`（全部锁进内存）**；19 次建表约 9 分钟（建表合计 545 s）；结束 `--stop`，status 为空，空闲显存 15074 MiB（之后 nvidia-smi 已用 941 MiB）。
- 计数（`B/build-report.json`、`B/gate.json`）：
  - 17 个正式建表：`ok` 16、**`failed` 1（HF-III：两次尝试都以 `length` 截断于 4096 token）**；首次尝试失败 **5／17**（HF-II、HF-III、W02、W03、W08），全部是 `finish_reason: length`（输出顶到 `max_tokens` 4096，内容约 7.6–10.6 千字符）、**没有一次是 JSON 解析失败**。A/A 第二次：HF-II 同样首次截断、重试 `ok`（20 条，第一次 23 条），HF-III 同样两次截断 `failed`。
  - 36 个请求：`reasoning_content` 全空、无 `<think>`；HTTP 错误 0、响应无额外字段；server log 推理自救 0、非有限 logits 0、重复截停 0（截断不是重复循环）。
  - 输出长度：S1 被接受回复的 completion 中位 3022 token（最大 3981，17 个）；27B dev 表 15 部全部首次 `ok`，completion 中位 1536（最大 3344）。dev 条目 S1 290 对 27B 201；HF-II 23 对 20。
  - `count_tokens`：17 部都可用，两段之和比 `usage.prompt_tokens` **恒多 87**（每段作为一条 user 消息各算一份模板），预检口径偏保守；prompt token 与 27B 逐部相同（HF-II 13240、HF-III 14609，同一分词器）；超预算 0。
  - 采样：全部被接受（见上条源码核对）。
  - 代价：dev 15 部建表 339 s（27B 468 s）；产品单次 48–53 s（27B 49／40 s，但 S1 含一次截断重试）；显存峰值 16.1 GB、整机内存峰值 62.4 GiB（共 63.9）。
- 门（§4.2）：17 部全 `ok` ✗（HF-III failed）、首次失败 ≤2／17 ✗（5）、思考输出为空 ✓、采样全部接受 ✓ → **不过门**，按 §4.2 停在这里，不进 C／D／E。GPU run 1（B 1／1）。
- 2026-11-08 用户裁定 §8 第 4 项 (a)：S1 改为 `names-strata-v2`（`max_tokens` 8192、context 24576，hash `eb4b1c6d…`），产物写到 `B2/`；v1 的 `B/` 保留。重跑本票据：先做开跑前核对，再 `v13-build`。
- 2026-11-08 23:4x 重跑（S1 v2）开跑前核对：无 llama-server／Strata／`gpu.lock`，显存已用 907 MiB，可用内存 54.7 GiB，`--plan` 下载量 0。`StrataServer` 核对通过（DFlash2、kv int8、spec 4、专家区 `ram`）；19 次建表合计 666 s；`--stop` 后显存释放（空闲 15106 MiB）。日志 `logs/build-v2.log`，计数 `B2/build-report.json`、`B2/gate.json`。
- 结果：17 个正式建表 `ok` 16、**`failed` 1（W11：两次都写满 8192 token 被截断）**；首次失败 **6／17**。25 个请求中：
  - **5 个写满 8192 token 仍未结束**（W03、W09、W10 首次，W11 两次；每个约 2.0–2.2 万字符，是正常最长回复 6356 token 的 1.3 倍以上、中位 2969 的近 3 倍）——生成失控，Strata 的单 token 重复截停没有触发（server log 重复截停 0、推理自救 0、非有限 logits 0）；
  - **2 个正常结束但 JSON 语法错误**（M02："Illegal trailing comma"、W08："Expecting ',' delimiter"）——没有约束解码时出现的格式错误；
  - 其余正常。v1 里被 4096 截断的两部产品片这次都一次成功（HF-II 2407、HF-III 5935 token），说明 v1 的截断里一部分是表本来就长，另一部分是失控。
- 其他：思考输出 0、采样全部接受、`count_tokens` 可用且超预算 0；dev 条目 246（v1 290、27B 201）；A/A：HF-II 18 对 23 条、HF-III 30 对 23 条（两次都一次成功）；显存峰值 15.9 GB、整机内存峰值 60.4 GiB；dev 15 部建表 545 s（含 6 次重试；27B 468 s）。
- 门：全 ok ✗、首次失败 ≤2 ✗、思考为空 ✓、采样接受 ✓ → **再次不过门**。B 预算 2／2 用完，按 §4.2 停，不进 C／D／E。

- 2026-11-08 用户要求补试 v3（`response_format`＋5 次）与 v4（5 次），`v13-build --variants v3 v4`，一次 Strata session。门不变，两种口径都报。

- 2026-11-09 补跑 v3／v4：见研究文档 §7 同日一行（`B3/`、`B4/`、`logs/build-v34.log`）。v3：17／17 ok（最多 5 次），首次失败 6／17，失败 12／31（失控 11、非法控制字符 1）；v4：17／17 ok（最多 3 次），首次失败 4／17，失败 6／25（全是失控，语法错 0）。按字面两臂都不过"首次失败 ≤2"；是否放行 v4 写进 §8 第 8 项，等用户裁定。

## Answer

**v3／v4 补跑后仍不过门：两臂在最多 5 次尝试内 17／17 建成（v4 最多用 3 次、JSON 语法错 0），但首次失败 v3 6／17、v4 4／17，门要求 ≤2。** `response_format` 不减少失控（11／31）。是否放宽门放行 v4，见研究文档 §8 第 8 项。

以下为 v2 的答案（保留）：

**S1 v2（`max_tokens` 8192）仍不过门：Strata 上没有约束解码，Flash-Next 建表时约 1／5 的请求生成失控（写满 8192 token 不结束），另有约 1／12 的回复 JSON 语法错误；W11 两次都失控（`failed`），首次失败 6／17。** 放宽上限只救回了"表本来就长"的情形（两部产品片都一次成功）。思考关闭、采样、预算预检都可行。按 §4.2 停在这里。

以下为首跑 v1 的答案（保留）：

**首跑不过门：Strata 建表当前不可用，原因是 Flash-Next 写出的表比 27B 长约一倍，现行配方的输出上限 `max_tokens` 4096 截断了 9／36 个回复，HF-III 两次都截断（`failed`），首次失败 5／17。** 格式（JSON）、思考关闭、采样、`count_tokens` 预检都没有问题。修复候选写进研究文档 §8，本轮不修。
