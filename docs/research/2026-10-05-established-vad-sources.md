# 成熟 VAD 候选的官方来源核查

> 2026-10-05 后续开发入口：将本文候选接入当前 W0 时，在 [W0 demo](../../experiments/w0_demo/README.md) 新增 VAD Adapter，复用其 ASR、MMS 和 runner；按 [契约](../specs/w0-reusable-demo.md) 保留源时间坐标并另建 recipe，不复制一套转写流程。

状态：探索性来源核查完成；未作采用决定，未新增推理实测  
最后更新：2026-10-05  
范围：Silero、Pyannote、FunASR FSMN、NeMo MarbleNet、SpeechBrain；原生 Windows／RTX 5080、日语电影音轨。VAD 可用 CPU 或 GPU，ASR／CTC 继续要求本地 GPU。所有外部链接访问日期均为 **2026-10-05**。

本研究时的 W0 固定 Pyannote 与 WhisperX 行为移植，X0 固定 30 秒且无 VAD；本文来源核查当时不改变这两条基准线，未安装、下载权重或运行模型。2026-10-05 后续用户已采用两条新 Pyannote＋MMS 基线，见[ADR-0003](../adr/0003-new-pyannote-baselines.md)及[选型原则](../development/inference-selection.md)；canonical demo 的执行默认仍待迁移。没有新增降噪、分离或说话人识别，本文不提供质量采用证据。

## 版本、维护者与更新节奏

表中版本是本次核验的最新稳定 **软件发布**，不代表对应模型重新训练。GitHub 的 `published_at` 通过公开 API 核验；发布日期使用 UTC。

| 候选／维护背景 | 已核验的软件发布历史 | 模型更新证据及边界 |
| --- | --- | --- |
| Silero；Silero Team，`snakers4/silero-vad` | [v6.2.3](https://github.com/snakers4/silero-vad/releases/tag/v6.2.3)：2026-09-23；v6.2.2：2026-09-17；v6.2.1：2026-02-24 | 6.2.3 修改可选音频依赖，6.2.2 增加 ONNX sequence 路径；不能称为两次新声学训练。[历史 Wiki](https://github.com/snakers4/silero-vad/wiki/Version-history-and-Available-Models)列 v6.0 为 2025-08-25；v6.2 日期与 release 页面存在差异，应在实验时固定 tag 与资产 hash。 |
| Pyannote；Hervé Bredin 等研究者、CNRS 背景及 pyannoteAI 商业生态 | [CHANGELOG](https://github.com/pyannote/pyannote-audio/blob/main/CHANGELOG.md)：4.0.7：2026-06-30；4.0.5：2026-06-22；4.0.4：2026-02-07 | 4.0.7 增加顺序 batch 等框架能力。[Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) benchmark 标注 2025-09；框架升级不能证明 W0 bundled checkpoint 更新。 |
| FunASR；ModelScope／Alibaba 语音生态，多贡献者 | [releases](https://github.com/modelscope/FunASR/releases)：1.4.16：2026-09-18；1.4.15：2026-09-09；1.4.14：2026-09-03 | [FSMN HF 历史](https://huggingface.co/funasr/fsmn-vad/commits/main)：2024-02-01 初期资产；2026 的近期提交为模型卡修改，未核实新训练。1.4.16 特别修复重复调用的子模型 device 配置。 |
| NeMo；NVIDIA 官方 Speech 团队 | [releases](https://github.com/NVIDIA-NeMo/Speech/releases)：3.0.0：2026-08-07；2.7.3：2026-04-23；2.7.2：2026-03-25 | 3.0 是仓库拆分后的 Speech release。[Frame v2 HF 历史](https://huggingface.co/nvidia/Frame_VAD_Multilingual_MarbleNet_v2.0/commits/main)可见 2025-05-12 `.nemo` 上传；[旧 NGC Segment 资产](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/vad_multilingual_marblenet)为 1.10.0、2023-04-04 更新。 |
| SpeechBrain；Mirco Ravanelli、Titouan Parcollet 等开放研究社区 | [releases](https://github.com/speechbrain/speechbrain/releases)：1.1.1：2026-08-27；1.1.0：2026-03-30；1.0.3：2025-04-07 | [VAD 模型卡](https://huggingface.co/speechbrain/vad-crdnn-libriparty)成绩 release 是 2021-09-09；[模型历史](https://huggingface.co/speechbrain/vad-crdnn-libriparty/commits/main)2024-02-25 更新 README。工具仍更新，选定 CRDNN 权重较老。 |

## 实际能力与许可

| 候选 | 已观察到的模型／接口能力 | 代码与权重许可 | 日语证据 |
| --- | --- | --- | --- |
| Silero v6 系列 | [官方 README](https://github.com/snakers4/silero-vad)：约 2 MB JIT，8／16 kHz，流式有状态；官方称训练涉及 6000+ 语言，GPU／batch 可用。 | 项目和发布模型标为 MIT；无 token、注册要求。 | 广泛多语言训练声明支持探索，但没有核验到日语电影独立分数；6000+ 不等于日语领域通过验证。 |
| WhisperX bundled Pyannote／W0 | [现有本机审计](2026-10-04-whisper-framework-vad-alignment-audit.md)：PyanNet，5 秒、16 kHz mono、多标签非 powerset，SHA256 `0b5b3216d60a2d32fc086b47ea8c67589aaeb26b7e07fcbe620d6d0b83e209ea`。分数、迟滞、min-cut 和 merge 共同决定 ASR 输入。 | [Pyannote 代码 MIT](https://github.com/pyannote/pyannote-audio/blob/main/LICENSE)；bundled 权重来源及再分发许可需单独追溯，不能用其他模型卡代替。 | 项目已有日语本机历史证据；仍有时间与覆盖问题。 |
| `pyannote/segmentation-3.0` | [模型卡](https://huggingface.co/pyannote/segmentation-3.0)：10 秒、16 kHz mono、7 类 powerset；有正式 `VoiceActivityDetection(segmentation=model)` 示例。 | 权重 MIT，获取需要接受 HF 条件和 token。 | 训练列出多个中英及其他数据集；本次未见日语专项 benchmark。与 bundled checkpoint 不同。 |
| `speaker-diarization-community-1` | [模型卡](https://huggingface.co/pyannote/speaker-diarization-community-1)：完整 diarization pipeline，VBx、exclusive diarization、离线使用；不是一个可直接宣称替换 W0 的 binary VAD。 | pipeline CC-BY-4.0；获取需接受 HF 条件。其内部每份权重仍应逐项核验。 | DER 主要回答说话人分配质量，不回答日语对白 VAD 边界。没有将其列为当前纯 VAD 默认。 |
| `funasr/fsmn-vad` | [现行模型卡](https://huggingface.co/funasr/fsmn-vad)：16 kHz、流式／离线、显式 CUDA、毫秒区间；[Model Zoo](https://github.com/modelscope/FunASR/blob/main/model_zoo/modelscope_models.md)列约 0.4M、5000 小时。 | [代码 MIT](https://github.com/modelscope/FunASR/blob/main/LICENSE)，该 HF checkpoint 标 Apache-2.0；不将 FunASR 通用 MODEL_LICENSE 自动套到所有模型。 | 卡标 Chinese／English；其他 FunASR ASR 支持日语不构成 FSMN VAD 的日语验证。 |
| NeMo Frame MarbleNet v2.0 | [NVIDIA 卡](https://huggingface.co/nvidia/Frame_VAD_Multilingual_MarbleNet_v2.0)：91.5K 参数，每 20 ms 输出，16 kHz mono；中英法德俄西六语言。 | [NeMo 代码 Apache-2.0](https://github.com/NVIDIA-NeMo/Speech/blob/main/LICENSE)，Frame 权重 **NVIDIA Open Model License**。 | 六语言不含日语；跨语言 VAD 可研究，日语质量未知。 |
| NeMo 旧 Segment MarbleNet | [NGC 卡](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/vad_multilingual_marblenet)：`EncDecClassificationModel`，80-bin log-mel，滑动段分类后输出帧预测；与新 Frame model 独立。 | 该 NGC 页写 NGC Terms of Use，不能从 Frame v2 许可推导旧权重许可。 | 训练列中英等六语言，无日语专项验证。 |
| SpeechBrain CRDNN | [卡](https://huggingface.co/speechbrain/vad-crdnn-libriparty)：16 kHz mono；frame posterior、阈值、merge、短段去除，可选 energy VAD／double-check，显式 `run_opts={"device":"cuda"}`。 | [代码 Apache-2.0](https://github.com/speechbrain/speechbrain/blob/develop/LICENSE)；本次卡和文件树未见明确独立权重 license，不将代码许可直接视为权重授权。 | English 标签；增强用 CommonLanguage 不等于发布日语效果声明。 |

## 基准证据如何使用

- [Silero 官方 quality Wiki](https://github.com/snakers4/silero-vad/wiki/Quality-Metrics)于 2026-03-26 编辑，17 小时 Multi-Domain 验证集，约 31.25 ms 帧评价；Silero v6 ROC-AUC 0.97，MSDWild 0.79。它是维护者自测，含私有集，没有电影日语字幕边界指标。
- [Frame MarbleNet 卡](https://huggingface.co/nvidia/Frame_VAD_Multilingual_MarbleNet_v2.0)给 AVA-SPEECH AUC 95.26、VoxConverse-test 96.65；[旧 Segment NGC 卡](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/vad_multilingual_marblenet)给 AVA ALL AUC 0.9112。这些是不同身份，不能统一称为“NeMo VAD 分数”。
- [SpeechBrain 卡](https://huggingface.co/speechbrain/vad-crdnn-libriparty)给 LibriParty precision 0.9518、recall 0.9437、F-score 0.9477、1×V100；发布者明确不保证其他数据集效果。
- [Community-1 卡](https://huggingface.co/pyannote/speaker-diarization-community-1)给无 collar、包含重叠的 DER，不能把它与 VAD AUC、F1 或本项目的字幕时间成功率做总榜。FSMN 当前卡未提供可复算的日语／跨候选统一分数，本次不虚构数值。

## GPU、Windows 与研究优先级

**观察：**Silero [v6.2.3 loader](https://github.com/snakers4/silero-vad/blob/v6.2.3/src/silero_vad/model.py)仍强制普通 ONNX CPU，JIT 默认 CPU。用户已明确 VAD 无 GPU 强制要求，因此官方 CPU 路径可以直接纳入研究。若比较 CUDA JIT 或自建 ORT provider，须记录状态、model/input device 与实际 provider，不将 CPU 执行误报为 GPU 性能。

**观察：**Pyannote 本项目已经使用原生 Windows CUDA 路径，可复用已证实的运行边界；Community-1 官方默认 CPU，需 `.to(cuda)`，且新版本有 telemetry 能力，离线实验应显式控制。[FunASR 1.4.16](https://github.com/modelscope/FunASR/releases/tag/v1.4.16)有 device 配置修复但 release 明说 stand-in 测试不是 CUDA 认证；其 Windows Vulkan／Blackwell ASR runtime 资产不能当作 FSMN 的 GPU 认证。

**观察：**Frame MarbleNet 卡列 **Blackwell**，但支持系统只列 **Linux**、运行栈 NeMo 2.3.0；测试硬件写 RTX 5000，不是 RTX 5080。官方 ONNX 示例使用 CPUExecutionProvider，Windows CUDA 导出部署是待验证适配路线。[SpeechBrain 安装文档](https://speechbrain.readthedocs.io/en/latest/installation.html)正式列 Linux／macOS、Windows 指向 issue；1.1.1 修复一个 Windows import 问题，仍不能证明整条 VAD 在 5080 通过。

**建议／推断：**保持 W0 原 checkpoint 作为回归锚点；先以 Silero v6 为轻量替代对照，CPU／GPU 均可，再考虑 Pyannote segmentation-3.0、FSMN。NeMo Frame v2 值得覆盖更宽的声学路线，但原生 Windows 适配和日语缺口降低其立即试验优先级；SpeechBrain 适合作为可训练、可解释的研究对照，旧权重、Windows 和许可待核验增加成本。此排序仅来自工程契合度，不是质量排名；更大模型不自动提供更好的 VAD 边界。

后续实验须分别固定原始分数与后处理：一组保持统一 padding／merge 等切分策略，各模型在开发集独立校准并冻结阈值，或比较匹配 recall 的工作点；另一组保留各发布者原生流程比较完整效果。不同模型概率未校准，固定相同数值阈值可能造成偏差。记录弱语音漏检、非语音误报、句首尾截断、帧偏移、ASR 漏字、完整分母时间成功和端到端耗时。公开数据分数无法替代两片日语主参考的本机比较。
