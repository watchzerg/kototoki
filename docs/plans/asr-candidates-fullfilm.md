# 第一批 ASR 候选两片整片比较

状态：五路线、十次整片运行、统一评分与独立审计完成  
最后更新：2026-10-05  
范围：用户指定 Cohere Transcribe 2B、Granite Speech 4.1 2B 基础版、Nemotron 3.5 ASR 0.6B，与当前 W0／X0 对照；完整 Heaven’s Feel II／III，不采样。

完成结果见[整片实测报告](../research/2026-10-05-asr-candidates-fullfilm.md)。三候选合并 CER 分别为 22.838%、31.088%、26.791%，均未超过当前 W0／X0；本次不改变已采纳基线。

## 固定范围

沿用[素材规则](../testing/fatestay-reference.md)及既有整片语料登记，II 7028.0426875 秒、III 7325.3333125 秒，共 239.222933 分钟。完整参考为 2064 条、22134 规范化字符。原 FLAC／SRT 只读，复用派生全片 PCM，核验完整身份。

本轮新执行 newPyannote 整片检测，W0／X0 使用既有 canonical ASR 适配器和共享 MMS；新候选使用原生特征与独立纯文字解码，共用本轮整片窗口及同一 MMS。每模型各两片，不对新候选机械运行两份相同流程。无降噪、人声分离、翻译、热词或前文 conditioning。ASR／MMS GPU-only，按阶段驻留，持有共享 GPU 锁。

## 身份与入口

- 对照运行：`.local/fullfilm-comparison/asr-controls-v1/`，只选择 W0／X0 的 `pyannote-current` 路线；原执行器的未选择 cut-merge 槽保持 pending，不冒充已完成。
- 候选运行及最终五路线登记：`.local/fullfilm-comparison/asr-candidates-v1/`。新执行器位于 `experiments/asr_candidates/`，复用整片源窗口、失败记账及 MMS 边界；命令与接跑规则见[实验入口](../../experiments/asr_candidates/README.md)。
- 权重供给与元数据：`.local/asr-candidates-provision/`，推理与联网下载分开。
- Cohere：`CohereLabs/cohere-transcribe-03-2026`，revision `b1eacc2686a3d08ceaae5f24a88b1d519620bc09`。
- Granite 基础版：`ibm-granite/granite-speech-4.1-2b`，revision `de575db64086f84fdc79da4932d1076e965bc546`。
- Nemotron：`nvidia/nemotron-3.5-asr-streaming-0.6b`，revision `ea30d66debe3740a08b573244286791d423d6b3e`。

新候选使用独立环境 `.local/envs/asr-candidates-py312-v1/`：Python 3.12、Transformers 5.18.0、Torch／Torchaudio 2.11.0+cu128。Granite 原生处理器需要 Torchaudio；官方尚无匹配既有 Torch 2.14.1 的 Torchaudio，因此采用可配对版本，不改动正在运行的 W0／X0 环境。模型许可和接口来源见[调研](../research/2026-10-05-asr-model-landscape.md)。Cohere 初始下载资格返回 GatedRepoError；用户处理权限后，本机凭据复查通过。三个官方固定版本现均已完成下载及哈希校验。

## 预先固定的分析规则

普通分段错误后保留证据并继续，不用重试成功结果替换模型失败；模型初始化、设备上下文损坏与工程集成故障单独记录。ASR 触顶不当作完整转写；MMS 失败保留文字及 text_only。完整影片所有参考始终留在分母。

主文字指标为每部片全局精确编辑距离 CER、S／D／I；合并先加计数和分母。时间评价沿用[既有整片分析](../research/2026-10-05-fullfilm-segmentation-comparison.md)的固定 300 秒统计分组，这些分组不是采样或推理切分。报告完整参考半秒确定成功、可测覆盖、严重偏移与条件长尾，以及加载／推理／进程成本。缺少资格的模型显式标记未测，不以空输出 CER 冒充模型成绩。

优先完成接口离线验证及短窗 GPU 资格确认，然后完整执行两片。短窗只验证工程接口，不作为最终质量样本。所有候选先冻结参数，不因质量结果调优；模型自身必须的解码上限按其 token／frame 语义记录，不机械统一数值。

字幕时间为显示参考，非人工声学真值；两片已在既有实验接触，不是独立盲测。未参考输出不自动归类为幻觉。最终结果、失败与独立审计见完成报告，研究不自动更换已采纳基线。
