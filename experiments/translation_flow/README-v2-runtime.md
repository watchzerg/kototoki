# 第二轮运行器与协议

此实现对应[第二轮计划](../../docs/plans/hy-mt2-translation-flow-exploration-v2.md)。旧 `worker`、配方与历史计划不变；新入口是 `experiments.translation_flow.v2_worker`。离线通过表示运行协议合格，翻译质量、长批次资源与缓存行为仍须实际证据。

每个候选与 seed 使用一次新的外层 `experiments.translation_demo_runtime` 会话，传入 `--session-worker experiments.translation_flow.v2_worker`。一个 v2 计划只允许一个 workload，不能通过共用同一服务跨候选继承缓存。外层已有独占端口检查、新进程与 PID／启动命令证据；内层要求单槽并核对**首次 completion 的 `timings.cache_n == 0`**。缺失、非整数或非零时停止并保留失败与尾段。`tokens_cached` 在固定引擎中表示响应结束时保留的 token 数，不是复用数量。`/slots/...action=erase` 仅清槽，无法据此证明 RAM prompt cache 为空。

## 冻结计划

`hy30-flow-session-v2` 的顶层字段为 `schema`、`stage`、`lane`、`budgets`、`experiment_identity`、`cache_reset`、`workloads`；可选 `resume` 与 `token_count_source`。阶段使用 `qualification`、`screening`、`confirmation`、`full-flow`，lane 固定 `P-flow`。不借用旧 P1／P2 窗口上限；全局质量分母由冻结源清单与评估侧维护。

`experiment_identity` 必须包含 `source_manifest_sha256`、`split`、`seed`、`recipe_id`、`source_order_sha256`；最后一项是 worker 的 `object_hash([batch_window_id,...])`，固定真实请求顺序。`cache_reset` 固定为 `{"method":"fresh-managed-server","verification":"first-completion-cache-n-zero"}`。四项保护预算与旧运行器相同，辅助规划、映射、审校及失败重试都计入 completion 调用和输入 token＋完整输出预留；预算耗尽是运行停止原因，不代表研究收敛。

唯一 workload 的必需字段是 `label`、`inputs`、`input_sha256`、`recipe`、`sampling`、`cache_prompt`、`n_predict`、`seed`、`max_attempts`。输入必须是严格的源文窗口 JSONL：`id`、`source_language`、`target_language`、`context:[{id,text}]`、`translate_ids`。源场景、时间、评分 ID 与源跨度由准备侧 sidecar 保留，不送给模型。目标必须按可见源顺序连续；批次数量、批大小与前后非对称邻文由准备侧冻结，worker 不二次分批。

官方采样与缓存分别冻结，不随提示名称改变。C0 固定官方采样、缓存开启及4096输出；所有生成步骤使用 Hy30 原生 `no_think` 模板、token IDs 传输。每次请求检查完整输入＋输出上限＋64 token 余量，不截源、不自动缩批、不回退 CPU。普通候选可显式冻结 `official-temperature0` 或关闭缓存作诊断，不能把这些混称当前官方对照。

准备入口的`n_predict`默认4096；非c0 recipe可在新卡中显式冻结其他正整数预算，用于有证据驱动的资源实验。它不会在容量不足时自动减少预算。可选`common_context_block_size`将只读可见范围固定为场景原点起的宏块及两侧邻文；宏块须整除固定目标批大小，不与token分批、offset、全场景common_context或辅助源文扩展混用。它保持原目标分批和尾批，额外记录逐批可见源身份；完整prompt容量仍须原生验证。共同源文诊断单列，不替代部署配方的总效应比较。

`v2_common_diagnostics`单独计算共同源文b3／b20对common-b5，以及三臂各对原匹配C0的五项直接配对诊断。入口要求外部固定的质量release SHA与全部29场景、三个seed实际可见源身份proof SHA；两场景资格或静态源几何不足。common-b5只是诊断参照，不改政策C0。它复用原作品等权、三seed、代表／风险分层及缺分界；探索区间不提供新增五项诊断或整个自适应搜索的同时覆盖，也不直接判胜。当前只有合成验证，尚未运行实际比较。CLI使用 `python -m experiments.translation_flow.v2_common_diagnostics --design DESIGN --release RELEASE --release-sha256 SHA --visibility PROOF --visibility-sha256 SHA --output NEW_JSON`。

## 已实现候选

| recipe | 行为与边界 |
| --- | --- |
| `c0` | C0 原提示逐字复用，原 ID JSON grammar，拒绝额外术语、背景、风格与审校 |
| `base-json` | 原 C0 提示与 grammar，允许单独加入 F6／F7／F8，避免同时改变联合理解 |
| `joint-json` | 仅替换“每值独立理解”指令为共同理解，保持 JSON、grammar、上下文与目标数据表达；禁止搬运事实或提前补完 |
| `id-text` | 实质非 JSON 协议：每条以独占行 `[[ID]]` 标记开始，允许正文换行，无 JSON grammar；解析严格核对顺序、完整覆盖与非空文本 |
| `semantic` | 真正三步：同模型仅凭源文规划连续语义单元，联合翻译单元，再按语义映射回原 cue；记录 evidence IDs 与 uncertainty |
| `id-text-flex` | 独立版本的非 JSON 协议，明确允许正文从精确 ID 标记同行或下一行开始；仍拒绝额外、遗漏、乱序、重复 ID，不模糊修复归属 |
| `id-text-ordered` | 新非JSON GBNF固定完整目标ID及顺序，每cue正文与标记同行且非空；正文保留Unicode和普通单方括号，双方括号留作协议分隔符，不允许正文换行；原生资格另验 |
| `semantic-anchors` | 保留源文规划和联合译文；单 cue 单元确定性映射，多 cue 单元用唯一精确子串定位边界，再由程序推导并验证完整跨度 |
| `semantic-structured` | 同模型对固定顺序的相邻源cue作合并／分界决策，程序推导精确覆盖的源单元；联合翻译后，模型提供原生译文的连续子串分区，程序验证逐字连接并计算跨度 |
| `semantic-partition` | 独立修订：有限空白的源边界规划；多cue映射使用针对原生译文构建的精确分区GBNF，只选择切分点，不允许删改、复制或重排字符 |

F5 保留完整单元译文，通过每单元 Unicode code point 半开跨度进行无遗漏、无重叠、顺序不变的精确分区。无法给每 cue 可靠非空区间时记录 `mapping_unjudgeable`，不复制整段、不回填日文；机械分区通过不证明语义归属正确。该候选须由交付和评估侧核对跨度与原 cue 时间。规划与映射为独立辅助调用，成本保留在同一 attempts 清单。

`v2_unit_diagnostics`提供纯函数辅助诊断：在读取输出前，用固定48／96评分窗相交的源batch去重选样，保留三个seed的全部slot，再分别构造完整原生单元忠实度和同一单元cue归属视图。跨窗单元不截拼参考、不回填主分，额外单元不增加独立样本。它核对所供原始字节、哈希和精确跨度；真实managed session／raw transport来源、源清单权限及冻结时间仍须custody接入验证。当前仅有合成测试，尚未执行实际单元语义评价。

`v2_unit_custody`新增源frame登记与原planner／native／mapper阶段的薄验证接口：生成前绑定三个seed卡、完整来源和固定源batch，需额外root外部SHA登记；之后只接收已认证主运行proof并核对原始请求及精确跨度。`v2_unit_main_proof`已实现完整主运行准入、exact20 proof和元数据复核callback：须认证全部734批，不能由选中84批反推全流程；原成本身份只计一次。旧匹配C0三seed已做离线机械认证并分别外部封存。实际F5尾批暴露原校验器不支持合法单目标planning跳过，新增`v2_unit_main_proof_singleton`仅修复此分支，73项离线检查通过；历史C0继续旧helper，候选须绑定新authority／replay和每seed外部seal，不能混称同一代码身份。候选seed08已完成完整机械认证、exact20 proof封签及实际metadata callback核验；seed09因映射与SRT交付失败保持partial，原singleton helper在invalid交付检查处拒绝。新增候选专用`v2_unit_main_proof_partial`区分worker执行完整与SRT交付完整，保留缺失证据拒绝、invalid／mapping unknown和原成本；83项组合离线覆盖与10项重叠独立检查通过，实际seed09全部734批已认证，但仍仅27/29场景完整。候选seed10也已完成完整认证与封签。新`v2_unit_role_seed_validator_partial`按固定角色／seed路由，V11主评价和`v2_unit_runner_partial`辅助入口通过39＋23项离线检查；实际六槽登记及六路metadata callback已通过，真实离线评价材料准备中；辅助新两profile手写探针各一次接受并通过原始raw／schema／drain和实际consumer验证；真实质量评价尚待；历史声明17个运行模块、捕获70个文件与当前9个诊断依赖分别记录，捕获不等于全部执行。`v2_unit_runner`已实现匿名fidelity／attribution分阶段调度、原生attempt留存、可靠性选择与封存，并通过59项离线合成检查。生成前固定84个完整源batch×3seed共252槽；各阶段每seed抽检ceil(84/5)=17槽，fidelity两臂使用同一选择，另加入严重或实质归属风险项。复核不按输出单元数量或成绩重选，同锚点的严重程度差异不能自动推断为同一事实争议。实际native profile探针、三seed候选MAIN准入和每阶段launch仍是独立前置；纯helper的`actual_native_authenticated=false`不被改写为原生或语义资格。

首版真实资格出现了 ID 标记换行不符和模型字符偏移错误，修订另立上述 recipe，旧记录不重分类。anchor 协议不让模型计算字符数量，不修改联合译文；没有多 cue 单元时不发送映射请求，明确记录该步骤零调用。修订协议的资格和质量状态仍以[接跑台账](../../docs/context/2026-10-08-hy30-flow-exploration-v2.md)中的真实运行证据为准。

`id-text-flex`后续长流程出现额外只读记录、重复／遗漏目标及正文布局失败；`id-text-ordered`是另立的严格协议，不能用来修复或追认旧输出。格式与grammar同时改变，可能影响生成分布；单行和保留分隔符也是表达限制。该recipe拒绝叠加review，未来组合须另行登记。

structured版本以GBNF固定边界决定数量、可见证据ID和映射源ID顺序，但不预设语义边界。
多cue单元的所有映射子串必须精确连接回未经修改的原生译文，允许相同短语出现在不同位置；
不能可靠对应时保留失败。单目标批无规划调用，单cue单元无映射调用，零调用及其来源明确落盘。
这些限制保证结构可检查，不证明分组、翻译或时间归属正确；真实引擎语法兼容性和模型资格另验。

`semantic-partition`的grammar构建有显式状态数与字节上限，超限保留失败，不截断译文；无法构成每cue非空分区时明确不可映射。它限制字符覆盖，不能证明语义或时间归属。真实引擎兼容和多cue实际调用资格必须另验，不能用全部单cue的零映射运行代替。

workload 可冻结 `terms:[{source,translation,evidence_ids,origin:"source-preparation"}]`、`background:[{text,evidence_ids,origin:"source-preparation"}]`、`style:"neutral"|"natural-dialogue"` 与 `review:boolean`。术语和背景须有允许源范围内的证据 ID；背景只在全部证据可见的批次注入，术语当前也按这个局部范围注入。代码只能核对证据身份和逐字引用，不能证明背景推断或译名正确；实际收益、错误传播和源文支持关系仍须后续独立语义评价检查。禁止从参考或裁判结果准备这些字段。

`review:true` 是 F8 普遍源文审校探针，保存审校前后结果及全部辅助成本；选择性运行路由尚未实现。semantic 审校会破坏精确原生分区，因此明确拒绝组合。当前支持冻结的局部术语／场景卡，未实现跨批自动提取译名、滚动记忆或场景状态传播，不能将 checkpoint 称为这些功能的证据。

`v2_review_trigger_features`仅提供三个事前固定的纯特征规则：目标源文的字面条件／否定标记、已接受初译的源文复制／相邻重复、二者的OR。`extract_features`保存全批次决策，初译失败或缺失时为unknown；触发不是错误标签。调用方必须先认证同批／同seed的真实初译，不能用审校后结果、参考或评分生成特征。目前仅合成验证，尚未接入原生审校选择、跳过交付或实际收益比较。

`v2_review_diagnostics.export_review_views(original_f8_delivery, output)`可导出同一次F8运行的
审校前后诊断视图，`validate_review_view`核验原运行、接受的两阶段输出、请求顺序和精确源锚点。
原始初译在后续审校失败时仍保留，完整SRT只在该视图全部cue与时间通过时导出。
该派生新增生成、样本与计时次数均为0，成本仅链接原trial；校正／误改／漏报仍须后续盲评。
主比较仍是F8最终译文对C0，不能把另一次生成的C0当作该次审校的实际初译。

`v2_review_root_evidence`已实现完整144配对分母的根证据packet、首轮证据与fresh假设复核、响应校验和开发90／留出54隔离。复核隐藏首轮分类、严重程度和理由，但可见中性根命题及锚点，因此明确属于hypothesis review；字符串一致不证明同一语义根。缺失或单方根保留unknown／provisional，开发发布重新核验完整私有记录，不能用全局汇总反推留出。`v2_review_root_runner`已实现custody派发、逐seed原始drain绑定的phase封存、重试前累计lease校验及开发集限定释放；最终版本27项定向检查与10项独立检查通过，历史23项完整生命周期检查属于修复前版本，不能作为最终全套重跑。一个手写hypothesis-review原生兼容探针已恰一次接受并完成封存及独立重验，真实F8素材、主证明、phase和根证据评价尚未执行；离线通过及探针都不证明实际质量收益。

`v2_review_evaluation`提供专用的同次运行前后诊断评价入口，验证真实派生视图、共同三seed范围及原始成本身份；两视图均使用fresh主评、独立全窗口复评和实际争议裁决，不导入旧意见。它保留全部预期窗口及失败，不将两个视图计成两次生成。分差不能直接变成修正／误改／遗漏计数，这些分类仍须独立的源命题证据关联。该入口已离线验证，真实F8诊断尚未运行；普通入口的诊断标签显式拒绝补丁仍在隔离区，运行时须使用此专用入口。

F6术语与F7背景可由同一个本地Hy30的独立源文准备会话生成。试验卡的`source_preparation:{plan,sha256}`绑定`hy30-source-preparation-session-v2`，其中分别选择`terms`或`background`，冻结源manifest／scene／freeze哈希、完整有序scene列表、stage、seed、采样与输出预算。准备器只读日文，保存原始提示／响应、逐scene尝试及证据原文；引用必须精确匹配源cue，重复术语至少出现于两条cue。v2不确定记录不注入主译文，证据匹配也不证明译名或背景语义正确。

`v2_trial`先执行完整准备会话，再用新的空缓存服务执行主翻译；前者的模型哈希、加载、生成、重试和卸载成本只记一次。只有完整且身份匹配的准备产物可进入主流程，失败保留成本并停止，不回退无术语翻译。`v2_prepare`将按批可见源证据投影为独立options sidecar，worker复核哈希和作用域后注入：术语使用当前可见的精确出现位置，背景要求全部支持证据可见。严格源输入行仍只有原有五个字段，不混入参考或评价资料。辅助预算显式冻结；超过实际token容量不得静默缩短源文或减少输出预留。

源准备v3另立`hy30-source-preparation-session-v3`，必须显式选择投影协议，不静默改变v2行为。F6的`eligibility-filtered-proposals-v1`保留模型全部建议及接纳／拒绝原因，由程序查找全部精确出现位置；不足两条cue的建议被明确排除，冲突仍失败，空集合明确记为零效果。精确出现次数不证明术语意义或译名正确。v3保留并展示`uncertain`标志，记录实际注入的不确定建议数量；不将建议称为已验证术语。

F7的`quoted-background-with-uncertainty-v1`配合`background-supported-scene-context-v1`，将选定支持原文与局部窗口合并展示，目标cue保持不变；记录实际可见ID、全部场景是否可见和注入数量。v3保留不确定记录及`uncertain`标志，并在提示中要求保留条件、否定、假设与歧义；记录不确定项的实际注入量，不能将其当作确定事实。提示只含模型需要的内容，完整哈希、协议与成本留在审计产物；worker启动时加载并验证sidecar，逐批仍检查字节身份。若有积极信号，须与相同准备产物、相同扩展原文范围的`background-supported-source-only-control-v1`比较；单独对C0的差异包含原文扩展和提示变化，不能称为纯背景摘要收益。

## 产物、恢复与计时

每个 workload 保留 `inputs.jsonl`、`run.json`、`window-*.json`、`results.jsonl`、完整 `ledger.jsonl`、只含未尝试尾段的 `schedule.jsonl`、`completion.json` 和原始 HTTP transport。`run.json` 保存准备映射哈希与源清单哈希；F5 窗口还保存 `semantic_plan`、`native_unit_translations`、`source_span_to_target_span` 和明确交付契约。失败不从机械或语义分母删去。

`checkpoint.json` 原子更新本次状态，成功窗口保存不可变产物路径／哈希。dispatch 前同步记录 `dispatch-journal.jsonl` 和预算预留，因此中断中的调用仍有保守成本证据。`resume:{checkpoint,sha256}` 只在新目录、新服务恢复；核对源、参数、seed、引擎、模板、源码、术语／背景与请求顺序兼容身份。只复用核验成功产物；复用行不冒充新计时或独立 seed，实测耗时为空，成本通过原产物追溯。旧预算累计沿用，未终结的旧 dispatch 保留未知成本记录。恢复改变 KV 连续性，`performance_valid_for_fresh_flow:false`，不能作为正常完整流程效率样本。

可选 `token_count_source:{inputs,input_sha256}` 指向严格源文窗口 JSONL。首次空缓存核验通过后，每个唯一 cue 的原文单独调用 `/tokenize`，输出 `source-token-counts.json`，保存模型／模板／引擎身份、原始 exchange、逐 cue 数量及耗时。此映射只用于 token packing 的加法估计，不包含提示、ID、模板开销，不能替代最终批次 tokenize。收集会影响运行耗时，资格运行与正常性能运行应分别冻结。

worker 墙钟包含源校验、准备、全部推理阶段、重试、映射与落盘；外层启动前完整权重哈希、冷加载、卸载、导出与评估仍须由父级计时记录。共享冷加载只记一次。源码快照与原始请求／响应可追溯；无实测的阶段保持未知，不能以阶段耗时之和冒充完整命令墙钟。
`generation_seconds`包含所有completion阶段，`auxiliary_seconds`包含规划／映射／审校等步骤，两者有重叠，不能相加；完整流程比较使用trial实测墙钟。

所有非`qualification`的`v2_trial`卡都必须绑定冻结判定规则，包括沿用`c0`提示但改变batch或邻文的候选。若卡提供`implementation_identity`，运行前还须逐项验证源码哈希；修改实现后另立卡，不能以相同名称掩盖代码漂移。

## 术语与准备传播诊断

`v2_consistency`提供三seed源术语并集、精确出现位置、整场景盲配对（A）及准备记录／实际曝光检查（B）的packet与本地响应校验。A区分同指称链、多义、嵌词、无害别称和统一但译错；B保留不确定性、缺失与全部预期记录，要求具体源命题、两侧译文和真实曝光才能记录传播一致模式。B无法完全隐藏处理组，此限制明确保留；两阶段均不改主评分，不将未知或未报告错误当作无风险。

`v2_consistency_custody`认证原始源、准备计划、raw／render、逐批曝光和成本身份，并保留各seed原始lineage；同一处理组三seed须有一致执行配置。`v2_consistency_runner`提供独立A／B packet与原生调用接入，复用custodian的全局六slot调度。真实F6／F7 v5卡片元数据形状及失败／漂移分支已通过合成回归和独立复审。首轮两个合成原生探针均因证据／覆盖校验未接受；新`v2_consistency_prompt_contract`显式提供响应身份和精确命题标签规则，并绑定独立probe目录，原严格validator不变。新版本已有离线与独立复核，两个合成原生探针各首试接受；一次模型调用前的路径类型错误另行保留，不当原生成功。探针仅证明接口接受性，真实F6／F7生成鉴权及辅助语义评价尚未完成；`v2_consistency_pair_bridge`已实现历史C0独立主proof与新源准备proof的配对接入，保留三seed、29场景×A/B共174槽及六份原始成本身份；UNKNOWN分支也核验控制侧源文、时间、顺序和分批。30项owner检查与8项公共入口合成检查通过，可信原始准入边界的stub范围另行披露。`v2_consistency_bridge_runner`已实现174槽的primary、fresh review、实际结构争议裁决、累计重试及跨阶段持久STOP；26项完整离线检查和5项独立范围检查通过，可信素材准入与native调用的stub边界保留。封闭producer已完成离线enrollment、独立复核与root精确登记，在guard前拒绝非精确executable路径字符串；新手写A／B原生探针各一次已排队，实际接口资格仍待其结果。实际F6／F7素材接入和frame仍待独立登记；旧C0不能套用当前代码身份。字面引用和哈希校验不证明语义判断正确；准备项覆盖也不代表全部术语。

## 正式配对计时入口

`v2_timing`将冻结政策绑定到计时计划：至少4对且AB／BA均衡的pilot，只用其方差选择最小偶数固定N（至少4），再以独立fresh会话完成全部确认计时；不按有利方向提前停止，不将时间重复当成新增质量seed。完整34场景／4297cue、实际trial墙钟、辅助准备和重试、缓存初态、原生请求及完整交付均须核验，旧运行不能冒充新计时。

正式卡片须覆盖原生会话记录的完整代码快照；日常候选卡的21项声明未必足够。条件观测器须按事前冻结规则提供安静运行条件证据，独立性、正态近似和顺序／漂移诊断须另有绑定收据；这些外部证据缺失、失败或未达到精度时仍为证据不足。合成测试和历史元数据对照不代表已经取得正式计时结果。

## 独立确认的预执行契约

`v2_confirmation`提供最多三个完整候选的一次性锁定、各三seed的C0／候选卡片、独立48窗评估范围、开封记录和dispatch身份检查。它绑定完整卡片执行配置及官方C0声明，拒绝跨seed配置漂移、开封后补位和筛选判断导入。元数据函数只核验源文件字节，不读取确认台词；外部custody记录仍须证明锁定时间和访问顺序。

`v2_confirmation_dispatch`是独立确认的专用启动入口：整队列绑定外部登记的lock／unseal哈希，在调用trial前后校验，拒绝既有输出，首次失败停止并保留所有未运行slot，不自动重试或补位。旧`v2_trial`仍可独立调用，因此不能用旧入口绕过确认契约。wrapper只证明实际调用及trial收据身份；`v2_confirmation_evaluation`进一步核验fresh session、cache、原生transport、辅助准备及完整交付，再建立每seed包含C0和全部锁定候选的全新评价根。失败／未运行slot保留完整48窗分母，不导入筛选判断。实际确认源仍未开放，离线验证不代表已取得确认结果。

确认collector也核验锁定候选的显式输出预算，以及可选共同源文宏块的真实源ID、顺序、正文和只读范围；每次原生请求必须匹配冻结预算。C0基线仍固定4096与原分批；使用c0提示的候选可显式采用不同分批，但不能改变4096。collector的离线兼容检查不代替相应生成版本的原生资格或独立确认。

`v2_compare`的确认分支须提供`--confirmation-authority PLAN --confirmation-authority-sha256 REGISTERED_PLAN_SHA`，并绑定C0及全部锁定候选的三seed卡片与三个全新评价根。它拒绝旧筛选／matched范围或判断导入；缺分保留上下界，严重风险仍须另行核验，不能用均分取代风险门。

辅助准备流程的配方身份使用完整规范化冻结计划，保留mode、协议、预算、源及其顺序、投影、split和声明代码；逐seed产物路径不能被当成配方变化，也不能从身份检查中简单删除。实际辅助产物、sidecar、原始命令及ledger成本分别核验。筛选评价元数据须提供受哈希绑定的`original_trial_attempt_identity`，或在`candidate_artifacts.artifacts`中绑定原trial-completion；确认使用其已登记的native trial收据。辅助成本每trial只计一次，这不自动赋予正式计时资格。

## 离线验证

```powershell
just translation-flow-v2-test
```

测试使用合成日文与 fake loopback 边界，覆盖 C0 提示一致、官方独立采样／缓存、F3／F4／F5、源证据、审校、上下文与辅助预算、空缓存核验、失败尾段、checkpoint 身份／复用和 token 计数成本。它们不证明真实模型能稳定生成相应协议或任何候选有质量优势。
