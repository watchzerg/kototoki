# 01 产品整片重跑（swr）与 STT 回归重测

Status: resolved
Type: task
Blocked by: —

## 范围

- 用当前 main 的 `python -m kototoki` 在 HF II／III 上跑整批：w0 必做；x0 在 w0 完成后视时间可选。配置复用 `.local/bilingual-fullfilm-08/w0.toml`／`x0.toml` 的路径，`output_dir` 改到 `.local/quality-exploration-v5/01/out-{w0,x0}/`，不覆盖验收目录。
- 跑完用 `kototoki_eval` 对 2026-10-05 基线算 CER（参考 `fullfilm-v1/corpus/references/hf-{ii,iii}-full.json`，与最终验收 §1 同口径），同时报 S／D／I、可测条数、条件时间误差。
- 核对派生 WAV 的 PCM SHA 与基线 swr 版一致（票据 10 已离线核对，这里用真实运行再确认一次）。
- 不改代码；发现缺陷只记录并建票。

## 完成标准

- 两部整片三份 SRT 齐全，STT 零失败，翻译降级与回退数记录。
- CER 表（产品 vs 基线，w0 两部，x0 若跑）写入 `docs/research/acceptance/2026-10-XX-bilingual-pipeline-swr-regression.md`，最终验收记录的"尚未重测"处加一句指向。
- 墙钟（各阶段）与显存峰值记录。
- Answer 写明：回归是否回到基线水平（差异 ≤ 0.3 个百分点视为回到），后续票据以本目录产物为输入。

## 文件所有权

只读代码；新增 `docs/research/acceptance/` 一个文件；更新最终验收记录一行、研究文档 §6／§7。

## 执行记录

- 2026-10-16 claimed。假设：main `b6d0dc4`（票据 10 已改回 swr）的产品整片在 HF II／III 上回到 2026-10-05 基线 CER（差 ≤ 0.3 pp）。唯一变化相对最终验收：派生 WAV 重采样 soxr → swr（及其后的票据 11／12／14／15 代码）。
  - GPU 核对：`Get-Process` 无 llama／python 进程，`nvidia-smi` 939 MiB（桌面），无 `.local/gpu.lock`。
  - 命令：`.venv/Scripts/python.exe -X utf8 -m experiments.quality_v5.telemetry_run --out .local/quality-exploration-v5/01/telemetry-w0 -- .venv/Scripts/python.exe -X utf8 -m kototoki .local/quality-exploration-v5/01/w0.toml`（x0 同理）。遥测脚本只旁路采样 `nvidia-smi`（0.5 s），阶段墙钟取产品日志。
  - 产物：`.local/quality-exploration-v5/01/out-{w0,x0}/`（SRT 与 `.work/`），`telemetry-{w0,x0}/`，评分 `eval/`。
- 2026-10-16 首次启动失败（遥测脚本 `FileNotFoundError`：Windows `CreateProcess` 不解析带 `/` 的相对 exe 路径），未进入产品；脚本改为先 resolve 再启动，重跑。
- 2026-10-16 w0 整批完成：退出码 0，总 890.3 s；vad 93.1 s（峰值 1969 MiB）、asr 323.4 s（5265）、align 96.1 s（8515）、translate 360.3 s（15648）。两部发布，0 failed，0 fallback。cue：II 1099、III 1219。翻译 110＋122 批，降级 0、回退 0、降级请求 0（`.work/*/translate/*/*/report.json`）。
- 2026-10-16 w0 评分（`eval/product-w0-hf-{ii,iii}.json`）：II CER 16.81%、S／D／I 876／676／260、可测 645、半秒成功 580、p95／p99 0.702／7.371；III 13.77%、777／444／342、690、595、0.729／7.960——与基线 `bilingual-fullfilm-08/eval/baseline-w0-*.json` 逐项相同。PCM SHA：II `ee4e2da3…`（= 基线 `hf-ii-full.wav`）、III `e8e841fd…`（= `round2/corpus/manifests/hf-iii-full-audio.json`）。
- 2026-10-16 x0 整批完成：退出码 0，总 1420.8 s；vad 32.4 s（1506）、asr 903.0 s（5420）、align 95.8 s（8060）、translate 367.6 s（15547）。cue：II 1173、III 1269；翻译 118＋127 批，降级与回退 0。评分：II 18.27%（1105／645／220，基线 18.30%）、III 14.99%（1005／485／212，基线 15.14%）。
- 2026-10-16 验收记录 `docs/research/acceptance/2026-10-16-bilingual-pipeline-swr-regression.md`；最终验收"待决 1"加补记；调研索引登记。

## Answer

**回归已回到基线。** 改回 swr 后，产品派生 WAV 与基线 PCM 逐字节一致；w0 两部的 CER、S／D／I、可测条数与时间误差与 2026-10-05 基线完全相同，x0 相差 −0.03／−0.15 个百分点（≤ 0.3 视为回到）。两次整批都零失败、翻译降级与回退 0。后续票据以 `.local/quality-exploration-v5/01/out-{w0,x0}/` 为产品输入。

| 路线 | II CER（基线） | III CER（基线） | 墙钟 s | 显存峰值 MiB | cue II／III |
| --- | --- | --- | ---: | ---: | --- |
| w0 | 16.81%（16.81%） | 13.77%（13.77%） | 890 | 15648 | 1099／1219 |
| x0 | 18.27%（18.30%） | 14.99%（15.14%） | 1421 | 15547 | 1173／1269 |

## Comments

- 2026-10-16 建票。
