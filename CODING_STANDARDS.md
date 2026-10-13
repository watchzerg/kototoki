# 编码标准

code-review 按本文评审 diff。只写工具查不出的判断类标准；可机械判定的规则进 lint、typecheck 或测试，不在此重复。动手前的流程约束在 [AGENTS.md](AGENTS.md)，测试专项规则在 [docs/agents/testing.md](docs/agents/testing.md)。

## 通用

- 改动涉及用户可见失败、数据完整性、资源清理或凭据时，diff 必须包含对应处理，不留给调用方或下一次迭代。
- 同一规则只有一处实现，调用方消费而不复制。
- 新抽象必须比直接实现更简单；为未来需求预留的参数、hook 和层应删除。
- 命名使用 [GLOSSARY.md](GLOSSARY.md) 的术语，不引入术语表明确避免的同义词。
- 新增或移动的测试归属正确：core 不启动真实服务、不占固定端口或桌面；full 已放入所属 stack 的 full 层位置并被 `gate-full` 收录（位置见 [docs/development/workflow.md](docs/development/workflow.md#测试分层与资源边界)）。分层标准见 [docs/agents/testing.md](docs/agents/testing.md#分层)。

## 项目特定

随 retro 逐条追加；每条写清规则与判断依据。超过约 1000 行时拆到 `docs/` 并在此留导航指针。

- Keep audio loading/preprocessing, model inference, and output handling separate from
  CLI/API/UI; keep model-specific details behind a boundary testable without a model.
- Explicit data structures for shared transcription results.
- Model path, device, inference options configurable; fail with actionable errors on
  unsupported configs. No model load or download at import time. Model acquisition is
  separate from inference; after provisioning, inference must work offline.
- Validate inputs (missing/unreadable/empty/silent audio, unsupported formats) and clean up
  temp files on success and failure.
