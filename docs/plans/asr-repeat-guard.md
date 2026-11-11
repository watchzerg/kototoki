# ASR 整窗复读守卫进产品（ADR-0023 的实现）

状态：**done**（2026-11-11 起草、同日完成；§5 三项 GPU 验收通过，smoke 九项全部通过，其中 `x0_frozen_window` 在用户裁定把已接受的窗口 0 差异写进脚本判定后通过，见 §7 与 §8 第 4 项；用户 2026-11-10 裁定 v15 的 A 进产品，决定已记为 [ADR-0023](../adr/0023-asr-repeat-guard.md)，本文是它的实现计划）。  
目标：产品 `kototoki/` 的 w0 路径在 `asr` 阶段解码之后加一步后处理——规则 `repeat-strict` 命中的窗口折叠相邻重复，折叠后仍命中则置空。不改解码、VAD、对齐，不改 x0 路径，不改 W0 基线身份。  
执行载体：tracker `.scratch/asr-repeat-guard/`（spec、map、票据，Git 忽略）。本文是唯一进 Git 的计划与完成记录：完成后在 §7 填结果，状态改为 done。  
先读：[ADR-0023](../adr/0023-asr-repeat-guard.md)；[v15 研究文档](../research/2026-11-10-asr-robustness-v15.md) §7 的 01、02 两行与 §8 第 8 项；[模块边界](../architecture/module-boundaries.md)；模块页 [STT worker](../architecture/modules/stt-workers.md)、[产物契约](../architecture/modules/artifact-contract.md)、[阶段计划](../architecture/modules/stage-plan.md)；[技术设计](../specs/bilingual-subtitle-pipeline.md)；[测试设计与验收](../agents/testing.md)、[验证边界](../testing/validation.md)；[CODING_STANDARDS](../../CODING_STANDARDS.md)；代码 `kototoki/workers/{asr,protocol}.py`、`kototoki/recipes.py`、`kototoki/judge.py`（`normalize`）、`experiments/asr_robustness_v15/{repeat,actions}.py`。

## 1. 为什么

- Whisper 偶尔在一个窗口里把同一短语复读几十遍。已知实例：HF III 第 51 窗，参考 11 字，输出 94 字。字幕里出现一大段复读是产品缺陷。
- v15 用"安全网"判据（对正常语音零误报＋拦住已知复读窗）在 101 个 w0 样本／5618 窗上选出唯一合格的规则 `repeat-strict`，动作比较里折叠最好（HF III 净 −42 编辑，官方 CER 13.7673% → 13.3973%；HF II 零命中）。
- 收益是堵住偶发缺陷，不是降平均 CER；代价是产品 W0 配方换 id，旧 `asr.json` 全部重算。

## 2. 已知事实（不要重复调查）

- 研究侧实现在 `experiments/asr_robustness_v15/repeat.py`：`signals`、`flagged`、`collapse`，规范化用 `kototoki_eval.schema.normalize`。产品里等价的规范化是 `kototoki.judge.normalize`（同样返回 `text` 与 `raw_spans`）。
- `repeat-strict` 的参数：`min_period` 2、`min_copies` 10、`min_count` 10、`min_length` 3、`min_coverage` 0.5。
- `collapse` 只折叠相邻重复（tandem）：在原文上保留第一个单元，删掉其后各次重复所占的原文区间（含夹在其中的标点）。非相邻复现（recurring）单独命中时折叠不改文字，因此落到"仍命中 → 置空"。
- `kototoki/workers/asr.py`：w0／x0 走 `compute()`，`asr.transcribe()` 返回 `segments, traces, failures`，`transcript_document()` 对 `failures` 里的窗口调 `protocol.fail_window`（文字移入 `failed_windows[].text`、段文字置空）。cross 走 `compute_cross()`，先写 `asr-w0.json`，再逐窗裁判，`index in failed_w` 的窗口不以 x0 替代。
- `recipes.W0` 的 hash 被 `CROSS` 嵌套；`tests/core/test_recipes.py::test_pinned_asr_recipe_hashes` 钉着 W0、CROSS 的 hash。
- 验收对照：HF III 对照工作目录 `.local/asr-robustness-v14/01/hf-iii/fb2e0da74018/`，HF II `.local/q3-product-fullfilm/work/input-7c924c80249b/8d2f3e76dd0c/`；v15 票据 02 的折叠结果在 `.local/asr-robustness-v15/02/`（HF III 折叠后第 51 窗 31 字，官方 CER 13.3973%，S 769／D 448／I 304）。

## 3. 已定决定（执行者不再询问）

1. **纯函数模块 `kototoki/guard.py`**（基础层，不依赖 worker、torch）：
   - `RULE`：上面五个参数加规则名 `repeat-strict`；
   - `check(text) -> bool`：是否命中；
   - `apply(text) -> (new_text, record | None)`：未命中返回原文与 None；命中则折叠，记录 `{rule, action, period, copies, removed_raw_chars}`，`action` 为 `collapse`，折叠后仍命中（含 recurring 单独命中）时 `action` 为 `blank`、`new_text` 不用。
   - 逻辑从 `repeat.py` 移植，规范化用 `kototoki.judge.normalize`；产品不导入 `experiments.*`、`kototoki_eval`。
2. **接入位置**：`workers/asr.py` 里一个小函数，对未失败的窗口逐个 `guard.apply`：
   - `collapse`：改写该段 `text`，在 `asr_traces[i]` 写 `guard` 记录；
   - `blank`：把 `(index, "guard:repeat-strict")` 追加进 `failures`（走现有 `fail_window`），trace 同样记 `guard`。
   - w0 引擎：在 `compute()` 的 `transcribe` 之后、`transcript_document` 之前调用。
   - cross 引擎：在 `compute_cross()` 里对 w0 那一路调用，位置在写 `asr-w0.json` 之前，后面的裁判用守卫后的 w0 文字；置空的窗口沿用 `w0_failed_window: stays failed`。
   - x0 引擎与 cross 的 x0 那一路不加守卫。
   - 日志只记窗口号、动作与计数，不记文字；`fields` 加 `guarded_windows`。
3. **配方**：`recipes.W0` 加 `"guard": {"rule": "repeat-strict", "min_period": 2, "min_copies": 10, "min_count": 10, "min_length": 3, "min_coverage": 0.5, "action": "collapse tandem run to its first unit; blank via failed_windows if still flagged", "normalize": "kototoki.judge.normalize"}`，`id` 改为 `w0-faster-whisper-large-v3-guard-v2`；`"baseline"` 字段不变。`guard.RULE` 与配方块取同一份常量，测试钉住两者相等。重钉 W0、CROSS 的 hash。
4. **不做迁移**：既有工作目录的 `asr.json` 身份失效、整批重算。
5. **等价守门**：`tests/core/` 里一项测试导入 `experiments.asr_robustness_v15.repeat`，在一组构造文本上核对 `guard.check`／`guard.apply` 与研究侧 `flagged`／`collapse`（`repeat-strict` 参数）结果相同（先例：`tests/core/test_names_session.py` 导入 v13）。
6. **文档**：实现完成的同一提交里，ADR-0023 状态行补实现日期与 W0、CROSS 的新 hash；[决定索引](../adr/INDEX.md)对应行去掉"尚未实现"、关闭未关闭项；更新[技术设计](../specs/bilingual-subtitle-pipeline.md)的 ASR 小节、[STT worker 模块页](../architecture/modules/stt-workers.md)与[产物契约](../architecture/modules/artifact-contract.md)（`asr_traces[].guard`、失败原因 `guard:repeat-strict`）。

## 4. 票据（建议拆法，执行者可在 map 里调整，须写明理由）

| 票据 | 内容 | 资源 |
| --- | --- | --- |
| 01 | `kototoki/guard.py` 与单元测试：周期 2 的 22 份复读被折叠成一份；9 份不命中、10 份命中；覆盖 <50% 不命中；单字连写按周期 2 计；标点夹在重复之间时原文区间删对；recurring 单独命中 → `blank`；与研究侧等价的守门测试 | 离线 |
| 02 | 配方块与新 id、重钉 hash；`workers/asr.py` 接入 w0 与 cross；worker 测试（伪 ASR：折叠改文字并写 trace、置空进 `failed_windows`、x0 不受影响、cross 用守卫后的 w0 文字、日志无文字）；`tests/core/test_plan.py` 等受身份变化影响的测试 | 离线 |
| 03 | 文档同步（§3 第 6 项） | 离线 |
| 04 | GPU 验收（§5） | GPU |

## 5. 验收、授权与停止条件

- **离线门禁**：`just check`、`just test`、`just test-full` 全绿（门禁入口以[开发工作流](../development/workflow.md)为准；仓库目前没有选定 linter 与类型检查器）。`just docs-check` 在 main 上本就因冻结文档外链失败，只看本次改动是否新增失败项。
- **GPU 验收**（用户在启动执行 session 时授权；开跑前用 `Get-Process` 核实没有 llama-server、Strata 或其他 GPU 作业，读 `.local/gpu.lock`，不抢占、不杀进程）：
  1. HF III 用产品 `asr`＋`align` 重算：第 51 窗被折叠（trace 有 `guard`，`action: collapse`，文字 31 字），官方 CER 13.3973%（S 769／D 448／I 304）逐项复现；
  2. HF II 全量：守卫零命中，官方 CER 与对照逐项相同；
  3. `just smoke` 一次。
  输入音频、VAD 产物可复用对照工作目录里的 `vad.json` 与 WAV；CER 用 v14／v15 已有的评估入口（`experiments/asr_robustness_v15/actions.py` 的口径），不新写评估。
- **停止条件**：HF III 的 CER 与 13.3973% 不逐项一致、或 HF II 出现命中——停下，把差异（计数，不贴文字）写进 §8，不调阈值、不改规则。
- 转写文字不进 Git 与日志。

## 6. 不做的事

- 不改规则参数、不加别的信号（压缩比、`avg_logprob`）、不重解码、不温度回退。
- 不处理低压缩比的插入套话（守卫范围之外）。
- 不给 x0 路径加守卫；不改研究侧 `experiments/w0_demo/` 与 W0 基线文档（基线身份不变）。
- 不做旧产物迁移或兼容垫片；不加配置键（守卫必开，参数在配方里）。
- v15 的 B（空子段补窗）与 C3（按专名表替换日文人名）不进产品（用户 2026-11-11 裁定），本计划不涉及。

## 7. 进度与结果

| 票据 | 日期 | 结果 |
| --- | --- | --- |
| 01 | 2026-11-11 | `kototoki/guard.py`（`RULE`、`check`、`apply`）与 `tests/core/test_guard.py`；与研究侧 `repeat.py` 在 317 个构造文本上命中与折叠结果相同。配方块、新 id `w0-faster-whisper-large-v3-guard-v2` 与重钉 hash 提前到本票（`guard.RULE` 取自 `recipes.W0["guard"]`）：W0 `b73198fac0a1b8eb1ccc24d7d33479e3a42059989e4ef2a6820367efcb603e76`，CROSS `d29b138b492290b3c1fbf788c029472c97ecc1fb58aa7cdc4bb415c1cbec717f`。`just test` 623 项通过 |
| 02 | 2026-11-11 | `workers/asr.py` 的 `apply_guard` 接入 w0 引擎与 cross 的 w0 那一路（x0 不过守卫）；trace 记 `guard`，置空原因 `guard:repeat-strict`，进度行加 `guarded_windows`。`just check`、`just test`（627 项）、`just test-full`（14 项）通过 |
| 03 | 2026-11-11 | 技术设计 §1.1／§4／§6、STT worker 模块页（新增"w0 复读守卫"一节）、产物契约（`asr_traces[].guard`、失败原因 `guard:repeat-strict`）、阶段计划页、架构总览分层图同步；`just docs-check` 无新增条目。ADR-0023 状态行与决定索引随 04 的验收结果一起改 |
| 04 | 2026-11-11 | GPU 验收，数字见下；ADR-0023 状态行、决定索引、调研索引时间线同步；顺带修两个冻结窗口 smoke 脚本的过期调用（§8 第 3 项） |

**GPU 验收（票据 04）**。开跑前 `Get-Process` 无 llama-server／Strata／python 进程，无 `.local/gpu.lock`，整卡已用约 0.8–1.0 GB；全程未启动 Strata 与 llama-server、未下载权重。驱动脚本 `.scratch/asr-repeat-guard/acceptance.py`（Git 忽略）：把对照工作目录的 `audio-16k.wav`（硬链接）与 `vad.json`（原字节）放进 `.local/asr-repeat-guard/04/<film>/<id>/`，用产品 `python -m kototoki.workers.asr`（engine `w0`）与 `kototoki.workers.align` 重算，官方 CER 用 `experiments.asr_robustness_v14.common.official_cer`（与 v15 `actions.py` 同一口径）；报告 `.local/asr-repeat-guard/04/report.json` 只含计数。

| 项 | 预期 | 实测 | 结论 |
| --- | --- | --- | --- |
| 1. HF III（207 窗） | 第 51 窗折叠、31 字；CER 13.3973%（S 769／D 448／I 304） | 只有第 51 窗有 `guard`（`collapse`，周期 2、22 份、删 63 字，94 → 31 字）；CER 13.3973%（S 769／D 448／I 304，候选 11209 字）；其余 206 窗文字与对照全等；失败窗口 0 | 通过 |
| 2. HF II（195 窗） | 守卫零命中；CER 与对照逐项相同 | 0 窗有 `guard`；CER 16.8073%（S 876／D 676／I 260），与对照逐项相同；195 窗文字与对照全等；失败窗口 0 | 通过 |
| 3. `just smoke` | 一次 | 只跑 STT 六项：`forced_align`、`vad_pyannote`、`ct2_after_torch`、`whisper_score`、`stt_frozen_window` 通过（w0 冻结窗口 8 窗文字与 token 全等、549 unit、1048 个边界最大差 0、守卫 0 命中）；`x0_frozen_window` 首次未通过（窗口 0 文字与对照不同，其余 7 窗全等，即 2026-10-14 已接受的环境差异；x0 不过守卫），用户裁定把该差异写进脚本判定后重跑通过（`accepted_difference: true`，136.1 s）；`llama_stock`、`translate_product`、`names_product` 起初因授权限制未跑，用户同日授权后补跑，三项通过（64.3 s／88.2 s／79.9 s；结束后 `strata launch --status` 为空、整卡已用 593 MiB、无 llama-server 进程） | 通过（九项全部通过，分四次运行；过程见 §8 第 2–4 项） |

asr 阶段墙钟 321.7 s（两部，整卡峰值 5339 MiB），align 121.3 s（7598 MiB）。align 的两条窗口级对齐失败告警（HF II 窗 182、HF III 窗 188）与对照相同。smoke 结果目录 `.local/smoke/20261110T165926Z/`（四项）、`.local/smoke/20261110T170128Z/`（两项冻结窗口）、`.local/smoke/20261111T015321Z/`（补跑的三项）与 `.local/smoke/20261111T061827Z/`（`x0_frozen_window` 重跑）。

**完成报告**

- 已实现：`kototoki/guard.py`（`RULE`、`check`、`apply`）；`kototoki/workers/asr.py` 的 `apply_guard`（w0 引擎与 cross 的 w0 那一路）；`recipes.W0` 的 `guard` 块与新 id，W0 hash `b73198fa…3e76`、CROSS hash `d29b138b…717f`；文档：ADR-0023 状态行、决定索引、技术设计、STT worker 模块页、产物契约、阶段计划页、模块边界、架构总览分层图、文档索引与调研索引。
- 已自动检查：`just check`、`just test`（627 项）、`just test-full`（14 项）全绿；`just docs-check` 仍只有 main 上原有的冻结外链条目，本次改动的文件无新增。
- 已用真实模型验证：上表第 1、2 项与 smoke 九项。九项不是一次不带参数的 `just smoke` 跑完的，而是分四次按名称运行。
- 未验证：cross 引擎的真实模型运行（守卫在 cross 的接入只有伪适配器测试；CROSS hash 已变，旧 cross 产物会重算）；`blank`（置空）路径的真实样本（两部电影里没有折叠后仍命中的窗口，只有构造文本测试）；编排入口 `python -m kototoki` 的端到端运行（本次只跑 asr／align 两个 worker）；剧集与其他作品上的守卫表现（同 ADR-0023"未验证"）。

## 8. 待用户裁定

1. **研究期 v14 测试钉着产品 W0 的旧 hash。** `experiments/asr_robustness_v14/test_offline.py::Identity::test_w0_recipe_hash_is_pinned` 断言 `plan.recipe_hash("asr", engine="w0")` 等于旧值 `127397b5…f7ba`，W0 配方换 id 后这一项失败（v14 其余 49 项与 v15 的 32 项通过）。它只在 `just experiments-test` 里，不属于任何门禁；本次按"不改 experiments/ 下既有脚本"没有动它。待裁定：保持失败（冻结证据）、还是允许把该断言改成新 hash 或删除。另：v15 的 `inventory.W0_RECIPE_HASH` 在导入时取产品当前 hash，所以重跑 v15 扫描时旧工作目录的 `asr.json` 不再被认作 `recipe_is_w0`——只影响重跑研究脚本，不影响已写出的报告。
2. **`just smoke` 没有整套跑。** 不带参数的 `just smoke` 包含 `llama_stock`（起 llama-server）、`translate_product`、`names_product`（起 Strata），与本次授权里的"不启动 Strata、不起 llama-server"冲突，所以只跑了 STT 六项（这三项与本次改动无关：守卫只在 asr 阶段）。另外第一次尝试在第一项结束后中断——我把输出接到管道，runner 在 cp1252 控制台编码下打印进度条字符抛 `UnicodeEncodeError`，与产品无关；设 `PYTHONUTF8=1` 后重跑。**已裁定（2026-11-11）：用户授权补跑，三项通过，见 §7。**
3. **两个冻结窗口 smoke 脚本原本跑不起来，已做一行修复。** `scripts/smoke/stt_frozen_window.py`、`x0_frozen_window.py` 还在用 ADR-0020 之前的 `artifacts.work_root(out)`（现在要两个参数），启动即 `TypeError`；改为 `artifacts.cache_dir(out)` 后 w0 冻结窗口门禁通过。这超出计划范围，为完成 smoke 验收而改。**已裁定（2026-11-11）：接受。**
4. **`x0_frozen_window` 未通过。** 窗口 0 文字与对照不同（其余 7 窗文字与 token 全等，587 unit 范围全等、时间在容差内，守卫 0 命中）。这与 STT worker 模块页记录的 2026-10-14 已接受差异（BF16 近平局在不同 torch 版本间翻转）是同一窗口；脚本本身仍把它判为不通过。逐项核对：窗口 0 的 38 个 token 中只有第 2 个不同、61 字中 1 字被替换、字数不变，与 2026-10-14 的记录一致。本次未改 x0 路径。另：本次环境的 transformers 是 5.20.1（模块页记录的是 5.19.0）。**已裁定（2026-11-11）：写进判定。** `scripts/smoke/x0_frozen_window.py` 新增 `accepted_difference`：只放行"唯一不等的窗口是窗口 0，token 等长且只有下标 1 不同，文字等长且恰好 1 字不同"，其它差异仍不通过；重跑通过。
5. **cross 可能选中 x0 自己的复读。** 按 §3 的决定 x0 那一路不过守卫；写测试时确认：x0 窗口若自己复读且裁判分数偏向它，复读会进合并结果。这是计划内的已知范围，不是缺陷；**已裁定（2026-11-11）：不需要，合并结果不再过守卫。**

## 附：执行提示词（粘贴到新 session）

```text
按 docs/plans/asr-repeat-guard.md 实现 ASR 整窗复读守卫（ADR-0023）。先读该文"先读"一行列出的文件；§2 的事实不要重复调查，§3 的决定不再询问。
做法：在 .scratch/asr-repeat-guard/ 建 tracker（spec、map、票据），按 §4 的票据顺序做；每张票据完成后写 Answer、更新 map 与计划 §7，并提交 Git（提交信息用简体中文）。接口形状先改模块页再动手（AGENTS.md"按任务读取"）。
授权：票据 04 的 GPU 验收——产品 asr／align worker 在 HF II、HF III 上重算，以及一次 just smoke。开跑前用 Get-Process 核实没有 llama-server、Strata 或其他 GPU 作业，读 .local/gpu.lock，不抢占、不杀进程、不关我的程序。不启动 Strata、不起 llama-server、不下载任何模型权重；不运行 just setup／install／upgrade 与 uv sync／add／lock。
规则：中途不问我，需要裁定的事写进计划 §8；触发 §5 的停止条件就停下并写明差异（只写计数，不贴转写文字）。不改规则参数、不改解码与 VAD、不动 x0 路径、不改 experiments/ 下既有脚本与 W0 基线文档；产品代码不导入 experiments.*。转写文字不进 Git 与日志。子 agent 用 Agent 工具显式指定 model（默认 sonnet，复杂设计或细微 debug 升级 opus，不用 Fable）。
完成标准：just check、just test、just test-full 全绿；§5 的三项 GPU 验收通过并把数字写进 §7；ADR-0023 状态行补实现日期与 W0、CROSS 的新 hash，决定索引去掉"尚未实现"并关闭对应未关闭项；技术设计、STT worker 模块页、产物契约已同步；计划状态改为 done，完成报告区分已实现、已自动检查与未验证项。
```
