# 05 现行文档改链与旧文档删除

Status: ready-for-agent
Type: task
Blocked by: 02, 03, 04

## 范围

1. **登记**：用 02–04 的 `## Answer` 填 `research/INDEX.md` 的轮次登记表；把 `docs/research/INDEX.md` 的"按主题的现状"与 `topics/*` 精简成 `research/INDEX.md` 的主题现状表；把研究方法约束（已结题线不重开、哪些确认集已开封需用新集合、v2 只取教训）写成几条规则。注明：`kototoki/` 注释中的 `experiments/…` 路径指归档 tag。
2. **改链**（`docs/research/…`、`docs/plans/…`、`docs/context/…`、`docs/testing/…`、`docs/guides/…`、`experiments/…`、`kototoki_eval/…` → 新轮次目录或 tag 路径）：`docs/adr/*`（只改链接）、`docs/adr/CURRENT.md`、`docs/adr/INDEX.md`、`GLOSSARY.md`、`README.md`、`docs/INDEX.md`（删"项目特有入口"中已删目录的行，加 `research/INDEX.md`）、`docs/architecture/**`、`docs/specs/INDEX.md` 与 `bilingual-subtitle-pipeline.md`、`docs/development/*`、`docs/agents/*`、`docs/pending-decisions.md`、`CODING_STANDARDS.md`。
3. **现行内容迁移**（旧目录里仍然有效的契约不能随目录删掉）：
   - `docs/testing/` 中标为活契约的文件：仍被产品或测试使用的规则并入对应模块页或 `docs/agents/testing.md`；只服务旧 demo 的随 02 的轮次记录。
   - `docs/agents/translation-evaluation.md`：保留为现行方法文档，删去 Codex 历史段落与脚本路径依赖，口径用文字描述（来源 04 的 README）。
   - `docs/development/inference-selection.md`：保留，删去"字节被校验，不得修改"的说明。
   - `docs/architecture/INDEX.md` 与模块页：删除 `kototoki_eval`、`experiments/display` 的模块行和 STT 评分模块页（若只服务研究侧）；`stt-candidate-pipelines.md` 若仍是现行权威则保留并改链，否则并入 W0／X0 轮次 README 后删除；`module-boundaries.md` 删去关于 `kototoki_eval`／`experiments` 的条款，加入 R5 的方向规则。
   - `docs/specs/INDEX.md`：只列现行规格。
4. **删除**：`docs/research/`、`docs/plans/`、`docs/context/`、`docs/testing/`、`docs/guides/`、`docs/archive/`、`docs/agents/subtitle-translation-evaluation.md`、`docs/specs/subtitle-translation-*.md`、`docs/specs/w0-reusable-demo.md`、`docs/specs/x0-reusable-demo.md`。

## 完成标准

- 在 `docs/`、`research/`、根目录 Markdown 中 grep `docs/research/|docs/plans/|docs/context/|docs/testing/|docs/guides/|docs/archive/|kototoki_eval|experiments/` 只剩 tag 路径形式（`archive/2026-11-18-pre-research-restructure:`）的命中。
- `just docs-check` 的链接检查通过（`check_docs.py` 本身的规则调整在 06；若此处因 `PATH_ROOTS` 或 `BYTE_VERIFIED` 报错，记录后交 06）。
