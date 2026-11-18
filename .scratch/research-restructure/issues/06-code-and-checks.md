# 06 代码侧清理与机械检查

Status: resolved
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

## Answer

- `THIRD_PARTY_NOTICES.txt` 用 `git mv` 移到根目录（内容不变），README 加"第三方许可"一节指向它，并注明模块注释里的旧位置。
- 删除 `experiments/`、`kototoki_eval/`、`tests/equivalence/`。
- `justfile`：删 `legacy` 变量与全部研究 recipe（`experiments-test`、`x0-demo`、`translation-*`、`test-equivalence`）；`check` 只编译 `kototoki scripts tests`；`gate-full` = `gate-core test-full`。
- `.claude/settings.json`：删 `experiments.translation_v3` 的 allow 规则和 `translation-*`／`x0-demo` 的 allow 与 ask 规则，deny 规则不动；`settings.local.json` 未动。`pyproject.toml`、`.gitignore`、`mise.toml` 不含相关条目，未改。
- smoke：产品 `kototoki.asr_whisper` 有同名同签名的 `features`／`generate`，`kototoki.align` 有 `character_targets`／`mms_numeric_policy`／`normalize_window`，`ct2_after_torch.py` 与 `forced_align.py` 改为导入产品模块，保留在 `run_all.py`。只做了 `compileall`，未运行。
- `tests/core`：`test_boundaries.py` 改为 `kototoki/` 与 `tests/core/` 都不导入 `research`，并加了扫描器的正例；`test_guard`、`test_judge`、`test_job` 子进程里的禁入模块列表由 `experiments`／`kototoki_eval` 改为 `research`；各钉子的来源注释改为 tag 路径，删除"由 `tests/equivalence/…` 实时对照"的说法；钉住的取值未改。
- `scripts/check_docs.py`：删 `ARCHIVE`、`SUBINDEX`、`EXPERIMENTS_INDEX`、`BYTE_VERIFIED` 与研究目录检查，清空 `BUDGET_WHITELIST`，`PATH_ROOTS` 换成 `research/`；新增 R8 检查（轮次 README 与验收记录的必填标题与登记、`research/` 的 64 位十六进制串、`research/`／`docs/`／`tests/` 的盘符绝对路径，测试里的虚构路径登记在 `ALLOWED_ABSOLUTE_PATHS`）；`REMOVED_PATHS` 加 `tests/equivalence`（CURRENT 与决定索引按历史提到）。`tests/core/test_check_docs.py` 为每条新检查各加正例与反例，另有一条测试核对必填标题与 `research/TEMPLATE.md` 一致。
- 检查：`python -m unittest tests.core.test_boundaries tests.core.test_check_docs` 22 项通过；`check_docs.py` 除 `.scratch/` 下 67 处链接（交 07）外无错误；`git diff --stat <tag> -- kototoki/` 为空。`rg "experiments|kototoki_eval"`（排除 `kototoki/`、`research/`）余下的命中都是 tag 路径、ADR-0031 正文、决定索引演进链，以及历史 ADR 正文里的当时入口命令（ADR 只改链接，未改写）。
- **未做**：`.venv` 不存在，`just gate-core` 需要先 `just setup`（改环境、联网）。按要求须先问用户，本次未执行，所以产品 core 测试的完整一轮与 `just test-full` 都没有跑。
