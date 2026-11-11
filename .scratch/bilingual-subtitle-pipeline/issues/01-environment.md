# 01 产品项目与统一 CUDA 12.8 环境

Status: resolved
Type: task
Blocked by: —

## 范围

- 根 `pyproject.toml` 改为产品项目 `kototoki`（Python 3.13，`requires-python >=3.13,<3.14`，`.python-version` 与 `scripts/check_toolchain.py` 同步到 3.13），运行时依赖：torch 2.11.0、torchaudio 2.11.0、torchcodec 0.17.0（`[[tool.uv.index]] pytorch-cu128, explicit = true` + `[tool.uv.sources]`）、transformers 5.19.0、pyannote.audio 4.0.7、faster-whisper 1.2.1、ctranslate2 4.8.3、numpy；`tool.uv.environments` 限 `sys_platform == 'win32'`；测试工具放 dependency group。`uv lock` 后 `uv sync --locked`。参照本机 `vad-pyannote-gpu-v1`（torch 2.11.0+cu128＋torchcodec 0.17＋pyannote 4.0.7）与 `whisper-latest`（torch 2.8 cu128＋CT2 4.8.2）两个组合；注意后者的 `setup_runtime` 同时把 `.local/tools/whisper-runtime-provisional` 加进了 PATH，它只证明同版本 DLL 可共存。
- 决定历史 `experiments` 测试在新根环境的策略（原本因缺 NumPy／Torch 跳过的测试会实际运行，`alignment.py` 断言 torchaudio 2.8.0；冻结代码不改，记录哪些 recipe 保留在旧环境运行）。`tests/` 已于 b2fe9a6 迁到 `experiments/tests/`，产品 `tests/__init__.py` 与 `just check` 的 `kototoki` 行由 00 负责，本票不动。
- 下载官方 llama.cpp b11583 `llama-b11583-bin-win-cuda-13.4-x64.zip` + `cudart-llama-bin-win-cuda-13.4-x64.zip` 到 `.local/tools/llama.cpp/b11583-cuda13.4/`，记录 SHA256；按其日志格式适配 `identity.json` 要求。
- smoke 脚本入库 `scripts/smoke/`，接入 `just test-full`（每项打印版本、设备、耗时；**每项各自在独立子进程运行**，避免 PyAV 与 torchcodec 的 FFmpeg DLL 同进程相遇）：
  1. torchaudio `forced_align` CUDA，合成序列＋一个真实冻结窗口（2026-10-14 已在 `vad-pyannote-gpu-v1` 只读核实 2.11.0+cu128 存在 `forced_align`／`merge_tokens`，本项验证 CUDA 路径结果）。
  2. pyannote 4.0.7＋torchcodec 0.17 在产品环境导入，对内存波形推理 10 s；列出进程实际加载的模块，记录是否有任何 `avcodec*`／`avformat*` DLL 被加载。没有则 VAD worker 不需要 FFmpeg PATH，把结论回写规格 §7.1 与票据 03。
  3. **在不含 `whisper-runtime-provisional` 的干净 PATH 下**，同一进程先 `import torch` 再用 CT2 解码一窗；打印实际加载的 cudnn／cublas／cudart 模块路径（应全部来自 torch 目录）与 cuDNN 版本；记录是否 PTX JIT 与二次启动时间。
  4. llama-server（stock）加载 APEX GGUF；与兼容引擎比对 `/tokenize` 输出与固定 seed 短生成；再发同一 session 的第二个 `cache_prompt` 请求，断言 `timings.cache_n`、`tokens_evaluated`、`stop_type`／`stopped_limit`／`truncated` 与 v3 `generate.py::run_step` 的假设一致；确认 `--fit off`、`--cache-ram`、`-lv` 仍被接受；保存一份加载日志供 `residency_evidence` 回归；跑一个真实 b10 批次测显存峰值。
- 文档随本票同步（不推到 08）：`just test-full`／`gate-full` 从此加载模型，更新 AGENTS.md 重任务清单与 workflow.md 的 `test-full` 描述；ADR-0005 的"被部分替代"反向链接已加（2026-10-14），本票核对；`justfile translation-baseline` 与 translation-runtime 模块页的兼容引擎说明改为历史记录（不改历史 ADR 正文）。

## 完成标准

- `uv sync --locked` 成功；四项 smoke 通过并记录；`just check`、`just test` 结果记录。
- `docs/development/technology-stack.md`、`toolchain.md`、`workflow.md`、`AGENTS.md` 重任务清单更新为实际版本与新 recipe。

## 注意

- 联网与改环境：开始前向用户确认。不删除三个历史环境。`.local/gpu.lock` 规则照旧。

## 文件所有权

`pyproject.toml`、`uv.lock`、`.python-version`、`justfile`（除 00 拥有的 `check`／`test` 两行）、`scripts/`、`.local/tools/llama.cpp/`、`docs/development/`、`AGENTS.md` 重任务清单段。

## Comments

- 2026-10-13 建票，依据规格 §12。
- 2026-10-14 按两轮评审修订（规格 §13）。
- 2026-10-14 用户裁定整体 CUDA 12.8，取消 CT2 侧车。
- 2026-10-14 第三轮评审：标题改 CUDA 12.8；smoke 改干净 PATH、各自子进程、FFmpeg 加载观察、stock 引擎响应字段；AGENTS／workflow／ADR-0005 链接随本票；`tests/` 迁移已完成的说明。
- 2026-10-14 实施（分支 `feat/bilingual-01`，worktree `D:\AI_Projects\kototoki-01`，其 `.local` 为指向主 checkout 的 junction）：
  - 环境：Python 3.13.16；`uv lock`／`uv sync --locked` 成功，torch／torchaudio 2.11.0+cu128（`pytorch-cu128` 显式索引）、torchcodec 0.17.0、transformers 5.19.0、pyannote.audio 4.0.7、faster-whisper 1.2.1、ctranslate2 4.8.3、numpy 2.5.4。**偏离票据**：cu128 索引没有 torchcodec 0.17.0，改从 PyPI 取（与 `vad-pyannote-gpu-v1` 相同）。没有测试工具依赖（只用 unittest），未建空的 dependency group。
  - llama.cpp b11583：两个 x64 zip 的 SHA256 与 GitHub release digest 一致（llama `daca162d…d61d`、cudart `738f8c25…e668`），解压到 `.local/tools/llama.cpp/b11583-cuda13.4/`，`identity.json` 记录 upstream commit `98801578…` 与 54 个 exe/dll 的 SHA256；原 zip 留在 `download/`。
  - 历史 experiments 测试策略：全部 experiments recipe（测试与 demo）改用 `justfile` 的 `legacy`（`uv run --no-project --python 3.12`，等同原无依赖根环境），不在产品环境运行。用户另行决定删除 `experiments/tests/` 中除 `test_evaluator.py` 外的 41 个文件（提交 9d2852d），recipe 模块列表同步删除；剩余 44 个列举模块均可导入，evaluator 27 项通过。
  - smoke（`just test-full <名称>` 逐项运行，结果在 `.local/smoke/20261014T04*`）：
    1. `forced_align` 通过：合成序列 CUDA 与 CPU 路径一致、分数差 0；冻结窗口 hf-ii-window-01 第 0 窗 CUDA／CPU 路径一致，65 个 token 帧位置与 torch 2.8 冻结记录全部相同（path SHA 相同，emission 字节不同）。**发现**：transformers 5.19 的 `Wav2Vec2CTCTokenizer` 把 `|` 作为 added token（id 2268）加入词表，超出模型 2268 类；字典须只取 id < `vocab_size`，否则 `character_targets` 对 `|` 的处理会变（票据 03 移植 `align.py` 时注意）。
    2. `vad_pyannote` 通过：导入与 10 s 内存波形推理后，进程未加载任何 avcodec／avformat 等 FFmpeg DLL，PATH 上也没有 FFmpeg 共享 DLL，无 torchcodec 告警。结论：VAD worker 不需要 FFmpeg PATH（规格 §7.1 那条可删）。
    3. `ct2_after_torch` **按票据判据未通过**：干净 PATH 下解码成功，token 与特征 SHA 与冻结记录逐一一致；cuBLAS／cudart 与 cuDNN 子库均来自 torch/lib（cuDNN 9.19.0），但 CT2 wheel 自带 `cudnn64_9.dll`（9.10.2.21，266 KB 调度器）并在 `__init__` 中按全路径 `ctypes.CDLL` 加载，进程内两份 `cudnn64_9.dll` 并存。PTX JIT：冷启动解码 27.2 s、二次启动 5.2 s（模型加载 7.3 s→3.2 s），`CUDA_DISABLE_PTX_JIT=1` 时解码报 `cudaErrorInvalidDevice`，判断 CT2 4.8.3 依赖 PTX JIT（脚本自动分类为 inconclusive）。
    4. `llama_stock` 通过：两引擎 `/tokenize`（4 个探针串＋b10 第 0、1 批 prompt）一致，固定 seed 48 token 生成一致，b10-joint 两批 run_step 结果一致；v3 假设在 stock 上成立：首个 completion `cache_n == 0`，第二个 cache 请求 `cache_n 181`／`prompt_n 550`／`tokens_evaluated 731 == len(tokens)`；两引擎响应都没有 `stopped_limit` 字段，`stop_type == "limit"` 驱动 run_step 判 limit，`truncated` 存在；`--fit off`、`--cache-ram 8192`、`-lv 4` 被接受（日志确认 verbosity 4 与 8192 MiB prompt cache），只有 `--no-webui` 提示已弃用、建议 `--no-ui`；residency 解析与校验在 stock 日志上通过，加载日志另存 `stock-load.log`（174 行，可复现同一 residency）。显存峰值（含约 2.4 GB 桌面基线）：stock b10 批次 15.5–15.7 GB、会话 15.75 GB；compat 15.8–15.95 GB。stock 冷加载 6.7 s。
  - `just check-toolchain`、`just check` 通过；`just test` 报 NO TESTS RAN（本分支基于 main，产品测试在 00 分支，合并后才有）；`just docs-check` 与 main 基线相比无新增错误。
  - 文档：technology-stack、toolchain、workflow、AGENTS 重任务清单已更新；translation-runtime 模块页只删了已删测试的引用。
  - 遗留／待用户决定：smoke #3 判据（是否接受 CT2 自带 cuDNN 调度器并存）；规格 §7.1 与票据 03 回写 FFmpeg 结论、§7.1／§7.2 的"按基名复用"表述修正（规格与票据 03 不在本票文件所有权内）；translation-runtime 模块页兼容引擎说明改为历史（同上）；ADR-0005 反向链接只存在于主 checkout 未提交的改动中，本分支未见；`mise exec` 首次在 worktree 运行时自动下载安装了 uv 0.12.22、just 1.58.0、python 3.14.8（未先询问）。
- 2026-10-14 用户裁定：接受 CT2 自带 cuDNN 调度器并存，smoke #3 判据改为"除 CT2 wheel 自带的 `cudnn64_9.dll` 外均来自 torch/lib"，重跑通过；授权回写规格 §7.1／§7.2／§9／§12、票据 03 与 translation-runtime 模块页，均已完成；ADR-0005 反向链接经合并 main（64a912e）后核对存在。main（含票据 00）已合并进本分支，`just test` 61 项通过；`just test-full` 全套一次通过（`.local/smoke/20261014T045328Z/`，2.5 分钟）。
- 2026-10-14 legacy recipe 复核（删测试后）：`translation-test`、`translation-flow-test` 通过；`translation-flow-v2-test` 461 项中 14 项、`experiments-test` 中 2 项只在 worktree 失败，原因是 `.local` junction 让 `resolve()` 指回主 checkout 路径；相同用例在主 checkout 下全部通过（76 项／2 项复跑），不是代码回归。以后在 worktree 里跑 legacy 测试需注意这一点。

## Answer

产品根环境与 llama.cpp b11583 就绪，四项环境 smoke 入库并全部通过；结论见上方 Comments 与 map 的 Decisions-so-far。

