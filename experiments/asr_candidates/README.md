# 第一批 ASR 候选整片比较

本轮已完成五路线、十次整片运行和统一评分，结果见[实测报告](../../docs/research/2026-10-05-asr-candidates-fullfilm.md)。以下说明维护可复现入口与证据边界。

本入口实现 Cohere Transcribe 2B、Granite Speech 4.1 2B 基础版、Nemotron 3.5 ASR 0.6B
与当前 W0／X0 的两片整片比较。工具实现、权重下载、短窗 GPU 资格确认和完整比较是不同阶段；
是否完成实测以各阶段产物和实测报告为准；完整运行结束不等于达到质量验收目标。

开始前阅读[执行计划](../../docs/plans/asr-candidates-fullfilm.md)、
[W0／X0 基线指南](../../docs/guides/baseline-testing.md)和
[素材规则](../../docs/testing/fatestay-reference.md)。模型来源、许可和原生接口见
[候选调研](../../docs/research/2026-10-05-asr-model-landscape.md)。

## 固定比较范围

完整 Heaven’s Feel II 为 7028.0426875 秒，III 为 7325.3333125 秒，共 239.222933 分钟。
主参考为两部原版内嵌日文 SRT，完整参考包含 2064 条、22134 个规范化字符。
原 FLAC／SRT 只读，复用已经登记的全片 mono／16kHz 派生 PCM；执行前后核验原素材、
派生音频和参考的 SHA256。保留日语原文，无降噪、人声分离、翻译、热词或前文 conditioning。

| 最终路线 ID | ASR | 分段／对齐 |
| --- | --- | --- |
| `w0-pyannote-current` | 当前 canonical faster-whisper | 本轮新 Pyannote 整片窗口／共享 MMS |
| `x0-pyannote-current` | 当前 canonical Qwen ASR | 同一窗口／同一 MMS |
| `cohere` | Cohere 原生 Transformers | 同一窗口／同一 MMS |
| `granite` | Granite 基础版原生 Transformers | 同一窗口／同一 MMS |
| `nemotron` | Nemotron 原生 Transformers RNNT | 同一窗口／同一 MMS |

五个家族各处理两部完整影片，共十个模型／影片槽。新候选各运行一次 ASR 和一次 MMS，
不复制成两份相同分段路线。新 Pyannote 在完整影片上执行一次，窗口保留内部静音；
三个候选读取同一组整数采样边界，使用自己的原生 processor 和独立纯文字解码。
300 秒区间只用于评分统计，不用于采样、截掉尾部或重置推理。

ASR 与 MMS 使用 `cuda:0`，不回退 CPU。父控制器持有 `.local/gpu.lock`，
子进程核对 `KOTOTOKI_FULLFILM_PARENT_PID`；模型按 ASR／MMS 阶段串行驻留和复用。
不得移除活跃 GPU 锁。

## 本地环境与资产供给

| 阶段 | 解释器／环境 | 用途 |
| --- | --- | --- |
| 轻量控制器、离线测试 | `.venv/Scripts/python.exe` | 管理冻结登记和子进程，不在控制器加载模型 |
| 候选原生 ASR | `.local/envs/asr-candidates-py312-v1/Scripts/python.exe` | Python 3.12、Transformers 5.18.0、Torch／Torchaudio 2.11.0+cu128 |
| 共享 MMS | `.local/envs/whisper-latest/Scripts/python.exe` | 已有 MMS GPU 环境 |
| 新 Pyannote 对照准备 | `.local/envs/vad-pyannote-gpu-v1/Scripts/python.exe` | 已有新 Pyannote GPU 环境 |
| 精确编辑距离评分 | `.local/envs/vad-comparison/Scripts/python.exe` | 已有 RapidFuzz 环境 |

Granite 原生处理器需要 Torchaudio。供给本轮候选环境时，既有 Qwen 环境的 Torch 2.14.1
没有可用的匹配 Torchaudio，因此候选使用独立的 Python 3.12 环境与配对的
Torch／Torchaudio 2.11.0+cu128；Transformers 保持 5.18.0。此选择有明确依赖原因，
不修改正在使用的 W0／X0 环境；该配对仍须由真实 GPU 资格测试确认，安装完成不是推理通过。

推理入口不安装依赖、不联网下载模型。下载和访问资格处理单独进行；模型目录默认位于
`.local/models/asr-candidates/`，供给证据位于 `.local/asr-candidates-provision/`。
只有获取完整本地原生 checkpoint、核验文件后，才写入对应的 ready manifest：

| manifest 文件 | 官方模型 ID | 固定 revision |
| --- | --- | --- |
| `cohere-ready.json` | `CohereLabs/cohere-transcribe-03-2026` | `b1eacc2686a3d08ceaae5f24a88b1d519620bc09` |
| `granite-ready.json` | `ibm-granite/granite-speech-4.1-2b` | `de575db64086f84fdc79da4932d1076e965bc546` |
| `nemotron-ready.json` | `nvidia/nemotron-3.5-asr-streaming-0.6b` | `ea30d66debe3740a08b573244286791d423d6b3e` |

ready manifest 的必需字段为 `status="ready"`、`model_id`、`model_revision`、
`path` 和非空的 `files_sha256`。`path` 指向本地模型目录；`files_sha256` 将该目录下的
相对文件名映射到实际完整 SHA256，覆盖全部原生模型、processor、tokenizer 和配置文件。
Hugging Face 下载目录的 `.cache` 管理文件不属于 checkpoint manifest。
以下只是结构示意，路径和哈希须由真实供给过程产生：

```json
{
  "status": "ready",
  "model_id": "ibm-granite/granite-speech-4.1-2b",
  "model_revision": "de575db64086f84fdc79da4932d1076e965bc546",
  "path": "D:/AI_Projects/kototoki/.local/models/asr-candidates/granite",
  "files_sha256": {
    "config.json": "<实际 64 位 SHA256>",
    "model.safetensors": "<实际 64 位 SHA256>"
  }
}
```

控制器核对固定模型身份、revision、目录内文件边界和每个哈希；原生适配器再次比较
实际 checkpoint 文件清单与同一 manifest。已接纳的 manifest 及权重不能在运行或接跑时替换。
权重、缓存、完整转写和凭据留在 Git 忽略的本地目录。

Cohere 的初始资格检查返回 `GatedRepoError`；本轮用户处理权限后已下载并校验完成。
在尚未获得权限的机器上，需由本机 Hugging Face 对应账号在
[官方模型页](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026)接受访问条件，
并确保本机登录凭据可访问后，再单独下载和生成 ready manifest。不要把 token 写入聊天或研究产物。
缺少 ready 文件或状态未 ready 时，控制器将该模型两部完整影片登记为 `blocked_access`，
继续处理其他已选择候选。

## 准备新对照并执行候选

先使用[整片控制器](../fullfilm_comparison/README.md)运行本轮 W0／X0 新对照：

```powershell
.venv/Scripts/python.exe -m experiments.fullfilm_comparison.run --study-id asr-controls-v1 --routes w0-pyannote-current x0-pyannote-current
```

该命令使用已登记的 `.local/fullfilm-comparison/fullfilm-v1/plan.json` 完整语料。
候选控制器要求两条选定对照的所有影片槽都进入终态，且两部新 Pyannote 整片分段已完成。
原控制器未选的 cut-merge 槽可以继续 pending，原 `study.json` 的 `terminal=false`
不会让已完成的选定对照被误判为缺失，也不会把未运行的 cut-merge 算入此次五家族比较。

三个候选完成短窗原生 GPU 资格确认、准备好本地资产后，运行：

```powershell
.venv/Scripts/python.exe -m experiments.asr_candidates.run
```

默认导入 `.local/fullfilm-comparison/asr-controls-v1/study.json`，
输出 `.local/fullfilm-comparison/asr-candidates-v1/`。控制器导入新对照的原始槽、
阶段成本、输出哈希和来源，不重新执行 W0／X0。可先选择已供给候选：

```powershell
.venv/Scripts/python.exe -m experiments.asr_candidates.run --candidates granite nemotron
```

未选择候选保留 pending，整项比较仍未终止。要明确登记 Cohere 的门控状态，可运行默认命令；
它会检查三个候选。Cohere 供给 ready 后，用同一研究身份接跑：

```powershell
.venv/Scripts/python.exe -m experiments.asr_candidates.run --candidates cohere
```

只执行 `pending` 或此前 `blocked_access` 的槽。已完成、partial 和 invocation_failed
均不重跑；中断留下 running 状态时，控制器要求先检查现场，不能悄悄重试或覆盖证据。
普通分段失败保留 checkpoint 并继续剩余窗口；初始化失败、致命 CUDA 错误和阶段集成错误
分别保留类型与诊断。ASR 触顶产物只保留为不完整诊断；MMS 失败保留已完成文字及 `text_only`。

`terminal=true` 只表示当前所有槽已有终态，可包含门控和失败；
`all_model_slots_attempted`、`all_models_tested`、`resumable` 分别反映尝试、ASR 观测及门控接跑情况，
不能把 terminal 当成全部模型成功。另起新比较时，为对照和候选同时选择新身份，例如：

```powershell
.venv/Scripts/python.exe -m experiments.asr_candidates.run --study-id asr-candidates-v2 --baseline-study .local/fullfilm-comparison/asr-controls-v2/study.json --provision-root .local/asr-candidates-provision
```

运行前须先准备该新身份对应的完整对照。既有完成目录和孤立证据不覆盖；研究登记只用于
受控更新状态。下载与运行所需的系统权限遵循仓库 `AGENTS.md` 和当前沙箱规则。

## 参数冻结与产物

默认候选设置为 `bfloat16`、SDPA、batch size 1、确定性 greedy decode。
Cohere 使用原生日语标记 `ja`；Nemotron 使用 `ja-JP`；Granite 使用官方转写 prompt，
保留源语言。Cohere 的 `max_new_tokens=1000`，Granite 为 1024；Nemotron 不套用文字 token 上限，
核验原生 RNNT encoder 帧消耗与完成证据。具体有效参数、原生 generation config、模型配置、
安装实现身份、GPU 参数／buffer／输入设备及 token／frame trace 随结果保存。
参数在整片比较开始前固定，不按识别成绩回调。

初次登记复制对照研究快照和冻结源码。候选分段计划保留原始 input、offset 和全部 chunks，
只加入合并的推理源码身份与 `origin_plan_path`／`origin_plan_sha256`。
冻结源包含原对照依赖和候选 controller／worker／adapters，排除候选评分器及测试文件；
执行与接跑核验当前源码、原始及派生计划、已导入证据、模型 manifest 和权重。
冻结后修改推理源码需另起研究身份。独立评分器的源码身份在评分产物中另记。

正常子进程明确设置离线模式，临时目录与模型库缓存放在研究目录内。主要产物为：

- `study.json`：五路线、十槽、来源、模型供给和前后输入核验。
- `control-study-at-import.json`、`source/`：导入快照和冻结推理源码。
- `segmentation/*/plan.json`：保留原始来源的共享全片窗口。
- `runs/*/asr/`、`runs/*/align/`：ASR／MMS 阶段结果、逐窗 checkpoint、进度和日志。
- `failure.json`：阶段失败类型、异常和诊断；研究登记绑定其 SHA256。

## 评分与离线验证

在研究 `terminal=true` 后，用新的输出目录评分：

```powershell
.local/envs/vad-comparison/Scripts/python.exe -m experiments.asr_candidates.evaluate .local/fullfilm-comparison/asr-candidates-v1/study.json --output .local/fullfilm-comparison/asr-candidates-v1/analysis-v1
.venv/Scripts/python.exe -m unittest discover -s experiments/asr_candidates -t . -p 'test_*.py' -v
```

评分输出 `report.json`、`summary.md`、`diagnostics.json`、`bin-scores.json` 和 `identities.json`。
再次评分或 Cohere 接跑后改用新的分析目录，保留先前门控报告。
离线测试使用 fake 模型／子进程，不能作为真实 GPU 或完整影片识别成绩。

主文字指标为每部完整影片的全局精确编辑距离 CER 和 S／D／I，合并先加计数与参考分母；
不使用对齐时间挑选识别文字。时间指标采用既有 300 秒统计分组，报告完整分母的半秒确定成功、
可测覆盖、严重偏移和条件长尾。五个不同 ASR 家族不套用旧分段策略实验的配对排除。
全部参考和失败／缺失槽始终保留；无 ASR 观测的模型文字质量显示 `null`，
假定空输出的缺失编辑数另列为完整性记账，不能当成门控模型的 CER 成绩。
若 MMS 阶段失败，仍可观测完整 ASR 文字，时间质量按缺失对齐证据处理。

字幕显示时间不是人工声学真值，两片也不是独立盲测。未参考输出不自动判定为幻觉或歌曲；
本研究不自动替换已采纳 W0／X0 基线，完整结论需结合整片证据与独立审计。
