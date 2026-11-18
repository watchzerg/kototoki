# cue 间隔断句引入 ASR token 边界的离线调研

## 状态
concluded：只读离线调研，用户裁定不实现（2026-10-15，对应产品票据 13 结票）。

## 时间
2026-10-15（立项与结题同日）。

## 问题
双语字幕流水线的日文 cue 间隔断句改为"只在跨 VAD 子段时成立"后，遗留一个样本：HF II 约 1969 s 处的两字词（参考字幕为真实拖长音）仍被切成两条，两字的字符时间都落在 VAD 子段之外（Pyannote 漏检了这段语音），cue 构建只凭字符时间与子段无法判定它是词内间隙。能否把 ASR 的 token 边界带进对齐产物，让 cue 构建在"同一 token 内不断句"？

## 策略
只读分析，不改产品：用 `tokenizers` 直接加载两个模型的 tokenizer，把 ASR 逐窗 trace 里的 token 字节按 GPT-2 字节表还原并整窗解码，对回窗口文字；把字节边界落在多字节字符内的相邻 token 并成一组，得到每个字符所属的 token 组；再在现有 cue 构建之外用额外包含区间模拟"同 token 内不断句"，离线重算 cue 统计。

## 环境与版本
- 引擎：W0（Whisper large-v3 tokenizer，eot id 50257）与 X0（Qwen3-ASR tokenizer，去特殊 token 后解码）。
- 数据来自产品最终验收的整片中间产物（两部电影 × 两个引擎，共 772 个窗口）；未运行模型、没有 GPU 作业。cue 配方为产品默认 `[cues]` 配置，见 [日文 cue 模块页](../../docs/architecture/modules/japanese-cues.md)。

## 测试
- 数据：Heaven's Feel II／III 整片、W0／X0 各一次产物的 ASR trace 与对齐结果（类型：整片电影，日语）。
- 判据：token 字节重建是否与窗口文字逐窗全等；同 token 内的间隔断句数；改后 cue 总数、≤2 字 cue 数、>6 s cue 数、重叠数相对默认配置的变化。无人工观感评估。

## 结果
- 映射可行且稳定：772 个窗口两个引擎的解码字节串与窗口文字逐窗全等，零不匹配；需并组的多字节字符 token 在 W0 约占 6.8%–7.5%、X0 约 2.6%–3.0%。
- token 粒度接近单字：Whisper 日文平均 1.28 字／组，Qwen 1.52 字／组；建票样本的两字词是两个独立 token，不会被合并。

| 整片 | 间隔断句数 | 其中同 token 内 | cue 数 | ≤2 字 | >6 s |
| --- | ---: | ---: | --- | --- | --- |
| W0／II | 795 | 10 | 1048→1045 | 110→106 | 2→3 |
| W0／III | 975 | 8 | 1181→1184 | 118→117 | 6→7 |
| X0／II | 320 | 7 | 1150→1146 | 114→109 | 0→0 |
| X0／III | 328 | 8 | 1257→1252 | 90→88 | 1→1 |

同 token 内的间隔多在 1–14 s，跨过 VAD 非语音区，是 CTC 把一个 token 的两个字对到了不同语句，不是拖长音；合并它们反而产生新的 >6 s cue，W0／III 的 cue 数还因后续硬切而增加。

## 结论与去向
- 放弃：四部合计 ≤2 字 cue 只减少 12 条（432→420），修不了建票样本，还引入 >6 s cue；不值得改两个 ASR worker 的产物、任务参数透传与三个阶段配方哈希。
- 根因是 Pyannote 对约 2.4 s 拖长音的漏检，属 VAD 召回问题，不在 cue 层解决；VAD 召回暂不另开票。
- 相关现行决定：产品架构 [ADR-0007](../../docs/adr/0007-bilingual-subtitle-pipeline-architecture.md)、VAD 基线 [ADR-0003](../../docs/adr/0003-new-pyannote-baselines.md)；VAD 候选比较见 [VAD 比较](../2026-10-vad-comparison/README.md)。

## 教训
- 把模型内部边界（token）带入下游断句，收益取决于 token 粒度；日文 token 近似单字时几乎没有合并机会。
- 推断而非观察：Whisper 日文 token 粒度在其他素材上同样接近单字，未在其他影片验证。

## 原始材料
前缀 `archive/2026-11-18-pre-research-restructure:`：
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-15-cue-token-boundary-study.md`
