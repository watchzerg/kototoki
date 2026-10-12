# 首轮本地 STT 的环境与复现清单

> 2026-10-05 后续开发入口：恢复或运行当前W0／X0时，先读[标准基线测试指南](../guides/baseline-testing.md)及对应demo的环境和资产说明。复用既有环境；W0的prepare_assets仅在独立VAD／Mel资产缺失时执行。本文是首轮清单，当前MMS资产及两套环境以demo说明和实际运行身份为准。

状态：环境、锁定版本与资产记录已核对；质量结论由对应实验报告负责  
最后更新：2026-10-04  
范围：原生 Windows 的 CPU 只读清点；模型、安装包、适配器来源和恢复入口。

机器清单保存在 `.local/analysis/reproducibility-inventory-v1.json`，包含全部模型运行文件的
已核验 SHA256、固定来源 URL、当前小型配置/源码 SHA256、安装包版本及锁文件比对。
本次调用各环境的 `platform`、`importlib.metadata` 获取实际版本，没有导入 Torch 或启动
模型、GPU 查询、下载、安装，也未读取保留测试结果。
大型权重与 CUDA DLL 的 SHA256 绑定此前已完成的核验清单；此次只核对模型文件存在和大小。

## 七组模型与资产

下列模型卡与固定 metadata 来源于 2026-10-04 的获取核查。对应资产位于
`.local/models/<本地目录名称>`，每个文件的来源、SHA256、复用方式及完整性证据在
`.local/manifests/model-<本地目录名称>.json`；官方 API 快照为同名 `-source.json`。
七组正式文件总计 16844694989 字节，`.local/manifests/model-assets-index.json` 已标记
`all_ready: true`。[资产获取记录](2026-10-04-model-assets.md)保留完整权重 SHA256 与获取经过。

| 本地目录名称 | 发布模型与来源 | 固定 revision | 模型卡许可 |
| --- | --- | --- | --- |
| faster-whisper-large-v3 | [Systran/faster-whisper-large-v3](https://huggingface.co/Systran/faster-whisper-large-v3/blob/edaa852ec7e145841d8ffdb056a99866b5f0a478/README.md) | `edaa852ec7e145841d8ffdb056a99866b5f0a478` | MIT |
| qwen3-asr-1.7b-hf | [Qwen/Qwen3-ASR-1.7B-hf](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf/blob/bcd2b5b7f32b480ab5790554cfa8347f246a14f3/README.md) | `bcd2b5b7f32b480ab5790554cfa8347f246a14f3` | Apache-2.0 |
| qwen3-forcedaligner-0.6b-hf | [Qwen/Qwen3-ForcedAligner-0.6B-hf](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf/blob/c07281df297b9905d24a508279258cccf987a064/README.md) | `c07281df297b9905d24a508279258cccf987a064` | Apache-2.0 |
| wav2vec2-large-xlsr-53-japanese | [jonatasgrosman/wav2vec2-large-xlsr-53-japanese](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-japanese/blob/cf031e020336460d15a417eba710bbc5bb43be9a/README.md) | `cf031e020336460d15a417eba710bbc5bb43be9a` | Apache-2.0 |
| crisp-qwen3-asr-1.7b-f16 | [cstr/qwen3-asr-1.7b-GGUF](https://huggingface.co/cstr/qwen3-asr-1.7b-GGUF/blob/674df5d44b50a63e7102a18895ed20e3f91de301/README.md) | `674df5d44b50a63e7102a18895ed20e3f91de301` | Apache-2.0 |
| crisp-qwen3-forced-aligner-0.6b-f16 | [cstr/qwen3-forced-aligner-0.6b-GGUF](https://huggingface.co/cstr/qwen3-forced-aligner-0.6b-GGUF/blob/1ec5110602ccab18c878ddebedab0891e290a95c/README.md) | `1ec5110602ccab18c878ddebedab0891e290a95c` | Apache-2.0 |
| crisp-silero-v6.2.0 | [ggml-org/whisper-vad](https://huggingface.co/ggml-org/whisper-vad/blob/9ffd54a1e1ee413ddf265af9913beaf518d1639b/README.md) | `9ffd54a1e1ee413ddf265af9913beaf518d1639b` | MIT |

CT2 文件是 large-v3 的 FP16 转换；实际推理精度仍由运行参数决定。Crisp GGUF 模型卡记录
转换自 non-HF Qwen，未说明转换时原 checkpoint 的 revision，因此仅冻结所发布的 GGUF
字节身份。当前 native HF 配套文件与 GGUF 的来源代际保持明确，不能仅凭同一模型家族
推断逐张量等价。

## 实际安装版本与软件身份

本次直接读取安装后的包 metadata，W0 的 24 包、WhisperX 的 104 包、Qwen 的 62 包均与
各自锁文件逐项相同，没有缺失、版本差异或额外安装包。根环境 Python 为 3.12.15，
`mise.toml` 固定 uv 0.12.22、just 1.58.0。

| 路线与环境 | Python | 主要运行组件 | 版本冻结证据 |
| --- | --- | --- | --- |
| W0：`.local/envs/whisper-w0-py312` | 3.12.15 | faster-whisper 1.2.1、CTranslate2 4.8.2；没有 Torch 包，CUDA DLL 由已核验 Torch 2.8.0+cu128 wheel 提供 | [requirements-w0.lock](../../experiments/whisper/requirements-w0.lock)；24 包，只有版本 pin |
| W1/W1-native：`.local/envs/whisper-latest` | 3.13.16 | WhisperX 3.8.6、faster-whisper 1.2.1、CTranslate2 4.8.2、Torch/torchaudio 2.8.0+cu128、torchvision 0.23.0+cu128、Transformers 4.57.6、pyannote-audio 4.0.7、torchcodec 0.7.0、NLTK 3.10.3 | [requirements-whisperx.lock](../../experiments/whisper/requirements-whisperx.lock)；104 包，只有版本 pin |
| Q0：`.local/envs/qwen-hf-final` | 3.13.16 | Torch 2.14.1+cu130、Transformers 5.18.0、Accelerate 1.15.0、nagisa 0.3.0、dyNET38 2.2 | [requirements.lock](../../experiments/qwen/requirements.lock)；62 包，逐包 SHA256 pin |
| Crisp：根 Python 包装原生程序 | 3.12.15 包装器 | CrispASR 0.8.41，Windows x86_64 Vulkan Release、MSVC 1951；源码 `340d7085eaa53c40a46dcb73a6d3d0448a480006` | `.local/tools/crisp/release.json`、`tree.json`、保存的 `diagnostics.txt` |

固定官方软件来源：[faster-whisper v1.2.1](https://github.com/SYSTRAN/faster-whisper/releases/tag/v1.2.1)、
[WhisperX v3.8.6](https://github.com/m-bain/whisperX/releases/tag/v3.8.6)、
[CTranslate2 v4.8.2](https://github.com/OpenNMT/CTranslate2/releases/tag/v4.8.2)、
[Transformers v5.18.0](https://github.com/huggingface/transformers/tree/v5.18.0)、
[CUDA 12.8 wheel 索引](https://download.pytorch.org/whl/cu128)、
[CUDA 13 wheel 索引](https://download.pytorch.org/whl/cu130)、
[Crisp v0.8.41](https://github.com/CrispStrobe/CrispASR/releases/tag/v0.8.41)。
访问日期与选用 WhisperX 4.x Transformers 的兼容理由，见
[Whisper](2026-10-04-whisper-execution.md)、[Qwen](2026-10-04-qwen-execution.md)、
[Crisp](2026-10-04-crisp-execution.md)的执行来源记录。

几个容易混淆的身份已在机器清单中单列：

- W0 的 `.local/tools/whisper-runtime-provisional/acquisition.json` 当前状态是 `verified`；
  11 个 DLL 此前已对照完整官方 wheel 逐项核验，目录名保留早期获取历史。
- Crisp ZIP 的官方 digest 为
  `146a38edb97a83fbc1b526e7767d3e25ab03bf6f4118c41342eda09abe9af6a0`；
  本机 EXE 与 DLL 的既有 SHA256 分别是
  `07dbe65c4adbea6e977bc0253d0991175cbd92ee871e5a5cf33ac4eda5303658`、
  `d346663c39948cef204db12768eb340003115af9e904e25979a00c44113878a2`。
- WhisperX 自带 VAD 位于安装包 `whisperx/assets/pytorch_model.bin`，17719103 字节，
  此次读取小型文件得到 SHA256
  `0b5b3216d60a2d32fc086b47ea8c67589aaeb26b7e07fcbe620d6d0b83e209ea`。
  `punkt_tab/english` 的四个文件也已单列 SHA256。
- Qwen `environment.json` 是 CPU preflight 快照，仍记录 `gpu_inference_tested=false`。
  当前三份 Transformers Qwen 源文件 SHA256 与快照一致，锁文件也一致；当前适配器
  `run_qwen.py` 已不同于 preflight 时版本。旧运行采用其各自保存的适配器 SHA256，
  当前源码 hash 不追认旧实验身份。

安装、字节完整性和版本相同只提供复现基础。ASR、aligner、VAD 的实际执行设备、
离线重载、耗时与显存仍以每次实验自己的设备和运行清单为证据。

## 许可记录边界

模型许可按上表固定模型卡记录。安装 metadata 分别记录 faster-whisper/CT2 为 MIT、
WhisperX 为 BSD-2-Clause、Transformers 为 Apache-2.0、nagisa 为 MIT、dyNET38 为
Apache-2.0；pyannote-audio 包内 LICENSE 为 MIT。Torch 2.8 metadata 记录 BSD-3-Clause，
2.14 metadata 列出多个 SPDX 组成许可，完整表达式保存在机器清单。

Crisp 源码的 [MIT 许可](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/LICENSE)
与具体模型许可分别记录；发行目录的 `THIRD_PARTY_NOTICES.txt` 保留第三方组件文本。
该文本还包含明确标为 Linux/GCC、Linux/ROCm 发行包的 OpenMP 说明，不能直接当作
本次 Windows Vulkan 包实际链接了这些 Linux 库的证明。
七组模型清单没有单列 WhisperX 内嵌 VAD 权重自身的许可来源；包许可与权重许可证据
应分别保留。本清单记录已提供的许可文本，没有审核后续整包再分发条款。

## 本机离线恢复入口

以下是恢复配方，本次清点未执行恢复。离线恢复需要已经存在的对应解释器、uv 缓存
wheel 和索引 metadata；复制缓存到另一台机器后的完整可用性尚未测试。
根工具链和离线检查入口为：

```powershell
uv sync --locked --offline
just test
just check
```

后端环境目录缺失时，以清单中的 `base_prefix/python.exe` 创建相应 uv 环境；已有环境
执行后面的 sync 行。W0 与 WhisperX 的锁文件只有版本 pin，Qwen 同时约束包 SHA256。

```powershell
$env:UV_CACHE_DIR = '.local/cache/whisper-w0-uv'
uv venv --offline --python .local/tools/python/cpython-3.12-windows-x86_64-none/python.exe .local/envs/whisper-w0-py312
uv pip sync --offline --python .local/envs/whisper-w0-py312/Scripts/python.exe experiments/whisper/requirements-w0.lock

$env:UV_CACHE_DIR = '.local/cache/whisper-uv'
uv venv --offline --python .local/cache/whisper-python/cpython-3.13.16-windows-x86_64-none/python.exe .local/envs/whisper-latest
uv pip sync --offline --python .local/envs/whisper-latest/Scripts/python.exe experiments/whisper/requirements-whisperx.lock --index https://download.pytorch.org/whl/cu128 --index-strategy unsafe-best-match

$env:UV_CACHE_DIR = '.local/cache/qwen-uv'
uv venv --offline --python .local/cache/whisper-python/cpython-3.13.16-windows-x86_64-none/python.exe .local/envs/qwen-hf-final
uv pip sync --offline --python .local/envs/qwen-hf-final/Scripts/python.exe experiments/qwen/requirements.lock --require-hashes --index-strategy unsafe-best-match
```

Crisp 可用已保存且已核验的 ZIP 恢复缺失的发行目录：

```powershell
Expand-Archive -LiteralPath '.local/tools/crisp/crispasr-windows-x86_64-vulkan.zip' -DestinationPath '.local/tools/crisp/v0.8.41-vulkan'
```

WhisperX 的 `punkt_tab` 需一同保留在 `.local/cache/whisper-nltk`。W0 的进程内 DLL 搜索目录
采用已核验的 `.local/tools/whisper-runtime-provisional`；不依赖全局 PATH 改动。
实际离线实验参数与各入口见上述后端文档；输入采用既有语料准备清单固定的 PCM 身份。

模型缺失时进入单独的网络获取阶段，固定 revision 和已保留的断点文件：

```powershell
uv run --no-sync python experiments/provision/acquire_models.py
uv run --no-sync python experiments/provision/range_models.py --model qwen3-asr-1.7b-hf --connections 4
uv run --no-sync python experiments/provision/range_models.py --model qwen3-forcedaligner-0.6b-hf --connections 4
```

同一模型的顺序下载和分块恢复应串行执行，遵循既有 `range-state.json` 的前缀和区间。
正常推理消费本地权重，不运行获取程序。恢复配方没有重新定义筛选规则或实验输入；
历史运行的有效配置、源码与输入身份继续以对应运行快照为准。
