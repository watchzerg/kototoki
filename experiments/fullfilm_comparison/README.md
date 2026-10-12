# 整片分段策略比较

状态：整片运行、评分与独立验收已完成  
日期：2026-10-05

按[整片计划](../../docs/plans/fullfilm-segmentation-comparison.md)运行两部完整电影：
W0、X0各比较新Pyannote与无VAD的cut-merge；复用canonical ASR／MMS，不修改默认demo。
原音频与字幕只读，全部输出位于Git忽略的`.local/fullfilm-comparison/`。
完整结果见[比较报告](../../docs/research/2026-10-05-fullfilm-segmentation-comparison.md)。

2026-10-05 后续用户已采用 W0／X0 新 Pyannote＋MMS 基线，见[ADR-0003](../../docs/adr/0003-new-pyannote-baselines.md)。本入口保留整片实验身份及失败后继续执行行为；上述“不修改默认demo”描述实验实施边界。canonical demo 的旧 W0／fixed30 X0 CLI 默认仍待迁移，后续标准实现与验证从[基线测试指南](../../docs/guides/baseline-testing.md)进入。

`corpus.py`核验并冻结完整输入与参考；`segment.py`在整片上一次性生成源窗口。
`worker.py`每阶段复用一个模型，保存逐分段进度，普通分段失败继续后续音频；生成上限不修改。
`run.py`串行管理共享GPU锁和独立解释器。`evaluate.py`提供完整分母和配对排除失败区间的两套分析。
300秒区间只用于评分分组，不重置推理切点，也不舍弃任何尾部。

```powershell
.venv/Scripts/python.exe -m experiments.fullfilm_comparison.corpus
.venv/Scripts/python.exe -m experiments.fullfilm_comparison.run --study-id fullfilm-new-run
```

新Pyannote使用`.local/envs/vad-pyannote-gpu-v1`，Whisper／MMS使用既有`whisper-latest`，
Qwen使用既有`qwen-hf-final`；正常运行离线，不安装依赖或下载模型。
父进程持有`.local/gpu.lock`，子进程核对父PID；不得清除活跃锁。
已完成／失败任务不重复执行；发现中断的running状态先检查，不覆盖或悄悄重试。

评分使用既有`vad-comparison`环境中的RapidFuzz，完整文字CER与时间分箱指标分开报告。
完整推理开始前需通过离线测试和canonical同窗验收，最终状态以结果记录为准。

```powershell
.local/envs/vad-comparison/Scripts/python.exe -m experiments.fullfilm_comparison.evaluate .local/fullfilm-comparison/fullfilm-final-v2/study.json --output .local/fullfilm-comparison/fullfilm-final-v2/analysis-new
.venv/Scripts/python.exe -m unittest discover -s experiments/fullfilm_comparison -t . -v
```

评分输出`report.json`、`diagnostics.json`、`bin-scores.json`与`identities.json`。
失败ASR分段的未完成文字仅计入单独敏感性诊断；正式分析保留其他成功分段，失败处按缺失计分。
MMS失败时保留ASR文字，并报告`text_only`。配对排除采用同家族两种策略的失败区间并集。
整片worker的继续执行规则仅用于本实验，canonical X0 demo仍保持原来的生成上限失败策略。
根环境离线测试会显式跳过需要NumPy或RapidFuzz的检查；完整数值检查在既有
`whisper-latest`及`vad-comparison`环境分别运行，不需要下载模型。

本轮49项离线测试通过，真实8窗W0／X0验收与canonical文字、token／特征和MMS语义一致。
首次整片III的Pyannote在ASR前发生浮点秒数表示校验失败；实验边界现以整数采样点为准重算秒数，
不改变窗口样本或VAD阈值。保留v1失败证据，`fullfilm-recovery-v2`仅补跑III／Pyannote两条链路。
最终`fullfilm-final-v2`引用六次v1有效运行与两次恢复运行，保留各自源码、输入和输出身份。
独立验收核验2003个文件，并要求修复前后源码差异仅为秒数转换；24组文字评分复算完全一致。
新的整片运行需使用未占用的`--study-id`；上面的`fullfilm-new-run`与`analysis-new`是示例新身份。
