# 地图

## 接跑手册（每次启动从这里开始）

1. 读[研究文档](../../docs/research/2026-11-09-asr-robustness-v14.md) §7，找到第一张未 resolved、且 Blocked by 全部 resolved 的票据，再读它的 `## 执行记录`。**状态以文件为准**，不信文档里声称正在跑的内容。
2. GPU 票据（01 的 HF III 重算、02、03、04）由用户立项时授权无人值守执行，预算以研究文档 §5 为上限（6 run／$5）。开跑前只做只读核对：
   - PowerShell `Get-Process | ? ProcessName -match 'llama|python|strata'`；
   - `nvidia-smi`；
   - `strata launch --status`；
   - 读 `.local/gpu.lock`；
   - 04 另核可用内存 ≥52 GiB。
   锁被存活 PID 持有、有 llama-server 或来历不明的 Strata 实例、内存不够时，不启动、不杀进程、不关用户程序，转做离线票据；没有可做的就停下并写进 §8。
3. CT2／torch 作业（01、02、03）持 `.local/gpu.lock`，不与 Strata 同时运行。04 只用 `strata launch --no-tui --model iq3_s`，先 `--plan`，下载量不为 0 就停下写进 §8；不运行 `strata update`；不启动 llama-server。启动后确认专家区全部锁进内存（退到 mmap 即停）。结束后 `strata launch --stop`，核实显存已释放。
4. 对照只读复用：HF II `.local/q3-product-fullfilm/work/input-7c924c80249b/8d2f3e76dd0c/`；参考 `hf-{ii,iii}-full.json`；基线评分 `.local/quality-exploration-v5/01/eval/product-w0-hf-{ii,iii}.json`。HF III 缺产品形状 STT 产物时按 §2.2 用产品 worker 重算，重算 CER 须与 13.77% 逐项相同。
5. 门与"不做的事"以研究文档为准（§4.0、§5）。不换模型、不改 VAD 参数、不对正常窗口重解码、不多次解码再挑选。
6. 预算台账写在下方 Notes；某票据超限即用已有数据写结论。
7. 每完成一张票据，依次做：
   1. 票据写 Answer 并标为 resolved；
   2. 本文 Decisions-so-far 加一行；
   3. 更新研究文档 §7；
   4. 提交 Git（签名失败不绕过，记 §8 第 0 项）。
8. 需要用户裁定的事项写进研究文档 §8，不中途停下来问。不新增方向。
9. 转写、参考字幕、校正输出不进 Git 与日志，只记计数与指标。在 Windows 上用 Python 写文件，一律 `newline='\n'`。

## Notes

- 预算台账（终值）：GPU run 4／6（01 HF III 重算，02 A2 补解＋align，04 Strata session × 2：v1、v2）；Opus 估算 <$2／$5（两次 30 条抽看）。

## Decisions-so-far

- 2026-11-09 起草：主会话起草研究文档与本骨架，待用户裁定立项（§8 第 1、2 项）。
- 2026-11-09 立项：用户裁定按 §5 立项（§8 第 1、2 项已裁定），研究文档改 planned，调研索引时间线登记；无人值守开始执行 01。
- 2026-11-09 01：输入核实通过（HF II 身份与 16.81% 逐项相同；HF III 重算 13.77% 逐项相同，GPU 1）。A0：无触顶窗，whisper-or 只标 II 1／III 2 窗，heavy 窗是漏转不是重复；B0：空子段覆盖 9.8% 的删除（<15%），**B1 不跑**，03 wontfix。[票据](issues/01-offline-signals.md)
- 2026-11-09 02：A1 置空 II 0／III −41 编辑（whisper-or），A2 补解 II 0／III −38（第 51 窗循环补解成 38 字，短窗不变）；三规则与 A2 都不过“两部都降”，**A＝不进**。[票据](issues/02-guard.md)
- 2026-11-09 04：C 两个 Strata session（v1、v2 提示）。单元口径：v1 C1／C2 与 v2 C1 都不过（一升一降或两升）；v2 C2（有表＋收紧提示）II −12／III −32 编辑，两部都降但合计 0.20 pp <0.3 pp，**C＝有效但不够**。Opus 抽看：收益几乎全是专名／同音修正，改坏多为改写与残片处理。[票据](issues/04-llm-correction.md)
- 2026-11-09 05：结题。A 不进、B 不进、C 有效但不够；§7.1 答 §3 四问，§8 追加第 0、4–11 项（A2 进入条件表述、B0 口径、C 收窄想法、专名表来源、费用口径、剩余预算）；研究文档 concluded，调研索引登记。[票据](issues/05-close.md)

## Fog

- （已清）HF III 产物不在盘上，01 已用产品 worker 重算并核对。
- （已清）子段秒坐标与 unit 时间口径一致（间隙字 1.7%／2.4%）。
- B1 补解文字如何并入窗口段才能让 `align` 与 cue 阶段不变地消费（§4.2 留给执行者定）。
