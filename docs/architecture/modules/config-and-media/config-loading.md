---
covers:
  - kototoki/config.py
---
# 配置与媒体子页：配置读取与校验

`配置与媒体` 的子页：`Config` 的读取行为。配方常量与 `recipe_hash` 见[配方常量与 recipe_hash](recipes.md)。

**配置**（`kototoki/config.py`，`load(path, *, environ=os.environ) -> Config`）：`tomllib` 读取，缺省键取 `config.DEFAULTS`，返回全部路径已解析为绝对路径的冻结数据类。键表、默认值与逐键校验见[配置参考](reference.md)；本页只写读取行为。

- `paths.input_dir` 没有默认值，必须写出；其余键缺省取默认值。
- 未知节、未知键（含已删除的键）、类型不符（整数键给字符串、布尔键给 1 等）、`stt.engine` 不是 `w0`／`x0`／`cross`（`config.ENGINES`）、`run.extract_workers < 1`、`[translate]`／`[names]` 的 `seed` 不满足 0 < seed < 2**31 均抛 `ConfigError`，消息给出键名；浮点键接受整数。TOML 语法错误与文件读不到同样抛 `ConfigError`。
- 路径：用户写出的相对路径按配置文件所在目录解析，省略键的默认相对路径按仓库根解析；`[vad]`、`[asr.w0]`、`[asr.x0]`、`[align]` 的模型路径为相对路径时相对于 `paths.models_root`（绝对路径原样）。
- `load` 只解析路径，不看文件系统；`input_dir` 存在性与位置、`work_dir` 位置由 `__main__` 的 `check_input_dir`／`check_work_dir` 检查（[批次编排](../batch-orchestration.md)）。
- 不可配置：GPU 锁固定为仓库内 `.local/gpu.lock`（`Config.gpu_lock`）；`Config.break_stale_lock` 只在环境变量 `KOTOTOKI_BREAK_STALE_LOCK=1` 时为真。
- `[input] use_embedded_subtitles` 不进任何产物身份：走哪条路径由产物本身体现。
- 翻译与建表只有 `seed`；模型由 Strata 管理、端口固定 8080，没有 `model`／`port` 键；建表的提示、采样、schema 与归一规则在 `kototoki/names/recipes.py`，不是配置项。

## 代码与验证入口

- 代码：`kototoki/config.py`、`kototoki.toml.example`。
- 测试（core，`mise run test`）：`tests/core/test_config.py`：见[配置参考](reference.md#代码与验证入口)。
