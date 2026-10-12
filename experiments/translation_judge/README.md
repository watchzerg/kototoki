# 字幕翻译裁判 CLI

这是 `sol-high-auto-v1` 的裁判传输层，与 [离线评估器](../translation_eval/) 配合使用。
每个候选／窗口启动一个全新的 `codex exec`，固定 `gpt-6.1-sol / high`；主评、复评与裁决共用此入口，
不会继承其他窗口、Codex app 对话或前一次尝试。参考和裁判输出只送入裁判，不回送翻译模型。
先读 [自动评估流程](../../docs/agents/subtitle-translation-evaluation.md)。

## 运行

实际调用使用现有 Codex 身份认证及网络，按本仓库沙箱规则必须通过 `require_escalated` 执行。
脚本不读取、复制或导出认证密钥，不新增账号。既有 CLI 的身份认证能力不代表所需模型一定可用；
不支持固定模型时记录失败，不自动替换模型。

```powershell
# 仅生成合成探针，离线执行。
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_judge prepare-probe --output '.local/translation-evaluation/20261006-v1/judge-probe'

# 网络／身份认证调用，需在获准的执行环境中执行。
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_judge run --output '.local/translation-evaluation/20261006-v1/judge-probe' --jobs '.local/translation-evaluation/20261006-v1/judge-probe/jobs.jsonl' --workers 4 --timeout 300

# 正式运行使用离线评估器输出目录及其 jobs 文件；参考、dev 与正式裁判合计最多六个并行 CLI。
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_judge run --output '<评估目录>' --jobs '<评估目录>/jobs.jsonl' --workers 6
# 完成主评后先 select-review，再运行 jobs-review.jsonl；finalize 后运行 jobs-adjudication.jsonl，最后再次 finalize。

# 离线检查，不启动 Codex、不访问身份认证。
& '.venv/Scripts/python.exe' -X utf8 -m unittest experiments.translation_judge.test_runner experiments.translation_judge.test_subagents
```

## 隔离与恢复

CLI 参数包括 `--ephemeral --ignore-user-config --sandbox read-only --json --output-schema --output-last-message`。
工作目录为仓库之外的全新临时空目录，关闭项目文档、shell、web search、插件、Apps、子 agent、记忆及其他可用工具功能；
仅向 stdin 提供冻结提示、当前 packet，以及裁决阶段允许的匿名既有判断。捕获到工具事件会拒绝该结果。
`CODEX_HOME` 保持既有认证位置；其他 `CODEX_*` 会话环境变量不向裁判继承，记录被移除的变量名而非值。
官方配置说明见 [OpenAI Docs](https://learn.chatgpt.com/docs/config-file/config-reference)。

每个 job 最多两次总尝试，第二次只用于格式／传输失败。重跑命令恢复已验证成功结果，失败任务也不超过原有重试预算。
提示、packet、schema 或模型设置变化会拒绝接跑，需新建运行目录；不会把旧尝试当新实验。
原始 stdout、stderr、最终消息、提示、schema、命令、实际耗时与 CLI 版本保存在 `judge-execution/<job-id>/attempt-*`。
通过共享 `validate_judgment` 检查后才写入评估器期望的 response；持续失败保留 `judge_failed`，不伪造零分。
目录级 OS 锁防止两个调度器同时消耗同一任务的重试次数；进程退出后锁自动释放。
四量化运行的私有参考／dev／正式裁判编排器另共享运行根目录的 `.judge-global-six.lock` 原生字节锁，
整条流水线持锁，并使用 Windows Job Object 等待自己启动的进程及后代排空后才释放。
单独的 `translation_judge run` 不自动取得这把跨流水线锁；直接调用仍须由协调者维护全局六进程上限。

成功响应在首次验证时记录原始文件与 canonical 响应的 SHA256，并保留不可覆盖的
`accepted-canonical.json` 字节快照。接跑先复核原始字节、canonical 字节及重新验证后的内容；
canonical 文件缺失时只允许从已校验的接受快照精确恢复。内容或哈希改变、证据缺失、部分哈希字段缺失时
拒绝接跑，不覆盖已有文件，也不重新分发已成功任务。
Windows路径包含关系检查先统一等价的普通／扩展DOS盘符与UNC表示，再解析真实路径；
同一文件的`\\?\`长路径前缀不应被误判越界。设备命名空间及真正的父目录／兄弟目录越界仍拒绝，
原始账本路径和响应字节不改写。原生Windows长路径已验证；真实UNC网络文件系统行为尚未验证。

旧成功账本可能没有首次接受时的哈希。默认拒绝这种接跑；确需迁移时，可显式执行以下离线命令，
仅在当前原始／canonical 两份文件均存在且内容一致时创建一次不可覆盖的当前文件基线：

```powershell
& '.venv/Scripts/python.exe' -B -X utf8 -m experiments.translation_judge.integrity --ledger '<job目录>/job.json'
```

该基线明确保存 `original_acceptance_hashes_available:false` 和实际观察时间，
不能补造历史首次接受哈希或证明旧原始字节未曾改变。已有哈希字段的记录不能降格为旧版基线。
四量化 dev 续跑采用新目录只读引用既有主评，执行剩余复评／裁决，不重跑旧成功主评传输。

CLI 裁判与参考审核使用有界调度：最多提交六个任务，不预先提交全量队列。
本次调用内三个不同任务连续出现同类明确 `quota`、`auth` 或 `model_access` 传输失败后，
停止提交新任务；已提交任务及其原有最多两次尝试正常排空。判定只读取传输错误事件／stderr，
不把字幕、assistant 正文、一般超时或 schema 失败当成账户阻碍；旧恢复结果不计入触发阈值。
未提交任务在本次汇总中记为 `not_run`，不消耗尝试次数，CLI 返回非零，后续依赖阶段停止。
完整预期分母仍保留，不能将未运行任务伪造成翻译零分。

记录请求模型和 effort；CLI 返回身份只取实际事件，未提供时明确保持未知，不能把命令设置说成服务器返回身份。
保存原始 usage 事件；CLI 未提供实际计费金额，成本保持未知。总尝试时间包含失败／重试，另列本次调度墙钟时间。
临时 cwd 会清理，原始运行证据保留在忽略目录。

## 已测边界

2026-10-06，原生 Windows 上 Codex CLI `0.147.0` 的四项合成探针（等价措辞、否定反转、改数字、缺失文本）
各执行两次，均收到服务端 HTTP 400：`The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account.`
该次旧版 CLI 检查未产生有效评分，也未切换模型。用户随后升级 CLI；2026-10-06 四量化比较的独立探针已确认 `codex-cli 0.160.1` 可使用相同隔离执行器调用指定的 `gpt-6.1-sol / high`，详情见下方新执行面记录。旧失败不代表当前可用性。
日志保存在上述 `judge-probe/judge-execution/`。合成探针是接口检查，不能证明裁判准确率。
离线 fake transport 测试覆盖恢复、重试上限、冻结设置、返回身份拒绝和原生进程锁；不证明实际模型可访问。

## Fresh subagent 传输

上述失败仅适用于当时的 CLI 版本与账户路径。下列 fresh subagent 执行面保留为独立已验证路径；当前四量化运行采用下节复验通过的 CLI。已授权的 `collaboration.spawn_agent` 可以用
显式 `model=gpt-6.1-sol`、`reasoning_effort=high`、`fork_turns=none` 为每个 packet 创建全新裁判。
以下 helper 只导出任务／验证响应，不调用网络、读取认证或自行启动 agent：

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_judge.subagents export --output '<评估目录>' --jobs '<评估目录>/jobs.jsonl'
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_judge.subagents import --output '<评估目录>' --tasks '<评估目录>/subagent-execution/jobs-tasks-1.jsonl'
```

协调者逐项读取导出的 `task.txt`，以全新 worker 分发；worker 仅允许读取这一份任务及写入自己的 `raw-response.json`。
任务中内嵌当前 packet、冻结 rubric/schema；复评不包含主评，裁决才附带允许的匿名判断。
协调者在对应 `invocation.json` 保存实际 `agent_id`、请求模型／effort、`fork_turns`、`tool_provenance`、
开始／结束时间、测量的 `elapsed_seconds` 及其测量范围。返回接口不暴露模型版本时保留 `returned_model:null`、
`returned_effort:null`；明确请求配置与返回 worker 身份的区别。不要将导出时间到产物落盘的时延说成纯模型推理时间。

每个任务只分发一次。发现已有 invocation 时通过其 worker 身份接跑，不再次启动。
首次导出 manifest 保留为不可覆盖的证据；重复导出会跳过终态／已分发任务，因此协调者还须逐项检查 invocation/validation 状态。
格式／传输失败经 import 记账后，可 `export --attempt 2`；第二次仍失败即结束。已成功或耗尽尝试的任务不会再次导出。
也可按同一 job schema 分为互不重叠的协调 shard；避免同一个 job 出现在两个 shard 中。
验证成功后写入原评估器约定的 `primary`／`review`／`adjudication` response 路径。

2026-10-06 的四项合成探针使用四个 fresh Sol/high worker，均通过 schema 与证据校验：
等价措辞语义 4、否定反转 2、人数改变 2、完全缺失 0／自然度 null。
原始任务、响应和调用身份保存于 `.local/translation-evaluation/20261006-v1/judge-subagent-probe/`；
这些是实际语义流程检查，不是裁判准确率验证。该探针仅测主评接口；随后 smoke/dev 已另行覆盖盲复评、裁决和程序汇总，正式结果见下节。

## 四量化比较的 CLI 复验与参考审核

运行根目录为 `.local/translation-evaluation/hy30-four-20261006/`。`judge-probe/` 保存四项 fresh subagent、四项 CLI 合成检查、六任务 CLI 并发检查与真实六窗口参考审核的原始响应及调用身份。六并发合成任务全部通过；真实参考初审六项也全部通过且无重试。真实六窗口调度墙钟约 55.92 秒，不能用单句合成探针推算全量完成时间。模型／effort 的请求配置已保存，CLI 未返回的服务端身份仍为未知，费用也不推算。

新增参考审核传输复用同一 CLI 的隔离命令及原始事件采集；每窗口每轮使用全新临时目录、独立进程和原始 packet。第二轮不包含初审意见。参考审阅与候选质量评分采用不同 schema，不混用评分结果。

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_reference_judge --output '<独立扩集目录>' --jobs '<独立扩集目录>/review-jobs.jsonl' --phase primary --workers 6 --timeout 300
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_reference_judge --output '<独立扩集目录>' --jobs '<独立扩集目录>/review-jobs.jsonl' --phase review --workers 6 --timeout 300
```

以上调用使用既有认证及网络，仍须 escalation。成功任务恢复时校验原始及 canonical 响应哈希；每任务最多两次格式／传输尝试，不因语义分歧重试。参考对齐、排除／候补和最终冻结由 `experiments.translation_corpus` 管理。四量化整体比较仍在执行，不能由探针通过宣称全量评估完成；状态见[接跑记录](../../docs/context/2026-10-06-hy30-four-execution.md)。

## 五候选历史正式运行结果

2026-10-06 的 smoke/dev、配置冻结和完整固定 test 已完成，见[中文报告](../../docs/research/2026-10-06-translation-model-comparison-results.md)。
五候选各 83 窗口／414 IDs；415 个候选窗口中 408 有语义终分，6 映射不可评、1 裁决未决。
全部必需裁判任务已终结；原始响应追溯例外、失败成本和新目录复现方式见报告及其证据链接。
