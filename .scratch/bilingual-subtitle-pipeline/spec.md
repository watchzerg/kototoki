# 中日双语字幕批量生产流水线

Status: done（00–12、14–16；13 调研后裁定不实现）

权威规格：[docs/specs/bilingual-subtitle-pipeline.md](../../docs/specs/bilingual-subtitle-pipeline.md)；架构取舍：[docs/adr/0007-bilingual-subtitle-pipeline-architecture.md](../../docs/adr/0007-bilingual-subtitle-pipeline-architecture.md)。目标架构（模块接口、依赖方向、接缝与责任边界，实现票据必读）：[docs/architecture/bilingual-pipeline-architecture.md](../../docs/architecture/bilingual-pipeline-architecture.md)。本文件只列票据与依赖，不复制需求。2026-10-14 按三轮评审修订（规格 §13；第三轮裁定见规格 §1.2 第二张表）。

## 票据

| 编号 | 里程碑 | 标题 | Blocked by |
| --- | --- | --- | --- |
| 00 | M0 | 产物契约、worker 协议与 SRT 基础 | — |
| 01 | M1 | 产品项目与统一 CUDA 12.8 环境 | — |
| 02 | M2 | 配置、配方常量与媒体提取 | 00 |
| 03 | M2 | VAD／ASR(w0)／对齐三个 worker | 01, 02 |
| 04 | M2 | 日文 cue 切分与时间回填 | 00 |
| 05 | M3 | 翻译移植与双语合并 | 01, 02, 04 |
| 06 | M4 | 批次编排、续跑与失败隔离 | 00, 02 |
| 07 | M5 | x0 引擎 worker | 03 |
| 08 | M5 | 两部整片运行与文档同步 | 03, 04, 05, 06, 07, 09 |
| 09 | M3 | 翻译降级与报告 | 05 |
| 10 | 验收后 | 派生 WAV 重采样改回 swr | — |
| 11 | 验收后 | 视频时长误取 `DURATION-<lang>` 统计标签 | — |
| 12 | 验收后 | cue 间隙切分把词切成两条 | — |
| 13 | 验收后 | cue 间隔断句引入词边界信息（调研，裁定不实现） | — |
| 14 | 验收后 | 阶段计划模块：阶段链与期望身份收进一个归属 | — |
| 15 | 验收后 | 翻译子系统拥有自己的 run 键、续跑判定与"是否需要模型" | 14 |
| 16 | 验收后 | 产品翻译配方合并 dp10-cut 切包 | 09, 15 |

00、02、04、06 不依赖新环境，可用现有 `.local/` 产物与伪 worker 离线推进。2026-10-14 用户裁定：Python 环境整体 CUDA 12.8（torch 2.11.0+cu128）；下混按布局；默认 swr；stock llama.cpp；`b10-joint-degrade-v1`；第三轮评审的全部建议（`offset_s` 恒为 0、翻译 run 目录分键、发布覆盖规则、输出目录锁、按文件重启等）照单采纳。无待裁定项。

文件所有权（写入者互不重叠）：`kototoki/recipes.py` 归 02，其 `CUES` 节 04 可改（2026-10-14 用户裁定）；`kototoki/translate/recipes.py` 由 05 建、09 改，05 完成前 09 不动手；`justfile` 的 `check`／`test` 行归 00，其余归 01；`tests/__init__.py` 归 00。

每张票动手前读目标架构页中本票模块的接口行与"责任边界"全部八条；票据正文的"架构"段只列本票特有的形状约束，不重复页面。接口形状要偏离架构页时先改页、在票据 Comments 记录，再动手。

票据从 00 起编号（tracker 约定从 01 起），00 是评审后补的共享基础票，接受这一例外，不重排。
