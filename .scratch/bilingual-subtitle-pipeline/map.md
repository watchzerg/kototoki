# 地图

## Notes

- 设计讨论于 2026-10-13 完成；2026-10-14 三轮评审合并修订（规格 §13），新增票据 00、09。
- 00／02／04／06 可离线开发；01 需联网与改环境，执行前向用户确认。
- 回归与容差本期不做；票据 03 的同窗对照只要求文字一致、时间 ±20 ms。
- 票据编号从 00 起，是 tracker 约定（从 01 起）的已接受例外。
- 2026-10-15 架构评审（`/improve-codebase-architecture`，范围 `kototoki/`，报告在系统临时目录、不进仓库）：两项 Strong 候选建为票据 14（阶段计划模块）与 15（翻译 run 键，Blocked by 14，run 目录命名方案由 agent 裁定为 A）；其余候选（发布归产物契约、Session 生命周期、进程代码移出 job、编排器声明式测试接缝、单一 WAV 读取器）未建票。

## Decisions-so-far

- 见 [docs/adr/0007-bilingual-subtitle-pipeline-architecture.md](../../docs/adr/0007-bilingual-subtitle-pipeline-architecture.md) 与规格 §1.2（含第三轮裁定表）。
- 2026-10-14：Python 环境整体 CUDA 12.8（torch 2.11.0+cu128），CT2 共用 torch DLL；派生 WAV 从容器解码；锁唯一归编排器；翻译按批次落盘；降级另立配方名；三份 SRT 一起发布。
- 2026-10-14（第三轮）：`offset_s` 恒为 0，零点由 `first_pts=0` 补齐；产物一律本地坐标；5.1 `pan` 常量；时长校验对视频流；翻译 run 目录按 `ja.srt` SHA 分键；发布按 `published.json` SHA 判定覆盖；`<output_dir>/.work/lock`；worker 按文件重启；x0 触顶窗口置空；`break_stale_lock` 改环境变量；删 `[vad] device`；产品测试放 `tests/`；翻译配方只在 `translate/recipes.py`。
- 2026-10-14 只读核实：本机 `vad-pyannote-gpu-v1`（torchaudio 2.11.0+cu128）存在 `forced_align`／`merge_tokens`；该环境 `import torchcodec.decoders` 成功且 site-packages 与 PATH 上都没有 `avcodec*.dll`，说明 torchcodec 在导入阶段不加载 FFmpeg（是否在推理时需要由 01 smoke #2 判定）。
- 2026-10-14（票据 01 完成，[01-environment.md](issues/01-environment.md)）：产品根环境 Python 3.13.16＋torch 2.11.0+cu128 已锁定并同步，torchcodec 0.17.0 取自 PyPI；CT2 在 sm_120 上依赖 PTX JIT，自带 cuDNN 9.10 调度器与 torch 9.19 并存（用户接受）；VAD 不需要 FFmpeg PATH；stock b11583 与兼容引擎 tokenize／生成／b10 结果一致，v3 `run_step` 假设成立，显存峰值 15.5–15.75 GB；MMS 分词器多出 `|` 须按模型类数过滤；experiments recipe 改用 legacy 解释器，`experiments/tests/` 只留评分器测试。
- 2026-10-14（票据 02 完成，[02-config-and-media.md](issues/02-config-and-media.md)）：swr 在 verbose 下只报告部分补偿，`extract` 另记 `net_padding_s`；派生 WAV 与 `hf-ii-full.wav` PCM SHA256 一致；`probe`／`extract` 多一个 `config` 参数（目标架构页已改）；时长校验按 §1.2（音频短于视频 >1 s 失败）。随后用户裁定重采样改 soxr 28 bit，派生 WAV 不再与 `hf-ii-full.wav` 逐字节一致。
- 2026-10-14（票据 04 完成，[04-japanese-cues.md](issues/04-japanese-cues.md)）：`build_cues` 纯函数落地；`max_gap_s` 初值 0.4 → 1.0；`FALLBACK_MAX_CHAR_S` 由 02 收编进 cue 配方 hash；`rules` 为 `[cues]` 同形映射。
- 2026-10-14（票据 03 完成，[03-stt-workers.md](issues/03-stt-workers.md)）：三个 STT worker 落地，冻结窗口门禁与旧 W0 结果全等（窗口、文字、token、unit 时间差 0）；共用守卫在新文件 `workers/gpu.py`；jobs `config` 约定 `models`／`model_cache`／`engine`；规格 §7.1 引擎选择与离线环境归属已对齐架构页。
- 2026-10-14（票据 07 离线完成，[07-x0-engine.md](issues/07-x0-engine.md)）：`asr_qwen` 适配器落地，触顶窗口置空并记 `failed_windows`；模型核对走壳的 `verify_models`，不移植 `checkpoint_identity`；x0 标点密度只改变断点位置、不改变 cue 长度，`[cues]` 初值不按引擎区分。同窗门禁：窗口 0 一个 token 与旧环境对照不同（BF16 近平局），其余全等，用户裁定接受为环境差异，票据完成。
- 2026-10-14（票据 08 完成，[08-fullfilm-and-docs.md](issues/08-fullfilm-and-docs.md)）：两部整片 × w0／x0 整批运行，12 份 SRT 齐全、STT 零失败、降级与回退 0；首轮翻译因桌面占显存低于 14900 MiB 阈值失败，经进程内临时阈值 14700 续跑成功（阈值去留待决）。目标架构页并入架构总览与模块边界后删除；规格 implemented。票据 09 随之完成。
- 2026-10-15（最终验收，[记录](../../docs/research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)）：工程行为全部通过；soxr 使 Pyannote 少保留约 10% 语音、CER 高于基线，用户裁定改回 swr（票据 10）；`DURATION-<lang>` 误判待修（票据 11）；cue 内切词待处理（票据 12）。00–09 保留为 done，不归档。
- 2026-10-15（票据 10／11／12 完成）：重采样改回默认 swr，派生 WAV 与基线 PCM SHA 一致，`MEDIA` hash 变化；`DURATION` 精确标签优先、与容器时长矛盾时取较小者并告警；间隔断句只在跨 VAD 子段时成立，`CUES` hash 变化，四部整片离线重算少 4–8 条 cue；建票样本（VAD 漏检的拖长音）未合并，需要词边界信息，用户裁定另开票据 13（先调研 token 边界映射与收益，再定是否实现）；票据 10 的 GPU 整片重跑暂不进行。
- 2026-10-15（票据 13 调研完成，[13-cue-word-boundary.md](issues/13-cue-word-boundary.md)）：ASR token→字符映射对 w0／x0 都稳定（四部整片 772 窗全等），但 Whisper 日文 token 接近单字（`先輩` 是两个 token），"同一 token 内不断句"四部整片只减 12 条 ≤2 字条目且新增两条 >6 s cue，建票样本不会合并；用户裁定不实现，票据关闭。
- 2026-10-15（票据 14 完成，[14-stage-plan-module.md](issues/14-stage-plan-module.md)）：阶段链、模型文件清单与各阶段期望身份收进 `kototoki/plan.py`（中间层，延迟导入翻译子系统取 `RECIPE_HASH`）；编排每文件 `next_stage` 一次、每个跑过的阶段 `advance` 一次；三个 worker 壳与伪 worker 都经 `plan` 取身份，身份字节不变（四个整片目录重算全等、新旧对拍一致）；用户授权由 agent 裁定架构细节。整片目录因票据 10 的 MEDIA 变化已不再命中 done。
- 2026-10-15（票据 15 完成，[15-translate-run-key.md](issues/15-translate-run-key.md)）：翻译 run 键、翻译身份与 `needs_model` 归翻译子系统 `translate.plan`；阶段计划模块反向调用，`translate_document(plan, session)`；GPU 锁与 `Session` 只在有文件 `needs_model` 时建立，删掉编排器读 `ja.srt` 的猜测；`artifacts.translate_run_dir` 与 `translate/data.py` 删除。run 目录命名由 agent 裁定维持方案 A（`<配方名>__s<seed>`，hash 不符拒绝并提示删目录），四个整片目录离线验证 `needs_model=False`，不需重翻。
- 2026-10-18（票据 16 完成，[16-translate-dp10-cut.md](issues/16-translate-dp10-cut.md)）：产品配方换成 `dp10-cut-degrade-v1`（[ADR-0011](../../docs/adr/0011-dp10-cut-product-recipe.md)），降级 10→5→1 不变；已交付影片的翻译身份过期、下次整批重译；`w0.toml` 两部真实运行记录在票据 Comments。

## Fog

- （无）
