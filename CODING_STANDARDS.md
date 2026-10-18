# 编码标准

code-review 按本文评审 diff。只写工具查不出的判断类标准；可机械判定的规则进 lint、typecheck 或测试，不在此重复。动手前的流程约束在 [AGENTS.md](AGENTS.md)，测试专项规则在 [docs/agents/testing.md](docs/agents/testing.md)。

## 通用

- 改动涉及用户可见失败、数据完整性、资源清理或凭据时，diff 必须包含对应处理，不留给调用方或下一次迭代。
- 同一规则只有一处实现，调用方消费而不复制。
- 新抽象必须比直接实现更简单；为未来需求预留的参数、hook 和层应删除。
- 命名使用 [GLOSSARY.md](GLOSSARY.md) 的术语，不引入术语表明确避免的同义词。
- 新增或移动的测试归属正确：任何测试都不调用真实模型；core 不调用外部二进制、不碰网络与 socket；full 已放入 full 层位置并被 `gate-full` 收录（位置见 [docs/development/workflow.md](docs/development/workflow.md#测试分层与资源边界)）。分层标准见 [docs/agents/testing.md](docs/agents/testing.md#分层)。

## 项目特定

随 retro 逐条追加；每条写清规则与判断依据。超过约 1000 行时拆到 `docs/` 并在此留导航指针。

- Keep audio loading/preprocessing, model inference, and output handling separate from
  CLI/API/UI; keep model-specific details behind a boundary testable without a model.
- Explicit data structures for shared transcription results.
- 公开接口带类型标注。
- Model path, device, inference options configurable; fail with actionable errors on
  unsupported configs. No model load or download at import time. Model acquisition is
  separate from inference; after provisioning, inference must work offline.
- Validate inputs (missing/unreadable/empty/silent audio, unsupported formats) and clean up
  temp files on success and failure.
- 产品包 `kototoki/` 的模块接口以各模块页"接口与依赖"节为准，依赖方向、责任边界与接缝以[模块边界](docs/architecture/module-boundaries.md#产品包的责任边界)为准：接口变宽、纯函数模块（`cues`、`merge`）出现文件读写、推理模块出现产物读写或跳过判定、在只有一个适配器的位置新建接缝（后端协议类、媒体后端抽象），都要求 diff 先改模块页与模块边界并写明第二个使用者；责任边界（时间轴、跳过与替换、三级失败、发布、锁、身份、子进程环境、日志）各只允许出现在模块边界指定的模块。
- 日志：产品模块只经 `logging.getLogger(__name__)` 发事件，handler 与目的地只由编排配置；转写、cue／窗口文字、译文、提示词、grammar 与模型响应正文不进日志；告警用 WARNING 级别表达，不在消息里写 "WARNING"（细则见[批次编排：运行日志](docs/architecture/modules/batch-orchestration.md#运行日志)）。
