# Demo 字幕显示契约

状态：最小统一 writer 已实现；仅完成合成测试，尚未建立字幕可读性或声学验收结论  
最后更新：2026-10-05  
范围：从既有规范化结果离线回放 SRT，并记录原生及统一字幕显示诊断；不执行识别、对齐或重新推理。

## 输入和冻结规则

当前W0／X0由各自标准demo生成完整 `text`／字符 `units`，`cues` 为空，未复刻旧WhisperX原生cue。
按[标准基线测试指南](../guides/baseline-testing.md)生成结果，再复用本writer；识别／对齐变化回到对应demo模块更新。

`experiments/display/replay.py` 读取 `{schema_version:1,text,units,cues}`。`text` 是完整原文；每个 unit 的 `char_start/char_end` 是 Python 原文字串的半开字符范围，`start/end` 是源媒体秒数。保留 `time_source`、原始 unit 及原生 `cues`；可选 `native_writer_cues` 也单独保存。API 修正时间、原生时间、fallback 和 interpolated 标签不互相替换。

规则 `minimal-display-v1-2026-10-04` 在查看候选输出之前确定：

- 按原文字符位置组合相邻有效 unit；句末符号 `.!?。！？` 后断开。
- 预测 unit 间的正间隔超过 0.4 秒时断开；合并后时长超过 7 秒或原文范围超过 42 字符时断开。
- 单个原生 unit 超过上述上限时完整保留，并记录超限；不擅自切割、截短或为内部文字虚构时间。
- unit 无时间、时间非有限/负值/非正时长、状态不是 `ok`、字符范围无效或相互重叠时，保留为不可渲染证据。有效但不足 1 ms、四舍五入后变成零时长的区间也不可写成合法 SRT。
- 原文中未计时的标点和空白可以附于相邻有效 cue，记录其关联，没有新增音节时间；没有时间的文字、数字等实词不能借此被补入。
- 时间不裁剪、不平移、不填静音。可指定源输入范围；超出范围的 unit 明确记为不可渲染，不能 clamp。原生时间重叠或倒序可完整保留为字幕诊断，不能据此声称时间结构通过。

writer 只组合原始时间单元，不按原参考字幕断句，不使用参考文本修正文字。改变原生 cue 合句/拆句但固定相同 unit 时，统一 SRT 应完全相同。原生与统一显示不同属于显示维度，不应影响识别 CER 或内容身份时间评分。

## 输出与完整记账

每次回放产生 `.srt` 与 `.display.json`。SRT 使用 UTF-8、源媒体时间和毫秒格式，采用最近毫秒、半值向上取整；sidecar 保留浮点原时间，因而不会隐藏取整差别。原文包含会破坏 SRT 结构的空行时，保留为不可渲染证据，不悄悄改写原文。

sidecar 完整保留原文、全部原始 unit、原生字幕、统一 cue 的原文范围和 unit ID、时间来源、未渲染范围和文本、失败原因、未计时标点/空白关联、输入 SHA256 和 writer 源码 SHA256。非有限原生数字以显式 `nonfinite_number` 记录，避免输出非法 JSON。SRT 为空也不能隐藏完整转写或缺时间问题。

诊断同时记录：完整字符分母、SRT 渲染字符数和覆盖率、原生/API 计时字符数、文字/数字字符覆盖；cue 时长列表、长 cue 和长文字计数、预测重叠与起点倒序；不可渲染项及未渲染范围。这些是预测结构和显示覆盖，不能证明文字正确、准确声学时间、真实内部静音或用户可读性。unit 时间间隔尤其不能自动成为实际声学静音指标。

此最小 writer 不做两行排版、语义断句、说话人分组或日语读速优化。42 字符和 7 秒是固定回放上限，用于有限诊断，不是已经实测采纳的产品保证。正式显示体验仍需[评估标准](subtitle-timing-benchmark.md)中的单独验证。

## 可复现入口

在仓库根目录运行，`INPUT.json` 替换为已有规范化结果的路径：

```powershell
uv run --locked python experiments/display/replay.py --input INPUT.json --output-prefix .local/display/run-id --source-start 10 --source-end 70
uv run --locked python -m unittest discover -s experiments/display -p 'test_*.py' -v
```

源范围参数可省略；省略代表没有验证输入上下界。writer 不从候选时间自行猜测范围。输出严格限制于本仓库 `.local/`，既有输出拒绝覆盖，需要使用新的回放身份。标准输出只打印路径、覆盖率和计数，不打印完整文字。

已在 uv 项目 Python 3.12.15、原生 Windows 上通过 10 项合成测试，覆盖固定 unit 下原生 cue 合拆不变性、完整文字记账、缺时间、非法/越界/零时长、不隐式修复、间隔及标点分组、超限原生单元、字符重复映射、原生时间重叠、空行；另实际执行 CLI，验证 SRT/sidecar 私有输出、源码身份及拒绝覆盖。真实候选的显示结果应由主执行阶段回放，分别报告其测量和未验证的声学/人工体验。
