# T0 共驻显存探针（GPU）

Status: done
Type: task
依赖：无

## 内容

同一进程加载 Whisper＋Qwen，对 HF II／III 全部 VAD 窗口按 ①w0 转写 ②x0 转写 ③Whisper 打分跑一遍，采样整卡显存峰值，记录加载、转写、打分墙钟，核对 CT2 与 torch 共驻无 DLL／OOM 问题。

## 文件所有权

`experiments/quality_v5/coresidency_probe.py`、`docs/research/acceptance/2026-10-19-cross-coresidency-probe.md`、`docs/research/INDEX.md` 登记

## 完成标准

峰值与阈值判定（峰值＋1 GB ≤ 13.5 GB 才共驻）写入记录；给出共驻或三段式回退的结论。

## Comments

- 2026-10-19 完成：`experiments/quality_v5/coresidency_probe.py` 在同一进程常驻产品 Whisper 与 Qwen，HF II／III 全部 402 个窗口按 ①②③ 跑完（约 23 分钟，持有并已释放 `.local/gpu.lock`）。整卡峰值 10688 MiB（含桌面约 2.0 GB），＋1 GB＝11712 MiB ≤ 13824 MiB，**判定共驻**，不回退三段式；无 DLL／OOM 问题，两路转写与单独运行逐窗口相同。墙钟：加载 Whisper 4.9 s、Qwen 4.5 s；w0 374.6 s、x0 948.7 s、打分 40.5 s（两部合计）。供 T5／T6 注意：窗口口径下相同窗口只有 10%，改为 x0 的区间 18.5%（§5 预期 6–10%，研究单元口径 37.7%）。记录见 `docs/research/acceptance/2026-10-19-cross-coresidency-probe.md`，逐窗口决定在 `.local/quality-exploration-v5/cross-coresidency-probe/judge-*.jsonl`。
