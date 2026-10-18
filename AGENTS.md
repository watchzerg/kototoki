# Kototoki

自托管 Speech-to-Text（STT）工具：Python + 本地 AI 模型，验证目标是原生 Windows（pwsh、RTX 5080），macOS 未验证。仓库以**研究／demo** 为主：W0／X0 基线与可复用 demo 已存在；第一个产品形态（双语字幕批量流水线 `kototoki/`，`python -m kototoki`）已实现，UI、流式、打包尚未开始。

## 常驻约束

本文只保留跨任务约束与触发入口；细则写入对应正文并在下表加行，不在此展开。

### 语言

- 内部推理、搜索、工具调用及临时 agent 通信用英文。面向用户及供人审阅的文字用简体中文，包括回复、文档、spec、计划、票据、PR、review 和代码注释。
- 代码标识、API、配置键、CLI 参数、schema 字段、文件名、测试名、日志与错误消息及通用技术术语保留英文。

### 设计与交付

- 采用符合项目规模的最小充分设计：校验与错误处理只覆盖实际会出现的情况；抽象、配置项、扩展点和兼容垫片等到出现第二个使用者时再加。
- 只针对当前代码、当前数据库 schema 和新数据实现。兼容旧版本、迁移历史数据或照顾进行中的旧流程属于额外需求：先说明具体需求、影响与新增复杂度，获用户批准后再纳入。
- 变更代码时按[随交付同步](docs/agents/documentation.md#随交付同步)更新受影响文档；完成报告区分实现、自动检查和未验证项。
- 每次交付前按[待填标记](docs/agents/documentation.md#待填标记)给出的命令搜索剩余标记：标记注明的时机已到，或本次任务产生了对应内容，就填写并删除标记；否则原样保留，不编造。全部标记消失后删除本条。

### 产品不变量

- **本地运行**：音频与转写留在用户机器上；外部推理服务只在用户明确要求时调用。
- **ASR 与强制对齐只跑 GPU**，不回退 CPU；VAD 可用 CPU 或 GPU（见[推理选型](docs/development/inference-selection.md)）。
- **保留原语言**：日语转写仍为日语。
- **不进 Git 与日志**：模型权重、缓存、录音、生成的转写、密钥、`.local/`；默认不打印音频内容和完整转写。

### 冻结证据与基线身份

- **冻结的历史证据只读**：结果报告、`docs/context/*`、ADR 历史，以及 Codex 时代的翻译裁判链（`experiments/translation_judge/`、`experiments/translation_flow/v2_*`、`experiments/translation_eval/`、参考 prompt）带 sha256 自检和记录在案的 `gpt-6.1-sol`／`codex-cli` 身份。需要改动时新增带版本的文件；原文件不重命名、不重排版、不"现代化"。
- 翻译代码中的 `reasoning_effort:no_think` 是 Hy-MT2 chat-template token，不是 agent 设置；`reasoning_effort` 不做批量替换。
- 翻译流程基线保持 `dp10-cut`（[ADR-0010](docs/adr/0010-dp10-cut-translation-flow-baseline.md)，2026-10-17 起；之前为 `dp6-grp`、`b10-joint`），直到用户另行决定；产品配方为 `dp10-cut-degrade-v1`（[ADR-0011](docs/adr/0011-dp10-cut-product-recipe.md)，2026-10-18 起），切包与邻文同 dp10-cut。
- **不自动选用"翻译多次再挑选"的方法**（多样本／多 seed＋MBR 或 reranking、best-of-N、多次全量翻译投票及其更省变体）：不提议、不列候选、不在无人值守时执行，除非用户明确要求；v4 `mbr8c`、v5 `mbr8s` 已放弃，边界情况先问（[ADR-0008](docs/adr/0008-no-multi-translation-selection.md)）。
- v3、v4、v5（剧集）确认集已开封，新的确认须用全新隔离的集合。第二轮（v2）已停止并冻结：其台账 1300+ 行，只按节读取，其作业不再恢复；先验只取[v1/v2 教训](docs/research/2026-10-10-hy30-flow-v1-v2-lessons.md)。

### 重任务与环境

- **重任务先问**（占 GPU、加载模型、可能跑数小时）：`just smoke`（真实模型验证，加载全部模型）、`just x0-demo`、`just translation-demo`、`just translation-baseline`、`just translation-srt`、`just translation-flow`、`just translation-eval`，产品入口 `python -m kototoki` 与 `kototoki.workers.*`，W0 的 `.local/envs/whisper-latest/Scripts/python.exe -m experiments.w0_demo.run`，以及 `experiments.*` 下任何加载模型的入口。用户只要求调查或清理时，不启动 demo 或重任务。
- `.local/gpu.lock` 标记正在运行的 GPU 作业：不抢占、不杀其他进程；用 PowerShell `Get-Process` 核实真实进程，而不是信任文档声称在跑的内容。
- `just setup`、`just install`、`just upgrade`／`uv sync|add|lock` 会改环境且可能联网：先问。
- 大目录（`.local/`、`.venv/`、`docs/research/*appendices`）会拖慢 Grep／Glob，搜索时限定子路径。

### 委派

- 有界的调研、审计、实现与验证在收益大于协调成本时主动委派子 agent；小而耦合紧的编辑留给主 agent。子 agent 可用时允许继续委派。
- 每次调用都通过 Agent 工具的 `model` 参数显式指定模型，不写进 prompt 文本代替，不依赖默认继承：默认 `sonnet`（Sonnet 5.5），只有跨模块设计、细微 debug、评审协议或统计工作等复杂任务升级到 `opus`（Opus 5.5）；所有层级均不得使用 Fable 系列模型，也不继承更贵的父模型。
- 给每个子 agent 范围、上下文、完成标准和文件所有权：写入者拿互不重叠的文件或 worktree，共享配置与 lockfile 归单一所有者；审计 agent 只读；子 agent 只在用户要求时运行 GPU 作业或 demo。
- 主 agent review 并整合全部委派产出，报告剩余不确定项。

## 按任务读取

开始动作前读取命中行的正文，只展开受影响的章节；未命中时查[文档索引](docs/INDEX.md)，不预读整套文档。

| 触发条件 | 必读入口 |
| --- | --- |
| 设计、修改、实现或 review 代码 | [架构总览](docs/architecture/INDEX.md) → 受影响的模块页（尚不存在时按[随交付同步](docs/agents/documentation.md#随交付同步)建页）；行为依据查 `docs/specs/`、`docs/plans/`，取舍查 `docs/adr/` |
| 实现、修改或 review 产品包 `kototoki/`（双语字幕流水线） | [模块边界](docs/architecture/module-boundaries.md)：依赖方向、产品包的责任边界与接缝 → 受影响模块页的"接口与依赖" → [技术设计](docs/specs/bilingual-subtitle-pipeline.md)。接口形状要变时先改模块页与模块边界，再动手 |
| review diff 的代码质量 | [CODING_STANDARDS.md](CODING_STANDARDS.md) |
| 编写、修改、移动或 review 测试，制定测试计划或整理验收证据，执行 `implement-spec` | [测试设计与验收](docs/agents/testing.md)、[验证边界](docs/testing/validation.md) |
| 运行命令、选择门禁，调整依赖、工具版本或平台／GPU 配置 | [开发工作流](docs/development/workflow.md)、[技术选型](docs/development/technology-stack.md)、[依赖布局与资产清单](docs/development/dependencies.md)、[工具链](docs/development/toolchain.md)、[Windows 与 NVIDIA](docs/development/windows-nvidia.md) |
| 新增、移动、删除文档，或讨论形成明确结论 | [文档维护规则](docs/agents/documentation.md) |
| 涉及领域术语、数据模型或与 ADR 冲突；需要 W0、X0 或翻译基线的身份定义 | [GLOSSARY.md](GLOSSARY.md)、[领域文档规则](docs/agents/domain.md) |
| 读取、创建或更新票据 | [tracker 约定](docs/agents/issue-tracker.md) |
| 分类票据或调整分诊标签 | [标签映射](docs/agents/triage-labels.md) |
| 调研、实验或复用已有结论 | [调研索引](docs/research/INDEX.md)；新产出放 `docs/research/` 并在索引登记 |
| 查最新采纳决定与探索状态 | [决定与探索时间线](docs/research/INDEX.md#决定与探索时间线) |
| 接续旧任务 | `docs/context/` 台账（冻结证据），**先对照仓库核实状态** |
| 测试、benchmark 或对比 W0／X0 | [基线测试指南](docs/guides/baseline-testing.md) → demo README → 契约 → 验证记录 |
| 运行或修改 W0（VAD、ASR、对齐）或 X0（分段、Qwen 输入、MMS） | W0：[demo](experiments/w0_demo/README.md) → [契约](docs/specs/w0-reusable-demo.md)；X0：[demo](experiments/x0_demo/README.md) → [契约](docs/specs/x0-reusable-demo.md)。复用并更新 `experiments/w0_demo/`、`experiments/x0_demo/`，`x0_flow` 与 `qwen` 只作回归参照；配方变更先出新版本并记录验证，再更新基线文档。CLI 省略参数会落到旧默认（旧 PyanNet／fixed30），须显式选择新 Pyannote（[ADR-0003](docs/adr/0003-new-pyannote-baselines.md)） |
| 选择或对比 STT 引擎、模型、对齐器 | [推理选型原则](docs/development/inference-selection.md) |
| 翻译基线 | 模型／采样：[ADR-0005](docs/adr/0005-apex-i-compact-translation-baseline.md)；完整 SRT 流程 `dp10-cut`：[ADR-0010](docs/adr/0010-dp10-cut-translation-flow-baseline.md)（joint 提示见 [ADR-0006](docs/adr/0006-b10-joint-translation-flow-baseline.md)）、`just translation-srt`；[翻译 demo](experiments/translation_demo/README.md) |
| 翻译流程探索历史（v3–v8 已结题） | v5–v8 只在[调研索引](docs/research/INDEX.md)登记（报告与 `.scratch/` 票据）；v4：[报告](docs/research/2026-10-11-hy30-flow-v4-report.md)、[台账](docs/context/2026-10-11-hy30-flow-exploration-v4.md)、[`translation_v4`](experiments/translation_v4/README.md)，唯一确认配方 `mbr8c`（约 6 倍墙钟）已放弃（ADR-0008）；v3：[报告](docs/research/2026-10-10-hy30-flow-v3-report.md)、[计划](docs/plans/hy-mt2-translation-flow-exploration-v3.md)、[`translation_v3`](experiments/translation_v3/README.md)，裁判 profile `claude-opus-5-5-mqm-v1` |
| 旧翻译评估（历史） | [评估方法](docs/testing/translation-model-evaluation.md) + [流程](docs/agents/subtitle-translation-evaluation.md)：冻结的 Codex 时代 `sol-high-auto-v1`，其分数不与 Claude 裁判分数混用 |
