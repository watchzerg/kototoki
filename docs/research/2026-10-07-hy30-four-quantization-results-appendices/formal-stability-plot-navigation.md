8 张新图均通过 1904×1462 原尺寸检查，没有文字裁切、空白面板或错配曲线。本次只读取已有图像和聚合元数据，未重新生成、安装、推理或修改原图。

最终报告使用下列四张正式 stability 图；其实际 attempt 均为 formal-stability-completion-v4。每张还包含单次预热、预算探针、load/unload 和资源释放，重复阶段请求计数单独列出。

| 候选／正式 stability 图 | 重复请求 | 重复阶段秒 | 会话采样最低空闲 MiB | 进程共享分配峰值 MiB |
| --- | ---: | ---: | ---: | ---: |
| [Q3_K_M 基线](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report/formal-stability-completion-v4-plots-v1/0004-stability-hy-mt2-30b-a3b-q3-k-m.png) | 1818 | 1800.191104 | 731 | 84 |
| [i1-Q3_K_M](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report/formal-stability-completion-v4-plots-v1/0005-stability-hy-mt2-30b-a3b-i1-q3-k-m.png) | 1979 | 1800.802432 | 731 | 84 |
| [APEX-I-Compact](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report/formal-stability-completion-v4-plots-v1/0006-stability-hy-mt2-30b-a3b-apex-i-compact.png) | 1936 | 1800.292145 | 255 | 84 |
| [i1-Q3_K_L](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report/formal-stability-completion-v4-plots-v1/0007-stability-hy-mt2-30b-a3b-i1-q3-k-l.png) | 1957 | 1800.109411 | 156 | 372 |

四个重复阶段共 7,690 个请求，均 delivered、无重试、CSV OOM=False，phase_finished 与 requested=1800 的实际时长均达到 1,800 秒；这些是重复固定块，不是新增质量样本。窗口首末 UTC span 略少于 1,800 秒（基线和 i1-L）不推翻 phase 墙钟达标，两个计时范围不能混用。图上约 30.8 分钟包括 idle/load/probe/unload，不应直接代替重复阶段时长。

图注可直接使用：四款正式冻结固定输入长跑的整卡已用显存、整卡空闲与进程共享 GPU 分配、GPU 利用率及逐窗请求耗时，统一按 UTC 对齐。橙色点为重复块，另色点为预热与预算探针。峰值和余量是有限采样而非模型独占或绝对安全余量；共享分配与速度不能证明 OOM、物理 paging 或 CPU fallback。探针点可能位于图例下方，精确值见窗口 CSV；精细尾段结论采用独立 terminal 审计，不以图中视觉密度代替检验。

继承 preflight 附图（不是新的长跑，元数据与旧 28 图中的同一 attempt 完全一致；标题和本地 curve 编号改变，PNG SHA 因而不同）：

- [0000-preflight-hy-mt2-30b-a3b-q3-k-m.png](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report/formal-stability-completion-v4-plots-v1/0000-preflight-hy-mt2-30b-a3b-q3-k-m.png)；对应旧图 0008-preflight-hy-mt2-30b-a3b-q3-k-m.png。
- [0001-preflight-hy-mt2-30b-a3b-i1-q3-k-m.png](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report/formal-stability-completion-v4-plots-v1/0001-preflight-hy-mt2-30b-a3b-i1-q3-k-m.png)；对应旧图 0009-preflight-hy-mt2-30b-a3b-i1-q3-k-m.png。
- [0002-preflight-hy-mt2-30b-a3b-apex-i-compact.png](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report/formal-stability-completion-v4-plots-v1/0002-preflight-hy-mt2-30b-a3b-apex-i-compact.png)；对应旧图 0010-preflight-hy-mt2-30b-a3b-apex-i-compact.png。
- [0003-preflight-hy-mt2-30b-a3b-i1-q3-k-l.png](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report/formal-stability-completion-v4-plots-v1/0003-preflight-hy-mt2-30b-a3b-i1-q3-k-l.png)；对应旧图 0011-preflight-hy-mt2-30b-a3b-i1-q3-k-l.png。

图像、冻结 plotter 和三份聚合输入 SHA 均校验匹配 plot-identity.json；8 个 curve 对应唯一 attempt/task/candidate，7,706 条窗口行全部且仅映射一次，30,276 条资源行有对应曲线。详见 qa.json、visual-inventory.csv、release.json 与 evidence-sha256.json。

原 28 图及质量摘要 v2 不变；本目录图编号与旧目录图编号不互换。新 8-run 聚合的 performance not_run 仅表示未继承性能分支，不覆盖先前真实的 16 个性能轮次状态。完整调度结论须联合原性能分支与本正式 stability 分支。
