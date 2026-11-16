# 首次大批量运行暴露的主程序问题

Status: in-progress
建票：2026-11-16。范围：产品包 `kototoki/`（抽取、发布、运行日志、专名、翻译、识别）。

## 1. 依据

2026-11-12～11-15 用 `just subtitles` 对一个 232 个视频文件的外接移动硬盘目录跑了完整批次（3 次运行，中途两次中断后续跑）。结果：228 个生成双语字幕，4 个在抽取阶段失败；发布阶段 228 个全部失败（字幕由人工从工作目录拷出）。运行中与运行后对日志和产物做了排查，本 spec 收录**原因已查清**的主程序问题。

证据都在本机、不进 Git（含源文件名与音频）：

- 运行台账：`.local/run-notes/jav_best_copy-20261112.md`（问题清单、时间线、排查过程）。
- 封存的 20 个问题文件工作目录与总结：`D:\jav_best_copy_work\README.md`；目录名为 `<番号>__<work_id>`，票据里只引用 work_id。
- 其余 212 个文件的工作目录：`.local/work/jav_best_copy-15fff3e12253/`；运行日志 `run-20261112T121603Z.log`、`run-20261112T141709Z.log`、`run-20261114T235704Z.log`。

不收录（原因不明，另行调查）：3 个源文件本身损坏（`moov atom not found`、STSC/STCO 矛盾）；5 个时间戳严重断裂文件的断裂成因（本 spec 只管"检测出来"）；7 个比值约 0.994 的轻微补偿的成因。

## 2. 约定

- 每张票都是 `Status: needs-triage`：问题与证据已写清，**优化方向未定**，由用户在单独 session 里逐票讨论确定后改为 `ready-for-agent`。票里的"候选方向"只是起点，不是结论。
- 定方向后按 AGENTS.md：接口形状、产物契约或失败判定有变化时，先改模块页（`docs/architecture/modules/`）与[模块边界](../../docs/architecture/module-boundaries.md)，必要时改[技术设计](../../docs/specs/bilingual-subtitle-pipeline.md)，再动代码；配方变化（识别、翻译、抽取）要出新版本；涉及翻译基线 Q3 行为的先问用户。
- 不跑 GPU 重任务验证，除非用户批准；可以用封存目录里的 `audio.m4a`（原始音轨流复制）离线复现抽取阶段问题。
- 一票一提交；`just test` 通过；按[随交付同步](../../docs/agents/documentation.md#随交付同步)更新文档。

## 3. 票据

| # | 标题 | 原清单条目 | 依赖 | 状态 |
| --- | --- | --- | --- | --- |
| 01 | [跨盘发布失败与审计顺序](issues/01-cross-drive-publish.md) | 1、2 | — | resolved |
| 02 | [音轨采样率标错](issues/02-sample-rate-mislabel.md) | 3 | — | resolved |
| 03 | [extract 诊断：按级别统计解码错误、限制日志体积](issues/03-extract-diagnostics.md) | 7、10 | — | needs-triage |
| 04 | [抽取质量门：解码远超视频时长、近乎全静音](issues/04-extract-quality-gate.md) | 4、5 | 03（软依赖：可能用到真实错误数） | needs-triage |
| 05 | [归档音轨流复制失败导致整片失败](issues/05-archive-copy-failure.md) | 6 | — | needs-triage |
| 06 | [运行日志与汇总修正](issues/06-run-log-and-summary.md) | 8、9、11、12、13 | — | needs-triage |
| 07 | [专名表把空列表判为不合格](issues/07-names-empty-list.md) | 14 | — | needs-triage |
| 08 | [单字与语气词 cue 的翻译失败](issues/08-short-cue-translation.md) | 15 | — | needs-triage |
| 09 | [极短窗口识别字数过多导致对齐失败](issues/09-short-window-asr-overflow.md) | 16 | — | needs-triage |

分组理由：01 是独立 bug；02–05 都在抽取阶段，02 是"修正"，03 是"测量"，04 是"判失败"，05 是"降级"，可以分开讨论；06 是一组互不依赖的小改动；07–09 分属专名、翻译、识别三个模型阶段，各自牵涉配方或基线。
