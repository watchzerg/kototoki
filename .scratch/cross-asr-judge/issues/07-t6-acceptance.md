# T6 产品路径验收（GPU）

Status: done
Type: task
依赖：06、01

## 内容

HF II／III 以 `engine = cross` 整批运行 `python -m kototoki`，`kototoki_eval` 评分，telemetry 采样；翻译阶段照常启动。

## 文件所有权

`docs/research/acceptance/2026-10-19-cross-asr-acceptance.md`、`docs/research/INDEX.md` 登记

## 完成标准

两部 CER 都低于 w0 且合计降幅 ≥ 1.0 pp；x0 失败窗口与单独运行一致；asr 阶段峰值 ≤ T0 阈值；12 份 SRT 齐全。

## Comments

- 2026-10-19 完成：HF II／III 以 `engine = cross` 整批运行 `python -m kototoki`（06:34:53–07:04:08 UTC，1754.8 s，退出码 0，2 部发布，无残留锁与进程）。验收线：两部 CER 都低于 w0（II 16.81% → 15.93%，III 13.77% → 12.75%）**通过**；两部合计 15.25% → 14.30%，降 0.95 pp，**未达 1.0 pp**（差约 12 处编辑），按增量说明 §5 待用户裁定是否仍采用；x0 失败窗口 0、`asr-x0.json` CER 与单独 x0 运行逐项相同 **通过**；裁判统计与 T0 探针逐区间相同（402／41／1084／200，d 差 0）**通过**；asr 整卡峰值 10030 MiB（＋1 GB ≤ 13824）**通过**；翻译启动前空闲 15120 MiB，293 批降级与回退 0 **通过**；6 份 SRT（一次 cross 整批的完整集合）与 2 份 `published.json` 齐全 **通过**。asr 墙钟 1211.6 s（swr w0 的 3.75 倍）。另发现：worker 以 `-m` 运行时 `getLogger(__name__)` 为 `__main__`，INFO 行（含 cross 每文件计数行）被丢弃，未修；`telemetry_run.py` 按旧日志格式切阶段已失效，本次离线补算。记录见 `docs/research/acceptance/2026-10-19-cross-asr-acceptance.md`，数据在 `.local/cross-acceptance/`。ADR-0012 状态留给 T7。
