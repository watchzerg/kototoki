# 01 `.scratch/` 纳入 Git

Status: resolved
Type: task
Blocked by: 无

范围见 [spec §4 票据 01](../spec.md#01-scratch-纳入-git)。

## 执行记录

- 删 `.gitignore` 的 `.scratch/` 行；`.gitignore` 的媒体、字幕、权重安全网规则仍对 `.scratch/` 生效。
- 提交前扫描 `.scratch/` 全部 197 个文件（196 篇 Markdown、1 个 `asr-repeat-guard/acceptance.py`）：
  - 密钥：按 `api key|secret|token|password|bearer|sk-…|hf_…|ghp_…` 搜索，命中的都是 `/tokenize`、`count_tokens`、
    `text_token_probs` 这类技术词，没有密钥。
  - 对白：查"连续 2 行以上、每行假名占比超过 30%"的段落，0 处。没有文件被扣下。
- `docs/agents/issue-tracker.md`：写明目录已纳入 Git、spec 即计划、结题后整目录冻结、隐私规则同仓库其余部分。
  改前已搜 `experiments/`、`scripts/`、`kototoki/`、`kototoki_eval/`、`tests/`，没有对它或 `documentation.md` 的 sha256 或内容断言。
- `docs/agents/documentation.md`：三态规则的"本次增量"改为落在 `.scratch/<slug>/`；落点表与权威归属表去掉
  `docs/changes/`；"既有目录"写明 `docs/plans/` 的 3 篇新计划原位冻结、不回迁。

## Answer

门通过：`just docs-check` 通过（238 篇、2625 个本地链接）；提交后 `git status` 干净；
`.scratch/` 下非 Markdown 文件只有 1 个 `.py`。
