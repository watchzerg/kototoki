# 01 输入核实、A0 守卫信号与归因、B0 空子段与删除项定位

Status: resolved
Type: research
Stage: A0、B0（离线；HF III 缺产物时 ≤1 GPU run）
Blocked by: —

权威：研究文档 §2.2、§4.1 A0、§4.2 B0。

## 范围

- 核实 HF II 对照产物身份（`asr.json` 的 recipe hash 等于当前 `kototoki.recipes.W0` 的 hash；`align.json` 官方 CER 等于 16.81%）。HF III 缺产品形状产物时，用产品 worker（`jobs-*.json` → `kototoki.workers.vad`／`asr`／`align`）重算，CER 须与 13.77% 逐项相同，否则停下写 §8。
- A0：逐窗压缩比、触顶、`avg_logprob`；逐窗对参考 CER（复用 `asr_source.units` 的时间对齐法）；按 Whisper 默认阈值与 2–3 个邻近阈值报告被标记窗口数、字符数、CER 分布对比。
- B0：逐子段落字数；空子段（≥0.5 s 且 0 字）数量与覆盖的参考字符数；对照删除项按"窗口外／空子段／有字子段内部"三类定位。
- 新包 `experiments/asr_robustness_v14/` 的离线测试（合成 `asr.json`／`vad.json`／`align.json`）。

## 完成标准

- `.local/asr-robustness-v14/01/` 下有 A0、B0 的 JSON 报告与复算脚本命令；研究文档 §7 一行；B0 是否满足 §4.2 进 B1 的条件写明。

## 执行记录

- 2026-11-09：新包 `experiments/asr_robustness_v14/`（`common`、`workers`、`inputs`、`signals`、`gaps`，`__main__` 子命令 `verify-hf-ii`／`reproduce-hf-iii`／`signals`／`gaps`），离线测试 `test_offline.py` 19 项（`.venv` 与 legacy 3.12 都通过），接入 `just experiments-test`。
- HF III 在 `.local/` 下确无当前配方的产品形状产物（v5 第 12 步目录只有 `asr.json` 的 `chunks` 副本与硬链接 WAV）；按 §2.2 用产品 worker 重算（GPU run 1）。
- 实现细节（理由）：触顶判定取 `len(tokens)+len(prompt) >= 447`（CT2 的 `max_length` 448 是解码器总长度、`sequences_ids` 不含 EOT）；逐窗 CER 把窗口当 cue 与参考按时间重叠连成单元（`asr_source.overlap_units`），单元 CER 归到其中每个窗口；置空收益按"只去掉该窗文字后单元编辑距离的变化"估；空子段的参考覆盖主口径按重叠时长比例分摊 cue 字符（`proportional`），另给整条 cue 计入的上界；删除项定位用 `kototoki_eval.alignment.align` 复算官方对齐，被删字符按所在 cue 内位置线性内插时间。

## Answer

**输入核实**：HF II 对照 `asr.json` 的 recipe hash 等于当前 `recipes.W0`（`127397b5…`），PCM `ee4e2da3…`，官方 CER 16.8073%（S 876／D 676／I 260）与基线逐项相同；`ja.srt` 可由 `align.json` 按默认 `[cues]` 规则逐字节复现（1099 条）。HF III 重算：VAD 207 窗（与 v5 第 12 步复制的窗口逐个相等）、ASR 0 失败窗、对齐 679 个 `text_only` unit，官方 CER 13.7673%（S 777／D 444／I 342）与基线逐项相同，cue 1219 条；墙钟 vad 35.5 s／asr 190.0 s／align 74.2 s，整卡显存峰值 2064／5360／8606 MiB。产物 `.local/asr-robustness-v14/01/hf-iii/fb2e0da74018/`。

**A0**（`signals-{film}.json`、`windows-{film}.json`）：两部都**没有触顶窗口**（token 最多 105／106，上限 444）。压缩比最大 II 1.99、III 3.83（只有 III 第 51 窗 >2.4：29.7 s、92 token、64 字对参考 11 字，典型重复循环）；`avg_logprob` 最低 II −1.36、III −1.18。阈值表（被标记窗口数／字符数／置空后单元编辑量变化，负为好）：doc-default II 0／0／0，III 1／64／−44；whisper-or（压缩比 >2.4 或 avg_logprob <−1.0）II 1／2／−2，III 2／68／−45；cr1.8-alp0.8 II 2／59／+46，III 4／81／−54；alp0.7 II 1／2／−2，III 5／29／−18；alp0.5 II 7／69／+4，III 9／92／+2。heavy 窗（单元 CER >0.25）II 37 窗 1018 字、III 29 窗 634 字，其 avg_logprob 均值 −0.30／−0.43（light −0.14），压缩比均值 1.08（light 1.29）：heavy 窗多是 21–30 s 长窗只出 2–30 字的**漏转**，不是重复，三种信号都分不开。02 的 A1 取 whisper-or（唯一两部估计都为负的规则）与 doc-default、cr1.8-alp0.8 对照。

**B0**（`gaps-{film}.json`、`segments-{film}.json`）：子段 II 1384 个／2066 s、III 1495 个／2314 s。空子段（≥0.5 s 且 0 字）II 57 个／48.2 s／36 窗、III 47 个／39.3 s／34 窗，其中 ≥1 s 只有 8＋8 个。空子段覆盖的参考字符（按重叠比例）II 72.5、III 37.4，合计 109.9；整条 cue 计入的上界 216＋111。对照删除项定位：II 676＝窗口外 219（32.4%）、窗内子段间隙 108（16.0%）、空子段 43（6.4%）、有字子段内部 306（45.3%）；III 444＝57（12.8%）／88（19.8%）／28（6.3%）／271（61.0%），两部都与官方 D 相等。**进 B1 的条件不满足**：109.9／1120＝9.8% <15%（直接落在空子段的删除只有 71 个＝6.3%）；即使按整条 cue 计入的上界也只有 29%，而 ≥1 s 的可补子段仅 16 个、覆盖参考 26 字，远不够过 0.3 pp（约 66 处）的门。03 wontfix。时间口径核对：字符中点落在窗内子段之间的"间隙字"II 172／III 265（1.7%／2.4%），无时间字 18／37，子段秒坐标与 unit 时间一致。GPU run 1／6。
