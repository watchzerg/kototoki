# Kototoki

自托管 Speech-to-Text（STT）工具：Python + 本地 AI 模型，**只面向 Ubuntu**（x86_64、NVIDIA RTX 5080），不支持 Windows 与 macOS。仓库以**研究／demo** 为主；第一个产品形态是双语字幕批量流水线 `kototoki/`（`python -m kototoki`），UI、流式、打包尚未开始。

## 常驻约束

本文只保留跨任务约束与触发入口；细则写入对应正文并在下表加行，不在此展开。

### 语言

- 内部推理、搜索、工具调用及临时 agent 通信用英文。面向用户及供人审阅的文字用简体中文，包括回复、文档、spec、计划、票据、PR、review 和代码注释。
- 代码标识、API、配置键、CLI 参数、schema 字段、文件名、测试名、日志与错误消息及通用技术术语保留英文。

### 设计与交付

- 采用符合项目规模的最小充分设计：校验与错误处理只覆盖实际会出现的情况；抽象、配置项、扩展点和兼容垫片等到出现第二个使用者时再加。
- 只针对当前代码、当前数据库 schema 和新数据实现。兼容旧版本、迁移历史数据或照顾进行中的旧流程属于额外需求：先说明具体需求、影响与新增复杂度，获用户批准后再纳入。
- 变更代码时按[随交付同步](docs/agents/documentation.md#随交付同步)更新受影响文档；完成报告区分实现、自动检查和未验证项。

### 平台

- 本项目只面向 Ubuntu：代码、脚本、文档与工具选型按 Linux 原生做法设计，不写 Windows／macOS 分支，也不为它们补兼容或测试。2026-11 从原生 Windows 迁来，迁移完成前仓库里残留的 Windows 写法（pwsh、`%LOCALAPPDATA%`、`.exe`、ctypes `WinDLL` 等）属待清理项，不作为现行约定。

### 产品不变量

- **本地运行**：音频与转写留在用户机器上；外部推理服务只在用户明确要求时调用。
- **ASR 与强制对齐只跑 GPU**，不回退 CPU；VAD 可用 CPU 或 GPU（见[推理选型](docs/development/inference-selection.md)）。
- **保留原语言**：日语转写仍为日语。
- **不进 Git 与日志**：模型权重、缓存、录音、生成的转写、密钥、`.local/`；默认不打印音频内容和完整转写。

### 现行决定与研究约束

- 现行决定的完整定义在 [CURRENT.md](docs/adr/CURRENT.md)，沿革在[决定索引](docs/adr/INDEX.md)。翻译只有**一条基线 Q3**，直到用户另行决定：新测试以 Q3 为对照，引用 Q2、Q1、Q0、F1、H0 时写明。
- 翻译代码中的 `reasoning_effort:no_think` 是 Hy-MT2 chat-template token，不是 agent 设置；`reasoning_effort` 不做批量替换。
- **不自动选用"翻译多次再挑选"的方法**（多样本／多 seed＋MBR 或 reranking、best-of-N、多次全量翻译投票及其更省变体）：不提议、不列候选、不在无人值守时执行，除非用户明确要求；边界情况先问（[ADR-0008](docs/adr/0008-no-multi-translation-selection.md)）。
- 已结题的研究线不重开，重开只由用户明确要求；确认集与已停止轮次的约束见[研究索引·研究方法约束](research/INDEX.md#研究方法约束)。
- 研究一轮一目录放 `research/`，记录精简、冻结靠 git 与归档 tag，不靠字节锁（[ADR-0031](docs/adr/0031-research-layout-and-lightweight-records.md)）。

### 重任务与环境

- **重任务先问**（占 GPU、加载模型、可能跑数小时）：`just smoke`（真实模型验证，加载全部模型）、产品入口 `python -m kototoki`、`just subtitles` 与 `kototoki.workers.*`，以及 `research/` 下任何加载模型的入口。用户只要求调查或清理时，不启动 demo 或重任务。用户批准的计划里写明的重任务视为已授权，一口气跑完再汇报；超出计划的重任务或破坏性操作再问。Windows 上长任务与 worktree 的坑见[开发工作流](docs/development/workflow.md#windows-上的长任务与-worktree)。
- `.local/gpu.lock` 标记正在运行的 GPU 作业：不抢占、不杀其他进程；用 `ps -p <pid>`／`pgrep` 核实真实进程，而不是信任文档声称在跑的内容。
- `just install`、`just upgrade`／`uv sync|add|lock` 会改环境且可能联网：先问。
- 大目录（`.local/`、`.venv/`）会拖慢 Grep／Glob，搜索时限定子路径。

### 委派

- 有界的调研、审计、实现与验证在收益大于协调成本时主动委派子 agent；小而耦合紧的编辑留给主 agent。子 agent 可用时允许继续委派。
- 每次调用都通过 Agent 工具的 `model` 参数显式指定模型，不写进 prompt 文本代替，不依赖默认继承：默认 `sonnet`（Sonnet 5.5），只有跨模块设计、细微 debug、评审协议或统计工作等复杂任务升级到 `opus`（Opus 5.5）；所有层级均不得使用 Fable 系列模型，也不继承更贵的父模型。
- 给每个子 agent 范围、上下文、完成标准和文件所有权：写入者拿互不重叠的文件或 worktree，共享配置与 lockfile 归单一所有者；审计 agent 只读；子 agent 只在用户要求时运行 GPU 作业或 demo。
- 主 agent review 并整合全部委派产出，报告剩余不确定项。

## 按任务读取

开始动作前读取命中行的正文，只展开受影响的章节；未命中时查[文档索引](docs/INDEX.md)，不预读整套文档。

| 触发条件 | 必读入口 |
| --- | --- |
| 设计、修改、实现或 review 代码 | [架构总览](docs/architecture/INDEX.md) → 受影响的模块页。产品包 `kototoki/` 另读[模块边界](docs/architecture/module-boundaries.md)，接口形状要变时先改模块页与模块边界再动手；跨模块契约查[技术设计](docs/specs/bilingual-subtitle-pipeline.md)；review 质量按 [CODING_STANDARDS.md](CODING_STANDARDS.md) |
| 编写、修改、移动或 review 测试，测试计划、验收证据，执行 `implement-spec` | [测试设计与验收](docs/agents/testing.md) |
| 运行命令、选择门禁，调整依赖、工具版本或平台／GPU 配置 | [开发工作流](docs/development/workflow.md)，再按需读 `docs/development/` 的对应页 |
| 新增、移动、删除文档，或讨论形成明确结论 | [文档维护规则](docs/agents/documentation.md) |
| 涉及领域术语、数据模型或与 ADR 冲突 | [GLOSSARY.md](GLOSSARY.md)、[领域文档规则](docs/agents/domain.md) |
| 读取、创建、更新或分类票据 | [tracker 约定](docs/agents/issue-tracker.md)、[标签映射](docs/agents/triage-labels.md) |
| 查现行决定与基线身份（翻译 Q3、产品翻译与建表、W0／X0）；用户采纳或变更决定 | [CURRENT.md](docs/adr/CURRENT.md)；[记录新决定](docs/adr/INDEX.md#记录新决定) |
| 新的翻译对比、裁判与统计口径 | [翻译评估方法](docs/agents/translation-evaluation.md)（旧 Codex 流程只作历史） |
| 调研、实验、复用已有结论，查研究轮次或验收记录 | [研究索引](research/INDEX.md)；新轮次按 `research/TEMPLATE.md` 建目录并登记 |
| 跑产品批量、写跑次记录、据跑次开票 | [批量运行与跑次记录](docs/agents/production-runs.md)；记录在 [runs/](runs/INDEX.md) |
| 选择或对比 STT 引擎、模型、对齐器 | [推理选型原则](docs/development/inference-selection.md) |
| 接续旧任务 | 进行中的 `.scratch/<slug>/spec.md` 与票据，**先对照仓库核实状态**；已结题的工作看 ADR、模块页或 git 历史 |
