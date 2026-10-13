# 测试设计与验收

编写、修改、移动或 review 测试，以及制定测试计划、执行 `implement-spec` 时按本文执行。命令、runner、目录与资源边界以[开发工作流](../development/workflow.md)为准。

## 分层

- **core**：无外部依赖、秒级完成、可在任意 worktree 并行运行；单 ticket 阶段的完整门禁只跑这一层。
- **full**：需要真实服务、独占资源或显著运行成本；随 ticket 编写并接入标准入口，ticket 阶段只经 `just test-full` 定向运行（入口是否带主机锁以[开发工作流](../development/workflow.md)为准），无筛选的完整 full 验证留到最终集成。

本项目的 core 是离线、不用 GPU 的 `unittest`（合成 fixture 或 fake backend）；full 是真实模型推理，没有自动化入口，每次须用户批准，独占 GPU 并以 `.local/gpu.lock` 串行。目录、recipe 与资源细节见[开发工作流](../development/workflow.md#测试分层与资源边界)，验证边界见 [validation](../testing/validation.md)。

## 编写与变更

1. 新增或移动测试前确定 core 或 full 归属，在测试计划中注明验证行为、标准入口和资源需求。
2. 核心业务规则优先通过公开接口的单元测试验证；集成与端到端覆盖关键边界和代表性主流程。需要真实接线证明的行为放 full，不为进入 core 而 mock 掉待验证边界。
3. 测试接入对应目录和 runner，确保标准入口自动发现，并纳入无筛选的完整门禁。
4. review 核对分类、收录、资源清理及证据范围。失败和零匹配不能作为通过；不得通过 skip、遗漏收录或弱化断言维持门禁通过。
5. Routine tests stay offline, GPU-free, and use small synthetic fixtures or fake backends.
   For inference changes run a real local smoke test if assets exist; otherwise state that
   real inference is unverified. Record model, device, settings, and sample characteristics
   for any quality/performance measurement.

## implement-spec 项目覆盖规则

1. 主 agent 派发前读取本节，将本节与分层合同的链接传给 implementer、merger 和后续修复 agent。
2. implementer 在自己的 worktree 内运行 core 范围的定向 red → green 验证；报告完成前在包含最新 integration branch 的代码上通过完整 core 门禁。本 ticket 的 full 测试可用 `just test-full` 定向运行观察 red → green（入口带主机锁时自动排队，等待不是失败）；不直接调用底层 runner 运行 full 测试。
3. 无筛选的完整 full 验证留到最终集成；报告列出已运行的命令和结果，以及尚未运行的 full 测试与入口，不把定向通过记作整体验收。
4. 所有 ticket 合并、code-review 修复完成后，主 agent 在最终 integration branch 运行无筛选的完整门禁。通过前不关闭 spec、不将 PR 标记为 ready。
