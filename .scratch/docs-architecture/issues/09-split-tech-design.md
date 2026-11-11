# 09 拆技术设计

Status: resolved
Type: task
Blocked by: 08

范围见 [spec §4 票据 09](../spec.md#09-拆技术设计)。

## 执行记录

- 委派给子 agent（`opus`），在独立 worktree（提交 a9c1da6 的 detached 检出）里改，不提交；主 agent 逐文件复制回主仓库、补索引并跑门。
  第一次用 Agent 工具的 worktree 隔离时，worktree 建在旧提交上，子 agent 按指示停下、没有改动；改为主 agent 自建 worktree 后重派。
- `docs/specs/bilingual-subtitle-pipeline.md` 51,461 → 12,336 字符（510 → 约 170 行，最长行 820 → 475）。保留 §1、§1.1 配方与 §2–§6 的跨模块契约。
  为了不让旧锚点和代码注释里的"§10"断开，保留了 §2.1、§2.2、§3.2、§5.2、§7.1–7.4、§10、§11 的标题桩，各一行指向新位置。
- 新增 `docs/architecture/modules/config-reference.md`（5,416 字符）：原 §10 配置参考，逐键对照 `kototoki/config.py` 重写。
- 新增冻结记录 `docs/research/2026-11-11-bilingual-pipeline-spec-history.md`（29,576 字符）：移出的原文，只改相对链接。
  收录范围比 spec 写的（§9、§12、§13 与状态行）宽：还原文收了 §1.2、§2–§6 移出的节选、§7.2–§7.4、§8、§11。
  原因：这些是带日期的实测与当时的"最新版本"表，其中重采样频谱对比与 §7.4 上游核实表在别处没有；搬进 `docs/development/` 活页会把过时版本写成现状。
- `docs/development/technology-stack.md` 新增"选版规则"一节，接收 §7.2 中仍成立的事实；`dependencies.md` 与
  `docs/architecture/stt-candidate-pipelines.md` 各改一个链接目标。改前都搜过代码，没有校验。
- 索引：`docs/architecture/INDEX.md` 模块地图、`docs/specs/INDEX.md`、`docs/research/topics/vad-alignment-and-cues.md` 各加一行。
- `check_docs.py`：技术设计从预算白名单与失效路径名单里去掉（现在按 15,000 字符的上限检查）。

### 被删的每一节 → 去向

| 原节 | 去向 |
| --- | --- |
| 状态行修订历史 | 历史记录"原状态行" |
| §1.2 已裁定表 | 历史记录；技术设计留一行指向 `CURRENT.md`、决定索引与 ADR |
| §2 阶段表的"做什么"与单片成本列 | 细则与 `config-and-media`、`stt-workers`、`name-consistency`、`translation-subsystem` 重复，删；原表进历史记录 |
| §2 内嵌字幕清洗细则、§2.1 容器映射表、§2.2 时长校验／下混／丢样补偿 | 与 `config-and-media`（及 `batch-orchestration`）重复，删 |
| §2.2 重采样器一条（swr／soxr 频谱数据） | 历史记录（别处没有） |
| §3.1、§3.3 的显存轮询、阈值、身份核对步骤 | 与 `batch-orchestration`、`translation-subsystem`、`name-consistency`、模块边界重复，删；跨模块规则留下 |
| §3.2 对比表 | 理由在 ADR-0007；原表进历史记录 |
| §3.4 时间线 | 历史记录（原图还画着已删除的替换步骤） |
| §4 目录树注释与规则细节 | 与 `artifact-contract`、`stage-plan`、`name-consistency` 重复，删；精简的树与规则留下 |
| §5.2 规则表、规则顺序与回填 | 键表进 `config-reference.md`；规则与 `japanese-cues` 重复，删 |
| §6 的守卫阈值、降级子批次 ID、预算数值 | 与 `stt-workers`、`translation-subsystem`、`name-consistency` 重复，删；摘要留下 |
| §7.1 的 DLL 共存证据与模块清单 | 与 `stt-workers`、`batch-orchestration` 重复，删；进程图与三条规则留下 |
| §7.2 仍成立的事实 | `docs/development/technology-stack.md` "选版规则"；其余原已在 `technology-stack.md`、`dependencies.md`、ADR-0007 |
| §7.2 其余（历史三环境表、llama.cpp 经过、备选方案）、§7.3 冻结的代码布局、§7.4 上游版本核实表 | 历史记录 |
| §8（内容为"无"） | 删除（原文也在历史记录） |
| §9、§12、§13 | 历史记录 |
| §10.1、§10.2 | `config-reference.md` |
| §11 | 历史记录；技术设计留一句指向 `docs/pending-decisions.md` 与 `.scratch/next-directions/issues/` |

### 技术设计与代码对不上的地方

都按代码写进新页面或删掉，没有改代码；需要用户知道的记在 spec §8 第 6 项。

1. extract 并发：原文"默认 `min(4, cpu_count)`"，代码是固定默认 4（`kototoki/config.py`、`kototoki/job.py`）。
2. 翻译 run 目录：原文 `<配方名>__s<seed>/`，代码是 `<配方名>__s<seed>__n<表sha12>/`（模块页原已与代码一致）。
3. 目录树里的 `translate-sessions/`：代码只有 `strata-sessions`。
4. §10.2 把"端口"列为配置项：代码没有端口键，Strata 端口固定 8080。
5. §10.2 说只有 cue 规则会让产物失效：`[input] audio_language` 也进 `probe.json` 的身份（`kototoki/plan.py`）。
6. §7.2 的"测试工具放 dependency group"、torchcodec 走 cu128 索引、transformers 版本：与 `pyproject.toml`、`technology-stack.md` 不符，已过时，只留在历史记录。
7. `kototoki.toml.example` 的 `[stt] engine` 注释写 `# w0 | x0`，代码还接受 `cross`。示例文件没有改。

## Answer

门通过：技术设计 12,336 字符（≤ 15,000），被删的每一节都有去向（上表）；`just gate-core` 退出码 0（716 个测试）。
遗留：代码注释与 `kototoki.toml.example` 里的"规格 §10"现在落到一行桩上；`scripts/upgrade.py` 的输出与 `dependencies.md` 里还写着"规格 §7.2 的配置示例"。
前者在票据 11 改 docstring 时处理，后者涉及脚本输出文字，记 spec §8。
