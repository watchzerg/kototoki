# 14 阶段计划模块：阶段链与期望身份收进一个归属

Status: resolved
Type: task
Blocked by: —

## 背景

2026-10-15 架构评审（`/improve-codebase-architecture`，范围 `kototoki/`）的首推候选。"某阶段的期望身份是什么、上游是谁、产物叫什么、要核对哪些模型文件"这一个概念今天散在六处，没有唯一归属：

- `kototoki/job.py:46-51`：`STAGE_OUTPUT`／`STAGE_INPUTS` 持有 worker 输入名 `wav`／`vad`／`asr`，这些名字由 worker 壳的 docstring 定义，不由 job 定义。
- `kototoki/job.py:385-388`：`_worker_models` 持有模型键表（`w0_mel_assets` 等），worker 壳从无类型 dict 读同一组键。
- `kototoki/job.py:405-435`：`_next_stage` 硬编码上游链（vad←pcm、asr←pcm+vad、align←pcm+asr）；`job.py:414` 直接读 `vad.json` 的 `chunks` 判 `no_speech`，知道 worker payload 形状；`job.py:519` 取 `identities[stage]["recipe_hash"]`，知道身份 dict 形状。
- `kototoki/workers/vad.py:32`、`workers/asr.py:62`、`workers/align.py:40`：三个壳各有一份 `identity()`，第二次编码同一上游集合；`model_files()` 同样三份。
- `kototoki/job.py:351-355、427-434`：probe、ja_cues、translate 三份身份在 job 内联拼出，不经产物契约；`job.py:446-447` 自做 canonical 比对，与 `artifacts.is_current`（`artifacts.py:264`）重复。
- `tests/fake_worker.py:88-94`：伪 worker 另抄一份身份链，且 PCM SHA 取自 `probe.json`，而真 worker 由 `workers/gpu.py:48-60` 自己读 WAV 计算；job 与真 worker 算出不同身份时离线测试发现不了。

[模块边界·产品包的责任边界](../../../docs/architecture/module-boundaries.md#产品包的责任边界)写"跳过与替换由产物契约的 `is_current` 判定，编排只负责问"，现状偏离此规则；本票让代码回到规则，不改规则。

## 范围

- 新建一个阶段计划模块（建议 `kototoki/plan.py`，基础层，不依赖 torch／ffmpeg／网络），对外接口尽量小，形如：
  - `next_stage(work_dir, pcm_sha256, config, models) -> Plan`，`Plan` 含第一个需要运行的阶段（`vad`／`asr`／`align`／`cues`／`translate`／`publish`／`done`）、逐阶段期望身份、`no_speech`；每文件只计算一次，不改写调用方状态（替代 `job.next_stage` 的六次重算与对 `video.identities`／`video.no_speech` 的就地修改）。
  - `inputs(stage)`、`output(stage)`、`model_files(stage, engine, models)`：供 job 写 jobs 文件、worker 壳核对模型；`STAGE_INPUTS`／`STAGE_OUTPUT`／`_worker_models` 从 job 删除。
  - 各阶段 `identity`：三个 worker 壳的 `identity()` 迁入并只保留一份，壳与 job 都向本模块取；probe／ja_cues 身份一并迁入；translate 身份（今天的 `job.py:433`）先原样迁入，由[票据 15](15-translate-run-key.md)再交还翻译子系统。
- `is_current` 与发布来源比对仍归产物契约：本模块只产出期望身份，比对调用 `artifacts.is_current`；`job._publish_state` 的内联 canonical 比对改为调用产物契约（删除 `job.py:446-447` 的重复实现；发布流程的其余部分不在本票范围）。
- `tests/fake_worker.py` 改为经本模块取身份，不再自算；PCM SHA 从 WAV 计算还是从 `probe.json` 读取，按真 worker 的方式统一（真 worker 读 WAV 的 `read_wav` 保持不动，伪 worker 可写出带正确 PCM 的最小 WAV 或改用同一函数）。
- 不做：不改任何 `recipe_hash` 的输入与取值（三阶段的身份字段、键名与排序逐字节不变，用现有产物目录续跑必须全部命中跳过）；不改 worker `--jobs` 协议与退出码；不动推理模块；不合并 `media._wav_pcm` 与 `gpu.read_wav`（评审候选 7，另议）。

## 完成标准

- `tests/test_job.py` 全部用例不改断言通过；`tests/test_stt_workers.py` 的身份链用例通过。
- 新增测试：① 对同一工作目录，本模块为 vad／asr／align 产出的身份与真 worker 壳写出的身份逐字段相等（直接调用壳的 `compute` 产出路径不可行时，用壳的 `identity` 入口与本模块对拍，并断言壳不再自有一份实现）；② `next_stage` 对同一输入连续调用结果相同且不改写入参；③ 一次整批运行中每文件 `next_stage` 只被调用一次（可用计数器断言）。
- 用整片验收留下的现有 `.work/` 目录（`.local/bilingual-fullfilm-08/out-{w0,x0}/.work/`）离线运行 `python -m kototoki` 的扫描与计划阶段（不启动 GPU worker、不启动 llama-server；可在测试中以伪 worker 命令验证 jobs 文件为空），确认全部文件判为 `done` 或 `translate`→`done`：身份字节不变的证据。
- `tests/test_job.py::test_job_and_main_import_no_inference_stack` 继续通过；`tests/test_stt_workers.py::test_worker_shells_import_without_inference_libraries` 继续通过。
- 文档随交付同步：[批次编排](../../../docs/architecture/modules/batch-orchestration.md)、[STT worker](../../../docs/architecture/modules/stt-workers.md)、[产物契约](../../../docs/architecture/modules/artifact-contract.md)模块页的"接口与依赖"；[模块边界](../../../docs/architecture/module-boundaries.md)职责归属表新增一行并在依赖方向的分层图中登记基础层新成员；[架构总览](../../../docs/architecture/INDEX.md)的产品包装配图。接口形状要变时先改模块页与模块边界，再动手。

## 文件所有权

`kototoki/plan.py`（新）、`kototoki/job.py`、`kototoki/workers/{vad,asr,align}.py` 的 `identity`／`model_files`、`tests/fake_worker.py`、`tests/test_job.py`、`tests/test_stt_workers.py`、新测试文件，以及上列文档页。`kototoki/artifacts.py` 只允许删除被本票取代的重复实现，不新增接口（发布接口归评审候选 3，另开票）。不触碰 `kototoki/translate/`（票据 15 的所有权）。

## Comments

- 2026-10-15 建票，依据架构评审报告候选 1（Strong）与首推理由：局部性收益最大，做完后候选 6（编排器测试接缝）、7（PCM 读取器）、8（多次重算）自然缩小。票据 15 依赖本票：translate 身份先在此集中，再由 15 交还翻译子系统。

## Answer

2026-10-15 实现（用户授权由 agent 自行裁定架构细节）。

**实现**

- 新建 `kototoki/plan.py`：`STAGES`／`GPU_STAGES`、`STAGE_INPUTS`／`STAGE_OUTPUT`、`IDENTITY_KEY`、`worker_models`、`model_files(stage, engine, models)`（模型文件清单与固定 SHA256 从三个壳迁入）、`recipe_hash(stage, engine)`、五个身份函数（`probe_identity`、`vad_identity`、`asr_identity`、`align_identity`、`cues_identity`、`translate_identity`），以及 `Target`／`Plan`／`PlanError`、`next_stage`、`advance`。`Plan` 不可变，`sources` 属性给出 `published.json` 的来源身份。
- 票据建议的"每文件只计算一次"落为：`next_stage` 每文件每次运行恰一次（从 vad 起全量核对），某阶段跑完后 `advance` 从该阶段继续核对（同时替代 worker 后的产物核对与 cues 后的翻译身份计算），不再六次从头重算，也不就地改写调用方状态。
- `job.py`：删除 `STAGE_OUTPUT`／`STAGE_INPUTS`／`_worker_models`／`next_stage`／`_next_stage`／`_expected_sources`／`_publish_state`／`probe_identity`，不再导入 worker 壳；`VideoFile` 以 `plan: Plan` 取代 `identities`／`no_speech`；`model_sha_lookup`（每次运行每阶段最多核对一次的缓存策略）留在编排，因为它依赖 `workers/gpu.verify_models`。
- 三个壳删除各自的 `identity`／`model_files`／`RECIPE_HASH`／`RECIPES`，改向 `plan` 取；`tests/fake_worker.py` 经 `plan` 取身份、与真 worker一样用 `gpu.read_wav` 从 WAV 算 PCM SHA256（`tests/test_job.py` 的伪 extract 改写最小合法 WAV）。
- 发布状态比对：`plan._publish_state` 用 `artifacts.canonical` 规范化两侧后比较，不再 `json.loads` 重解析；未给产物契约新增发布接口（归评审候选 3）。

**裁定**

- `plan` 放在中间层（与 worker 壳、cues、翻译子系统同层），不是基础层：它为翻译身份延迟导入 `kototoki.translate.RECIPE_HASH`（票据 15 改为调用 `translate.plan`），壳不会触发这条边。模块边界与总览装配图已按此登记。
- `recipe_hash(stage, engine=…)`／`model_files(stage, models, engine=…)` 的 `engine` 为可选关键字参数，只有 asr 需要（review 后修订，去掉 vad／align 的占位实参）；asr 引擎不可用在这里报错，壳的启动失败由此而来。
- 发布状态比对："调用产物契约"与"不新增接口"在本票互相矛盾，取后者：比对留在 `plan._publish_state`，只用 `artifacts.canonical` 规范化，不再 `json.loads`；真正的发布接口归评审候选 3。
- 本票为壳 API 删除而同步改动了所有权之外的 `tests/{stt,x0}_frozen_window.py`、`tests/test_asr_qwen.py` 与规格 §4 一句，均为引用更新。
- 双轴 review（2026-10-15）后修订：`advance` 对已到终态的计划抛 `ValueError`；编排侧包装改名 `advance_or_fail` 以区别于纯函数 `plan.advance`。未采纳：`Plan | None` 的断言（`VideoFile` 在 CPU 阶段前就存在，断言表达的正是"计划已就绪"）、把模型 SHA 表拆出 `plan.py`（只有一个使用者）。`vad.json` 当前但读 `chunks` 出错时的归属由旧 `asr` 变为 `vad`（`is_current` 已保证可解析，实际不可达）。

**自动检查**

- `just test`：328 个用例通过（原 317 ＋ `tests/test_plan.py` 10 个 ＋ `tests/test_job.py::PlanCallTests` 1 个）；`test_job.py` 原有断言未改；`test_stt_workers.py` 改为经 `plan` 取身份并断言壳不再自有 `identity`／`model_files`／`recipe_hash`／`RECIPE_HASH`；`test_job_and_main_import_no_inference_stack`、`test_worker_shells_import_without_inference_libraries` 继续通过。
- 身份字节不变的证据（`.local/bilingual-fullfilm-08/out-{w0,x0}/.work/` 四个整片工作目录，脚本在会话临时目录、不进仓库）：① 每个 `vad.json`／`asr.json`／`align.json` 以其记录的上游 SHA 与模型 SHA 经 `plan` 重算，身份与产物内存的逐字节相等；`published.json` 的 translate 身份同样相等；`ja-cues.json` 只差 `recipe_hash`（票据 12 已改 CUES 配方，与本票无关）。② 旧代码（HEAD worktree）`job.next_stage` 与新代码 `plan.next_stage` 对四个目录给出相同阶段与相同期望身份。
- 离线整批运行（伪翻译模块、立即退出的 worker 命令、临时 GPU 锁）：四部影片都判为 `vad`，与旧代码一致——票据写"全部判为 done"的前提已被票据 10 推翻（MEDIA 配方 hash 变化、GPU 整片重跑被推迟），所以这次运行按产品规则重做了 extract（`probe.json`／`audio-16k.wav`／`audio.flac` 更新为 swr 版本，与票据 10 所述基线 PCM 一致），随后被拒绝启动的 worker 使四个文件记为 vad 失败；本次运行写出的 `failure.json`、运行日志与 stderr 日志已删除，`jobs-vad.json` 被同内容重写。这些目录要重新命中 done 须跑一次 GPU 整片（票据 10 遗留，执行前另问）。

**未验证**：真实 GPU worker 下的端到端（冻结窗口门禁 `just test-full stt_frozen_window`／`x0_frozen_window` 已改为经 `plan.recipe_hash` 取 jobs 配方 hash，未在本票运行）。
