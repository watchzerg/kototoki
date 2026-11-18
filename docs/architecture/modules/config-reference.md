# 配置参考：`kototoki.toml`

状态：current（2026-11-11 由[技术设计](../../specs/bilingual-subtitle-pipeline.md) §10 移来，键、默认值与校验已对照 `kototoki/config.py`、`kototoki/__main__.py` 核对）

## 定位与阅读

本页是产品配置文件 `kototoki.toml` 的键、默认值与校验规则的参考。读取配置的代码与配方常量归[配置、配方与媒体提取](config-and-media.md)；各键在哪个阶段生效见对应模块页。入口 `python -m kototoki [kototoki.toml]`，省略参数时读当前目录的 `kototoki.toml`；仓库根的 `kototoki.toml.example` 列出全部键。

## 结构与默认值

下面就是各键的默认值（`config.DEFAULTS`）；只有 `paths.input_dir` 没有默认值、必须写出。

```toml
[paths]
input_dir   = "<影片目录的绝对路径>"     # 必填；递归扫描视频与音频；双语字幕 <主名>.ja-zh.srt 写在源文件旁
work_dir    = ".local/work"             # 缓存与各目标目录的工作根
models_root = ".local/models"           # [vad]、[asr.*]、[align] 的相对模型路径相对于它
ffmpeg      = ".local/tools/ffmpeg/n9.0.2-28-g669f5ab083/bin/ffmpeg.exe"
ffprobe     = ".local/tools/ffmpeg/n9.0.2-28-g669f5ab083/bin/ffprobe.exe"

[input]
extensions = [".mkv", ".mp4", ".m2ts", ".ts", ".mov", ".avi",
              ".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".mka"]   # 大小写不敏感；视频还是音频由 ffprobe 判定
audio_language = "jpn"                  # 优先选此语言的音轨（jpn／ja／jp 视为同一语言），没有则取第一条并告警
use_embedded_subtitles = true           # 有该语言的文本字幕轨（非 forced）时跳过 STT、直接翻译字幕轨（ADR-0024）

[run]
extract_workers = 4                     # extract 线程池大小（ffmpeg 并发数），≥ 1
stable_check_s = 10.0                   # 两次采样文件大小不变才视为写入完成

[stt]
engine = "w0"                           # w0 | x0 | cross（cross 用 [asr.w0] 与 [asr.x0] 两路模型）

[vad]
model = "vad-comparison/pyannote-segmentation-3.0/pytorch_model.bin"   # 设备固定 cuda:0，没有配置键

[asr.w0]
model      = "faster-whisper-large-v3"
mel_assets = "w0-assets"

[asr.x0]
model = "qwen3-asr-1.7b-hf"

[align]
model = "mms-1b-all"

[cues]
max_chars = 24
max_duration_s = 6.0
min_duration_s = 0.8
max_gap_s = 1.0
sentence_endings = "。！？!?"
soft_breaks = "、，,"
lead_out_s = 0.3

[translate]
seed = 20261008                         # 0 < seed < 2**31；改 seed 即另起翻译 run、整片重译

[names]
seed = 20261019                         # 0 < seed < 2**31；改 seed 即重建专名表
```

`[cues]` 各键的含义与切分规则见[日文 cue](japanese-cues.md)：

| 键 | 默认 | 含义 |
| --- | --- | --- |
| `max_chars` | 24 | 单条 cue 的日文字符数上限（非空白码点数，含附着的标点）；双语显示时日文只占一行 |
| `max_duration_s` | 6.0 | 单条 cue 显示时长上限 |
| `min_duration_s` | 0.8 | 加完 `lead_out_s` 仍不足此值的 cue 延长到此值，不越过下一条起点 |
| `max_gap_s` | 1.0 | 相邻词汇字符之间的正间隔超过此值、且该间隔不整个落在同一个 VAD 子段内时断开 |
| `sentence_endings` | `。！？!?` | 遇到即断开 |
| `soft_breaks` | `、，,` | 超过 `max_chars` 时优先在这些字符后断 |
| `lead_out_s` | 0.3 | cue 结束时间向后延长的秒数，不越过下一条起点 |

## 读取与校验

- 未知节、未知键报错（`ConfigError`，消息给出键名），不忽略；已删除的键（`[paths] output_dir`、`llama_server`，`[input] video_extensions`，`[run] force`，`[translate] model`／`port`，`[names] enabled`／`model`／`port`，`break_stale_lock`，`[vad] device`）同样按未知键报错。
- 类型按默认值的类型校验：字符串键须为非空字符串；布尔键只收 `true`／`false`；整数键不收布尔与浮点；浮点键也收整数；`extensions` 须为非空字符串列表。
- 取值校验：`stt.engine` 只收 `w0`／`x0`／`cross`；`run.extract_workers` ≥ 1；`[translate] seed` 与 `[names] seed` 须满足 0 < seed < 2**31（Strata 不接受 0）。TOML 语法错误与文件读不到都报 `ConfigError`。`[cues]` 的数值范围（`max_chars` ≥ 1、`max_duration_s` > 0、其余时长 ≥ 0）不在读取时检查，由 ja-cues 阶段的 `cues.build_cues` 检查，不合法时该阶段报 `ValueError`。
- 路径：用户写出的相对路径按配置文件所在目录解析；省略的键用默认值，其中相对路径按仓库根解析（配置文件放仓库外时默认模型目录与 ffmpeg 仍可用）。`[vad]`、`[asr.w0]`（含 `mel_assets`）、`[asr.x0]`、`[align]` 的模型路径为相对路径时相对于 `paths.models_root`。
- 启动检查（`__main__`，失败即退出码 2）：`input_dir` 必须是已存在的目录，且不得位于仓库内（`.local/` 除外）；`work_dir` 不得位于仓库内（`.local/` 除外），也不得位于 `input_dir` 内（含二者相同）。
- 不可配置：GPU 锁固定为仓库内 `.local/gpu.lock`；破除残留锁只认环境变量 `KOTOTOKI_BREAK_STALE_LOCK=1`，只对本次运行生效（配置里的开关是粘性的，每次都会自动破锁，因此不放配置文件）。翻译与建表的模型由 Strata 管理、端口固定 8080，没有对应键。

## 暴露与冻结的边界

配置文件只放用户关注、不改变模型行为的项；影响模型行为的常量留在代码里，改动即新配方 hash。

| 放配置文件 | 留在代码（`kototoki/recipes.py`、`kototoki/translate/recipes.py`、`kototoki/names/recipes.py`） |
| --- | --- |
| 所有路径、模型目录、二进制位置（GPU 锁路径除外） | VAD onset／offset、30 s 窗口与合并策略、设备 `cuda:0`、下混矩阵与重采样参数 |
| extract 并发数、文件稳定性采样间隔 | w0：beam 5、FP16、日语、无前文、无时间戳、复读守卫；x0：BF16、greedy、4096；cross：裁判阈值 −1.0、无长度项、打分批上限 16（配方 `CROSS`） |
| 输入扩展名、音轨语言偏好、是否用内嵌字幕 | MMS FP32、归一化、字符映射；内嵌字幕清洗规则（`EMBEDDED`） |
| cue 显示规则（`[cues]`） | 翻译采样（0.7／0.8／20）、`dp10-cut` 切包与 `wide-context-v1` 邻文、`qwen-joint-v1` 提示、专名注入规则、模型与 Strata 身份核对、请求重试次数、失败分类、降级策略 |
| 翻译 `seed`、专名表 `seed` | 建表提示、采样、JSON schema、`max_tokens` 16384、context 49152（提示预算 32256）、5 次尝试与重试条件、归一规则、模型与 Strata 身份（配方 `q3-names-v3`，ADR-0026、ADR-0028）；产物 schema 版本 |

## 配置与产物身份

只改配置文件里的项一般不会使已有 STT 产物失效；进身份的键如下（身份规则见[产物契约](artifact-contract.md)与[阶段计划](stage-plan.md)）：

- `[cues]` 全部键进 `ja-cues.json` 的身份：改了只重跑 ja-cues 及之后。
- `[names] seed` 进 `name-table.json` 的身份；`[translate] seed` 进翻译身份与 run 目录键（`<配方名>__s<seed>__n<表sha12>`）。
- `[input] audio_language` 进 `probe.json` 的身份；`[stt] engine` 决定 asr 阶段用哪个配方 hash。
- 模型路径本身不进身份，进身份的是模型文件的 SHA256。
- `use_embedded_subtitles` 不进任何身份：走哪条路径由产物本身体现。

## 代码与验证入口

- 代码：`kototoki/config.py`（`DEFAULTS`、`load`、`ConfigError`、`ENGINES`）、`kototoki/__main__.py`（`check_input_dir`、`check_work_dir`）、`kototoki.toml.example`。
- 测试（core，`just test`）：`tests/core/test_config.py`（默认值、两种相对路径基准、模型路径、未知键与已删除键、类型、环境变量破锁、示例文件覆盖全部键）。

## 变更与决策来源

原为技术设计 §10（文档架构整理票据 09，`.scratch/docs-architecture/`）；该节此前的修订见技术设计历史记录（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`）。键的增删依据：[ADR-0012](../../adr/0012-cross-asr-judge.md)（`cross`）、[ADR-0019](../../adr/0019-product-translation-q2.md)、[ADR-0020](../../adr/0020-media-inputs-work-dir-and-side-by-side-publish.md)、[ADR-0022](../../adr/0022-product-names-on-strata.md)、[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)。
