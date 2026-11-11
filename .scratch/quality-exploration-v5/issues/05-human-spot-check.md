# 05 人工观感抽查（可选，不阻塞）

Status: resolved
Type: research
Blocked by: 01

## 范围

- agent 部分（ready-for-agent）：从 01 的 w0 两部双语 SRT 各抽 3 段约 2 分钟（开头、中段对白密集处、结尾），生成抽样表 `.local/quality-exploration-v5/05/sheet.md`：每条给中文、日文参考、时间；留"看得懂／别扭／错"三选一与备注列。同时附上这些段落的裁判 MQM 结果（若 02 已有）或留空。做完即 `resolved`（Answer 写"抽样表已生成，待用户填写"），不阻塞任何票据。
- 用户部分：任何时候填表，可选。
- agent 收尾：后续会话发现表已填时，汇总观感分布，与裁判分数或 CER 桶对照，追加到研究文档 §7。

## 完成标准

- 抽样表生成即完成。用户填表后的汇总是追加项，不是本票完成条件。

## 文件所有权

`.local/quality-exploration-v5/05/`；研究文档。

## 执行记录

- 2026-10-16 claimed 并完成 agent 部分。`experiments/quality_v5/spot_check.py` 从 01 的 w0 两部生成 `.local/quality-exploration-v5/05/sheet.md`：每部开头（首条参考字幕起 2 分钟）、中段（中间三分之一里产品 cue 起点最密的 2 分钟）、结尾（末条参考字幕前 2 分钟），共 6 段 141 条；每条列显示时长、产品中文、产品 ASR 日文、同时段参考日文，留"看得懂／别扭／错"与备注两列。02 的裁判结果尚未产生，表内未附 MQM，汇总时再按时间对照。
  - 命令：`python -X utf8 -m experiments.quality_v5.spot_check --film "HF II（w0）" <ja> <zh> <hf-ii-full.json> --film "HF III（w0）" ... --out .local/quality-exploration-v5/05/sheet.md`
  - 段落：II 0:00:43–0:02:43、1:06:20–1:08:20、1:54:03–1:56:03；III 0:00:48–0:02:48、0:47:23–0:49:23、1:59:20–2:01:20。中段按 cue 密度选，覆盖 03 发现的 0.8 s 短 cue 密集处。

## Answer

抽样表已生成（`.local/quality-exploration-v5/05/sheet.md`，两部 × 3 段 × 约 2 分钟，141 条），待用户填写；不阻塞其他票据。用户填表后，下一个会话汇总观感分布，与 02 的裁判结果、03 的短 cue 统计对照，追加到研究文档 §7。

## Comments

- 2026-10-16 建票。2026-10-16 改为可选不阻塞（用户要求减少人工干预）。
