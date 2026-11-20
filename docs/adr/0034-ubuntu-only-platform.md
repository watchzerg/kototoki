# ADR-0034：只面向 Ubuntu，工具链与外部前置按 Linux 原生做法重定

状态：已接受，2026-11-20（用户裁定），实现中：代码、脚本与文档已按本决定改完，Linux 上的真实模型验收（fetch-models、smoke、小批量）待做；验收通过后删掉"实现中"字样。
替代关系：
- 取代 [ADR-0033](0033-ffmpeg-branch-lock.md) 全文；
- 取代 [ADR-0029](0029-translate-per-cue-resolution.md)「Strata session」第 4 点与第 8 点中有关版本的部分；
- 取代 [ADR-0021](0021-q3-strata-names-baseline.md)「Q3 服务与运行顺序」第 1 点中有关版本的部分。

范围：
- 支持哪个平台；
- 工具链分层：mise、uv、just、Python；
- 外部前置：NVIDIA 驱动、ffmpeg、Strata；
- `assets.toml` 与安装、升级入口；
- Strata 版本怎么核对，以及它和配方身份的关系；
- 子进程清理与长任务运行方式。

不改：翻译与建表的请求规则、STT 配方、基线定义，以及 W0／X0 基线身份。

## 决定

### 平台

1. **只面向 Ubuntu**（x86_64、NVIDIA GPU，本机为 RTX 5080）。代码、脚本、文档与工具选型都按 Linux 原生做法设计。不写 Windows／macOS 分支，不保留兼容垫片，也不为它们补测试。Windows 时期的写法一律清理，包括 pwsh recipe、`%LOCALAPPDATA%`、`.exe` 路径、ctypes `WinDLL`、Job Object 和文件占用重试。
2. **不与 Windows 时期的结果比对。** Linux 上的 smoke、产物与跑次重新建立基线。Windows 时期的验收记录与跑次只作历史，不作对照。
3. **不迁移旧数据。** 模型由 `just fetch-models` 重新下载；工作目录、缓存与跑次产物都从零开始。工作根 id 不再对路径做 `normcase`。

### 工具链分层

1. **mise 是唯一需要另装的系统工具。** `mise.toml` 钉 uv 与 just 的版本，一次性准备步骤是 `mise trust && mise install`，并在 shell 里激活 mise。
2. **Python 由 uv 管理：** 解释器版本按 `.python-version`（`3.13`），Python 依赖按 `uv.lock`。采用 uv 的默认布局：解释器在 uv 的共享目录，项目依赖在仓库的 `.venv/`。不再把解释器和 uv 缓存放进仓库 `.local/`。
3. **`pyproject.toml` 只锁 Linux**：`[tool.uv] environments` 改为 `sys_platform == 'linux'`。
4. **`check-toolchain` 照旧核对** uv、just 与 Python 的版本是否符合项目文件。

### 外部前置

以下三项由用户自行安装与维护，项目不负责安装，只在文档里写明，并在运行时核对：

- NVIDIA 驱动；
- ffmpeg：用 apt 安装的系统包；
- Strata：0.2 版本线，连同模型 `qwen3.8-flash-next-iq3_s`。

### ffmpeg

1. **用系统包。** 配置里 `[paths] ffmpeg`／`ffprobe` 的默认值是命令名 `ffmpeg`／`ffprobe`，从 PATH 查找；用户写了路径时按路径使用。
2. **运行日志首行记实际版本**（沿用 ADR-0033 的做法）：`[run] start: … ffmpeg=<ffmpeg -version 报的版本>`，取不到时记 `unavailable`。
3. **清单与入口相应缩小：**
   - `assets.toml` 只列产品用到的 STT 模型，删掉 `[tools]` 段；
   - `scripts/assets.py` 删掉工具安装；
   - `just install` 只做 `uv sync --locked`；
   - `scripts/upgrade.py` 只升 Python 依赖。

### Strata 版本

1. **只锁 0.2 版本线。** 接入检查要求 `strata --version` 报告的版本以 `0.2.` 开头，不再钉引擎 build。
2. **实际版本只记录，不进配方身份。** 实际的 version 与 build 写进 session 的 `strata.json` 和运行日志，但不进翻译配方（`q3-translate-*`）或建表配方（`q3-names-*`）的 runtime 身份。所以 0.2 线内升级 Strata 不会让已有产物过期，也不会触发重译。
3. **功能核对保留不变：** 本机 8080、run config 的模型名与 `--max-context 131072`、DFlash2、`/v1/models`、`/v1/status` 原生上下文 131072、专家区在内存（`ram`）。
4. **按 Linux 上的位置和日志写法核对：**
   - Strata 的状态目录在 `$XDG_STATE_HOME/strata/`（默认 `~/.local/state/strata/`），服务日志在其下的 `runtime/`，引擎日志在 `launch/`；
   - CLI 直接用 PATH 上的 `strata`；
   - 专家区的判据：日志里有 `expert arena: cudaHostRegister … ok`，且没有退到 mmap 的标记，才算 `ram`；
   - 可用内存读 `/proc/meminfo` 的 `MemAvailable`。`MIN_AVAILABLE_RAM_GIB` 的数值等 Linux 上第一次产品运行的证据出来后重新标定。
5. **基线 Q3 的服务身份随之改为**"Strata 0.2 版本线、默认启动（IQ3_S、128K、DFlash2、本机 8080）"。Windows 时期的 Q3 证据来自 0.2.12／build 0.1.58，照原样保留为历史。

### 子进程与长任务

1. **编排器以任何方式退出，ffmpeg 和 GPU worker 子进程都不能留下来占显存。**
   - 子进程经 `setpriv --pdeathsig KILL` 启动（`PR_SET_PDEATHSIG`），父进程一死就跟着结束；不在 Python 里用 `preexec_fn`，因为编排器有提取线程池，`preexec_fn` 在多线程进程里不安全；
   - GPU worker 与 Strata CLI 各自新开进程组，Ctrl+C 只由编排器处理，由它收尾；ffmpeg／ffprobe 留在前台进程组，Ctrl+C 让它们立即退出，提取线程池不必等整部影片解码完；
   - 锁文件防 pid 复用，改为比对 `/proc/<pid>/stat` 记下的进程启动时间（starttime）。
   - Strata 服务由 Strata 自己放在后台，仍靠 `strata launch --stop` 收尾，与以前相同。
2. **长任务**（整批运行、smoke）推荐用 `systemd-run --user --unit=<名字>` 启动，日志进 journal，用 `systemctl --user status|stop` 查看与停止，停止时整组进程一并清理。
3. **主机锁**：`gate-full`／`test-full` 经 `scripts/with_lock.py`（`flock`）串行执行。

## 身份

- 平台：Ubuntu 26.04 LTS、x86_64、RTX 5080，裁定时驱动 595.99.02。
- Strata：0.2 版本线，裁定时本机为 0.2.13.1／build 0.1.59.1。
- ffmpeg：系统包，裁定时为 `8.0.1-3ubuntu2+esm5`。
- 配方：`q3-translate-v1` 与 `q3-names-v3` 的 runtime 身份去掉 `strata`／`engine_build` 两个字段（2026-11-20 实现）。配方 id 不变，因为旧数据不迁移，不存在新旧产物混用的情况。
  - `q3-translate-v1` 的 `RECIPE_HASH` 为 `1372b37146babf6817ffeacf4d0019af5eec319dc19cf7d62a1d5f1f7fde577d`（Windows 时期 `865bcd1d…`）；
  - `q3-names-v3` 的 hash 为 `bcb9bebc5274d88a5f3737559b4ab77afa7278afc6d6196c77aad07b12acd072`（Windows 时期 `d57ed0c6…`）；
  - 基线 `names-strata-v4` 的 hash `38cb7bcd…` 不变，测试拼回 v4 形状时补回 0.2.12／0.1.58 两个字段。

## 依据

- 运行机器从原生 Windows 换成了 Ubuntu。用户定的原则是全新开始，按 Linux 原生的优雅做法来，不受 Windows 时期的做法、ADR 与历史数据约束（2026-11-20）。
- **ffmpeg 不必锁版本或分支。**
  - 产品只用 ffmpeg 做 probe、解码成 16 kHz PCM 与抽取字幕轨，Ubuntu 包里的解码器已经够用。
  - 下游产物按 `audio-16k.wav` 的内容 hash 判断是否过期。ffmpeg 变了只会触发重算，不会串缓存。
  - LTS 期间系统包只打安全补丁。
  - ADR-0033 的下载、分支锁与 `identity.json` 那一套，原本是为了解决 Windows 上没有包管理器。
- **Strata 只锁版本线。** 真正决定翻译行为的是模型、上下文、草稿方式和专家区位置，这些都逐项核对。精确版本进身份的话，每次升级都要整批重译；只记录不进身份，事后仍能从证据追溯。
- **工具分层**让 mise 成为唯一需要另装的工具，其余版本都由仓库文件决定；采用 uv 默认布局，是因为解释器不必每个仓库存一份。
- **专家区的日志写法在 Linux 上不同**（2026-11-19 本机 `iq3_s-128k.engine.log`）：Linux 用 `cudaHostRegister` 锁定，不受 `ulimit -l` 限制，日志里没有 Windows 的 `expert arena: locked`。
- **Linux 上没有 Job Object。** 必须另有机制，才能守住"不留占显存的孤儿"。

## 未验证与已知限制

尚未实现，以下都要在实现与验收时确认：

- torch、torchaudio（cu128）、torchcodec、ctranslate2、pyannote.audio 在 Linux 上的 wheel 能否锁定；
- CTranslate2 能否加载 cuBLAS／cuDNN 的 `.so`（Windows 时期验证的是 DLL 加载顺序）；
- 本机能否装上 mise 钉住的 uv、just 版本；
- 第一次 smoke 与产品运行的结果，以及新的内存阈值。

## 沿革

- 2026-11-20：从原生 Windows 迁到 Ubuntu，取代 ADR-0033，并修订 ADR-0029、ADR-0021 中的 Strata 版本条款。
