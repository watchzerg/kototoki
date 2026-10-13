# 模块边界

本文规定职责归属、依赖方向与状态所有权。模块页说明自己如何遵守；实际偏差在模块页就地注明，不在此改写规则。

## 职责归属

| 规则 | 唯一归属 | 消费方 |
| --- | --- | --- |
| VAD 候选加载、原生检测、`source-span-merge-v1` 窗口切分合并（`chunk_intervals`、`CHUNK_POLICY`） | [外部 VAD 阶段](modules/vad-stage.md)（代码位于 `w0_demo/vad_candidates.py`） | 只经 manifest 文件被 W0／X0 消费 |
| VAD manifest 校验（`read_vad_manifest`） | [W0 pipeline](modules/w0-pipeline.md) 的 `experiments/w0_demo/run.py` | X0 的 `x0_demo/vad.py::import_vad_plan` 直接调用，不复制 |
| 音频读取与输入身份（`read_audio`：mono／16 kHz／PCM16，WAV／PCM SHA256） | `experiments/w0_demo/run.py` | X0 子阶段、外部 VAD 阶段 |
| Whisper 特征、无时间戳独立解码 | [W0 pipeline](modules/w0-pipeline.md) | — |
| fixed30／cut-merge 分段、Qwen 原生特征与解码、子进程编排 | [X0 pipeline](modules/x0-pipeline.md) | — |
| CTC 强制对齐、整数样本窗口校验（`sample_window`）、字符→unit 映射与 `text_only` | [MMS 对齐](modules/mms-alignment.md) | W0、X0 |
| 转写 JSON 结构契约（`validate_transcript`）与评分 | [STT 评分与显示重放](modules/stt-evaluation.md) | W0、X0 写出前调用；评分 CLI 读取 |
| 字幕显示切分（`minimal-display-v1`） | [STT 评分与显示重放](modules/stt-evaluation.md) 的 `display/replay.py` | demo 不复制 WhisperX cue 逻辑 |
| 模型下载与资产 SHA256 固定 | [语料与模型资产准备](modules/corpus-and-assets.md) | 推理入口只读本地文件 |
| llama-server 命令行、驻留证据解析、资产清单与 OOM 识别 | [逐窗翻译运行时](modules/translation-runtime.md) | 完整 SRT 流程导入 `residency_evidence`、`validate_residency`、`load_assets`、`explicit_oom` 等 |
| Hy30 原生提示模板与 ID JSON grammar（`translation_demo.adapters`） | [逐窗翻译运行时](modules/translation-runtime.md) | 完整 SRT 流程 |
| 流程配方身份（`Recipe.recipe_hash`）、批次、整片交付 | [完整 SRT 翻译流程](modules/translation-srt-flow.md) | — |

## 依赖方向

- 允许：X0 → W0（`read_audio`、`setup_runtime`、`gpu_lock`、`read_vad_manifest`、`MmsAligner`）；外部 VAD 阶段 → W0（`gpu_lock`、`read_audio`、`vad_candidates`）；W0／X0 → `kototoki_eval.schema`。
- 允许：完整 SRT 流程 → 逐窗翻译运行时（`translation_demo.adapters`、`client`、`run`、`translation_demo_runtime` 的纯函数）。
- 现存的当前→历史依赖（只读导入，不得扩大）：X0 → `experiments.qwen.run_qwen`（Qwen 资产身份常量与 `checkpoint_identity`、`check_gpu`）；完整 SRT 流程 → `experiments.translation_flow.srt`（SRT 读写与覆盖校验），其测试另导入冻结的 `translation_flow.v2_prepare`／`v2_recipes` 做 C0 等价核对；W0 测试导入 `experiments.framework_equivalence` 作数值参照，运行时不导入。
- 禁止：`kototoki_eval` 导入任何推理或 `experiments` 代码；推理入口导入 `experiments/provision`；当前模块写入或修改历史实验包（`translation_flow/v2_*`、`translation_judge/`、`translation_eval/` 等冻结证据）。
- 文件契约代替导入：W0／X0 不导入外部 VAD 阶段的入口，只读其 manifest；评分 CLI 只读 `result.json`；各入口只读语料准备产出的 WAV 与参考 JSON。

## 状态与契约

- 每个运行目录由创建它的入口独占：`.local/w0-demo/`、`.local/x0-demo/`、`.local/vad-comparison/`、翻译 `--output-dir` 及 v3 根目录（默认 `.local/translation-evaluation/hy30-flow-v3/`）。目录已存在即拒绝；结果、全文和缓存只写在该目录内。
- VAD manifest 是窗口的唯一权威：runner 将其原字节复制为 `vad-manifest.json` 并记录 SHA256，运行中来源变化即失败。manifest 中的 `stages` 是外部进程成本的快照，不计入 W0／X0 自身 `stages` 或 `wall_s`；回放 manifest 不是新的 VAD 推理（`fresh_inference=false`／`precomputed_external_manifest`）。
- 输入身份以内容为准（`file_sha256`、`pcm_sha256`、采样率、声道、样本数、时长、`offset_s`），路径可以不同。
- 运行身份（recipe 名、v3 `recipe_hash`、模型 SHA256、冻结源码哈希）是派生结果可比的前提；同名配方内容不同时拒绝续跑。
- X0 子进程之间只通过运行目录中的 JSON 交接（`request.json` → `plan.json` → `asr.json` → `alignment.json`），每阶段重验源码与输入哈希。

## 并发与生命周期

- `.local/gpu.lock` 是所有 GPU 作业共用的互斥文件，存在两种实现：`experiments/w0_demo/run.py::gpu_lock`（O_EXCL 创建，写 `pid`＋`recipe`，退出时删除；W0、X0 父进程、CUDA 设备的外部 VAD 阶段使用）与 `experiments/translation_v3/procs.py::ProcessLock`／`server.py::GpuLock`（写 `pid`＋`pid_created`＋`run_id`；存活持有者在时退出码 3，死锁只在 `--break-stale-lock` 时替换）。两者都不抢占、不杀进程。
- 逐窗翻译运行时（`translation_demo_runtime.py`）不获取 `.local/gpu.lock`，只检查端口是否被占用；与其他 GPU 作业的互斥由操作者保证。
- 模型生命周期按阶段串行：W0 通过工厂在 VAD 关闭后加载 ASR，ASR `close()` 后再加载 MMS；X0 每阶段一个独立子进程，进程退出即释放；父进程持锁直到全部子进程退出。
- 取消：X0 父进程在中断时 `terminate`→10 秒后 `kill` 当前子进程，记录被中断阶段成本并清理 `tmp/`；v3 把 llama-server 放入 KILL_ON_JOB_CLOSE Job Object，Python 被强杀时服务器随之退出。发出取消不等于 GPU 已释放；完整 Windows 取消／OOM 恢复仍未验证（见 [X0 pipeline](modules/x0-pipeline.md#代码与验证入口)）。
