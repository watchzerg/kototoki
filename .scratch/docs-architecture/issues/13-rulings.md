# 13 落实 §8 的裁定

Status: resolved
Type: task
Blocked by: 12

2026-11-11 票据 12 结题后，用户答复"待我裁定的部分，你自己决定并优化"。本票据落实 [spec §9](../spec.md#9-裁定结果) 的裁定。

## 执行记录

- 改前搜过代码：没有对这些 ADR、`docs/pending-decisions.md`、`docs/agents/translation-evaluation.md`、`docs/development/dependencies.md` 的 sha256 或内容断言；
  `tests/core/test_config.py` 读取 `kototoki.toml.example` 做解析测试，注释改动不影响。
- 8 篇 ADR 只在状态行末尾追加一句，带"（2026-11-11 标注，用户委托 agent 裁定）"；正文未动。
- `docs/pending-decisions.md`：翻译、STT、产品与架构三节合并为一句"没有未裁定项"，10 行移入"已裁定"表（7 行，逐行写理由）。
  来源报告是冻结证据，没有回去在报告里注明裁定结果；以该页为准。
- `scripts/upgrade.py` 只改了一行注释和一条提示文字，逻辑未动。
- `scripts/check_docs.py`：`BUDGET_WHITELIST` 去掉 `dependencies.md`，只剩字节被校验的 `docs/agents/subtitle-translation-evaluation.md`。

## Answer

7 项全部裁定并落实。门：`just docs-check`、`just gate-core` 通过。
没有代为决定的一项：`lint`、`typecheck` 的工具选择（要改环境）。
