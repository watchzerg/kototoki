# 产品建表切到 Strata（对齐基线 Q3）

状态：**done**（2026-11-09；票据 01–07 全部完成，GPU 验证 smoke 与 HF-II 整片均通过，见 §7）。  
目标：产品 `kototoki/` 的 `names` 阶段改为在 Strata 上用 Qwen3.8-Flash-Next 建表，建表规则与基线 Q3（[ADR-0021](../adr/0021-q3-strata-names-baseline.md)）的 `names-strata-v4` 相同。names 与 translate 共用同一个 Strata 实例，产品不再启动 llama-server、不再加载 27B。  
执行载体：tracker `.scratch/q3-product-switch/`（spec、map、票据，Git 忽略）。本文是唯一进 Git 的计划与完成记录：完成后在 §7 填结果，状态改为 done。  
先读：[ADR-0021](../adr/0021-q3-strata-names-baseline.md)、[ADR-0019](../adr/0019-product-translation-q2.md)、[ADR-0014](../adr/0014-name-consistency-in-product.md)；[模块边界](../architecture/module-boundaries.md)；模块页 [专名一致性](../architecture/modules/name-consistency.md)、[翻译子系统](../architecture/modules/translation-subsystem.md)、[批次编排](../architecture/modules/batch-orchestration.md)、[阶段计划](../architecture/modules/stage-plan.md)、[配置与媒体](../architecture/modules/config-and-media.md)；[技术设计](../specs/bilingual-subtitle-pipeline.md)；[测试设计与验收](../agents/testing.md)、[验证边界](../testing/validation.md)；[CODING_STANDARDS](../../CODING_STANDARDS.md)。

## 1. 为什么

- 用户 2026-11-09 采纳 Q3 为唯一翻译基线。基线的表由 Strata 建，产品的表仍由 27B＋llama-server 建，两者不一致（[决定索引·未关闭项](../adr/INDEX.md#未关闭项)）。
- 切换之后，产品的两种推理服务只剩 Strata 一种。可以去掉 names 的 llama-server 生命周期、27B 模型配置，以及"停 llama-server → 等显存、等内存释放 → 启 Strata"这一步交接。2026-11-08 整片变慢，起因之一就是这一步。

## 2. 已知事实（不要重复调查）

- **Q3 建表的研究实现**在 `experiments/scene_batching_v6/v13.py`，只读，产品不得导入 `experiments.*`，需要时复制：
  - `s1_recipe("v4")`：配方 `names-strata-v4`，hash `38cb7bcd…`；
  - `NamesClient`：Strata 上的 `chat`／`tokenize` 回调，`tokenize` 走 `/v1/messages/count_tokens`，不可用时的退路也在这里；
  - `build_one`：外层重试，以 seed＋2k 反复调用 `build_table`，`client.remaining` 限制总请求数。
- **产品的 `build_table`**（`kototoki/names/table.py`）：v13 原样导入使用。内部两次尝试（seed、seed＋1），终态失败（`too_long`、`failed`）返回空表。v13 v4 的请求序列因此是 seed、seed＋1、…、seed＋4，最多 5 个请求，取第一张合格的表。
- **Strata 生命周期**（`kototoki/translate/strata.py::StrataServer`）在产品里已经验证过（ADR-0019）：
  - 启动前：`--status` 为空、空闲显存 ≥14000 MiB、可用内存 ≥52 GiB；
  - 启动：`strata launch --no-tui --model iq3_s`；
  - 接入后：做接入检查，确认专家区为 `ram`，否则拒绝；
  - 退出：`--stop`，并核实显存释放。

  v13 的 GPU 入口直接复用了这个类：一个 session 里先建表、再翻译，整机内存峰值 60.4–62.4 GiB（共 63.9）。
- **当前产品结构**：
  - `job.names_batch` 持有 `names.Session`（llama-server，`ManagedServer`，整批最多启动 3 次）；
  - `job.translate_batch` 持有 `translate.Session`（Strata，同调用内重启、`StrataRefused` 置 unavailable）；
  - 两个 Session 互相独立，按顺序各起各停。
- **names 不导入翻译子系统**，这是模块边界的规则。只有 `kototoki/translate/` 依赖 `translate/strata.py`。
- **`kototoki/llama_server.py` 不能删**：
  - 翻译子系统要用其中的 `LlamaClient`、`InfraFailure`、`wait_for_free_vram`、`nvidia_smi`、`explicit_oom`；
  - 研究侧 `experiments/translation_v3/{qwen,server,generate,strata}.py` 也导入它，其中包括 `ManagedServer`。
- **研究侧仍要用的资产**（Q0／Q1 的研究、H0 对照）：`assets.toml` 里的 llama.cpp 工具与 `unsloth/Qwen3.8-27B-GGUF` 条目。
- **身份与续跑**：
  - names 的身份是 `{ja_srt_sha256, recipe_hash, seed}`（`plan.names_identity`）。建表配方一变，旧 `name-table.json` 全部失效、重建；注入行跟着变，`names_sha256` 变，进而重译。
  - 已发布的影片（源文件旁已有 `ja-zh.srt`）按 ADR-0020 直接跳过。
- `scripts/smoke/names_product.py` 现在走 llama-server。

## 3. 已定决定（执行者不再询问）

1. **建表与 Q3 等价**：
   - 产品建表的提示、schema、采样、`max_tokens` 8192、context 24576（提示预算 15872）、归一兜底，与 `names-strata-v4` 相同；
   - 请求不带 `response_format`，带 `chat_template_kwargs.enable_thinking: false`，`model` 为 `qwen3.8-flash-next-iq3_s`；
   - 预算检查用 `/v1/messages/count_tokens`，system 与 user 两段分别计数再相加；不可用时的退路与 v13 相同；
   - 请求序列为 seed、seed＋1、…、seed＋4，取第一张合格的表，不挑选（ADR-0008）；
   - 5 次都失败时写空表，翻译照常进行、不注入，同现行规则。

   实现可以在产品内部直接做 5 次尝试，不必照搬 v13 的外层循环，但请求体与 seed 序列必须与 v13 `NamesClient`＋`build_one` 逐字节一致，由测试守门：测试里可导入 experiments 作参照，产品代码不行。
2. **建表配方新名、新 hash**：
   - 产品 `BUILD` 改为新配方，配方名由执行者定，须与 `names-strata-v4` 区分，因为 hash 不同（产品配方不含研究侧的说明字段）；
   - `BUILD_RECIPE_HASH` 由 `tests/core/test_names_recipes.py` 钉住；
   - 模块页与新 ADR 写明它与 `names-strata-v4` 的对应关系（逐项列出相同与不同）；
   - 运行时身份（Strata 版本、引擎 build、默认启动的解析值、KV）进配方，取值与翻译配方一致。
3. **names 与 translate 共用一个 Strata session**：
   - 整批只启动一次：第一次真正需要模型时启动（可能在 names，也可能在 translate），两阶段之间不停；
   - 整批结束、出错或编排被中断时都 `--stop`，并核实显存释放；
   - 不需要模型时不启动；
   - 启动前的检查、接入检查、专家区检查不变；
   - GPU 锁照常记录 Strata 的 pid；
   - 任何阶段都不启动 llama-server。
4. **模块位置**：
   - Strata 的生命周期移出翻译子系统的内部，放到 names 与翻译都能依赖的中间层（建议 `kototoki/strata.py`，与 `llama_server.py` 同层）。共享的 session（启动计数、`unavailable`、`ensure_started`／`stop`）也放在这一层，由编排器持有，传给两个阶段。
   - names 仍不导入翻译子系统，翻译子系统也不导入 names。翻译子系统保留自己的同调用内重启与降级逻辑，只是改用共享的 session。
   - 接口细节由执行者设计，但**先改模块边界与模块页，再写代码**（AGENTS.md 的规则）。这是第二个使用者出现后的正当抽取，在模块边界的"接缝"一节写明。
5. **失败路径**：
   - 建表请求遇到传输失败、HTTP 错误、OOM：停掉 Strata，该影片 names 阶段记文件级失败；下一个需要模型的影片再启动 Strata。
   - 整批启动 Strata 的总次数上限，取翻译现行规则与 names 现行"最多 3 次"中更严的一个，写进模块页。
   - `StrataRefused`（身份不符、已有别的 launch、专家区退到 mmap）不重试：共享 session 置为不可用，本批其余需要模型的影片在 names 和 translate 都直接失败。
6. **删除与保留**：
   - 产品里删除 names 的 llama-server 路径：`NAMES_SERVER`、`NAMES_SPEC`、names 的 `Session`、`BUILD["model_asset"]`。
   - 配置键 `[names] model`、`[names] port`、`[paths] llama_server` 与默认的 27B 模型路径，若产品已无其他使用者就删除。写了这些键的旧配置按"未知键"报错，同 ADR-0019 的做法，不做兼容垫片。
   - `kototoki/llama_server.py` 保留翻译和研究侧要用的部分。`ManagedServer` 只剩研究侧使用者时仍留在原文件，不挪动、不删除，在模块边界里写明"产品不再使用"。
   - `assets.toml` 的 llama.cpp 与 27B 条目保留，标为研究侧使用；`just install`／`fetch-models` 的行为不改。
   - `experiments/` 不动。
   - `scripts/smoke/names_product.py` 改走 Strata。
7. **ADR**：新增 ADR-0022（产品建表切到 Q3），替代以下各点：
   - ADR-0014 第 3 点的建表模型与 llama-server 部分；
   - ADR-0019 第 2 点"names 阶段整批用 llama-server 建表、两者不同时驻留"；
   - ADR-0007 第 3 点里剩下的建表引擎部分。

   按[决定索引·记录新决定](../adr/INDEX.md#记录新决定)同一提交同步：决定索引里"产品与基线 Q3 不一致"一条改为已关闭；AGENTS.md 的产品句、GLOSSARY 的 Q3 词条（"未进产品"）、README 一并改。ADR-0021 正文不改，只在状态行追加"产品已于某日切换"。
8. **不兼容旧产物**：旧 `name-table.json`、旧翻译 run 目录按身份失效，重建、重译，不写迁移。

## 4. 票据（建议拆法，执行者可在 map 里调整，须写明理由）

1. **设计与文档先行**：写 ADR-0022 并同步决定索引；改模块边界（依赖方向、中间层 `strata`、共享 session、接缝一节）和受影响的模块页（专名一致性、翻译子系统、批次编排、阶段计划、配置与媒体）、技术设计规格。不写代码。
2. **Strata 生命周期下沉为共享模块**：`StrataServer` 与共享 session 移到中间层，翻译子系统改用它。行为不变：现有的 `test_translate_strata.py`、`test_translate.py` 全过，必要时只改导入路径；禁止导入测试照常守门。
3. **names 改走 Strata**：
   - 新 `BUILD` 配方与 hash；
   - Strata 上的 chat 与 `count_tokens` 回调，以及退路；
   - 5 次尝试；
   - 伪服务测试：正常、首次失控后重试成功、5 次都失败写空表、`count_tokens` 不可用的退路、传输失败与 `StrataRefused`。
   - 与 v13 逐字节对照：给定合成文档与伪回复序列，比较请求体与 seed 序列。
4. **编排共用 session**：
   - `job` 持有共享 session，跨 names 与 translate 使用，整批只启动一次；
   - 中断或出错时 stop；
   - GPU 锁写入 pid；
   - names 全部 current、只有 translate 需要模型时，从 translate 开始启动；
   - 两阶段都不需要模型时不启动。
   - 都用伪服务测。
5. **删除与配置**：删 names 的 llama-server 路径与配置键，改 `kototoki.toml.example`、`config` 测试、资产清单测试（`test_assets_manifest.py`）里与产品相关的部分；smoke 脚本改走 Strata；依赖文档、技术选型、开发工作流按[随交付同步](../agents/documentation.md#随交付同步)更新。
6. **GPU 验证**（授权见 §5）：
   - `just smoke names_product`（改后走 Strata）；
   - 一部产品整片端到端：`python -m kototoki`，HF-II，W0，用全新工作目录与输出位置，做法同 2026-11-08 的 `.local/q2-product-fullfilm-2/`，确保源文件旁没有已发布的 `ja-zh.srt`。
7. **收尾**：§7 填结果，搜待填标记，检查 `kototoki/` 里是否还残留 names 的 llama-server、27B、`NAMES_SERVER`。

## 5. 验收、授权与停止条件

**离线验收**：
- `just gate-core` 全过（`docs-check` 在 main 上本就有 44 处冻结外链失败：只看新增的条目，不看退出码）。
- 以下行为都有测试：
  - 与 v13 逐字节一致；
  - 5 次尝试与空表；
  - 共享 session 只启动一次；
  - 中断时 stop；
  - `StrataRefused` 让两个阶段都失败；
  - 不需要模型时不启动；
  - 改表使翻译失效；
  - 禁止导入守门。
- `just test-full` 若可运行就跑。

**GPU 授权**（只限 §4 第 6 张票据）：
- 每次开跑前核实：没有 llama-server、没有别的 Strata launch 或 GPU 作业（`Get-Process` 核实，读 `.local/gpu.lock`），可用内存 ≥52 GiB。
- 不抢占、不杀进程、不关用户的程序。可用内存不够就等最多 10 分钟，仍不够就停下，写进 §8。
- 不运行 `strata update`；`strata launch --plan` 显示下载量不为 0 时停下。

**整片的通过条件**：
- names 与 translate 只启动一次 Strata，`expert_arena` 为 `ram`，全程没有 llama-server 进程；
- 建表 `ok`，记录实际用了几次尝试。若这一部 5 次都失败：产品按规则写空表、照常翻译，这不是停下的理由，但验证算不过，在 §7 如实记录（失败原因分布、每次耗时），并在 §8 写明是否要换一部再验；
- 翻译交付失败 0，回退计数如实记录；
- 双语 SRT 条数等于 `ja.srt`，`ja-zh` 全为两行；
- `--stop` 后 status 为空，空闲显存回到 ≥14000 MiB；
- 记录内存与显存峰值、建表耗时、翻译每包耗时。

**停止条件**（停下，写进 §8，不自改配方）：
- 专家区退到 mmap；
- 整机内存溢出；
- 翻译失败率明显高于 v13（v13 dev 6 run、产品 6 run 交付失败共 1 个包）；
- 需要改 Q3 的建表规则或翻译配方；
- 需要运行改环境的命令（`uv sync|add|lock`、`just install`／`setup`／`upgrade`）。

## 6. 不做的事

- 不改 Q3 的建表规则（提示、schema、采样、上限、尝试次数、归一）与 Q2 翻译配方 `q2-degrade-v1`。
- 不做多次建表或多次翻译再挑选（ADR-0008）。
- 不跑裁判，不做质量评测，不开封确认集。
- 不改 `experiments/`、冻结证据、ADR-0021 正文。
- 不删 `assets.toml` 里研究侧要用的条目，不删磁盘上的 27B 权重。
- 不推送，不开 PR。按功能分次提交，提交信息用中文，不绕过签名；签名失败时停下，写进 §8。
- 子 agent 显式指定 model（默认 `sonnet`，不用 Fable），写入者拿互不重叠的文件。

## 7. 进度与结果

（执行者填写：每张票据一行，含日期、提交、测试结果、GPU 数字；最后写完成报告，区分已实现、自动检查、GPU 结果、未验证项。）

- 2026-11-09 票据 01（设计与文档先行）：新增 [ADR-0022](../adr/0022-product-names-on-strata.md)，同步决定索引、AGENTS.md、GLOSSARY、README、调研索引；改模块边界、专名一致性（整页）、翻译子系统、批次编排、阶段计划、配置与媒体、架构总览、技术设计规格。设计定稿：中间层 `kototoki/strata.py`＋共享 `Session`（启动失败整批累计 3 次即不可用——票据 02 修正，原定"最多启动 3 次"、`<work root>/strata-sessions/`、日志前缀 `[strata]`），配方名 `q3-names-v1`；`kototoki/translate/strata.py` 保留为研究侧再导出（见 §8）。`docs-check` 无新增失败（44 条均为 main 上已有）。未改代码。
- 2026-11-09 票据 02（Strata 下沉为共享模块）：新增 `kototoki/strata.py`（`StrataServer`、`StrataRefused`、身份常量、共享 `Session`、`strata-sessions/`），`kototoki/translate/strata.py` 改为研究侧再导出，`translate/recipes.py` 从中间层取身份常量（`RECIPE_HASH` 不变），`generate.py` 删掉自己的 `Session`；`test_translate_strata.py` 改名 `test_strata.py` 并加共享 session 测试，`test_translate.py` 只改导入。修正票据 01 的设计：整批上限只计 Strata **启动失败**（累计 3 次即不可用），成功启动不限次——原定"最多启动 3 次"会改变翻译既有行为，与本票据"行为不变"冲突；ADR-0022 与模块页同步改写。`just test` 600 过、`just check` 过、`docs-check` 44 条均为已有。
- 2026-11-09 票据 03（names 改走 Strata）：`table.py` 改为 Q3 参数（`max_tokens` 8192、context 24576、5 次尝试，请求体去 `response_format`、加 `model`），配方 `q3-names-v1`（hash `d3317926…`，嵌套 `build`／`model`／`runtime`／`request`），`build_document` 接共享 `strata.Session`，`count_tokens` 预算检查与退路照 v13；names 的 llama-server 代码（`Session`、`NAMES_SPEC`、`NAMES_SERVER`、`model_asset`）提前删除（理由见 map）。测试：用产品配方四块拼回 v13 `s1_recipe("v4")`，hash 等于 ADR-0021 的 `38cb7bcd…`；伪服务测试 12 项；与 v13 `NamesClient`＋`build_one` 的请求体与 seed 序列逐字节对照 5 项。`just test` 607 过、`just check` 过、`docs-check` 44 条均为已有。04 之前 `job.py` 的 names 阶段不可运行。
- 2026-11-09 票据 04（编排共用 session）：`job._run` 建一个 `kototoki.strata.Session` 包住 names 与 translate（退出即 `--stop`，之后才放 GPU 锁），两阶段按需传入（names 有 cue、translate `needs_model`），整批只启动一次、都不需要时不启动；`kototoki.translate` 不再导出 `Session`。`test_job.py`／`test_job_ffmpeg.py` 改用伪 `kototoki.strata` 模块，新增整批一个 session、`StrataRefused` 两阶段都失败、Ctrl+C 仍 stop 的用例。`just test` 609 过、full 层 ffmpeg 3 过、`just check` 过、`docs-check` 44 条均为已有。
- 2026-11-09 票据 05（删除与配置）：删 `[paths] llama_server`、`[names] model`／`port`（`Paths`／`Models`／`NamesConfig` 同步，旧键按未知键报错），`[names] seed` 与翻译一样校验为正整数；`kototoki.toml.example`、config 与资产清单测试同步；`scripts/smoke/names_product.py` 重写为走共享 `strata.Session`（通过条件含专家区在内存、`released`、`status == ok`、≥1 person、全程无 llama-server）；`scripts/upgrade.py` 与依赖布局、技术选型、开发工作流文档改为“llama.cpp 与 27B 只供研究侧”。`just test` 609 过、full 层 ffmpeg 3 过、`just check` 过、`docs-check` 44 条均为已有；smoke 只做了导入检查，真实运行在票据 06。
- 2026-11-09 票据 06（GPU 验证）：**未执行，GPU 门未过**。开跑前核对：无 llama-server、无 Strata、无其他 GPU 作业（`Get-Process`），`.local/gpu.lock` 不存在，空闲显存 15089 MiB，`strata launch --status` 为空，`--plan` 无下载；可用内存 50.5 GiB（< 52 GiB），按 §5 每分钟采样等满 10 分钟仍 50.5–50.6 GiB（进程 working set 合计 8.4 GiB、committed 13.9 GiB、内核池 4.2 GiB；11-08 两次通过时启动前可用 54.2／54.3 GiB）。按“不关用户的程序”与“仍不够就停下”未启动 Strata，`just smoke names_product` 与 HF-II 整片都没有跑；见 §8 第 2 条。
- 2026-11-09 票据 06 重跑（用户重启后，§8 第 2 条由此解决）：开跑前可用内存 53.7 GiB、空闲显存 14977 MiB、无 llama-server／Strata／GPU 作业、无 `gpu.lock`、`--plan` 无下载。`just smoke names_product`（`.local/smoke/20261109T122829Z/`）**通过**，87.5 s：Strata 启动后 `expert_arena` 为 `ram`、drafting `dflash2`、kv `int8`；`count_tokens` 可用（`prompt_check: count_tokens`）；建表第 1 次即 `ok`（5.9 s，提示 1655／输出 299 token），2 条均为 person、置信度非 high，注入行 0（只记录）；表对身份 current；全程无 llama-server 进程；整机显存峰值 16007 MiB、内存峰值 61.1 GiB；`--stop` 后 status 为空、空闲显存 14977 MiB。 HF-II 整片（`python -m kototoki`，W0，全新 `.local/q3-product-fullfilm/`，源文件经硬链接放入新 input 目录、旁边无 `ja-zh.srt`）**通过**，墙钟 1014.8 s、退出码 0：extract 17.2 s、vad 74.7 s、asr 174.7 s、align 87.4 s（1 个窗口 CTC 目标过长的既有告警）；**names 阶段首次启动 Strata**（ready 78.1 s，`expert_arena` 为 `ram`，引擎日志 VirtualLock 3502 MiB＋45 片 pinned 43 GiB），建表第 1 次失败（seed 20261019，回复 JSON 数组末尾多逗号，7879 输出 token，55.1 s），第 2 次 `ok`（seed 20261020，48.6 s）：25 条（person 10、class 4、org 2、place 2、other 7；high 20、medium 5），归一丢弃 74（shape 64、ja_shape 10），提示 13240／输出 7766 token，建表共 103.8 s，names 阶段 182.0 s；**translate 沿用同一 session、未重启**：149 包 462.0 s，每包均值 3.10 s（p50 3.20、p90 3.70、最大 4.00 s，约 146 tok/s，输出约 178 token），149 包全部首次接受，重试、降级、回退、思考输出均为 0，144 包带注入行（20 条 high 条目展开为 44 行），`cache_n` 全为 0；整机显存峰值 16099 MiB、内存峰值 60.8 GiB；`--stop` 后 status 为空、空闲显存 15059 MiB，GPU 锁释放；`ja.srt` 与发布的 `ja-zh.srt` 各 1099 条、`ja-zh` 全为两行；`published.json` 的 names 来源 recipe_hash `d3317926…`、translate 的 `names_sha256` `e3733fce…`。 与 2026-11-08 的 Q2 整片（27B＋llama-server 建表、翻译 533 s、每包 3.07 s）相比：建表多一次失败重试、翻译速度相当、整机内存峰值相近（60.8 对 62.4 GiB）。两次 GPU 运行之间 Strata 都已完全停掉。
- 2026-11-09 票据 07（收尾）：待填标记只剩 `docs/development/workflow.md:57`（按需，时机未到，保留）；`kototoki/` 无 `NAMES_SERVER`／`NAMES_SPEC`／`model_asset`／27B 路径残留，“llama-server”只在说明文字里；计划状态改为“停在票据 06”；`docs/INDEX.md` 条目同步。

### 完成报告（2026-11-09）

提交（均在 `main`，ssh 签名）：01 `052b065`、02 `f21b1bf`、03 `f9a14cc`、04 `8410d90`、05 `e702cf4`、07 `c6f8f64`、06 重跑结果见本行所在提交。

**已实现**
- 中间层 `kototoki/strata.py`：`StrataServer`、`StrataRefused`、身份常量、共享 `Session`（第一次需要模型时启动，整批一个，启动失败累计 3 次或 `StrataRefused` 后本批不可用，退出即 `--stop` 并核实显存释放）；`kototoki/translate/strata.py` 的再导出按 §8 第 1 条的裁定删除，研究侧导入改指 `kototoki.strata`。
- `kototoki/names/`：建表在共享 Strata session 上按 Q3 规则做——配方 `q3-names-v1`（`BUILD_RECIPE_HASH` `d3317926…`），建表块、模型、运行时身份、请求形状与 `names-strata-v4` 相同，请求体与 seed 序列与 v13 逐字节一致，最多 5 次尝试取第一张合格的表；`count_tokens` 预算检查与退路照 v13；删除 names 的 llama-server session、`NAMES_SERVER`／`NAMES_SPEC`／`model_asset`。
- 编排 `job._run` 持有一个 Strata session 包住 names 与 translate，两阶段按需传入，都不需要时不启动，中断也 stop，pid 进 GPU 锁；`kototoki.translate` 不再导出 `Session`。
- 配置：删 `[paths] llama_server`、`[names] model`／`port`（旧键按未知键报错），`[names] seed` 校验为正整数；`kototoki.toml.example` 同步。
- `scripts/smoke/names_product.py` 改走 Strata；`scripts/upgrade.py` 的 llama.cpp 说明改为研究侧。
- 文档：ADR-0022 与决定索引、AGENTS.md、GLOSSARY、README、模块边界、七个模块页、技术设计规格、依赖布局、技术选型、开发工作流、调研索引。

**自动检查**（最后一次，票据 05 后）：`just test` 609 过；`tests.full.test_job_ffmpeg` 3 过；`tests.core.test_upgrade_script` 过；`just check` 过；`docs-check` 44 条均为 main 上已有；§5 列的行为各有测试（v13 逐字节对照 5 项与 hash 重构、5 次尝试与空表、共享 session 只启动一次、中断 stop、`StrataRefused` 两阶段都失败、不需要模型不启动、改表使翻译失效、禁止导入守门）。`just test-full` 的其他用例未跑（需要 ffmpeg 以外的真实资产）。

**GPU 结果**（2026-11-09，票据 06 重跑）：smoke 通过（建表 1 次即 ok、专家区在内存、停后显存释放）；HF-II 整片通过（§5 全部条件：Strata 只启动一次、`ram`、无 llama-server；建表 ok 用了 2 次尝试；翻译交付失败 0、回退 0；SRT 1099 条、`ja-zh` 全两行；停后 status 为空、空闲显存 15059 MiB ≥ 14000；峰值显存 16099 MiB、内存 60.8 GiB、建表 103.8 s、翻译每包均值 3.10 s）。数字见上面票据 06 重跑一行。

**未验证项**
- 产品写出的表未经人工抽看（25 条里 high 20、含 other 7 条）；注入后的译文质量只有研究侧 Q2／Q3 证据，未跑裁判。
- `count_tokens` 退路、5 次都失败写空表、Strata 起不来、被中断时 stop 等失败路径只经伪服务测试；x0 输出、其他作品与剧集未跑。
- 建表在同 seed 下跨 Strata 启动不保证可复现（本次第 1 次尝试失败说明输出受采样影响；v13 已观测同片两次建表差异大）。
- 整机内存峰值 60.8 GiB（共 63.9），可用内存门 52 GiB 之下仍可能退到 mmap；本次开跑前 53.7 GiB 够用，余量约 1.7 GiB。

## 8. 待用户裁定

（执行者追加。）

1. **`kototoki/translate/strata.py` 的去留**：研究侧 `experiments/translation_v3/strata.py`（`drafting_from_log`）与 `experiments/scene_batching_v6/v13.py`（`StrataServer`、`ResourceSampler`、`http_get`、模块本身）从 `kototoki.translate.strata` 导入，而 `experiments/` 不在本次改动范围。执行者把生命周期移到 `kototoki/strata.py` 后，保留 `kototoki/translate/strata.py` 作只做再导出的研究侧导入路径（产品内不使用，模块边界已写明）。是否改研究侧导入并删掉这个再导出模块，请用户裁定。**已裁定（2026-11-09）**：删掉再导出模块，`experiments/translation_v3/strata.py` 与 `scene_batching_v6/v13.py` 的导入改为 `kototoki.strata`（各一行，研究脚本行为与配方 hash 不变）；ADR-0022、模块边界、翻译子系统模块页、`scene_batching_v6/README.md` 同步，`test_strata.py` 改为断言旧路径不可导入。
2. **GPU 验证的内存门未过（票据 06 未执行）**：2026-11-09 12:04–12:14 开跑前核对，除可用内存外全部通过（无 llama-server／Strata／GPU 作业，空闲显存 15089 MiB，status 为空，`--plan` 无下载）；可用内存 50.5 GiB，低于 §5 的 52 GiB，等满 10 分钟仍为 50.5–50.6 GiB。占用来自桌面程序与内核（进程 working set 合计 8.4 GiB、committed 13.9 GiB、内核池 4.2 GiB、Hyper-V 在运行），执行者按规则不关用户的程序。2026-11-08 两次通过时启动前可用 54.2／54.3 GiB，差 1.26 GiB 即退到 mmap，故不能以 50.5 GiB 开跑。请用户决定：腾出约 2 GiB 内存后重跑票据 06（`just smoke names_product`，再 HF-II 整片，命令与通过条件见 §4／§5），或另定门。**已解决**：用户重启机器后可用内存 53.7 GiB，执行者按原门重跑票据 06，smoke 与整片均通过（§7）。
3. **票据 06 结果的提交未能签名**：2026-11-09 20:50 提交时 ssh 签名经 1Password agent 失败两次（`1Password: failed to fill whole buffer`，应是重启后 1Password 尚未解锁）。按 §6“不绕过签名、失败即停下”，票据 06 的文档改动（本文 §7／§8、ADR-0022、三个模块页、开发工作流、`docs/INDEX.md`）已写入工作区并 `git add`，未提交。请解锁 1Password 后在仓库根运行下面的命令即可（提交信息已备好）：`git commit -F "C:/Users/watch/AppData/Local/Temp/claude/48969ae9cead7bf2/ea36c9ec-4545-5d89-8462-0c7b37692b4b/scratchpad/commit06.txt"`，或自行撰写提交信息。**已解决**：用户解锁 1Password 并审批后，以提交 `017ecc6` 落盘。
