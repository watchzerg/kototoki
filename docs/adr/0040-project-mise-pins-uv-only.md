# ADR-0040：项目 `mise.toml` 只钉 uv，不再钉 just

状态：已接受，2026-11-22（用户裁定），已实现。
替代关系：
- 取代 [ADR-0034](0034-ubuntu-only-platform.md)「工具链分层」第 1 点中"`mise.toml` 钉 just"的部分，以及第 4 点中"`check-toolchain` 核对 just"的部分。

范围：项目级 mise 版本锁定。

不改：uv 的锁定、Python 由 uv 按 `.python-version` 管理、依赖由 `uv.lock` 管理、外部前置。

## 决定

1. 用户的依赖分层：OS 管 ffmpeg 等系统工具与 mise；mise 管 uv、just、beads 等通用开发工具；uv 管 Python 版本与项目依赖。项目级 `mise.toml` 只锁对精确版本敏感的工具。
2. 本项目 `mise.toml` 只钉 uv：uv 版本影响 `uv.lock` 的格式、解析结果与 `--locked` 的行为。
3. just 对版本不敏感，不在项目钉，由用户的全局 mise 配置提供。
4. `just check-toolchain` 只核对 `mise.toml` 里列出的工具与 `.python-version`，脚本按文件内容遍历，无需改代码。

## 身份

不涉及任何配方身份。

## 依据

- just recipe 只用到稳定语法；精确钉版本只会让全局升级 just 后 `check-toolchain` 失败，没有收益。
