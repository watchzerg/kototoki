# 单组件消融实验

> 2026-10-05 后续开发入口：本目录是历史组件实验。当前W0／X0实验从[标准基线测试指南](../../docs/guides/baseline-testing.md)进入相应demo，更新对应Adapter或模块，复用共用MMS并另建身份；本目录冻结配置仅作历史对照。

状态：首轮及用户指定的 VAD＋CTC 追加完成；未采用新的产品配置  
日期：2026-10-04  
范围：三条冻结基线的增量研究，不是产品转写接口。

执行计划与评估规则见[方案](../../docs/plans/component-augmentation.md)，
模型身份与来源见[组件核查](../../docs/research/2026-10-04-component-augmentation-sources.md)。

`separate.py` 使用隔离 Demucs 4.1.0 环境与预先获取的本地 safetensors，
在 GPU 上分离 vocals，输出同样长度的 16 kHz mono PCM16 与时间映射清单。
输入为既有单声道实验 PCM，因此不能推断原生立体声分离的质量上限。
采样坐标不变也不能证明分离没有声学边界影响；应通过端到端评分及声学核对评估。

`run.py` 冻结并串行执行四窗筛查或十二窗扩展，通过现有 GPU harness 保留原始证据。
它不修改旧适配器或原始素材。`manifest.py` 绑定新结果、分离输入及旧基线，
`evaluate.py` 沿用现有计分核心、完整分母和边缘不确定性，输出独立新目录。
所有命令从仓库根运行。`--name` 必须是未使用的新实验身份。

分离环境与旧后端隔离；已测 Python 3.12.15／Torch 2.8.0+cu128／Demucs 4.1.0，
精确安装清单为 `requirements-demucs.lock`。恢复环境时通过 uv 使用对应 CUDA wheel 来源，
不得把这份实验锁直接同步到旧 Whisper／Qwen 环境。正常分离只读取本地 safetensors；
获取地址、版本及许可边界见来源报告。

```powershell
uv run --locked --offline python -m unittest experiments.components.test_separate experiments.components.test_evaluate -v
uv run --locked --offline python -m experiments.components.run prepare --name comp-sep-pilot-v1
uv run --locked --offline python -m experiments.components.run run --name comp-sep-pilot-v1
uv run --locked --offline python -m experiments.components.finalize_manifest --name comp-sep-pilot-v1 --output .local/components/comp-sep-pilot-v1/evaluation.json
uv run --locked --offline python -m experiments.components.evaluate --manifest .local/components/comp-sep-pilot-v1/evaluation.json --output .local/analysis/components/comp-sep-pilot-v1
```

旧轮冻结了公共配置文件，本轮新增测试显式执行，避免为登记 recipe 改写历史冻结身份。
环境安装、权重获取不属于正常推理；资产必须预先独立配置。
任务中断后，已完成且身份一致的 harness 可恢复登记；未完成尝试保留，并要求新实验身份。
不覆盖旧日志或将失败自动重试后的产物伪装成首次成功。

独立 VAD 消融使用 `run_vad.py prepare/run --name comp-vad-pilot-v1`，输入原始 PCM。
`vad.py` 通过已安装 GPU Pyannote 产生带上下文且不重叠的语音区间，
`w0_vad.py` 使用公开 `clip_timestamps`，`qwen_vad.py` 用精确采样分窗并生成独立 CTC 桥接。
它们不改变 W1 的原生 VAD，也不与分离器默认叠加。裁剪窗口仍可能包含内部静音；
W0 的实际时间 seek 为 10 ms 网格，Qwen 为原始样本坐标。
旧 Qwen 连续窗 exporter 保持原约束；非连续 VAD 桥接属于独立实验实现。

新增离线测试统一可执行：

```powershell
uv run --locked --offline python -m unittest discover -s experiments/components -p 'test_*.py' -v
```

根环境缺少 NumPy 时，Qwen VAD 的三个数值桥接测试明确跳过；在既有 `qwen-hf-final`
环境另行执行该模块可覆盖它们，不把跳过项记为通过。

`extend_vad.py` 只扩展冻结的 W0＋VAD 配置至十二个原窗口，
`evaluate_w0_vad.py` 保留三条原基线及八轴诊断。实测出现删除／完整覆盖取舍后停止该分支，
首轮没有执行 VAD＋CTC 叠加。用户后续指定的时间优先追加见
[独立方案](../../docs/plans/w0-vad-ctc-follow-up.md)，保留首轮原始结果与停止理由。

`align_raw_w0.py prepare/run --name comp-raw-w0-ctc-dev-v1` 为独立 W0＋CTC 消融：
读取原 round2 的 W0 完整结果并核验原 harness、源码快照及模型身份，只新运行归一化标准 CTC。
保留原 PCM、全文、ASR segments 和源 offset；缓存 ASR 和新 CTC 成本分别记录。
若对齐失败，完整 ASR 文字仍进入评估，不删除对应窗口或回退成成功的原生时间结果。

`evaluate_raw_w0_ctc.py` 计分这一原始尝试。它暴露了父 segment 未包住自身 word 时间的
输入契约问题；`word_envelope_ctc.py` 只按原 ASR 时间生成确定的搜索包络，保留原始
segments 和逐段映射，拒绝无效词时间或重叠搜索窗口，不读取参考字幕或 CTC 得分。
`run_word_envelope.py prepare/run --name comp-w0-ctc-envelope-dev-v1` 另行冻结并执行该修复，
`evaluate_word_envelope.py` 使用相同完整分母规则计分；原失败尝试仍保留。

`prepare_confirmation.py` 准备事先登记的六个 III 窗口；仅在配置锁定且开发证据支持后使用。
评测方法、分支停止决定与结果以[实测报告](../../docs/research/2026-10-04-component-augmentation-results.md)为准。

用户指定的追加使用 `run_vad_ctc.py prepare/run --name comp-w0-vad-ctc-dev-v1`：
读取已完成的 W0＋VAD 原坐标结果，只新运行相同的归一化标准 CTC，保留原全文和原始 segments。
`evaluate_vad_ctc.py` 在相同十二窗比较原三基准、W0＋VAD、W0＋CTC 及叠加方案；
偏移收益、漏字和无有效时间分别记录，见[追加报告](../../docs/research/2026-10-04-w0-vad-ctc-follow-up.md)。
