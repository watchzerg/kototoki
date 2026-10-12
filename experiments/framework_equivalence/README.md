# Whisper 框架行为等价实验

> 2026-10-05 后续开发入口：本目录保留冻结的框架对照原型。继续开发当前 W0 或独立 Pyannote／MMS 时，复用并更新 [W0 demo](../w0_demo/README.md)，而非继续扩展本对照 runner；独立端到端证据见 [demo 验证](../../docs/testing/2026-10-05-w0-demo-validation.md)。

状态：隔离原型，2026-10-04 两窗已测；不更改正式后端。

同一冻结 Pyannote 分块下，比较 WhisperX 3.8.6、未修改的 faster-whisper API、
以及自研 faster-whisper 适配层。`adapter.py` 与 `vad.py` 不导入 WhisperX。
保留的算法来源及许可见 `THIRD_PARTY_NOTICES.txt`。

`adapter.py` 需要调用方供应冻结的 Mel filterbank；实测使用 WhisperX 安装包中
OpenAI Whisper 来源的 `mel_filters.npz` 私有副本，不证明使用 faster-whisper 动态
生成的滤波器也逐 bit 相等。此原型未独立实现 Pyannote checkpoint 加载或 MMS 对齐。

```powershell
.local/envs/whisper-latest/Scripts/python.exe experiments/framework_equivalence/run.py all --output .local/framework-equivalence/new-identity
.local/envs/whisper-latest/Scripts/python.exe experiments/framework_equivalence/check_vad.py --output .local/framework-equivalence/new-identity
.local/envs/whisper-latest/Scripts/python.exe experiments/framework_equivalence/analyze.py --output .local/framework-equivalence/new-identity
```

入口仅接受 `.local/framework-equivalence/` 内的新实验目录。模型已经配置时离线执行，
不安装、升级或下载。共享 GPU 锁确保模型推理串行；完整文字、raw score、特征及 token
只保存在私有目录。取消会先结束并等待子进程，再释放锁。
未来运行的两条 ASR 子进程从冻结源码副本调用；已完成 v1 保留当时实际源码身份。

CPU 验证包括冻结 score 后处理、严格阈值、长段 min-cut、短语音与间隙及 seed 固定的
多轨随机样本。空 score 原型返回 `[]`，原生代码会抛错，这是额外防护，未声称完全等价。
`analyze.py` 的 S/D/I 是相对 WX 输出的未经规范化文字差异，不能当作对真实日语的识别质量。

结果和边界见[实验报告](../../docs/research/2026-10-04-whisper-framework-experiment.md)。
