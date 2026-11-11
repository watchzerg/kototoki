# 08 两部整片运行与文档同步

Status: done
Type: task
Blocked by: 03, 04, 05, 06, 07, 09

## 范围

- 用 Heaven's Feel II／III 原视频（或已分离音频）各一部，整批运行 w0 全流程；再以 x0 跑一次。记录各阶段墙钟、显存峰值（复用 `experiments/translation_monitor.py` 采样）、失败清单、降级次数、磁盘占用。
- 文档收口（各票据已随交付更新：01 的 AGENTS 重任务清单与 workflow、06 的不变量与入口、03 的模块页；本票只核对并补齐）：`docs/architecture/INDEX.md` 模块地图与装配入口、`module-boundaries.md`、README 使用方式、`AGENTS.md` 触发表、`GLOSSARY.md` 新术语（必含票据 09 的产品翻译配方 `b10-joint-degrade-v1`：字段同 `b10-joint`，仅批次终态失败按 10→5→1 降级、单条保留日文，另算 hash）、`technology-stack.md`。规格状态改 implemented，ADR-0007 状态注明已实现。
- 按[目标架构](../../../docs/architecture/bilingual-pipeline-architecture.md)开头的吸收规则收口：依赖图与不变量并入架构总览，责任归属与依赖方向并入模块边界，然后删除该页；更新 `docs/INDEX.md`、`AGENTS.md` 触发表与 `CODING_STANDARDS.md` 中指向它的条目（改指架构总览与模块边界），各模块页的"变更与决策来源"记录吸收位置。
- 验收记录写 `docs/research/acceptance/2026-MM-DD-bilingual-pipeline-fullfilm.md` 并登记调研索引。

## 完成标准

- 两部电影三份 SRT 齐全；验收记录与文档同步完成；`PYTHONUTF8=1` 下 `just docs-check` 对新文档无报错。

## Comments

- 2026-10-13 建票，依据规格 §12。
- 2026-10-14 按两轮评审修订（规格 §13）。
- 2026-10-14 第三轮评审：AGENTS／不变量更新移到 01／06 随交付完成，本票只收口。
- 2026-10-14 票据 09 移交：用户裁定产品配方名 `b10-joint-degrade-v1` 的 GLOSSARY 登记留到本票，已写入范围的文档收口条目；票据 09 的整片真实运行（记录降级次数）也尚未执行，可与本票整片运行合并核对。
- 2026-10-14 实施（直接在 main 上开发，按用户指示）。Blocked by 核对：00、02–07 done，01 resolved；09 为 claimed，但其代码已交付、唯一遗留的整片运行由用户移交本票，按已满足处理。
  - 整片运行（用户确认后执行）：Heaven's Feel II／III 的 `.mkv` 硬链接到 `.local/bilingual-fullfilm-08/input/`，w0、x0 各一份最小配置、分开输出目录，会话临时目录的驱动脚本用 `ResourceMonitor` 0.5 s 采样。STT 三阶段零失败（w0 约 9.4 分钟，x0 约 16.4 分钟）；首轮翻译四个文件全部失败——桌面程序占约 1236 MiB，空闲 14742 MiB 低于 `MIN_FREE_MIB = 14900`，等满 3×120 s。用户裁定临时下调阈值：包装脚本只在本进程把 `wait_for_free_vram` 默认阈值改为 14700，仓库代码未改；重跑同一配置，STT 按身份全部跳过，翻译四个文件 468 批一次成功，降级 0、回退 0，12 份 SRT 齐全并通过一致性核对。结果写入 `docs/research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md` 并登记调研索引。票据 09 的"一部电影真实运行记录降级次数"随之完成（降级 0）。
  - 文档收口：目标架构页的分层图与产品不变量并入架构总览（另加产品入口到装配表、改写开头与按任务阅读行），四条硬规则、八条责任边界与接缝裁定并入模块边界，删除该页；`docs/INDEX.md`、`AGENTS.md` 触发表、`CODING_STANDARDS.md`、规格 §7.3 与各模块页的链接改指模块边界，六个产品模块页的"变更与决策来源"记录吸收位置；模块页的"未验证"按整片结果更新。GLOSSARY 新增"双语字幕流水线"一节（含 `b10-joint-degrade-v1`、STT 引擎 w0／x0、日文 cue、整窗 fallback、回退 cue、产物身份、发布）；README 加使用方式，`AGENTS.md` 开头与 README 开头不再写"后端迁移尚未开始"；`technology-stack.md` 加 ffmpeg（libsoxr）与产品翻译配方；规格状态改 implemented，ADR-0007 注明已实现，调研时间线加一条。
  - 自动检查：`just test` 312 个通过，`just check` 通过；`PYTHONUTF8=1 just docs-check` 仍失败，但 46 行报错与改动前完全相同（冻结的 Codex AGENTS 归档与越出仓库的链接），新增与改动的文档无报错。待填标记只剩 `docs/development/workflow.md` 的"有发布流程时"，时机未到，保留。
  - 遗留与待决：① 空闲显存阈值 14900 MiB 在本机桌面占用 0.6–1.2 GB 漂移时会让翻译整批失败，是否改阈值、改为启动后实测或保持并要求先释放显存，待用户决定（本次只做进程内临时下调）；② 真实数据未触发降级；③ GPU 阶段中途中断、worker 崩溃重启、强杀与无语音视频未在真实环境验证；④ 质量与基线回归按规格 §11 推迟；⑤ 整片产物（约 5.6 GB）留在 `.local/bilingual-fullfilm-08/`，是否保留待用户决定。
- 2026-10-15 用户裁定：`MIN_FREE_MIB` 由 14900 下调到 14700（改票据 05 拥有的 `kototoki/translate/server.py`，经用户同意），翻译子系统模块页同步；整片产物只删提取的音频（`audio.flac`、`audio-16k.wav`，共约 5.4 GB），其余保留；规格追踪器 `spec.md` 改 done。
