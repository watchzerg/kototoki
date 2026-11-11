# 05 C：Q0 产品对照（seed 20261054–56）＋替换

Status: resolved
Type: GPU
Stage: C
Blocked by: 01

范围、终点与门见研究文档 §4／§5（docs/research/2026-10-22-q0-product-route-v11.md）。

## 执行记录

- 2026-10-23 12:31 开工：B 的 GPU 生成已结束（s13 裁判仍在跑，仅 CPU）；GPU 859 MiB、0%，无 gpu.lock。`c-translate.sh "qwen-wide" "20261054 20261055 20261056"`（`logs/c05-translate.out`，每部每 seed 一个 `C/logs/qwen-wide.<film>.s<seed>.out`）。
- 6 个整片 run 12:31–13:27 全部 exit 0，墙钟 HF-II 565／557／560 s、HF-III 558／559／558 s（v10 D0 的 Q0 为 561 s/部）；`product failures`：6 run 交付失败 0 条（v10 曾有末尾换行判部分交付的情况，本轮没有）。
- `product replace --arms qwen-wide` → `C/zh/qwen-wide+rep/`（`apply_table` 默认参数＋产品 `name-table.json`），每 run 改动 cue 数 18／21／17（HF-II）、14／10／12（HF-III），合计 92。
- 整片不一致率（`C/inconsistency-05.json`，`apply_table measure` 口径）：**Q0 0.051**（HF-II 0.080／0.000／0.070，HF-III 0.032／0.092／0.032）、**Q0＋替换 0.050**（0.091／0.000／0.081、0.000／0.094／0.033）——与 v10 一样，替换几乎不降低该指标（v10：0.047 → 0.050），因为替换只改表里有的写法，个别 run 替换后反而升高（替换把部分写法统一后，剩下的少数派占比变化）。
- 对照材料就绪：06／07 用 `qwen-wide+rep`（Q0＋替换，产品等价链）作 x，08 用 `qwen-wide` 作 x。
- 代价：GPU 3 run（C 3／12）；裁判 $0。

## Answer

Q0 三 seed 整片 6 run 全部交付（失败 0，墙钟约 560 s/部），替换链已生成；不一致率 Q0 0.051、Q0＋替换 0.050（替换共改 92 处）。对照材料就绪。
