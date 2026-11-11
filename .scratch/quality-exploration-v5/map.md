# 地图

## 接跑手册（每次启动从这里开始）

1. 读 [研究文档](../../docs/research/2026-10-16-quality-exploration-v5.md) 第 6 节进度表，找到第一张未 resolved 且 Blocked by 已全部 resolved 的票据；读它的 `## 执行记录`。
2. 只读核对 GPU：PowerShell `Get-Process | ? ProcessName -match 'llama|python'`、`nvidia-smi`，读 `.local/gpu.lock`。锁被存活 PID 持有时不要启动新作业、不要杀进程。
3. 翻译 run 与裁判状态用 `uv run --locked --offline python -X utf8 -m experiments.translation_v4 status`（v4 根目录）或本轮脚本的 status 命令；**以文件输出为准，不以文字状态为准**。
4. 裁判（`claude -p`）退出码 75 表示配额耗尽：不要循环重试，先做离线票据（03、04、统计、写记录），没有可做的就停下。
5. 每完成一张票据：票据写 Answer 并 resolved → 本文 Decisions-so-far 加一行 → 研究文档第 6、7 节更新 → 提交 Git。

## Notes

- 2026-10-16 立项。顺序与理由见研究文档 §1；已知不重复的事实见 §2；判定纪律见 §3；记录协议见 §4。
- 第 1 步同时关闭最终验收挂着的"swr 回归未重测"项，其验收记录写 `docs/research/acceptance/`。
- 第 2 步的测量设计有提示（研究文档 §5），HF 两部没有中文参考，需要新建成对偏好 profile 并先校准。
- 无人值守：第 6 步按研究文档 §3 的投向规则自动排序，两侧顺序都做；第 5 步可选不阻塞；第 8、12 步的下载按 §3 预授权条件自行执行；所有需要用户裁定的事项集中到研究文档 §8，不中途停下。
- 重任务授权范围以用户启动提示词为准；根环境的 `uv sync|add|lock` 不做，新依赖进独立 `.local/envs/`。
- 唯一不可消除的停顿：Claude 配额耗尽（退出码 75）。

## Decisions-so-far

- 2026-10-16 [01](issues/01-product-rerun-swr.md)：swr 产品整片回到基线（w0 逐项相同，x0 差 ≤0.15 pp），后续用 `.local/quality-exploration-v5/01/out-{w0,x0}/`。
- 2026-10-16 [04](issues/04-consistency-metric.md)：一致性指标可用（精确率样本外 24／24，参考 ≈0.01、对照 0.04–0.055），分辨率粗（A/A SE 0.009–0.015）；07 护栏阈值 Δ > +0.02，10 可作主终点；产品整片不一致率 0.09–0.28，远高于干净源。
- 2026-10-16 [03](issues/03-readability-stats.md)：CPS 与人工字幕相当（>9 CPS 1.3–2.4%），不需约束；行长 >16 字 11–13%（排版问题）、26–28% 的 cue 卡在 0.8 s 下限，待 05 观感佐证，若改归 cue 规则。
- 2026-10-16 [05](issues/05-human-spot-check.md)：抽样表 `.local/quality-exploration-v5/05/sheet.md` 已生成（141 条），待用户可选填写；填了由后续会话汇总进研究文档 §7。
- 2026-10-16 [02](issues/02-asr-vs-reference-source.md)：ASR 带来的中文错误占比 r_all 0.76（CI90 0.70–0.82），r_text 0.68；校准通过；STT 侧收益上限远大于翻译侧（翻译侧约 1%）。
- 2026-10-16 [06](issues/06-decide-direction.md)：r_all 0.76（保守 r_text 0.68）≥ 40%，先 STT 侧 11 → 12，后翻译侧 07 → 10；07、10 的 Blocked by 加 12。
- 2026-10-16 [11](issues/11-vad-recall.md)：VAD 召回 6 组 × 2 部无一组两部都优于当前，不改默认；漏检确为 VAD 未检出，但补回的短窗被 Whisper 幻觉与语气声抵消（删除降、插入涨得更多）；瓶颈转向 ASR（12）。
- 2026-10-16 [12](issues/12-asr-candidates-round2.md)：无新日语开放权重 ASR；anime-whisper（29.4／25.4%）与 Qwen3 动漫微调（21.7／20.3%，33 窗生成循环）都不如 w0（16.8／13.8%），不换基线；许可不明的 efwkjn 系列只记录，归 §8。STT 侧结束，进入翻译侧 07。
- 2026-10-16 [07](issues/07-cheaper-mbr.md)：没有更省的变体稳定保留 mbr8c 收益（≤3 倍目标未达成）：mbr4c 无效应，mbr6c（4.68 倍）与早停 es3m70（2.95 倍）dev 显著但重复 seed 不复现（电影翻正）；并行槽位墙钟 −25%（质量未验证）；一致率无变化。08／09 的 N 取 8。
- 2026-10-16 [08](issues/08-semantic-utility.md)：bge-m3 语义效用在同一批 8 样本上优于 chrF（vs mbr8c Δ −0.014，dev p 0.026、重复 p 0.064；vs b10-joint −0.035／−0.038，p 0.003／0.001），两类都为负，一致率不变；`mbr8s` 列为确认候选，确认集等 09／10 筛选后统一建（Holm）。
- 2026-10-16 [09](issues/09-lowtemp-plus-mbr.md)：低温与逐条 MBR 不叠加：t03mbr8c vs b10-joint −0.021（p 0.058），与 t03、mbr8c 各自相同（差 ≤0.001），成本 6.4 倍；低温样本两两 chrF 0.85（默认 0.72），机制成立；不列确认候选。
- 2026-10-16 [10](issues/10-work-glossary.md)：按作品术语表让不一致率 0.041 → 0.002，但 MQM 准确性 +0.022（worse，非劣不成立），变差全部来自注入了术语的批（错位、模板残片、错条目带偏）；不采纳，后续思路记 §8。新增 [14](issues/14-confirm-mbr8s.md)：08 的 mbr8s 是唯一复现候选，按 §3 建剧集确认集确认；13 的 Blocked by 加 14。
- 2026-10-16 [14](issues/14-confirm-mbr8s.md)：mbr8s 在全新剧集确认集上确认：剧集 Δ −0.036（CI90 −0.052 到 −0.019，p 0.0004，Holm reject），安全门槛全过（`category_noninferior` 因电影为 None 字面不过，范围已在锁定文件预先写明）；电影未确认；成本 6.3 倍；进产品事项列 §8。
- 2026-10-16 [13](issues/13-final-report.md)：结题。研究文档 concluded；唯一确认改进 mbr8s（剧集 −7%，6.3 倍墙钟）待用户裁定；STT 侧无可采纳改动；§8 共 8 项。

## Fog

- 第 7 步起的确认集：已盘点（07）——电影被 v4 confirm 用尽，只能建剧集确认集（`confirm_set.py`，11 部各 2 集，2640 条；未运行）。
- 2026-10-16 用户裁定：放弃 mbr8s 与 mbr8c；今后不自动选用"翻译多次再挑选"的方法，除非用户明确要求（docs/adr/0008-no-multi-translation-selection.md）。
