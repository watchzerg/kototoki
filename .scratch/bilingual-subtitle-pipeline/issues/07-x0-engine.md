# 07 x0 引擎 worker

Status: done
Type: task
Blocked by: 03

## 范围

- 架构（[目标架构](../../../docs/architecture/bilingual-pipeline-architecture.md)"ASR 引擎"行）：`asr_qwen` 是 ASR 引擎接缝的第二个适配器，接口形状与 `asr_whisper` 相同（加载一次、按窗口转写、窗口级失败），`workers/asr.py` 只加按 `config.engine` 的选择分支，不改协议与产物结构。
- `kototoki/asr_qwen.py`：复制 `experiments/x0_demo/asr.py`（CUDA BF16、SDPA、greedy、4096、原生 processor）与 `experiments/qwen/run_qwen.py` 的资产身份常量、`checkpoint_identity`、`check_gpu`（复制，不导入历史包），适配 transformers 5.19；`engine = "x0"` 时 ASR worker 加载它，产物结构与 w0 相同。
- 触顶（4096）按窗口失败记账（规格 §6、协议 00）：该窗 `text` 置空，截断文字与原因记入 `failed_windows`，不进对齐、cue 与翻译；不让整部影片失败；窗口失败数进入汇总。现有 `x0_demo/pipeline.py::validate_asr` 拒绝 `token_limit_reached` 与 `QwenAsr.transcribe` 触顶即抛错的行为不移植。
- 观察 Qwen 输出的标点密度对 cue 切分的影响，记入 Comments。

## 完成标准

- 同窗对照标准同 03（文字一致、时间 ±20 ms）；离线测试覆盖触顶窗口置空与 `failed_windows` 记账。

## 文件所有权

`kototoki/asr_qwen.py`、对应测试。

## Comments

- 2026-10-13 建票，依据规格 §12。
- 2026-10-14 按两轮评审修订（规格 §13）。
- 2026-10-14 第三轮评审：触顶窗口置空并记 `failed_windows`。
- 2026-10-14 实施（分支 `feat/bilingual-07`，worktree `D:/AI_Projects/kototoki-07`，提交 cf8c7dc）：`kototoki/asr_qwen.py`（`QwenAsr`、`check_gpu`，参数取自 `recipes.X0`）；`workers/asr.py` 只加 `x0` 选择分支、`RECIPES["x0"]` 与 `X0_FILES`（Qwen checkpoint 7 个文件的 SHA256，取自 X0 基线 `model_files_sha256.asr`，本机文件已核对一致）。触顶窗口：适配器保留截断文字并返回 `(序号, "token_limit_reached: generated <n> tokens")`，壳经 `fail_window` 置空并移入 `failed_windows`，进度行计数；单窗 `RuntimeError` 同 w0。测试 `tests/test_asr_qwen.py`（伪 processor／模型，含经壳串到对齐与 `build_cues`）；`just test` 等价命令 248 项通过、`compileall` 通过。transformers 5.19 下用研究期 trace 的 token 解码，hf-ii-window-01 的 8 窗文字、原始输出、检测语言与 5.18 记录全等（只加载 processor，未加载模型）。
- 与旧 experiments 的差别（以规格／架构为准）：不移植 `checkpoint_identity`——目标架构"身份"条规定模型 SHA256 经产物契约缓存，由壳的 `verify_models` 完成，避免每次启动重复哈希 4 GB；`validate_asr` 拒绝触顶与 `transcribe` 触顶抛错不移植（规格 §6）；metadata 不写模型绝对路径；段多一个 `avg_logprob: null` 以保持与 w0 同结构；trace 的 token 字段改名 `tokens`（与 w0 一致）。
- 超出"文件所有权"的改动（属本票范围内的必要连带，03 已完成）：`workers/asr.py` 的选择分支（票据范围明文要求）；`tests/test_stt_workers.py` 中"x0 不可用"用例改为未知引擎 `x9`。新增 full 门禁 `tests/x0_frozen_window.py`（复用 `tests.stt_frozen_window` 的 `child_env`／`run_stage`／`compare`，对照 `.local/x0-demo/pyannote-gpu-v1-x0-pyannote-current-hf-ii-window-01/`），未接入 `scripts/smoke/run_all.py`（01 所有），未实跑。
- 标点密度观察（离线，现有研究期 X0／W0 `result.json`，hf-ii／hf-iii 冻结窗口中两引擎都有结果的 11 个，同 101 个 VAD 窗口，默认 `[cues]`）：x0 句末标点 7.7／100 词汇字符、逗号 2.5，w0 为 2.3、0.6；cue 626 对 591，平均 9.9 对 9.8 字、p90 均 18、触及 24 字上限 4 对 3，平均时长 1.84 s 对 1.99 s；以句末标点收尾的 cue 69% 对 20%（由末字符推断，`build_cues` 不记录切分原因）。结论：x0 标点改变断点位置、不改变条目长度，初值无需按引擎区分；未人工看观感。研究期 X0 在 hf-iii-window-03 上 ASR 子进程 RuntimeError 无结果，未纳入。已记入日文 cue 模块页。
- 遗留：同窗 GPU 门禁（文字逐字符一致、unit ±20 ms）未跑——对照的 ASR 来自 torch 2.14.1+cu130／transformers 5.18，产品环境为 torch 2.11.0+cu128／5.19，BF16 数值可能导致文字不一致，届时需用户裁定；真实触顶与窗口级 OOM 只有伪对象验证；整片 x0 归 08。
- 2026-10-14 用户批准：门禁接入 `just test-full`（改 01 的 `scripts/smoke/run_all.py`，`SMOKES`／`MODULES` 各加一项）并合并 main。首跑 ASR 启动失败：`device_map` 需要 accelerate，产品环境没有；改为加载后整体 `.to("cuda:0")`（不改环境）。之后连跑两次（`.local/smoke/20261014T082609Z/`、`20261014T082759Z/`，产物逐字节相同）：8 窗边界全等；7 窗文字与 token 全等，窗口 0 的 38 个 token 中第 2 个不同（一个汉字换成另一个汉字，字数不变）；587 个 unit 范围与状态全等，1080 个起止时间最大差 0；无触顶。按门禁规则文字不一致即不通过，判断为 BF16 近平局在 torch 2.11+cu128 与对照的 2.14.1+cu130 之间翻转，确定性可复现。**待用户裁定**：接受为环境差异，或以产品环境结果为新对照。
- 2026-10-14 用户裁定：窗口 0 的单 token 差异接受为环境差异，票据完成；模块页已同步并合并 main。
