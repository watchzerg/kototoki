# kototoki

以 Python 和本地 AI 模型为主的自托管 Speech-to-Text 项目：音频与转写留在本机，ASR 与强制对齐只在本地 GPU 上推理，日语转写保留日语。第一个产品形态是[双语字幕流水线](#双语字幕流水线)；W0／X0 两条 STT 基线与字幕翻译基线来自仓库内的研究与 demo，见[研究与基线](#研究与基线)。验证目标是原生 Windows（pwsh、RTX 5080），macOS 未验证。

## 双语字幕流水线

从一批日语视频或音频批量生产中日双语 SRT（写在源文件旁），全部在本机 GPU 上运行（[技术设计](docs/specs/bilingual-subtitle-pipeline.md)、[ADR-0007](docs/adr/0007-bilingual-subtitle-pipeline-architecture.md)）。

1. 环境：`just install`（`uv sync --locked` 建根环境即产品环境，统一 CUDA 12.8；再按资产清单 `assets.toml` 把 ffmpeg 与官方 llama.cpp 装到 `.local/tools/<name>/<version>/`）；模型放在 `.local/models/`（专名建表用的 Qwen3.8-27B-UD-IQ3_S，12.0 GB，位于 `glossary-v1/`），缺失时 `just fetch-models` 按清单下载（几十 GB）；翻译用的 Strata（0.2.12／build 0.1.58，装在 `%LOCALAPPDATA%\Strata`，模型 `qwen3.8-flash-next-iq3_s` 在 Strata 自己的数据目录）不在清单里，由你自己安装与维护，产品启动翻译时会核对版本与启动配置，不符即拒绝；`just verify-assets` 离线核对。两者都联网、改环境，先问再跑。ffmpeg 只用默认 swr 重采样，不要求 libsoxr，路径可在配置里改。全部模型与二进制的来源、版本与 SHA256 以 [`assets.toml`](assets.toml) 为准，布局与升级步骤见[依赖布局与资产清单](docs/development/dependencies.md)。
2. 配置：复制 `kototoki.toml.example` 为 `kototoki.toml`，至少填 `paths.input_dir`（递归扫描视频与音频，扩展名见 `[input] extensions`；不得位于仓库内，`.local/` 除外，因为字幕写在源文件旁）；中间产物在 `paths.work_dir`（默认仓库内 `.local/work/`；不得位于输入目录内，也不得位于仓库内 `.local/` 以外）；`stt.engine` 默认 `w0`，可选 `x0`。全部键与默认值见[配置、配方与媒体提取](docs/architecture/modules/config-and-media.md)。`[names]` 节（`model`、`port`、`seed`）控制专名建表：翻译前用 Qwen3.8 给每部影片建一张专名表，翻译时把表里高置信的译法注入提示；建表必开，没有开关。`[translate]` 只有 `seed`（正整数），翻译模型与端口由 Strata 管理。
3. 运行：`.venv/Scripts/python.exe -m kototoki kototoki.toml`（省略参数时读当前目录的 `kototoki.toml`）。这是加载全部模型的 GPU 重任务，运行期间持有 `.local/gpu.lock`。
4. 输出：每个输入在源文件所在目录得到 `<stem>.ja-zh.srt`（双语每条中文在上、日文在下），不再单独发布日文或中文 SRT；`ja.srt`、中间产物、日志与续跑状态在 `<work_dir>/<输入目录末段名>-<sha12>/`（模型缓存共用 `<work_dir>/cache/`）；运行日志 `run-<UTC 时间戳>.log` 在该目录下，与控制台内容相同，分 INFO／WARNING／ERROR 三级。源文件旁已有 `<stem>.ja-zh.srt`（不论来源）即跳过该文件；要重做就删掉这份字幕，中间产物按身份续跑，只重做受影响的阶段。中断或失败后重跑同一命令，从各文件的最后一个有效产物继续。同目录主名相同的两个输入（如 `ep01.mkv` 与 `ep01.mp3`）争用同一份字幕，后一个报错。退出码 0 全部成功、1 有文件失败、2 配置错误、3 同一输入目录已有进程在运行、4 GPU 锁冲突。
5. 专名表：每部影片的表在 `<work_dir>/<输入目录末段名>-<sha12>/<id>/name-table.json`（条目只在工作目录，日志只记计数）。翻译只注入 `confidence: high` 的实体（每个写法一行 `日文 → 中文`），没有发布时替换。表可人工校对：改 `name-table.json` 的 `entries` 后，**改到会被注入的条目（`high` 的实体或其写法）会改变该片的翻译身份，但已发布的字幕不会自动重做，须先删掉该片的 `.ja-zh.srt`，再重跑才重译（需要 Strata，约数分钟）；只改 medium／low 条目不触发任何重做**；改 `ja.srt`、`[names] seed` 或建表配方会重建表并覆盖手改。建表失败（提示超预算、两次回复都不合格）写空表、翻译照常进行（不注入）并记 WARNING。

翻译（Q2，[ADR-0019](docs/adr/0019-product-translation-q2.md)）由产品自动启停 Strata：建表的 llama-server 停掉后才启动，整批翻完或出错、被中断时停止；启动前 `strata launch --status` 必须为空（别人的 launch 在服务则拒绝，不替别人停），产品被强杀后若 Strata 残留，须手动 `strata launch --stop`。翻译失败按 10→5→1 拆批降级，单条仍失败保留日文并计入回退数（`translate/report.json`，发布日志与汇总也给出回退数）。行为与模块说明从[架构总览](docs/architecture/INDEX.md)进入（入口是[批次编排](docs/architecture/modules/batch-orchestration.md)）；验收见[两部整片验收](docs/research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)与[最终验收](docs/research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)（工程行为通过，早期 Hy-MT2 翻译；Q2 翻译与 Strata 自动启停尚未做真实运行；产品 STT 与 2026-10-05 基线的质量回归在重采样改回 swr 后尚未重测）。

## 开发

- 工具链：mise、uv、just；`just --list` 列出全部 recipe，命令、门禁与测试分层见[开发工作流](docs/development/workflow.md)。`just check` 做语法检查，`just test`、`just test-full` 跑离线的 core 与 full 测试（都不加载模型）；`just smoke`（真实模型验证）与各 demo 入口加载模型、独占 GPU，先问再跑。
- 所有模型、私有音频、完整转写、生成的字幕与运行日志存于 Git 忽略的 `.local/`。
- 文档从[文档索引](docs/INDEX.md)进入；agent 约束在 [AGENTS.md](AGENTS.md)。

## 研究与基线

产品直接使用已采纳的基线，不做多种可选配置。基线身份与采纳依据：

- **STT**：W0（faster-whisper＋新 Pyannote VAD＋MMS 日语 CTC）与 X0（Qwen-ASR＋新 Pyannote＋同一 MMS），均无降噪、无人声分离；定义见[当前基准线](docs/architecture/stt-candidate-pipelines.md)，采纳见 [ADR-0003](docs/adr/0003-new-pyannote-baselines.md)（旧 PyanNet、fixed30 与无 VAD cut-merge 为历史对照）。测试、benchmark 或对比基线先读[W0／X0 标准基线测试指南](docs/guides/baseline-testing.md)；demo 入口 [`experiments/w0_demo/`](experiments/w0_demo/README.md)、[`experiments/x0_demo/`](experiments/x0_demo/README.md) 与各自[契约](docs/specs/w0-reusable-demo.md)、[契约](docs/specs/x0-reusable-demo.md)。demo CLI 省略参数仍落到旧默认，运行最新基线须显式选择新 Pyannote。
- **字幕翻译**：基线为 Q3（[ADR-0021](docs/adr/0021-q3-strata-names-baseline.md)，2026-11-09），产品为 Q2（[ADR-0017](docs/adr/0017-q2-strata-default-launch-baseline.md)）。两者翻译规则相同：Strata 上的 Qwen3.8-Flash-Next IQ3_S、不加参数 `strata launch`（DFlash2）、`qwen-wide` 配方规则＋只注入 `confidence: high` 的专名表；只差建表：Q3 在同一 Strata 实例上用 Flash-Next 建（`names-strata-v4`，最多 5 次请求），产品仍用 27B＋llama-server。产品配方 `q2-degrade-v1`（[ADR-0019](docs/adr/0019-product-translation-q2.md)，另加 10→5→1 降级）。H0（Hy-MT2 30B-A3B APEX-I-Compact＋`dp10-cut`，[ADR-0005](docs/adr/0005-apex-i-compact-translation-baseline.md)、[ADR-0010](docs/adr/0010-dp10-cut-translation-flow-baseline.md)）不再是基线，只作研究侧历史对照（`just translation-srt`、[本地字幕翻译 demo](experiments/translation_demo/README.md)），产品已不再使用。
- **评估素材**：Heaven's Feel II／III 原版日文字幕为精确主参考，I 与 Black Panther 只作补充，见[评估素材](docs/testing/fatestay-reference.md)。

模型比较、流程探索（翻译 v1–v8）、验收与各轮结论按时点登记在[调研索引](docs/research/INDEX.md)及其[决定与探索时间线](docs/research/INDEX.md#决定与探索时间线)；历史报告中的 W0／W1／X0 指当时身份，分数不直接归给当前基线。
