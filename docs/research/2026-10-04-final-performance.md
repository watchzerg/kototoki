# 最终重复性与整片资源实测

状态：实测完成，性能与质量分开解释。日期：2026-10-04。

两条路线各完成三次 chapter07 新推理，以及一次完整电影输入。八次均正常退出；
输入、参数、模型、源码、设备身份完整，均无历史 ASR/FA 推理缓存。
各自三次短片的完整文字与 timed units SHA 完全一致。这只证明本次重复稳定，不能证明识别正确。

## 配置与计时条件

W0 为 faster-whisper1.2.1 / CTranslate2 4.8.2 / large-v3，CUDA FP16、beam5、日语
transcribe、无 VAD、无前文 conditioning、保留原生 temperature fallback。
W1 为 WhisperX3.8.6 原生 Pyannote VAD/ASR，batch1、chunk30、相同 large-v3 CUDA FP16，
再用日语 wav2vec2 checkpoint 官方归一化与 TorchAudio2.8.0 标准 CUDA CTC。
精确模型 revision 与锁文件见[环境清单](2026-10-04-runtime-inventory.md)及
[保留测试](2026-10-04-heldout-results.md)。

原生 Windows11 build26200，RTX5080 16303MiB、driver616.92。root/W0 Python3.12.15，
W1 Python3.13.16。GPU 串行，所有其他 agent 的评测、模型、下载任务均已结束或暂停；
桌面与操作系统后台仍不受控制。每次为新进程，操作系统文件缓存未清空，不是冷磁盘测试。
环境设置 HF_HUB_OFFLINE、TRANSFORMERS_OFFLINE、HF_DATASETS_OFFLINE；全部资产在本机。
没有断网或网络抓包验证，不能把 offline 标志扩大解释为系统级网络隔离。

## 实测结果

固定片段长277.756秒，源偏移1438.427秒；整片7028.0426875秒、偏移0。
RTF为外层 harness 实际墙钟除以音频时长，包含新进程、加载、预处理与推理。

| 路线 | 短片三次墙钟秒 | 短片 RTF 中位数 | 整片墙钟秒 | 整片 RTF | 短片/整片整卡采样最大显存 |
| --- | --- | ---: | ---: | ---: | ---: |
| W0 | 16.863 / 15.805 / 15.792 | 0.05690 | 329.740 | 0.04692 | 6461 / 7551 MiB |
| W1 修正流程 | 30.493 / 25.245 / 25.233 | 0.09089 | 195.980 | 0.02789 | 6947 / 6949 MiB |

W1短片启动成本较大，整片却更快；其原生 VAD/ASR 处理方式与 W0 不同，不能据此归因
为单个神经网络或 CTC 算子更快，也不能推断关闭/开启 VAD 的独立因果收益。
三次重复不足以估计总体延迟尾部，整片仅各一次，不能保证任意影片同速。

整片 W0 adapter 内部：音频加载0.610秒、ASR加载2.714秒、ASR324.787秒；
W1：音频加载0.616秒、ASR/VAD加载9.747秒、ASR135.514秒、aligner加载0.912秒、
归一化准备1.052秒、对齐46.016秒。归一化 hook 的0.337秒已包含在对齐内，不重复相加。
这些是调用墙钟而非独立 CUDA kernel 时间；总成本使用外层 harness，不能简单叠加重叠计时。

所有 nvidia-smi 查询有效，间隔约1.04–1.10秒；首点均约2126MiB。
显存数值是整卡采样，包含桌面、runtime和其他系统占用，短峰可能漏采。
首点不是严格空闲基线，不能用相减得到精确模型独占显存。没有 OOM、CPU fallback 或进程失败。
八次运行前后原 SRT SHA 均保持基线。
未采集进程CPU/RAM峰值，不能据此给出完整最低系统内存要求。

## 复现与证据

- 固定协议：`.local/manifests/performance-protocol-v1.json`。
- 运行前选择：`.local/manifests/final-evidence-selection-v1.json`，SHA256
  `030d1a6472521c619818f92f39f442d8281818603425ca937c8e125cd0ea6def`。
- 串行入口：`.venv/Scripts/python.exe .local/analysis/run-final-evidence.py`。
  已存在目录只有命令、音频、manifest及结果receipt完整匹配才复用；复用不是新的测速。
  新重复需另登记新ID，不覆盖原证据。
- 结果：`p1-{w0,w1norm}-ch07-r{1,2,3}` 与 `f1-{w0,w1norm}-full-r1`。
- 只读汇总：`python -m experiments.performance <八个manifest明确路径> --output <新的.local路径>`。
  本轮 `.local/analysis/performance-final/r1/report.json` 保留逐次输入、source/model/runtime、
  stage计时、输出hash和逐卡采样。不同音频分组，不把整片算作第四次相同片段重复。

独立核查 `.local/audit/final-evidence-r1/README.md` 已重新计算八次墙钟/RTF、原始CSV采样
与真实输出相等性，并检查运行时间段不重叠、输入/source/receipt与实际GPU证据。
性能报告SHA256为 `f2ede3bdcbfb123404146788714ac27833329fbfa9eede9b885a1313b3c7731c`。

本页证明本机运行与成本，不授予时间、声学或字幕可用性资格。完整电影包含已用开发、验证、
保留章节，是上下文变化实验，不是新增独立测试集；质量详见[整片结果](2026-10-04-fullfilm-results.md)。
