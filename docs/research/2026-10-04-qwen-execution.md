# 官方 Qwen native HF 执行核查

> 2026-10-05 当前入口说明：本文保存历史Q0的ASR／原生FA核查及当时任务状态。当前X0为Qwen＋MMS，运行和修改使用[X0 demo](../../experiments/x0_demo/README.md)，测试按[统一指南](../guides/baseline-testing.md)；原生FA和旧Jonatas桥接不作为当前默认入口。

状态：探索中；源码、冻结环境和原生 CUDA 推理已验证，开发集时间失败定位与有界消融进行中。  
最后更新：2026-10-04。  
范围：原生 Windows、RTX 5080、官方 Qwen3-ASR-1.7B 与 Qwen3-ForcedAligner-0.6B；
为[本地 demo 计划](../plans/local-stt-demo-selection.md)的 Q0 提供可复现实验入口。

## 来源与冻结版本

本次使用 research 工作流，直接核查官方模型卡、官方 Transformers 稳定 tag、PyPI
元数据和 PyTorch 官方 wheel 索引。下列链接访问日期均为 2026-10-04；本报告未将
模型卡公开精度或 A100 性能数字视为本机证据。旧 wrapper 调研保留为[历史核查](2026-10-03-qwen-crisp-demo-readiness.md)。

| 组件 | 本轮冻结身份 | 来源 |
| --- | --- | --- |
| Transformers | 5.18.0；tag commit `a906d3c4b65095f2308b6a6a193e934d03b8eb5d` | [PyPI](https://pypi.org/pypi/transformers/json)、[稳定 tag](https://github.com/huggingface/transformers/tree/v5.18.0) |
| PyTorch | 2.14.1+cu130，Windows cp313 wheel；SHA256 `f064c797bb497daf2b2b5e32b6d794abef087e3f24e758e6c6f8010bd2698319` | [官方 CUDA 13 索引](https://download.pytorch.org/whl/cu130/torch/)、[PyPI](https://pypi.org/pypi/torch/json) |
| Accelerate | 1.15.0 | [PyPI](https://pypi.org/pypi/accelerate/json) |
| nagisa | 0.3.0；日语 FA 分词依赖 | [PyPI](https://pypi.org/pypi/nagisa/json) |
| SoundFile / librosa | 0.14.0 / 1.0.0 | [SoundFile](https://pypi.org/pypi/soundfile/json)、[librosa](https://pypi.org/pypi/librosa/json) |
| Python | 最终 3.13.16；准备阶段 3.13.2 | 最新兼容补丁由 Whisper 环境负责人 provision，本环境只读引用该解释器 |
| ASR checkpoint | `Qwen/Qwen3-ASR-1.7B-hf` @ `bcd2b5b7f32b480ab5790554cfa8347f246a14f3` | [模型卡](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf)、[固定元数据](https://huggingface.co/api/models/Qwen/Qwen3-ASR-1.7B-hf/revision/bcd2b5b7f32b480ab5790554cfa8347f246a14f3?blobs=true) |
| FA checkpoint | `Qwen/Qwen3-ForcedAligner-0.6B-hf` @ `c07281df297b9905d24a508279258cccf987a064` | [模型卡](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf)、[固定元数据](https://huggingface.co/api/models/Qwen/Qwen3-ForcedAligner-0.6B-hf/revision/c07281df297b9905d24a508279258cccf987a064?blobs=true) |

模型卡标示两者 Apache-2.0。ASR `model.safetensors` 为 4,076,193,080 字节，官方
LFS SHA256 `2db53c7d81bd9b8cbc6a074e89be2c968a0d373fb4ee68bb1b1e14f7042dfee1`；
FA 为 1,835,545,960 字节，SHA256
`00568245ceca5af1991d28562a75fe1ddc9bfeb041c27fda66947ea05c47fb86`。
这些是预期完整性身份，下载完成后须由资产流程验证，不能冒称本报告已经校验本地文件。
两者 processor/tokenizer/config/chat template 必须配套同一 checkpoint revision。

## 推荐接口与实际预处理

当前[官方 native ASR 卡](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf)明确将
`apply_transcription_request` 推荐为转写入口，并要求 Transformers >=5.13.0。
本轮直接使用 `AutoModelForMultimodalLM` 的 greedy `generate`，再用配套 processor
解析；FA 使用 `AutoModelForTokenClassification`、`prepare_forced_aligner_inputs` 和
`decode_forced_alignment`。不将旧 `qwen-asr==0.0.6` 接口装进同一环境。

[5.18.0 processor 源码](https://github.com/huggingface/transformers/blob/v5.18.0/src/transformers/models/qwen3_asr/processing_qwen3_asr.py)
设置 16 kHz、padding=True、truncation=False、attention mask、n_window=50。helper 没有
VAD 或自动 waveform 切窗；解析文字会调用上游 repetition 修正，原始 decoder 文本也保存。
[feature extractor](https://github.com/huggingface/transformers/blob/v5.18.0/src/transformers/models/qwen3_asr/feature_extraction_qwen3_asr.py)
将不足 8000 samples 的输入补零，并把 mel 帧轴右补齐到 `2*n_window` 的倍数。
其 `chunk_length=30` 说明限定为 padding='max_length' 时 trim/pad 的长度；推荐 helper
覆盖为 padding=True/truncation=False，因此不能据这个默认配置宣称只支持 30 秒音频。

官方模型卡声明 FA 最多 5 分钟语音，且支持日语；本轮单窗限制为 300 秒。ASR helper
本身不建立长音频分窗，长片必须显式使用适配器连续窗并标记为扩展诊断。没有假设
原 wrapper 的 180 秒时间模式仍作用于 native HF。

FA API 将 80 ms 类别预测通过 LIS 和异常块修正转为单调时间。适配器保存修正前类别
ID 和修正后 API 秒数，标注 `time_source=api`，报告修正数量；API 单调性不是声学
正确性的证明。日语 nagisa 单元按保留字母/数字/撇号的原文字映射回字符跨度，标点不
参与时间匹配。未覆盖文字保留为 text_only；不插值缺失时间，不按字幕行号对齐。

## 本机准备、入口与验证边界

最终独立环境 `.local/envs/qwen-hf-final`；uv 缓存 `.local/cache/qwen-uv`。准备阶段
`.local/envs/qwen-hf` 保留，最初 torch 下载未因升级解释器而重启。模型资产由统一
下载负责人写入 `.local/models/qwen3-asr-1.7b-hf` 与
`.local/models/qwen3-forcedaligner-0.6b-hf`，本 agent 不并发下载。初始驱动只读查询
为 RTX 5080、616.92；这不是模型执行证明。推理队列由主 agent 排队。

入口与用法见 [Qwen 实验 README](../../experiments/qwen/README.md)。适配器默认
BF16、SDPA、ja、batch 1、4096 token 上限、无 prompt、ASR/FA 顺序驻留；这是本轮
显式配置，并非宣称模型卡的所有示例默认都相同。保存上游 generation config 和实际
参数，记录 token cap 命中。模型和输入张量逐项检查 CUDA，ASR token 输出和 FA logits
也需为 CUDA；设备不可用直接失败。所有模型加载 `local_files_only=True`，离线环境
变量强制关闭 HF 网络获取。正常读取源 WAV 后将同一 float32 PCM 交给两个 processor。

GPU-free 测试 5/5 通过：原文标点/源时间 offset、未映射文字保留、非法时间不修补、
重复文字按顺序映射、已有输出不覆盖。模型权重每次核对预期 SHA256，配套文件哈希保存，
完整性核查用时单列。真实模型载入、CUDA 推理和独立离线进程已由主 agent 实测，
开发结果见下节；整片连续性、独立保留测试和重复性仍未验证。冷启动进程用时由外层记录，入口 total
从重型 Python 依赖导入后开始；不能当作完整冷启动速度。入口不含统一字幕 writer。

## 准备结果与未决事项

1. 已按 62-package SHA256 [hashlock](../../experiments/qwen/requirements.lock) 安装，
   `uv pip check` 通过；torch 下载 23 分 25 秒，其余依赖下载 52.99 秒、安装 5.13 秒。
   nagisa 0.3.0 / DyNet38 2.2 Windows 导入和 synthetic 分词、两个 native Qwen AutoModel
   类导入、1 秒 synthetic PCM processor 处理、batch decode 均通过。安装模块 processor/
   feature source SHA256 与稳定 tag 完全一致，完整证据见
   [environment.json](../../experiments/qwen/environment.json)。这些 CPU 检查不是 GPU 推理证明。
2. 两个官方 checkpoint 已由资产负责人完成 SHA256 校验；主 agent 串行执行原生
   Q0 smoke 和 chapter-01/02/05/07。ASR、FA 全部参数、输入、输出均为 `cuda:0`，
   本报告不把 CPU 准备脚本当作推理证据。
3. 当前 BF16/SDPA 已可运行，没有证据要求盲目更换精度。
4. 已复核真实分词映射和 API 时间修正，映射 diagnostics 为 0，仍保留零时长和逆序原始预测。
5. 对进入验证的配置再运行长音频、整片和离线重载；本报告当前不推荐任何已达标实施路线。

## 开发实测：ASR 可用性与 FA 失败分开解释

以下均来自主 agent 的 `.local/results/q0-*-cuda-*-r1/`，使用同一模型、实现、ja、
BF16、SDPA、batch 1、4096 token cap。分数为 `scoring-v2` 原 SRT 显示参考差异，
不是人工声学真值；匹配器为 `nfkc-punctuation-v2-universal-complete-invariant-boundaries`。
没有读取验证或保留集。native 是每个章节单窗口；30 秒为显式连续固定网格扩展。

| 开发范围 | native CER / 删除率 | native 可测 n/N / 条件 E-P95 | 30 秒 CER / 删除率 | 30 秒可测 n/N / 条件 E-P95 |
| --- | --- | --- | --- | --- |
| chapter-01 | 0.2743 / 0.0338 | 8/28 / 46.290 s | 0.3165 / 0.1646 | 14/28 / 15.210 s |
| chapter-02，稀疏音乐语音 | 0.1250 / 0 | 1/1 / 0.209 s | 4.3750 / 0 | 1/1 / 0.209 s |
| chapter-05 | 0.2109 / 0.0192 | 17/64 / 33.862 s | 0.2332 / 0.0224 | 27/64 / 6.782 s |
| chapter-07 | 0.1931 / 0.0157 | 32/62 / 1.163 s | 0.1633 / 0.0141 | 37/62 / 1.653 s |

分母包含不可测项；条件分位数不能独立决定晋级。chapter-02 原生仅 8 个参考字符，
30 秒产生 34 个插入，不能将其正确短句的 0.209 s 时间包络当成整体成功。
chapter-07 原生具有较好的条件时间，说明“长窗必然失败”不成立；场景、文本和
声音条件仍有影响。chapter-17 超过 FA 300 秒上限，原生单窗不合格，不能静默切窗
后继续称为 native。其固定窗分支需要完整失败记账后另报。

60 秒 smoke（源时间 10–70 s）经 scoring-v2 得 16 个参考字符 S/D/I=0。
ASR 的同步 `generate` 调用墙钟为 16.915 s，FA 的同步 forward 调用墙钟为 0.101 s；
两者包含主机调用开销，不是隔离的 GPU kernel 时间。ASR/FA 峰值 allocated 分别
4,546,444,288 / 2,337,640,960 字节，reserved 分别 4,718,592,000 /
2,512,388,096 字节。ASR 加载 3.160 s、FA 加载 1.674 s，入口 total 26.725 s，
其中权重完整性核查 3.367 s；入口 total 不含 Python 导入冷启动，不能作为整片速度。
四个重复短词都识别出来，但只有 2/4 可测，另外两个为零时长非法时间；两个可测
E 分别为 4.430 / 14.640 s。文字正确没有证明 FA 时间正确。

## 重复短词的只读取证和下一轮探针

CPU 取证脚本及私有结果为 `.local/analysis/qwen/replay_smoke.py` 和
`smoke-fa-forensics.json`。重建 FA processor 输入证明实际 PCM SHA256 一致，
四个分词单元及八个 timestamp marker 与运行记录吻合，形状为 `[1,802]`；marker
位置为 785/786、790/791、795/796、800/801。同样单元分别映射四个不同字符跨度，
source offset 只加一次。没有发现 helper 或字符映射导致此失败的证据。

原始类别已经含重复的第三组锚点和逆序的第四组起止。重放官方 LIS 修正，与保存的
API 输出逐项一致，恰好修改第三组起点、第四组终点，形成两个零时长单元。
第一组过宽、第二组过晚在修正前已经存在，关闭修正无法解决其内容关联问题。
这可以定位错误先于 API 修正出现，但尚不能确定神经网络预测错误的内部原因。

有界下一轮由主 agent 执行：

1. 保持其他配置不变，使用 120 秒固定网格，与 native/30 秒三臂比较开发全集。
   30 秒使部分时间失败减少，却恶化 chapter-01 删除和 chapter-02 音乐幻觉；120 秒
   用于测试上下文与 FA 长度的取舍。这个探针同时改变 ASR 和 FA 上下文，不冒称纯 FA 因果实验。
2. 固定已保存 Q0 smoke 文字，仅将 FA 音频换为原 smoke 第二个 30 秒网格，即原 PCM
   `[480000:960000]`、源时间 40–70 s。派生 FLOAT WAV 读回后逐样本相等；
   `.local/analysis/qwen/smoke-grid-second30-manifest.json` 保存来源、文本、WAV/PCM
   哈希与命令。使用 `--alignment-only` 和 `--offset 40`，不重新运行 ASR。
   这是看到长前导假设后的开发诊断；四个词仍保留在固定网格中，不是独立 ASR 评估。

若短 FA 搜索范围有益，后续值得研究较长 ASR 上下文配合独立较短 FA 窗口，但需要
可靠的预测文字分配边界。不能用参考字幕切窗或把参考文字注入正常推理来制造成功。

## 有界探针结果与停止方向

固定 Q0 文字的 FA-only 30 秒 crop 已由主 agent 在 GPU 执行，结果目录
`.local/results/q0-smoke-fa-grid30-fixedtext-r1/`。可测数从 2/4 变为 3/4，仍有一个
非法零时长；三个可测起点相对 SRT 的最大误差仅 0.030 s，但终点最大误差仍达
4.880 s，中位综合 E 为 0.610 s，完整分母中 <500 ms 只有 1/4。删除前导上下文
改善了定位起点，却没有解决所有重复词尾部关联，不能推断已经得到可靠 FA。
这个比较固定文字且未新增 ASR；crop 是开发集观察后的诊断，不能算独立泛化证据。

120 秒臂 chapter-17 出现明确的生成失稳：第三窗源时间 5191.812–5311.812 s
生成 4096 token 达到上限，无 EOS，ASR 用时 176.277 s。raw decode 为 4104 字符，
其中连续三字符模式循环 1358 次，覆盖 4074 字符；官方 repetition 修正将其压成
33 个 parsed 字符，恰好删去 4071 个重复字符。因此 parsed CER 不能单独代表生成
稳定性。raw decoder 没有 control/language marker 字符串，证据指向实际文字循环；
原运行没有保存生成 ID 序列，不能据此声称完成精确逐 ID 的特殊 token 分类。
私有诊断为 `.local/analysis/qwen/ch17-cap-classification.json`，分类由取证派生，
没有回写原结果或伪造上游 finish_reason。

chapter-17 的 120 秒臂共 4389 token、ASR 191.396 s，入口 total 201.440 s；
30 秒臂共 331 token、ASR 16.180 s，入口 total 26.781 s，所有窗均有 EOS 且无
cap 命中。主 harness 全进程时间分别 208.996 / 33.754 s。生成 cap 路径不作为稳定
实施候选；停止 120 秒方向，不继续提高 cap、盲目换窗或更换精度。Q0 30 秒保留为
后续工程比较候选，但其音乐幻觉、删除和 FA 时间失败仍不满足已达标结论。

10 秒数字全零音频 `.local/results/q0-silence-cuda-native-r1/` 的 PCM 已独立验证
最大绝对值为 0。新 ASR 生成 4 token，raw decode 13 字符（含 EOS），parsed 3 字符，
规范化后插入 2 字符；N=0、CER 未定义，不能记成 CER=0。FA 对该假语音文字执行了
一个对齐单元，ASR/FA 参数、输入和输出均为 CUDA，两个阶段都是新推理。
这属于静音幻觉；只测一次 10 秒静音不支持概括实际音乐或所有长静音的事件率。
私有细节在 `.local/analysis/qwen/silence-forensics.json`，这里不公开完整文本。

## Q0 文字与独立 CTC 的缓存组件桥接

为检查 FA 失败是否可由另一家族对齐改善，新增最小
[`export_ctc_input.py`](../../experiments/qwen/export_ctc_input.py)，用法见
[实验 README](../../experiments/qwen/README.md)。桥接仅消费已完成 Q0 结果与同一原
WAV，校验冻结 ASR revision/权重/config 身份、每窗 PCM 与 CUDA 证据、源 offset
和完整文字拼接，并拒绝 generation cap 命中的源。original_segments 保留 ASR 输入
样本窗口，不使用原 FA 或参考 SRT 的边界；它不是已经声学对齐的字幕。

现有 W1 合约将 `pcm_sha256` 定义为 PCM16 序列化 bytes，Q0 为解码 float32 bytes。
桥接明确保存两个哈希及表示，验证 PCM16/32768 与 Q0 float32 逐样本相等；不是
将不同表示的哈希强行设成相同。provenance 保存原 Q0 result、WAV、模型/config、
CUDA、exporter 身份和 `cached_asr_component_comparison`。缓存 ASR 不能当作新 ASR
推理或速度；CTC 阶段还需真实 CUDA 运行和完整评测。

新增 6 项合成离线桥接测试通过，共 11 项离线测试。chapter-01/02/05/07/17 的
Q0 30 秒结果已分别导出 8/3/10/10/14 个原始窗口到 `.local/analysis/qwen/`。
这个跨家族配置占用一个有理由的组件实验分支；导出成功不代表对齐达标，也不能
解决已经在 Q0 文字中产生的漏识别或静音幻觉。

## 三臂开发集的冻结汇总

最终汇总引用评测负责人独立重算的
`.local/analysis/dev-comparison/cpu-v2-r3c/main-report.json`，SHA256 为
`9db8bf7333cd0a9643e4f2b97db87f72f4924059dfc0c0163a1e39258851ba4a`。
五个固定开发章节共有 1902 个规范化参考字符、195 个内容时间参考跨度。下表保留
完整分母及缺失运行；CER 是相对 SRT 的文字差异，不是人工听辨准确率。时间 E 为
同一内容跨度两端误差的最大值，条件分位数只覆盖可测跨度。

| 配置 | S / D / I | CER | 可测 n/N（覆盖率） | 条件 E-P95 / P99 | 完整分母 <500 ms 下界 / 上界 |
| --- | --- | --- | --- | --- | --- |
| native 单窗 | 239 / 424 / 52 | 37.59% | 58/195（29.74%） | 32.772 / 46.290 s | 23.59% / 27.69% |
| 固定 30 秒 | 253 / 69 / 129 | 23.71% | 91/195（46.67%） | 6.668 / 27.682 s | 40.51% / 46.67% |
| 固定 120 秒 | 305 / 42 / 57 | 21.24% | 93/195（47.69%） | 20.410 / 28.022 s | 41.54% / 46.67% |

native 的 chapter-17 因超过 FA 300 秒限制没有执行，缺失运行按完整分母记账，
其中 394 个参考字符计入删除。因此 native 汇总 CER 含一个未执行场景，不能用它
直接估计已运行四章的 ASR 文字质量。30/120 秒五章均有 ASR、FA CUDA 执行证据；
这项执行完整性不抵消 120 秒生成 cap 的稳定性淘汰。

两固定窗共有 74 个同时可测跨度；在相同子集上，30 秒的 E 中位数/P95/P99 为
0.183 / 4.880 / 14.980 s，120 秒为 0.183 / 21.868 / 28.022 s。中位数近似相同而
120 秒尾部明显恶化，覆盖率仅增加 2/195；连同实际循环和耗时证据，没有足够收益
支持继续这个方向。上界包含参考不确定性允许的成功可能性，不能将上界当作已证实
成功数；匹配歧义、非法时间、缺文字或不完整时间保留各自失败分类。

当前选择是保留 Q0 30 秒作为有限工程比较分支，下一步只做已有冻结文字与独立 CTC
的组件探针。它仍有 53.33% 内容时间跨度不可测、插入 129/1902、静音幻觉和严重
时间尾部，尚不能称为字幕时间已达标方案。没有新增验证集、保留集、整片连续性或
重复运行稳定性证据；这些汇总不能替代后续验证。
