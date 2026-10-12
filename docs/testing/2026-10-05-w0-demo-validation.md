# W0 可复用 demo 独立验证

状态：旧 PyanNet demo 两窗回归通过；当前 newPyannote 证据另见整片报告  
最后更新：2026-10-05  
范围：原生 Windows／RTX 5080；本页原数字和逐项等价结论属于旧 PyanNet `w0-pyannote-mms-v1`，保留冻结身份。

当前 W0 已按[ADR-0003](../adr/0003-new-pyannote-baselines.md)采纳 faster-whisper＋newPyannote＋MMS，
显式 manifest recipe 为 `w0-pyannote-current-mms-v1`；无降噪、无人声分离。
本次仅更新文档，代码无参数默认仍是旧 PyanNet。新的基线命令见[demo README](../../experiments/w0_demo/README.md)。
最新 newPyannote 两部整片运行及 canonical ASR／MMS 同窗验收见
[整片报告](../research/2026-10-05-fullfilm-segmentation-comparison.md)。整片 W0 两次 MMS 极短窗失败均保留全文／text_only；
它不继承下文旧 VAD score、窗口、特征或 token 逐项相等的结论，不宣称时间目标已通过。

## 实现与身份

后续共享接口补充：为[X0 demo](../../experiments/x0_demo/README.md)增加可选整数样本窗口，
W0不传整数字段时继续旧裁剪路径。修改后41项W0后端离线测试通过；1001样本、非零起点及原秒坐标行为分别覆盖。
本页原两窗GPU结果保持冻结源码身份；新增X0真实GPU证据见[X0验证](2026-10-05-x0-demo-validation.md)，
不把X0运行写成重跑了W0的Pyannote／Whisper。

本页历史验收入口为 [`experiments/w0_demo/`](../../experiments/w0_demo/README.md)，recipe `w0-pyannote-mms-v1`。
VAD、ASR、MMS 各有独立模块和可替换边界；推理不导入 WhisperX，也不导入旧实验 runner／monkeypatch。
VAD 与 Mel 资产离线复制到 `.local/models/w0-assets/`，保留 hash 和许可通知。
使用既有 `.local/envs/whisper-latest`，没有安装、升级、下载或修改默认后端。

- Python 3.13.16；faster-whisper 1.2.1、CTranslate2 4.8.2、Pyannote.audio 4.0.7、Torch／TorchAudio 2.8.0+cu128、Transformers 4.57.6。
- large-v3，CUDA FP16、日语 transcribe、beam5、batch1；无前文 conditioning、无时间戳 token；冻结 Mel 与有效 CT2 参数。
- 已测 PyanNet checkpoint：`0b5b3216d60a2d32fc086b47ea8c67589aaeb26b7e07fcbe620d6d0b83e209ea`；CUDA，onset 0.5／offset 0.363，原 cut/merge。
- Mel 资产：`7450ae70723a5ef9d341e3cee628c7cb0177f36ce42c44b7ed2bf3325f0f6d4c`。
- MMS jpn，2268 词表、blank0，参数／输入 CUDA FP32、标准 CUDA forced_align；前向数值策略见下节。
- 每次独立输出保存输入／全部本地模型文件 hash、源码快照、运行包版本、设备和参数；完整音频／文字仍在 `.local/`，不写入本文。

## 同输入回归

输入是已有 II／III 各 window-01 的300秒16k单声道PCM16 WAV，源偏移分别351.402125与366.2666875。
ASR／VAD 参照 `.local/framework-equivalence/v1/`；MMS 参照
`.local/results/jctc-mms-full-v2-{clip-id}-w1-mms/result.json`。
本轮是重新运行真实 VAD、ASR 和 MMS，不是缓存对齐；比较脚本为 `experiments/w0_demo/compare.py`。

验收逐项检查原始 VAD score hash／帧坐标、切分合并窗口、ASR 特征 hash／prompt／CT2 kwargs／token、
完整识别分段、MMS 搜索窗口、完整文字／字符 units、归一化音频 hash、MMS emission hash、CTC path hash 与 token 帧／概率。
没有删去无法计时的内容，全文和全部 units 一起比较；不是只看平均值或条件分位数。

最终私有身份：`.local/w0-demo/verified-v1-hf-{ii,iii}-window-01/`，每份 `result.json` 与 `comparison.json` 记录证据。

| 输入 | 块数 | 全文字数 | 有时间字符 | text_only 字符 | 对照结果／CTC失败 |
| --- | ---: | ---: | ---: | ---: | --- |
| II window-01 | 8 | 550 | 532 | 18 | 全项相等／0 |
| III window-01 | 9 | 676 | 628 | 48 | 全项相等／0 |

合计17块、1226字符，其中1160字符有时间，66字符保留为 text_only；完整 units 与旧 MMS 一致，未通过删除内容制造改善。
17块特征、prompt、生成参数、token、分段及 MMS emission／路径／概率全部相等。
这证明本次完整移植在同两窗保留了旧 W1＋MMS 的已测行为，不代表改善了原有时间质量。

| 输入 | VAD推理 | ASR推理 | 新MMS对齐推理 | VAD／ASR／MMS加载 | runner墙钟 |
| --- | ---: | ---: | ---: | --- | ---: |
| II | 15.274s | 15.074s | 1.884s | 21.419／2.862／2.303s | 59.351s |
| III | 14.978s | 16.162s | 2.053s | 20.626／2.700／2.243s | 59.276s |

加载包含对应包的延迟导入。runner墙钟在主要结果构造后、完整模型哈希／输出序列化前记录，不是操作系统级进程总时长。
没有使用缓存 ASR 或缓存 CTC；两窗只是串行实测，不作为稳定性能排名。

## 数值状态泄漏与修复

初次开发 smoke `.local/w0-demo/v1-hf-ii-window-01/` 的8块识别、550字全文和全部字符时间已经一致，
但 MMS emission hash 与 token 概率不同。该次运行处于代码整理期间，只作故障定位，不作为源码冻结验收。

逐项排查确认：原始／归一化 waveform hash、采样边界、有效长度和补零均完全相同；概率最大绝对差约0.001353，CTC path 未变。
本机 `pyannote/audio/core/inference.py` 调用 `utils/reproducibility.py::fix_reproducibility`，
将 PyTorch matmul／cuDNN TF32 全局置为 False，不恢复。旧 cached-only MMS 的独立进程默认 matmul False、cuDNN True，
因此将三个模块串联会暴露原实验的隐含状态约束。

本 demo 将 MMS 前向限定在显式作用域：matmul TF32 False；cuDNN enabled True、benchmark False、deterministic False、TF32 True，
成功或异常退出都恢复调用者原配置。全局 deterministic algorithms 要求不擅自修改，实际值写入记录。
II 的重新完整推理恢复了所有8段 emission hash、CTC path 与 token 概率的逐项相等，确认该差异可由数值配置消除。
III 随后9段也全部相等。这也是以后替换 VAD 必须保留的隔离边界；FP32 参数不等于所有 cuDNN 内核禁止 TF32。

## 离线检查与限制

- 新 demo 在推理环境35项离线测试全部通过，包含46个 VAD 后处理对照、特征字节一致、官方归一化、重复字符／OOV、失败保留、私有输出、源偏移和资源释放。
- 轻量根环境同35项中27通过、8项因可选 NumPy／Torch／Pyannote 依赖缺失明确跳过；推理环境补齐了这些测试。
- 现有10组共220项离线回归无失败，其中18项既有可选依赖测试跳过。使用项目 `.venv` 执行等价于 justfile 的 unittest 命令；临时目录在 `.local/tmp`。
- Python compileall 通过。模型推理环境仍安装 WhisperX，但真实 demo `whisperx_imported=false`；未声称验证过完全不安装 WhisperX 的新环境。
- Pyannote 的 torchcodec 警告不影响预加载 WAV 路径；本入口只接收已准备的PCM WAV，没有新增通用媒体解码能力。
- TorchAudio 2.8 forced_align 的弃用警告仍存在；没有升级环境。它是明确的后续维护点。
- 不兼容旧 WhisperX 原生句级 cue；通过现有显示层消费全文／字符 units。本页早期两窗验收没有做主观听辨、十二窗、整片、batch>1或新模型／新VAD评估；后续 newPyannote 证据独立见上方报告，不宣称字幕时间已达标。

后续 session 应按[demo 流程](../../experiments/w0_demo/README.md)继续迭代此入口，更换行为使用新 recipe／运行身份并维护本文后续证据入口。
