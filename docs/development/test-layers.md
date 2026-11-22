# 测试分层合同

本文是测试分层合同的权威正文：各层的目录、收录入口、独占资源与串行约束，以及精简测试后的保留范围。`/prune-tests` 按本页路径读写，不要改名或移动。测试编写规则在[测试设计与验收](../agents/testing.md)，命令与门禁在[开发工作流](workflow.md)。

## 分层与资源边界

分层标准（core 与 full 都不调用真实模型）见[测试设计与验收](../agents/testing.md#分层)；本节是目录、入口与资源合同。

- core：`tests/core/` 下的产品 `unittest` 测试，`just test` 以 `discover -s tests/core -t .` 收录（`tests/__init__.py`、`tests/core/__init__.py` 须保留，模块以 `tests.core.*` 导入）；覆盖产品包 `kototoki/` 的全部模块，各模块的测试清单与覆盖行为见其模块页"代码与验证入口"（[架构总览的模块地图](../architecture/INDEX.md#模块地图)）。进程内或本解释器子进程：GPU 阶段由 `tests/fake_worker.py` 子进程顶替、翻译用伪 server 对象／伪客户端、导入边界用 `sys.executable -c` 子进程核对；不调用外部二进制、不碰网络与 socket、不读真实视频、不加载模型。
- full：`tests/full/` 下的离线集成测试，`just test-full` 以 `discover -s tests/full -t .` 收录；用系统 ffmpeg（`config.load` 默认从 PATH 查找）合成秒级小样本：`test_media_ffmpeg`（媒体提取）与 `test_job_ffmpeg`（端到端：真实媒体阶段、fake worker 顶替 GPU 阶段、假翻译 session，检查发布结果）。不加载模型、不占 GPU，因此不需要 `.local/gpu.lock`；经 `scripts/with_lock.py` 持主机级锁（默认 `~/.cache/gate-full.lock`，`flock`）串行，不同 worktree 同时跑不互相干扰。
- 没有产品与研究实现的实时对照层：研究直接调用产品实现；core 里需要钉住的取值以字面量钉，注释写来源（ADR 或归档 tag 路径）；`tests/core/test_boundaries.py` 以 AST 扫描要求 `kototoki/` 不导入 `research`，`tests/core` 自身不导入 `research`（[ADR-0031](../adr/0031-research-layout-and-lightweight-records.md)、[ADR-0025](../adr/0025-product-package-boundaries.md)）。`gate-full` = `gate-core` + `test-full`。
- `fake_worker.py` 留在 `tests/` 根，供两层共用。`just check` 编译 `kototoki`、`scripts` 与 `tests`。
- 真实模型验证（不是测试，不属于任何 gate）：入口是 `just smoke`（`scripts/smoke/`），每次运行都须用户批准。
- 独占资源：GPU，由 `.local/gpu.lock` 标记运行中的作业；同一时间一个作业，不抢占、不删除活跃锁，先用 `ps -p <pid>`／`pgrep` 核实真实进程。产品只起 Strata（建表与翻译共用一个 session），固定占用 127.0.0.1:8080，且同一时间只允许一个 Strata launch；llama-server 默认也用 8080，不能与 Strata 同时运行。运行产物写入 `.local/` 下的新目录，拒绝覆盖。

## 保留范围

<待填 按需：第一次用 `/prune-tests` 精简测试后记录：core 聚焦哪些核心规则；full 覆盖哪些 `docs/behaviors/` 主流程与必须真实接线才能证明的合同；明确不再维护的测试类别。产品行为合同不随测试删减而改变，完整门禁通过仅证明本节范围>
