# 待用户裁定事项

状态：current（活文档；原文在来源文件里，本页只抄录并链接；裁定后删行并按 [adr/INDEX.md#记录新决定](adr/INDEX.md#记录新决定) 落 ADR）

整理于 2026-11-11，同日用户委托 agent 裁定了其中"待确认是否仍开放"的各行（来源：3 篇新计划 §8、v5–v15 报告的待裁定节、10-19 交叉合并与专名各篇、决定索引原"未关闭项"）。本页不替用户选，也不给建议。"待用户确认是否仍开放"指：来源文件写着待裁定，但没有 ADR 或决定索引明确裁定，也没有明确的"已关闭"字样，请用户确认后删行或改为未裁定。三份最新计划（[architecture-cleanup](plans/architecture-cleanup.md)、[asr-repeat-guard](plans/asr-repeat-guard.md)、[product-names-on-strata](plans/product-names-on-strata.md)）的 §8 已全部裁定或解决，没有遗留项。

## 翻译、STT、产品与架构

没有未裁定项。2026-11-11 用户委托 agent 逐项裁定，原先 9 行"待用户确认是否仍开放"与"引擎并存"一行全部关闭，见下方"已裁定"表末尾各行。
这些都是已结题研究线上的遗留想法或只在某个未采纳方案下才有意义的子问题；重开只由用户明确要求。

## 文档与工具

| 主题 | 提出日期 | 来源 | 选项（来源原文，浓缩） | 状态 |
| --- | --- | --- | --- | --- |
| `lint`、`typecheck` 选定哪个工具：现已从 `gate-core` 拿掉，换成 `check`（`compileall`），两个 recipe 保留 | 2026-11-11 | [architecture-cleanup 计划](plans/architecture-cleanup.md) §8 第 1 条 | 来源写"选定工具属改环境，另行决定"，未列候选 | 未裁定 |

## 文档架构整理中提出

2026-11-11 文档架构整理执行中记下的 7 项（[spec §8](../.scratch/docs-architecture/spec.md#8-待用户裁定)）已由用户委托 agent 裁定并落实，结果见 [spec §9](../.scratch/docs-architecture/spec.md#9-裁定结果)。

## 未验证与已知限制（不需要裁定，仅列示）

原在决定索引"未关闭项"，2026-11-11 原文移到这里；是验证缺口或运行注意事项，不是待选择的问题。

- **W0／X0 demo 的 CLI 旧默认**：省略参数时仍落到旧 PyanNet／fixed30，须显式选择新 Pyannote（[0003](adr/0003-new-pyannote-baselines.md)）。
- ~~产品与基线 Q3 不一致~~（2026-11-09 提出，同日由 [0022](adr/0022-product-names-on-strata.md) 关闭：产品建表切到 Strata，规则与 Q3 逐字节一致；翻译仍是 `q2-degrade-v1`＝Q2 规则＋降级）。
- **未裁定或未验证**：
  - Q2 在产品里曾每包约 16 s（v12 F1 的 6 倍），原因是启动时整机内存不够放下专家区、引擎退到 mmap；专家锁进内存后整片重跑每包约 3.1 s（2026-11-08，[翻译子系统模块页](architecture/modules/translation-subsystem.md#代码与验证入口)）；产品已改为启动前等可用内存、ready 后确认专家全部锁进内存、退到 mmap 即拒绝（[0019](adr/0019-product-translation-q2.md)），因此需要约 52 GiB 可用内存；同 seed 跨 Strata 启动不可复现；产品进程被强杀时 Strata 可能留在后台，须手动 `strata launch --stop`；
  - 给新 SRT 生成 Q1／Q2／Q3 翻译配方已有 `v13.write_q2`；用 Q3 规则建表的通用入口自 0022 起是产品的 names 阶段（研究侧 v13 仍只覆盖固定输入）；Q3 的产品结果只来自一次建表，同一部片两次建表写法 Jaccard 只有 0.56／0.48（[0021](adr/0021-q3-strata-names-baseline.md)）；
  - 同 seed 输出不确定的噪声底没有量化（[v11](research/2026-10-22-q0-product-route-v11.md) §8 第 5 项；2026-11-11 裁定不做 A/A 重跑，同 seed 配对比较的结论继续带这层噪声读）；
  - `cross` 尚未在新素材上确认（[0012](adr/0012-cross-asr-judge.md)）；
  - 音频输入未用真实音频文件跑过整条链；音频时长偏短只告警，损坏的音频文件会出不完整字幕（[0020](adr/0020-media-inputs-work-dir-and-side-by-side-publish.md)）；
  - 内嵌日文字幕路径只用合成片段验证过：没有用真实片源跑过，ASS 的卡拉 OK／屏幕字噪声未知，Strata 对人工字幕输入的建表与翻译未做真实模型验证（[0024](adr/0024-embedded-japanese-subtitles.md)）。

## 已裁定（仅供对照）

| 条目 | 来源 | 裁定出处 |
| --- | --- | --- |
| `dp6-grp` 设为完整 SRT 流程基线（v7 第 1、2 项；`mark5` 未设默认） | [v7](research/2026-10-16-gap-aware-batching-v7.md) §8 | 同节 2026-10-17 用户裁定；[ADR-0010](adr/0010-dp10-cut-translation-flow-baseline.md) |
| 语序重排线关闭，不立项备选路线；产品门槛与同步随之关闭 | [v8](research/2026-10-18-group-reorder-v8.md) §8 | 同节 2026-10-18 用户裁定 |
| 是否进入 L3、`qwen-wide` 进基线、3.3 倍墙钟、是否改基线／产品（v9 第 1、2、4、7 项） | [v9](research/2026-10-21-general-model-translation-v9.md) §8 | [ADR-0015](adr/0015-two-translation-baselines.md)（Q0）；[ADR-0019](adr/0019-product-translation-q2.md)（产品翻译） |
| `q0-names` 如何进 Q 线；新基线 Q1；产品是否改用 Q 线；A2 盲读表（v10 第 1、3、4 项；v11 第 1、3 项） | [v10](research/2026-10-21-q0-exploration-v10.md)、[v11](research/2026-10-22-q0-product-route-v11.md) §8 | v10 同节 2026-10-22 用户裁定；[决定索引·演进链](adr/INDEX.md#演进链)"Q 线基线" 0016→0017；[ADR-0019](adr/0019-product-translation-q2.md) |
| 专名表质量线（v11 第 4 项） | [v11](research/2026-10-22-q0-product-route-v11.md) §8 | [ADR-0021](adr/0021-q3-strata-names-baseline.md)、[ADR-0022](adr/0022-product-names-on-strata.md) |
| v12 全部（立项、MTP 下载、F1 门、阶段 E、DFlash2 对比） | [v12](research/2026-11-08-strata-flash-next-v12.md) §8 | 同节各项"已裁定（2026-11-08）"；[ADR-0017](adr/0017-q2-strata-default-launch-baseline.md) |
| v13 全部（产品是否切 Strata、Q2 基线处理、放行 v4、交付失败口径、后续怎么走） | [v13](research/2026-11-08-names-on-strata-v13.md) §8 | 同节"已裁定（2026-11-08／09）"；[ADR-0021](adr/0021-q3-strata-names-baseline.md)、[ADR-0022](adr/0022-product-names-on-strata.md) |
| v14 立项、C 臂边界、A2 越权、B0 口径、C 后续（第 1–6 项） | [v14](research/2026-11-09-asr-robustness-v14.md) §8 | 同节第 12 项（2026-11-10 用户裁定）及 [v15](research/2026-11-10-asr-robustness-v15.md) §8 第 1–6 项 |
| v15 全部（A 进产品；B、C3 不进；规范写法规则与"同指称等价"口径随之关闭） | [v15](research/2026-11-10-asr-robustness-v15.md) §8 第 7、10、11 项 | 同节 2026-11-10／11 裁定；[ADR-0023](adr/0023-asr-repeat-guard.md)；[决定索引·专名一致性](adr/INDEX.md#当前有效决定)行"2026-11-11 用户裁定该替换不进产品" |
| asr-repeat-guard 计划 §8 第 1–5 项 | [计划](plans/asr-repeat-guard.md) §8 | 同节各项"已裁定（2026-11-11）" |
| product-names-on-strata 计划 §8 第 1–3 项 | [计划](plans/product-names-on-strata.md) §8 | 同节各项"已裁定"／"已解决" |
| architecture-cleanup 计划 §8（`Session` 接口等） | [计划](plans/architecture-cleanup.md) §8 | 同节 2026-11-11 用户裁定（lint／typecheck 工具选择未决，见上） |
| `cross` 合并线（是否开新线、交叉打分作裁判、MMS 过滤） | [oracle](research/2026-10-19-asr-pair-oracle.md)、[交叉打分](research/2026-10-19-asr-pair-cross-score.md)、[CTC](research/2026-10-19-asr-pair-ctc-judge.md) | [ADR-0012](adr/0012-cross-asr-judge.md)（可选引擎 `cross`，默认 `w0`） |
| 专名一致性各轮（第 1–6 轮）的下一轮候选与是否进产品 | [round2–6](research/2026-10-19-name-consistency-round6.md) 等 | [ADR-0014](adr/0014-name-consistency-in-product.md)；[现行决定·专名](adr/CURRENT.md#专名) |
| 许可未声明的日语 ASR 权重、Qwen3 动漫微调（v5 第 3、4 项） | [v5](research/2026-10-16-quality-exploration-v5.md) §8 | 同节 2026-10-18 用户裁定：换 ASR 模型线停止 |
| 切包吸附 `gsnap5`、路由配方（v6 第 1–3 项）；切包硬边界按产品时间轴重定、`mark5` 可选配方（v7 第 3、4 项） | [v6](research/2026-10-16-scene-aware-batching-v6.md)、[v7](research/2026-10-16-gap-aware-batching-v7.md) §8 | 2026-11-11 用户委托 agent 裁定：关闭、不采纳。切包已定为 `dp10-cut`（[ADR-0010](adr/0010-dp10-cut-translation-flow-baseline.md)），两项都只在采纳各自变体时才有意义 |
| `qwen-wide` 线遗留项（v9 第 3、6 项）；v10 执行中记录的三个想法（第 5 项） | [v9](research/2026-10-21-general-model-translation-v9.md)、[v10](research/2026-10-21-q0-exploration-v10.md) §8 | 2026-11-11 同上：关闭、不执行。Q 线已走到 Q3，产品已是 `q2-degrade-v1`；三个想法在来源里就没有执行资格 |
| 新基线之后的确认集（v11 第 2 项） | [v11](research/2026-10-22-q0-product-route-v11.md) §8 | 2026-11-11 同上：不是待选择的问题。新的确认只能用全新隔离的集合（[ADR-0018](adr/0018-q2-sole-translation-baseline.md) 第 5 点），等有新的产品素材与参考字幕时由用户立项 |
| 同 seed 输出不确定：是否做 A/A 量化噪声底（v11 第 5 项） | [v11](research/2026-10-22-q0-product-route-v11.md) §8 | 2026-11-11 同上：不做（要占 GPU 并花裁判费用）；作为已知限制列在上一节 |
| STT 下一轮的对象（v14 第 11 项）；VAD 召回加窗与观感抽查表（v5 第 1、2 项） | [v14](research/2026-11-09-asr-robustness-v14.md)、[v5](research/2026-10-16-quality-exploration-v5.md) §8 | 2026-11-11 同上：关闭。来源只记想法、不建议改默认；不提议新轮次，立项由用户提出 |
| 声学裁判线后续（Parakeet-ja 试装、继续投入声学裁判） | [声学裁判调研](research/2026-10-19-acoustic-judge-survey.md)、[CTC 裁判](research/2026-10-19-asr-pair-ctc-judge.md)、[交叉打分](research/2026-10-19-asr-pair-cross-score.md) | 2026-11-11 同上：不继续。交叉打分已作为 `cross` 的裁判进产品（[ADR-0012](adr/0012-cross-asr-judge.md)），换 ASR 模型线已停止（v5 §8） |
| 引擎并存：H0 研究侧是否从 compat loader b11429 升级 | [ADR-0005](adr/0005-apex-i-compact-translation-baseline.md) | 2026-11-11 同上：不升级。H0 只作历史对照身份，换引擎会改变它的身份 |
