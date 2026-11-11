# 产品包架构整理（2026-11-11 review 的落地）

状态：**in progress**（2026-11-11 起草，同日开始执行，分支 `architecture-cleanup`）。  
目标：修掉 2026-11-11 架构 review 在产品包 `kototoki/` 里找到的问题：规则有两个归属的地方收成一个，身份 hash 的漏洞补上，产品不再为研究代码保留死代码。不加功能，不改任何转写、对齐、建表与翻译的输出。  
执行载体：tracker `.scratch/architecture-cleanup/`（spec、map、票据，Git 忽略）。本文是唯一进 Git 的计划与完成记录：完成后在 §7 填结果，状态改为 done。  
先读：[模块边界](../architecture/module-boundaries.md)、[架构总览](../architecture/INDEX.md)；模块页 [批次编排](../architecture/modules/batch-orchestration.md)、[阶段计划](../architecture/modules/stage-plan.md)、[产物契约](../architecture/modules/artifact-contract.md)、[STT worker](../architecture/modules/stt-workers.md)、[配置与媒体](../architecture/modules/config-and-media.md)、[日文 cue](../architecture/modules/japanese-cues.md)、[翻译子系统](../architecture/modules/translation-subsystem.md)、[专名一致性](../architecture/modules/name-consistency.md)；[ADR-0022](../adr/0022-product-names-on-strata.md)、[ADR-0024](../adr/0024-embedded-japanese-subtitles.md)、[ADR-0012](../adr/0012-cross-asr-judge.md)、[ADR-0023](../adr/0023-asr-repeat-guard.md)；[决定索引·记录新决定](../adr/INDEX.md#记录新决定)；[测试设计与验收](../agents/testing.md)、[验证边界](../testing/validation.md)；[CODING_STANDARDS](../../CODING_STANDARDS.md)。

## 1. 为什么

2026-11-11 对产品包做了一次分段 review（编排与产物契约、STT／媒体／cue、翻译／专名／Strata、仓库级依赖）。结论：

- 分层是健康的，四条硬规则都成立，各阶段期望身份只在 `plan.py` 写一次，不需要大改。
- 问题集中在三类：
  - 同一条规则在两处实现，两处已经不一致或只靠人手保持一致（GPU 锁冲突的失败级别、worker 退出码的解释、Strata 启动额度、`ja.srt` 的新鲜度判定、`cross` 路径）。
  - 身份 hash 没有覆盖全部影响输出的输入，改了行为会复用旧产物（媒体配方、`ja.srt`）。
  - 产品包为研究侧导入方保留已不使用的代码，产品核心测试又反过来导入研究代码。

用户同日裁定全部按 review 建议办，三项需要裁定的事见 §3。

## 2. 已知事实（不要重复调查）

行号是 2026-11-11 分支 `embedded-japanese-subtitles`（`c639b22`）上的位置，动手前以当时的源码为准。

**编排与协议**

- GPU 阶段撞 `.local/gpu.lock` 时 `GpuLocked` 向上抛，`__main__` 返回退出码 4（`job.py:884-888`、`__main__.py:51-53`）。names 与 translate 却把它捕获成逐文件失败（`job.py:703-708`、`741-747`）：整批退出码 1，每个文件的 `failure.json` 被写成 `GpuLocked`。批次编排页两种说法都写了。没有测试覆盖“首个需要 GPU 的阶段是 names”时的锁冲突。
- `run_gpu_stage` 用字面量解释协议：`if code in (0, 1): break`（`job.py:624`）、事件名 `"failed"`、`"startup_failed"`、`"fatal"`。常量定义在 `workers/protocol.py:28-30`。退出码 1 同时是 Python 未捕获异常的退出码：worker 在 `run_jobs` 之外崩溃时，剩余文件不重启，只在 `advance_or_fail` 里报产物缺失。“谁是崩溃文件、从哪重启”的算法（`job.py:634-642`）只能通过完整的 `job.run` 测到。
- `_launch`（`job.py:579-585`）读 stdout 期间抛异常（Ctrl+C、写日志失败）时不杀也不等 worker；`run()` 的 `finally` 随后放 GPU 锁。
- `_run` 末尾的发布循环没有兜底分支（`job.py:904-915`）：某个文件的 `plan.stage` 没被任何执行器处理时，既不发布也不失败，退出码 0。目前不会触发。
- `job.py:94-275` 是与流水线无关的进程原语（`pid_alive`、`process_created`、`process_matches`、`contain_children`、`ProcessLock`、`LockError`），复制自 `experiments/translation_v3/procs.py`，没有单元测试，只经 `job.run` 的 LockTests 间接覆盖。
- `job.py:399-412` 经 `importlib` 导入 `strata`、`names`、`translate`、`merge`。这四个模块都只依赖标准库，不导入 `plan` 与 `job`，直接导入不成环、不加载 torch。间接导入的唯一用途是让 `test_job.py:131-167` 往 `sys.modules` 里塞整个伪模块。
- `test_job.py:241-257` 的伪翻译模块自己重写了“只取 `confidence: high`”的注入规则与 run 目录键，`:959`、`:986` 两个测试断言的是伪模块，不是 `translate.plan`。
- `model_sha_lookup`（`job.py:421-424`）不缓存失败：模型 SHA 不符时每个文件都重新哈希一次。

**身份**

- `recipes.LAYOUT_BY_CHANNELS`（`recipes.py:34`）不在 `MEDIA` 里，`media.pan_filter`（`media.py:277`）用它给未标注布局的音轨选下混。音轨选择规则（`media.select_audio`，`media.py:185-200`）与 `LANGUAGE_ALIASES`（`media.py:49`）也不在 `MEDIA` 里。`plan.probe_identity`（`plan.py:135-138`）只哈希 `MEDIA`。
- cues 阶段对 `ja.srt` 只查文件存在（`plan.py:275-276`），`ja-cues.json` 不记 `ja.srt` 的 hash。内嵌路径记了并且核对（`job.py:462-465`）。两条路径不混淆，靠的是 `use_embedded_subtitle` 写 `ja.srt` 前先删 `ja-cues.json`（`job.py:475`）。
- `cues.FALLBACK_MAX_CHAR_S`（`cues.py:31`）与 `CUES["fallback_max_char_s"]`（`recipes.py:196`）是两份值，靠 `test_recipes.py:113` 钉相等。`guard.py:24` 是直接读配方的做法。
- 只有 W0、X0、CROSS 三个配方 hash 被测试钉住（`test_recipes.py:65-75`）；MEDIA、VAD、MMS、CUES、EMBEDDED 没有。
- 专名建表的 `USER_TEMPLATE`（`names/table.py:145`）与 cue 渲染（`table.py:350-358`）不在 `BUILD` hash 里；翻译的专名行格式（`translate/recipes.py:132`）与窗口 JSON 形状（`translate/batching.py:64-66`）不在 `RECIPE` hash 里。
- Strata 版本、引擎 build、模型、启动参数都在两个配方 hash 里，来源唯一（`strata.py:71-77`）。阈值与超时不在身份里，这是对的。

**Strata 与翻译**

- 启动失败额度有两个计数器：`strata.MAX_START_FAILURES = 3`（`strata.py:101`，整批）与 `generate.MAX_RESTARTS = 2`（`generate.py:53`，单次调用）。`generate.py:491` 与 `:497` 从外部写 `session.unavailable`，两处都是 `Session` 已经做过的事。前一部影片用掉部分额度后，翻译会把“启动额度耗尽”记成“Strata refused”。
- names 与翻译都伸手取 `Session` 的内部来组装客户端与 trace 目录：`session.runtime_root.name`、`session.ordinal`、`session.client_factory`（`names/__init__.py:96-97`、`generate.py:438-448`）。`client_factory` 文档上是测试用内部接缝（`strata.py:426`），实际是生产路径。
- `session.cache_state`（`strata.py:443`、`464`）只有翻译用。
- `kototoki/llama_server.py` 共 368 行，约 215 行产品不用：`ServerSpec`（45-56）、驻留函数（100-135）、`server_command`／`port_free`／`check_model`／`check_engine`（140-186）、`ManagedServer`（189-290）、`LlamaClient.tokenize`／`.complete`（355-365）。唯一使用者是 `experiments/translation_v3/qwen.py:396,413`（延迟导入）。`tests/core/test_llama_server.py` 约一半在测这些。产品实际使用：`InfraFailure`、`explicit_oom`（names、翻译），`LlamaClient`、`nvidia_smi`、`wait_for_free_vram`（`strata.py:58`），`list_llama_servers`（只有 `scripts/smoke/names_product.py:33`）。
- [ADR-0022](../adr/0022-product-names-on-strata.md) 第 4 点规定 `llama_server.py`“留在原文件、不挪不删”。

**STT 与 cue**

- `workers/asr.py` 里“读 WAV 与 VAD → 转写 → 计时 → 守卫 → 记失败 → 组文档”出现三次（`:92-100`、`148-154`、`159-164`）；守卫策略写两次（`:97` 的 `if engine == "w0"` 与 `:151`）。
- 约 35 行逐窗裁判决策在壳里（`asr.py:170-205`：`w0_failed`／`x0_failed`／`score_error` 的分类、计数、`window_record`、合并），`clean_x0`（`:109-123`）也在壳里。除打分回调外都不需要 GPU 与文件系统。
- `cross` 自己写三个审计产物并各自重复“查 CUDA 再写”（`asr.py:155-157`、`165-167`、`215-217`），因为 `gpu.Compute` 只能返回一个产物（`gpu.py:26`）。
- “引擎由哪些模型组成”写在四处：`config.ENGINES`（`config.py:28`）、`plan.ASR_RECIPES`（`plan.py:55`）、`plan.model_files` 的两个分支（`plan.py:109`、`114`）、`workers/asr.start`（`asr.py:236-262`）。
- `align.map_records` 给 units 加 offset（`align.py:180-181`），docstring 写明参数只为测试保留（`:155`）；`cues` 给窗口与 VAD 子段加 offset（`cues.py:50-51`）。文档说 cue 是唯一加 offset 的地方，对 units 不成立。产品 offset 恒为 0。
- `align.py` 有产品走不到的旧窗口分支：`sample_window` 对旧窗口返回 None（`:105-108`）、`clamp_window`（`:327-328`）、`int(start * SAMPLE_RATE)` 回退（`:262-265`）。ASR 适配器总是先 `validate_windows`（`asr_whisper.py:110`、`asr_qwen.py:80`）。
- `SAMPLE_RATE = 16000` 定义五次（`recipes.py:14`、`schema.py:13`、`vad.py:19`、`align.py:25`、`workers/gpu.py:23`），`MAX_WINDOW_SAMPLES` 两次（`recipes.py:15`、`schema.py:14`）。`format_srt` 收秒（`srt.py:128-132`），两个调用方手里都是整数毫秒（`cues.py:206-211`、`embedded.py:65`）。`embedded._ms`（`embedded.py:23`）与 `srt._milliseconds`（`srt.py:60`）重复。

**研究侧与测试**

- 5 个研究包的 27 个文件导入产品符号（`asr_robustness_v14` 11、`quality_v5` 7、`asr_robustness_v15` 4、`scene_batching_v6` 3、`translation_v3` 2），含私有名 `names.table._request_body`、`vad._seconds`、`strata.drafting_from_log`。其中 `translation_v3/strata.py` 与 `scene_batching_v6/v13.py` 是基线 Q3 的实现，必须保持可运行。这些包都不在冻结清单里，源码没有 sha256 自检。
- `tests/core` 有 5 个文件导入 `experiments.*` 作等价核对：`test_guard.py:15`、`test_judge.py:234,251-253`、`test_names_recipes.py:15`、`test_names_session.py:19`、`test_translate_recipes.py:68-152`。
- 没有全仓库范围的导入边界测试，只有 `test_guard.py:38`、`test_judge.py:275` 两个按模块的检查与 `test_job.py` 的禁止导入测试。
- `.local/gpu.lock` 约有 10 个写入方、4 种 payload，除产品外都在 `experiments/` 与 `scripts/smoke/`。全部用 `O_EXCL`，互斥有效；只有产品与 v3 记录 `pid_created` 并处理过期锁。

**文档漂移**

- `docs/architecture/INDEX.md:3` 写研究侧翻译基线是 Q2，没有提 Q3 与 ADR-0021；`:95` 写“产品与研究入口之间没有导入关系”，只对产品 → 研究这个方向成立；`:108-109` 写翻译 recipe 用根 `.venv`，justfile 实际用 `legacy`（Python 3.12、`--no-project`）环境。
- `module-boundaries.md:68` 与 `stt-workers.md:82` 把 `cross` 的“超出阈值回退为三段式整批转写”写成运行时行为，代码里没有，它是 ADR-0012 决策时的备选。
- `module-boundaries.md:48` 说 names 依赖 `config` 与 `llama_server（LlamaClient）`，实际导入的是 `InfraFailure`、`explicit_oom`，不导入 `config`；`:77` 说进程级是“退出码 2 → 从下一文件重启”，`startup_failed` 同为退出码 2 但不重启。
- `translation-subsystem.md:3` 的状态行仍写每包约 6 倍 F1 的耗时，同页 `:87` 已记录修复；`:80` 把 `LlamaClient` 列为翻译的导入。
- `kototoki/translate/__init__.py:6` 的 docstring 还在讲已删除的 `translate/strata.py`。`batch-orchestration.md:82` 的依赖清单漏了 `embedded` 与 `logs`；`job.py:18` 的 docstring 漏了 `name-table.json`。
- `experiments/w0_demo/README.md:41` 与 `:35` 对 `prepare_assets` 用哪个解释器说法不一。

**review 确认没问题、不要动的部分**

- `strata.py` 的范围、`generate.py` 的校验／降级分离、翻译续跑状态、names 与翻译的不对称、`media.py` 的内聚、`artifacts.py`、`protocol.py` 的 worker 侧、`gpu.py`、`tests/fake_worker.py`、`_Context`。
- `plan.py:170`、`176` 的延迟导入保留。

## 3. 已定决定（执行者不再询问）

用户 2026-11-11 裁定：

1. **GPU 锁冲突一律是进程级**：任何阶段撞 `.local/gpu.lock` 都以退出码 4 结束整批，不写逐文件 `failure.json`；已完成的 CPU 产物保留。零条目文件等到下一次运行再发布。
2. **接受补 `MEDIA` hash 带来的一次性重抽**：`LAYOUT_BY_CHANNELS` 与音轨选择规则进 `MEDIA`，现有工作目录的 `probe.json` 全部失效、各重抽一次音频。`MEDIA["id"]` 不变（行为没变）。PCM 逐字节不变，vad 及下游产物必须仍然当前，用测试证明。
3. **产品不为研究侧导入方保留代码**：`llama_server.py` 的产品死代码搬到 `experiments/translation_v3/`。这一点替代 ADR-0022 第 4 点，写进新 ADR。
4. **产品符号移动或改名时，同一提交里改研究侧的导入行**：只做机械的导入路径与名字替换，不改研究代码的行为。Q3 基线实现（`translation_v3/strata.py`、`scene_batching_v6/v13.py`）改完后其离线测试必须仍通过。
5. **`tests/core` 不再导入 `experiments.*`**：核心测试里的等价断言改成钉字面量或 sha256（值取自当前对照实现，注释写明来源与日期）。与研究实现的实时对照搬到 `tests/equivalence/`，由新的 `just test-equivalence` 运行，并入 `gate-full`，不并入 `gate-core`。

执行约定：

6. 工作分支：在当前 `embedded-japanese-subtitles` 的提交之上新建 `architecture-cleanup`（本计划依赖 ADR-0024 的代码）。
7. 新 ADR 编号 0025，一篇覆盖决定 1、3、4、5；决定 2 是配方内容变更，写进配置与媒体模块页与本文 §7，不单独立 ADR。
8. 除 `MEDIA` 外，任何配方 hash 都不得变：W0、X0、CROSS、VAD、MMS、CUES、EMBEDDED、翻译 `RECIPE_HASH`、建表 `BUILD_RECIPE_HASH`。票据 03 先把还没钉住的几个钉上，后面的票据以此为门。
9. `asr.json`、`align.json`、三个 `cross` 审计产物、`ja-cues.json`（除新增字段外）、`name-table.json` 与翻译 run 目录的内容和字节不变。
10. 没有第二个使用者就不加抽象：不建阶段注册表、不建后端协议。本计划新增的东西只有 `kototoki/procs.py`、一个协议纯函数、一张引擎组成表、`Session.client()`。
11. 接口形状变化先改模块边界与模块页，再改代码（AGENTS.md）。

## 4. 票据

执行者可在 map 里调整拆法，须写明理由。顺序即依赖：01 先行，02–09 依次做（07 须在 05 之后，其余相互独立时可调序），10 最后。

**01 ADR-0025 与文档先行**（Type: task）

- 新增 `docs/adr/0025-*.md`：决定 1、3、4、5。ADR-0022 只追加状态行（第 4 点被替代）。同一提交改决定索引（当前有效决定、演进链、全部 ADR、编号起点 0026）。
- 模块边界与模块页写入本计划会改的接口：`kototoki/procs.py`、`protocol` 的分类纯函数、`plan` 的引擎组成表与 `ja.srt` 新鲜度、`judge` 的整文件裁判函数、`Compute` 返回多个产物、`Session.client()`、`llama_server.py` 拆分后的模块名、offset 只在 cue 加、`tests/equivalence/`。
- 修 §2“文档漂移”列出的全部条目（代码 docstring 两条留给碰到该文件的票据）。`.local/gpu.lock` 的多个写入方在模块边界“并发与生命周期”里如实记一句。`workflow.md` 的门禁表加 `test-equivalence`。
- 门：不写产品代码；`just docs-check` 无新增失败。

**02 GPU 锁冲突统一成进程级；worker 协议的读侧收进 `protocol.py`**（Type: task）

- `names_batch`、`translate_batch` 不再捕获 `GpuLocked`，与 GPU 阶段一样向上抛；Strata 的 `with` 块此时尚未启动，正常退出。
- `protocol.py` 新增纯函数（名字执行者定，例如 `classify_launch(ids, exit_code, events)`），用协议自己的常量返回：已报失败的 id、崩溃文件、是否启动失败、剩余待跑 id。退出码 0／1 只有在每个待跑 id 都有事件时才算正常结束，否则按崩溃规则处理。`run_gpu_stage` 只留循环与 `ctx.fail`。
- `_launch` 读 stdout 的部分加 `try/finally`：进程还活着就 kill 并 wait。
- `_run` 结尾加不变量：每个未失败的文件必须已在 `published`、`existing` 或 `no_speech` 里，否则记 `publish` 阶段失败。
- `model_sha_lookup` 缓存失败结果。
- 测试：只含内嵌字幕文件的批次遇到存活的外部 GPU 锁 → 退出码 4、无 `failure.json`；分类函数的单元测试（正常、部分失败、`fatal`、`startup_failed`、无事件崩溃、退出码 1 但缺事件）；`_launch` 异常时子进程被回收；现有 IsolationTests 不改断言即通过。

**03 身份补洞**（Type: task）

- 先钉住 MEDIA（改之前的值，用于对比）、VAD、MMS、CUES、EMBEDDED 的 hash，与已钉的 W0、X0、CROSS 放在一起。
- `LAYOUT_BY_CHANNELS` 嵌进 `MEDIA`；`MEDIA` 新增音轨选择条目（规则说明＋`LANGUAGE_ALIASES`，别名表挪到 `recipes.py`，`media.py` 读它）。更新钉住的 MEDIA hash。
- `build_ja_cues` 在 `ja-cues.json` payload 里记 `ja_srt_sha256`；`plan` 的 cues 检查比对它，不再只查文件存在。“内嵌记录是否当前”的判定挪进 `plan`（与 cues 检查共用一个辅助函数），删掉 `job.py:475` 的先删 `ja-cues.json`。旧的 `ja-cues.json` 没有该字段，自然重建一次，不写兼容分支。
- `cues` 直接读 `recipes.CUES["fallback_max_char_s"]`，删自己的常量与钉相等的测试。
- `USER_TEMPLATE` 的 sha256、建表 cue 渲染的一个固定输出、翻译专名行格式与窗口 JSON 形状的一个固定输出，各用一条测试钉住（不进 hash，见 §6）。
- 测试：`MEDIA` hash 变了而 PCM 不变时，vad、asr、align、cues 仍当前；手改 `ja.srt` 后 cues 重建；STT 路径与内嵌路径互相切换（现有 EmbeddedSubtitleTests）仍通过；`CUES` hash 不变。

**04 Strata 额度与 `Session` 接口**（Type: task）

- `unavailable` 只由 `Session` 写：删 `generate.py:490-491` 与 `:497` 的赋值。`generate.py:434` 的预检查留不留由执行者定；留的话错误信息要能区分“启动额度耗尽”与“身份被拒”。
- `Session` 新增 `client(trace_root, timeout)`，返回 trace 目录为 `<trace_root>/<runtime_root.name>/session-NN` 的客户端；names 与翻译改用它，不再碰 `ordinal`、`runtime_root`、`client_factory`。trace 目录布局与 `run.json` 的 `sessions[]` 内容不变。
- `cache_state` 挪进翻译子系统（按 session 序号记）。
- 测试：前一部影片耗掉部分额度后，下一部的失败信息是额度耗尽；`test_translate.py:475-499` 的路径按新归属调整；trace 路径不变。

**05 拆 `llama_server.py`**（Type: task）

- `ServerSpec`、`ManagedServer`、驻留函数、`server_command`、`port_free`、`check_model`、`check_engine`、`LlamaClient.tokenize`／`.complete` 及其测试搬到 `experiments/translation_v3/`（文件名执行者定）。`translation_v3/qwen.py` 改导入。研究侧需要 `tokenize`／`complete` 时在那边用子类或函数补上，不留在产品类里。
- `nvidia_smi`、`wait_for_free_vram` 搬进 `kototoki/strata.py`。
- 剩下的 `LlamaClient`、`InfraFailure`、`explicit_oom` 改名为 `kototoki/local_client.py`（类名不变），不留再导出。`list_llama_servers` 只有 smoke 脚本用，搬到 `scripts/smoke/`。
- 同一提交改全部导入方：产品、`tests/core`、`scripts/smoke`、研究侧（决定 4）。
- 门：`git grep llama_server -- kototoki tests scripts` 只剩历史性注释或为空；Q3 基线实现与 `translation_v3` 的离线测试通过；禁止导入测试通过。

**06 `workers/asr.py` 的 `cross` 路径改为组合**（Type: task）

- 抽一个壳内辅助函数承担“转写 → 计时 → 守卫 → 记失败 → 组文档”，`compute` 与 `compute_cross` 的两路都用它；守卫是否生效由“这一路是不是 w0”决定，只写一处。
- `clean_x0`、`window_record` 与逐窗决策循环挪进 `judge.py`，成为一个纯函数（输入两路文本与失败窗口、打分回调、`CROSS` 参数，输出合并文本、逐窗记录、计数）。`judge` 仍不导入推理模块。
- `gpu.Compute` 改为返回若干 `(path, identity, payload)`；`file_processor` 查一次 CUDA 后全部写出，`asr.json` 最后写。
- `plan` 新增引擎组成表（`w0 → (w0,)`、`x0 → (x0,)`、`cross → (w0, x0)`），`model_files`、`workers/asr.start` 与守卫判定都读它。
- 门：CROSS、W0、X0 hash 不变；用现有 cross 测试的夹具对比，`asr.json` 与三个审计产物的内容不变；裁判决策规则有不经 worker 伪对象的直接单元测试。

**07 `job.py` 瘦身与编排测试**（Type: task，Blocked by: 02、04、05）

- `job.py:94-275` 的进程原语搬到 `kototoki/procs.py`（基础层：只用标准库与 ctypes）。`job.py` 从它导入，现有 `mock.patch("kototoki.job.contain_children")` 继续有效。给 `ProcessLock` 补直接单元测试：空文件、不可解析、无 `pid_created` 的外部锁、过期锁与破锁环境变量、release 只删自己的锁。研究侧 `quality_v5/coresidency_probe.py` 的导入按决定 4 改。
- `strata`、`names`、`translate`、`merge` 改为普通导入，删四个 `_xxx_module()`；`session: Any`、`result: Any` 换成真实类型。`test_job.py` 与 `test_plan.py` 改用属性 patch（`mock.patch("kototoki.translate.translate_document")` 等），`merge` 用真的。
- `test_job.py` 的伪翻译不再重写注入规则：身份取整张表的不透明 hash，只断言“表身份变了 → 需要模型 → 用 session、不重建表”。`confidence: high` 的注入规则改在翻译子系统的测试里对真实的 `translate.plan` 断言。
- 改 `job.py` docstring（漏 `name-table.json`）与 `translate/__init__.py` docstring。
- 门：`test_job.py` 的禁止导入测试通过；`job.py` 不再有 `importlib`。

**08 时间轴与小重复**（Type: task）

- `align.map_records` 与 `MmsAligner.align` 去掉 `offset` 参数，units 输出 WAV 本地秒；`cues` 给 units 也加一次 offset。`align.json` 的 `offset_s` 字段保留。删 `align.py` 三处旧窗口分支。
- `SAMPLE_RATE`、`MAX_WINDOW_SAMPLES` 只在 `recipes.py` 定义，其余模块导入。
- `srt` 提供整数毫秒入口，`cues` 与 `embedded` 直接用；`embedded._ms` 改用 `srt` 的函数。
- 门：MMS 与 CUES hash 不变；offset 为 0 时 `align.json`、`ja-cues.json`、`ja.srt` 字节不变（用现有夹具对比）；非零 offset 的行为由 cue 的测试覆盖。

**09 核心测试不再导入研究代码**（Type: task，Blocked by: 05）

- 按决定 5 改 `tests/core` 的 5 个文件：等价断言改成钉字面量或 sha256。
- 新建 `tests/equivalence/`，放与研究实现的实时对照（guard ↔ `v15.repeat`、judge ↔ `quality_v5`、names ↔ `v13`、翻译配方 ↔ `translation_v3`／`scene_batching_v6`）。justfile 加 `test-equivalence`，并入 `gate-full`。
- `tests/core` 新增一条全仓库边界测试：用 AST 扫 `kototoki/` 全部模块，不得导入 `experiments`、`kototoki_eval`；`tests/core` 自身不得导入 `experiments`。
- 门：`just test` 在不存在 `experiments/` 导入的前提下全过；`just test-equivalence` 全过。

**10 GPU 验证与收尾**（Type: task，Blocked by: 01–09）

- 按 §5 授权跑一次 `just smoke`。
- 各模块页“代码与验证入口”、技术设计规格、README 按[随交付同步](../agents/documentation.md#随交付同步)核一遍；`docs/INDEX.md` 的本计划条目改状态；按[待填标记](../agents/documentation.md#待填标记)的命令搜一次。
- 在 §7 写完成报告：已实现、自动检查、GPU 结果、未验证项。状态改 done，或写明停在哪张票据。

## 5. 验收、授权与停止条件

**离线验收**（每张票据）：

- `just test` 全过；`just test-full` 可运行就跑；票据 09 之后加 `just test-equivalence`。
- `just gate-core` 按契约不可能通过（`lint`、`typecheck` 未接入，见 [开发工作流](../development/workflow.md)）：逐项跑 `check-toolchain`、`docs-check`、`test`，`docs-check` 只看相对 main 的新增条目（main 上已有 44 处冻结外链失败）。
- 研究侧导入行改过的包，跑它自己的离线测试（有 just recipe 的用 recipe，没有的用 `python -m unittest discover` 指到该包，解释器按该包 README）。跑不起来的如实记进 §7，不为了让它通过去改研究代码的行为。
- §3 第 8、9 条的 hash 与字节不变，由测试证明，不靠目测。

**GPU 授权**（只限票据 10）：

- 只运行一次 `just smoke`（全部项）。运行前核实：没有 llama-server、没有别的 Strata launch 或 GPU 作业（PowerShell `Get-Process`），读 `.local/gpu.lock`，可用内存 ≥52 GiB。不抢占、不杀进程、不关用户的程序。内存不够等最多 10 分钟，仍不够就停下写进 §8。
- 不运行 `strata update`；`strata launch --plan` 显示下载量不为 0 时停下。
- 不运行 `python -m kototoki` 整片、不运行任何 demo 或 `experiments.*` 的加载模型入口。
- 结束后核实 `strata launch --status` 为空、显存已释放。

**smoke 的通过条件**：全部项通过，与改动前同样的判定（含 `x0_frozen_window` 已记录在案的已接受差异）。某一项失败时重跑该项一次；仍失败就停下，把失败项、输出摘要与怀疑的票据写进 §8，不改配方、不改 smoke 的判定。

**停止条件**（停下，写进 §8，不自行绕过）：

- 任何不该变的配方 hash 变了，或 §3 第 9 条的产物字节变了，而原因不是笔误。
- 某项改动需要修改研究代码的行为（不只是导入行）才能让 Q3 基线实现或其测试继续工作。
- 需要改环境（`uv sync|add|lock`、`just setup|install|upgrade`）。
- 需要改动冻结证据（`docs/context/*`、ADR 历史正文、`experiments/translation_judge/`、`experiments/translation_flow/v2_*`、`experiments/translation_eval/`）。
- 提交签名失败。

## 6. 不做的事

- 不改 `names` 的 `BUILD` 与翻译的 `RECIPE` 内容：把 `USER_TEMPLATE` 等放进 hash 会打破与 `names-strata-v4` 的逐字节一致，只用测试钉住，留到下一次有意的配方升级。
- 不改 `asr-judge.json` 里与复读守卫重名的 `guard` 字段：留到下一次 CROSS 配方升级。
- 不统一 `experiments/` 与 `scripts/smoke/` 里的 `.local/gpu.lock` 写入方。
- 不选定 lint 与类型检查工具，不改 `gate-core` 的组成（见 §8）。
- 不拆 `media.py`，不再拆 `job.py` 的阶段函数（`names_batch`、`translate_batch`、`publish`、扫描），不建阶段注册表或推理后端协议。
- 不把产品里的副本（`validate_transcript`、`normalize`、SRT、MMS、`chunk_intervals`）与研究代码合并或互相导入。
- 不裁剪 `strata.__all__`（研究侧在用）。
- 不为旧工作目录写兼容或迁移代码：身份不符的产物按现有规则重跑。
- 不加功能，不改配置项，不改日志格式。

## 7. 进度与结果

（每张票据完成后加一行：日期、票据号、做了什么、测试结果。）

改动前基线（`c639b22`，2026-11-11）：`just test` 651 项通过；`just test-full` 17 项通过；`just docs-check` 44 处失败（全部是冻结文档外链）；`just check-toolchain` 失败（本机 uv 0.13.0，`mise.toml` 钉 0.12.22，见 §8）。研究侧离线测试（根 `.venv` 解释器，`unittest discover -s experiments/<包> -t .`）：`translation_v3` 90、`quality_v5` 101、`asr_robustness_v14` 49、`asr_robustness_v15` 32 项全过；`scene_batching_v6` 81 项里 `test_v13` 本就有 3 失败 1 错误（见 §8）。

- 2026-11-11 **票据 01**：新增 [ADR-0025](../adr/0025-product-package-boundaries.md)（决定 1、3、4、5），ADR-0022 只追加状态行，决定索引同步（编号起点 0026）；模块边界、架构总览与 9 个模块页先行写入目标接口（`procs.py`、`classify_launch`、`ENGINE_PARTS`、`ja.srt` 新鲜度、`judge_file`、`Compute` 多产物、`Session.label`／`Session.client`、`local_client.py`、offset 只在 cue 加、`tests/equivalence/`），修掉 §2"文档漂移"的文档条目，`workflow.md` 与 `agents/testing.md` 加 `test-equivalence`。不含代码。`just docs-check` 失败清单与基线逐行相同，无新增。

## 8. 待用户裁定

- **lint 与类型检查工具**：`just gate-core` 因 `lint`、`typecheck` 未接入而不可能通过，这是工作流文档记录在案的现状。要让门禁可用，需要选定工具（会改环境）或把这两项从 `gate-core` 拿掉。本计划不动。
- **`just check-toolchain` 在本机失败**（2026-11-11 基线即如此）：本机 uv 是 0.13.0，`mise.toml` 钉 0.12.22。修它要改环境或改钉住的版本，本计划不动；各票据的离线验收因此只有 `docs-check` 与 `test` 两项有效。
- **`experiments/scene_batching_v6/test_v13.py` 在改动前就有 3 失败 1 错误**（`VariantTest.test_hashes`、`ClientTest.test_body_drops_response_format_and_states_no_thinking`、`IdentityTest.test_product_build_hash_unchanged_and_s1_separate`、`VariantTest.test_v3_keeps_response_format_and_502_is_a_failed_attempt`）：这些测试钉着 ADR-0022 之前的产品建表配方（`response_format`、`attempts`、旧 `BUILD` hash），产品换成 `q3-names-v1` 后没有跟着改。修它们要改研究测试的断言，超出"只改导入行"的授权；本计划只保证不新增失败。要不要修、怎么修，请裁定。
- **`Session` 的客户端接口与 §4 票据 04 的写法不同**：计划写 `Session.client(trace_root, timeout)`，由 `Session` 决定子目录 `<trace_root>/<runtime_root.name>/session-NN`。但翻译现有的 trace 目录是 `<run 目录>/transport/session-<run 内序号>`，只有 names 用 `<runtime_root.name>/session-NN` 作目录；照计划的签名做，翻译 run 目录的布局就要变，违反 §3 第 9 条。执行时改为 `Session.label`（只读，`<runtime_root.name>/session-NN`）＋`Session.client(trace_dir, *, timeout)`（目录由调用方给）：两处布局都不变，names 与翻译同样不再碰 `ordinal`、`runtime_root`、`client_factory`。如不同意请指出。
- ADR-0022 里"留在原文件、不挪不删"实际在决定第 6 点，不是 §2、§3 写的第 4 点；ADR-0025 与 ADR-0022 的状态行按实际出处写。
- 票据 01 没改的两处：`docs/specs/bilingual-subtitle-pipeline.md` 的移植来源表里仍写 `llama_server`（票据 10 核对规格时处理）；`experiments/w0_demo/README.md` 对 `prepare_assets` 解释器的两种说法（§2 列为文档漂移，但它在研究代码目录里，哪一种说法对需要跑环境才能确认，未改）。
- （执行中遇到的事项追加在这里。）
