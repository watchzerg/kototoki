# 01 从原生 Windows 迁到 Ubuntu：改动面探查

Status: needs-triage
Type: research

## 背景

仓库的验证目标一直是原生 Windows（pwsh、RTX 5080）。本机现已换成 Ubuntu，本票只做探查：列出要改的地方、需要用户裁定的事项和风险，不改代码。探查时间 2026-11-20，基线 `7edc394`。

### 本机现状（只读探查，没装任何东西）

| 项 | 本机 | 仓库钉的版本或假设 |
| --- | --- | --- |
| OS | Ubuntu 26.04.1 LTS, x86_64 | 原生 Windows |
| GPU | RTX 5080, 16303 MiB, driver 595.99.02 | 同卡；`MIN_FREE_MIB = 14000` |
| 内存 | 共 60 GiB，探查时可用约 52 GiB | `MIN_AVAILABLE_RAM_GIB = 52.0`（按 Windows 实测标定） |
| Strata | **0.2.13.1 / build 0.1.59.1**，装在 `~/.local/share/strata`，状态目录在 `~/.local/state/strata/{runtime,launch}`，`iq3_s` 已安装 | **0.2.12 / build 0.1.58**，`%LOCALAPPDATA%\Strata` |
| uv / just | uv 0.13.8, just 1.45.0 | `mise.toml`：uv 0.13.0, just 1.58.0 |
| Python | 本机只有 3.14；3.13 要由 uv 下载 | `.python-version` 3.13.16 |
| ffmpeg | 系统自带 8.0.1（Ubuntu 包） | BtbN 9.0 分支 win64 构建（ADR-0033） |
| `.local/` | 不存在：没有模型、没有工作目录 | — |

## 已定（2026-11-20，用户）

大原则：Ubuntu 上是全新开始，按 Linux 原生的优雅做法解决问题，不受 Windows 时期的做法、ADR 与历史数据约束。

1. **只支持 Ubuntu**，删掉全部 Windows 分支，不保留兼容。`AGENTS.md` 已加"平台"一节，GPU 锁核实方式也改成了 `ps`／`pgrep`。
2. **Strata 只锁 `0.2` 版本线**。去掉 engine build 的钉版，实际的 version、build 记进 `strata.json` 和运行日志，**不进**翻译和建表配方的 runtime 身份，所以升级 Strata 不会触发重译。`probe` 的功能核对保留：模型、端口 8080、上下文 131072、DFlash2、专家区。
3. **ffmpeg 用 apt 装的系统包**（用户已装好，`/usr/bin/ffmpeg` 8.0.1）。配置默认值改成从 PATH 查找 `ffmpeg`／`ffprobe`，实际版本照旧记进运行日志。删掉 `assets.toml` 的 `[tools]` 段，以及 `assets.py`、`upgrade.py` 里下载、解包和升级 ffmpeg 的代码，ADR-0033 作废。这样做的理由：
   - 产品只用 ffmpeg 做 probe、解码成 16 kHz PCM 和抽字幕轨，Ubuntu 包里的解码器已经够用；
   - 下游产物按 `audio-16k.wav` 的内容 hash 判断是否过期，即使 ffmpeg 升级改变了输出，也只会触发重算；
   - LTS 内的 ffmpeg 只打安全补丁，主版本不变。
4. **不要求与 Windows 结果一致**。Linux 上的 smoke 和产物重新建立基线，不与 Windows 时期的数据比对。
5. **旧数据不迁移**。模型由 `fetch-models` 重新下载；工作目录、缓存、跑次产物都从零开始。`artifacts.py` 和 `job.py` 里的 `normcase` 一并删掉。
6. **工具分层**：mise 是唯一的系统外部依赖，其余都由项目控制。
   - mise 按 `mise.toml` 钉 uv 和 just；
   - uv 按 `.python-version` 管 Python 解释器，按 `uv.lock` 管 Python 依赖；
     - 用 uv 的默认布局：解释器装在 uv 的共享目录（`~/.local/share/uv/python/`），同一版本只装一份；项目依赖装在仓库的 `.venv/`，`.venv/bin/python` 链接到共享解释器。不再把解释器和 uv 缓存放进 `.local/`。
   - ffmpeg、NVIDIA 驱动和 Strata 是用户自装的外部前置，文档写明即可，不由项目安装。
   - 落地时要做的事：
     - 删掉 `mise.toml` 的 `[env]` 里把 uv 缓存和 Python 装进仓库 `.local/` 的配置，改用 uv 默认目录，版本仍由项目文件决定；
     - `.python-version` 放宽到 `3.13`；
     - `mise.toml` 钉的 uv 和 just 版本按 `mise install` 时的最新稳定版重定；
     - `check-toolchain` 照旧核对版本；
     - 文档写明一次性准备步骤：`mise trust && mise install`，并在 shell 里激活 mise。
7. **进程清理**：worker 和 ffmpeg 用 `PR_SET_PDEATHSIG`（父进程一死就收到 SIGKILL），并各自成一个进程组（`start_new_session`），这样 Ctrl+C 只由编排器处理，再由编排器负责收尾。锁文件防 pid 复用改读 `/proc/<pid>/stat` 的 starttime。`procs.py` 里的 Job Object 和 ctypes 部分删除。
8. **长任务**：整批运行和 smoke 推荐用 `systemd-run --user --unit=<名字>` 启动，它自带 journal 日志、`systemctl --user status|stop` 和整个 cgroup 的清理；交互式调试可以用 tmux。`workflow.md` 里"Windows 上的长任务与 worktree"一节按此重写。
9. **主机锁**：`with_lock.py` 接到 `gate-full`／`test-full` 上。

## 专家区与内存（第二轮探查，已澄清）

用户手工 `strata launch` 一直正常，问题不在 Strata 能不能跑，而在**产品对 Strata 的核对是按 Windows 日志写的**。查本机日志 `~/.local/state/strata/launch/iq3_s-128k.engine.log` 的结论如下：

- Linux 上专家区靠 `cudaHostRegister` 锁定，不用 `mlock`，日志写的是 `expert arena: cudaHostRegister PORTABLE ok`，所以不受 `ulimit -l` 限制。第一轮列出的 memlock 风险不存在。
- 但这行里**没有** `expert arena: locked`，而产品的 `ARENA_LOCKED` 正是匹配这个字符串，所以会判定"无法确认"，然后 `StrataRefused`。核对规则要按 Linux 日志重写：看到 `cudaHostRegister ... ok` 并且没有 mmap 退化标记，才算 `ram`。
- 日志里的 `MAP_HUGETLB unavailable (vm.nr_hugepages=0)` 和 `transparent huge pages requested` 只是性能提示。预留 2 万多个 2 MiB 大页会长期占住约 47 GiB 内存，对 60 GiB 的桌面机不合适，不做。
- 内存门槛 `MIN_AVAILABLE_RAM_GIB = 52.0` 的检查逻辑保留，改为读 `/proc/meminfo` 的 `MemAvailable`。阈值等第一次产品运行的证据（`resources.json` 的内存峰值）出来后再重新标定。

## 改动清单

### 依赖与工具链

- `pyproject.toml`：`[tool.uv] environments = ["sys_platform == 'win32'"]` 要改为包含（或只保留）`sys_platform == 'linux'`，然后重新生成 `uv.lock`（`uv lock`／`uv sync` 会改环境并联网，先问）。torch、torchaudio 的 cu128 索引有 Linux wheel；torchcodec 0.17.0、ctranslate2 4.8.3、pyannote.audio 4.0.7 在 Linux 上的 wheel 和 CUDA 依赖需要在锁定时逐项确认。
- **CTranslate2 的 CUDA 库加载**（风险最高）：`kototoki/asr_whisper.py` 的模块说明和 smoke `ct2_after_torch` 都建立在 Windows 的机制上，即 cublas、cudart 来自 torch，CT2 按全路径加载自带的 `cudnn64_9.dll`。Linux 上 CT2 wheel 通常依赖系统里或 `nvidia-*` pip 包提供的 `libcublas.so.12`、`libcudnn*.so.9`，未必在默认的加载路径上。可能需要先 `import torch` 预加载，或者设 `LD_LIBRARY_PATH`。cuDNN 9.10 和 9.19 并存（2026-10-14 用户接受的结论）在 Linux 上也要重新确认。
- `mise.toml`：按已定 6 改。删掉 `[env]` 里指向仓库 `.local/` 的 uv 缓存和 Python 目录配置，uv 和 just 的版本重新钉定。
- `docs/development/technology-stack.md` 里"CUDA 12 锚点"的选版规则要补上 Linux wheel 的情况；`scripts/upgrade.py` 的 `ANCHORS` 逻辑本身与平台无关。

### 产品代码 `kototoki/`

- `procs.py`
  - `process_created()` 在非 Windows 平台上直接返回 None，锁文件因此失去防 pid 复用的保护。可以改读 `/proc/<pid>/stat` 第 22 字段 starttime。
  - `contain_children()` 在非 Windows 平台上什么也不做，编排器异常退出时 GPU worker 和 ffmpeg 会成为孤儿并占着显存，必须修。做法见已定 7。
  - 模块说明和 ctypes `WinDLL` 那部分（删除）。
- `job.py`
  - worker 由 `subprocess.Popen` 启动（约 439 行）。POSIX 上 Ctrl+C 产生的 SIGINT 会发给整个前台进程组，worker 也会同时收到 `KeyboardInterrupt`。这和 Windows 的行为不同，中断与清理路径需要重新验证。
  - 约 762 行用 `os.path.normcase` 判断"只差大小写的改名"冲突。Linux 上 `normcase` 不做任何转换，语义随之改变（票 `architecture-review/14` 的场景），需要确认这正是想要的行为。
- `strata.py`
  - `strata_cmd()` 写死 `%LOCALAPPDATA%\Strata\...\strata.cmd`。Linux 上 PATH 里的 `strata` 是 sh 启动器，直接用即可。
  - `LOG_DIR` 和 `ENGINE_LOG_DIR` 写死 `%LOCALAPPDATA%\Strata\{runtime,launch}`，要改成 `$XDG_STATE_HOME`（默认 `~/.local/state`）下的 `strata/{runtime,launch}`。runtime 目录还受 `STRATA_RUNTIME_DIR` 影响。这两个目录读错时，DFlash2 起草方式和专家区都会核对失败，Strata 会被拒绝。
  - `available_ram_gib()` 用的是 `ctypes.windll`。Linux 上它返回 None，`_wait_ram` 遇到 None 会**静默跳过**内存等待，专家区仍有日志兜底。要改为读 `/proc/meminfo` 的 `MemAvailable`。
  - `MIN_AVAILABLE_RAM_GIB = 52.0` 是按 Windows 标定的；本机共 60 GiB，空闲时可用约 52 GiB。按上一节，标定改由 Linux 上的实测证据决定。
  - `STRATA_VERSION` 和 `STRATA_ENGINE_BUILD` 改法见已定 2。`nvidia_smi()` 里的 `CREATE_NO_WINDOW` 已经用 `getattr` 兜底，不用改。
  - `ARENA_LOCKED` 只认 Windows 的日志写法，要按 Linux 日志里的 `cudaHostRegister ... ok` 重写，见上一节。
- `config.py`：默认的 `ffmpeg`、`ffprobe` 路径带 `.exe`（`.local/tools/ffmpeg/9.0/bin/ffmpeg.exe`）。
- `artifacts.py`：`replace_with_retry` 专为 Windows 文件占用而写，在 Linux 上不需要，删掉重试，直接用 `os.replace`。`work_id` 和 `job.py` 里的 `normcase` 在 Linux 上不做任何转换，删掉（旧数据不迁移，work id 改变无妨）。
- `media.py`：日志里的命令行用 `subprocess.list2cmdline`（Windows 引号规则）记录，Linux 上应换成 `shlex.join`。只影响显示。
- `asr_whisper.py`：模块说明里的 DLL 加载描述要随 CTranslate2 的验证结论重写。

### 脚本 `scripts/` 与 `justfile`

- `assets.toml`：删掉 `[tools.ffmpeg]` 段（已定 3）。
- `scripts/assets.py`：删掉 tools 安装的全部代码（BtbN 正则、zip 解包、`install-tools`），只保留模型的下载和核对。
- `scripts/upgrade.py`：删掉 ffmpeg 组件和与之相关的 WAV 比对代码。
- `justfile`
  - `set windows-shell := [...]` 删除。
  - `subtitles` recipe 的写法是 pwsh 专用的：`'...'` 里把 `'` 转义成 `''`，结尾 `exit $LASTEXITCODE`。在 sh 下，路径含单引号时会出错。退出码在 sh 下碰巧还能正确传递，但写法要改。
  - `scripts/with_lock.py` 依赖 `fcntl`，所以以前在 Windows 上没接入任何 recipe。到了 Linux 上，可以按它的原本设计包住 `gate-full`／`test-full`（是否接入另行决定）。
- `scripts/smoke/smokelib.py`：`loaded_modules()` 用 psapi `EnumProcessModulesEx`，可改读 `/proc/self/maps`；llama-server 检测用的是 `tasklist`，在产品已不使用 llama-server 的情况下可以直接删掉。
- `scripts/smoke/ct2_after_torch.py`：整体建立在 Windows 机制上（`WinDLL("version")` 读 DLL 版本、`cudnn64_9.dll` 白名单），要按 Linux 的 `.so` 加载方式重写判据。
- `scripts/subtitles.py`：只有注释提到 Windows 路径。

### 测试 `tests/`

- `tests/core/test_assets_manifest.py`：钉死了 `ffmpeg.exe`、`ffprobe.exe` 路径，要随 `assets.toml` 和 `config.py` 一起改。
- `tests/core/test_assets_script.py`：删掉 tools 安装相关的用例。
- `tests/core/test_procs.py` 目前不覆盖进程身份；Linux 下的 starttime 和子进程随父进程退出（pdeathsig）要补到 full 层（真实子进程）。
- `tests/fake_worker.py`：注释里写着 Windows venv 启动器会导致 pid 不同。Linux 上不存在这个问题，等待逻辑可以保留。
- 环境建好后，`just gate-core`、`just gate-full` 都没在 Linux 上跑过，可能还有没被 grep 到的平台假设，比如路径大小写、换行、信号。

### 文档（与代码同一次交付）

按[随交付同步](../../../docs/agents/documentation.md)更新。涉及 Windows、pwsh、`LOCALAPPDATA`、`.exe` 的正文，按命中次数排序：

- `docs/architecture/modules/stt-asr.md`（13 处，主要是 CT2 DLL 的说明）
- `docs/development/workflow.md`（8 处；其中"Windows 上的长任务与 worktree"一节要重写或删除）
- `docs/development/windows-nvidia.md`（7 处；整页要重写，可能还要改名，比如改成平台与 NVIDIA 页）
- `docs/architecture/modules/artifact-contract.md`、`stt-workers.md`、`run-logging-and-processes.md`、`strata-session.md`
- `README.md`、`AGENTS.md`
  - "验证目标是原生 Windows（pwsh、RTX 5080）"
  - `.local/gpu.lock` 要用 PowerShell `Get-Process` 核实，改成 `ps`／`pgrep`
  - 指向 Windows 长任务一节的链接
- `docs/development/dependencies.md`、`toolchain.md`、`technology-stack.md`、`inference-selection.md`
- `docs/architecture/modules/config-reference.md`、`japanese-cues.md`、`config-and-media.md`、`batch-orchestration.md`、`docs/architecture/module-boundaries.md`
- `docs/specs/bilingual-subtitle-pipeline.md`、`GLOSSARY.md`、`docs/INDEX.md`
- `kototoki.toml.example`：`D:/movie/inbox` 和 `.exe` 路径
- ADR：由拆票 1 的新 ADR 取代 ADR-0033、修订 Strata 身份条款；ADR-0007、0029、0030 里与平台相关的表述只在沿革里注明。
- 不改：`research/`（已冻结；grep 也没有命中）、`runs/` 的历史跑次记录。

## 建议拆票

1. ~~平台决定写成 ADR~~：已完成，见 [ADR-0034](../../../docs/adr/0034-ubuntu-only-platform.md)（2026-11-20）。它取代了 ADR-0033，并修订了 ADR-0029、ADR-0021 中的 Strata 版本条款；INDEX、CURRENT、GLOSSARY 已同步。
2. ~~依赖与锁~~：已完成（2026-11-20）。
   - `mise.toml` 只钉 uv 0.13.9 和 just 1.59.0，删掉了 `[env]`；
   - `.python-version` 改为 `3.13`，`check_toolchain.py` 按前缀核对；
   - `environments` 改为只解析 linux，删掉旧 lock 重新解析：直接依赖版本不变，传递依赖取当日最新稳定版；
   - 已执行 `mise install` 和 `uv lock`（uv 下载了 CPython 3.13.18），`just check-toolchain` 通过。
   - `uv sync --locked` 已完成（`.venv` 约 7.3 GB）。torch 2.11.0+cu128（cuDNN 9.19）识别出 RTX 5080（sm_120）；ctranslate2 4.8.3 能看到 1 张 CUDA 卡，支持 float16、bfloat16、int8。还没加载模型解码。
   - torchcodec 改用 `pytorch-cpu` 索引的 `0.17.0+cpu`，原因是 PyPI 的 Linux wheel 依赖 CUDA 13 的 `libnvrtc.so.13`。
   - `just gate-core` 通过（794 个用例），只修了 `test_config` 里一处 Windows 绝对路径 `D:/abs/mms`。
   - `just test-full` 的 13 个用例全部失败，原因都是 ffmpeg 默认路径 `.local/tools/ffmpeg/9.0/bin/ffmpeg.exe` 不存在，留给拆票 3 处理。
3. 资产：删掉 ffmpeg 的下载和升级代码；`config.py` 默认从 PATH 查找；`assets.toml`、`assets.py`、`upgrade.py` 和相关测试一并改。
4. 进程：`procs.py` 的 starttime 和子进程随父退出、`job.py` 的中断路径、full 层测试。
5. Strata 适配：CLI 路径、XDG 日志目录、按 Linux 日志重写专家区核对、`/proc/meminfo`、版本只锁 0.2、重新标定内存阈值。
6. smoke 脚本的 Linux 化（`smokelib`、`ct2_after_torch`）。
7. 文档全面同步、`justfile`（删 pwsh 写法，`gate-full` 接 `with_lock.py`）、`workflow.md` 长任务改 `systemd-run --user`。
8. 验收（每一步都是重任务，逐项先问）：`just install` → `just fetch-models` → `gate-full` → `just smoke` → 小批量的 `just subtitles`。

## Comments
