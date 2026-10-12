# APEX-I-Compact 基线入口采纳验证

日期：2026-10-07（Asia/Singapore）。状态：通过。采纳决定见 [ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md)。

本次新增 `just translation-baseline`，固定 APEX candidate、兼容引擎、GPU layers 99、context 4096 和线程 8／8；通用 `translation-demo` 仍用于显式对照。Python 推理代码、模型权重、模板及解码配方未修改。新 recipe 显式使用 `python -X utf8`，修正本机默认 cp1252 无法输出中文帮助的问题。

## 实际验证

- `just --dry-run translation-baseline --inputs input.jsonl --output-dir output`：展开为 APEX 及已验证兼容引擎。
- `just translation-baseline --help`：修正 UTF-8 后 exit 0；初次编码失败不是模型推理失败。
- 通过新 recipe 运行完整冻结 smoke：15 个窗口全部成功，失败 0、剩余 0；不是新的质量评分，也不加入原四量化质量分母。
- 原生 Windows／RTX 5080；模型 SHA256 为 `8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a`，runtime 完整重新核验匹配。
- loader 实际 49/49 层 GPU，CUDA model buffer 14,201.67 MiB，`cpu_offload_allowed:false`；没有部分层 offload。该证据不等于所有权重始终物理驻留。
- 冷加载 6.717 秒，整会话约 52.443 秒（含空闲监测及清理）；整卡采样峰值 15,500 MiB、最低空闲 478 MiB，释放后 511 MiB。此 smoke 不能替代原正式 30 分钟稳定性结果。
- 外层工具真实 exit 0；translation exit 0，server／worker 已退出。server exit 1 是运行器主动清理记录，保留其原值。

从仓库根目录实际执行（输出目录已经存在，复跑请换新名称）：

```powershell
just translation-baseline --inputs 'D:/subtitle-samples/翻译模型评估库_v2/固定评测集/模型输入/smoke.jsonl' --output-dir '.local/translation-evaluation/apex-adoption-20261007-smoke-01'
```

本次工具环境将 `UV_CACHE_DIR` 指向仓库 `.local/cache/root-uv`，并启用 `PYTHONUTF8=1`，使用现有依赖；Windows GPU／进程监测按 sandbox 规则升级权限，无模型下载或外部推理。

原始证据：[完成账本](../../.local/translation-evaluation/apex-adoption-20261007-smoke-01/translation/completion.json)、[运行身份与退出](../../.local/translation-evaluation/apex-adoption-20261007-smoke-01/runtime/runtime-final.json)。完整四量化结论继续引用[历史报告](../research/2026-10-07-hy30-four-quantization-results.md)，其中 Q3_K_M 始终表示当轮统计对照；本次切换不重写历史分数、别名或冻结身份。
