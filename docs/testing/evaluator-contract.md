# 离线评测器与结果契约

状态：已实现；合成测试已通过，真实模型与声学真值仍需独立验证  
最后更新：2026-10-05  
范围：`kototoki_eval` 的连续文字、内容时间、完整分母和输出结构；不定义正式晋级门槛。

关联：[时间优先评估方法](subtitle-timing-benchmark.md)、[质量与性能评估](stt-evaluation.md)、[demo 计划](../plans/local-stt-demo-selection.md)。

## 入口与隐私

在项目根目录执行：

```powershell
uv run --locked --offline python -m unittest discover -s tests -v
uv run --locked --offline python -m kototoki_eval '.local/references/dev-smoke.json' '.local/results/example/transcript.json' --output '.local/results/example/evaluation.json'
```

Python 接口是 `kototoki_eval.evaluate(reference, transcript)`。每次输入一个预先固定场景的完整文字，或整片完整文字；不要按预测时间截掉迟到文字。`micro_summary` 合并固定场景的 S/D/I，保留静音的插入。场景及跨边界归属由语料清单负责，评测器不自动为候选选择窗口。章节边界未核对、截断上下文、参考口述身份未核对等元数据随报告保留，不能将章节差异直接称为准确识别 CER。

文件报告包含字符映射及逐跨度信息，属于私有产物，应放到 Git 忽略目录。CLI 只在控制台显示分数及统计，不显示完整参考或候选文字。JSON 用字符串 `"infinity"` 表示联合指标中的非有限值；它是不可测或不完整，不是实际无限偏移。

CLI 强制输出位于当前项目的 `.local` 下，禁止覆盖输入与已有结果，使用新的运行身份保存重评结果；因此不能以输出参数修改 `D:/movie/` 素材。Python 接口只返回数据，调用者仍负责自身写入位置及证据保护。

## 后端输出

当前基线输入生产者为 [W0 demo](../../experiments/w0_demo/README.md)和[X0 demo](../../experiments/x0_demo/README.md)的 `result.json`。
按[标准基线测试指南](../guides/baseline-testing.md)运行对应demo；修改输出映射时更新对应实现，
保留完整 `text`、字符 units 和 `text_only`，再按本文契约评估。X0两种配方分别登记，历史runner结果保持旧身份。

```json
{
  "schema_version": 1,
  "text": "今日は元気",
  "source_start_seconds": 100,
  "duration_seconds": 4,
  "units": [
    {"char_start": 0, "char_end": 2, "start": 100, "end": 102,
     "granularity": "word", "time_source": "api", "status": "ok"},
    {"char_start": 2, "char_end": 5, "start": 102, "end": 104,
     "granularity": "word", "time_source": "api", "status": "ok"}
  ],
  "cues": [{"text": "今日は元気", "start": 100, "end": 104}]
}
```

`char_start/char_end` 是完整原文字中的半开区间，使用 Python Unicode 字符索引，不是字节、UTF-16 单元、规范化文字或后端数组编号。`text` 必须保留全部识别文字，包括无时间文字和重复。原生 word/character 单元可与外层 segment 同时存在；选择最细粒度，再选择较短跨度。

全部时间是恢复后的源媒体秒数。crop 结果不可只保存局部时间。可选 `source_end_seconds` 显式指定源区间终点；否则 `duration_seconds` 解释为从 `source_start_seconds` 起的时长，起点缺省 0。实际音频身份、处理阶段、采样率、设备、模型版本、缓存及耗时由运行 manifest 保存，评测器不会把这些执行证据推断为通过。

`granularity` 为 `word/character/segment`；`time_source` 为 `native/api/fallback/interpolated`；`status` 为 `ok/failed/text_only`。API 已修正的时间用 `api`，不能声称是 raw logits。标记 fallback/interpolated 的时间不进入原生内容时间成功分子；该排除是当前评测器的保守诊断规则，不等于正式产品要求。不可观察的上游回退率应在 manifest 记未知。

`from_segments` 辅助适配常见 `{text,start,end,words:[{word,start,end}]}` 数据。词文字只做严格单调原文查找；找不到保留 segment 和完整文字，记录 `word_text_not_found`，不猜测位置。

## 参考输入

```json
{
  "schema_version": 1,
  "reference_kind": "srt_display",
  "spans": [{"id": "cue-0042", "text": "今日は元気", "start": 100, "end": 104}]
}
```

人工声学参考使用 `human_acoustic`，可增加 `start_interval/end_interval`，各为包含冻结点估计的 `[lo,hi]`。两种参考独立报告，不能混合 P95。跨度 ID 必须唯一；参考文本拼接顺序是实际讲话顺序，不按候选 cue 匹配。排除口述以外的参考内容应预先写入派生参考及排除清单，评测器不自动删除标签或中文。

另支持真实生成的 `synthetic_digital_silence`：仅允许空 `spans`，要求 `expected_spoken_characters=0`、`silence_kind=digital_zero_no_room_noise`、明确非空 `provenance` 和正的 `duration_seconds`。这种参考只证明全零数字音频应没有文字，不是人工声学标签，也不证明室内噪声/弱语音能力。其时间 N=0、CER 未定义，候选全部文字仍计 I 和静音幻觉字符。扩展不改变 SRT/人工参考的 v2 计分语义，源码哈希需随新运行重新记录。

## 冻结的计分行为

- 全文 Unicode NFKC，去除 Unicode `P*` 标点类别和空白；保留数字、表记差异和符号。日语半角浊点、组合浊点保留原文字来源。遇到尚不支持的跨簇 NFKC 合成会报错；组合字符来源跨越固定参考跨度边界也显式报错，不能把两边静默计为空参考或自行合并。
- 精确 Levenshtein 编辑匹配；总代价固定为替换/删除/插入各 1。S/D/I 多个最优解时取 diagonal → deletion → insertion 的确定路径用于计数；CER 总数不变。自适应 band 的最优代价严格小于 band 时可证明与全文最优相同，否则扩大 band，不用近似锚点默默替代。
- 所有等价最优文字路径都参与匹配歧义判定。重复台词若无法靠前后文确定位置，记 `matching_ambiguity`；时间不参与匹配。上界仅包括存在完整最优文字路径、有效原生单元及可能达到对应时间门槛的未决项；确定漏字、无时间和全部远离目标的重复均不增加上界。
- 当前规则版本为 `nfkc-punctuation-v2-universal-complete-invariant-boundaries`。如果仅内部字符对应存在歧义，而**每条**最优路径都完整保留参考跨度、端点字符身份完全一致、每条路径有精确文字锚点、所有可能选中的原生单元有效且所有可达相邻映射保持时间顺序，则内容边界可测；保留 `character_mapping_ambiguous` 元数据和全部 CER 插入/替换。只存在一条有利路径不够，重复端点即使数值时间相同仍未决。
- 例如参考 `aba`、候选 `abba` 的最优路径可为 `(0,1,3)` 或 `(0,2,3)`，两者首尾字符身份不变，因此在原生时间均有效时可测同内容外部边界；插入仍记 I=1。反向 `abba/aba` 的所有最优路径都丢字，是确定内容不完整，不增加成功上界。它们验证计分定义，不是针对某个模型调整目标。v1 历史结果必须保留，v2 重评使用新文件身份，不能混合规则汇总。
- 首尾单元必须恰好提供对应文字边界。一个长 segment 可以测其完整跨度，不能测其内部短跨度；word 内部也不能按字符比例分配时间。没有时间标记 `text_only`；负数、非有限数、零/负时长、倒序、源区间越界标记 `invalid_time`。
- 部分删字保留局部预测边界；无独立部分参考边界时不伪造局部时间误差。删字不进入完整同步成功；整段替换没有任何相同字符锚点记 `text_mismatch`。精确字符覆盖与映射字符覆盖分开。
- `E=max(abs(ds),abs(de))`。nearest-rank P50/P90/P95/P99、端点有符号中位数、>0.5/2/5 秒数量与全体联合成功率一起报告。严格 `< t` 为成功；人工区间整个误差范围都小于阈值才确定成功，交叉门槛为未决。
- 有非零规范化文字的参考跨度构成时间分母，缺失及失败不删除。空白/非口述派生项单独计 `empty_reference`。纯静音场景 CER 为 `null`，幻觉字符仍进入全语料 I。
- 最终 cue 数量、时长、重叠、非法时间及文字是否保留独立报告。结构正确不证明声音同步；没有独立声音标注时跨静音显示、晚显示和闪烁只能列为未验证。

`map_time` 接受显式 piecewise 样本映射，分别记录处理和源采样率，直接恢复秒数，不累积舍入。VAD 拼接边界用 `boundary=start/end` 区分两侧。padding 若无真实源映射会报错，不借参考字幕补齐。每个正常推理阶段仍须自己记录和校验实际映射。

## 已验证与局限

合成 unittest 已覆盖 cue 合拆不变性、标点/NFKC、遗漏/重复/静音分母、整体 1 秒偏移、粗时间与 text-only、失败/插值、重复内容歧义上下界、人工区间、严格门槛、crop/重采样/padding/VAD 映射、源区间和独立完整矩阵编辑距离对照。它们证明计分行为，不证明 GPU 执行或声学质量。

当前没有人工盲审、专名/数字类别审查、独立声学静音事件标注、配对 bootstrap 或共同有效子集候选分析。静音事件/分钟缺少独立连续事件标注，不从文本长度推断。帧级音频变化和标签错误由上游语料及人工审查处理。条件分布的成功集合随候选变化；小样本、同场景相关性和单片泛化局限仍需在结论中说明。评测方法已版本化，但正式晋级规则尚未因此冻结。

长文本采用精确自适应 band，通常接近 `O(n × 编辑数)` 时间和 byte trace 空间；高错误率或大规模重复的最坏情况接近 `O(n × m)`。优先使用预先冻结场景做完整文字分数及语料汇总，并保留整片总分检查，不能按候选结果改场景以降低难度。
