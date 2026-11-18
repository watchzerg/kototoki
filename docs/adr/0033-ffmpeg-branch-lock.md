# ADR-0033：ffmpeg 只锁维护分支，实际版本记在安装目录与运行日志

状态：已接受（2026-11-18，用户决定）、已实现（同日）。替代[依赖布局与资产清单](../development/dependencies.md)此前对 tools 的"清单锁版本、URL、压缩包与逐文件 SHA256"，以及 ffmpeg 升级"派生 WAV 全部相同才切换默认路径"的规则。  
范围：`assets.toml` 的 `[tools.ffmpeg]`、`scripts/assets.py`、`scripts/upgrade.py`、默认路径、运行日志首行与相关测试、文档。不改媒体提取逻辑、配方与基线。

## 背景

- 清单原先钉住 BtbN 构建 `n9.0.2-28-g669f5ab083`（tag `autobuild-2026-10-18-13-01`）。BtbN 约一个月后删除旧的带日期 release，2026-11-18 `just install` 下载它得到 HTTP 404；原始压缩包也不在本机，钉住的版本已无法重装。
- BtbN 不长期保留任何具体构建，钉死版本意味着每月都要手动升级才能装上。
- 用户的取舍：可复现性让位于能装上；但结果有变化时要能看出 ffmpeg 实际版本变了。

## 决定

1. **`assets.toml` 只锁维护分支**（`branch = "9.0"`），不写版本、URL 与 SHA256。`just install` 取 BtbN 最新带日期 autobuild 里该分支的 win64 gpl 构建；压缩包 SHA256 取自 GitHub asset digest，缺失即拒绝。
2. **安装目录按分支命名**：`.local/tools/ffmpeg/<branch>/`；分支内换构建时默认路径不变。实际版本、release tag、压缩包与逐文件 SHA256 写进该目录的 `identity.json`；`just verify-assets` 按它离线核对。已装的就是最新构建且文件一致时 `install` 不动，否则整目录替换。
3. **运行日志首行记实际版本**：`[run] start: … engine=<engine> ffmpeg=<ffmpeg -version 报的版本>`，取不到时为 `unavailable`。
4. **`just upgrade ffmpeg` 显式换分支**：把分支换到 BtbN 当前最高的维护分支，装好新分支、改清单与 `kototoki/config.py`、`kototoki.toml.example` 的默认路径。旧分支仍装着且 `--films` 下有 `.mkv` 时，对照两个分支派生的 WAV，结果只写进报告，不阻止切换。

## 后果

- 同一分支内 ffmpeg 构建会随 `just install` 变化，派生 WAV 不再保证跨时间逐字节可复现；对比运行结果时先看日志首行的 `ffmpeg=`。
- 续跑复用的派生 WAV 可能由更早的构建产出，日志首行只反映本次运行时的构建。
- 若 BtbN 不再提供锁定的分支，`install` 失败并提示运行 `just upgrade ffmpeg`。
- 2026-10-19 的验收记录与既有证据绑定在当时的 `n9.0.2-28-g669f5ab083` 上，不改写。
