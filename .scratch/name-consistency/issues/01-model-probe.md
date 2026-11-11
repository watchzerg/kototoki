# 01 建表模型探针：下载 Qwen3.8-27B UD-IQ3_S 并加载一次

Status: resolved
Type: research

## Answer

- 2026-10-19 用户授权后下载 `unsloth/Qwen3.8-27B-GGUF` revision `4ca720788d1e01f1bff70c033e0d0028fd02e502` 的 `Qwen3.8-27B-UD-IQ3_S.gguf`（12,040,883,104 字节，sha256 `d847e2c1…7f3864` 与 hub LFS 一致，80 s），清单 `.local/models/glossary-v1/qwen3.8-27b-ud-iq3_s-ready.json`。
- b11669 `llama-server.exe` 能加载（`qwen35` 架构，`blk.64.nextn.*` MTP 张量被忽略），加载 5.6–6.6 s（文件在系统缓存中）。支持 `--reasoning off|on`、`--reasoning-budget`、`--chat-template-kwargs`。
- 显存：桌面基线 1109–1123 MiB；`-c 16384` 峰值 13371 MiB，`-c 20480` 13631 MiB，`-c 24576`（think）13884 MiB。余量约 2.4 GB，**IQ3_S 可用**，不必退 IQ3_XXS。
- 吞吐：提示 2024 tok/s（13.7K tokens 约 6.8 s），生成 51–53 tok/s。
- 失败教训：① 贪心（temperature 0）在 `ja_variants` 里陷入"遠坂を…"无限重复直到 16K 上下文耗尽；改用 Qwen 官方 non-thinking 采样（0.7／0.8／20／presence 1.5）并加 JSON schema（maxItems）后正常。② 16K 上下文不够（提示 13.7K ＋ 输出 4K），no-think 用 20K；think 模式思考会吃光 4096 输出预算，改 `max_tokens 8192`、`-c 24576`、`--reasoning-budget 4096` 后四部均成功，每部 110–145 s（no-think 36–49 s）。
- 产物：`.local/name-consistency/01-probe/`（探针 JSON、server 日志、首版表）。

## 背景

[方向讨论记录 §4](../../../docs/research/2026-10-19-name-consistency-direction.md) 选定 `unsloth/Qwen3.8-27B-GGUF` 的 `UD-IQ3_S` 作建表模型；b11669 对 `qwen35` 架构的支持与 12K 提示下的峰值显存都未在本机验证。

## 范围

1. 下载 `Qwen3.8-27B-UD-IQ3_S.gguf`（约 12.0 GB）到 `.local/models/glossary-v1/`，记录 revision 与文件 sha256，写 `ready.json`（形式同 `.local/models/embedding-v5/bge-m3-ready.json`）。**下载前须用户批准。**
2. 用 `.local/tools/llama.cpp/b11669-cuda13.4/llama-server.exe` 加载：`-ngl 99`、`-c 16384`、单槽、`--jinja`、no-think（按 Qwen3.8 模板的开关），flash attention on，KV f16。
3. 喂 02 的建表提示（HF III w0 的 `ja.srt`，剥时间轴、带 cue 编号，约 12K tokens），记录：是否加载成功；提示处理与生成的 tok/s；整卡峰值显存（`nvidia-smi` 轮询）；输出是否为合法 JSON、是否连贯（无乱码即排除 DeltaNet CUDA 旧 bug）。
4. 若 OOM 或峰值加 0.5 GB 余量超过 16 GB：改 `UD-IQ3_XXS` 重做第 3 步；不改用 IQ2_M。

## 约束

- GPU 作业与下载都先问用户；运行前核对无 `.local/gpu.lock`、无其他 llama／python 进程。
- 不改产品代码，不进 `assets.toml`（研究资产）。

## 完成标准

- `ready.json`；探针记录（峰值显存、tok/s、一次完整输出样例）写入研究文档或本票执行记录。
- 明确结论：IQ3_S 在本机"可用／须退到 IQ3_XXS"。

## Blocked by

- 02 的建表提示要先有草稿（可并行，提示文本不依赖模型）。
