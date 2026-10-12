# 固定 APEX-I-Compact 的 SRT 翻译流程筛选结果

2026-10-08结论范围更正：下文“已收敛”是第一轮交付时的判断。复盘确认其证据只支持所测具体配方未通过8窗筛选，不足以证明主要方向充分收敛或1-5-1最优；原始结果、评分和失败记录保持不变。后续采用[第二轮C档计划](../plans/hy-mt2-translation-flow-exploration-v2.md)，本报告不作为继续淘汰整个方向的依据。

2026-10-07。本轮有界筛选已收敛，**没有确认优势的新方案**。
不替换 [ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md) 的基线，也不把工程资格通过当成翻译质量胜出。
主要低成本方向均已实测；复杂术语记忆、真正语义分段与自审保留为有明确取舍的后续方向。
这不是“优化不可能”的结论。

可恢复状态见[探索台账](../context/2026-10-07-hy30-flow-exploration.md)，
入口见[translation_flow](../../experiments/translation_flow/README.md)，
参数依据见[官方建议与本机接口核对](2026-10-07-hy30-flow-parameter-check.md)。

## 范围和判定方式

- 使用四部作品：Frieren、ODDTAXI、SAO Progressive、鬼太郎诞生之谜。
  4个资格窗口与8个开发窗口分别冻结，没有横向跑全测试集合。
- 主要筛选始终使用同8窗／40条评分字幕。完整流程实验将它们扩为8段连续源字幕，
  每段15cue，共120cue；每个方案翻译全部120cue、检查全部覆盖并导出SRT，语义评分仍只有原40cue。
  另有20cue的早期SRT工程资格摘录。**这些都不是全片测试。**
- 所选参考来自已冻结、自动双轮复核的字幕库；不是人工日语金标准。
  这些作品曾用于历史模型选型，不能宣称完全未见的保留集。
- 非零温度筛选使用事前固定的20261006／20261007／20261008三个seed。
  其余结构比较使用显式temperature0；它在8个原窗口上与B0逐字相同，但仍保留独立配置身份。
- 每轮先冻结输入、变化和停止规则，再看结果。质量晋级需至少两组、两作品的可解释改善；
  成本晋级以配对流程时间降低至少15%、无明显严重错误或交付退化为起点，再做独立确认。
  不挑最佳seed，不因接近门槛扩样。用户后续放宽固定调用额度，实际执行继续受小样本和非穷举原则约束。
- 使用既有 `sol-high-auto-v1`：fresh Sol/high主评、风险并集与抽审的独立盲复评、一次有界裁决。
  比较只在各轮共同评估上下文内成立；参考、裁判输出均未进入翻译及源文准备。

本轮没有方案通过晋级门槛，因此未启动独立确认或全片验证。
12个备用确认窗及其中按每作品第一窗得到的4窗只做了源文选择／映射，**没有运行，不计入证据规模**。

## 完整流程和精确配置

共同流程为：只读解析源SRT → 保存原字节SHA与原cue ID／时间 → 冻结不重叠目标批次及只读邻文 →
本地Hy30生成带ID的JSON → 校验每批和全范围唯一覆盖 → 按原cue顺序／时间导出`chn.srt`及来源sidecar。
不靠返回顺序zip，不把缺失译文回填成日文。原时间是显示锚点，不代表已核验音画同步。

固定模型是 `Hy-MT2-30B-A3B-APEX-I-Compact.gguf`，SHA256：
`8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a`。
引擎为现有b11429／d81235049兼容loader，CUDA13.4，Windows11／RTX5080；
启动核对完整模型SHA，实际49/49层GPU，没有CPU层回退。
共同启动参数：context4096、单slot、batch256／ubatch128、threads8／threads-batch8、f16 K/V、
Flash Attention on、fit off、cache-ram8192MiB。仅容量探针将context改为8192。

| 配置层 | 原B0 | 后续结构实验的稳定对照 |
| --- | --- | --- |
| 提示 | 原Hy30逐ID JSON提示，包含只读日文及待译JSON | 完全相同的B0提示 |
| 模板 | 原生Hy30、no_think | 相同 |
| 输出 | GBNF固定目标ID；n_predict1024 | 相同 |
| 请求采样 | temperature0、seed20261006；保留旧省略字段 | temperature0、top_p1、top_k0、min_p0、repeat_penalty1、frequency/presence_penalty0、dynatemp_range0、mirostat0、samplers=[temperature]、seed20261006 |
| 缓存／重试 | cache_prompt=false；最多两次相同请求 | 相同，缓存消融除外 |
| SRT分批对照 | 工程外层补充，不改变已采纳demo | fixed5、每侧1cue、原范围完整交付 |

官方30B起点是temperature0.7／top_p1／top_k-1／repetition_penalty1／输出4096；
native HTTP把禁用top_k映射为0。最初先实测该采样族，再因三seed波动做唯一temperature0后续。
1024是本轮短批次的显式输出上限，没有冒充官方4096；后者另行完成资源资格核验。

## 候选对比与筛选结论

确认优势候选数为 **0**。下面保留被筛选的方案及适用边界，供人工决策，不把它们列为推荐替换项。
时间是对应比较内的翻译工作耗时；完整启动与评估成本另列，不能把窗口时间当全片耗时。

| 方案／唯一主要变化 | 适用假设 | 相对本轮对照的证据 | 代价、风险与未验证项 | 状态 |
| --- | --- | --- | --- | --- |
| 官方0.7采样族 | 官方解码起点改善质量 | 8窗×3seeds；B0 major窗口2，三个seed分别1／0／4；只有一组改善在至少2seeds重复 | 第三个seed在两处原先干净的窗口新增major；参数族含多个字段，不单独归因温度 | 已淘汰：不作本轮默认候选 |
| 官方显式族、仅temperature改0 | 降低随机波动，保留明确参数 | 8/8译文与B0逐字相同 | 不是新增独立质量证据，也没有质量优势 | 收益饱和：后续稳定对照 |
| 单份原文、去掉重复待译内容 | 减少输入干扰和prefill | 8窗；输入3576→2966tokens，时间5.985→5.563秒，约7%；major窗口1→3 | 第一seed即出现退化，不再增加seed找好结果；必要的寻址措辞属于格式变化 | 已淘汰 |
| 标点／停顿边界，最多5条 | 改善跨cue接缝 | 同120cue，24→32批；20.248→21.322秒；major窗口均2；仅一窗语义3→4，一窗自然度2→1 | 增加请求；标点和停顿会切断枚举或说明，不等于真正语义分段 | 已淘汰 |
| 固定批次5→10 | 减少请求和重复输入 | 同120cue，24→16批；AB/BA顺序交替，19.570→17.996秒，约8%；worker21.249→19.683秒；major窗口1→4 | 语义退化明显；批大小也自然改变单次可见源文范围，不能只解释成计算效率变化 | 已淘汰 |
| 每侧邻文1→3 | 补充省略与跨cue依赖 | 同120cue／24批；20.248→20.820秒；major窗口1→3，仅一个窗口改善 | 更多输入不保证忠实度；未搜索更大邻文 | 已淘汰 |
| 追加一条简洁自然对白条件 | 改善中文风格 | 8窗；自然度均2；major窗口均2；系列语义均分3.5→3.0，电影持平；时间基本不变 | 无可重复收益，不继续改写提示 | 已淘汰 |
| cache_prompt=true | 新字幕间共享提示前缀提速 | 首次新会话8窗，6.110→5.485秒，约10.2%；cache_n为0及142–146 | 低于15%晋级门槛，6/8译文发生变化，未进一步语义评价；同会话重复旧请求约32%提速不能外推首次翻译 | 暂缓：未确认流程优势 |
| context8192、输出上限4096 | 验证官方输出设置的本机容量 | 同一短窗分别上限1024／4096均完成，49/49 GPU，最低空闲223MiB | 实际只生成99tokens；不是满context、长输出或长跑稳定性证据，无质量优势声明 | 资源资格通过 |

上述major是自动裁判接受的严重错误窗口数，不是人工验证的错误率。
相同控制文本在不同轮的共同邻文／独立裁判请求下有评分波动，因此不跨轮拼接均分排名。
原始主评、复评、裁决及来源疑点均保留；小差距本身不支持优胜结论。

## 未继续投入的主要方向

**术语、背景和跨批记忆。** 先从120cue的日文中识别重复形式，再检查20次候选自身译写。
发现フリーレン的一处基础译名不一致；水木、時麿等称呼差异部分由原文敬称／亲属关系变化造成，不能统一替换。
这支持一个窄的人名偏好问题，尚不支持普遍的整片记忆收益。固定首译可能传播首译错误；
采用外部惯用译名又需要明确术语来源与风格偏好。本轮不从参考或裁判抽取术语，不据单个人名构建“已胜出”方案。

**恢复与按需审校。** 故障注入覆盖缺失、重复ID、结果冲突、截断、OOM、中断、源身份变化和原子发布失败。
实际214次生成全部结构交付，无翻译重试；机械恢复能力达到本轮资格要求，但并未证明全片恢复。
语义审校尚无已验证、独立于参考的触发器；无条件每批自审会增加生成与误改风险。
不把自动裁判指出的错误返送模型修复，也不把结构完整称为语义正确。

**自由段落／直接SRT／重映射／reasoning。** 当前逐ID输出未出现真实交付失败，
增加重映射需另证时间归属和遗漏风险；尚无证据支持这项复杂度。
官方模板存在low/high分支，不证明本机native completion、思考分离与GBNF组合已可用。
真正的语义规划、自审和背景准备并未被本轮否证；它们属于愿意承担额外推理及验证代价后的新选择，未假装完成实测。

## 成本、完整交付与限制

`final-costs.json`核对214次本地生成、236次Sol/high调用（含4次合成资格），均无重试，所有已启动的语义评估闭环完成。
本地tokenization加生成累计168.146秒，worker累计178.711秒；裁判attempt累计5142.030秒，
由于并行执行，后者不是用户等待的墙钟。裁判报告输入2,587,814、输出111,203 tokens；没有账单金额证据。

35个受管理模型会话累计runtime1626.699秒，其中每会话包含30秒空闲采样，冷加载累计233.733秒。
全量模型／DLL校验发生在该runtime计时之前，早期准备和导出没有统一独立计时，
所以不宣称这个数覆盖整个命令或全部工程投入。后续同模型dispatcher只记一次共享启动成本。
所有会话worker成功退出、模型进程清理完成、49/49层GPU；全设备采样峰值15755MiB出现在8192容量探针。
4096流程最低空闲约477–480MiB。采样可能漏过瞬时峰值。

首个SRT导出在沙箱原子重命名处失败，失败目录保留，获准host重试新目录成功。
一个本地导出辅助脚本曾因Python导入路径失败，修正后两组导出全部通过；这些不是模型翻译失败。
最终离线测试结果与源码／运行快照见台账。全片、音画同步、真实长输出、长期词汇一致性仍未验证。

## 复现入口与结果目录

以下路径均位于 `.local/translation-evaluation/hy30-flow-20261007/`，属于本机忽略目录，原文与结果不入Git。

| 实验 | 冻结入口 | 原始结果／评估 |
| --- | --- | --- |
| 官方族与seed | `p1-e1-a-plan.json`、`p1-e1-b-plan.json`、`p1-e1-t0-plan.json` | 同名`*-runtime/`；`p1-e1-eval/`；`p1-e1-t0-equivalence.json` |
| 去重复 | `p1-e2-plan.json` | `p1-e2-runtime/`、`p1-e2-eval/` |
| 简洁风格 | `e5-style-plan.json` | `e5-style-runtime/`、`e5-style-eval/` |
| 自然边界 | `run-e3.py`、`e3-*/screening.json` | `e3-*-runs/`、`e3-*-exports/`、`e3-projection/evaluation/` |
| 批次10 | `e3b-dispatch-plan.json` | `e3b-dispatch-runtime/`、`e3b-exports/`、`e3b-projection/evaluation/` |
| 邻文3 | `run-e4.py`、`e4-fixed5context3/screening.json` | `e4-fixed5context3-runs/`、对应`-exports/`、`e4-projection/evaluation/` |
| 缓存／容量 | `e7-cache-plan.json`、`e7-cache-cold-plan.json`、`e7-capacity-plan.json` | 同名`*-runtime/`及`*-metrics.json` |
| 机械资格／总成本 | `p0-srt-prepared/session-plan.json` | `p0-srt-export-v2/`、`final-costs.json`、`final-runtime-summary.json` |

例如复现批次实验，使用现有环境与固定引擎，将输出改成一个尚不存在的目录：

```powershell
& '.venv/Scripts/python.exe' -B -X utf8 -m experiments.translation_demo_runtime `
  --candidate hy-mt2-30b-a3b-apex-i-compact `
  --engine '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/llama-server.exe' `
  --engine-identity '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/identity.json' `
  --layers 99 --context-size 4096 --threads 8 --threads-batch 8 `
  --session-worker experiments.translation_flow.dispatch `
  --session-plan '.local/translation-evaluation/hy30-flow-20261007/e3b-dispatch-plan.json' `
  --output-dir '<新的输出目录>'
```

单计划改用`experiments.translation_flow.worker`；容量探针明确使用context8192。
SRT导出使用`python -m experiments.translation_flow export`。
重新评价新生成结果时，复制对应projection plan到新文件，只更新候选运行路径，
保留源选择／评分ID／参考身份，再运行`project_evaluation`和`judge_loop`。
不要覆盖旧目录或静默复用旧评分。源模型、语料的绝对路径与哈希保存在冻结计划里。

## 人工review需要决定的事项

1. 是否继续维持当前B0，先把已验证的SRT工程外层用于下一阶段？它提供完整交付与可追溯性，不代表质量提升。
2. 约10%的首次前缀缓存收益是否值得单独继续？若值得，下一轮优先做独立短SRT确认和语义非退化检查；本轮没有完成这项确认。
3. 是否为跨批人名制定明确译名偏好，允许以源文／首次模型译写建立小型术语表？下一轮应先检验错误传播，不能只看名字一致率。

更昂贵的语义规划或按需自审应单独设立质量优先实验，不与本轮未胜出的提示／分批组合叠加。
本轮到此停止，不自动选择最终方案、替换基线或启动下一轮。
