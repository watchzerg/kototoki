# 02 配置、配方常量与媒体提取

Status: done
Type: task
Blocked by: 00

## 范围

- 架构（[目标架构](../../../docs/architecture/bilingual-pipeline-architecture.md)"配置与配方""媒体"行）：`load(path) -> Config`；`probe(path) -> Probe`、`extract(path, work_dir, probe) -> Extract` 返回结果对象，只产生 ffmpeg 自身的输出文件（WAV、`extract.log`）；`probe.json` 等 JSON 产物的身份包装与写入、是否跳过，由编排经产物契约完成，媒体模块不读写 JSON 产物、不判断跳过。媒体是唯一定义时间轴零点的模块。
- `kototoki/config.py`：`tomllib` 读取 `kototoki.toml`（规格 §10.1），缺省填默认、未知键报错；用户写的相对路径按配置文件目录解析，省略键的默认相对路径按仓库根解析；GPU 锁路径固定不可配，`KOTOTOKI_BREAK_STALE_LOCK` 由环境变量读取；没有 `break_stale_lock`、`[vad] device` 键；`kototoki.toml.example` 入库。
- `kototoki/recipes.py`：VAD（含固定设备 `cuda:0`）、w0、x0、MMS、cue、媒体（下混 `pan` 表达式、重采样参数）的配方常量与 `recipe_hash`。**不含翻译配方**（归 `kototoki/translate/recipes.py`，05／09）。
- `kototoki/media.py`：
  - `probe`：全部流；音轨选择规则（`language` 归一化后等于 `jpn`（接受 `jpn`／`ja`／`jp`）且非 `disposition.comment` 优先，再 `disposition.default`；多条匹配告警；无匹配取第一条并告警）；记录绝对流索引、编码、声道布局、音轨与容器 `start_time`（只作诊断）、时长、视频流时长、字幕流清单。
  - `extract_original`：`-c:a copy`，容器映射规格 §2.1（小端 PCM 才用 `.wav` 含 RF64，其余 `.mka` 回退）。
  - `derive_pcm16k`：**从视频容器**按绝对流索引解码，`-af aresample=async=1:first_pts=0,<pan 常量>,aresample=16000`，`pcm_s16le`，默认 swr；`-loglevel verbose` 写入 `extract.log` 并记录补偿量（实测 swr 是否报告，记入 Comments）；`offset_s = 0`；校验解码时长对**视频流时长**：短于 1 s 以上判失败，长于只告警；记录 PCM SHA256、样本数。
  - 下混 `pan` 常量：单声道直通；双声道 `pan=mono|c0=0.5*c0+0.5*c1`；5.1 及以上用标准系数（前左右 1、中置 0.707、环绕 0.707、丢 LFE）并除以系数和归一化；不用 `-ac 1`。
  - 子进程参数列表、`-nostdin`、显式编码；路径含空格与非 ASCII。

## 完成标准

- 离线 unittest（`tests/`）：配置（含默认路径解析、未知键、环境变量破锁）、容器映射、语言标签归一化、音轨选择（含 commentary、多 jpn、无 jpn 样本）、命令行构造、`pan` 常量进 hash；用 ffmpeg 合成的测试媒体覆盖：音轨延迟 0.5 s（**断言派生 WAV 前 0.5 s 为静音且后续阶段 cue 时间等于视频时间**）、中途 2 s 间隙、5.1 满幅不削波、单声道、立体声、视频比音频长 2 s（告警不失败）。
- 真实视频产出三份产物；用 II 的原始 FLAC 派生 WAV 与现有 `hf-ii-full.wav` 对照（默认 swr 下 PCM SHA256 应一致）。

## 文件所有权

`kototoki/config.py`、`recipes.py`、`media.py`、`kototoki.toml.example`、对应测试。

## Comments

- 2026-10-13 建票，依据规格 §12。
- 2026-10-14 按两轮评审修订（规格 §13）。
- 2026-10-14 第三轮评审：`offset_s` 恒为 0；时长校验对视频流；verbose 日志；`pan` 常量；语言标签归一化；小端 PCM 映射；配置键增删；翻译配方移出。
- 2026-10-14 实施（分支 `feat/bilingual-02`，worktree `../kototoki-02`）：
  - 新增 `kototoki/config.py`、`recipes.py`、`media.py`、`kototoki.toml.example`，测试 `tests/test_config.py`、`test_recipes.py`、`test_media.py`、`test_media_ffmpeg.py`；新建模块页 `docs/architecture/modules/config-and-media.md`，同步架构总览、模块边界、目标架构、workflow、规格 §2.2。
  - **接口偏离（已先改目标架构页）**：`probe(path, config)`、`extract(path, work_dir, probe, config)` 多一个 `config` 参数（提供 ffmpeg／ffprobe 路径与音轨语言偏好）；失败统一抛 `MediaError`。
  - **swr 实测**：`-loglevel verbose` 下 swr 报告 `adding N audio samples of silence`（及 `discarding N audio samples`），但只报一部分：合成 0.5 s 延迟报全（24000 样本），合成 2 s 间隙只报 30448 样本（约 0.63 s），WAV 实际补齐了 2 s。因此 `Extract.compensation` 另记 `net_padding_s`（派生时长 − ffmpeg 结束统计的输入样本时长），以它为准。
  - **视频流时长**：Matroska 视频流没有 `duration`，取 `tags.DURATION` 或 mkvmerge 的 `DURATION-<lang>`；都没有才退回容器时长并告警。
  - **真实视频**：HF II mkv（FLAC 立体声）三份产物齐全，派生 WAV PCM SHA256 `ee4e2da3…` 与 `hf-ii-full.wav` 一致（112448683 样本，默认 swr，滤镜链多出的 `aresample=async=1:first_pts=0` 对无间隙源不改样本）；Black Panther mkv（12 条音轨，选中 jpn E-AC-3 5.1(side)）产出 `audio.eac3`＋WAV＋日志。产物在会话 scratchpad，不进仓库。
  - **与票据文字的冲突，按规格 §1.2 实现**：完成标准写"视频比音频长 2 s（告警不失败）"，但 §1.2 裁定是"解码短于视频超过 1 s 判失败，长于视频只告警"。实现按裁定：音频比视频短 2 s → 失败；音频比视频长 2 s → 告警；两种都有测试。"长于视频只告警"也用 1 s 容差，避免毫秒级差异刷告警。
  - 自行裁量：`paths.input_dir`／`output_dir` 设为必填（规格示例值是机器专用路径，不当默认）；`ffmpeg`／`ffprobe` 默认按规格取 `D:/bin/*.exe`；`6.1`、`7.1` 也给了 `pan` 常量，`5.0`／`quad` 等未列布局报错；单声道用 `anull`。
  - 遗留：(1) "cue 时间等于视频时间"目前在 WAV 样本层断言（`sample/16000 + offset_s`），经 cue 阶段的断言留给 04；(2) `recipes.CUES` 只写了规格已定的算法项，04 的整窗 `fallback` 每字符时长上限等数值尚无定值，`recipes.py` 归 02 所有，04 需要改它时要明确归属；(3) `.gitignore` 未忽略用户的 `kototoki.toml`（不在本票文件所有权内）；(4) 广播 `.ts`（绝对 `start_time`、负延迟、PTS 回绕）与 6.1／7.1 无真实样本；(5) 合成测试发现：48 kHz 满幅方波经默认 swr 降到 16 kHz 会过冲到 −32768，`pan` 本身不削波，5.1 测试改用 16 kHz 源只验证下混系数；是否需要在重采样前留余量（会改变与基线的逐字节一致）待用户裁定。
- 2026-10-14 来自票据 04（用户裁定）：`[cues] max_gap_s` 默认值改为 **1.0**（规格 §5.2／§10.1 已改，`kototoki.toml.example` 随之）；`kototoki/cues.py` 的 `FALLBACK_MAX_CHAR_S = 0.25`（整窗 `fallback` 每字符时长上限）会改变输出，须由本票收编进 cue 配方 hash（迁入 `recipes.py` 后让 `cues.py` 导入，或在 hash 中纳入该常量）；`build_cues` 的 `rules` 参数是与 `[cues]` 表同形的映射，键集合严格，配置直接传入即可。
- 2026-10-14 用户裁定：(1) 时长规则按 §1.2 实现、长于视频也用 1 s 容差——认可；(2) 重采样质量待讨论（实测两部真实影片派生 WAV：HF II 1.12 亿样本中 1 个样本到满幅，Black Panther 峰值 31073、无削波）；(3) 04 可修改 `recipes.py` 的 `CUES` 节；(4) 必填路径、`D:/bin` 默认、未列布局报错由实现方定，维持现状；(5) `.gitignore` 不加 `kototoki.toml`。
- 2026-10-14 用户裁定重采样改 soxr 28 bit（`aresample=16000:resampler=soxr:precision=28`）：先在 HF II 整片对比 swr／soxr20／soxr28，6 kHz 以下差异约 −79 dB（相对信号），差别只在 7.8–8 kHz 边缘（swr 残留折叠），削波无差别。完成标准"默认 swr 下 PCM SHA256 应一致"在切换前已满足（`ee4e2da3…`），切换后产品派生 WAV 为 `c203f952…`，与基线不再逐字节一致，用户接受。票据 03 门禁读冻结窗口文件，不受影响。规格 §1.2／§2.2／§7.3／§11／§13 与模块页已同步；ADR-0007 的旧句不改写。
- 2026-10-14 合并：先把 main（含票据 04）合入分支，跟进 `max_gap_s` 默认 1.0 并把 `FALLBACK_MAX_CHAR_S` 纳入 `recipes.CUES`（测试钉住相等），再 `--no-ff` 合回 main（`2377ac5`），132 个测试通过；worktree 已移除。
