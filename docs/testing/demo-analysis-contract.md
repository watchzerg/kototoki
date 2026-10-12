# Demo 描述性汇总接口

状态：已实现，已用于固定开发、验证及原始保留实测；核心汇总仍不排名，冻结角色选择由独立入口执行  
最后更新：2026-10-04  
范围：`experiments/analysis` 的冻结运行清单、完整失败记账、配对描述与隐私输出。

关联：[评测器契约](evaluator-contract.md)、[时间优先基准](subtitle-timing-benchmark.md)、[实测计划](../plans/local-stt-demo-selection.md)。

当前W0／X0的新运行按[标准基线测试指南](../guides/baseline-testing.md)生成结果，分别登记recipe及运行身份后纳入冻结清单；本文旧清单示例不定义当前基线组合。

## 使用入口

```powershell
uv run --locked --offline python -m unittest experiments.analysis.test_analysis -v
uv run --locked --offline python -m experiments.analysis '.local/manifests/dev-comparison-v1.json' --output '.local/results/dev-comparison-v1.json'
```

Python 接口为 `aggregate_manifest(manifest, base=Path(...), bootstrap=False)`。CLI 相对输入路径以 manifest 所在目录为基准，不以当前工作目录为基准。输出必须在本项目 `.local` 下，禁止覆盖清单、引用文件和既有结果，重评用新运行身份。

不扫描结果目录、不只挑成功模型，也不自动推断正式筛选规则。汇总只使用预先冻结的完整场景列表，每条路线对每个场景都占一个位置。`table_rows` 直接提供按清单原顺序排列的数值表；它不是排行榜。`ranking/promotion` 始终为 `not_performed`。

## 冻结输入清单

```json
{
  "schema_version": 1,
  "manifest_id": "dev-comparison-v1",
  "frozen": true,
  "reference_kind": "srt_display",
  "evaluation_config": {"status": "exploratory", "revision": "development-v1"},
  "scenes": [
    {"id": "scene-01", "reference_path": "../references/scoring-v2/chapter-01.json",
     "reference_sha256": "<derived-reference-file-SHA256>"}
  ],
  "routes": [
    {"id": "Q1-native", "configuration_id": "crisp-native-f16-v1",
     "model_metadata": {"engine": "Crisp", "precision": "f16"},
     "runs": [
       {"scene_id": "scene-01", "run_id": "q1-ch01-native-r1",
        "status": "execution_unverified", "execution_verified": false,
        "evaluation_path": "../results/q1-ch01-native-r1/score-v2.json",
        "evaluation_sha256": "<evaluation-file-SHA256>"}
     ]}
  ]
}
```

`reference_sha256` 是这份派生 JSON 文件的哈希，不能填原始 SRT 哈希代替。默认严格要求所有已读取参考、评测结果或转写文件的精确哈希；不匹配直接报错，不把损坏的冻结证据当作模型失败。显式 `strict_hashes=false` 可用于开发脚手架，但报告保留实际哈希和未要求冻结哈希的事实，不能据此宣称已通过正式身份核查。

参考类别在一份清单内必须统一：`srt_display`、`human_acoustic`，或严格空跨度的 `synthetic_digital_silence`。数字零静音要求明确生成来源、零预期文字和正时长，N=0/CER未定义，插入仍可记账；不能冒称房间噪声或人工声学参考。每份结果必须采用当前评测规则版本、具有相同参考跨度 ID 顺序、完整文字分母和合法 S/D/I 关系。已有结果中的 corpus revision 也须匹配。导入结果通过文件身份、revision、ID 和分母绑定；如果参考被同长度改写而未更新身份，需要人工核查运行来源或从原转写重评，汇总器不声称可以靠计数证明原始匹配过程。

每条 route 是一套模型/配置，不应把不同配置的场景成绩拼成一个“最好路线”。`configuration_id` 必填，实际模型、精度和参数可附在 `model_metadata`；应保持该字段只含模型和配置说明，不放音频或完整文字。重复 route、重复场景、清单之外的场景会报错。不同场景的 source 输入及评测 identity 保留在 `artifacts`。

## 失败、缺失与执行资格

| run status | 文字分母 | 内容时间 | 执行资格 |
| --- | --- | --- | --- |
| `completed` | 完整评测结果 | 按原逐跨度结果 | 仍须显式 `execution_verified=true` |
| `execution_unverified` | 保留实际成绩 | 保留实际成绩 | 未证明 ASR/FA 设备或离线等条件，不作可采用结论 |
| `alignment_failed` | 保留已识别文字 S/D/I | 所有非空跨度计对齐失败 | 未通过完整流程 |
| `invocation_failed` | 主表全参考删除；已有部分结果只存诊断计数 | 所有非空跨度计调用失败 | 调用失败独立计数 |
| `missing` 或没有 run slot | 主表全参考删除 | 所有非空跨度计缺失运行 | 未完成，不隐藏 |

声明成功但结果文件缺失会转为 `missing`。声明对齐失败却不提供识别后的评测计数或转写会报错，避免把已识别文字消失伪装成整段漏识别。可用 `transcript_path/transcript_sha256` 代替 evaluation 文件，汇总器在 CPU 上调用现有评测器重算。

GPU/离线/资源证据是独立执行资格，未知设备不改成全部漏字。相反，数字好看也不会把 `execution_unverified` 升级为通过。清单提供的 `execution_verified` 应由独立运行证据支持，汇总器不自行认证这个布尔值。

## 汇总与配对

文字使用 `Σ(S+D+I)/Σ参考字符数`，纯静音场景单场景 CER 保持未定义，插入仍加入总体分子。时间分母覆盖所有预定非空参考跨度，缺失、对齐失败、调用失败和歧义保留。条件误差 nearest-rank P50/P90/P95/P99、有符号端点中位数、完整性与时间联合分位数、全体成功上下界和失败分类同时显示。合并多个场景直接合并单个跨度观测，不平均各场景 P95。

每一对路线另给共同有效跨度的误差分布、逐跨度差值和每个冻结场景的成对摘要，同时保留两者各自全体覆盖率。差值方向是左减右：误差/CER 越小对左侧越有利，覆盖率越大对左侧越有利。只有两个量均有限才计算分位差，不计算 infinity 减 infinity，也不把无共同有效跨度变成零误差。

`--paired-bootstrap` 只在至少 10 个固定场景时启用，按场景成组同步抽取两条路线，固定 seed `20261004`、2,000 次。报告 CER、覆盖率、0.5 秒确定成功率和联合 P95 的差值；非有限 replicate 另报数量/比例。可计算的区间明确称为“有限 replicate 条件下的 percentile 区间”，不能删除非有限项后假装总体置信区间。没有启用或场景少于 10 个时记录未运行及原因。

电影内部章节可能仍相关，10 个场景只是禁止过少样本强行 bootstrap 的实现下限，不证明独立抽样。重复模型运行也不新增独立参考样本。保留测试参考不足、声学人工标注不足和章节截断上下文限制不会因汇总而消失；正式晋级配置应由主流程在开发阶段另行冻结。

## 隐私和已验证范围

报告仅保留数值、状态、模型/配置标识、场景/跨度 ID、运行来源路径与哈希，不保留参考原文、候选全文或字符对应关系。文件路径本身可能含本机信息，发布报告前仍应检查。CLI 控制台输出仅有 route/configuration 标识和数值摘要。

10 项合成测试验证缺失完整分母、调用失败全删除与部分诊断、对齐失败保留文字、未证设备保留成绩但不获资格、静音插入、共同有效子集和原始覆盖率、哈希/规则拒绝、隐私文字不进入汇总、禁止选择性场景和 bootstrap seed/非有限处理。测试使用临时合成 JSON，没有读取真实电影或保留集模型结果。该工具不采纳模型、不实现正式晋级、不证明声学或 GPU 效果。

核心 `aggregate_manifest` 的上述边界保持不变。其外部已新增实际实验入口：

- `build_development` 固定开发195跨度、13配置，冻结源result/harness/参考/源码身份，CPU重评，另存实际设备、参数、缓存阶段和资源证据。最新不可变开发快照为 `.local/analysis/dev-comparison/cpu-v2-r7/`，见[开发报告](../research/2026-10-04-dev-comparison.md)。
- `development_selection` 经主agent授权独立计算[冻结规则](evaluation-config-v1.md)的八个Pareto轴和角色排序，不改变核心汇总。候选排除依据记录的生成/支持性失败，不能新增CER保护线。计算待主agent复核并冻结；独立审查已重新核对开发角色。
- `build_validation` 仅消费明确已启动的验证轮次，绑定实际freeze SHA、六候选、三章对应输入及151完整跨度。等待所有预定尝试终止后才提出固定角色锁定，已识别而FA失败保留文字，ASR部分失败另列诊断，全分母不变。实际验证快照 `.local/analysis/validation/cpu-v2-r1/`，见[验证报告](../research/2026-10-04-validation-results.md)。
- `build_heldout` 已在整批结束后读取16章、五套预锁配置和620完整跨度。参考按冻结的具体路径与SHA双重绑定，缺失或损坏result/harness单列完整性问题；下游未启动或导出拒绝时，仍保留独立证明已完成、对应音频SHA正确的上游ASR文字。Qwen全流程harness因FA失败时，全部窗口文本、CUDA生成证据、连续完整sample覆盖及固定source映射可独立证明ASR阶段完成，但不证明FA或全流程资格。保留阶段禁止重新选配置；固定场景bootstrap为2,000次、seed `20261004`，一部电影章节相关性仍限制解释。原始快照 `.local/analysis/heldout/cpu-v2-r1/` 及设备检查补充、失败边界见[保留结果](../research/2026-10-04-heldout-results.md)。
- `build_nonlexical_recovery` 为原轮次之后单章标点guard修复的CPU敏感性入口，保留15章原FA缓存、1章新FA及完整N620，要求原/新text、units、native、cues不变并核对音频/来源SHA与实际设备。它不替换原失败、不构成新盲测、不重选路线；独立快照 `.local/analysis/heldout/nonlexical-recovery-r1/` 只恢复1个可测跨度，整体未达标结论不变。

```powershell
uv run --locked --offline python -m experiments.analysis.build_development --include-qwen --include-crisp --include-extra-whisper --include-cross-family --include-whisper-components --include-normalized-ctc --output '.local/analysis/dev-comparison/cpu-v2-recheck-1'
uv run --locked --offline python -m experiments.analysis.development_selection --snapshot '.local/analysis/dev-comparison/cpu-v2-recheck-1'
uv run --locked --offline python -m experiments.analysis.build_validation --validation-started --freeze '.local/manifests/validation-freeze-v1.json' --output '.local/analysis/validation/cpu-v2-recheck-1'
uv run --locked --offline python -m experiments.analysis.build_heldout --batch-complete --freeze '.local/manifests/heldout-freeze-v1.json' --output '.local/analysis/heldout/cpu-v2-recheck-1'
uv run --locked --offline python -m unittest experiments.analysis.test_analysis experiments.analysis.test_development experiments.analysis.test_selection experiments.analysis.test_validation experiments.analysis.test_heldout -v
```

新增合成测试覆盖独立ASR/FA设备证据、GPU summary不能替代实际marker、按保存上游compression阈值记录生成风险、固定角色优先级/覆盖取舍、未启动拒绝读取验证、完整ASR与部分ASR失败区别、ASR-only上游设备、退出0但backend失败，以及预定范围未完成不得锁定。保留阶段另测整批读取门禁、原始/正式解码长度分离与不含原文的重复计数、缺失/损坏文件分类、缺失下游时完整ASR保存、FA失败但完整ASR仍保留、窗口完整覆盖与设备实证要求、错误源身份拒绝和参考路径互换拒绝。连同原10项共35项通过。开发、验证与原始保留主表均从冻结manifest重新消费复现；保留另外核对319个文件位置及逐章完整计数。这是实际已验证范围，不将CPU重评说成新推理。全部严格时间观察和声学资格未达标/未验证，整片、重复性、断网和人工边界仍依赖独立证据。
