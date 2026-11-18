# STT demo 与 W0／X0 基线：多路线实测、评测方法与两条基线的建立

## 状态
concluded：首轮多框架实测、两片复核、框架等价实验与两套可复用 demo 的验证均已完成；没有任何配置达到严格字幕时间目标，但两条基线已由 ADR 采纳。

## 时间
2026-10-03（立项）至 2026-10-05（demo 验证与整片对照后用户采纳基线）。

## 问题
在原生 Windows＋RTX 5080 上，哪些"ASR＋（VAD）＋强制对齐"组合适合做日语电影字幕的本地转写，时间位置能否达到字幕可用的精度；WhisperX 的有效逻辑能否由自有适配层承接；两条实施基线（W0、X0）应如何定义并保证可复现。

## 策略
- 四个框架的本机完整流程：faster-whisper（W0）、WhisperX（W1，含独立 CTC 对齐）、官方 Qwen3-ASR＋ForcedAligner（Q0）、CrispASR Qwen＋FA（Q1）；再加跨家族组合 X0（Qwen 文字＋标准 CTC）。
- 开发章内受控消融（W0 关闭前文 conditioning、WhisperX 归一化与标准 CTC、Qwen 窗口长度、Crisp 关闭 VAD 等），再用冻结规则晋级到验证、保留集，随后做整片与两片（Heaven's Feel II／III）固定样本复核。
- 框架等价实验：冻结同一份 Pyannote 分数与音频分块，比较原生 WhisperX、独立 faster-whisper 适配层、未修改 `transcribe()`、`BatchedInferencePipeline`。
- 把 W0／X0 做成可复用 demo（入口、契约、验证记录），形成两条基线；之后 ADR-0003 将 VAD 更新为新 Pyannote。

## 环境与版本
- GPU RTX 5080（16303 MiB），驱动 616.92，Windows 11；ASR／对齐全部 GPU，仅 Crisp 原生 Silero VAD 为披露过的 CPU 预处理。
- W0：faster-whisper 1.2.1、CTranslate2 4.8.2、large-v3（Systran 转换，revision edaa852e），CUDA FP16、beam 5、日语 transcribe。
- W1／WhisperX：WhisperX 3.8.6、Torch／TorchAudio 2.8.0+cu128、Transformers 4.57.6、pyannote.audio 4.0.7；CTC 用 jonatasgrosman/wav2vec2-large-xlsr-53-japanese（cf031e02），后期换 facebook/mms-1b-all＋`jpn` adapter（3d33597e）。
- Q0／X0：Qwen3-ASR-1.7B-hf（bcd2b5b7）＋ForcedAligner-0.6B-hf（c07281df），Transformers 5.18.0、Torch 2.14.1+cu130，BF16。
- Q1：CrispASR 0.8.41（Windows Vulkan），Qwen3-ASR／ForcedAligner f16 GGUF。
- 新 Pyannote（ADR-0003）：pyannote.audio 4.0.7＋pyannote/segmentation-3.0（e66f3d3b），整片证据为 CUDA FP32。

当前 W0／X0 组件（取自 ADR-0001／0003，历史上先后有旧 PyanNet、fixed30 等身份）：

| 组件 | W0 | X0 |
| --- | --- | --- |
| ASR | faster-whisper large-v3，逐块独立、无前文、无时间戳 token | Qwen3-ASR-1.7B，逐块独立纯文字、无前文 |
| 降噪／人声分离 | 无 | 无 |
| VAD／分段 | 新 Pyannote，源跨度合并至 ≤30 秒，块内间隙保留 | 同一窗口契约 |
| 特征 | 移植的 Whisper 波形补齐、Torch STFT／log-Mel 数值契约 | Qwen 原生 processor，不照搬 Whisper 固定 Mel 或补齐 |
| 对齐 | MMS-1b-all `jpn`，CUDA FP32，标准 CTC | 同一 MMS 实现 |
| 配方身份 | `w0-pyannote-current-mms-v1` | `x0-demo-vad-source-windows-v1`＋`vad_id=pyannote-current` |

W0 承接 WhisperX 的切分合并、独立无时间戳解码与特征处理，作为基线组成而非可选优化；X0 不使用 Qwen ForcedAligner，也不迁入 Whisper token、固定 Mel 或 CT2 参数。旧 fixed30 与无 VAD `cut-merge` 仅作历史／对照。demo 入口、窗口契约与结果字段由两套 demo 的契约规定（现已随产品实现 `kototoki/` 取代）。

## 测试
- 语料：Fate/stay night 剧场版系列日语电影的外置音频与日文 SRT。第一轮为单片（Heaven's Feel 之一）按容器章节冻结开发／验证／保留划分（开发 5 章 N=195、验证 3 章 N=151、保留 16 章 N=620、整片 N=1026，章节两端各留 10 秒隔离）；之后改为 II、III 为主参考、I 与另一部电影仅作补充。两片复核从每片 5%…80% 处各取 300 秒共 12 窗（3600 秒、590 条参考、6544 字符）；后期整片 239 分钟、2064 条参考。参考是原 SRT 显示边界，不是人工声学真值。
- 文字指标：连续全文 NFKC＋去标点字符 CER（S／D／I），与字幕行拆合无关，失败与未决留在完整分母。时间指标：对同内容跨度取 E=max(|Δ起|,|Δ终|)，报告完整分母的确定成功数（E<0.5 s、<2 s、<5 s）、可测覆盖、条件 P95／P99；严格目标是 P95<0.5 s、P99<2 s，联合要求至少 ⌈0.95N⌉／⌈0.99N⌉ 条确定成功。
- 晋级规则（冻结于验证前）：每路线最多 12 个开发配置；Pareto 轴为 CER、D／Nchar、I／Nchar、首尾完整覆盖、可测覆盖、成功下界；每路线至多一个"时间角色"和一个"内容保全角色"进入验证。保留集不用于调参。
- 评测器：离线 `archive/2026-11-18-pre-research-restructure:kototoki_eval` 校验转写 JSON 并计分；显示层用冻结的最小 writer（间隙 0.4 s、单 cue ≤7 s、≤42 字符、不修补时间）重放，只记账 cue 数、短／长 cue、渲染覆盖率。数字静音 10 秒输入作幻听预检。
- demo 与评估器各模块做了什么（研究代码，现已删除）：
  - 外部 VAD 阶段：在隔离环境运行一个 VAD 候选，把原生语音区间整理成 ≤30 秒的源窗口（`source-span-merge-v1`：超过 480000 样本的区间硬切，再按源跨度贪心合并，不加 padding），写出带输入身份与成本的 manifest。
  - W0 pipeline：回放 VAD 窗口，逐窗独立无时间戳解码，再调共享 MMS 对齐，写私有结果与全文；单个 MMS 窗口失败时文字保留为 `text_only`，不回退 CPU。
  - X0 pipeline：父进程依次启动 plan、ASR、对齐三个子进程，只导入外部 VAD manifest，不复制 MMS；支持 fixed30、cut-merge、vad 三种分段配方。
  - MMS 对齐：W0／X0 共用，`jpn` adapter、CUDA FP32、TorchAudio 2.8 标准 `forced_align`，字符级时间映射回覆盖全文的 units，词表外字符用通配符参与对齐。
  - 评分与显示重放：校验转写 JSON、以完整分母计 CER 与参考跨度时间，并用冻结 writer 重放为 SRT 与 sidecar；与推理后端无关。
  - 语料与资产准备：冻结章节划分与样本精确的 16 kHz mono PCM16 输入、生成参考 JSON、按固定 revision 获取模型并记录校验清单。
- 性能：同一进程协议下三次短片重复＋一次整片，RTF 取外层墙钟除以音频时长，显存为整卡采样。

## 结果
保留集（N=620，参考 6654 字符）与两片、整片的关键数字：

| 配置 | 范围 | CER | 确定 E<0.5 s | 备注 |
| --- | --- | ---: | ---: | --- |
| W0 无前文 | 保留 | 20.35% | 42.10% | 删除 249／插入 539；可测 62.9% |
| W1 归一化标准 CTC | 保留 | 17.43% | 53.06% | 删除 442／插入 235；条件 P99 10.3 s |
| Q0 官方 Qwen＋FA（30 秒窗） | 保留 | 17.31% | 38.55% | 可测仅 43.4% |
| Q1 Crisp＋FA（无 VAD） | 保留 | 18.05% | 14.03% | 可测仅 16.8% |
| X0 Qwen＋归一化标准 CTC | 保留 | 17.31% | 46.45% | 条件 P99 15.9 s |
| W0／W1 | 两片 12 窗（590 条） | 16.41%／14.98% | 40.85%／54.24% | X0 51.53%，与 W1 区间重叠 |
| W0／W1 | 整片 N=1026 | 20.02%／19.99% | 420／504 条 | 完整分母联合 P95／P99 均为无穷 |

- 性能：W0 整片（7028 s）墙钟 330 s（RTF 0.047），W1 196 s（RTF 0.028）；短片三次输出逐字相同；整卡显存采样峰值约 7–8 GiB。
- 数字静音：W0 无 VAD 产生 14 个字符，Q0 产生 2 个，W1／Crisp 原生 VAD 为空；幻听不能靠关闭前文解决。
- 框架等价：独立 faster-whisper 适配层在两窗 17 块上与原生 WhisperX 的特征、prompt、生成参数、token、文字、分段、平均 logprob 全部严格相等；换成未修改的 `transcribe()` 或 batched 管线则不等价。
- 显示重放：整片固定 writer 下 W0 1056 条（77 条 <0.5 s、14 条 >7 s），W1 1600 条（705 条 <0.5 s）；SRT 覆盖生成文字的约 98%。
- 旧 PyanNet demo 两窗回归：17 块、1226 字符（1160 有时间、66 `text_only`）的 VAD 分数、特征、token、MMS emission 与路径全部与旧 W1＋MMS 一致；X0 fixed30／cut-merge 两窗四次 GPU 验证通过。

## 结论与去向
- 无配置达到严格时间目标；W0（内容保全、部署简单）与 W1（时间研究）各有取舍，W1 在时间上更强但删除更多。Q0／Q1 因覆盖不足不进入短名单。
- 用户采纳 faster-whisper＋新 Pyannote＋MMS（W0）与 Qwen＋新 Pyannote＋MMS（X0）两条基线：[ADR-0003](../../docs/adr/0003-new-pyannote-baselines.md)；历史演进见 [ADR-0001](../../docs/adr/0001-two-stt-baselines.md)、[ADR-0002](../../docs/adr/0002-x0-demo-flow.md)。
- 产品实现取代研究 demo：双语字幕流水线见 [ADR-0007](../../docs/adr/0007-bilingual-subtitle-pipeline-architecture.md)，产品 STT 引擎现行规则见 [CURRENT.md](../../docs/adr/CURRENT.md)。
- 同期衍生轮次：[组件与 CTC](../2026-10-components-and-ctc/README.md)、[VAD 比较](../2026-10-vad-comparison/README.md)、[ASR 候选](../2026-10-asr-candidates/README.md)、[X0 吸收 WhisperX 流程](../2026-10-x0-whisperx-flow/README.md)。

## 教训
- 报告时间指标必须保留完整分母；条件 P95 只覆盖可测子集，覆盖低的路线看上去"更准"。
- 参考字幕是显示边界，不是声学真值；插入字不等于幻听，未听辨不要把 S／D／I 全归咎模型。
- 对同一素材反复调参会使开发／验证／保留失去盲测意义；新的确认应使用新素材。
- Whisper 数字静音幻听、Qwen 4096 token 触顶与重复、CTC 极短窗帧数不足是需要在产品阶段显式处理的失败类型。
- 报告 WhisperX 逻辑可迁移时要分开：VAD 后处理、独立无时间戳解码、特征补齐是显式流程，不需要整个框架。
- 冷进程不是冷磁盘，整卡显存采样不是模型独占峰值，三次重复不足以估计延迟尾部。

## 原始材料
前缀 `archive/2026-11-18-pre-research-restructure:`：
- 报告：`archive/2026-11-18-pre-research-restructure:docs/research/2026-10-04-stt-demo-conclusions.md`、`dev-comparison.md`、`validation-results.md`、`heldout-results.md`、`fullfilm-results.md`、`two-film-revalidation.md`、`final-performance.md`、`display-analysis.md`、`silence-preflight.md`
- 执行与框架：`2026-10-04-whisper-execution.md`、`qwen-execution.md`、`crisp-execution.md`、`whisper-engineering-boundaries.md`、`whisper-framework-{experiment,architecture,asr-audit,vad-alignment-audit}.md`
- 计划与台账：`archive/2026-11-18-pre-research-restructure:docs/plans/local-stt-demo-selection.md`、`whisper-framework-equivalence.md`、`two-film-stt-revalidation.md`、`archive/2026-11-18-pre-research-restructure:docs/context/2026-10-04-demo-execution.md`
- 评测与语料：`archive/2026-11-18-pre-research-restructure:docs/testing/{2026-10-04-corpus-freeze,2026-10-04-evaluator-audit,2026-10-04-media-matching,2026-10-05-w0-demo-validation,2026-10-05-x0-demo-validation,evaluation-config-v1,evaluator-contract,stt-evaluation,subtitle-timing-benchmark,fatestay-reference,demo-analysis-contract,demo-display-contract}.md`
- demo：`archive/2026-11-18-pre-research-restructure:docs/guides/baseline-testing.md`、`docs/specs/w0-reusable-demo.md`、`x0-reusable-demo.md`、`docs/architecture/stt-candidate-pipelines.md`、`archive/2026-11-18-pre-research-restructure:docs/architecture/modules/{vad-stage,w0-pipeline,x0-pipeline,mms-alignment,stt-evaluation,corpus-and-assets}.md`、`archive/2026-11-18-pre-research-restructure:experiments/{w0_demo,x0_demo,whisper,qwen,crisp,framework_equivalence,analysis,display,performance,corpus}/`
