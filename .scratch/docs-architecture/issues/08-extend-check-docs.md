# 08 扩展 `scripts/check_docs.py`

Status: resolved
Type: task
Blocked by: 04, 05

范围见 [spec §4 票据 08](../spec.md#08-扩展-scriptscheck_docspy)。

## 执行记录

新增检查全部用标准库，每条错误带文件与行号；入口仍是 `just docs-check`（在 `gate-core` 内）。

| 检查 | 级别 | 实现 |
| --- | --- | --- |
| `docs/` 每篇 `.md`（含归档件）被某个 `INDEX.md` 或子索引（`docs/research/topics/`）链接 | 错误 | `check_registration` |
| `experiments/` 每个含 `.py` 的包目录出现在 `experiments/INDEX.md` | 错误 | `check_experiments` |
| 预算：`AGENTS.md` ≤ 4,500 字符；各 `INDEX.md` ≤ 150 行、单行 ≤ 400；活正文（`docs/architecture`、`docs/development`、`docs/agents`、`CURRENT.md`、`pending-decisions.md`）≤ 12,000 字符、单行 ≤ 800；技术设计 ≤ 15,000 | 错误 | `check_budgets`；超标的既有文件记在 `BUDGET_WHITELIST`，按当前数值封顶，回到预算内时告警提醒删行 |
| 活文档里反引号包住的仓库路径存在 | 错误 | `check_paths`；通配、占位符、带空格的命令与 `.local/` 不算路径 |
| `kototoki/` 每个模块与子包出现在某篇模块页的"代码与验证入口" | 错误 | `check_product_ownership` |
| 活文档状态行含 3 个以上日期 | 告警 | `check_status_lines` |
| ADR 文件、"全部 ADR"表（含跳转页一行）、"编号从 N 起"一致 | 错误 | `check_adr_index` |
| 链接检查范围加入 `experiments/INDEX.md`、`experiments/**/README*.md`、`.scratch/**/*.md` | 错误 | `link_scope`；文档数 253 → 486 |

- 首次运行的结果与处理：
  - 孤儿 5 篇（`docs/agents/domain.md`、`triage-labels.md`，`docs/development/inference-selection.md`、`toolchain.md`、`windows-nvidia.md`）：在 `docs/INDEX.md` 补链接。
  - 预算超标 13 个文件：记入白名单（当前数值）。其中 `docs/agents/subtitle-translation-evaluation.md` 被代码校验、不能改，长期留在白名单；
    其余由票据 09–11 清掉。`docs/development/dependencies.md` 与 `workflow.md` 只是单行超长，不在 09–11 的对象里，见 spec §8。
  - 失效的反引号路径 8 处：7 处在模块页与技术设计里（`docs/changes/*` 5 处、`docs/changes/name-consistency-product.md`、`tests/test_translate.py`），
    记入 `KNOWN_MISSING_PATHS`，由票据 09、10 修；`kototoki/llama_server.py`（决定索引演进链按历史提到）与文档规则里按需创建的
    `docs/operations`、`docs/architecture/collaborations.md` 记入 `REMOVED_PATHS` 并写了原因。
  - `.scratch/` 里 12 处断链，都在已结题的票据里、指向 3 篇已删除的文档：冻结后不能修，按目标路径放行（`FROZEN_DEAD_TARGETS`，只对 `.scratch/` 下的来源生效）。
  - 模块归属：`kototoki/` 的 20 个顶层模块与 3 个子包都已出现在某篇模块页的"代码与验证入口"，0 个缺失
    （spec §1.2 第 11 条"`strata.py`、`guard.py` 等没有明确归属"按这条检查不成立；是否单独成页仍由票据 10 处理）。
  - 状态行告警 8 条（7 篇模块页与技术设计），由票据 09、10 处理。
- 冻结保护没有做成 diff 检查；`docs/archive/` 继续跳过链接检查，原因写在脚本 docstring 里。
- 单元测试 `tests/core/test_check_docs.py`（15 个，core 层，只用临时目录里的合成文档树）。`docs/development/workflow.md` 的 `docs-check` 一行同步。

## Answer

门通过：`just gate-core` 退出码 0（`check-toolchain`、`docs-check`、`check`、`test`；716 个测试通过）。
