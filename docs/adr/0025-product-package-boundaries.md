# ADR-0025：产品包的边界与失败级别（GPU 锁冲突进程级、产品不为研究侧留代码、核心测试不导入研究代码）

状态：已接受（2026-11-11，用户裁定，依据计划 [`docs/plans/architecture-cleanup.md`](../plans/architecture-cleanup.md)；实现结果记在计划 §7）。替代 [ADR-0022](0022-product-names-on-strata.md) 第 6 点中 `kototoki/llama_server.py`"留在原文件、不挪不删"（计划 §2、§3 称之为"第 4 点"，实际出处是 ADR-0022 决定第 6 点"删除与保留"的第二条；第 4 点只说 `strata.py` 与 `llama_server.py` 同层），以及 ADR-0022 第 1 点末句"等价由 `tests/core/` 导入 v13 做逐字节对照守门"。ADR-0022 其余各点不变。  
范围：产品包 `kototoki/` 的模块边界、失败级别与产品测试的分层；研究侧只改导入行。不改任何配方、身份字段与产物内容（`MEDIA` 除外，见"不属本 ADR"），不改 W0／X0、Q3 基线与产品翻译、建表的行为，不加功能。

## 决定

1. **GPU 锁冲突一律是进程级。** 任何阶段（vad、asr、align、names、translate）需要 `.local/gpu.lock` 而它被存活的持有者占着（或残留锁未获准破除）时，编排抛 `GpuLocked`，整批以退出码 4 结束：不写逐文件 `failure.json`，不把冲突记成某个文件的阶段失败；已完成的 CPU 产物（`probe.json`、`audio-16k.wav`、`ja-embedded.json`、`ja-cues.json` 等）保留，下次运行按身份续跑。零条目文件（无语音、或 `ja.srt` 为空）不需要 GPU，但同一批里撞锁时它们也等到下一次运行再发布。此前 names 与 translate 把冲突捕获成逐文件失败（整批退出码 1、每个文件的 `failure.json` 记 `GpuLocked`），与 GPU 阶段的规则不一致。
2. **产品不为研究侧导入方保留代码。** 产品不用的代码搬到使用它的研究包里：
   - `kototoki/llama_server.py` 中产品不用的 `ServerSpec`、`ManagedServer`、驻留函数（`residency_evidence`、`validate_residency`、`loader_logs`）、`server_command`、`port_free`、`check_model`、`check_engine` 与 `LlamaClient.tokenize`／`.complete` 及其测试搬到 `experiments/translation_v3/llama_server.py`（研究侧需要 `tokenize`／`complete` 时在那边用子类或函数补上）；
   - 剩下的 `LlamaClient`、`InfraFailure`、`explicit_oom` 改名为 `kototoki/local_client.py`（类名不变），不留再导出；
   - `nvidia_smi`、`wait_for_free_vram` 搬进唯一的产品使用者 `kototoki/strata.py`；
   - `list_llama_servers` 只有 smoke 脚本用，搬到 `scripts/smoke/`。
   此后产品包里没有 `llama_server` 模块；产品只起 Strata（ADR-0022 不变）。
3. **产品符号移动或改名时，同一提交里改研究侧的导入行。** 只做机械的导入路径与名字替换，不改研究代码的行为。基线 Q3 的实现 `experiments/translation_v3/strata.py` 与 `experiments/scene_batching_v6/v13.py` 改完后其离线测试必须仍通过；某项改动若需要改研究代码的行为才能让它们继续工作，停下交用户裁定。
4. **`tests/core` 不再导入 `experiments.*`。** 核心测试里与研究实现的等价断言改成钉字面量或 sha256，值取自当前对照实现，注释写明来源与取值日期。与研究实现的实时对照搬到新目录 `tests/equivalence/`（复读守卫 ↔ `asr_robustness_v15` 的 `repeat`、裁判 ↔ `quality_v5`、建表 ↔ `scene_batching_v6.v13`、翻译配方 ↔ `translation_v3`／`scene_batching_v6`），由新 recipe `just test-equivalence` 运行，并入 `gate-full`，不并入 `gate-core`。`tests/core` 另有一条全仓库导入边界测试（AST 扫描）：`kototoki/` 的任何模块不得导入 `experiments` 与 `kototoki_eval`，`tests/core` 自身不得导入 `experiments`。

## 依据

- 2026-11-11 对产品包做了分段 review（编排与产物契约、STT／媒体／cue、翻译／专名／Strata、仓库级依赖）：分层健康、四条硬规则都成立，问题集中在"同一条规则两处实现"、"身份 hash 漏了输入"与"产品为研究侧保留代码、核心测试反过来导入研究代码"三类（计划 §1、§2）。用户同日裁定全部按 review 建议办。
- 决定 1：GPU 锁冲突与文件内容无关，逐文件 `failure.json` 让人误以为是那些文件出了问题，退出码 1 也与 GPU 阶段撞锁的退出码 4 不一致；批次编排页曾两种说法都写了，且没有测试覆盖"首个需要 GPU 的阶段是 names"的情形。
- 决定 2：`kototoki/llama_server.py` 约 368 行中约 215 行产品不用，唯一使用者是 `experiments/translation_v3/qwen.py` 的延迟导入；`tests/core/test_llama_server.py` 约一半在测这些代码。留着它们让产品的模块边界、核心测试与"产品只起 Strata"的事实不符。
- 决定 3：5 个研究包的 27 个文件导入产品符号（含私有名），其中两份是基线 Q3 的实现；这些包不在冻结清单里、源码没有 sha256 自检，机械改导入行不破坏任何冻结证据，不改则产品无法移动符号。
- 决定 4：核心测试导入研究代码使 `just test` 依赖研究包可导入，产品门禁被研究侧的改动牵连；钉值保留了等价的证据，实时对照仍可单独运行。

## 影响

- 用户可见：撞 GPU 锁时整批退出码 4、控制台一行说明，不再出现一批 `GpuLocked` 的 `failure.json`；其他行为不变。
- 代码：新增 `kototoki/procs.py`（进程原语，基础层）、`kototoki/local_client.py`、`experiments/translation_v3/llama_server.py`、`tests/equivalence/`；删除 `kototoki/llama_server.py`。模块边界与各模块页已先行写入目标接口（AGENTS.md"接口形状要变时先改模块页与模块边界"）。
- 研究侧：导入 `kototoki.llama_server` 的文件改指 `kototoki.local_client` 或 `experiments/translation_v3/llama_server.py`；导入被移动的产品符号（如 `kototoki.job` 的进程原语）的文件改指新位置。研究脚本的行为与配方 hash 不变。
- 门禁：`gate-full` 多一步 `test-equivalence`；`gate-core` 的组成不变（`lint`、`typecheck` 未接入的现状不在本 ADR 处理）。

## 不做

- 不统一 `experiments/` 与 `scripts/smoke/` 里的 `.local/gpu.lock` 写入方（约 10 个、4 种 payload，全部 `O_EXCL`，互斥有效）。
- 不把产品里的副本（`validate_transcript`、`normalize`、SRT、MMS、`chunk_intervals`）与研究代码合并或互相导入；不裁剪 `strata.__all__`（研究侧在用）。
- 不建阶段注册表、不建推理后端协议；不拆 `media.py`，不再拆 `job.py` 的阶段函数。
- 不改 `names` 的 `BUILD` 与翻译的 `RECIPE` 内容（保持与 `names-strata-v4`、Q2 请求逐字节一致）。

## 不属本 ADR

计划 §3 决定 2——`recipes.LAYOUT_BY_CHANNELS` 与音轨选择规则（规则说明＋`LANGUAGE_ALIASES`）并进 `MEDIA`，`MEDIA["id"]` 不变、`MEDIA` hash 变一次，现有 `probe.json` 全部失效、各重抽一次音频，PCM 逐字节不变、vad 及下游仍当前——是配方内容变更，不是决策取舍，记在[配置、配方与媒体提取](../architecture/modules/config-and-media.md)模块页与计划 §7。

## 未验证

- 实现前写成：各项的离线测试与 `just smoke` 的结果记在计划 §7。
- 研究侧导入行改过的包，其离线测试能否在各自解释器里跑起来，以计划 §7 的记录为准；跑不起来的不为通过而改研究代码的行为。
