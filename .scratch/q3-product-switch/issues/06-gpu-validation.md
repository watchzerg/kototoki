# 06 GPU 验证：just smoke names_product 与 HF-II 整片

Status: resolved
Type: task
Blocked by: 05

范围、终点与门见计划 §4 第 6 张票据（docs/plans/product-names-on-strata.md）。

- 授权与开跑前核对见计划 §5。
- 整片用全新工作目录与输出位置（`.local/q3-product-fullfilm/`），源文件旁不得有 `ja-zh.srt`。

## 执行记录

- 2026-11-09 12:04–12:14 开跑前核对（只读）：`Get-Process` 无 llama-server、无 strata、无 python／ffmpeg；`nvidia-smi` 空闲显存 15089／16303 MiB，无计算进程；`.local/gpu.lock` 不存在；`strata launch --status --output json` 为 `running: []`；`strata launch --no-tui --model iq3_s --plan` 显示“Nothing to download”（模型已在本机，与 ADR-0017 的默认启动同形）。
- 可用内存（`Win32_OperatingSystem.FreePhysicalMemory`，与产品 `available_ram_gib` 的 `ullAvailPhys` 同源）为 **50.5 GiB**，低于门 52 GiB；按计划 §5 等候，每分钟采样一次，12:05–12:14 共 10 次均为 50.5–50.6 GiB，无上涨趋势。占用分解：进程 working set 合计 8.4 GiB（最大单个 0.35 GiB，无 vmmem）、committed 13.9 GiB、内核池 4.2 GiB（paged 3.0＋nonpaged 1.2）；Hyper-V（`HvHost`／`vmcompute`）在运行。2026-11-08 两次通过的运行启动前可用 54.2／54.3 GiB，本次差约 1.5 GiB，而 11-08 的记录表明差 1.26 GiB 即退到 mmap。
- 按 §5“仍不够就停下，写进 §8”与“不关用户的程序”：没有运行 `just smoke names_product` 与整片，没有启动 Strata。写进计划 §8 第 2 条。

- 2026-11-09 20:27 用户重启机器后重跑：开跑前可用内存 53.7 GiB、空闲显存 14977 MiB、无 llama-server／Strata／GPU 作业、无 `gpu.lock`、`--plan` 无下载。`just smoke names_product`（`.local/smoke/20261109T122829Z/`）**通过**，87.5 s：Strata 启动后 `expert_arena` 为 `ram`、drafting `dflash2`、kv `int8`；`count_tokens` 可用（`prompt_check: count_tokens`）；建表第 1 次即 `ok`（5.9 s，提示 1655／输出 299 token），2 条均为 person、置信度非 high，注入行 0（只记录）；表对身份 current；全程无 llama-server 进程；整机显存峰值 16007 MiB、内存峰值 61.1 GiB；`--stop` 后 status 为空、空闲显存 14977 MiB。
- HF-II 整片（`python -m kototoki`，W0，全新 `.local/q3-product-fullfilm/`，源文件经硬链接放入新 input 目录、旁边无 `ja-zh.srt`）**通过**，墙钟 1014.8 s、退出码 0：extract 17.2 s、vad 74.7 s、asr 174.7 s、align 87.4 s（1 个窗口 CTC 目标过长的既有告警）；**names 阶段首次启动 Strata**（ready 78.1 s，`expert_arena` 为 `ram`，引擎日志 VirtualLock 3502 MiB＋45 片 pinned 43 GiB），建表第 1 次失败（seed 20261019，回复 JSON 数组末尾多逗号，7879 输出 token，55.1 s），第 2 次 `ok`（seed 20261020，48.6 s）：25 条（person 10、class 4、org 2、place 2、other 7；high 20、medium 5），归一丢弃 74（shape 64、ja_shape 10），提示 13240／输出 7766 token，建表共 103.8 s，names 阶段 182.0 s；**translate 沿用同一 session、未重启**：149 包 462.0 s，每包均值 3.10 s（p50 3.20、p90 3.70、最大 4.00 s，约 146 tok/s，输出约 178 token），149 包全部首次接受，重试、降级、回退、思考输出均为 0，144 包带注入行（20 条 high 条目展开为 44 行），`cache_n` 全为 0；整机显存峰值 16099 MiB、内存峰值 60.8 GiB；`--stop` 后 status 为空、空闲显存 15059 MiB，GPU 锁释放；`ja.srt` 与发布的 `ja-zh.srt` 各 1099 条、`ja-zh` 全为两行；`published.json` 的 names 来源 recipe_hash `d3317926…`、translate 的 `names_sha256` `e3733fce…`。
- 运行后核实：`strata launch --status` 为空，空闲显存 15059 MiB，`gpu.lock` 不存在，无 llama／strata 进程。结果写入计划 §7、ADR-0022 未验证节、专名一致性／批次编排／翻译子系统模块页、开发工作流 smoke 说明。

## Answer

完成（第二次执行通过）。第一次因内存门未过停下：
未执行（blocked）。GPU 门未过：等满 10 分钟可用内存仍为 50.5 GiB（< 52 GiB），其余核对项全部通过、无需下载。待用户腾出内存后重跑本票据（命令与通过条件不变）。
