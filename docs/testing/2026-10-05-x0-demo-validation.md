# X0 可复用 demo 验证

状态：fixed30／cut-merge 两窗四次 GPU 验证通过；当前 newPyannote 证据另见整片报告  
最后更新：2026-10-05  
范围：原生Windows／RTX 5080、既有本地模型与环境；验证可复用入口，不重新选模型或宣称普遍质量提升。

当前 X0 已按[ADR-0003](../adr/0003-new-pyannote-baselines.md)采纳 Qwen＋newPyannote＋MMS，
无降噪、无人声分离。当前执行须显式 `--segmentation vad --vad-manifest`，recipe
`x0-demo-vad-source-windows-v1` 连同 `vad_id=pyannote-current` 与外部模型身份确定基线。
本次仅更新文档；代码无参数默认仍是 fixed30。下文四次运行、测试数量和逐项相等结论保留早期冻结身份，
不能改写为已验证 newPyannote。最新两部整片与 canonical 同窗证据见
[整片报告](../research/2026-10-05-fullfilm-segmentation-comparison.md)：X0 newPyannote 无触顶、一次极短窗 MMS 失败；
本轮采用依据是稳定性与成本，配对剔除后不支持总体文字或时间优势，且没有测整片 fixed30。

## 实现与身份

入口为[X0 demo](../../experiments/x0_demo/README.md)，接口见[契约](../specs/x0-reusable-demo.md)，
采用理由见[ADR-0002](../adr/0002-x0-demo-flow.md)。

- 本页早期／代码无参数默认 `x0-demo-fixed30-v1`：无降噪、无人声分离、无VAD，固定30秒、完整尾段。
- `x0-demo-cut-merge-v1`：每个5秒区域选择低能量候选切点，再按源跨度合并到最多30秒；所有样本保留。
- Qwen3-ASR-1.7B：native Transformers、日语、CUDA BF16、SDPA、greedy、batch1、最多4096生成token。每块独立，不传前文，使用Qwen自己的processor。
- MMS：直接共用W0 `MmsAligner`，日语jpn、2268词表、blank0、CUDA FP32、TorchAudio标准CTC；前向cuDNN TF32开、matmul TF32关，退出恢复调用者状态。
- X0通过成对整数样本坐标传窗；W0旧秒坐标调用保持原路径。没有复制第二套MMS，也没有导入WhisperX或VAD进行推理。
- 既有Qwen环境为Python3.13.16／Torch2.14.1+cu130／Transformers5.18.0；MMS环境为Python3.13.16／Torch及TorchAudio2.8.0+cu128／Transformers4.57.6。根编排环境Python3.12.15。
- RTX 5080、16303MiB、驱动616.92；不安装、升级或下载。

## 离线与接口验证

`just test`的12组测试共274项，全部成功退出，31项可选依赖测试显式跳过。
随后修复取消时的成本记账，X0最终14项在根环境12通过／2跳过，在已有后端环境14项全部通过。
共享MMS改动后的W0后端离线套件41项全部通过；`just check`编译检查通过。
根环境缺NumPy／Torch的跳过不是数值验证，相关新增边界由后端环境补测。

测试覆盖完整样本分区、30秒上限、真实相邻段合并、静音与连续音、任意尾长、非法窗口、
全文及每字符一次映射、OOV／text_only、源偏移、token触顶、失败保留、拒绝覆盖、取消后的子进程成本与清理。
共享MMS测试明确检查1001样本及非零起点：整数路径保持全部样本，原秒坐标路径仍保持旧行为。
取消测试使用假子进程；不等于真实GPU驱动卡死或Windows强制终止已验证。

独立代码审查发现取消时漏记当前子进程成本，已修复并新增回归测试；未发现其他明确的数据丢失问题。
`just --list`及`just x0-demo --help`已通过。当前shell未暴露裸`just`时使用既有
`.local/tools/just/just.exe`，uv缓存和Python路径指向项目`.local/`，没有修改系统配置。

## 本机推理

输入为既有Heaven’s Feel II／III各window-01：每段300秒、4800000样本、mono16kPCM16，
源偏移分别351.402125和366.2666875。输入与参照沿用此前冻结的
`.local/x0-flow/pilot-v1/study.json`，不是新独立保留集。

本轮新产物位于`.local/x0-demo/verified-v1-{clip-id}-{fixed30,cut-merge}/`。
每次重新运行Qwen与MMS；保存源码快照、输入与模型hash、实际设备、native输入形状、token、
MMS归一化及CTC证据、各子进程墙钟与全部文字。私有音频和全文不写入本文。

四次运行均成功，结果如下。耗时是包含解释器启动、模型加载和身份核验的父流程墙钟；
每次3个子进程，规划／ASR／MMS的完整进程时间也分别保存。

| 输入 | 配方 | 窗口数 | 全文字符 | text_only字符 | 端到端秒 |
| --- | --- | ---: | ---: | ---: | ---: |
| II window-01 | fixed30 | 10 | 598 | 53 | 94.476 |
| II window-01 | cut-merge | 12 | 584 | 44 | 94.007 |
| III window-01 | fixed30 | 10 | 706 | 53 | 95.131 |
| III window-01 | cut-merge | 11 | 709 | 53 | 95.190 |

独立核验脚本和结果为`.local/x0-demo/verify_demo.py`、`.local/x0-demo/verification-v1.json`。
脚本不导入demo实现来重算窗口，以原PCM和保存记录独立核对：

- 四次各4800000样本构成完整连续分区，无删除、重复或重排，每窗不超过480000样本；cut-merge保存实际合并成员。
- 全部43个ASR窗口及43个MMS窗口都有实际CUDA证据；ASR原float32 PCM hash与MMS裁剪、归一化有效样本数及补齐前内容一致。
- 四次无token触顶、无对齐失败；每个原文字字符恰好记账一次，未获词汇时间的内容完整保留为text_only。
- 两次fixed30与历史同窗全文、生成token、识别分段、全部1304个字符units完全相同；MMS归一化、emission、CTC path和token概率也一致，仅新增整数字段及运行身份。
- 四次源码快照均与当前21个Python源文件一致；共用同一MMS模型文件身份与数值策略。
- 原始FLAC／SRT、派生WAV／参考与前轮冻结hash一致，审查前后未变化。未改写历史运行。

字符数或text_only数量的变化不等于漏字减少或时间更准，本轮没有对新cut-merge重新计算CER或人工听辨。
固定顺序、每种一次，约94～95秒的观察不证明稳定提速。源码以后变化时，保留本次源码快照并另建验证身份。

## 结论边界

cut-merge是当前demo正式支持的流程配方，采用不以这两窗评分取胜为前提。
它与历史`x0_flow`的“每个30秒上限前5秒找切点”算法不同，不能继承历史energy的分数。
本轮验证实现、契约与本机兼容性；不证明切点必然位于句末、转写更准、字幕声学边界更准或稳定提速。
MMS的CTC nonblank跨度不是声学真实字长。任意奇数尾段由合成／假模型接口测试覆盖，真实GPU样本均为300秒整窗。
整片、其他作品／语言、批处理、其他GPU及macOS未在本页早期两窗验收；后续整片证据由上方独立报告维护。
整片 worker 失败后继续的行为只属于该实验，不能从本次采纳推断 canonical demo 的生成触顶退出策略已改变。
