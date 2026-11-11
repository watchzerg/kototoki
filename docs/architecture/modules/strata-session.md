# Strata 服务与共享 session

状态：current；权威决定：[ADR-0017](../../adr/0017-q2-strata-default-launch-baseline.md)、[ADR-0019](../../adr/0019-product-translation-q2.md)、[ADR-0022](../../adr/0022-product-names-on-strata.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责产品唯一的推理服务 Strata 的生命周期与本机 HTTP 客户端：

- `kototoki/strata.py`：`StrataServer`（启动、身份核对、专家区检查、资源采样、停止与显存释放核实）、显存轮询、Strata 身份常量、整批共用的 `Session`。
- `kototoki/local_client.py`：`LlamaClient`（只连本机回环）、基础设施失败 `InfraFailure`、OOM 文本识别 `explicit_oom`。

两者都是中间层：[专名一致性](name-consistency.md)（建表）与[翻译子系统](translation-subsystem.md)单向依赖它们。不负责：何时需要模型、GPU 锁与 Strata pid 写进锁文件（[批次编排](batch-orchestration.md)）；请求内容、重试与降级（各使用者）；Strata 与模型的安装（[依赖布局](../../development/dependencies.md)）。现行定义见[决定定义：产品翻译](../../adr/CURRENT.md#产品翻译)。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**共享 `Session(config, *, on_server_pid=None)`**（编排器整批持有一个，传给 names 与翻译两个阶段）：

- 上下文管理器；退出（含异常与被中断）时总是 `stop()`。
- `ensure_started()`：没有运行中的服务才启动一个新 session，返回服务对象；第一次真正需要模型时才启动（可能在 names，也可能在 translate），两阶段之间不停。
- `stop()`：停掉当前服务；之后再 `ensure_started()` 即新 session（新的 `session-NN` 目录）。
- 成功的启动不限次数。启动失败（`InfraFailure`）整批累计 3 次（`MAX_START_FAILURES`），或任一次 `StrataRefused`，即置 `unavailable`；此后 `ensure_started()` 直接抛 `StrataRefused`，消息带原因，两个阶段其余需要模型的影片都直接失败。
- `unavailable` 只由 `Session` 写，使用者只读。
- `label`：当前 session 名 `<runtime_root.name>/session-NN`（NN 是最近一次尝试启动的序号，含失败的启动）。翻译记进 `run.json` 的 `server_session`，names 用作交换目录的相对路径。
- `client(trace_dir, *, timeout)`：对运行中的服务建 `LlamaClient`，逐请求 trace 写进调用方给的目录；未启动时抛 `RuntimeError`。
- `on_server_pid(pid)`：服务 ready 后以 `strata launch --status` 报告的 pid 回调（报告里没有 pid 时不回调），停止后以 `None` 回调，供编排器写进 GPU 锁。

**一次 `StrataServer` 进入（启动一个 session）**：

1. `strata launch --status --output json` 必须没有正在服务的 launch，否则 `StrataRefused`（不抢占、不替别人停）。`--status` 本身执行失败是 `InfraFailure`。
2. 轮询 `nvidia-smi` 空闲显存到 ≥ 14000 MiB（`MIN_FREE_MIB`，即上一个 GPU worker 已退出）；120 s 仍不够抛 `InfraFailure`，等超过 30 s 记一次 WARNING。
3. 轮询可用内存（Windows `GlobalMemoryStatusEx`）到 ≥ 52 GiB（`MIN_AVAILABLE_RAM_GIB`：专家区 46.84 GiB 加引擎分配前自占的约 4.8 GiB 与余量）；等满 180 s 仍不够只记 WARNING 照常启动；取不到读数时不等。
4. 执行 `strata launch --no-tui --model iq3_s`（子进程里不点名模型时 Strata 以退出码 2 拒绝；`--model iq3_s` 即默认启动，ADR-0019）。执行失败或非零退出是 `InfraFailure`（消息带 stderr 末尾 300 字符）。
5. 轮询 `--status` 到唯一一个 `ready` 的 launch（300 s，超时 `InfraFailure`；出现多于一个 launch 即 `StrataRefused`）。
6. 接入检查（`probe`，ADR-0017），任一项不符即 `StrataRefused`：
   - `strata --version` 为 0.2.12／build 0.1.58；
   - launch 服务于 `127.0.0.1:8080`；
   - run config 的 `model_name` 为 `qwen3.8-flash-next-iq3_s`、`--max-context 131072`；
   - 起草方式为 DFlash2：取自本次启动写进 `%LOCALAPPDATA%\Strata\runtime\launch-<name>.server.log` 的最后一行 `[strata] drafting:`，不按 run config 的参数判断（Strata 总会传 `--mtp`）；
   - `/v1/models` 含该模型，`/v1/status` 的原生 context 为 131072。
7. 专家区检查：读本次启动写进 `%LOCALAPPDATA%\Strata\launch\<name>.engine.log` 的新内容。日志有 `expert arena: locked` 且没有退到 mmap 的记录才算 `ram`；`mmap` 或无法确认即 `StrataRefused`（消息提示释放内存后重跑）。结果记进 `strata.json` 的 `expert_arena`。
8. 启动资源采样，记一行 INFO，回调 pid。

两类日志都只读启动前记下的长度之后新写的部分。进入过程中任何异常（含被中断）都先走退出路径再上抛。

**运行中**：`ResourceSampler` 每 5 s 从 `/v1/status` 取整机显存与内存的峰值（系统总量）。服务日志只计事件数（推理循环自救、logits 非有限、单 token 重复截停），不复制日志。

**退出（停止一个 session）**：只停自己启动的 launch。执行 `strata launch --stop`，再轮询到 `--status` 为空、空闲显存回到 14000 MiB（各最多 180 s）。核实失败只记 ERROR 并写进 `strata-final.json`，不抛出，以免盖住原异常。产品进程被强杀时 Strata 可能留在后台，下次运行因 `--status` 非空而被拒绝，须手动 `strata launch --stop`。

**证据**：`<work root>/strata-sessions/<UTC戳>-<pid>/session-NN/`，names 与翻译共用：

- `strata.json`：接入时观察到的身份（版本、launch、run config 摘要、kv、spec、起草方式、`/v1/models`、`/v1/status` 摘要、`expert_arena`），不含 API key；
- `resources.json`：显存／内存峰值、采样与出错次数、服务日志事件计数；
- `strata-final.json`：停止、status 为空、空闲显存与 `released` 的核实结果。

**日志**：logger `kototoki.strata`，前缀 `[strata]`，经编排写进运行日志（[批次编排：运行日志](batch-orchestration.md#运行日志)）：ready 与停止为 INFO；等显存超时前的提示与内存不足为 WARNING；停止未核实为 ERROR。

**本机客户端 `LlamaClient(url, timeout=180, trace_dir=None)`**：

- 只接受无认证的本机回环 `http://`（`127.0.0.1`、`localhost`、`::1`），否则 `ValueError`；不走系统代理，拒绝重定向。
- `request(endpoint, data, *, trace_label=None)` 返回 JSON 对象；非 JSON 或不是对象时抛 `ValueError`，HTTP 与传输异常原样上抛。
- `chat_completion(body)` 即 `POST /v1/chat/completions`，trace 标签 `chat`。
- 给了 `trace_dir` 时每个请求写一个交换目录（`request.json`、`response.raw`、`transport.json`）：无标签的目录名为 5 位序号，有标签的为 `<label>-NN`，同一客户端共用一个序号计数。
- `explicit_oom(message)`：按 CUDA／Vulkan／`std::bad_alloc` 等 OOM 文本判断（不区分大小写）。

## 实现设计

- 只有 Strata 这一个后端实现，不抽后端协议。服务进程不由本模块持有：`launch` 返回后它在后台运行，`--stop` 才卸载。
- `strata` 在 PATH 上是 PowerShell 脚本，子进程优先用 `%LOCALAPPDATA%\Strata\terminal\current\bin\strata.cmd`（`strata_cmd`）。
- `probe` 改编自研究侧 `experiments/translation_v3/strata.py::probe` 的 `"default"` 分支：不检查 preset 名、不限制并发数，起草方式改读服务日志。
- Strata 身份常量（`MODEL`、`STRATA_VERSION`、`STRATA_ENGINE_BUILD`、`STRATA_LAUNCH`、`STRATA_RESOLVED`）只在这里定义，翻译配方 `q2-degrade-v1` 与建表配方 `q3-names-v1` 的运行时身份都取这些值。
- `Session` 的状态（`server`、`ordinal`、`start_failures`、`unavailable`、`runtime_root`）归它自己；`runtime_root` 在构造时按 UTC 时间戳与 pid 定下。
- `LlamaClient` 源自 `experiments/translation_demo/client.py`（产品新增 `chat_completion`），`explicit_oom` 复制自 `translation_demo/run.py`；只复制不导入。llama-server 的进程生命周期与 `tokenize`／`complete` 只在研究侧 `experiments/translation_v3/llama_server.py`（ADR-0025）。

## 接口与依赖

- 使用者（names、翻译）只经 `ensure_started()`、`stop()`、`label`、`client()`、`unavailable` 使用 `Session`，不碰 `ordinal`、`runtime_root`、`client_factory`。翻译还读服务对象的 `identity`（`candidate`、`strata`、`cold_load_seconds`、启动前空闲显存与可用内存）写进 `run.json`。
- 内部接缝只供测试：`Session(server_factory=..., client_factory=...)`（伪服务须有 `url`、`identity` 与上下文管理器协议；伪客户端只经 `client()` 生效）；`StrataServer` 的 `cli`、`get`、`free_vram`、`available_ram`、`sleep`、`clock`、`log_dir`、`engine_log_dir`。
- 依赖：`kototoki/strata.py` 依赖标准库、`kototoki.artifacts`、`kototoki.config`（只用工作根位置）与 `kototoki.local_client`；`kototoki/local_client.py` 只依赖标准库。两者都不导入 names、翻译、torch 与 `experiments.*`。
- 研究侧 `experiments/translation_v3/` 与 `experiments/scene_batching_v6/v13.py` 直接导入本模块。
- 外部依赖：Strata CLI、本机 8080 服务、`nvidia-smi`。

## 代码与验证入口

- 代码：`kototoki/strata.py`（`Session`、`StrataServer`、`StrataRefused`、`probe`、`expert_arena`、`drafting_from_log`、`ResourceSampler`、`wait_for_free_vram`、`nvidia_smi`、`available_ram_gib`、身份常量）；`kototoki/local_client.py`（`LlamaClient`、`InfraFailure`、`explicit_oom`）。
- 测试（core，`just test`）：
  - `tests/core/test_strata.py`：伪 CLI 下正常启动、核对与停止；已有 launch 时拒绝且不替别人停；等显存与超时；`probe` 各项不符即停并拒绝；未就绪、两个 launch、启动命令失败、被中断都 `--stop`；停止未确认或显存未释放只记录不抛出；启动前等内存、等不到只警告；`mmap` 或未确认锁定时停掉并拒绝；`--status` 只解析 JSON 行；显存轮询的告警与超时；共享 `Session` 首次才启动、`stop` 后再起为新 session、成功启动不限次、启动失败累计 3 次或被拒即不可用、`client()` 的 trace 目录、`label` 跟随启动序号；旧的 `translate/strata.py` 已不存在。
  - `tests/core/test_local_client.py`：OOM 识别、`chat_completion` 的端点与 `chat-NN` trace、无标签请求的序号目录、研究专用方法不在产品客户端、非回环 URL 被拒、旧的 `llama_server` 模块已不存在。
  - 使用者侧的启动失败、被拒与重启见 `tests/core/test_translate.py`、`tests/core/test_names_session.py`，整批只启动一次见 `tests/core/test_job.py`。
- 真实运行：经 `just smoke translate_product`、`just smoke names_product`（占 GPU，须用户批准，不属于任何 gate），见[翻译子系统](translation-subsystem.md#代码与验证入口)与[专名一致性](name-consistency.md#代码与验证入口)。
- 未验证：强杀后残留 launch 被拒绝的真实运行。已知限制：空闲显存等满 120 s 仍低于 14000 MiB（桌面程序占用较多）即启动失败；可用内存不足 52 GiB 时专家区很可能退到 mmap，启动被拒绝，须先关掉部分程序。

## 变更与决策来源

- [ADR-0017](../../adr/0017-q2-strata-default-launch-baseline.md)、[ADR-0019](../../adr/0019-product-translation-q2.md)、[ADR-0022](../../adr/0022-product-names-on-strata.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)
- [`docs/plans/product-names-on-strata.md`](../../plans/product-names-on-strata.md)、[`docs/plans/architecture-cleanup.md`](../../plans/architecture-cleanup.md)
- `.scratch/q3-product-switch/`、`.scratch/architecture-cleanup/`、`.scratch/architecture-review/`
- [Q2 首用 smoke 与整片记录（含 mmap 诊断）](../../research/acceptance/2026-11-11-module-page-history-translation-names.md)
