# Kototoki

Self-hosted Speech-to-Text (STT) tool: Python + local AI models, native Windows, RTX 5080.
The repo is in the **research/demo phase**, not product development: W0/X0 baselines and
reusable demos exist; backend migration, UI, streaming, packaging are still open.

## 常驻约束

- 采用符合项目规模的最小充分设计：校验与错误处理只覆盖实际会出现的情况；抽象、配置项、扩展点和兼容垫片等到出现第二个使用者时再加。
- 只针对当前代码、当前数据库 schema 和新数据实现。兼容旧版本、迁移历史数据或照顾进行中的旧流程属于额外需求：先说明具体需求、影响与新增复杂度，获用户批准后再纳入。
- 变更代码时按[随交付同步](docs/agents/documentation.md#随交付同步)更新受影响文档；完成报告区分实现、自动检查和未验证项。
- 每次交付前按[待填标记](docs/agents/documentation.md#待填标记)给出的命令搜索剩余标记：标记注明的时机已到，或本次任务产生了对应内容，就填写并删除标记；否则原样保留，不编造。全部标记消失后删除本条。
- 本文只保留跨任务约束与触发入口；细则写入对应正文并在下表加行，不在此展开。
- 内部推理、搜索、工具调用及临时 agent 通信用英文；面向用户及供人审阅的文字用简体中文，包括文档、spec、计划、票据、PR、review 和代码注释。
- 代码标识、API、配置键、CLI 参数、schema 字段、文件名、测试名、日志与错误消息及通用技术术语保留英文。项目或外部规范明确指定语言时，遵循其约定（本项目的约定见下一条）。
- Reply to the user in Simplified Chinese, keeping established English technical terms.
  Code, identifiers, commands, and agent-facing docs are English; human-facing plans,
  guides and reports are Chinese.
- Inspect current code and the baseline testing guide before changing any baseline component.
- **Local only.** Audio and transcripts stay on the user's machine. Do not call external
  inference services unless explicitly asked.
- **GPU-only ASR and forced alignment**, no CPU fallback. VAD may use CPU or GPU
  (see [inference selection](docs/development/inference-selection.md)).
- **Preserve the spoken language** in transcription (Japanese stays Japanese).
- **Keep out of Git and logs:** model weights, caches, recordings, generated transcripts,
  secrets, `.local/`. Do not print audio contents or full transcripts by default.
- **Frozen historical evidence is read-only.** Result reports, `docs/context/*`, ADR history,
  and the Codex-era translation-judge chain (`experiments/translation_judge/`,
  `experiments/translation_flow/v2_*`, `experiments/translation_eval/`, reference prompts)
  contain sha256 self-checks and recorded `gpt-6.1-sol` / `codex-cli` identities. Never
  rename, reformat, or "modernize" them. Add new versioned files instead.
- `reasoning_effort:no_think` in translation code is a Hy-MT2 chat-template token, not an
  agent setting. Never bulk-replace `reasoning_effort`.
- Legacy CLI defaults (old PyanNet / fixed30) are **not** the adopted baselines. Select new
  Pyannote explicitly. See [ADR-0003](docs/adr/0003-new-pyannote-baselines.md).
- **Heavy, ask first** (GPU, model load, can run for hours): `just x0-demo`,
  `just translation-demo`, `just translation-baseline`, `just translation-srt`, `just translation-flow`,
  `just translation-eval`, W0 via `.local/envs/whisper-latest/Scripts/python.exe -m
  experiments.w0_demo.run`, anything under `experiments.*` that loads a model.
- `.local/gpu.lock` marks a running GPU job. Do not preempt or kill other processes; verify
  real processes (PowerShell `Get-Process`) rather than trusting what a doc says is running.
- `just setup` / `uv sync/add/lock` change the environment (may go online): ask first.
- Do not start demos or heavy jobs while the user asked only for investigation or cleanup.
- Native Windows is the validation target; report macOS as unverified.
- Type hints on public interfaces.
- Translation baseline stays `b10-joint` until the user decides (v4 confirmed `mbr8c`, not adopted).
  The v3 and v4 confirmation sets are opened; any new confirmation needs a fresh, isolated set.
  Round 2 (v2) is stopped and frozen; its ledger is 1300+ lines of history, so do not load it
  whole and never resume its jobs. Use only the
  [v1/v2 lessons](docs/research/2026-10-10-hy30-flow-v1-v2-lessons.md) as priors.
- Large dirs (`.local/`, `.venv/`, `tests/bridge-cohort-test-*`, `docs/research/*appendices`)
  make Grep/Glob slow. Search specific subpaths.
- Delegation: use subagents proactively for bounded research, audits, implementation and
  validation when the benefit outweighs coordination cost; small tightly coupled edits stay
  with the main agent. **Always set `model` explicitly: default `sonnet` (Sonnet 5.5); upgrade
  to `opus` (Opus 5.5) only for complex tasks** (cross-module design, subtle debugging,
  judging-protocol or statistics work). Do not inherit a more expensive parent model.
- 子 agent 可用时允许继续委派。每次调用子 agent 都通过 Agent 工具的 `model` 参数显式指定，不写进 prompt 文本代替，不依赖默认继承；所有层级的子 agent 均不得使用 Fable 系列模型。
- Give each subagent scope, context, completion criteria, and file ownership. Writers get
  disjoint files or worktrees; shared config and lockfiles go through one owner. Audit
  agents are read-only. Subagents must not run GPU jobs or demos unless the user asked.
- The main agent reviews and integrates all delegated changes and reports remaining
  uncertainty.

## 按任务读取

开始动作前读取命中行的正文，只展开受影响的章节；未命中时查[文档索引](docs/INDEX.md)，不预读整套文档。

| 触发条件 | 必读入口 |
| --- | --- |
| 设计、修改或 review 代码 | [架构总览](docs/architecture/INDEX.md)，再进受影响的模块页；模块页尚不存在时按[文档维护规则](docs/agents/documentation.md#随交付同步)建页 |
| 编写、修改、移动或 review 测试，制定测试计划，执行 `implement-spec` | [测试设计与验收](docs/agents/testing.md) |
| 运行命令、选择门禁、调整依赖或工具链 | [开发工作流](docs/development/workflow.md)、[技术选型](docs/development/technology-stack.md) |
| 新增、移动、删除文档，或讨论形成明确结论 | [文档维护规则](docs/agents/documentation.md) |
| 涉及领域术语、数据模型或与 ADR 冲突；需要 W0、X0 或翻译基线的身份定义 | [GLOSSARY.md](GLOSSARY.md)、[领域文档规则](docs/agents/domain.md) |
| 读取、创建或更新票据 | [tracker 约定](docs/agents/issue-tracker.md) |
| 分类票据或调整分诊标签 | [标签映射](docs/agents/triage-labels.md) |
| 调研、实验或复用已有结论 | [调研索引](docs/research/INDEX.md)；新产出放 `docs/research/` 并在索引登记 |
| review diff 的代码质量 | [CODING_STANDARDS.md](CODING_STANDARDS.md) |
| Test / benchmark / compare W0 or X0 | [baseline testing guide](docs/guides/baseline-testing.md), then the demo README, contract, validation record |
| Run or change X0 (segmentation, Qwen input, MMS) | [X0 demo](experiments/x0_demo/README.md) → [contract](docs/specs/x0-reusable-demo.md). Reuse `experiments/x0_demo/`; `x0_flow` and `qwen` are regression references only |
| Run or change W0 (VAD, ASR, alignment) | [W0 demo](experiments/w0_demo/README.md) → [contract](docs/specs/w0-reusable-demo.md). Reuse and update `experiments/w0_demo/`; version changed recipes and record validation before updating baseline docs |
| Translation baseline | model/sampling: [ADR-0005](docs/adr/0005-apex-i-compact-translation-baseline.md); full-SRT flow `b10-joint`: [ADR-0006](docs/adr/0006-b10-joint-translation-flow-baseline.md), `just translation-srt`; [translation demo](experiments/translation_demo/README.md) |
| Translation flow exploration (v4, completed) | [v4 report](docs/research/2026-10-11-hy30-flow-v4-report.md), [v4 ledger](docs/context/2026-10-11-hy30-flow-exploration-v4.md), [`experiments/translation_v4`](experiments/translation_v4/README.md); 1 confirmed recipe `mbr8c` (~6x wall clock), not adopted |
| Translation flow exploration (v3, completed) | [v3 report](docs/research/2026-10-10-hy30-flow-v3-report.md), [v3 plan](docs/plans/hy-mt2-translation-flow-exploration-v3.md), [`experiments/translation_v3`](experiments/translation_v3/README.md); judge profile `claude-opus-5-5-mqm-v1` |
| Old translation evaluations (history) | [evaluation method](docs/testing/translation-model-evaluation.md) + [workflow](docs/agents/subtitle-translation-evaluation.md): frozen Codex-era `sol-high-auto-v1`; never mix those scores with Claude-judged ones |
| Choose or compare STT engines, models, aligners | [inference selection principles](docs/development/inference-selection.md) |
| Dependencies, tool versions, tasks | [toolchain](docs/development/toolchain.md); platform/GPU: [Windows and NVIDIA](docs/development/windows-nvidia.md) |
| Test planning / acceptance evidence | [validation boundaries](docs/testing/validation.md) |
| Implementing behavior | relevant `docs/specs/`, `docs/plans/`; architecture in `docs/architecture/`, `docs/adr/` |
| Resuming work | `docs/context/` handoffs; **verify status against the repo first** |
| Latest adopted decisions and exploration status | [决定与探索时间线](docs/research/INDEX.md#决定与探索时间线) |
