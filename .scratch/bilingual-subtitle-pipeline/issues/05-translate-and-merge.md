# 05 翻译移植与双语合并

Status: done
Type: task
Blocked by: 01, 02, 04

## 范围

- 架构（[目标架构](../../../docs/architecture/bilingual-pipeline-architecture.md)"翻译子系统""合并"行）：子系统对编排器只暴露 `translate_document(document, run_dir, session, config) -> TranslateResult` 与 `Session` 生命周期对象；`server`、`client`、`batching`、`generate`、`procs` 是内部实现，编排不导入它们，server 的存在对编排不可见；`client` 是只供测试的内部接缝（伪客户端）。`merge(ja_document, zh_translations) -> srt_text` 是纯函数，写出由编排完成。子系统内不取 GPU 锁、不做时间换算。
- `kototoki/translate/`：从 `experiments/translation_v3` 复制 `server.py`（ManagedServer、verify_model；**去掉 GpuLock**）、`recipes.py`（只保留 b10-joint 字段；产品配方 `b10-joint-degrade-v1` 由票据 09 在本文件追加）、`batching.py`、`generate.py`、`procs.py`（ProcessLock、KillOnCloseJob、list_llama_servers）、`common.py`（引擎与根目录改配置，来自 02 的 `config.py`）、`data.py`（`Scene`／`Cue`）；`experiments/translation_demo` 的 `adapters.py`、`client.py`、`run.py` 的 `explicit_oom` 与资产清单函数；`translation_demo_runtime` 的驻留解析（按 stock 引擎日志适配，参照 01 smoke #4 保存的日志）。去掉 `mbr` 导入与裁判／统计／队列命令；保留一条测试钉住 v3 `b10-joint` 的原 hash `2ba680540f055b2ae0c8122faa3ba537418eb12720a552f53c3aa5b652d0969a`。
- session 模型改造：编排器为整批建一个 server session 并传入；缓存校验（`cache_n == 0`）在每个 session 首个请求做一次；基础设施失败在同 run 内重启 server 重做，最多 2 次，**每次重启是新的 session**（`sessions[]` 新增、`cache_state` 重置、`resumed=true`）；启动 server 前用 `nvidia-smi` 轮询空闲显存达到阈值，超时按基础设施失败并写明空闲量。
- run 目录：每部影片 `.work/<id>/translate/srt-<ja.srt SHA256 前 12 位>/`，`run.json` 只含该影片；`ja.srt` 变化即换新目录，旧目录保留（v3 `run_generation` 对 `sources` 变化是拒绝而非重建）；**按批次追加落盘**、按批次续跑，部分写入的场景文件不视为终态。
- 空场景（零条目 `ja.srt`）直接写零条目 `zh.srt`，不请求模型。
- `kototoki/merge.py`：按编号合并，中文在上、日文在下；中文内的换行替换为空格，保证每条恰好两行；写 `ja-zh.srt`（回退条目两行相同时也照常输出，报告见 09）。

## 完成标准

- 伪客户端测试（`tests/`）：正常、按批次续跑、OOM 重启 server 并记新 session、缓存校验、空场景、`ja.srt` 变化换目录、显存轮询超时、请求字节与 v3 b10-joint 一致（移植 `AdoptedBaselineTest` 的字节对比与 hash 钉子）、合并换行处理。
- 一部电影真实运行：`zh.srt` 覆盖完整，`ja-zh.srt` 行数一致；记录墙钟与显存峰值。

## 文件所有权

`kototoki/translate/`（`translate/recipes.py` 在本票完成后由 09 追加产品配方）、`merge.py`、对应测试。

## Comments

- 2026-10-13 建票，依据规格 §12。
- 2026-10-14 按两轮评审修订（规格 §13）。
- 2026-10-14 第三轮评审：Blocked by 加 02；run 目录按 SHA 分键；重启即新 session；显存预检；hash 钉子；合并换行；配方文件归属。
- 2026-10-14 实施（分支 `feat/bilingual-05`，worktree `../kototoki-05`）。离线部分完成，整片真实运行待用户确认后执行，故 Status 保持 claimed。
  - 实现：`kototoki/translate/`（`__init__`、`adapters`、`batching`、`client`、`data`、`generate`、`procs`、`recipes`、`server`）与 `kototoki/merge.py`，接口与票据 06 的调用一致（`Session(config, on_server_pid=...)`、`translate_document(...) -> TranslateResult`、`RECIPE_HASH`、`merge(document, translations)`）。`B10_JOINT.recipe_hash` 等于 v3 原 hash `2ba68054…0969a`，提示／grammar／请求与冻结 v3 函数逐字节一致并另有 SHA256 钉子。
  - 与票据正文的出入（按规格／最小设计处理，请复核）：① run 目录在 `srt-<sha12>/` 下再分 `<配方名>__s<seed>/`（与 v3 run_id 同形），否则改 seed 重试会被 run.json 不一致拒绝；规格 §4 与 §13 已记。② llama-server 由整批共用，其运行日志放 `<output_dir>/.work/translate-sessions/<时间戳>-<pid>/session-NN/`（规格 §4 已加）。③ 未移植 `common.py`（哈希／原子写／模型核对复用 `kototoki.artifacts`）；`procs.py` 只留 `list_llama_servers`：`ProcessLock` 归编排器，`KillOnCloseJob` 已由编排器 `contain_children` 覆盖子进程。④ 资产清单文件读取改为冻结资产常量（文件名、大小、SHA256）＋ `artifacts.verify_model`。⑤ 译文含空行时按 `parse` 失败处理（v3 解析接受、但 SRT 写出会拒绝，否则该片每次重跑都在发布时失败）。⑥ 批次终态失败（context／limit／parse）本票直接判该片翻译失败、批次不落盘、重跑再试；降级归 09。⑦ 空闲显存阈值 14300 MiB、超时 120 s（01 smoke：server 自身约 14450 MiB，本机空闲 free 约 14560 MiB）。
  - 独立 Opus 只读审计后修复：空行译文、意外异常不留记录（现记 `session_error` 并停 server）、强杀后 `sessions[]` 批次数丢失（现每批后重写 run.json）。审计提出但未改：端口被占／驻留校验失败等按原异常抛出不重试；`identity.json` 未逐文件核对 exe SHA；`on_server_pid` 在加载完成后才回调（最长约 180 s 锁里无 server pid）；GPU 被他人长期占用时每片要等 3×120 s，未做整批提前放弃。
  - 自动检查：`tests/test_translate.py`（17）、`test_translate_recipes.py`、`test_translate_server.py`、`test_merge.py` 新增；全量 287 个测试通过、compileall 通过（用主仓库 `.venv` 解释器在 worktree 内运行，worktree 无独立 venv）；文档链接检查本票改动无新错误。
  - 遗留：完成标准第二项（一部电影真实运行，记录墙钟与显存峰值）未做。
- 2026-10-14 用户裁定：完成报告中的待决事项按实施方建议处理（分支合并另定）。保留：run 目录分 `<配方名>__s<seed>/`、server 日志放 `.work/translate-sessions/`、显存阈值 14300 MiB／120 s、空行按解析失败、`common.py`／锁／Job Object／资产清单的移植取舍；端口被占与驻留校验失败按原异常抛出、不重试（配置问题，重试无益）。新增（提交 `ea1ef95`）：启动前核对 `llama-server.exe` 与同目录全部 DLL 的 SHA256 等于 `identity.json`（size+mtime 缓存；真实 b11583 目录 34 个文件通过，首次 1.5 s）；server 进程一启动即回调 `on_server_pid`；某片重启额度全耗在 `server_start` 上时 `Session` 记不可用，本批其余影片直接失败。全量 292 个测试通过。
- 2026-10-14 整片真实运行未启动：`.local/gpu.lock` 不存在、无 llama-server 进程，但桌面程序占 1781 MiB，空闲 14197 MiB 低于阈值 14300 MiB（01 smoke 中 server 自身约 14450 MiB），预计会 OOM 或等满 3×120 s。待用户释放显存后再跑。
- 2026-10-14 完成标准第二项通过（main `c98659c`，脚本只在会话临时目录、输出不进仓库与 `.local/`）：HF II W0 对齐 → 默认 cue 规则 → 1112 条 `ja.srt`；单 session 112 批全部一次通过（无重试、无触顶、无重启），`zh.srt` 覆盖 1112/1112，`ja-zh.srt` 1112 条、每条两行。墙钟 176 s（模型 SHA 首次核对 16.7 s、冷加载 7.1 s、翻译约 150 s）；输入 75408／输出 19272 token；首个请求 `cache_n == 0`；启动前空闲 15112 MiB，峰值 15687 MiB（基线约 880 MiB → server 约 14800 MiB）。GPU 锁与 llama-server 进程运行后均已释放。
  - 遗留：空闲显存阈值 14300 MiB 低于实测 server 自身约 14800 MiB，建议上调（待用户决定）；与编排器的真实联调归票据 08。
- 2026-10-14 用户同意：空闲显存阈值 `MIN_FREE_MIB` 由 14300 上调到 14900 MiB（实测 server 自身约 14800 MiB）。
