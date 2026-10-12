# Crisp 本地实验入口

冻结版本、模型身份、参数、设备与评测边界见 [Crisp 实测记录](../../docs/research/2026-10-04-crisp-execution.md)。`run.py`运行原生CLI，`align_only.py`对保存的ASR及其原生预测范围执行独立GPU FA；不会使用参考字幕作对齐文字。

`align_only.py`的2026-10-04边界修复仅改变“缺少words是否为执行失败”的判定：按固定v0.8.41源码的 `tokenise_words()`过滤合同检查实际alignment labels，替代 `text.strip()`。没有labels时，上游返回空result本属正常行为；原文继续保留为现有text_only，不生成词时间。正常文字有labels但返回空words仍失败。模型、native调用、精度、VAD、窗口、参数、时间映射和评分规则均保持原配置；相关helper含revision、源码SHA与行号。

原始 `h1-q1-ch20-r1` 的包装器失败与原评分保留。其原源码在 `.local/results/h1-q1-ch20-r1/source/experiments/crisp/align_only.py`，以及修复前的冻结快照；此次不会追认旧harness为成功。未来恢复ID为 `h2-q1-ch20-nonlexical-r1`，主agent将同一ASR、WAV与参数执行新的FA，并比较完整原文及timed-units身份。恢复属于单独的已披露边界修复，不重排原盲筛结果，也不把ASR缓存复用算成新完整流水线速度。

离线验证：

```powershell
.venv/Scripts/python.exe -m unittest discover -s experiments/crisp -p test_*.py
```

不加载模型或GPU。标签helper测试保留apostrophe、emoji和过滤块以外的Hebrew Po；按照实际源码过滤FF00–FF65中的全角字母/数字。Unicode标点类别、`isalnum()`或评测器normalize不能替代该合同。恢复推理仍由主GPU队列安排。
