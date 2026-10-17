# kototoki

以 Python 和本地 AI 模型为主的自托管 Speech-to-Text 项目：音频与转写留在本机，ASR 与强制对齐只在本地 GPU 上推理，日语转写保留日语。第一个产品形态是[双语字幕流水线](#双语字幕流水线)；W0／X0 两条 STT 基线与字幕翻译基线来自仓库内的研究与 demo，见[研究与基线](#研究与基线)。验证目标是原生 Windows（pwsh、RTX 5080），macOS 未验证。

## 双语字幕流水线

从一批日语视频批量生产日文、中文与中日双语 SRT，全部在本机 GPU 上运行（[技术设计](docs/specs/bilingual-subtitle-pipeline.md)、[ADR-0007](docs/adr/0007-bilingual-subtitle-pipeline-architecture.md)）。

1. 环境：`uv sync --locked`（根环境即产品环境，统一 CUDA 12.8）；模型放在 `.local/models/`，官方 llama.cpp 放在 `.local/tools/llama.cpp/b11583-cuda13.4/`；ffmpeg／ffprobe 默认在 `D:/bin/`（路径可在配置里改，只用默认 swr 重采样，不要求 libsoxr）。模型与引擎的来源与 SHA256 见[语料与模型资产准备](docs/architecture/modules/corpus-and-assets.md)与[本地翻译模型资产](docs/guides/local-translation-model-assets.md)。
2. 配置：复制 `kototoki.toml.example` 为 `kototoki.toml`，至少填 `paths.input_dir`（递归扫描视频）与 `paths.output_dir`（不得位于仓库内，`.local/` 除外，也不得位于输入目录内）；`stt.engine` 默认 `w0`，可选 `x0`。全部键与默认值见[配置、配方与媒体提取](docs/architecture/modules/config-and-media.md)。
3. 运行：`.venv/Scripts/python.exe -m kototoki kototoki.toml`（省略参数时读当前目录的 `kototoki.toml`）。这是加载全部模型的 GPU 重任务，运行期间持有 `.local/gpu.lock`。
4. 输出：每部视频在 `output_dir` 下按输入子目录镜像得到 `<stem>.ja.srt`、`<stem>.zh.srt`、`<stem>.ja-zh.srt`（双语每条中文在上、日文在下）；中间产物、日志与续跑状态在 `output_dir/.work/`。中断或失败后重跑同一命令，从各文件的最后一个有效产物继续；用户改动过的最终文件默认不覆盖，`[run] force = true` 才覆盖。退出码 0 全部成功、1 有文件失败、2 配置错误、3／4 输出目录锁／GPU 锁冲突。

翻译失败按 10→5→1 拆批降级，单条仍失败保留日文并计入回退数（`translate/report.json`）。行为与模块说明从[架构总览](docs/architecture/INDEX.md)进入（入口是[批次编排](docs/architecture/modules/batch-orchestration.md)）；验收见[两部整片验收](docs/research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)与[最终验收](docs/research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)（工程行为通过；产品 STT 与 2026-10-05 基线的质量回归在重采样改回 swr 后尚未重测）。

## 开发

- 工具链：mise、uv、just；`just --list` 列出全部 recipe，命令、门禁与测试分层见[开发工作流](docs/development/workflow.md)。`just check` 做语法检查，`just test` 跑离线 core 测试，`just test-full` 与各 demo 入口加载模型、独占 GPU，先问再跑。
- 所有模型、私有音频、完整转写、生成的字幕与运行日志存于 Git 忽略的 `.local/`。
- 文档从[文档索引](docs/INDEX.md)进入；agent 约束在 [AGENTS.md](AGENTS.md)。

## 研究与基线

产品直接使用已采纳的基线，不做多种可选配置。基线身份与采纳依据：

- **STT**：W0（faster-whisper＋新 Pyannote VAD＋MMS 日语 CTC）与 X0（Qwen-ASR＋新 Pyannote＋同一 MMS），均无降噪、无人声分离；定义见[当前基准线](docs/architecture/stt-candidate-pipelines.md)，采纳见 [ADR-0003](docs/adr/0003-new-pyannote-baselines.md)（旧 PyanNet、fixed30 与无 VAD cut-merge 为历史对照）。测试、benchmark 或对比基线先读[W0／X0 标准基线测试指南](docs/guides/baseline-testing.md)；demo 入口 [`experiments/w0_demo/`](experiments/w0_demo/README.md)、[`experiments/x0_demo/`](experiments/x0_demo/README.md) 与各自[契约](docs/specs/w0-reusable-demo.md)、[契约](docs/specs/x0-reusable-demo.md)。demo CLI 省略参数仍落到旧默认，运行最新基线须显式选择新 Pyannote。
- **字幕翻译**：Hy-MT2 30B-A3B APEX-I-Compact、采样 `official30b-cached-v1`（[ADR-0005](docs/adr/0005-apex-i-compact-translation-baseline.md)），完整 SRT 流程 `dp10-cut`（[ADR-0010](docs/adr/0010-dp10-cut-translation-flow-baseline.md)，`just translation-srt`；每包 ≤10 条、可见 ≤12 条，切点偏向停顿、不跨 ≥20 s，提示同 `b10-joint`）；产品配方仍为 `b10-joint-degrade-v1`（每批 10 条，只多降级）。demo 入口见[本地字幕翻译](experiments/translation_demo/README.md)。
- **评估素材**：Heaven's Feel II／III 原版日文字幕为精确主参考，I 与 Black Panther 只作补充，见[评估素材](docs/testing/fatestay-reference.md)。

模型比较、流程探索（翻译 v1–v4）、验收与各轮结论按时点登记在[调研索引](docs/research/INDEX.md)及其[决定与探索时间线](docs/research/INDEX.md#决定与探索时间线)；历史报告中的 W0／W1／X0 指当时身份，分数不直接归给当前基线。
