# T1 文档先行

Status: done
Type: task
依赖：无

## 内容

按 changes 文档 §2、§6 改模块边界、四个模块页、技术设计相应小节，新增 ADR-0012（proposed）与 GLOSSARY 词条。

## 文件所有权

`docs/architecture/module-boundaries.md`、`docs/architecture/modules/{stt-workers,stage-plan,artifact-contract,config-and-media}.md`、`docs/specs/bilingual-subtitle-pipeline.md`、`docs/adr/0012-cross-asr-judge.md`、`GLOSSARY.md`

## 完成标准

接口形状与 changes 文档一致；未交付的部分在模块页标注实施中；`just docs-check` 无新增报错。

## Comments

- 2026-10-19 T1 交付：已改模块边界、四个模块页（stt-workers、stage-plan、artifact-contract、config-and-media）、技术设计 §1.1／§2／§3.2／§4／§7.1／§10／§13、GLOSSARY（扩写 `STT 引擎` 条目），新增 ADR-0012（proposed）。所有 cross 目标行为都带"实施中（票据 .scratch/cross-asr-judge T5／T6），交付前以 changes 文档为准"标记，T7 须全部去掉：`grep -rn "实施中（票据 .scratch/cross-asr-judge" docs GLOSSARY.md`，并删除指向 `docs/changes/cross-asr-judge.md` 的链接。已按协调者更正：start_sequence 为 `tokenizer.sot_sequence`（CT2 自动接 `<|notimestamps|>`）、新增"打分抛错取 w0、告警计数"守卫、`score(audio, chunk, texts, max_batch=16)`。`docs/INDEX.md` 的 ADR 清单需另加一行（见报告）。
