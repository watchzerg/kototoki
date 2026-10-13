# 完整 SRT 翻译流程

## 定位与阅读

负责把一份日文 SRT 按固定流程配方翻译为中文 SRT：配方定义批次、只读邻文、提示与 grammar，生成器在每个 session 新启动的托管 llama-server 上逐场景生成并可续跑，`translate-srt` 校验完整覆盖后保留原 cue 编号与时间写出。当前采纳的流程基线是 v3 内置配方 `b10-joint`。同一包内还有 v3 探索用的裁判、统计与校准命令，探索已完成，只作历史工具。不负责模型与采样身份（见[逐窗翻译运行时](translation-runtime.md)与 ADR-0005）。

上级总览见[架构总览](../INDEX.md)；采纳决定见 [ADR-0006](../../adr/0006-b10-joint-translation-flow-baseline.md)；命令、配方列表、目录布局、恢复语义与统计规则见 [translation_v3 README](../../../experiments/translation_v3/README.md)；探索结果见 [v3 报告](../../research/2026-10-10-hy30-flow-v3-report.md)。

## 当前行为规格

- 入口：`just translation-srt --srt <ja.srt> --seed <S> --out <chn.srt> [--category anime_series|animation_movie]`，即 `python -m experiments.translation_v3 translate-srt --recipe b10-joint`；子命令可加 `--port`、`--break-stale-lock`。产物根目录 `--root`（默认 `.local/translation-evaluation/hy30-flow-v3/`）是顶层参数，须写在子命令之前，因此经 `just translation-srt` 追加的参数无法改变它。
- `b10-joint`：每批 10 条目标 cue、前后各 1 条只读邻文、`joint-understanding-v1` 提示；固定项见 `recipes.py`（`N_PREDICT` 4096、`CONTEXT_SIZE` 8192、`GUARD_TOKENS` 64 即最大输入 4032 tokens、`CACHE_PROMPT`、每请求最多 2 次相同尝试、官方采样）。超出输入预算记为失败，不截断、不自动缩批。带 `category_overrides` 的配方必须给 `--category`，否则在加载模型前报错。
- 流程：整份 SRT 作为一个场景（ID `srt-<源 SHA256 前 12 位>`），运行目录为 `<root>/deliveries/<recipe>__s<seed>__srt-<sha12>/`。已有同名 run 时核对 `recipe_hash`、seed、scope、源与场景列表，任一不同即拒绝；相同则续跑未完成部分。
- 输出：场景完成且 `validate_translations` 判定每个源 ID 恰有一条非空、无空行的译文时，`write_srt` 以独占创建方式写出（拒绝覆盖已有文件或源 SRT），打印 run id、cue 数、墙钟和输出 SHA256 并返回 0；否则打印覆盖统计与失败原因并返回 1，不写残缺 SRT。
- GPU 锁：持有 `.local/gpu.lock` 期间运行；存活持有者存在时退出码 3 且不杀进程；持有者已死时只报告，确认后加 `--break-stale-lock` 替换。
- 失败分类：上下文超限、输出上限、解析／grammar 失败（重试后）是场景终态；OOM、传输／服务器错误、缓存校验失败是基础设施失败，不写场景终态，下次调用自动重做。

## 实现设计

- `recipes.py`：不可变 `Recipe`，`recipe_hash` 覆盖所有影响生成的字段与提示常量版本；`BUILTIN` 内置配方；`load_recipe` 支持 `<root>/recipes/<name>.json` 组合配方，同名内置配方内容不符即拒绝。提示与 grammar 复用 `translation_demo.adapters`。
- `batching.py::build_batches`：按源顺序从第 0 条起分批，附只读邻文；`cue_positions` 记录批内位置。
- `generate.py::run_generation`：逐场景原子写 `scenes/<id>.json`；`managed_session_factory` 每个 session 新启动服务器，首个 completion 必须 `timings.cache_n == 0`；session 只在服务器成功启动后记入 `run.json`；多于一个实际工作的 session 时标 `resumed: true`、`performance_comparable: false`。
- `server.py`：`ManagedServer` 复现 `translation_demo_runtime` 的基线命令行（模块 docstring 列出全部参数），驻留解析直接导入该模块；`verify_model` 加载前对 GGUF 全量 SHA256 并按路径＋大小＋mtime 缓存；`resolve_model` 要求资产清单 SHA256 等于 `common.EXPECTED_MODEL_SHA256`。
- `procs.py`：`ProcessLock`（pid＋进程创建时间，防 PID 复用）、`KillOnCloseJob`（Windows Job Object，Python 被强杀时服务器随之退出）、`list_llama_servers`。
- `common.py`：仓库内固定路径（引擎、身份文件、v2 冻结源数据目录、v3 根目录、GPU 锁）与原子写（Windows `PermissionError` 时最多重试 20 次）。
- 探索工具（历史）：`judge.py`（Claude MQM 盲评，profile `claude-opus-5-5-mqm-v1`）、`stats.py`（配对 bootstrap 与判定）、`synth.py`、`mbr.py`、`status.py`、`data.py`（读取 `.local/translation-evaluation/hy30-flow-v2-20261008/` 下的冻结 v2 源数据）。

## 接口与依赖

- 依赖[逐窗翻译运行时](translation-runtime.md)：`adapters`、`client.LlamaClient`、`run.explicit_oom` 与资产清单函数、`translation_demo_runtime` 驻留函数。
- 依赖历史包 `experiments.translation_flow.srt`（`read_srt`、`validate_translations`、`write_srt`）完成 SRT 解析、覆盖校验与写出；`test_recipes.py` 还导入冻结的 `translation_flow.v2_prepare`／`v2_recipes` 核对 C0 等价。这些历史文件不得修改（见[模块边界：依赖方向](../module-boundaries.md#依赖方向)）。
- 被历史 `experiments/translation_v4` 导入（`data`、`common`、`judge`、`synth` 等）；改变 v3 公共符号会影响 v4 复现。

## 代码与验证入口

- 源码：`experiments/translation_v3/cli.py::cmd_translate_srt`、`recipes.py`（`Recipe`、`BUILTIN`、`load_recipe`）、`batching.py`、`generate.py`（`run_generation`、`run_id_for`、`managed_session_factory`）、`server.py`（`ManagedServer`、`GpuLock`、`verify_model`）、`procs.py`、`common.py`。
- 测试（离线，55 项，约 3–4 秒）：`uv run --locked --offline python -m unittest discover -s experiments/translation_v3 -t . -p "test_*.py" -v`。`test_recipes.py::AdoptedBaselineTest` 固定 `b10-joint` 的批次参数与 hash `2ba68054…`；`C0EquivalenceTest`、`RecipeIdentityTest`、`BatchingTest`、`CategoryRoutingTest` 覆盖配方；`test_generate.py::GenerationTest` 用伪客户端覆盖续跑、OOM、缓存校验、重试、上下文超限；`test_status.py` 覆盖锁、Job Object、原子写。
- 已知限制：上述 v3 测试不在任何 just recipe 中（`just experiments-test`、`just translation-test` 都不包含 `experiments/translation_v3`），只能按 README 命令单独运行。
- 已知差异：[translation_v3 README](../../../experiments/translation_v3/README.md#验证范围)「未验证」列出 "`translate-srt` 端到端"，而 [ADR-0006](../../adr/0006-b10-joint-translation-flow-baseline.md#证据与已知代价如实记录) 记录了两份整片交付（1993 条电影、387 条剧集）完整完成。两者不一致，需确认 README 的未验证清单是否应更新（文档修正，不涉及代码）。
- 未验证：新 Job Object／锁逻辑下的真实 llama-server 启动（README 明示）。

## 变更与决策来源

[ADR-0006](../../adr/0006-b10-joint-translation-flow-baseline.md)；[v3 计划](../../plans/hy-mt2-translation-flow-exploration-v3.md)、[v3 报告](../../research/2026-10-10-hy30-flow-v3-report.md)；后续探索 [v4 报告](../../research/2026-10-11-hy30-flow-v4-report.md)（`mbr8c` 已确认但未采纳）。
