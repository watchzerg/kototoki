# 13 结题报告

Status: resolved
Type: task
Blocked by: 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 14

## 范围

- 把研究文档状态改为 concluded；补齐 §6 进度表、§7 各步结论、成本汇总、未验证项与建议；在 `docs/research/INDEX.md` 的时间线与调研条目更新一句话结论。
- 被 06 裁定为 `wontfix` 的票据在 Blocked by 中视为已解除。
- 不自动替换基线；任何建议进产品的改动列为"待用户裁定"并说明需要的 ADR。

## 完成标准

- 文档检查通过（`uv run python scripts/check_docs.py` 对本轮文件无报错）；提交。

## 执行记录

- 2026-10-16 18:25 claimed（01–12、14 全部 resolved；Blocked by 已加 14）。
- 2026-10-16 研究文档：状态改 concluded；§6 补 13 行；§7 末尾加"结题"（一句话结论、方向表、成本汇总、未验证项、建议）；§8 共 8 项待裁定；09 的一致率表述按 04 的重复 seed 结果加保留。`docs/research/INDEX.md` 时间线与调研条目更新。`experiments/translation_v4/README.md` 补 v5 `glossary` 字段。
- 2026-10-16 检查：`.venv/Scripts/python.exe -X utf8 scripts/check_docs.py` 退出 1，44 条全是既有文件（archive／2026-10-03 等）的历史问题，本轮文件 0 条；未用 `uv run`（不触发根环境同步）。待填标记只剩 `docs/development/workflow.md:47`（时机"按需：有发布流程时"，未到），原样保留。quality_v5、translation_v3、translation_v4 离线测试全部通过。

## Answer

本轮结题，研究文档状态 concluded。结论：STT 是最大误差来源但没有可采纳的改动；翻译侧唯一确认的改进是 8 样本＋bge-m3 语义逐条 MBR（`mbr8s`，剧集确认集 Δ −0.036、约 −7%、p 0.0004，电影未确认，约 6.3 倍墙钟），未自动采纳，进产品与否及其余 7 项后续列在研究文档 §8。成本：GPU 约 9 小时，MQM 裁判 3197 包（约 $320），下载 9.5 GB。

## Comments

- 2026-10-16 建票。
