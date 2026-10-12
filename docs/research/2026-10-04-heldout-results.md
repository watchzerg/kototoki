# 固定保留测试：五条预锁 STT 路线

状态：原始轮次已完成，完整分母与失败均保留；描述性结果，不作项目采用决定  
日期：2026-10-04  
关联：[验证结果与锁定](2026-10-04-validation-results.md)、[开发比较](2026-10-04-dev-comparison.md)、[冻结筛选规则](../testing/evaluation-config-v1.md)、[时间基准](../testing/subtitle-timing-benchmark.md)、[汇总契约](../testing/demo-analysis-contract.md)。

## 结果与边界

五套预锁配置均以完整N=620、参考字符6,654记账。W1的0.5秒确定成功率最高（53.06%）；W0可测覆盖率最高（62.90%），条件尾部较短，但相对SRT起止偏早且插入较多。Qwen漏识别较少，原生FA覆盖较低；规范化CTC改善覆盖，却继承ASR触顶且仍有长尾。Crisp原轮次对齐覆盖不足。

**五条路线完整性与时间联合P95/P99均为无穷大，均未达到冻结时间目标。** 误差全部是SRT显示区间相对误差，缺少人工声学边界验证。条件P50不能代替全体成功率。本轮没有调整门槛、参数或重新选择W1；后续恢复或新组合不能覆盖此原轮次。

## 冻结输入和实现

推理前锁定 .local/manifests/heldout-freeze-v1.json，SHA256 f639c655017c789c095cfc62a241595484d3835b5423a9c3478ece08dd20bad5，含81份身份、五套配置和16章：04、06、08、09、10、11、12、13、15、16、18、19、20、21、22、24。输入 .local/audio/chapter-XX.wav 为mono16kHz，总时长4,463.426秒，单章58.100–748.017秒。逐章WAV SHA、source offset、duration、scoring-v2参考路径及SHA均在锁定清单和源登记中，按具体路径与SHA绑定，不能互换同分母参考。

参考corpus revision为fatestay-chapters-v1-2026-10-04；原SRT SHA为2d31b51406dd33cfc3af300c9346280a31aac7b6c199208e87f1f92ce79ae583。scoring-v2排除四条来源确认的非口语署名，没有用模型输出制作真值。章节音频可能截断跨界话语，完整SRT跨度参考可能省略边缘仍存在的话语；I不能直接等同声学幻觉。编辑、专名和歌声仍有参考不确定性。

评测规则nfkc-punctuation-v2-universal-complete-invariant-boundaries固定。连续规范化字符匹配保证拆合行不直接影响CER；所有最优路径完整、端点身份不变且native units有效、时序安全才可测。内容时间与字幕显示、声学边界分开，不按字幕行号对应或插值造时间。

| 简称 | 配置ID | 原始运行模板 |
| --- | --- | --- |
| W0 | fw121-ct2482-largev3-cuda-fp16-beam5-ctx-off-vad-off-temp-fallback | h1-w0-chXX-r1 |
| W1 | wx386-largev3-pyannote-native-officialnorm-torchaudio28-forced-cuda | h1-w1norm-chXX-r1 |
| Q0 | hf518-qwen17-fa06-cuda-bf16-sdpa-greedy-window30 | h1-q0-chXX-r1 |
| Q1 | crisp0841-qwen17-fa06-f16-vulkan0-vad-off-fa-replay | h1-q1-chXX-r1；ASR来源h1-q1asr-chXX-r1 |
| X0 | qwen17-hf518-window30-reused-officialnorm-torchaudio28-forced-cuda | h1-x0-chXX-r1 |

全部native Windows11、RTX5080，GPU作业串行，日语transcribe。harness/root与W0环境Python3.12.15；WhisperX和官方Qwen环境Python3.13.16；Crisp为native exe/DLL，不能把harness Python版本当其引擎依赖。

- W0：faster-whisper1.2.1、CTranslate2 4.8.2，Systran/faster-whisper-large-v3@edaa852ec7e145841d8ffdb056a99866b5f0a478。CUDA float16、beam5、word timestamps、chunk30、VAD off、previous context off；temperature [0,.2,.4,.6,.8,1]、compression阈值2.4，其余保存默认参数未静默改变。
- W1：WhisperX3.8.6、Torch/torchaudio2.8.0+cu128、Transformers4.57.6、pyannote-audio4.0.7，同large-v3；推荐Pyannote VAD（onset .5、offset .363、chunk30、batch1）。日语CTC为jonatasgrosman/wav2vec2-large-xlsr-53-japanese@cf031e020336460d15a417eba710bbc5bb43be9a，CUDA float32；Pyannote checkpoint SHA为0b5b3216d60a2d32fc086b47ea8c67589aaeb26b7e07fcbe620d6d0b83e209ea。逐片采用固定feature processor归一化，同一emissions上使用torchaudio CUDA forced_align/merge_tokens输出非blank spans，OOV不造时间。
- Q0：Torch2.14.1+cu130、Transformers5.18.0、Accelerate1.15.0、Nagisa0.3.0。Qwen/Qwen3-ASR-1.7B-hf@bcd2b5b7f32b480ab5790554cfa8347f246a14f3与Qwen/Qwen3-ForcedAligner-0.6B-hf@c07281df297b9905d24a508279258cccf987a064。CUDA bfloat16、SDPA、greedy、batch1、window30、max_new_tokens4096，ASR/FA顺序驻留，当前官方HF helper不额外加VAD。
- Q1：Crisp v0.8.41、源码340d7085eaa53c40a46dcb73a6d3d0448a480006，f16 GGUF ASR cstr/qwen3-asr-1.7b-GGUF@674df5d44b50a63e7102a18895ed20e3f91de301，FA cstr/qwen3-forced-aligner-0.6b-GGUF@1ec5110602ccab18c878ddebedab0891e290a95c。Vulkan0、temperature0、seed42、max512、threads4、chunk30/overlap3、VAD off、保留energy gate。先保存CLI ASR，再用同版DLL显式GPU FA重放及官方timestamp correction，成本分阶段记录。
- X0：严格复用同一Q0文字及双PCM身份，不使用参考或Q0 FA时间；新推理仅为上述规范化日语CTC与forced align，不能计作独立ASR。

Crisp ASR/FA权重SHA为ac6c58f9cb0f2bb22290319cde01b0e25a2c1f1ee69aa2f1a9265f29a8bfc9d7、35bd243939212f675652d36de061bedf09daee9a7af2a866f47e57be148a8578；exe/DLL SHA为07dbe65c4adbea6e977bc0253d0991175cbd92ee871e5a5cf33ac4eda5303658、d346663c39948cef204db12768eb340003115af9e904e25979a00c44113878a2。完整实际参数、checkpoint文件、adapter和底层decoder身份保存在逐运行记录与冻结归档。

## 完整主表

S/D/I共用6,654字符分母，所有路线N=620。

| 路线 | S | D | I | CER | D率 | 可测n/N | 覆盖 | 文字端点完整 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| W0 | 566 | 249 | 539 | 20.35% | 3.74% | 390/620 | 62.90% | 540 |
| W1 | 483 | 442 | 235 | 17.43% | 6.64% | 374/620 | 60.32% | 512 |
| Q0 | 643 | 240 | 269 | 17.31% | 3.61% | 269/620 | 43.39% | 532 |
| Q1 | 652 | 284 | 265 | 18.05% | 4.27% | 104/620 | 16.77% | 526 |
| X0 | 643 | 240 | 269 | 17.31% | 3.61% | 363/620 | 58.55% | 532 |

E=max绝对起止误差，单位秒、nearest-rank；下表只计算各自可测子集，不同路线子集不同。

| 路线 | E P50 | P95 | P99 | 最大 | start/end有符号中位数 | 可测E>2/>5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| W0 | .410 | 1.430 | 4.346 | 26.081 | −.346/−.317 | 12/3 |
| W1 | .306 | 2.627 | 10.309 | 14.628 | +.110/−.2875 | 22/12 |
| Q0 | .199 | 4.496 | 10.192 | 22.687 | +.044/−.180 | 22/13 |
| Q1 | .186 | 5.568 | 10.697 | 11.416 | +.044/−.1585 | 8/6 |
| X0 | .324 | 6.460 | 15.946 | 24.718 | +.110/−.296 | 37/25 |

全体下界=确定成功/N，上界加入确有可能成功路径的未解决跨度，不把所有歧义无条件计成功。

| 路线 | 0.5秒确定+未解决；上下界 | 2秒确定+未解决；上下界 | 5秒确定+未解决；上下界 |
| --- | --- | --- | --- |
| W0 | 261+39；42.10–48.39% | 378+57；60.97–70.16% | 387+59；62.42–71.94% |
| W1 | 329+43；53.06–60.00% | 352+48；56.77–64.52% | 362+50；58.39–66.45% |
| Q0 | 239+26；38.55–42.74% | 247+27；39.84–44.19% | 256+28；41.29–45.81% |
| Q1 | 87+8；14.03–15.32% | 96+8；15.48–16.77% | 98+11；15.81–17.58% |
| X0 | 288+42；46.45–53.23% | 326+50；52.58–60.65% | 338+54；54.52–63.23% |

联合统计将未确认完整有效时间的跨度保留为无穷大：W0/W1/Q0/Q1/X0分别230/246/351/516/257个，五者联合P95/P99均无穷大。95%/99%目标在N620下分别需要至少589/614个确定成功，当前差距明显。

| 路线 | 歧义 | 不完整 | 缺失 | 文字不匹配 | 无效时间 | coarse | text-only | 对齐失败 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| W0 | 97 | 109 | 8 | 8 | 7 | 1 | 0 | 0 |
| W1 | 83 | 110 | 29 | 5 | 0 | 0 | 19 | 0 |
| Q0 | 95 | 121 | 2 | 5 | 117 | 11 | 0 | 0 |
| Q1 | 107 | 107 | 8 | 7 | 0 | 0 | 0 | 287 |
| X0 | 87 | 129 | 2 | 5 | 0 | 0 | 29 | 5 |

## 原始失败与生成遥测

原计划96个GPU阶段，实际95次尝试：94完成、1次Crisp FA失败；X0章12导出拒绝，未启动CTC。全部16章占固定位置：X0章12保留Q0的S5/D1/I69（42字符、5跨度），Q1章20保留CLI ASR的S2/D2/I20（108字符、10跨度），各计一条alignment_failed。零missing/ASR全删除调用失败；未启动与返回失败分别记录。

Crisp章20返回2且actual_fa_gpu_verified=true；segment2只有1个Po标点、0词汇字符，官方过滤后不要求FA词输出。适配器text.strip且无words误判整轮失败，独立源码核查确认是适配器边界；不能据此宣称声学/model FA失败，也不把原轮次改成功。287失败跨度中只有10来自该整章失败，其余15章仍有大量逐词失败。

Q0共156窗口，两个4096 token触顶均在h1-q0-ch12-r1零基窗口4/5。raw/official parsed字符4096/4、7369/34；在最多32字符单元的扫描内，最长相邻字面重复分别为3字符单元×1365（4095字符）、9字符单元×816（7344字符）。章12窗口3未触顶（3864 tokens）仍有3873→1字符、3863个同字符；章06窗口6为2370 tokens、2379→1字符、2369个同字符。**低于cap只作描述，不新增失败门槛，不无人工听辨就断言声学幻觉。** 全窗口raw/parsed为26,671/7,474字符，还包括解码格式字段，不能把全部差值归因于重复清理。

章12adapter/harness耗时540.474/548.050秒；触顶导出被拒绝，X0无bridge/result/harness，完整ASR仍保留。触顶按冻结规则构成Q0及依赖X0的稳定性风险，与CER无关。

W0保存compression阈值2.4，16章返回segment未观察到超过阈值，只是可见指标，不证明所有生成正常。WhisperX batch可能缺少每chunk cap/compression遥测；Crisp配置max512但无对应逐窗口实际token/cap记录。缺少记录是未知，不能写成无触顶；observed_generation_failures为空只表示没有被现有遥测记录的事件。

## 配对与统计限度

共同有效子集只比较同一跨度，原N620和各自覆盖保留。

| 左/右 | 共同有效n | 左/右条件P95秒 | 左/右全体覆盖 |
| --- | ---: | ---: | ---: |
| W0/W1 | 336 | 1.336/2.164 | 62.90/60.32% |
| W0/Q0 | 238 | 1.430/4.496 | 62.90/43.39% |
| W0/X0 | 319 | 1.491/5.506 | 62.90/58.55% |
| W1/Q0 | 219 | .953/4.390 | 60.32/43.39% |
| W1/X0 | 312 | 2.164/4.995 | 60.32/58.55% |
| Q0/X0 | 246 | 5.258/5.093 | 43.39/58.55% |
| Q0/Q1 | 88 | 1.318/5.568 | 43.39/16.77% |

16章配对scene bootstrap，seed20261004、2,000次，差值左减右。下列95% percentile区间仅描述此片章节，不是16部独立电影的泛化置信证明。章节仍相关且篇幅不均，章08有128跨度、章24仅1跨度；稀疏章CER可超过100%。逐章配对及全部10对保存在报告。

| 左/右 | CER差百分点 | 覆盖差百分点 | 0.5秒确定成功差百分点 |
| --- | ---: | ---: | ---: |
| W0/W1 | −.50至+8.63 | −.71至+5.28 | −16.48至−6.15 |
| W1/Q0 | −3.03至+3.07 | +10.22至+22.05 | +8.18至+19.87 |
| W1/X0 | −3.03至+3.07 | −2.71至+5.51 | +3.05至+10.16 |
| Q0/X0 | 0至0 | −19.08至−11.81 | −11.87至−3.11 |

全部10对联合P95差bootstrap均2,000/2,000非有限，有限条件区间null，没有删掉无穷项制造尾部区间。Q0/X0文字差恒零源于同ASR复用，不是独立识别器打平。

描述性取舍：W0覆盖、漏字和条件尾部相对有利；W1半秒成功与插入控制有利，却比W0多193个D、少16个可测跨度；Q0比W1少202个D，却少106个可测跨度且触顶；X0保留Q0文字，增加94个可测跨度、49个半秒确定成功，仍有长尾和依赖失败。不能仅据低CER宣布全面优胜；本报告不作采用决定。

## 设备、离线与成本

W0实际CT2 CUDA float16。W1有ASR设备、Pyannote model/input CUDA、CTC forward CUDA与decoder input/output CUDA证据；16章269个OOV slots如实记录，decoder failure0。X0的15次CTC有853个OOV slots、decoder failure0，来源ASR逐窗口CUDA且双PCM一致，不使用参考或Q0 FA时间。decoder成功不等于每跨度时间成功。

Q0所有ASR及实际FA均保存model/input/output CUDA。原检查对非空raw text要求FA，章20/22三个no_alignable_tokens标点窗口未dispatch，故保守标execution_unverified；词汇窗口FA实际CUDA。原r1标签不变。独立CPU处理器重放15窗口证明3次跳过词列表为空，其余词列表与实际执行记录相同；补充 .local/audit/qwen-heldout-empty-labels/supplement-r1.json，SHA4616c393235c1bac744f1df4265e978a5e63ec1f0174e8964a616b3fb7286e0c。章20为5次ASR/3次FA/2预期跳过，章22为10次ASR/9次FA/1预期跳过；补充只澄清神经推理GPU资格，不改变评分、触顶风险或时间未达标结论。

Q1有保存CLI ASR Vulkan0设备、当前DLL preferred backend marker、无CPU fallback；章20亦GPU执行，对齐整轮仍失败。模型下载与推理分离，全批请求offline、本地checkpoint，无静默CPU、云或WSL回退证据；local_files_only与环境变量不单独证明物理断网。16次独立章节启动、最长连续748.017秒处理不能替代整片单会话或跨章连续性。

| 路线 | adapter累计秒 | harness累计秒 | 主要推理秒 | 全设备采样最大MiB |
| --- | ---: | ---: | ---: | ---: |
| W0，16次 | 362.240 | 374.763 | ASR314.857 | 7583 |
| W1，16次 | 504.681 | 528.384 | ASR233.703/CTC89.410 | 6948 |
| Q0，16次 | 1260.307 | 1378.886 | ASR1098.375/FA12.736 | 6997 |
| Q1，16ASR+16FA尝试 | ASR158.098+FA98.948=257.046 | ASR239.171+FA135.034=374.204 | 分阶段wall，含失败 | 6381（15成功FA摘要） |
| X0，15次新CTC | 233.926 | 255.252 | CTC130.313 | 4433 |

Q1是分阶段之和，X0必须另计已有Q0 ASR来源成本，不能把缓存当新ASR或端到端测速。fresh subprocess重复加载，成本含加载/校验，不等于常驻服务速度。GPU串行但CPU准备可并行，速度为探索观测而非重复统计。nvidia-smi约1秒全设备采样含桌面基线，非进程精确峰值，不作显存硬下限。

Q0 allocator最大ASR allocated/reserved为4,636,884,480/4,785,700,864 bytes，FA为2,105,944,064/2,369,781,760 bytes；顺序驻留不应相加。Crisp失败章20harness6.300秒、FA4.491秒已计入成本。

## 重现与身份复核

不可变CPU快照 .local/analysis/heldout/cpu-v2-r1。评分前冻结所有原result/harness/上游存在性及SHA，缺失X0明确登记。随后独立核对319个文件位置、重消费manifest得到相同主表，逐章S/D/I与N相加一致，Q0/X0完整文字计数相同；两失败章D仍为1/2。核查记录 .local/analysis/heldout/cpu-v2-r1-check/verification.json。

| 文件 | SHA256 |
| --- | --- |
| source-registry.json | a42817cadc05acd5f0922f5b69d51cf2284cc2b3872dfb919270492687fa681d |
| main-manifest.json | c200563aca4dc91638e3343cf727f02f5fdf75b0f249c2ce87d5890f1ab8adbe |
| main-report.json | 0ef58b4013c80ea9e27130bc6f3a1a51a23a35dc2f06f03cd00f04e958a9e939 |
| execution-evidence.json | 294e8a6e237ff286334a37c50f347b4be4c396c4983d4cc995cf768d672f61dc |

~~~powershell
uv run --locked --offline python -m experiments.analysis.build_heldout --batch-complete --freeze '.local/manifests/heldout-freeze-v1.json' --output '.local/analysis/heldout/cpu-v2-recheck-1'
uv run --locked --offline python -m unittest experiments.analysis.test_analysis experiments.analysis.test_development experiments.analysis.test_selection experiments.analysis.test_validation experiments.analysis.test_heldout -v
~~~

复核入口只CPU重评，不是新模型推理。35项合成汇总/编排测试通过，冻结核心未修改。原始音频、完整文字、映射和模型在Git忽略的私有目录，公开本文仅标识、计数、证据身份。

尚待：人工声学时间/漏识别听辨、整片单会话、同配置重复性能、严格断网重跑、字幕显示策略验收。采用路径和后续边界由主调研交付综合。

## 原轮次之后的标点边界修复敏感性

此节不是新盲测或新配置排名。原cpu-v2-r1和失败不变；主agent在原81文件审计与源登记后，只修正Crisp非词汇片段的空FA输出检查，并以新身份h2-q1-ch20-nonlexical-r1执行FA，harness6.348秒、实际Vulkan GPU。仍复用同一h1-q1asr-ch20-r1文字。

独立比较修复前后text、units、native、cues全部相同，音频SHA相同；区别为适配器不再误判标点片段，使原先存在的有效时间可进入正常记账。保存 .local/analysis/heldout/nonlexical-recovery-r1，明确采用15章原缓存FA加1章新guard FA，全N620而非只报修复章。

| Q1观察 | 原轮次 | 边界修复敏感性 |
| --- | ---: | ---: |
| S/D/I、CER | 652/284/265、18.05% | 相同 |
| 可测n/N | 104/620、16.77% | 105/620、16.94% |
| 半秒确定成功 | 87/620、14.03% | 88/620、14.19% |
| 半秒上下界 | 14.03–15.32% | 14.19–15.48% |
| 2秒/5秒确定成功 | 96/98 | 97/99 |
| 条件P95/P99秒 | 5.568/10.697 | 相同 |
| 对齐失败跨度 | 287 | 284 |
| 歧义跨度 | 107 | 109 |
| 联合P95/P99 | 无穷大 | 无穷大 |

敏感性all_execution_verified=true只澄清整轮调用与设备，不能抹去284个逐跨度对齐失败。修复仅恢复一个可测跨度，没有改变任何预测文字或native时间，也没有使路线达标。该敏感性主报告SHA5843a879471af84827516b410be25e339cec202d81face98b98166c753fab600，源登记SHA c3b2f193ea75dce3a7284d240bf5278f457e5cfeae2e792cafd032cc572558a7。

~~~powershell
uv run --locked --offline python -m experiments.analysis.build_nonlexical_recovery --output '.local/analysis/heldout/nonlexical-recovery-recheck-1'
~~~

此入口CPU重评，要求修复前后内容/时间相同、原source SHA仍一致、独立上游ASR与新FA设备证明有效；不执行或假称重复模型推理。

快照所用builder源码另归档为 .local/analysis/heldout/nonlexical-recovery-r1-source.py（SHA566400b247d4b7e52184ce1d625a3eed48c7af9b005feff3afaddb80a54d992c）。当前入口随后增加原/新音频SHA显式相等检查，私有核查记录确认本轮相等；原快照和评分未改变。
