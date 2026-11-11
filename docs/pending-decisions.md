# 待用户裁定事项

状态：current（活文档；原文在来源文件里，本页只抄录并链接；裁定后删行并按 [adr/INDEX.md#记录新决定](adr/INDEX.md#记录新决定) 落 ADR）

整理于 2026-11-11（来源：3 篇新计划 §8、v5–v15 报告的待裁定节、10-19 交叉合并与专名各篇、决定索引原"未关闭项"）。本页不替用户选，也不给建议。"待用户确认是否仍开放"指：来源文件写着待裁定，但没有 ADR 或决定索引明确裁定，也没有明确的"已关闭"字样，请用户确认后删行或改为未裁定。三份最新计划（[architecture-cleanup](plans/architecture-cleanup.md)、[asr-repeat-guard](plans/asr-repeat-guard.md)、[product-names-on-strata](plans/product-names-on-strata.md)）的 §8 已全部裁定或解决，没有遗留项。

## 翻译

| 主题 | 提出日期 | 来源 | 选项（来源原文，浓缩） | 状态 |
| --- | --- | --- | --- | --- |
| 切包吸附 `gsnap5`（`gap-split-v1`）是否设为 `translate-srt` 默认并写 ADR；是否同步产品；是否另做"只对剧集吸附"的路由配方 | 2026-10-16 | [v6](research/2026-10-16-scene-aware-batching-v6.md) §8 第 1–3 项 | 1：设为默认／不设（b10-joint 保持基线）；2：同步／不同步产品 `b10-joint-degrade-v1`（仅第 1 项采纳才有意义）；3：追路由配方须在全新隔离的剧集确认集上确认（v3、v4、v5 剧集集已开封），成本是一套新确认集 | 待用户确认是否仍开放 |
| 产品时间轴上小包过多，切包硬边界／下限是否按产品时间轴重定；`mark5` 是否保留为可选配方、是否同步产品 | 2026-10-16 | [v7](research/2026-10-16-gap-aware-batching-v7.md) §8 第 3、4 项（第 1 项 `mark5` 默认、第 2 项 `dp6-grp` 已裁，见下表） | 3：硬边界提高（例如 20 s），或下限改为"小于 6 句的段并入相邻段"，只在采纳切分类变体时才需要；4：同步／不同步产品（只在 `mark5` 采纳时有意义） | 待用户确认是否仍开放 |
| 通用模型（`qwen-wide`）线遗留项：自然度提示修订是否允许一次；产品时间轴上复算包大小分布与 wide 邻文条数 | 2026-10-21 | [v9](research/2026-10-21-general-model-translation-v9.md) §8 第 3、6 项 | 3：默认不允许，先复现；6：若进产品，在产品 `ja.srt` 上离线复算 | 待用户确认是否仍开放 |
| v10 执行中记录的想法：按类别路由 `v2b`；`qwen-p15`（C2）重开；ASR 感知提示与注入叠加（未测） | 2026-10-21 | [v10](research/2026-10-21-q0-exploration-v10.md) §8 第 5 项 | 三项均"没有资格按 §4.7 执行"，来源未给取舍；C2 称"若用户认为门过严可单独补跑" | 待用户确认是否仍开放 |
| 新基线之后的确认集：是否用剧集隔离集确认；产品侧无第三部有参考字幕影片 | 2026-10-23 | [v11](research/2026-10-22-q0-product-route-v11.md) §8 第 2 项 | 来源指出 N\* 适用产品 ASR 源而隔离集是 dev 干净源，确认只能等新的产品素材＋参考字幕 | 待用户确认是否仍开放 |
| 同 seed 输出不确定（prompt 逐字相同的包 24% 单元输出不同）：是否做 A/A（Q0 对 Q0 重跑）量化噪声底 | 2026-10-23 | [v11](research/2026-10-22-q0-product-route-v11.md) §8 第 5 项 | 做（1 seed＝GPU 1、另有裁判费用）／不做；此前所有同 seed 配对比较含一层噪声底 | 待用户确认是否仍开放 |

## STT

| 主题 | 提出日期 | 来源 | 选项（来源原文，浓缩） | 状态 |
| --- | --- | --- | --- | --- |
| STT 下一轮的对象：VAD 边界／分窗，或 ASR 模型本身，而非后处理 | 2026-11-09 | [v14](research/2026-11-09-asr-robustness-v14.md) §8 第 11 项 | 来源只记"想法（不执行）"：删除项定位显示两部 13–32% 的参考删除落在 VAD 窗口外、45–61% 落在有字子段内（长窗漏转），守卫或补窗触达不了；v5 第 11 步测过 onset／offset，未测窗口切分 | 待用户确认是否仍开放 |
| 声学裁判线后续：是否为 Parakeet-ja 做隔离环境试装与下载；是否继续在声学裁判上投入（读音级打分、逐 cue 过滤、更多影片调参） | 2026-10-19 | [声学裁判调研](research/2026-10-19-acoustic-judge-survey.md) §8 第 3 项；[CTC 裁判](research/2026-10-19-asr-pair-ctc-judge.md) §8 第 3 项；[交叉打分](research/2026-10-19-asr-pair-cross-score.md) §10 第 3 项 | 批准／不批准试装（不批准则候选停在"Windows 路径未证实"）；继续／不继续（均需新 GPU 作业或新依赖，按 AGENTS.md 先问）；交叉打分的后续含 Whisper EOT 概率、更多影片验证、按区间类型分阈值、官方整片口径复核 | 待用户确认是否仍开放 |
| VAD 召回：另开票试"只为漏检语音加窗口＋短窗幻觉过滤"（须两部同时降 CER 才谈改默认）；v5 第 5 步观感抽查表是否填写 | 2026-10-16 | [v5](research/2026-10-16-quality-exploration-v5.md) §8 第 1、2 项 | 2：来源注明"不建议改默认"，已转入 STT 第三轮票据；1：可选，不影响其他步骤 | 待用户确认是否仍开放 |

## 产品与架构

| 主题 | 提出日期 | 来源 | 选项（来源原文，浓缩） | 状态 |
| --- | --- | --- | --- | --- |
| 引擎并存：H0 研究侧仍用 compat loader b11429，产品用官方 llama.cpp；研究侧是否同步升级 | 2026-11-08 | 决定索引原"未关闭项"；[ADR-0005](adr/0005-apex-i-compact-translation-baseline.md) | 来源写"未裁定"，未列选项 | 未裁定 |

## 文档与工具

| 主题 | 提出日期 | 来源 | 选项（来源原文，浓缩） | 状态 |
| --- | --- | --- | --- | --- |
| `lint`、`typecheck` 选定哪个工具：现已从 `gate-core` 拿掉，换成 `check`（`compileall`），两个 recipe 保留 | 2026-11-11 | [architecture-cleanup 计划](plans/architecture-cleanup.md) §8 第 1 条 | 来源写"选定工具属改环境，另行决定"，未列候选 | 未裁定 |

## 文档架构整理中提出

2026-11-11 文档架构整理执行中冒出的事项记在 [spec §8](../.scratch/docs-architecture/spec.md#8-待用户裁定)（ADR 之间的不一致、过时但状态行未标的句子等），未裁定；裁定后在那里注明结果并从本节删除。

## 未验证与已知限制（不需要裁定，仅列示）

原在决定索引"未关闭项"，2026-11-11 原文移到这里；是验证缺口或运行注意事项，不是待选择的问题。

- **W0／X0 demo 的 CLI 旧默认**：省略参数时仍落到旧 PyanNet／fixed30，须显式选择新 Pyannote（[0003](adr/0003-new-pyannote-baselines.md)）。
- ~~产品与基线 Q3 不一致~~（2026-11-09 提出，同日由 [0022](adr/0022-product-names-on-strata.md) 关闭：产品建表切到 Strata，规则与 Q3 逐字节一致；翻译仍是 `q2-degrade-v1`＝Q2 规则＋降级）。
- **未裁定或未验证**：
  - Q2 在产品里曾每包约 16 s（v12 F1 的 6 倍），原因是启动时整机内存不够放下专家区、引擎退到 mmap；专家锁进内存后整片重跑每包约 3.1 s（2026-11-08，[翻译子系统模块页](architecture/modules/translation-subsystem.md#代码与验证入口)）；产品已改为启动前等可用内存、ready 后确认专家全部锁进内存、退到 mmap 即拒绝（[0019](adr/0019-product-translation-q2.md)），因此需要约 52 GiB 可用内存；同 seed 跨 Strata 启动不可复现；产品进程被强杀时 Strata 可能留在后台，须手动 `strata launch --stop`；
  - 给新 SRT 生成 Q1／Q2／Q3 翻译配方已有 `v13.write_q2`；用 Q3 规则建表的通用入口自 0022 起是产品的 names 阶段（研究侧 v13 仍只覆盖固定输入）；Q3 的产品结果只来自一次建表，同一部片两次建表写法 Jaccard 只有 0.56／0.48（[0021](adr/0021-q3-strata-names-baseline.md)）；
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
