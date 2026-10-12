# Whisper 实验入口

> 2026-10-05 后续开发入口：此目录的 W0 指历史无外部 VAD 路线，命令用于复现旧实验。开发当前 W0、修改解码或特征时，复用并更新 [W0 demo](../w0_demo/README.md) 的 `asr.py`；旧 runner 保留作回归参照。

## 锁定后的 W0 → 规范化标准 CTC 探索分支

`run_combined.py` 是新的、顺序冷子进程入口：先在独立 W0 环境执行无前文 conditioning、
保留原生 temperature fallback 的 ASR，再在 WhisperX 环境执行规范化标准 CTC。
它不改动冻结 `run.py` 或三个 CTC helper，也不属于原锁定保留候选，不能据此新增盲测结论。
目的仅是保留 W0 文字，在同输入/源坐标上隔离新对齐机制。

```powershell
.venv/Scripts/python.exe experiments/whisper/run_combined.py --audio .local/audio/chapter-07.wav --offset 1438.427 --output .local/results/w0-ctc-exploratory-ch07-r1/result.json --dll-dir .local/tools/whisper-runtime-provisional
```

模型与环境必须预先获取；默认环境为 `.local/envs/whisper-w0-py312` 和
`.local/envs/whisper-latest`。使用 `--w0-python`、`--whisper-python`、`--asr-model`、
`--ctc-model` 可明确本地路径。新结果只能写入项目 `.local` 且不能覆盖旧目录。
GPU 推理必须由主任务外层 harness 排队；本入口不会并发启动两个模型或新建 GPU 队列。

输出保存全部原文/无时间字符、原生结果及 `pipeline`：ASR/CTC stage命令、日志、source
副本及SHA、输出SHA、设备证明、完整音频SHA和阶段缓存分类。两阶段均为新推理，CTC
只复用本次新ASR；模型下载缓存不算推理复用。wrapper wall包含准备与冷子进程，完整
进程性能以外层 harness wall为准，不能把阶段计时重复相加。

CTC验证器仅从本次snapshot的 `experiments/qwen/run_cross.py` 加载stdlib纯函数，
不调用Qwen推理。它检查每次 normalization、CTC模型forward和新decoder的CUDA证据与
对应关系。OOV仍保留文字为text-only，decoder失败保留stage结果并将pipeline标记失败。
ASR config/source/device不符时直接失败。压缩率超上游阈值作为未解决生成风险保存，
不清洗重复文字、不仅凭压缩率认定真实声学错误；原生segment API没有完整token-cap
证据，不能把无marker当作无cap保证。任何错误均保留已产生的source/结果/log和失败清单。

离线CPU检查：

```powershell
uv run --locked --offline python -m unittest discover -s experiments/whisper -p 'test_combined.py' -v
```

这是fake subprocess/source/失败保留测试，不证明该组合实际GPU成功或质量达标。
分支范围与锁定后的探索身份由主任务
`.local/manifests/w0-standard-ctc-exploration-v1.json` 维护；既有保留候选与规则不因它改变。
模型、配置与CTC时间语义详见
[Whisper执行记录](../../docs/research/2026-10-04-whisper-execution.md)及
[后续工程边界](../../docs/research/2026-10-04-whisper-engineering-boundaries.md)。
