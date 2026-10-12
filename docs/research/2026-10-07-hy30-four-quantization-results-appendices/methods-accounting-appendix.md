# 方法、执行成本与复现附录

本附录保留完成的参考与正式质量账目。正式长跑与复现分别见正文及本目录对应附录；不把工程历史或计划位置称为全部正式验收完成。

## 样本账目与概率边界

原始机械抽样框记录 1,200 个初始选中块及 13,313 个候补块；这不是 v2 库全文质量样本。抽样先随机选择七单元划分起点，再以 seed 20261006 固定选集、选窗和候补次序。选集概率按各集序层合格集数取倒数；选窗概率为目标窗数除以该集或电影位置层合格窗数，初始设计概率为两者乘积。下表仅表示机械块框上的条件设计，不含随机 offset 概率；最终留存概率不能在审核拒收后直接沿用这一乘积。逐作品语义汇总仍使用预声明的作品等权口径，不能把这些概率当事后逆概率权重。

历史审核 1,428 窗，最终移除 228/1,428（15.97%）；初始 1,200 中有 186 窗未留存（15.50%），228 个补入窗中又有 42 窗移除。最终 1,200＝1,014 个初始留存＋186 个补位留存；历史 1,428＝最终 1,200＋移除 228。五轮补位 186/32/8/1/1，全为同 `selection_group` 的首个未使用冻结候补，未用额外集 tier。每个补位窗重新完成独立双审；重复调用不是新源样本，移除范围也不参与最终模型质量计分。

预选框另有 273 条 episode/frame 排除记录：旧 dev/test 整集 33、天气之子隔离 1、非连续源 cue 或未配对间隔 172、旧 context 或已隔离源事件 67。它们是不同单位的预选排除记录，不能与审核后移除 228 窗相加成一个窗级拒收率。初始禁用事件并集为 630，旧整集范围为 33 个源文件；全部 context 事件检查的结果见最终源审计。最终冻结 8,400 个 context 单元包含 16,800 个语言源事件键、16,240 个去语言的原始事件键，不将这三种单位混为字幕条数。

旧 test 83 窗／414 IDs 是已用于选型的 test-informed 回归，单独同轮推理与重评；dev 41／204，smoke 15／75 是 dev 子集。新增集限当前 15 作品、审核后可判的片段留出；共享系列及仅四部电影限制作品独立性和功效，不外推未见作品、真人电影、整片翻译或音画同步。源侧标签仅作既定诊断；没有标签的场景保持未知，不能根据模型结果补贴标签改变样本。

### 逐作品留存与拒收

“历史拒收率”分母为该作全部不同已审核源窗；“初始留存／补位留存”是最终 80 的来源组成。作品名称沿用源清单标识。

| 作品 ID | 作品 | 初始 | 历史审核 | 最终移除 | 历史拒收率 | 初始留存 | 补位留存 | 最终窗／计分 ID |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M01 | Sword Art Online The Movie Progressive - Aria of a Starless Night (2021) | 80 | 90 | 10 | 11.11% | 72 | 8 | 80/400 |
| M02 | Sword Art Online the Movie Progressive - Scherzo of Deep Night (2022) | 80 | 93 | 13 | 13.98% | 69 | 11 | 80/400 |
| M03 | Suzume （2022） | 80 | 108 | 28 | 25.93% | 60 | 20 | 80/400 |
| M04 | The Birth of Kitarou Mystery of GeGeGe (2023) | 80 | 95 | 15 | 15.79% | 68 | 12 | 80/400 |
| W01 | Delicious in Dungeon (2024) | 80 | 89 | 9 | 10.11% | 72 | 8 | 80/400 |
| W02 | Fate Stay Night Unlimited Blade Works (2014) | 80 | 93 | 13 | 13.98% | 69 | 11 | 80/400 |
| W03 | Frieren Beyond Journey's End (2023) | 80 | 101 | 21 | 20.79% | 61 | 19 | 80/400 |
| W04 | Heavenly Delusion (2023) | 80 | 93 | 13 | 13.98% | 71 | 9 | 80/400 |
| W05 | JoJo's Bizarre Adventure (2012) | 80 | 92 | 12 | 13.04% | 69 | 11 | 80/400 |
| W06 | Komi Can't Communicate (2021) | 80 | 106 | 26 | 24.53% | 61 | 19 | 80/400 |
| W07 | Natsume's Book of Friends | 80 | 99 | 19 | 19.19% | 65 | 15 | 80/400 |
| W08 | ODDTAXI (2021) | 80 | 96 | 16 | 16.67% | 66 | 14 | 80/400 |
| W09 | SPY x FAMILY (2022) | 80 | 95 | 15 | 15.79% | 67 | 13 | 80/400 |
| W10 | Summer Time Rendering (2022) | 80 | 89 | 9 | 10.11% | 72 | 8 | 80/400 |
| W11 | Sword Art Online | 80 | 89 | 9 | 10.11% | 72 | 8 | 80/400 |

### 全部 128 个选窗层

剧集层以实际选集 ID 命名，每层目标十窗；电影层 `decile-00` 到 `decile-09` 各目标八窗。位置十等分指配对白进度，不是电影时长十等分。各层的历史审核／最终移除／最终数量从五份不可覆盖 selected 历史与最终 selected 的 ID 并集核算，未读模型成绩；全部层合计 1,428／228／1,200。

| 作品／选窗层 | 合格框 N | 初始目标 | 选集 p | 选窗 p（条件） | 初始设计 p | 历史审核 | 最终移除 | 拒收率 | 最终 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M01\|decile-00 | 17 | 8 | 1.00000000 | 0.47058824 | 0.47058824 | 8 | 0 | 0.00% | 8 |
| M01\|decile-01 | 16 | 8 | 1.00000000 | 0.50000000 | 0.50000000 | 9 | 1 | 11.11% | 8 |
| M01\|decile-02 | 15 | 8 | 1.00000000 | 0.53333333 | 0.53333333 | 10 | 2 | 20.00% | 8 |
| M01\|decile-03 | 16 | 8 | 1.00000000 | 0.50000000 | 0.50000000 | 9 | 1 | 11.11% | 8 |
| M01\|decile-04 | 15 | 8 | 1.00000000 | 0.53333333 | 0.53333333 | 9 | 1 | 11.11% | 8 |
| M01\|decile-05 | 16 | 8 | 1.00000000 | 0.50000000 | 0.50000000 | 8 | 0 | 0.00% | 8 |
| M01\|decile-06 | 16 | 8 | 1.00000000 | 0.50000000 | 0.50000000 | 12 | 4 | 33.33% | 8 |
| M01\|decile-07 | 15 | 8 | 1.00000000 | 0.53333333 | 0.53333333 | 8 | 0 | 0.00% | 8 |
| M01\|decile-08 | 16 | 8 | 1.00000000 | 0.50000000 | 0.50000000 | 8 | 0 | 0.00% | 8 |
| M01\|decile-09 | 16 | 8 | 1.00000000 | 0.50000000 | 0.50000000 | 9 | 1 | 11.11% | 8 |
| M02\|decile-00 | 15 | 8 | 1.00000000 | 0.53333333 | 0.53333333 | 8 | 0 | 0.00% | 8 |
| M02\|decile-01 | 15 | 8 | 1.00000000 | 0.53333333 | 0.53333333 | 9 | 1 | 11.11% | 8 |
| M02\|decile-02 | 15 | 8 | 1.00000000 | 0.53333333 | 0.53333333 | 10 | 2 | 20.00% | 8 |
| M02\|decile-03 | 15 | 8 | 1.00000000 | 0.53333333 | 0.53333333 | 9 | 1 | 11.11% | 8 |
| M02\|decile-04 | 15 | 8 | 1.00000000 | 0.53333333 | 0.53333333 | 8 | 0 | 0.00% | 8 |
| M02\|decile-05 | 16 | 8 | 1.00000000 | 0.50000000 | 0.50000000 | 9 | 1 | 11.11% | 8 |
| M02\|decile-06 | 15 | 8 | 1.00000000 | 0.53333333 | 0.53333333 | 9 | 1 | 11.11% | 8 |
| M02\|decile-07 | 16 | 8 | 1.00000000 | 0.50000000 | 0.50000000 | 11 | 3 | 27.27% | 8 |
| M02\|decile-08 | 15 | 8 | 1.00000000 | 0.53333333 | 0.53333333 | 11 | 3 | 27.27% | 8 |
| M02\|decile-09 | 15 | 8 | 1.00000000 | 0.53333333 | 0.53333333 | 9 | 1 | 11.11% | 8 |
| M03\|decile-00 | 26 | 8 | 1.00000000 | 0.30769231 | 0.30769231 | 11 | 3 | 27.27% | 8 |
| M03\|decile-01 | 27 | 8 | 1.00000000 | 0.29629630 | 0.29629630 | 10 | 2 | 20.00% | 8 |
| M03\|decile-02 | 25 | 8 | 1.00000000 | 0.32000000 | 0.32000000 | 9 | 1 | 11.11% | 8 |
| M03\|decile-03 | 27 | 8 | 1.00000000 | 0.29629630 | 0.29629630 | 15 | 7 | 46.67% | 8 |
| M03\|decile-04 | 26 | 8 | 1.00000000 | 0.30769231 | 0.30769231 | 11 | 3 | 27.27% | 8 |
| M03\|decile-05 | 26 | 8 | 1.00000000 | 0.30769231 | 0.30769231 | 10 | 2 | 20.00% | 8 |
| M03\|decile-06 | 26 | 8 | 1.00000000 | 0.30769231 | 0.30769231 | 10 | 2 | 20.00% | 8 |
| M03\|decile-07 | 25 | 8 | 1.00000000 | 0.32000000 | 0.32000000 | 10 | 2 | 20.00% | 8 |
| M03\|decile-08 | 26 | 8 | 1.00000000 | 0.30769231 | 0.30769231 | 13 | 5 | 38.46% | 8 |
| M03\|decile-09 | 27 | 8 | 1.00000000 | 0.29629630 | 0.29629630 | 9 | 1 | 11.11% | 8 |
| M04\|decile-00 | 18 | 8 | 1.00000000 | 0.44444444 | 0.44444444 | 9 | 1 | 11.11% | 8 |
| M04\|decile-01 | 17 | 8 | 1.00000000 | 0.47058824 | 0.47058824 | 9 | 1 | 11.11% | 8 |
| M04\|decile-02 | 17 | 8 | 1.00000000 | 0.47058824 | 0.47058824 | 11 | 3 | 27.27% | 8 |
| M04\|decile-03 | 17 | 8 | 1.00000000 | 0.47058824 | 0.47058824 | 12 | 4 | 33.33% | 8 |
| M04\|decile-04 | 18 | 8 | 1.00000000 | 0.44444444 | 0.44444444 | 8 | 0 | 0.00% | 8 |
| M04\|decile-05 | 18 | 8 | 1.00000000 | 0.44444444 | 0.44444444 | 9 | 1 | 11.11% | 8 |
| M04\|decile-06 | 17 | 8 | 1.00000000 | 0.47058824 | 0.47058824 | 8 | 0 | 0.00% | 8 |
| M04\|decile-07 | 17 | 8 | 1.00000000 | 0.47058824 | 0.47058824 | 10 | 2 | 20.00% | 8 |
| M04\|decile-08 | 17 | 8 | 1.00000000 | 0.47058824 | 0.47058824 | 11 | 3 | 27.27% | 8 |
| M04\|decile-09 | 18 | 8 | 1.00000000 | 0.44444444 | 0.44444444 | 8 | 0 | 0.00% | 8 |
| W01\|episode-band-00\|W01_E002 | 63 | 10 | 0.50000000 | 0.15873016 | 0.07936508 | 12 | 2 | 16.67% | 10 |
| W01\|episode-band-01\|W01_E005 | 47 | 10 | 0.33333333 | 0.21276596 | 0.07092199 | 11 | 1 | 9.09% | 10 |
| W01\|episode-band-02\|W01_E007 | 58 | 10 | 0.50000000 | 0.17241379 | 0.08620690 | 11 | 1 | 9.09% | 10 |
| W01\|episode-band-03\|W01_E010 | 58 | 10 | 0.33333333 | 0.17241379 | 0.05747126 | 10 | 0 | 0.00% | 10 |
| W01\|episode-band-04\|W01_E015 | 66 | 10 | 0.33333333 | 0.15151515 | 0.05050505 | 11 | 1 | 9.09% | 10 |
| W01\|episode-band-05\|W01_E016 | 58 | 10 | 0.50000000 | 0.17241379 | 0.08620690 | 12 | 2 | 16.67% | 10 |
| W01\|episode-band-06\|W01_E019 | 64 | 10 | 0.33333333 | 0.15625000 | 0.05208333 | 11 | 1 | 9.09% | 10 |
| W01\|episode-band-07\|W01_E024 | 60 | 10 | 0.33333333 | 0.16666667 | 0.05555556 | 11 | 1 | 9.09% | 10 |
| W02\|episode-band-00\|W02_E001 | 91 | 10 | 0.50000000 | 0.10989011 | 0.05494505 | 12 | 2 | 16.67% | 10 |
| W02\|episode-band-01\|W02_E004 | 29 | 10 | 0.33333333 | 0.34482759 | 0.11494253 | 11 | 1 | 9.09% | 10 |
| W02\|episode-band-02\|W02_E008 | 43 | 10 | 0.33333333 | 0.23255814 | 0.07751938 | 10 | 0 | 0.00% | 10 |
| W02\|episode-band-03\|W02_E012 | 47 | 10 | 0.33333333 | 0.21276596 | 0.07092199 | 10 | 0 | 0.00% | 10 |
| W02\|episode-band-04\|W02_E015 | 55 | 10 | 0.33333333 | 0.18181818 | 0.06060606 | 12 | 2 | 16.67% | 10 |
| W02\|episode-band-05\|W02_E018 | 36 | 10 | 0.33333333 | 0.27777778 | 0.09259259 | 13 | 3 | 23.08% | 10 |
| W02\|episode-band-06\|W02_E021 | 35 | 10 | 0.33333333 | 0.28571429 | 0.09523810 | 12 | 2 | 16.67% | 10 |
| W02\|episode-band-07\|W02_E026 | 42 | 10 | 0.33333333 | 0.23809524 | 0.07936508 | 13 | 3 | 23.08% | 10 |
| W03\|episode-band-00\|W03_E002 | 34 | 10 | 0.33333333 | 0.29411765 | 0.09803922 | 10 | 0 | 0.00% | 10 |
| W03\|episode-band-01\|W03_E007 | 38 | 10 | 0.33333333 | 0.26315789 | 0.08771930 | 15 | 5 | 33.33% | 10 |
| W03\|episode-band-02\|W03_E010 | 40 | 10 | 0.33333333 | 0.25000000 | 0.08333333 | 12 | 2 | 16.67% | 10 |
| W03\|episode-band-03\|W03_E011 | 40 | 10 | 0.33333333 | 0.25000000 | 0.08333333 | 13 | 3 | 23.08% | 10 |
| W03\|episode-band-04\|W03_E017 | 38 | 10 | 0.33333333 | 0.26315789 | 0.08771930 | 11 | 1 | 9.09% | 10 |
| W03\|episode-band-05\|W03_E020 | 44 | 10 | 0.33333333 | 0.22727273 | 0.07575758 | 14 | 4 | 28.57% | 10 |
| W03\|episode-band-06\|W03_E021 | 40 | 10 | 0.33333333 | 0.25000000 | 0.08333333 | 13 | 3 | 23.08% | 10 |
| W03\|episode-band-07\|W03_E027 | 41 | 10 | 0.25000000 | 0.24390244 | 0.06097561 | 13 | 3 | 23.08% | 10 |
| W04\|episode-band-00\|W04_E001 | 55 | 10 | 1.00000000 | 0.18181818 | 0.18181818 | 11 | 1 | 9.09% | 10 |
| W04\|episode-band-01\|W04_E002 | 46 | 10 | 1.00000000 | 0.21739130 | 0.21739130 | 10 | 0 | 0.00% | 10 |
| W04\|episode-band-02\|W04_E004 | 47 | 10 | 1.00000000 | 0.21276596 | 0.21276596 | 11 | 1 | 9.09% | 10 |
| W04\|episode-band-03\|W04_E005 | 45 | 10 | 0.50000000 | 0.22222222 | 0.11111111 | 11 | 1 | 9.09% | 10 |
| W04\|episode-band-04\|W04_E008 | 32 | 10 | 1.00000000 | 0.31250000 | 0.31250000 | 11 | 1 | 9.09% | 10 |
| W04\|episode-band-05\|W04_E009 | 45 | 10 | 1.00000000 | 0.22222222 | 0.22222222 | 10 | 0 | 0.00% | 10 |
| W04\|episode-band-06\|W04_E010 | 43 | 10 | 1.00000000 | 0.23255814 | 0.23255814 | 19 | 9 | 47.37% | 10 |
| W04\|episode-band-07\|W04_E013 | 39 | 10 | 0.50000000 | 0.25641026 | 0.12820513 | 10 | 0 | 0.00% | 10 |
| W05\|episode-band-00\|W05_E014 | 45 | 10 | 0.07142857 | 0.22222222 | 0.01587302 | 11 | 1 | 9.09% | 10 |
| W05\|episode-band-01\|W05_E027 | 40 | 10 | 0.07142857 | 0.25000000 | 0.01785714 | 10 | 0 | 0.00% | 10 |
| W05\|episode-band-02\|W05_E033 | 38 | 10 | 0.07142857 | 0.26315789 | 0.01879699 | 13 | 3 | 23.08% | 10 |
| W05\|episode-band-03\|W05_E044 | 57 | 10 | 0.07142857 | 0.17543860 | 0.01253133 | 11 | 1 | 9.09% | 10 |
| W05\|episode-band-04\|W05_E064 | 33 | 10 | 0.07142857 | 0.30303030 | 0.02164502 | 12 | 2 | 16.67% | 10 |
| W05\|episode-band-05\|W05_E085 | 45 | 10 | 0.07142857 | 0.22222222 | 0.01587302 | 12 | 2 | 16.67% | 10 |
| W05\|episode-band-06\|W05_E097 | 29 | 10 | 0.07142857 | 0.34482759 | 0.02463054 | 12 | 2 | 16.67% | 10 |
| W05\|episode-band-07\|W05_E110 | 43 | 10 | 0.07142857 | 0.23255814 | 0.01661130 | 11 | 1 | 9.09% | 10 |
| W06\|episode-band-00\|W06_E002 | 46 | 10 | 0.50000000 | 0.21739130 | 0.10869565 | 14 | 4 | 28.57% | 10 |
| W06\|episode-band-01\|W06_E006 | 45 | 10 | 0.33333333 | 0.22222222 | 0.07407407 | 13 | 3 | 23.08% | 10 |
| W06\|episode-band-02\|W06_E008 | 49 | 10 | 0.50000000 | 0.20408163 | 0.10204082 | 16 | 6 | 37.50% | 10 |
| W06\|episode-band-03\|W06_E011 | 51 | 10 | 0.33333333 | 0.19607843 | 0.06535948 | 13 | 3 | 23.08% | 10 |
| W06\|episode-band-04\|W06_E014 | 52 | 10 | 0.33333333 | 0.19230769 | 0.06410256 | 10 | 0 | 0.00% | 10 |
| W06\|episode-band-05\|W06_E017 | 34 | 10 | 0.50000000 | 0.29411765 | 0.14705882 | 15 | 5 | 33.33% | 10 |
| W06\|episode-band-06\|W06_E018 | 41 | 10 | 0.33333333 | 0.24390244 | 0.08130081 | 12 | 2 | 16.67% | 10 |
| W06\|episode-band-07\|W06_E023 | 40 | 10 | 0.33333333 | 0.25000000 | 0.08333333 | 13 | 3 | 23.08% | 10 |
| W07\|episode-band-00\|W07_E001 | 50 | 10 | 1.00000000 | 0.20000000 | 0.20000000 | 11 | 1 | 9.09% | 10 |
| W07\|episode-band-01\|W07_E002 | 53 | 10 | 1.00000000 | 0.18867925 | 0.18867925 | 14 | 4 | 28.57% | 10 |
| W07\|episode-band-02\|W07_E004 | 53 | 10 | 1.00000000 | 0.18867925 | 0.18867925 | 11 | 1 | 9.09% | 10 |
| W07\|episode-band-03\|W07_E006 | 48 | 10 | 0.50000000 | 0.20833333 | 0.10416667 | 10 | 0 | 0.00% | 10 |
| W07\|episode-band-04\|W07_E008 | 44 | 10 | 1.00000000 | 0.22727273 | 0.22727273 | 14 | 4 | 28.57% | 10 |
| W07\|episode-band-05\|W07_E009 | 52 | 10 | 1.00000000 | 0.19230769 | 0.19230769 | 15 | 5 | 33.33% | 10 |
| W07\|episode-band-06\|W07_E010 | 48 | 10 | 1.00000000 | 0.20833333 | 0.20833333 | 13 | 3 | 23.08% | 10 |
| W07\|episode-band-07\|W07_E012 | 49 | 10 | 0.50000000 | 0.20408163 | 0.10204082 | 11 | 1 | 9.09% | 10 |
| W08\|episode-band-00\|W08_E001 | 47 | 10 | 1.00000000 | 0.21276596 | 0.21276596 | 14 | 4 | 28.57% | 10 |
| W08\|episode-band-01\|W08_E002 | 63 | 10 | 1.00000000 | 0.15873016 | 0.15873016 | 12 | 2 | 16.67% | 10 |
| W08\|episode-band-02\|W08_E004 | 52 | 10 | 1.00000000 | 0.19230769 | 0.19230769 | 11 | 1 | 9.09% | 10 |
| W08\|episode-band-03\|W08_E005 | 61 | 10 | 0.50000000 | 0.16393443 | 0.08196721 | 14 | 4 | 28.57% | 10 |
| W08\|episode-band-04\|W08_E008 | 66 | 10 | 1.00000000 | 0.15151515 | 0.15151515 | 10 | 0 | 0.00% | 10 |
| W08\|episode-band-05\|W08_E009 | 53 | 10 | 1.00000000 | 0.18867925 | 0.18867925 | 11 | 1 | 9.09% | 10 |
| W08\|episode-band-06\|W08_E010 | 60 | 10 | 1.00000000 | 0.16666667 | 0.16666667 | 11 | 1 | 9.09% | 10 |
| W08\|episode-band-07\|W08_E012 | 59 | 10 | 0.50000000 | 0.16949153 | 0.08474576 | 13 | 3 | 23.08% | 10 |
| W09\|episode-band-00\|W09_E004 | 59 | 10 | 0.25000000 | 0.16949153 | 0.04237288 | 14 | 4 | 28.57% | 10 |
| W09\|episode-band-01\|W09_E007 | 61 | 10 | 0.25000000 | 0.16393443 | 0.04098361 | 10 | 0 | 0.00% | 10 |
| W09\|episode-band-02\|W09_E010 | 46 | 10 | 0.25000000 | 0.21739130 | 0.05434783 | 11 | 1 | 9.09% | 10 |
| W09\|episode-band-03\|W09_E015 | 46 | 10 | 0.20000000 | 0.21739130 | 0.04347826 | 11 | 1 | 9.09% | 10 |
| W09\|episode-band-04\|W09_E021 | 47 | 10 | 0.25000000 | 0.21276596 | 0.05319149 | 12 | 2 | 16.67% | 10 |
| W09\|episode-band-05\|W09_E024 | 60 | 10 | 0.25000000 | 0.16666667 | 0.04166667 | 11 | 1 | 9.09% | 10 |
| W09\|episode-band-06\|W09_E028 | 41 | 10 | 0.25000000 | 0.24390244 | 0.06097561 | 12 | 2 | 16.67% | 10 |
| W09\|episode-band-07\|W09_E036 | 54 | 10 | 0.20000000 | 0.18518519 | 0.03703704 | 14 | 4 | 28.57% | 10 |
| W10\|episode-band-00\|W10_E001 | 45 | 10 | 0.50000000 | 0.22222222 | 0.11111111 | 12 | 2 | 16.67% | 10 |
| W10\|episode-band-01\|W10_E003 | 46 | 10 | 0.33333333 | 0.21739130 | 0.07246377 | 12 | 2 | 16.67% | 10 |
| W10\|episode-band-02\|W10_E007 | 48 | 10 | 0.33333333 | 0.20833333 | 0.06944444 | 11 | 1 | 9.09% | 10 |
| W10\|episode-band-03\|W10_E012 | 42 | 10 | 0.33333333 | 0.23809524 | 0.07936508 | 10 | 0 | 0.00% | 10 |
| W10\|episode-band-04\|W10_E015 | 39 | 10 | 0.50000000 | 0.25641026 | 0.12820513 | 10 | 0 | 0.00% | 10 |
| W10\|episode-band-05\|W10_E016 | 50 | 10 | 0.33333333 | 0.20000000 | 0.06666667 | 11 | 1 | 9.09% | 10 |
| W10\|episode-band-06\|W10_E019 | 46 | 10 | 0.33333333 | 0.21739130 | 0.07246377 | 10 | 0 | 0.00% | 10 |
| W10\|episode-band-07\|W10_E025 | 53 | 10 | 0.33333333 | 0.18867925 | 0.06289308 | 13 | 3 | 23.08% | 10 |
| W11\|episode-band-00\|W11_E001 | 48 | 10 | 0.50000000 | 0.20833333 | 0.10416667 | 11 | 1 | 9.09% | 10 |
| W11\|episode-band-01\|W11_E006 | 20 | 10 | 0.33333333 | 0.50000000 | 0.16666667 | 11 | 1 | 9.09% | 10 |
| W11\|episode-band-02\|W11_E007 | 38 | 10 | 0.50000000 | 0.26315789 | 0.13157895 | 13 | 3 | 23.08% | 10 |
| W11\|episode-band-03\|W11_E011 | 41 | 10 | 0.33333333 | 0.24390244 | 0.08130081 | 10 | 0 | 0.00% | 10 |
| W11\|episode-band-04\|W11_E015 | 34 | 10 | 0.33333333 | 0.29411765 | 0.09803922 | 11 | 1 | 9.09% | 10 |
| W11\|episode-band-05\|W11_E016 | 26 | 10 | 0.50000000 | 0.38461538 | 0.19230769 | 12 | 2 | 16.67% | 10 |
| W11\|episode-band-06\|W11_E018 | 34 | 10 | 0.33333333 | 0.29411765 | 0.09803922 | 10 | 0 | 0.00% | 10 |
| W11\|episode-band-07\|W11_E023 | 35 | 10 | 0.33333333 | 0.28571429 | 0.09523810 | 11 | 1 | 9.09% | 10 |

### 全部 88 个剧集选集层

| 作品 | 集序层（0–7） | 合格集数 | 最初选集 | 选集概率 |
| --- | --- | --- | --- | --- |
| W01 | 0 | 2 | W01_E002 | 0.50000000 |
| W01 | 1 | 3 | W01_E005 | 0.33333333 |
| W01 | 2 | 2 | W01_E007 | 0.50000000 |
| W01 | 3 | 3 | W01_E010 | 0.33333333 |
| W01 | 4 | 3 | W01_E015 | 0.33333333 |
| W01 | 5 | 2 | W01_E016 | 0.50000000 |
| W01 | 6 | 3 | W01_E019 | 0.33333333 |
| W01 | 7 | 3 | W01_E024 | 0.33333333 |
| W02 | 0 | 2 | W02_E001 | 0.50000000 |
| W02 | 1 | 3 | W02_E004 | 0.33333333 |
| W02 | 2 | 3 | W02_E008 | 0.33333333 |
| W02 | 3 | 3 | W02_E012 | 0.33333333 |
| W02 | 4 | 3 | W02_E015 | 0.33333333 |
| W02 | 5 | 3 | W02_E018 | 0.33333333 |
| W02 | 6 | 3 | W02_E021 | 0.33333333 |
| W02 | 7 | 3 | W02_E026 | 0.33333333 |
| W03 | 0 | 3 | W03_E002 | 0.33333333 |
| W03 | 1 | 3 | W03_E007 | 0.33333333 |
| W03 | 2 | 3 | W03_E010 | 0.33333333 |
| W03 | 3 | 3 | W03_E011 | 0.33333333 |
| W03 | 4 | 3 | W03_E017 | 0.33333333 |
| W03 | 5 | 3 | W03_E020 | 0.33333333 |
| W03 | 6 | 3 | W03_E021 | 0.33333333 |
| W03 | 7 | 4 | W03_E027 | 0.25000000 |
| W04 | 0 | 1 | W04_E001 | 1.00000000 |
| W04 | 1 | 1 | W04_E002 | 1.00000000 |
| W04 | 2 | 1 | W04_E004 | 1.00000000 |
| W04 | 3 | 2 | W04_E005 | 0.50000000 |
| W04 | 4 | 1 | W04_E008 | 1.00000000 |
| W04 | 5 | 1 | W04_E009 | 1.00000000 |
| W04 | 6 | 1 | W04_E010 | 1.00000000 |
| W04 | 7 | 2 | W04_E013 | 0.50000000 |
| W05 | 0 | 14 | W05_E014 | 0.07142857 |
| W05 | 1 | 14 | W05_E027 | 0.07142857 |
| W05 | 2 | 14 | W05_E033 | 0.07142857 |
| W05 | 3 | 14 | W05_E044 | 0.07142857 |
| W05 | 4 | 14 | W05_E064 | 0.07142857 |
| W05 | 5 | 14 | W05_E085 | 0.07142857 |
| W05 | 6 | 14 | W05_E097 | 0.07142857 |
| W05 | 7 | 14 | W05_E110 | 0.07142857 |
| W06 | 0 | 2 | W06_E002 | 0.50000000 |
| W06 | 1 | 3 | W06_E006 | 0.33333333 |
| W06 | 2 | 2 | W06_E008 | 0.50000000 |
| W06 | 3 | 3 | W06_E011 | 0.33333333 |
| W06 | 4 | 3 | W06_E014 | 0.33333333 |
| W06 | 5 | 2 | W06_E017 | 0.50000000 |
| W06 | 6 | 3 | W06_E018 | 0.33333333 |
| W06 | 7 | 3 | W06_E023 | 0.33333333 |
| W07 | 0 | 1 | W07_E001 | 1.00000000 |
| W07 | 1 | 1 | W07_E002 | 1.00000000 |
| W07 | 2 | 1 | W07_E004 | 1.00000000 |
| W07 | 3 | 2 | W07_E006 | 0.50000000 |
| W07 | 4 | 1 | W07_E008 | 1.00000000 |
| W07 | 5 | 1 | W07_E009 | 1.00000000 |
| W07 | 6 | 1 | W07_E010 | 1.00000000 |
| W07 | 7 | 2 | W07_E012 | 0.50000000 |
| W08 | 0 | 1 | W08_E001 | 1.00000000 |
| W08 | 1 | 1 | W08_E002 | 1.00000000 |
| W08 | 2 | 1 | W08_E004 | 1.00000000 |
| W08 | 3 | 2 | W08_E005 | 0.50000000 |
| W08 | 4 | 1 | W08_E008 | 1.00000000 |
| W08 | 5 | 1 | W08_E009 | 1.00000000 |
| W08 | 6 | 1 | W08_E010 | 1.00000000 |
| W08 | 7 | 2 | W08_E012 | 0.50000000 |
| W09 | 0 | 4 | W09_E004 | 0.25000000 |
| W09 | 1 | 4 | W09_E007 | 0.25000000 |
| W09 | 2 | 4 | W09_E010 | 0.25000000 |
| W09 | 3 | 5 | W09_E015 | 0.20000000 |
| W09 | 4 | 4 | W09_E021 | 0.25000000 |
| W09 | 5 | 4 | W09_E024 | 0.25000000 |
| W09 | 6 | 4 | W09_E028 | 0.25000000 |
| W09 | 7 | 5 | W09_E036 | 0.20000000 |
| W10 | 0 | 2 | W10_E001 | 0.50000000 |
| W10 | 1 | 3 | W10_E003 | 0.33333333 |
| W10 | 2 | 3 | W10_E007 | 0.33333333 |
| W10 | 3 | 3 | W10_E012 | 0.33333333 |
| W10 | 4 | 2 | W10_E015 | 0.50000000 |
| W10 | 5 | 3 | W10_E016 | 0.33333333 |
| W10 | 6 | 3 | W10_E019 | 0.33333333 |
| W10 | 7 | 3 | W10_E025 | 0.33333333 |
| W11 | 0 | 2 | W11_E001 | 0.50000000 |
| W11 | 1 | 3 | W11_E006 | 0.33333333 |
| W11 | 2 | 2 | W11_E007 | 0.50000000 |
| W11 | 3 | 3 | W11_E011 | 0.33333333 |
| W11 | 4 | 3 | W11_E015 | 0.33333333 |
| W11 | 5 | 2 | W11_E016 | 0.50000000 |
| W11 | 6 | 3 | W11_E018 | 0.33333333 |
| W11 | 7 | 3 | W11_E023 | 0.33333333 |

## 参考审核与质量流程

参考双审均以原 packet 为输入，第二轮 fresh 且隐藏第一轮，裁决阶段才额外读取匿名、打乱顺序的意见。只在原日文上下文支持确定修改时修订；不能可靠解决的窗隔离后按同层候补补足。最终 934 agreed＋266 adjudicated；保留范围 primary 1,200＋review 1,200＋adjudication 266＝2,666 jobs。历史移除范围 primary 228＋review 228＋adjudication 65＝521 jobs，合计 3,187。所有参考任务一次成功，程序核验 raw/canonical、prompt/packet/schema 和请求设置，不能由哈希或格式检查证明复核推理正确。

正式主判预期为旧集 332、新集 4,800 个候选窗口位置，共 5,132。实际主判 CLI job 为 5,131：一个全无可评分交付的位置按程序保留交付零，不伪造裁判调用。新增 primary 4,799 个逻辑 job／4,800 attempts，review 3,168／3,169，裁决 824／824；旧集 primary 332、review 224、裁决 51。主复审风险并集及固定抽样使复审量高于最小 20%，这是预声明流程的真实成本，不是事后增加好分数样本。两个 schema/证据验证失败仅对相同冻结包允许一次重试，transport failures 为零；所有状态、空分、交付零仍须在最终质量表保留其不同含义。

## 全阶段 CLI 调用、时间和 usage

以下 worker 秒为各次请求 elapsed 的累加，包含失败重试，不是串行等待时间或 CPU/provider 计算时间。cache write input 各阶段均为零，故不再独立列一栏；cached input 不另加进 input，reasoning output 不另加进 output。四次 subagent 合成探针只计调用，usage 未提供。不存在权威实付费用、quota 或 provider API 计费请求总数，不做货币换算。

| 阶段 | 逻辑任务 | 实际尝试 | 累计 worker 秒 | input | cached input | output | reasoning output |
| --- | --- | --- | --- | --- | --- | --- | --- |
| reference-primary | 1428 | 1428 | 34923.359448 | 17,002,519 | 0 | 933,171 | 594,057 |
| reference-review | 1428 | 1428 | 34506.903221 | 17,002,341 | 78,848 | 955,382 | 618,029 |
| reference-adjudication | 331 | 331 | 9058.968759 | 4,237,076 | 0 | 284,288 | 142,369 |
| dev-primary | 164 | 164 | 3379.261540 | 1,788,092 | 616,448 | 76,678 | 51,636 |
| dev-review | 120 | 120 | 2447.103521 | 1,308,921 | 652,288 | 61,926 | 41,614 |
| dev-adjudication | 29 | 29 | 627.980746 | 330,668 | 35,840 | 17,926 | 8,842 |
| formal-regression-primary | 332 | 332 | 4919.477829 | 3,621,037 | 1,870,848 | 159,473 | 108,817 |
| formal-regression-review | 224 | 224 | 3852.558426 | 2,445,092 | 1,541,120 | 131,085 | 91,052 |
| formal-regression-adjudication | 51 | 51 | 778.194999 | 582,712 | 114,688 | 28,987 | 13,578 |
| formal-expanded-primary | 4799 | 4800 | 73428.491248 | 52,777,913 | 33,926,400 | 2,473,412 | 1,650,313 |
| formal-expanded-review | 3168 | 3169 | 58470.934405 | 34,863,728 | 22,396,416 | 1,945,906 | 1,317,585 |
| formal-expanded-adjudication | 824 | 824 | 15687.082169 | 9,511,906 | 5,179,648 | 507,683 | 238,210 |
| probe-cli | 4 | 4 | 39.123047 | 42,098 | 0 | 769 | 305 |
| probe-cli-six | 6 | 6 | 72.020926 | 63,144 | 0 | 1,251 | 572 |

总计 12,908 CLI 逻辑 jobs／12,910 attempts＋4 subagent＝12,914 调用；正式质量 9,398／9,400，dev 313／313，CLI 合成探针 10／10，参考历史 3,187／3,187。dev 克隆 164 份不重计，真实参考六窗探针已包含在 reference-primary。总 input 145,577,247，cached input 66,412,544，output 7,577,937，reasoning output 4,876,979；总 worker 242,191.460285 秒（67.275406 小时）。

### 实际 chronology 与探针口径

每行 interval union 仅在该行内计算，行间存在历史并发或空档，不能相加为全局等待时间。

| 实际阶段（UTC） | 首个 attempt | 末个 attempt | attempt 首末跨度秒 | 区间并集秒 | 峰值 |
| --- | --- | --- | --- | --- | --- |
| reference-all-history | 2026-10-06T13:52:28.818227+00:00 | 2026-10-06T18:16:58.266490+00:00 | 15869.448263 | 13453.347251 | 6 |
| dev-primary | 2026-10-06T15:17:36.016511+00:00 | 2026-10-06T15:40:03.331847+00:00 | 1347.315336 | 586.779532 | 6 |
| dev-review | 2026-10-06T17:03:28.140713+00:00 | 2026-10-06T17:10:35.499511+00:00 | 427.358798 | 427.358798 | 6 |
| dev-adjudication | 2026-10-06T17:10:42.917237+00:00 | 2026-10-06T17:12:43.719830+00:00 | 120.802593 | 120.802593 | 6 |
| formal-regression-primary | 2026-10-06T21:22:24.201036+00:00 | 2026-10-06T21:36:10.459065+00:00 | 826.258029 | 826.258029 | 6 |
| formal-regression-review | 2026-10-06T21:36:30.434367+00:00 | 2026-10-06T21:47:25.298098+00:00 | 654.863731 | 654.863731 | 6 |
| formal-regression-adjudication | 2026-10-06T21:47:43.844957+00:00 | 2026-10-06T21:50:03.215248+00:00 | 139.370291 | 139.370291 | 6 |
| formal-expanded-primary | 2026-10-06T21:50:29.912596+00:00 | 2026-10-07T01:14:45.060134+00:00 | 12255.147538 | 12255.147538 | 6 |
| formal-expanded-review | 2026-10-07T01:20:04.885955+00:00 | 2026-10-07T04:02:43.076639+00:00 | 9758.190684 | 9758.190684 | 6 |
| formal-expanded-adjudication | 2026-10-07T04:10:00.638813+00:00 | 2026-10-07T04:53:42.844719+00:00 | 2622.205906 | 2622.205906 | 6 |
| probe-cli | 2026-10-06T13:45:58.665033+00:00 | 2026-10-06T13:47:55.302572+00:00 | 116.637539 | 20.262600 | 3 |
| probe-cli-six | 2026-10-06T13:48:37.965238+00:00 | 2026-10-06T13:48:54.775959+00:00 | 16.810721 | 16.810721 | 6 |

四 subagent 探针从 dispatch 到全部验证 75.741392 秒（3.168677 job/min），六 CLI 合成调度 16.826955 秒（21.394246 job/min），真实六窗参考初审调度 55.920454 秒（6.437716 job/min）。按最小 8,592 jobs 加 20% allowance 的三种早期外推分别为 54.230837／8.032066／26.692697 小时。不同 packet、传输、任务阶段及观察开销不等价；后来实际工作量含补位、风险复审与仲裁，不能用合成吞吐证明正式吞吐或承诺工期。

全局 CLI 区间并集 40,870.988583 秒；13:45:58.665033–次日 04:53:42.844719 UTC 首末跨度 54,464.179686 秒。首次 subagent 探针 13:44:26.624488 UTC 到实际工具终态观察 04:56:09.703326 UTC 为 54,703.078838 秒。正式 quality reservation 从 18:46:36.555164 到次日 04:55:45.091317 UTC 持有 36,548.536153 秒，到真实工具终态观察为 36,573.148162 秒；native drain/lock proof 于 04:56:14.846586 UTC 完成。单一 watcher 的质量流水线终结不包含仍独立运行的 GPU 正式稳定性。

### 历史七并发偏差

| 2026-10-06 UTC 起止 | 保存区间秒 | 情况 |
| --- | --- | --- |
| 15:39:52.922756–15:39:56.223291 | 3.300535 | dev 恢复 1＋reference review 6 |
| 15:39:56.241505–15:40:03.331847 | 7.090342 | dev 恢复 1＋reference review 6 |
| 合计 | 10.390877 | 观测峰值 7，偏离共用最多 6 的要求 |

没有已查明的直接用户例外授权；parent 的单任务协调指令与 recovery scope note 不能证明用户豁免。正式后续峰值六及原生全局锁不是追溯执法。当前 docs SHA/mtime 也不代表该规则历史生效时间。区间外层时间包含调用前后账本和临时目录开销；恢复 attempt 的 timestamp span 比 transport elapsed 多 0.0028132 秒，缺少 provider start/end 与完整 CLI PID lifetime，不能伪造精确 provider 重叠，也不能据此删除已记录的 6＋1 偏差。原记录保留，后补 v2 纠正“authorized overlap”措辞。

## 冻结配方、资产与复现入口

| 字段 | 正式冻结值 |
| --- | --- |
| temperature | 0 |
| seed | 20261006 |
| n_predict | 1024 |
| context_size | 4096 |
| batch | 256 |
| ubatch | 128 |
| gpu_layers | 99 |
| flash_attention | on |
| fit | off |
| parallel | 1 |
| max_attempts | 2 |
| cpu_offload_allowed | False |
| threads | 8 |
| threads_batch | 8 |
| cache_type_k | f16 |
| cache_type_v | f16 |
| cache_ram_mib | 8192 |

除此以外，固定 `native-target-json-gbnf-v3`、`token-ids-v1`、`no_think`、单窗口 fresh、`cache_prompt:false`；每次仅一个 GPU 模型。请求 layers 99 本身不是全驻留证明，实际 loader/offload 和资源曲线需各 session 证据。CPU_Mapped 不等同 CPU 实际驻留。温度零不代替实测译文 hash 一致性；后轮重测只能作性能／确定性诊断。

| 量化 | 来源 repository | revision | bytes | SHA256 |
| --- | --- | --- | --- | --- |
| Q3_K_M（现基线） | GrahLnn/Hy-MT2-30B-A3B-4bit-GGUF | 4ae7787177f6d4f2d54ec2d543d9fe5f9114d1c9 | 14,446,329,888 | 9398dedb6f783963f0e9b7fc6ecb16a0158a92aa9a4c0a25eab29ba9704c19d5 |
| i1-Q3_K_M | mradermacher/Hy-MT2-30B-A3B-i1-GGUF | c36beb0d9a93b2790313f6beff90482b492ce820 | 14,446,330,368 | a70d7755b52cc96999c9d5645f881647c598967a5142b0177d7a6c018a4a3a46 |
| APEX-I-Compact | alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF | 312cce865e03a0718e36cfd1077e6307957aef72 | 15,035,838,080 | 8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a |
| i1-Q3_K_L | mradermacher/Hy-MT2-30B-A3B-i1-GGUF | c36beb0d9a93b2790313f6beff90482b492ce820 | 15,644,000,768 | e63046e3379cc2cd43116146c42c2b433e8a6a7d86e85b13924f4a479c94395b |

兼容引擎 identity 为 `llama-b11429-hyv3-router-bias-v1`，上游 commit `d81235049384534c167caea52b85a694f6103d14`，server SHA256 `7e236243c9b670c6a49410c03186fd575c57a0efe3fd8a21d8727503d571d5b6`。完整 33 DLL、兼容补丁、构建环境及之后真实 GPU 验证在[精确身份附录](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report-draft-preparation/exact-identity-appendix.json>)，formal freeze 的全部 33 DLL 哈希与该附录元数据一致。该 identity 原始创建状态不代表后来的 GPU 验证状态，不能复制其旧“待 smoke”字段充当本轮结果。

| 文件 | SHA256 |
| --- | --- |
| model-input/expanded.jsonl | 3d9792ad5b09e7cfccf5fac2f8feff67a94f23e871655e0aa7417971ed312b8e |
| reference/expanded.jsonl | 81ddbb69366ac85bbf9f229e579a404363fff1bce2eead5769f6818085435532 |
| source-manifest.json | 085c7ddaaa0e86d9c1a5f7676a31c2747ca227db3c4c21b26ce988988b5211ae |
| corpus freeze-manifest.json | 456b3828b3583bde36564d6f55ebaba58a46dd3b10f4cdf658c182b753d7708f |
| formal-freeze-v4/freeze.json | 819e918ced141c5f89203c1f317927b167d466cf7c9afcbf8ab4d5e58b95e559 |

初始 sampling manifest SHA `b1f56347a068be9b3c1545f7709d93d666de1bdd26cfb4017b4fa7ef938ff3be` 保持历史 staged 状态；推理是否可用由最终 `freeze-manifest.json` 判定，不能要求改写历史状态。初始 `builder-snapshot/prepare-current.py` SHA `278520297dcb621255f905973dbfcc0e7bfe4fee27730fc746450dce74eb0a36`；最终代码在 `final-freeze-snapshots/237e8ddb6c66c19900c526c69fe7943c5d168107ca5d5f517691629c478f740a/`，不覆盖初始快照。历史提示来源 LF SHA `a42781eea632b4e52e6cfc479eb6f77395d7e7616684d23b910ad9fe2a394e86`，实际执行 CRLF SHA `d7a370108d1d35689a988c44141f52947131dc617a1b310955c98190b76957d8`。发布阶段只接受严格 LF→CRLF 等价，且只排除两个根控制锁 `.reference-orchestration.lock`／`.judge-scheduler.lock`；两次先前发布失败及三份未发布导出已精确归档，新执行身份最后成功发布，不构成新增审核或静默改写。

实际传输使用 `codex-cli 0.160.1` 的 `codex exec --model gpt-6.1-sol --ephemeral --ignore-user-config --sandbox read-only --skip-git-repo-check --json --output-schema ... --output-last-message ... -c model_reasoning_effort="high"`，在每次全新空 cwd 下通过 stdin 提供冻结提示与一个 packet。关闭 web、项目文档、MCP、shell、Apps、plugins、multi_agent、memories 等全部启用工具能力；实际完整参数和可用环境字段见逐 attempt 的 command 与 raw 事件以及冻结 runner 快照。全部 12,910 CLI attempts 完整 returned model/effort 未暴露；仅证明固定请求配置及真实 CLI/raw 追溯，不冒充已验证服务端身份。

| 复现阶段 | 实际入口／冻结证据 | 新输出与保护 |
| --- | --- | --- |
| 源抽样、参考和补位 | `experiments.translation_corpus` 的 prepare/reconcile/replace-excluded/freeze；`experiments.translation_reference_judge --phase primary/review/adjudication`；初始及最终 builder 快照 | 新 corpus 目录；冻结同层候补；第二轮独立；已成功任务不重复分发 |
| 四模型正式冻结与推理 | [实际 commands-v6.ps1](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-launch-preparation/commands-v6.ps1>)、[formal freeze-v4](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-freeze-v4/freeze.json>)；`experiments.translation_four_quantization freeze/run --stage preflight/performance/stability` | 先复核 source_snapshots、inputs、reference、asset/engine/DLL 身份；新 attempt 输出，不直接执行会复用原输出名的旧命令 |
| 首轮质量导出与评分 | `export-quality`、`experiments.translation_eval prepare/select-review/finalize`、`experiments.translation_judge run`；[实际 watcher v6](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-launch-preparation/watch_round1_v6.py>) | 新评估目录；唯一首轮最早终态快照；全局原生六 worker 额度串行参考/dev/质量，所属进程及后代排空后释放 |
| 成本、性能和统计 | `experiments.translation_four_performance`、`experiments.translation_four_stats` 与各已执行 renderer/source 快照 | 读取完整来源与分母写入新汇总目录；先验区分工程／正式／稳定性，不能将恢复会话选作更优质量结果 |

所有 Python 入口使用仓库 uv 项目 `.venv/Scripts/python.exe -B -X utf8`。上述是已实现的实际模块与冻结入口清单，不是本稿重新执行记录；网络认证裁判调用仍按项目规定 escalation。原路径和源码字节需校验后才复现；修改输入、提示、配方或代码需要新身份，新运行不覆写任何原账本。正式四轮顺序为 APEX→i1-M→基线→i1-L；i1-M→基线→i1-L→APEX；基线→i1-L→APEX→i1-M；i1-L→APEX→i1-M→基线。正式翻译成本的所有轮值、中位数、范围与失败成本见[四轮成本细表](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report-draft-preparation/formal-performance-fragment-v1/cost-summary-appendix.md>)及其[数值投影](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report-draft-preparation/formal-performance-fragment-v1/numeric-tables.json>)；基线失败会话成本不是合格速度，相对基线的合格性能比较仍须保持其 NA。

## 证据映射

下表绑定本节读取的权威文件，不将早期 integrated v5 的待补字段当最终状态来源。完整 machine-readable 计数及输入前后稳定性另存 `validated-numbers.json`、`evidence-map.json`、`validation.json`。

| 证据角色 | 入口 | SHA256 |
| --- | --- | --- |
| plan | [hy30-four-quantization-comparison.md](<D:/AI_Projects/kototoki/docs/plans/hy30-four-quantization-comparison.md>) | a4d6d3083bb93762ad7d1148d5a482a47787aa058f7117261e0ccb94ce9f4cfc |
| workflow | [subtitle-translation-evaluation.md](<D:/AI_Projects/kototoki/docs/agents/subtitle-translation-evaluation.md>) | ed005fa0c91de1f3e85a90fca98c0018a15afe09f339dada53bfa85cca3bdab8 |
| execution_accounting | [execution-complete.md](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/judge-probe/full-pipeline-accounting-v1/execution-complete.md>) | 5a099ec18629c9d8a7c083ed3d4bebed1d2ba749518723e0d7daa05420fc133c |
| all_phase_usage | [all-phase-usage-supplement.json](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/judge-probe/full-pipeline-accounting-v1/all-phase-usage-supplement.json>) | 207b68824f68a06bb937b52130c1f227b2277df6a93f5d79b6f49617d1df658f |
| historical_concurrency | [historical-concurrency-disclosure-v2.json](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/judge-probe/full-pipeline-accounting-v1/historical-concurrency-disclosure-v2.json>) | 02edf85d9eda1b792d0d72e9744f935cf04c2037b0b24ee662305f575ad77d42 |
| external_integrity | [final-external-integrity.json](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/final-external-v2-readonly-audit-v1/final-external-integrity.json>) | cb9ba786eaf9fc934c17340ec710deb06c14011ef2a516fc46ad3ecbf4f10f73 |
| reference_accounting | [summary.json](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/judge-probe/reference-final-accounting-v1/summary.json>) | a60c93c6c477375602695a18aaa18f9bfcf68063fda584d736c1e80c24e5d19e |
| source_audit | [final-source-audit-20261006T183745233032Z.json](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/corpus-audit/final-source-audit-preparation/final-source-audit-20261006T183745233032Z.json>) | b67e2e47f08a7c3e686c3e885556f999d16bf395510013ea3f5dae2b7ef91788 |
| sampling_frame | [frame.jsonl](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/corpus/hy30-expanded-v1/audit/frame.jsonl>) | e82822ac0eee73e9f575a132114a419fb3e91de2a4ea3239a3a0afa44ce1fae6 |
| strata | [strata.json](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/corpus/hy30-expanded-v1/audit/strata.json>) | abdf58c89cd8394814e18ba230c1bc003df85bf8f2d7647d8741c7680380cb3b |
| replacements | [replacements.jsonl](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/corpus/hy30-expanded-v1/audit/replacements.jsonl>) | 6635c2de9d43cd30ea811a2cc7de5cef47d021da9dd5248f53c197a35b168dfa |
| reference_freeze | [freeze-manifest.json](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/corpus/hy30-expanded-v1/freeze-manifest.json>) | 456b3828b3583bde36564d6f55ebaba58a46dd3b10f4cdf658c182b753d7708f |
| formal_freeze | [freeze.json](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-freeze-v4/freeze.json>) | 819e918ced141c5f89203c1f317927b167d466cf7c9afcbf8ab4d5e58b95e559 |
| reference_binding | [reference-success-audit-binding-v6.json](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-launch-preparation/reference-success-audit-binding-v6.json>) | 421d17e54a0fabd1965affab6a6e7e4644d86cff8281414913543a7ea1fc92e6 |
| identity_appendix | [exact-identity-appendix.json](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report-draft-preparation/exact-identity-appendix.json>) | f40cfc7f1c5d93d6c622078dae71bda47c30400ae00ca58191b7a6bb5b53fb9b |
| probe | [combined-probe-summary.json](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/judge-probe/combined-probe-summary.json>) | 7369253ad47605549503cad83cee80d9d7ca075e9785ef006d233139bc8ab808 |
| actual_entrypoints | [commands-v6.ps1](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-launch-preparation/commands-v6.ps1>) | f02653e1dda34a2a85cc881396875f08e0d27efefb59935a31d7722086e573ea |
| quality_watcher | [watch_round1_v6.py](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/formal-launch-preparation/watch_round1_v6.py>) | 20aae6fa30969092609ce1063d95acdaea99248e9f728dd946f637e35ef0bc43 |
| translation_cost_tables | [cost-summary-appendix.md](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report-draft-preparation/formal-performance-fragment-v1/cost-summary-appendix.md>) | c1a626caf22e456c55c1c271dbcbe51a23cd92b91ee3ef9080dd9d4d7acf49ae |
| translation_cost_numeric | [numeric-tables.json](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report-draft-preparation/formal-performance-fragment-v1/numeric-tables.json>) | 17f3f58b6c7eabbbb17a5fd5a3f797738e4e79981de83a7c5fb2b13606fd253a |
| integrated_report_v5 | [report-final-draft.md](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/report-draft-preparation/integrated-report-v5/report-final-draft.md>) | ed889b8aa4c69c1cd398fec70147782e4772c41f47423db8d8c7f55b0b90fd49 |
