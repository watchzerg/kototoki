# 日语 CTC 缓存文字补充实验

> 2026-10-05 后续开发入口：此目录保留缓存文字的多候选对齐实验。当前 W0／X0 的 MMS 共用 [W0 demo](../w0_demo/README.md) 的 `alignment.py`，保留 jpn 校验、归一化、数值配置与完整文字契约；本目录结果作为历史对照。[X0 demo](../x0_demo/README.md) 的接入与验证单独记录，不能直接套用 W0 的验收结论。

本入口只重算对齐阶段；原 ASR 文字、音频与源时间保持完整，模型获取由独立准备步骤完成。
所有真实 forward 与 TorchAudio 2.8.0 `forced_align` 必须在 GPU 上执行，推理采用 FP32。
运行环境复用冻结的 WhisperX 3.8.6 环境，不升级依赖。

```powershell
.local/envs/whisper-latest/Scripts/python.exe experiments/japanese_ctc/run.py --candidate reazon --route W1 --audio AUDIO.wav --asr-result CACHED.json --align-model .local/models/japanese-wav2vec2-large-rs35kh --offset 0 --output .local/japanese-ctc/RUN/result.json
uv run --locked --offline python -m unittest experiments.japanese_ctc.test_run -v
```

输入是已有 `original_segments`、完整 `text`、PCM16 WAV `file_sha256`／`pcm_sha256` 与 `offset_s` 的缓存结果或 bridge。
X0 使用既有 Qwen→CTC bridge 或已有 X0 的 `original_segments`。
W0 使用原生 word envelope bridge；也可对完整 W0 缓存加 `--word-envelope` 生成独立 bridge。
输出必须在项目 `.local/` 下且不存在，不覆盖原结果。记录来源、实现、模型各文件与输出 SHA256；
`.sha256` 边车保存实际输出文件哈希。失败 segment 的完整文字保留为 `text_only`。

`--candidate jonatas` 默认复用原 WhisperX `execute`、feature extractor normalization 与 `ForcedRecorder`；
`mms` 同样复用，但显式选择 `jpn` tokenizer 与 adapter。本轮12项 Jonatas 重跑与原结果的
全文和全部时间单元严格一致；后续修改此边界时仍需重新核对。
MMS 先以 `target_lang=None` 完整加载 base，再通过 `load_adapter("jpn")` 替换 adapter 与 classifier；
这避免 Transformers 在 base 加载前将 154 维 head 改为 2268 维引发权重尺寸冲突。
最终 head weight／bias 必须逐值精确匹配本地 `adapter.jpn.safetensors`，校验结果写入设备证据；
旧失败尝试保持原记录，修复属于独立运行身份。

Reazon 默认走 `native-token`：使用 tokenizer 原生多字符 pieces 和 `model.config.pad_token_id`，
以完整 token 区间生成时间。多字符 piece 以 `word` 粒度输出，不均分为伪造的字符时间。
其 tokenizer `<pad>` 与模型 blank 并不相同，因此 `--tokenization whisperx-char` 仅可用作旧接口兼容性探针，
不能将其质量解释为正确 Reazon 原生推理。OOV 使用现有 max nonblank wildcard，并保留为 untimed。

原生 token 路径按 checkpoint feature extractor 的 `return_attention_mask` 设置向模型传 mask；
这是与旧 WhisperX 不传 mask 路径的显式差异。`--padding` 扩大已有音频搜索窗口；
`--zero-pad-seconds 0.5` 在 Reazon waveform 两侧增加物理零采样，按官方建议作为独立 recipe 消融。
时间减去该零填充偏移，完全位于填充区域的 token 不接收时间，部分相交区间裁剪至源窗口。
默认物理零填充为 0，各配置应在推理前固定。

`hiragana` 使用同目录 `phonetic.py` 的 pykakasi 读音转换，
由 `--reading-packages` 指向隔离依赖目录。原文多字符汉字范围只输出整体 word 区间；
读音错误、缺词或 OOV 会保留原文并记为无时间。此路径新增读音转换责任，需要独立报告。

成本记录 model load、对齐时间、CUDA peak allocated／reserved memory；
这些是缓存对齐阶段成本，不能替代新 ASR＋对齐的端到端时间。离线单元测试不证明真实模型兼容性或质量。

批次入口 `batch.py` 先冻结再执行，复用原 GPU 串行 harness，并用未修改的现有评分器汇总：

```powershell
.venv/Scripts/python.exe experiments/japanese_ctc/batch.py prepare --name EXAMPLE --candidate reazon --scope pilot
.venv/Scripts/python.exe experiments/japanese_ctc/batch.py run --name EXAMPLE
.venv/Scripts/python.exe experiments/japanese_ctc/batch.py score --name EXAMPLE
```

`pilot` 固定两片各 window-01／04；`full` 为原十二窗。用 `--routes w0,w1,x0`
明确上游；`--zero-pad-seconds 0.5` 必须在 prepare 时登记。每次尝试使用新名称，
不得覆盖已有结果。模型或代码变化应另建计划；下载与推理分开执行：

```powershell
.venv/Scripts/python.exe experiments/provision/japanese_ctc.py --candidate reazon --candidate mms --candidate hiragana
```

Hiragana 的隔离依赖固定在 `.local/japanese-ctc/reading-packages`：
`pykakasi==2.3.0`、`jaconv==0.5.0`、`Deprecated==3.0.0`、`wrapt==2.5.0`。
完整新增离线检查已进入 `just test`，也可单独执行
`uv run --locked --offline python -m unittest discover -s experiments/japanese_ctc -p 'test_*.py' -v`。
真实模型结果和边界见[实测报告](../../docs/research/2026-10-04-japanese-ctc-results.md)。
