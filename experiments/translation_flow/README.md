# 固定 Hy30 的有界字幕流程实验

当前探索以[第二轮C档计划](../../docs/plans/hy-mt2-translation-flow-exploration-v2.md)和[新台账](../../docs/context/2026-10-08-hy30-flow-exploration-v2.md)为准，已完成源／参考与判定规则冻结，正在执行多seed筛选及新协议资格；新入口见本文末尾及[v2运行器](README-v2-runtime.md)。旧screening仍固定旧采样与短片段，旧recipe缓存规则不变；不能直接用下面旧筛选入口冒充第二轮，历史结果保留。

状态：有界筛选历史保留；2026-10-08按用户决定更新新准备任务的默认采样和缓存，见[ADR-0005](../../docs/adr/0005-apex-i-compact-translation-baseline.md)。

[结果报告](../../docs/research/2026-10-07-hy30-flow-optimization-results.md)：无可靠胜出方案；完整流程实测为连续摘录，全片未验证。

本模块为[优化计划](../../docs/plans/hy-mt2-translation-mode-optimization.md)提供新实验入口。
实际试验、选择清单、成本、失败与接跑见[探索台账](../../docs/context/2026-10-07-hy30-flow-exploration.md)。
模型固定为 ADR-0005 的 APEX-I-Compact；复用现有兼容 loader 和 loopback 传输，不下载资产。
新`prepare`默认`--recipe b0-cached --sampling official --n-predict 4096`：B0提示、官方30B采样与缓存。
`b0-cached`名称指沿用B0提示，不表示仍使用B0的temperature0。历史筛选器和冻结计划显式指定旧参数，保持不变。
复现旧SRT准备须显式`--recipe b0 --sampling b0 --n-predict 1024`及运行时context4096。

## 输入、推理与导出

`python -m experiments.translation_flow prepare --help` 查看源 SRT 准备参数；
`export --help` 查看完整交付导出参数。源 SRT 只读，准备阶段保存原字节 SHA256、cue 时间和来源映射，
生成无重叠目标批次与只读邻文。`--context-size` 在此入口表示每侧邻接 cue 数；
模型总 token context 由外层 runtime 的同名参数单独指定，不是同一单位。

准备目录生成的 `session-plan.json` 可交给现有管理运行器：

```powershell
& '.venv/Scripts/python.exe' -B -X utf8 -m experiments.translation_demo_runtime `
  --candidate hy-mt2-30b-a3b-apex-i-compact `
  --engine '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/llama-server.exe' `
  --engine-identity '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/identity.json' `
  --layers 99 --context-size 8192 --threads 8 --threads-batch 8 `
  --session-worker experiments.translation_flow.worker `
  --session-plan '<准备目录>/session-plan.json' --output-dir '<新的运行目录>'
```

真实运行按仓库规则执行于获准环境。GPU 只有一个受管理模型进程；启动前重新核验完整权重 SHA。
运行计划填写翻译调用、裁判调用、估计 tokens 和墙钟保护上限，防止单次运行失控。
worker 在生成前预留实际输入 token 加输出上限，超总 context 不截原文，显式 OOM 停止。
探索范围由冻结的小样本与晋级／停止规则控制；成本累计记录，保护上限不作为宣称收敛的理由。

worker 保留每次 HTTP 原始请求／响应、提示与源码身份、服务端生效参数、重试、
逐窗结果、未执行尾段和资源证据。现有 `b0` 保持旧请求；其他配方使用独立身份。
官方采样起点和本机输出上限是不同设置；新准备默认输出4096，总context须另设8192。
session worker的采样以冻结计划为准，不能用runtime的demo profile覆盖计划；这里使用通用runtime入口。
另有context8192／输出4096的短窗资源资格通过，但实际只生成99tokens，长输出仍未验证。

导出按冻结批次和 cue ID 核对唯一覆盖，不按返回顺序 zip。
仅完整交付写成功 `chn.srt`；缺失、空文本、冲突或无效结构保留失败清单，不回填日文。
时间源为原 SRT 显示 cue，不声称音画同步。字符／秒、行长、重叠等仅作为诊断，无显示profile不设虚构阈值。
源段摘取须保留原文件哈希与原 cue 范围，不称全片交付。

当前恢复策略为保留不可覆盖的原运行，使用新目录执行明确的剩余范围；未完成结果不得伪装成功。
修改任何源文、配方、采样、模板或状态后不能复用旧输出身份。完整自动断点缓存不作为已验证能力。

## 评估隔离

小窗口格式消融使用 `V2-native-adapted`；完整源 SRT、额外邻文或改变批次属于 `P-flow`。
评估器新增的 `p-flow-source-id-preserved-v1` 只支持保留源cue的明确映射：
源SRT／允许范围／映射／原始结果均需哈希，逐项核对计分原文与来源ID。
它不支持自由段落拆回、任意时间重排或复制整段填多个ID。
参考和裁判反馈只进入评估侧，禁止用于源文准备、术语、记忆或翻译修订。

`python -m experiments.translation_flow.screening --help` 从显式来源映射准备一个指定分批／邻文变体。
每个评分片段两侧扩展5条源cue，重叠范围合并；保留原始时间和独立的不可覆盖准备目录。
`screening.json`记录输入哈希、范围、批次数与原计划路径。各段按原计划分别执行；
不要直接改名冻结 workload 或把同名 workload 塞进新计划，否则身份核验会拒绝。

多个片段可通过 `--session-worker experiments.translation_flow.dispatch` 共用一次模型加载。
其计划为 `hy30-flow-dispatch-v1`，按序列出 `{label, plan, plan_sha256}`；
预检并重新核验子计划及源输入，原始 workload、参数和计划哈希保持不变。
子产物位于 `translation/<label>/<原workload标签>/`，可直接导出及投影。
首个失败停止并记录未运行尾段。共享冷加载、卸载和显存仅在父 runtime 记一次，
不要把共享启动耗时重复分摊为每个评分窗口的实测耗时。

`python -m experiments.translation_flow.project_evaluation --help`在评估侧把原始cue结果投影到冻结评分ID。
`append_batch_context`可将两候选实际使用的日文邻文并集提供给裁判，新增部分不计分且不含中文参考。
共享批次的窗口耗时保持null；性能从完整运行及导出计，不把一批成本重复归给多个评分窗口。
`python -m experiments.translation_flow.judge_loop --help`执行既有主评、独立盲复评和有界裁决闭环；
`costs --help`汇总实际翻译、裁判和资源记录，保留未知项。

## 离线验证

```powershell
& '.venv/Scripts/python.exe' -B -X utf8 -m unittest experiments.translation_flow.test_srt experiments.translation_flow.test_worker experiments.translation_flow.test_cli experiments.translation_flow.test_costs experiments.translation_flow.test_judge_loop experiments.translation_flow.test_project_evaluation experiments.translation_flow.test_screening experiments.translation_flow.test_dispatch experiments.translation_eval.test_runner -v
```

离线检查验证覆盖、输入隔离、预算和交付契约；模型质量与资源可行性只由实际运行证据支持。
# 第二轮探索入口

第二轮C档使用独立的`hy30-flow-session-v2`，历史P阶段和旧配方不变。
精确worker配置及资格边界见[第二轮运行器](README-v2-runtime.md)；
当前进度由[接跑台账](../../docs/context/2026-10-08-hy30-flow-exploration-v2.md)维护。
实现和离线通过不代表候选质量改善或探索收敛。

`python -m experiments.translation_flow.v2_prepare --help`提供源片段分批入口：
输入已冻结的源manifest与scenes，支持固定条数、实测源token目标、非对称邻文和共同源范围诊断。
从源片段起点打包，评分窗不决定批边界；`packed-mapping.json`保存源身份、批次、评分位置及场景。
按token组织只使用明确提供的tokenizer计数文件，最终完整提示仍由worker核验8192总预算。

`python -m experiments.translation_flow.v2_execute --prepared <准备目录> --output <新运行目录>`
启动一个新的兼容模型服务，记录包含启动前完整模型哈希核验的命令墙钟；准备、导出、评价成本另列。
每个候选／seed独立服务，首个completion实测`timings.cache_n=0`；不以slot清除或`tokens_cached`冒充空缓存。

源文交付API `v2_delivery.deliver(source_manifest_path, packed_mapping_path, run_dir, output)`
按scene导出完整SRT并保留原cue索引和时间；缺失／失败／未执行／映射不可评保留，缺失片段不伪造成功SRT。
原生联合译文与精确拆分诊断单列；向评估侧投影明确的源ID，不复制整段译文填补多个ID。
窗口不重复承担共享批次成本。参考仅由隔离评估侧拼装，翻译侧不读取参考。

`v2_statistics.build_statistics()`先在窗口内平均seed，再按作品内窗口等权、类别内作品等权汇总；
风险层单列，作品／系列聚类区间、缺分界和逐作品剔除敏感性分开。
`summarize_blind_calibration()`不选择有利重复分数；`summarize_paired_timing()`区分探索精度估计与独立固定重复确认。
阈值由候选成绩之前冻结的decision policy决定，不由统计模块默认猜测。

`python -m experiments.translation_flow.v2_compare --help`离线比较已封签的评估目录：
为全部三个预定seed分别重复`--baseline`、`--candidate`及`--card`，再传入
`--source-manifest`、`--policy`和新的`--output`目录。card的`candidate_group`显式连接同配方，
不能从运行名后缀猜测；核验源／参考身份、终评字节、原试验卡及实际使用的源码快照。
统一全窗盲审的派生96窗C0可按精确评分范围作探索性投影，但生成场景和请求历史不同的投影
不能直接声称是匹配对照。本轮已分别冻结实际工作负载验证协议和条件性的matched48评估范围；
原34场景／96窗C0与新29场景／48窗C0保留各自生成身份。
`v2_matched_evaluation`逐阶段核对完整packet、rubric、rendered prompt、schema及模型／effort设置，
只有实际输入逐字节一致的接受判断才可导入；裁决须待新争议实际形成后核对。
比较器另有显式matched48分支，绑定条件scope与原全窗复审scope的关系，要求三个实际控制seed
和精确48窗一致；不能混用96／48控制seed。新生成成本与旧裁判成本分别追溯，
原根不改写、不拼成虚构的96窗生成或六个seed。
旧选择性复审根仅作不可变导入来源；比较要求双方所有可评窗口有独立复审，并核验精确范围、
派生链和封签清单。未运行seed、缺分或未封签终评保持完整分母和未知状态。
实现与真实补验状态见接跑台账，入口存在不代表所有matched控制均已封签。
历史验证协议的代码依赖在后续实现升级后仍按原始哈希核验：仅允许通过已绑定的提升收据、清单和备份解析相同旧字节，同时记录原指针与归档指针；执行原冻结源校验函数，不把当前代码冒充旧执行。旧协议和既有封签保持原样。
输出只含聚合统计，不自动判胜；严重风险门仍需独立错误复核。
跨窗口根错误仅合并有明确支持、作用域和registry哈希的共享身份；局部`root_id`不据名字跨窗合并。

`v2_fluency`提供独立、探索性的阅读缺陷诊断契约：匿名单候选packet、源文及译文精确证据、
语法／搭配／阅读障碍／语域与纯偏好分离。它不读取参考、不产生加权分数或胜者，不能改变
主语义终点或确认阈值。`v2_fluency_runner`使用统一六槽、原生Windows进程树保护和不可变终态；
合成探针及固定C0重复校准已执行，具体敏感性、复审及后续候选状态仍以接跑台账为准，不能因原自然度量尺满分而认定没有改善空间。

离线回归：`just translation-flow-v2-test`。新模块仍需本机真模型资格与独立语义评估。

新准备区分源冻结状态：尚未完成参考资格的源仅允许`qualification`；
`screening`／`confirmation`／`full-flow`要求同源合格发布和哈希证据。
既有资格输出可以经`v2_reproject.reproject_scoring()`复用到同scene的最终评分窗：
严格要求源scene字节、顺序和范围不变，保留原始run／mapping及成本身份，新增推理和计时次数均为0。

后续端到端实验使用`python -m experiments.translation_flow.v2_trial --card <冻结卡.json> --output <新目录>`，
计时从源准备到完整SRT导出，评价不计入翻译耗时；阶段失败仍保留耗时和错误。
所有非资格卡须绑定已冻结的decision policy，包括只改变batch或邻文而仍使用`c0`提示的候选，避免候选成绩出来后再定判断规则。
可选源术语／背景准备使用同Hy30独立会话，完整计入端到端时间；协议修订、准备产物与作用域核验见[第二轮运行器](README-v2-runtime.md)。
