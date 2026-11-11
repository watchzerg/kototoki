# 地图

## 接跑手册（每次启动从这里开始）

1. 读[研究文档](../../docs/research/2026-10-21-general-model-translation-v9.md) §7 进度，找到第一张未 resolved 且 Blocked by 已全部 resolved 的票据；读它的 `## 执行记录`。**状态以文件为准**：`python -X utf8 -m experiments.scene_batching_v6 --round v9 status` 只读列出 run、裁判进度、配额阻塞与 GPU 锁。
2. GPU 票据（02、03、04）已获用户授权无人值守执行（≤10 个 dev run）。启动前只读核对 GPU：PowerShell `Get-Process | ? ProcessName -match 'llama|python'`、`nvidia-smi`，读 `.local/gpu.lock`。锁被存活 PID 持有、或有不明 llama-server 时不启动、不杀进程，转离线票据。
3. 生成：`.venv/Scripts/python.exe -X utf8 -m experiments.scene_batching_v6 --round v9 generate --recipe <dp10-cut|qwen-narrow|qwen-wide> --seed S`（可续跑）。Hy 臂走 `translation_v3/server.py`（compat b11429），Qwen 臂走 `translation_v3/qwen.py`（`kototoki.llama_server`，官方 b11669）。
4. 核对三臂批次：`... --round v9 check-batches --seed S`（目标 ID 序列逐字相同，否则是实现错误，先修再跑）。
5. 裁判：`... --round v9 judge-run --recipe R --seed S`（全集、同包组成）；比较：`... --round v9 compare9 --variant R --against R2 --seeds S…`。
6. 裁判（`claude -p`）退出码 75 = 配额耗尽：不循环重试；转离线票据，没有可做的就停下，在票据执行记录与研究文档 §7 写明停在哪里。
7. 预算台账：每个 GPU run（含 smoke 折 1）与裁判标价累计写在下方 Notes；超过 10 run 或 $100 即以现有数据结题。
8. 每完成一张票据：票据写 Answer 并 resolved → 本文 Decisions-so-far 加一行 → 研究文档 §7 更新 → 提交 Git（研究文档、INDEX.md 与 `experiments/` 下本轮代码；不提交 `.claude/settings.json`）。
9. 需要用户裁定的事项写研究文档 §8，不中途停下来问。

## Notes

- 预算台账（结题）：GPU run 10／10；裁判标价 $87.41／$100（9 套 816 包）。
- v4 dev 每个 seed 覆盖一个场景块（主 seed 20261011–13 合起来覆盖整个 dev 一次）；"全集"指该 seed 块的全部窗口。

## Decisions-so-far

- 2026-10-21 [01](issues/01-offline-impl.md)：`Recipe.model`／`wide_context`、`qwen.py`（`qwen-joint-v1` 为 Hy joint 文字原样拆成 system／user，GBNF 原文作 chat `grammar`，`/apply-template` 计预算）、`--round v9`（`v9.py`）已实现；18 个旧配方 hash 不变，`qwen-narrow` `d878d2d1…`、`qwen-wide` `719237b9…`；dev 621 包三臂目标 ID 相同；离线 157 项通过。
- 2026-10-21 [02](issues/02-smoke.md)：smoke 10 包全部第一次接受，无思考段／重复／日文照抄／繁体／邻文泄漏，不调整提示与采样；grammar 探针证实 chat 端点执行 `grammar`；生成 59.5 tok/s、显存峰值 13.1–13.5 GB、载入约 5 s。
- 2026-10-21 [03](issues/03-l1-gate.md)：两个 Qwen 臂都未关门；单 seed accuracy Δ narrow −0.091／−0.178、wide −0.162／−0.160（剧集／电影，CI90 上界均 <0），unnatural 显著上升，墙钟 2.9–3.1×；无泄漏；人工 17／20 支持 Qwen。进入 04。
- 2026-10-21 [04](issues/04-l2-screen.md)：三 seed 合并 wide − 对照 剧集 −0.058［−0.104, −0.010］、电影 −0.091［−0.152, −0.028］（改善）；narrow −0.020／−0.034（非劣无改善）；unnatural 显著上升，墙钟 3.3×。
- 2026-10-21 [05](issues/05-close.md)：结题，结论为 §3 Q4 第三种写法，建议 L3 交用户裁定；提交签名阻塞，改动暂存未提交。本 tracker 关闭。

## Fog

- Qwen 生成速度对 Hy 约 1/3；每个 Qwen run 预计约 17 分钟加载入。
