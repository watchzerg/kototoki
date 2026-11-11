# 地图

## 接跑手册（每次启动从这里开始）

1. 读[研究文档](../../docs/research/2026-10-22-q0-product-route-v11.md) §7 进度，找到第一张未 resolved 且 Blocked by 已全部 resolved 的票据；读它的 `## 执行记录`。**状态以文件为准**，不信任文档声称在跑的内容。
2. GPU 票据已获用户授权无人值守执行，预算以研究文档 §5 的表为上限。启动前只读核对 GPU：PowerShell `Get-Process | ? ProcessName -match 'llama|python'`、`nvidia-smi`，读 `.local/gpu.lock`。锁被存活 PID 持有、或有不明 llama-server 时不启动、不杀进程，转离线票据。
3. Qwen 臂走 `translation_v3/qwen.py`（`kototoki.llama_server`，官方 b11669）。dev 走 `scene_batching_v6` 驱动，产品整片走 `translation_v3 translate-srt`（`--work-id`），产品评测走 `asr10.py`（本轮参数化根目录与 seed）。v10 的脚本模板在 `.local/q0-exploration-v10/logs/`（`gen-queue.sh`、`judge-queue.sh`、`d-translate.sh`）。
4. dev 比较必须同期重判对照；产品配对裁判同 packet 比较，不需重判。**送裁判前先 diff 两臂文本**，相同的单元不判（Δ＝0）。
5. 裁判（`claude -p`）退出码 75 = 配额耗尽：不循环重试；转离线票据，没有可做的就停下，在票据执行记录与研究文档 §7 写明停在哪里。
6. 预算台账写在下方 Notes；阶段超限即结该阶段。
7. 每完成一张票据：票据写 Answer 并 resolved → 本文 Decisions-so-far 加一行 → 研究文档 §7 更新 → 提交 Git（研究文档、INDEX.md 与 `experiments/` 下本轮代码；不提交 `.claude/settings.json`）。签名失败不绕过，记研究文档 §8 第 0 项。
8. 需要用户裁定的事项写研究文档 §8，不中途停下来问。本轮不新增方向。
9. Windows 上用 Python 写文件一律 `newline='\n'`；Bash heredoc 会把 `\n` 变成真换行，含转义的代码改用 Edit 工具。

## Notes

- 预算台账：GPU run 16／19（C 12 个臂 run＋dev 护栏 1 全部生成）；裁判标价 $85.45／$125。按阶段：B 3／3（$57.76／$70，结束）、C 12／12＋1（$27.69／$40：06 $5.97、07 $5.74、08 $6.19、dev 护栏 $9.79，结束）、D 0／3（$0／$15，09 不触发）。短会话：smoke 1（`qwen-names-dev-high`）。

- 执行注记（16:20）：Windows 上 Claude Code 的 TaskStop **杀不掉** Git Bash 后台脚本（`Get-CimInstance Win32_Process` 核实：`c-chain.sh`、`c-chain2/3/4.sh`、`judge-chain.sh` 全部存活），2 h 上限也没有真的结束 `c-chain.sh`——它自己在 16:16 跑起了 seg10 dev 护栏。无法杀进程（权限拒绝），改为让重复步骤无害：`c-translate.sh` 顶部加 `logs/NO-GAPFILL` 标记即退出（避免 seg10 HF-II s56 部分交付被重跑成第 13 个 C run）；`asr10.judge` 加每比较一把 `ProcessLock`（`judge/<name>/.lock`，活锁即退出 0），两条裁判链谁先到谁判，另一条顺延到下一步；dev `judge-run` 本来就有 `judge_lock`；`generate` 对已完成 run 会直接复用（重复的 `gen-queue seg10:20261011` 只是空转）。
- 执行注记：后台命令有 2 h 上限，`c-chain.sh` 在 14:45 被截断（正在跑的 translate-srt 子进程未受影响、持锁跑完）；被截断的 `c-chain.sh` 的子进程 `c-translate.sh` 其实仍在继续跑并写 `c-chain.out`（14:52 仍有新行），`c-chain2.sh` 会与之竞争锁，已在起跑前停掉；改用 `c-chain3.sh`：等 `c-chain.out` 出现 18 条臂影片记录（成功与否）且无 `gpu.lock` 后，再跑一遍 `c-translate.sh` 补缺（跳过已有输出），然后 seg10 dev 护栏生成。

## Decisions-so-far

- 2026-10-22 立项：用户裁定不读盲读表、简报不进；注入、ASR 提示叠加、跨段截断补测。
- 2026-10-23 [01 离线实现](issues/01-offline-impl.md)：跨段截断＝`wide_context.silence_gap`（`wide-context-v2`，旧 hash 不变，`seg10` hash `14fef2f7…`）；N\* 修订开关＝`names.filter: "targets"`＋v2 表头；产品 diff＝`plan(skip_identical)`＋Δ＝0 计入；dev diff＝复制全同包判分＋`compare11` 相同 cue Δ＝0；`--round v11` CLI；测试 9 项新增。
- 2026-10-23 [02 诊断](issues/02-names-diagnosis.md)：新增错误 39 cue 中 (a) 表条目错 22、(d) 14、(b) 2、(c) 1 → N\*＝v1 注入＋只注入 `confidence: high`（dev `qwen-names-dev-high` `9c444d3c…`、产品 `q0-names-high` `c10e143a…`）。警示：(a) 的 22 个里 19 个所涉条目是 high，high 条目 34% 与参考多数不一致——修订预计难消除 dev 反向；表质量问题同样影响产品替换（§8）。
- 2026-10-23 [03 截断离线统计](issues/03-seg-offline.md)：G＝10 s 影响产品 90.2% 的包（前邻文 19.6→6.7、后 5.0→2.5）、dev 61.4% → 08 截断臂照跑、dev 护栏（1 seed）适用。
- 2026-10-23 [04 B 护栏](issues/04-names-dev-guard.md)：**门未过**。对照 Q0 同期重判，N\* 3 seed accuracy 剧集 +0.043［+0.002, +0.085］、电影 +0.070［+0.028, +0.112］，电影 wrong-referent +0.062，人名错误 97 对 87；不一致率 0.017 对 0.038。N\* 入 C 只作"ASR 源专用"，§8 标风险。dev 两臂相同 cue 44%，但无整包全同，裁判费省不了。GPU 3、裁判 $57.76。
- 2026-10-23 [05 Q0 产品对照](issues/05-q0-product.md)：6 run 全交付（约 560 s/部），替换链生成（改 92 处）；不一致率 Q0 0.051、Q0＋替换 0.050。GPU 3。06／07／08 的 GPU 臂已按链排队（`logs/c-chain.sh`）。
- 2026-10-23 [06 N\* 产品](issues/06-names-product.md)：**门通过**。对照 Q0＋替换，全体 Δ −0.050［−0.116, +0.020］（非劣，非"改善"），人名错误 120→72（差 CI90 ［−0.036, −0.020］），不一致率 0.027 对 0.050；heavy 桶上界 +0.160 不确定。相同单元 713／1728 不判，裁判 $5.97。与 dev 反向相反：产品表比 dev 表干净。
- 2026-10-23 [07 N\*＋ASR 提示](issues/07-names-asr-product.md)：**门未过**。对照 N\*，全体 +0.008［−0.048, +0.065］，exact +0.111［+0.049, +0.175］显著变差，heavy −0.140［−0.290, −0.003］改善，人名错误 77 对 79；与 v10 的 ASR 提示同形（用 exact 换 heavy）。相同单元 765／1728 不判，裁判 $5.74。
- 2026-10-23 [08 seg10 跨段截断](issues/08-seg10.md)：**不进**。对照 Q0，全体 +0.104［+0.041, +0.167］，受影响单元 +0.103［+0.031, +0.173］，heavy +0.280，人名错误 102→120，不一致率 0.073 对 0.051；dev 护栏剧集 wrong-referent +0.042［+0.009, +0.078］未过。副产物：未受影响单元（prompt 相同）仍有 24% 输出不同——同 seed 不确定，写 §8。裁判 $6.19＋dev $9.79。
- 2026-10-23 [09 组合检查](issues/09-combo.md)：不触发——C 阶段只有 N\* 一个成分过门（07、08 未过），§4 的"≥2 个成分"条件不满足；D 阶段 GPU 0、裁判 $0。
- 2026-10-23 [10 结题](issues/10-wrap-up.md)：§7.1 与候选清单写毕——唯一候选 N\*（产品 ASR 源专用）；§8 第 1（新基线 a/b/c）、2、3、4、5（同 seed 不确定、A/A）、6 项交用户；索引登记；文档 concluded。预算合计 GPU 16／19、裁判 $85.45／$125。

## Fog

- 02 的四类划分在部分 cue 上可能难分；执行者写明判据，拿不准的单列。
