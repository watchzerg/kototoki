---
covers:
  - kototoki/config.py
  - kototoki/recipes.py
  - kototoki/media.py
  - kototoki/embedded.py
---
# 配置、配方与媒体提取

状态：current；权威决定：[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0003](../../adr/0003-new-pyannote-baselines.md)、[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责双语字幕流水线（[行为规格](../../behaviors/bilingual-subtitle-pipeline.md)）的四件事：

- 读取 `kototoki.toml` 得到 `Config`（键、默认值与校验的参考见[配置参考](config-and-media/reference.md)）；
- STT／cue／媒体／内嵌字幕的配方常量与 `recipe_hash`；
- 从输入（视频或音频文件）选音轨、派生模型输入 WAV（不流复制原始音轨，ADR-0007「输入范围」）；
- 内嵌日文字幕的选轨、抽取与清洗（`kototoki/media.py`、`kototoki/embedded.py`）。

不负责：是否采用字幕轨、`ja.srt` 与 `ja-embedded.json` 的落盘与跳过判定（[批次编排](batch-orchestration.md)）；翻译配方（`kototoki/translate/recipes.py`）与建表配方（`kototoki/names/recipes.py`）；`probe.json` 等 JSON 产物的身份包装、写入与跳过判定（编排经[产物契约](artifact-contract/layout-and-identity.md)完成）；VAD／ASR／对齐推理（[STT worker](stt-workers.md)）。现行配方身份见[现行决定](../../adr/CURRENT.md)。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

### 子页

| 子页 | 何时读 |
| --- | --- |
| [配置读取与校验](config-and-media/config-loading.md) | 改 `Config` 的读取、路径解析或校验时 |
| [配方常量与 recipe_hash](config-and-media/recipes.md) | 改配方常量、`recipe_hash`、cross 配方、下混或 `MEDIA` 范围时 |
| [probe 与 extract](config-and-media/media-extract.md) | 改音轨选择、参照时长、采样率纠正、ffmpeg 提取命令或解码日志时 |
| [内嵌日文字幕](config-and-media/embedded-subtitles.md) | 改内嵌字幕的选轨、抽取命令或清洗规则时 |
| [配置参考](config-and-media/reference.md) | 查 `kototoki.toml` 的键、默认值、校验与进身份的键时 |

## 当前行为规格

行为规格按主题写在各子页，见上方子页表。

## 实现设计

媒体模块只写 ffmpeg 自身的输出文件（`audio-16k.wav`、`extract.log`；临时文件 `.<名>.<pid>.partial<ext>` 正常结束时自行删除，被强杀留下的残留由编排在下次提取前清理），不读写 JSON 产物、不判断跳过；`MediaError` 由编排记为该文件 extract 阶段失败；`Probe.warnings`／`Extract.warnings` 只作数据返回，本模块不发日志，由编排逐条写进运行日志（[批次编排：运行日志](batch-orchestration/runtime-rules.md#运行日志)）。时间轴零点只在本模块定义，下游阶段只传 `offset_s = 0`（[模块边界：产品包的责任边界](../module-boundaries.md#产品包的责任边界)）。

## 接口与依赖

`embedded` 是基础层之上的纯函数模块（与 `cues` 同级），只依赖 `srt`，由编排直接调用。`config`、`recipes` 属基础层，只依赖标准库与 `artifacts`；`media` 依赖二者与 ffmpeg／ffprobe 可执行文件（apt 系统包，默认从 PATH 查找，见[依赖布局与资产清单](../../development/dependencies.md#ffmpeg)），不依赖 torch 与网络，编排器在线程池里直接调用。

## 代码与验证入口

代码与验证入口写在各子页末尾：[配置读取与校验](config-and-media/config-loading.md#代码与验证入口)、[配方常量与 recipe_hash](config-and-media/recipes.md#代码与验证入口)、[probe 与 extract](config-and-media/media-extract.md#代码与验证入口)、[内嵌日文字幕](config-and-media/embedded-subtitles.md#代码与验证入口)、[配置参考](config-and-media/reference.md#代码与验证入口)。

## 变更与决策来源

- [ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0003](../../adr/0003-new-pyannote-baselines.md)、[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)、[现行决定](../../adr/CURRENT.md)
- [固定配方](../../behaviors/bilingual-subtitle-pipeline/fixed-recipes.md)、[阶段分解](../collaborations/stage-chain-and-scheduling.md#阶段分解)
- 归档 tag `archive/2026-11-18-pre-research-restructure` 中：
  - 技术设计历史记录 docs/research/2026-11-11-bilingual-pipeline-spec-history.md（§1.2 裁定表、重采样器经过）
  - 计划 docs/plans/architecture-cleanup.md（§3 决定 2：`MEDIA` 补入布局映射与音轨选择规则）
  - 模块页拆出的历史记录 docs/research/acceptance/2026-11-11-module-page-history-orchestration-config.md（真实视频核对与削波实测）
  - 常量来源 experiments/corpus/prepare_round2.py（下混与重采样）、experiments/w0_demo/（vad_candidates.py、asr.py、alignment.py）、experiments/x0_demo/asr.py、experiments/qwen/run_qwen.py
- 验收：[两部整片](../../research/acceptance/bilingual-pipeline-fullfilm-2026-10-14.md)、[最终验收](../../research/acceptance/bilingual-pipeline-final-acceptance-2026-10-15.md)、[swr 回归](../../research/acceptance/bilingual-pipeline-swr-regression-2026-10-16.md)、[cross 产品路径](../../research/acceptance/cross-asr-acceptance-2026-10-19.md)、[ffmpeg 9.0 升级](../../research/acceptance/ffmpeg-9.0-upgrade-2026-10-19.md)
- 票据：归档 tag 中的 .scratch/bilingual-subtitle-pipeline/issues/02-config-and-media.md、`10-resampler-swr.md`、`11-duration-tag.md`；.scratch/cross-asr-judge/；.scratch/name-consistency-product/issues/05-config-assets-plan.md；.scratch/architecture-cleanup/；.scratch/batch-run-fixes/（02：`MEDIA` v2）
