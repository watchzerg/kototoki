# FireRedVAD、OmniVAD-Kit 与 TEN VAD 来源核验

> 2026-10-05 后续开发入口：将 FireRed／OmniVAD／TEN 接入当前 W0 时，在 [W0 demo](../../experiments/w0_demo/README.md) 新增 VAD Adapter，复用已验证的 ASR／MMS／runner，并单独冻结检测与后处理身份；来源调查本身不证明替换效果。

状态：exploratory；仅来源调查，未采用、未安装、未运行模型  
最后更新：2026-10-05  
范围：原生 Windows／RTX 5080 的本地日语电影转录；VAD 可使用 CPU 或 GPU，ASR／CTC 继续使用 GPU。本文核查时不修改 W0 的 Pyannote 或 X0 的无 VAD、固定 30 秒契约。所有外部来源访问日期均为 2026-10-05。

2026-10-05 后续用户已采用两条新 Pyannote＋MMS 基线，见[ADR-0003](../adr/0003-new-pyannote-baselines.md)及[推理选择原则](../development/inference-selection.md)。canonical demo 的执行默认仍待迁移；本文 FireRed／OmniVAD／TEN 来源调查保留历史范围，不构成其他 VAD 的采用决定。

## 身份与维护

| 项目 | 实际背景 | 版本与可见维护证据 |
| --- | --- | --- |
| FireRedVAD | 官方 FireRedTeam，自述为小红书 Super Intelligence 基础算法实验室；发布者列出 Kaituo Xu、Wenpeng Li、Kai Huang、Kun Liu。[团队](https://github.com/FireRedTeam)、[包元数据](https://pypi.org/project/fireredvad/) | PyPI 最新普通版本 `0.0.2`，2026-03-09；但开发状态明确为 **Beta**，不能据版本号称成熟稳定。GitHub 无 Releases；`main` 最新提交 `c30ec49` 为 2026-05-06 的 README 更新。[PyPI API](https://pypi.org/pypi/fireredvad/json)、[提交](https://github.com/FireRedTeam/FireRedVAD/commit/c30ec49e8cc69642b0ee65362eba11b9d11c6e54)、[Releases](https://github.com/FireRedTeam/FireRedVAD/releases) |
| OmniVAD-Kit | `lifeiteng`／FeiTeng Li 的社区部署工具；个人主页自述 Full stack Algorithm Engineer、Singapore。复用 FireRedVAD 模型，不能作为另一种独立声学模型重复计数。[个人主页](https://github.com/lifeiteng)、[README](https://github.com/lifeiteng/OmniVAD-Kit) | PyPI `omnivad 0.2.13`，2026-06-30，同样标记 **Beta**；GitHub 无 Releases。`main` `3ef93e1`，2026-09-23，增加共享权重但独立配置的 stream clone；比发布包更新，不能将其全部特性自动归给 `0.2.13`。[PyPI API](https://pypi.org/pypi/omnivad/json)、[提交](https://github.com/lifeiteng/OmniVAD-Kit/commit/3ef93e1c288096225f90c57e3a3fb80d790adc5e)、[Releases](https://github.com/lifeiteng/OmniVAD-Kit/releases) |
| TEN VAD | TEN Team／TEN-framework 发布；源码与许可版权为 Agora，适合描述为 TEN／Agora 背景，而不是独立无企业背景的个人项目。[版权和许可](https://github.com/TEN-framework/ten-vad/blob/main/LICENSE) | 非 prerelease GitHub Releases `v1.0`、`v1.0-ONNX` 均为 2025-07-11；GitHub 将后者标为 Latest。`main` `22a3bcd`，2026-02-02，消息为 `fix bug`。README 另有 2025-11 的 ONNX／Java／Go／WASM 更新。[Releases](https://github.com/TEN-framework/ten-vad/releases)、[提交](https://github.com/TEN-framework/ten-vad/commit/22a3bcd4509d0faaa8eef4881e8af5f39c178950)、[README](https://github.com/TEN-framework/ten-vad) |

以上日期由公开 GitHub REST API 的 `commits?per_page=1`／`releases` 和 PyPI JSON 复核。提交日、包上传日、权重更新日是不同证据；未见最新声学训练变更，不等于无人维护，也不等于近期有新模型。

## 架构与电影任务含义

**FireRedVAD** 提供离线 VAD、因果 Stream-VAD 与三标签 AED。论文 §4 描述 8 个 DFSMN block，约 0.6M 参数／2.2 MB；离线路径使用未来上下文，流式路径保留历史 cache。重要的是其二分类 **voice 正类包含 speech 和 singing**，负类包含 music、silence、noise；AED 则分别输出 speech／singing／music，可以重叠。论文称使用数千小时人工声学事件标注，但未给出足以复现训练的数据清单。[技术报告 §4](https://arxiv.org/html/2603.10420v1#S4)

默认二分类 VAD 保留歌唱，符合用户本轮明确偏好：重点检测对白，歌唱检测是次要加分，保留歌声本身不扣分。因此无须仅为排除歌曲另加 AED。AED 可用于分析 speech／singing／music 的重叠，但事件检测不分离音源，也不意味着可恢复被配乐淹没的对白。此处为任务映射判断，不是日语电影质量实证。

**OmniVAD-Kit** 将 FireRed 转为 ncnn／C API，提供 Python、TypeScript／WASM、Rust 绑定、后处理与 `merge_chunks`。模型随 wheel／仓库 bundle 提供。它属于部署和切分层；上游 DFSMN 的语言、训练和质量证据不会因移植而增加。README 的 WhisperX 等价说法只覆盖其指定切分配方，不能替代 Kototoki 已核验的 Pyannote 分数、独立解码与特征契约，也不能证明与现有 W0 等价。[上游归属及接口](https://github.com/lifeiteng/OmniVAD-Kit)、[切分实现](https://github.com/lifeiteng/OmniVAD-Kit/blob/3ef93e1c288096225f90c57e3a3fb80d790adc5e/native/src/chunking.cpp)

**TEN VAD** 是流式帧级神经 VAD，和经典 WebRTC 统计检测器（GMM）不同。公开头文件／实现显示 16 kHz、40 个 Mel 特征加 pitch 特征，3 帧上下文、4 个 64 维状态输入／输出，ONNX Runtime 执行；完整训练架构和训练语种比例未核实，不依据状态形状武断称为某种 LSTM 层数。[结构常量](https://github.com/TEN-framework/ten-vad/blob/22a3bcd4509d0faaa8eef4881e8af5f39c178950/src/aed_st.h)、[特征和推理代码](https://github.com/TEN-framework/ten-vad/blob/22a3bcd4509d0faaa8eef4881e8af5f39c178950/src/aed.cc)

## 日语与基准证据边界

- FireRed 自报 FLEURS-VAD-102：9,443 条、102 语言、帧级 10 ms，神经模型统一阈值 0.5；F1 为 FireRed 97.57、Silero 95.95、TEN 95.19、FunASR 90.91。统一阈值不是各模型各域的最佳工作点；论文与 README 仍称标注集待公开。未报告日语独立 F1、电影对白边界／漏字或 MMS 时间收益。[论文 §7.2](https://arxiv.org/html/2603.10420v1#S7.SS2)
- FLEURS 官方数据确实包含 Japanese，但这只能支持多语覆盖，不能从平均分恢复日语成绩；原数据是平行句子的录音，不能代表电影强配乐、耳语、爆破、喊叫与重叠对白。[Google 数据卡](https://huggingface.co/datasets/google/fleurs#fleurs)
- Silero 团队 2026-03-26 的另一套 17 小时 Multi-Domain Validation 上，ROC-AUC 为 Silero v6 0.97、FireRed 离线 0.94、FireRed 流式／TEN 0.93；帧粒度为 31.25 ms，语料含会议、通话和噪声。排名方向不同，说明必须保留评测作者、数据和版本身份；两表不是统一榜单。[Silero Quality Metrics](https://github.com/snakers4/silero-vad/wiki/Quality-Metrics)
- TEN 提供来自 LibriSpeech、GigaSpeech、DNS Challenge 等的人工标注测试集及 PR 绘图工具，比仅有总分更利于复现；公开 README 没有日语电影的专门结果。低延迟和 CPU RTF 是其自报主要卖点，不能换算成本机 GPU 或完整 STT 性能。[TEN Evaluation](https://github.com/TEN-framework/ten-vad#1-high-performance)

## 原生 Windows、GPU 与离线可行性

| 路线 | 官方证据 | 对本项目的判断 |
| --- | --- | --- |
| FireRed 官方 PyTorch | README 明列 Windows／Linux NVIDIA 安装路径；`FireRedVadConfig(use_gpu=True)` 会把模型与特征移至 `.cuda()`。默认值为 False；`gpu` extra 仅声明 `torch>=2.0.0`，没有锁定 Blackwell 兼容构建。[README](https://github.com/FireRedTeam/FireRedVAD#setup)、[vad.py](https://github.com/FireRedTeam/FireRedVAD/blob/c30ec49e8cc69642b0ee65362eba11b9d11c6e54/fireredvad/vad.py)、[依赖](https://github.com/FireRedTeam/FireRedVAD/blob/c30ec49e8cc69642b0ee65362eba11b9d11c6e54/pyproject.toml) | 三者中最直接满足 GPU 神经推理的探索入口。资产本地路径加载、特征与后处理在 CPU、网络前向在 GPU，符合项目允许普通 CPU 音频处理的边界。未见 RTX 5080 官方实测保证；需适配 CUDA／Torch 和 kaldi-native-fbank Windows 环境，本轮未验证。 |
| OmniVAD 当前 ncnn | Windows x86-64 wheel 存在；但当前 `omnivad.cpp` 明确 `use_vulkan_compute=false`，说明为并发状态安全关闭 Vulkan。绑定无已核实 GPU 选择入口。[PyPI 文件](https://pypi.org/project/omnivad/#files)、[固定提交源码](https://github.com/lifeiteng/OmniVAD-Kit/blob/3ef93e1c288096225f90c57e3a3fb80d790adc5e/native/src/omnivad.cpp) | 原生 Windows／离线易分发，CPU 路线符合当前 VAD 选型要求；无需仅为获得 GPU 标签自行开启 Vulkan。仍应验证实际包版本、状态与切分契约。 |
| TEN 官方 DLL／ONNX 示例 | 预编译 DLL 支持 Windows；ONNX 示例文档验证 Linux／macOS。公开 `aed.cc` 直接创建 ORT session，没有注册 CUDA 或其他 GPU provider。[ONNX 示例说明](https://github.com/TEN-framework/ten-vad/tree/main/examples_onnx/python)、[session 源码](https://github.com/TEN-framework/ten-vad/blob/22a3bcd4509d0faaa8eef4881e8af5f39c178950/src/aed.cc) | 官方 Windows CPU 路线可直接列为候选，无需另建 GPU 适配；需验证状态／特征契约和实际端到端开销。若宣称 GPU 性能，仍须另有实际 provider 证据。 |

三者均可作为本地资产推理方案，不需要外部推理服务。FireRed 模型获取与推理分离；Omni bundle 和 TEN DLL／ONNX 获取完成后可离线加载。本文未下载权重、未证明离线实际推理成功。

## 许可与可复现身份

- FireRed **代码**根 LICENSE 为 Apache-2.0；**官方权重** Hugging Face 模型卡独立标 Apache-2.0。核验的权重 repo revision 为 `7990aaccc6b7aec1e527743bd30201f2c4a03b8c`，最后修改 2026-03-13。[代码 LICENSE](https://github.com/FireRedTeam/FireRedVAD/blob/c30ec49e8cc69642b0ee65362eba11b9d11c6e54/LICENSE)、[模型卡](https://huggingface.co/FireRedTeam/FireRedVAD)、[模型 API](https://huggingface.co/api/models/FireRedTeam/FireRedVAD)
- OmniVAD **代码**标 Apache-2.0，并明确归属上游 FireRed；模型 bundle 是上游权重的转换部署资产，本轮未逐个核对其转换 SHA／上游 checkpoint 对应关系。若试验，必须同时冻结 `.omnivad` bundle 与 wrapper，不能仅记录 PyPI 版本。[LICENSE](https://github.com/lifeiteng/OmniVAD-Kit/blob/main/LICENSE)、[归属与 bundle](https://github.com/lifeiteng/OmniVAD-Kit#model-files)
- TEN 使用 **Apache-2.0 加附加条件**，包括不得以竞争 Agora offerings 的方式部署、限定给自己的应用及直接终端用户、衍生作品继续受该许可约束；不能缩写为普通 Apache-2.0。另有 LPCNet 衍生代码 BSD notices。未找到给权重另发且更宽松的许可证，不假定 ONNX 导出脱离项目条款。[TEN LICENSE](https://github.com/TEN-framework/ten-vad/blob/22a3bcd4509d0faaa8eef4881e8af5f39c178950/LICENSE)、[NOTICES](https://github.com/TEN-framework/ten-vad/blob/main/NOTICES)

## 探索优先级

根据本项目约束的推断：优先研究 **FireRed 离线 VAD／AED**，理由是事件监督与歌唱／配乐标签；其 Beta 状态、日语电影证据缺口仍需保留。用户已明确 VAD 不要求 GPU，OmniVAD 当前 CPU ncnn 路线因此可以作为 FireRed 的实用部署候选，需要验证转换模型和后处理是否符合目标契约。TEN 也可直接研究 CPU 路线，附加许可及日语电影证据仍影响采用判断。CPU／GPU 由质量、稳定性、集成成本和实测端到端性能决定，不是资格筛选条件。

若另立实验，应只替换 W0 的 VAD 并保持已移植的解码／特征、MMS 与原音频；AED 必须明确目标标签。原始帧分数、后处理阈值、切分合并策略各自冻结，分别量测漏对白、边界截断、无歌声的纯配乐误报、次要的歌声召回、最终 CER 与时间全分母成功率。歌声保留不算 VAD 假阳性。X0 加 VAD 会改变已接受配置，必须有新身份。此为试验建议，未形成采用决定。
