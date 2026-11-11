# 02 smoke 与可行性门

Status: resolved
Type: GPU
Stage: B
Blocked by: 01

范围、终点与门见研究文档 §4.2（docs/research/2026-11-08-strata-flash-next-v12.md）。

## 执行记录

- 2026-11-08 开跑前核对：`Get-Process` 无 llama-server／Strata／python；`nvidia-smi` 显存 1477／16303 MiB（仅桌面程序）；`strata launch --status` 无运行；无 `.local/gpu.lock`；整机空闲内存 49.5／63.9 GiB。
- `strata launch --plan`（调研 §3 的固定参数）：**download About 5.2 GB（the draft layer）**，即 MTP 草稿层不在本机。只读核查：`D:\Strata\Strata-data\` 下只有 `dflash2/`（823 MB，DFlash2 草稿器）、`models/`、`packs/`，没有 `mtp/`；旧 run config `iq3_s-128k.json` 的 `--mtp D:\Strata\Strata-data\mtp\rt` 指向不存在的目录。信息性 dry-run（`--plan`，不改任何东西）：`--drafting auto` 与 `--mtp off` 都显示 "Nothing to download"、drafting＝DFlash2。
- 按授权规则停下：未启动 Strata，GPU 0 run。改 drafting 属于改 §4.0 固定的启动参数，写进 §8 第 4 项待裁定。
- 2026-11-08 用户裁定 §8 第 4 项 (a)：允许下载 MTP 草稿层（约 5.2 GB），参数不变，续跑。
- 2026-11-08 续跑：核对同前（无 llama-server／Strata／python，无锁，显存 1.5 GB）。`strata launch ... --save-preset kototoki-translate --no-tui --yes`：下载 MTP 草稿层（约 5 GB）后加载约 60 s，`Ready: http://127.0.0.1:8080`；显存 15.7 GB。`probe` 通过：0.2.12／build 0.1.58、本机、`--max-context 32768`、`--kv int8`、`--spec 4`、MTP、无 vision、单并发。修一处：`launch --status --output json` 在 JSON 后多打一行人读文本，改为只解析第一行（测试已覆盖）。启动后整机内存已用 63.2／63.9 GiB（Strata 加上桌面程序），很紧。
- smoke 两遍（`smoke/pass1|2/flash-names-high__s20261011__smoke3`，3 场景 45 包）：每遍首次格式失败 0、交付失败 0、`reasoning_content` 非空 0、限长停止 0、超 Q1 预算 0、首请求 cache_n 0；server log 推理循环自救 0、非有限 logits 0。每包耗时均值 3.28／3.20 s（中位 3.39／3.30，p90 3.75／3.65，最大 5.23／3.86），接受输出约 64–65 tok/s，墙钟 149／145 s。峰值：显存 16098／16073 MiB，整机内存 63.5／62.6 GiB。A/A：45 包中 38 包（84%）、382 cue 中 167 个（44%）文本不同。
- 可行性门：交付失败 0 ✓、首次格式失败率 0／90 ✓、思考输出全空 ✓、无非有限 logits ✓ → **通过**。`strata launch --stop` 后显存 1010 MiB，无残留进程。GPU：smoke 2 次（约 5 分钟，按次计，不占 run 预算）。

## Answer

**可行性门通过，进 C。** 无 grammar 时 90 包首次即全部合法（格式失败 0、交付失败 0），思考完全关闭（`reasoning_content` 全空），无非有限 logits、无推理自救。每包约 3.2–3.3 s。同 seed 不能复现：A/A 不同的 cue 占 44%（llama-server Q1 约 24%）。整机内存峰值 63.5 GiB／63.9 GiB，接近上限。
