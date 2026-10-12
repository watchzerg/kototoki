# 官方30B采样与缓存基线采纳检查

日期：2026-10-08（Asia/Singapore）。配置采纳依据为用户明确要求，见[ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md)。本记录验证配置和交付路径，不追加质量排名，也不改写此前筛选结论。

## 当前配置

模型继续为 Hy-MT2 30B-A3B APEX-I-Compact，权重与兼容引擎身份均由 ADR 固定。本次启动重新核验权重 SHA256。

| 设置 | 采用值 | 本机 native HTTP 字段 |
|---|---|---|
| temperature | 0.7 | temperature: 0.7 |
| top_p | 1.0 | top_p: 1.0 |
| top_k | -1，禁用 | top_k: 0 |
| repetition_penalty | 1.0 | repeat_penalty: 1.0 |
| max_tokens | 4096，输出上限 | n_predict: 4096 |
| 提示缓存 | 开启 | cache_prompt: true |

配方身份为 `official30b-cached-v1`。显式 `min_p:0`、`samplers:["temperature"]`、`dynatemp_range:0`、`mirostat:0`、frequency/presence penalty 0，避免引擎附加采样默认值改变上述意图。seed 为 20261006。

总 context 为8192，输入、输出预留和安全余量独立核算。模型、提示、grammar、no_think、token ID 传输均沿用原基线。缓存复用匹配的输入前缀，不向下一窗添加上窗译文。

通用 demo 保留 `legacy-greedy-v1`，历史计划及结果不变；当前基线由 `just translation-baseline` 固定新配方。完整 SRT 的新 `prepare` 默认 `b0-cached`、`official`、4096；冻结 session plan 拥有其参数，不能用 demo profile 覆盖。

## 验证与复现

本地产物根目录：`.local/translation-evaluation/official30b-cached-adoption-20261008/`。以下目录不可覆盖，重放时使用新的输出目录。

```powershell
just translation-baseline --inputs '.local/translation-evaluation/hy30-flow-20261007/selection/p0.jsonl' --output-dir '.local/translation-evaluation/official30b-cached-adoption-20261008/demo-runtime'
```

4个既有源文窗口、20个目标ID全部首试交付。实际响应确认 temperature约0.7、top_p1、top_k0、repeat_penalty1、n_predict4096、samplers仅temperature；cache_n依次为0、142、142、143。缓存下 tokens_evaluated 仍与完整输入token数一致，原核验契约通过。输出各为99、91、85、73tokens，无截断。

翻译调用耗时合计约3.115秒；受管理 runtime 总耗时45.654秒（含监测、加载及卸载等环节），冷加载7.123秒。整卡采样峰值15,871 MiB、最低空闲107 MiB；49/49层 offload，翻译退出码0，server及worker均退出。运行记录包含请求、原响应、源代码哈希、引擎身份、资源采样和清理状态。

完整 SRT 路径使用 W03_E001 原始日文第1–10条连续摘录，默认分成两批。准备、推理、导出入口如下：

```powershell
& '.venv/Scripts/python.exe' -B -X utf8 -m experiments.translation_flow prepare --source 'D:/subtitle-samples/翻译模型评估库_v2/动画v1/清洗候选/W03/W03_E001/ja.srt' --output '.local/translation-evaluation/official30b-cached-adoption-20261008/srt-prepared' --start-cue 1 --end-cue 10 --stage P0 --max-translation-calls 4 --max-judge-calls 0 --max-estimated-tokens 30000 --max-wall-seconds 600

& '.venv/Scripts/python.exe' -B -X utf8 -m experiments.translation_demo_runtime --candidate hy-mt2-30b-a3b-apex-i-compact --engine '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/llama-server.exe' --engine-identity '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/identity.json' --layers 99 --context-size 8192 --threads 8 --threads-batch 8 --session-worker experiments.translation_flow.worker --session-plan '.local/translation-evaluation/official30b-cached-adoption-20261008/srt-prepared/session-plan.json' --output-dir '.local/translation-evaluation/official30b-cached-adoption-20261008/srt-runtime'

& '.venv/Scripts/python.exe' -B -X utf8 -m experiments.translation_flow export --prepared '.local/translation-evaluation/official30b-cached-adoption-20261008/srt-prepared' --translation-run '.local/translation-evaluation/official30b-cached-adoption-20261008/srt-runtime/translation/b0-cached' --output '.local/translation-evaluation/official30b-cached-adoption-20261008/srt-export'
```

两批首试成功，实际响应采样值与上表一致；cache_n为0和150，分别输出105和102tokens。导出`chn.srt`，覆盖10/10，无缺失、额外ID或无效项，逐条比较10条时间行与源文件完全一致。完整受管理runtime耗时43.479秒，峰值15,842 MiB，49/49层offload，翻译退出码0，server及worker均退出。来源哈希、映射和机械诊断见`srt-export/export-sidecar.json`。这验证的是连续摘录的完整流程，不是全片。

离线验证：demo 44项、四量化及兼容回归15项、受影响flow测试35项，共94项通过；CLI帮助及canonical入口dry-run通过。涉及Windows TEMP写入的测试在沙箱EACCES后按仓库要求升级重试成功。

## 验证边界

本次没有调用裁判、没有重新比较翻译质量。4个窗口及SRT摘录属于配置与交付烟测，不是独立质量确认集。短输出运行通过不等于已验证实际生成4096tokens，亦不覆盖满context、全片稳定性或并发。显存余量小，整卡采样峰值不证明模型持续物理驻留；不自动减层或回退CPU。

此前关于采样波动及缓存数值差异的发现仍有效；用户采纳此配置不构成“质量稳定优于旧基线”或“缓存逐字无损”的结论。
