# 地图

## 接跑手册（每次启动从这里开始）

1. 读[研究文档](../../docs/research/2026-11-08-strata-flash-next-v12.md) §7，找到第一张未 resolved、且 Blocked by 全部 resolved 的票据，再读它的 `## 执行记录`。**状态以文件为准**，不信文档里声称正在跑的内容。
2. GPU 票据已获用户授权无人值守执行，预算以研究文档 §5 为上限（含阶段 E：10 run／$115）。开跑前只做只读核对：
   - PowerShell `Get-Process | ? ProcessName -match 'llama|python|strata'`；
   - `nvidia-smi`；
   - `strata launch --status`；
   - 读 `.local/gpu.lock`。
   锁被存活 PID 持有，或者有来历不明的 llama-server／Strata 实例时，不启动、不杀进程，转做离线票据。
3. Strata 只按调研 §3 的 `kototoki-translate` 参数启动。先跑 `--plan`，下载量不为 0 就停下，写进 §8；不运行 `strata update`。票据结束后执行 `strata launch --stop`，并核实显存已释放。
4. Q1 对照复用 `.local/q0-product-route-v11/` 中的产物，只读。产品 Q1：`C/zh/q0-names-high/`，seed 54–56；dev Q1：`runs/qwen-names-dev-high__s*__dev`，本轮须同期重判。
5. 送裁判前先 diff 两臂文本，相同的单元不判，按 Δ＝0 计入。裁判（`claude -p`）退出码 75 表示配额耗尽：不要循环重试，转离线票据；没有可做的就停下，并写明停在哪里。
6. 预算台账写在下方 Notes；某阶段超限即结束该阶段。
7. 每完成一张票据，依次做：
   1. 票据写 Answer 并标为 resolved；
   2. 本文 Decisions-so-far 加一行；
   3. 更新研究文档 §7；
   4. 提交 Git。
8. 需要用户裁定的事项写进研究文档 §8，不中途停下来问。不新增方向。
9. 在 Windows 上用 Python 写文件，一律 `newline='\n'`。

## Notes

- 预算台账：GPU run 7／10（C 4／4、D 3／3；另 smoke 2 次）；裁判 $65.63／$115（C $57.56／$65、D $8.07／$15）。

## Decisions-so-far

- 2026-11-08 立项：用户裁定按 §5 立项，含阶段 E（有界思考，C、D 至少非劣时触发）。旧 gpu.lock（pid 35460，已死）已按用户指示删除。
- 2026-11-08 01 resolved：Strata 附着后端（`translation_v3/strata.py`）、F1 `60bd457f…`（产品 `a2075b25…`）、F2 `903d1cad…`、`--round v12`；旧 hash 不变；reasoning 计数改读 server log；Strata 配方失败包只丢自己的 cue；smoke 取 v11 smoke 的 2 剧集＋1 电影整场。
- 2026-11-08 02 停：`--plan` 显示 MTP 草稿层需下载 5.2 GB（本机无 `mtp/`，有 DFlash2 草稿器）；未启动 Strata，GPU 0；写入研究文档 §8 第 4 项等用户裁定。03–06 均被 02 阻断。
- 2026-11-08 用户裁定 §8 第 4 项 (a) 允许下载 MTP；02 resolved：可行性门通过（90 包首次格式失败 0、交付失败 0、思考全空、无非有限 logits），每包约 3.2 s，A/A cue 不同 44%，整机内存峰值 63.5 GiB；Strata 已停、显存已释放。
- 2026-11-08 03 resolved：F1 对 Q1 dev 两类 accuracy 都显著改善（剧集 −0.186、电影 −0.126），wrong-referent 下界 ≤0；交付失败 0，首次失败 1／621（Strata 重复截断）；墙钟快约 29%；A/A cue 不同 49%；GPU 4、裁判 $57.56。进 D。
- 2026-11-08 04 resolved：产品全体 −0.269［−0.340, −0.201］、三桶都显著改善、交付失败 0、不一致率 0.0175 对 0.0273；人名错误 79 对 89 但差 CI90 上界 +0.0006 >0，按字面门未过 → §8 第 6 项；E 按字面不触发。GPU 3、裁判 $8.07。
- 2026-11-08 05 resolved（不触发：D 按字面未达非劣）。06 resolved：结题，§7.1／§8／索引已写。合计 GPU 7／10（另 smoke 2 次）、裁判 $65.63／$115。
- 2026-11-08 用户裁定 §8 第 6 项 (b)：人名错误一条视为边界噪声，F1 改判为"优于 Q1，作为 Q 线新基线候选"；E 不补跑；基线仍是 Q1，换基线另写 ADR。
