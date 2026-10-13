# 本地 STT demo 执行记录

状态：首轮与两片复核已完成；用户随后将未来基准线更新为 W0／X0，尚无严格时间达标配置。日期：2026-10-04。

2026-10-05 后续用户采用两条新 Pyannote＋MMS 基线，见[ADR-0003](../adr/0003-new-pyannote-baselines.md)。
W0为faster-whisper＋新Pyannote VAD＋MMS，并须保留WhisperX的切分合并、独立无时间戳解码和特征处理；
X0为新Pyannote VAD＋Qwen-ASR＋MMS，仅吸收兼容Qwen的流程并保留原生特征；均无降噪和人声分离。
2026-10-05已建立[W0 demo](../../experiments/w0_demo/README.md)和[X0 demo](../../experiments/x0_demo/README.md)。
后续session从[标准基线测试指南](../guides/baseline-testing.md)启动新测试，复用对应demo；两套均有小样本GPU验证，正式后端迁移尚未完成。
完整定义以[当前基准线](../architecture/stt-candidate-pipelines.md)及 ADR-0003 为准。canonical demo 的旧W0／fixed30 X0执行默认仍待迁移，既有demo验证不能证明新配方已完成迁移。
下文W0／W1／X0及“两条优先方向”均为当时的实验身份和研究建议，不替代当前demo及其独立验证记录。

## 后续评估入口：参考优先级与已有音频

两片主参考复核现已完成，见[新结果](../research/2026-10-04-two-film-revalidation.md)：五条旧配置、12 个固定300秒窗口、N590，84阶段全部完成，仍优先 W1 时间研究与 W0 工程入口，保留接近的 X0 对照。新结果和恢复入口位于 `.local/round2/` 与 `.local/analysis/round2/cpu-r1/`，不替换下文首轮证据。

2026-10-04 用户确认 II、III 的原版内嵌日文 SRT 为精确主参考；I 的双语抽取 SRT 可信度较低，Black Panther 的日语配音/字幕可信度最低，后两者仅作补充。后续直接识别 `D:/movie/` 各影片目录已有的 `.jpn.flac` / `.jpn.eac3`，无需再次提取视频音轨。路径、哈希及来源以[素材规范](../testing/fatestay-reference.md)为准，计分与分层报告见[评估方法](../testing/stt-evaluation.md)。

以下为已完成的旧单片轮次证据，不是 II、III 新轮次结果。新轮次另冻参考和分集，保留旧 manifest、哈希及成绩；既有开发、保留测试和四片机器抽查的接触历史不能清零。

## 已完成检查点：整片、重复测试与收尾审查完成

- `.local/analysis/run-final-evidence.py` 八次调用全部完成：
  `p1-{w0,w1norm}-ch07-r{1,2,3}` 与 `f1-{w0,w1norm}-full-r1`。GPU锁已释放；不重复运行这些ID。
  两路线短片各三次完整文字与timed units完全一致，外层墙钟中位数15.805/25.245秒；
  7028.043秒整片耗时329.740/195.980秒。性能报告和独立核查分别为
  `.local/analysis/performance-final/r1/`、`.local/audit/final-evidence-r1/`。
- 整片CPU评分 `.local/analysis/fullfilm/cpu-v1-r1/`：完整N1026、10782参考字符；
  W0 CER20.015%、D474、可测652、半秒确定成功420；W1 CER19.987%、D947、可测592、成功504。
  所有实际神经阶段GPU且无推理缓存；二者仍无严格时间资格。整片不是新增独立保留集。
- 固定writer整片重放 `.local/analysis/display/fullfilm-r1/`；W0实际SRT文字覆盖97.75%，
  W1为98.25%，完整生成文本保留sidecar。W1的1600条字幕中705条不足半秒，不宣称可读性合格。
- 最终配置数字静音 `s2-{w0,w1norm}-silence-r1`：W0仍插入14字，W1原生GPU VAD输出空。
  W1空输入不派发ASR/CTC；不能将其当作全部神经阶段执行证据。
- 新E2端到端逐字段与缓存组件相同，59次CTC/归一化/decoder CUDA观察，独立核查见
  `.local/audit/w0ctc-fresh-and-tail-r1/`。47秒长尾由跨片段文字对应形成，同项W0为coarse_time，
  不把不同可测子集P99差异说成新CTC导致退化；停止额外E2扩展的决定不变。
- 结论入口 [实测结论与实施顺序](../research/2026-10-04-stt-demo-conclusions.md)，
  [整片质量](../research/2026-10-04-fullfilm-results.md)和[最终性能](../research/2026-10-04-final-performance.md)。
  独立审查核验保留、整片、性能和版本措辞，root另复核原始JSON、连续性计数和文档。
  根环境164项测试146通过18跳过；Whisper独立环境23/23、Qwen20/20均通过，编译检查通过。
  没有正在运行的GPU队列；不需要重跑已完成ID。后续应以新数据/独立人工标注为新轮次，
  保留现有快照，不能把已观察数据重新称为盲测。剩余验证不伪装为已完成。
  原始SRT在最终推理后SHA仍为基线，私有模型/音频/结果均被Git忽略，没有Git提交或远程变更。

## 历史检查点：保留完成，最终整片与重复测试登记

- 原保留 80 个评分槽位与 16 章均完成；报告为
  [固定保留测试](../research/2026-10-04-heldout-results.md)，独立审查重算全部分数与 bootstrap 通过。
  五路线完整 N620，均未严格达标。Q0 chapter12 生成触顶、X0 对应桥接拒绝、Crisp chapter20 原始对齐失败均保留。
- Crisp chapter20 仅非词汇标点的原生空标签被旧 guard 误判；修复后新 FA 调用
  `h2-q1-ch20-nonlexical-r1` 实际 Vulkan 成功，文字、units、native 与原输出完全相同。
  独立敏感性只有确定成功数 87→88，不覆盖原保留轮次；原冻结源码副本仍在运行目录。
- W0＋规范化标准 CTC 的五开发章和三验证章已完成。验证确定 0.5 秒成功数为 48/151，
  W0 为 37、W1 修正流程为 56；E2 条件 P99 为 47.482 秒，且可测覆盖下降。
  不扩展为新的保留或整片搜索，不把锁定后的探索称为盲测。
  新鲜端到端 `e2-w0ctc-fresh-ch07-r1` 完成 38.935 秒，尚待最终证据核查。
- 最终选择 W0-no-context 与 W1-normalized-forced 两条有独立工程价值的配置。
  登记 `.local/manifests/final-evidence-selection-v1.json` SHA256
  `030d1a6472521c619818f92f39f442d8281818603425ca937c8e125cd0ea6def`；每条 chapter07
  三次新推理，再各一次完整 7028.043 秒音频。入口 `.local/analysis/run-final-evidence.py`。
  开始前暂停 agent CPU/下载/模型任务，GPU 串行；完整电影不是新增独立保留集。
  此处为运行前登记，不能解释为已完成整片或测速。
- 最新 `just test` 与 `just check` 均通过，日志 `.local/analysis/final-offline-tests.log`。
  测试中的可选后端依赖跳过须结合独立后端环境测试说明。

## 历史检查点：保留测试启动时

- 验证 21 个阶段全部完成，汇总 `.local/analysis/validation/cpu-v2-r1/`：六配置均保持
  N151、1669 个参考字符，实际设备证据齐全，无调用失败；没有严格时间达标者。
- 按冻结时间角色选择 `W1-normalized-forced`：确定 E<0.5 秒为 56/151，对照为 45/151；
  同时多删除 104 个参考字符，可测数量少 11。上下界可重叠，选择不构成整体质量胜出。
- 保留清单 `.local/manifests/heldout-freeze-v1.json` 在首次保留推理之前冻结，SHA256
  `f639c655017c789c095cfc62a241595484d3835b5423a9c3478ece08dd20bad5`，81 项身份。
  五组固定为 W0-no-context、W1-normalized-forced、Q0-window30、Q1-no-vad、
  X0-Q0-window30-normalized-forced；16 章、N620，后续不修改参数或评分规则。
- `.local/analysis/heldout-batch.ps1 -Execute` 正在串行执行 96 个阶段，ID
  `h1-{w0,w1norm,q0,x0,q1asr,q1}-chXX-r1`。恢复前核对 GPU 锁与运行进程；
  完成记录只作严格校验后的缓存复用，失败记录不得覆盖。此前的“保留未推理”为历史状态。
- 运行中已观察到 `h1-q0-ch12-r1` 的生成失败：调用完成但两个窗口触及 4096 token，
  另一个生成 3864 token，整章耗时 548.050 秒。官方后处理显著压缩原始重复文字；
  最终 CER 不能替代生成稳定性检查。桥接按既有规则拒绝，因此 `h1-x0-ch12-r1`
  未调用；汇总须保留已完成的 Q0 ASR 文字并计下游对齐失败，不能缩小 N620。
  队列继续其他路线和章节，预期最终脚本退出非零以报告该桥接失败，不等于后续全部未执行。
  恢复脚本仅核验已有 harness 状态、命令与音频，正式汇总还需核验结果文件完整性。
- 新端到端入口 `experiments/qwen/run_cross.py` 已完成 `x0-fresh-ch07-r1`，真实执行
  Qwen ASR-only、导出及归一化标准 CTC，harness 墙钟 65.214 秒。后台 CPU 工作并行，
  仅作为可运行性证据，最终测速另做安静条件下的三次新推理。
- 另登记一个有界探索配置：固定 W0 无前文 ASR，改用归一化标准 CTC，隔离验证中
  “时间改善但 ASR 删除增加”的取舍。清单 `.local/manifests/w0-standard-ctc-exploration-v1.json`
  SHA256 `6ddc4ded9a6834eb8d2f8d7d4b1b1439112df968dd0a509cf516857972452b25`。
  先完成原保留队列，再运行 `.local/analysis/whisper/w0-standard-ctc-probe.ps1 -Execute` 的五个开发章，
  ID `e2-w0ctc-chXX-r1`。只测试此一个组合，不调参；它不是原轮次保留候选，也没有新的独立盲测。
- 原轮次 `h1-q1-ch20-r1` 记录退出 2：一个只有标点的 ASR 片段未产生 FA words，被包装器判失败；
  实际 GPU 已验证。正在独立核查是否为包装器边界错误，当前不修改冻结文件或覆盖该运行。
- 当前公共 `just test` 共 150 项，132 通过、18 可选依赖跳过；对应固定 Whisper/Qwen 环境
  分别 16/20 项全部通过；`just check` 通过。新增报告测试已纳入未冻结的 justfile。
- 开发选择的独立审查通过，报告 `.local/audit/2026-10-04-development-selection-audit.md`；
  验证后的选择及保留冻结清单另行审查。人工声学标注和整片连续性仍未完成。

## 当前事实

- 开始时仓库仅有文档；README 修改及未跟踪的 AGENTS.md/docs 均保留。
- 已读取执行计划及评测、素材、工具链、Windows 约束。
- 原始 SRT SHA256 与文档基线一致。输入始终只读，输出在 `.local/`。
- 原生 Windows RTX 5080，驱动 616.92，显存 16303 MiB；这只是设备枚举证据。
- 日语音轨为 stream 1、FLAC、48 kHz、双声道，媒体与音轨 start_time 均为 0。
- 根评测环境由 uv 创建，Python 3.12.15；模型后端环境互相隔离。
- mise 2026.10.0、uv 0.12.22，just 1.58.0。just 官方 Windows 包已核对 SHA256。
- 评测器、语料冻结、Whisper、Qwen、Crisp、模型获取由不同 agent 分目录准备；GPU 由主 agent 串行调度。

## 运行与恢复

`pyproject.toml` / `uv.lock` 只管理轻量评测环境；各路线自己的锁与运行说明随适配器保存。
根环境可执行 `uv run --locked --offline python ...`；`just test` 和 `just check` 不下载模型。

`experiments/run_experiment.py` 串行运行 GPU 子进程，记录命令、输入 SHA256、前后字幕哈希、
全设备显存/利用率采样、墙钟时间和退出状态。后端详细结果与日志位于 `.local/results/<run-id>/`。
命令必须显式给出音频、输出和本地模型路径；不能把缓存结果作为新推理。

运行前检查 `.local/gpu.lock`。中断后先核对其中 PID 与子进程状态；确认无进程后才可清除陈旧锁，
不要直接覆盖同名运行目录。超时会终止该次子进程树。

媒体探测：`.local/manifests/media-probe.json`。模型和语料清单将在各自步骤完成后补充。
下载使用已冻结的 revision，保留部分文件；不要删除缓存重新从头下载。

## 阶段 0 已有证据

- [语料冻结](../testing/2026-10-04-corpus-freeze.md)已完成：开发 199、验证 151、保留 620、
  边界隔离 60 条。全片及开发章音频已解码；尚未使用保留集调参。
- 主 agent 独立运行初版评测器 15 项测试及语料处理 4 项测试通过；独立审查正在扩展边界例子。
- CT2 large-v3、Crisp ASR f16 / FA f16 / Silero 已逐文件核对固定 revision 与哈希。
  官方 Qwen native HF 和日语 CTC 资产也已完成；七组资产共 16.84 GB 全部核验，当前没有模型下载。
  详见[资产记录](../research/2026-10-04-model-assets.md)。
- `q1-smoke-vulkan-native-r1`：60 秒开发片段，Crisp v0.8.41 Vulkan + 原生 Silero，
  VAD 判定 0 个语音段，上游退出 0 但未写 JSON，适配器正确记录失败；不能证明 ASR/FA 成功。
- `q1-smoke-vulkan-no-vad-r1`：仅关闭 VAD 的诊断对照，上游产生文字与 FA 输出，
  存在 alignment collapse 警告。ASR 有 Vulkan 设备日志，但 FA 位于 DLL 内，CLI 的日志不足以
  独立证明其设备，当前仍为设备未验证，不能列为合格方案。
- 独立源码核查发现 FA 可通过官方 C ABI 在同一个 DLL 显式设置 GPU 后端；正在准备独立验证。
- 初始 smoke 的原始 8 条 SRT 中 4 条为中文制作信息/声明，不能作为口述文字真值。
  源文本核对已确认此问题，将保留原 v1 参考并新增明确非口述项 overlay；初版未清理 CER
  只保留为调试产物，禁止用于选型或声称模型漏识别。

预检期间适配器和评测器仍在修正；正式筛选规则尚未冻结，尚无排行榜或达标结论。

## 最近进度与下一步

以下为恢复工作用清单，不是选型结论：

- 评测器已修至 `nfkc-punctuation-v2-universal-complete-invariant-boundaries`，26 项测试通过，
  独立审查穷举 6,882 个跨度通过。新的评分文件名为 `score-ref2-eval2.json`；
  旧 `score-v2.json` 的 v2 仅指参考 overlay，算法仍是旧版，不能混入新汇总。
- 参考使用 `.local/references/scoring-v2/`，仅排除明确中文制作信息 0001/0002/0003/0006。
  开发分母 195、全片 1026；原始 v1 与源 SRT 都保留。
- W0 原生与关闭前文两个配置，5 个开发章 01/02/05/07/17 都已完成。
  ID：`w0-chXX-cuda-native-r1`、`w0-chXX-cuda-no-context-r1`。
  实际 CUDA float16；早期临时复制的 DLL 已与完成的官方 Torch wheel 全部核验一致，
  `.local/tools/whisper-runtime-provisional/acquisition.json` 当前状态为 verified，路径名保留防止破坏复现。
- WhisperX 原生也已完成上述 5 个开发章，ID `w1native-chXX-cuda-r1`。
  ASR CUDA float16、VAD/CTC CUDA float32 前向记录齐全。
  `w1-ch01-w0native-ctc-r1` 与 `w1-ch01-w0nocontext-ctc-r1` 已完成。
  后者可测 20/28、条件 P95 1.379 秒、全分母 500 ms 成功 11/28；仍未达到目标。
- Crisp 原生/关闭 VAD 的章 01 与 17 已完成，但 CLI 内 FA 设备日志不足，仍标未验证。
  `q1-ch01-cli-asr-novad-r1` + `q1-ch01-cli-novad-explicit-fa-r1` 分开证明 ASR 和 FA Vulkan；
  字幕文字与原 CLI 关闭 VAD 结果完全一致，237 个共享时间单元中 236 个相差不超过 11 ms，
  另一个差 80 ms。对齐质量问题仍存在。
- Crisp 同 DLL ASR session 试验两次出现 setter 返回语义及非法 UTF-8 问题，保留失败记录，
  目前优先采用 CLI ASR + 显式 GPU FA 的可观察阶段路径，不无限修补 C ABI ASR。
- Crisp 原生 VAD 的 CPU 诊断确认 smoke 最大概率低于 0.5；64sample carry 没有改善，
  chapter17 则有正常高概率语音。不能将单片段零 VAD 误报为模型损坏。
- 官方 Qwen 环境 `.local/envs/qwen-hf-final` 就绪：Python 3.13.16、Torch 2.14.1+cu130、
  Transformers 5.18.0，62 个包 hash lock。ASR/FA 权重均已核验。
  `q0-smoke-cuda-native-r1` 已证明 ASR/FA 参数、输入、输出 CUDA；短片文字与参考一致，
  但两个跨度时间无效，其余两个 E 为 4.43/14.64 秒。章 01/02 原生也已完成，05/07 排队执行。
  章 17 超过原生 FA 的 300 秒限制，须明确记为配置不支持，并另标窗口对照。
- WhisperX 环境 `.local/envs/whisper-latest`，W0 环境 `.local/envs/whisper-w0-py312`。
  全部私有逐次结果在 `.local/results/<ID>/`，harness manifest 记录是否实际完成以及源码快照。

继续顺序：完成 W1 组件及一次有依据的低 VAD 阈值对照；补齐 Crisp 显式阶段路径的开发章；
完成官方 Qwen 原生开发流程，再检验长窗口 FA 的有界窗口对照。用统一 v2 算法重评全部开发结果，
再校准并冻结晋级规则，才进入验证、保留与整片。至今验证/保留未推理，人工声学标注仍缺失。
GPU 同时只运行一个 harness；后台 CPU/下载准备阶段的耗时只作探索记录，最终入围者需独立重复测速。
验证章 03/14/23 的音频已按冻结时间精确裁切并核验，但尚未推理；保留章尚未裁切。

## 证据边界

### 后续开发检查点

**当前已进入验证，以下开发历史保留供追溯。**

- 决策规则与六个晋级配置见 `docs/testing/evaluation-config-v1.md`，验证期间不可修改。
- `.local/manifests/validation-freeze-v1.json` SHA256
  `e2bbfa0c5b0e34f696390cf5089ad07d71e8b603e796a05ed458da68f0f06662`，冻结 61 项身份；
  配套源码在 `.local/manifests/validation-freeze-v1-sources/`。
- 运行 `.local/analysis/validation-batch.ps1 -Execute`：固定章 03/14/23，每章 W0、两种 W1、
  Q0、Q1、X0，共 21 个阶段调用；先核对 GPU 锁，脚本验证所有冻结身份，已完成结果严格核验后复用。
  ID 前缀 `v1-{w0,w1component,w1norm,q0,q1asr,q1,x0}-chXX-r1`。
- 最终开发快照 `.local/analysis/dev-comparison/cpu-v2-r7/` 共十三个全五章配置，N195/1902 字符。
  规则计算已由主 agent 复核；没有严格时间达标者。
- 新增标准 CTC：WhisperX 同一次模型 emission 用 TorchAudio 2.8 的 CUDA forced_align 提取
  非 blank token 跨度，配合 checkpoint 官方逐段归一化；不是单帧诊断。
  `w1native-chXX-ctc-normalize-forced-r1` 与
  `x0-q0window30-chXX-ctc-normalize-forced-r1` 均完成五章，实际 decoder CUDA 已核验。
  OOV 保留 text_only；原生输出与派生输出同时保存；TorchAudio API 的弃用限制已记录。
- W0 原生、固定 temperature0 和 Q0 window120 有未解决的重复/上限故障，保留诊断，未晋级稳定路径。
  W0 关闭前文保留原生温度 fallback，在开发范围没有同类强重复异常。
- Q0 `--asr-only` 新路径真实 GPU 章 07 与原完整流程的文字、逐窗文字及样本范围完全一致，
  用于后续 X0 新端到端性能运行，避免执行无用 Qwen FA；不是新的质量配置。
- 数字静音五种流程已执行，见 `docs/research/2026-10-04-silence-preflight.md`。
  根测试 102 项中 85 通过、17 可选依赖测试显式跳过；冻结后端环境测试另行全部执行。
- 保留章 16 份音频已按冻结范围准备，`.local/manifests/corpus-heldout-preparation.json`；
  尚未执行保留模型推理。没有人工声学标注，仍不能宣称声学目标达到。

- Q0 原生 01/02/05/07、固定 window30/window120 全五章均已完成。ID 为
  `q0-chXX-cuda-{native,window30,window120}-r1`。统一汇总在
  `.local/analysis/dev-comparison/cpu-v2-r2/`，不要只扫描 run 文件夹里的旧 score。
- window120 章 17 有生成上限失败：第三窗重复短串 1358 次、4096 token 无正常终止，
  官方清理压缩重复，最终 CER 不能显示全部问题；这一方向停止，不晋级稳定路径。
- Q0 window30 完整开发 CER 23.71%、D=69/I=129、n=91/195、E P95=6.668 秒，
  确定 E<0.5 秒 79/195。仍是待验证工程候选，不是时间达标方案。
- Crisp `q1-chXX-cli-{native,novad}-explicit-fa-r1` 两组全五章阶段路径已完成，
  对应 `q1-chXX-cli-asr-{native,novad}-r1`。全部显式 GPU 证据待汇总独立复核。
  私有恢复脚本 `.local/analysis/crisp/dev-batch.ps1 -Execute`，已完成则严格校验后复用，不能当新测速。
- WhisperX 转移帧诊断 `w1native-ch{01,07}-ctc-transition-r1` 已完成：保留 native_evaluation
  与原生 chars，根 units 是实验性 CTC 转移帧区间，不是发声时长。章 07 有收益、章 01 仍很差，
  不将此诊断直接当正式对齐方案。下一探针仅检查 checkpoint 指定的逐段归一化。
- W0 第三组 `w0-chXX-cuda-no-context-temp0-r1` 正串行运行，单独关闭温度 fallback。
- Q0 固定短片 ASR 文字的 FA-only 裁切探针已准备 `.local/analysis/qwen/smoke-grid-second30-manifest.json`，
  源时间 40–70 秒，尚待 GPU；不算新 ASR 或独立样本。
- 数字静音 `.local/audio/synthetic-silence-10s.wav` 和空参考已准备。评测器新增
  `synthetic_digital_silence` 空参考类型，旧 v2 算法不变；27 个评测器测试通过。
- [第一轮筛选规则](../testing/evaluation-config-v1.md)已冻结决策方法，具体晋级配置还未冻结。
  验证音频已准备但没有模型结果；保留集仍未使用。

没有可靠人工听辨和边界标注时，只报告相对 SRT 的文字/显示时间差异；声学目标保持未验证。
章节是场景代理，不能证明语义场景完全独立。保留集在正式规则冻结前不用于候选调参。
设备枚举、安装完成、合成测试通过都不是模型 GPU 推理证据。
