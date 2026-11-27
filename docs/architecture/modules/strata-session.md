---
covers:
  - kototoki/strata.py
  - kototoki/local_client.py
---
# Strata 服务与共享 session

状态：current；权威决定：[ADR-0021](../../adr/0021-q3-strata-names-baseline.md)、[ADR-0029](../../adr/0029-translate-per-cue-resolution.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责产品唯一的推理服务 Strata 的生命周期与本机 HTTP 客户端：

- `kototoki/strata.py`：`StrataServer`（启动、身份核对、专家区检查、资源采样、停止与显存释放核实）、显存轮询、Strata 身份常量、整批共用的 `Session`。
- `kototoki/local_client.py`：`LlamaClient`（只连本机回环）、基础设施失败 `InfraFailure`、失败分类 `classify_failure` 与 `response_body`。

两者都是中间层：[专名一致性](name-consistency.md)（建表）与[翻译子系统](translation-subsystem.md)单向依赖它们。不负责：何时需要模型、GPU 锁与 Strata pid 写进锁文件（[批次编排](batch-orchestration.md)）；请求内容、重试与追问（各使用者）；Strata 与模型的安装（[依赖布局](../../development/dependencies.md)）。现行定义见[决定定义：产品翻译](../../adr/CURRENT.md#产品翻译)。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

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

1. `strata launch --status --output json` 必须没有正在服务的 launch，否则 `StrataRefused`（不抢占、不替别人停）。`--status` 本身执行失败是 `InfraFailure`（`CalledProcessError` 保留返回码与 stderr 末尾 300 字符）。
2. 轮询 `nvidia-smi` 空闲显存到 ≥ 14000 MiB（`MIN_FREE_MIB`，即上一个 GPU worker 已退出）；120 s 仍不够抛 `InfraFailure`，等超过 30 s 记一次 WARNING；`nvidia-smi` 失败时保留异常、退出码与 stderr 截尾或异常 stdout 到告警与超时消息中。
3. 轮询可用内存（`/proc/meminfo` 的 `MemAvailable`）到 ≥ 50 GiB（`MIN_AVAILABLE_RAM_GIB`，2026-11-20 Linux smoke 重标：启动前可用 51.0 GiB 时专家区 46.84 GiB 仍锁进内存，门槛取比它低 1 GiB）；等满 180 s 仍不够只记 WARNING 照常启动；读 `/proc/meminfo` 遇 `OSError` 或缺项时限频记一次 WARNING 并直接跳过等待。
4. 执行 `strata launch --no-tui --model iq3_s`（子进程里不点名模型时 Strata 以退出码 2 拒绝；`--model iq3_s` 即默认启动，ADR-0029「Strata session」）。执行失败或非零退出是 `InfraFailure`（消息带 stderr 末尾 300 字符）。
5. 轮询 `--status` 到唯一一个 `ready` 的 launch（300 s，超时 `InfraFailure`，保留最近一次 `--status` 异常与 stderr 截尾；出现多于一个 launch 即 `StrataRefused`）。
6. 接入检查（`probe`，ADR-0021「Q3 服务与运行顺序」），任一项不符即 `StrataRefused`：
   - `strata --version` 属 0.2 版本线（以 `strata 0.2.` 开头）；实际版本与 build 只记进 `strata.json`，不进配方身份（ADR-0034「Strata 版本」）；
   - launch 服务于 `127.0.0.1:8080`；
   - run config 的 `model_name` 为 `qwen3.8-flash-next-iq3_s`、`--max-context 131072`；
   - 起草方式为 DFlash2：取自本次启动写进 `$XDG_STATE_HOME/strata/runtime/launch-<name>.server.log`（默认 `~/.local/state/strata/`，`STRATA_RUNTIME_DIR` 可覆盖 `runtime/`） 的最后一行 `[strata] drafting:`，不按 run config 的参数判断（Strata 总会传 `--mtp`）；
   - `/v1/models` 含该模型，`/v1/status` 的原生 context 为 131072。
7. 专家区检查：读本次启动写进 `$XDG_STATE_HOME/strata/launch/<name>.engine.log` 的新内容。日志有 `expert arena: cudaHostRegister … ok`（专家区登记为锁页内存）且没有退到 mmap 的记录才算 `ram`；`mmap` 或无法确认即 `StrataRefused`（消息提示释放内存后重跑）。结果记进 `strata.json` 的 `expert_arena`。
8. 启动资源采样，记一行 INFO，回调 pid。

两类日志都只读启动前记下的长度之后新写的部分。进入过程中任何异常（含被中断）都先走退出路径再上抛。

**运行中**：`ResourceSampler` 每 5 s 从 `/v1/status` 取整机显存与内存的峰值（系统总量），预期传输/解析失败静默计入 `errors` 与 `last_error`；后台采样线程捕获未预期异常并按实例限频记一次 `ERROR`（不随 5 s 轮询刷屏）。

**退出（停止一个 session）**：只停自己启动的 launch。`ResourceSampler.finish()` 停线程、补做最终采样并取快照（有未记过 `ERROR` 的预期失败记一条汇总 `WARNING`，最终采样未预期异常只记一条 `ERROR`）；再执行 `strata launch --stop`，轮询 `--status` 为空与显存回到 14000 MiB（各 180 s）。`--stop`／`--status` 失败均保留 stderr 截尾到 `strata-final.json`（`stop`／`status_error`）；写盘或核实失败只记 ERROR 不抛出。强杀残留的后台 launch 须手动 `strata launch --stop`。

**证据**：`<work root>/strata-sessions/<UTC戳>-<pid>/session-NN/`，names 与翻译共用：

- `strata.json`：接入时观察到的身份（版本、launch、run config 摘要、kv、spec、起草方式、`/v1/models`、`/v1/status` 摘要、`expert_arena`），不含 API key；
- `resources.json`：显存／内存峰值、采样与出错次数（含 `last_error`）、服务日志事件计数；
- `strata-final.json`：停止、`status` 为空（出错时附 `status_error`）、空闲显存与 `released` 的核实结果。

**日志**：logger `kototoki.strata`，前缀 `[strata]`，经编排写进运行日志（[运行日志](run-logging-and-processes/run-log.md#运行日志)）：

- INFO：等完显存与内存、执行 `strata launch` 之前 `[strata] launching (free VRAM X MiB, available RAM Y GiB)`（取不到内存读数写 `unknown`）；ready；停止开始时 `[strata] stopping`；停止核实通过。
- WARNING：等显存超过 30 s 的提示、内存不足、读 `/proc/meminfo` 失败或缺少 `MemAvailable`（按路径与错误类型限频一次）；退出时未记过 `ERROR` 的预期采样失败汇总（含 `last_error`）；每次启动失败（`InfraFailure`）`[strata] start failed n/3: <首行>`。
- ERROR：`Session` 置 `unavailable` 时一次 `[strata] unavailable for the rest of this batch: <首行>`（被拒绝或启动额度用尽）；后台或最终采样首次未预期异常（按实例限频一次）；写 `resources.json` 或 `strata-final.json` 遇 `OSError`；停止未核实（写盘成功时行尾 `see <strata-final.json 路径>`，写盘失败时不指向不存在的文件）。首行截到 200 字符。
- 启动失败（`strata launch` 退出码非 0）与就绪超时的异常消息带本次新写的服务日志的绝对路径（找不到唯一一份时给日志目录）。

**本机客户端 `LlamaClient(url, timeout=180, trace_dir=None)`**：

- 只接受无认证的本机回环 `http://`（`127.0.0.1`、`localhost`、`::1`），否则 `ValueError`；不走系统代理，拒绝重定向。
- `request(endpoint, data, *, trace_label=None)` 返回 JSON 对象；非 JSON 或不是对象时抛 `ValueError`，HTTP 与传输异常原样上抛。
- `chat_completion(body)` 即 `POST /v1/chat/completions`，trace 标签 `chat`。
- 给了 `trace_dir` 时每个请求写一个交换目录（`request.json`、`response.raw`、`transport.json`）：无标签的目录名为 5 位序号，有标签的为 `<label>-NN`，同一客户端共用一个序号计数。
- `classify_failure(text)`：失败文本含 CUDA／Vulkan／`std::bad_alloc` 等 OOM 记号（不区分大小写）为 `oom`，否则 `server_error`；`response_body(client)`：读客户端最近一次交换的 `response.raw`（没有则空串）。names 与翻译的 HTTP 失败经 `response_body` 取正文再交 `classify_failure`，翻译的响应 `error` 直接交 `classify_failure`；它是分类的唯一出处。

## 实现设计

- 只有 Strata 这一个后端实现，不抽后端协议。服务进程不由本模块持有：`launch` 返回后它在后台运行，`--stop` 才卸载。
- `strata` 从 PATH 调用（安装器放在 `~/.local/bin/strata`）；安装与外部前置见[依赖布局与资产清单](../../development/dependencies.md)。
- `probe` 改编自研究侧 `archive/2026-11-18-pre-research-restructure:experiments/translation_v3/strata.py::probe` 的 `"default"` 分支：不检查 preset 名、不限制并发数，起草方式改读服务日志。
- Strata 身份常量（`MODEL`、`STRATA_SERIES`、`STRATA_LAUNCH`、`STRATA_RESOLVED`）只在这里定义，翻译配方 `q3-translate-v1` 与建表配方 `q3-names-v3` 的运行时身份取 `STRATA_LAUNCH` 与 `STRATA_RESOLVED`（版本线只在接入检查里用）。
- `Session` 的状态（`server`、`ordinal`、`start_failures`、`unavailable`、`runtime_root`）归它自己；`runtime_root` 在构造时按 UTC 时间戳与 pid 定下。
- `LlamaClient` 源自 `archive/2026-11-18-pre-research-restructure:experiments/translation_demo/client.py`（产品新增 `chat_completion`），`explicit_oom` 复制自 `translation_demo/run.py`；只复制不导入。llama-server 的进程生命周期不在产品里（ADR-0025）。

## 接口与依赖

- 使用者（names、翻译）只经 `ensure_started()`、`stop()`、`label`、`client()`、`unavailable` 使用 `Session`，不碰 `ordinal`、`runtime_root`、`client_factory`。翻译还读服务对象的 `identity`（`candidate`、`strata`、`cold_load_seconds`、启动前空闲显存与可用内存）写进 `run.json`。
- 内部接缝只供测试：`Session(server_factory=..., client_factory=...)`（伪服务须有 `url`、`identity` 与上下文管理器协议；伪客户端只经 `client()` 生效；伪服务与 `Session` 装配在测试里只有一份，`tests/core/strata_fakes.py`，翻译、names session、strata session 三个套件共用，伪客户端由各套件自备）；`StrataServer` 的 `cli`、`get`、`free_vram`、`available_ram`、`sleep`、`clock`、`log_dir`、`engine_log_dir`。
- 依赖：`kototoki/strata.py` 依赖标准库、`kototoki.artifacts`、`kototoki.config`（只用工作根位置）与 `kototoki.local_client`；`kototoki/local_client.py` 只依赖标准库。两者都不导入 names、翻译、torch 与研究代码。
- 研究代码可以直接导入本模块（[ADR-0031](../../adr/0031-research-layout-and-lightweight-records.md) R5）。
- 外部依赖：Strata CLI、本机 8080 服务、`nvidia-smi`。

## 代码与验证入口

- 代码：`kototoki/strata.py`（`Session`、`StrataServer`、`StrataRefused`、`probe`、`expert_arena`、`drafting_from_log`、`ResourceSampler`、`wait_for_free_vram`、`probe_nvidia_smi`、`nvidia_smi`、`available_ram_gib`、身份常量）；`kototoki/local_client.py`（`LlamaClient`、`InfraFailure`、`classify_failure`、`response_body`）。
- 测试（core，`mise run test`）：
  - `tests/core/test_strata.py`（伪 CLI）：
    - 启动与停止：正常启动、核对与停止；已有 launch 时拒绝且不替别人停；`probe` 不符即停并拒绝；会话内被中断即 `--stop`。
    - 采样与退出日志可靠性：后台采样线程未预期异常限频记日志并保留 `last_error`；预期采样出错退出记单条汇总 `WARNING`，最终采样未预期异常只记单条 `ERROR`（不重复 `WARNING`）；`strata-final.json` 写盘 `OSError` 记 `ERROR` 且不指向缺失文件；`--status`／`--stop` 保留 `CalledProcessError` 的 stderr 与 `status_error`。
    - 等显存：达阈值即返回读数、超时抛错并带最后读数、默认 `nvidia-smi` 查询失败诊断不依赖线程局部状态。
    - 共享 `Session`：首次才启动并跨阶段复用、`stop` 后再起为新 session、启动失败累计后批次不可用、被拒即不可用。
    - 测试精简（2026-11-22）后不再有测试覆盖：两个 launch、启动命令失败与加载中被中断仍 `--stop`；显存未释放超时记录；等内存与内存不足警告；`mmap` 或未确认锁定时停掉并拒绝；`expert_arena`、`available_ram_gib` 与正常 `--status` 的解析；显存等待与读内存失败的告警日志；成功启动不限次、一次失败后成功、`client()` 的 trace 目录、`label` 跟随启动序号；旧 `translate/strata.py` 已不存在的检查。
  - `tests/core/test_local_client.py`：OOM 消息识别、`classify_failure` 与 `response_body`、`chat_completion` 的端点与 `chat-NN` trace、非回环 URL 被拒。其余（无标签请求的序号目录、研究专用方法不在产品客户端、旧 `llama_server` 模块已不存在）不再有测试覆盖。
  - 使用者侧的启动失败、被拒与重启见 `tests/core/test_translate.py`、`tests/core/test_names_session.py`，整批只启动一次见 `tests/core/test_job.py`（精简后 `test_job.py` 只剩共享 session 的阶段顺序与 names 表身份变化重译）。
- 真实运行：经 `mise run smoke translate_product`、`mise run smoke names_product`（占 GPU，须用户批准，规则见[开发工作流](../../development/workflow.md)），见[翻译子系统](translation-subsystem.md#代码与验证入口)与[专名一致性](name-consistency.md#代码与验证入口)。
- 未验证：强杀后残留 launch 被拒绝的真实运行。已知限制：空闲显存等满 120 s 仍低于 14000 MiB（桌面程序占用较多）即启动失败；可用内存不足 50 GiB 时专家区可能退到 mmap，启动被拒绝，须先关掉部分程序；50 到 51 GiB 之间没有实测过。

## 变更与决策来源

- [ADR-0021](../../adr/0021-q3-strata-names-baseline.md)、[ADR-0029](../../adr/0029-translate-per-cue-resolution.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)
- `archive/2026-11-18-pre-research-restructure:docs/plans/product-names-on-strata.md`、`archive/2026-11-18-pre-research-restructure:docs/plans/architecture-cleanup.md`
- 归档 tag 中的 .scratch/q3-product-switch/、.scratch/architecture-cleanup/、.scratch/runtime-logging-gaps/；Beads `kototoki-e8t`（2026-10-19 审计）
- Q2 首用 smoke 与整片记录（含 mmap 诊断）（`archive/2026-11-18-pre-research-restructure:docs/research/acceptance/2026-11-11-module-page-history-translation-names.md`）
- 增量规格 `kototoki-598`（票据 `kototoki-598.3`）：Strata 生命周期与采样器日志可靠性
