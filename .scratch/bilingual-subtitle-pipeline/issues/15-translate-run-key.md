# 15 翻译子系统拥有自己的 run 键、续跑判定与"是否需要模型"

Status: resolved
Type: task
Blocked by: 14（已完成）

## 背景

2026-10-15 架构评审候选 2（Strong）。翻译 run 的键与续跑规则今天在五处分别拼出，编排器为了取锁时机越过接缝读 `ja.srt`：

- `kototoki/artifacts.py:183`：`translate_run_dir` 产出 `translate/srt-<sha12>/`，产品侧只有一个调用方（`job.py:614`）。
- `kototoki/translate/data.py:26`：`scene_from_document` 用同一个 `srt-<sha12>` 独立拼出 `scene_id`。
- `kototoki/translate/generate.py:362`：run 根目录为 `<配方名>__s<seed>`，按配方**名**而非 hash 分目录；`generate.py:238-250` 的 `_open_run` 再按 hash／seed／source 拒绝（`ValueError`），因此配方内容微调而名字不变时，同名目录成为需手工删除才能恢复的文件级失败。
- `kototoki/job.py:433-434`：`ids["translate"] = {ja_srt_sha256, recipe_hash, seed}` 是同一事实的第三份身份（票据 14 先把它集中到阶段计划模块）。
- `kototoki/job.py:608-617`：job 决定 run 目录；`job.py:760` 用 `any(srt.read_srt(...).cues ...)` 猜要不要取 GPU 锁，而只有翻译子系统知道"全部批次是否已完成"。最终 SRT 被用户删除时 `_publish_state`（`job.py:451`）返回 `translate`，job 取锁，但 `translate_document` 发现 run 已完成不起 server：锁被白取。
- `tests/test_job.py:119`：伪翻译实现靠 `Path(run_dir).parent.parent.name` 反推工作目录 id，依赖目录布局。

[模块边界](../../../docs/architecture/module-boundaries.md#产品包的责任边界)规定翻译 run 目录按 `ja.srt` SHA 分键（ADR-0007 决定 9），本票保持满足。

## 范围

- 翻译子系统新增一个计划入口（建议 `translate.plan(work_dir, document, config) -> TranslatePlan`），返回：run 目录（相对工作目录）、期望身份（即票据 14 迁入阶段计划模块的 translate 身份，本票把它的唯一实现放回 `kototoki/translate/`，阶段计划模块改为调用）、`needs_model: bool`（零条目文档或全部批次已完成时为 False）。`translate_document` 改为接收 `TranslatePlan`（或由它派生的信息），不再自己拼目录。
- 删除 `artifacts.translate_run_dir` 与 `translate/data.py` 的重复键；`scene_id` 只在翻译子系统内部定义一处。`data.py` 剩余的 `Cue`／`Scene` 若只剩包装 `srt.SourceDocument`，并入 `batching.py`（评审删除测试：它会移回 batching，本身是浅模块）。
- job 的改动：`translate_batch` 与发布循环改用 `TranslatePlan`；`job.py:760` 的 ja.srt 猜测删除，GPU 锁按 `any(plan.needs_model)` 获取；伪翻译实现不再依赖目录布局。
- run 目录对配方变化的处理：**待用户裁定**（见 Comments 问题 1）。两种方案：
  - A（维持现状）：目录名仍为 `<配方名>__s<seed>`，hash 不符仍拒绝；只把拒绝消息补上"删除该目录可重跑"的提示。
  - B：目录名改为含配方 hash 前缀（如 `<配方名>-<hash12>__s<seed>`），配方变化即新目录、旧目录保留为证据，与中间产物"身份不匹配即原地替换"的精神一致但不删旧 run。
  两者都不改 `b10-joint-degrade-v1` 的 `RECIPE_HASH`、提示、grammar、采样与请求字节；只有目录命名不同。
- 不做：不改批次、降级与 `batches.jsonl`／`degrade.jsonl`／`scene.json`／`report.json` 的内容与格式（现有 run 目录在方案 A 下必须原样续跑命中）；不动 `Session`／`ManagedServer` 生命周期（评审候选 4，另议）；不改 `merge.py`。

## 完成标准

- `tests/test_translate.py` 全部用例通过；`test_changed_ja_srt_uses_a_new_directory_and_keeps_the_old`、`test_seed_change_uses_its_own_run`、`test_rerun_of_a_complete_run_does_not_start_a_server` 改为经 `translate.plan` 断言键与 `needs_model`。
- 新增 `tests/test_job.py` 用例：① 全部 run 已完成（或全部零条目）时整批运行不取 GPU 锁（现有伪翻译即可构造）；② 删除最终 SRT 后重跑只重新发布，不取 GPU 锁、不调用 `translate_document` 起 session（对应 `job.py:760` 的泄漏）。
- `grep -rn "srt-" kototoki/` 中 `srt-<sha12>` 的拼接只剩翻译子系统内一处；`artifacts.translate_run_dir` 与 `translate/data.py` 不再存在（或 `data.py` 不再含键拼接）。
- 方案 A 下：用 `.local/bilingual-fullfilm-08/out-{w0,x0}/.work/` 现有 run 目录离线验证 `translate.plan` 对每部影片返回 `needs_model=False`（不启动 llama-server）。方案 B 下：同一目录返回 `needs_model=True` 且目录名为新格式，旧目录保留；在 Comments 记录这意味着整片需重翻一次（GPU 重任务，执行前另问）。
- 文档随交付同步：[翻译子系统与双语合并](../../../docs/architecture/modules/translation-subsystem.md)、[产物契约](../../../docs/architecture/modules/artifact-contract.md)、[批次编排](../../../docs/architecture/modules/batch-orchestration.md)模块页；[模块边界](../../../docs/architecture/module-boundaries.md)职责归属表的"产品翻译"行加 run 键与 `needs_model` 归属、"产物契约"行删 `translate_run_dir`；[技术设计 §6](../../../docs/specs/bilingual-subtitle-pipeline.md) 若写有 run 目录命名，按裁定更新；[GLOSSARY](../../../GLOSSARY.md)"产物身份"条目如需提及翻译 run 键则补一句。

## 文件所有权

`kototoki/translate/`（全部）、`kototoki/artifacts.py` 中 `translate_run_dir` 的删除、`kototoki/job.py` 的 `translate_batch`／发布循环／`job.py:760`、`kototoki/plan.py`（票据 14 产出）中 translate 身份改为调用翻译子系统、`tests/test_translate*.py`、`tests/test_job.py` 的伪翻译实现与新增用例、`tests/test_artifacts.py` 中 `translate_run_dir` 用例的删除，以及上列文档页。

## Comments

- 2026-10-15 建票，依据架构评审报告候选 2（Strong）。依赖票据 14：translate 身份先由 14 从 `job.py:433` 集中到阶段计划模块，本票再把它交还翻译子系统并让阶段计划模块反向调用；两票同时改 `job.py` 的身份段会冲突，故串行。
- 2026-10-15 **待用户裁定（问题 1）**：run 目录对配方内容变化采用方案 A（维持按名分目录、hash 不符拒绝）还是方案 B（目录名含 hash，自动另开目录）。评审意见：A 零迁移风险、保持与 v3 实验"同名配方内容不同拒绝续跑"规则一致；B 消除"改配方后需手工删目录"的失败模式，但现有四部整片的 run 在新命名下不再命中，需重翻一次。裁定后把本票 Status 改为 `ready-for-agent`。
- 2026-10-15 用户授权由 agent 裁定（本轮任务说明："优化决策都是你来决定"）：**采用方案 A**。理由：零迁移（四部整片现有 run 原样命中、不重翻）；与 v3 "同名配方内容不同拒绝续跑"规则一致；配方改内容本就应改名（票据 09 的 `b10-joint-degrade-v1` 即先例），把"改内容不改名"做成自动另开目录会掩盖这一约定。拒绝消息补上"删除该目录可重译"。

## Answer

2026-10-15 实现（用户授权由 agent 裁定方案）。

**实现**

- `kototoki/translate/generate.py`：新增 `TranslatePlan(work_dir, run_dir, identity, needs_model, document)`（`relative` 给出相对工作目录的 posix 串）与 `plan(work_dir, document, config)`：run 目录 `<work_dir>/translate/srt-<sha12>/<配方名>__s<seed>/` 在此唯一拼出；`needs_model` 在零条目或 `run.json` 记 `complete` 时为 False；只读、不写文件。`translate_document(plan, session)` 改收计划，`needs_model=False` 时 `session` 可为 `None`，只读回已完成的 run（run 记完成而批次缺失时抛 `TranslateError`，不起 server）。`plan` 与 `_open_run` 共用 `_check_run`：hash／seed／来源不符的拒绝消息带 "Delete <dir> to translate again"。
- `kototoki/translate/batching.py`：`source_key(sha)` 是 `srt-<sha12>` 的唯一出处（场景 ID 与目录键共用）；原 `data.py` 的 `Cue`／`Scene`／`scene_from_document` 并入，`data.py` 删除；`degrade.py` 改从 `batching` 导入。
- `kototoki/artifacts.py`：删除 `TRANSLATE_DIR`／`translate_run_dir`。
- `kototoki/plan.py`：`translate_identity` 改为 `translate_plan(work_dir, config)`（读 `ja.srt` 后调用 `translate.plan`），`Plan` 新增字段 `translate`（核对到翻译阶段后才有），`_publish_state` 沿用其 `identity`。
- `kototoki/job.py`：`translate_batch` 改用 `video.plan.translate`；只有任一文件 `needs_model` 才建 `Session`，否则用 `nullcontext`；不需要模型的文件传 `session=None`。翻译前 GPU 锁改为 `any(plan.translate.needs_model)`，删除 `srt.read_srt(...).cues` 的猜测；发布循环用 `plan.translate.document`，`published.json` 的 `translate_dir` 现在是完整 run 根（`translate/srt-<sha12>/<配方名>__s<seed>`），它不在 `sources` 比较之内，现有记录不因此失效。
- `tests/test_job.py` 伪翻译模块提供 `plan`（目录同形，`needs_model` 由伪 `translate_done` 集合决定），`_translate_document` 用 `plan.work_dir.name` 取 id，不再反推目录层级；新增 `TranslatePlanTests`：① 两部影片 run 已完成、各删一份最终文件后重跑只重新发布，`translate:` 调用时无 GPU 锁、无 session、无 `session_enter`，不新起 worker；② 零条目文件删最终文件后重跑不取锁、无 session。`tests/test_translate.py` 三个指定用例改经 `translate.plan` 断言键与 `needs_model`，另加 `plan` 键／身份用例、hash 不符拒绝用例、"run 记完成但批次缺失"用例；`test_plan.py` 伪翻译模块提供 `plan` 并断言 `Plan.translate`；`test_artifacts.py` 删 `translate_run_dir` 用例。

**自动检查**

- `uv run --locked --offline python -m unittest discover -s tests -t .`：332 个用例通过（328 ＋ 新增 4 净增：test_translate +3、test_job +2、test_artifacts −1）。
- `grep -rn "srt-" kototoki/`：只剩 `translate/batching.py` 的 `source_key` 一处拼接（其余为注释）；`artifacts.translate_run_dir` 与 `translate/data.py` 不存在。
- 方案 A 离线验证（脚本在会话临时目录，不进仓库，不启动 llama-server）：`.local/bilingual-fullfilm-08/out-{w0,x0}/.work/` 四个整片目录上 `translate.plan` 均返回 `needs_model=False`，`identity` 与各自 `published.json` 的 `sources.translate` 相等，`run_dir` 指向现有 `b10-joint-degrade-v1__s20261008` 目录。
- `compileall` 通过；改动文件无 CRLF。

**未验证**：真实 llama-server 下的端到端（翻译请求字节未改，由 `test_translate_recipes.py` 钉子测试守住）。

**双轴 review（2026-10-15，固定点 608ea05，Standards／Spec 两个 sonnet 子 agent）**

- 采纳并修订：① Spec 发现的回归——`Session` 建不起来时整批失败，连零条目／run 已完成、本不需要模型的文件也失败；改为只让 `needs_model` 的文件失败，其余照常读回并发布，新增用例 `test_session_failure_only_fails_files_that_need_the_model`。② Standards 的重复代码——`any(needs_model)` 在 `_run`（取锁）与 `translate_batch`（建 session）各算一次；GPU 锁的获取移进 `translate_batch`，与 session 同处一个 `if needed`。③ `Plan.translate`／`translate_plan` 的 `Any` 改为 `TYPE_CHECKING` 下导入的 `TranslatePlan`，运行时仍延迟导入。④ `VideoFile.translate_plan` 属性取代 `video.plan.translate` 链与 `assert plan is not None`。
- 记录但不改：`session` 用 `contextlib.nullcontext()` 作"不需要模型"的占位（拆成两条显式路径会复制循环体）；`TranslatePlan.work_dir` 只用于算 `relative`（保留，`translate_document` 内部与伪翻译模块都以它为工作目录标识）；伪翻译模块用 `SimpleNamespace` 复刻字段（改用真 dataclass 会让 test_job 导入翻译子系统，违背该测试"伪模块注入"的隔离）。
- Spec 轴指出的时机变化（记录为已知）：`run.json` 与期望 hash／seed／来源不符时，拒绝由翻译阶段提前到阶段核对（`PlanError`，记为该文件 translate 失败）；已发布且最终文件未动的文件此前不会读 `run.json`，现在也会。这是把"run 是否可续"纳入计划的必然结果，错误消息已含删目录提示。
- Spec 轴列为范围外但保留：`translate_document` 对"run 记完成但批次缺失"抛 `TranslateError`（`needs_model=False` 时不建 session，这条路径必须有明确失败而不是静默空译文），以及 `plan` 的 hash 不符拒绝用例。
- 自动检查：全量离线测试 333 个通过。
