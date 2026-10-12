# 新 Pyannote 的 CPU／GPU 对照

状态：十二窗 GPU 重测、复用补测、评分及产物核验完成；保留1次真实生成上限失败  
日期：2026-10-05  
范围：原生 Windows 11、RTX 5080、既有十二个电影窗口；不修改默认基线。

2026-10-05 后续采用：用户在[整片比较](2026-10-05-fullfilm-segmentation-comparison.md)完成后明确采用 W0／X0 新 Pyannote＋MMS 基线，见[ADR-0003](../adr/0003-new-pyannote-baselines.md)。本文仅保留 CPU／GPU 补测事实及其质量、加载与模型复用边界；下文“不构成更换依据”不否定后续用户决定。canonical demo 的执行默认仍待迁移。

## 结论

改用 GPU 没有改变本次检测、识别或对齐结果，也没有消除 X0 的生成上限失败。
速度取决于模型是否复用：每次启动新进程时 GPU 更慢；同一 VAD 实例复用时，本次单窗补测的 GPU 约快 13.1 倍。
这支持在持续处理、可复用模型的场景继续评估 GPU，但不构成更换默认 W0／X0 配方的质量依据。

## 比较身份

用户要求将[十组合研究](2026-10-05-vad-baseline-comparison.md)中的新 Pyannote 改为 GPU 重测。
范围按[补测计划](../plans/pyannote-gpu-comparison.md)固定：60分钟、6544参考字符、590条参考字幕。
所有素材此前已接触；字幕是文本／显示边界参考，不是人工声学真值。

CPU 和 GPU 都使用 Python 3.12.15、`pyannote.audio 4.0.7`、Torch／TorchAudio 2.11.0，
同一 `segmentation-3.0` revision `e66f3d3b9eb0873085418a7b813d3b369bf160bb`。
全环境逐包核验，只有 Torch／TorchAudio 从 `+cpu` 变为 `+cu128`。
GPU 为 CUDA 12.8、`cuda:0`、FP32；Pyannote 原生 TF32 禁用策略保持不变。
没有更换权重、阈值、切分合并、Whisper、Qwen 或 MMS 参数。

GPU 环境为 `.local/envs/vad-pyannote-gpu-v1/`，清单为
`.local/vad-comparison/provision-pyannote-gpu-v1/`。
`environment.json` 保存完整依赖差异与 RTX 5080／sm_120 运算验证；
`torch-wheels-manifest.json` 保存官方 CUDA wheel URL／SHA256。
原 CPU、ASR、MMS 环境均保持原状；音频与推理只在本机。

## 执行与证据

新登记：`.local/vad-comparison/pyannote-gpu-v1/study.json`。
其中两条新 Pyannote 路线各重新运行十二窗；每窗 GPU VAD 检测一次，两条路线导入相同整数窗口后分别重做 ASR／MMS。
其余八路线的96次历史结果仅作为参考，未重新推理。原登记 SHA256 为
`ba4f29fea36d2bef1d03010a789b709bbc63beea7689ff82119ee754c5fcda1d`，原 CPU 失败也保持不变。
每次输出另立身份，完整参考保留；失败不得按成功子集排除。

## 单窗冷进程资源测量

同一个 II window-01，300秒。CPU 为此前冻结测量，GPU 为本次新测；每个数字来自一次独立进程。
加载与推理计时分开，首次调用可能包含后端初始化成本。

| 指标 | CPU | GPU |
| --- | ---: | ---: |
| VAD 加载 | 15.683秒 | 21.941秒 |
| 第一次 VAD 推理 | 3.115秒 | 15.083秒 |
| 完整进程 | 23.199秒 | 43.196秒 |
| 推理进程 lifetime peak working set | 1024.91 MiB | 1550.58 MiB |
| Torch 显存 allocated 峰值 | 不适用 | 413.05 MiB |
| Torch 显存 reserved 峰值 | 不适用 | 734 MiB |

CPU／GPU 首窗的8个切分窗口及组成语音段完全相同。GPU 参数实际位于 `cuda:0`，不是 CPU 回退。
显存数字是 CUDA 初始化之后、加载模型前至推理后的 Torch allocator 峰值，排除 CUDA context 与其他库，不能当作整卡占用。
RAM 为实际推理解释器的进程峰值，不是 Windows venv launcher。
GPU 证据：`.local/vad-comparison/resource-pyannote-gpu-v1/pyannote-current/`；
CPU 证据：`.local/vad-comparison/resource-pyannote-v1/pyannote-current/`。

## 模型复用补测

为区分首次调用开销与模型常驻成本，CPU／GPU 各使用独立进程，加载一次模型，对同一300秒波形连续调用三次 `segment`。
每次都重新执行 Pyannote 检测，创建新的输入字典，没有回放检测缓存；CUDA 调用前后同步。
不调精度、阈值、batch 或 TF32，不在调用之间清空 allocator 缓存。

| 同一模型实例 | CPU | GPU |
| --- | ---: | ---: |
| 第一次检测 | 2.726秒 | 15.065秒 |
| 第二次检测 | 2.615秒 | 0.201秒 |
| 第三次检测 | 2.639秒 | 0.200秒 |
| 后两次平均 | 2.627秒 | 0.201秒 |

后两次平均耗时比为13.094。六次检测的完整 chunks 都与 CPU／GPU 主批次首窗一致。
GPU 三次调用的 Torch allocated 峰值均为413.05 MiB；峰值含驻留模型，排除 CUDA context 与其他库。
首次检测计时已排除包导入、显式 CUDA 初始化及模型加载，因此只能说存在明显首次调用成本，尚未通过 profiler 确定内部耗时来源。
这里仅复用一个已接触窗口、各两次后续调用，不是长期吞吐、不同输入、并发或整片验证。

证据：`.local/vad-comparison/warm-pyannote-cpu-v1/`、`warm-pyannote-cuda-v1/`。
脚本为 `.local/vad-comparison/warm-pyannote-probe.py`，源码快照保存在每份结果中。

## 质量、完成率与失败

24次新尝试中23次完成、1次失败：W0 12／12完成，X0 11／12完成。
十二窗 GPU VAD 均为实际 `cuda:0`、FP32，共111个窗口，与 CPU 的整数裁剪和组成语音段完全一致。
23组成功结果的全文、字符 units、原始分段、对齐记录及非空 ASR token 序列均完全一致。

| 路线 | CPU CER | GPU CER | CPU／GPU 的 S／D／I | 严格半秒成功（两者相同） |
| --- | ---: | ---: | --- | ---: |
| W0＋新 Pyannote | 14.914% | 14.914% | 494／331／151 | 353／590 |
| X0＋新 Pyannote | 25.672% | 25.672% | 548／1025／107 | 307／590 |

X0 的主成绩为**保留失败的管线成绩**。`hf-iii-window-03` 首段93375–507556样本再次生成4096 tokens后失败；
计划10段，仅第一段尝试，剩余9段与MMS未执行。CPU／GPU的部分文字、分段和 token 序列也一致。
失败窗742参考字符／59条字幕仍留在6544字符／590条完整分母中，不能把部分输出当作完整转写。
本次没有通过重试、提高生成上限或删除该窗来改善成绩。

## 完整批次成本

| 十二窗重构串行成本 | CPU VAD | GPU VAD |
| --- | ---: | ---: |
| 独立 VAD 进程总墙钟 | 275.391秒 | 512.429秒 |
| W0：VAD＋新 ASR／MMS | 1027.508秒 | 1227.818秒 |
| X0：VAD＋新 ASR／MMS，含失败尝试 | 1525.631秒 | 1722.961秒 |

本批次每窗都重新启动 VAD 进程，所以没有享受上节的模型复用速度。
W0／X0 每条路线分别计入共享 VAD 的完整进程成本；不可将两行相加当作研究实际墙钟。
ASR／MMS 原配置未变，批次分时执行，其他进程成本也有波动；不将路线总耗时差全部归因于 GPU VAD。

## 核验入口

`.local/vad-comparison/pyannote-gpu-v1/` 保存以下产物；原96份历史参考记录及原 CPU 登记保持不变。

- `study.json`、`study-after-execution-raw.json`：最终登记、原执行快照及失败证据哈希。
- `analysis/report.json`、`analysis/identity.json`、`analysis/diagnostics.json`：完整分母评分、成本、输入／输出及评测器身份。
- `audit.json`：119份完整产物通过、0份校验失败，其中96份为历史参考、23份为新 GPU 结果。
  顶层 `incomplete`／`not_executed_slots=1` 是审计器沿用的“没有完整结果”分类，该槽实际上已经执行并触顶失败，不能解释为未测。
- `device-comparison.json`：十二窗检测、23组成功输出、1组失败部分输出和两路线总体／分片评分对照；六组评分字段完全一致。
- `independent-audit.json`：独立子 agent 对实际设备、版本差异、原参考保持、输出一致性和复用推理的复核。

比较工具的38项离线测试通过；推理代码未变，仅增加独立 GPU provision 的审计选择及验证。
