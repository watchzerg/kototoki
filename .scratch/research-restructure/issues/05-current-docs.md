# 05 现行文档改链与旧文档删除

Status: resolved
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

## Answer

- **登记**：`research/INDEX.md` 登记 16 个轮次与 8 篇验收记录，加"按主题的现状"表（取代旧 `topics/*` 与 `timeline.md`）、研究方法约束（已结题线不重开、v3／v4／v5 确认集已开封、v2 只取教训、裁判规则见翻译评估方法）与"遗留路径"说明（`kototoki/` 注释中的 `experiments/…` 指归档 tag）。
- **改链**：全部 ADR（0031 除外）只改链接与旧路径代码段（改为 tag 形式）；CURRENT、决定索引、GLOSSARY、README、`docs/INDEX.md`、`docs/specs/INDEX.md` 与现行技术设计、`docs/development/*`、`docs/agents/*`、`docs/pending-decisions.md`、架构总览与各模块页。CURRENT 专名一节的"`experiments/name_consistency/` 冻结"改为"研究代码已随 0031 删除"。
- **现行内容迁移**：`stt-workers.md` 直接写入此前只在研究页的继承规则（`source-span-merge-v1` 的 480000 样本硬切与 ≤30 s 合并、w0 解码参数、MMS 词表／blank／精度／失败回退／TF32）；`translation-evaluation.md` 重写为文字口径（裁判 profile、执行面、MQM 规则、成对盲评、统计、两种人名错误口径），不再引用脚本；`inference-selection.md` 删去字节校验说明；`module-boundaries.md` 删研究侧条款、加 R5／R6；`workflow.md` 删 legacy、等价层与研究测试 recipe 的描述。
- **删除**：`docs/research/`、`docs/plans/`、`docs/context/`、`docs/testing/`、`docs/guides/`、`docs/archive/`、`docs/agents/subtitle-translation-evaluation.md`、`docs/specs/subtitle-translation-*.md`、`docs/specs/{w0,x0}-reusable-demo.md`，以及只服务研究侧的 `docs/architecture/stt-candidate-pipelines.md` 和 8 个模块页（vad-stage、w0／x0-pipeline、mms-alignment、stt-evaluation、corpus-and-assets、translation-runtime、translation-srt-flow）。
- **预算**：tag 路径变长使 5 个模块页与决定索引超预算，靠把"变更与决策来源"里的归档项合并为一句"归档 tag 中：…"（不加反引号）压回预算内，没有加白名单。
- **完成标准**：grep 旧路径只剩 tag 形式、ADR-0031 与决定索引演进链中描述删除范围的历史提法。`check_docs.py`（06 的新规则已在工作区）除 `.scratch/` 下 67 处指向已删文档的链接外无错误；这些交 07 处理。告警 1 条：`japanese-cues.md` 状态行含 3 个以上日期（既有）。
