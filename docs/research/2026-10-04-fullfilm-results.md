# 整片连续推理：W0 与规范化 W1

状态：两次真实GPU整片推理与CPU评测完成；同片诊断，均未达时间目标  
日期：2026-10-04  
关联：[原始保留测试与精确模型配置](2026-10-04-heldout-results.md)、[冻结规则](../testing/evaluation-config-v1.md)、[性能与离线请求证据](2026-10-04-final-performance.md)。

W0和W1均一次处理完整7,028.0426875秒音频，退出成功，未发现源坐标越界或有效native单位时间倒退。**这不证明无漏识别、无累计声学漂移或字幕达标。** 两者CER几乎相同，W1比W0多473个删除、少365个插入、少60个可测跨度，半秒确定成功则多84个。时间仍相对SRT显示边界，无人工声学真值；两者完整性联合P95/P99均为无穷大。

## 身份与完整结果

原运行f1-w0-full-r1、f1-w1norm-full-r1。配置分别为fw121-ct2482-largev3-cuda-fp16-beam5-ctx-off-vad-off-temp-fallback、wx386-largev3-pyannote-native-officialnorm-torchaudio28-forced-cuda；model/package/Python与保留对应配置逐字段相同，精确revision见上述保留报告及execution-evidence。

W0：Python3.12.15、faster-whisper1.2.1、CTranslate2 4.8.2，large-v3 CUDA float16、beam5、word timestamps、context/VAD off、chunk30、温度fallback。W1：Python3.13.16、WhisperX3.8.6、Torch/torchaudio2.8.0+cu128、Transformers4.57.6、pyannote-audio4.0.7，large-v3 CUDA float16、batch1、推荐Pyannote VAD；日语CTC CUDA float32逐片官方归一化与同emissions上的torchaudio forced_align，OOV不造时间。冻结评测core及aggregate SHA核对未变，沿用nfkc-punctuation-v2-universal-complete-invariant-boundaries。

输入 .local/audio/fatestay-full.wav，mono16kHz、112,448,683 samples、source offset0，WAV SHA bf0e59b0b89dadb72271c1feaf9bbd7d684fe6070d71b7ff06278ce8a59a85d1。完整参考 .local/references/scoring-v2/full.json，N=1026、规范化字符10,782，原1030条排除4条非口语署名；原SRT SHA2d31b51406dd33cfc3af300c9346280a31aac7b6c199208e87f1f92ce79ae583前后未变。完整PCM、参考与模型/source身份均存源登记。

| 路线 | S/D/I | CER | D率 | 文字端点完整 | 可测n/N；覆盖 |
| --- | ---: | ---: | ---: | ---: | ---: |
| W0 | 1030/474/654 | 20.0148% | 4.3962% | 897 | 652/1026；63.55% |
| W1 | 919/947/289 | 19.9870% | 8.7832% | 834 | 592/1026；57.70% |

E=max绝对起止误差，秒、nearest-rank；只在各自可测子集内计算。

| 路线 | E P50/P90/P95/P99 | 最大 | start/end有符号中位数 | 可测E>2/>5 |
| --- | ---: | ---: | ---: | ---: |
| W0 | .410/1.020/1.580/3.150 | 15.540 | −.330/−.320 | 20/4 |
| W1 | .304/.824/3.412/12.220 | 16.724 | +.100/−.285 | 38/23 |

| 路线 | 0.5秒确定+未解决；上下界 | 2秒确定+未解决；上下界 | 5秒确定+未解决；上下界 |
| --- | --- | --- | --- |
| W0 | 420+73；40.94–48.05% | 632+99；61.60–71.25% | 648+103；63.16–73.20% |
| W1 | 504+79；49.12–56.82% | 554+97；54.00–63.45% | 569+99；55.46–65.11% |

联合无穷跨度为W0 374、W1 434，P95/P99均无穷大。95%/99%目标在N1026下需要至少975/1016个确定成功，未达到。共同有效533跨度，W0/W1条件P50 .400/.301、P95 1.470/3.285、P99 3.040/12.220秒；原覆盖分母不丢弃。

| 路线 | 歧义 | 不完整 | 缺失 | 文字不匹配 | 无效时间 | coarse | text-only |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| W0 | 166 | 163 | 12 | 11 | 17 | 5 | 0 |
| W1 | 170 | 160 | 68 | 7 | 0 | 0 | 29 |

零missing/invocation_failed/alignment_failed运行不等于逐跨度成功。SRT编辑、专名、歌声和省略仍限制D/I解释，未经听辨不能把I直接称为幻觉。

## 连续性、上下文与资源

W0有8490个word units，181个非正时长、0缺失时间；有效时间29.720–7028.020秒。W1有10768个character units，其中9952个ok、816个text_only，后者可能含标点/OOV，**不是816个漏识别词**；有效时间43.156–7004.507秒。两路线有限时间均无源范围越界，按char位置及同granularity检查有效ok单位起止倒退/overlap均0；不证明自然语音无交叠或范围内文字完整。W1有200个CTC/decoder records、600个OOV slots、decoder failure0。

将source均分早/中/晚，按参考区间中点归bin，固定N384/303/339。下列仅各bin可测子集有符号中位数，不能据稳定中位数断言无累积声学漂移。

| 路线/区间 | 可测n/N | start/end中位数秒 |
| --- | ---: | ---: |
| W0早/中/晚 | 250/384；188/303；214/339 | −.310/−.320；−.330/−.330；−.350/−.325 |
| W1早/中/晚 | 226/384；175/303；191/339 | +.0925/−.278；+.105/−.297；+.102/−.285 |

原开发5章、验证3章、保留16章的相同配置评分另微汇总为24章N966/10,225字符；分章参考省略60条跨边界跨度，音频范围及上下文重置也不同。整片包含同一电影，不能加分母、重选参数或做新的bootstrap。

| 路线/上下文 | CER | D/I | 覆盖 | 半秒确定成功 | 条件P95/P99秒 |
| --- | ---: | ---: | ---: | ---: | ---: |
| W0原24章/整片 | 22.98/20.01% | 506/848；474/654 | 61.80/63.55% | 40.06/40.94% | 1.491/5.694；1.580/3.150 |
| W1原24章/整片 | 20.53/19.99% | 869/373；947/289 | 58.07/57.70% | 49.79/49.12% | 2.276/10.211；3.412/12.220 |

两种上下文联合P95/P99均无穷大。整片执行没有使目标达标，差异不能归因于单一因素。

实际RTX5080/native Windows：W0 CT2 CUDA float16；W1保存ASR设备、Pyannote model/input CUDA、CTC forward CUDA和200个decoder input/output CUDA。全部请求本地offline，无CPU、云或WSL回退。**物理断网和网络流量捕获未执行**，离线flag不是物理断网证明；独立重复性能与离线请求证据见关联报告。

| 路线 | adapter/harness秒 | ASR/CTC秒 | 全设备采样最大MiB |
| --- | ---: | ---: | ---: |
| W0 | 328.235/329.740 | 324.787/— | 7551 |
| W1 | 194.449/195.980 | 135.514/46.016 | 6949 |

这是各一次完整fresh subprocess，含加载，非重复统计。nvidia-smi约1秒全设备采样含桌面基线，非进程精确峰值。W0返回segments的max compression2.3870968、阈值2.4、超阈值0、最大同字符重复15，仅是可见指标；W1 batch缺少逐chunk实际cap/ratio遥测，未知不能写成无异常。

## 复现与限制

结果 .local/analysis/fullfilm/cpu-v1-r1。main-report SHA f19ccedcf8eb2d5880aa88e581bab7fdee8c34c8bcb1d5f0b02312fce6c02f5c；source-registry SHA e79efc69c04db583a5137f518123204a58503d944174f462358ba82b653015e3；continuity-audit SHA79b6a07eb7bfb895f4b4ac23974b9d624081579fdd66fde98fc87a25b6e1f7fe。verification.json确认重新消费manifest表相同、来源SHA未变、model/package/Python身份一致。helper副本build_fullfilm-source.py SHA47427900ba15db48b8c3417b6a50df91909ca43d66fb022c028db1550d288a70；supplement.py保存时序及分章比较方法。

~~~powershell
uv run --locked --offline python -m experiments.analysis.build_fullfilm --output '.local/analysis/fullfilm/cpu-v1-recheck-1'
~~~

入口只CPU重评既有输出，新目录且拒绝覆盖，不下载/推理模型；完整文字、映射与素材保持私有。仍缺人工声学/漏字听辨、独立多素材泛化及显示策略主观验收；单片连续性不能替代。采用排序由最终调研综合决定。
