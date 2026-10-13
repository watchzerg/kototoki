# 逐窗翻译运行时

## 定位与阅读

负责本地字幕翻译的模型运行与逐窗生成：外层 `translation_demo_runtime` 启动并独占一个 loopback llama.cpp server，记录引擎／模型身份、GPU 驻留与资源采样；内层 `translation_demo.run` 对冻结窗口 JSONL 逐窗构造各模型家族的原生提示、受 grammar 约束生成、机械校验 ID JSON 并留存全部 HTTP 交换。ADR-0005 的模型与采样基线（APEX-I-Compact＋`official30b-cached-v1`）以此为入口。不负责整片 SRT 的批次组织（见[完整 SRT 翻译流程](translation-srt-flow.md)）、译文质量评审或参考构建。

上级总览见[架构总览](../INDEX.md)；采用身份见 [ADR-0005](../../adr/0005-apex-i-compact-translation-baseline.md)；使用说明、候选列表、映射配方与产物格式见 [translation_demo README](../../../experiments/translation_demo/README.md)；行为规格见[字幕翻译通用规格](../../specs/subtitle-translation-common.md)与 [Hy-MT2 规格](../../specs/subtitle-translation-hy-mt2.md)；模型资产见[资产指南](../../guides/local-translation-model-assets.md)。

## 当前行为规格

- 入口：`just translation-baseline --inputs <窗口.jsonl> --output-dir <新目录>`（固定 APEX、兼容引擎与身份文件、99 层、`official30b-cached-v1`、`n_predict` 4096、context 8192、线程 8／8）；`just translation-demo` 为通用入口，须显式给 `--candidate` 等参数。CLI 的默认 `--sampling-profile` 是历史 `legacy-greedy-v1`（temperature 0、输出 1024、context 4096、不缓存）。
- `resolve_profile`：`official30b-cached-v1` 只允许 APEX 候选且不得用于映射阶段，要求输出 4096、context ≥ 8192；显式发送 `top_k:0`、`repeat_penalty:1.0`、`samplers=["temperature"]` 等以关闭其余采样器。
- 外层前置检查：层数与 context 为正（不支持纯 CPU）；自定义引擎必须附身份文件；模型文件 SHA256 须与资产清单一致；端口已有服务即拒绝；输出目录须不存在。加载后核对实际 offload 层数与 GPU buffer，部分 CPU offload 须 `--allow-cpu-offload` 明确许可，否则中止，不自动降层。
- 内层：只接受 loopback、无认证、不跟随重定向的 HTTP（`LlamaClient`）；Hy30 使用 `token-ids-v1` 传输（先 `/tokenize` 再以 token 数组请求 `/completion`）；每窗至多两次相同请求；超出 context 不截断而记失败；输出截断、无效 JSON、错／漏／重复 ID 均记失败。
- 退出码：0 阶段完成，1 存在逐窗失败，2 配置／准备错误（README「产物与恢复」）；`--stop-on-oom` 时遇明确 OOM 文本停止后续窗口并列出未执行尾段。

## 实现设计

- `translation_demo_runtime.main`：解析配置 → 资产清单合并与模型哈希 → 组装 llama-server 命令行（单槽、batch 256／ubatch 128、KV f16、`--cache-ram 8192`、flash attention on、fit off）→ 启动 `ResourceMonitor`（`experiments/translation_monitor.py`）→ 等待健康 → 以子进程运行 `experiments.translation_demo.run`（或经 `--session-worker` 指定的历史 worker）→ 停止服务器并写 `runtime/engine.json`、`runtime-final.json`。运行器、profiles 与 monitor 源码副本连同哈希保存到 `runtime/`。
- `translation_demo/adapters.py`：各家族原生模板（`render`、`wrap`）、ID JSON grammar（`id_grammar`）、严格解析（`strict_json`、`translations`）及 TranslateGemma 映射阶段的边界 anchor 与分组校验。
- `translation_demo/run.py`：候选表 `CANDIDATES`、资产清单（`asset_manifest_paths`、`load_assets`、`select_asset`）、模板校验、`attempt_generation`／`run_window` 重试与记账、`explicit_oom`。
- `translation_demo/gguf.py` 只读 GGUF 元数据，不加载张量；`profiles.py` 维护版本化采样配置。

## 接口与依赖

- 被[完整 SRT 翻译流程](translation-srt-flow.md)导入：`adapters`（模板与 grammar）、`client.LlamaClient`、`run.explicit_oom`／`asset_manifest_paths`／`load_assets`／`select_asset`、`translation_demo_runtime.residency_evidence`／`validate_residency`／`loader_logs`。改变这些符号会改变 v3 配方的请求字节，进而改变 `recipe_hash` 或 C0 等价测试结果。
- `--session-worker` 的可选值全部指向历史包（`translation_four_quantization`、`translation_flow`），只用于复现历史运行。
- 运行环境：根 `.venv`（无第三方依赖）＋本机 llama.cpp server 与 GGUF 资产，均在 `.local/` 下预先准备。

## 代码与验证入口

- 源码：`experiments/translation_demo_runtime.py`（`main`、`parser`、`residency_evidence`、`validate_residency`、`loader_logs`、`forward_worker_events`）、`experiments/translation_demo/`（`run.py`、`adapters.py`、`client.py`、`profiles.py`、`gguf.py`）、`experiments/translation_monitor.py::ResourceMonitor`。
- 测试（离线）：`experiments/translation_demo/test_demo.py::DemoTests`（44 项：ID 校验、原生模板、无参考输入、映射保真、截断与重试记账、禁止远程推理、产物防覆盖、资产清单身份、OOM 中止、部分 offload 许可）、`tests/test_translation_monitor.py`；由 `just translation-test` 运行，`tests/` 下的部分也被 `just test` 发现。
- 真实验证：[新配方采纳检查](../../testing/2026-10-08-official30b-cached-baseline-validation.md)；离线测试不验证翻译质量。
- 已知限制：外层不获取 `.local/gpu.lock`，只检查端口占用；与 STT 或 v3 GPU 作业的互斥须由操作者保证（见[模块边界：并发与生命周期](../module-boundaries.md#并发与生命周期)）。
- 已知差异：无（CLI 默认 `legacy-greedy-v1` 与 README、ADR-0005 的说明一致）。

## 变更与决策来源

[ADR-0004](../../adr/0004-hy-mt2-translation-baseline.md)（已被替代）、[ADR-0005](../../adr/0005-apex-i-compact-translation-baseline.md)；[四量化实测报告](../../research/2026-10-07-hy30-four-quantization-results.md)。
