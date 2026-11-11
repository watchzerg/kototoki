# 12 cue 间隙切分把词切成两条

Status: done
Type: task
Blocked by: —

## 范围

- 现象（[最终验收](../../../docs/research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md) §2）：HF II w0 约 1969 s 处，一个两字词被切成相邻两条各一字、各 0.8 s 的 cue。`align.json` 里两个字符都是 `api` 时间，但 CTC 只给每字 20 ms 的发射点，两字相距 1.5 s（拖长音），`cues.py` 的 `sentence_break` 把字符间隙 > `max_gap_s`（1.0 s）当作句界。
- 原因归类：CTC 发射稀疏导致的字符间"假间隙"，不是真实停顿；仅看字符时间无法区分。
- 候选方案（实现时先验证，择一）：① 间隙切分只在间隙内含 VAD 非语音区时成立——`vad.json` 的 `chunks[].segments` 给出子段，间隙落在同一子段内则不切；`build_cues` 多一个输入（子段列表），仍是纯函数；② 字符时长按相邻字符外推填满间隙（当前边缘外推只用于无时间字符）。倾向 ①，因为它用的是已有产物且不改变时间回填语义。
- 不做：不引入分词器、不改 `max_gap_s` 初值。

## 完成标准

- `tests/test_cues.py`：同一 VAD 子段内 1.5 s 字符间隙不切、跨子段间隙照切、`max_gap_s` 其他行为不变。
- 离线用整片验收的 `align.json`＋`vad.json` 重算 w0／II 的 cue：1969 s 处合为一条，总 cue 数变化与 ≤2 字条目数写入 Comments；无新增重叠、无 >6 s 新增。
- `CUES` 配方 hash 变化（票据 02 的 `recipes.py` `CUES` 节，本票可改），模块页[日文 cue](../../../docs/architecture/modules/japanese-cues.md) 更新切分规则与接口；规格 §5.2 补一句。

## 文件所有权

`kototoki/cues.py`、`kototoki/recipes.py` 的 `CUES` 节、`tests/test_cues.py`；`kototoki/job.py` 中调用 `build_cues` 的一行（传入 VAD 子段，归票据 06 的文件，改动前需用户同意）。

## Comments

- 2026-10-15 建票，依据最终验收 §2 与用户裁定。
- 2026-10-15 完成（方案 ①，有保留）：`build_cues` 直接读 `align.json` 的 `chunks[].segments`，不需要 `job.py` 改动；间隔 > `max_gap_s` 且整个落在同一 VAD 子段内时不断句，子段相接、跨窗口、没有子段的窗口（以窗口边界代替）照切。`CUES` 配方 hash 变化。测试：跨子段切、同一子段内不切、相接子段不切、跨窗口切；原有依赖间隔断句的测试补了带空洞的子段。离线重算（整片验收 `align.json`）：cue 数 w0／II 1056→1048、w0／III 1188→1181、x0／II 1154→1150、x0／III 1263→1257；≤2 字 113→110、124→118、115→114、95→90；重叠、>6 s 不变。**建票样本未合并**：1969 s 处两字（1969.27 与 1970.77）都在 VAD 子段之外——参考字幕 1968.89–1971.24 是真实拖长音，Pyannote 漏检，本规则按设计不干预。合并它需要词边界（ASR token 边界进 `align.json`，涉及票据 06 的 `job.py` 与 worker 产物），超出本票"不引入分词器"的范围，是否另开票待用户裁定。文档：模块页切分规则与离线重算、规格 §5.2／§13。
- 2026-10-15 用户裁定：接受 VAD 子段规则，词边界方案另开 [13](13-cue-word-boundary.md)。
