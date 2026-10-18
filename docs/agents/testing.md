# 测试设计与验收

编写、修改、移动或 review 测试，以及制定测试计划、执行 `implement-spec` 时按本文执行。命令、runner、目录与资源边界以[开发工作流](../development/workflow.md)为准。

## 分层

任何测试（core 与 full，含 `gate-full`）都**不加载模型权重、不推理、不占 GPU**，因此都不需要 `.local/gpu.lock`。

- **core**：轻量测试，在进程内或本解释器（`sys.executable`）子进程中运行；不碰网络与 socket、不调用外部二进制，可用临时文件；可在任意 worktree 并行运行，整套单机约半分钟。单 ticket 阶段的完整门禁只跑这一层。允许子进程是用户 2026-10-18 的裁定：伪 worker 子进程与导入边界测试（ADR-0007 第 8 条"编排器与 worker 壳不 import torch"）留在快门禁里，代价是 core 约 30 s 而不是几秒。
- **full**：离线集成测试，可调用项目内 ffmpeg 合成秒级素材、用 fake worker 子进程、起本地伪 HTTP server、用 mock；不调用真实模型。随 ticket 编写并接入标准入口 `just test-full`，可在 ticket 阶段定向运行，无筛选的完整 full 验证留到最终集成。
- **小模型例外**：体积很小、可在 CPU 运行的产品模型可以进 full，每个须用户单独批准，批准记录写在本节下方。CPU 测试走的是另一条设备路径（产品 VAD 设备固定为 `cuda:0`，ADR-0007），不能当作 GPU 路径的证据。当前唯一候选是产品 VAD 用的 pyannote segmentation-3.0（`pytorch_model.bin` 约 5.9 MB），尚未批准。
  - 已批准：无。

真实模型调用不称为测试，称为**真实模型验证**：入口 `just smoke`，持有 `.local/gpu.lock`，每次运行须用户批准，不属于任何 gate。

目录、recipe 与资源细节见[开发工作流](../development/workflow.md#测试分层与资源边界)，验证边界见 [validation](../testing/validation.md)。

## 编写与变更

1. 新增或移动测试前确定 core 或 full 归属，在测试计划中注明验证行为、标准入口和资源需求。
2. 核心业务规则优先通过公开接口的单元测试验证；集成与端到端覆盖关键边界和代表性主流程。需要真实模型证明的行为进真实模型验证（`just smoke`），不为进入测试而 mock 掉待验证边界。
3. 测试接入对应目录和 runner，确保标准入口自动发现，并纳入无筛选的完整门禁。
4. review 核对分类、收录、资源清理及证据范围。失败和零匹配不能作为通过；不得通过 skip、遗漏收录或弱化断言维持门禁通过。
5. Routine tests stay offline, GPU-free, and use small synthetic fixtures or fake backends.
   For inference changes ask the user to approve a real model validation (`just smoke`) if assets exist;
   otherwise state that real inference is unverified. Record model, device, settings, and sample characteristics
   for any quality/performance measurement.

## implement-spec 项目覆盖规则

1. 主 agent 派发前读取本节，将本节与分层合同的链接传给 implementer、merger 和后续修复 agent。
2. implementer 在自己的 worktree 内运行 core 范围的定向 red → green 验证；报告完成前在包含最新 integration branch 的代码上通过完整 core 门禁。本 ticket 的 full 测试可用 `just test-full` 定向运行观察 red → green（full 是离线集成测试，不占 GPU、不持锁）；不直接调用底层 runner 运行 full 测试。真实模型验证（`just smoke`）不属于 ticket 门禁，需要时由主 agent 向用户申请批准后运行。
3. 无筛选的完整 full 验证留到最终集成；报告列出已运行的命令和结果，以及尚未运行的 full 测试与入口，不把定向通过记作整体验收。
4. 所有 ticket 合并、code-review 修复完成后，主 agent 在最终 integration branch 运行无筛选的完整门禁。通过前不关闭 spec、不将 PR 标记为 ready。
