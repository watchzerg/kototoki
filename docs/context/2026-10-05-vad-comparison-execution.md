# VAD 十组合执行状态

状态：十组合实测与分析完成，保留一次真实生成上限失败  
最后更新：2026-10-05  
范围：本次用户 `/goal` 的最终执行记录，结论以[比较报告](../research/2026-10-05-vad-baseline-comparison.md)为准。

2026-10-05 后续交接：用户在[整片比较](../research/2026-10-05-fullfilm-segmentation-comparison.md)完成后明确采用 W0／X0 新 Pyannote＋MMS 基线，见[ADR-0003](../adr/0003-new-pyannote-baselines.md)。本页“不变”是十组合结束时的历史状态，不是现行基线决定；原失败和分数保留。canonical demo 的旧 W0／fixed30 X0 执行默认仍待迁移，继续实施须读取当前契约及新 ADR。

## 最终执行

首批 session `5433` 和 Pyannote 补测 session `56948` 均已正常退出；不要再轮询或重启它们。
`.local/vad-comparison/vad-comparison-v1/study.json` 为 `terminal=true`，120 槽全部实际执行：119 completed、1 invocation_failed，无 blocked／pending／running。
原八组合的 96 个槽位与补测前登记逐项相同，没有重跑或覆盖原输出。

2026-10-05 10:15（UTC+8）用户要求重试后，固定 `pyannote/segmentation-3.0` revision `e66f3d3b9eb0873085418a7b813d3b369bf160bb` 下载成功。
CPU VAD smoke、W0／X0 两路线十二窗及独立 VAD 资源补测已执行。权重文件 SHA256 与原清单备份在 `provision/pyannote-activation.json`。
旧 401 只是授权前历史，不再是阻碍。

## 必须保留的失败

`x0-pyannote-current` 的 `hf-iii-window-03` 首个 ASR 分段生成达到 4096-token 上限，子进程退出 1。
10 个计划分段只尝试了第一个；其余 9 段和 MMS 未执行，不能声明该窗完整转写。
完整参考 742 字符／59 条仍留在总体 6544 字符／590 条的主结果分母中。
该路线主 CER 是含失败占位的管线成绩，不是成功 ASR 输出的纯文字成绩；若展示成功十一窗，须与原基线相同十一窗比较并明确为条件统计。
没有改参数或通过重跑覆盖这次失败。

私有原始证据：`.local/x0-demo/vad-comparison-v1-x0-pyannote-current-hf-iii-window-03/` 中的 `failure.json`、`failure-asr.json`、`asr-partial.json`、`asr-stderr.log`。
四份文件 SHA256 已绑定到登记的 `failure_evidence_sha256`。
旧门控原因从 `reason` 移到 `prior_block_reason`，当前 `failure_reason` 来自实际 ASR 失败；未更改输出或执行状态。
规范化前登记原文保存在 `study-after-pyannote-raw.json`，对应 SHA256 位于新登记的 `resumed_reason_normalization`。

## 最终证据入口

- `analysis-with-pyannote/`：十组合总体／分片评分、S／D／I、完整分母时间成功、条件长尾、配对描述性 bootstrap、成本和源码身份。
- `audit-with-pyannote.json`：119 份完整结果全部通过、0 份证据失败。审计器的 `not_executed_slots=1`／`incomplete` 表示一个槽位缺少完整产物；该槽位实际上已执行并失败，不能写成未测。
- `deletion-diagnostic-with-pyannote/`：无歧义新增漏字诊断；X0＋新 Pyannote 只纳入 11 个完整配对，失败窗明确保留不可分析身份。
- `.local/vad-comparison/resource-v2/`：原 Pyannote、Silero、FSMN、FireRed 的有效单窗资源补测。
- `.local/vad-comparison/resource-pyannote-v1/`：新 Pyannote 单窗资源补测成功，chunks 与主批次一致。
- `study-before-pyannote.json` 与旧 `analysis/`／`audit.json`／`deletion-diagnostic/`：授权前八组合分析快照，不再作为最终十组合成绩。

以上未注明根目录的路径均相对于 `.local/vad-comparison/vad-comparison-v1/`。
119 份成功结果执行证据全部通过；失败窗的 GPU、生成触顶与部分输出另由日志和 trace 验证，不冒充完整执行通过。
比较工具此前 36 项最终离线测试通过，`final-tests-host.log` 保留证据；本次补测未修改模型推理代码。

## 解释与后续

本轮结束时默认 W0／X0 未改，后续用户采用见 ADR-0003。新版 Pyannote 在 W0 的 CER 仅少 4 个编辑错误，且严重偏移、成本有取舍；X0 出现一次真实生成上限失败。
两次批量运行分时进行，不把小幅成本差异当作稳定吞吐优势。原 W0 VAD 在 CUDA、新候选在 CPU，ASR／MMS 均为 GPU。
共享 VAD 成本可计入每条路线的重构串行成本，不能将路线总成本相加当作整项研究实际墙钟。
字幕时间不是人工声学标签；漏字诊断不是 VAD 因果证明，保留歌声不算 VAD 假阳性。
如进一步调参、复现触顶或改变分段策略，应使用新的实验身份，保留本轮失败与完整分母，不能回填替换本轮成绩。

## 后续 GPU 重测已完成

用户要求将新 Pyannote 改为 GPU 后，新建 `pyannote-gpu-v1` 登记，24次新尝试中23次完成、1次同窗触顶。
原 CPU 登记和96份历史参考保持不变。新环境为 `.local/envs/vad-pyannote-gpu-v1/`；
相同 Python／依赖，仅 Torch／TorchAudio 构建换为 `2.11.0+cu128`。
主批次 session `26594` 已结束，GPU 锁已释放；不要重启旧批次。
十二窗检测和23组成功输出均与 CPU 一致，失败的4096-token部分输出也一致。
单窗模型复用 GPU 约0.201秒、CPU约2.627秒；逐窗新进程的 GPU 首次调用约15秒，不能混用两种成本结论。
最终结果、评分、审计与私有证据入口见[独立 GPU 报告](../research/2026-10-05-pyannote-gpu-comparison.md)。
