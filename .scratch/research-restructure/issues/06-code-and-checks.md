# 06 代码侧清理与机械检查

Status: ready-for-agent
Type: task
Blocked by: 05

## 范围（`kototoki/` 不动）

1. `git mv experiments/w0_demo/THIRD_PARTY_NOTICES.txt THIRD_PARTY_NOTICES.txt`（内容不改）；README 的许可一节指向它。
2. 删除 `experiments/`、`kototoki_eval/`、`tests/equivalence/`。
3. `justfile`：删 `legacy` 变量与 `experiments-test`、`x0-demo`、`translation-test`、`translation-demo`、`translation-baseline`、`translation-srt`、`translation-eval`、`translation-flow`、`translation-flow-test`、`translation-flow-v2-test`、`test-equivalence`；`check` 的 compileall 列表去掉 `kototoki_eval experiments`；`gate-full` 改为 `gate-core test-full`。
4. `pyproject.toml`、`.claude/settings.json`：删除指向 `experiments`、`kototoki_eval` 的配置与权限条目（`.claude/settings.local.json` 不动）。
5. `scripts/smoke/ct2_after_torch.py`、`scripts/smoke/forced_align.py` 导入了 `experiments.w0_demo`：若产品模块（`kototoki/asr_whisper.py`、`kototoki/align.py`）提供等价函数，改为导入产品；否则删除这两项 smoke 并从 `run_all.py` 与 `docs/development/workflow.md` 的 smoke 列表移除。不运行 smoke，只做静态检查（`compileall`、`--help` 或导入）。
6. `tests/core`：`ResearchPinTests` 等注释里的研究来源改为 tag 路径；`test_boundaries.py` 增加"产品不导入 `research`"；删除对 `experiments`／`kototoki_eval` 存在性的断言（如有）。不改被钉住的取值。
7. `scripts/check_docs.py`（及 `tests/core/test_check_docs.py`）：
   - 删除 `BYTE_VERIFIED` 与已删文件的 `BUDGET_WHITELIST` 行；`PATH_ROOTS` 去掉 `kototoki_eval/`、`experiments/`，加入 `research/`。
   - 新增 R8 检查：`research/*/README.md` 必填标题（与 `research/TEMPLATE.md` 一致，`research/acceptance/` 用其模板）；`research/`、`docs/`、`tests/` 中的绝对盘符路径（允许在测试里用明确的白名单标注虚构路径，例如现有的 `D:/movies/ep01.mkv`）；`research/` 中的 64 位十六进制串。
   - 每条新检查各加一个正例和反例测试。
8. `.gitignore`、`mise.toml` 无需改（确认即可）。

## 完成标准

- `rg -n "experiments|kototoki_eval" --glob '!kototoki/**' --glob '!research/**'` 只剩 tag 路径形式或 ADR-0031 正文。
- `just gate-core` 通过（需先 setup，见 spec 前置条件）；`just test-full` 若 ffmpeg 可用则通过。
- `git diff --stat archive/2026-11-18-pre-research-restructure -- kototoki/` 为空。
