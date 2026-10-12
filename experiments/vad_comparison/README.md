# W0／X0 VAD 比较

状态：十组合十二窗实测与分析完成；119 项完成、1 项生成上限失败  
最后更新：2026-10-05  
范围：十种组合、冻结十二窗、复用标准 W0／X0 demo。

2026-10-05 后续用户已采用 W0／X0 新 Pyannote＋MMS 基线，见[ADR-0003](../../docs/adr/0003-new-pyannote-baselines.md)。本目录保留十二窗比较及 CPU／GPU 补测的历史身份；`w0-original`／`x0-original` 仍指旧 W0／无 VAD fixed30 X0，不能作为新基线身份。canonical demo 的执行默认仍待迁移，标准实现与验证从[基线测试指南](../../docs/guides/baseline-testing.md)进入。

先读[实验计划](../../docs/plans/vad-baseline-comparison.md)与[官方版本核验](../../docs/research/2026-10-05-vad-stable-versions.md)。
本轮结果见[比较报告](../../docs/research/2026-10-05-vad-baseline-comparison.md)：120 槽全部实际执行，119 份完整产物审计通过，X0＋新 Pyannote 的 1 次生成上限失败保留计分。
新模型放在 `.local/models/vad-comparison/`，CPU 环境为 `.local/envs/vad-comparison/`，
Pyannote GPU 补测使用独立 `.local/envs/vad-pyannote-gpu-v1/`；正常推理离线，不下载或升级。

`vad_stage.py` 调用 W0 目录中的候选 Adapter，输出输入身份、整数源窗口、模型配置和单独加载／推理成本。
`run.py` 保留全部十条路线的十二窗运行槽位，可逐次执行或恢复；每个 VAD 每窗只运行一次，W0／X0 导入同一份结果后各自重新 ASR／MMS。
冻结的原基线走原 demo 入口。GPU 推理串行，共用原锁。新输出禁止覆盖历史运行。

```powershell
.venv/Scripts/python.exe -m experiments.vad_comparison.run --study-id vad-comparison-v1 --candidates .local/vad-comparison/provision/candidates.json
.venv/Scripts/python.exe -m experiments.vad_comparison.evaluate --study .local/vad-comparison/vad-comparison-v1/study.json --out .local/vad-comparison/vad-comparison-v1/analysis
.venv/Scripts/python.exe -m experiments.vad_comparison.verify --study .local/vad-comparison/vad-comparison-v1/study.json --out .local/vad-comparison/vad-comparison-v1/audit.json
.venv/Scripts/python.exe -m experiments.vad_comparison.diagnose --study .local/vad-comparison/vad-comparison-v1/study.json --out .local/vad-comparison/vad-comparison-v1/deletion-diagnostic
```

`--routes w0-original x0-original` 或 `--clips hf-ii-window-01` 可限制当前执行，注册表仍保存全部槽位。
未完成的注册表不进入正式比较。门控权重不可用时保留 blocked，不能以旧模型顶替。
执行失败保留日志与完整分母；修复后另立运行身份，不能覆盖已有模型输出。
配置 JSON 以 `pyannote-current`／`silero`／`fsmn`／`firered` 为键，值含 `python`、`model`、`revision`、`device`、`status`。

新版 Pyannote 的 GPU 补测按[独立计划](../../docs/plans/pyannote-gpu-comparison.md)使用新登记与隔离环境；
[补测结果](../../docs/research/2026-10-05-pyannote-gpu-comparison.md)为23次完成、1次同窗触顶，检测及完整输出与 CPU 一致。
模型复用的单窗 GPU 检测约快13.1倍，每窗新进程的批次则更慢；两种成本分别保存。
只重新执行两条 Pyannote 路线；其余八条作为明确标注的历史参考，不能称为本次新测。
`study.json` 可用 `vad_provision_dirs` 按候选 ID 指定独立 provision 目录；目录须含
`models-manifest.json`、`packages-manifest.json`。显式包清单中的每个版本均须出现在 VAD 运行元数据中并一致，
完整环境依赖另存 freeze；审计记录所选目录、清单 SHA256 及检查的模型／包身份。未指定时继续使用原 CPU 清单。

评分保留全文、text_only、局部对齐失败、全部参考和跨边界不确定性。完整进程墙钟由父进程记录，
新增 VAD 的串行总成本是实测 VAD 成本加实测 ASR／MMS 流程成本，不是两次独立 VAD 端到端重复测量。
GPU 内存按秒采样整卡使用量，包含桌面和其他进程，只作机器级观察，不是模型独占显存或严格峰值。
CPU 利用率未测，不用缺测值推断轻量程度。

主批次结束后可另跑 VAD 独立资源补测；不要与主批次同时运行：

```powershell
.local/envs/vad-comparison/Scripts/python.exe -m experiments.vad_comparison.resources
```

默认输出到新的 `.local/vad-comparison/resource-v1/`，使用冻结的第一个 II 片窗口，
核对模型、源码、输入身份及主批次同窗 chunks。比较使用 `result.worker_memory` 中真实推理进程的
lifetime peak working set；50 ms RSS 采样作为补充，Windows venv launcher 的内存只作诊断。
原 Pyannote 使用共享 GPU 锁，另记 Torch allocator 峰值，排除 CUDA context 和其他库。
这些指标只覆盖单窗 VAD 独立进程，包含导入及加载成本，不代表 ASR／MMS 总内存或全数据集峰值；
本轮有效补测保存于 `.local/vad-comparison/resource-v2/`，四模型均成功且与主批次同窗 chunks 一致。
`resource-v1` 保留模型加载前输入哈希校验失败记录；继续补测须用 `--out` 指定新的目录，不覆盖既有证据。

独立 `verify.py` 从源 WAV 重算 float32 PCM hash，逐窗核对 VAD／ASR／MMS 的整数边界、
模型与环境记录、源码快照、全文字符覆盖和原基线同窗回归。未执行槽位不会当作通过；
若有门控 blocked 或无完整产物的失败，整个产物审计仍为 incomplete，已完成槽位的证据检查单独报告。
当前审计的 `not_executed_slots=1` 表示没有完整结果产物；对应任务实际已尝试推理并因生成上限失败，不能解释为未测。
最终证据位于 `analysis-with-pyannote/`、`audit-with-pyannote.json`、`deletion-diagnostic-with-pyannote/`；
旧 `analysis/` 与 `study-before-pyannote.json` 保留授权前八组合快照。新 Pyannote 资源实测在 `.local/vad-comparison/resource-pyannote-v1/`。

`diagnose.py` 是独立补充分析：只统计所有最优文字对齐路径都确定的“基线正确、候选新漏掉”字符，
用基线 CTC 时间与候选原时间窗口比较，分别记录裁剪外、跨界、裁剪内、无可靠时间。
零时长、粗粒度或插值时间不用于归因，跨相邻窗口但音频完全保留的情况另计；不改变主评分，
不把基线 CTC 时间视为声学真值，也不把相关性写成 VAD 导致漏字的证据。

```powershell
.venv/Scripts/python.exe -m unittest discover -s experiments/vad_comparison -t . -v
```

仅输出数量、状态、成本和私有路径；完整音频、转写、模型、日志与 JSON 留在 Git 忽略的 `.local/`。
