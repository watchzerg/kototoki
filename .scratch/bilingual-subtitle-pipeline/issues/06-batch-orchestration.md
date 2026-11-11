# 06 批次编排、续跑与失败隔离

Status: done
Type: task
Blocked by: 00, 02

## 范围

- 架构（[目标架构](../../../docs/architecture/bilingual-pipeline-architecture.md)"编排"行与"责任边界"全部八条）：对外只有 `run(config) -> Summary`；媒体、cue、合并、翻译子系统直接调用，推理只经 `kototoki.workers.<stage> --jobs` 子进程；所有 JSON 产物的身份包装、写入与跳过判定在编排经产物契约完成（纯函数与媒体模块只返回结果）；编排自身不做任何时间换算。
- `kototoki/__main__.py`：`python -m kototoki [kototoki.toml]`，默认 `./kototoki.toml`；拒绝 `output_dir` 位于仓库内（`.local/` 除外）或位于 `input_dir` 内。
- `kototoki/job.py`：
  - 启动即取 `<output_dir>/.work/lock`（`ProcessLock`），防止同一输出目录并发编排。
  - 递归扫描 `input_dir`，按路径排序；文件稳定性用两次采样（间隔 `stable_check_s`）大小不变判定，不用 mtime；镜像到 `output_dir`；工作目录用 `artifacts.py` 的短 id；扫描阶段即调用 00 的覆盖判定：`published.json` 身份匹配的文件跳过，最终文件被用户改动且非 `force` 的文件告警跳过，不进 GPU 阶段。
  - 阶段 × 整批：ThreadPool 跑 probe/extract 到整批完成，再依次以子进程 worker 运行 GPU 阶段（`sys.executable -m kototoki.workers.<stage> --jobs <json>`）；jobs 只含前置产物就绪且身份匹配的文件；子进程环境含 `PYTHONUTF8=1`、离线变量与共用的 `HF_HOME`／`TORCH_HOME=<output_dir>/.work/cache/`。
  - worker 异常退出：按增量结果判定正在处理的文件，记该文件该阶段失败，为其后文件重启 worker；重启次数按文件计。退出码 1 的部分失败按文件记账继续。
  - 唯一 GPU 锁：`ProcessLock` 于 `.local/gpu.lock`，第一个 GPU 阶段前获取，记录编排器、worker、server pid；破锁只认环境变量 `KOTOTOKI_BREAK_STALE_LOCK=1`。所有子进程进入 KILL_ON_JOB_CLOSE Job Object。
  - 无语音路径：VAD 空 → 直接发布三份零条目 SRT。
  - 三份 SRT 在 merge 后一起发布并写 `published.json`；覆盖按 00 的规则，带 `PermissionError` 重试。
  - 控制台与 `output_dir/.work/run-<时间戳>.log` 只有进度、计数、耗时。
- 测试保证 `import kototoki.job`／`kototoki.__main__` 之后 `sys.modules` 中没有 `torch`、`ctranslate2`、`faster_whisper`、`transformers`、`pyannote`、`torchaudio`、`torchcodec` 与任何 `experiments.*`。
- 文档随本票同步：架构总览"只写 `.local/`""已有目录拒绝"不变量加产品例外；AGENTS.md 重任务清单加 `python -m kototoki` 与 `kototoki.workers.*`。

## 完成标准

- 伪 worker 离线测试（`tests/`）：扫描与镜像、大小采样稳定性、发布前置判定、阶段顺序、崩溃文件隔离与按文件重启、失败隔离、中断后续跑、输出目录锁冲突与 GPU 锁冲突退出码、无语音路径、一起发布、禁止导入清单。

## 文件所有权

`kototoki/__main__.py`、`job.py`、对应测试、`docs/architecture/INDEX.md` 不变量段、`AGENTS.md` 重任务清单中本票新增的条目。

## Comments

- 2026-10-13 建票，依据规格 §12。
- 2026-10-14 按两轮评审修订（规格 §13）。
- 2026-10-14 第三轮评审：输出目录锁、大小采样稳定性、发布前置判定、按文件重启、环境变量破锁、`PYTHONUTF8` 与共用缓存、禁止导入清单、文档随票同步。
- 2026-10-14 票据 00 交接（用户裁定）：`failure.json` 在该文件重跑成功后的清理规则由本票决定并实现；发布顺序固定为 `publish_blockers` 放行 → `record_published` → 移动三份 SRT。
- 2026-10-14 实现（分支 `feat/bilingual-06`，worktree `../kototoki-06`）：`kototoki/__main__.py`、`kototoki/job.py`、`tests/test_job.py`、`tests/fake_worker.py`；模块页 [批次编排](../../../docs/architecture/modules/batch-orchestration.md)。接口补定（已写入目标架构页"worker 协议""翻译子系统"行）：
  - GPU 阶段产物的期望身份由编排计算，经 jobs `config = {"config_path", "identities": {id: 身份}}` 交给 worker，worker 用给定身份写产物；`inputs` 为 vad `{wav}`、asr `{wav, vad}`、align `{wav, asr}`；`vad.json` 的 `chunks == []` 即无语音。票据 03／07 须按此实现 worker 壳。
  - 翻译子系统除 `translate_document` 外还需暴露 `RECIPE_HASH` 与 `Session(config, on_server_pid=...)`（上下文管理器），`TranslateResult` 带 `translations`（cue id → 译文）与 `fallback_count`；`merge.merge(document, translations)`。05 未交付，编排以 `importlib` 在用到时导入，测试注入伪模块。
  - `probe.json` 同时承载 extract 记录（`extract` 键，含 PCM SHA256），不另设产物文件。
  - 产物身份暂不含模型文件 SHA256：期望值尚无归属（`recipes.py` 未记录），待 03 定下后由编排在 GPU 阶段前 `verify_model` 并写进身份。
  - "发布前置判定"分两步：扫描阶段只做 `publish_blockers`（被改动的文件不 probe、不进 GPU）；"已是最新"判定需要视频身份，在 probe 之后、GPU 阶段之前完成（每次运行都跑 ffprobe，<1 s／片，不跑 extract）。
  - worker `startup_failed`（与文件无关）时本阶段剩余文件全部失败、不逐个重启；其余异常退出按文件归因并从下一文件重启。
  - `failure.json` 清理规则（00 交接）：该文件本次成功发布后删除；重跑不看它，只按产物身份续跑。
  - Job Object：编排器把自身放进 KILL_ON_JOB_CLOSE Job Object，ffmpeg、worker 与 llama-server 自动继承，翻译子系统无需传句柄。
  - 输出目录残留锁与 GPU 锁同语义：默认拒绝，`KOTOTOKI_BREAK_STALE_LOCK=1` 时移除。
  - 顺带解决 main 合并提交 2377ac5 遗留在 `docs/architecture/INDEX.md` 与目标架构页的冲突标记（两边内容都保留）。
- 2026-10-14 验证：`tests/test_job.py` 26 条（伪 worker `tests/fake_worker.py`、伪翻译／合并模块、打桩的 `media.probe`／`extract` 与 `build_cues`），全量 `tests/` 158 条通过；`compileall` 通过。worktree 没有自己的 `.venv`，`just test`／`just check` 的 `uv run --locked --offline` 在此无法创建环境，改用主 checkout 的 `.venv` 解释器运行等价命令。遗留：`contain_children`（Job Object）在测试中被打桩，未自动验证；GPU 锁记录的 `worker_pid` 是 `Popen.pid`，venv 启动器下为父进程；真实 worker／llama-server／ffmpeg 下的整批运行留给 08。
- 2026-10-14 合并 main（含已交付的票据 03）：03 的 worker 壳自行计算身份（含模型文件 SHA256，期望值在壳内常量）并约定 jobs `config = {"engine", "models", "model_cache"}`，取代本票先前的"编排经 `config.identities` 传身份"与"身份暂不含模型 SHA"两项；编排改为调用壳的 `identity`／`model_files` 与 `gpu.verify_models`（缓存与 worker 共用）计算期望身份。`ja-cues.json` 的上游键改为 `align.json`，与壳的命名一致。用户裁定其余待决定事项按推荐执行（含输出目录残留锁与 GPU 锁同语义）。
