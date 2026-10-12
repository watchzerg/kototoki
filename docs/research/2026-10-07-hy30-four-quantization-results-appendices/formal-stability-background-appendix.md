# 四款 formal stability 完整后台重叠核算

实际主 runner session44736 exit0，主代理观察 tool chunk1b0be1；最后 scheduler completed 为 2026-10-07T06:39:00.423940UTC。本附录仅分析已保存 metadata，不新增 inference、裁判、sampler 或系统查询。

| 候选 | monitor start/end UTC | CLI union 重叠秒 | reservation 重叠秒 | 请求交叠数/peak |
|---|---|---:|---:|---:|
| baseline | 2026-10-07T04:32:13.266067+00:00 / 2026-10-07T05:02:58.941999+00:00 | 1289.578652 | 1411.825250 | 408/6 |
| i1m | 2026-10-07T05:03:57.272970+00:00 / 2026-10-07T05:34:43.007963+00:00 | 0.000000 | 0.000000 | 0/0 |
| apex | 2026-10-07T05:35:45.349257+00:00 / 2026-10-07T06:06:29.850563+00:00 | 0.000000 | 0.000000 | 0/0 |
| i1l | 2026-10-07T06:07:32.316750+00:00 / 2026-10-07T06:38:17.873334+00:00 | 0.000000 | 0.000000 | 0/0 |

monitor UTC lifetime 合计 7381.468814 秒；baseline实际request并集重叠1289.578652秒，request occupancy sum7696.149718秒，不能当CPU seconds。schedule lifetime另存于overlap.json；仅基线schedule口径实际request重叠1300.759835秒、reservation1423.006433秒。

| 候选 | RAM 可用 min/median GiB | commit 可用 min/median GiB | monitor worker/reader/smi CPU 秒 | 样本 |
|---|---:|---:|---:|---:|
| baseline | 22.881/25.413 | 15.379/18.089 | 3.531250/0.687500/0.828125 | 7383 |
| i1m | 24.419/25.135 | 16.990/17.953 | 3.031250/0.578125/0.796875 | 7383 |
| apex | 24.831/25.190 | 17.268/17.952 | 2.640625/0.609375/1.031250 | 7378 |
| i1l | 24.508/24.842 | 17.272/18.107 | 3.140625/0.578125/0.859375 | 7383 |

总样本 29527；整机RAM/commit均无缺测。GPU server process memory缺测共513，WDDM dedicated/shared各缺测545。缺测不当零；按all/request-active/no-request/phase保存分布与缺测原因。

CPU仅覆盖monitor worker thread、GPU reader thread与nvidia-smi process，不是judge或llama-server CPU；整机可用RAM/commit不是judge memory。judge CPU、memory、network bytes均未计量，保持null。CLI timestamps包含外围记账与清理，不冒称精确socket/provider/PID lifetime。其余三款无本实验judge请求，并不证明Windows主机空闲，也没有相同session反事实支持因果比较。

12项final binding核对无失败。baseline-v1所有sealed文件及producer script一致，基线session在complete快照与baseline快照完全相同。原formal-performance-background-overlap-v1全部文件SHA保持一致；两类附录是不同scope，不重复计质量样本。
