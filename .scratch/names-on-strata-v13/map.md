# 地图

## 接跑手册（每次启动从这里开始）

1. 读[研究文档](../../docs/research/2026-11-08-names-on-strata-v13.md) §7，找到第一张未 resolved、且 Blocked by 全部 resolved 的票据，再读它的 `## 执行记录`。**状态以文件为准**，不信文档里声称正在跑的内容。
2. GPU 票据（02、04、05）已获用户授权无人值守执行，预算以研究文档 §5 为上限（13 run／$80）。开跑前只做只读核对：
   - PowerShell `Get-Process | ? ProcessName -match 'llama|python|strata'`；
   - `nvidia-smi`；
   - `strata launch --status`；
   - 读 `.local/gpu.lock`；
   - 可用内存 ≥52 GiB。
   锁被存活 PID 持有、有 llama-server 或来历不明的 Strata 实例、内存不够时，不启动、不杀进程、不关用户程序，转做离线票据；没有可做的就停下并写进 §8。
3. Strata 只用 `strata launch --no-tui --model iq3_s`（Q2 启动方式）。先跑 `--plan`，下载量不为 0 就停下写进 §8；不运行 `strata update`；不启动 llama-server。启动后确认专家区全部锁进内存（退到 mmap 即停）。票据结束后执行 `strata launch --stop`，并核实显存已释放。
4. 对照的 27B 表只读复用：产品 `.local/name-consistency-product/after/{HF-II,HF-III}/name-table.json`，dev `.local/q0-exploration-v10/E/dev-name-tables.json`。本轮不用 27B 重新建表。
5. 送裁判前先 diff 两臂文本，相同的单元不判，按 Δ＝0 计入。裁判退出码 75 表示配额耗尽：不要循环重试，转离线票据；没有可做的就停下，并写明停在哪里。
6. 预算台账写在下方 Notes；某阶段超限即结束该阶段。
7. 每完成一张票据，依次做：
   1. 票据写 Answer 并标为 resolved；
   2. 本文 Decisions-so-far 加一行；
   3. 更新研究文档 §7；
   4. 提交 Git。
8. 需要用户裁定的事项写进研究文档 §8，不中途停下来问。不新增方向。
9. 在 Windows 上用 Python 写文件，一律 `newline='
'`。

## Notes

- 预算台账：GPU run 15／15（B 3、D 6、E 6）；裁判 $62.52／$80。

## Decisions-so-far

- 2026-11-08 立项：用户裁定按 §5 立项（重开专名研究线由用户明确要求）。
- 2026-11-08 01：离线实现完成；S1 `91671bd9…`；研究侧 probe 默认分支改读服务日志判断 DFlash2；Strata 启停复用产品 `StrataServer`＋开跑前核对。
- 2026-11-08 02：可行性门不过（HF-III 两次 length 截断 failed；首次失败 5／17，全是 4096 token 截断，无解析失败）；按 §4.2 停，03–05 不跑。
- 2026-11-08 06：结题，S1＝不进（输出上限截断）；修复候选写 §8 第 4 项。
- 2026-11-08 用户裁定 §8 第 4 项 (a)：S1 改为 v2（`max_tokens` 8192、context 24576，`eb4b1c6d…`），产物在 `B2/`；B 预算 2；票据 02–06 重开，从 02 重跑。
- 2026-11-08 02 重跑（v2）：仍不过门（5／25 请求写满 8192 失控、2 个 JSON 语法错；W11 failed；首次失败 6／17）；B 预算用完，停；06 结题，S1＝不进（无约束解码）。
- 2026-11-08 用户要求补试 v3（`response_format`＋5 次，`61e092bf…`）与 v4（5 次，`38cb7bcd…`）；B 预算 3；票据 02–06 重开。
- 2026-11-09 02 补跑：v3 首次失败 6／17、v4 4／17，两臂 5 次内都全部 ok；按字面不过门，§8 第 8 项等用户裁定是否放行 v4。
- 2026-11-09 结题：S1 不进；02、06 resolved，03–05 wontfix（被 B 阻断）。用户若放行 v4（§8 第 8 项），把 `CANDIDATE` 改为 v4、重开 03–06。
- 2026-11-09 用户裁定 §8 第 8 项 (a)：放行 v4，`CANDIDATE = "v4"`；03–06 重开。
- 2026-11-09 03：v4 dev 表非劣（一致率 Δ +0.054 [−0.032, +0.132]，high 不一致 Δ −0.046 [−0.121, +0.033]），不阻断；进 04。
- 2026-11-09 04：dev 不过非劣（剧集 wrong-referent +0.042 [+0.021, +0.067]；电影 accuracy −0.049 显著变好）；D、E 互不阻断，继续 05。
- 2026-11-09 05：产品全体 Δ −0.095 [−0.159, −0.031]；门按字面因对照 6 cue 交付失败不过（候选 0）。
- 2026-11-09 06：结题，S1＝不进（dev 剧集 wrong-referent 变差＋建表不稳定）；建表维持 27B。
