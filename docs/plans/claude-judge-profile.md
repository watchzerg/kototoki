# Claude 裁判 profile `claude-opus-5-5-auto-v1`：迁移、校准与基线重锚定

状态：superseded（2026-10-10）。用户决定不续跑 v2、改为新开第三轮，裁判改为 MQM 式标注 profile `claude-opus-5-5-mqm-v1`；现行设计见[v3 计划](hy-mt2-translation-flow-exploration-v3.md)第4节。本文保留为迁移分析记录，其中对冻结代码耦合点的盘点仍然有效。
最后更新：2026-10-10。
范围：为日文→简体中文字幕翻译自动评估新建 Claude Opus 5.5 裁判 profile，替代已不可达的
`sol-high-auto-v1`；包括执行面选型、新模块边界、证据字段、对既有 Sol 结果的校准，以及
APEX-I-Compact（`official30b-cached-v1`）新锚点。不修改任何冻结证据，不接入 STT 产品。

相关文档：
[自动评估流程（agent）](../agents/subtitle-translation-evaluation.md) ·
[翻译评估入口](../testing/translation-model-evaluation.md) ·
[裁判执行面（冻结）](../../experiments/translation_judge/README.md) ·
[离线评估器（冻结）](../../experiments/translation_eval/README.md) ·
[四量化报告](../research/2026-10-07-hy30-four-quantization-results.md) 及其
[复现入口](../research/2026-10-07-hy30-four-quantization-results-appendices/reproduction.md) ·
[ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md) ·
[第二轮探索台账](../context/2026-10-08-hy30-flow-exploration-v2.md)。

所有结果只能称为“自动裁判结果”，不是经人工核验的翻译准确率。用户不阅读日文，本方案不安排人工审查。

## 1. 可比性与完整性要求

### 1.1 旧 profile 保证了什么（观察，来自代码与流程文档）

- 判断单位：每个候选／窗口一次全新调用，`codex exec --ephemeral --ignore-user-config --sandbox read-only`，
  仓库外空临时 cwd，禁用 shell／web／插件／子 agent／记忆等功能；出现工具事件即拒收。
- 固定请求身份 `gpt-6.1-sol / high`；返回身份只取 JSONL 事件，未暴露则记 `null`，不以请求值冒充。
- 冻结提示核心（`PROMPT_VERSION=group-scope-evidence-v2`）、`response_schema()`、
  `validate_judgment()`（`evidence-v2-semantic-omission`）；fingerprint 覆盖提示＋packet＋schema＋模型设置，变化即拒绝接跑。
- 每 job 最多两次尝试，第二次仅用于格式／传输失败；持续失败记 `judge_failed`，不伪造零分。
- 接受字节哈希与不可覆盖快照（`integrity.py`），恢复时复核。
- 复评：按 `sha256("sol-high-auto-v1|audit-20261006|<window>")` 每作品取 20%，并上风险窗；隐藏主评；
  分歧一次有界裁决；汇总为完整分母、作品等权、缺分 0／4 界。
- 主评与复评同模型，只是独立调用，不是不同模型家族的独立证据；参考库也由 Sol/high 复核。

### 1.2 新 profile 必须保持的

1. 同一 rubric 文本、同一 schema、同一 validator、同一 packet 构造、同一复评／裁决／汇总规则；
   唯一预期差异是裁判模型与执行面。
2. 每次判断独立的新上下文：不继承会话、项目文档、记忆、其他窗口或既有判断（裁决阶段的匿名意见除外）。
3. 请求身份与返回身份分开记录；身份不符拒收；拒绝时不自动换模型（含 Anthropic 端 refusal fallback）。
4. Claude 分数与 Sol 分数永不混算：不同 profile 的结果不进入同一均值、配对差或排名表；
   跨 profile 的对照只出现在校准报告中，并明确标注。
5. 失败、未运行、拒答都保留在完整分母中，不是候选质量零分。

### 1.3 必然改变的（观察）

- Claude Opus 5.5（`claude-opus-5-5`）不接受 temperature 等采样参数，思考不可关闭，只能用 effort 控制；
  其 effort 默认 `medium`，必须显式设置（依据本机 claude-api skill 文档，2026-10-06 缓存）。
  因此同一输入重复判断的波动无法用采样参数压低，只能测量。
- 执行面、认证、费用口径、返回字段格式全部改变；`codex` 专属的 `OVERRIDES`／`DISABLED_FEATURES`
  与 JSONL 事件解析不适用。

## 2. 既有耦合点与新增模块

### 2.1 不得原地修改的耦合点（观察）

| 文件 | 耦合 |
| --- | --- |
| `experiments/translation_judge/runner.py` | `MODEL="gpt-6.1-sol"`、`EFFORT`、codex `command()`、`event_evidence()`、fingerprint 含 codex 设置 |
| `experiments/translation_judge/subagents.py` | 导入 `MODEL/EFFORT`；`tool_provenance="collaboration.spawn_agent"`、`fork_turns="none"` 硬断言 |
| `experiments/translation_judge/scheduling.py` | `classify_access_failure()` 按 codex 传输错误分类 |
| `experiments/translation_eval/runner.py` | `PROFILE="sol-high-auto-v1"`、`AUDIT_SEED`；`order_key()` 把 PROFILE 混入复评抽样哈希；`prepare()` 写 `judge_requested: gpt-6.1-sol`；`select_review()`／`finalize()` 使用模块常量 |
| `experiments/translation_flow/judge_loop.py` | 断言 `run.json.judge_requested == Sol/high` |
| `experiments/translation_flow/v2_compare.py`、`v2_confirmation.py`、`v2_confirmation_evaluation.py`、`v2_review_evaluation.py`、`v2_review_root_runner.py`、`v2_fluency*.py` | 断言 profile 为 `sol-high-auto-v1` 或 `gpt-6.1-sol / high / codex-cli` |
| `experiments/translation_flow/v2_judge_dispatch.py` | codex 原生进程托管，导入 `event_evidence` |
| `experiments/translation_corpus/prepare.py` 与参考审核 prompt | 参考审核 job 固定 Sol 身份 |
| `tests/test_translation_*`、`experiments/*/test_*.py` 中约 20 个文件 | 以 Sol 身份为期望值 |

这些文件中许多带 sha256 自检或被冻结清单引用；修改会让历史复现失败。新 profile 只能新增文件，
通过导入复用其中的**纯函数**（`response_schema`、`validate_judgment`、`disagree`、`major_claims`、
`aggregate`、`report`、`integrity.accept_response/resume_success`、`scheduling.schedule_jobs`），
并在清单中记录被导入文件的 SHA256。

### 2.2 执行面选型

| 选项 | 隔离（对应 `fork_turns="none"`） | 模型身份 | 可复现性 | 成本／认证 | Windows |
| --- | --- | --- | --- | --- | --- |
| A. Claude Code 会话内 Agent 工具 fresh 子代理 | 无父对话轮次，但会注入项目 CLAUDE.md／AGENTS.md、环境信息及文件工具；不等价于旧隔离 | `model` 参数只接受别名（`opus`），无法固定 `claude-opus-5-5`，不返回服务端身份 | 依赖编排者手工记录；会话中断后难以接跑 | 共用当前会话额度 | 无额外进程问题 |
| B. `claude -p` 子进程（推荐默认） | 每 job 新进程、空临时 cwd、`--no-session-persistence`、不用 `--resume/--continue`、`--tools ""`、空 `--strict-mcp-config`、`--system-prompt` 替换默认提示；需探针验证无用户级记忆注入 | `--model claude-opus-5-5` 显式；`--output-format json` 结果中的 per-model usage 可能暴露返回身份（待探针确认） | 与旧 `codex exec` 结构同构，可复用调度／接跑／哈希框架 | 用现有 Claude Code 认证；`--max-budget-usd` 可设上限；`total_cost_usd` 是 CLI 估算 | 本机 `claude.exe` 2.1.295 已安装；需验证 stdin 编码与超时清理 |
| C. Claude Agent SDK | 同 B（底层是同一 CLI） | 同 B | 同 B | 需新增依赖（`uv add`，需批准） | 同 B |
| D. Messages API（`anthropic` SDK） | 天然无工具、无项目上下文；最干净 | 响应 `model` 字段、request-id、usage 均可记录 | 最好；无 harness 系统提示漂移 | 需要 API key（不是订阅 OAuth）与新依赖；按 token 计费 | 纯 HTTP |

结论：**默认 B**，因为它不改依赖、沿用现有认证、与已验证的 codex 子进程框架同构。阶段 3 探针若发现
B 无法证明隔离（例如 `--bare` 依赖 `ANTHROPIC_API_KEY` 而 OAuth 下仍注入用户记忆，或无法得到返回模型身份），
则在用户提供 API key 并批准依赖变更后切换为 D；**一个 profile 版本只允许一种执行面**，切换即新版本号。
A 只用于编排与代码实现，不用于产出评分。C 相对 B 无实质收益。

`--bare` 的帮助文本显示它要求 `ANTHROPIC_API_KEY` 或 `apiKeyHelper`（OAuth 不可用），这一点需在探针中确认。

### 2.3 最小新增模块

全部为新文件；导入时不加载模型、不访问网络。

1. `experiments/translation_judge_claude/`（执行面）
   - `profile.py`：冻结常量与 `profile_record() -> dict`；`PROFILE="claude-opus-5-5-auto-v1"`、
     `MODEL="claude-opus-5-5"`、`EFFORT`、`SURFACE="claude-code-cli"`、`AUDIT_SEED="audit-20261010"`、
     `TRANSPORT_SUFFIX_VERSION`、被导入冻结文件的期望 SHA256。
   - `transport.py`：`command(executable, cwd, schema_path) -> list[str]`；
     `execute(args, prompt, cwd, attempt, timeout) -> dict`（保存原始 stdout/stderr，移除会话类环境变量，仅记录名称）；
     `parse_cli_result(stdout: bytes) -> CliEvidence`（structured output、返回模型集合、usage、费用估算、stop/错误类型、工具事件）；
     `classify_failure(record) -> str | None`（quota／auth／model_access／refusal）。
   - `runner.py`：`run_job(root, job, executable, version, timeout, invoke=execute)` 与 `run(...)`，
     逻辑镜像冻结 `run_job`，但 fingerprint 包含新 profile 记录；复用 `integrity` 与 `scheduling.schedule_jobs`。
   - `__main__.py`：`prepare-probe`、`run`；`test_transport.py`、`test_runner.py`（fake invoke）。
2. `experiments/translation_eval_claude/`（profile 参数化评估器）
   - `prepare_from_root(source_root, output, window_ids)`：从既有冻结根逐字节复制 packet、`expected` 行，
     先按源 `run.json.packet_sha256` 校验；写入本 profile 的 `run.json`。
   - `prepare_new(...)`：调用冻结 `translation_eval.runner.prepare` 到私有 staging 目录仅作 packet 构造，
     再派生本 profile 根；staging 的 `profile` 字段标为“构造器常量，非评分身份”，并记录其 SHA256。
     这样避免复制约 200 行 packet 逻辑，packet 与 Sol 时代构造器逐字节一致。
   - `select_review(expected, primary, profile, seed)`、`finalize(output)`：显式参数化 profile／seed，
     其余组合冻结纯函数；差分测试保证在合成数据上与冻结 `finalize` 的分数和终态逐项相同（仅 profile 字段不同）。
3. `experiments/translation_judge_calibration/`（离线校准）
   - `sample.py`、`metrics.py`、`perturb.py`、`report.py`，详见第 4 节；全部离线可测。
4. `justfile` 新增 `translation-judge-claude-test`（仅离线单测）；不改既有 recipe。

## 3. Profile 定义与证据字段

### 3.1 Profile（冻结后不可原地改）

| 字段 | 值 |
| --- | --- |
| `profile` | `claude-opus-5-5-auto-v1` |
| 主评／复评／裁决 | 均为全新 `claude-opus-5-5` 调用，互不继承 |
| `effort` | `high`（与旧 `high` 对齐；见开放问题） |
| thinking | adaptive（模型强制）；不发送采样参数 |
| 输出约束 | `--json-schema` 使用冻结 `response_schema(adjudication)`，仍以 `validate_judgment` 为准 |
| refusal fallback | 关闭；拒答记失败，不由其他模型接管 |
| rubric 提示 | 与四量化冻结根逐字节同源，见 3.3 |
| 传输后缀 | 新文本 `claude-transport-suffix-v1`（“只用 packet，不用工具/文件/记忆”），单独哈希 |
| 复评规则 | 与旧流程相同：每作品 20% 基线抽样＋风险并集；哈希键 `claude-opus-5-5-auto-v1|audit-20261010|<window>` |
| 重试 | 每 job 最多 2 次，仅限传输／schema 失败 |
| 并发 | ≤4（订阅额度未知，先保守；可在探针后冻结） |

### 3.2 `run.json` 与每次尝试的证据

- `run.json`：`profile`、`profile_record_sha256`、`surface{kind, executable, cli_version, argv_template}`、
  `judge_requested{model, effort, thinking}`、`rubric_lf_sha256`、`prompt_file_sha256`、`transport_suffix_sha256`、
  `schema_sha256{primary, adjudication}`、`validator_version`、`frozen_dependency_sha256{translation_eval/runner.py, translation_judge/runner.py, integrity.py, scheduling.py}`、
  `packet_sha256`、`expected_sha256`、`audit_seed`、来源根及其 `run.json` SHA256（校准时）、`lane`、`split`、
  `mixing_policy:"never-with-other-profiles"`、`label_zh:"自动裁判结果"`。
- `judge-execution/<job>/attempt-N/`：`prompt.txt`、`schema.json`、`command.json`、原始 `stdout.json`、`stderr.txt`、
  `attempt.json`（开始／结束时间、实测秒数、退出码、`returned_models`（未暴露则 `null`＋原因）、session id、
  usage、`cost_usd_cli_estimate`（标注为 CLI 估算）、stop/refusal 类别、工具事件列表、移除的环境变量名、临时 cwd）。
- 成功接受仍用 `accepted-canonical.json` 与原始／canonical 双哈希。

### 3.3 提示哈希的处理（决定）

决定：**复用冻结 rubric 文本，不新建 rubric**。理由：校准只能证明“在这份 rubric 上 Claude 与 Sol 的一致程度”，
换 rubric 会把模型差异与提示差异混在一起；锚点和后续比较也必须使用被校准过的同一份文本。

观察：四量化 `formal-expanded-v4/judge-prompt.txt` 的 SHA256 为 `1f6312a5…`，当前 `translation_eval.runner.PROMPT + "\n"`
按 LF 编码为 `07772a7a…`；把 LF 换成 CRLF 后恰为 `1f6312a5…`。即文本相同，差异来自 Windows `write_text` 换行转换。
另外当前 `translation_eval/runner.py` 的 SHA256（`cf9c5f42…`）与该根记录的 `runner_sha256`（`1b9dc0b6…`）不同，
validator 版本字符串仍同为 `evidence-v2-semantic-omission`。

因此：新模块以字节方式（`newline=""`／`write_bytes`）写提示文件，并同时断言 LF 文本哈希 `07772a7a…`
与源根文件哈希 `1f6312a5…`；传输后缀另行版本化，不并入 rubric 哈希。冻结文件的哈希自检不受影响，因为新模块只读取和断言，
不重写它们。validator 采用当前冻结代码，`run.json` 记录其 SHA256 与源根差异；阶段 1 用源根的 `aggregation-runner.py`
副本对已接受的 Sol 记录复跑 `validate_judgment`，确认两版 validator 对同一记录的接受结果一致后才进入付费阶段。

## 4. 校准协议

### 4.1 数据来源（观察）

`.local/translation-evaluation/hy30-four-20261006/evaluation/formal-expanded-v4/`：4 候选（c01–c04 匿名）× 1,200 窗，
`expected` 4,800 行、`primary` 4,799、`review` 3,168（792 窗 × 4）、`adjudication` 824；`formal-regression-v4` 为 83 窗。
复评窗＝每作品 20% 基线抽样（无偏）＋风险窗（有偏）。这些候选输出是 `legacy-greedy-v1` 配方，可直接复用，不需 GPU。

### 4.2 样本（可复现、分层）

- 层 S1（无偏）：Sol 基线审计窗（`baseline_audit` 原因），每作品 6 窗，15 作品共 90 窗。
- 层 S2（风险）：仅因风险入选的复评窗，每作品 4 窗，共 60 窗；结果与 S1 分开报告，不合并为总体估计。
- 每窗包含全部 4 候选，以便窗口内排序比较；合计 150 窗 × 4 ＝ 600 条记录。
- 选择顺序：在层内按 `sha256("claude-calibration-20261010|<work>|<window_id>")` 升序取前 k；不足时如实记录。
  抽样只读 `review-selection.json` 的原因字段与 `expected.jsonl`，**不读分数**，避免按结果挑样本。
- 先导：S1 每作品 1 窗（15 窗 × 4 ＝ 60 条，主评＋复评 120 次调用），用于传输、费用和拒答率检查，再决定是否全量。
- Claude 对 600 条各做一次主评、一次独立复评（与旧流程不同，这里复评全覆盖，用于测 Claude 自一致性），共约 1,200 次调用。

### 4.3 合成扰动（已知方向，用户可凭中文核对）

从 S1 中 Sol 主评与复评均为语义 4 的记录取 20 条，程序生成两类扰动候选：删除一个计分 ID 的译文（漏译）、
替换译文中的阿拉伯数字或中文数字（改数）。期望：扰动后语义下降或报告对应错误。外加旧四项合成探针（等义、否定、改数、缺失）。
扰动只改候选中文，不改源文与参考；扰动脚本与期望单独保存，不进入 packet。

### 4.4 指标

全部以“作品簇 bootstrap 10,000 次、seed 20261010”给描述性区间；相邻字幕不作独立样本。

1. Sol 自身基线（阶段 1 离线计算，无模型调用）：同一记录 Sol 主评 vs Sol 盲复评。
2. 语义：精确一致率、相差 ≤1 一致率、二次加权 Cohen κ（0–4）；因多数为 4，同时报 Gwet AC1。
   对比 `κ(Claude主, Sol主)`、`κ(Claude主, Sol终)` 与 `κ(Sol主, Sol复)`。
3. 自然度：二次加权 κ（0–2），null 单列。
4. 严重错误：窗口级“是否有 major/critical”二元 κ 与 AC1；对 Sol 两次均标严重的记录计算 Claude 召回；
   Claude 独有的严重标记单列（不默认算错）。
5. 状态一致性：`scored／source_ambiguous／reference_suspect` 混淆矩阵与 null 率。
6. 排序：每窗 6 个候选对，比较语义差的符号；“翻转”＝双方均为严格且方向相反；另报平局不一致率；每窗 Kendall τ-b 平均。
7. 系统层（仅描述）：S1 内按类别作品等权的 4 候选均值与名次、APEX(c03)−Q3_K_M(c04) 差的方向；样本小，不设门槛。
8. 平均偏移：Claude − Sol 语义均值差；只报告，不作门槛，但用于说明为何不能混算。
9. 运行：有效率、重试、拒答率、实测耗时、usage 与 CLI 费用估算。

### 4.5 通过门槛（提议，执行前冻结）

没有金标准；Sol 的自身复测一致性是唯一可用的“可接受分歧”尺度，所以门槛相对 Sol 自一致性设定。
0.10／0.05 的余量是事先选定的工程容忍度，不是统计保证，通过也不证明 Claude 更准或与 Sol 同样准确。

| 门 | 条件（S1 层） |
| --- | --- |
| G1 传输 | 最终接受 ≥98%；工具事件 0；返回身份不符 0；拒答 ≤2%（超过即单独报告并停） |
| G2 语义 | `κ(Claude主,Sol主) ≥ κ(Sol主,Sol复) − 0.10`，且差值的 95% 区间下界 ≥ −0.20 |
| G3 严重 | 二元 κ 或 AC1 ≥ Sol 自身 − 0.10；对 Sol 双次共识严重错误的召回 ≥0.75 |
| G4 排序 | 翻转率 ≤ Sol 自身翻转率 ＋0.05 |
| G5 自一致 | `κ(Claude主,Claude复) ≥ κ(Sol主,Sol复) − 0.10` |
| G6 扰动 | 已知方向扰动中 ≥90% 被降分或报对应错误；旧四项合成探针方向全部正确 |

结果分三类：全部通过→建议采纳；G2–G5 有一项未过→“校准未达标”，只有用户明确接受时才可继续，并在所有后续报告标注；
G1 或 G6 未过→停止，回报选项（提高 effort 重新校准、改执行面、或新 rubric 版本，均为新 profile 版本）。

### 4.6 向不读日文的用户报告分歧

- 中文报告只放汇总：门槛红绿表、各指标与 Sol 自身基线并列、分歧类型计数（Claude 更严／更宽、严重度不同、状态不同）、扰动结果。
- 明确写出：“一致”只表示两个自动裁判相互接近；参考译文由 Sol 复核，可能偏向 Sol；分歧不能判断谁对。
- 逐窗分歧卡片放在忽略目录：候选中文、中文参考、两方 `reason_zh` 与证据 ID；日文原文附带但标注“用户无法核验”。
  扰动例子用户可以直接从中文核对（例如数字被改、整句缺失）。
- 跟踪的报告不含字幕原文摘录。

## 5. 基线重锚定协议

1. 采纳 profile 后，用当前 `just translation-baseline`（APEX-I-Compact，`official30b-cached-v1`）在四量化冻结根的
   `source-inputs` 副本上重新生成旧 83 窗与新增 1,200 窗译文，写入新目录
   `.local/translation-evaluation/claude-anchor-official30b-<date>/`。四量化中的 APEX 输出是 `legacy-greedy-v1`，不能当作当前配方锚点。
2. 生成前只读核对 `.local/gpu.lock` 与真实进程；单次 seed 20261006；采样温度 0.7 带来的生成波动另行记录，
   不在本方案内做多 seed（见开放问题）。
3. 用 `translation_eval_claude.prepare_new` 构造 `V2-native-adapted` 根；全量 Claude 主评、默认复评选择、有界裁决、完整分母汇总。
4. 锚点身份＝{候选输出哈希、配方、packet 构造器哈希、profile 记录哈希}。后续候选只在 **同一 profile 版本、同一输入、
   同一 lane、同一 packet 构造器** 下与锚点配对比较；配对统计复用冻结统计程序前须确认其不断言 profile（`translation_four_stats.py`
   初查未见 profile 断言，待阶段 2 确认）。
5. profile 任一冻结项改变（模型、effort、执行面、rubric、后缀、schema、validator）→ 新版本号，锚点必须重判，旧版本分数不跨版本比较。
6. 四量化及历次 Sol 报告只作历史背景，不与 Claude 分数同表、同差值或同排名呈现。

## 6. 分阶段步骤

所有付费调用、GPU、依赖变更均需用户在对话中逐项批准；“本方案存在”不构成授权。

| 阶段 | 内容 | 负责 | 验证 | 需批准 |
| --- | --- | --- | --- | --- |
| 0 | 用户审阅本方案，回答开放问题，冻结门槛 | 主 agent | 用户确认 | 是（决策） |
| 1 | 离线：Sol 自身基线指标、抽样清单、validator 两版一致性复核 | 实现子代理 sonnet；复核子代理 opus | 合成数据单测；抽样确定性测试；只输出聚合数字，子代理不读裁判正文 | 否 |
| 2 | 离线：三个新包与 fake transport/差分测试；新 just recipe | 实现 sonnet（按包分配独占写入）；代码审查 opus | 新单测通过；`just translation-test`、`just translation-flow-test`、`just translation-flow-v2-test` 原样通过；冻结文件 SHA 不变 | 否（改 justfile 前告知） |
| 3 | 探针：4 合成＋若干扰动，验证隔离、返回身份、schema、拒答、单次费用 | 主 agent 运行 CLI | G1 子集；`--tools ""` 下零工具事件；输入 token 与提示长度一致（检查无隐藏注入） | 是（网络、费用、数据发往 Anthropic） |
| 4 | 先导 60 条 → 全量 600 条校准 | 主 agent 调度；不派生子代理当裁判 | 中途哈希与接跑检查；先导后报告费用再请求全量 | 是（各一次） |
| 5 | 校准中文报告，用户决定是否采纳 | 主 agent；opus 子代理独立复核统计 | 程序数字与账本对账 | 是（采纳决定） |
| 6 | APEX 锚点生成（GPU） | 主 agent | 交付校验、`validate_results.py` | 是（GPU） |
| 7 | 锚点全量 Claude 评判与报告 | 主 agent | 完整分母；覆盖率；费用 | 是 |
| 8 | 文档与 ADR 更新 | 主 agent／sonnet 起草 | 链接检查 | 否 |

离线可单测部分：命令构造、CLI JSON 解析（用保存的样例）、失败分类、fingerprint、profile 记录、抽样、扰动生成、
所有指标（含已知答案的小矩阵）、差分 finalize、报告生成。真实隔离、返回身份与 Opus 判断行为只能在阶段 3 后得到证据。

## 7. 后续需要的文档变更（现在不改）

- `docs/agents/subtitle-translation-evaluation.md`：增加 profile 段落与执行者表；保留 Sol 历史说明。
- `docs/testing/translation-model-evaluation.md`：入口改指新 profile 与校准报告，声明不混算。
- 新 `docs/adr/0006-…`：采纳 Claude 裁判 profile 的决定、理由与已知代价。
- 新 `docs/research/<date>-claude-judge-calibration.md`（校准结果）与锚点结果报告。
- 新 `docs/context/<date>-claude-judge-execution.md`（接跑记录）；不改 2026-10-08 冻结台账正文。
- `docs/plans/hy-mt2-translation-flow-exploration-v2.md`：注明 Sol 阶段受阻、继续须在新 profile 下重判控制组。
- `docs/INDEX.md`：本计划与后续 ADR／报告链接。
- `CLAUDE.md` 与 `AGENTS.md`：新 profile 入口；`AGENTS.md` 中以 `gpt-6.1-sol` 为上限的子代理模型规定已与当前环境不符，需用户确认后改写。
- 新包各自的 `README.md`；`justfile` 新 recipe。冻结 README（`translation_judge`、`translation_eval`）不改。

## 8. 风险与开放问题

### 8.1 观察到的事实

- Sol 在用户 Codex 账号下返回 HTTP 400（冻结 README 与 2026-10-09 台账记录）。
- 冻结 rubric 与当前常量文本相同，仅换行字节不同；评估器源码自四量化准备后已变化。
- 参考库与历史评分均由 Sol/high 产生或复核。
- 本机 `claude` CLI 2.1.295 提供 `--model`、`--effort`、`--json-schema`、`--output-format json`、`--tools`、
  `--no-session-persistence`、`--strict-mcp-config`、`--system-prompt`、`--max-budget-usd`、`--bare`（仅读取帮助文本，未调用模型）。
- Opus 5.5 不接受采样参数、思考不可关闭、effort 默认 medium（来自 skill 文档，非本项目实测）。

### 8.2 推断与未知（需探针或实测）

- **Opus 5.5 对日文字幕语义的判断能力未知**；本方案不假设它与 Sol 相当或更好，校准也只测一致性。
- `claude -p` 在 OAuth 下是否注入用户级 CLAUDE.md／记忆、`--system-prompt` 是否完全替换 harness 提示、JSON 输出是否给出返回模型身份，均未验证。
- 无法固定采样，重复调用波动大小未知；G5 用来测量。
- 动画字幕含暴力等内容时的拒答率未知；拒答会变成缺分并扩大 0／4 界。
- 订阅额度、速率限制与费用未知；`total_cost_usd` 在订阅认证下可能不代表实际账单。
- 参考由 Sol 复核，Claude 与 Sol 一致可能部分来自“都贴近参考”，不一致也可能是参考偏差。
- 将字幕与参考发送至 Anthropic 属于外部推理；用户已批准换裁判，但阶段 3 仍需确认数据范围（只发 packet，不发音视频或整库）。

### 8.3 开放问题（阶段 0 请用户决定）

1. effort 采用 `high`（与旧名称对齐）还是 `xhigh`／`max`（更贵）？
2. 是否有 Anthropic API key 可用于选项 D？若无，只能用 B。
3. 校准规模（150 窗／约 1,200 次调用）和费用上限是否接受？是否同时校准旧 83 窗？
4. 门槛余量 0.10／0.05 是否接受？
5. 锚点复评采用默认 20%＋风险，还是全窗复评（成本约翻倍，但更稳）？
6. 锚点是否需要多 seed 生成以分离翻译采样波动？
7. 第二轮流程探索（P-flow）中已用 Sol 评过的控制组，是否按新 profile 重判后再继续？
