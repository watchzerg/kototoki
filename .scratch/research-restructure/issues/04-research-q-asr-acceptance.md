# 04 Q 线、ASR 稳健性、专名、交叉合并与验收记录

Status: resolved
Type: task
Blocked by: 01

## 范围

做法与完成标准同 [02](02-research-stt.md)，目录为：

- `research/2026-10-cross-asr-judge/`：oracle、CTC 裁判、交叉打分、声学裁判调研 → ADR-0012。先看 `.scratch/cross-asr-judge/` 是否还有未完成票据，若有，在 `## Answer` 里报告，不替它结题。
- `research/2026-10-name-consistency/`：专名 1–6 轮 → ADR-0013、0014。
- `research/2026-10-q-line-v9-v11/`：v9 Q0、v10 广度探索、v11 Q1 → ADR-0015、0016。
- `research/2026-11-strata-v12-v13/`：v12 Q2（含 Strata 使用笔记）、v13 Q3 → ADR-0017、0018、0021、0022。
- `research/2026-11-asr-robustness-v14-v15/` → ADR-0023（v15 的待裁定项若仍有效，写进 `docs/pending-decisions.md` 的链接里由 05 处理，本票据只标出）。
- `research/acceptance/`：`docs/research/acceptance/` 中产品验收记录逐篇精简（一篇一文件，保留日期、对象、版本、测了什么、结果、结论；模板同 R2，标题可按验收调整）。`2026-11-11-module-page-history-*` 三篇不迁。

## 额外注意

- 现行翻译评估方法（`docs/agents/translation-evaluation.md`）引用 `experiments/scene_batching_v6/asr10.py`、`v9.py` 等脚本作为口径来源：在 v12–v13 README 中把这些口径（裁判身份、统计方法、人名错误口径）写成文字，05 再把方法文档改为引用文字而不是脚本路径。

## Answer

由子 agent（sonnet）撰写、主 agent 审阅（必填标题逐字通过 `check_docs.py`；轮次 54–72 行、验收 23–34 行；无哈希与盘符路径；主 agent 修正 v12–v13 中"Q3 身份见 ADR-0018"为对照规则 0018、身份 0021，并把原始材料补全为完整 tag 路径）。供 05 登记：

| 路径 | 时间 | 状态 | 一句话 |
| --- | --- | --- | --- |
| `2026-10-cross-asr-judge` | 2026-10-19 | concluded | Whisper 教师强制打分作裁判，单元范围 CER 16.16% → 14.31%（oracle 上限 11.90%）；作可选引擎 `cross` 进产品，默认仍 w0（ADR-0012） |
| `2026-10-name-consistency` | 2026-10-19 | concluded | 六轮离线验证，冻结配置 89% 行有益、2.5% 有害；研究线结题并进产品 `names` 阶段（ADR-0013／0014） |
| `2026-10-q-line-v9-v11` | 2026-10-21 – 10-23 | concluded | Q0（`qwen-wide`）accuracy 显著优于 H0、自然度较差；唯一留下的成分是 high 专名注入，形成 Q1（ADR-0015／0016） |
| `2026-11-strata-v12-v13` | 2026-11-08 – 11-09 | concluded | Strata Flash-Next 翻译显著优于 Q1 且快约 26–29%（Q2）；作建表模型未过 dev 剧集 wrong-referent 门，用户仍采纳为 Q3（ADR-0017／0021） |
| `2026-11-asr-robustness-v14-v15` | 2026-11-09 – 11-11 | concluded | 只有 `repeat-strict` 折叠守卫进产品（ADR-0023）；补窗重解码与表内专名替换被否决 |
| `acceptance/2026-10-14-bilingual-pipeline-fullfilm.md` | 2026-10-14 | 通过 | 两片 × w0／x0 产出 12 份 SRT，STT 失败 0、降级 0；显存阈值临时调到 14700 MiB 后翻译通过 |
| `acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md` | 2026-10-15 | 部分通过 | 失败路径全部通过；soxr 重采样拖累 VAD，CER 比基线高 0.5–3.5 pp |
| `acceptance/2026-10-16-bilingual-pipeline-swr-regression.md` | 2026-10-16 | 通过 | 改回 swr 后 w0 与基线逐条一致、x0 差 ≤0.15 pp；477 批 0 降级 |
| `acceptance/2026-10-19-cross-asr-acceptance.md` | 2026-10-19 | 差 0.05 pp 未达线 | `cross` 合并 CER 15.25% → 14.30%，用户仍采纳 |
| `acceptance/2026-10-19-cross-coresidency-probe.md` | 2026-10-19 | 通过 | Whisper 与 Qwen 可同进程共驻，峰值 10688 MiB |
| `acceptance/2026-10-19-ffmpeg-9.0-upgrade.md` | 2026-10-19 | 通过 | 新旧 ffmpeg 派生 WAV 的 PCM 逐字节一致，新构建设为默认 |
| `acceptance/2026-10-20-name-consistency-product.md` | 2026-10-20 | 通过 | ADR-0014 判据 1–3 满足；替换后来由 ADR-0019 移出产品 |
| `acceptance/2026-11-12-product-fullflow-acceptance.md` | 2026-11-12 | 通过 | 全流程退出码 0，296 批全部 `stop`；含 ADR-0026 复核与内嵌字幕选轨修复 |

- `.scratch/cross-asr-judge/`：01–08 全部 done，票据 08 写"文档部分 done；代码修复与提交由主 agent 处理"，spec 状态仍是过期的 `ready-for-agent`；本票据不替它结题，交 07 处理。其余相关 `.scratch` 目录（name-consistency、name-consistency-product、v9–v15 各轮）票据均已 resolved 或 wontfix。
- v15 待裁定项：无仍有效项（A 进产品、B 与 C3 已于 2026-11-11 否决）。
- 来源吸收：各轮报告与对应 ADR 全部吸收；8 篇验收一对一精简；`2026-11-11-module-page-history-*` 三篇按票据不迁；`timeline.md` 与 `topics/*` 只重复一句话摘要，交 05 处理。丢弃逐窗／逐条表、台账、哈希、本机路径、抽样文字与执行前清单（R3）。
- 评估口径（裁判 `claude-opus-5-5-mqm-v1` 与 `v5-asr-pairwise-v1`、按作品分层的窗口 bootstrap、人名错误两种口径）已在 v12–v13 README 的"测试"一节写成文字，05 据此改写 `docs/agents/translation-evaluation.md`。
