# Hy-MT2 30B 四量化串行比较

本入口实施[四量化方案](../../docs/plans/hy30-four-quantization-comparison.md)的 GPU 调度，复用
`translation_demo_runtime` 与原翻译器，不创建新的翻译配方。本历史比较的冻结对照基线为 Q3_K_M；
当前已采纳 APEX-I-Compact，见 [ADR-0005](../../docs/adr/0005-apex-i-compact-translation-baseline.md) 与 [demo 基线入口](../translation_demo/README.md)。原比较的 candidate、顺序和统计 baseline 键保持原义。
离线检查不能代替实际容量、30 分钟稳定性或完整质量评估。

所有命令从仓库根目录运行，输出必须为不存在的独立目录。下列 `<...>` 需替换为实际路径。
资产获取、参考审核和裁判分别使用对应入口；本运行器只读取精确的源输入 schema，
不接收参考译文、模型评分或裁判反馈。

## 冻结与工程预检

先等待相关实现修改完成，再冻结。未完成新增语料时可只冻结 smoke/dev；该冻结没有正式性能任务。
`--freeze-file` 可重复指定语料 manifest、参考文件及额外执行材料，保存哈希和源码／材料副本。
默认还冻结 runtime、demo、monitor、调度器、语料构建与审核提示、评估器、裁判、参考传输、统计脚本和流程方案。
执行时核对冻结文件，修改实现后应创建新冻结及新运行身份。

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_four_quantization freeze `
  --smoke 'D:/subtitle-samples/翻译模型评估库_v2/固定评测集/模型输入/smoke.jsonl' `
  --dev 'D:/subtitle-samples/翻译模型评估库_v2/固定评测集/模型输入/dev.jsonl' `
  --engine '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/llama-server.exe' `
  --engine-identity '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/identity.json' `
  --asset-manifest '.local/manifests/translation-download-plan.json' `
  --asset-manifest '.local/manifests/hy30-shortlist-downloads.json' `
  --output-dir '.local/translation-evaluation/<engineering-freeze>'

& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_four_quantization run `
  --freeze '.local/translation-evaluation/<engineering-freeze>/freeze.json' `
  --stage preflight --output-dir '.local/translation-evaluation/<preflight-attempt>'
```

预检顺序固定为基线、i1-Q3_K_M、APEX-I-Compact、i1-Q3_K_L。每款仅加载一次，先运行同一 dev
首窗预热，再执行完整 smoke15、dev41 和接近总预算的合成探针。探针使用实际 `/tokenize`
寻找最多 3008 输入 tokens，保留 1024 输出＋64 安全余量；探针不是质量样本。
`--candidate ID` 可选择单个候选；旧 smoke/dev 可通过 `--smoke-evidence DIR --dev-evidence DIR`
引用原翻译目录，须同时指定单个候选与 `--stage preflight`。程序核对完整成功、输入哈希、
context/output 配方及资产／引擎身份；预热和探针仍在新 session 执行。

GPU layers99、context4096、batch256、ubatch128、单槽、flash on、fit off 固定，不自动降低层数。
CPU threads8／batch threads8、KV f16／f16 与 RAM cache8192MiB 也显式固定在 runtime；原始 `/props` 保存有效设置。
runtime 校验权重 SHA256、模板及实际 offload；模型加载前有 30 秒空闲监测，冷加载与预热成本单列。

## 连续稳定性

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_four_quantization run `
  --freeze '.local/translation-evaluation/<engineering-freeze>/freeze.json' `
  --resume-from '.local/translation-evaluation/<preflight-attempt>' `
  --stage stability --output-dir '.local/translation-evaluation/<stress-attempt>'
```

成功预检是前置条件。每款重新加载、统一预热，运行合成容量探针后，固定重复同一 dev 源窗至少
1800 秒；只有当前请求结束才停止。每次重复使用新目录，明确 `quality_sample:false`，不计新增样本。
资源曲线由 runtime 唯一 monitor 采集；worker 的绝对 UTC 事件与监测时间戳可关联。

## 正式冻结、性能与首次质量结果

在冻结命令额外加入 `--regression <旧test.jsonl> --expanded <已复核新集inputs.jsonl>`，
以及必需的 `--expanded-corpus-freeze <语料freeze-manifest.json>`。程序校验最终双轮 fresh Sol/high 审核执行、
输入／参考／源映射哈希和 context 源事件隔离；staging 未审输入禁止正式推理。
默认要求旧83、新1200；明确规模不足时
可加 `--allow-scale-shortfall`，实际规模及 `expanded_scale_sufficient:false` 永久记录。
这不会把短缺、新旧集或 dev 合并成完整目标。

`run --stage performance` 执行四轮全部输入；通过 `--resume-from` 引用同一冻结下的预检证据。
正式冻结与工程冻结哈希不同，需重新验证预检，或引用一致的旧 smoke/dev 证据运行新预检。
A–D 映射以 seed20261006 随机冻结，各轮为 ABCD、BCDA、CDAB、DABC；每轮每款重新加载，
先同一 dev 预热，再在同一加载内分别执行旧83和新1200，不把两个集合合成一个计时／评分分母。

每个 `workload-summary.json` 包含完整／已尝试／成功／失败／未执行、token 数、重试成本、
p50/p95/p99、逐窗译文哈希，以及从首正式窗开始到全部终态已落盘后的墙钟耗时。
该耗时含 tokenization、请求、validation、重试及落盘，排除冷加载、预热、参考和裁判。
未跑完整时 `full_set_wall_seconds:null`，不能用局部耗时声称完整集更快。
`started_at_utc`／`finished_at_utc` 保留实际窗口边界，`terminal_artifacts_observed_at_utc`
是 worker 确认终态落盘的时刻，后者略包含 completion 写入和返回开销。

首轮原始产物确定质量输入，后轮仅做性能及复现一致性。导出示例：

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_four_quantization export-quality `
  --freeze '<formal-freeze>/freeze.json' --candidate hy-mt2-30b-a3b-q3-k-m `
  --split expanded --attempt '<formal-attempt-01>' --attempt '<formal-attempt-02>' `
  --output-dir '<quality-export-new-directory>'
```

按时间顺序传入恢复 attempt；其 `attempt.json` 记录的祖先链自动追溯、去重。
必须已存在该候选第一轮的终态 session，正在运行的第一轮不能导出为最终质量结果。
只读取最早终态 session 的原始产物，包括其中失败与未尝试尾段；后续恢复 session 或第二至四轮
不能补齐、替换首 session 的质量结果。已开始的 session 不能改记为整个任务 `not_run`。
恢复生成的完整结果可用于工程诊断，另建实验身份后才能作为另轮质量证据。
导出的 `ledger.jsonl`／`results.jsonl` 只有已尝试窗口，`schedule.jsonl` 为精确
`{window_id,status:not_run,reason}`，可传给评估器的 `--candidate-schedule alias=PATH`。
完整输入分母保留；译文、失败、未执行保持独立。

## 第一轮质量评估与后续性能并行

四量化私有 v4 编排器须等待四候选第一轮均持久终结，或留有明确容量阻碍及进程退出证据，
再将每候选唯一的第一终态 session 制成不可变快照并导出两个集合。
旧回归／新增集分别准备四匿名候选的完整 332／4,800 个预期窗口；失败与未运行尾段保留分母。
等待不能把正在写入的第一轮尾段当成最终缺失，也不能从后轮成功产物补齐首轮失败。

参考与 dev 流水线终结、实际子进程排空后，质量主评／复评／有界裁决可以与 GPU 第二至四轮并行。
GPU 仍一次只加载一个候选；CLI 全局最多六个。私有编排器共享原生字节锁，整条质量流水线持锁；
每步核对冻结源码与输入哈希，已有阶段账本或输出目录不重新分发。非零退出、必需任务缺失或传输失败
停止依赖阶段并保存完整缺分分母。合法 `resolved:false` 裁决只有在对应任务成功、canonical 身份和终评
null 字段一致时才是已完成的未决结果；保留不确定性，不追加裁判来强行确定。
并行 CLI 带来的 CPU／RAM／网络背景负载须随性能轮次报告，不能全部归因于量化。
这些是本轮私有编排器的约束；上方通用导出命令不自行启动或预约裁判。

## 中断、OOM 与污染

`schedule-ledger.jsonl` 只追加，每次运行新建 attempt。恢复使用 `--resume-from`，已完成 session
保留；中断性能 session 重新执行完整负载，历史结果保留，质量导出仍仅采用第一轮最早终态 session。
若只需待执行源子集，使用 `recover-workload --inputs PATH --history DIR [--history DIR] --output-dir NEWDIR`；
它保留首次终态路径，仅为缺失窗口生成 `pending-inputs.jsonl`，不修改历史。

显式 OOM 立即停止剩余请求，记录失败尝试及 `not_run` 尾段，清理只由 runtime 管理的进程。
默认不自动诊断重试；同配方最多一次独立诊断，可用
`run --stage preflight --candidate ID --diagnostic-oom-retry --resume-from PRIOR --output-dir NEWDIR`。
必须存在原 OOM、进程退出及采样显存回落至空闲基线＋512MiB 以内的证据；祖先链用于审计重试上限。
重复 OOM 不继续该候选正式任务；其余候选继续。

污染标准在冻结中预声明：共享／未授权实验服务或 GPU driver/reset 错误标记污染；
正式 session 的空闲 used/free 中位数相对首个正式 session 任一差值大于512MiB 标记环境不一致。
保留所有轮次，另建恢复 attempt 重跑；不根据速度挑删轮。显存变化或慢本身不代表 OOM。
缺少可用空闲采样时写明原因，不能视为已证明相同环境。

## 耗时、资源与稳定性汇总

独立离线汇总器读取已有产物，不启动模型或裁判：

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_four_performance `
  --freeze '<formal-freeze>/freeze.json' `
  --attempt '<engineering-preflight>' --attempt '<engineering-stability>' `
  --attempt '<formal-performance>' --output-dir '<new-summary-directory>'
```

可重复传入不可变 attempt，保留全部失败、污染和未执行记录。只有与指定正式冻结相符、
四轮完整且无污染的性能记录才计算相对基线中位耗时；工程冻结的运行单独列出。
输出 `performance.json`、中文 `engineering-report.md`、来源哈希快照、
`resource-curves.csv` 和 `window-alignment.csv`。后两者不含字幕文本；GPU 接收时间和
进程内存观测时间分别对齐，超过 0.75 秒的 GPU 旧采样不计为当前窗口观测。
长跑只有已完成阶段达到 1,800 秒才标记达标，进行中的采样不推断完成。

正式冻结应通过 `--freeze-file` 加入 `experiments/translation_four_performance.py`
及其测试，统计代码更新后使用新汇总目录，保留旧快照。详细字段和缺测边界以 JSON 为准。

## 离线检查与限制

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m unittest tests.test_translation_four_quantization -v
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_four_quantization --help
```

测试覆盖源输入防火墙、固定平衡顺序、OOM 停止、缺失尾段分母、首次失败保留、恢复防覆盖、
首次质量导出、固定重复块和输出预算。不会加载模型、下载资产或调用裁判。
GPU 稳定性、量化兼容及翻译质量仍以实际运行／裁判证据为准。
