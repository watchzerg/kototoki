# 正式固定短块长跑、加载、尾段与释放

| 候选 | 重复首次成功/预期 | 阶段秒 | p50 | p95 | p99 | max | GPU peak MiB | min free MiB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Q3_K_M 基线 | 1818/1818 | 1800.191104 | 0.715600 | 0.743785 | 0.758899 | 0.914907 | 15247.0 | 731.0 |
| i1-Q3_K_M | 1979/1979 | 1800.802432 | 0.689914 | 0.722253 | 0.744927 | 0.907189 | 15247.0 | 731.0 |
| APEX-I-Compact | 1936/1936 | 1800.292145 | 0.730489 | 0.756326 | 0.763718 | 0.902641 | 15723.0 | 255.0 |
| i1-Q3_K_L | 1957/1957 | 1800.109411 | 0.720694 | 0.747395 | 0.753330 | 0.874790 | 15822.0 | 156.0 |

| 候选 | cold load s | warm request s | warm完整phase s | probe完整phase s | load→末工件 s | cleanup UTC | preload used MiB | released used MiB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Q3_K_M 基线 | 8.086727 | 0.884011 | 1.077213 | 1.609117 | 1811.515636 | 2026-10-07T05:02:56.935469+00:00 | 790.0 | 790.0 |
| i1-Q3_K_M | 7.604960 | 0.845004 | 1.040292 | 1.595849 | 1811.607930 | 2026-10-07T05:34:41.001441+00:00 | 790.0 | 790.0 |
| APEX-I-Compact | 6.634191 | 0.896405 | 1.081917 | 1.586108 | 1810.104301 | 2026-10-07T06:06:27.844330+00:00 | 790.0 | 736.0 |
| i1-Q3_K_L | 7.680475 | 1.142746 | 1.331201 | 1.700777 | 1811.386987 | 2026-10-07T06:38:15.871919+00:00 | 736.0 | 511.0 |

warm request 是聚合记录的请求耗时，warm 完整 phase 另外包含客户端、验证与持久化；例如基线为 0.884011／1.0772135 秒，不能将两者混用。load→末工件包含 warm／probe 及重复阶段，排除 idle 与 unload。

| 候选 | 相对段 | 窗口数 | p50 s | p95 | p99 | max | GPU used max MiB | free min MiB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Q3_K_M 基线 | first60 | 61 | 0.715587 | 0.747178 | 0.764181 | 0.771882 | 15247.0 | 731.0 |
| Q3_K_M 基线 | middle60 | 61 | 0.713292 | 0.733735 | 0.750020 | 0.750586 | 15247.0 | 731.0 |
| Q3_K_M 基线 | last60 | 60 | 0.728373 | 0.746642 | 0.752257 | 0.756308 | 15247.0 | 731.0 |
| Q3_K_M 基线 | last120 | 122 | 0.721459 | 0.746562 | 0.765842 | 0.770416 | 15247.0 | 731.0 |
| i1-Q3_K_M | first60 | 60 | 0.719902 | 0.745865 | 0.779516 | 0.820247 | 15247.0 | 731.0 |
| i1-Q3_K_M | middle60 | 62 | 0.705563 | 0.735004 | 0.755736 | 0.763274 | 15247.0 | 731.0 |
| i1-Q3_K_M | last60 | 68 | 0.679815 | 0.700145 | 0.703443 | 0.703775 | 15247.0 | 731.0 |
| i1-Q3_K_M | last120 | 136 | 0.679876 | 0.701260 | 0.703943 | 0.704257 | 15247.0 | 731.0 |
| APEX-I-Compact | first60 | 63 | 0.741653 | 0.769473 | 0.807500 | 0.861715 | 15723.0 | 255.0 |
| APEX-I-Compact | middle60 | 65 | 0.731093 | 0.757532 | 0.759580 | 0.759702 | 15723.0 | 255.0 |
| APEX-I-Compact | last60 | 64 | 0.728848 | 0.751745 | 0.758974 | 0.759892 | 15723.0 | 255.0 |
| APEX-I-Compact | last120 | 129 | 0.728919 | 0.753072 | 0.758653 | 0.759892 | 15723.0 | 255.0 |
| i1-Q3_K_L | first60 | 64 | 0.731730 | 0.753676 | 0.802551 | 0.874790 | 15822.0 | 156.0 |
| i1-Q3_K_L | middle60 | 65 | 0.719086 | 0.744133 | 0.757404 | 0.766188 | 15822.0 | 156.0 |
| i1-Q3_K_L | last60 | 65 | 0.718928 | 0.745953 | 0.750339 | 0.751556 | 15822.0 | 156.0 |
| i1-Q3_K_L | last120 | 131 | 0.719045 | 0.742387 | 0.750254 | 0.751556 | 15822.0 | 156.0 |

first60／middle60／last60／last120 按重复阶段 UTC 定义；这些是保存的段摘要，未另行重算分位数。释放采用 released 的独立新鲜样本，不将混有 unload 的 after 段当释放。基线与 i1-Q3_K_M 回到 used 790 MiB；APEX-I-Compact 为 736 MiB，低于自身预加载 54 MiB。初始无目标 PID 的 process null 保持未知，不补为零。

| 候选 | phase | 进程计数 | 已知样本 | min MiB | p50 MiB | max MiB | null |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Q3_K_M 基线 | phase:idle | working_set_bytes | 0 | NA | NA | NA | 1 |
| Q3_K_M 基线 | phase:idle | private_commit_bytes | 0 | NA | NA | NA | 1 |
| Q3_K_M 基线 | phase:idle | dedicated_gpu_bytes | 0 | NA | NA | NA | 1 |
| Q3_K_M 基线 | phase:idle | shared_gpu_bytes | 0 | NA | NA | NA | 1 |
| Q3_K_M 基线 | phase:idle_baseline | working_set_bytes | 0 | NA | NA | NA | 119 |
| Q3_K_M 基线 | phase:idle_baseline | private_commit_bytes | 0 | NA | NA | NA | 119 |
| Q3_K_M 基线 | phase:idle_baseline | dedicated_gpu_bytes | 0 | NA | NA | NA | 119 |
| Q3_K_M 基线 | phase:idle_baseline | shared_gpu_bytes | 0 | NA | NA | NA | 119 |
| Q3_K_M 基线 | phase:load | working_set_bytes | 33 | 1.969 | 6523.484 | 14128.625 | 0 |
| Q3_K_M 基线 | phase:load | private_commit_bytes | 33 | 0.363 | 14382.727 | 15243.215 | 0 |
| Q3_K_M 基线 | phase:load | dedicated_gpu_bytes | 32 | 227.512 | 13899.617 | 14345.645 | 1 |
| Q3_K_M 基线 | phase:load | shared_gpu_bytes | 32 | 74.000 | 74.000 | 84.000 | 1 |
| Q3_K_M 基线 | phase:inference | working_set_bytes | 4 | 14128.824 | 14248.168 | 14351.289 | 0 |
| Q3_K_M 基线 | phase:inference | private_commit_bytes | 4 | 15243.336 | 15399.645 | 15537.152 | 0 |
| Q3_K_M 基线 | phase:inference | dedicated_gpu_bytes | 4 | 14345.645 | 14403.645 | 14457.645 | 0 |
| Q3_K_M 基线 | phase:inference | shared_gpu_bytes | 4 | 84.000 | 84.000 | 84.000 | 0 |
| Q3_K_M 基线 | phase:warmup | working_set_bytes | 5 | 14351.508 | 14356.695 | 14408.727 | 0 |
| Q3_K_M 基线 | phase:warmup | private_commit_bytes | 5 | 15537.281 | 15543.074 | 15594.484 | 0 |
| Q3_K_M 基线 | phase:warmup | dedicated_gpu_bytes | 5 | 14457.645 | 14457.645 | 14457.645 | 0 |
| Q3_K_M 基线 | phase:warmup | shared_gpu_bytes | 5 | 84.000 | 84.000 | 84.000 | 0 |
| Q3_K_M 基线 | phase:near-budget-probe | working_set_bytes | 4 | 14408.723 | 14408.727 | 14410.184 | 0 |
| Q3_K_M 基线 | phase:near-budget-probe | private_commit_bytes | 4 | 15530.359 | 15531.057 | 15594.484 | 0 |
| Q3_K_M 基线 | phase:near-budget-probe | dedicated_gpu_bytes | 4 | 14457.645 | 14457.645 | 14457.645 | 0 |
| Q3_K_M 基线 | phase:near-budget-probe | shared_gpu_bytes | 4 | 84.000 | 84.000 | 84.000 | 0 |
| Q3_K_M 基线 | phase:repeated-source-block | working_set_bytes | 7201 | 14410.207 | 14640.402 | 14640.430 | 0 |
| Q3_K_M 基线 | phase:repeated-source-block | private_commit_bytes | 7201 | 15531.754 | 15717.820 | 15717.980 | 0 |
| Q3_K_M 基线 | phase:repeated-source-block | dedicated_gpu_bytes | 7201 | 14457.645 | 14457.645 | 14457.645 | 0 |
| Q3_K_M 基线 | phase:repeated-source-block | shared_gpu_bytes | 7201 | 84.000 | 84.000 | 84.000 | 0 |
| Q3_K_M 基线 | phase:unload | working_set_bytes | 8 | 1759.531 | 8557.531 | 14640.406 | 0 |
| Q3_K_M 基线 | phase:unload | private_commit_bytes | 8 | 1032.340 | 1032.340 | 4626.449 | 0 |
| Q3_K_M 基线 | phase:unload | dedicated_gpu_bytes | 1 | 3197.535 | 3197.535 | 3197.535 | 7 |
| Q3_K_M 基线 | phase:unload | shared_gpu_bytes | 1 | 74.000 | 74.000 | 74.000 | 7 |
| Q3_K_M 基线 | phase:released | working_set_bytes | 0 | NA | NA | NA | 8 |
| Q3_K_M 基线 | phase:released | private_commit_bytes | 0 | NA | NA | NA | 8 |
| Q3_K_M 基线 | phase:released | dedicated_gpu_bytes | 0 | NA | NA | NA | 8 |
| Q3_K_M 基线 | phase:released | shared_gpu_bytes | 0 | NA | NA | NA | 8 |
| i1-Q3_K_M | phase:idle | working_set_bytes | 0 | NA | NA | NA | 1 |
| i1-Q3_K_M | phase:idle | private_commit_bytes | 0 | NA | NA | NA | 1 |
| i1-Q3_K_M | phase:idle | dedicated_gpu_bytes | 0 | NA | NA | NA | 1 |
| i1-Q3_K_M | phase:idle | shared_gpu_bytes | 0 | NA | NA | NA | 1 |
| i1-Q3_K_M | phase:idle_baseline | working_set_bytes | 0 | NA | NA | NA | 119 |
| i1-Q3_K_M | phase:idle_baseline | private_commit_bytes | 0 | NA | NA | NA | 119 |
| i1-Q3_K_M | phase:idle_baseline | dedicated_gpu_bytes | 0 | NA | NA | NA | 119 |
| i1-Q3_K_M | phase:idle_baseline | shared_gpu_bytes | 0 | NA | NA | NA | 119 |
| i1-Q3_K_M | phase:load | working_set_bytes | 31 | 1.969 | 6419.090 | 14129.156 | 0 |
| i1-Q3_K_M | phase:load | private_commit_bytes | 31 | 0.367 | 14383.094 | 15243.555 | 0 |
| i1-Q3_K_M | phase:load | dedicated_gpu_bytes | 30 | 227.512 | 13899.617 | 14345.645 | 1 |
| i1-Q3_K_M | phase:load | shared_gpu_bytes | 30 | 74.000 | 74.000 | 84.000 | 1 |
| i1-Q3_K_M | phase:inference | working_set_bytes | 4 | 14129.348 | 14247.875 | 14351.789 | 0 |
| i1-Q3_K_M | phase:inference | private_commit_bytes | 4 | 15243.629 | 15399.732 | 15537.293 | 0 |
| i1-Q3_K_M | phase:inference | dedicated_gpu_bytes | 4 | 14345.645 | 14403.645 | 14457.645 | 0 |
| i1-Q3_K_M | phase:inference | shared_gpu_bytes | 4 | 84.000 | 84.000 | 84.000 | 0 |
| i1-Q3_K_M | phase:warmup | working_set_bytes | 5 | 14351.938 | 14357.570 | 14408.742 | 0 |
| i1-Q3_K_M | phase:warmup | private_commit_bytes | 5 | 15537.363 | 15542.934 | 15594.160 | 0 |
| i1-Q3_K_M | phase:warmup | dedicated_gpu_bytes | 5 | 14457.645 | 14457.645 | 14457.645 | 0 |
| i1-Q3_K_M | phase:warmup | shared_gpu_bytes | 5 | 84.000 | 84.000 | 84.000 | 0 |
| i1-Q3_K_M | phase:near-budget-probe | working_set_bytes | 4 | 14408.738 | 14408.742 | 14410.203 | 0 |
| i1-Q3_K_M | phase:near-budget-probe | private_commit_bytes | 4 | 15530.039 | 15562.795 | 15594.160 | 0 |
| i1-Q3_K_M | phase:near-budget-probe | dedicated_gpu_bytes | 4 | 14457.645 | 14457.645 | 14457.645 | 0 |
| i1-Q3_K_M | phase:near-budget-probe | shared_gpu_bytes | 4 | 84.000 | 84.000 | 84.000 | 0 |
| i1-Q3_K_M | phase:repeated-source-block | working_set_bytes | 7204 | 14410.219 | 14640.617 | 14693.008 | 0 |
| i1-Q3_K_M | phase:repeated-source-block | private_commit_bytes | 7204 | 15518.781 | 15718.695 | 15771.441 | 0 |
| i1-Q3_K_M | phase:repeated-source-block | dedicated_gpu_bytes | 7204 | 14457.645 | 14457.645 | 14457.645 | 0 |
| i1-Q3_K_M | phase:repeated-source-block | shared_gpu_bytes | 7204 | 84.000 | 84.000 | 84.000 | 0 |
| i1-Q3_K_M | phase:unload | working_set_bytes | 7 | 2337.652 | 8539.648 | 14640.605 | 0 |
| i1-Q3_K_M | phase:unload | private_commit_bytes | 7 | 1023.656 | 1023.656 | 1231.707 | 0 |
| i1-Q3_K_M | phase:unload | dedicated_gpu_bytes | 0 | NA | NA | NA | 7 |
| i1-Q3_K_M | phase:unload | shared_gpu_bytes | 0 | NA | NA | NA | 7 |
| i1-Q3_K_M | phase:released | working_set_bytes | 0 | NA | NA | NA | 8 |
| i1-Q3_K_M | phase:released | private_commit_bytes | 0 | NA | NA | NA | 8 |
| i1-Q3_K_M | phase:released | dedicated_gpu_bytes | 0 | NA | NA | NA | 8 |
| i1-Q3_K_M | phase:released | shared_gpu_bytes | 0 | NA | NA | NA | 8 |
| APEX-I-Compact | phase:idle | working_set_bytes | 0 | NA | NA | NA | 1 |
| APEX-I-Compact | phase:idle | private_commit_bytes | 0 | NA | NA | NA | 1 |
| APEX-I-Compact | phase:idle | dedicated_gpu_bytes | 0 | NA | NA | NA | 1 |
| APEX-I-Compact | phase:idle | shared_gpu_bytes | 0 | NA | NA | NA | 1 |
| APEX-I-Compact | phase:idle_baseline | working_set_bytes | 0 | NA | NA | NA | 119 |
| APEX-I-Compact | phase:idle_baseline | private_commit_bytes | 0 | NA | NA | NA | 119 |
| APEX-I-Compact | phase:idle_baseline | dedicated_gpu_bytes | 0 | NA | NA | NA | 119 |
| APEX-I-Compact | phase:idle_baseline | shared_gpu_bytes | 0 | NA | NA | NA | 119 |
| APEX-I-Compact | phase:load | working_set_bytes | 27 | 1.969 | 5338.492 | 14605.664 | 0 |
| APEX-I-Compact | phase:load | private_commit_bytes | 27 | 0.367 | 14915.711 | 15704.723 | 0 |
| APEX-I-Compact | phase:load | dedicated_gpu_bytes | 26 | 23.508 | 14429.621 | 14871.648 | 1 |
| APEX-I-Compact | phase:load | shared_gpu_bytes | 26 | 72.000 | 74.000 | 84.000 | 1 |
| APEX-I-Compact | phase:inference | working_set_bytes | 4 | 14661.801 | 14780.740 | 14885.164 | 0 |
| APEX-I-Compact | phase:inference | private_commit_bytes | 4 | 15778.004 | 15933.586 | 16072.812 | 0 |
| APEX-I-Compact | phase:inference | dedicated_gpu_bytes | 4 | 14875.648 | 14933.648 | 14987.648 | 0 |
| APEX-I-Compact | phase:inference | shared_gpu_bytes | 4 | 84.000 | 84.000 | 84.000 | 0 |
| APEX-I-Compact | phase:warmup | working_set_bytes | 5 | 14885.371 | 14890.105 | 14941.457 | 0 |
| APEX-I-Compact | phase:warmup | private_commit_bytes | 5 | 16072.941 | 16077.566 | 16128.980 | 0 |
| APEX-I-Compact | phase:warmup | dedicated_gpu_bytes | 5 | 14987.648 | 14987.648 | 14987.648 | 0 |
| APEX-I-Compact | phase:warmup | shared_gpu_bytes | 5 | 84.000 | 84.000 | 84.000 | 0 |
| APEX-I-Compact | phase:near-budget-probe | working_set_bytes | 4 | 14941.445 | 14941.449 | 14942.895 | 0 |
| APEX-I-Compact | phase:near-budget-probe | private_commit_bytes | 4 | 16066.246 | 16128.980 | 16128.980 | 0 |
| APEX-I-Compact | phase:near-budget-probe | dedicated_gpu_bytes | 4 | 14987.648 | 14987.648 | 14987.648 | 0 |
| APEX-I-Compact | phase:near-budget-probe | shared_gpu_bytes | 4 | 84.000 | 84.000 | 84.000 | 0 |
| APEX-I-Compact | phase:repeated-source-block | working_set_bytes | 7203 | 14942.926 | 15173.031 | 15173.051 | 0 |
| APEX-I-Compact | phase:repeated-source-block | private_commit_bytes | 7203 | 16052.031 | 16253.664 | 16253.820 | 0 |
| APEX-I-Compact | phase:repeated-source-block | dedicated_gpu_bytes | 7203 | 14987.648 | 14987.648 | 14987.648 | 0 |
| APEX-I-Compact | phase:repeated-source-block | shared_gpu_bytes | 7203 | 84.000 | 84.000 | 84.000 | 0 |
| APEX-I-Compact | phase:unload | working_set_bytes | 7 | 2345.488 | 8855.488 | 15173.031 | 0 |
| APEX-I-Compact | phase:unload | private_commit_bytes | 7 | 1037.035 | 1037.035 | 1235.391 | 0 |
| APEX-I-Compact | phase:unload | dedicated_gpu_bytes | 0 | NA | NA | NA | 7 |
| APEX-I-Compact | phase:unload | shared_gpu_bytes | 0 | NA | NA | NA | 7 |
| APEX-I-Compact | phase:released | working_set_bytes | 0 | NA | NA | NA | 8 |
| APEX-I-Compact | phase:released | private_commit_bytes | 0 | NA | NA | NA | 8 |
| APEX-I-Compact | phase:released | dedicated_gpu_bytes | 0 | NA | NA | NA | 8 |
| APEX-I-Compact | phase:released | shared_gpu_bytes | 0 | NA | NA | NA | 8 |
| i1-Q3_K_L | phase:idle | working_set_bytes | 0 | NA | NA | NA | 1 |
| i1-Q3_K_L | phase:idle | private_commit_bytes | 0 | NA | NA | NA | 1 |
| i1-Q3_K_L | phase:idle | dedicated_gpu_bytes | 0 | NA | NA | NA | 1 |
| i1-Q3_K_L | phase:idle | shared_gpu_bytes | 0 | NA | NA | NA | 1 |
| i1-Q3_K_L | phase:idle_baseline | working_set_bytes | 0 | NA | NA | NA | 119 |
| i1-Q3_K_L | phase:idle_baseline | private_commit_bytes | 0 | NA | NA | NA | 119 |
| i1-Q3_K_L | phase:idle_baseline | dedicated_gpu_bytes | 0 | NA | NA | NA | 119 |
| i1-Q3_K_L | phase:idle_baseline | shared_gpu_bytes | 0 | NA | NA | NA | 119 |
| i1-Q3_K_L | phase:load | working_set_bytes | 30 | 303.871 | 6979.729 | 15629.098 | 1 |
| i1-Q3_K_L | phase:load | private_commit_bytes | 30 | 606.680 | 15528.484 | 16389.449 | 1 |
| i1-Q3_K_L | phase:load | dedicated_gpu_bytes | 30 | 227.512 | 15041.625 | 15296.027 | 1 |
| i1-Q3_K_L | phase:load | shared_gpu_bytes | 30 | 74.000 | 74.000 | 276.000 | 1 |
| i1-Q3_K_L | phase:inference | working_set_bytes | 5 | 15629.285 | 15840.887 | 15909.043 | 0 |
| i1-Q3_K_L | phase:inference | private_commit_bytes | 5 | 16389.523 | 16611.910 | 16675.328 | 0 |
| i1-Q3_K_L | phase:inference | dedicated_gpu_bytes | 5 | 15296.027 | 15304.215 | 15312.215 | 0 |
| i1-Q3_K_L | phase:inference | shared_gpu_bytes | 5 | 276.000 | 372.000 | 372.000 | 0 |
| i1-Q3_K_L | phase:warmup | working_set_bytes | 4 | 15909.250 | 15913.309 | 15914.973 | 0 |
| i1-Q3_K_L | phase:warmup | private_commit_bytes | 4 | 16675.461 | 16679.652 | 16681.129 | 0 |
| i1-Q3_K_L | phase:warmup | dedicated_gpu_bytes | 4 | 15312.215 | 15312.215 | 15312.215 | 0 |
| i1-Q3_K_L | phase:warmup | shared_gpu_bytes | 4 | 372.000 | 372.000 | 372.000 | 0 |
| i1-Q3_K_L | phase:near-budget-probe | working_set_bytes | 8 | 15966.422 | 15966.430 | 16196.430 | 0 |
| i1-Q3_K_L | phase:near-budget-probe | private_commit_bytes | 8 | 16732.648 | 16732.648 | 16963.000 | 0 |
| i1-Q3_K_L | phase:near-budget-probe | dedicated_gpu_bytes | 8 | 15312.215 | 15312.215 | 15312.215 | 0 |
| i1-Q3_K_L | phase:near-budget-probe | shared_gpu_bytes | 8 | 372.000 | 372.000 | 372.000 | 0 |
| i1-Q3_K_L | phase:repeated-source-block | working_set_bytes | 7198 | 16088.016 | 16089.547 | 16197.816 | 0 |
| i1-Q3_K_L | phase:repeated-source-block | private_commit_bytes | 7198 | 16854.277 | 16855.668 | 16964.387 | 0 |
| i1-Q3_K_L | phase:repeated-source-block | dedicated_gpu_bytes | 7198 | 15312.215 | 15312.215 | 15312.215 | 0 |
| i1-Q3_K_L | phase:repeated-source-block | shared_gpu_bytes | 7198 | 372.000 | 372.000 | 372.000 | 0 |
| i1-Q3_K_L | phase:unload | working_set_bytes | 9 | 650.281 | 9199.004 | 15775.930 | 0 |
| i1-Q3_K_L | phase:unload | private_commit_bytes | 9 | 715.062 | 1027.641 | 16256.859 | 0 |
| i1-Q3_K_L | phase:unload | dedicated_gpu_bytes | 1 | 14717.625 | 14717.625 | 14717.625 | 8 |
| i1-Q3_K_L | phase:unload | shared_gpu_bytes | 1 | 74.000 | 74.000 | 74.000 | 8 |
| i1-Q3_K_L | phase:released | working_set_bytes | 0 | NA | NA | NA | 8 |
| i1-Q3_K_L | phase:released | private_commit_bytes | 0 | NA | NA | NA | 8 |
| i1-Q3_K_L | phase:released | dedicated_gpu_bytes | 0 | NA | NA | NA | 8 |
| i1-Q3_K_L | phase:released | shared_gpu_bytes | 0 | NA | NA | NA | 8 |

WDDM allocation、working set、private commit 是不同统计范围；数值相关不证明 CPU fallback、物理显存分页或 OOM。全量原摘要、有效设置、段计数与 null 原因保持在本机受限证据中。

- Q3_K_M 基线：[原始技术摘要](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-stability-terminal-audit-v1/hy-mt2-30b-a3b-q3-k-m/summary.json>)、[完整有效设置](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-stability-terminal-audit-v1/hy-mt2-30b-a3b-q3-k-m/effective-addendum.json>)。

- i1-Q3_K_M：[原始技术摘要](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-stability-terminal-audit-v1/hy-mt2-30b-a3b-i1-q3-k-m/summary.json>)、[完整有效设置](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-stability-terminal-audit-v1/hy-mt2-30b-a3b-i1-q3-k-m/effective-addendum.json>)。

- APEX-I-Compact：[原始技术摘要](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-stability-terminal-audit-v1/hy-mt2-30b-a3b-apex-i-compact/summary.json>)、[完整有效设置](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-stability-terminal-audit-v1/hy-mt2-30b-a3b-apex-i-compact/effective-addendum.json>)。

- i1-Q3_K_L：[原始技术摘要](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-stability-terminal-audit-v1/hy-mt2-30b-a3b-i1-q3-k-l/summary.json>)、[完整有效设置](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-stability-terminal-audit-v1/hy-mt2-30b-a3b-i1-q3-k-l/effective-addendum-v4.json>)。

四个正式重复阶段合计 7,690 次、7,201.395091 秒，均首次成功、无重试、未执行或显式 OOM。i1-Q3_K_L 本次正式固定短块 p50／p95／p99／max 为 0.720694／0.747395／0.753330／0.874790 秒，前／中／后 60 秒与末 120 秒中位为 0.731730／0.719086／0.718928／0.719045 秒，没有数量级慢尾；shared 全段 372 MiB、重复期最低 free 156 MiB。此前工程长跑的末 48 次慢尾和长语料轮间差异仍是实际观测：本次完整 30 分钟通过不能抹去它们，也没有确认成因或保证其他输入不再发生。R4 快状态本身仍不能证明长时问题解决，新增的独立正式短块证据须与其区别。

最后 i1-Q3_K_L cleanup 为 06:38:15.871919 UTC，任务 completed 为 06:39:00.423940，attempt completed 为 06:39:00.457116。发布前 06:42:55.3083139–06:42:59.7056875 UTC 的原生只读观察未发现所属活进程或 8080 listener，整卡 used/free 为 511／15,467 MiB、利用率 0%；这是有界时点观察，不证明所有历史背景负载不存在。公开文档编辑前，174 个原冻结文件与 174 个对应快照全部符合原 SHA；公开文档正常演进后旧绝对路径门禁应拒绝，使用复现附录的新身份入口。
