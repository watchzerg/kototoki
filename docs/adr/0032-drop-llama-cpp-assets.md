# ADR-0032：资产清单去掉 llama.cpp 与 27B，`install` 并入环境同步

状态：已接受（2026-11-18，用户决定）、已实现（同日）。替代 [ADR-0022](0022-product-names-on-strata.md) 第 6 点中"保留 `assets.toml` 的 llama.cpp 工具与 `unsloth/Qwen3.8-27B-GGUF` 条目，`just install`／`fetch-models` 行为不改"。  
范围：`assets.toml`、`scripts/upgrade.py`、`justfile` 的安装入口与相关测试、文档。不改产品代码、配方、基线与产品行为。

## 背景

- 产品翻译与专名建表自 2026-11-09 起都在 Strata 上（ADR-0019、ADR-0022），产品不起 llama-server。
- ADR-0022 保留这两个条目，是给研究侧 Q0／Q1 与 H0 对照用；研究代码已随 [ADR-0031](0031-research-layout-and-lightweight-records.md) 删除，这两个条目没有使用者了。
- `just install` 仍每次下载 llama.cpp 与它的 CUDA 运行库（约 0.6 GB），`fetch-models` 仍下载 12 GB 的 27B 权重，`verify-assets` 对已清理的目录报缺失。
- `just setup`（`uv sync --locked`）与 `just install` 分成两个 recipe，但门禁与产品运行都离不开 ffmpeg，实际总是一起跑。

## 决定

1. **`assets.toml` 删除 `tools."llama.cpp"` 与 `models."qwen3.8-27b-ud-iq3_s"`**：清单只列产品用到的二进制（ffmpeg）与模型。
2. **`scripts/upgrade.py` 去掉 llama.cpp 组件**：只剩 `python` 与 `ffmpeg`。
3. **删掉 `just setup`，`just install` 自己执行 `uv sync --locked` 再安装清单里的工具**：环境入口只有一个。
4. 以后研究需要 llama.cpp 或 27B，由该轮在自己的目录里记录版本并自行准备，不进产品清单。

## 后果

- `just install` 只下载 ffmpeg；`fetch-models` 只下载产品用到的模型。
- 历史 ADR（0005、0007、0014、0015、0021）里关于 llama.cpp 与 27B 的描述是当时的事实，不改写。
- `tests/core/test_assets_manifest.py` 改为钉住清单里只有 ffmpeg 一个工具、没有 27B 条目。
