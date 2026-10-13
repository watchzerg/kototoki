# Inference Selection Principles

状态：用户优先级及 W0／X0 两条基准线已确认；两条可复用 demo 已建立，正式后端迁移尚未完成
Last updated: 2026-10-05
Scope: engine, model, precision, and forced-alignment selection for local STT.

测试当前W0／X0时，从[标准基线测试指南](../guides/baseline-testing.md)进入对应demo；新模型、精度或组件使用独立配方，已有基线保持可复现。

## Constraints and priorities

- 以用户 RTX 5080 上的原生 Windows 为目标。ASR 和强制对齐必须使用 GPU，不回退 CPU。
  VAD 可使用 CPU 或 GPU，不以 GPU 支持作为资格条件；比较检测质量、稳定性、集成成本和
  实测端到端性能。普通 CPU 音频／文件处理与不依赖 GPU 的单元测试仍然允许。
- Consider GPU implementations beyond a CUDA-only shortlist, including routes
  described by candidates as cuBLAS or Vulkan. Verify the actual acceleration
  stack per engine; these labels are not interchangeable engine identities.
- Prefer mainstream, mature, maintained solutions with reproducible local setup.
- VAD 优先检测并保留说话／对白。检测和保留歌声是次要加分，保留歌声本身不扣分；
  不要求排除歌声，也不因其不是说话而计作假阳性。用户于 2026-10-05 明确此偏好，
  尚未设定新的数值评分权重。
- Default to the latest stable release when evaluating engines, models, aligners,
  and supporting components. Verify upstream release information at selection
  time and record the exact version or checkpoint revision and verification date.
  Preview, beta, nightly, and development builds are not the default. For named
  model variants, evaluate their latest stable artifact without silently replacing
  the requested variant with a different model. If compatibility or validation
  requires an older release, document the reason and evidence. This selection
  baseline does not authorize automatic upgrades of a locked environment.
- For demo evaluation, recheck the latest official documentation and model cards
  at experiment setup, and bind their recommended API, preprocessing and defaults
  to the corresponding implementation/checkpoint revisions. Historical research
  pins are evidence, not reasons to prefer an obsolete interface. If current docs
  describe unreleased behavior, distinguish it from the stable baseline and label
  any necessary development-build experiment separately. Freeze the verified
  versions for a comparison round; upgrades start a separately identified round.
- Within the preferred model families, aim for the largest model the target
  machine can run reliably. Prefer quality over selecting a small model merely
  for speed. Validate actual peak memory and end-to-end behavior rather than
  assuming that fitting weights alone proves usability.
- The user expects the preferred models to fit the 5080. Treat that as an
  expectation to test, not an established benchmark or compatibility result.

## Preferred candidates

W0 的后续实验复用并更新 [可复用 demo](../../experiments/w0_demo/README.md)，按其契约新增 VAD Adapter 或修改相应模块，
保留历史运行并另建新身份；当前实现及回归范围见 [demo 验证](../testing/2026-10-05-w0-demo-validation.md)。

当前经用户确认的基准线为：

- **W0：faster-whisper＋新Pyannote VAD＋MMS日语CTC**，无降噪、无人声分离；必须保留WhisperX切分合并、独立无时间戳解码和特征处理等已核验逻辑的适配。
- **X0：Qwen-ASR＋新Pyannote VAD＋同一MMS日语CTC**，无降噪、无人声分离；吸收Qwen兼容流程，保留原生特征与独立纯文字识别。

新Pyannote明确指已测segmentation-3.0，身份和采纳边界见[ADR-0003](../adr/0003-new-pyannote-baselines.md)。
X0持续迭代复用[X0 demo](../../experiments/x0_demo/README.md)，旧fixed30和无VADcut-merge保留为对照；
当前CLI省略参数的旧默认尚未迁移，新基线必须按指南显式选择新Pyannote输入。
可跨模型的流程设计按模型契约采用，质量提升仍需实测；不将Whisper专属特征和token移入Qwen。
具体组件与新旧ID边界以[当前基准线](../architecture/stt-candidate-pipelines.md)为准。
历史W1仅保留研究及回归身份；旧W0／X0结果不因沿用名称而变成新组合的实测成绩。
下表保留更广泛的探索偏好，不代表其中每种组合都已纳入当前候选或通过实测。

These are user-supplied priorities, not an exhaustive list or an adopted stack.
Model artifacts, engines, quantization formats, and aligners are separate choices;
do not assume every engine supports every listed artifact.

| Dimension | User preference | Required clarification during research |
| --- | --- | --- |
| Engine or integration route | faster-whisper, WhisperX, official Qwen implementation, Crisp | Identify exact upstream project, release, GPU backend, Windows support, and integration boundary. |
| Whisper models | large-v2, large-v3, anime.ja | Resolve exact repository/checkpoint and any conversion provenance; preserve the distinction between base and fine-tuned models. |
| Qwen ASR models | 1.7b-f16, 1.7b-amine-q8_0 | Resolve exact model family, artifact, revision, precision, and compatible engine. |
| Alignment | Qwen ASR + forceAligner | Resolve the intended aligner/model and verify GPU execution, language support, and timing quality separately from ASR. |

Preserve these labels as supplied. In particular, `anime.ja`,
`1.7b-amine-q8_0`, and `forceAligner` are not yet canonical download identifiers.
Do not silently correct spellings or invent model URLs. Record the resolved
identities and evidence during research, asking for clarification if ambiguity
cannot be resolved from the available context.

The 2026-10-04 [Subtitle Edit inventory](../research/2026-10-04-subtitle-edit-model-reuse.md)
resolved the installed Whisper `anime.ja` CT2/GGML artifacts against publisher
hashes and recorded a likely mapping from the original `amine` label to the
installed Qwen `ja-anime` GGUF. Keep the original preference labels and artifact
formats distinct; asset identity verification is not inference qualification.

## Research and demo latitude

Research and demo validation may compare other models, engines, precisions, and
aligners. The preferred list guides investigation; it does not prohibit useful
comparisons.
用户于 2026-10-05 明确：GPU 要求适用于 ASR 和强制对齐；VAD 可使用 CPU 或 GPU。

当前基准线明确排除降噪和人声分离；W0／X0均使用新Pyannote VAD，具体身份以ADR-0003及当前基准线文档为准。
历史实验的宽泛探索授权不能用于静默改变这两条配置。需要研究其他组件时，应另立实验身份，
记录音频变换、阶段输入、时间影响、设备和成本，与未改动基准比较，不自动纳入默认流程。
时间质量仍优先，同时保留识别和覆盖护栏；评分与选择规则应在保留测试前冻结，不按有利结果调整。

Compare recognition quality, omissions/hallucinations, alignment quality where
applicable, stability, memory, latency, and integration effort on representative
inputs. Keep model and aligner residency, batching, and concurrent memory use
visible when assessing the largest viable configuration. Record evidence for
any recommendation that departs from the preferred list.

Follow the [evaluation protocol](../testing/stt-evaluation.md) and
[validation boundaries](../testing/validation.md).

比较优先使用[素材规范](../testing/fatestay-reference.md)指定的 Heaven’s Feel II、III
原版内嵌日文 SRT 作为精确主参考；I 的双语抽取字幕及 Black Panther 的日语配音/字幕
依可信度递减，仅作补充。直接读取已分离日语音频，不重复从视频提取；遵守只读保护、
SHA256 与时间映射规则，主参考和补充结果分别报告。

Record observations in
`docs/research/`; record a final adopted combination and rationale in `docs/adr/`.
An exploratory demo is not a production selection. These priorities do not add
translation to the current milestone.
