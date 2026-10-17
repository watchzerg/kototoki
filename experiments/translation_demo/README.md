# 本地字幕翻译 demo

独立实验入口，支持九个已获取 GGUF：Hy-MT2 7B Q8_0／30B-A3B Q3_K_M／官方 Q4_K_M／APEX-I-Compact／i1-Q3_K_L／i1-Q3_K_M、
TranslateGemma 12B Q8_0／27B Q3_K_L、Tower+ 9B Q8_0。仅连接本地 loopback
llama.cpp server，不下载模型，不启动服务器。实际 GPU 加载与质量证据由具体运行目录记录。

运行前阅读[比较计划](../../docs/plans/translation-model-comparison.md)、
[自动评估流程](../../docs/agents/subtitle-translation-evaluation.md)及
[模型资产指南](../../docs/guides/local-translation-model-assets.md)。本入口实现
`V2-native-adapted`：各窗口 fresh；完整冻结日文 context、原 translate_ids，无参考答案、
跨窗历史、全文预分析或反思。

## 当前已采纳基线

固定模型的完整SRT流程优化使用独立[translation_flow实验入口](../translation_flow/README.md)；
它维护配方、来源映射与导出；2026-10-08起默认官方30B采样、缓存和4096输出，历史B0和冻结结果保留。
2026-10-17 起，完整 SRT 流程基线为 v3 配方 `dp10-cut`（[ADR-0010](../../docs/adr/0010-dp10-cut-translation-flow-baseline.md)，入口 `just translation-srt`；同日短暂的前任为 `dp6-grp`（[ADR-0009](../../docs/adr/0009-dp6-grp-translation-flow-baseline.md)），2026-10-11 起为 `b10-joint`，[ADR-0006](../../docs/adr/0006-b10-joint-translation-flow-baseline.md)）；本 demo 的逐窗入口和身份不变。第三轮已完成（[计划](../../docs/plans/hy-mt2-translation-flow-exploration-v3.md)、[translation_v3](../translation_v3/README.md)），下一轮见[第四轮计划](../../docs/plans/hy-mt2-translation-flow-exploration-v4.md)；第二轮（[计划](../../docs/plans/hy-mt2-translation-flow-exploration-v2.md)、[台账](../../docs/context/2026-10-08-hy30-flow-exploration-v2.md)）已停止，仅作历史；[第一轮台账](../../docs/context/2026-10-07-hy30-flow-exploration.md)保留历史结果。

**Hy-MT2 30B-A3B APEX-I-Compact** 是后续字幕翻译优化、讨论与回归的基准，见[ADR-0005](../../docs/adr/0005-apex-i-compact-translation-baseline.md)。GrahLnn Q3_K_M 保留为历史对照。以下命令从仓库根目录运行完整 smoke，使用已验证的兼容引擎。每次换用尚不存在的输出目录。

推荐基线入口固定 APEX、兼容引擎、99层GPU、`official30b-cached-v1`与8192总context：
temperature0.7、top_p1、禁用top_k、repeat_penalty1、输出4096、cache_prompt=true。
官方top_k=-1在native HTTP中映射为0；max_tokens映射为n_predict，均在运行身份里记录。

```powershell
just translation-baseline --inputs 'D:/subtitle-samples/翻译模型评估库_v2/固定评测集/模型输入/smoke.jsonl' --output-dir '.local/translation-evaluation/apex-baseline-smoke-01'
```

等价的项目环境直接入口：

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_demo_runtime `
  --candidate hy-mt2-30b-a3b-apex-i-compact `
  --engine '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/llama-server.exe' `
  --engine-identity '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/identity.json' `
  --layers 99 --context-size 8192 --sampling-profile official30b-cached-v1 --n-predict 4096 --threads 8 --threads-batch 8 `
  --inputs 'D:/subtitle-samples/翻译模型评估库_v2/固定评测集/模型输入/smoke.jsonl' `
  --output-dir '.local/translation-evaluation/apex-baseline-smoke-01'
```

外层自动启动／停止本地服务，保存 `runtime/` 与 `translation/`；无需额外映射模型。`just translation-baseline` 是已采纳基线的快捷入口，其固定选项在用户参数之后传入；其他候选或配方使用通用 `just translation-demo` 后接显式参数。Python CLI 仍要求显式 candidate，Hy30 仍须提供兼容引擎与身份文件。
基线固定参数、权重身份、显存限制和后续优化的 test 隔离规则由 ADR 维护；原始比较结果和运行目录保留不覆盖。

旧配方的15窗smoke见[历史采纳记录](../../docs/testing/2026-10-07-apex-baseline-adoption-validation.md)；
当前配置验证见[2026-10-08采纳检查](../../docs/testing/2026-10-08-official30b-cached-baseline-validation.md)，不能把旧验证当作新参数的质量证据。

新增三个 Hy30 候选分别使用 `hy-mt2-30b-a3b-apex-i-compact`、
`hy-mt2-30b-a3b-i1-q3-k-l`、`hy-mt2-30b-a3b-i1-q3-k-m`；复用 Hy30
原生 `no_think`／GBNF／token transport，保持独立资产身份。注册支持不代表兼容 loader、
全 GPU 容量或质量已通过验证。[四量化实测报告](../../docs/research/2026-10-07-hy30-four-quantization-results.md)
现已提供这四份固定 GGUF 的完整旧集／新增集质量、四轮性能及正式长跑证据；本机观察到的显存余量、失败和慢态限制不能外推到其他配置。报告交付后用户已采纳 APEX；报告中的 Q3 基线标签保留实验当时含义。

两个 CLI 默认合并原清单 `.local/manifests/translation-download-plan.json` 与存在的
`.local/manifests/hy30-shortlist-downloads.json`；后者不存在时仍可使用旧资产。
可重复传入 `--asset-manifest <path>` 明确冻结清单；显式指定会替代默认清单集合。
清单合并拒绝未知候选、重复 ID、路径／SHA256 复用及不完整身份；四量化候选的
repo、revision、文件名、字节数和 SHA256 必须匹配冻结文件身份。
运行前核验实际字节数，外层启动前重新计算完整模型 SHA256，保存清单路径／哈希与模型哈希。
内层使用匹配的外层核验记录；独立运行缺少该记录时自行重新计算，文件损坏会中止。

外层可用 `--session-worker experiments.translation_four_quantization.worker --session-plan <path>`
将同一次加载后的工作负载交给四量化编排 worker；此模式不要求 `--inputs`。
worker 单独保存预热、正式输入及压力重复的不可覆盖目录，不能把重复压力窗口计成新质量样本。
外层仍持有并清理唯一模型进程，工作计划副本和哈希随 runtime 保存。
线程／KV 参数已按本机原基线有效值显式固定：generation／batch CPU threads 8／8、
KV K／V `f16`、server prompt cache RAM 8192 MiB。`--threads`／`--threads-batch`
允许明确另建实验配置；当前比较保持 8／8。`cache_prompt:false` 的逐窗请求行为保持原配方。

## 官方 Q4 的部分 GPU offload 实验

候选 `hy-mt2-30b-a3b-q4-k-m-official` 使用资产清单中腾讯官方 Q4_K_M，复用 Hy30 原生模板、
`no_think`、GBNF、token transport 与重试契约。它是历史独立对照，当前已采纳基线为 APEX-I-Compact。
外层用 `--layers` 显式固定 GPU 层数；部分层留在 CPU 必须另加 `--allow-cpu-offload`。
例如以下命令验证完整 smoke；36 层只是明确的起始配置，最终比较须冻结实际验证后的层数：

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_demo_runtime `
  --candidate hy-mt2-30b-a3b-q4-k-m-official `
  --engine '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/llama-server.exe' `
  --engine-identity '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/identity.json' `
  --layers 36 --allow-cpu-offload --context-size 4096 `
  --inputs 'D:/subtitle-samples/翻译模型评估库_v2/固定评测集/模型输入/smoke.jsonl' `
  --output-dir '.local/translation-evaluation/hy30-official-q4-smoke-01'
```

加载后核对日志中的实际 offloaded／total 层数与 GPU model buffer；层数须与显式请求一致，
缺少 GPU 证据、未授权的部分 offload 或加载失败均中止，不自动降低层数或回退纯 CPU。
`runtime/engine.json` 与 `runtime-final.json` 保存 `residency`、CPU／GPU model buffer MiB、
offload 许可及实际层数；原始日志和运行器源码也保留。CPU_Mapped buffer 是 loader 的映射量，
不等于物理驻留内存；全层 GPU 时仍可能有 CPU_Mapped embedding。每秒 `nvidia-smi` 峰值
是整卡采样峰值，不是模型独占峰值。以上证据不能代替实际翻译速度与质量评估。

外层新增独立 `ResourceMonitor`：默认 250 ms 请求采样，加载前至少 30 秒空闲基线，
覆盖加载、推理、卸载和退出后的释放观察。`resource-samples.jsonl`、
`resource-events.jsonl`、`resource-summary.json` 保存 UTC、整卡 used/free/total、
功耗／温度／时钟、目标 PID 的 working set／commit、可用 Windows dedicated/shared
GPU memory 及实测采样间隔；不可用字段保存 null 和原因，查看 GPU 样本 age 判断新鲜度。
旧 `gpu-samples.json` 仍是约每秒整卡读取；精细监测也可能漏过亚采样间隔峰值。
worker 工作负载事件会转发为监测阶段，原事件 UTC 保留在 details 中；轮询转发可能约延迟一秒。
runtime 另保存服务器 PID、worker／server 退出证明、退出码与清理 UTC，便于确认只停止本实验
进程及诊断重试前释放。driver reset／device lost 等日志标记保留为污染疑点，不能单独证明发生迁移。

## 其他候选与底层运行

已有本地资产可通过外层入口自动顺序启动／停止 llama.cpp server，并保存 runtime 证据：

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_demo_runtime `
  --candidate translategemma-12b-q8 `
  --inputs 'D:/subtitle-samples/翻译模型评估库_v2/固定评测集/模型输入/smoke.jsonl' `
  --output-dir '.local/translation-evaluation/<run-id>/tg12-native'
```

外层产物位于 `runtime/` 与 `translation/`。原生阶段完成后另起映射运行：

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_demo_runtime `
  --candidate translategemma-12b-q8 `
  --inputs 'D:/subtitle-samples/翻译模型评估库_v2/固定评测集/模型输入/smoke.jsonl' `
  --mapping-only '.local/translation-evaluation/<run-id>/tg12-native/translation' `
  --mapper tower-plus-9b-q8 `
  --mapping-recipe native-scored-groups-gbnf-v4 `
  --output-dir '.local/translation-evaluation/<run-id>/tg12-groups'
```

Hy30 若使用已构建的兼容引擎，须同时指定程序与身份文件，例如本轮资产：
`--engine '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/llama-server.exe'`
与 `--engine-identity '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/identity.json'`。
自定义引擎必须留下独立身份，不能与默认引擎混报。

从仓库根目录使用 uv 创建的 Python 环境。外层负责一次加载一个模型，并保存引擎版本、
GPU backend、加载命令、驻留证据和冷加载耗时。`--engine-manifest` 为该引擎的 JSON 清单，
建议包含绝对 `model_path`；运行器核对文件身份与服务器 `/props`。其他清单字段原样冻结。

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_demo.run `
  --candidate hy-mt2-7b-q8 `
  --inputs 'D:/subtitle-samples/翻译模型评估库_v2/固定评测集/模型输入/smoke.jsonl' `
  --output-dir '.local/translation-evaluation/<run-id>/hy7-smoke' `
  --server-url 'http://127.0.0.1:8080' `
  --engine-manifest '.local/translation-evaluation/<run-id>/engine-hy7.json'
```

`--candidate` 的其他值为 `hy-mt2-30b-a3b-q3-k-m`、`hy-mt2-30b-a3b-q4-k-m-official`、`tower-plus-9b-q8`、
`translategemma-12b-q8`、`translategemma-27b-q3-k-l`。运行目录必须没有已有 run／ledger。
开发时可用 `--limit 1`；完整 smoke／test 不设置 limit。通用CLI为兼容旧实验默认`legacy-greedy-v1`：
temperature0、固定seed、输出1024、总context4096；**当前基线请用`just translation-baseline`**，
或显式`--sampling-profile official30b-cached-v1`。新旧配置都有独立运行身份，至多两次相同请求。
超限不截掉 context；输出截断、无效 JSON、错／漏／重复 ID 均记录失败。

`token-ids-v1` 将完整原生 prompt 用 `/tokenize`（`add_special=false`、
`parse_special=true`）得到整数 token 数组，再直接交给 `/completion`；避免服务器为
已含 BOS 的原生模板重复添加 BOS。保存原始模板文本、token 数组／哈希与实际响应；
服务暴露的最终 prompt 和输入 token 数必须相符，否则按有界失败记账。
此验证补充 GGUF Jinja 文本对照，二者不能相互替代。旧字符串传输的开发运行独立保留。

Hy-MT2 7B 使用 `<|startoftext|>`／`<|extra_0|>`；30B 使用所选 GGUF 的 Hunyuan
特殊 token、`reasoning_effort:no_think` 与空 think 前缀。两者包装不同，分别核验。
Tower+ 使用原生 Gemma 2 单 user 包装；应用提示
要求精确 ID→译文 JSON，并使用逐窗口固定键的 GBNF，配方为
`native-target-json-gbnf-v3`。Hy-MT2 的待译 JSON 直接提供日文值，完整日文 context
另列只读。GBNF 限制键集合与 JSON 语法，不能防止字符串内漏译或串段。
GGUF 模板的兼容性检查与原始 metadata 保存在运行目录；
结构通过只证明交付格式，不能证明译文正确。

## TranslateGemma 的独立映射阶段

TranslateGemma 使用 GGUF 中 `ja`→`zh-Hans` 的原生翻译模板；完整窗口 context
按顺序换行拼成单个纯正文，不添加 ID 或任务指令。原生阶段保存整段中文，状态
`native_delivered`，尚不能作为完成的计分 ID 输出。

外层切换到显式选择的本地映射器后，运行纯映射，不再调用 TranslateGemma：

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_demo.run `
  --candidate translategemma-12b-q8 `
  --inputs 'D:/subtitle-samples/翻译模型评估库_v2/固定评测集/模型输入/smoke.jsonl' `
  --mapping-only '.local/translation-evaluation/<run-id>/tg12-native-smoke' `
  --mapper tower-plus-9b-q8 `
  --mapping-recipe native-boundary-anchors-v2 `
  --output-dir '.local/translation-evaluation/<run-id>/tg12-assisted-smoke' `
  --engine-manifest '.local/translation-evaluation/<run-id>/engine-tower.json'
```

`--mapper` 支持 `hy-mt2-7b-q8`（默认）或 `tower-plus-9b-q8`，不自动切换模型。
默认 `native-boundary-anchors-v2` 让映射器按语义为除第一条外的每个 context ID 输出
一个边界起始处的原生中文短子串；GBNF 固定全部边界 ID 和顺序，并保留显式 unresolved
分支。程序要求每个 anchor 在原生中文中恰好出现一次，起点严格递增，再从原生字符串
切出完整区间。无需让模型重新复制整段中文，也不按换行数或句号数关联。
旧的全段复制配方可用 `--mapping-recipe native-exact-partition-v1` 显式复现，
仅支持 Hy-MT2-7B。两种配方属于不同开发运行身份；v2 尚须实际 dev 和独立语义评估验证，
不能仅凭机械通过冻结正式配置。

可显式使用 `--mapping-recipe native-boundary-anchors-gbnf-v3`：程序在原生中文的每个
非零 Unicode code point 起点枚举 4／8／12／16 字符前缀（末尾不足时取剩余后缀），
仅将全文恰好出现一次的子串加入 GBNF 候选。因此映射器不能输出不存在或重复的 anchor；
独立 validator 再核对该固定词表、顺序和完整区间。模型仍须按日中语义选择边界，
无可靠对应时返回 unresolved；有限候选不能证明归属正确，也不替代语义评估。
v2 保留为默认，v3 是独立开发配方，须显式选择并分别记录实测。

`native-scored-groups-gbnf-v4` 根据源 context 的原有顺序，仅以 `translate_ids` 的成员
身份将 cue 划成最长连续计分／不计分组。组保留全部原始 `source_ids`；映射器只寻找
组间的语义边界，组内合句不再要求逐 cue 切开。边界仍采用 v3 的精确唯一 anchor 和
unresolved 分支，完整原生文本仍由各组区间无重叠地覆盖。不连续的计分 IDs 必须形成
不同计分组，中间上下文不能混入计分译文。无法可靠区分计分与上下文语义时仍不可评。

v4 的 `translation_groups` 仅保存计分组。
`delivery_contract: native-scored-groups-v4` 在所有 v4 结果／账本行（含失败）显式保留；
分组字段的单项格式为
`{source_ids:[...],text:原生精确区间,target_spans:[[start,end]]}`；`translations` 保持空对象，
不把同一段复制到多个 ID。账本的 `mapping_groups` 保存包括不计分组在内的全部组与
原生区间，`source_span_to_target_span` 保存同样的源 ID／跨度关联。该输出须走支持
分组契约的评估分支，旧的逐 ID validator 不适用；本轮配方已完成 dev 语义闭环并冻结，改变组边界策略时须重新验证。

映射器只读取本窗口带 ID 的日文、原生中文；逐 ID 配方的每个源 ID、v4 的每个源组
对应原生中文的非空连续子串，
拼接必须与原生中文逐字符相等，包括标点与空白。程序保存 Python Unicode code point
半开 offset。任何新增、删改、重复、重排或可靠边界缺失均拒绝；失败状态为
`mapping_unjudgeable`，评估保留完整分母和缺分上下界，不赋交付零分。
原生生成失败仍为 `translation_failed`。映射通过仅证明文本保真与可追溯，语义归属
由独立评估检查；这是 assisted 流程，辅助耗时不归为裸 TranslateGemma 能力。

## 产物与恢复

- `run.json`、`source/`：输入／模板／代码哈希与源码副本、候选、资产和引擎身份、参数、预期窗口。
- `transport/<序号>/request.json`、`response.raw`、`transport.json`：所有 HTTP 请求、
  原始响应字节、实际时间与错误；包括 props、tokenize、全部生成重试。
- `window-<ID>.json`、`ledger.jsonl`：原生文本、全部尝试、最终状态、原因、映射跨度和成本。
  `started_at_utc`／`finished_at_utc` 覆盖 tokenization、请求、校验与重试；落盘开销由外层工作负载计时覆盖。
  映射阶段 `attempts` 记录辅助调用，`native_attempts` 保留原生生成的全部尝试，
  `native_window_artifact` 指向原始窗口记录。缺失原生耗时写 `null` 和原因，
  不编造零耗时；辅助耗时单独实测，总耗时在原生耗时未知时也为 `null`。
- `results.jsonl`：外部结构 validator 所需的窗口 ID、translations、实测 elapsed_seconds。
  v4 额外保存 `translation_groups`，使用分组评估契约。
  失败／待映射项保留空对象，validator 的失败是预期记录，不能删去该行美化结果。
- `completion.json`：窗口数与失败数。返回码 0 表示该阶段完成，1 表示存在逐窗失败，
  2 表示配置／准备错误；TG 原生阶段返回 0 不代表映射或评估已完成。

四量化 worker 显式传入 `--stop-on-oom`：遇到明确 OOM 文本或 CUDA 内存错误后停止相同请求
重试和后续窗口，保留该次实际失败与原始 transport；不由超时或速度慢推断 OOM。
`completion.json` 的 `windows` 是实际尝试窗口数，`expected_windows` 是预期数，
`remaining_window_ids` 列出未执行尾段，`stopped_reason: oom` 解释中止。
未执行尾段不伪造 `translation_failed` 账本行，由编排层另记 `not_run`。

原始运行目录不覆盖。中断时已完成窗口均有独立记录；接跑可以先生成新的源输入子集
和目录，再由外层按原窗口清单审计合并，不修改冻结外部语料。当前 CLI 不自动断点接跑。
裁判不得读取候选名或尝试记录；评估 runner 单独读取最终译文与对应终态。

## 离线验证

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m unittest experiments.translation_demo.test_demo -v
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_demo.run --help
```

测试不需要 GPU、模型加载或网络；覆盖重复／额外／缺失 IDs、原生模板、无参考输入、
纯映射保真与 offset、截断、重试失败记账、映射不可评、禁止远程推理、产物防覆盖、
官方 Q4／新增 Hy30 原生契约、清单合并／身份／大小校验、明确 OOM 中止与未执行尾段、
部分 offload 许可／加载证据检查。
它们不验证翻译质量；实际五候选加载、输入预算、GPU 驻留和完整自动评估须另留运行证据。

## 五候选正式运行结果

2026-10-06 的 smoke/dev、配置冻结和完整固定 test 已完成，见[中文报告](../../docs/research/2026-10-06-translation-model-comparison-results.md)。
五候选各 83 窗口／414 IDs；415 个候选窗口中 408 有语义终分，6 映射不可评、1 裁决未决。
全部必需裁判任务已终结；原始响应追溯例外、失败成本和新目录复现方式见报告及其证据链接。

## Q3／官方 Q4 实测

[追加比较](../../docs/research/2026-10-06-hy30-q3-q4-comparison-results.md)已完成。Q4 使用同一兼容引擎与 `--layers 38 --allow-cpu-offload`，实际 38/49 层 GPU；两候选各 83/83 质量终分，三次运行均完整交付。Q4 三轮中位耗时为 Q3 的 4.18 倍，当时决定继续以 Q3 为基线；后续已由 ADR-0005 采纳 APEX。38 层是本机已测配方，不声称最优 offload 策略。
# 第二轮流程worker

外层`--session-worker experiments.translation_flow.v2_worker`支持第二轮的独立冻结计划，
每次仅一个候选／seed并使用新的managed server；配置、空缓存实测、辅助阶段与恢复见
[v2运行器说明](../translation_flow/README-v2-runtime.md)。旧demo默认和历史worker不变。
工程与质量进度以[第二轮台账](../../docs/context/2026-10-08-hy30-flow-exploration-v2.md)为准。
