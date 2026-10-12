# 字幕翻译自动评估 harness

状态：已实现离线 packet、schema 校验、复评选择、裁决编排和确定性汇总；合成流程测试通过。
这些检查不能验证裁判的日中语义判断，也不代表五候选实测已完成。
权威规则见[自动评估流程](../../docs/agents/subtitle-translation-evaluation.md)和[评估计划](../../docs/plans/translation-model-comparison.md)。

实现采用 `sol-high-auto-v1`，支持 `V2-replay`、`V2-native-adapted`，以及显式 `p-flow-source-id-preserved-v1` 契约限定的 `P-flow`。后者仅支持保留源cue的映射，不将自由段落重组误当作 ID 对齐。
本模块本身不调用模型。裁判执行器读取任务 JSONL，每个候选／窗口使用独立的新请求，再把验证后的 JSON 保存到任务指定路径。
不得将评估 packet、中文参考或裁判输出送给翻译器、辅助映射器或修补步骤。

## 离线验证

从仓库根目录运行，使用 uv 已创建的根环境：

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m unittest experiments.translation_eval.test_runner -v
```

测试使用合成文本，覆盖四条计分 ID、漏译、映射不可评、裁判失败、复评失败、未决及已解决裁决、
主评／packet 冻结、不同作品窗口数、类别分层完整分母、缺分 0／4 边界和自然度独立汇总，
以及中断尾段未执行、setup／容量不可用与实际请求失败的独立记账。
测试不调用网络、不加载 GPU 模型、不读取真实字幕作为答案。

真实裁判联调前还应运行合成 packet 检查：

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_eval prepare-synthetic --output '.local/translation-evaluation/<run-id>/synthetic-evaluation'
```

该步骤准备否定反转、数字变化、等义中文措辞和完整漏译四窗，以及三项可评裁判任务。
诊断预期单独保存在 `synthetic-expectations.json`，不能送入裁判；检查明显故障，不充当人工校准或准确率验证。
完整漏译由程序记零分。旁边的 `synthetic-evaluation-synthetic-source/` 保存这些合成输入，必须使用新路径。

## 准备运行

`--lane P-flow` 必须同时提供 `--p-flow-contract <契约.json>`。契约冻结输入、参考、语料清单哈希，
完整源SRT及允许范围、逐窗 `eval_id → source_cue_id` 映射和各候选原始产物指针／哈希；
程序逐项核对日文原文和来源顺序，所有结果／账本行须声明 `delivery_contract:p-flow-source-id-preserved-v1`。
这不是任意重分段评价入口；原生分组、跨cue自由重映射仍不在该契约内。
新流程操作与实际验证见[translation_flow](../translation_flow/README.md)。

先按权威流程只读运行外部库的 `verify_freeze.py` 和 `validate_results.py --self-test`，检查 exit code 并保存日志。
对每个候选运行 `validate_results.py --inputs ... --results ...`，保留其失败报告。
映射不可评不满足普通 ID 结果校验时，保留失败和显式终态，不能伪造译文通过 validator。
`native-scored-groups-v4` 分组交付采用以下独立契约检查，原始 per-ID v2 validator 不适用；不能声明其通过。

```powershell
$corpus = 'D:/subtitle-samples/翻译模型评估库_v2'
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_eval prepare `
  --inputs "$corpus/固定评测集/模型输入/smoke.jsonl" `
  --references "$corpus/固定评测集/参考答案/smoke.jsonl" `
  --corpus-manifest "$corpus/freeze_manifest.json" `
  --candidate 'c01=.local/translation-evaluation/<run-id>/candidate/results.jsonl' `
  --candidate-ledger 'c01=.local/translation-evaluation/<run-id>/candidate/ledger.jsonl' `
  --lane V2-native-adapted --split smoke `
  --output '.local/translation-evaluation/<run-id>/evaluation'
```

`<run-id>` 是需替换的唯一运行名；输出目录必须为空。多个候选重复传入 `--candidate`、可选 `--candidate-ledger` 和 `--candidate-schedule`。
别名仅允许 ASCII 字母、数字、下划线和连字符；模型身份键由 orchestrator 保存，裁判看不到候选模型名。
候选原始结果按字节复制到 `originals/`，原始路径和哈希保存在 `run.json`。
参考文件可覆盖更多窗口，程序仅关联输入指定的窗口并记录使用／文件窗口数，不产生其他窗口 packet。
清单记录输入、参考、workflow、runner、prompt、packet、expected、可选调度清单和语料 manifest 的哈希。
新增语料沿用 `V2-native-adapted` schema 时，须通过 `--corpus-manifest` 提供声明新语料版本的冻结清单；
不能因使用 `--split test` 而将其称作原版 v2 test，旧回归与新主集分别准备和汇总。
实际模型／量化／模板／生成设置、语料核验日志、冷加载与裁判实际身份需由运行清单补充，不能由离线代码猜测。

`results.jsonl` 每行形如：

```json
{"id":"窗口ID","translations":{"计分ID":"候选中文译文"},"elapsed_seconds":1.23}
```

耗时只填实测值，不可用时填 `null` 或省略。缺失、重复、额外 ID、空译文和 JSON 解析问题均保留。
部分交付仍送裁判评遗漏，不能获得语义 4；完整缺失或违反冻结 ID 交付契约的不可用输出由程序记语义 0、自然度 `null`。

可选 `ledger.jsonl` 默认必须恰好覆盖全部输入窗口；中断或容量不可用时，
允许原翻译账本与以下独立调度清单的并集恰好覆盖全部输入窗口，每行包含：

```json
{"window_id":"窗口ID","status":"delivered","reason":null,"translations":{"计分ID":"候选中文译文"},"elapsed_seconds":1.23,"generation_seconds":1.23,"auxiliary_seconds":0,"attempts":[{}]}
```

允许状态为 `delivered`、`translation_failed`、`mapping_unjudgeable`。
`delivered` 的译文若同时记录在账本中，必须与 results 一致。
`mapping_unjudgeable` 必须有非空 `reason`，其最终语义／自然度为 `null`，不记交付零分。
`translation_failed` 表示候选违反已冻结交付契约，终态为 `delivery_zero`。

未请求窗口不能补造 `translation_failed`。可选 `--candidate-schedule 'c01=.../schedule.jsonl'`
接受稀疏调度记录，仅允许这三个字段：

```json
{"window_id":"尚未请求的窗口ID","status":"not_run","reason":"请求 OOM 后中断，此窗口尚未执行。"}
{"window_id":"准备阶段阻塞的窗口ID","status":"setup_failed","reason":"加载容量预检失败，此窗口尚未执行。"}
```

`not_run` 表示未执行尾段或尚未调度；`setup_failed` 表示模型加载、环境准备或容量预检阻塞，
实际翻译请求失败仍由原账本记 `translation_failed`。每条调度记录必须有非空原因，
窗口不能同时出现在原翻译账本或 results 中，即使 results 的译文为空也视为矛盾并拒绝。
调度清单按字节保存到 `originals/<alias>/schedule.jsonl` 并记录哈希，不改写原翻译产物。
未提供调度记录的缺失 results 仍采用既有交付零分语义；不能从缺失文件猜测未执行。
完全无法开始的候选可提供空 results／原账本及覆盖全部窗口的 `setup_failed` 清单。
这些状态保留全部预期窗口与计分 ID，语义／自然度为 `null`，不产生主评、复评或裁决任务；
语义上下界分别按 0／4 填补。summary 和报告分别计数未执行、setup 失败及实际交付零分，
部分已测时间不能作为完整集更快的证据。接跑完成后应另建评估目录重新冻结实际产物，不能改写已冻结 expected。

重试次数由 `attempts` 列表长度减一计算，也兼容实测整数 attempt count；未知记录不会补造。
最终辅助映射账本中的 `native_attempts` 与当前 `attempts` 分别计入原生生成和映射重试；
任一阶段记录未知时，全阶段 attempt 覆盖保留缺口，已知阶段的计数单独报告。
`native_window_artifact` 和 `generation_timing_reason` 保留原生来源及未知时间原因。
`generation_seconds` 与 `auxiliary_seconds` 分别汇总，并显示各自覆盖；冷加载、设备驻留、token、评估时间和成本仍由各执行记录提供。

TG 原生段落可采用 `native-scored-groups-v4`：results 的 `translations` 必须为 `{}`，
每个结果／账本行均显式声明 `delivery_contract: native-scored-groups-v4`，失败行也保留，
避免全部映射失败时误识别为逐 ID 契约；历史已有分组字段的开发产物仍可识别。
另有 `translation_groups:[{source_ids:[原始计分ID],text:原生中文切片,target_spans:[[start,end]]}]`。
按原始上下文顺序，将连续计分／不计分 ID 分为最大连续组；只把计分组放入 packet。
若中间存在不计分 ID，必须分成两侧计分组，不能把中间中文一起评分。
每组共享其 source_ids 的语义范围，不声称逐句对齐，不把同一段中文复制给多个 ID。
整窗评分、原始计分 ID 和全部预期窗口分母不变。

账本必须保留 `native_text`、全部计分／上下文 `mapping_groups`，以及去掉 text 的
`source_span_to_target_span`；各组含 `group_id:g0/g1/...`、有序 source_ids、scored、text 和单个 target_spans。
程序验证组划分、完整 ID 顺序、跨度整数与无间隙分区、非空逐字切片、完整原生文本重建，
以及结果／账本计分组完全一致。缺少原生／完整映射来源为 `mapping_unjudgeable`；
显式交付违反分组契约为 `delivery_zero`；映射器明确无法确定边界仍为 `mapping_unjudgeable`，不是零分。
原生生成的显式 `translation_failed` 优先记交付零分，不因没有原生文本或映射证据变为不可评；
原生文本已交付、辅助映射明确失败时，即使存在无效尝试分组，也保留映射不可评与 `null` 分数。
这些验证证明文本未改写，不能证明边界的语义正确性。
裁判允许针对相关原始 ID 引用共享组文本，评实际遗漏／错译及有证据的映射问题。
新 prepare 的统一 prompt 带分组说明；已经冻结的 dev prompt 不会自动更新，正式运行应重新准备全部候选。

## 任务与恢复

`prepare` 生成 `expected.jsonl`、`packets/`、冻结的 `judge-prompt.txt`、`jobs.jsonl` 和 `run.json`。
每项任务含 `job_id`、`candidate_alias`、`window_id`、`packet`、`prompt`、`response`；全部路径相对评估目录。
`job_id` 第一段为 `primary`、`review` 或 `adjudication`。
packet 仅含允许的日文上下文、计分 ID、候选译文和这些 ID 对应的修订参考 `zh`，不含未计分中文参考。

裁判必须使用 `gpt-6.1-sol / high` 的新请求，遵循冻结 prompt；每个 transport／schema 失败最多重试一次，保留两次原始响应。
`validate_judgment(value, packet, adjudication=False)` 检查字段、整数范围、IDs 和逐字证据归属；
JSON 文件通过 `read_json` 读取会拒绝重复键和非标准数值。
证据校验只证明引用可追溯，不证明语义推理正确。

开发修正版本：`judgment_validator_version=evidence-v2-semantic-omission`，
`prompt_version=group-scope-evidence-v2`，写入新运行清单；实际汇总也记录执行 validator 版本。
所有交付表示统一允许 `type=omission` 使用空 `candidate_evidence`，即使该 ID 或共享组有其他中文：
遗漏的含义本就没有候选引用，强制引用无关残留词语无助于核验。
裁判仍须给出逐字匹配的非空 source_evidence 和非空 reason_zh，说明实际遗漏。
其他错误类型只有在相关 ID 机械缺失时允许空引用，否则仍须匹配候选文本。
程序无法证明语义缺席；它只验证证据格式，漏译结论仍是需要复评的裁判主张。
评分锚点、重试预算、候选原文与完整分母不变。
旧 `dev-eval-de` 保留为部分开发证据；修正后 `dev-eval-de-v2` 使用相同候选原件重新准备全部 29 项 fresh 主评。
既有运行目录与冻结 prompt 不会改写；正式 test 的全部候选须使用一致的新 prompt。

全部主评完成或记录永久失败后，冻结风险／抽样并集：

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_eval select-review --output '.local/translation-evaluation/<run-id>/evaluation'
```

该步骤生成 `review-selection.json` 和 `jobs-review.jsonl`。
按作品对固定 SHA256 顺序取 `max(1, ceil(20% × 窗口数))`，再加入所有候选风险窗口；同一并集中的所有可评候选均复评。
完整缺失／映射不可评／调度不可用没有可归属译文，不产生该候选复评任务。
复评看原 packet，不看主评分数、意见或选择原因。
选择清单及主评内容冻结后若发生变化，命令报错，应另建运行目录或恢复冻结产物。

复评完成后运行：

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_eval finalize --output '.local/translation-evaluation/<run-id>/evaluation'
```

该步骤生成 `jobs-adjudication.jsonl` 和 `disputes/`：分数、状态或 major／critical 证据主张不同即进入一次裁决。
裁决任务额外包含 `dispute` 路径；文件保留随机排序且去除身份的两份意见。
裁决返回原 schema 加 `resolved` 布尔值与非空 `resolution_zh`。
完成裁决后再次运行 `finalize` 即可更新最终账本，无需重跑已接受主评／复评。
裁决不能解决的记录为 `unresolved`；必需复评／裁决缺失或校验失败为 `review_failed`，主分仅作 provisional。
原 packet／prompt／expected 哈希改变时拒绝汇总。

## 汇总与边界

`final.jsonl` 恰好保留每个预期候选／窗口；`summary.json` 与中文 `report.md` 由程序产生，
`aggregation-runner.py` 保存当时汇总源码。缺失裁判文件不会删除窗口或虚构译文零分。
实际执行源码另存为 `aggregation-executed-runner.py`，summary 记录它与准备时源码的哈希是否一致；
开发阶段改动后的重汇总据此可追踪。正式比较应冻结这些源码；归档源码也可直接运行 `finalize --output ...`。

先在每个作品内取窗口均值，再分别对 `movie`、`anime_series` 的作品等权平均，不按 ID 数或对白量加权。
冻结库中的 `animation_movie` 显式映射为报告类别 `movie`，保留 `source_category` 和清单中的映射规则。
所有缺分分别填 0／4 得到上下界，provisional 主分不能缩窄边界；该范围不是置信区间。
自然度只汇总非空终分，单独列覆盖和被省略作品，不能与语义相加。

五候选正式运行可用 `python -m experiments.translation_comparison_report`
（`--evaluation-dir`、`--run-root`、`--candidate-alias-key`、新的 `--output-dir`）
核对 expected／final／summary，再生成含七个本地阶段、裁判调用和开发失败历史的中文报告。
默认正式目录约定为 `test-v1/<candidate>` 与 `test-map-v1/<TG candidate>`；
不存在的证据保持未知，不推算为零。`just translation-test` 包含该汇总器的合成账本检查。
严重错误计数只采纳最终支持的判断，保留初始分歧和改分数量；仍未决的意见不会冒充确定错误。
不自动声明 50／50 总分或统计显著排名；上下界重叠、细小差距、复评不稳时不能确定优胜者。

报告属于同模型 Sol/high 的自动评估，中文参考也经同模型文本复核；不能表述为人工准确率、跨作品泛化或音画同步验证。
五候选历史计划的正式比较范围是完整固定 test；四量化计划另含经审核冻结的新增主集，两者分开报告。
smoke 是 dev 子集，不重复计分。

## 四量化配对统计

`python -m experiments.translation_four_stats --expected <expected.jsonl> --final <final.jsonl> --source-manifest <source-manifest.json> --baseline-alias <匿名基线ID> --output <新目录>`
生成中文报告、`summary.json`、统计配置与执行源码副本。可用 `--primary`／`--review` 指定汇总判断文件，`--shared-series` 提供明确的作品到系列映射。

输入仍采用本评估器账本；旧回归和新增集按 manifest 的 `set` 独立报告，不合并分母。统计保留所有预期窗口、缺分 0／4 界、逐作品与类别等权成绩、四者共同覆盖、最终严重错误和初终评分变化。三个候选对基线按作品为簇、类别内配对 bootstrap 10,000 次，seed `20261006`；输出普通 95%、三项对照 98.33% 和六项对照 99.1667% 区间，另做逐个移除作品及显式共享系列合并敏感性分析。区间只针对可评分配对子集，不取代完整分母缺分界，也不证明同模型裁判准确率。

`python -m experiments.translation_identical_output_diagnostics --expected <expected.jsonl> --candidate <匿名ID>=<首轮results.jsonl> --primary <primary.jsonl> --review <review.jsonl> --final <final.jsonl> --set-name <regression或expanded> --output <新目录>`
提供补充的相同译文评分诊断，四个匿名候选分别传入一次 `--candidate`。
只对同窗、完整 translations map 精确相同的候选成组；空白、标点及 Unicode 差异均不归一化。
主评、盲复评和终评的分差／严重错误分歧分开列出，并区分窗口、组、候选对及缺分覆盖。
终评受复评和裁决影响，不能当作另一次独立盲评。此诊断不复制分数，也不将译文相同解释为翻译正确。

`python -m experiments.translation_terminology_diagnostics prepare --inputs <日文模型输入.jsonl> --source-manifest <源清单.json> --catalog <事前词目录.json> --set-name <regression或expanded> --output <新目录>`
在正式候选输出产生前，从计分 ID 的原日文建立有限术语范围；目录、生成清单和实现均须纳入正式冻结。
目录只供评估，禁止进入翻译输入或修补流程。参考最终替换后须以最终源清单重新准备，不能沿用初始样本预览。

`python -m experiments.translation_terminology_diagnostics analyze --manifest <source-term-manifest.json> --candidate <匿名ID>=<首轮results.jsonl> --output <新目录>`
对四款分别传入 `--candidate`，按作品、源词形和预声明上下文规则诊断跨窗译法；同族合法别名允许变化。
跨族变化仅是潜在不一致，未命中、多族命中和无译文分别保留，不自动判为语义错误、漏译或未翻译。
该工具不调用模型、不更改评分，也不自行证明清单冻结早于候选输出；先后顺序由正式运行身份核验。
`just translation-test` 包含此工具的源范围、参考隔离、未知专名和拒绝覆盖检查。

## 五候选历史正式运行结果

2026-10-06 的 smoke/dev、配置冻结和完整固定 test 已完成，见[中文报告](../../docs/research/2026-10-06-translation-model-comparison-results.md)。
五候选各 83 窗口／414 IDs；415 个候选窗口中 408 有语义终分，6 映射不可评、1 裁决未决。
全部必需裁判任务已终结；原始响应追溯例外、失败成本和新目录复现方式见报告及其证据链接。
