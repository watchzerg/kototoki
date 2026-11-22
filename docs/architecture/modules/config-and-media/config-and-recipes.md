---
covers:
  - kototoki/config.py
  - kototoki/recipes.py
---
# 配置与媒体子页：配置读取与配方

`配置与媒体` 的子页：`Config` 的读取行为、各配方常量与 `recipe_hash`、cross 引擎配方、下混常量与 `MEDIA` 覆盖范围。

**配置**（`kototoki/config.py`，`load(path, *, environ=os.environ) -> Config`）：`tomllib` 读取，缺省键取 `config.DEFAULTS`，返回全部路径已解析为绝对路径的冻结数据类。键表、默认值与逐键校验见[配置参考](reference.md)；本页只写读取行为。

- `paths.input_dir` 没有默认值，必须写出；其余键缺省取默认值。
- 未知节、未知键（含已删除的键）、类型不符（整数键给字符串、布尔键给 1 等）、`stt.engine` 不是 `w0`／`x0`／`cross`（`config.ENGINES`）、`run.extract_workers < 1`、`[translate]`／`[names]` 的 `seed` 不满足 0 < seed < 2**31 均抛 `ConfigError`，消息给出键名；浮点键接受整数。TOML 语法错误与文件读不到同样抛 `ConfigError`。
- 路径：用户写出的相对路径按配置文件所在目录解析，省略键的默认相对路径按仓库根解析；`[vad]`、`[asr.w0]`、`[asr.x0]`、`[align]` 的模型路径为相对路径时相对于 `paths.models_root`（绝对路径原样）。
- `load` 只解析路径，不看文件系统；`input_dir` 存在性与位置、`work_dir` 位置由 `__main__` 的 `check_input_dir`／`check_work_dir` 检查（[批次编排](../batch-orchestration.md)）。
- 不可配置：GPU 锁固定为仓库内 `.local/gpu.lock`（`Config.gpu_lock`）；`Config.break_stale_lock` 只在环境变量 `KOTOTOKI_BREAK_STALE_LOCK=1` 时为真。
- `[input] use_embedded_subtitles` 不进任何产物身份：走哪条路径由产物本身体现。
- 翻译与建表只有 `seed`；模型由 Strata 管理、端口固定 8080，没有 `model`／`port` 键；建表的提示、采样、schema 与归一规则在 `kototoki/names/recipes.py`，不是配置项。

**配方**（`kototoki/recipes.py`）：`MEDIA`、`VAD`、`W0`、`X0`、`CROSS`、`MMS`、`CUES`、`EMBEDDED` 八个字典；`recipe_hash(recipe)` 是其规范 JSON 的 SHA256（`artifacts.object_hash`），供产物身份的 `recipe_hash` 字段使用。值取自已验证的 demo（来源写在各节注释）。

- VAD：固定设备 `cuda:0`、Pyannote revision `e66f3d3b…`、`source-span-merge-v1`。
- w0：beam 5、FP16、日语、无前文与时间戳 token、128 Mel 特征链，另含整窗守卫块：复读、语速、已知幻听句三个子块（[ADR-0030](../../../adr/0030-asr-window-plausibility-guard.md)）；x0：BF16、SDPA、greedy、4096。
- MMS：FP32、`jpn` adapter、字典按模型类数过滤。
- cue：切分顺序、回填方式、整窗回退每字符时长上限 0.25 s（`CUES["fallback_max_char_s"]`，`cues` 直接读它，没有第二份常量）与毫秒取整；数值规则在配置 `[cues]`，作为影响输出的配置键另入身份。
- `SAMPLE_RATE`、`MAX_WINDOW_SAMPLES` 只在 `recipes.py` 定义。

**cross 引擎的配方**：`cross` 需要 `[asr.w0]` 与 `[asr.x0]` 两节的模型路径，不新增配置键。配方 `CROSS`（id `cross-w0-x0-whisper-judge-v1`，hash 由 `tests/core/test_recipes.py` 钉住）嵌入 `W0` 与 `X0` 两个子配方和裁判参数 `judge`：

- 判定阈值 `margin` −1.0、`length_weight` 0.0（无长度项）、打分批上限 `max_batch` 16。
- 打分器与 start_sequence 约定：`tokenizer.sot_sequence` 即 `<|startoftranscript|><|ja|><|transcribe|>`，CT2 自动接 `<|notimestamps|>`，等价于产品无时间戳、无 initial prompt 的提示。
- 规范化与区间规则；文本形式：w0 原文，只替换分歧区间的字符，映射失败退回规范化文本。
- 守卫：`identical_windows`、`empty_result`、`x0_failed_window`、`w0_failed_window`、`score_error`。
- `x0_text_cleaning`：只清 x0 原文中与非 ASCII 字符相邻的空白，w0 原文不动，实现为 `judge.clean_x0`。
- 裁判参数是配方常量而非配置项，一个 `recipe_hash(CROSS)` 覆盖全部，任一子配方或参数变化即新身份。

**下混常量**（`recipes.PAN`，进 `MEDIA` 因而进 hash）：单声道 `anull` 直通；双声道 `pan=mono|c0=0.5*c0+0.5*c1`；`5.1`、`5.1(side)`、`6.1`、`7.1` 用前左右 1、中置 0.707、环绕 0.707、丢 LFE 的权重除以权重和、向下截到 6 位小数，系数和 ≤ 1，满幅同相输入不削波。ffprobe 未给布局时按声道数取 `mono`／`stereo`／`5.1`／`7.1`（`recipes.LAYOUT_BY_CHANNELS`，嵌在 `MEDIA` 里）；其它布局（如 `5.0`、`quad`）报 `MediaError`。不用 `-ac 1`。

**`MEDIA` 覆盖全部影响音频的规则**（id `media-pcm16k-v2`）：下混常量、声道布局映射、重采样、时长容差、采样率标错纠正规则（`sample_rate_correction`）与音轨选择条目（规则说明＋语言别名表 `LANGUAGE_ALIASES`；别名表定义在 `recipes.py`，`media.py` 读它，内嵌字幕选轨同用它）。

## 代码与验证入口

- 代码：`kototoki/config.py`、`kototoki/recipes.py`、`kototoki.toml.example`。
- 测试（core，`just test`）：
  - `tests/core/test_config.py`：默认值、两种相对路径基准、模型路径、未知键与已删除键、类型、环境变量破锁、示例文件覆盖全部键。
  - `tests/core/test_recipes.py`：`pan` 系数与归一化、不削波、重采样参数、`LAYOUT_BY_CHANNELS`、音轨选择（含 `LANGUAGE_ALIASES`）与采样率纠正规则进 hash、固定值、无翻译配方；`MEDIA`、`VAD`、`W0`、`X0`、`CROSS`、`MMS`、`CUES`、`EMBEDDED` 的 hash 全部钉住。
