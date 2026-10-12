# Crisp Qwen 原生 Windows 实验入口

状态：开发五章的两种受控流程实测完成；GPU执行可复现，字幕时间未达标  
最后更新：2026-10-04  
范围：CrispASR 0.8.41、Qwen3-ASR-1.7B f16 GGUF 与 Qwen3-ForcedAligner-0.6B f16 GGUF；RTX 5080，原生 Windows。

## 冻结身份与来源

以下来源于 2026-10-04 重新读取的上游 release API、固定 tag 源码和 Hugging Face model API，而非沿用旧会话的安装状态。

| 项目 | 固定身份 |
| --- | --- |
| 最新稳定 release | `v0.8.41`，发布时间 `2026-10-02T15:21:50Z` |
| 源码 | `340d7085eaa53c40a46dcb73a6d3d0448a480006` |
| Windows Vulkan CLI ZIP | `crispasr-windows-x86_64-vulkan.zip`，38,659,200 bytes；SHA256 `146a38edb97a83fbc1b526e7767d3e25ab03bf6f4118c41342eda09abe9af6a0` |
| 本机 EXE | SHA256 `07dbe65c4adbea6e977bc0253d0991175cbd92ee871e5a5cf33ac4eda5303658` |
| ASR GGUF | `cstr/qwen3-asr-1.7b-GGUF` revision `674df5d44b50a63e7102a18895ed20e3f91de301`；`qwen3-asr-1.7b-f16.gguf`，4,704,800,576 bytes；SHA256 `ac6c58f9cb0f2bb22290319cde01b0e25a2c1f1ee69aa2f1a9265f29a8bfc9d7` |
| FA GGUF | `cstr/qwen3-forced-aligner-0.6b-GGUF` revision `1ec5110602ccab18c878ddebedab0891e290a95c`；`qwen3-forced-aligner-0.6b-f16.gguf`，1,841,707,200 bytes；SHA256 `35bd243939212f675652d36de061bedf09daee9a7af2a866f47e57be148a8578` |
| 原生 Silero VAD | `ggml-org/whisper-vad` revision `9ffd54a1e1ee413ddf265af9913beaf518d1639b`；`ggml-silero-v6.2.0.bin`，885,098 bytes；SHA256 `2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987` |

GitHub 发布附件公开 digest 与本机 ZIP SHA256 已一致；ZIP 未包含大模型。GGUF由资产负责人串行准备并核对完整hash；开发stage批次ASR与FA入口均再次校验实际模型SHA256，身份与本表HF LFS一致。已由下载manifest校验的后续诊断可显式 `--skip-model-hash`，输出仍记录这次没有重新hash。

来源：[release](https://github.com/CrispStrobe/CrispASR/releases/tag/v0.8.41)、[release API](https://api.github.com/repos/CrispStrobe/CrispASR/releases/latest)、[ASR 固定 model card](https://huggingface.co/cstr/qwen3-asr-1.7b-GGUF/blob/674df5d44b50a63e7102a18895ed20e3f91de301/README.md)、[FA 固定 model card](https://huggingface.co/cstr/qwen3-forced-aligner-0.6b-GGUF/blob/1ec5110602ccab18c878ddebedab0891e290a95c/README.md)。ASR card 明确转换自官方非 `-hf` Qwen checkpoint，两种 GGUF card 均声明 Apache-2.0。上游 card 的质量或“近乎无损”描述不作为本地实测结论。

## 本机观察与默认流程

`--version` 已运行，输出版本 `0.8.41`、git `340d7085`、MSVC 1951、Windows x86_64 Release、构建时间 `2026-10-02T15:51:50Z`、ggml backends `cpu,vulkan`。`--diagnostics` 枚举了唯一 Vulkan GPU：`Vulkan0`，`NVIDIA GeForce RTX 5080`，fp16/bf16 可用、`NV_coopmat2v` matrix cores。这证明二进制可启动及设备可枚举，仍不能证明实际模型图推理。

[固定 CLI 文档](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/docs/cli.md)推荐字幕流程启用 VAD，并提供 `-am`、`--force-aligner`、`-ojf`。默认未启用 VAD时以 30 秒能量寻找切口、3 秒上下文 overlap 分块，能量门默认开启；有 VAD 时使用其切片。适配器保留这些默认值，仅固定日语、greedy temperature 0、seed 42、token cap 512、4 CPU threads，以及 GPU backend Vulkan/device 0。参数试验通过独立新输出路径记录，不静默改变模型版本。

重要设备边界：ASR 和 FA 各创建一个 `qwen3_asr_context`，默认 `use_gpu=true`；显式 preference 时共享 GPU initializer 打印 `using preferred GPU backend`。但首轮非 VAD 实跑只有 ASR 的 marker，而 FA 的 `aligner_forward` 已执行。CLI EXE 与共享 DLL 的 inline static preference 可能分离：FA 在 DLL 内未设置 preference，走自动设备选择，不打印该 marker。这是源码解释，尚未对运行中的 DLL context 取值。不能凭 ASR 设备日志推定 FA 实际 GPU；入口保持该运行 `actual_fa_device_unverified`，没有将缺失证据改为通过。[ASR init](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/qwen3_asr.cpp)、[FA init](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/crispasr_aligner.cpp)、[GPU preference](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/core/gpu_backend_pref.h)。

原生 Silero VAD 明确运行 CPU：固定源码 `src/crispasr.cpp` 的 VAD init 将 `params.use_gpu=false`，权重与 CPU scheduler 同驻留。此原生预处理必须公开披露；不能将本路线描述成“全部模型均 GPU”。本次按用户保留内置预处理的原则保留它，ASR/FA 仍要求 GPU。ggml 模型 scheduler 还注册 CPU helper backend，context GPU 证明不意味着所有辅助算子都 GPU。[Silero 实际实现](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/crispasr.cpp)。

`--strict-pipeline --require-word-timestamps` 防止 aligner/VAD 加载失败后 exit 0 的宽松降级；直接传本地权重和 VAD 路径，正式推理不触发 auto-download。静音无文字可以成功，但 FA 未执行，输出不能据此宣称 FA GPU smoke 通过。

## 可复现入口

模型与工具、音频、完整日志均在 Git 忽略的 `.local/` 下；入口自身只依赖标准库，可使用根 uv project Python。

```powershell
uv run --no-sync python experiments/crisp/run.py `
  --audio .local/audio/fatestay-dev-smoke.wav `
  --output .local/runs/crisp-native-dev-smoke.json `
  --vad-model .local/models/crisp-silero-v6.2.0/ggml-silero-v6.2.0.bin
```

如果 WAV 来自整片中间，必须传 `--offset <源秒数>`。入口拒绝非 PCM16/mono/16 kHz 文件，完整 SHA256 绑定实际 WAV。默认路径使用已冻结的两个 f16 GGUF；工具路径为 `.local/tools/crisp/v0.8.41-vulkan/crispasr-windows-x86_64-vulkan/crispasr.exe`。无 VAD 的受控分支省略 `--vad-model`；是否追加 `--disable-energy-gate` 要按固定连续输入试验目的决定并记录。

输出包括完整原始 `native` JSON、原生 `.native.srt`、stdout/stderr、actual command/config/环境控制、模型与 binary 身份、wall time、原生 stage timings、GPU marker。stdout 的公开摘要仅含文字长度和设备证明，不打印转写内容。原生阶段计时是 nested timers，不能把全部计时直接相加当作总耗时；CLI wall time包含初始化、ASR、FA和writer。外部统一资源监测应由 GPU 队列负责人运行。

统一 schema 保留原始 segment text 的串接及 exact word 原文区间。缺少文字对应的标点/内容显式记为 `text_only`，无效或零长度时间记为失败，不自动插值。FA 已通过官方 `fix_timestamps()` 移植修正，标记 `time_source=api`；并非未修正 logits 原值。JSON segment/word `offsets` 是毫秒；legacy `t0/t1` 是厘秒。分别保存 raw segment cue 与 `native_writer_cues`，writer 的拆句/插值不能算成 aligner 原生准确时间。[固定 JSON writer 源码](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/examples/cli/crispasr_output.cpp)、[官方 correction 移植](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/core/qwen3_forced_aligner.h)。

独立 FA 设备诊断入口 `experiments/crisp/align_only.py` 使用官方 C ABI，在同一个 DLL 里先调用 `crispasr_set_gpu_backend("vulkan")` 再执行 `crispasr_align_words_abi()`。两个导出函数在已下载的实际DLL存在，随后已完成组件及stage GPU实跑。它以保存的 ASR JSON/text 为输入，另存 API correction 后结果，要求实际 FA 初始化 GPU marker 且无 CPU fallback 才认可设备。正常识别榜不能把该组件诊断当成 native CLI 同次运行的设备证据，也不能输入参考字幕假装正常 ASR。[固定 C ABI 声明](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/include/crispasr_session.h)。

```powershell
uv run --no-sync python experiments/crisp/align_only.py `
  --audio .local/audio/fatestay-dev-smoke.wav `
  --text-file .local/results/q1-smoke-vulkan-no-vad-r1/result.json `
  --output .local/runs/crisp-explicit-fa-smoke.json --offset 10
```

连续窗口受控入口 `experiments/crisp/run_session.py` 在同一 DLL 中明确设置 GPU preference、打开 ASR session，再对每个连续 30 秒 PCM 窗口进行 ASR 和 FA。两个 context 跨窗复用，关闭 VAD、能量门和 overlap，只用于定位 native 故障，不是等价 CLI。记录窗口样本区间、各窗 ASR/FA 用时、GPU实际 marker、模型加载时间、所有空/失败窗口；每窗保存中间 JSON以便恢复。温度0、seed42、beam1、max_new_tokens512、日语 assistant prefill 均按 C ABI setter/source核对。[官方 session 来源](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/crispasr_c_api.cpp)、[官方 Python bindings](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/python/crispasr/_binding.py)。

日本语 FA 实际分词方式是 CJK Unicode 字符切分，并去除标点作为 alignment labels，然后将标点恢复到相邻字。它不使用 nagisa；逐字的 timestamp slots 与官方日语词法分词不同，可能影响零跨度和覆盖，但未完成因果实验。这种切分是稳定实现的原生行为，不能标成意外 fallback。入口已将 `fa_text_segmentation` 和 correction 写入 manifest。[tokenise_words()](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/crispasr_aligner.cpp)。

VAD 诊断 `experiments/crisp/vad_diagnostic.py` 通过实际 DLL 的 whisper_vad API获取逐32ms概率，记录不同阈值覆盖和分位数。可另设 `--source-context`，调用上游导出的内部 `crispasr_silero_enable_context()`，测试原始 TorchScript wrapper 的64samples carry；这是单独recipe试验，不静默改 native默认。该诊断固定CPU，与本路线内置VAD的设备相符。

## 已完成验证与缺口

10 个 adapter GPU-free 单元测试通过：原文字与缺失标点保留、毫秒/厘秒/源 offset、重复词的单调映射与 missing-time 失败、无 words 文字保留、ASR/FA 两上下文证明及回退拒绝、temperature sticky-field 返回与其他 setter 真失败、UTF-8跨segment字节完整拼接与非法字节不替换，以及仅接受未对齐ASR预测范围的replay。另5项恢复核查测试通过。五章stage GPU推理、逐秒资源采样和当前reference时间评分已完成；C ABI连续窗口仍仅失败诊断，独立网络断开与整片长输入连续性未完成。

主 agent 统一排队的首两次实跑：`q1-smoke-vulkan-native-r1`，60 秒开发 WAV（源时间从 10 秒起）加载正确 v6.2.0 VAD、1875 个概率窗口，最终 speech segments=0；上游 exit 0，在写 JSON 前提前 return，适配器记为失败。`q1-smoke-vulkan-no-vad-r1` 保留 chunk/energy 默认，3 slices，22 文字字符/17映射单元，实际执行 3 次 FA forward；出现 alignment collapse warning，前两次零长度 spans 为 6/8、5/8，第一段 coverage=0.040/28.200s。该结果不是时间达标证据，FA实际device仍缺直接日志。所有文字及原生结果留 `.local/results/`。

VAD 模型不是误用版本：固定 CLI默认 URL正是 `ggml-silero-v6.2.0.bin`；本机加载日志也验证 6.2.0。固定源码存在 `crispasr_silero_enable_context()` 内部 recipe 开关，增加 Silero原始 wrapper 的前 64 samples carry；CLI cached Silero init未调用它。默认 graph 输入因此不含 carry。此差异是后续诊断线索，尚不能断言它导致全部 VAD漏检。[VAD source](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/crispasr_vad.cpp)、[context recipe](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/core/silero_context.h)、[no speech return](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/examples/cli/crispasr_run.cpp)。

`q1-smoke-fa-explicit-vulkan-r1` 已由主 agent 在GPU队列实际执行并在本研究独立核对：同一DLL setter 后确实打印 `using preferred GPU backend: Vulkan0`，FA返回17单位，exit0、没有fallback warning；实际DLL SHA256 `d346663c39948cef204db12768eb340003115af9e904e25979a00c44113878a2`，WAV SHA256 `f64e2f8ebaed91c33dd2788a105c37abe5b0239ebd033570ebfe6be38baa89f7`，C ABI调用/加载wall13.85s。设备证明通过，但`zero-position words 9/17(0.529)` warning仍在，不能混同为对齐质量通过。原CLI FA未知设备没有被这次独立调用追认。

`q1-ch01-session30-vulkan-r1` 初始化ASR Vulkan0成功，随后适配器误把 temperature setter 的 `-2` 当作未生效而停止，未进行识别。固定源码 setter 先写 shared `s->temperature`、`s->seed`，再按 backend-specific touched count 返回；Qwen decoder直接读取这两个 shared field，因此该 backend返回 `-2` 并不代表这些值没生效。入口已只对此明确源码核查的情况接受 `-2` 并记录，其他setter仍严格要求0。增加回归测试，所有执行过的setup崩溃/timeout也写empty schema与失败manifest，不因没有转写而漏计尝试。这是适配器修复，下一次推理须用新runID；旧失败不会追认通过。[setter与Qwen decoder同版本源码](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/crispasr_c_api.cpp)。

本入口不会下载模型、自动换版本或生成真值。已读 README、AGENTS 与文档索引；实验不是正式采用 backend，现有选型约束未改变。索引/共享计划进度由主 agent 统一更新，避免并发修改。

`q1-ch01-session30-vulkan-r2` 通过setter后，在首个ASR窗口遇到原生返回非法UTF-8字节（0xe5，byte offset18）。已复核官方binding签名与结果生命周期完全一致；getter返回结果拥有的 `std::string::c_str()`，在free前复制，且没有另一个整体text getter。`ja`按源码转换为`Japanese`。CLI与C ABI共同使用 `core_bpe::token_bytes_to_utf8()`，不能据此归因于不同decoder。入口改为先拼接全部原始segment bytes，再严格decode，避免合法字符跨segment时误报；若仍非法，保存每个segment的完整hex和异常位置，该窗口文字为空、跳过FA、保留完整时间分母并记失败，继续其他窗口。没有ignore或replacement字符进入质量结果。这是诊断处理，不把非法输出变成达标证据。[C ABI与共享decoder](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/crispasr_c_api.cpp)、[共享BPE helper](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/core/bpe.h)。

受控stage路线使用 `run.py --asr-only`：保留CLI本来的VAD/切片/energy默认，仅移除aligner与输出拆句；Qwen粗segment范围在backend原生转写时来自实际输入起点和样本长度，外部FA在ASR之后执行，关闭FA不改变ASR分块。随后 `align_only.py --asr-segments --text-file <ASR-only result.json>` 从这些**尚未FA修正**的预测范围裁切同一WAV，再在同DLL中明确设置GPU执行FA。拒绝已对齐结果、非成功ASR、输入SHA256或源offset不一致；不读取参考字幕。CLI JSON毫秒量化到样本的映射和原始范围保留在manifest。此路线保留新FA推理证据与ASR既有provenance，FA replay耗时不能冒充新完整流水线推理或无初始化成本的速度。[粗范围生成](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/examples/cli/crispasr_backend_qwen3.cpp)、[后置FA dispatch](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/examples/cli/crispasr_run.cpp)。

CPU VAD实际诊断已执行，模型、DLL和输入身份均写入 `.local/cache/crisp/vad-*-r1.json`：60秒smoke默认1875frames，p50=0.000615、p99=0.07248、max=0.30124，默认0.5阈值覆盖0；打开64sample carry后p50=0.000409、p99=0.04465、max=0.36206，0.5覆盖仍为0。这排除“概率已经高但分段/writer漏输出”的解释，且该carry方向未解决smoke，不继续盲目扩大调参。chapter17（413.892s）默认12935frames，p90=0.42075、p95=0.96912、max=0.99999，0.5覆盖9.54%；父agent相应native run输出29个最终speech segments。因此VAD不是全输入恒零；不能仅凭首个60秒片段宣布整个checkpoint损坏或阈值不适合全部影片。无人工speech真值时，这些概率覆盖不是识别召回率。

开发批次私有入口 `.local/analysis/crisp/dev-batch.ps1` 默认仅preview，显式 `-Execute` 才经统一 `experiments/run_experiment.py` GPU lock 串行运行；`-Mode native/novad`可分批恢复。最小序列是5个开发chapter（01/02/05/07/17）的native VAD ASR-only→显式GPU FA，再补无VAD的02/05/07/17（01已有且严格身份核对通过）。不再补3个FA设备未证实的CLI全流程重复baseline：01/17现有全流程与官方源码足以描述默认行为，stage路线保留ASR调度/预处理，但FA调用与性能是独立受控配置。仍不能把此配置宣称为原CLI同进程实测。

恢复核查 `experiments/crisp/batch_state.py` 只读，要求harness已完成、原素材引用hash保持、非空有效prediction、固定pins、输入SHA、源offset、VAD/decoding/chunk/overlap参数、ASR实际GPU、FA显式GPU及输入ASR identity均一致；失败或空结果保留并使用新rN，不当作完成跳过。ASR失败时评分其空prediction并跳过相应FA，其余章节继续。评分使用scoring-v2 reference与当前v2 evaluator，新score及独立identity sidecar保存候选/reference/评测器源码SHA；没有可信sidecar的旧评分不会被冒充此次完成；运行途中源码变化会停止以防混用。准备时preview核查通过，其后主agent统一队列实跑见下节。

批次恢复规则另有5个离线回归测试，连同adapter共15项通过：匹配身份接受，空/失败尝试拒绝，offset/VAD改变拒绝，WAV替换拒绝，以及原始字幕身份和GPU证明均不可缺。脚本每stage开始和结束保存可恢复batch记录，GPU已占用时停止等待主队列安排；不清理他人的lock。有失败时完成其余独立工作后返回非零状态，避免被误报为整个批次成功。评测器源码SHA在实际batch启动时获取，因此应等共享评测器所有者完成修改再开始；批次运行中保持冻结。

## 开发五章实际结果

主agent串行batch已完成native VAD与无VAD各5章（01/02/05/07/17），总音频1303.861秒。每个ASR实际初始化Vulkan0、每个FA同DLL显式初始化Vulkan0并完成，模型及DLL身份与冻结表一致，无CPU fallback warning。native VAD仍为CPU原生预处理，不称全模型GPU。所有10个阶段组合都有成功harness和v2评分，batch `failures=[]`只表示执行/证据流程完成，不表示时间或质量达标。独立只读审查结果及结果SHA在 `.local/analysis/crisp/dev-readonly-r2.json`，入口 `.local/analysis/crisp/analyze-dev.py`，不执行推理。

| 五章完整分母结果 | native VAD | 无VAD |
| --- | ---: | ---: |
| reference文字 / cues | 1902 / 195 | 1902 / 195 |
| 加权CER | 27.50% | 23.24% |
| deletion rate | 11.46% | 3.31% |
| 可测时间覆盖 | 23/195（11.79%） | 29/195（14.87%） |
| 2秒完整分母成功 lower–upper | 10.77%–13.85% | 12.82%–17.95% |
| alignment_failure / matching_ambiguity | 69 / 50 | 90 / 53 |
| missing_content / incomplete_content | 24 / 25 | 0 / 19 |
| 零长度单元 / 全部输出单元 | 247 / 1724 | 329 / 1922 |
| collapse warnings | 3 | 11 |
| 条件可测 max-boundary error p50 / p95 | 0.172s / 7.102s（n=23） | 0.182s / 10.142s（n=29） |
| joint完整覆盖 p95 | infinity | infinity |

加权CER按所有reference字符累计S/D/I计算，不平均章节CER；条件误差汇总所有可测cue，不能用漂亮的条件p50掩盖低完整分母覆盖。条件start绝对p95为native0.308s、无VAD7.783s；end绝对p95为0.990s、3.510s。上述本地统计p95使用nearest-rank，p50使用通常median；正式统一报告应使用共享评测器的约定。lower/upper来自当前冻结v2规则；当前SRT是显示时间参考，未人工听辨，matching ambiguity不能私自当作成功。这五章不足以建立统计泛化结论，也尚非保留集、整片连续性验证。

native各章零长度单元为41/1/82/65/58（总单元195/8/558/631/332），collapse warning仅chapter17有3条。这说明没有warning不代表全部时间有效。无VAD降低文字漏失，伴随更多zero spans和alignment failures；chapter02的8个reference字符，native CER0而无VAD CER237.5%，暴露额外文字风险。没有声学静音标注，不能将该插入差异或规则中的silence计数冒充已确认幻觉率。当前两种完整组合都不是字幕时间达标方案；无VAD仅是文字侧较好的已测配置，若进入后续有限跨家族尝试，需要更可靠aligner，并另设受控静音测试。

原CLI complete-flow与显式stage路线的两个观察样本存在强等价证据：chapter01原文214字符完全相同，195个相同char范围的有限start/end时间差全部为0；chapter17原文373字符相同，331个有限范围时间差全部为0（另1个缺时间范围保留失败）。因此这两个输入的文字及content时间输出一致；不能推广为所有输入证明、追认原CLI FA设备、或称性能等价。原CLI同进程与stage分离进程的初始化、显存峰和FA计时仍分别报告。

ASR阶段wall（排除适配器事前完整hash，包含CLI模型初始化）native为4.286–12.728秒，无VAD为7.734–16.255秒；FA replay worker wall（含FA初始化）native3.311–6.366秒，无VAD4.088–7.583秒。FA replay是新FA推理而ASR结果复用，不把阶段和计时写成一次新完整流水线。root harness另有含hash/解释器启动的wall和逐秒GPU采样。whole-device采样峰ASR native7061–9329MB、无VAD9281–9330MB；FA native5442–6358MB、无VAD6307–6360MB，均包含桌面基线且非per-process精确峰。这些是原生Windows RTX5080本地实际图执行证据；正式入口仅用本地assets、root harness设置HF离线环境，Crisp命令无auto-download。仍没有整片长输入、独立网络断开测量或正式产品性能承诺。
