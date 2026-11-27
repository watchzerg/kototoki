# 测试分层合同

本文是测试分层合同的权威正文：各层的目录、收录入口、独占资源与串行约束，以及精简测试后的保留范围。`/prune-tests` 按本页路径读写，不要改名或移动。测试编写规则在[测试设计与验收](../agents/testing.md)，命令与门禁在[开发工作流](workflow.md)。

## 分层与资源边界

分层标准（core 与 full 都不调用真实模型）见[测试设计与验收](../agents/testing.md#分层)；本节是目录、入口与资源合同。

- core：`tests/core/` 下的产品 `unittest` 测试，`mise run test`（定向用 `mise run uv:test -k …`）以 `discover -s tests/core -t .` 收录（`tests/__init__.py`、`tests/core/__init__.py` 须保留）；覆盖 `kototoki/` 全部模块，清单见各模块页"代码与验证入口"（[模块地图](../architecture/INDEX.md#模块地图)）。进程内或本解释器子进程：GPU 阶段由 `tests/fake_worker.py` 顶替、翻译用伪客户端、导入边界用 `sys.executable -c` 核对；不调外部二进制、不碰网络与 socket、不读真实视频、不加载模型。
- full：`tests/full/` 下的离线集成测试，`mise run test-full`（定向用 `mise run uv:test-full -k …`）以 `discover -s tests/full -t .` 收录；用系统 ffmpeg 合成秒级样本：`test_media_ffmpeg`（媒体提取）、`test_job_ffmpeg`（真实媒体＋fake worker＋假翻译 session）与 `test_procs_children`（子进程随父进程退出）。不加载模型、不占 GPU，不需 `.local/gpu.lock`；经 `scripts/with_lock.py` 持主机锁（默认 `~/.cache/gate-full.lock`，`flock`）串行，多 worktree 并行不互扰。
- 没有产品与研究实现的实时对照层：研究直接调用产品实现；core 里需要钉住的取值以字面量钉，注释写来源（ADR 或归档 tag 路径）；`tests/core/test_boundaries.py` 以 AST 扫描要求 `kototoki/` 不导入 `research`，`tests/core` 自身不导入 `research`（[ADR-0031](../adr/0031-research-layout-and-lightweight-records.md)、[ADR-0025](../adr/0025-product-package-boundaries.md)）。`gate-full` = `gate-core` + `test-full`。
- `fake_worker.py` 留在 `tests/` 根，供两层共用。`mise run check` 编译 `kototoki`、`scripts` 与 `tests`。
- 真实模型验证（不是测试）：入口是 `mise run smoke`（`scripts/smoke/`），运行规则见[开发工作流](workflow.md#命令与门禁)。
- 独占资源：GPU，由 `.local/gpu.lock` 标记运行中的作业；同一时间一个作业；不抢占与核实真实进程的规则见 [AGENTS.md](../../AGENTS.md#重任务与环境)。产品只起 Strata（建表与翻译共用一个 session），固定占用 127.0.0.1:8080，且同一时间只允许一个 Strata launch；llama-server 默认也用 8080，不能与 Strata 同时运行。运行产物写入 `.local/` 下的新目录，拒绝覆盖。

## 保留范围

2026-11-22 第一次用 `/prune-tests` 精简：core 764 → 206 个测试（约 37 s → 8 s），full 21 → 5 个（约 6 s → 1 s），`gate-full` 约 43 s → 10 s。

- **core 聚焦的核心规则**（每条一两个代表性用例，经公开接口）：
  - 阶段计划：按产物身份逐级推进与失效重来、手改 `ja.srt` 回到 cues、专名表 high 条目进翻译身份、内嵌路径；产物契约：工作 id、最终路径、身份失效、原子写。
  - 编排：阶段 × 整批、文件级失败隔离与 worker 重启、无语音、续跑只补缺失阶段、GPU 锁冲突退出码 4、扫描与已有字幕跳过、内嵌字幕开关与回退、转写／译文不进日志、编排器不导入推理库。
  - worker 协议与壳：失败隔离与退出码、`classify_launch`、`failed_windows`、CUDA 损坏、模型核对、`ProcessLock`。
  - 算法：VAD 切窗、W0 整窗守卫、cross 裁判、对齐映射、日文 cue 切分、双语合并、`dp10-cut` 切包与按条解决、专名建表与过滤、媒体选轨与下混映射、内嵌字幕清洗、配置校验。
  - Strata session：接入检查与拒绝、显存等待、整批一个 session、不可用判定。
  - 少量钉子：翻译 `RECIPE_HASH`、专名 `BUILD_RECIPE_HASH` 与系统提示 sha256、`plan.py` 模型 SHA256 == `assets.toml`；`kototoki/` 与 `tests/core` 不导入 `research`。
- **full 覆盖**：行为规格"运行一批""发布"（真实 ffmpeg 合成视频到源文件旁的双语字幕）与"内嵌日文字幕"（subrip 轨替代 STT）；真实接线合同：延迟音轨补静音使样本 0 对齐视频 0、满幅 5.1 下混不削波、父进程被杀后 worker 子进程随之退出。
- **full 未覆盖的主路径**："切分规则""专名表可人工校对""续跑"只有 core 用替身验证。
- **不再维护的测试类别**：边界值与异常输入、故障注入与罕见失败（Strata 启停细节、锁残留、跨卷发布、中断回收等）、日志措辞与格式、命令行参数与字节快照、大多数配方 hash 钉值、研究实现等价钉值、开发工具脚本（`scripts/assets.py`、`scripts/upgrade.py`、`scripts/subtitles.py` 的边界、smoke runner）的测试。各模块失去的覆盖记在其模块页"代码与验证入口"。

产品行为合同不随测试删减而改变，完整门禁通过仅证明上述保留范围。
