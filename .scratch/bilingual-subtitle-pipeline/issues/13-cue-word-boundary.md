# 13 cue 间隔断句引入词边界信息

Status: done
Type: research
Blocked by: —

## 范围

- 遗留（[票据 12](12-cue-gap-split-inside-word.md) Comments）：间隔断句改为只在跨 VAD 子段时成立后，建票样本（HF II w0 约 1969 s 的两字词，参考字幕 1968.89–1971.24 为真实拖长音）仍被切成两条：两字（1969.27、1970.77）都落在 VAD 子段之外，Pyannote 漏检了这段语音，`cues.py` 只凭字符时间与子段无法判定它是词内间隙。
- 方向：把 ASR 的 token 边界带进 `align.json`，`build_cues` 在同一 token 内不按间隔断句。`asr.json` 的 `asr_traces` 今天只有 token id（w0：whisper id；x0：id 加 `raw_asr`），没有 token 到字符偏移的映射，需要 worker 侧解码（涉及 `kototoki/workers/asr.py`、`asr_qwen.py`，票据 03／07 文件）与 `job.py` 透传（票据 06 文件），`ASR`／`ALIGN` 配方 hash 随之变化。
- 先做调研再定是否实现：① 两个引擎的 token 边界能否稳定映射到窗口文字的字符偏移（whisper 多字节 token、Qwen 的标点合并）；② 用四部整片的 `asr.json`＋`align.json` 离线统计，按"同一 token 内不断句"能再减少多少 ≤2 字条目、是否引入 >6 s 或重叠；③ 若收益只有个位数条目，记录结论后关闭，不实现。
- 不做：不引入分词器；不改 `max_gap_s` 初值；不改票据 12 的 VAD 子段规则。

## 完成标准

- 调研结论写入 Comments（含离线统计表）并在[日文 cue](../../../docs/architecture/modules/japanese-cues.md) 模块页登记；是否实现由用户裁定。
- 若实现：`tests/test_cues.py` 与 worker 测试覆盖 token 边界；四部整片离线重算的 cue 数、≤2 字、重叠、>6 s 写入 Comments；受影响的模块页与规格 §5.2 更新。

## 文件所有权

调研阶段只读。实现阶段：`kototoki/cues.py`、`kototoki/recipes.py` 的 `CUES` 节、`tests/test_cues.py`；`kototoki/workers/asr.py`、`asr_qwen.py`、`job.py` 的改动须先经用户同意。

## Comments

- 2026-10-15 建票，依据票据 12 Comments 与用户裁定（接受 VAD 子段规则，词边界另开票；票据 10 的 GPU 整片重跑暂不进行）。
- 2026-10-15 调研完成，**建议关闭、不实现**（待用户裁定）。方法：只读整片验收的 `asr.json`＋`align.json`（`.local/bilingual-fullfilm-08/out-{w0,x0}/.work/`），用 `tokenizers` 直接加载两个模型目录的 `tokenizer.json`，把 `asr_traces[].tokens` 按 GPT-2 字节表还原为字节串、整窗解码后对回窗口文字，再把"token 字节边界落在多字节字符内"的相邻 token 并成一组，得到每个字符所属的 token 组；然后在现有 `build_cues` 之外，把"同一 token 组内两个词汇字符之间的间隔"作为额外包含区间喂给 `_within_one_span`，等价于"同一 token 内不按间隔断句"，其余规则与默认 `[cues]` 不变。脚本 `.local/bilingual-fullfilm-08/accept/token_boundary_study.py`（Git 忽略）。
  - ① 映射可行且稳定：w0 取 `tokens` 中小于 eot（50257）的 id，解码字节串与窗口 `text` 逐窗全等；x0 去掉 `<|im_end|>` 等特殊 token 后解码再 `strip()`（与 transformers `processing_qwen3_asr` 的 `parsed` 解析一致），同样全等。四部整片 772 个窗口零不匹配。跨多字节字符的 token（必须并组）：w0 587／8662 与 741／9946 个，x0 195／7484 与 247／8343 个。x0 把标点并进词的 token 组 39／11 个、w0 69／101 个，标点是非词汇字符，不影响切点。
  - ② 收益个位数，且方向不稳。Whisper 对日文的 token 接近单字粒度（HF II：10369 字分 8075 组，平均 1.28 字／组；Qwen 11070 字 7289 组，1.52 字／组）。**建票样本不会合并**：1969 s 窗口里 `先輩` 是 `先`(10108)＋`輩`(12290+102) 两个 token，`さくら` 也是三个单字 token。离线重算（默认 `[cues]`，基线数与票据 12 一致）：

    | 整片 | 间隔断句数 | 其中同 token 内 | cue 数 | ≤2 字 | >6 s | 重叠 |
    | --- | --- | --- | --- | --- | --- | --- |
    | w0／II | 795 | 10 | 1048→1045 | 110→106 | 2→3 | 0→0 |
    | w0／III | 975 | 8 | 1181→1184 | 118→117 | 6→7 | 0→0 |
    | x0／II | 320 | 7 | 1150→1146 | 114→109 | 0→0 | 0→0 |
    | x0／III | 328 | 8 | 1257→1252 | 90→88 | 1→1 | 0→0 |

    同 token 内的间隔多在 1–14 s（如 `でも` 208.25→215.51 s、`うん戻って` 3456→3469 s），都跨过 VAD 非语音区，是 CTC 把一个 token 的两个字对到了不同语句，不是拖长音；合并它们反而生成两条新的 >6 s cue，w0／III 的 cue 数还因后续硬切而增加。
  - ③ 结论：四部合计 ≤2 字条目只减 12（432→420），不能修复建票样本，还引入 >6 s 条目；不值得为此改两个 ASR worker 产物、`job.py` 透传与 `ASR`／`ALIGN`／`CUES` 三个配方 hash。建票样本的根因仍是 Pyannote 漏检约 2.4 s 拖长音，属 VAD 召回问题，不在 cue 层解决。
- 2026-10-15 用户裁定：采纳建议，不实现，结票。建票样本的根因归 VAD 召回（Pyannote 漏检拖长音），暂不另开票。
- 2026-10-16 调研方法、数据表与结论已落到 `docs/research/2026-10-15-cue-token-boundary-study.md` 并登记调研索引；本票据不进 Git，正文以该文件为准。
