# 10 模块页重写到现状

Status: resolved
Type: task
Blocked by: 08, 09

范围见 [spec §4 票据 10](../spec.md#10-模块页重写到现状)。

## 执行记录

- 分三组委派给子 agent（`opus`），文件互不重叠，直接在主检出里改、不提交；主 agent 补索引、清白名单、跑门。
  每条行为规则由子 agent 对照 `kototoki/` 代码或 `tests/core/` 核对；没有改任何 `.py`。
- 状态行统一为 `状态：current；权威决定：<ADR 链接>`，不带日期；"变更与决策来源"只列链接。
  例外：`japanese-cues.md` 与 `corpus-and-assets.md` 不在本票据的重写对象里，只修了失效引用。
- 新增三篇模块页（按职责拆出）与三篇冻结记录（别处没有的带日期原文）。
- `docs/architecture/INDEX.md` 模块地图加三行；`docs/research/topics/acceptance-records.md` 登记三篇记录。
- `scripts/check_docs.py`：`BUDGET_WHITELIST` 去掉 7 篇模块页与 `workflow.md`，`KNOWN_MISSING_PATHS` 清空（6 条）。

### 字符数（Unicode 字符；括号内为最长行）

| 页面 | 整理前 | 整理后 |
| --- | --- | --- |
| `modules/translation-subsystem.md` | 21,389（2,261） | 11,858（546） |
| `modules/stt-workers.md` | 22,892（1,967） | 9,080（315） |
| `modules/batch-orchestration.md` | 20,637（1,253） | 11,993（458） |
| `modules/name-consistency.md` | 13,318（1,150） | 9,107（333） |
| `modules/config-and-media.md` | 13,301（895） | 11,232（399） |
| `modules/stage-plan.md` | 10,506（832） | 9,262（551） |
| `modules/artifact-contract.md` | 9,775（887） | 9,078（468） |
| `modules/strata-session.md`（新） | — | 7,841（348） |
| `modules/stt-asr.md`（新） | — | 10,735（321） |
| `modules/run-logging-and-processes.md`（新） | — | 8,245（491） |
| `docs/development/workflow.md` | 8,046（1,313） | 7,723（568） |

### 拆分与归属

- `strata-session.md`：`kototoki/strata.py`（`Session`、`StrataServer`）与 `kototoki/local_client.py`；翻译子系统页只留翻译侧的 session 规则。
- `stt-asr.md`：`kototoki/asr_whisper.py`、`kototoki/asr_qwen.py`、`kototoki/judge.py`、`kototoki/guard.py`、`kototoki/workers/asr.py`；
  `stt-workers.md` 留 worker 壳共用规则、VAD 与对齐。
- `run-logging-and-processes.md`：`kototoki/logs.py`、`kototoki/procs.py` 与 worker 子进程的启动、崩溃判定；批次编排页的"运行日志"标题保留并指向它。
- `kototoki/embedded.py` 归 `config-and-media.md`。
- 被其他文件链接的锚点都保留（`#当前行为规格`、`#代码与验证入口`、`#运行日志`）；`#cross-引擎` 改指 `stt-asr.md`。

### 带日期内容的去向

- 别处没有的原文存入三篇冻结记录（`docs/research/acceptance/2026-11-11-module-page-history-*.md`）：
  Q2 首次 smoke 与整片记录（含 mmap 诊断）；冻结窗口首跑、cross 显存与共驻表、x0 在 transformers 5.19 下的全等记录；
  批次编排原状态行、真实运行核对、重采样削波实测、门禁耗时与用例数。
- 别处已有的只删、留链接：来源是 `docs/research/acceptance/` 的 2026-10-14／15／19／20 各篇、
  `docs/plans/product-names-on-strata.md` §7、`docs/plans/asr-repeat-guard.md` §7、`docs/plans/architecture-cleanup.md`、
  ADR-0012／0022／0023 与 `.scratch/` 下各票据。

### 失效路径

`docs/changes/local-dependencies-and-test-layers.md`（5 处）、`docs/changes/name-consistency-product.md`（1 处）、
`kototoki/llama_server.py`（1 处）都已从模块页去掉或改指现存位置。

### 规则与代码对不上的地方

页面一律按代码写或改成中立说法，没有改代码；需要用户知道的记 spec §8 第 7 项。

1. 产物契约：旧文写"判定为已有字幕而跳过时删除 `failure.json`"；`kototoki/job.py` 扫描到已有字幕时直接跳过，不删。
2. 产物契约：旧文的 `names_apply` 遗留键与 `sources` 比较已不存在（发布只看源文件旁字幕是否存在），删。
3. STT worker：旧文同页自相矛盾（x0 `device_map` 固定 `cuda:0` 与"已改用 `.to`"）；按 `kototoki/asr_qwen.py` 写成加载后 `.to("cuda:0")`。
4. STT ASR：`kototoki/judge.py::judge_window` 的 `normalize_failed` 分支旧页没写，已补。
5. 配置与媒体：旧文 CROSS `recipe_hash` 前缀 `ab9f4532…` 与 `tests/core/test_recipes.py` 钉住的值不同；改为"由该测试钉住"。
6. 配置与媒体：旧文"配方字典共七个"与同页"八个字典"矛盾，`kototoki/recipes.py` 是 8 个；去掉计数。
7. 配置与媒体：容器映射的旧写法有歧义，按 `media.CONTAINERS` 逐项写。
8. 运行日志：旧文说只有翻译重启与放弃两行把异常首行截到 200 字符；代码在批次尝试失败行、`Strata refused` 行、names 尝试行也截。页面只写"不做通用截断"。
9. 开发工作流：smoke 清单漏了 `whisper_score`（`scripts/smoke/run_all.py` 的 `SMOKES` 有 9 项），改为不穷举并指向 `SMOKES`。
10. 开发工作流：`translate_product`"未运行、待用户批准"已过时（`docs/plans/architecture-cleanup.md` §7 记了已运行），删。
11. 开发工作流：`test_job_ffmpeg`"检查三份 SRT 发布"与现状（只发布 `ja-zh.srt`）不符，改为"检查发布结果"。
12. 翻译子系统：`plan` 的 `ValueError` 消息在代码里是英文，页面不再引用中文原文；"Strata ready／停止"日志来自 `kototoki.strata` logger，不是 `kototoki.translate`。

## Answer

7 篇模块页全部进预算并从白名单清零，另拆出 3 篇新模块页；失效路径名单清空。
门：`just docs-check` 通过（496 篇）；`just gate-core` 通过（716 个测试）。
未验证：子 agent 的"规则对照代码"是阅读核对，没有为每条规则新增测试；主 agent 只抽查，没有逐条复核。
