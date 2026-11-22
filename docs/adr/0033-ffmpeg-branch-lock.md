# ADR-0033：资产清单与安装，ffmpeg 只锁维护分支

状态：已接受。2026-11-18 按主题合并（用户授权）：并入 ADR-0032，原文见 git 历史（提交 807de3e 及之前）。 全文自 2026-11-20 起由 [ADR-0034](0034-ubuntu-only-platform.md) 替代。
范围：`assets.toml`、`scripts/assets.py`、`scripts/upgrade.py`、`justfile` 的安装入口、ffmpeg 默认路径、运行日志首行与相关测试、文档（见[依赖布局与资产清单](../development/dependencies.md)）。不改产品代码、媒体提取逻辑、配方与基线。

## 决定

### 资产清单与安装

1. `assets.toml` 只列产品用到的二进制（ffmpeg）与 STT 模型；不含 llama.cpp 工具与 Qwen3.8-27B 条目（产品翻译与建表都在 Strata 上，不起 llama-server）。
2. `scripts/upgrade.py` 只升 `python` 与 `ffmpeg`。
3. 没有单独的 `just setup`：`just install` 先 `uv sync --locked` 再安装清单里的工具，环境入口只有一个；`just install` 只下载 ffmpeg，`fetch-models` 只下载产品用到的模型。
4. 研究需要清单外的二进制或模型（如 llama.cpp、27B）时，由该轮在自己的目录里记录版本并自行准备，不进产品清单。

### ffmpeg 分支锁

1. **清单只锁维护分支**：`[tools.ffmpeg]` 写 `branch = "9.0"`，不写版本、URL 与 SHA256。`just install` 取 BtbN 最新带日期 autobuild 里该分支的 win64 gpl 构建；压缩包 SHA256 取自 GitHub asset digest，缺失即拒绝。
2. **安装目录按分支命名**：`.local/tools/ffmpeg/<branch>/`；分支内换构建时默认路径不变。实际版本、release tag、压缩包与逐文件 SHA256 写进该目录的 `identity.json`；`just verify-assets` 按它离线核对。已装的就是最新构建且文件一致时 `install` 不动，否则整目录替换。
3. **运行日志首行记实际版本**：`[run] start: … engine=<engine> ffmpeg=<ffmpeg -version 报的版本>`，取不到时为 `unavailable`。
4. **`just upgrade ffmpeg` 显式换分支**：把分支换到 BtbN 当前最高的维护分支，装好新分支、改清单与 `kototoki/config.py`、`kototoki.toml.example` 的默认路径。旧分支仍装着且 `--films` 下有 `.mkv` 时，对照两个分支派生的 WAV，结果只写进报告，不阻止切换。
5. 后果：同一分支内 ffmpeg 构建会随 `just install` 变化，派生 WAV 不再保证跨时间逐字节可复现，对比运行结果时先看日志首行的 `ffmpeg=`；续跑复用的派生 WAV 可能由更早的构建产出；若 BtbN 不再提供锁定的分支，`install` 失败并提示运行 `just upgrade ffmpeg`。

## 身份

- ffmpeg 分支 `9.0`（BtbN win64 gpl）；实际构建只记在 `identity.json` 与运行日志。
- 历史：曾钉住 BtbN 构建 `n9.0.2-28-g669f5ab083`（tag `autobuild-2026-10-18-13-01`）；2026-10-19 的验收记录与既有证据绑定在它上，不改写。已删除的清单条目：`tools."llama.cpp"`、`models."qwen3.8-27b-ud-iq3_s"`。

## 依据

- 产品翻译与专名建表自 2026-11-09 起都在 Strata 上；研究侧使用者（Q0／Q1 与 H0 对照）随研究代码在 [ADR-0031](0031-research-layout-and-lightweight-records.md) 中删除，llama.cpp 与 27B 条目没有使用者。`just install` 原先每次下载 llama.cpp 与 CUDA 运行库（约 0.6 GB），`fetch-models` 下载 12 GB 的 27B 权重，`verify-assets` 对已清理目录报缺失。
- 门禁与产品运行都离不开 ffmpeg，`setup` 与 `install` 实际总是一起跑。
- 钉住的 ffmpeg 构建约一个月后被 BtbN 删除（2026-11-18 `just install` 得 HTTP 404，原压缩包也不在本机），钉死版本意味着每月手动升级才能装上。用户取舍：可复现性让位于能装上，但 ffmpeg 实际版本变化要能看出来。
- `tests/core/test_assets_manifest.py` 钉住清单里只有 ffmpeg 一个工具、没有 27B 条目。

## 沿革

- 2026-10-19：产品默认 ffmpeg 换为 BtbN win64 gpl 9.0.2 维护分支构建 `n9.0.2-28-g669f5ab083`（验收记录见 docs/research/acceptance）。
- 2026-11-18 ADR-0032：资产清单去掉 llama.cpp 与 27B，`upgrade.py` 去掉 llama.cpp 组件，`setup` 并入 `install`。
- 2026-11-18 ADR-0033：钉住的构建被上游删除，ffmpeg 改为只锁维护分支，实际版本记入 `identity.json` 与运行日志。
- 2026-11-18：按主题合并为本页。
