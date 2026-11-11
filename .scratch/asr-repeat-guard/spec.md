# ASR 整窗复读守卫进产品

权威来源：[计划](../../docs/plans/asr-repeat-guard.md)（§2 事实、§3 已定决定、§5 验收与停止条件、§6 不做的事）与 [ADR-0023](../../docs/adr/0023-asr-repeat-guard.md)。本文不复述要求，只记执行约束：

- 产品 w0 路径在 `asr` 阶段解码后做 `repeat-strict` 折叠，仍命中则按 `failed_windows` 置空；cross 的 w0 那一路同样处理；x0 不处理。
- 不改规则参数、解码、VAD、x0 路径、`experiments/` 既有脚本与 W0 基线文档；产品不导入 `experiments.*`。
- 转写文字不进 Git 与日志；需要裁定的事写计划 §8，不中途问。
- GPU 只在票据 04，授权范围：产品 asr／align worker 在 HF II、HF III 上重算，一次 `just smoke`；不启动 Strata、不起 llama-server、不下载权重。
