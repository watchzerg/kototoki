# Hy30 第二轮探索台账与接跑

> **Claude Code 接手说明（2026-10-10）**：旧会话的进程、custodian／ROOT 角色与 `gpt-6.1-sol` 裁判均已失效；冻结评审模型不可由 Claude 延续，只能新建版本化 profile，且不得与旧分数混算。接手先只读核对 python／llama-server 进程与 `.local/gpu.lock`，不要终止他人进程，再决定是否继续。以下为 Codex 时代原文，保留作证据。**v2 已停止，不再接跑；后续工作见[v3 台账](2026-10-10-hy30-flow-exploration-v3.md)。**

日期：2026-10-08；最近人工交接核对：2026-10-09 21:49–21:52（Asia/Singapore，13:49–13:52 UTC）。**用户要求切换 agent，本轮停止追加实验。探索尚未收敛，独立确认48仍封存，尚未锁定确认候选，未替换基线。F2六项已返回：5项sealed、最后ctx3 seed20261010为terminal_unknown；不能沿用此前“45468仍运行中”的状态。fresh C0三seed生成与机械认证完成，材料／MAIN未执行。**

权威方案：[第二轮探索计划](../plans/hy-mt2-translation-flow-exploration-v2.md)。用户已选C档96筛选＋48确认，并要求深入验证、资源配额宽松、批次大小充分自适应探索。2026-10-08已授权执行完整计划；下方准备审计保留计划制定时的事实，新增执行状态另记。

## 2026-10-09 切换 agent 接跑入口（最新，覆盖下方历史状态）

### 交接时核对到的实际状态

- F2真实文件 `summaries/F2-exact-six-native-main-once-preparation-v1/retained-native-once-v1/SAFE-completion.json` SHA256 `6b4f27cd7b165113b82ba3813d94460b647446afb8029886f5bf3f7caf9bd40e`：state=`six_original_F2_MAIN_entries_returned`，固定576槽；index0／1／3／5／7均sealed96，index8（ctx3 seed20261010）为terminal_unknown。最后一组PRIMARY96 accepted；REVIEW0 accepted、8 failed、88 pending。不能将其96槽使用PRIMARY代替最终评分或当零分；不能据缺失判基线胜出。六个终态manifest仅核对字节，全部SHA匹配，未读取私有评分正文。
- ROOT最新CIM快照无python／pythonw／llama-server进程；仅见Codex应用相关进程。这是快照，不是正式custodian drain。原45468属于旧子代理session，新agent不能以自己的session查询失败推断其退出码；本次未取得45468外部工具EXIT记录或最新D0。终态文件已存在，不可重跑原once入口。
- `evaluation-only/PRIVATE/F8-dev90-root-evidence-v1` 当前不存在；已签的 `summaries/ROOT-F8-dev90-post-side-material-v1/ROOT-prepare-once-release.json`（f0075bd6…）是待执行材料prepare，不是native授权。本轮没有启动它。先核对实际前序drain与入口是否已有失败记录。
- 原 `evaluation_custodian` 接收交接请求时返回400：`The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account.` 这是本次子代理启动失败的实证，尚不能推断F2末组失败与它同因。下一agent先核对实际可用agent／judge模型与认证；不要悄悄替换冻结评审模型、混算不同模型结果。若必须改judge，版本化并重新满足可比性要求。
- 已要求旧custodian停止追加任务；未杀进程、未清锁、未删除失败、未覆盖旧命名空间。切换agent不继承旧session控制能力；新上下文应重建角色隔离并按文件／真实进程接跑。

### 已有发现及边界

最新已发布汇总为 `summaries/current-screening-evidence-matrix-v16/summary.zh.md` 与同目录metrics／freeze。它是筛选证据，不是最终收敛报告。批次和上下文多项在剧集有正向信号，但电影非劣、严重风险及跨作品稳健性仍未普遍满足；不能宣布现基线最优。

- token400 full96三seed：代表剧集语义Δ约+0.3611，但family区间跨零；代表电影约+0.0185，尚不稳定；B半风险剧集−0.3333且三个seed均负。配对自然度代表剧集−0.0556、电影−0.0370；完整严重风险门未通过。当前控制身份需由fresh C0严格比较澄清，旧诊断不冒充正式晋级证据。
- F4 full96代表电影约−0.1574，family区间为负；F5当前语义单元配方代表剧集／电影约−0.5185／−0.5。否定具体配方不等于整个探索方向收敛。
- F9 full96首seed容量超限、其余未跑；不要把partial或matched48混入full96。B60、token600等电影退化另有证据，不能只取剧集收益。
- 生成／机械通过／SOURCE实现通过均不等于翻译质量通过。旧失败、UNKNOWN、真实辅助与重试成本必须保留；参考、候选及judge原文维持评估侧隔离，ROOT仅看允许的SOURCE／SAFE／限定元数据。

### 下一步顺序与现成入口

以下路径均相对于 `.local/translation-evaluation/hy30-flow-v2-20261008/`；先读各目录readiness／README／签署recipe，实际执行前核验完整SHA、现状及权限，不把这里的路径清单当作执行授权。

1. 回收F2实际终态／D0／失败诊断；F2统计就绪入口 `summaries/F2-full96-post-MAIN-comparison-readiness-v1/`，保留ctx3末seed未知。按既存限定程序做runtime／metadata／结构核验，再分别比较ctx0/C0与ctx3/C0；不得自动重试或混入ctx8。
2. F8已签post-side prepare完成后，优先fresh C0材料／MAIN。fresh C0生成11028及三seed机械检查均完成；真实绑定未激活草稿 `summaries/ROOT-fresh-C0-material-hydrated-draft-v1.json` SHA `ebd63751b3297422892b839b10a86b6423450797af66d666537b329903ce8ea3`；入口 `summaries/fresh-C0-full96-material-main-intake-preparation-v1/`。新writer观察／真实D0／分别签署material与MAIN仍缺，固定288槽。
3. fresh C0 MAIN真实完成后依次走 `fresh-C0-token400-full96-strict-comparison-preparation-v1` → `fresh-C0-token400-full96-selected-numeric-metadata-preparation-v1` → `fresh-C0-token400-full96-strict-numeric-envelope-preparation-v1`（均在summaries）。三段SOURCE已实现并独立审查，实际授权／结果未生成。原numeric selector的候选dispatch上限132明确保留，不能截断额外attempt成本来通过。
4. 已有材料优先消化：ctx8固定144（`ROOT-ctx8-typed-native-signing-draft-v1`）；F6 rolling六组固定288（`ROOT-F6-rolling-six-native-signing-draft-v1`）；origin固定270含10 UNKNOWN（`ROOT-origin-primary-draft-v1`）；common b3/b5/b20九组固定432（`common-native-queue-preparation-v1`），B1另144。common12实际runtime同一哈希已验证（`common-twelve-generation-runtime-metadata-projection-v2`），不必重做该投影；质量／reference尚未因此通过。
5. F7 fluency与semantic现成入口见 `summaries/F7-existing-queued-native-readiness-audit-v1/ROOT-dispatch-recipe.zh.md`，不必重建材料／重probe。F5 cue归属252材料已完成，新合成probe／retained入口见 `summaries/F5-cue-v2-post-material-readiness-audit-v1/implemented-SOURCE-readiness-v1.json`；仅SOURCE资格通过，实际probe及三个阶段未授权。旧224 UNKNOWN是zero-ADJ层，不能称完整fidelity最终缺失224；cue归属也不能替代语义单元忠实度。
6. F8 dev90先取得开发证据，再冻结一个可部署trigger，才可打开独立held54。原synthetic probe已做且只读验证通过，登记 `summaries/ROOT-F8-existing-probe-reuse-registration-v1.json`（182d8487…）；**不要重新执行旧0542 probe或重置其目录**，先验证新dev90 transport与已验证probe完全一致。
7. 后续机制分支取舍见 `summaries/remaining-exploration-decision-audit-v1/decision.zh.md`：先消费现有结果，再按证据做B15、非对称邻文、语义单元修订、style／context交互等必要探索，不默认铺满网格，也不以预算为由删除尚未解决的问题。

所有后续严重风险审查、正式效率重复计时、候选联合锁定、独立确认48、整片验证及最终中文报告仍按计划完成。确认48与F8 held54不同，均不得提前解封。尚未锁定任何确认候选、没有正式性能结论、不自动替换ADR-0005基线。此前15–20小时乐观估计早于本次模型不可用及F2未知终态，不能继续当作可靠剩余时间承诺。

## 此前累积摘要

此前累积摘要（保留00:10 UTC及更早接跑状态；当前执行状态以上方最新条目为准）：**F1-b3／b10／b20／b40三seed matched48配对结果已解封，剧集代表窗有正向信号，电影非劣尚未证明。b20与b3风险复核均支持新增major，且有未解决记录，当前具体配方不能放行；b20与b3完整96三seed生成均完成，b20完整96统计已完成：代表窗剧集Δ+0.3185、电影+0.0926，但新增半组剧集风险窗Δ−0.4444且三seed均负，当前配方不能放行。F2 ctx0／ctx3三seed生成均完成，ctx0主评价和统计完成，代表窗剧集Δ+0.2407／电影+0.0042，风险剧集−0.1111；风险复核新增MAJOR3对、恶化1对且46未知，当前配方不能放行；ctx3三seed评价及统计完成：代表窗剧集Δ+0.3333／电影+0.0792，但风险复核新增MAJOR8对、恶化1对且42未知，当前配方不能放行，尚未锁定确认候选；两组完整96及8/8上下文补充9卡已冻结并在原36项队列生成，前9项命令完成，八项机械通过、一项恢复输出触顶被原检查拒绝；初始ctx0／3共576材料准备中，质量待核验。F5主评价三seed完成，代表性动漫／电影Δ−0.5185／−0.5000且各作品剔除后仍负；当前版本全流程T/F/T，辅助诊断继续，不能据此淘汰整个方向。F3联合理解matched48代表剧集Δ+0.2037／电影0；风险复核新增MAJOR3组、恶化1组且39对未知，当前具体配方不能晋级，完整96 MAIN已封存，统计前源版本可比性审计继续；F9 b80／3072 matched48剧集+0.5185、电影−0.05，严重风险汇总新增MAJOR9组／8窗口／13配对且37UNKNOWN，当前配方不能晋级；完整96生成因输入输出预算失败，不与matched结果混算；B40 full96代表剧集+0.1778／电影+0.0370，但第二半风险剧集−0.6111且三seed均负，不能据第一半晋级；F4 ordered代表剧集+0.0741／电影−0.1542，尚无稳定优势。原始B60 matched48代表剧集+0.3889／电影−0.3292，电影各seed及逐作品剔除均负、whole F/F/T；不与finite-v2混算。token400／600 matched48代表剧集Δ+0.5370／+0.6481、电影−0.0583／−0.1208；位置诊断显示明显作品与场景异质性，不能确认最优token预算，token600保留whole F/F/T。token400完整96与finite-B60三seed生成完成，前者三seed机械校验及材料接入完成、MAIN待执行；后者MAIN三组已封存、固定144统计待完成；F6记忆两策略通过真实工程资格，质量未测；F8开发子集材料就绪、语义未测，F3完整96 MAIN已完成但统计未发布，F9完整96首seed partial后原队列停止，其余两seed尚未运行。源准备四槽完整、两槽AUX失败且MAIN未运行，真实机械认证完成，评价接入继续。探索尚未收敛，基线不变。**

## 本次执行进度

### 10月8日至9日跨日接跑（UTC时间）
- **F5归属诊断执行入口已补齐**：SOURCE readiness e66c5938、producer fbedbf51、retained entry dee56dc4与独立review38379057已冻结并核对字节。21项限定测试及6项独立检查通过；修复post-drain schema／stdin绑定，保留历史D0而不设置任意年龄阈值。实际probe与252槽各阶段尚未授权／执行；原zero-ADJ层224 UNKNOWN仍保留，cue归属不能替代完整语义单元忠实度。
- **fresh C0严格比较的限定数值元数据入口就绪**：独立review8106aa79／freeze89b81a28通过，ROOT已读SOURCE和审查并核对字节。严格compare→限定metadata→ROOT核对签署→numeric的实际链仍待fresh C0 MAIN；原数值selector限定candidate最多132 dispatch，合成133明确拒绝，不能宣称泛用重试支持。已发布旧token400数值使用相同固定候选，未来若实际范围不符仍拒绝，不截断成本。
- **fresh C0严格结果数值导出SOURCE就绪**：独立numeric入口21ba8a59／freeze31d10456，review da1e23eb／receipt54691946通过；ROOT0f25c3已读完整入口。继续使用原8个数值selector与三split算术，仅替换严格结果身份校验，不接受旧diagnostic bridge或历史C0成本。实际summary／cost metadata／ROOT许可均未生成；另一个限定字段lexical提取入口正在收尾，不能把模板存在当作实际结果。
- **common实际runtime元数据已一致**：修正v2实际931644 EXIT0，[SAFE metadata14974766](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/common-twelve-generation-runtime-metadata-projection-v2/SAFE-selected-twelve-runtime-metadata.json)／result fc43af2d／toolchain faba55cc保留旧c71520失败。12组实际session原13e稳定engine＋template哈希只有1个，全部wrapper对应captured32a；此结果只消除这项runtime身份疑点，不是reference／quality／whole pipeline认证，九组MAIN仍待执行。
- **F7既有入口可直接接跑**：[审计95e3b1ce与执行步骤](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/F7-existing-queued-native-readiness-audit-v1/ROOT-dispatch-recipe.zh.md)核对fluency b49d／77cdf仅PRIMARY288，以及独立semantic548340／fc55固定144 MAIN。旧授权不因日期较早自动失效；实际新writer观察／前序drain尚NULL。未运行、未重建材料、不重新probe；后续按真实队列分配执行，量尺与结果分开。
- **common runtime元数据投影v1真实失败**：c71520 EXIT1／SAFE27e844b1，全部12套原generation／card／captured源码／session字节核对先通过，随后提取器将session.code_sha256误断言为scalar。ROOT按原v2_worker源码2ab2c6确认其为source_snapshot模块映射；已限定授权相同12范围v2修正，只选wrapper键存在性和原engine稳定字段，不改比较或认证规则。旧失败保留，无runtime比较结果；F2 owned polld1b15f仍LIVE。
- **common后续五项比较无需重写统计**：[readiness b6813e83](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/common-post-MAIN-readiness-v1/readiness.json)／freeze8b2cf6ce已冻结；保留原e160 visible-source验证及3df summarize。ROOT3023c8检查的12槽SOURCE roster faab4cfb显示matched29 C0与九个common captured wrapper均32a16，与旧full34 C0的4fd身份不同；实际session／完整runtime／reference仍待验证，已限定授权generation runtime元数据投影，不读评审正文。
- **F5新版归属评测接入缺口**：SOURCE审计发现原1e1f runner要求new-v2 native probe，但未提供执行producer；不能用252正式phase绕过。已授权补一个独立synthetic单次probe入口与精确签署草稿，保持原schema／prompt／parser及global guard，实际native仍未授权。旧fidelity零选中ADJ层UNKNOWN224与not_required280保留；224不是collapsed final fidelity缺分数，原contract没有final scalar。新版cue attribution252不能回填旧unit fidelity。
- **fresh C0／token400严格比较SOURCE就绪**：入口d50d7c40／producer freeze3b62040e，独立复核65f30a10／receipt9cbe9e33通过；ROOT已读完整入口与role view并在3adf4b核对25＋4清单文件。强制真实fresh terminal intake先于token879和原13e／f808；仅已登记三卡的统计baseline角色显式映射，原执行身份保留，无runtime waiver。实际MAIN／严格比较／数值结果未完成，旧diagnostic exporter不能直接接用；仅准备窄数值身份接口后继，统计算法不变。
- **F2实际进度4／6**：custody owned poll9affd1确认45468仍LIVE，限定public SAFE检查8f0915显示exact prefix index0／1／3／5均sealed96，新增ctx0 seed09；剩余7／8终态未发出，不推测质量或调用数。F5新版归属诊断和F7既有fluency／主语义入口开始限定接跑审计，不增加native权限或改变当前队列。
- **F8原探针复用证据已核实**：原9aa8 read-only validator实际a2cf0d EXIT0，SAFE f245ad5f／tool2165f1ff；原cb82 receipt兼容、synthetic、jobs1／max1，库存及accepted ledger／历史drain完整性通过。ROOT325e93核对并独立登记[既有证据复用记录](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/ROOT-F8-existing-probe-reuse-registration-v1.json)，新增probe／dispatch／seal均0。原历史external tool未找到，明确保留限制；本次真实只读验证有独立工具终态。仍须等待实际dev90 protocol并逐项比对transport、另签evidence权限和最新D0，不以历史drain冒充当前空闲。
- [剩余探索决策审计](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/remaining-exploration-decision-audit-v1/decision.zh.md)93cab530已完成：先兑现F2／fresh C0、common／origin、rolling／F7、F8与F5归属诊断，再依机制触发B15、镜像邻文或最小交互；不默认全部齐跑，也不因最小序列删除独立未解问题。未释放结果继续UNKNOWN，尚未锁候选或收敛。
- **F8探针历史发现**：ROOT实际路径检查49c73c确认原synthetic probe根已有execution、responses及compatibility-receipt.json，原0542 wrapper的禁止重跑条件成立。旧SOURCE签署方案不能直接执行新probe；已要求定位原真实工具／sealed receipt，并审查与dev90 transport完全相同时的既有证据复用路径。未读probe正文、未重置或重跑；不能仅由文件存在推定兼容成功。已授权F8 prepare f007不受此发现影响。
- **F2后续比较入口已完成源码资格**：[交付aa8e6987](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/F2-full96-post-MAIN-comparison-readiness-v1/final-SOURCE-handoff.json)与[签署步骤2bbb3499](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/F2-full96-post-MAIN-comparison-readiness-v1/ROOT-next-signing-sequence.zh.md)冻结；独立core3bb74／numeric989db通过，旧numeric ABI失败记录保留。ROOT已读完整comparison3e23／runtime seam06b6和元数据契约，尚未观察实际runtime资格或签署执行。两个full96比较各自288／288槽，三个原C0跨报告共享、不重复计成本。最新custody实际poll44928c确认45468仍LIVE，public checkpoint e2dc33维持3／6；ROOT直接查询子代理session的Unknown process id不作为终态证据、未重启。
- **fresh C0材料接入草稿已绑定真实证据**：限定metadata投影b281e1 EXIT0，metadata f3a83edf／SAFE bded63f6／tool4c153c8b。ROOT8f7254按原source contract核对三个card／trial root、原generation成本及checker身份，生成[未激活草稿ebd63751](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/ROOT-fresh-C0-material-hydrated-draft-v1.json)。fresh observation／immediate D0仍NULL，无材料或native权限；等待F2终态及已排在前面的F8 prepare。F2实际poll7dafc9确认45468仍LIVE，不依据锁文件推断存活。
- **fresh C0三seed机械核验通过**：08／09／10实际session71227／40784／1070分别992a87／40651e／d17c23 EXIT0；[串行终态证据0781c290](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/custodian-recent-actual-tool-evidence-v1/fresh-C0-three-mechanical-actual-tool-chain-v1.json)及三个SAFE已由ROOT eb555a核对，六个私有proof仅hash验证。机械通过尚不代表翻译质量、材料或MAIN完成。F2最新public checkpoint b395e5已有3／6项sealed96（index0／1／3）；其余结果待实际终态。
- **剩余时间预估**：已向用户说明乐观仍需15–20小时、较稳妥20–30小时；条件是无重大新增失败或必要探索分支。此估计不是预算上限或收敛判据，优先完成已有实验和共用当前控制，避免重复工程工作。确认48仍封存，未锁定候选。
- **fresh C0生成全部完成**：11028实际6a700c EXIT0，SAFE f60e4809／tool26a0b0be确认三个原命令complete，但机械资格仍NULL。whole entry2312.003575秒与trial重叠，不重复加总、不作正式性能证据。ROOT实际CIM3c4219得到目标writer快照87e0c8be，matching0／unknown0；只代表快照。ROOT c184c2签署[机械enrollment12a56a35](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/ROOT-fresh-C0-full96-mechanical-enrollment-v1.json)，授权固定08→09→10逐项原replay／build／verify，首个失败停止。实际机械终态尚未知；无material／MAIN权限。
- [证据矩阵v16中文报告](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/current-screening-evidence-matrix-v16/summary.zh.md)已冻结：report3e74ab76／metrics b63bb8d8／freeze4336ed48。完整保留v15和旧缺失字段，新增token400三视图配对自然度；两项报告字节后缀和157原pins不变。新增统计来自同一六次生成，不增加独立样本或成本。
- **待执行队列优化（不是授权）**：F2六项真实终态后仍先执行已签F8 prepare f007；若fresh C0生成与机械认证均真实完成并获得独立新权限，优先fresh C0 material／MAIN，再ctx8→F6→origin／common。这样先澄清共用当前版本控制组，减少对历史控制下已无保留价值候选的重复风险评测。若控制未就绪，ctx8仍须新ROOT grant才可执行；没有预占或中断当前任务。
- **token400完整配对自然度已发布**：v2 25879实际a2325b EXIT0，SAFE b5bacec6／外部工具4ea04cee；[numeric2efb3432](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/token400-full96-paired-naturalness-SOURCE-v2/actual-numeric-once-v2/numeric-summary-SAFE-v1.json)两臂288／288自然度已知。combined代表剧集Δ−0.055556，family9区间[−0.175926,+0.064815]，三seed及逐作品剔除均负；代表电影Δ−0.037037，work95区间[−0.064815,−0.009259]，seed正负混合但逐作品／系列剔除均负。电影series／family区间退化为同一值，源于本样本簇均值相同，不能理解为真实差值零不确定性。risk剧集+0.111111、电影+0.277778独立展示，不抵扣语义严重错误。原C0语义缺失1仍缺失，不因自然度已知补分；新数字不带来pipeline等价、严重门通过或晋级。旧90385失败保留，whitelist正文未发布，native／auth／新增generation均0。
- **新增实际进度**：F2 MAIN45468 checkpoint067b4f仍LIVE，原SAFE prefix已有index0／1（ctx0／ctx3 seed08）各sealed96，完成2／6，质量未发布。fresh C0 11028 checkpoint216cca仍LIVE，原public journal已有index0／1 COMPLETE、index2 STARTED，完成2／3 seed命令；整组资格待核验。自然度v2权限59ac下实际25879（初始8aacd9）已启动，数字结果待回收。
- **自然度v2新许可**：SOURCE1db8c2cb、math4fe原字节、独立review73c29a8e及freeze b60e7849通过；ROOT ca644e签署[新单次许可59ac3d3b](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/ROOT-token400-full96-paired-naturalness-numeric-once-v2.json)，绑定六组原登记mapping b8dcb25b和全部旧失败证据。实际v2终态未知，尚无新数字发布；不是复用旧3c325权限自动重试。
- fresh C0 11028普通checkpoint73f860仍LIVE；原9c0 public journal限定投影4369c9记录index0 COMPLETE、index1 STARTED，共1个seed命令完成。该计数不证明生成质量、机械资格或整组三seed完成。F2 MAIN45468 checkpoint36ea9a仍LIVE。
- **common-source接跑审计**：[报告faff79b2](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/common-source-remaining-evidence-source-audit-v1/conciseChinese.md)／freeze4d2ae023确认原实际九组full29／3606可见源证据已存在且30文件hash匹配，不需要重新生成或导出；common b3/b5/b20各144材料就绪，B1另144。MAIN完成证据尚未取得，质量仍未知；后续沿原执行与五项比较，common b5不等于policy C0。
- **自然度失败原因已限定核实**：identity-only44330实际108d7d EXIT0，[SAFE052e5a44](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/token400-paired-naturalness-first-failure-structural-diagnosis-v1/SAFE-identity-counts.json)显示六槽每槽96行都使用已登记的内部alias；window越界／重复均0，固定96集合完全一致。失败来自内部终评名与公共比较名的命名层差异。原13e显式做两层映射，新SOURCE successor将先严格核验run／seal身份再映射，原评分算法和分母不变；尚未授权重跑，paired naturalness继续NULL。
- **配对自然度真实失败**：90385实际386b2a EXIT1，SAFE为ValueError／native0／auth0；原trace86f7d360保留。限定SOURCE栈为run_once228→project201→project_rows161，谓词是alias不等、window越界或重复三者之一；具体分支待数值身份计数核对。失败在whitelist保存和统计compute之前，不发布自然度、不自动重试，原语义数字不受影响。
- **实际启动补记**：fresh C0生成11028（初始a9f07a，外部LIVE handle eb8a18ee）为唯一local GPU生成，F2 MAIN45468为唯一native评价。ROOT配对自然度权限3c325a26绑定原22441比较工具及六个final字节，限定quiet只读窗口；数字投影90385（初始e19d0b）已启动，实际成功及数值尚未知。不把LIVE／权限写为完成，不将新控制成本计入旧控制。
- **10月9日约03:09 UTC接跑**：[v15报告](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/current-screening-evidence-matrix-v15/summary.zh.md)已冻结（948ab655），保留v14并追加token400与F4的A／B／combined三个视图。token400完整96代表剧集complete-case Δ+0.361111（35／36），family9区间[−0.064815,+0.833333]；固定36窗缺失界[+0.351852,+0.388889]另列。电影+0.018519且区间跨零，B半组风险剧集−0.333333且三seed均负。仍值得继续验证，但未证明稳定收益或电影非劣。
- F4完整96数字57e5aacf：代表电影Δ−0.157407，family9区间[−0.222222,−0.074074]，三seed及逐作品剔除均负；B风险剧集−0.611111。当前配方不支持进入确认，不能据此淘汰全部非JSON组织方向。token400／F4的paired naturalness、候选完整严重风险门仍NULL，pipeline等价false；历史C0与当前版本成本不用于正式性能结论。
- F2 activation88351对应实际MAIN45468仍LIVE，外部handle3cc14f51仅证明运行中，phase／完成数未知。F8 post-side once门禁已修复并独立复核1519fb19；ROOT prepare权限f0075bd6等待F2真实终态后执行，尚无probe／native权限。ctx8 draft collector7868d9 EXIT0，frame e276f210／unsigned grant31177338准备144槽，D0及native权限仍NULL。
- ROOT34d3e8签署[单次fresh C0生成权限](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/ROOT-fresh-C0-full96-generation-once-v1.json)8f3d1de3：固定三个seed、原C0配方、当前wrapper，保留历史控制身份，禁止重复直到胜出。目的为解决版本可比性；token400尚有待验证信号，不是确认候选锁定。原fresh GPU前后观察保留，其他GPU生成暂停；可与远程native评价并行，耗时仅描述性、非正式独占性能。生成实际终态未知，机械认证、材料及MAIN均未授权，后续fresh baseline intake仍需完成。
- **ctx8材料实际完成**：46019实际8adbdb EXIT0，[SAFE3873e8ba](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/F2-ctx8-typed-material-only-source-v1/actual-material-once-v1/SAFE-completion.json)及[tool9506e302](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/custodian-recent-actual-tool-evidence-v1/F2-ctx8-material-actual-tool-46019-v1.json)确认typed group verify1、prepare3、固定144、replay／new generation／native均0；新opaque proof cc3c8b7e。旧idx6 normal61拒绝、旧48 UNKNOWN／720及ctx8 exclusion144台账保持，新材料成功不倒改历史。token400比较22441（初始61ca6f）已实际启动，质量终态待回收。
- F8后续ROOT SOURCE的独立审查发现once门禁问题：原kernel幂等写不保证重复release只执行一次。当前尚无真实调用，producer正在增加局部独占claim并保留失败回归，原kernel／评分算法不变；完成修复与独立复核之前不激活该入口。
- **10月9日追加终态**：B10 canonical Stage B 88284实际8ecc02 EXIT0，[外部工具96bbced1](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/custodian-recent-actual-tool-evidence-v1/B10-canonical-stage-B-actual-tool-88284-v1.json)、outer SAFE84f20c17及[inner SAFE833b9ee0](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/B10-full96-risk-formal-material-two-stage-preparation-v1/actual-stage-B-once-v1/SAFE-result.json)确认34jobs／288槽、transport prepare1、build packet0、native0，原成本每份一次。run-plan ce01bdd6仍native inactive；历史失败保留，C0 fresh性能NULL。ctx8材料46019已启动，结果待回收。
- ROOT6f0ce2签署[F2 exact-six native activation88351f6e](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/ROOT-F2-six-after-F8-5008-v1/ROOT-exact-six-activation.json)，两组grant770b65b9／e660f8f2；最新F8 genuine D0 13da已独立核验且once未消费。仅在当前材料与token400／F4比较终态、没有中间native并确认原D0仍为直接前序后，可按原0/1/3/5/7/8顺序执行；当前尚未启动，不把权限当完成。
- [剩余假设审计](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/remaining-hypothesis-audit-v1/conciseChinese.md)1a7dd460／freeze a452778c保留条件式决策：先消费已有完整集、common/origin、F2、rolling和F8开发证据，再判断B15、非对称上下文或fresh C0的新增价值；不默认同时跑，也不将未测区域视为饱和。F7 style／scene不等于真正语义组织，旧命名不能替代计划中的该项筛选。
- **10月9日约02:49 UTC接跑**：B10新observer3b0b76实际EXIT0，cc692269确认无相关writer；ROOT063422按原f36登记逐字复制prerequisite pointers，签署canonical Stage B authority ef372feb／window9fb8e151／release45b93916。实际88284已启动，终态待回收；旧726c13不删除、不改判。F4新比较入口经独立0bd74324通过，ROOT00e5f0签署四项权限（Source fbd592dc、quality2563e3ef、observerfe479b2f、comparison3c2aeb7d），实际比较仍待B10／ctx8／token400之后。
- fresh C0生成SOURCE4104b70c经独立70c8ad34限定通过，超五秒drain会在启动前STOP；真实生成仍未授权。SOURCE审计确认原统计只保留自然度均值／计数，未保留逐seed自然度配对；因此既有paired自然度NULL不能用描述均值冒充补齐。新的token400完整集窄数值路径开始实现，实际输出与权限均NULL。严重错误门槛仍须独立同scope核验，不由新数值路径或旧matched风险结果替代。
- **10月9日约02:43 UTC接跑**：F8 continuation5008实际c800ef EXIT0，[外部工具31cdf772](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/custodian-recent-actual-tool-evidence-v1/F8-continuation-actual-tool-5008-v1.json)及[SAFE0f11289f](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/F8-dev90-canonical-finalize-artifact-continuation-source-v1/future-actual-continuation-native-v1/SAFE-result-v1.json)确认剩余8阶段全部成功：R08=60、A08=9、P09/R09=60/60、A09=12、P10/R10=60/60、A10=10；已消费P08=60未重放。三份side seal合计180，对应开发90对；最后genuine D0为13da1c15。专项ROOT evidence／hypothesis review、触发器冻结与held54评估尚未执行，不能把side完成视为一致性结论或收敛。
- F4结构2002实际EXIT0，[SAFEe9bdf994](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/F4-full96-diagnostic-runtime-source-bridge-preparation-v1/actual-structure-once-v1/SAFE-qualified-structure-v1.json)六组均96窗／480 scored IDs／34场景／4297 cues，三项结构谓词相等。这不认证source text/time、完整pipeline或质量；新的诊断comparison SOURCE94c077／8e5cda已实现，等待独立收据与新ROOT权限。
- ctx8 native SOURCE独立1e643b95通过，实际typed材料仍待执行。token400 numeric SOURCE92324／433c经独立45ec66ae限定通过，实际比较及数值导出均未发生。origin native d7da02／270 join f6f5a6已实现，readiness f9ad3e5d；当前7项native／23项join和独立检查通过，真实native与join登记仍NULL。fresh C0同版本对照已形成三个SOURCE草案，但尚未授权生成，原normal61的promotion与21份source声明不适用新control，不能借旧检查冒充新对照认证。
- **10月9日补充接跑**：F4 metadata55983实际EXIT0，外部工具d4f0f991、[SAFE b369d747](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/F4-full96-post-main-comparison-source-preparation-v1/retained-metadata-once-v1/SAFE-projection.json)。六组仅runtime wrapper Source稳定字段不同（4fd571→32a16；66066→23939），三个候选声明card均等于实际执行card；这不是源码／流程／计时等价认证，质量仍NULL。结构投影bb8c／63f6已ROOT审核，尚待实际终态。
- token400完整96 diagnostic entry8ab6／seame59a经独立dce3限定通过；ROOT35298a签署[一次比较权限61696642](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/ROOT-token400-full96-diagnostic-comparison-v1/ROOT-comparison-permission.json)、Source d614／quality0478／observer6d79。实际compare仍0；保留原879／13e／f808及六目录原始认证，runtime只作诊断class再恢复原身份，native480不等同qualified480。原classifier拒绝任何native CLI，因此排在真实F8终态、B10材料和ctx8材料之后、F2 native之前；不借签署推断实际成功。
- ctx8后续native入口af28已SOURCE实现，12项合成测试通过且独立审查中；实际材料、库存、D0及native grant仍NULL。它使用新typed材料和原7091 phase/core/guard，不把恢复seed强制视为旧normal61。原48 UNKNOWN和720台账不变。正在做同版本fresh C0的SOURCE可行性审计，以判断是否需要另跑真实对照；尚未授权生成，不替换历史C0或当前基线。

- **10月9日约02:15 UTC／10:15本地接跑**：B10 Stage B实际失败的[SAFE predicate e907df3f](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/B10-stage-B-retained-preclaim-predicate-diagnosis-v1/SAFE-predicate-diagnosis.json)已确认line50：registration schema／owner／state、Stage A manifest和34个job envelope hashes均匹配；只有fresh_packet_custody及probe_eligibility_review两条raw path斜杠拼写不同，SHA相等且resolve后同路径，另外两条prerequisite完全相等。inner claim、transport output、原ROOT lock均未到达，transport prepare0、auth／replay／native0。这是ROOT路径装配错误，不是翻译或模型失败；原726c13、36b2与私有上下文保留，新canonical外层／observer SOURCE准备中，没有自动重试。
- ctx8 SOURCE2bd200／a4a682冻结，42项synthetic及compile2通过，独立[91b46992限定审查](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/F2-ctx8-typed-material-independent-review-v1/review-receipt.json)通过。ROOT0782b4签署[typed登记4b3c4dc7](../../.local/translation-evaluation/hy30-flow-v2-20261008/cards/F2-ctx8-explicit-cost-typed-ROOT-registration-v1.json)、public enrollment5b4a37a9及material authorityc2ea05f0；actual typed认证／材料仍0。排队条件是F8实际终态、B10保留slot之后再材料接入、F2 native之前；源码和签署不表示执行已经完成，原48 UNKNOWN与完整720槽框架保持。F8最近5008仍LIVE，未获得新终态或质量权限。
- **10月9日约02:09 UTC／10:09本地接跑**：F4 MAIN9984实际EXIT0（chunk53edce），[SAFE9c0b1cd0](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/F4-full96-native-main-once-preparation-v1/retained-native-once-v1/SAFE-completion.json)及[外部工具fab8e6d3](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/custodian-recent-actual-tool-evidence-v1/F4-native-actual-tool-9984-v1.json)确认三seed sealed：每seed PRIMARY96／REVIEW96、ADJ分别21／25／34全部accepted，failed／pending均0、固定288。quality_exported=false、材料准备与mechanical replay重复调用均0；最终真实D0d02faaa2保留。这里只报告MAIN完成，不读取grade／统计或给出质量晋级。
- B10 Stage B observer3c5efb实际EXIT0（bee10），ROOT5069e8权限下原thin3ea305实际726c13 EXIT1；[SAFE36b2c049](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/B10-full96-risk-two-stage-thin-observation-preparation-v1/actual-stage-B-retained-once-v1/SAFE-result.json)及[tool093f67c1](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/custodian-recent-actual-tool-evidence-v1/B10-stage-B-actual-tool-726c13-v1.json)记录首次失败STOP、无outer retry、native0。Stage A已冻结的34job／288槽不改；完整私有上下文由custody保留，canonical-path仅为待核实假设，原因尚未确认，不把失败写成质量失败或自动重跑。
- F8 ROOT signer145c08曾因mixed-path metadata pointer在predispatch失败，原件保留。canonical外部四pointer的v2修正后3b77c7签署成功，新launch263498d2ee38a4aa960c9b1aae9c03288f92bcc8590afc0408fa153f74ea1223下实际session5008（chunk643c14）仍LIVE，ROOT在10秒边界确认它是当前唯一native。这不是已完成三seed、质量发布或held54解封；原PRIMARY08消费史与35079 REVIEW失败保持，origin／ctx8的实现ACTIVE也不当作actual完成。
- **10月9日约02:02 UTC／10:02本地接跑**：token400结构metadata64476实际EXIT0，工具[a3461b55](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/custodian-recent-actual-tool-evidence-v1/token400-structure-v2-actual-tool-64476-v1.json)绑定[SAFE3f36f277](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/token400-full96-qualified-window-structure-preparation-v2/actual-once-v1/SAFE-qualified-structure-v1.json)。六组各qualified96窗／480 scored IDs、34场景／4297全源cue的expected逐窗身份、allowed-source coverage及native全目标覆盖metadata均一致；原native packing scored480没有与qualified480混同。state为structural_metadata_equal_not_authenticated：未完整重扫inventory，source text／time／reference provenance未认证、pipeline／timing等价未证明，auth／replay／compare／host／native均0。原78139 category literal失败、六组native480集合差异及后续captured-source边界保留，本次只是原closed category规范后的诊断检查，不是质量或晋级权限。
- F4 MAIN9984按ROOT最新通报仍LIVE，前两seed各genuine sealed96，第三seed终态未知；没有据前两组成功推出三seed完成、质量差值或serious gate。origin native实现ACTIVE但尚未完成；ctx8 explicit controls typed registration实现ACTIVE但尚未完成，原拒绝与48 UNKNOWN不因正在实现的SOURCE改变。B10 Stage B尚未实际执行，post-F4时段已为其保留；无新观察、解封或promotion。
- **10月9日约01:49 UTC／09:49本地接跑**：finite46045实际EXIT0，[compare SAFEe24c8652](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/finite-B60-diagnostic-card-path-compatibility-source-successor-v2/actual-diagnostic-statistics-once-v1/SAFE-result.json)固定每臂144槽、只调用一次原13e比较；数字exportcc08b3实际EXIT0，[released numeric30d12a9f](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/finite-B60-diagnostic-numeric-SAFE-export-v1/numeric-summary-SAFE-v1.json)在ROOT e3b413权限下发布。原3510 relative-code失败及旧模板身份blocker均保留，新SOURCE只支持限定诊断，不倒推旧失败为质量结果。
- [v14报告e837cfe0](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/current-screening-evidence-matrix-v14/summary.zh.md)已冻结，receipta0989dda／freeze3c219e22；累计22条quality／6条risk／3条资格，v13全部结果逐项保留。finite独立于原B60：C0与finite均144／144 known，代表动漫Δ+0.333333、family9 simultaneous CI[−0.092593,+0.814815]；代表电影Δ−0.295833，三seed−0.4／−0.2375／−0.25且全部work／series LOO负。work95% CI[−0.458333,−0.104167]与series／simultaneous[−0.5,约0]不可混选；risk层可翻号，不抵扣电影弱项。pipeline／source-frame／grammar-only causal均false，paired naturalness／candidate serious gate／same-scope fullflow ratio均NULL；六个原generation成本各计一次，没有正式优势、收敛或新扩展权限。
- origin95594实际EXIT0，[SAFEc742be96](../../.local/translation-evaluation/hy30-flow-v2-20261008/evaluation-only/F1-origin-ten-window-material-v1/SAFE-material-terminal.json)及外部工具5eee23fe：complete材料260条，另10条缺完整admitted proof独立保留，固定270槽；known quality0。恰好26次原proof verify、机械replay0、public prepare1、native／judge0。材料准备不把原失败卡或10 UNKNOWN变为交付零，也没有实际裁判或质量结论。
- F4 MAIN9984最近ROOT工具62b231／01:45:38 UTC仍LIVE；custody确认seed08 genuine sealed96，09／10终态尚未知。B10 Stage B prerequisite ROOT744286已签署，B observer request仍inactive，等待F4真实D0并按ROOT排序先于F8；没有根据签署或seed08成功推定Stage B、F4三seed、F8 continuation已开始。F8、F2、F6 native SOURCE限定通过均未激活，ctx8 typed registration仅恢复准备、未实际接入。
- token400 full96实际78139在metadata predicate失败，原失败／once记录保留。实际49555的[SAFE四合取3d2925ed](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/token400-qualified-structure-first-failure-source-diagnosis-v1/SAFE-four-conjunct-comparison-v1.json)确认六组scene_id／work／scored_ids各96窗均一致，每组仅category48窗不同；实际39243的[SAFE category8a13b304](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/token400-qualified-structure-first-failure-source-diagnosis-v1/SAFE-canonical-category-pairs-v2.json)确认原closed映射animation_movie→movie，六组canonical equality均true。SOURCE successor准备中，尚未实际重跑/auth/比较；此category规范差异不消除既有native480集合不同或captured-code审计边界，不据此宣称整体等价。
- **10月9日约01:27 UTC／09:27本地接跑**：F3三split数字export936f90实际EXIT0，ROOT a107释放[SAFE610eae5a](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/F3-full96-three-split-diagnostic-numeric-SAFE-export-v1/numeric-summary-SAFE-v1.json)。A／B每臂各144槽、combined每臂288槽，六个原成本在split外各计一次。原8d1dd3失败保留，原67126比较成功未被推翻，也没有新bootstrap、grade认证或native调用。
- [证据矩阵v13报告5a5ff664](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/current-screening-evidence-matrix-v13/summary.zh.md)已释放，receipt23cfd754、freezeaafd1b3a；累计21条quality／6条risk／3条资格，原v12全部F6／F7／F9数值与正文保留。F3 combined代表动漫完整窗Δ+0.105556，work／series95% CI[−0.009259,+0.261111]，family9 simultaneous CI[−0.027778,+0.338889]；完整三seed窗35／36，固定36窗缺失界[+0.111111,+0.148148]。后者保留已知部分与缺失差值界，不能当作同一estimand的CI或用于“修正”点估计。代表电影Δ−0.018519、CI[−0.037037,0]且LOO全负；B-risk动漫Δ−0.388889、三seed及LOO全负，不能事后只取A改善或把A/B均值拼成combined。
- F3本报告只是限定诊断：pipeline_equivalence=false、source_frame_equivalence=false，paired naturalness、same-scope fullflow time ratio及full96 serious gate均NULL。原matched48新增MAJOR3、恶化MAJOR1与UNKNOWN39仍属原scope的阻断，既不被撤销也不冒充full96 gate。当前结果未证明优势、机制或晋级资格，不淘汰整个F3方向、不改变C0基线。
- F8 continuation SOURCE9477已限定通过，ROOT[resume登记5378c5bf](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/ROOT-F8-consumed-primary08-resume-registration-v1.json)只绑定已消费PRIMARY08及剩余阶段，native_dispatch_authorized=false；实际future activation仍NULL，须等待F4真实终态及新D0。F2 SOURCEbe63限定通过，latest activation同样future NULL。F4 MAIN9984按custody最新通报仍LIVE，本条未查询active tool、payload或host，不能推定phase／三seed完成。
- finite SOURCE repair v2采用最终一致的bridge f924与once24a，[ROOT signer readiness861b7588](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/ROOT-finite-B60-exact14-successor-signing-preparation-v2/readiness.json)是SOURCE草稿，signing／auth／compare／host／native均0。旧df11 stale模板blocker与原3510失败完整保留；未来执行仍须actual current checkpoint及fresh CIM，不据源码修复重试或宣称统计完成。
- token400 full96 actual37127的[SAFE membership extension008d9d1a](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/token400-full96-six-metadata-membership-extension-v1/actual-once-v1/SAFE-membership-extension-v1.json)仅是metadata projection：六组qualified96 window集合一致，baseline／candidate native480 scored-ID集合不同。原顺序、各自membership及captured代码差异均保留；captured-source审计待完成，不能由qualified集合一致推定原native frame、pipeline或字节等价，也未据此授权比较。
- **10月9日约01:16 UTC／09:16本地接跑**：B10 Stage A62248实际EXIT0，内层[SAFE d96a0036](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/B10-full96-risk-formal-material-two-stage-preparation-v1/actual-stage-A-once-v1/SAFE-result.json)、外层SAFE3f17d174及外部工具2e3a696a相互绑定。34个scene job、固定288槽材料已冻结，state为等待ROOT custody；transport prepare与native均0。Stage A完成不表示Stage B、正式风险评价或质量完成。
- F4 full96 MAIN9984最近ROOT工具chunk678395仍LIVE，在activation0d39ea19下于B10锁释放后启动；ROOT通报它是唯一native。沿用已准备材料和原88b74执行路径，不重复材料准备或原61机械检查；本条没有观察active payload，也没有把live状态写成终态或三seed成功。
- origin32816实际EXIT0，内层[SAFE07b9eba4](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/F1-origin-complete-original65-once-preparation-v1/actual-original65-once-v1/SAFE-terminal.json)、外层4cd2613b及工具18e1490c：恰好26次原public admit_trial返回，立即verify_envelope调用0、native／judge调用0，材料与质量权限仍false。等待独立ROOT外部proof登记；原失败卡和固定UNKNOWN不由认证成功消除。
- F3数字export8d1dd3实际EXIT1，SAFE91460493及原失败记录保留。限定[SAFE形状722557e1](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/F3-full96-numeric-first-failure-source-diagnosis-v1/SAFE-statistics-shape-v1.json)确认原统计包含screen-a、screen-b、screening-combined三个canonical split，旧exporter只接受single-A结构；失败发生于closed numeric projection。原67126比较成功仍有效，SOURCE successor准备中，未重跑或数字发布，也不把export接入失败视为质量失败。
- finite原3510的relative-code失败史保留。[新签署准备df11a2f5](../../.local/translation-evaluation/hy30-flow-v2-20261008/summaries/ROOT-finite-B60-exact14-successor-signing-preparation-v1/readiness.json)又发现冻结模板仍指向bridge028d／oncebebc，而最终SOURCE为bridgef924／oncec64a；闭集模板相等与实际代码身份不能同时满足。新SOURCE后继必须统一精确身份，不能改冻结模板或沿用未消费的签署权限；尚未实际认证、比较或重试。
- **10月9日约00:56 UTC／08:56本地接跑**：F4材料56714实际EXIT0（edb9e4），SAFE0de1a3、外部工具8645；F2 exact6材料6644实际EXIT0（778efd），SAFE0c203313、外部工具0a83。F2已准备576／总720槽，只是材料接入，不是评价或质量发布；ctx8原typed intake false及48 UNKNOWN不因其他材料成功而改变。
- 数字export a7d1e4实际EXIT0，SAFE4633040，使用SOURCE b22及ROOT release66cb。证据矩阵v12已冻结：summary1c61／metrics4879／freezebaec。F6代表窗动漫Δ+0.074074、CI[−0.074074,+0.259259]，电影−0.041667、CI[−0.25,+0.141667]；风险动漫−0.055556、电影−0.041667，未证明稳定优势。F7仅seed08有48／144槽交付，另96 NOT_RUN；三seed点估计与paired naturalness均为NULL，不将缺失当零或声称方向胜出。
- F3 ROOT observer90303实际EXIT0（74e7e5），证据34701a：六目录字节集合相等、七次CIM clear。ROOT once权限9ad95后67126实际EXIT0（784a87），SAFE2678、私有结果90b4；尚未进行数字export，不根据私有结果或退出码发布比较结论。此前63691失败仍保留，新的成功不倒推旧NULL命令行进程的原因。
- finite observer64843实际EXIT0（9371e4），观察fae972通过；ROOT c229权限下3510实际EXIT1（934442），SAFEe4e。允许的限定原因是原13e relative-code检查拒绝14条local implementation路径，发生在grade读取之前；不是质量失败，也不是已完成统计。另版SOURCE修复准备中，原失败和once记录保留，尚未重跑。
- origin metadata constructor3c099b实际EXIT0，proposal85eb；ROOT observer99889实际EXIT0（beb462），SAFE4f9dd。proof末次00:55:55 UTC，26目录两遍字节相等、两次相关writer检查clear。ROOT admit release3a896已签署并交custody；当前实际admit会话状态未知，尚未收到启动或认证回执。
- F8在activationcfc22／launchc64eb下实际run35079（d123b3），随后EXIT1（bc67d3），停在seed08 REVIEW的ValueError。PRIMARY08成功60，未完成任何seed；held54仍封存、featuresfalse。PRIMARY的D0c689保留，私有causef5cfe由custody限定诊断，ROOT未读取正文；不把PRIMARY成功当作review或三seed质量完成，也不自动重试。
- **10月9日约00:30 UTC／08:30本地接跑**：token400 native95957实际DONE／EXIT0（7122fd），SAFE10c6aeca，最终D0 `84cad`，外部工具证据094743b5；MAIN固定288已完成，质量统计尚未发布，不据成功退出推断收益或晋级。
- ctx8旧observer v1 afcb观察窗口已过期且未消费，原件保留。fresh v2 cef29c实际两遍各5368文件一致，末次00:24:33 UTC相关CIM clear；ROOT7a3a权限下原once523d实际22834 EXIT0（d90c09），SAFE4c6e5059、外部工具f036e903、replay receipt88613／envelope66448。新机械认证不覆盖原拒绝史，不改原48 UNKNOWN，typed intake仍false，也未授权质量评价。
- F4 full96材料once56714在ROOT6de5权限下仍LIVE；F2 exact6材料串行权限4f08只允许在F4成功后接续，尚未开始。这里没有把正在运行的过程记为终态，也不借seed间空隙探锁或抢占EVALROOT scheduler lock。
- F3 fresh observer63691实际EXIT1（fed031），SAFEb951；final writer check记录两条命令行NULL的Python PID2524／31100，无明确target指向。后续两进程消失仅与瞬态相容，尚不能证明根因，原因仍UNKNOWN。新retained SOURCE准备不等于实际观察或比较；原失败证据保留，不缩窄writer判据。
- 数字export V2 b22／a293经独立b3a00 SOURCE审查通过，尚未实际export；不将先前合成白名单缺陷写成真实字幕泄漏。B10两阶段 SOURCE b1d719／1bb45经独立1028通过，尚未实际观察、认证或join，未来fresh custody与原失败历史仍须精确绑定。
- **10月9日00:10 UTC／08:10本地接跑**：origin17 GPU94347实际EXIT0（373e4f），ROOT原始工具包4a3fe380、SAFE c259179b、journal6fb7ab13；17项均complete，最后00:01:00 UTC。whole entry4460.535秒只计一次，不加总为每seed成本。与原36队列合计26个origin complete卡待原65机械检查；原idx18失败仍保留10个诊断UNKNOWN，不因后续成功清零。native交付23窗／115ID与诊断10窗／50ID严格分开。
- F4 metadata constructor92097实际EXIT0（9d2adb），重新核对原三组文件集合；ROOT独立登记terminal db55ffcf／material cda6a91d／ExternalPins21457508，证据a1919861。模板构造1f2725完成，once76325e4d已完整审阅但authority尚未签署。token879在每个`process_single_entry`全程持有EVALROOT scheduler lock，故明确等待95957整体终态后再材料准备，不探锁、不抢seed间空隙。
- F2显式成本binding successor7091fa0b／once6c85bb25经独立869e21f7通过，ROOT签新cards登记edea7e5e（856b0f），证据73e17fd3。原4440九项generation／机械／成本逐项完全不变，只新增匹配控制成本登记；full96原核验不放宽。576材料once仍待真实95957终态／D0和单独permission，尚未重跑。
- F3新observer452f00b6保留失败分类，原writer判据不变；新once0a7c695e绑定664a80f8历史与新观察身份，ROOT已读完整diff，尚未实际观察或比较。ctx8 once523d497b补充完整私有cause/context，ROOT已读，仍未授权实际机械检查。F8新retained launcher3951c0e补充pre/postclaim私有errno／filename／异常图，原phase与guard流程不变，待空闲及单独新权限。
- 原六组数字exporter5bd5ae3e尚未执行；独立5786ddd6发现通用投影对成本pointer字典未限制额外键，正在新版本窄修。真实入口固定使用已释放SAFE成本fcdbd793，**未证明实际e77数据泄漏**。不得把合成白名单缺陷写成实际字幕泄漏。
- token40095957仍是唯一native，前两seed有finalization文件，第三seed review推进；文件计数不当作终端认证或质量结果。下一空闲窗口优先F3／ctx8观察及F4／F2材料，再分配F8。B10正式风险材料的fresh custody须先有真实bundle hashes，已改为准备两个独立阶段，不能伪造成功probe或自造no-call证明。
- 23:50 UTC补充：原六组统计60854实际EXIT0（554192），SAFE133a7e26、私有统计e77a5f55，固定288／MAIN NOT_RUN96；尚待只含数字的SAFE报告发布，不能据成功退出宣称质量收益。证据矩阵v11已冻结于`summaries/current-screening-evidence-matrix-v11/`（matrix ad7a0cc3），追加F9风险并完整保留v10证据；下一数值点只条件准备target15，先消费pending full96／common／origin／F2证据，不预定胜出或机械铺网格。
- F2根因进一步核实：三个matched48 C0控制卡binding均缺`original_run`字段，而认证artifact包含原始成本pointer，原9bb line237因此把pointer与NULL比较失败；full96三组和其余匹配合取均通过。缺顶层window IDs假设被实测否定，尚无pointer路径或hash漂移证据。修复须明确补齐受认证的成本归属，保留冻结卡与失败史，不能跳过成本核验。
- finite-B60 runtime SOURCE独立0ba4b933限定通过：只支持精确六组manager／engine诊断比较，保留geometry、finite grammar、额外验收／STOP及clock处理差异，不声称grammar单因果或pipeline／计时等价，实际统计未执行。F8独立38ebfcbe通过7项与owner重叠的真实Windows锁回归，未新增实际调用；等待token400终态后再单独分配native。
- ctx8恢复检查once851497的独立8679e824发现suppressed context会被`traceback.format_exc()`遗漏；尚未实际执行，先在新SOURCE版本修复完整私有cause记录，旧版本保留。该诊断缺陷不构成模型或译文失败。
- 23:45 UTC接跑：**尚未收敛，确认48仍封存，未替换基线。** F9 collector8024实际EXIT0（135681），SAFE6409ef80／final13b627b8；ROOT签de049e0a后语义汇总197f40实际EXIT0，SAFE cd8ab569／中文报告f29931a6／final1762ebbf。固定144配对中27缺prior、10 unresolved，并集37 UNKNOWN；新增MAJOR9个scene-local组、8个原文窗口、13个窗口seed配对，新增CRITICAL及恶化severe均0。107个未报告UNKNOWN不表示无错；improved18组不抵扣新增严重错误，当前F9配方不能晋级，不淘汰整个方向。
- F4 canonical wrapper8a23be07在ROOT实际观察71760 EXIT0（51e6f6，evidencec7752545）及新权限aa2a6b38后，65395实际EXIT0（3eecde），原61机械调用恰好三次成功。SAFE52d6932c、外部工具ba2f8c45；仍待外部终端登记及材料评价，不把机械通过当作质量通过。先前Windows路径字符串失败8bda7c完整保留。
- token400路径修复71ebb3ef／once c58e4fd0经独立a5aeebdc审查通过，新增反例证明同bytes错误EXE路径仍被闭集拒绝；ROOT签bf6c300a activation及cd00089e successor permission（cc151b），绑定真实71a09008 D0。custodian唯一native session95957（8cae7a）运行中，固定288，原三组115文件材料不重建；旧562a14失败与claim保留。
- 原六组observer V2只移除与历史Windows Path排序不兼容的额外POSIX排序断言，唯一文件与全部bytes检查保持。ROOT87402实际EXIT0（243d57），inventorye1ad3612／observationdfd9d05e／evidencea556edc1，两遍九目录一致且末次23:43:10 UTC无target writer。新统计权限9e90e8af和双失败history70bf8b46已签，交原3b256cc0 once执行；scene09／10固定96 NOT_RUN继续保留UNKNOWN。
- F3统计observer80990实际EXIT1（4f5394）：第一次byte pass之后的真实writer检查拒绝，发生在token400 native运行期间；尚无外部观察结果、SOURCE授权或比较调用。不缩窄writer判据、不自动重试，先核对其保守范围并等待适当接跑条件。
- origin17 GPU94347最近实际poll871956仍live。F8真实Windows锁回归已重现原inventory读取自身scheduler lock的PermissionError；最小SOURCE successor与独立审查准备中，原实际trace未记录文件名的不确定性保留。F2 exact6首control08所有合取均通过，原top-level window_ids缺失假设对此不成立，继续核对09／10；未重试材料。
- F9只读68075实际EXIT0（0045a6），proof e6e5b02c／兼容观察0b9c1040；ROOT核对三次target CIM clear及十目录两遍字节一致，末次23:25:05 UTC。ROOT签一次CPU collector权限4e641aec（2afb13），custodian实际8024（f13378）运行中；尚未语义报告。工具摘要1cb8fe6a与实际ADJ328文件登记保留。
- ctx8新recovery helper3e4f0632／typed adapterb6f64593 SOURCE已完成；30项owner离线测试包含完整734批735尝试的合成genuine worker replay，独立531260b3另跑1新增＋1重叠检查。ROOT已读diff／接口与审查结论，实际原证据replay尚未发生；原61拒绝／48UNKNOWN保留，未来seed10单次检查入口准备中，不授权材料或裁判。
- F4／token失败纯predicate SAFE fa9a23dc确认Windows lexical path ABI：真实SHA和resolve后的路径均一致，但外部F4 argv的D:/与内部token EXE的C:/未规范化，原bound整dict比较拒绝；F4原claim不存在／纯verify_release通过，token早于CLI／guard。分别准备保留旧失败的最小路径规范化薄层／源码后继，不改原checker／质量规则。
- 原六组新只读observer1f34实际6110ca EXIT1，在任何CIM／目标字节观察前validate_inventory拒绝原8c709清单的排序；旧清单使用Windows Path排序，新断言误用relative POSIX string排序。独立修正只移除此不相容冗余排序条件，原精确集合／逐文件hash／两遍一致门槛保持，实际comparison尚未发生。
- F9 terminal observer88bb8784已ROOT完整读；ROOT字节登记实际ADJ328文件d9ee0ba4（含seal与lock），新request820de57a经e92a08生成，实际ROOT68075（88530e）正在观察原195／P408／R413／ADJ328及六input目录。此时仍未调用collector或语义报告。
- F4原三目录只读观察68623实际EXIT0（e26eb2），两遍各6352文件完全一致，23:19:20／23:19:39 UTC target CIM clear；evidence0775fdda／proposal3b9c012a由ROOT核对，构造器73d3f5签c070fb7e。紧接原61 once入口实际EXIT1（8bda7c）仅暴露ValueError，尚未确认是否进入claim／replay；已授权纯metadata／SOURCE predicate定位，禁止重试checker。外部ROOT工具摘要a667de74保留，记录生成时的PowerShell布尔字面错误已纠正，不影响实际观察。
- token400失败进一步定位在bound(EXE)/bound(TERMINAL)且早于CLI版本调用、controller及guard；正核对Windows斜杠拼写与完整pointer相等比较这一实现问题，不推断实际质量失败。F8准确锁路径关联及真实Windows synthetic回归继续。所有新失败仍是接入状态，探索未收敛、基线不变。
- token400完整96 MAIN首次薄层实际EXIT1（562a14），SAFE0571bd31为original_dispatch_once／ValueError，完整cause/context已存，未自动重试；是否触及native须以限定机械诊断确认。F8失败SOURCE定位到持有target run_lock时_inventory先hash后排除scheduler lock，真实Windows锁回归与精确排除修复准备中；不吞掉一般PermissionError。F2失败定位原_verify_controls的source/reference/seed/cost合取，限定标量及pointer差异核对已授权。
- 原六组resolver独立8dfbba37和F4 adapter V2独立7f761802已ROOT核对；前者1项新增反例通过，后者仅重跑owner两项针对回归、不得计新增独立测试。F9 collector/report独立f83cb67b限定PASS：9项测试中6复用、3新增，21attempt不等于21accepted，固定144／prior27保留；实际collector及语义报告仍待观察与签署。
- F8首次dev90 native实际即刻EXIT1（687c08），seed08／primary PermissionError，phases与completed均空；不能只凭stage推断是否已dispatch。完整私有58302de2保留，限定frame诊断已授权，无自动重试。真实guard新D0 71a09008于23:14:02 UTC drained／零callback与job，ROOT已读。随后ROOT签token400完整96 MAIN权限62bde737、原group launch c6b78411（ffcd91），交custodian以已审查fce4薄层一次执行，固定288与质量未发布边界不变。
- F3独立审查a8106ab3已ROOT读，2项新增合成检查通过、无SOURCE阻断；仅允许准备新的诊断统计签署链，实际比较仍未执行，整体pipeline／frame／计时等价未证明。
- F2 exact6实际52001 EXIT1（2e2667）：首index0的原public prepare_entry抛ValueError，完成prefix为空，后五组未调用；私有完整诊断c6c210c7与原claim保留，不自动重试。已限定授权frame／源码predicate诊断；不据此判断译文质量。F8在真实52001终态后由ROOT签59484388（d339c1），绑定原F9 D0 5b533及九个dev-only phase admission，交custodian执行唯一native；held54／custom-stage／quality仍未放行。
- 原六组relative-sidecar修正1f75ca8f／消费入口fa3ca723仅按四组实际prepared plan解析并逐项验证hash，ROOT已读完整diff和限定元数据76253c34，projection独立审查继续。F9终端collector c9b75a21／once720dbe0b与报告f37e53fe已ROOT读完整diff，独立审查中；实际UNKNOWN与严重错误计数仍待真实汇总，不能把21调用成功当作全部accepted。
- 23:10 UTC后续核对：B10 v5 once70042实际EXIT0（595827），外部工具记录0d3aff23、材料manifest235568e8；37文件、固定288风险槽仍UNKNOWN，未新增native／judge，尚无严重错结论。旧三次join失败和观察失败保留。
- F2 exact6入口8f4da6cb经ROOT完整审阅，plan140aba20／六项合成检查就绪；独立ROOT材料权限e0494317绑定原登记4440f524及F9真实39377 EXIT0／D0 5b5331db，已交custodian执行once。仅初始ctx0／3六组576材料；固定720和ctx8原拒绝／48UNKNOWN保留，未授权native。
- F3 captured SOURCE选中分支审计a113006b未发现已证明的active C0请求／解码漂移；不能只因hash不同就认定混杂或追加昂贵C0。frame、历史cost与未投影prepare路径限制保留，全pipeline等价仍未证明。独立审查继续；新C0 full96 proposal仅条件准备，不执行、不替换基线。
- finite-B60统计准备86261799冻结，runtime32a／286源码与精确六组命令标量审计继续；尚无统计结果。F4原61三组入口2ff7b643准备完成，ROOT已完整读、独立审查与外部byte/writer observer准备中，未实际认证。origin17 GPU94347最近实际poll仍live；F8待F2材料真实终态再接唯一native。探索尚未收敛。
- 22:59 UTC：F9仲裁39377实际EXIT0（9b2e91），SAFE65eef646原phase仅调用一次，29槽终态／21新逻辑调用／21实际裁判调用，seal1a894004；质量／严重错报告仍待固定144汇总，不把调用成功当裁判全接受。F2 exact6材料之后接F8，均须真实新D0与各自权限。
- B10新观察68066实际EXIT0（18d751），evidence7764acef／writer59eaa2dc／history4890c247，两遍完整字节一致、三次历史核验一致、最后真实CIM22:57:35 clear。ROOT在120秒内审阅并签32edb5be，custodian70042（d3fc35）已调用原328c／9ba一次join；原三次join失败和14902观察失败均保留，无额外native。
- F4修正版88b74bbd仅恢复四个错误hex及版本号，ROOT已读dfa1diff；原函数AST未改，7项检查通过（5保留＋2新增），独立复审仍待回。context8恢复型证明已开始纯SOURCE设计，初始ctx0／3接入范围不变，原61拒绝与48UNKNOWN未改。
- F2具体登记46147826已ROOT核对原八份envelope与九项generation／cost字节，cards中新ROOT登记4440f524已签（仅状态／签署者改变）；固定720＝672机械通过＋48拒绝UNKNOWN，初始仅ctx0／3六组576材料。最小材料once入口准备中，须等待39377真实终态以免争用ROOT锁，不因签登记便视为已评价。
- B10新observer e25e4ae1与精确伴随历史3470682f已ROOT完整读，3项限定fake通过；新request0ec7f999绑定同34167失败的真实关联，ROOT68066（a88afc）观察进行中。旧14902失败保留，冻结producer9ba未改，join尚未授权。
- F4材料adapter首版1dc4559f被ROOT源码审阅拦截：F3→F4替换误改POLICY_SHA及其他历史hash常量；这是实现问题，不是模型结果。旧版本／测试记录保留，正在新版本修复并由独立审查核对所有不应变化的hex。不得对首版实际认证／接入。
- 原六组相对路径诊断进一步确认：first terms08的真实sidecar位于原trial/prepared，哈希匹配；执行worker按原plan目录解析，但比较器按已复制的run目录解析相对路径。不是原artifact丢失，未移动或伪造文件。正在限定审计四个已交付MAIN的路径关系并准备保留hash校验的窄修正，统计尚未发布。
- 22:48 UTC：F9新readonly21601实际EXIT0（e27d2a），proof9f8373b0／attestatione7167849已ROOT核对，195／408／413／11和六sealed目录两遍一致、22:47:24及22:47:37 target CIM clear、原69尝试保留。新native权限d6c931d6绑定finite最新471ca D0和ccb2独立审查，custodian实际39377（f3296d）启动21争议仲裁／上限42尝试／固定144；无其他native。
- F4三seed整组26953实际EXIT0（e81a0d），真实工具d07b6d60、driver6add17c5、journal97680f50／whole2050.5830668秒，交付及质量仍待独立核验。未跑origin17新0c7fe587经ROOT完整差异审阅及79f6独立回归后，依据实际F4终态签e11c115a，ROOT GPU94347（4fc04a）接跑原jobs19–35；不重跑原失败18，不覆盖已完成项，维持整组前后fresh drain及firstfailure STOP。
- B10观察诊断60d3ea47定位v4同一次失败的SAFE文件未列入recognized；限定关联提取eba3566f确认b4eb文件引用原claima972与trace5f474、同34167/tool874历史。新observer只拟精确补登记此伴随记录，旧producer与额外attempt拒绝规则不变，实际join仍未执行。
- 原六组85716已实际进入原13e.compare，在_auxiliary_generation第88行解析batch_options sidecar时FileNotFoundError。此前口头定位“第一个artifact指针”已纠正：artifact绝对路径校验通过，首F6 terms seed08的相对batch-options.json基址需进一步核对；当前6414帧记录、旧claim及完整cause/context保留，无再次comparison。
- 22:40 UTC：finite14851实际EXIT0（357ffb），group-terminal131a33ce三seed sealed／固定144，尚未质量发布；F9下一native仍须当前D0与fresh目标观察。原六组85716实际EXIT1（7df189），SAFE stopped_no_retry／original_run_once RuntimeError，完整私有context6edfc097保留，正在限定诊断，不能当成功统计或自动重试。
- B10 v5只读观察14902实际EXIT1（fcd780）：verification5c65606d，初始CIM clear，但two_complete_bytepasses_and_histories抛ValueError，writer/history均NULL；没有签发join权限／调用producer，已指派纯字节与源码predicate诊断。原三次join失败之外另存本次观察失败，不重置历史。
- F4 seed08／09于22:23:31／22:34:47 UTC命令完成，seed10进行中，整组26953仍live。origin17后继源码0c7fe587已实现并ROOT读窄diff／生命周期，两个fake检查通过，独立审查中；真实F4终态与新签权仍未填，未执行尾17。
- 22:38 UTC接跑：原六组新517统计权限7aa9f888已ROOT签署，真实九根目录观察6424 EXIT0、两遍文件完全一致、target CIM clear；外部4b423772明确保留73037旧失败及私有证据哈希，实际CPU once85716进行中。只修正NOT_RUN binding的sorted窗口顺序，proof／final槽顺序和统计分母不变。
- B10 v5 observer b5106049已ROOT读完整窄diff，保留三次失败和四个runtime源码闭集。新只读request22da4b99、实际14902观察进行中；未授权join或新增裁判。token400 MAIN独立2f6d1f0b通过2项新增检查，最小完整异常外层fce4f039就绪，仍等待后续唯一native分配。
- F3完整96限定元数据62059 EXIT0，SAFE49c4fc94：六组均34场景／4297cue／874调用／96窗；原13e稳定字段仅runtime_source_sha256不同，模板及其余引擎字段相同。F3 whole773.2241188／756.2978914／790.6157982秒，原C0 fullflow仍NULL；正在做F3专属源码等价审计，不能移用B10的ec304权限，尚未统计。
- origin idx18最终SAFE400d8893确认前述输出limit原因，3项限定离线检查通过；未跑17项后继entry已进入源码实现，仍须等F4真实终态，不重跑idx18。finite14851与F4 26953截至最近实际poll仍live。F9 ADJ21最小入口e0955e51已ROOT读，独立审查中，须finite真实D0后另签；确认48及F8 held54继续封存，探索尚未收敛。
- B10 v5独立集成5eb79125已ROOT读，1项新增AST回归通过，原校验前后链与三失败保持；实际六目录观察／join未做。token400完整96 MAIN原bfc3b843已ROOT完整读，三份115文件材料库存／固定288／原879生命周期，5合成检查通过且独立审查中；未来须最小once外层保留首异常完整私有cause/context，不能直接用仅输出异常类的CLI丢失诊断。
- origin未跑17项SOURCE已冻结：计划1f4f1b9a／queue29164184／readiness32403982，完整原jobs19–35、4258名义批次、原10场景1297cue不改。23 native交付窗与10诊断质量窗分开，不能冒充matched48/full96。2项SOURCE测试通过；当前尚未实现后缀launch entry，必须等F4真实终态和新ROOT／fresh whole drain，不自动接跑。
- origin idx18初步限定元数据显示真实输出上限失败：444批中443交付／1translation_failed，共445 native尝试；失败批两次均input378／output4096／stop_type limit且truncated=false，在parser前被guard拒绝。全局调用／token／时间预算仍充足，非总预算耗尽；trial partial／rc1、whole328.318815秒保留一次。原文／输出内容未读，尚不推断模型为何耗尽输出；最终SAFE指针待回，尾17仍仅SOURCE准备、不重试失败项。
- B10 v5 SOURCE producer9ba9566a／readonly22f454f7、最终diff d7a014c3及readiness4b39868a已ROOT完整读；只替换错误run-as-worker runtime接缝，原raw／transport／full34／dual／core96等保持，三次失败保留。独立集成审查与最小v5只读observer准备中，尚无实际join。审查产物必须位于新的兄弟目录，不能向已固定的四个runtime SOURCE namespace追加文件破坏闭包。
- F3 full96统计已授权仅三F3＋三原full34 C0的source/run/session/cost限定元数据提取，构造F3专属源等价注册；旧ec304其他候选权限不能移用，不读评分或重做认证。token95834实际工具218bab7e已保存。22:23 UTC ROOT26953仍live／F4 index0进行中，finite14851由custodian核对仍live。
- F9分歧准备63306实际EXIT0（60ad4c），SAFE02eedf33／finalf734068a已ROOT核对：29场景、23双方accepted，其中21实际签名分歧、2一致；6缺prior场景对应27个window-seed UNKNOWN，原P34＋R35尝试保留。新ADJ上限21逻辑／42传输，最终UNKNOWN仍NULL；不会用accepted数量推断无严重错。准备原70a/4329的具体phase，待finite14851终态与新ROOT权限后短ADJ优先，再F8 dev90，以先补齐F9风险证据决定是否值得容量修复；目前无新ADJ调用。
- 原六组window顺序诊断532018ba已ROOT读：两个NOT_RUN均48唯一ID、集合相同；原dd5:330校验sorted(proof.scope.window_ids)等于authority顺序，:617据此发布binding。bc4误以原proof顺序要求binding，故失败。已授权最小新版本只修expected binding的规范排序，原proof／final槽顺序、96NULL和其余校验保持，旧73037失败保留，无自动比较重试。
- F9实际一次分歧准备63306（0dbc13）已启动，e789→原5c67/70a→4329仅历史认证／选择的源码路径无全局judge锁，故与finite14851并行；未调用phase execution／ADJ native，不增加新评分。
- token400后继材料95834真实EXIT0（cccb9c），SAFE8404befd29adca8d5fae5e8702bd60d36f784f45e71dc38f738e2af2dc68cd15已ROOT读：三seed各96、合计288材料准备完成、native0。旧5035锁失败仍保留。finite-B60原201f在bc769下随后实际启动14851（b69820），没有夹入其他native，F8 dev90仍排其后；token400完整96 MAIN后续只做SOURCE准备，尚未评分。
- F2机械状态分离独立f3a58ceb已ROOT读并采纳：两个新定向合成测试通过、26个旧AST单元保持、无具体阻断；初始576材料槽与672机械准入槽的区别明确。具体注册仍仅SOURCE准备，实际材料未执行。
- F4 GPU实际句柄26953（e97d2a）已启动，ROOT继续独占GPU调度；不得再接原98657或另起推理。F3真实工具packet c7ff38c6、F2 tail2工具f9c96431、原六组失败工具2b825d85已保存。
- 原六组统计失败617f9bcc限定诊断已ROOT读：bc4 validate_unknown:115中expected binding仅window_ids列表不一致，其余字段相同；尚待核对集合／顺序及原producer发布规则，不能直接放宽为任意集合或删未知槽。
- 原GPU36队列98657真实EXIT1（ROOT write_stdin 0109da），原entry terminal亦rc1／whole9814.441086秒，journal97979d70：idx0–17命令完成，idx18 origin-b3-o1 seed09于22:09:03 UTC失败，idx19–35未运行。未重启／未覆盖；原F2九项与前origin九项保留，失败idx18限定生命周期／调用状态诊断中，不将后17项成本填零。
- F4完整96新ROOT注册：实际前驱工具3ebf608f、独立source/control42fc8dc2、三seed权限41c1b358e2bba212271d899009b007dcecc512490fa0de37fadd87a1cf51b760。复用已审7e4b300d，允许已如实记录的前驱非零EXIT；新whole-group前后GPU观察与原9c0串行队列启动中，未宣称容量／交付通过。
- F9 v2观察97471实际EXIT0（0ac6f6），94b4cfdb／proof1ff0663d已ROOT核对：195／408／413及六matched48目录两遍一致，两次target CIM clear，原69尝试保留。独立窄增补6fd931f4通过；ROOT一次CPU认证／分歧准备权限02a60c3d75f86e78da9d6375276415c7e12fc5aec083467fd78f87d3743ff24e已签，actual待回，native ADJ尚未授权。
- F2新分离控制器9bb1d24b（readiness08008f92）已ROOT完整读README与diff，9合成检查通过，独立审查中。已授权纯SOURCE具体注册准备：固定720、八份真实机械证明加idx6拒绝／成本保留。672机械准入槽不等于672质量评分：因原三seed组门槛保留，初始材料范围仅ctx0/ctx3共576槽，ctx8两份机械通过证据保留但该组暂不接入。
- token400后继材料95834已在851045下实际启动（63e784）；finite MAIN须等它真实终态，不能只凭旧D0同时开跑。F9 v2最小diff3b791b31已ROOT读，新request e7faddf8与真实readonly session97471（9827c9）已启动；修复显式relative POSIX排序、隔离失败命名空间并保留旧e41/138f，原5c67与输出v1未改，认证／native仍未放行。
- F3完整96 MAIN12887实际EXIT0（708d30），SAFE a64b498a已ROOT读，三组入口返回／固定288，质量未发布；真实最终D0 0e0510b1（e6bd173e token，22:03:35 UTC，callback／job0）已ROOT核对。token400后继材料新权限8510451e147c321e8242746fde3d0d627504899e792173666d90f27fe50931b4已签，先做一次三组接入；随后finite-B60 MAIN权限bc769d8989606c1f809f478ac837ed3bc32399abf0dc68abfaa0d1b8c33924b0已签，明确等待材料实际退出才可启动，固定144，不得同时竞争ROOT锁。
- F2尾两项95751实际EXIT0（76fb1f），SAFE c85d2411已ROOT读：idx7/8各PASS，合计八项原61通过、一项ctx8拒绝；旧六证明、idx6失败与原成本不改。新的generation/mechanical分离注册仍待完成；工程准入不代表质量已测。
- 原六组统计73037实际EXIT1（3dcea7）：在F7 scene seed09的literal_NOT_RUN_two_file_validation失败，原compare尚未调用。旧claim、inner c03c84／outer806bd3私有证据保留，已授权限定predicate诊断，不重试、不将NOT_RUN改零或伪造普通run。
- B10历史质量helper独立809fe4b1已ROOT读，2项窄审查通过；已授权仅新增v5最小接线实现，保留原前后所有native/raw/aux/dual/core96校验与三次失败历史。实际认证／join仍未放行。
- F2 tail2最小入口a9094769已ROOT完整读，6定向合成测试通过；新ROOT权限9272cf916d0bf9d13d51cda718df3c670c47d5b2dd343d17bd6eae37a8175e3b绑定原7c7832计划、b51库存、c458状态与a27拒绝证据，交custodian执行当前两目标writer／byte检查后各一次原61 CLI。仅idx7/8，旧0–6不重跑，V9／native仍未授权。
- token400材料后继c0646357完整diff54a5c150已ROOT读，6合成检查通过；原879与062269材料gate、同288槽不变，新增旧5035失败九指针及实际12887 EXIT0／D0分配门槛。实际仍待F3退出，无新claim。B10历史质量helper5f26806c与差异06c70896已ROOT读，9合成检查通过，独立审查中，v5实际join尚未启动。
- 原六组bc4一次统计在be186下实际启动73037（8cd1ba），源码调用链已核不获取全局judge锁、不重复原trial认证；仍由原入口完成byte barrier／claim／比较。结果待回，不能把先前运行配置一致或sealed计数当质量通过。原GPU98657仍live，21:59 UTC journal已开始index17，原36项尚未终态。
- 原六组统计ROOT九目录观察79903实际EXIT0（206829），两遍byte一致／两次相关CIM clear，目录计数1188／1199／1200／1178／2／2／1988／2030／2009。库存8c7093df、观察f7557737、证据2d54b0d3；ROOT exact once权限be186fb19eb0d48e8125d7e8277cb15e1be55c2e6e3accd6dd39614e80395d87已签，交custodian一次原bc4比较，实际结果待回。
- F9 observer真实失败已定位SOURCE库存排序：exact集合、12文件及哈希都一致，但Windows Path排序与relative POSIX字符串排序对README／ROOT等大小写次序不同；在SOURCE HERE库存检查即失败，尚未触及原195／P/R与core。已授权新最小版本统一字串排序并分开observer/once失败命名空间，保留e41旧失败；不是祖先材料损坏或评分失败。
- token400材料失败已定位为全局judge锁竞争：runner.py:255 PermissionError转260 ValueError，原prepare_entry:915在进入锁内材料处理之前失败；F3 MAIN仍持同一ROOT锁。已核材料pins但未做typed proof认证；失败不属卡片／机械模型拒绝。新一次接入须等F3真实EXIT与D0后，使用保留旧失败的独立入口，不能以“无关CPU任务”推断可并行。
- F9只读observer010450实际立即EXIT1（4fabaf），stage all_declared_bytes／ValueError，私有cause e41cb6a3保留，未做认证／native。已授权限定frame诊断。旧observer与未来once共用失败路径，当前旧once不可再用；不得删除失败文件解锁，恢复需另版。
- token400 typed材料5035实际EXIT1（99a9fc／工具a0ac6aa5），首seed08在original_public_prepare_entry抛ValueError，完成0／288、native0；claim与私有失败9bb5e80b保留，未重试。已授权仅frame／类型／源码predicate诊断，不能据此判断模型或质量失败。
- 原F6/F7六组typed统计独立审查875c6228通过（2项定向测试，其中1项新增）；实际限定成本／runtime投影fcdbd793已提取，七份可比较runtime身份一致，两个NOT_RUN仍NULL。六份原成本和三份共享C0各计一次；实际统计尚未运行，不把192 sealed当已知分数数目。
- F2尾两项SOURCE计划7c7832f1已ROOT读，仅idx7/8未验证项可后续一次原61校验；六份PASS与idx6拒绝不重跑。已授权新增独立V9机械状态分离实现，原91853不改、固定720槽；若尾两项通过，672槽具机械准入、idx6的48槽仍UNKNOWN，尚无材料或质量放行。
- F9 ADJ once入口ee2bd1e6及只读observer010450c3已ROOT完整读并交独立审查；ROOT另签只读请求967d6d2c，实际观察开始，原69次尝试与六份matched48库存不变。尚未授权实际认证、分歧选择或native ADJ。
- F2 idx6拒绝原因已核实为真实retained limit：SAFE a27a5c1e／原61 mechanical_replay:253；735 dispatched＝734 EOS＋1 output4096 limit，最终734批／3606ID全部交付且trial rc0。不是ABI错误，不能把恢复后的complete当全尝试EOS；原成本／失败保留，后两项机械NOTRUN分开补查，原V9需显式机械状态处置。
- token400 typed材料具体24字段606dd2b1、5035 once及原constructor已ROOT读；四targeted fake通过，三份actual proof pointer与afce匹配。ROOT独立gate062269027f90a2773a613c081d7fb5864bed50e23a94386c9dbd981a50de09cf／once release72115d2384d82293a8ca327eec6cc398c0eb528cbf65229a4375178fc2c9e96b已签并交custodian执行原879.prepare_entry三次；native／quality仍false，实际结果待回。
- F2原14385机械once实际EXIT1（207320），SAFE c4581bdc／工具76b207b1已ROOT核对：idx0–5六PASS，idx6 ctx8 seed10 FAIL／原61 rc1且无receipt/envelope，idx7 ctx0 seed10及idx8 ctx3 seed10两项机械NOTRUN。九项原generation complete不改标，六份证明保留不重跑；限定stderr frame诊断与原V9机械拒绝/生成状态分离的SOURCE处置正在推进，不能将机械NOTRUN当generation失败或漏掉720槽。
- F9 ADJ独立SOURCE972bc535通过，固定29场景／144pairs／原69尝试完整，实际分歧/缺prior pair/最终UNKNOWN仍待一次认证，不从双方accepted计数推定。
- F2九项机械校验在原a74权限下启动14385，薄入口e1f7d28f已ROOT完整读，2 targeted fake通过：先当前target CIM／9 opaque库存比对，再exclusive claim，逐项原61 CLI，首失败STOP；native／材料调用0，结果待回。原98657于21:40 UTC再次核对live；F3 MAIN12887由custodian原句柄核对live。
- B10 SOURCE审计15b595f8／README8740aabd已ROOT读，5原AST合成测试通过：readonly误把run.json当worker完成记录，真实字段在worker-completion.json；简单换记录仍涉及08合法aux计数成本与fresh-only检查不兼容。已授权三seed限定worker／workload lifecycle、cache、budget、aux指针与标量提取及另版历史质量专用严格校验；shared helper与原记录不改，不推断新鲜性能。
- F9 matched风险ADJ SOURCE准备329d4372（constructor5c67／helper70a3）已进入独立审查，原P24 accepted／5failed／34尝试，R23／6／35保留，真实分歧数与UNKNOWN尚NULL；新增一次原方法私有选择与readonly observer准备中，没有新ADJ调用。
- F6 rolling六组MAIN SOURCE01f726e6已ROOT读，复用原175／588入口；六份材料proposal3f6f0f29经ROOT逐目录67文件byte与run metadata/raw SHA复核后签定，index4ea00640183cc9a093f66370a59d184621802e137cb7e814c2006a4037cb276c。只完成独立材料freeze，native仍false／排队。ROOT首签脚本135b53因将candidates字典误当计数而在写入前assert失败，已保留说明，实际以原manifest每组48核对。
- token400 typed consumer87908b22完整diff及独立7db18ab9已ROOT审阅：8 owner＋2 reviewer（1重叠）通过，具体三seed proof已完成，独立材料registration proposal正在填充，不再冒用原6d checker namespace。
- F2原61九项literal CLI路线3b316e24／4项SOURCE测试与完整源码说明已ROOT读；新一次机械权限a74a7179绑定实际checkpoint b51e8006，交custodian先核当前target writer／opaque库存再exclusive claim后执行。原61每项replay＋build各一次、首失败STOP，原generation complete不得改标failed以绕V9；固定720，材料／native未授权，实际句柄待回。
- 当前SAFE矩阵为v10 `summaries/current-screening-evidence-matrix-v10/matrix.zh.md` SHA01993baac9a7fddd7d3b9103406ac1f7a00612447b18f066c95f08aa6cb94d5e，仅新增F3风险行；v9全部18质量／4旧风险／3机械与118pins原值保留，新合计5风险记录，未重算bootstrap。
- B10 v4第一实际异常定位v2_unit_main_proof._runtime:228，原C0 seed08 worker缺少reused_windows与performance_valid_for_fresh_flow两个字段（不是已观察到正数reuse或明确false）；原get==0／True校验拒绝。05c386b9与字段presence补充fa00a227保留。继续限定历史元数据／源码核对，不填造fresh标志、不将历史质量复用冒充新计时；原874尝试及aux库存检查已到达，后续core96认证／join未到达。
- token400 full96兼容机械校验70640实际EXIT0（097670），SAFE afce018e、工具0ac7ab6a已ROOT读：三seed各full34／4297cue／96窗／480ID／132 completion均EOS未截断；原whole耗时675.5846201／675.2550805／677.4807341各计一次。原39e失败仍保留，新证明不等于质量通过，typed材料接入继续。
- B10 v4实际34167 EXIT1（cda32f），工具87434bf3、私有trace5f4740a7／claim a9724aa6保留，无自动重试。SAFE限定baseline seed08 original_full34_native_authentication中的ValueError，真实第一predicate仍待frame-only提取；没有新增native／judge／compare，严重风险仍未评。
- F2 checkpoint80443实际EXIT0（ecf4e4），b51e8006已ROOT核验：9目录两遍opaque库存相同、三次目标CIM clear，9项complete／原scene计数34或29／两项cleanup均true；前缀18行22749字节ff84f563、FINAL21:27 UTC。后27未观察、全局idle未声明；机械61入口准备中，无proof或质量授权。
- F3 matched144风险报告实际175729 EXIT0（工具9a412aa1），SAFE653087d6／中文报告bc6bc30c／final5227e3a0已发布。固定144，UNKNOWN39＝27缺prior＋6 failed ADJ＋6 unresolved；新增MAJOR3个scene-local groups／3窗／3pairs，恶化MAJOR1组／1窗／2pairs，已报告CRITICAL0不代表排除未知风险。当前具体配方不能晋级，improved不能抵消；在跑完整96 MAIN12887仍为有界分布诊断，不改原分数／不缩分母。
- B10第三次ROOT观察59094实际EXIT0（8beb68），证据11108db3／writer a3a689f8／history1562ef91；三次CIM clear、两遍六core字节一致、三遍失败历史一致。FINAL21:25:31 UTC，ROOT一次新权限4e90c116；producer实际claim于21:26:14 UTC写入（attempts1），未使用前两次过期观察。实际join结果待回。
- F2前9 checkpoint原observer c7f33638实际启动80443，request fb727236；只读前18行固定前缀与9产物，原98657后27继续GPU。机械61与V9材料仍未执行。
- F2前9项已于21:24:10 UTC全部command complete／rc0，原98657继续origin27。ROOT仅保存原journal前18完整行，独立checkpoint请求fb727236已签，实际观察待运行；未冻结增长中的整journal，未宣布机械／质量通过。
- token400 full96 lineage修正版067ff6cb／validatorf591c059及独立1b54b97a已ROOT审阅，八项owner合成与两项reviewer检查（含一项重叠）通过。ROOT另签一次三seed机械权限c594952e，排在B10 join与F3报告后，材料／native不授权；新typed consumer接入仍在实现。F4未来launch v2 7e4b300d独立23796872通过，原authority替换缺口闭合，实际GPU仍等待原36队列真实退出。
- F9 REVIEW48241实际EXIT0，工具b3b730a0／SAFE5af91031／真实D0 8e54db49已ROOT核对。F3完整96三seed MAIN获新outer bd069974并由custodian一次启动12887，固定288，尚无质量结果。
- B10第二次只读66412实际EXIT0（18c361b9），但ROOT接回时已超120秒，签署脚本正确拒绝，v2权限未写、producer未调用。原证据保留；原observer字节不变的新第三次59094运行，request e2edf5c1，不改旧时间戳。
- F2原98657前8项命令完成／rc0，第9项ctx3 full96 seed10于21:10:42 UTC开始；整36项继续。F4未来launch发现可替换实际前驱authority的SOURCE缺口，新v2仅固定真实396c pointer与等式，独立反例复核中，无实际GPU调用。
- F3 matched风险语义报告SOURCE v2 8f730a78及独立4c0e7c63已ROOT审阅；固定144、UNKNOWN39不变，新一次报告权限已签，尚未运行，不将终态collector当质量结论。
- B10 e06431未实际启动：custodian上下文接续完成时已超过120秒观察新鲜度，确认没有claim／实际join，旧成功观察及未用权限保留，未改时间戳。ROOT在新external execution-v2目录复用字节完全相同f3c447 observer，另签请求4b77504c，实际重新观察session66412（bd2212）已启动；这不是重试原producer。custodian已专门等待新结果，后续须新v2权限。
- B10 V4 ROOT现场84031实际EXIT0（eae50d），evidence `e6e8309b73b2b9dd3edd8e5276f366ee0a8a3a9a29063213a98ef173873bf9af` 已ROOT读：六core两遍一致、三次history一致、三次相关writer clear，末次21:06:55 UTC／history21:06:49。ROOT随后签一次join `e06431d19dc6c8301ec6a729ec458df153593b53f986cf45ee07b3f8fba379f4`（cards/B10-full96-risk-v4-ROOT-once-join-authority-v1.json），交custodian在120秒内调用原v4一次；无额外auth／preflight，真实结果待回。
- F4 full96独立审查 `bba9549a4cb8f43767c148fa21bbe53fd185010c2b4564f3baac116e5c9d2bd0` 通过，2新增反例、未重跑owner4；ROOT已读结论。原协议／runtime21与source身份保持，实际全范围容量／新V7 tuple注册仍未完成，不可直接enqueue。B10 observer独立回执 `870971962453fff4b3ddfd90252ae74821b93ab4ebf97392b7b027ef5ac1d2a4` 已ROOT读，无阻断；真实84031仍运行。
- ROOT B10 V4现场只读观察已实际启动session84031（79f466），请求 `7e5efeb15c02f4897290f3820ccace3935662bc30d9b7ea1ad18a3c941980c5d`，600秒allocation窗口。独立窄审查2 targeted PASS（1原AST复用＋1新failed-history文件系统回归），目前无阻断；真实结果仍待回，尚未签新join。custodian已确认独立CPU join槽空闲，F9 native可继续。
- token400 matched薄入口新版 `33d11aaea1344b46473c272f1f5c8f172a7648afe72970d61e28cfb3f7a267ba` 已ROOT读完整差异，保留suppressed cause/context图；1针对性fake通过，原v1不改、未执行。未来使用recipe dff4a330，仍待原190 fresh观察／新启动登记。
- F4 ordered full96暂存方案已冻结（queue8226623c、readiness3a58a395）；ROOT已读生成源码及范围说明，独立审查继续。仅扩展34／4297／96／480，原batch5／ctx1+1／4096协议与runtime不改；完整prompt容量仍NULL，当前36队列不改，未来启动须待其真实终态。
- F2 journal第7项ctx8 seed10于20:58:31 UTC实际command complete／rc0，当前第8项ctx0 full96 seed10运行；三seed ctx8命令均通过，整组机械／质量仍未核验。
- B10 V4 fresh observer `f3c447c0867cb341c8ab582e8040f1100f637d75faf7a5ed2e9782e827ee7bca` 已ROOT读完整差异及观察／freshness主路径，readiness555dfdba、6纯SOURCE测试通过；独立审查继续。两失败root、精确pending SOURCE与诊断／审查库存均纳入，不忽略额外文件；保留六core双遍字节、三次writer／history及120秒新鲜度。当前尚未实际观察或新join。
- token400 matched scope桥激活准备805ecbc8已ROOT完整读；发现薄入口仅 `traceback.format_exc()` 会遗漏原wrapper以 `raise ... from None` 隐藏的底层context，已要求另版最小保留cause／context修正及单个针对性测试，旧SOURCE冻结不改。尚无实际新观察或dispatch；这与full96原卡来源ABI修复是两条不同路径。
- F9 REVIEW已实际启动custodian48241（b155b2），原47c4薄入口／5fc启动权限／17d9前驱D0；只调用原0797.dispatch一次，当前live，未增加其他native池。
- 原六槽最后真实D0 `cf70fc9909514e44bd9d9c9741af63bc.json`／SHA `17d9e9b8852eec85d8dc84a7887709afdf70e3b0362a7390fb90ce1ee05eaef8` 已ROOT读并重算：PID75152、20:45:15 UTC、drained／callbacks0／jobobjects0／6并发。custodian按既有47c4／5fc接续F9 REVIEW；没有等待无关SOURCE准备的依赖，当前仅待实际启动回执。
- 原六槽MAIN32080实际EXIT0（8af138），SAFE117a46b4；四完整／两NOTRUN固定288不变，尚未释放质量。F3新版collector48244实际EXIT0（4addb6），SAFE handoff `847350dae2a0b142be5795a3f72de14250dfe7f3b94c0a7a41b51aa680997e81` 与finalization84069c30；ROOT已读允许的认证／完整性字段：原195、P420、R429、A332库存通过，A21逻辑／20accepted／1failed／22attempts。registry22 ready，6前序缺失场景对应27对、1裁决失败，另3 unresolved场景6对，合计UNKNOWN39；未发布语义根因结论。后续只准备原方法风险报告，不新增judge或重试意见。
- F3 full96原f0c薄入口 `4fc751ac919e372bd21825aecf404abec860ebc5861c4947db8eb912bed7a2cc` 已ROOT完整读，3fake通过；静态group launch `eb2fb5c17bae53a98cbc621d15a93759caf60b73cb41f2753b038e1c778069fe` 已签，外层activation／真实F9前驱D0仍NULL，不能独立启动native。
- 收敛路径审计最终报告summaries/convergence-critical-path-audit-v1/report-final.zh.md（a6fdd736）已ROOT读；确认F4 full96×3为具体待补项，其他新batch／方向context／交互点先消费当前证据再决定。正式确认、同口径计时与必要长流程证据仍缺，不能从队列长度或暂时无赢家推断收敛。
- B10 V4独立审查 `f50ecaca92ae0a79ae92823867e40ea6cf6a77ee2b168777b94a7701d512d4e3` 已ROOT读，5fake通过（4复用＋1新增）。未来调用须补原parser必需的 `--root-allocated-once-window`；只修正外部调用说明，不改已冻结认证代码或既往失败。
- token400 full96 cab5私有frame限定抽取定位实际KeyError：原67 `mechanical_replay` 第93行读取 `card[derivation][promotion_receipt]`，三张原卡没有该字段而使用full96 source/control metadata登记。首seed在此拒绝，尚未进入源packing／native attempt核验，不能归为模型失败；ROOT已读原67相应源码，授权另版最小来源兼容分支SOURCE准备，原卡／checker／失败历史不改，实际新replay未授权。
- F3新版collector已实际启动custodian48244（6122fb），精确243e／1ed332，仅一次collect，尚无终态。token400 matched scope桥的新失败历史／fresh观察／最小保留入口仅SOURCE准备；B10 V4 fresh observer同样尚未实际运行。
- F2 first9 observer c7f33638已ROOT完整读源码；独立审查 `5b874f64dead0a98cfa10b9910d9ece88a29acdad0ed93b717a3c2a05a6e2e3f` 已读，3新增fake通过、未重跑owner8。实际观察仍须等原九项终态；两次字节和三次process snapshot不是原子lock，不授予机械或语义资格。
- 收敛路径复核：F4 ordered已满足非JSON最低有界筛选，但matched48剧集区间跨0、电影负向且作品异质，不能据此关闭方向。按计划5.1准备固定原协议的full96×3扩展，尚未生成新运行或改变原98657队列；不额外展开direct-SRT／协议网格。
- token400 full96原67实际一次EXIT1（6ed869），首seed08在 original67_mechanical_replay 阶段失败，成功0，09／10未尝试；SAFE `096a6ea24ba9e6fd4083966e694c3e0934125ff783b0731ae30647dde96f1044` 已ROOT读，私有失败cab5a1c8与tool50f13321保留。权限39e988已消费，不重试；仅授权custody抽取源码frame／拒绝predicate，不读取或发布正文。F3新版collector在该CPU退出后接续。
- F2原98657 journal确认前6项均command complete／rc0，第6项ctx0 seed09结束20:44:22 UTC；第7项ctx8 seed10开始。前9 checkpoint条件尚未满足，不把局部命令成功等同整组认证。
- token400 full96原67一次入口df0228独立审查 `6e60181e91949e71946c75305af70b773b51e704adf8bd7b8a436eaedcb8f923` 已ROOT读，3新增fake通过；ROOT按四字段签署 `39e988fa6b06afb6419a8516e36406da8726aa3496511fdf5fae99367c4b9b1c`（summaries/ROOT-token400-full96-original67-three-seed-once-v1.json），交custodian执行三seed原67 replay／build各一次、首失败STOP。材料／native未授权，真实结果待回。
- F3新版collector05999／once243e独立审查 `d1db9c7b248d33612546d0993990ecbfd535f2d7d3420e41ec7b625816bfc4e3` 已ROOT读，5测试通过（4复用＋1新增）。ROOT实际目标CIM未发现相关writer，排除自身祖先进程且不宣称全局idle；另核对source／seal／launch字节与新路径空缺，签新一次权限 `1ed3321c4f62bab7a9b0d8b5836d64e41437ae0189634ce7a295999fcd49617d`，排在token400机械CPU退出后。旧89337失败保留，尚未释放风险结果。
- B10专用aux helper独立审查10849b2f通过；最小V4接入已冻结（producer78fa7aa8／readonlyf28329／readinessefadecb1），ROOT已读完整差异，独立审查继续。绑定74302与82232两次失败、原full/core/dual/join不改；仍无实际新join权限。
- F2前9 checkpoint SOURCE入口c7f33638／freeze8dd15bd1已冻结，8合成测试通过、独立审查继续；实际九目录／journal／CIM尚未观察，前9未确认完成。原98657继续，原六槽32080继续唯一native评分池；不把任何中间文件计数当最终质量。
- B10 C0专用transport helper `2bd0ad21af7fd8bac6bfb4f0ed847dfaca4528738b6e661739fea492d21ca047` 已ROOT完整读，readinessc118c229、8 focused synthetic通过；独立复核继续。该seam仅完整核对extra辅助请求库存与归属，不能声称辅助response token值／JA payload逐字得到认证。C0主流程不消费这些计数，原874 main `_all_attempts`／runtime／交付／成本路径仍不改；额外指针只用于原transport库存函数，不计成翻译次数或再加成本。
- F9 REVIEW最小保留入口 `47c4eec5083df7718e0469b1ffefad12b280732f6cae7dcc2f25c3c4d26b18ad` 已ROOT完整读，3 fake通过；在既有5fc权限下，只待原六槽32080真实EXIT及其D0后调用原0797一次，私有异常context链保留，无额外auth／preflight。当前尚未实际启动。
- F5 cue新版材料原9276实际EXIT0（c3fe56），SAFE `424e71940027b8a2a0e755159d5383cc3ba9278e4ba6190f6d9b7609d5bf293a` 与实际tool4ea2b25e已ROOT读取；原e598.materialize_once恰一次、固定252／scheduled252／unavailable0／native0。新材料result `6293941c0cf76846d512818a0b9c3ada2ec2696dbed3f53a95cb5186528658b7`，fresh probe仍NULL、callsfalse，尚无质量。后续probe／PRIMARY保持排在F3 full96之后。
- F2前9checkpoint source-note `315418ed633cc4be0d69ec52035264dfb044c9c7a22d7df07bef69717c205903` 已冻结；仅准备复用byte／CIM工具的目标范围observer，尚未观察实际九目录／journal或重放。将明确保留后27仍活动与已有native pool，不以全局空闲作为离线资格前提。
- 资源灵活接续：F2 checkpoint SOURCE审计确认原9c0等待每个子进程退出后才append／flush终态并推进，不回写已完成root；36输出路径相异且前9／后27无祖孙交叠。原61／V9无需whole36 EXIT。因此拟在真实前9全部结束后，仅冻结18条已完成journal前缀及字节边界、做目标目录writer／字节屏障，然后在后27仍GPU运行时做离线61资格与材料。当前尚未满足前9终态；不冻结仍增长的整journal，不宣称全局GPU空闲。
- F2 source route审计7c638278／readinessc583600a已ROOT完整阅读：现有checker61＋V9 `91853e086ec27a1a00c531912fda99c307d8551a242df62a7074eedfdf1b5885` 足够，原ROOT offline acceptance7f3cd保留，不新建controller。ctx0／3各full96×3、ctx8 matched48×3共720槽，完整trial才有61 proof，partial／failed／NOTRUN照原规则登记。GPUjournal第4项ctx3 seed09已于20:18:44 UTC command complete／rc0；第5项ctx8 seed09运行。
- B10三seed允许endpoint metadata核对：仅08存在额外4297源计数，09／10为props1、tokenize874、completion874，source-token-counts文件不存在。修正限定08严格aux4297 provenance，09／10继续原validator且禁止aux；没有一般性忽略extra请求。09首次试读不存在计数文件的FileNotFound保留，为提取脚本假设错误，不是模型失败。
- F3终态collector另版SOURCE缺口已隔离：原controller对本轮新failed ADJ输出 `unknown_adjudication_missing`，旧collector期待 `unknown_adjudication_failed`；纯metadata标签修正GREEN、错误accepted计数仍RED。仅证明兼容性缺口，不声称就是89337第一失败行；其前面的registry字节重验未重新执行。最小新collector与私有失败留痕准备中，原242d不变。
- token400 scope桥独立审查 `9dcc71d27608cd8b85fc1bfe5918553691b7c4521e44cca649bd10939ee52cb1` 已ROOT读：14冻结文件不变，6新增合成反例通过；authority只改expected_scope，wrapper12其他函数AST相同。现有190材料fresh观察可优先复用原可指定新output的observer，未另签实际调用。
- 当前custodian原六槽32080继续唯一native pool；最近允许metadata检查首F6 terms08已有109成功ledger／109attempts（中间状态，非最终评分）。F5新材料原9276已在7a11下启动，仅原e598.materialize_once，无额外auth或native。F3失败collector限定metadata检查header／binding通过，声明的22 registry／7 unknownscene／39 UNKNOWNpairs仍未获完整registry认证，不能作为已释放风险真值。
- B10 v3允许metadata诊断已ROOT读SAFE `324cf0a511310d9358becc871a0606d3e2e21dd4fe3b954c410861ebf8816e0f`／provenance `160df6c34743282d09c644e95e7b331001544adc3a7ed6d2f39ab916fc31e853`：seed08唯一拒绝是tokenize库存，实际5171＝main874＋source计数4297；completion874、props1均正确。extra4297与原source-token-counts v2全部accepted／unique exchange集合精确相等，重复0；尚未因此声称全transport／正文认证。其余两seed同范围metadata核对及新C0专用严格aux库存SOURCE修正已授权，原共享helper不改，实际新join未授权。
- token400 matched scope桥3abb8ac6 wrapper及纯映射／完整diff已ROOT读，原4329 `_scope` 旧shape RED／新shape GREEN，5 targeted fake；只映射既定29／3606／48／240／144，reference false仅指risk packet不加入参考文本。独立审查继续，两次原失败保留，未来仍需fresh观察／新ROOT权限，不自动调用。
- finite MAIN独立限定审查 `3da1a7cfe0b795c5faae9332b5f1eae2fdf1a5a480f19c71ff8c8f7a0b3d23a8` 已ROOT读，7 fake（5复用＋2新增）通过；既有ROOT0852实际byte freeze另记，不将SOURCE审查的NULL模板混作当前状态。finite144及F8 dev90后续排在原六槽MAIN→F9风险REVIEW→F3 full96之后，未来各自另绑定真实前驱drain，尚无native启动权限。
- finite独立byte freeze原4122a4实际EXIT0，ROOT权限1868e5d3，原201f入口生成 `0852f22541c7e5c19b7d1a62fa062c2198ae65c5a4f97a295ba649473ae91290`：三seed各67初始文件／48槽，固定144，body decode／auth replay均0。源码完整ROOT审阅，native独立审查继续，实际评分尚未授权，不重复freeze。
- F3 SAFE collector原89337实际EXIT1（c7cd92），固定stage private_registry_terminal_validation，new_calls0；原b5c8 seal／c81c drain及原意见不改。没有发布风险或将失败当UNKNOWN闭合；继续SOURCE及限定metadata字段／计数诊断，不自动重新collect或重放认证。F5一次材料可在此CPU退出后继续。
- F5 cue新版route e5982b2e及独立静态69691e83已ROOT读，14 fake通过。实际metadata constructor a72752 EXIT0，新proposal `282268b1f0845b4be250345abe6b95052f23a9b25cbb0a7e89c3fc0c1d71f816` 固定252；ROOT仅改state形成protocol90770342，再签一次材料approval `7a11fb2691c086f9e602b0114783cff5682af7be06a26682fa48f07f59ea9848`，排在F3 SAFE collector退出后执行。实际材料尚未返回；native／fresh probe仍未授权，排在F3 full96之后。
- B10 v3失败已限定到baseline seed08的原full34 transport completeness：原 `_transport_inventory` 拒绝main ledger外缺失／额外调用；全874批解析之后、runtime／core96／拷贝一致性／candidate及dual join之前。私有trace7efbf2ca、claim6b53fc6e保留。具体哪个endpoint／集合差异仍待只读metadata诊断，不豁免额外调用，不把v2源frame修复当v3认证完成。
- token400 full96材料derivative6d726734已ROOT读相对已审F3源码完整差异，独立限定审查1da56b1b（17复用synthetic／32代码hash）通过；仍需原67三seed真实机械认证，proof为NULL，材料／native未执行。finite MAIN201f62e5源码已ROOT完整阅读，独立审查进行中，材料初始opaque库存尚未freeze。
- F2原98657队列允许的journal核对：seed08 ctx0 full96、ctx3 full96、ctx8 screen-a三项均command complete／rc0，分别结束19:37:27／19:51:02／20:04:55 UTC；当前第4项ctx3 full96 seed09运行。ctx8仅证明本seed命令通过，不是全部机械／质量通过，整36项尚未完成。
- B10 v3原82232实际EXIT1（e9f7af），RuntimeError，原735b一次权限已消费，不重试；保留新私有失败并限定提取实际predicate，风险仍未评。F3 SAFE collector在B10退出后获ROOT一次授权，固定seal b5c8，独立审查48611d39（7 fake，6复用＋1新增）通过，真实collect待回。
- 原六槽MAIN薄入口首次867c8d因BASE parent计算错误，在marker／import／原dispatch之前FileNotFoundError；原文件保留，新薄v2修正绝对范围后原32080实际启动，同一478权限下首次原14ea.dispatch，无auth／judge重跑。
- B10原3012实际EXIT0（c0247d），观察证据 `4d744b57ffdafd3f7ff579ba32808b4e1625a73103f6d112270cb4b5e839f521` 已ROOT读取：两遍六core字节集合一致、三遍失败历史一致、诊断20文件均匹配、三次相关进程clear。FINAL writer20:06:47 UTC／history20:06:42 UTC；不证明全局idle或未来lease。ROOT签一次v3 join权限 `735b62124a37300e54f0f7b1b744a66e224d5d1e91bcdcd8dfebf0c467508674`，交custodian在原120秒新鲜度内启动；不重置旧失败历史，不允许judge／比较。
- F8 side native独立限定审查 `b9546e985d5d079d3f50f15abdba45e04fdd23974fb3395b67a87890e499b4ba` 已ROOT阅读：6 fake（4复用＋2新增）通过，实际native尚未启动。F3风险SAFE终态出口242d9dc7已ROOT完整读源码，独立审查进行中，尚未实际collect或发布风险。
- F3 ADJ原73758实际EXIT0（43011c），21逻辑调用／22真实尝试，SAFE99cbf91f、私有seal b5c8d681、实际工具d8bce4c2；新D0 `c81c5bf95c3e43f5bbc1f222efc0df20c04b1513057ee6a2e7391b96c865cda7` 于20:01:24 UTC drained。仅终态，不是风险释放。
- token400一次性诊断原54471在新phase762fbfb8／entry1227d7ba下实际EXIT1（cfd2ff），SAFE6b1688ae、私有trace a3139b37保留。新D0 `8f59ec1f7d0a008ee0b1c07c6dad074bae58c2e97ef21ca6eec11b513a5f7872` 已ROOT核对。允许的frame-only抽取定位原4329._scope：原source-join provenance44bac的scope字段嵌套，与controller要求顶层字段不符；本次真实原因已定位，不能倒推旧84538同因。另版最小metadata桥接准备中，不改变原4329、不重放原调用。
- 为避免无关材料被token400接入问题阻塞，ROOT依据实际D08f59另签原六槽MAIN启动 `478bcd9c029769e369d14e0be9b7b20381cbfd02dd75e8138e05ccc78de860e3`，原14ea入口、四槽192有交付／两槽96 NOTRUN、固定288保持；交custodian一次执行，真实结果待回。
- B10新observer preparation-v2源码 `b9dbd7141bbea6f28b023b0d884c67198d3db7fe16aee63b2e3ced4a115d547a` 已ROOT读完整差异；10 fake（6复用＋4新增）通过。显式绑定诊断目录19声明文件＋freeze自身，逐历史pass验20文件，不豁免其他目录。ROOT现场byte／CIM观察session3012已启动，请求 `be2b575448cbf18cd49c551966655d55398026175fbb22fd35b19076828c7ec7`，结果待回；尚无新join权限。
- token400一次性诊断入口28f553独立限定审查 `5c9d8ee8382ccb8e190ee0d64bfe6b27eb2ecd80b927227447880665f4563fc9` 通过，5 fake（3复用＋2新增）；仅原b6f9.dispatch一次，无额外preflight／auth／重试。仍待F3 ADJ真实终态后另签新phase及entry权限，旧84538原因仍UNKNOWN。
- F8开发集普通side native入口3c68e753、readiness58a0e6b0已ROOT完整读源码，6 fake通过，独立审查进行中；仅dev90／180侧、全局6并发guard内三seed P／R／实际A，drain后seal，held54及后续ROOT自定义证据阶段均不授权。finite MAIN与token400 full96材料接入仍SOURCE准备，未从工程完成推断质量。
- B10 failed-history observer初版d85fa17a已ROOT完整读取，6 fake通过但尚未实际运行。ROOT发现其仅允许四个既定风险目录，会把真实存在的SOURCE-only `F1-b10-full96-risk-source-join-v2-structural-diagnosis-v1` 误判为额外历史；正在另版显式绑定该诊断目录完整冻结库存，保持未登记目录拒绝，不扩大到任意忽略。初版不改写、不消耗实际观察窗口或join权限。
- F5 cue diagnostic-v2最终SOURCE `1e1f29fbdb19be2e88a3fe9b9542da33f12160a943d197f4d17aa3f34d461dc7`、readiness0de3ad81、19 SOURCE／fake测试及独立静态回执5fbc1464已ROOT审阅。首SOURCE版可将available改标unavailable／调换private join的缺口已在实际运行前修复：full gate按真实custody全252槽重放blind／join，并验证顺序、可用状态。仅cue新版，不继承旧fidelity seal或旧意见；原schema／validator／252分母不变。现仅继续协议与材料入口SOURCE准备，实际material／probe／native均未执行，排在F3 full96之后。
- F3 ADJ21已由custodian实际启动session73758，经新薄入口 `F3-risk-adjudication-ROOT-registration-v1/run_original_once.py` 调原4329.run_phase、原7fd3／ROOT79ea；私有异常阶段记录另保留，无额外auth／preflight／controller调用或重试。原98657的ctx3 full96 seed08继续GPU生成。
- F3 ADJ ROOT现场观察原69401实际EXIT0（379e1e），证据 `4403dcfabc4f9542888f0fe9b4efd226bfd9ce8aa93b4979c4ff252c473cda8b`：原195／PRIMARY420／REVIEW429及六core两遍完整库存一致，三次相关writer／native快照clear，末次19:43:45 UTC，原73历史保留；不把快照当未来lease。ROOT另签一次ADJ启动 `79ea00b84366552461fa0a9a2ad72393cb75f0680cb9c88515d4492db57bd3f8`，使用原4329、21调用／42尝试、6并发／600秒，交custodian在finite材料真实成功后执行；结果尚未返回，27既有UNKNOWN不改。
- B10 v3 dual-frame独立SOURCE审查 `ec116c4805d9fd9ac892476cf6949678f87e7a0a8db11589e55528579c182e2c` 通过，21冻结文件不变、6新增反例，owner7未重跑。ROOT已读改动及完整C0只读v2／dual projection源码；全4297原认证与qualified96／480投影分离，实际拷贝逐值一致仍是未来真实检查。新failed-history现场观察入口正在准备，未实际重试join。
- F3 ADJ21独立SOURCE审查 `2334eafa2c7aa0da2f7bdfec9320922cebf23b02e5eac065f9319a7d3d36932e`，7方法（5复用＋2新增）通过，ROOT已读原helper／constructor及签署方案；仍待实际库存／writer观察及新的启动登记。
- finite材料原80629实际EXIT0（6e25a3），SAFE `f1b40bef316b5e907beac01154621a5fd4c0f083eae63fe4fbccceba342ebc0d` 已ROOT读取：原3967.prepare_material恰一次、三seed各48、固定144、replay／judge／native均0。下一步仅准备独立MAIN评分入口，不由材料完成推出质量。
- token400失败的允许metadata／SOURCE检查目前均通过，包括public launch、42pins／190库存、六封签、callbacks、plan jobs／model／effort／attempts及legacy command/schema。精确私有拒绝predicate仍UNKNOWN，原入口丢弃trace；已批准另版SOURCE-only once诊断入口设计，保持原b6f9.dispatch且单独登记旧84538／bb249失败历史，未来一次真实调用保留私有trace后STOP。尚未批准或执行新调用。
- F2原98657队列首项ctx0 full96 seed08命令实际complete／rc0，journal结束19:37:27 UTC；同seed ctx3已开始。此为首项命令终态，整36项仍运行，未登记全组成功或任何质量收益。
- F8 dev材料原38897实际EXIT0（bc540b），SAFE prepared_all3已ROOT读取；私有side-material指针08／09／10为63948a86／88b3d1a4／4911aa29，固定dev90配对／180侧，native0，held54仍封闭。finite144材料在此正向退出后进入唯一CPU窗口；后续F8评分入口另行登记，不能从材料成功推断纠错收益。
- finite-B60登记constructor455fd8b已ROOT完整读源码，独立限定审查4d700614（5新增负例）通过；实际083bd3 EXIT0，SAFE `3cbd02f2e8e90c504083fc82bdde325f332d5d934875f7de9aa88ab9f86d4c60`，三trial完整opaque库存双遍hash、原三成本各一次。ROOT依据原69939／e77／8c552链及typed fbee的C0来源，另签登记 `aa668cb2d1c6a19e470d1828ae318ae257a271941d55673230b1408a4b68146a`；没有把fbee冒充normal67。材料release `07727e5b15b9c965040f28c6dd58a063fbdc2d9c014675c7d5bd5a75e8f33374` 已排在F8原38897真实成功退出之后、下一native之前，仅原3967.prepare_material一次，固定144，无judge权限。该API自身没有全局ROOT锁，必须由唯一custodian明确串行分配CPU窗口。
- token400失败阶段进一步限定：原84538窗口留下真实guard D0 `156640536bb34777b43049a260d1bf39.json` SHA `bb2492ff96a2890a0ea97431525e5f98fc8474998e758293a33fa31fd3b3ec1f`（19:25:47 UTC、PID49208、callbacks／jobobjects0），ROOT已读及重算hash。overlay仍不存在，源码先进入guard再构造controller，故前置preflight／CLI版本已通过，失败在材料化之前的controller初始化／认证范围；版本literal只是已排除假设。纯元数据42pins／190库存检查通过，继续限定SOURCE诊断，不重放认证。
- 利用上述真实资源释放窗口，ROOT签F8一次材料release `4cfa9e9ce1ae2a67737576cfc57d6235ffccd3f332282a7df4c5f309fbdbe4b9`（原18018／登记077a／D0bb249）；custodian实际38897（be26fe）已启动三seed原prepare，结果待返回，native与held权限仍false。
- F3 ADJ21准备回执f09d7d77与原方法源码已ROOT审阅，独立限定审查及ROOT三根完整库存／writer观察入口准备中；未来最多21新调用／42尝试，27原缺失对仍UNKNOWN，尚未dispatch。
- token400 matched风险PRIMARY原84538实际EXIT1（d949a3，19:26:19 UTC），原b6f9仅输出registration／integrity拒绝，未保留内部trace。真实达到阶段、是否进入guard／attempt尚待限定诊断，不计作模型judge失败或虚构新D0，不重跑原入口。F8材料与原六槽MAIN暂停接续，等待真实状态与另版修复；F2生成98657独立继续。
- token400原88526整组实际EXIT0（ROOT tool947602），完整原tool packet已保留，10字段实际工具证据 `f57fd41549241dd0dcd82f305cf4366796a6a38fec9e4950e7d60463426de228`。三seed全34场景完成，成本675.585／675.255／677.481秒，第三trial SHA28f7804e；原whole wall2034.235秒，重叠成本不相加。F2 constructor原cae8f4实际EXIT0，终态证据 `7b4afd3545e284a162e9340b13660db19fd347c137bd2619ada9e6bc187cb866`、新权限 `396c3f74a1a9be951212acdf1fb795ad2d5890e75ad30352afa45b654f750d58`。原F2九项→origin27队列已实际启动ROOT98657（fa72ba），fresh whole pre/post及首非零STOP保留，结果未知。
- F6材料原80017实际EXIT0（386b83），六次原175 prepare全部成功，固定288／control0／judge0；私有manifest43c0796f、工具记录7a5be782。token400 matched风险PRIMARY原b6f9已于fb5权限下实际启动custodian84538（6e00e6），真实前驱仍52c2，无外层重试。
- F8 signer2原e8aec1实际metadata build EXIT0，回执 `7021d347dba7ad24b770c34579e1099a149fe3c931a33e79c699d5a6995d7ffc`。ROOT审核并签署三scope及material `077a15ed9b6cbfa3c902e786acd396187468c8aa0e0925bed986860094645b89`；native／held权限仍false。一次材料release须等84538真实退出后的CPU窗口再签。ROOT临时build脚本第一次因多余括号SyntaxError在解析期失败，修正后才首次调用constructor，未消费材料或改写旧输出。
- F3风险已有两轮的私有SAFE汇总：23任务两轮均接受，21有分歧、2无signature分歧；PRIMARY缺6／REVIEW缺5，缺失并集6（重叠5），27个window-seed仍UNKNOWN；原73尝试保留。后续21项ADJ入口仅准备，未擅自裁决或释放质量。
- F8原三seed机械view出口65175实际EXIT0，SAFE `F8-dev90-original-view-export-preparation-v1/actual-once-view-export-v1/SAFE-result-v1.json` SHA `99afd1bab34d7ceddaadde39a3d7b54d209ab6ad5154a6fa1f0ffb967d2786d6` 已ROOT读取。三组before／after私有指针齐备，原2202 native批次／每seed48机械窗，native／judge／feature新增均0；原成本每seed归属一次，不把六view当六次生成。接下来仅构造dev90登记，held54仍不开放语义或特征。
- token400 full96第二seed09也已complete、34／34、runtime rc0；trial SHA `e949690589aaf603072fe6625a4cdaedf88bbd11d3f27fcfcaae0426ebe0c3f0`，total_flow675.255秒，结束19:12:57 UTC。原88526仍执行第三seed，全组真实tool终态尚未取得，F2后继尚未启动。
- F3 matched风险REVIEW原62927实际EXIT0（tool02af8d），29任务中24成功／5judge_failed、37尝试，固定144分母尚未释放质量。真实D0 `ee3aed3c8a634e15b6456cec3cc8acbe.json` SHA `52c2bab27896cff4873537897121295e9ec9374c4d38ff1aa9cbcb2ee3be96e7` 已由ROOT读取、重算bytes，记录时callbacks／jobobjects均0。原F6六腿材料3d6排在此后执行，token400 PRIMARY另签 `token400-primary-ROOT-registration-v2/ROOT-signed-launch-v2.json` SHA `fb5ab6d9d00f9d467948f24b0a96bdd782e020f6002bf6b5ab9b3acd6cd93694`，须待F6材料真实退出及锁释放后启动。
- F3 full96 MAIN的UTC兼容性疑问经真实bytes核对撤销：上述D0存储19:10:15 UTC；03:10:15 +08只是同一时刻的本地显示，不能据此更改冻结f0c入口。原源码仍可接受真实记录，不进行无依据的生产修复。
- F8 view-export原65175已在3f6下实际启动，终态待返回；signer V2独立限定审查 `f5e4164f99c5165297da57bed3477dbfbeff041db54bad9a87f646112f5e9c12`，4方法（3复用＋1新增）通过，实际constructor／dev材料仍未执行。finite-B60 intake独立审查 `099bc818c9689aa8d22109610a6a81a53dc61e4a7bd4b80b7226a66ce86c7bf1`，5新增负例通过；原collection、三seed matched29 C0及成本来源仍需ROOT独立登记，不能由intake的opaque hash冒充内容认证。
- B10双frame SOURCE seam eb094d30已冻结、5纯测试及允许ID结构RED／GREEN通过；seed08的qualified480 IDs均存在于原4297源中。已将同样的限定结构核对扩展至09／10，继续生产接入及独立审查；旧失败claim17d8／trace0020保留，无实际join重试或新鲜零历史声明。
- F8 full48机械view出口ab2934b已由ROOT读完整源码，独立限定审查 `1e30649b18cd2899922468bd907182fd1d9da10ca55b93f9e782a9f52b44bbae`，4方法（2复用＋2新增）通过；ROOT另签 `3f6baf0a1afe2483e6489c13264c7424213d90f7615b87e3be12b1c718e391a2`，授权原5fd出口每seed一次，仅私有机械／source／provenance，无reference／held semantic／features／评价／native权限，结果仍待实际返回。新signer2 2c93c97a已ROOT完整读取，严格两字段scope与外部四字段来源分开，独立审查继续。
- B10允许的SOURCE结构抽取证实不是无害重排：原native96与后续qualified96仅86个ID共同、各10个独有，34场景／4297cue相同，scored tuples不同。旧只读C0 seam把原packing探测窗误等同后续冻结评分窗。ROOT仅批准SOURCE另版双frame方案：保留原native mapping与全源认证，另按既定bd3的96／480投影、验证场景ID／source membership／顺序及原评价拷贝一致性。新权限必须绑定旧失败17d8／0020；原full34足够支持投影目前仍是待认证假设，没有实际join重试或改写历史。
- token400完整96首seed08 trial已complete、runtime rc0、34／34场景；completion SHA `86c86ce2a567a0eda1203af8a3d33ce19f779458a20f11cc884ea1b9661d1906`，total_flow675.585秒，结束19:01:42 UTC。原88526整组继续，尚无全组终态或质量结论。
- F3完整96 MAIN源码f0c3b980已由ROOT完整读取，独立限定审查 `6689915f4492994b95bd3957bfd3b61b3ef4ba6d44e04e7c6a9c25cadf6682f2`，6方法（3复用＋3新增）通过。拟排在原六槽MAIN、F9风险REVIEW之后且B1之前；未来仍需真实immediate D0、独立签署group／outer及live CustodyGuard，不提前授予native或质量权限。
- F5 taxonomy最终SAFE receipt `a8c4d434c5303b67a04aa747a1d1a48858adf375c5fa64156022cc818a077f48`、中文报告 `5e65f02061b11996e2de58b779a84bc290d843bec888910351dbfbe5db46e8f7` 已释放并由ROOT读取。原prompt／schema没有明确自身group source subset与response内root唯一性限制，形成可复现的提交说明与本地接收规则差距；尚不能证明这就是模型失败的因果原因。新固定252诊断提案只改说明、不放松校验或接受旧失败。
- F2后继terminal constructor源码e3449d94已完整审阅，readiness77854e35、6离线方法；要求未来token400真实10字段tool attestation及4字段原tool packet、三个full34完成trial与全链drain，不能由driver文件推断工具退出。实际token400仍运行，未签F2执行权限或填未来事实。
- F6材料源码独立审查80597255通过（5方法、3复用＋2新增）。ROOT constructor实际f13eac EXIT0，批准b50577fd，闭合18字段登记 `4f8d908f91f2a257fc1fd7d21e7870454ea51bb3eabdde481163503574f17bf4`，六腿／33源码，judgefalse；另签材料once release `3d6da522f959f26be57dc5681498d77c8336fed3963d3ed1a39b0efc08ea787e`，条件仍为F3复评真实EXIT／D0后的CPU窗口，不提前执行。
- F8允许字段提取实际7159b3 EXIT0，metadata projection `3269e135f86a029fd4a6be21364b761c33ce1ccb156c282f38c175459d68ef83` 已由ROOT读取：三原receipt仅五字段、共享源／参考／initial-index描述，不继承F7活动权限或虚构历史F8登记。ROOT源码审查发现新constructor98a1把四字段freeze写进side scope，但冻结kernel._pointer严格只接受两字段；实际material尚未执行，正在另版正规化scope指针并保留完整描述来源。完整机械view export3的窄入口也仍在SOURCE准备，held54未开放。
- F5实际taxonomy一次执行完成（私有eba6ea63，最终SAFE报告待释放）：135失败均可解析／schema有效，冻结校验复现128项分组source scope错误、7项重复root IDs；960读取文件前后bytes稳定。target span／quote／UTF16／cue-local诊断均0，原坐标假设未获支持。此为结构诊断，不证明译文错误；新提示约束实验仅SOURCE提案，原失败／成本／UNKNOWN保留。
- B10保留trace定位原C0seed08只读验证器第83行source/window frame字面等式；前置来源及34／4297／874 packing gate通过，后续ledger／results／transport／delivery以及candidate／join尚未到达。已授权仅source packed结构ID／计数／顺序抽取与惯性比较，不读取文本或重放认证，任何修复另立失败历史登记。
- B10原74302实际EXIT1（toolff1055），一次性claim `17d8abff1b78e29d88881ad8b5b27d4b8f5de9d89e5cb5a4828fc77866911ef5` 已消费；底层ValueError，私有trace002067c7及stage保留，newnative／judge／compare0。已授权仅保留trace的结构诊断，不重复join／auth。今后不能再声称B10无先前调用，任何修复必须另立绑定失败历史的权限，旧v2禁止重跑。
- F3 matched风险REVIEW实际session62927（tool9d9f58）已按原f713／14c90启动。F6原588材料入口明确持ROOT锁，内部两次只读auth为原完整性屏障；预留在F3复评实际EXIT＋D0之后、token400 PRIMARY之前的CPU窗口，正常锁保留、不造未来D0。
- F3完整96材料v4原81745实际EXIT0（toolc15651），SAFE completion `88cb77a0ef4e5c1b289cc64f96babe1f3491c8627c83245f1b235ad25668b849`；三个原9a公共prepare均返回96槽，总288，binding分别ffe630bb／ce4a8c58／df9578dc，judge0。ROOT已读SAFE；正在准备后续独立native launch，不能把材料成功当质量通过。ROOT材料锁已释放，已有f713的matched风险REVIEW可按序继续。
- B10新鲜e01f权限已实际启动custodian session74302（tool92c88d），首次私有join进行中；无额外judge／native权限。
- finite-B60原69939实际EXIT0（toolb9c7dc），三腿均collected／complete、29场景完整。第三trial SHA3cc7d1e1、600.708秒；dispatch receipt `3ed0054cd71085b294a5a7740b989a595247bdd356270c15765fecfd0183dc6c`，ROOT真实tool记录e8f40e4f，整组wall1839.662秒，与各分项重叠，不相加重复计费。评价接入另立finite身份，旧B60身份不借用。
- token400 constructor实际c5ee3e EXIT0，原328a门验证三完整finite终态；终态证据8c55204c、新authority `dc2b6f09587f875b1b2a702d611aa9d63a0b11d4a866f3890107004c88aef333`。ROOT已启动完整96三seed GPU session88526（toolcf80b7），原队列b880／34场景4297cue132批，执行前后fresh drain保留；结果未知。
- B10 v3原22869实际EXIT0（toolce1ddb），evidence `ae4bb213c45b044b953ecf34ff4135832a2c53b04cd83f83dc5c44b780b8b455`，三CIM clear／三history0。ROOT核对时writer／history仅18.9／22.0秒，签署 `cards/B10-full96-risk-v2-ROOT-material-authority-v1.json` SHA `e01f1de407e72eaeb53f519934466725c656a260042d870bf28ce952e3d76d91` 并交custodian立即执行一次288材料；尚无材料完成或风险评分结论。
- F5原28647实际EXIT0（tool055767）；cue PRIMARY completion3ee620e6、SAFEad33d681，117成功／135judge_failed、252次尝试，原D0 3cfd不变。已启动仅保留结果的原因分类诊断。F3 risk REVIEW虽已获权，但需待仍持ROOT材料锁的F3 full96 V4实际81745结束；不绕过锁或提前启用guard。
- F3 v4独立限定审查 `6f4f7398a236baa8c45bb443032b94709307113599710ddfc9ef6e4db776db77`，5方法（3复用＋2新增）核对原始controller predicates和后续metadata边界；ROOT签署canonical schema权限 `43a75bc9dd5de7f69c09dbbf4dc155357b845b2d67878b35e8999a9d52048235`。实际custodian session81745／tool07c080已启动，结果未知；后续真实inventory／proof认证与材料仍须实际通过。
- finite-B60前两seed已实际complete（29／29场景、runtime rc0）：08 trial SHA e107ea656c92a9338d43128d2aa344ac659ae133c2a8228101a25187f6920682、total_flow595.127秒；09 SHA90dccdf74023c3a3706b1435fc7c0248bed188951a63d2981cac00f9ad93cb6b、602.088秒。原69939整组仍运行第三seed，尚不登记真实全组EXIT或质量通过。
- B10 v3 SOURCE c25d3474仅把真实FINAL CIM移至末次完整history／pins之后，两个慢扫描时效回归通过；ROOT已读差异并启动新session22869（tool5b0e7e），request16ab8a8f，等待观察终态。F3最小canonical schema修复v4 005bb5cc也已SOURCE准备并待独立审查，原v3不重试。
- F6原公共认证session80760实际EXIT0（tool8bb765），SAFE确认六腿全部返回、candidate288／controls0、material／native／quality均0。私有manifest `6556c5eb0a59568f255c86764e1a25482b801bb43217f131245f209579a943d1`，工具记录 `3c8254dd83249f4a9c6cdf3c2e96800932ecae0cf3dd17d957748e993c15949f`。正在单独准备闭合18字段材料登记与原175六次prepare入口；原consumer自身完整性认证不算新生成，但将如实记录。
- token400后继constructor源码 `33566775e54cd762e1ea5a673cbdb5af76c558c2cf3a363a2c80389fb86ac38a` 已完整审阅，6离线方法通过；实际前驱tool／terminal仍NULL。ROOT重新核对29文件源闭包及原full34 C0来源、已释放matched48信号，另签 `cards/token400-full96-independent-source-control-ROOT-registration-v1.json` SHA `4661564385cbbb88e7545e387ebab9838b4219d07d7d44b12cc5b2b25ded9a93`；该source决定不证明未来prompt容量、交付或质量，不授权judge／确认。
- B10新v2原30071实际EXIT1（tool8191d8），SAFE观察evidence `c069a4139775b13cd9f3ef48c8403ee3b8e6f0c06197c388d63a273866861ffc`。三次目标CIM均clear，三次history均0，两遍bytes完成；但FINAL CIM 18:36:12 UTC之后的全历史扫描直到18:38:18才完成，使writer超过120秒，正确拒绝且未产出可签观察。另版将真实FINAL CIM放在最后history／pins后，保留全检查与旧失败证据；不改时间戳，不放宽时效，B10材料仍从未调用。
- F3 v3原tool终态记录 `actual-material-tool-terminal-result-v3.json` SHA3522ee1e。私有trace定位冻结9a6c的verify_f3_material第214行：登记仍为proposal schema，公共controller要求正式registration schema；允许元数据上的18项初始predicate中仅该项拒绝。原67认证尚未到达，正在静态核对其余路由／闭包约束后准备最小新版本，不修改已消费v3或重复认证。
- F3 v3独立SOURCE审查d75ef378（5方法、4复用＋1新增）通过后，ROOT签署新材料权限 `0d063bf22165b7e675a586ece3e9cb92d225babd89042167fcd976d53d62a504`。实际tool52afcd EXIT1（0.835秒、ValueError），已写v3 marker，在seed08的frozen_public_prepare停止、completed空；private trace SHA e50b6fad保留，禁止重跑。已授权仅私有保留trace诊断，不调用controller／auth／prepare；证明进展越过旧preread，但整条实际接入仍未通过。
- F6六次原公共认证已实际启动custodian session80760（tool6f9c5f），窄入口 `F6-rolling-original-six-authentication-entry-preparation-v1/authenticate_six_once.py` SHA ddee6e57，四合成方法通过。原266公共parent按固定顺序调用，失败保留并停止，无材料或native权限；ROOT已读完整入口源码。
- F6 byte constructor 原50580实际EXIT0（tool d058e6），新原六腿登记 `F6-rolling-original-six-terminal-byte-registration-root-v1/terminal-registration.json` SHA `f31763363b2dfe5d9746fbc69390830a49d78c12ba1e669a8073ae4ec27ef9af`，companion94973270；六腿各8314物理文件／14 artifacts。已授权custodian使用原266公共parent入口按固定顺序各认证一次，保留私有proof；尚无材料或评分权限。
- F3纯元数据诊断复现旧preread拒绝：reference_freeze是固定四字段描述，通用byte binder只接受两字段指针；其余74指针形状／hash核对通过，三个目标不存在。新v3仅严格验证原四字段后投影path／SHA给旧binder，完整描述保留；源码5b1e78ae、readinessfbe33999，8合成方法通过，待独立审查与新权限。原783686未保留traceback，故此为确定性复现而非读取原异常栈。诊断最初测试隔离缺口曾创建一个仅含synthetic sentinel的旧failure文件，核实后仅删除该文件；随后改为BaseException与I/O tripwire，原材料仍不存在，未调用公共prepare或认证。
- F8 dev90独立限定审查receipt `4abf09408c477ce143d6419ac69cbdeb690e2531ec2dfcfa296c1cd94a7fbcc3`：5方法通过（4复用＋1新增），确认先过滤再构造dev30 packets及固定90／180分母。实际三seed链未执行；held54路线仍未实现，不视为探索完成。
- B10新v2观察源码54c7b1cb保留两遍byte检查，结束后实际追加FINAL CIM／history采集。ROOT新request c4871f05已启动session30071，待实际终态和新鲜度核对后才签一次材料权限；旧观察成功但过期的事实不变。
- B10原91931实际EXIT0（toolc72d58），观察evidence `9428a2246c5971811d91b88f9fa65276223694e86c2b743c11d613583fde3bca`，六根物理文件2172／2202／2211／2339／2229／2207、两遍一致且目标进程clear。但ROOT读取时最后writer实际时间18:17:55 UTC已过234秒，超过120秒，未签材料authority、未进入producer。保留成功旧观察，准备另版增加全部字节检查后的真实CIM／history终末快照及新输出，不伪造刷新时间。
- F3原20a／14bf材料入口实际tool783686 EXIT1，0.658秒、ValueError；`actual-material-tool-terminal-result-v2.json` SHA `36291fa189cac6c6e78155c1644df22f0fc9c49f49e9361e3e4218987f729b48`。material start marker及私有failure／completion均不存在，源码显示拒绝发生在loader／public prepare之前；具体predicate待纯SOURCE与允许元数据诊断，不重试或重复认证。
- F6 原92958整组实际EXIT0（ROOT tool ea3934），第六腿reset60 seed10 SAFE `7c4d4833041818b129c0fa82c1f62782aeccdfb2f7c72a8209f00c0cc57acfd8`，execution wall799.962秒；六腿均mechanical_complete。ROOT实际8-key工具记录 `F6-rolling-after-F9-accounted-partial-root-entry-v1/ROOT-actual-tool-terminal-v1.json` SHA `8a5672a6a9290ff63072f786152eeabb9d4f1ebbe620818d29acaf086ab449e6`，driver结束18:16:12 UTC。原8a8完整前驱验证通过，d518 constructor实际2458f9 EXIT0，六终态证据7a2b253f。
- finite-B60已实际启动ROOT session69939（首tool d8b37d），新outer权限 `ed04d23e009693bd528f387ffed9d9349b21a41f6fb87bdc7560c5a81cb84c90`，原e262权限ef858304；新fresh whole／逐腿drain仍执行。结果未知，不能与旧B60失败配方混算。F6独立terminal byte登记 f2f76729也已另起ROOT session50580，权限4595b3d4，尚无原公共auth／材料／评分。
- B10已核实可与F5 post-auth并行的CPU材料窗口：F5只持cue阶段局部锁，global native guard已释放，剩余源码仅认证读与本阶段completion写。ROOT独立观察session91931已启动，request1626dab7，尚未返回；120秒观察新鲜度与600秒窗口仍严格保留，无B10材料调用。F3材料14bf可在该CPU窗口随后执行，不人为等待整个原生队列。
- F6 原92958第五腿scene seed10已mechanical_complete／EXIT0，SAFE SHA `2567f7bca2066e92148c50b1e10379a96d7bf99d050143ca39adc3567d1d6746`；准备2.588秒、managed747.886秒、audit26.454秒、execution wall785.024秒。全组5/6，末腿reset60 seed10继续；全组真实工具终态、后置drain、评价登记仍待完成。
- F2九项→origin27的后继入口 `F2-origin36-after-token400-root-entry-preparation-v1/root_entry.py` SHA `0f893d421325ab7a194143c66449902a8254ef63b981be23ff62c93250fac5c4`已SOURCE冻结，20合成测试；独立限定回执 `35ca7bf83067883207ea587ed95dcc7419b85a195c68d167a1b9ab8da68149bb`，5方法含4复用＋1真实21a过期拒绝检查。ROOT已读完整源码，原3b038／9c0保持，只whole-group fresh pre/post，不宣称逐腿新增检查或atomic lock；实际token400前驱证据与权限仍NULL。
- F5 252项最终attempt枚举为117成功／135终态evidence_failure、252尝试；对应实际D0 `9986e571b2e24bd5b4cc841502187b1d.json` SHA `3cfd224ba179016734bd4b6a5fdcfbd12c061f0bf600b6fb2d436b47ffd21e49`，全部252项custody token一致、callbacks／jobobjects0。原28647仍进行结束库存核验，尚无工具EXIT，不据D0单独启动F3复评。证据坐标说明缺口目前只是源码假设，实际135项原因分类待终态后执行。
- F9 ancestry once原10760实际EXIT0（tool2268c7），receipt `d505755b912e19376647738bff29cccf65a907a425ad63f54e1b953a00db8f8f`，工具元数据3e1a7487；29历史／24成功／5失败／34attempt及stdin认证，fresh review输入一致，native0。新独立REVIEW29权限 `summaries/F9-risk-review-ROOT-registration-v1/ROOT-signed-launch-v1.json` SHA `5fc53e086e686ab7236d14d64b13fb73383c39586438c6927a2ba36840054085`已登记，排在原六槽MAIN之后、B1前，不重复ancestry认证、不自动ADJ／释放质量。
- F5 cue于17:55:25 UTC的SAFE枚举核对澄清：219 job／attempt，100成功、114已终态evidence_failure、5 started未终态（虽然job占位status为judge_failed）。214个已完成attempt均transport completed／rc0，未观察到transport／timeout／access失败；这仅定位到本地证据校验拒绝，不证明译文有错，也不证明裁判prompt／ABI无缺陷。终态后追加保留原件的私有原因分类诊断，不追加重试或导出裁判文本。
- F3 ROOT byte v2原41021实际EXIT0（tool74ca81），SAFE `actual-three-intake-material-preparation-v2/SAFE-byte-audit-result-v2.json` SHA `28f7ca49189fa2dcf676f2cdca2f30f7a87b8d6a3ea2d63483d319434b197d46`：三seed各6352物理文件、5247transport、114captured源码／21声明依赖，874原completion／seed；mechanical replay0。独立材料权限 `ROOT-signed-actual-three-material-enrollment-v2.json` SHA `14bf10a4549326635276b2a038b74171a8d1f4a03f742521950da4d811cf5ae7`已交custodian，须在正向分配的材料窗口调用20a5→原9a每seed一次，无native／quality权限。
- F3 byte helper修复v2 cccc1b53／material successor20a50f1e已冻结；非repo CWD、去除PYTHONPATH的实际direct CLI合成RED／GREEN验证通过，独立回执e419ef65（3复用方法）。ROOT新权限adfabd85已启动一次实际byte audit session41021，结果未返回；旧v1 claim／失败不改写，不重复原67 replay。
- F9 ROOT实际观察tool6110be EXIT0：629文件两遍一致、目标writer快照clear，proof `1b1045b05e3c9e2343096b1afc4dd2746baec7c5fdb5d6b97bb822a213decd3f`，wrapper ebafd30b；不是全局idle或未来lease。独立SOURCE回执a68d83fb已读，新一次ancestry权限 `evaluation-only/F9-risk-review-ancestry-authentication-once-root-authority-v1.json` SHA `7cc43cf8b26094c6628657aa1d770296b6b4229f18a111e7d6f45338e9fc2f3c`已交custodian执行，仅已有记录认证，无REVIEW dispatch／ADJ权限。
- F6 原92958第四腿scene seed09已mechanical_complete／EXIT0，SAFE SHA `75093d16cc8ca49c242186a991aabfa1e06e730c5692253d7d6e16cf9b8a1fe9`；准备2.567秒、managed744.411秒、audit28.035秒、execution wall782.951秒分别保留。全组4/6，剩余两腿继续；不把终态交付当作质量证据。
- B10 风险producer v2 eca61ab0／入口2cd5已修复六封签前置检查，ROOT已读完整producer、原C0只读验证器df500及差异；独立修复回执 `F1-b10-full96-risk-private-producer-independent-review-v2/review-receipt.json` SHA `99bd400c20ed8d3254efae836c36c7cba4b828405b4fd818f3b55fce6e776ce6`，2项限定回归通过。实际原C0 ABI／六根内容一致性仍未执行，待新鲜writer／zero-history观察后单独放行一次材料，风险仍未评估。
- 后续 F2九项→origin27 的既有36项队列已完成SOURCE核对，SAFE `F2-after-token400-source-succession-readiness-v1/safe-handoff.json` SHA `d0cbfe2233fc033a861e31790318fb7fe132a0c4b230e078cb0218214dacbd3f`，431绑定文件核对；原schedule3b038不重建。正在补齐连接token400实际三终态与fresh drain的窄入口，当前所有未来执行证据NULL；ctx8实际prompt容量未知，不静默缩上下文或输出预算。
- F9 matched风险REVIEW29的SOURCE已冻结，wrapper0797f6b5、once ancestry入口abcadf15，准备inventory9f294f28；原195＋PRIMARY408物理文件（406 seal条目＋seal＋lock）与407 history分开。ROOT已读源码，独立检查及ROOT当前writer／byte观察准备中；actual authentication／REVIEW仍未执行，不能把PRIMARY24成功／5失败解释为最终风险结论。
- F5 cue原28647于17:41:36 UTC已有实际PRIMARY持久化状态80项／80尝试，succeeded39、judge_failed41；此前无目录的状态已过时。这只是中途执行状态，未终态、未重试或重置，不解释为裁判真值或最终质量结论。
- B10 full96风险新producer f6288独立检查发现P2：第六原始封签缺失／漂移时仍先写claim并进入后续join。独立合成复现保留于`F1-b10-full96-risk-private-producer-independent-review-v1/review-receipt.json` SHA `2b083a146e8379608efae6052dc83b5b933a423152d90d3a670cc4138a6fcb4f`，4方法含3复用＋1新复现通过，真实auth／material／native为0。正在另立修正版将六封签检查前移；旧版不放行。
- F6 原92958第三腿reset60 seed09已mechanical_complete／EXIT0，SAFE SHA `49cb000b848a42abd5e307ebb49d1321dd7db5f518a9b4e7b3806efc0dc8e7af`；734批／3606cue完整、0失败，input211–834、首次cache_n0核验。准备2.681秒、managed750.137秒、audit23.905秒、execution wall784.646秒分别记录。全组3/6，第四腿scene seed09目录已出现；仍无质量结论。
- F3 新 ROOT byte helper5b957 的广告直接命令实际 EXIT1（tool f7ebda，ModuleNotFoundError，首 seed08／完成0）；权限 e40d8ea7、已消费 claim 与 SAFE-byte-audit-failure-v1.json 保留，未重试。正在核对直接脚本的仓库 import 路径并准备独立新版本，不改写原三seed机械成功，也不重复原67认证。
- F8 INITIAL 的实际 SAFE count 投影 `summaries/F8-original-INITIAL-dev-readiness-v1/INITIAL-SAFE-count-projection-v1.json` SHA `d60058035a8db2b60e6345646923322015a3688b313e71296ed38021f86b0352`：2202批 lineage，每seed477开发snapshot存在、257非开发snapshot不存在；总1431／771，未读snapshot值。旧144pairs原生入口要求全量封签，与当前bridge先dev90、冻结单一规则、再hold54的顺序不兼容；准备显式dev90pairs／180sides新派生，不能把私有执行等同于hold评价授权，实际judge仍未开始。
- F6原92958第二腿reset60 seed08已mechanical_complete／EXIT0，SAFE `runs/F6-rolling-memory-v3-screen-a/reset60-seed20261008/mechanical-safe.json` SHA `964c9f2c72626f82132fbe1b3aee34d5c60d4845408a79d136165188fb12bd52`，734批／3606cue完整，0失败；255学习entry、275注入／231批、77计划reset／移除189entry，input211–833，首completion cache_n0核验。execution wall802.558秒、managed765.060秒单列；全组2/6，第三腿reset60 seed09运行中，剩余质量与终态未知。
- F9 matched48风险PRIMARY原16685的24accepted／5judge_failed／34attempts将进入ALL29独立REVIEW准备，保留固定144及盲化新fingerprint；与full96输入容量受阻分开，不因后者跳过前者，也不提前推断ADJ或无严重错误。
- F8 INITIAL原51511实际EXIT0（tool e910a8），工具证据 `summaries/F8-all3-release-preparation-v2/actual-INITIAL-tool-terminal-result-v1.json` SHA `b8a0b7b0997de37e17e4ab25cf04171e4589c6ece72cf00ba4a692c4f69a5f8e`。私有导出70c01227／inventory85a3e3be，物理2207文件仅hash/count观察；代码预期2202批不替代实际内部范围审计。准备SAFE实际count/schema和dev90pairs／180sides评价提案，尚未judge；hold54／108与全量质量仍封存。
- token400 PRIMARY ROOT实际byte／目标writer观察已EXIT0（tool59fbae）：`summaries/token400-primary-root-observation-preparation-v1/actual-root-observation-v1/root-observation-proof.json` SHA `2d0efbabebe00186f4a903b59617bf72b2d35972c1445e943578ee45c48bc2b8`，190文件两遍一致、目标writer两快照clear、历史ownerPID明确UNKNOWN。无native lease或全局idle声明；后续原生次序为F5 cue→F3 risk review→token400 PRIMARY→原六槽MAIN→B1/commonB3/F7，token400精确权限须绑定F3 review结束后的实际D0，尚未派发。
- F6 rolling原92958首腿scene08已mechanical_complete／EXIT0，SAFE `runs/F6-rolling-memory-v3-screen-a/scene-seed20261008/mechanical-safe.json` SHA `0ae6f92542f0720561e6ada76f9d2a7433e7b6cbfce222c69b9e7f85255f4b8f`：734/734批、3606cue交付，0失败，152学习entry、373注入exemplar／298批，首次completion cache_n0核验；input219–833，无容量超限。准备2.923秒／managed781.146秒／audit-export28.486秒／execution wall821.010秒口径分别保留，不当正式计时。仅1/6腿完成，reset60 seed08已启动，无质量结论或全组完成结论。
- F8仅开发INITIAL原51511已实际启动（首tool92a1b4），按84f811权限进入原8969／05175；结果待回报，无新增judge／model或hold54解封。
- F8 ROOT byte v2原30403实际EXIT0（tool540ba2），SAFE `F8-all3-mechanical-root-byte-registration-preparation-v2/actual-root-byte-audit-SAFE-v2.json` SHA `cb18dcf621768719c78a595904d7034294678c37bad918116a08ba52a5ac4c38`，三seed各9766文件完整物理库存／hash通过，captured114与declared21分开；每seed1468原completion、完整flow约1279.325／1282.219／1279.621秒仅计一次。原v1 consumed失败仍保留，无新模型／judge调用。
- 新独立F8 INITIAL开发导出权限 `F8-original-INITIAL-ROOT-registration-v1/ROOT-INITIAL-release-v1.json` SHA `84f811a8807d44ee353a4bb65795e506e632df76ab538243a50c0bd6c2a98f81`已放行一次原8969 glue／05175 custody；卡c0c8fa00、五key proof registration09b014bb。仅development_only，hold54／确认48封存，无judge或full aggregate quality权限；实际session待回报。
- F9条件工程单卡已冻结于`F9-b80-output2560-full96-seed08-engineering-proposal-v1/`，卡ce4231d9、proposal a2bcfa90、final pins908d42f0；仅单seed08、full34／68批，须先读token400 full96再决定执行。4项元数据检查／8负变异通过，无tokenizer／GPU调用，不继承3072 formal timing资格。
- F3 full96原机械13674实际EXIT0，SAFE `F3-joint-json-full96-intake-route-preparation-v1/original-three-mechanical-once-preparation-v1/SAFE-completion.json` SHA `4c51a6ea4e7d98bc8f387513be54b947069791e7ea91e254fdf076b5d7da7cfe`；工具元数据`87fb70a6b1d8155700acb260b747c61f6edced22fe12f18a138a174137184706`显式省略SAFE stdout，不冒充完整原工具字节。三67 replay/build各一次、verify0，后续ROOT字节登记及材料仍待完成。
- F8 byte v2 c26162修复经ROOT完整diff审阅、独立b7aae646限定复核7项（5复用＋2新增）通过；新权限`F8-all3-mechanical-root-byte-registration-preparation-v2/ROOT-signed-byte-audit-release-v2.json` SHA `969c3965e63252631293015a8829c9f2add24f58dbead2ce3d756bec247c65b2`已启动ROOT实际session30403，全量byte／物理库存结果未返回，不提前宣称通过。
- token400 PRIMARY源码b6f9a53d已完整diff／源码审阅，独立限定receipt `f9047578afac0e1a93ea533a9916bc38d3fa0db4422f53f923278989b3b2f86d`，8项复用合成检查通过；实际材料190files／29场景／144槽分开。新当前writer／byte观察准备中；历史97515 ownerPID未留证则保持未知，不编造PID；尚无PRIMARY启动权限。
- F8 byte登记拒绝已有确定性结构复现：旧9345 `audit_seed`在actual08结构元数据＋byte／inventory stubs上于closure guard失败，完整captured snapshots为114，而声明implementation dependencies为21。旧helper混同两者；原实际异常详细trace未保留，不能称已恢复原trace。新v2的同结构回归GREEN，实际全量byte／物理库存检查仍未执行；旧claim／失败保留，新增独立diff复核与新权限准备中。
- F3 full96原三seed机械入口1a051f7d经ROOT完整源码审阅、source_profile预读缺口已在冻结前修正；新权限`F3-joint-json-full96-intake-route-preparation-v1/original-three-mechanical-once-preparation-v1/ROOT-signed-original-three-mechanical-authority-v1.json` SHA `7ca579ee3fbb800058af85267e1e1880ae4cca7e6c5eed4159104848a411cf24`，仅原67 replay／build每seed一次，无另行verify replay／材料／judge／quality权限。实际session待custodian回报，874批／seed与288窗口seed分母不混用。
- F5 cue原28647尚无终态；custodian于17:05–17:06 UTC测得其owner Python PID61688 CPU增加约63.3秒／67.2秒墙钟，属实际CPU活动证据，不推算裁判调用数或成功量。原入口继续，不因无stdout认定停滞或重启。
- F8 ROOT byte登记helper9345d1e1一次实际执行失败（tool484b37 EXIT1，active_seed20261008／ValueError），原claim及`actual-byte-audit-consumed-failure-SAFE-v1.json`保留；尚无INITIAL。这是新增字节登记层拒绝，不能改写原36544机械EXIT0或归因模型失败。正以receipt／envelope元数据最小回归定位，不重跑原native认证、模型或已消费入口；修复如需新版本将另封存。
- 当前SAFE矩阵更新为`current-screening-evidence-matrix-v9/matrix.zh.md` SHA `fa7df6f7eb1100a8d41a62668c4a7dc00764e89b3889f88fef2e64cbe1ce5f3f`：v8所有18质量／4风险／3历史机械记录保留，仅追加F9 partial＋NOT_RUN、F8机械handoff、token400材料3项时点状态；118来源pin核对通过。`adaptive-one-next-value-memo-v1/memo.zh.md`建议先消费pending证据，必要时单点target15或有明确方向机制时替代为5前／1后；只是条件建议，未执行或创建卡片。
- token400 full96新版后继绑定`token400-full96-after-accounted-partial-finite-B60-root-entry-preparation-v2/root_entry.py` SHA `328a3102c263fb68ea80b30ae228ecaa5ec7400fe8882300aa9afae83570edc0`已完整diff审阅，16函数AST不变、5定向测试通过；只连接新finite8a8c，原queueb880及current21保持，未来实际finite证据NULL，无启动权限。
- finite-B60后继入口已按实际新F6身份更新并保持inactive：`summaries/finite-B60-after-F6-accounted-partial-successor-entry-preparation-v1/root_entry.py` SHA `8a8c60f8e54ad8309827af331640e1de4a301ed2d60de796a910c02d712bcde9`；仅五处绑定差异，原终态／成本／drain检查不变。10 owner方法含8复用＋2新绑定；独立2项重叠检查PASS，receipt `243c92a8ab90f00012f5ca3b85fe588172f42ec845ba1db15df1d3ac74a5f526`。未来F6结果仍NULL，不能以F9的NOT_RUN替代F6真实终态；token400后继绑定相应更新准备中。
- F9容量后续source-only分析指出：finite-B60 matched29不含故障场景F2-W11_E020-S00001；token400 full34包含它，但source-token400也不是完整prompt容量保证。拟冻结条件性单seed b80／output2560工程对照，仅改变输出预留和实验身份；已知故障批输入余量204、此前输出最大1820，但未知后半批容量与输出需求不能外推。等待token400 full96结果再决定执行，不重启原09／10、不视为新基线。
- token400 f3c一次材料join原97515实际EXIT0，SAFE `evaluation-only/F1-token400-matched-risk-source-join-preparation-v2/safe-preparation-handoff-v1.json` SHA `b2084b07e3bed32d8e3b69cbee94ba43697b5590cfeced44cb9f4a7f4dbc28f0`，finalization `a5739ddfa7004fb3170d96b632ac13a25601a1e19b27c9db747aa0835c278344`。29源场景／144固定记录，171严重claim occurrence／85 annotation不是独立根因或确认错误；风险仍unassessed、native0，准备PRIMARY精确入口。旧v1失败不被此次成功反向解释。
- F6新入口独立限定复核SAFE `summaries/F6-after-F9-accounted-partial-independent-review-v1/receipt.json` SHA `ce011e2a9888b8f015671adcc20f71628b8b50ee77cbdb300e99ec623d7e041c`，3项已有合成测试复用通过、0新增独立方法；未发现NOT_RUN或执行绑定阻碍，不等于真实GPU验证通过。
- F6 rolling新入口6446fac4已实际启动session92958（首tool7654a6，10秒仍运行），权限700ae940；独立审查未发现新NOT_RUN／execute绑定阻碍，原21a六腿、efd7 whole及逐腿drain保留。尚无交付或质量结论，ROOT独占该GPU session。
- F3风险review的ROOT实际byte／进程观察已EXIT0：`summaries/F3-risk-review-root-observation-preparation-v1/actual-root-observation-v1/root-observation-proof.json` SHA `b091d0f3c4c215c7e62fa6dd27b7f52e54b2d6d57bafe35cf355bf8b0cfac915`，两次完整195＋420库存一致、目标writer快照为空，不声称全局idle。新独立review29权限 `summaries/F3-risk-review-ROOT-registration-v1/ROOT-signed-launch-v1.json` SHA `f71399aea486ca8f29f0f1b745236af1df6d87310d0dae010350d78ef989425e`；排在当前F5 cue之后、B1之前，尚未实际dispatch。不自动追加ADJ或导出最终风险结论。
- F9 full96受限诊断已封存：`summaries/F9-b80-full96-seed08-terminal-metadata-diagnosis-v1/receipt.zh.json` SHA `3fc62b26b551fdc2ff3e90de6916a5b90fb38c49562b39f0d596ef11b4c3e24f`。ROOT核对三卡prepare仅除seed／recipe_id后的相等性、原实际EXIT1与尾部缺席，签署NOT_RUN disposition `750ea64b2b9136f59d30be14a60a5e54f2a03a5b4ef140606feb1dd01d69176d`；09／10预算失败只是冻结源配置下预测，不冒充实测，成本NULL。F6新入口6446fac4独立权限 `summaries/F6-rolling-after-F9-accounted-partial-root-entry-v1/ROOT-signed-entry-authority-v1.json` SHA `700ae940b0f5b361acb3a6cf1abe8408b163bae5b94d86f21efb2ccf8161c87a` 已完成admission，实际GPU启动仍待独立复核完成；原成功专用入口保持。
- F8机械原session36544实际EXIT0，三seed handoff `evaluation-only/F8-all3-original-native-admission-v1/production-handoff.json` SHA `6962773b68b8e341595bbef1433058e514607e6c5b3c4f3447c60386591a87da`；原proof仍需ROOT字节登记及单独INITIAL权限，hold54保持封存。F9 matched48风险PRIMARY原16685实际EXIT0，29项中24accepted／5judge_failed、34尝试；不是最终风险结论。F5 cue PRIMARY已实际启动28647，token400新v2一次材料join已实际启动97515；均不重复启动。

- token400新观察31495实际EXIT0，SAFE `evaluation-only/F1-token400-risk-v2-root-observation-evidence-v1/verification-inventory.json` SHA `3376b8673c33936c4820b5d09e0f0cdf7aa4cbd0eef391907efa1f6b08ddaf52`；两个快照和字节核验通过，新v2相关writer／风险历史／attempt-start均0，旧v1 consumed失败记录明确保留，不宣称全局idle或未来lease。ROOT一次新材料权限 `evaluation-only/F1-token400-risk-material-once-root-authority-v2.json` SHA `2bd9ae3a00ec4b03fc69c9cb13bf497bd2c79d646169a486292cbf06136a69c1` 已签发，仅f3c新版本一次join，实际结果待回报。
- F8 v2原机械认证已实际启动session36544，三seed原proof／envelope认证中，无INITIAL、generation、judge或hold导出权限；后续登记必须绑定本次真实结果。

- 边界偏差记录：F3 review观察helper准备期间，naturalness_design的一次宽范围rg误扫F6／F7 `PRIVATE-original-proofs`，工具显示哈希匹配行；未将其用于本任务证据，也未用于语义判断。已停止该搜索范围，改用明确源码／SAFE路径，单独事件记录待冻结。此偏差不能记作合规私有byte-only检查。

- F8 once v2 8969969c已完成ROOT完整差异审阅及独立复核f3b0d313；仅增加固定阶段／seed与私有traceback，旧2c172保留。独立 `summaries/F8-all3-release-preparation-v2/ROOT-signed-mechanical-release-v2.json` SHA `13a5cffe7a6f34cf64323cdb6f1a034a03366f67518d6bdb53049fb4dfb214d8` 已放行一次原c3bad三seed机械认证／envelope核验；实际结果待custodian回报。INITIAL仍需后续独立原proof登记及单独权限，hold54／确认48仍封存。

- F9首08失败的受限元数据诊断已确认：第35记录为setup_failed／budget，tokenize阶段input5364，completion_dispatched=false；5364＋3072输出预留＋64安全余量＝8500，超过8192共308。此前34次dispatch均交付，之后33/68批缺失，不是68批全部解析失败或输出截断，也非272次总预算耗尽。另两seed源请求／配置一致性正在核对；如同样必然触发，保留NOT_RUN并记录明确停止决定，避免无信息重复。原尾2提案仍未执行，不修改原卡或把未知成本写成0。

- token400新材料观察实际session31495运行中：新observer86d3c7d5经ROOT完整差异审阅，独立request `summaries/token400-risk-v2-root-observation-request-v1.json` SHA `f2af57a855b857cfc9503d63c4630916cab035357f74f9a616e668ff7c3aac8f`。保留并重hash旧claim71b／failure6b259等历史，仅要求新v2未执行；无材料或裁判权限。观察结果未返回，不作无writer结论。
- F9原09／10尾入口342afa58已冻结、ROOT源码审阅完成；它保留首08 partial及成本，原卡／配方／输出路径不改，用原9c0首失败停止及efd7 fresh drain。尚待SAFE失败诊断和独立ROOT disposition，未实际启动。F3 full96材料controller9a6c33c0源码差异已审阅，实际原67／61机械认证及材料仍待具体登记；F8 once入口2c172的认证／INITIAL两阶段准备完成，补充私有失败诊断记录的新版本与独立审查进行中，均未实际认证或解封hold54。

- F9完整96首seed08实际partial，原session55808 EXIT1，原driver按首失败停止；09／10尚未运行。08 trial为17/34场景complete、34导出、391.549035秒，原journal于16:27:34 UTC结束；工具证据在 `summaries/F9-after-actual-F3-root-registration-preparation-v1/actual-root-preparation-v1/ROOT-actual-F9-tool-terminal-v1.json`。失败类别待受限元数据诊断，不能先声称output-limit或质量失败。原F6-after-F9成功入口／70be构造器未消费；拟另立原09／10尾队列并保留08失败，不重跑08、不改配方，当前未授权实际尾队列。
- 六槽材料原73728实际EXIT0，tool SHA `fb3f3457e4f7c22b439de64520db2c7a65391c688a264a3e85b0598a6a71ddf4`，SAFE `summaries/F6-F7-original-producer-plan-v8-intake-integration-v1/enrollment-material-preparation-v2/material-manifest-v1.json` SHA `d1e6ce83b37eaf2ef693a2a16fd0b1267b849324a2ff1995fc4c3f473a87d1c6`。四槽各67文件／48材料，两槽各2文件／48 MAIN not_run NULL；总固定288，standalone认证0、native0。F9 matched风险原90f／e275已启动session16685，与本次full96 partial是不同实验身份。

- 当前SAFE汇总为 `summaries/current-screening-evidence-matrix-v8/matrix.zh.md` SHA `211284a2c30e9afeda1d875f3a436dd2bf1d49f307e2f154ca2f2a624e53e9dc`：18项质量、4项风险、3项机械记录，v7所有原行／pins／中文保留，仅追加B10完整96；111个唯一来源pin通过。六槽材料b07已实际启动session73728，结果待返回；F3 PRIMARY后保留该材料空档，完成后再按原权限接F9风险。

- B10完整中文解读 `summaries/F1-b10-full96-three-seed-screening-v1/interpretation.zh.md` SHA `31e1d7085a66d464d650f96b00c1c63bab6245fe2eab37bb3babc9b5df5fcbb0` 已完成；原summary85d221／report568990保持。B风险剧集三个seed为−0.6667／−0.3333／−0.5000，逐作品剔除仍负；完整代表剧集删任一作品仍正但删Frieren仅+0.0533。电影删Suzume转负，代表两类自然度均约−0.0463。B代表剧集17/18子集负均值对应全分母界跨0，不宣称确定伤害；独立严重根因仍未核定。

- F3风险PRIMARY原session16352实际EXIT0，29任务中23成功／6裁判失败，共36尝试，仍只是PRIMARY阶段。真实tool9f732424与末次D0 209dcf33保留，失败不变成模型错误或自动追加重试；后续review／实际争议裁决准备中。
- 六槽材料v2 b07dc3eb的P2回归通过：末槽proof／authority缺失或漂移均在marker及首次writer前拒绝。ROOT独立登记 `summaries/F6-F7-original-producer-plan-v8-intake-integration-v1/enrollment-material-preparation-v2/ROOT-signed-exact-six-enrollment-v2.json` SHA `05cf4b3989c6a78263d2ea6d8ab1ed970cf67b7f3aa93d0258e55a60972b57a1`，仅放行原六槽一次材料prepare；custodian取得新鲜组间drain后执行，尚无材料结果／新裁判权限。固定288中的96 MAIN not_run仍为NULL。
- F9登记构造器在ROOT执行后发生文字与raw-tool预hash修订；实际执行版本 `dec336db…` 已恢复到 `methods/source-publisher-history/dec336dbcd1bae86dd20a60b1f317995de226dd4ce576459e7fdc737e2cc1e6e.py` 并精确核对。实际receipt d3a438／权限df2814保持原样；后来2af826／7ff79仅未消费源码，不冒充实际执行身份。实际33af入口、原F3工具包及独立验收未变。

- F9 b80／3072完整96已实际启动session55808，原33af入口和原68批×3队列不变。实际F3三终态、完整all13账、原driver／历史drain及ROOT工具结果分别核对；新独立权限 `summaries/F9-after-actual-F3-root-registration-preparation-v1/actual-root-preparation-v1/ROOT-signed-F9-authority-v1.json` SHA `df2814c88b454e09ba963daf47500067cc901e8b00118527bdd6a90f8c22b818`。testimony时间为ROOT登记时重新确认，而非声称工具返回的精确时刻；保留原tool包。后继F6 rolling→finite-B60→token400 full96→原future36仍串行。

- B10统计session76211实际EXIT0，receipt SHA `245a74e94ff5f002982f117be01cebaa637682a6a77f6ba5e0c60d5c8e1b6608`：六槽库存通过、原V7严格96验证3次、原统计一次。`summaries/F1-b10-full96-three-seed-screening-v1/report.md` 显示代表剧集完整配对Δ+0.1648（35/36窗，固定分母缺分界[+0.1759,+0.2130]）、电影+0.0093；第二半剧集风险Δ−0.5000。缺分界不是置信区间，完整配对与固定分母不可混用；候选288语义已知、C0 287/288。进一步逐seed／作品解释进行中，尚不能放行或判为基线胜出。
- 六槽材料入口e681独立审查发现P2：仅校验proof声明，末槽实际proof缺失／变更仍可越过前置barrier。仅合成复现，不代表实际文件损坏。旧入口未执行，修订另立v2，在首次marker及材料写入前对全部六份proof／authority做字节核验，不重复typed认证。

- F3完整96原session53679已实际EXIT0，driver于16:14:01 UTC结束，原工具终态保存于 `summaries/F3-all13-accounted-after-tail3-root-entry-v1/ROOT-actual-F3-tool-terminal-v1.json`。下一项F9完整96独立登记准备中；未继承F3质量权限。
- B10 ROOT字节audit session49092 EXIT0，`summaries/B10-full96-root-terminal-byte-verification-v1.json` SHA `5e934ef16e9f72c732676375012d7442c0c728e9d501ccda2701c1a426bba812`，三库存2338／2228／2206、唯一文件6824。精确六槽提案9e490a7d已完成ROOT审阅，新一次统计权限 `cards/F1-b10-full96-ROOT-execution-approval-v1.json` SHA `785bc4fde805d441068dfdddfe2b060d23cf9d970b99ef17e3509b71267dbfed`；按原3dc9入口执行，结果仍待返回，不提前作质量结论。
- 收敛缺口审计 `summaries/convergence-gap-audit-20261008-v1/memo.zh.md` SHA `336b6b345150a0892f9aed34a25f9a9e768238a0214a1cfee9e44a407f9db0c8` 已核对27项要求、163个输入。优先完成现有质量／风险、common与origin、长期记忆和审校，再由机制选择少量内点或交互；高优先级有界探索已有结果，不再笼统称未探索。独立确认、正式计时及可能反转结论的缺口仍在，尚未收敛。
- F9计时ABI独立限定审查3c0dea62通过；token400 full96后继入口bd7c12d4经ROOT源码审阅与独立审查a303a4ee通过，只是源码资格，实际finite前序及容量仍待验证。token400风险材料新版本f3c65989只修复已复现的scope-window接缝并增加私有失败阶段记录；原失败保留，尚无新的真实材料执行。

- B10原5a74 SAFE导出session27517 EXIT0，`evaluation-only/F1-b10-full96-mixed-three-seed-terminal-safe-handoff-v1/actual-safe-handoff-v1.json` SHA `8ad895ef0df4daaf53804cf2f74c1a096b725ee71f7a458671ac9d3c375b46d6`；288主评＋288复评＋56裁决＝632逻辑／实际尝试，固定288。三库存2338／2228／2206文件，原trial707.6872／731.5703／699.3710秒各一次；09保留445次尝试中的一次output-limit失败及恢复，三whole为T/T/T。原完整full34 C0不是matched29对照，formal／同口径fullflow ratio仍NULL。ROOT字节核验与精确六根统计登记准备中，尚无新质量结论。
- F3严重风险PRIMARY29已按原52a8权限实际启动session16352，接续B10真实终态与D0 d6167307；全局裁判并发仍受原guard控制。此次主评不等于风险最终裁决。
- B10原session1378实际ALL3 EXIT0，ROOT工具终态证据 `evaluation-only/F1-b10-owned-session-evidence-v1/tool-terminal-result-v1.json` SHA `e846d4ceaf16e5c9b60abd93a3f94c09fe8b7e2bcc4485c0a8a6876947d06017`；三seal ffbf9077／1927e25f／605594c6。仅授权原5a74 SAFE exporter一次，统计未释放；评审队列随后接F3风险，不等待统计。恢复seed09与原444／445／444调用及成本身份保持。
- F6／F7原始producer-plan评价入口独立版本dd5ddd93已通过13项定向检查及静态差异复核5acc34d4，ROOT已审阅完整差异。真实机械6槽2dbb证明保留；固定288包含192 delivered及96 MAIN not_run NULL。下一步准备独立登记与六槽一次材料入口，未调用真实prepare、helper loader或裁判。

### token400／600统计完成与后续真实验证

- token400材料源码最小接缝已复现：13ce传给原13e `_card` 的是五字段模型请求对象，缺少窗口元数据的`split/scene_id`；仅换成冻结scope-window形状即可由RED转GREEN。仍未证明原51159实际到达该行。另分别核对同内容不同路径、前置inventory以及卡片／seed／native lineage可能性，禁止原材料重放；后继入口将保留私有阶段／traceback及对外opaque摘要，旧失败不覆盖。
- F9 full96正式计时ABI v2源码freeze `summaries/F9-full96-formal-timing-abi-v2/final-pins.json` SHA `2212f64aacd939e3b8a69d2460236c3ffa789011622188ab2803466d9a46ee23`，7个不同离线方法通过，独立审查中。真实geometry为34／4297／68／96／480、output3072；未来计时卡明确补列完整114项snapshot闭包，保留原21项及原卡。没有真实计时、pilot或finalist。冻结计时规则是区间**半宽**≤15秒，不是总宽≤15秒；未改policy。
- 位置诊断完整中文报告已保存：`summaries/token-batching-position-score-join-preparation-v1/interpretation.zh.md` SHA `29f034b0314f73dcbf1e71eae95165d7292e7aea96397ce19a07d9a14c567b32`，包含全部三轴正负／空cell、覆盖及限制，不新增计算。finite-B60后继入口fe263272已完成ROOT源码审阅与独立窄审查a06e19b3；实际F6前序证据仍NULL，尚未启动。该准备不证明finite-B60交付或质量通过。
- token位置SAFE join v2唯一实际调用bedf83 EXIT0，0.798秒；receipt28518fcd，输出 `summaries/token-batching-position-score-join-preparation-v1/descriptive-position-join-v2.json` SHA `c2c35e5d4b99aff1a4ac1bc7b0ffa5f26a923b35fbc21fbb054a143fb14d32cd`。没有重评／compare／bootstrap／native。代表剧集batch early/middle/late：token400 +0.074／+0.356／+1.444，token600 +0.478／+0.556／+0.667；但400 early三seed为−0.222／−0.222／+0.667。电影代表scene late两者均−0.556；400风险电影唯一跨两批窗口−1.333。小cell、作品／系列与分组成员差异明显，不支持位置因果或token400／600直接交互结论。token600同一窗口两条自然度NULL在不同轴重复显示，不能相加；空层仍NULL、每contrast固定144。
- token400材料唯一入口session51159实际EXIT1，未产生输出目录，claim71b16492、failure6b259118保留，无native调用。原包装器未保存内部traceback，具体失败谓词尚未知；已启动受限源码／闭合元数据诊断，禁止重跑13ce、认证或私有join。新回归必须区分可复现接缝证据与原异常推断，不能把材料失败算模型质量失败。
- F3全96首seed于15:48:14 UTC原journal complete／EXIT0，第二seed启动；session53679继续。B10第三seed正在复评，尚无三seed质量释放。
- token400只读观察session74906实际EXIT0，证据 `summaries/token400-risk-root-observation-preparation-v1/actual-root-observation-v1/verification-inventory.json` SHA `91f01671924c7975563f89c2ebada5c07ed2d7b22deb6e3c14d963471aa9f5e3`；两次快照及精确字节核对通过，0正文解码、未发现既有带标记风险历史。新独立observation2447168c，最终一次材料权限 `evaluation-only/F1-token400-risk-material-once-root-authority-v1.json` SHA `4d55fb3aaedc4e24353029ff6e5fef3082f71b9f732272164400461860744367`。仅放行原13ce一次私有join，无native权限。首次登记的NULL observation对象因PowerShell成员已存在而未填入，未执行且已按原字节保留c7ed历史；执行仅接受修正后的4d55。
- 位置分数join的v1权限642b未消费即撤销：发现原142e读取卡片geometry但不自行重hash。独立v2入口33e67a1a增加全部原卡片前后字节核验，7项合成检查通过；新 `cards/token-batching-position-score-join-root-release-v2.json` SHA `f276abdece4fb37e92497f607b5bfd41730417792b58db7b815222f380180ae8` 仅放行一次现成SAFE数字表描述性join，不重评／不重bootstrap，不读取私有正文。实际结果待返回。
- B10全96统计接入源码ec5af493／入口3dc9d618已独立窄审查通过27f8e6d8，保留原full34 C0、recovered09及全部成本身份，formal ratio=NULL。实际候选三终态仍未齐全，未放行统计。B10原1378第三seed已进入复评。
- 六原槽新认证session93239实际EXIT0，SAFE `summaries/F6-F7-original-producer-plan-once-entry-preparation-v1/actual-original-six-derivative-once-v1/SAFE-completion.json` SHA `2dbb031527d624adf92a0deb040b8187cfa6b4b337599afd7648550814a132bf`。认证6槽、交付4槽，审核346.995秒；新generation／material／judge均0。F6术语三seed与F7场景08各48 delivered；场景09／10仍是AUX失败、MAIN not_run各48，不改成语义0，未知边界及原失败成本保留。下一步仅准备匹配新helper的V8材料接入，不重复原认证。
- token400风险前置只读观察入口b6f389f3经ROOT完整源码及窄diff审阅，request7183ba61实际session74906运行中。两次目标writer／精确六根字节／既有风险历史检查，不宣称全局idle或未来无writer；无关裁判活动保留，不触发材料或模型调用。真实通过后才独立登记一次私有join。
- producer-plan独立窄审查836ddb2e通过，6项检查＝5项复用＋1项新增防fallback，原件未变。ROOT 15:36:26 UTC新目标writer查询无匹配；唯一缺失命令行项经服务CIM核实为CodexSandboxService，局限单独保存，不宣称全局idle／原子锁。新独立权限 `summaries/F6-F7-original-producer-plan-once-entry-preparation-v1/ROOT-once-approval-v1.json` SHA `c798da4266238e3d618b22b0f6ee3b2e2d77a7df9a4345772f1f27bc0bce7905`；实际认证session93239运行中。仅原六槽机械认证／验证，禁止生成、材料加载、裁判及自动重试；旧13339 STOP保留。
- token位置／源暴露映射 `summaries/token-batching-source-position-diagnostic-v1/source-position-mapping.json` SHA `32bc3f00cc55e2137e47e1975b5f7838e501c64061414beafb17d7bee069ea81`，4项离线检查通过。token400 matched48跨批2／尾7／首14窗；token600跨批0／尾11／首20窗；计划token400 full96跨批9／尾12／首34窗。属于看过SAFE后的描述性诊断，沿用原位置定义，不新增确认终点；未读取分数／译文，score join尚未授权，不能把源位置当native cache／attempt证据。
- 15:34:56 UTC ROOT实际观察F8队列session64466 EXIT0，三个原seed全部complete；全13槽保持8 complete＋2源准备failed＋3 F8 complete。实际tool、全13登记与独立F3权限保存在 `summaries/F3-all13-accounted-after-tail3-root-entry-v1/`；新 `ROOT-signed-authority-v1.json` SHA `584b5b72f0b3796133faae8f6b8f316b9892345d32e6a151482ca7e62902bfd3`。F3完整96原入口实际session53679已启动，后续仍按原序串行。F8质量／净改正与误改尚待独立评价。
- 当前汇总升级为 `summaries/current-screening-evidence-matrix-v7/matrix.zh.md`，SHA `eb58aebb8307236e8119dff53fb31a56e1eccf1142a4302f93a5902918f2daeb`。17项质量、4项风险、3项机械记录；v6全部旧行、pins和解释保留，仅追加已释放token400／600。确认48仍封存，探索尚未收敛、基线不变。
- token600实际统计session53513 EXIT0：精确六槽inventory屏障及原core48／dfbd验证后，一次原13e／f808。SAFE summary SHA `5a654c8eaad20eef2d05c4a5dbf62b68b1c30be26e0b34f88b49d9ff62eaafc5`，中文解释 `summaries/F1-token600-matched48-three-seed-screening-v1/interpretation.zh.md` SHA `a9e4a3d6b872d90935aa6aa347ecb62fd2bb550ae39de743f528490998165aec`。代表动画+0.6481，三个seed及逐作品LOO均正，但Komi负且自然度−0.1296；代表电影−0.1208，三个seed及逐作品LOO均负，去整个SAO cluster后为0。风险动画+0.3333去Fate约0，风险电影+0.0833去M01为−0.2222，不能把均值当一致收益。
- token600两条真实失败仍计语义0／自然度NULL，固定144语义已知、自然度142已知；电影自然度完整配对17/18差+0.0875与固定18窗口界[+0.0167,+0.0833]分别保留。whole F/F/T、原80／80／79调用及全部trial成本各一次，formal ratio仍NULL，严重根因未核定。不能据此断言token600优于token400或进入确认。
- 正式计时ABI单次只读host smoke实际EXIT0，SAFE `summaries/formal-paired-timing-real-abi-host-smoke-v1/actual-once-v1/SAFE-host-smoke.json` SHA `e79c32b15be5d72c0b8b1ac6c566fe459d2d5600a298d2f26f32a20d5cab9a10`。两条查询EXIT0、解析完整、分类busy；未知WhatsApp GPU行保守保留。无lease、native、重试或清理，不构成drain／quiet／正式计时资格。
- 新producer-plan机械认证入口 `summaries/F6-F7-original-producer-plan-once-entry-preparation-v1/` 已冻结29e6d519，绑定6d376f75 helper与独立输出；10项检查包含9项复用及1项新binding检查。旧13339失败与marker保留。真实认证仍待独立审查、新ROOT目标writer观察和独立登记，不把准备通过当真实六槽认证通过。
- B10原session1378于15:26 UTC已进入seed09；seed08原主评96／复评96／裁决26完成仅为进度，三seed完整终态与SAFE导出未完成。F8原session64466仍在接跑。后续GPU顺序保持F3 full96→F9 full96→F6 rolling→finite-B60→token400 full96→原future36，不并行争用推理GPU。

### F8三卡接跑、token400终态与B60解释补充

- token600一次d9f2 SAFE导出10347 EXIT0，handoff c69a6b2f；142主评＋142复评＋28裁决＝312逻辑／312接受尝试。ROOT字节audit `summaries/token600-root-terminal-byte-verification-v1.json` SHA `509f480615106af0388be049b5bdfc6a0ad57fc60e961b1b69a74ece2778df8d`，精确1156／1101／1143文件、3439唯一文件。原完整trial604.6811／602.6218／569.3020秒、whole F/F/T，质量统计待精确六根释放。
- F7主语义评价经ROOT审阅5483401f retained entry及86项pins，独立launch `evaluation-only/F7-natural-main-material-preparation-v1/root-activated-natural-main-launch-v1.json` SHA `fc55cb403ddc94b3d1703b027e21b92156ecb5123b1efcff803bb40c9a6d5eb9`。只在既有队列及fluency PRIMARY之后执行原af512三seed／固定144主评、全窗复评及实际争议裁决；不重建材料、不自动统计，fluency与语义量尺分开。
- 正式计时真实ABI v3独立窄复核通过a0441065，两项检查确认归档／receipt碰撞先于查询及副作用拒绝，正常固定namespace交接通过。后续准备只读Windows查询smoke，当前F8／B10活跃事实不能当quiet；尚未授权真实计时或pilot。
- token600原31820实际ALL3 EXIT0，三outer25588ca5／1d682712／fcbe2c8f封签；真实tool记录 `evaluation-only/F1-token600-owned-session-evidence-v1/tool-terminal-result-v1.json` SHA `6ca455f4f77a91c29f5138dbc7e9595ca573f1993d8306e9fd64a2b3a2e5609d`。最新D0 a2261782后原B10 e2bb／1f565实际session1378启动；token600一次d9f2 SAFE导出并行，不等待统计。原F/F/T、两条真实delivery-zero／自然度NULL及80／80／79调用仍保持。
- F8实际接入前置提案冻结 `summaries/F8-all-three-terminal-handoff-readiness-v1/readiness-proposal-v1.json` SHA `0aa6d34fdab1e88ff18d4ee9d40ec4a8e602fb2d3f0ef1f9e3c7963c895d2612`，SAFE4ba47acf。明确main144与before/after144对／288侧分开，开发90／保留54分开；253c／05175当前修订0ca495仅源码／合成资格，实际INITIAL loader／projector仍待认证。未来terminal／proof／材料权限为NULL，不能从入口存在推断真实质量资格。
- 六槽验证入口缺失文件诊断已冻结：`summaries/F6-F7-original-six-once-missing-file-diagnosis-v1/SAFE-diagnosis-receipt-v2.json` SHA `b3655108925cc59bde7bd12e7cd592a5c1f7354d63144c341e142d3753436144`。原2834把复制后runtime session-plan父目录用于定位batch-options／packed-mapping；实际worker先从prepared session-plan解析再复制，两份plan字节相同，但辅助文件只在prepared存在。该候选缺失路径构造的errno2文本hash与原opaque错误hash完全相同；原traceback未保存，故明确为hash佐证推断，不冒称观察到traceback。第0原目录5739文件未变；新derivative绑定真实producer plan及原侧文件，待独立审查后另签，不复制文件伪修复旧运行。
- 正式计时真实ABI v2 freeze `eeaf7b3bc842db7333c9478aa388ae9463a7fa5e706ef99da82ee6f667e8989c`，19文件、6项定向合成检查；修复完成marker接续及可选NULL处理，保留必需cache证明。正在独立复核，尚无实际host／native／pilot。
- token400完整96 source-only准备已冻结，SAFE handoff `summaries/F1-token400-full96-source-audit-v1/three-seed-safe-preparation-handoff.json` SHA `c3c0998ac38f251f165d76c53f1f28127bcc03283e52f0ffd1b41766a99f9000`，queue b880c392、freeze f97e7e60。每seed34／4297／96／480，132批＝98非尾＋34尾，目标1–63cue、9评分窗跨批；三次真实dry prepare及29文件closure通过，无新模型调用。排程决定：保持F3→F9→F6 rolling→finite-B60在先，再token400 full96，之后原future36；此为准备／排程，不是执行授权。全96实际容量、交付及质量仍未知。
- 六原始terminal机械认证实际13339 EXIT1：第0槽F6 terms seed08在authenticate_original_trial出现FileNotFoundError，成功槽0、validate0，其余五槽未尝试；SAFE rejection70f4803a、once marker0091006f、invocation0f609d35保留。新ROOT批准c072aa9e限定原2834一次认证，原23,814文件字节稳定、14:56:17 UTC目标无writer观察；F8及token600独立目录活跃明确保留，不声称全局GPU空闲。已授权只读缺失路径诊断，不重复原入口、不把验证失败当模型质量失败。
- F8 seed08于14:52:11 UTC原journal实际complete／returncode0，随即进入seed09；ROOT64466仍live。单seed命令结束不是三seed质量结论，完整机械／before-after评估接入准备中。
- token400中文解释 `summaries/F1-token400-matched48-three-seed-screening-v1/interpretation.zh.md` SHA `edd4aa1084a1fd6824608e01e00e435ae6950c28e424e86487cf4564b792ef8a`，补充dff7426d、完成收据639a6476。动画六作品语义均正，去掉最大收益Dungeon仍+0.3111；自然度代表动画−0.0741／电影−0.0208，风险电影自然度+0.1667不能抵消语义负值。历史计数map287402f7覆盖4297源cue，准备核对全34源身份后复用；原21.318秒取得成本单独保留、不重复加到每seed，未来fresh端到端计时必须包含必要计数或明确匹配预供缓存范围。
- token400统计83493实际EXIT0，六根屏障及原V7验证通过，一次13e／f808；SAFE `summaries/F1-token400-matched48-three-seed-screening-v1/summary.json` SHA `866e152f0095653b006b688fa903392ca93f0dc8fe86b46257fc37801f9daeeb`。代表动画Δ+0.5370，三seed +0.3889／+0.5000／+0.7222，全部LOO正；代表电影−0.0583，三seed−0.175／+0.05／−0.05、全部LOO负。电影区间上界约−1.11e−17按零边界解释，不能声称严格负；风险动画+0.2778但09负，风险电影−0.25且全部LOO负。两臂语义／自然度各144已知。已安排source-only完整96三seed扩展准备及候选特异严重风险准备，以消除类别／场景异质性；未授权新生成或确认，正式耗时仍NULL。
- token400统计释放 `summaries/F1-token400-matched48-statistics-preparation-v1/root-exact-six-quality-statistics-release-v1.json` SHA `53b6a985c79111b49d19fef1b4d756befb278737bb690ffad1ae0dfea67d843d`；ROOT审阅10e18502入口并核对198项指针，实际session83493执行一次原V7→13e／f808。尚待结果，不把统计启动写成质量结论。
- F3后继F9完整96入口已更新为v3，source33afab6a、unsigned3de75af8、readiness015152f3；仅复用已合格efd7 observer，16函数AST与v2一致，16项合成检查通过。F3入口02cdb304及F9入口均等待真实前序终态后ROOT另签，未提前运行。F6后继入口按相同观察器准备，旧版本不覆盖。
- 正式计时真实ABI独立审查receipt c07874b9确认两项P2：固定namespace完成marker没有接续清理步骤；原native可选token字段NULL被额外reader误拒。五项合成检查（两新增／三复用）通过，30文件不变；修复另立v2。实际Windows组合／正式pilot仍未验证，不放行计时。
- F7 fluency PRIMARY入口b49d10c1经ROOT全文审阅及12项依赖字节核对；精确15字段登记 `cards/F7-natural-dialogue-fluency-primary-root-admission-v1.json` SHA `77cdf2f7968aebe04fc4d4029295053c26d1d8b4f25d5ce8a0a256047e304b0f`。允许既有裁判队列之后一次原288 PRIMARY，原global6／max2／600，run后drain再seal；未启动，不含review／adjudication／自动resume权限。实际plan已准备不是质量结果。
- token400一次SAFE导出98561实际EXIT0，handoff `evaluation-only/F1-token400-v7-three-seed-terminal-safe-handoff-v1/actual-safe-handoff-v1.json` SHA `f5527fd529099eb1b58a1f65e429d7a674e650234909e757a35cc6345fa89613`；ROOT复用字节审计并只换精确输入／输出绑定，`summaries/token400-root-terminal-byte-verification-v1.json` SHA `6199e0aaf3442201393753eb2c6085a4140f5703f682b7f938313deb20c9772a`，核验3506唯一文件、三根1165／1165／1132，未解码私有正文。生成均110首次成功调用、whole T/T/T，完整trial561.032／565.867／559.363秒；同范围六根配对统计待单独释放，暂无质量结论。
- 正式计时v2针对P2绑定缺口的独立复核通过，receipt `466f431dfe268ded7360a037e6ab4019312719b6481cbece4d7a4f1dab4f13f6`：精确路径／SHA及summary后漂移拒绝，四项定向检查；未重跑完整合成pilot，真实ABI仍在另行审查。
- 剩余三个原F8 universal-review seed08／09／10已实际启动，ROOT session64466仍live；队列`cards/execution-queues/tail3-after-F7-scene10-failure-proposal-v1.json` SHA `988e67a9c333eaddd844a98144bf7c22a4cfa57571ae26329b4ac0966ebfab1a`，入口a08cf8b5、ROOT权限10a53e1e。只接原未运行三卡，两个F7 AUX失败不重跑、不算交付成功。F3完整96的新入口须核对原13槽全部终态记账，包括这两次失败，不能沿用旧“13项全部成功”的入口。
- B60中文解释已冻结：`summaries/F1-b60-original77-matched48-three-seed-screening-v1/interpretation.zh.md` SHA `98056c386d9e20fe568d57ae39b6f2d25423da3160b7a1e1d35e71b1d2d2d5eb`，补充SAFE7fa23a2f、完成收据87a53428。电影负信号剔除含机械失败的M01后仍为−0.2833；自然度完整17窗差+0.0500，固定18窗含两个NULL的界限为[−0.0208,+0.0458]，不能混用不同分母。该原始77批配方与finite-v2分开，whole F/F/T及全部尝试成本保持；严重风险未评、formal ratio NULL。
- F7 fluency原624的一次prepare_packets实际64184 EXIT0，55.8350196秒，无native或额外standalone validate；SAFE6850859c、真实plan c6d74ad7、tool终态b7993eb2。元数据独立观察288槽／144pairs／48窗／两匿名臂／三seed，288个非空packet指针，无NULL或UNKNOWN槽。该准备成功不代表质量或native已执行；PRIMARY派发权限单独准备。
- token400原73202于14:37:52 UTC实际ALL3 EXIT0，107／107／104逻辑任务，共144主评＋144复评＋30裁决；第三seal de6ea20f。一次原a000 SAFE导出随后执行，未释放质量。原token600权限074865下实际session31820接续运行，之后B10；两组SAFE导出源码经ROOT检查，仅在各自真实三seed终态后允许一次导出，不能以当前历史drain证明未来空闲。
- 正式计时真实ABI源码及17项合成测试已交独立审查（freeze5bb63a57、readiness5cf5d7fe）；实际host组合、pilot和正式测量仍未执行。确认48保持封存，探索尚未收敛，基线不变。

### B60统计已完成；scene10源准备真实失败

- B60实际session86548 EXIT0，ROOT释放c78932a9下完成全部六根inventory屏障、原abdb＋strict core48及一次13e／f808。SAFE `summaries/F1-b60-original77-matched48-three-seed-screening-v1/summary.json` SHA `d9b2b710344bc4f807eda5e963ffa421f4ba663f3ec4a216bb85600795c30bc0`。代表剧集Δ+0.3889，seed +0.2222／+0.3889／+0.5556，family9下界约0（浮点9.25e−18，不解释为严格确认正值）；电影−0.3292，seed−0.4625／−0.225／−0.3000，所有逐作品剔除仍负。语义144已知包含两条交付零分，候选自然度142已知、C0 144；不丢弃失败或填自然度0。严重根因未评，formal ratio NULL，不能确认或自动淘汰整个大批次方向。
- GPU86442现已真实EXIT1，14:23:45 UTC tail4 index0 F7-scene10源准备失败，MAIN未启动、后三F8未派发。ROOT tool终态 `summaries/tail4-scene10-root-terminal-v1/root-observed-terminal.json` SHA `1cddb4f7678784bfa2bf576441e18f64f0ea5a12f715497638d96f0f6e2f11fa`；原driver-completion、post drain及journal均保存。有限诊断确认36AUX调用、25accepted／11校验拒绝，25场景准备成功／4失败；全部EOS未截断，普通证据引用／ID顺序／缺失证据失败，无OOM或预算停止。完整trial151.1083500秒、estimated211771 tokens各保留一次。准备精确剩余三F8接跑，不重跑09／10。
- F7自然度六入口opaque session98865 EXIT0，一次prepare、无额外validate、103.9207141秒；SAFE96bd31ed，真实intake41a892fb。ROOT按字节登记 `cards/F7-fluency-original-intake-root-registration-v1.json` SHA `28dc13ed2ab23a2c7afa19fa77ccb4153da7e1775e0349106e00ee0556970b4e`，只允许原624一次prepare_packets（内部真实验证），不授native；288槽／144pairs此时仍为声明数量，不冒称ROOT已解码核数。
- 原token400 session73202前两seed均封签107jobs，第三seed继续；全组终态后只允许原a000 SAFE exporter一次，随后token600，不等待统计。确认48未开启，探索尚未收敛。
### 14:21 UTC 剩余四卡实际启动

- tail4 v3源码07219e5f、observer efd7ba81经ROOT检查窄diff与pins，独立权限 `summaries/tail4-after-failure-root-entry-v3/root-signed-authority-v3.json` SHA `0f0d50efa5de3b210d2dcbaba375ff183c04d90ce8f353d8ff9b93f45bfcd543`。实际fresh pre通过，session86442启动原9c0 driver；14:21:13 UTC新journal记录首卡F7-scene seed10 started，之后仍原F8三卡。ROOT已再次轮询86442确认live；非推断锁文件或意图。旧09失败／两次前检拒绝保留，不重跑它们。
- v3只在原5.1子进程显式加载原生Security／Utility模块；实际只读身份query已通过原完整predicate，WhatsApp按精确Store Appx／路径／hash／PID／N/A分类为桌面进程。并不宣称其GPU占用为0，也不是正式quiet计时资格。
- F7六入口fluency enrollment经ROOT66 pins核对，实际12字段卡 `cards/F7-natural-dialogue-fluency-original-intake-enrollment-v1.json` SHA `87f6f68a8ecd7dae3cca61337ba541a74bbbe0ff29fea717b3d25a20c6fb8147`；finalizer独立5字段接受卡 `cards/F7-fluency-finalizer-implementation-root-acceptance-v1.json` SHA `ac2e431b0000736680189d540734650bdfd2aa8cf2f044675588bdf91a209048`。只授权一次原99b prepare_intake构造288匿名槽／144pairs，不含native或质量权限；实际proof闭包仍须failclosed验证。原112不重跑，后续intake登记／各评价阶段另签。
### B60真实认证完成与共同源范围证明

- B60新19328 exporter session77457实际EXIT0，SAFE `evaluation-only/F1-b60-three-seed-terminal-safe-handoff-v2/actual-safe-handoff-v2.json` SHA `4f1692ecc67075ffe3df2f17fddf0970c7c098ebbc9ac018c80e5efa985368d6`。142主评＋142复评＋33裁决＝317逻辑／317尝试，全部接受。固定144仍含两条真实delivery-zero及naturalness NULL，生成whole F/F/T保持；原78／78／77调用及613.7558371／625.0837229／585.6984714秒成本各一次。
- ROOT字节核验 `summaries/B60-root-terminal-byte-verification-v1.json` SHA `7dd4bcfcce6108c4964eef1b1f75872d659d5d53ee71759067dcb2f83c250a27`，三精确目录1134／1178／1143文件，共3494唯一文件、0正文解码；保持原scheduler lock排除。后续同范围配对登记准备中，尚无质量结论。
- common60九组source visibility真实32678退出0，proof e61c3271、sidecar730863c2、SAFE handoff62a37a36；ROOT `summaries/common60-v2-root-byte-audit-v1.json` SHA `faddc2330e4e55602681f61757445fe55d6ca69e3cae2f0072018be2616766e7`核对精确30文件。每组29／3606／48／240，历史6414批／6417调用、9成本身份各一次。B3 native T/T/T但whole T/F/T，B5均T/T/T，B20均T/F/T；源可见范围证明不授予质量统计。
### 14:17 UTC 评价接续与运行器修正

- F7唯一合成probe79342实际EXIT0／drained sealed：SAFE `evaluation-only/F7-fluency-finalizer-native-probe-entry-v1/custodian-safe-probe-result-v1.json` SHA `0c7de515962f8f75abf391596b99f8ae18412c203944fda683a49983060dceac`；terminal92f4e0f5、invocation03b529b4、D048b490ca。1次accepted尝试，无重试；仅compat资格，quality sensitivity／served identity未证明，actual intake未授权。裁判已进入原token400 session73202，仍global6，后续token600／B10。
- B60拒绝确因为native生成status为accepted／failed，旧导出器误用了judge transport的succeeded／failed；08／09实际各76accepted＋2failed／78calls，10为77accepted。新19328fb1仅改生成词汇／SAFE计数键／schema与输出位置，7项实际形状边界测试通过，原strict core48／abdb不改。ROOT审阅精确diff后允许新v2导出一次，结果待SAFE；原22d848失败保留。
- tail4 v2权限239e56f5实际前检再次拒绝，driver仍0。原因是其powershell.exe未能自动加载Security模块，修正显式模块加载后又暴露Get-FileHash未加载；真实query packets均保留，未绕过身份校验或改系统设置。v3须实际只读身份查询通过后另审另签，原v1/v2记录保持。此时GPU尚未接跑，不声称4任务运行中。
- C0自然度intake的历史external_registration=NULL已通过源代码aec506及fbee proof元数据核对为合法原契约；三真实typed MAIN proofs存在，不能因NULL补造新登记。六入口新精确proposal准备中，未解码私有评价正文。正式计时v2修复87eb66e0／freeze f4ca5be1已交独立复核，真实ABI实现继续source／synthetic阶段。
### 恢复后的实际派发与两项前检拒绝

- tail4新入口f5bc8055经ROOT审阅并签署 `summaries/tail4-after-failure-root-entry-v1/root-signed-authority-v1.json` SHA `e0e63aeedf90af57be89649d18c56ec92c5866d48d8054b6689895dba976b45d`。真实调用在pre drain退出1，尚未调用原driver，四卡输出／journal未开始。14:07:07 UTC快照无8080监听、managed进程或已识别active GPU任务，但WindowsApps WhatsApp.Root.exe／[N/A]列为unknown。保留原record；正在核对已安装Appx、路径／hash和实时PID，新增窄分类版本，不杀用户进程，不放行任意unknown。
- F7原fac4材料session7200三项EXIT0并释放锁，manifest e0080062；单次合成probe session79342已启动，1worker／1attempt，未授权actual fluency intake。结果待终态，之后按原裁判队列继续。
- B60只读SAFE exporter22d848 session7853一次EXIT1，原strict inner core及abdb outer验证先通过，generation_metadata第76行native_attempt_chain状态词集合检查拒绝。初报误称身份／成本guard，已由源码行号纠正；不推断质量或成本错误，不重跑原collector。有限SAFE元数据诊断进行中，尚无成功handoff／统计权限。
- F9未来风险PRIMARY权限 `summaries/F9-risk-resumed-root-activation-v1/root-launch.json` SHA `90f44953738c693b546014d608084c2d9f31daff5e73dc50b70b994fe983e5f9`，绑定ROOT实际473057观察及原SAFE空历史，固定ALL29／144、最多29逻辑／58尝试；没有复评／裁决自动权限。排在原token400／600／B10及F3风险之后，未来fresh guard仍必需。
- 正式计时独立审查2885fa37实际重现P2：同目录替代pilot receipt可绕过lifecycle身份绑定。现有v1冻结保留，准备v2精确绑定修复；真实计时、finalist选择及确认集继续未开启。
### 恢复执行：B60终态与F9实际观察

- 目标重新核验为active（updatedAt1791468162），恢复执行；下面暂停检查点保留为历史。ROOT已全文检查B60 exporter22d848，允许唯一custodian在原三终态基础上只读导出一次SAFE handoff；质量统计尚未释放。
- ROOT实际执行原6ee观察器退出0，`summaries/F9-resume-root-actual-observation-v1/f9-root-observation.json` SHA `4730573ae23e9c7719ad9959f3429bae84e847b840e7d500d7c67d8e553c4110`，原195文件精确集合匹配，前后两次相关writer／native池观察通过。新ROOT request060da87绑定实际B60 tool20d7、三seal与最新D0；不解码原native正文，历史调用计数仍NULL，亦不保证未来空闲。已释放短观察窗口，custodian接既有F7材料、一次合成probe、token400→token600→B10。
- common60 source-only v2权限 `cards/common60-nine-source-visibility-root-release-v2.json` SHA `050694263b870e398255ee39e3af2d505c636634edf60a75b18fefab8537536f`，ROOT核对12 pins及精确源码差异后授权一次e160导出；旧10af失败与5774权限保持，不含native／质量权限。实际结果待回执。
- 剩余tail4独立执行入口正在准备，未启动GPU；正式计时适配器独立审查发现pilot receipt可能未与已核验的同目录固定receipt绑定，正在用合成反例核实，真实计时仍未开始。探索未收敛。
### 暂停接跑检查点（目标状态核验）

- ROOT重新读取目标状态得到 `paused`（updatedAt=1791467649），因此停止新派发；尚未收敛，确认48封存，基线不变。已通知唯一裁判custodian停止后续材料／探针／token400调度。此次不执行F9观察器，不把等待窗口当作未来空闲证明。
- B60 session85801已于13:51:37 UTC实际EXIT0，三seed outer seals为b6e9df8e／0a491251／a04cd1a1；实际tool evidence `evaluation-only/F1-b60-owned-session-evidence-v1/tool-terminal-result-v1.json` SHA `20d7f8de7012345e6ffce3ae422d355929753ef5d85e26bc22e5857ac1438a09`，三D0索引8f47248c、最新D0 3a618617。尚未执行一次SAFE exporter22d848、ROOT字节核验或质量统计，不能推断质量。
- F7-scene09失败诊断已冻结：`summaries/F7-scene09-source-preparation-failure-diagnosis-v1/safe-diagnosis-receipt.json` SHA `fef1e093b8f272b87f64a36214384d605834f8c35ade2024922683afc119c7a7`。36次AUX生成均EOS且未截断，27次接受、9次拒绝，2场景耗尽尝试；不是OOM或预算停止。MAIN调用0，真实trial failed/source_preparation，全trial147.384408秒、estimated tokens212979；原420文件未改。原2834/V8支持AUX-only未运行MAIN，但真实proof及六槽登记尚未建立。
- 剩余四卡提案 `cards/execution-queues/tail4-after-F7-scene09-failure-proposal-v1.json` SHA `04dfce3f9d47d0cd9253d262f78c9f767a054b360bb8bb5deaa01b4b72e84093`，恰为原jobs[9:]；readiness8a3b9283，尚未授权／运行。原F3入口188169要求13成功，已不适用；后续需新门禁保留8成功＋09真实失败＋剩4真实终态。F9入口97d6仍绑定旧F3，亦不得直接启动。
- common60 visibility v2 e160独立审查9b73049f通过（11项：8重叠、3新增），实际v2导出未授权。F7单次合成探针入口3e716f23就绪、5项fake通过，但未实际运行；六入口fluency intake继续保持未授权。formal paired timing适配器冻结175103af／readiness79825d43，真实observer／proof reader／F9 full34 ABI仍待绑定审查，无实际计时。
- 恢复时先核对当前进程、目录和新消息；不要复用历史drain作为即时空闲证据。按本记录补B60终态认证及统计、F9独立观察、新tail4门禁，再恢复既定GPU与裁判队列。不得重跑或覆盖失败09、旧visibility失败或既有native调用。

当前横向证据快照：`summaries/current-screening-evidence-matrix-v6/matrix.zh.md`（`db92be34…`），新增原始B60后共15条质量／4条风险／3条机械，86 pins核验；final check `0bbdb18b…`。v5历史快照：`.local/translation-evaluation/hy30-flow-v2-20261008/summaries/current-screening-evidence-matrix-v5/matrix.zh.md`（`afd1d378…`），预计算指标与来源索引 `c2c72da9…`，SAFE receipt `5a17f7de…`，final check `0b6dd508…`。v5逐字节保留v4的13条质量、4条风险及3条机械结果，新增B40 full96质量行，共14／4／3；78个身份核验通过，未重算旧统计。旧表与context快照保留；此索引不是最终报告，只比较对应控制及同范围，保留质量缺分界、风险UNKNOWN与未完成评价，后续状态以下方新记录为准。

### 13:48 UTC GPU队列真实失败与保留

- ROOT轮询唯一GPU session73759得到实际EXIT1：idx7 F7-scene seed08完整退出0；idx8 seed09源准备退出1（146.9118951秒，13:45:35 UTC），原v2_trial:165抛出source preparation failed，MAIN未启动。原tail13 idx9–12未运行。终态元数据 `summaries/tail13-sourceprep-failure-root-terminal-v1/root-observed-terminal.json` SHA `85f301b3901b602ff6579cb2512f51f39bc8fceb6f2bcc0f288dd106d281e92d`。没有覆盖或自动重跑失败目录。
- 13:48实际GPU／8080观察 `gpu-post-drain.json` SHA `d5dc2b819515b7486cf210ebf185e949cbc295eaa751f384dfb2a2721fd27ce3`，当时port listeners／managed processes／active或unknown GPU tasks均空；这是一次历史观察，不授予下一次执行。已委派有限opaque诊断，区分源准备模型输出、实现错误及真实成本；尚未确认根因。F3 full96原188169入口要求tail13全13成功，当前条件不满足，不能直接启用或伪造EXIT0；任何新接跑须另立精确剩余队列／权限并保留失败。
- F6-terms三份已生成，但原2834／V8六项门禁尚未满足，尤其F7-scene09无成功trial；不能把未运行MAIN或后续seed填成完成。GPU暂未接新组；裁判B60 session85801独立继续，前两seed已封签，第三份运行中。
- common60 source visibility70031一次退出1，原10af与5774权限保留。SAFE诊断32e46755表明第270行前四个范围条件成立，仅packed48的原manifest顺序与frame48的V7排序不同；两者ID集合相同。准备新v2分别核对各自权威顺序，不通过随意排序放宽范围；真实再执行仍待新ROOT授权，未产生visibility proof或质量结论。

### 13:38 UTC B40 full96统计结果

- 一次原1df→13e／f808完成，SAFE `summaries/F1-b40-full96-three-seed-screening-v1/summary.json` SHA `8a750b759b1c281931d8d5b3d1920026deda7e47cf745a048138993f2d54b505`；中文解释4d73ce6a、数值补充d518bc1d、完成receipt89e22679。代表剧集Δ+0.1778，family9[−0.1944,+0.6074]，逐作品剔除仍+0.0667…+0.2800；电影+0.0370，[−0.0926,+0.1852]，去铃芽变负，不能称稳定优势。
- 同一次full34生成的A／B描述性子集：代表剧集A+0.4259、B−0.1204；风险剧集A+0.3333、B−0.6111。B风险三seed −0.8333／−0.5／−0.5，逐一去作品仍−1.0667…−0.1333；SPY−2／SAO−3是大负贡献，但去任一仍负。A/B不是旧matched29结果，也不是独立确认，未新增子集CI或位置因果分析。
- C0语义287／288、B40 288／288；全96代表剧集完整窗口35／36，固定分母未知0／4界[+0.1759,+0.2130]。B代表剧集17／18完整、固定分母界[−0.0741,0]，不把NULL填0。双方自然度288／288已知，全96代表剧集Δ0、电影+0.0278；风险自然度改善不抵消严重语义风险。scene-local新增major／critical尚未评，不能宣告安全或整个batch方向失败。
- B40原完整trial655.852／651.183／668.190秒；原full34 C0仅runtime command738.983／719.619／714.569秒，wholeflow NULL。两者成本口径不同，formal ratio仍NULL，不计算提速百分比。确认48未开启，探索尚未收敛。F6-terms三seed已全部生成完成，但原2834六项门禁仍须等F7-scene三真实终态；GPU73759继续tail13。

### 13:33 UTC 材料完成与后续权限

- common-b20三材料session39276退出0，实际receipt `3b371d0f…`、SAFE handoff `a6ed2df4…`，各67文件；唯一裁判已接原B60 session85801，后续仍token400→token600→B10。F7主语义三材料已准备原一次性producer，待B60整组三终态短窗口执行fac4；同时新的自然度finalizer合成native探针只准1job／1attempt／1worker／600秒，ROOT `cards/F7-fluency-finalizer-single-native-probe-root-admission-v1.json` SHA `a389ba985fa33bc0b9141db1b56e31741fb77da2ed81a4bd90847db2f671d293`，plan4b7fa7d3。若届时未就绪，不扣住原裁判队列等待；actual六入口fluency intake仍未授权，历史112不重跑。
- F5唯一session54525实际退出0，没有超时杀进程或重试。归属材料SAFE `3c22d4bd…`、phaseplan `b2d51f70…`、清单 `1c73cce3…`；固定252候选槽全部scheduled，来源可靠性固定51。9821原文件身份保持，ROOT另核对1043唯一pins及新1009材料文件精确集合。未来PRIMARY权限 `cards/F5-cue-attribution-primary-root-launch-v1.json` SHA `50f411778587db16406961ad31a339fc558f037d6e44fc3c27dac0c99f2aeab6`；不含复评／裁决，不改变已有UNKNOWN。
- B40完整96一次统计获ROOT122pins核对后释放：`summaries/F1-b40-full96-root-statistics-activation-v1/execution-approval.json` SHA `11d5f4bef3f730fbdf26dcefc5c60d38be277098b35afc6ff2e6899d9e9d5c14`，quality release bdb0cdb4／六根登记9dc8307f。session53582正在原1df→13e／f808比较，全部六根字节检查必须先于成绩读取；不新造source bridge，formal ratio NULL，严重风险尚未评。
- 后续裁判权限另行签发：F3 risk PRIMARY29／58attempt `summaries/F3-risk-post-B40-root-activation-preparation-v1/root-signed-launch-v1.json` SHA `52a8e89b4e798a181435e1d39f662edf4b4aa245fb0c19833bd25e8a67befcf8`；B1 main `cards/B1-post-B40-root-native-launch-v2.json` SHA `984e8ab47e6a45cf27a0aab67cf85427f10f8d89a07ddca38527b66f2966be1b`；commonB3 main `cards/commonB3-post-B40-root-native-launch-v2.json` SHA `7cde2f2b89030efa26010f6c7d7f9838b294b02ea1e526d233e2fabac43dde25`。这些绑定历史B40实际观察，不能当将来pool闲置证据；实际启动仍需fresh排空核对、原preflight和live guard。原四组裁判完成后拟先F3风险、F9风险（须另授权）、F5归属，再B1及共同源范围主评价；当前均未启动。
- common60固定9组源可见范围实际导出获ROOT source-only权限 `cards/common60-nine-source-visibility-root-release-v1.json` SHA `5774787039d99f9e23b361e509dcfcca8ec768737ff6ee94d1df3e9988152d75`。新helper10af0ab8通过20项合成检查及独立源码审查；仅opaque准入后核对源文／token／request及失败成本，尚无quality或统计权限。长片桥接独立2df7ffe9通过，正式计时runtime adapter继续源码／合成实现。确认48封存，探索尚未收敛。

### 13:24 UTC B40终态核账与后续材料

- B40 full96唯一session53759实际退出0，三seed封签8a2b5c05／02bb3c01／cb1682e1；SAFE `evaluation-only/F1-b40-full96-v7-three-seed-terminal-safe-handoff-v1/actual-safe-handoff-v1.json` SHA `26e50660be4d035d0f5d1c5f17116c3f65a0e31d549723120d5b8dcf92f00933`。288主评＋288复评＋57裁决＝633逻辑及633实际尝试，全部接受。ROOT只读字节审计 `summaries/B40-full96-root-terminal-byte-verification-v1.json` SHA `3984221f928d2105ec246e0702832b2ae34074c7925a48b791125828b52cc4ea`，核对6824唯一文件，其中三目录2239／2283／2261，沿用原scheduler lock排除规则。统计尚未释放，不能从完成状态推断质量。
- ROOT将实际退出tool evidence9f4065cd、三seal及最新D0 71d69367绑定后，执行原61bf观察器；七材料目录597文件一致、前后两次CIM相关writer及native池观察均clear。新证据 `summaries/B40-root-actual-barrier-20261008-v1/actual-observation/root-observation-evidence.json` SHA `6d32a088e6dd7b6a32ea55c7969193654c9be3d5f47d2950699da86c11012a6e`；材料投影2b7f5b8b／B40排空投影f0da6b8c。该观察不保证未来闲置，也不代替native guard；已通知custodian执行既有common-b20单次材料短窗口，再接原B60裁判顺序。
- F7 main专用af512独立审查11081d16通过，5项独立方法含3部分重叠／2新增，不与owner18直接相加。ROOT阅读相对V7差异并验证52个身份后，新材料登记 `cards/F7-natural-main-material-root-registration-v1.json` SHA `fac4a40d1f6f114ba8443493c9b5ca21cac99166fbacfdfab3d1edb7c0235f95` 仅允许三次原semantic prepare。原d000机械登记不改；无fluency intake、native评价或quality权限。F9风险材料独立8212ab4a通过，仍未评；165条annotation不是已确认根因。
- GPU session73759仍为唯一生成者，F6-terms seed09已终态，tail13继续。长片source bridge新52文件冻结6713f979、15项合成验证通过，独立复核中；未选择影片或finalist，实际整片能力和正式计时未验证。确认48继续封存，探索尚未收敛，基线不变。

### 13:09 UTC 后续证据准备

- F9 b80／3072固定ALL29／144严重风险材料session99277退出0，SAFE `evaluation-only/F9-b80-output3072-matched-risk-source-join-preparation-v1/safe-preparation-handoff-v1.json` SHA `4c2376fddff9e1505c5e5345c6eefd4156769bbc97e1afa4e4257f8d29cfc40d`，195文件seal `2bb85790…`。165条主张／81个窗口seed对仅是待核对annotation，不是新根因数量；固定144槽、unique roots仍NULL、风险未评。独立源码／范围审查中，无native权限或调用。
- F9 full96三卡源准备通过，freeze `6b64b4a3…`、独立inactive队列 `da754502…`；每seed34／4297／96／480、68批，保持80／3072／ctx1。6个评分窗跨批，最大prompt15559 UTF-8 bytes不代表token容量。另一半仍是筛选，不是确认；实际GPU容量与质量未测。
- finite-B60新的逐seed fresh drain外层 `e26245d9…`通过12项owner合成测试及独立 `20af2ec4…` 的5项检查（4新增／1重叠）。原v1四十文件不改；普通partial可继续但不得称全部交付完整，busy／unknown停止并保留成本。尚未GPU启动。F6-terms seed08完整trial为824.6271秒，其中source preparation139.5158、managed MAIN656.8102秒，不能相加重复计算总成本；后续采用原2834／V8的六终态门禁，须等terms三份与scene-card三份真实终态，不填造未来证明。
- B40 full96前两seed封签，第三份仍在运行；其原V7 SAFE exporter已只读审查并获全部终态后单次导出许可。F5 cue attribution唯一session54525仍认证中，未出现新子树或失败，不重跑。确认48封存，探索尚未收敛。

### 12:53 UTC F7机械交付认证与方法补齐

- common-b20专用consumer `adbf6deb…`独立审查 `bb531712…`通过，8项重复检查不增加owner16项总数。ROOT核对55个文件及激活体canonical SHA，公共prep gate通过；材料权限 `cards/F1-common60-b20-mixed-v1-material-preparation-root-authority-v1.json` SHA `74d30efce78fa6cc50cde4b101e79531f71a26d89dc0d64cc9bb6eded0f17352` 只允许三个原prepare各一次。安排B40全部终态、ROOT完成六份材料及F3原195文件的writer观察后，短暂准备材料，再接原B60裁判；当前未做实际common-b20材料或native评判。
- 后续GPU调度决定：当前tail13不中断；其全部终态核账后，先独立F3 full96三seed，再独立F9 b80／3072 full96三seed，随后F6 rolling六腿与finite-B60三seed，最后恢复原future36。理由是F3／F9已出现需完整范围核对的信号，F6／finite仍缺真正完整流程证据，优先补齐这些证据再进行较大的位置／上下文诊断组。该顺序仅是排程决定，不授予执行权限、不改写任何冻结队列；每组仍须独立签发和fresh drain，失败如实停下核账，不自动跳过。
- F7-natural三个终态经原61各一次opaque replay／build／verify通过，ROOT机械登记 `cards/F7-natural-three-terminal-root-mechanical-registration-v1.json` SHA `d0002091ba99f72fa15f333a34b90bde7bcc390e515993d75148acda96220731`；SAFE `0a73c6b6…`。每seed734首次EOS／3606cue／29完整SRT，固定144窗全部结构有效，无额外attempt；native及whole完整性T/T/T。ROOT另将5362×3＝16086原始文件逐字节核对，清单完全一致；成本639.3643／639.2122／642.8464秒各计一次。未授权语义材料、fluency intake或native评价。初次ROOT授权构造只因误把terminal-row外层对象当row而拒绝，改读其row字段后才写权限，未影响原始产物或触发replay。
- F7新的fluency intake窄修正为实际base-json／natural-dialogue三卡，保留原误写c0版本；新intake `99b46e05…`／runner `624c0e9e…`通过48项owner及9项独立合成检查，未用真实材料。前瞻分歧终结方法获ROOT设计批准 `cards/F7-fluency-finalizer-design-root-approval-v1.json` SHA `0c3c2b03105d6db643b060e9da2eb08032a0fa2dfa47aeb468446218221c0065`：精确锚点不是共同根因证据；需复评的非空主张最多一次新盲裁决，无法解决则UNKNOWN，双方各seed规则一致。只允许隔离实现和合成验证，原112／993／b152及主政策不改，actual材料与native仍未放行。
- B40裁判seed08已封签，96主评／96复评／17裁决均接受；session53759继续seed09，尚无质量释放。F5 cue attribution离线材料准备session54525仍在原认证流程，未另启native。新finite-B60的逐seed GPU drain外层修正与现有B60／token400／token600裁判无关，后者既有权限和队列顺序保持。探索尚未收敛。

### 12:46 UTC 大批次筛选信号与扩展

- F9 b80／3072原V6＋13e／f808一次配对完成，ROOT释放 `a981e90f…`；SAFE `summaries/F9-b80-output3072-matched48-three-seed-screening-v1/summary.json` SHA `41ef12ed4e2d8c20dd749fbff11ab0c9204bdce9b19ca5da250fdf405160308b`，中文解释 `8c9cf907…`，完成receipt `1c458edb…`。代表剧集Δ+0.5185，三seed+0.5000／+0.4444／+0.6111，family9区间[+0.1111,+0.9815]、逐作品剔除仍[+0.3778,+0.6222]；代表电影−0.0500，区间[−0.4167,+0.4000]、剔除范围跨零。风险剧集+0.5556、三seed及剔除均正；风险电影+0.0417由M01+1抵消M02−0.5／鬼太郎−0.3333，不能称普遍改善。双方各144语义及自然度均已知，无交付零分或缺分。
- 自然度代表剧集−0.1111、电影+0.0125，不能只凭语义正向忽略代价；新增严重根因仍未评。F9原完整trial成本570.932／569.715／574.701秒，对照633.837／625.401／635.576秒，均完整，正式配对计时未做，formal ratio为NULL。batch80与预算3072共同改变，不能独立归因；family9筛选区间不覆盖全部适应性搜索，也不是确认结果。
- 据此准备同一完整配方的固定full96三seed source-only扩展，以及固定ALL29／144槽严重风险reconciliation；不挑有利窗口、不改提示、不打开确认48。实际生成及risk native仍待各自审查／放行。F7-natural三seed生成已全部退出0，tail13已进入F6-terms seed08；F7原61机械认证仍待一次性授权，尚不能认定质量资格。F9 finite-B60独立审查发现逐seed实时host drain缺口，新外层版本正在补齐，冻结v1及旧失败保持。探索尚未收敛。

### 12:37 UTC 三seed终态与后续诊断准备

- F9-b80三seed native全部退出0并封签，SAFE `evaluation-only/F9-b80-output3072-v6-three-seed-terminal-safe-handoff-v1/actual-safe-handoff-v1.json` SHA `e80a13b0433cfa91d5fc95d5c5e0d3754d364bc3fee4f77b6b119bbabe538144`；144主评＋144复评＋33裁决＝321逻辑／321尝试均接受。ROOT字节核验 `summaries/F9-b80-root-terminal-byte-verification-v1.json` SHA `4dca81d8be183713b1a4e5593ce59b90fea0825745881293f4f0f80657df202e`，三清单1176／1176／1143，含元数据共3536唯一文件；未解码正文。初版误把原exporter排除的scheduler lock纳入集合而停止，无输出或释放，v2仅沿用原排除规则。配对统计正在准备，暂无质量结论。
- common-b20三个终态机械证明完成并获ROOT登记 `cards/F1-common60-b20-mixed-three-terminal-mechanical-root-registration-v1.json` SHA `86bfef114e508e17fdb2be84af636fde12abb39eece8215ff11a0a917cf8b420`。路径e55／e55／普通67；native及整场景完整性均T/F/T，但固定144评分窗结构均有效，不把09未评分批次失败扩散为144个零分。584调用／581 EOS／3 limit保留，原成本1781.5356秒只计一次。专用评估consumer继续实现，未进行材料准备或native评判。
- common-b5三个原public prepare均完成，SAFE `2c55115c…`／实际receipt `e65f7846…`，144有效未评分窗、734／735／734调用、完整性T/T/T；新native提案 `f4397668…` 仍inactive。唯一六worker裁判已转入B40 full96，session53759；此前F9 drain只作历史证据，不声称当前空闲。B1、common-b3及F3风险PRIMARY29的材料／源码已准备，但独立审查与新的实际drain绑定尚未完成，不借用旧观察激活。
- GPU tail13 session73759继续：common-b20 seed10及F7-natural seed08／09退出0，F7 seed10运行中。未另启GPU任务。F3完整96三seed仍排在tail13之后、原future36之前，均待独立激活。F6 rolling完整29场景六腿fresh-source dispatcher离线及独立检查通过，12项独立检查含8项重复／4项新增；尚未运行或计入质量分母。F9 finite-B60完整三seed实现完成15项独立合成测试，独立源码审查进行中；旧失败保留，不把warm故障点成功当作完整配方验证。
- F5 fidelity原seal `a784365c…` 已接受用于后续材料准备，ROOT权限 `cards/F5-cue-attribution-material-root-release-v1.json` SHA `562289de6afb2281af04708302a5780092c8cac769e6b48d22477bc361794339` 仅允许严格检查原三轮accepted raw／canonical／snapshot后调用一次原9fd prepare_phase，写新的cue_attribution子树。保留252 candidate-only槽及所有缺失／分歧；复评使用自己的固定source51并入本阶段严重／归属错误，不转移fidelity分数筛选。未授权native或最终诊断汇总。探索尚未收敛，确认48仍封存，基线不变。

### 12:11 UTC 恢复证明与辅助诊断接续

- common-b20 v2 helper `e55ba3f8…` 保留原e632，只删除可选stopped_limit=true额外要求，并使用新authority／receipt身份；真实missing／null／false形状和错误stop／cap／truncated边界16项通过，独立7项部分重叠不相加。ROOT全文diff与独立报告核对后签发 `cards/F1-common-b20-terminal-v2-root-replay-authority-v1.json` SHA `61b96013d0ed285bac6662e46c22a674d86ec7683866b5d4e03ea37ced82ded6`，公共闭合authority检查通过。只允许08／09各一次保留记录的opaque机械replay，10终态pointer仍null，不含生成／质量授权；结果待实际执行。
- common-b5代码和具体source registry核对通过，ROOT54身份字节核验及公共prep gate通过，新材料权限 `cards/F1-common60-b5-mixed-v1-material-preparation-root-authority-v1.json` SHA `26f15fbdde72cc8449254a33b0946a4a7b5dc60f3f403d285ad018b4640105ac`。仅允许原三终态opaque材料，计划在F9三seed评测全部排空后、B40前短窗口执行；不打断现有六worker池，不重跑原734／735／734调用。
- F5原完整fidelity seal session83018退出0，一次原9fd封签 `evaluation-only/F5-partial-auxiliary-actual-six-slot-offline-preflight-v1/private-aux-run/phases/native_fidelity/seal.json` SHA `a784365ccc3035e0c5f86db283ac9c94fda2e775e23b82e378d4491ceae8ca4d`。252逻辑／504arm槽、9798清单指针及六原成本身份保持，0新native调用。该seal不生成单一最终数值；主复评各意见保留，224仲裁UNKNOWN不是最终缺分计数。后续归属诊断材料尚未授权，不能据此宣布某阶段根因。
- F9-b80 seed08已完成48主评／48复评／12裁决，seal `b49ab1ab…`，同session68667进入09，未解封质量。F7自然度新候选路径正在补充失败／恢复资格测试，既有112成功诊断保持；F8触发／heldout桥仅离线实现，不提前看holdout或确认集。

### 12:04 UTC 有序协议统计与剩余13卡恢复

- F4 ordered原13e／f808一次比较已完成，SAFE `summaries/F4-id-text-ordered-b5-matched48-three-seed-screening-v1/summary.json` SHA `6928cf12a2493ccceb426a05ffc5c2fd09b0ca6fc053ebfd1354742dc8cc7390`，中文解释 `f804d76f…`。代表剧集Δ+0.0741、family9[−0.1852,+0.3333]，剔除迷宫饭变0；代表电影−0.1542、[−0.3333,+0.1333]，逐作品剔除仍−0.25…−0.0667。风险剧集+0.0556（去芙莉莲−0.0667），电影+0.0833且seed方向异质。双方144语义／自然度均已知；自然度代表−0.0370／+0.0167。当前不支持稳定优势，严重风险未评；不外推整个协议方向无效。三个完整成本608.382／594.512／583.964秒仅探索观测，formal ratio NULL。
- F6独立SAFE交叉核对及ROOT1530文件完整字节清单通过，终态接受 `summaries/F6-rolling-native-root-terminal-acceptance-v1.json` SHA `2317f09f67d6007f38fa26afc88da90a673dceb45b3aeb1076bbea0d14692add`。正在准备scene／reset60各三seed完整29场景筛选卡，仍未运行；不从资格效果选择更有利的一条。
- tail13真实重新激活：ROOT entry `methods/root_activate_tail13_v1.py` 核对exact old jobs[6:]、所有card／runtime／source／policy身份和fresh outputs，启动前新drain `874c5784…`；最终队列 `cards/execution-queues/v5-after-common-b20-seed09-terminal-tail13-v1.json` SHA `c6c9bccaa3bc6e3a0a92ea3f2f90f9065364d67a7f37f35a398d256201169f0c`，独立授权 `cards/tail13-post-F6-root-execution-v1.json` SHA `254d0975449bb0dd3ff46f4237540dcd24309a74ee846ef78ac3c5aed32650e6`。session73759为唯一GPU，从common-b20 seed10开始；首次nonzero停止，不重跑原09，也不自动启动future36。
- B1v3真实三材料准备已退出0，SAFE `58b994e7…`，144有效窗／144主评包，原调用3609／3606／3606与成本各一次。唯一custodian已进入F9-b80 session68667，六worker；B1和common-b3的独立native launch仍在只读复核，不借用材料权限。F3固定ALL29／144风险材料准备完成，SAFE `94f61fba…`；177条严重错误annotation／79对是待核对标注，不是已确认根因或新增风险结论，native未放行。
- common-b20确认新helper e632过严：实际三次失败均有stop_type=limit／4096／truncated=false，但可选stopped_limit键不存在；真实client不归一化，genuine run_step以stop_type识别。仅添加v2兼容修复及真实形状离线反例，保留原native失败，不补造flag或改结果。实际08／09机械replay仍0。
- F3 full96 v2三卡冻结 `20a9f347…`／队列 `e1a2457b…`，每seed34／4297／96／480／874，source-only无模型调用；另一半48窗含34个来自已见场景的窗口和14个来自5个新场景的窗口，不称48个全新独立来源。拟于tail13后优先独立运行，再接原future36；尚无执行权限。F9 finite-B60全流程grammar-only设计 `0117cbdd…` 继续离线实现，原两次部分失败保留。探索尚未收敛。

### 11:58 UTC F9故障机制与F6真实资格完成

- F9 warm v3两腿session61436退出0，ROOT终态接受 `summaries/F9-warm-v3-root-terminal-acceptance-v1.json` SHA `658469807eeda8f7846722af9fdeac3af310d22ada248ee7a45e670b8e06519a`；598文件完整字节清单通过。原始腿复现目标批两次4096 token limit；finite故障点腿一次EOS、789 tokens。两腿前45批与旧运行的请求、输出hash、stop、cache_n、预算调用和保留tokens均匹配；不声称KV张量或RNG状态相同。故障元数据补充 `621dc7e7…` 保留旧响应stopped_limit缺失／null。两腿合计93调用、629487预算tokens、870.089秒，质量分母0。已准备全流程finite-B60三seed隔离实现；尚未执行，不把故障点成功冒充可部署配方优势。
- F6真实scene／reset60资格session78364退出0，authority `168a4b86…`；SAFE位于 `runs/F6-rolling-memory-v3-qualification/{scene,reset60}-seed20261008/mechanical-safe.json`，SHA分别 `4deffdf8…`／`b29f85fa…`。每腿54批／270cue／2完整SRT、54首次成功调用；scene学习9项、24批注入30次、2次计划reset；reset60学习17项、18批注入22次、6次reset并移除14项。无健康reset／输入容量超限，首响应cache_n均0；最大输入695／678。原managed命令107.595／106.605秒，完整dispatcher228.332秒。沿用旧source dry准备，fresh准备耗时NULL；仅工程资格，不含质量分母或正式全流程计时。
- F4 ordered三seed全封签，SAFE `b5290ae4…`；144主评＋144复评＋36裁决＝324逻辑／324尝试全部接受。ROOT终态字节审查 `3bbc6e0f…` 验证3570原始唯一文件及完整清单；60个直接／嵌套身份核对后，统计权限 `summaries/F4-ordered-matched48-root-quality-statistics-release-v1.json` SHA `bc465423a76eb0e74582bd6b1f5ab2d58fc63f4fb83f4dbbb1d5005cdf503db6` 允许原13e／f808精确六根一次比较。旧flex不并入；质量结果仍待实际统计。
- common-b3三份真实材料准备完成，SAFE `980613c6…`，native完整T/T/T、整场景SRT完整T/F/T、144窗结构有效；材料成功不等于native盲评完成。B1v3材料session84119进行中，之后唯一custodian接F9-b80既有评测队列。F5完整fidelity seal原session83018仍在运行，不重跑。
- common-b20最终helper e632的旧响应flag要求正在核对实际ABI，真实replay尚未执行；历史普通limit及部分场景交付保持。tail13与future36仍待各自ROOT激活，先前失败不覆盖。F3完整96扩展和固定全144严重风险诊断继续准备；确认48仍封存，探索尚未收敛，基线不变。

### 11:35 UTC 联合理解筛选信号与新一轮检查

- F3原13e／f808同范围比较一次完成，SAFE `summaries/F3-joint-json-matched48-three-seed-screening-v1/summary.json` SHA `86050fb7358395890c47fc633d3e28a7fae5b6dccad307987700b7deae11c685`。双方144语义／自然度均已知；代表剧集Δ+0.2037、探索family9区间[+0.0556,+0.3704]，三seed为0／+0.2778／+0.3333，各作品剔除后+0.1556…+0.2444；代表电影Δ0、区间[−0.0667,+0.1333]，seed−0.1625／+0.1625／0。风险剧集−0.0556、电影+0.0417；自然度代表剧集+0.0556、电影−0.05。尚非实际改善阈值及电影非劣的确认，更未通过严重风险门。
- 已安排F3固定完整96窗三seed source-only扩展卡，保持34／4297／96／480、batch5、邻文1／1、原4096及联合理解提示；问题是第一半信号能否推广到原另一半筛选，不筛选有利作品或改提示。严重风险reconciliation另行准备，native尚未放行。确认集未开启，不把筛选区间当确认。
- F3一次入口v1在六根inventory barrier通过后因缺少原methods导入路径而停止，比较调用0，SAFE `0b5f295d…`／诊断 `25a54c5e…`；新v2只补原exporter相同import路径，在原一次compare权限内完成。原13e、f808、V6及guard不改，失败保留。
- B1v3 `2b525abe…` 的native stop_type窄修正获独立 `bec1f2a0…` 通过，11项owner、4项重复检查不相加。ROOT41 pins及相对40c的精确文本反向归一核对后签发新材料登记 `698a5f75a80ca3116b8daaee3eee60299c7d3ddeefe23d437c40448a3fe6587b`，不继承旧v2权限。common-b3真实七项registry与25项源码闭包补齐，ROOT60 pins及公共prep gate通过，新prep authority `17ba4fdf8428ad02c41aa3723614757774ad7f633dfee7347ebeb487eff83ef8`。两者均仅离线opaque材料准备，native／quality仍未放行。
- F6真实两腿资格dispatcher在离线检查中发现host drain识别缺口：当前已知桌面进程及 `[N/A]` 表示未全纳入，会误拒绝本机；修正限定于真实SAFE元数据形状，未知GPU任务仍拒绝。F9 session61436继续，原始腿runtime终态已存在但全对结果尚未发布，不能先判断效果。探索尚未收敛。

### 11:11 UTC 共同范围B20失败与评测接跑

- 11:26接跑：ROOT重验F3精确三集合及3434唯一文件、F9 v3源码／模型／依赖，共3820唯一pins，receipt `147ea2c5…`。F9已获两腿46批资格授权 `cards/F9-warm-prefix-v3-two-leg-root-execution-v1.json` SHA `57d94347e0268f3662504cd3c25f535ad1497492dad79615a4f9d8963c3bc6b2`，session61436占用单GPU；11:25:57新快照无受管推理进程及8080监听，GPU仍有16个已识别桌面进程，不声称设备全空闲。两腿原始／fault-only finite各seed08，质量分母0；之后须真实终态／新drain再运行F6资格和剩余13卡。
- F3统计提案 `48d46cdf…` 保持原13e／f808与V6验证、六份原成本once；ROOT59个直接pins核对后签发 `summaries/F3-matched48-root-quality-statistics-release-v1.json` SHA `cfc5aef25ce8d5db5325af7a3c3479a921895fdce6b4e46228c04a358ec53ae3`，只允许精确六根一次同范围比较，统计正在执行，未有质量结论。F5完整fidelity seal获单次授权 `37d76f1d…`，原9fd严格前检／封签session83018进行中，无新裁判或归属诊断调用。
- common-b20 seed09 SAFE `be91a8f4…` 已确认194批全部尝试，193成功＋1批两次普通limit，195调用、28完整SRT，原610.992825秒全成本保留。失败20目标不交48评分窗仍不等于全流程成功；新helper须分别记录native认证与native完整性，不能沿用common-b3的native_complete恒真。剩余13卡提案 `ad7f17f3…` 精确对应旧jobs[6:]，尚未激活。
- common-b5三证明完成ROOT机械登记 `cards/F1-common60-b5-mixed-three-terminal-mechanical-root-registration-v1.json` SHA `95a5e0a3ea157b05d66fa8b01e55e2385874510f93005e21bf7c175652b40afb`（47 pins核对）；仅metadata intake，consumer正在离线实现。common-b3 v2独立receipt `d5e771f3…` 无具体发现，16 owner＋3独立新增通过；材料准备仍待补齐真实source/reference等七项registry身份后另签。
- GPU session93807已退出1：tail19 index0–4完成，index5 common-b20 seed09失败，原队列自动停止；index6–18尚未派发。正常observer同步停止，SAFE stop `030c036a…`。正在独立opaque诊断及准备精确剩余13卡的新lineage；尚未授权剩余队列，不覆盖失败或推断后续seed。
- common-b20 seed08共有194批／195调用，含1普通limit及194 EOS；同请求第二次恢复，29场景完整，597.586550秒全成本保留。SAFE `40b9406c…` 指出首失败97.10%为字符串外空白，不能解释为20条正常译文需要4096 tokens；原67首次全EOS证明不适用。新helper提案 `92788c36…` 保持complete-only闭合约束，须结合09诊断再决定接入。
- common-b5 seed09一次授权opaque replay通过，SAFE `24e52ff3…`；三seed handoff `82758939…` 保留734／735／734调用及完整交付，144窗结构有效但未评，三份全成本664.839258／672.150928／648.419642秒各计一次。08／10原67未重跑；合并登记仍无材料／质量权限。
- F3三seed真实评测全部封签，SAFE `977e4f72…`：144主评＋144独立复评＋23仲裁＝311逻辑任务、312尝试，seed10复评的一次失败重试保留。三份exact inventory为1110／1143／1139文件；尚待同范围统计。唯一custodian已进入F4 ordered session43255，08封签 `e300e792…`，09继续；原后续队列不变。
- B1 actual准备在首次all3前检中拒绝，实际材料／native均0。原恢复receipt使用 `stop_type == 'limit'`，consumer40c却额外要求合成fixture才有的 `stopped_limit == True`。SAFE字段矩阵 `01dccc6e…` 保留；仅授权新v3窄修复及测试，原拒绝和版本不改。common-b3 consumer v2已完成真实ABI及最小V7生命周期适配，独立审查中。
- F5空ADJ真实completion `f620cf3b…` 已产生：0新调用，224 UNKNOWN＋280不要求；外层wrapper随后因错误读取返回pointer发生KeyError，修正SAFE `a75ff9cc…` 认证原completion，不重跑阶段。完整fidelity seal仍另行放行，不把0仲裁解释为一致。
- F9 warm v3完整原始clock trace离线资格通过：owner12＋独立新增2＝14不同检查，独立 `4eec9d80…` 关闭跨批及retry前两处P2；v1／v2及失败记录保留，真实GPU资格尚未运行。确认仍封存，探索尚未收敛，基线不变。

### 10:42 UTC CTX3严重风险与后续精确登记

- 10:53补记：common-b5 seed10原67 once证明通过，SAFE `e754d26a…`／receipt `b00750b0…`／envelope `909b94eb…`，734首次EOS、全流程648.419642秒；三seed全流程完整，09仍须新recovered helper核验，不冒用原67。GPU已进入index4 common-b20 seed08。F9v2原跨批超时缺陷已关闭，但独立完整46批复现又发现同一run_step内部retry前的真实无tokenize预算停止仍不能重放，最终finding `7f5bd771…`；已授权新v3记录完整原始clock调用顺序，v1/v2保留，native仍未放行。
- 10:49补记：B1 mixed v2 `40c12490…` 修复内层core封签缺口，9项owner＋2项独立检查通过，独立receipt `99de629b…`；root阅读全文、33指针核验后签发材料准备登记 `b6cb92b1…`／接受 `b80d2f7c…`。只允许原三seed新v2目标的离线opaque准备，仍无native／quality权限，不重复76463文件合成链。F9 warm-prefix v2九项针对性测试通过并冻结 `8022f0a6…`，真实guard clock边界修复继续独立复核，尚未启动GPU。
- 10:47补记：B10独立launcher审查 `1da76590…` 通过；root再次核对410唯一指针及三个115文件完整集合，并通过冻结 `86c1.verify_launch`。新native授权 `evaluation-only/B10-full96-mixed-material-preparation-v1/root-activated-mixed-launch-v1.json` SHA `1f565034164f4c2f56def60d8b4fb137805134c98d26edf3da606fcc56e44e93`／接受 `2c2ab9f0…`，明确绑定新ec304来源桥与原三材料清单，直接使用mixed公共API。旧inactive提案不改，仍由唯一custodian在既有原队列后串行三seed，全部封签后才另行放行质量／统计。F3 seed08已seal `99472b7f…`，48主评＋48复评＋6争议全接受；session98040继续seed09，尚无三seed质量结论。
- CTX3严重风险SAFE `evaluation-only/aggregate-reports/F2-ctx3-risk-safe-aggregate-v1/safe-aggregate-v1.json` SHA `8214ecdc5e0238a5fdc9b00151fbcf7bae70e0fa8cb57e4f8d5515cd7c936a6c` 已发布，root核对五份文件hash及公开分布。新增MAJOR为6个scene-local组／6窗／8对，涉及M02、M03、W06、W09、W11；三seed新增3／2／3对，08另恶化MAJOR1对（W09）。代表窗新增3／恶化1，风险窗新增5；全144保留42 UNKNOWN。报告critical0不证明不存在，改善项不抵扣。当前ctx3配方不能通过风险门，不能外推F2方向无效或C0胜出。
- F5空ADJ已获精确真实生命周期授权 `5af412dc…`／root接受 `acc31b0e…`，重验15555唯一文件（含15540原inventory）及两份drain。仅允许原9fd零调用run_phase，固定0选中／224未知／280不要求；完整seal与归属诊断仍另行登记。
- B10六根源码桥已独立登记 `cards/F1-b10-full96-runtime-source-equivalence-root-authority-v1.json` SHA `ec3041a1050df5b3580dfbfe6ae947113f9b13de095b42732de9c25848436071`，只认可实际未使用CLI choice追加；不声称整个worker、可见信息、cache或耗时等价。B10实际native launcher仍待核验。共同B3机械登记 `a9a07947…` 仅开放metadata intake，mixed consumer须适配真实登记结构；不继承B10的288窗或完整交付假设。
- F6v3 root离线接受 `33a8fa56…`，真实两腿54批资格仍未启动。GPU tail19继续，common-b5 seed09完整交付但735调用／734批，不能用首次全EOS的67检查；原672.150928秒及恢复尝试保留，正在窄诊断。其余已授权正常槽继续一次检查。确认封存，探索尚未收敛。

### 10:37 UTC CTX3终态、材料准备与重放复核

- CTX3仲裁20次全部接受、退出0，seal `ede7225b…`；实际SAFE `189a2059…` 保留全144对，42 UNKNOWN＝30缺prior＋12 unresolved，不等于其余102无错。exporter `0f02ccbe…` 经独立17项检查通过，root阅读全文差异并核对1400唯一文件及193／434／420／318精确集合、原生drain，签发严重风险SAFE汇总授权 `ee2824c49b75404f0815dad87dfb8284caa8a3bd10cc01173cb2fb078aee2b8a`。具体严重风险分布尚待发布，不预判胜负。
- B10三seed离线材料准备已完成，完整288槽、每seed96 primary jobs／115文件，manifest `9e422df0…`／readiness `2eaa446a…`；未运行judge。精确六根源码桥提案 `99e87970…` 及父审查 `26db3c03…` 已完成，仍待root签权；不能借用B40等价声明。唯一custodian已在CTX3完全drain后启动F3 session98040，后续原队列不变。
- 共同范围B3三proof合并 `35035e85…`／inactive登记提案 `6a65902c…` 已冻结，保留native T/T/T与全流程T/F/T，不重复opaque replay；144窗均结构有效且未评。共同范围B5 seed08原67 once检查通过，SAFE `2005e289…`，734首次EOS、全流程664.839258秒。GPU session93807继续index2，不重跑既有成本。
- F6 v3 owner29＋独立新增5项通过，独立receipt `46561a6a…`，原I1/I2/I3全部关闭；真实GPU容量与持久恢复仍待资格实验，未授权native。F9连续前缀v1独立审查发现P2：合法的下一批tokenize前wall-budget停止无法重放；完整46批合成collector已复现，receipt `8f4baf97…`。已授权全新v2窄修复，保留v1与失败证据，不放宽预算、不补造旧clock trace。
- F5 AUX postreview完整15540 pins及721 accepted原件核验完成，280可比侧中numeric分歧37、major/critical信号分歧12；224缺意见不算一致。冻结selector实际选中ADJ0，空阶段仍待精确root授权及真实completion／全phase seal；尚未准备attribution。确认仍封存，探索未收敛，基线不变。

### 10:20 UTC 共同范围B3三seed终结

- tail19 index0 common-b3 seed10完整通过原67 once检查：SAFE `7685cecfabdc46645a0af71821b0c8d134dc5c51d3d8008954ffaa609b523dfe`／receipt `d4c6bcb2…`／envelope `60e8ad5b…`。29／3606／48／240／1210，1210首次EOS，全流程708.732979秒；原cost `afde6bb9…` 仅计一次。三seed原终态T／F／T均保留，09新partial proof不变；三seedmixed登记仍待root，不能称全流程全部合格。GPU session93807继续index1 common-b5 seed08。
- CTX3 ADJ session43088仍运行，尚无终态汇总；B10材料准备等待其真正drain后取锁，不旁路global6。F5 AUX postreview核验／空ADJ proposal在离线准备，没有新native权限。B1v2封签修复、F6v3 clock修复及F9连续前缀资格仍在独立验证路径。
- 自然度辅助诊断状态已重核：protocol `99327af2…`／module `b15277f8…`／runner `74bcb1c2…`，历史112次调用已全部drain。C0固定16窗×3为48接受且零缺陷；强化合成60接受，permitted机制18／18、精确类别15／18、正常侧误报0／42。只支持这些校准范围，不证明真实细微差异可检出或收益饱和。F7候选比较尚未执行，保持原48×3全窗／flagged复核规则，不挑主自然度满分子集。确认仍封存，探索未收敛。

### 10:13 UTC CTX0严重风险结果、B10材料资格与共同范围partial核验

- CTX0风险SAFE已发布 `evaluation-only/aggregate-reports/F2-ctx0-risk-safe-aggregate-v1/safe-aggregate-v1.json` SHA `e9fe7ae61302d6991ea5a18cc603c5fcf75fd7cc820dc2a35422acb0ec00ead5`，中文报告 `e22f1396…`。全144对，46 UNKNOWN＝39缺prior＋7unresolved；105 registry覆盖含7未决，98未报告UNKNOWN不等于无错。新增MAJOR 3个scene-local组／3窗／3对（M02、W03、W11），恶化MAJOR 1组／1窗／1对（M02）；08新增2对、10新增1对及恶化1对。代表窗新增2、恶化1，风险窗新增1；报告critical0不证明不存在。当前ctx0具体配方风险门不能放行，不能据此宣布C0胜出或淘汰F2方向。root核对五个发布文件hash及SAFE分布，原评分不变。
- AUX REVIEW session97066退出0，288调用／288 attempts、280接受8 evidence UNKNOWN，原63 upstream UNKNOWN和153不要求复评保留；252逻辑槽不变。review completion `68e5ae02…`／positive drain `a14285d5…`。空ADJ仍待完整认证与精确新授权，不伪造seal／不把无仲裁当意见一致。CTX3 ADJ20在原 `0d85…` 授权下进入session43088，唯一global6保持。
- B10 mixed adapter `86c1dc4c…` 独立 `66a5b902…` 通过（20 owner＋4新增＝24不同，mock／公共API边界如实保留），root全文检查及pins通过。新 `cards/F1-b10-full96-mixed-three-terminal-material-root-registration-v2.json` SHA `ef897f9d4d6e167202ef6c880c9eb45ece24ee91c0f2a364a4c0868066b96c36` 仅允许原三seed实际离线材料准备，接受 `3a258bb2…`；完整34场景／96窗／288槽，不借B40来源等价、不授权native／质量比较。实际准备由custodian负责，等待裁判锁自然空档。
- B1 mixed v1独立合成发现封签resume缺口：内层core seal错version／state及空files仍可能被custom检查接受，外层精确inventory不足替代core语义校验。原 `9d19…`／`ea4…` 保留，reproducer receipt `1690c044…`；已授权新v2窄修复和独立验证，B1实际材料仍未放行。相同攻击在B10真实V7 seal校验中被拒绝，不按类比改写B10。
- common60-b3 seed09一次原始opaque replay已通过，SAFE `e765eb2cdcb627a928e516da11ab371bbaa9d994df02063a9f9338b36a8a9133`，receipt `ee2081f5…`／envelope `c0012b0d…`。1210调用首次EOS、nativecomplete true但全流程partial：3605有效＋1未评分invalid cue、28 SRT；48评分窗全valid且未评，原725.748838秒成本只计一次，54.294606秒核验开销不冒充新推理。08原67未重跑、10仍由session93807生成；三seed尚未全部终结，mixed consumer仅允许代码准备，材料／quality待登记。
- F6新v3继续修复I3真实clock调用顺序；F9连续前缀资格代码与离线测试进行中。尚未收敛，确认封存，基线不变。

### 10:00 UTC 资格终态、CTX3仲裁登记与CTX0风险汇总放行

- 10:09补记：common-b3 helper独立审查 `3d70c6b8…` 限定通过，40 owner＋3新增＝43不同测试；root全文核对相对B1差异及42 pins，接受 `f3e4d2e9…`，只授权原seed09一次opaque replay／envelope校验，authority-v2 `6d06d764e272223374ef057bbd7cd1c347cd60465dc991dae868a13e9909bd09`。08原67与10未来67不变。root构造器三次错误保留：diagnosis字段名、全null模板假设均写入前失败；额外说明字段让首次authority-v1被closed schema拒绝，不可使用。有效v2移除说明并绑定已核实09原terminal；实际replay尚待完成，不是新推理或质量放行。

- 10:07接跑：F9完整SAFE审计 `4f79d576…` 核对406唯一文件（84 private文件仅字节hash）、模型完整SHA、12终态清理；12调用／82554预留tokens，managed command合计742.164786秒，含核验runner共767.242918秒，均不作正式配对性能。root另验12终态、source/runtime/cards及fresh server0／8080可绑定，签发tail19外部授权 `c26b3743d69a7d00137d7ad2182b193f08298fd047bcebfcbc4e0a8950e8625d`，原queue `b38b5c8c…` 字节不变，**GPU session93807已启动**。journal为 `runs/v5-after-common60-b3-seed09-terminal-tail19-v1-queue.jsonl`；从common-b3 seed10继续19原任务，首个非零停止，不重试旧09。v3正常7槽observer授权 `a3b66443131911d81784b25b5e9c355033c1d052dc2f69587fa3a832c196d428`，只允许原67 once检查，实际材料／judge仍另登记。future36及F6／新F9资格native均未放行。F9审计构造器两次SAFE字段假设错误（slots整数、runtime_error缺省）均保存失败说明及源码快照，非模型失败。

- 10:04补记：F6 v2独立新增I3阻断，未篡改的真实run_step在deadline前dispatch、deadline后返回有效response可成功，但audit在tokenize阶段提前使用postresponse wall，误判预算失败并拒绝恢复。独立最终9项中的1项是缺陷复现，不计资格通过。已授权新v3隔离修复真实pre-dispatch／reservation时间与postresponse时间的重放顺序，v2全冻结保留，native仍0。F9十二腿已由root读取SAFE确认全部首次成功，original／finite各6，未证明防故障收益；连续前46批双臂资格仅授权实现与离线测试。

- F9隔离12腿session27359已退出0，原receipt报告12 attempted／0 not_run、quality denominator 0；逐腿SAFE终态与清理独立审计正在进行。尚不能据此说明原长流程故障解决。tail19固定queue `b38b5c8c…` 仍inactive，等待root核实全部drain再签发外部执行授权，不能改写原queue字节；future36仍未放行。
- CTX3 ADJ20已由root登记 `evaluation-only/F2-ctx3-risk-adjudication-custody-launch-v2.json` SHA `0d85f158d86312f93be2a112cd24f13d7ddc8b75ff82f5b7ef8f59e40b55d4ba`，attestation `49577a08…`／review `35a008fb…`。constructor全文及独立19项审查已核对，原193／primary434／review420完整物理集合、native drains、writer0和CLI版本通过。只允许原20实际signature争议，最多40新attempt、74历史attempt保留；全局唯一custodian在AUX复评drain后运行。缺少prior的6场景仍UNKNOWN，争议签名不是严重错误事实。
- CTX0 exporter v3 `0029666a…` 修复经6项owner＋2项独立检查通过，原coherent-count篡改被拒绝；实际摘要仅版本身份变化，39缺prior＋7unresolved＝46 UNKNOWN不变。root全文检查及1377唯一文件hash、192／423／427／306精确物理集合与原生drain通过，已签发 `summaries/F2-ctx0-risk-terminal-root-safe-release-v1.json` SHA `3021017ad3f1e0429b4be636a5baa7ebfe5d541cf4ea6639f027c0d17a9f9d8d`，仅允许保留全144分母与未知项的严重风险SAFE汇总，不改原评分、不增调用。尚未收到实际严重风险结果。
- F6全新v2已冻结readiness `ae37ef8e…`／worker `9a737d0f…`，最终24项测试通过162.124秒（原16＋新8，不叠加开发轮）。修复raw→交付文本／terminal严格绑定和原始失败分类→halt／checkpoint重放；原v1、pure55d与canonical runtime21未变。projection正在独立复核I1／I2，新资格卡仍inactive、native0。
- common60-b3 partial helper `b976e132…` 最终40项测试通过131.297秒，包含未缩小29／3606／48／240／1210的完整合成链；独立窄审查进行中。真实seed09 replay尚未授权。B1 mixed adapter13项、B10 mixed adapter20项离线通过，但测试边界不同：B10主要mock及4项未patch公共API检查，不冒称完整native生命周期。两组实际材料仍须独立资格和新root授权。
- common canonical67身份更正另存 `78749b6b…`／`72873599…` 附录，旧83a记录保留；B10正常61身份不受影响。探索尚未收敛，确认样本保持封存，基线不变。

### 09:37 UTC 共同源范围交付失败、F9资格启动与F6阻断修复

- 09:44身份更正：root核对common60-b3 seed08原SAFE493c中的实际checker为 `67e0fae7…`（`native_mechanical_admission_v2.py`），不是此前口头简称的61；77b5 receipt／4444 envelope原字节不变。后续common60材料与统计登记必须绑定67／新partial helper的真实混合身份，原83a71 code-only说明若有61假设须新附录修正，不能改写旧证明。

- 09:40补记：F6独立finding receipt `e4792000e9e2c2a21bbb56ddb6b4118017f9d37f38d542925defb90ac3cb6d87` 确认I1之外的I2：原始OOM响应不变，重封row／terminal为普通失败仍可能恢复并清除halt。最终6项审查测试中2项专门复现缺陷，不构成资格通过。已授权同一新v2从原始调用重放失败分类，绑定row／terminal／checkpoint并保留OOM／cache／budget／setup优先级；v1完整保留。CTX0 exporter `1412877a…` 也复现摘要校验缺口：未决registry不变但把count／flag一起降低可通过；这不是实际cb34计数错误证明，新版本须依原4329规则从registry重建唯一(seed,window)集合。严重风险仍未解封。

- 原GPU tail28／session51004在index8 common60-b3 seed09于09:29:01退出1，未自动继续。SAFE `summaries/F1-common60-b3-seed09-terminal-diagnosis-v1/safe-failure-receipt.json` SHA `cde4df191ed1ca0f25d2ef4e95c5c8747442806668406cb697bd863e55ffa876`：1210原生批／1210调用全部首次EOS，worker完成、runtime返回0；最终交付3605有效＋1无效cue、28／29 SRT、全流程partial725.748838秒。无效 `F2-M02-J00418` 位于 `F2-M02-S00338-b0027`，原因 `empty_or_invalid_srt_cue_text`，不在固定评分ID内；48评分窗口保留且尚未评价。不能归为OOM／输入容量失败，不能据此把整seed48窗置0。清理09:28:18完成，worker／server均退出；`runtime_error`字段实际不存在，而非原文件显式null。
- 原prefix0–7成功、8失败保存，source-only suffix19提案 `ca496717…` 精确取原9–27且无已有输出，未放行。正常observer已停止，未来须新lineage后才观察剩余7个common60正常seed。future36仍不得提前运行。
- 利用已退出且清理确认的队列边界，root已签发F9十二腿资格授权 `cards/F9-finite-whitespace-twelve-leg-root-execution-v1.json` SHA `7a14e44aa919b929dfd2ee263b5e0ec4a8ca62430fb1f1bec9de514523e2ea26`。原proposal `8d8c64e5…`／runner `d6c39ab5…`／master `245b20de…`不变，session27359独占GPU执行两个源固定case×三seed×original／finite两臂，质量分母0。目的是诊断此前B60／token600输出触顶，普通失败照留，fatal／未知即停；完成并drain后才续跑suffix19。旧离线40项资格不等于真实效果，尚无结论。首版root授权构造器因错误假定旧runtime存在 `runtime_error` 键，在写授权前退出；v2显式允许该键缺失并另核translation_exit0／positive cleanup，不改原run。
- F6 staged v1最终16项离线通过147.374秒，freeze `048515a6…`／readiness `abfae0f3…`，但独立审查发现阻断缺陷F6-I1：`audit_output`认证了原始响应和native parser映射，却未要求最终交付／terminal映射与其相等。合成改动terminal文本及自哈希后，恢复可能接受并写入首译记忆；该复现是缺陷证据，不算资格通过。禁止native资格，source_audit正在全新v2目录修复写入／恢复前的严格绑定；保留v1全部冻结字节和历史测试，pure55d及当前canonical runtime21不改。
- B3 matched48严重风险SAFE已正式发布 `evaluation-only/aggregate-reports/F1-b3-matched-risk-safe-aggregate-v1/safe-aggregate-v1.json` SHA `0efc71cd512cd939a5a7e7a1908707a90405351672414a7faf5b05e0f13986ba`。新增MAJOR为9个scene-local组／8源窗口／10window-seed对，另恶化MAJOR 1组／1窗／1对；跨scene唯一根数未知。新增分布M01／M03／M04／W03／W06／W11，恶化W09；三个seed分别报告5／2／3个新增对。9个新增对来自代表窗，1个来自风险窗；不能因类别平均改善抵扣。120选中／144全分母、9未知及24未选照留；无报告新增CRITICAL不等于不存在。当前B3具体配方风险门不能放行，不推成C0胜出或F1整体淘汰。
- CTX0 ADJ终态SAFE `cb34ce05…`：19仲裁全接受，但固定29场景／144对仍有8场景缺少prior的39对＋3场景unresolved的7对＝46 UNKNOWN。只取得机械SAFE、严重错误尚未解封，exporter独立审查继续。CTX3仲裁只在inactive准备中。
- B10 full96三seed机械root登记 `cards/F1-b10-full96-mixed-three-terminal-mechanical-root-registration-v1.json` SHA `034e210fee39db59e8d8f4e7b2d5f0411002f7ae98a3b9c2e50528e8da1c0c04` 已完成：08／10原61、09新53db，1333调用含1limit后恢复，288评分槽未评。首次root登记脚本把handoff组标签写成`F1-b10`而非实际`F1-b10-full96`，在读取proof前拒绝；v2只修该预期标签，所有原身份不变。mixed评估adapter仍在离线资格，材料／native未授权。
- common60统计设计已冻结 `summaries/F1-common60-statistics-design-v1/statistical-contract-v1.json` SHA `73ee542b47743526901d6376f07f04eb121ccc942bb2146ebcb05a97a8bd6bbb`；两主要诊断b3−b5／b20−b5，承接原三项C0次级联系，b5不是policy C0。共同visible范围通常62条（block60＋外侧1／1），target角色、prompt token和生成竞争不同。固定432槽，partial补充 `c014959a…` 要求真实失败0／自然度NULL与未知NULL分开；不以complete-only入口删掉失败seed。实际统计未执行。
- AUX REVIEW session97066已从约1TB重复历史读校验进入真实复评；该认证开销与裁判native耗时分开。原63初评未知与5 accepted NULL继续保留。fidelity的冻结 `_dispute` 不按分差仲裁，native_fidelity枚举不会触发supported／misattributed互斥条件；未来空仲裁仍须真实终态登记／精确授权，不能伪造phase seal或称全部一致。归属phase必须等完整fidelity seal，尚未派发。探索未收敛，确认封存，基线不变。

### 09:10 UTC F5主结果发布、辅助复评接跑与恢复认证

- 09:23补记：B10 full96恢复helper `53dbf059…`／最终test `9d361a48…` 经32项owner＋3项独立新测试（35不同）通过，包含未缩小production PROFILE的34／4297／96／480／444批、445真实worker合成调用。历史scratch拼写错误及更正轮均保留，不累计重复测试。root接受 `d20b409b…`，签发 `cards/F1-b10-full96-seed09-recovered-native-replay-root-authority-v1.json` SHA `0ebfaba54f279cfb33fed9a05b1764f77acd103f14a5f00b183c4edb99af8e12`，允许09一次原始opaque replay；08／10复用原61，尚无质量授权。
- CTX3 review终态root登记 `68c97e6192b0139c9d374247bd2f5b79cbb1299ff6b14276b0e49b0e7b2f7170`：重验1067唯一文件和193／434／420精确inventory，只允许后续inactive仲裁准备；初评6未知与复评6未知不能假定是同一集合。CTX0 ADJ19退出0，seal `c7930cf3…`；AUX REVIEW进程97066已启动，仍在原不可变历史认证、尚无review调用记录，不把预检查耗时解释成裁判失败或重试。
- common60 b3 seed08完整终结并由原67一次认证，29／3606／1210批首次EOS，完整trial724.541499秒，SAFE `493c2c22…`／receipt `77b5d3ed…`／envelope `4444ad4f…`；GPU继续index8。该诊断的b5是共同源范围控制，不能借用部署C0名称或直接替代主比较。F5主结果另经78项公开汇总一致性检查，独立receipt `b37f2e24…`，未发现算术或policy矛盾。

- F5 MAIN v4完成一次真实公共统计，`summaries/F5-main-matched48-three-seed-screening-v4/summary.json` SHA `669e1e044621e14a6f3d4584d6eed214089fda2f9dbd17a72d29d0ac5f10bc1a`，中文解释 `interpretation.zh.md` SHA `e7fadcca2be7be79631357b605a460dde32758f8e101e78c8e9eb8dd24745249`。固定144／arm全部semantic与naturalness已知；代表性动漫／电影Δ−0.5185／−0.5000，去掉任一作品仍负；family9探索区间分别[−0.9074,−0.0926]／[−0.6750,−0.0667]。risk动漫−0.2778主要由SAO驱动，去SAO为0；risk电影−0.2917，上界0并非严格负。主评分不能定位planner、单位翻译或mapper责任，继续辅助诊断，不否定整个F5方向、不宣布C0胜出。
- F5原完整流程仍T／F／T，1690.836725／1904.808773／1578.836291秒；09全部评分窗口已知不修复未评分部分的失败，亦不应抹去真实naturalness。各原trial成本仅计一次，正式效率比NULL，严重根因仍未评估。v1–v3及其失败记录保留，v4获root `a8cdb232…` 精确执行授权，16项不同合成测试与全六槽接口认证通过。
- F5 AUX REVIEW已签发 `evaluation-only/F5-partial-native-fidelity-review-preparation-v1/root-activated-review-launch-v1.json` SHA `5a7e17240821f8853bc3aa863175e468cac06f86405548bac4184358047622b4`；root接受 `7d2e5a5847eb1acb181d1a60ed4cd2a4a5edde87e5082ec082dfa3b51095a87b`，重验12690唯一文件（含12671原inventory）及精确primary前缀集合。固定51逻辑槽＋实际风险并集选择288侧复评，63上游未知不补跑，153不要求复评；441已接受中5个仍NULL。此为原primary终态登记，不是全phase封签。按原9fd在当前CTX0仲裁完全drain后、F3前执行；尚无adjudication、attribution或AUX质量解封授权。
- B3风险终态exporter独立11项测试通过（8原＋3新）。root新保存的只读脚本重验1127唯一文件、149／324／305／319四个精确物理集合；原149另与冻结b1c2清单相等，不追认成exporter测试范围。风险SAFE汇总放行 `summaries/F1-b3-risk-terminal-root-safe-release-v1.json` SHA `14a904b6f7b200a1d5687d7a1dfb632d9d464c6558d935f016b26942a17570d7`；120选中／144全槽、24外部、9未知照留，严重错误分布尚待汇总，不能把其余111解释成无错。
- CTX3 REVIEW session87845已退出0，29逻辑／36实际attempt、23接受6未知、7重试，seal `8363737f…`。CTX0 ADJ19按原7acb登记进入session34131；CTX3仲裁尚未放行。全局裁判仍唯一custodian、最多6并发。
- b1三seed原证明已登记 `cards/F1-b1-mixed-three-terminal-mechanical-root-registration-v1.json` SHA `65ca8d9ba2a8eadf4cdaeb8778a7e05e9b1fc1d6da9142b048b5c96225cab295`：08原恢复helper、09／10原61，10821实际调用含3首次limit后恢复，不是delivery_zero。mixed评估adapter仍离线资格中。
- b10-full96三seed均已完整34／4297／96／480交付，08／10各444首次EOS，原61证明各执行一次；09为445调用／444批、全流程731.570329秒，不能套用首试全成功证明。另建闭合恢复helper离线资格后才允许原始opaque replay。08／10完整流程707.687169／699.370960秒；质量尚未启动。GPU session51004已进入index7 common-b3 seed08，当前tail28仍未全部终结，future36不得抢跑。
- F6 staging集成15项稳定离线测试通过，包含六个fake54批流程、四处实际文件恢复和不重复派发；随后静态审查发现DLL／custom identity／asset manifests尚需与新卡逐值绑定，正在补齐并更新独立新版本。未运行native资格、未改当前flow源码、未据合成通过声明实际容量或收益。探索尚未收敛，确认集封存，基线不变。

### 08:40 UTC 原始恢复认证与风险材料进展

- GPU session51004已于08:29:11进入index4 b10-full96 seed08；b1三seed均完整终结。seed10原61一次认证通过，SAFE `aef3d806…`／receipt `30c201ed…`／envelope `5f52c2ca…`，3606首试EOS、完整trial1213.348541秒。seed08新helper `bba9167f…` 经root全文及独立完整29／3606／48／240合成链审查通过，共30原测试＋4独立新测试；初次合成文件读取干扰引起的WinError5另存，未冒充通过或真实模型失败。
- root接受 `a236fd2e…` 并签发 `cards/F1-b1-seed08-recovered-native-replay-root-authority-v1.json` SHA `4979c5d6b306d471334a184b4bcb5cfc0d791dfb987735f6dfaa26f30e385a20`，仅08终态获实际opaque replay授权；session72544执行中，09／10复用原61。新mixed adapter仅离线实现，不提前准备评分材料，不能把08伪装为原61全首试证明。
- F5 AUX PRIMARY session52123完整认证退出0，原completion `ffcaf2b3dc8aa217e99e8ebfc09b1986b1e309b25b9ebe7d5614354a793aaaaf`：504次／252逻辑槽、441成功、63未知、无额外调用。失败类型SAFE `evaluation-only/aggregate-reports/AUX-primary-validation-taxonomy-v1/safe-receipt.json` SHA `ef22aca1f58e1e0275ad621a15f7ade4fd9add0066e491380a651683cdcc190a`：首拒绝43分组源ID越界、17重复root ID、3unit-local span不符；全部schema有效且原本地validator可复现，不是语义真值判决。另有重叠错误，不能把这些首拒绝类别累加到重复计数。原validator、失败记录不改，只准备未来提示澄清提案；未批准补评失败子集。
- B3 ADJ session92477已退出0，22／22一次通过，原final-seal `4ee7c22d…`。初步完整性计数：120选中／144全槽，原failed-primary场景6槽＋其余未决3槽＝9 UNKNOWN，24未选择；不等于其余111无错。严重错误汇总待SAFE交接及root核验。CTX3 review已进入session87845；首次launcher漏import路径在guard前退出，SAFE `40cb5b09…` 保留，修正launcher后原冻结wrapper／登记未变。
- F5主统计v3的第二问题发生在已通过all6屏障和原13e控制验证之后：把带version/state/selection/expected48附加声明的原matched指针与裸path/SHA整体比较，误拒绝同一原身份。故障SAFE `be458867…`，v4将精确path/SHA及四项必需声明分别核验；13项合成已过，完整真实六槽私有接口探测继续，公开配对汇总仍未生成。

### 08:21 UTC 主统计再次执行、辅助初评终结与新实现隔离

- 08:25补记：F5 v3实际调用173.046秒后ValueError拒绝，summary仍未生成，失败receipt `c0fe09ada3fe38e0b66d141ce31709564194a07adf6b443b16619cfc9f0a0d77` 保留。已授权统计custody按全部六槽屏障与原验证接口分阶段定位；异常正文和stack仅保存在私有诊断目录，root只接收函数／字段／阶段SAFE信息。不会改原评分或删除guard，也不将缺少统计汇总解释为候选输赢。

- F5统计v2拒绝的原因是三个历史matched29控制artifact没有后来新增的 `original_trial_attempt_identity` 字段；其原trial／run／cost仍由e3d证明认证。v3 `573f691f…`／proposal `f5b5f2ec…` 明确保留历史缺字段，仅控制可通过该原证明绑定；候选缺字段、控制已有字段为NULL或错指针均拒绝，不改旧run。14项不同合成测试通过，独立receipt `e0fc1569…`；root核对源码差异及85个指针，批准 `cards/F5-main-statistics-root-execution-approval-v3.json` SHA `d914095a442e680d8e4fd5f9d6d2f96c54a5064407ffe91831b693071e570576`，实际统计正在执行。
- F5 AUX PRIMARY全部504调用终结，441通过本地证据校验、63终结UNKNOWN、无额外attempt。原native guard已证实drained_released／active_callbacks0，dispatch receipt `2f244ac1…`；session52123仍做只读完整认证，尚无AUX结论。原协议review采用固定51逻辑槽与实际severe／归属问题union，但每侧须有成功primary，失败侧保持upstream未知；不套用risk场景的独立复核规则。已授权封存后的失败类型诊断，不新增裁判重试。
- B3 ADJ22已按原登记 `d48ceb7b…` 开始session92477。随后CTX3 review、CTX0 adjudication、F3／F4ordered／F9／B40／B60／token400／token600等原native队列不变，仍由单一custodian限制全局6并发。
- b1 seed09为3606首试EOS，原61证明一次完成；SAFE `a45c57a7…`，receipt `c0f5b80e…`，envelope `c76b9dfb…`，trial 1140.195309秒。seed08三次limit后恢复的新完整交付helper `bba9167f…` 已通过30项离线测试，readiness `2fb602f9…`，独立复核中；不重复生成或重复认证seed09。seed10仍在生成。
- F6纯模块经root全文及独立26项测试复核，接受 `summaries/F6-pure-memory-root-offline-acceptance-v1.json` SHA `65ad97dc362a0b89e60b2513cdba2ca09aff4a50eea5a5c663393dc5fd4b8852`。接入设计 `c9ab9c92…` 先做两个policy×seed08、每次固定两场景54批，共108批原生资格，尚未派发。最小worker／trial／delivery／runtime版本实现已授权在新ignored staging目录完成；禁止向当前flow源码目录添加文件，以免改变运行中source_snapshot。实际容量、磁盘恢复与native证据仍需独立验证，正式memory筛选须先审静态F6结果。
- README已将过时的“S0源样本／参考阶段”更新为当前多seed筛选与完整96扩展状态；该句5个本地链接存在。AGENTS／INDEX及流程README现有说明仍准确，未机械改写。探索未收敛，独立确认未启动，未替换基线。

### 08:06 UTC 接跑、统计修订与记忆实现

- 08:08补记：F5统计v2独立审查 `3e87bac1742189d91ec6bf5fefafeca6d2c591645a8f8ed4334ba2e6b6daf222` 通过，12个不同合成方法。root完整源码／差异复核及80个指针重验后签发 `cards/F5-main-statistics-root-execution-approval-v2.json` SHA `19e89b3bd1e88c9bb39aa685552cc21bec1914c4a4c7a5ca593d0232c6169564`，允许统计agent按原六槽opaque认证后计算SAFE配对汇总。实际结果尚待产出，不包含AUX和严重错误结论。
- 08:10补记：上述真实统计首次调用41.812秒后因KeyError拒绝，`summaries/F5-main-matched48-three-seed-screening-v2/actual-execution-receipt-v1.json` 保留，summary未生成、native调用0。安排私下核对实际metadata字段后另立最小修订；不重跑旧v2、不跳过验证。GPU已于08:08:57进入b1 seed10，前两个seed终结，额外调用资格继续独立认证。

- GPU session51004／tail28 `1adf9449…` 已完成token600第三seed和b1 seed08，现执行b1 seed09。b1 seed08完整29场景／3606批／3606cue，实际3609调用＝3606 EOS＋3首次limit后恢复，完整trial 1207.895082秒；不能走首轮全成功61入口。原once路径未写，另建闭合恢复认证路径，保留三次失败调用及全部成本；不重跑译文。
- token600新adapter `dfbde99f…` 的11项离线测试及6项独立重验通过，root接受 `a2633f5f…` 并另发材料登记v2 `6d5659c1…`。原调度锁空闲后，三组真实opaque材料准备完成，SAFE `evaluation-only/F1-token600-native-launch-preparation-v1/actual-preparation-offline-readiness-v1.json` SHA `641f93adedb3d5a50ca187b1543ec37c10d76680546689bc1c3d53174fdd5285`：固定144、142待评、2认证delivery_zero／自然度NULL，原成本各一次；32个精确依赖包含原initial-index完整29项。native启动仍待root核验，未解封质量。
- F5主统计v2 `0d5a736f…`／proposal `7aa687ac…` 已修复六槽认证先于任何评分读取的顺序，9项合成测试通过，等待独立delta审查及精确执行登记；v1保留未执行。F5 AUX primary session52123仍运行；初始化中的job.status可能预置judge_failed，进度必须按终结attempt分类，不把in-flight默认值当失败。局部证据校验失败保留UNKNOWN，不擅改重试。
- F6日文-only slot冻结 `cc5c82a9…`、SAFE `72df1800…`：5031表面候选中152选入、20保留；全部29场景具298批示例注入机会（假定成功交付），reset60为231批。原两场景资格片段具24／18批注入机会，足以检验学习、注入和reset，但不覆盖cap／dedup。新目录 `summaries/F6-rolling-memory-pure-module-v1/` 正实现纯状态转移及合成测试；尚无worker整合、实际记忆推理或质量结论，当前冻结runtime不改。
- token600启动核验完成：root重新核对278个唯一文件指针及201个完整材料文件、实际CLI和公开元数据接口，启动登记 `evaluation-only/F1-token600-native-launch-preparation-v1/root-activated-launch-v1.json` SHA `0748656f0dbc984607e0b56f8e5633b427e586175f8850af88eaf08b4de0a6d2`，接受 `12e6e85a…`；排在token400之后，由原custodian独占全局6并发，质量仍封存。
- F6纯模块初版 `55d43919…` 已冻结，22项合成测试通过；54／734批合成范围均覆盖两种reset策略和三个seed。已安排独立审查，不等于原生运行资格或真实质量收益。
- 当前goal状态已恢复active；探索仍未收敛，独立confirmation和正式配对计时尚未执行，基线不变。

### 07:47 UTC 统计审查与后续条件设计

- F5主统计v1 bridge `3004acadf9d54b757eb2699363b9b1e3d0dc620987f6d0b4f19568391546c18d`／proposal `ff9571ecca0eefc34f5b1b1e590c8be6ba5650d0c63de5c7000cf081a5c18ea6` 尚未实际执行。独立审计发现逐槽校验会在后续五槽原生proof完成前读第一槽final；root要求保留v1、另立v2，先全部六槽metadata／原生proof通过，才调用原V11终态与13e控制评分读取。六项原合成通过不覆盖此缺口；真实分数未读。
- F2方向提案 `summaries/F2-directional-context-source-only-design-v1/proposal.zh.md`、SAFE `19825788403801e7e34ee0c37fef0b313ecee349d8839a8286bb4ae8e1aaf682` 建议4/2对2/4镜像、连接3/3及C0；固定只读总cue与最大距离，但不声称token／信息等价。screen-a47/48、full9692/96窗全部所涉B5批具完整邻文；主分母仍保留全部48／96。仅条件选项，须待完整96／8/8／风险机制证据决定，不自动新增六trial。
- 后续源准备12项新lineage plan `summaries/source-preparation-next-wave-native-intake-plan-v2/plan.json` SHA `7d37df4d7d47acbaca913f3262c1d752220445d1fe0bc1373951790788c5c451`，SAFE `d74d053d0cee3890dcf81b7016f1b8044a4017c138f82bf7107f2eb2377d21e8`，仅映射新tail28的indices16–27；旧card／outputs／runtime／来源未变。三项metadata检查通过，无实际trial或helper读取。natural用V8/61，源准备2834需六终态authority，F8c3bad需三终态authority；dev90／hold54隔离不变。

### 07:39 UTC token600完整证据登记

- 新217add helper实际三终态opaque replay全部通过，SAFE `summaries/F1-token600-three-terminal-native-admission-v1/three-seed-safe-handoff.json` SHA `73d45cdbea835ee89f5922c44125f09176c0ffcfb8e26dda0c782401c60d3aec`。08／09各79批全部尝试、80调用＝78 EOS＋2 limit，10为79首试EOS；总239调用、三个原成本各计一次，历史token-count获取成本不冒充新增成本。
- root重新通过三个公开verify_envelope并重验原始文件清单，登记 `cards/F1-token600-three-terminal-mechanical-root-registration-v1.json` SHA `6de1181e2544e95463c7682ac9edb1659e1936a4d635f3d1de91a2b81647be3a`。固定144窗中2个认证delivery_zero（语义0／自然度NULL）、142个待评；whole-flow仍false／false／true。仅放行metadata intake，真实材料准备与native裁判待新adapter资格，不调用旧完整成功入口。
- F6滚动首译示例记忆仅有设计提案 `summaries/F6-rolling-memory-source-only-design-v1/design.json` SHA `d260f72f5bbe2002d0e023e69fcaefcc3750c3769e301983e6cb6098f44ece40`，不是已实现能力。当前静态memory_state不支持动态转移。已安排日文-only重复slot／跨批与reset机会审计；不读取候选译文或参考，不把完整cue示例伪称对齐术语，正式质量实验仍需另注册。

### 07:32 UTC token600三终态认证开始

- 第三seed10于07:29:49 UTC完整终结，terminal `45412a9cef35263fc44f6ae723d1ae77a8cec39a8d93a340db9152f0d5e2667d`，完整命令569.302013秒、29/29完整SRT。第三次成功不能覆盖前两partial。队列已进入index1 b1 seed08，GPU session51004仍在运行。
- root逐一核对三终态、原卡及每次runtime的server／worker退出与cleanup时间，签发新217add专用authority `cards/F1-token600-three-terminal-native-replay-root-authority-v1.json` SHA `e65c3dbccd25225d7868d925ec81d8c2e9abf99fbf95adeb4405d9528bb94575`，接受 `30c3beb16259d2ad8aedb5358372ea6b3a17ecbb9d9bc3f812010d5a413afdaf`。仅允许runner对三次原生证据离线opaque replay、receipt／envelope及SAFE交接；root未读取译文，不声称当前全局GPU空闲。尚待实际认证与评价登记，固定144语义／自然度规则不变。

### 07:28 UTC 评价释放与后续观察器

- F5主评三终态SAFE `3d649fe74045c49aae23e581f00338d335cb6fd5f79225fa0c8db62cfbde72be` 经root核验3690封存文件、60指针与实际主评writer0，release `8a8c1814274e3e75f5cafd829ebddc8c52fe280b60623f6e0c59c79acab7ac20` 仅开放安全汇总。统计执行仍须固定六槽来源／方法；不释放参考、译文或裁判理由。
- token400三seed原V7材料准备完成，root核验201文件、84指针、实际CLI与公开verify_launch通过；launch `7ca2b29320cddbce7e267d9527f1be0ac0da24ff7003a705654420365d01f534`，接受 `63c0e012ae49a28196597f84ff6bf8d3eadcd3708cb5c3acbd1e90fb12607eb5`，排在B60后。
- 后续normal15的新tail28观察器仅改lineage／indices1–15，保留旧版本、controls及once路径；15 metadata tests通过，root公开validate_plan通过。精确一次认证权限 `cards/F1-following-normal15-terminal-checker-root-authorization-v2.json` SHA `b75ab3ef2e77e582ac9425f819aacc472f7a900df28ebfe9ba47761dc10388ae`；必须对应已终结首试全部交付且drain，recovered／partial不得强行进入，实际质量准入另行登记。
- token600新helper root离线接受 `ae950c8ee2cc373bcdc9b59214f8c388ad33dff67c1b9e1487a372ac97a09bd4`：56 owner测试＋2独立新增＝58 distinct，独立复跑14项不重复计数。实际三终态replay权限未签发；custodian仅准备新版最小评价adapter与合成验证。F9修复root离线接受 `6b96f7ee380073ea06f54ea998401702184a310b3a55549fa1e22d605e7ffa3e`，仍未GPU激活。

### 07:21 UTC 第二次token600失败、28项续跑与F5主评终结

- token600 seed09在07:05:33 UTC终止，session92640返回1。79批全部尝试、78交付、同一47cue尾批两次4096输出上限；80调用＝78 EOS＋2 limit，160次HTTP交换均200，无新的fatal观察。SAFE `475ad33010878425207fee512a48d87bc7efdc7c2bf1338f5f58342d752ff4f5`；完整成本602.621848秒，28/29完整SRT、3559/3606 cue，尚未native认证或赋质量分。字符串外空白约86.9%／86.2%只是机械线索，不证明因果。
- root重新校验140个指针、全部28卡及源／runtime身份，独立确认worker/server0与8080可绑定；原41ee.jobs[1:]登记 `cards/execution-queues/v5-after-token600-seed09-terminal-tail28-v1.json` SHA `1adf94498ccb2c6a88601ae2441ca64e1da6b0f126fde5d4894c9294b45b1f20`，执行批准 `ed49a62a0f7f7243a92b40c7d25889fc4c54fcc5cbe6a15901d8a850e26ca5ca`。GPU session51004已启动第三seed10；前两失败不重试，后续首次非零仍停。新journal `runs/v5-after-token600-seed09-terminal-tail28-v1-queue.jsonl`。未来36准入的有效链为30524前2＋56ffe前5＋c067前1＋daa5前5＋41ee前1＋新28全终态/drain，旧tail29不再处于运行状态。
- F5主评价session76961三seed全部EXIT0、各固定48窗封存，最终seal为08 `6ce94900c78b473e8734684cead4a27ddbfedd366e000d34696005d0b7dee1b8`、09 `47b826793f88645491b97c4b475e69ca081948cdac8deae93772757de50c5895`、10 `07576b4338a96a82f366e740be9698d43fe11c69d522073acae622887e48a905`。待root复核后释放安全汇总；09 whole-flow partial不能因评分窗完整而改为成功。token400先在原ROOT锁释放窗口准备，之后按既有权限进入F5 auxiliary PRIMARY504及风险队列。
- token600新helper `217add9992d4ee9f8f0656c0a369c25671b1da691028ee16f07d7d547770b5f4` 已冻结，56项离线测试＝20改编＋36新增，通过；readiness `8f1fcd164166cf1901f0a911b18f44f5a9bf0ddae6318695edac8d858a5938d8`。独立审查进行中，尚未授权实际replay。
- F9 collector窄修复的独立复审 `cf3ffc5b4aeb52e0fcfcc13953bd78f339e2fafbbcd9ce03c9de20c23c4e3af1` 通过，原五种raw与元数据冲突均被拒绝；40测试＝37已有覆盖复跑＋3独立新增。新readiness `b827768cf0fd191b17ae0a4c837d5f2718a486d2bbb8800c96b45774944bd7ed` 保留原12次顺序、源及runtime，真实GPU资格仍待精确时序准入，不把离线通过当模型收益。


### 06:55 UTC token600失败保留与29项续跑

- token600 seed08的79批全部尝试，78 delivered／1 translation_failed，80调用＝78 EOS＋2 limit，3559/3606 cue交付、28/29完整SRT。两次失败均为同一47cue尾批M01-S00325-b0002，input2349，输出4096；固定Q088五cue受影响。SAFE失败 `a900e4d06e6f129b34e17aca99ca48211c77f933b3569d77730310e9900b813a`、补充 `152075c5c26c5f950bc75d1feb1d6a793350452545abaabfe68a28b2686d4d9b`：80 tokenize与80 completion均HTTP200，两次约79%字符串外空白；普通失败，无fatal观察。尚非native机械认证，不直接赋质量分。
- root06:55:22 UTC重新观察GPU worker/server0、8080无监听，并核验原daa5十条开始／终结journal、29卡／21runtime／source/policy及所有新输出不存在。精确原daa5.jobs[5:]登记 `cards/execution-queues/v5-after-token600-seed08-terminal-tail29-v1.json` SHA `41ee05b14c9e9b7b385a73938955fc8cfe52ddaa3dcf70066f345f69ffd5de70`，执行批准 `989c710bd9ba56422a80404642ed9ac109cd18d13993c921df2db63ec8794017`，session92640已启动token600 seed09。新journal `runs/v5-after-token600-seed08-terminal-tail29-v1-queue.jsonl`；08不重跑，09/10不删除。未来36准入需合并30524前2＋56ffe前5＋c067前1＋daa5前5＋本tail29全终态/drain，未运行不是完成。
- token600新的closed partial helper只获实现／合成检查权限，原ff9/B60、61/67完整成功入口不改；须独立版本证明token600 count-map来源、79批packing及全部失败／成本，不冒用B60身份。
- CTX0实际19裁决获root launch `7acb71a2194820894f87a90f797c376ac125ac6ddaf36892942de71a64b70736`，原29中2一致、8缺accepted prior仍UNKNOWN。192＋423＋427物理文件和两原生drain收据重验，独立19测试（17原覆盖＋2新增）通过；native认证仍在原4329 guard内执行。排在CTX3独立review后、F3前。
- token400材料准备在共享index的12个额外既存代码pin缺失处拒绝，尚无私有材料；SAFE gap `e994548bb497de341097b4fcc1fb01a1b1fd2cbcfd97a9b0c7509cde18f59148`。已允许新metadata closure补齐原V7所需29模块，保留旧pin与失败记录，不修改controller。
- token400补齐29依赖后的metadata authority／bind_entry／verify_delivery通过；再次prepare停止是F5占用全局ROOT scheduler lock（原runner.py:260），不是schema或proof漂移。未写私有材料／未native调用，保留拒绝记录；F5三seed全部释放锁后按既有权限重试准备，禁止绕锁。


### 06:43 UTC 风险与后续准入更新

- CTX3独立review29已获精确launch `72af6851aa3349f4119273042c1ee3354c470c1ecc919b6d65cc05bd470c5456`，root核验193＋434物理文件、实际CLI、正向drain／writer0并通过公开preflight；独立审计 `c3a66e3c…` 新增7项反例通过，含6项已有覆盖复跑。排在F5主评／aux primary、B3裁决之后，不导入primary观点、包含6项未知。
- token400三个原生envelope经原67公开metadata核验，登记 `cards/F1-token400-screen-a-native-admission-registration-v1.json` SHA `e8adf7ef75158e6a86745fbc8d07dcad1f9ace83e28a781c2bf27cf273bf91b8`；仅放行固定144材料准备，裁判精确launch仍待。
- F9有限空白资格的独立审计发现collector未复核raw响应与accepted hash／cache／settings／EOS／ID覆盖的一致性，五种合成冲突可通过旧collector。审计 `f18edc82…` 要求窄修复，未激活GPU，原计划及代码先留快照；27原测试＋3新增测试不代表此缺口已解决。
- 风险prompt独立说明 `summaries/risk-prompt-contract-independent-audit-v1/memo.zh.md` SHA `abf7ebb5ca6b4eca56bb5bb48629892dc74b9bf93b872449019d79288cc07a3f`：unknown可无一侧中文quote与旧提示“两侧必须引用”冲突；minor可以作为严重根内occurrence，不能错误禁止全部minor。新提示只是提案，旧validator／schema／primary评分不改。待旧完整风险阶段后判断残余UNKNOWN是否影响结论；如需新版本，须新资格＋受影响组完整29fresh，不只补失败子集。
- S1／S2剩余证据图 `summaries/S1-S2-remaining-evidence-decision-map-v1/memo.zh.md` SHA `34dd87e7ad73d32c4e903ac2fe203cd1e068adda723dcb6d27e4cdc9a7e6bfd0`列出内点、方向、长期状态、背景同信息对照、审校触发器与交互的条件性问题。它是建议，不新增门槛或强制笛卡尔积；已知风险不禁止为解释／修复该风险设计诊断，但阻止把未解决配方作为已确认赢家。

### 06:33 UTC 判定层次澄清与接跑

- ROOT采纳规则解释 `summaries/confirmation-entry-policy-interpretation-v1/memo.zh.md` SHA `5fb79953ce4651129146ef753675917b63963e6973988e9e5e95e60a4563ebda`。筛选区间无需先达到最终优势／非劣门才允许选择候选；最多三套完整配方须在开启任何独立确认资料前统一锁定，最终接受阈值与family9不变。此前“不晋级”若暗示筛选未显著构成入口禁令，以本澄清为准；历史收据保留。已知新增实质major、真实交付失败及未处理关键混杂分别审查，不能被均值收益抵消。当前尚未锁定、未开启确认、未收敛。
- B60三终态已完成原生认证：08／09各47有效窗＋1认证delivery_zero，10为48有效窗，固定144分母；whole-flow仍false／false／true，前两seed各自认证delivery_zero窗口的自然度不可用、不填0，其余有效窗口仍照常评价。实际评价材料准备67.990秒完成，SAFE `76def4561f9cc43f24abd1964e24de95dc4c6d3e2941168f2601b43c844a362b`；root已逐字节复核256文件并通过实际CLI／公开启动验证：launch `714b0043b1f793892dda0e73f13cb81fed6b9336230b56f1985234d74a21e7c3`，接受 `42ce82dadac122cdd10edcba7b89355fe56a77a79e1a3c7056b529e154aeedcc`；排在现有已授权评价后，尚无质量结果。
- CTX3 primary29终结为23接受、6失败，38attempts；全29独立review正在准入，包含6未知。CTX0／CTX3共31次本地响应校验拒绝的分类已完成；发现minor-only根与可引用锚点的提示边界不足，旧validator、失败及当前review均不改，新澄清版本仍待审查。


### 06:07 UTC 三终态与评价启动更新

- 当前GPU session88235／tail34 `daa5a83b…` 已完成b60 seed10，runtime582.038492秒，06:05:44.925 UTC终结；已继续token400 seed08。runtime不是whole-flow，后者等待完整成本认证。b60前两seed partial均保留，未重跑或修复原结果。
- 新B60 closed native helper `ff9a08f096bcf04d6c7172da1108efec2269cbcc99257d5529d0bd5787b5f582` 经20项合成检查、独立10项重叠复跑及root全文审查；实际三终态离线回放authority `82096710da1f2dae8c228509b8ab02973153bb1fdcaa1352181b5dbbe640a326`、接受 `43cd0293f28621b54ab3846049f1fd42a6e62a4fed5af1331cbe0bee60a884aa`。只授权机械回放／envelope，不授权质量或新推理；HTTP／nonJSON／未完成分支仍fail closed。固定failed→0须以认证后的冻结规则为准，不能从SAFE诊断直接赋分。
- F5主评价root launch `e18ef889065963579a014eedadd65d16d26293431cc6ee237187c931d7ef0735` 已公开入口通过，201个私有准备文件逐字节核验，接受 `670010e0046b7ee138317449fb6cb6ab2af01776fe9d68a423da5052d281870b`。144主评＋144独立复评＋实际争议裁决，三个seed及09 wholepartial完整保留。
- CTX0独立review29 root launch `e3412db83e53078f4ff7cd6ea961a4cb74b5934d2f089822b5de90e4b312f706` 已通过192＋423文件核验、独立writer／drain观察和公开preflight；独立代码审计 `b5b3943d…` 共24 distinct合成检查（21原检查＋3新增）。CTX3主评全部drain后进入CTX0 review，再F5 main、F5 auxiliary PRIMARY504，之后原F3／F4 ordered／F9／b40队列。仅各自精确阶段授权，unknown不清零。
- B3完整96事后位置分析 `summaries/F1-b3-full96-position-analysis-v1/interpretation.zh.md` SHA `00c46eb713f8728b11a3d3322c3334052a184aaf942202ee1f5aeb0cf35fdf75` 已完成：旧bins不变，全部窗口批内均值均为middle；跨两个batch类别内部A/B符号反转，不能用跨更多batch的比例变化解释。场景位置仍有作品混杂；不作因果、赢家或新显著性结论。



### 05:11 UTC 补充记录

- b3完整96全部三seed：288主评＋288独立复核＋72实际裁决＝648 fresh accepted，无失败或导入；仍需统计及独立严重风险结论。root通过冻结92b的原生来源及六根绑定入口；完整成本与旧C0子进程成本不可直接比率，time ratio保持NULL。
- F5三次4096-token触顶机械诊断 `summaries/F5-native-limit-diagnostics-v1/formatting-refinement.json` SHA `dbcaa77ca0bc7e2a2db30194f66a84510fc05d6e607528013992f22e7e96acea`：98%以上为空白，在JSON对象闭合前重复，已输出unit正文仅52／111／121字符。相同请求重试后52／100／76 tokens完成；保留全部失败与重试成本，不据此归因cache或修改协议。此类触顶与seed09映射NULL／导出invalid分别记录。
- 新F5 mixed consumers root离线接受e178：控制aec、候选08／10 bbf、09 partial76ec；每seed完整原运行proof已认证。只允许准备精确六槽登记与非激活protocol／launch，尚无实际主／辅助质量调用。旧版本与资格不继承为新版本资格。

### 05:24 UTC 接入与资格更新

- F5实际六槽registry已root登记 `cards/F5-mixed-partial-six-slot-main-registry-root-v1.json` SHA `8fd557189fb7d1d8bbfc5a9865ba2927b5e318805ed9852e6417e97308708fe2`，root实际调用e3d逐角色／seed六个metadata callback，全部exact20通过，候选whole-complete仍为true／false／true。接受 `06fe78de6b1301ae357dd83039190c88afc29ac57f8c8d83ad0c4d0bba2bfbf8`只放行真实离线144主评价槽及252辅助槽材料准备，尚无实际裁判。
- 新F5辅助protocol `cards/F5-unit-partial-native-diagnostic-protocol-root-approved-v1.json` SHA `525292eebc4fcd23ce8628fc3d50ed9ed5e8011e3b645bcf7bfc43e6b99be63c` 已经真实source frame／固定reliability复算及9fd公开validator；新两项手写探针准备，旧协议资格不继承。
- 一致性A/B新profiles root接受 `summaries/consistency-bridge-native-profiles-root-acceptance-v1.json` SHA `6492c6682b6f9caa87f83277dfb2dedd6cc13da02e5cbe0caee151d0a6b4b63c`，资格map `e39fe62f9f0e7f4c1bcb51cb119df21f2b90f93c2a865ed55aa93b57bdb82fe9`。root重新hash sealed bytes／metadata／drain，接受原wrapper实际response验证链，未声称新response replay或语义准确；真实语料另行准入。
- b40完整96三seed均通过61c：375批全部EOS、无截断，full-flow655.851696／651.182510／668.189580秒；SAFE handoff `f3c1b641e77e9a795fb2b194c895de959b7ffcf2f26cb270815a4b2a5211bbde`。独立六根源码authority `23cb14f36fb861e1ec88d636d697db55e516ffb43976fbaf767ffec9aa0ba9db`已登记；质量入口与评价尚待，不冒充耗时等价。


- b40三seed真实V7 metadata准入完成：root registration `fe82926130c4ff3847b968221a1de35b2a92b2459bf71c7a19d95baae1afbb7e`、registered preparation `69d97315ffeadb23134e36c4f9fbc0a302ad058fe7e783a3d7e832d3d06bcd2f`、精确launch `14176320a5809ccea1ec3915b52b887551b4178aef717dfc4c3b83178dbd48e5`，root公开入口与CLI版本核验通过；实际裁判排在F3／F4 ordered／F9之后。
- F5新辅助两项探针精确launch已登记并公开_enroll通过：fidelity `57ecda732debd22294bdb6960fec7d7d9fe12ac71ea3c0fb39ad39b4c77d71dc`、attribution `e8773bc8ddcd312b591d32ddc972ee7ed893e4a63b0c9987f9e63aed94073266`，各仅一次／workers1／不重试；接受 `98a695b6df7c61de34178615bb86d68a0385e5f63a7a67da621b4fc9657f0c5d`。CTX0风险主评完成drain后插入两探针，再回原风险与F3队列；实际F5辅助语料调用尚未授权。


### 05:37 UTC 续跑与失败处理

- b60 seed08原始失败已冻结 `summaries/F1-b60-seed20261008-terminal-diagnosis-v1/safe-failure-receipt.json` SHA `58290beb385a0859cea3e79973ae0607cbbe26664d864ddd6ac31827e39f3af9`。3559／3606 cue delivered，28／29完整场景；失败47cue尾批两次输出触顶，约79%字符为字符串外空白，固定Q088窗5个评分cue受影响。机械诊断不自行赋分；后续完整native认证后须按冻结translation_failed→delivery_zero规则处理，与notrun／judge unknown的NULL区别保留。whole-trial613.755837秒，runtime610.257732秒，全部78次调用成本保留。
- root重新核验35卡／21 runtime模块及source/policy指针，05:33:28 UTC观察worker/server0、8080无监听；新队列严格原56ffe.jobs[5:]，保留b60 seed09／10。未来36项门须合并原30524前2终结、56ffe前5终结、新c067尾35终结，不把未启动当完成。
- F5实际主材料首次在共享index附带的8个既存源码pin缺失处拒绝，尚无私有评价根。新metadata closure `acc3508de1dfe77b05fd64668000b35b44d90e2a60e45cdaa402e7ffb5ebd19a`／external-pins-v2 `11a29aa892a659e33a985346bc501ba2890f9d5f886e473127c2376945abb472`仅补齐冻结依赖，未改controller或开放confirmation；继续原离线材料准备。

### 最新接跑指针（仅本节描述当前状态）

产物路径均相对`.local/translation-evaluation/hy30-flow-v2-20261008/`。恢复时核对真实进程、journal、trial completion和封签；会话ID仅用于当前宿主，不替代文件证据。

| 工作项 | 当前事实与下一步 |
| --- | --- |
| 最新补充核验 | F5三seed主评已封存：144主评＋144复评＋51裁决＝339 fresh accepted，3690封存文件root逐字节复核，质量安全汇总release `8a8c1814…`，统计准备中；whole-flow仍true／false／true。辅助PRIMARY504正由session52123执行，未授权辅助review或attribution。token400 fixed144材料准备完成，精确native launch `7ca2b293…` 已通过root公开验证并排在B60后。CTX0／CTX3及B3风险状态见对应条目，UNKNOWN保留。 |
| GPU | 当前session51004执行新tail28 `1adf9449…`，token600 seed10已于07:29:49 UTC完整结束，当前index1 b1 seed08运行；08／09原失败保留。最近root执行批准 `ed49a62a…`，上方07:21更新为权威入口。token400三seed完整，B60两partial一完整；后续normal15和源准备12仍待运行。未来36门须核对30524前2＋56ffe前5＋c067前1＋daa5前5＋41ee前1＋新28全部终态及drain，未运行不算完成。 |
| 批大小3／10／20 | matched48三组全部三seed评价已完成，fresh判断314／321／320；均未证明电影非劣。b20完整96三seed625 fresh，summary b02a：代表剧集/电影Δ+0.3185/+0.0926，family9区间跨0，新增半组剧集风险Δ−0.4444且三seed均负；现有未限定配方不进入确认。matched48风险封存c3e5：6个scene-local新增major组，4窗/6个window-seed对；22条unknown保留，不能用平均收益抵消。b3完整96三seed648 fresh全接受，summary1cf3：代表剧集/电影Δ+0.11667/+0.04630，family9均跨0，自然度两类均下降；尚未锁定，待风险与关键混杂审查，不以筛选区间跨零设确认入口禁令。b3 matched48风险primary22接受1失败/26attempts，review23全部首试接受，22实际结构争议准备裁决、1缺primary保留UNKNOWN；不外推完整96风险已清。b10完整96尚在GPU后续队列。 |
| b40／旧F4评价 | b40三seed生成已完整。seed08统一评价已封签SHA `f02754f42deafe834e5bed7adc9c7d50a55df377cd407a255b20393ae97d8c9b`，48主＋48独立复核＋11实际裁决全部接受；三seed全部封签并授权安全汇总，release SHA `2fcd5c600efcd01cc7a0e7962bdf0918074d1cd89c7e29e5060ca9a8059165bf`；144主＋144复核＋30裁决=318次均首试接受。安全汇总已开放：剧集Δ+0.3704／电影+0.1292，均未确认；root决定另立b40完整96扩展。旧F4-flex三seedfresh评价已全封存：144固定记录、4个机械0、308次接受。partial侧车018f通过16合成检查与15837原始文件哈希核验，root完整代码复核并激活2f300，原13e统计已完成d16a87：代表性动漫／电影Δ−0.0556／−0.1083，风险动漫／电影−0.3333／+0.2083；整流程交付门仍失败，严重根因未审查。 |
| 匹配验证 | 首seed734/734完整局部请求相同，但1批原生及解析输出不同；进入事前冻结的`evaluation-only/matched-control-evaluation-scope-v1.json`（SHA `6b72e98045a99689b58770338fe9639d75877ab270fce97600eb3687e4244ca0`）。旧96窗生成不重标为新48窗。逐判断完整输入相同才复用；三seed均已封签，共315条逐项判断复用、零新裁判调用。精确归档依赖解析103项离线检查通过，最后完整packet／元数据联合检查已通过，没有改旧根、协议或评分。 |
| 隔离实现 | r2引入F5精确分区／F6术语建议／F7证据场景卡，旧生成绑定其21模块。r3现已提升prepare／id-text／recipes／worker四运行文件和四新测试：共同源文宏块、显式输出预算、ordered非JSON协议。隔离132项与提升后150项通过；完整C0 874×3、匹配C0 734×3各自历史请求构造／token／顺序核验通过。五项新协议原生资格已通过，新卡绑定r3，不修改旧运行身份。 |
| C0代码复用 | 新旧代码的734批×3seed纯构造／dispatch审计通过，只证明未来相同29场景workload的代码行为身份。`summaries/C0-staged-behavior-reuse-v1-scope-clarification.json`明确不替代本次34→29场景真实生成／packet验证，不继承旧计时。 |
| 下一协议资格 | F5／F7、F6max32、F8均已有两场景机械资格，主语义分母0。v5五项独立审计索引SHA `c6b42d7b95304d62ebf26fcbfbc4e0e87a12915ac31039883f45beab782620ab`：ordered-text54批、b80/output3072四批、common b3／5／20分别90／54／14批，均完整270cue／2SRT、首试EOS未截断。共同源文三组逐cue实际可见源身份一致；不推断其余场景容量或质量收益。旧F4-flex／b80-4096失败保留。 |
| v5评价入口 | 当前native session52123执行F5辅助PRIMARY504；F5 MAIN已三seed封存并允许安全统计。之后已授权顺序为B3裁决22→CTX3 review29→CTX0裁决19→F3三seed→F4 ordered三seed→F9三seed→b40 full96三seed→B60三seed→token400三seed，全部global6。B60固定144中142 fresh主评／复核＋2认证delivery_zero，whole-flow两partial一完整；token600评价adapter仅获离线准备权限、真实准入待三终态认证。多阶段或partial不得套完整成功61／67入口。 |
| 测量与诊断 | 判定政策保持SHA `409553d1a5e2cbfb2e329d415a2b0e862b6a248550b5be5812dffcc4f3c85a9e`。自然度原48次C0重复均零缺陷；另20合成arms×3已完成，六组预设轻微缺陷均可重复区分；真实F7检出率未验证。F2远距／方向几何已核对，F1位置诊断设计已冻结，均用于后续自适应探索，不预选赢家。 |
| 尚未完成 | F1范围与转折、F2–F8质量筛选、必要交互、96窗扩展、独立确认和正式配对计时均未完成。48窗confirmation仍封存，探索尚未收敛，当前基线不变。 |

### 执行证据追加记录（保留当时状态，不作为当前队列指令）

- F5三seed原生生成均已终结：08／10完整，09 partial。新partial helper SHA `76ec393bc6d377fb3611fe3a005f77c88b61870d734fa081df8323c51be6f093`获root离线接受`971731c890f9232df169433d6b27214cc9e38abd9fc30625b0c423170119232b`；83项独立case由组合命令覆盖，10项独立复审与其重叠，不称93或单次83通过。实际09全734批准入`d7275c92db053a46b155cd55f1dc7ae53a998350d6beb5165459233f4fcc8e54`，root再核验13658原始文件并批准exact20 build `6a834a5549b002d658ba0bf50ea28a2d7cad89543a2138d5ab096aa4d1326210`；仍是27/29完整、5 mapping NULL＋1 invalid。完整2118 attempts含2次native触顶后恢复，不把此前失败批局部EOS诊断外推全trial。10的bbf准入`b5f55bdf5afbb7f740b2e1d569fddcd7af00a35af3124d3c70abe083ff601c14`，12265文件重哈希通过，build批准`118e93f00a179a770bdef7c790eb0fcfccab87846ef9338627019db475e06b94`；1885 attempts含1次native触顶后恢复，29 SRT完整。09／10外部seal与新混合逐seed路由仍待，不改08 bbf或旧C0 aec身份。
- CTX3全29／144自适应风险PRIMARY29已获精确v3 launch `c3b441a00f4fe1074f3656c39064bd84e100e0616fa87aacadee177b5e0b707a`，root193原始文件、零历史、无对应writer、CLI及公开preflight通过。171 severe claim occurrences／80 annotation records只是注释，不是风险根数。排在一致性两探针→CTX0 primary→b3 review之后、F3之前；只primary，最多58 attempts。root初版v2 attestation仍保留proposal三个NULL观察值，preflight在dispatch前拒绝；该历史原样保留，只有新v3明确记录独立观察的零值并获接受，不使用v2 launch。
- 交互备忘录 `summaries/interaction-design-options-v1/memo.zh.md` SHA `9f19123398a244f1068f270c6b1240c7299421d6ae82ddb76ee4577de6555670`提出条件性b3／b5×ctx0／ctx3小矩形，尚未新建卡或调用；须等待完整96和风险证据决定。正式计时准备度审查 `summaries/formal-timing-readiness-audit-v1/memo.zh.md` SHA `039cce5da09de04168cfd7d06deb930472ba6f40dff3f6dbed3c087ad4ad43ce`确认现有完整墙钟、缓存及独立固定N入口，同时指出最终配方还需逐leg严格native配置准入和整leg裁判drain／hold证据；未实际计时或声明历史污染。
- V9状态修正完成：最终controller SHA `91853e086ec27a1a00c531912fda99c307d8551a242df62a7074eedfdf1b5885`，29项owner检查及其中3项独立增量检查通过；root全文复核及AST确认仅`generation_attempt_frame`变化，离线接受 `7f3cd16776d8a793cdc6d58e9f6dd76701db56cc64dc020f9932162a1d543fdd`。保留execution／source-preparation尝试文件时拒绝not_run；空目录及纯准备状态仍保留720 NULL。未授权实际生成、准入或裁判；后续须绑定九项真实终结状态及独立完整native proof。
- 一致性新调用链路的两项手写探针已完成精确root登记，`summaries/consistency-bridge-native-probes-root-dispatch-registration-v1.json` SHA `8b1ed57cef84d6362139b80e98b45b5b5ee5c0f896a1e319872b01e2b962edea`。root逐项核验离线enrollment原50文件、公开入口与实际activation元数据；A／B新outer activation分别`9157f5fd39b79e1090b30c48d1668d573767ce8ea605c5268541abf63ee6f0e4`／`edfd971f356ac6d0774b5a409012c6f7b288ada6cc5a7c3f2f0aec8341410591`。只允许各一次、workers1、无重试，唯一custodian在当前b3完整96三seed全drain后执行，再接ctx0风险；尚无探针结果或真实一致性质量结论。
- F5 seed08新bbf机械准入完成，734批／29场景完整、1932原生阶段调用均首试接受；exact20 proof `74c6ff85e0e68e40d09c3703395a5ba68192d98ac627b95598e52a4fd3e71eb1`、一次成本authority `1663078b5b381b35ed2259bdbf8d620972f481ff0316ca7c33f2e32324f81db6`。root独立封签 `1d98c5c9cd9e03ee70d0db2fb3c7e1a65097ccb9a3c92add5cdf68dab1054ba8`，实际metadata callback重验原始清单通过，receipt `fe68fa33c7f331676dcda886bc87bd6d5c487ae4bfb246d724e22ac2d9d4130c`；不授权辅助调用或宣称质量通过。
- F5 seed09对bbf的单次准入在missing／invalid交付guard处拒绝，尚未进行全native replay；拒绝receipt `efccf23bb3491d43822f9042215d5b905c0df61651ce40e212b0a59e1cb81016`。这与已知映射／SRT失败分别保留，不能冒充完整认证。正在另立partial helper及精确seed路由：区分worker执行完整与字幕交付完整，保持mapping NULL、invalid、全部原始成本；不修改bbf／aec或重跑seed09。既有合成native尾批失败测试不能代替实际invalid-SRT情形。
- V9独立窄范围审查5项通过，receipt `7819b43c2802cd88ccd3e495e83e128b8baf519b36b01b830d41c30426966e64`；发现无顶层trial标记但保留execution尝试文件时仍可登记not_run的状态缺口。仍为720 NULL且无调用，但会误标执行历史；正在修正，尚未root接受该版本。

- F5 seed09原始失败完整保留，安全诊断 `summaries/F5-seed20261009-terminal-failure-diagnosis-v1/diagnosis-receipt.json` SHA `d57022d9286006d505f0efcceb658487744d6a6c9cd61591e36d1b395a750504`。一个3cue单元联合译文仅2字符，无法拆为3个非空精确子串，两次mapper原样返回unresolved；另1cue开头空行导致SRT无效。3600 delivered＋5 mapping_unjudgeable＋1 invalid，评分240cue未受这些位置影响，但只27/29场景完整，不能宣称whole-flow成功。原2118调用、输入1298285／输出214369 token保留；aux1243.537秒属于generation1733.250秒的子集，不相加，完整trial1904.809秒。此诊断不是完整734主证明准入。
- 原42 session39398在04:07:20 UTC退出1，完整4条journal SHA `5f1b210b4ccf33e1de2cfd10d8faa56a4a8834f4adc028a263b02d89a23b5c10`。root在实际失败分类和新drain核验后登记40项续跑queue `56ffe7f66806b6314c7176ef366c6cb0889a3b84619cdb5d9324a3df618be0d7`，批准 `7932e7f7b4784acdab130106fce707da2d88a75d1454a3bebce4b7dd2b26ebeb`，session19560已启动；exact原jobs[2:]，无隐式重试或卡片修改。
- F5候选专用新helper `v2_unit_main_proof_singleton.py` SHA `bbf81f0a8ba72aac601ba7085a2d2f2d55521183c94c75a673b485ace58acae7`只修复合法单目标尾批planning跳过；root AST复核20个其余函数及imports/constants不变。73项离线检查通过，readiness `74243f8933267b4f693d062045aa4fcd18318e5b5501e95ac6a1988c6dd63e55`，root接受 `01401d971b28047d0f59626a012dad7426978151d02b23e54b8a923f45d85351`。新候选replay `84624789c7ee2c96178430fc49e053040ab91ac9d3826fe2294d2eb40971d8c8`、seed08 authority `b016ae99f9c8fafb803a7ca74a8edd0dae340f98a1ea1335de324e695437ceaf`已授权完整机械鉴权，尚未批准proof build；历史C0保持aec/fbee，新role/seed callback与V10／辅助runner版本另行准备。
- b3风险独立review23获精确root launch `1b7b3d8b22e332e687bb6de3f2ed7e8feac95a8276c1ccb6b90d9aaa2710773e`；root复核149原准备＋324 primary物理文件、原正向drain链及零活动ancestry writer，公开preflight通过。原22接受／1失败与26 attempts保留，所有23 fresh复核，包括失败primary场景；只review，最多46 attempts，不重跑primary或提前裁决。排在b3完整96、ctx0 PRIMARY29之后。
- b3完整96 seed08已封签 `d1df56ed0e1b85ed6a52a932848962ae8886e573d64119340fada932c9457443`，96主＋96复核＋22实际裁决均接受；session53514继续09／10，all3 release前不读取质量。
- 临时覆盖矩阵（非最终报告）`summaries/convergence-coverage-audit-v1/coverage-v2.zh.md` SHA `96fc5b10fd806e00ae03c757adabd270a7a98fdcdda9e920ec6c48b632ad1f4a`。纠正历史与当前资格混称：b60／token400／600有旧v3两场景机械记录，不能冒充当前r3全29范围通过；common另有当前两场景资格。关键交互、真实F3／新F4／F5–F8质量、严重风险、正式计时及确认仍有缺口，不因队列或预算收敛。


- F2新增9卡完成源侧独立复核与冻结：final readiness `7cbcb52267e99a8c1a6b94120b75a8ab564312b52b30297fb83da4f0713cfa86`，独立final rehash `fb56f9f07f693c6ff2721cceeb50aadc20ed502a382190d30e5a5338219e223f`。freeze `3af174d0d4970621c80320cc50a6dc93145ddb11fffcbd38162b30d150524b7d`、queue `e317d3c4541669a2643804e467f7867afa2ed609878446aaefedc0fc334fae54`。固定720质量槽、7446 nominal批，12 owner与8独立离线检查通过；完整96对照与matched48对照分开，ctx8实际容量仍未知，不缩输出或截断源文。V9封闭准入正在准备，不改当前42队列。
- ctx0全29风险PRIMARY29获精确root launch `968144518313ff45765c02b056f13c5020a2759469420dae20407c754248a884`。root重验原192文件、29零历史、源execution／response与新overlay不存在、无相应活动writer，实际CLI版本及哈希符合；原不变性attestation `81686db910fc05d4213199e679ead62d460f0f245ddb4d706357832f12022bd7`、review `b097d1c578ddbd4185b9d16f10083400cca2858ed6d73e3c968e36f892a41c29`。公开preflight通过且尚无新dispatch；只授权primary，后续独立review／裁决另行登记。
- b3风险primary封签 `3d8923b02cc725a35d5b9c92405b34b1daee7e191f088acf1a8df152d34e0750`，safe handoff `fde04fa9a841a4a0f4f94922faad6e339ef6ee47747d06f268e9b7529b137e04`。22接受／1失败不代表风险已裁定；全部23 fresh review正在准备新历史authority。原26 attempts保留。
- 一致性新bridge runner最终 `d954a0f85b1b53d1fa6d70442c202fced29687b7ffac9d3162bfd1abdfebc4fc`，26项完整离线测试通过（1617.870秒），独立5项范围检查另列且不相加。root重哈希11指针并复核后离线接受 `415c3d838335b1632c22ea9d96b045b1cca3e11d4b13091419a93b4f589559a4`。新封闭producer及手写A/B探针仅准备，须在guard前拒绝executable非精确字符串；旧探针不代替新调用链路资格。
- F5 seed08完整trial结束1690.837秒；1629.666秒仅子运行，不能代替完整成本。root初版authority多了三个元数据字段，被冻结七字段ABI拒绝，保留 `4d534e651a59ce8d823a8ee4f6ec5998ce95077f2452447abfc7b6bdb880078f`；新版七字段authority `44ce660cf667c8190fee72329748a9fc32eab4cf2b8bbc071869455fe47d19f6`通过该入口，但随后发现校验器对单目标尾批仍调用planning_prompt，而runtime按设计跳过。尚未产出admission／主proof，正在代码及合成独立诊断；不修改原运行、冻结aec或将此机械缺口计作候选失败。
- ctx3中文解释及0／1／3自适应描述表已完成；后者 `summaries/F2-context-0-1-3-adaptive-descriptive-v1/report.zh.md` SHA `2e667a9370407ac82b8baadf234451e4d742c351bd8468efc0fa9a9c1185c811`。共享C0只计一次，九份原始生成成本不重复；没有直接ctx3−ctx0新检验或因果结论。


- ctx3原13e安全统计完成，summary SHA `8465717f01401a5e75a0319c6db24a62547a85e54c0610fc9e36d39c72b68a00`、receipt SHA `053cfe67ef5ff186bd936235d7b207e1f8bfbf802424ba65f2402e7473ba291e`。代表窗剧集／电影Δ+0.33333／+0.07917，family9区间[+0.01852,+0.83333]／[−0.05,+0.33333]；风险剧集约0／电影−0.04167。剧集LOO均正，但风险均值0由Komi正贡献抵消SPY与SAO负贡献，不能证明无风险。均值完整trial675.234秒对matchedC0 631.605秒，非正式ABBA。
- 新F2自适应设计批准SHA `025468f66bed0f6e7e1ccef2dbe39ce59400983b7726968d76ab521107390f52`仅准备9卡：ctx0／ctx3各完整96三seed、ctx8对称8/8的screen-a三seed。依据是收益与异质性尚未充分区分及0/1/3的非单调现象；明确晚于两组安全结果，未改变判定、风险历史、当前42队列或confirmation。更远实际prompt容量及生成／裁判尚未放行，不预选最优。
- 起点偏移helper最终65d7获得root全文复核，原公开verify_registration实际重算27源卡／9几何／270槽通过；外部登记SHA `1f07d580976cb11b8a244e7ca0197085e20b63741953ad968ed9fd9e6a957264`，离线接受SHA `d3711516de2212028fb84fea45efeaeae34794191c0fce26346ee075ce01f607`。原生23/115与诊断10/50保持分开，所有27输出尚不存在；此登记不授权实际生成或judge。


- ctx3三seed共144主评／144复核／30实际裁决=318次fresh接受，交接SHA `52a4d16063c042146984082512aa143fa66f24fcea97702004824314af61dbca`。root重哈希106指针及1142／1142／1175封存文件后开放安全统计，release SHA `64a1f9cdd6df729a0c5e85055b6fc1f4b25905cf652c0767d883e0021b0fa35b`；原13e/f808比较fresh matched29，固定144，结果待。
- F8手写Hreview探针恰一次原生接受，seal SHA `cb82b2b00efa0c507f0e6c075da9b7580937b289caadad3c49b5ac060ee3c000`。root原9aa公共validator重验通过，资格登记SHA `1089beed7d72d5bcfe6493f86555c0b7c79cdb5c8beb7ab82b5339fbf22ebb8e`。仅传输／机器绑定／quote兼容，实际F8语料与敏感度未验证；完成drain后b3风险23项primary session97921接跑。
- F9三seed实际V6 launch已放行SHA `a47b6292eca4983824cc536bcd9022acc3c5e316256ee2235deec62de1bbe433`，位于`evaluation-only/F9-b80-output3072-v6-launch-preparation-v1/root-activated-launch-v1.json`；root核验精确manifest ce9c／wrapper aacf、CLI及原V6三入口。排在F4之后，各48 fresh主评与复核及实际争议裁决，不复用旧4096失败；三seal前不开放质量。


- F9 b80/output3072三seed均通过实际61机械审计，root再核验全部原始清单并登记 `cards/F9-b80-output3072-screen-a-native-admission-registration-v1.json` SHA `0d91b974122b20a766e8e26aa80da55a5e9c4f3046987ec4d53bc8c32053e10b`。每seed58批／29SRT完整，prompt最大4917≤5056、输出最大1820／1829／1836<3072，完整墙钟570.932／569.715／574.701秒；尚无质量证据。V6 fresh三seed评价正在准备。


- 当前18任务e36d全部退出0，末项03:06:03 UTC。root核验36条完整开始／结束journal、GPU无残留server、后续42全部卡／源／21模块／parent gates哈希一致且输出不存在后，启动queue30524，session39398。F5三seed正在首组生成，实际语义单元主证明和辅助裁判待终态准入。
- b3完整96受限源码桥接最终SHA `92b9dc4cb6bb62ccc7fbfd35260bea22ed92212b1d74c300b0ce6031ddffc232`获root离线接受SHA `12af258dd5a0235f096dd5e69036d6c51c3a818032fad75c2006cb9f1eb07123`；21 owner检查及3项重叠定向独立检查通过。实际比较还须all3 release、六seal精确登记及独立执行批准，不能用源码批准代替质量放行。


- just的v2离线入口新增F8 root runner测试模块，55个模块路径均存在；已引用定向检查，不重复整套长测试。README、AGENTS和docs/INDEX相关路由已复核，无需更改基线路由或索引。


- 起点诊断v2源卡准备完成，收据SHA `42fe8ada787ad17c7ec909a445d8aa13bdf5cb70fe89332916d4938f6cf6b2cf`。27卡／270诊断槽／7053 nominal批，明确23窗机械sidecar与10窗诊断分离，旧v1字节保留；实际GPU与judge均未放行。


- F8最终runner获得离线接受SHA `cebfe568df78bfc2af09b8b2f88e611754285a2a74ab2b3558e52ab6c959d21a`；root全文复核producer／wrapper、重哈希26指针并实际纯认证通过后，单个手写hypothesis-review探针放行SHA `451d9f7c28b2bd2f52f82744d030c98b9591ce74e69c8e9865853d610c9a2e8b`。固定1 job／1 attempt／workers1，排在ctx3三seed全drain后、b3风险primary前；无自动重试或真实F8素材准入。README已更新实现与未验证边界。
- F4 ordered实际V6 launch已放行，`evaluation-only/F4-ordered-b5-v6-launch-preparation-v1/root-activated-launch-v1.json` SHA `8384e56871c122e46083bc1a90cc6f9ef86253e81c6eaab00d1ae6b04137562a`，manifest SHA `775c1c5685b47b24d363635bdc992c8494a15ce9414cd07e76b63067e063a89d`。root核验实际CLI／wrapper及V6 metadata三入口、launch和authority；每seed48 fresh主评／复核及实际争议裁决，排在F3之后，不导入旧flex意见。
- ctx0中文安全解释SHA `80ce00886eadb728fbab8e35cb01cafd265366b497d0c5c05429438c98d9163c`，最终导出验证SHA `c1f2b8c76c1e9dc55b41852b819536112fbb018ffb0adb28c10bf8b4f7b6b0d1`。代表窗动画逐一移除作品后仍为正，但电影Suzume与M02变化相抵、移除Suzume转负。动画风险退步集中一个SPY窗，严重程度仍未知；按统一全144 union规则准备风险核对，不能挑这一窗代替全规则。完整trial均值C0 631.605秒／ctx0 618.630秒，仅探索计时，正式节省未知。

- ctx0三seed安全统计退出0，summary SHA `79e42438034c538a9e62894de7aec0e8b6b48bb210c75c524fa5cad37eeaac57`、receipt SHA `c223484ed9c22ba957c83f8be794c8ecfcc7e3e54b6868000a98e68b81a95ca9`。144配对语义均已知；代表窗剧集／电影Δ+0.24074／+0.00417，family9区间[−0.11111,+0.64815]／[−0.125,+0.26667]；风险剧集／电影−0.11111／+0.04167。剧集风险区间上界恰0不称严格负；严重独立根因仍未知，不宣布赢家。
- F5两个原生手写profile探针各恰一次接受、零重试，安全交接SHA `ba65a4e4cb289f686652c2b3d8dd2ddeed18d5c328d9aea3a2c27581f563cc78`。root实际验证完整原生stdout／绑定／drain后登记 `cards/F5-native-profile-probe-root-qualification-v1.json` SHA `42a1df193f48f06ac6b7c245ce0db78c7472c63db5198530949af54d7815ef6f`；仅证明传输兼容，不证明真实候选质量、服务端模型或账单。真实F5主证明／辅助评价仍待生成及精确授权。
- F4 ordered三seed全部机械审计通过，root实际61重验完整清单并登记SHA `b4a8256e150d360014545f8765dc967aa6c3c43d105083319be04626d6eddccf`；全流程608.382／594.512／583.964秒。补充卡V6评价launch仍在准备，尚无质量结论。F9机械审计计划SHA `2fb6248889cc6f18cd4f1bd3f6dd0e6dc7910799433c257c8d96eb51456e70fd`精确约束58批／seed、输出3072／context8192／margin64，完整prompt上限5056，不套用4096输出预算的旧上限。
- F8 runner两项集成缺陷修复后最终SHA `9aa8b9634e74a13263e678b7c8904be7bef0a3cc19210f827eedf52abfd2b0f4`，test SHA `b67575605da3fd0813c0e343d54f50995631a6234544c454c5ea4f2b61264870`；27项owner定向检查和10项独立定向检查通过，独立回执SHA `754fa0b43ec07e1ca5d0373264824038cc65b2db501e3d2ebefcacc8b68601eb`。逐seed原始drain组合及重试前全部历史lease校验已覆盖；历史23项长suite没有冒充最终版本全套重跑。仅允许准备一个手写hypothesis-review兼容探针，真实调用尚未放行。

- ctx0三seed安全交接SHA `6a7781f3c10ae54002a2d98d77d1b94ca8755f15576e5ca60ab691ff0b7f95ca`，末seed封签SHA `43adf118e1de2a4a19b8335448efcb7cce5d254f4d2e106e55ae470967c3cc70`。root重哈希全部交接指针及1131／1142／1120文件，release SHA `76becbe9fddb3d2f1efca3025175a6aeb8fd40f5bed0f0f82e24b4e2190214c5`；固定144记录、fresh matched29控制，安全统计已启动。F5 fidelity一次探针session71288运行，随后attribution一次，无重试，再ctx3。
- 起点诊断设计已审阅，root批准SHA `d603e06a301eb3071e8e1df42ab8afedac499698f89ada44b0fb0806b73cf171`仅用于准备新卡／离线封闭准入：b3／b5／b20×offset0／1／2×三seed，共27 fresh trial、10完整场景／1297cue、10固定代表窗／270评价槽。两个额外起点仅按源几何选择；保留全部warmup，不修改已有主运行和42队列。明确设计晚于主筛选启动，不声称覆盖全部相位／风险；GPU和评价尚未放行。

- F3 V6实际launch已放行，`evaluation-only/F3-joint-json-v6-launch-preparation-v1/root-activated-launch-v1.json` SHA `88a82e95f53d8dc26e2fb31620fc00767a8e7a49239f452d940e921b3e868355`。root核验wrapper81fc／manifest41e2及实际V6 `verify_launch`／`verify_authority`、CLI版本／二进制；三个seed各48主评＋fresh复核及实际争议裁决，三seal之前不开放质量。排在ctx3、b3风险primary和b3 full96之后。
- b3完整96已获得独立、封闭六根的runtime源码等价登记，`cards/F1-b3-full96-runtime-source-equivalence-root-authority-v1.json` SHA `eb0da1d5e8398fdf52058c99ac35849575addac84c274c67f15a332c3fdce6cd`。root重哈希45指针、全文唯一未用choice增补、六次实际v2_worker命令及其他stable engine／template；不复用b20授权。C0旧卡S0／prequalification／缺省评分字段原样保留，96评价来自独立资格投影，不倒填旧生成。统计适配器仅在准备，尚无b3 full96质量结果。

- 一致性pair bridge UNKNOWN缺口已修复，最终代码SHA `19ef9eb7b8d1193310af68fd0a3c1a123ff9b8658e216f9e89ec8d1d9c08e796`，30项owner及8项独立公共接口合成检查通过；后者真实执行freeze→validate、174槽／六成本与漂移拒绝，原生可信准入边界明确stub。root针对性代码复核及pins核验后离线接受SHA `0bca34b955753ab095b30ae71007ee9987c5aeb2907753e55859658e1466d5a9`；真实素材／frame／裁判仍未授权。README已补实施边界，just新增对应测试模块，冻结runtime不变。
- 旧F4中文完整解释已完成，`summaries/F4-id-text-flex-terminal-partial-three-seed-screening-v1/interpretation.zh.md` SHA `0366697651d85bfa57299c645a67442407b8a5ddd82f3d1b97558043bb4705a1`；4个机械0记录实际来自2个固定窗口，不是4个独立源样本。自然度仅140/144已知，按冻结0/2缺分界处理，不把交付失败自然度填零。该具体flex实现不据此扩展，新的ordered协议继续；不宣布C0整体胜出或非JSON方向无效。

- 旧F4实际原13e统计退出0，summary SHA `d16a87c0532c9a68209b44a479a4f5a6e4e523f2aff759c1f627eaf4d15d2cac`、analysis-receipt SHA `b203138de8df20675eb72bb62f17c9a9ff50f2348f2b7d93a8628ff037013376`，root已重哈希核验。全144语义记录已知（含4个真实机械0），代表性动漫／电影差值−0.0556／−0.1083，风险动漫／电影−0.3333／+0.2083。三seed完整交付均失败，不能称完整流程赢家；新的ordered协议独立进行。
- F8 runner `c85bd9…`虽通过23项完整合成检查（1956.233秒），root集成审查发现其上游三seed seal共用单一drain参数，与V8要求逐seed原始lease一致的契约冲突；正在独立复现和修复，暂不批准实际F8探针。不把单模块通过冒充跨模块可接跑。

- F3 joint-json三seed全部734批机械通过，完整墙钟649.509／642.689／651.412秒。root实际67 `verify_envelope`核验三份全部留存清单，登记`cards/F3-joint-json-screen-a-native-admission-registration-v1.json` SHA `9c638c16272f3a57af95c3d8c39830a573a2a0cfbb56b99c85474c7912f34581`；V6 fresh评价launch正在准备，尚无质量结果。F4 ordered首seed734批机械通过，envelope `e792982942ac2578ccea767375782d962a5d1f7777754854b4f557d1c16c91b3`，其余seed待终态。
- F5两个手写原生兼容性探针的producer `aa4f5318…`通过16项fake调用检查与root全文复核，root实际metadata `_enroll`通过并各授权一次原生调用：fidelity launch SHA `e07618d81e2abb4cd8a8b026c55cc890f7865f87c61f21d62d95fa693d53e5c5`；attribution launch SHA `c168e6f9f2cc7dc2be3d345add6264da5b26aeef69833e5915422faf7b5b3daf`。排在ctx0三seed全部封存之后、ctx3之前；各maxattempt=1、无重试／语义修补，唯一custodian全局池。此刻未实际调用，不代表真实候选质量或服务端模型／账单证明。
- V8最终controller SHA `91a59cc3aeb696a15e2a3f0676d942a3b23919c00f73b21136dd003fdc4c2335`通过43项离线检查及独立限定审查，root完成代码复核与依赖重哈希，离线接受SHA `db5b7557b632cc7a6ed4ae22b69d328826561155c1d5c64bc5b4f7933e7f6601`。支持封闭F5/F6/F7/F8主准入及F8私有全分母／dev-only释放；实际proof、frame、launch尚未接纳，不能把离线通过当真实评价已执行。
- 一致性pair bridge的独立公共接口合成验证复现P2：unsupported-terminal UNKNOWN分支跳过历史C0与当前源文全文／时间／顺序join。原c6c代码及复现收据SHA `50ba8630ed1894291794e55b0963b225e468a519a7ac3ec8977e519f2c97a930`保留；正在窄修复。此前公共174槽正向组合测试通过不覆盖该错误，原native proof边界使用明示stub，未读取实际候选或授权真实frame。
- 旧F4部分失败的统计侧车SHA `018f9e487187ac018ed791e5fa7f970fa573009096769e125d2838e7b87a68f0`经root全文复核及全部最终pin核验，实际统计激活SHA `2f300843008b3ef991a21dea91b541db833e74219baa683bb4e3d77a2e6ea67b`。仅用原13e/f808与fresh matched29控制，保留144分母／4个机械0／原失败history和成本；严重风险仍未独立审查、整流程交付门=false，不进入确认。

- b20完整96安全统计已完成，summary SHA `b02a1c9f588344a0a3d7af82bddf71362702ea3f49f4d6782296dab9ee998e66`。候选语义288/288已知、C0为287/288；代表窗剧集完整配对35/36的Δ+0.3185，全分母0/4缺分界[+0.3148,+0.3519]，family9区间[−0.0370,+0.8148]；电影Δ+0.0926。新增screen-b剧集风险窗Δ−0.4444，三seed分别−0.6667／−0.5／−0.1667，与同次完整34场景screen-a的+0.3889不同，不可拿另一次29场景成绩混合。已知新增major和unknown继续阻止未限定b20进入确认；保留诊断对照，不能推断C0整体胜出或整个batch20方向被否证。中文异质性／位置解释已完成，报告06f99、完成收据fc47；screen-b风险退步主要集中SPY（−2）和SAO（−2.6667），Frieren与Fate为正，不当作每部作品均退步。
- F8最终准入helper `c3bad750…`已获root离线接受SHA `141ba5094a9079daf105eed25103fed30f46c3e56b2d476a6cc64551f1672f2b`（20 owner检查及15个定向复核，不相加当独立测试数）。F6／F7最终helper `2834a429…`的37检查及限定独立审查通过，root实际依赖重哈希，接受SHA `701e5a9bc1002894b6cfd3b9f80fa8e582d25344192ebcf694bbb930677e6005`；实际机械proof仍待生成。
- 旧F4三seed评价全部封存，144固定记录、4个真实机械0分，140主＋140复核＋28裁决共308 fresh判断接受。root独立重哈希1135／1093／1135文件后签发安全比较release SHA `bb9bba71e4e8f886a893befb8d35710649bea1879218d18c78e08e3a9a354dfd`；原每seed10／10／6失败批与1／2／1评分窗机械0是不同分母。整流程delivery_gate=false保留，尚须显式partial lineage sidecar复核后使用原13e统计。裁判已接跑ctx0 seed08 session57474。

- b20完整96受限统计适配器SHA `7f225a884c04f2ff95aca6018d43a39e98992c229b3ac799b1b4f88bccce045b`通过14项合成检查及独立代码复核SHA `edac2c759b25c34fd1d2c0e881f37a5a6a6722ee91f641323bd7a97d8055d490`。root阅读代码并重新核验精确pins，签发实际安全统计执行批准SHA `a33429d9f4515053709b67bedeae7337819568741261fa77705b99ad712dc779`；新输出目录保留此前失败v1，原13e／f808不改。适配器仅在原验证后为精确六根生成独立comparison class，导出恢复原runtime／source hash，不泛化到其他候选，也不解除major风险或计时口径限制。

- F3 joint-json seed09完整生成并经67 checker机械通过，734批首试EOS／未截断，完整墙钟642.689秒；report SHA `4dfcb8f264b57dfb4384eb8a125c14d902cba0f2e943e12308f3dc38145524fb`、envelope SHA `90411ba8c6a8f437fa81baf93ac4e0d33319f361184455be523e01253fcd8744`。01:56:48 UTC转入第三seed，前两seed机械成功不构成质量证据。

- 原34场景C0与b20的runtime源码限定审计已通过，receipt SHA `dc0c65b2b8a51c0e006b913daf248ea06a107333c389784be66541e4d534da9f`。唯一变更为argparse增加未选择的`v2_source_preparation`选项；12项纯检查及10个旧argv namespace对照通过。root独立核验全文去除该唯一新增选项后相同、六次actual command均选原v2_worker，其他stable engine／template一致，登记authority SHA `a3641ba788e59eaa4c7ee3e4bbc98b3ee3435dee3d710824cafea608b73b1617`。仅授权此六根源码等价关系，保留4fd／32a原hash；新统计适配器尚待复核，不推断译文、缓存轨迹、完整worker实现或计时等价。
- F3 joint-json seed08完整生成并经67 checker机械通过：734批／3606cue／29SRT，首试EOS未截断，完整墙钟649.509秒。report SHA `11c8d9dda38edced8ba1e305d81fcf62a0ebe002c216b4aa95a90240af310ea6`、envelope SHA `437c2729d1fe33773a97ea1ae9696823b5d74df56d7626323ddc55d63a441c8e`；其余seed及质量结论仍待。

- F5辅助runner已冻结SHA `13ca80a94954254122b0dea7c5fe50f36cd6dd6de2e0c573f44290165995acde`，59项离线检查通过、四次限定独立复核未留具体阻碍；实现收据SHA `ae2b68619b25dad1d2737312db139a5d742eb709fe57bfe4a88d6c0243ed075d`。root逐项核验代码／frame／188e抽样登记后批准protocol SHA `2fb9278951b5e1e8d06bf30f102dc06af24a08235e0a7266cf009052a3074504`，实际`_protocol`验证通过。两个手写兼容性探针尚待构造和精确launch放行，候选MAIN证明仍0，不隐含裁判调用授权。README已更新此实现边界，just入口新增其测试模块，53个模块路径检查通过；未重复整套长测试。

- b20完整96统计首次执行被原13e身份门拒绝，未生成summary。旧C0的`runtime_source_sha256`为`4fd5710802b2d8c4bd130c5e384bb906c1321f2f1e995a5d21d40a1539bca087`，新b20为`32a16f785dc7f36976b260a52d45764cd2b110ecb32a911a3e5afa5421e519f9`；其余已核对model／template／binary／DLL／settings一致不等于可忽略源码差异。失败收据SHA `b684a3c346dbb94cfbde84353033bf1f2125a2043093866d45ca56fef8d8e895`，六份留存源码与session指针SHA `844bca40dfab7301b7b029c516a163bdbeab89ce02e3fc1bf63e6d0b829535cf`。正在源码／命令限定审计；原13e／f808与旧结果不改，不能直接删除差异字段。

- ctx3实际评价launch SHA `e3dd678d904015990dc69b575e65ad52426693d618a81358912cf3840bd34aba`经root原9c `verify_launch`、1dac登记精确对应和实际CLI版本／二进制核验通过，已授权在ctx0后开展三seed各48窗fresh主评／复核及实际裁决，三seal之前不解封质量；不导入旧判断。ctx0／ctx3之后为b3风险primary、b3完整96，单一全局六槽归custodian管理。

- 完整96统计再次核对计时口径：原34场景C0的738.983／719.619／714.569秒仅覆盖含模型哈希核验的runtime subprocess，明确不含prepare／export；其完整流程耗时为NULL。安全成本收据SHA `5066cda5c4fb71c73642be085d903e8465084d4eb720ac060b4dc089f0ebf5be`。不得与新b20的完整trial墙钟直接计算全流程提速，也不能用29场景C0补齐34场景身份；正式AB／BA测量仍待后续候选锁定。

- ctx3三seed全部734批机械通过，完整墙钟669.521／680.315／675.866秒（并行CPU负载下探索计时，非正式配对计时）。root实际61 metadata-only三次核验完整清单后登记`cards/F2-ctx3-screen-a-native-admission-registration-v1.json` SHA `1dac1ef5f1113fc2d0253cc12e295c3c07f2bb5f1421996fd65c7e5a1fb41b7b`，交接SHA `dab76d4f95a29722a7b21b5ecbc07edb02581c66599d5c7faaef7554e1c83c8e`；尚无ctx3质量结果。
- 新F6／F7与F8机械准入模块的交叉审查发现可复现缺口：首次HTTP失败后合法重试被误拒绝、durable dispatch journal的保留／预算状态未充分核对，以及F8缓存硬停止及失败路径校验。独立合成反例收据分别SHA `b368db9aaa81eca6be28d24c4266c5ef9ca7c9bbd1b5fd4aeccd614dcab3138f`、`7693dc1515183a53510ee329830473b8972e8b41b511778c168b575ca110cb71`；旧候选helper快照保留后做窄修复，原冻结runtime／270／已执行试验不变。此前26／11通过仅属原覆盖，不能替代这些新增反例的修复验证。

- F5源文复核抽样已在候选生成前独立冻结，root登记SHA `188e6f4d67594becca454bb7ed664fd23f1ad5f7c0fb24bcd7ac076321492d88`，提案SHA `2d753cdb6196b5b0e03a4cad91dcd8c0bec96533f4d26b0dcf0328c161e84bd4`。每seed固定84个完整源批次，按phase／seed／batch ID的canonical SHA256排序取ceil(84/5)=17，三seed每lane51／252；fidelity两臂配对同槽，attribution独立phase域。root复算全部选择与test vector并核对源指针；不按未来输出unit数、cue数或成绩抽样，51不代表51个独立源样本。实际runner／调用尚未放行。

- b20完整96第三seed封签SHA `29f6536589057aa93435ce6f937c74e889c1362837bf2a6e01dba1ae8360042c`，三seed交接SHA `54a1640e598a1dcf7839f5f4c9be8a8dcee70f45c84b1f0d7aca236f99603bad`。root独立重哈希2183／2271／2238个文件及交接指针后签发安全统计release SHA `6d8d3f9286bcbde070b8136fe78cc1030a02595ad9e7715187b787dde1ec1919`。比较须用原完整34场景C0，不用matched29控制；625次fresh接受不等于625独立样本。matched48严重风险仍阻止放行，confirmation未开放。

- common-source exporter离线实现已接受，代码SHA `5245be567d833a9f67f7f11f8fba92786c92ea5745525567f53666f2f6a2fa27`、就绪SHA `09a685e23eed9420fd1e5e4188fb0f7e4d6a4f640e91884a39056016214bdbe9`；18个测试方法／106案例通过，root代码复核及全部声明依赖重哈希通过。九组连接使用明示projection stub，完整29场景／200批路径使用真实renderer；不能把合成证据当实际visibility。实际导出仍0，须先外部登记9份终态完整native证明。

- root已用冻结9c实际调用metadata-only `verify_launch`，核验ctx0 launch SHA `f42d9e5312d92d43446dea811c92097ba166c4a93fd848782ecebd84d84d9237`、7411三份机械登记及实际CLI二进制／版本，零裁判调用。已放行其三seed完整fresh评价，排在旧F4后；每seed48主评与独立复核、实际争议裁决，三份封签齐备才开放安全汇总。
- 历史C0一致性pair bridge设计 SHA `5e6c01e024d6097eea4fb5bbaa1ecf7430f9dbda6ea56070f5c1dcddb43c7461`已审查并批准新文件实现，分别保留fbee32／aec506历史控制和真实事前登记的候选证据；不改原270、911、b6a或已完成probe，不倒填“生成前批准”。实际素材提取／frame／调用另行核验。
- 新F6／F7主准入helper SHA `beea19f3bec54589ff4715d298d114b038eb1b55d349ffd710878216e7e9a49b`，26项native形状合成检查通过；新F8主准入helper SHA `acfcec050f67c42e8945571148ee388c96e0c20a62999872fb48e9b030d852ef`，11项检查通过。两者已进入交叉独立复核，实际准入尚未发生。已启动但缺规范delivery的执行明确拒绝准入，调用方仍须保留全部固定UNKNOWN槽，不能抽取成功子集。

- 一致性修订探针实际完成：A-v3原生恰一次接受，seal SHA `a80c826ef231745491808f880d40fe7cfc611f203ba647b2fa0c4fd7729630f5`；B-v2恰一次接受，seal SHA `ae8765f8057b06a0450e280bcde1210392d5f5db981518dfb25158a96fc46f3c`。A-v2先前wrapper路径类型错误为0原生调用，旧失败保留；新A-v3 launch SHA `40268f48832160c9ed9c3b1cfbbbba7f56b37f8ee14cea26422e8ca1fbda5bca`。session61317退出0／drained后，b20完整96 seed10已启动session30841，原9c／df8不变。
- root代码检查发现一致性270的live snapshot要求会拒绝旧C0（17声明／70捕获）与当前r3差异，不能因此重标或重跑旧控制来混淆身份。另拟薄pair bridge复用已外部封存的fbee32历史主proof与新F6／F7完整native准入；当前仅设计，原270／b6／911及probe结果不改。

- 裁判队列优先级更新（不改冻结launch／配方／三seed解封条件）：完成b20第三seed及原定旧F4三seed后，先评价已完整准入的F2 ctx0三seed、再ctx3三seed（若已准备），随后b3完整96；ctx3未准备则不空等。为高优先级上下文方向更早提供趋势反馈，b3扩展并未取消或减量。具体新launch仍逐项登记。
- b20风险中文补充说明`summaries/F1-b20-matched-risk-interpretation-addendum-v1.md`已冻结SHA `5935e46f161afdf21a81a7c06d80467e999ae09b9a6c76ebfb29695fbf937d43`，收据SHA `cbd043647f41f44707c7e1e28dbc1ab642b4a85930f64a3e051ad77ff2c32969`；只解释已释放48×3，不改主评分，也不以新增风险推断C0整体胜出。

- b20风险严重程度安全附录SHA `feca219fccc4f04637f87712a40f7ace5fcd5b116a61c417da6f994fbe467a1d`：新增严重项均为major，6个scene-local组／4窗／6个window-seed配对、9个supported occurrence，作品M03／M04／W11；W11同一窗三个seed均有信号。未报告新增critical不等于不存在。117条selected=105条registry覆盖（含10条unresolved）＋12条失败场景unknown；未知合计22，95条仅为未报告unknown，不能称95条全部无错误。27条union外不当零风险，完整96不由此附录覆盖。

- b20 matched48风险安全汇总已开放，SHA `c3e5d3a6e88e1da127da909ab62a769a3de47b712161dccafc67996bcbc3b6cb`。root逐项哈希核对20份新旧registry完全相同，terminal仅registry路径迁移。支持新增major／critical共6个scene-local组、4窗、6个window-seed配对；22条选中记录未知、4个封存场景含未解决occurrence。跨场景独立根数为null，不能把20个same／13个improved与6个new相减当净严重风险，也不能把27条union外记录当无风险。该结果阻止b20风险放行；完整96主评继续，严重程度及作品／seed拆分另出安全附录。
- F2 ctx0三seed全部734批机械通过，完整耗时617.088／641.363／597.440秒；root重新核验三envelope完整清单并登记`cards/F2-ctx0-screen-a-native-admission-registration-v1.json` SHA `7411a5171f90a1c47a813e9c76ec7a2f3738e09ed9636092fa418d7bada50916`。已授权准备原9c的48窗×3 fresh评价launch，尚未实际评价或开放质量。

- 风险零调用封存已退出0（session38050），`evaluation-only/F1-b20-risk-freeze-overlay-v2/final-seal.json` SHA `a53815029d3715cade17fcc04386c5f38e53cd411834dc7c97ef053c8f6f83a1`；实际20registry与全分母复核／安全汇总仍待。A-v2合成探针因wrapper将Path传为str，在guard及原生callback之前失败，native0；原根保留。root授权同一固定协议A-v3新根恰一次原生调用，单独记录恢复，不改旧失败；B-v2仍恰一次。
- F5历史C0主proof已由root外部登记`cards/F5-original-C0-main-proof-external-seal-v1.json` SHA `fbee32bdec993e576197edcc4fc87bba2f4cd96cce1587278cde5614444b64f6`；原三seed exact20 metadata callback实际通过，完整原清单重哈希，无raw重解析／新生成／新计时。F5候选proof仍0。新辅助runner设计SHA `de5da6084c9972b6f11f9c69f697cbd9de4668685a8f85bed863ba972195dc2e`已批准独立实现，固定252源slot、完整native fidelity与独立attribution；实际裁判调用另行登记。

- b20完整96 seed09已封签SHA `8b80fdc1c1adbc594d7b12bb9da8e5983c9f8de47511db941d071020af26b9a6`：96主＋96复核＋20裁决全部接受，session91403退出0；三seed前仍不解封质量。
- 风险新实际checkpoint准备通过，receipt SHA `653cd68e59dbc46b35d2d0734aa00c3a436514fbcece0e809fac2f97171accef`、checkpoint SHA `b31de2ddc9771e437b4966ef4c351a016da1695afe4255e6eab2a3e4ec0c4814`。65历史判断／67尝试、20原registry全部逐字节一致、144分母；未调用模型或改旧文件。root登记`evaluation-only/F1-b20-risk-freeze-only-launch-v2.json` SHA `8b79346ea2207b278aae46ef6f742b8d7f786f6ee3b4dae84d46d32c48f17325`，仅授权4329在原全局lease下对精确新overlay封存一次、0新意见，实际终态待核实。
- v7 controller SHA `6a579901c3a3c40baba4223a43ebb24644c11d029a7e307c9919c6089b58ef05`获得独立限定复核SHA `514a1380e76ebd56a163c1b27148e5735809197805ea826263d10eb7b7493cf2`：8项外层含17项生命周期回归通过，原v5／v6不变。仅新增b40完整96／b60 screen-a闭集profile，真实native准入仍待生成完成，不自动授权派发。

- F2 ctx0首seed完整29场景／3606cue／734批机械通过，fulltrial617.088秒，原生首试EOS无截断；envelope SHA `edaaf0d8626b356b5a95ed718f29fa9d72c36dfeca4959273a73283c10ef1974`。第二seed00:51:32 UTC完成退出0待审计，第三seed运行中；未开放质量。
- 风险新版controller SHA `4329beb2cc9955142dd7f16837c2fdfe80f11bd69d02a0f995b036bba3014703`获得限定独立复核：11项Windows／封存与15项dispatch检查通过，收据SHA `f22ff24881d2619c1aa33338ed1b1e568d79fc365ae82e544613303c5ece0944`。真实历史新checkpoint准备中，旧CRLF／stdin记录不改，0新意见；实际封存及后续dispatch授权分开。
- 一致性prompt adapter最终SHA `757be87acb4e08ab30fbab6400ed51f105866be34ec5a75d8f44b25571119c03`，独立复核SHA `ca1995fa6622a73159282cb9732ed946dfcc2e7d6a625da08c7854ce94ad8c9e`确认精确probe根绑定。root批准新固定A／B各最多一次，待当前评价seed释放全局池；原0接受／2unknown不改写。
- F5主proof新模块SHA `aec506822df7844377782759c06087e33ef9eaf095bace90bd57c7f9ee745c6d`，64项离线通过；OLD匹配C0三seed完整734批再认证proposal SHA `f5f3155b5d27af18ead66e744802606d3b9fab9bd2ecda7220844cb3ec12a7dd`待独立root审查，尚无正式MAIN_PROOF或实际F5结果。
- F8根证据adapter SHA `8ec17c2a6e4b95c9ee34f64df870357aa0fbf72f36df7b9a2c76fea922b39698`，最终18项离线通过699.175秒并独立复核；旧摘要预报19项不是最终测试数。完整私有144重新鉴权后仅开发90可释放，留出54保持封存；runner与phase封存尚待实现。共享测试入口新增F5主proof、一致性prompt和F8根证据三模块，未改变生成runtime21。

- b3完整96新launch `evaluation-only/F1-b3-full96-v5-custody-launch-v1.json` SHA `589a98bbb853a58078af37fabf47a18bdb1a1c915582849f3a7bee30c86b9182`已由root实际`verify_launch`及三份机械登记逐项一致性核验通过，授权原9c执行fresh三seed96全窗评价，排在b20与旧F4之后，全部封签才发布质量。
- 风险Windows诊断进一步直接核对全部67份真实`stdin.bin`：均与canonical LF相同，原prompt CRLF另行raw SHA绑定。新收据SHA `092fb54bb640799c7a884ef0e21a31349fe506f5de8c175c73ef27fda7022f3e`；不存在缺失stdin须推断补证的情况，旧文件／报告原样保留。

- 新risk checkpoint首次真实准备session65326退出1：`History actual attempt bytes differ`。诊断确认旧runner的`Path.write_text`写出CRLF，而fingerprint／发送内容使用canonical LF；现有23个主轮attempt仅有该换行差异，记录raw SHA相符。未改旧文件或冒称通过；新版本将分开保留raw哈希与实际stdin／canonical身份，加入Windows原生夹具和变更拒绝。7c4及失败新目录保留，b20下一seed继续，不为空等修复。
- b60 root gate首版复制提案时遗留pending／not-authorized标记，已保留旧版并另建明确批准的`cards/F1-b60-screen-a-root-gate-v2.json` SHA `7fd539072d8a25f13b01fb9e212c1ad2e983b72fe0df6166772193f600f543d8`。对应未来42队列v2 `cards/execution-queues/v5-after-current-families-and-adaptive-v2.json` SHA `30524d54e37a8eb2328eee1896461866d9bd2edac8e71745f14a7384039d98fe`仅替换gate指针，全部卡片、42任务顺序和未执行状态不变；以此v2为最新派发路由。

- 新b40完整96／b60 screen-a三seed卡片获root生成授权，独立元数据审查SHA `86ca58f9704d8ec4982dd0be641704d188ffe94c422cec701afbe41ae9f52002`。root gates分别`cards/F1-b40-full96-root-gate-v1.json` SHA `59c33501cddfd29bb0a19ca6323ab082f5116a2556b478547d79e570126143b8`与`cards/F1-b60-screen-a-root-gate-v1.json` SHA `db080f78e950bbb7bc3956abd151eaff30d09f58dac66755e33ab761c3956723`；每seed125／77批，完整native容量仍待实跑。
- 当前18项之后改用新42项队列`cards/execution-queues/v5-after-current-families-and-adaptive-v1.json` SHA `354bf5625581ba99b6fae1328779a1d7e8fd3bcfa5cd8cf1c7a1da40dd2e59d7`：先F5三seed，再新增b40完整96与b60各三seed，其后原36队列剩余33项。旧36/d7fb仅被替代派发路由、原文件保持；42输出仍全未尝试，不自动启动并行GPU。新evaluation profile另行实现，不由生成授权推定。

- b20完整96 seed08原生评价封签SHA `14eb56605117eefb743648b391b19eb1c87c925d460266b67dac3cde2cbd19ce`，204条判断全部接受、无failed／pending。三seed完成前不开放质量；当前native边界优先处理7c4零调用risk checkpoint，随后继续09／10。

- b3完整96三seed已全部独立准入核对并登记：`cards/F1-b3-full96-native-admission-registration-v1.json` SHA `61575834d8b3a205f1588f6b78d8c53ffb0503d015cd6f36834f8fc57e1dd235`，handoff SHA `1281d72364353b9f9f3783e2f5b1af3447cbc6f55b1cc1f15dce99bba921b409`。第三envelope SHA `9795ab3972c6235ebc5976c811fb27c93e27cf0ed120c221c7a698a884e26010`；三seed完整耗时867.178／871.320／889.498秒，均1441首试批次。root重新核对完整retained／transport／snapshot清单；custodian准备9c新launch，计划b20三seed及旧F4之后评价，质量未开放。

- b20风险旧CPU后处理已停止并保存：root独立检查PID47120不存在，三份custody均drained／0callbacks／0owned jobs；65原ledger、20registry及相关原指针hash相符，63接受／2失败／67尝试。新增donor内`root-native-drain-postprocess-completion-v1.json` SHA `fca76c09e36f202a381d573404a2aad08ea51992bdcbbd4988516f2126540d55`，明确仅中断后处理，未改native状态，原raw finalization仍缺。新checkpoint／独立overlay封存待执行，不提前发布严重风险结论。

- b40完整安全报告已冻结：`summaries/F1-b40-matched-three-seed-screening-overview-v1.md` SHA `0b1ad70343efc4e738a95914c52f8960532731e3f4150ca96ae51a809a6c455a`，complete receipt SHA `4bb32f08d0e5166ad2dd285536e339794a822c53048cf5d9d0cc054a6a0a543f`。144/144语义与自然度均已知，剧集自然度每seed均−0.1111；电影移除Suzume后代表语义Δ仅+0.0167。原6个trial成本一次计价，探索均值C0 631.605秒／b40 586.122秒，约少7.20%，非正式配对。位置诊断SHA `33917580e0917273ac8bb7d2b2be1b25905ead74b920c53ae365654fcb2cb8ce`，仅描述，不归因为纯位置效应。严重错误根尚未reconcile，不以风险层均分替代。

- v6 supplement目录窄修复已通过root复核：controller SHA `544315ab0a0d84ed9f03e36b93a4b6956bbba8de2a5c7a2879680e0a0ca292b7`、readiness v2 SHA `0b6fb0c7bcf6fbe326c07a53b5e0cd6c59fade36c6b2c97389807a94b41072ea`。root重跑19项通过10.569秒，四pins相符，接受收据SHA `630c81904c0586a2677cc6b494d45c8a3d04a8e3c10d52de64d741b020dcada0`。支持原登记profile与supplement15/v2checker闭集，不含新b40／b60；实际intake仍须逐trial外部admission和独立launch，无自动派发。
- b40三个seed仍有正向且不确定信号，因此除完整96扩展外，root决定补b60 screen-a三seed（原4096／ctx1不变）。它用于检查原预算下的大批次区域；b80/3072为不同预算条件，不能替代该问题。新source-only卡／队列待核验，严格实际token容量失败保留，不自动缩预算。

- 风险新controller SHA `7c4d2110e22312f2b7f128ba533961bc0ac42132c5e3f01054c390197ca646ec`的freeze-only路径通过28项owner检查（含11项封存），独立11项通过22.991秒，review SHA `f9bd38845ade2978570a8559b34c21fb805c44286fc1cfc531a373de64c0fdb4`。root已授权核实所属PID与所有native drained后停止旧87414纯CPU后处理、保存外部completion／checkpoint；实际新封存须精确登记后执行，0新调用，未来b3 dispatch尚未获此审查授权。当前b20主评价59120保持运行。

- b40三seed安全主汇总SHA `3f89cbdd51aceef5a95bf806b62a8cbd0de4d29ae31477eb222639d6d7e61744`已开放：144/144已知；代表剧集Δ+0.3704，95%区间[−0.0741,+0.8519]，电影+0.1292、[−0.0833,+0.4667]。剧集自然度−0.1111；电影+0.0250。两类均未达到确认条件，风险仍未决。root基于完整三seed安全结果决定新增b40完整96扩展，另立新卡／bundle，不修改原9卡或已冻结36队列；这是适应性筛选，不是独立确认。
- 原定一致性A／B合成probe各恰一次，schema提交均兼容，但两者本地`evidence_or_coverage_mismatch`、0接受／2unknown；不追加重试或放宽证据。独立诊断具体原因后才考虑新版本验证。b20 full96 seed08主评价已启动session59120，使用原批准controller9c／launchdf8，与上述辅助probe失败无混淆。
- 新v6评价扩展首版离线通过，但root复查发现supplement实际生成目录为`runs/v5/screen-supplement-v1/`，旧派生仍用语义lane `screen-a`，会拒绝合法真实队列；窄修复与真实元数据路径测试进行中，首版238cb不获实际派发授权。原9c及当前b20不变。

- b40三seed评价完成，外部safe release SHA `2fcd5c600efcd01cc7a0e7962bdf0918074d1cd89c7e29e5060ca9a8059165bf`、handoff SHA `b2861696468d4ddd978702ca93e4a28a4dd95d3ab65eedd495c7ef0ade3c2eb1`。318次有效调用全首试，statistics按预定调用记录fb2eb汇总；严重风险尚未reconcile。custodian于池drained后启动原定两个合成一致性probe session12674，再执行已授权b20完整96评价。

- b3完整96 seed09机械重放通过：`summaries/native-admission-v1/F1-b3-full96-seed20261009-v5-native-replay.json` SHA `88dbc154586c13edf5e2767be401a45cdf3c5373f143a3c6bc40d4cfe7917b64`；envelope SHA `401758520834e8268f3c6526bf5799492edf48d79f45206a1d9cdf59a0c34fe0`。1441批全首试EOS／未截断、34SRT完整，完整流程871.320秒；第三seed仍在生成，尚无完整三seed质量或正式速度证据。

- 一致性custody最终SHA `270596ca396f62620d3af2df6a6bccba033b0fdfe1cb9d376043d8e4baf4756e`、readiness v4 SHA `06592cba2c920837c163ea374f10c1981cc1d2b212130aefac732485d413c22c`：62项相关离线检查通过，独立6项真实卡片形状／执行漂移定向复审通过45.682秒，四个pins未变。原runner b6a保持冻结；custodian获准原定两个合成A／B兼容probe（各最多一次），实际调用待共享池空闲。共享just已加入custody与runner测试，README准确区分实现、合成验证和未执行的实际评价。

- 其余36项生成队列已冻结但未启动：`cards/execution-queues/v5-remaining-source-families-v1.json` SHA `d7fb34df31f6a8610364af477b5726a77aff9e57c24aa5d477d23ede8ec7ea6a`。全部来自原登记卡、输出均尚不存在；顺序F5、token400／600、b1、b10完整96、common b3／5／20、自然对白、F6术语、F7场景卡、F8普遍审校，每组三seed。须等当前18队列终态、GPU释放后核验再启动，首非零停；不授权提前释放F8留出或质量评价，不作正式计时。

- b3完整96首seed机械证明已完成：native replay SHA `cc205c1159881c081d82c6b21c9cc69b5f0c8f8d239954ebbdec363d38747e5d`，envelope SHA `80c049be11f5b4d959218ef8a7d0d801e06e432365eaab69db3d855fdf3ca220`。34场景／4297cue／1441批均首试EOS、未截断，完整流程867.178秒；待三seed后root统一外部登记，不当质量证据。
- F5 actual-main设计SHA `02386e684ffe590b4b46add5a547229f11ea5d09f7e52ac399f1a567d897d566`及F8根假设复核设计v2 SHA `500987a1cc6fea599e4ccc1ba3e50e74992f85c77026c0905be2964431d86320`已审查并授权独立新文件实现与合成检查。F5须先认证全部734批，不能由选中84批反推全流程；F8固定fresh证据＋隐藏首轮判断的假设复核，无分类裁决，开发90／留出54隔离。v1误写global guard根路径已保留并由v2更正为`evaluation-only/`，实际调用仍待实现复查与custodian调度。
- b20风险原生全部drained，旧session87414仍在CPU重复历史核验，registry目录尚未建立；未宣称封签或风险结论。正在实现独立phase controller，拟在有界离线检查及复审通过后，以不可变checkpoint接续纯封存，不追加意见或重试，不覆盖旧记录。

- b20完整96三seed全部机械证明已独立外部登记：`cards/F1-b20-full96-native-admission-registration-v1.json` SHA `c5a893e74ca1f721775f2cf3481ae8c063fd2809dd9ba21644b1bda704d1c174`。root逐项复核全部retained／transport／snapshot清单；10envelope SHA `7c56b61ee542cf283e5fc04926ec627b58fa6f53034f5d584b7a7ed67b890846`、10实际重放SHA `3b0aac5bc34634ddcfb2bd90cab60ca66b7f4d24c9ab08ea25529fc4830b03b4`。三seed完整墙钟685.607／702.621／678.009秒；均231批首试，语义评价未开始。
- 风险phase-auth v2 SHA `85d3ca368e87a5f6061d204078cf612414cdc1b2f04662bc15139e1508877954`修复既有裁决资格与成功attempt历史两项问题；42项owner测试通过，独立12项针对性复审通过。新phase controller已获有限离线实现授权，保持原native guard、独立输出目录、原attempt上限和最终全量复核；尚无新b3实际调用，不中断旧b20。
- v5controller启动及两类resume窄修复的独立复审通过，但发现真实admission采用prepared inputs路径、synthetic夹具误设为native lane路径的兼容缺口，修正中；F6/F7一致性入口另需覆盖真实v5描述字段。此时相关新入口仍未派发，不能把离线通过倒写为实际接入成功。

- F5源frame已在任何新生成前实际冻结：`cards/F5-unit-source-frame-screen-a-v5-v1/registration.json` SHA `4f54ffbe147d13ed070ea12671b165f684af23ce06341b11113757720e03d61a`；外部root登记SHA `bc4c1961c4a25ecf81072d3e9f778bf1d884654e59ad7a24e5dc1c9986ce4038`并重新验证通过。29场景／48窗对应84个完整源batch×3seed=252固定slot，不按后续单元数量、映射成功或评分重选。registrar/custody模块SHA `66c9c6415ab8e28122823011225427c60f4e72bba45d1f99c6c1dce4e748d8c6`保持不变；45项相关离线检查通过。实际主proof adapter及两阶段fresh调度尚待，不是原生或语义通过。
- 新native admission checker SHA `61caae39d6f8c11584008e9dfa59ecf6b3b57351450ded7dd14fc406aea893fa`通过27项合成检查，并实际完成b20 full96 seed09重放：231批／4297cue／34SRT／96窗完整，原始effective settings全部验证、首cache_n0、49/49；完整trial702.621秒。新报告SHA `a0176ff395fab955c3b10e5cfffafe2c4feb4a43a4ba0c51b45d1647ec9d2054`，09envelope `096ca4c7279c24b67a49f463363c4042f0d8503ad0c520c2e6a2ea0a65550ef8`。08仅新legacy envelope `453041778fc6fa70a65c921a9ae0cc99c6669afe8b880c606488526d250c8c08`连接既有dca35审计，executed_checker=null，不冒称历史存在该checker。实际intake还需root外部登记全部envelope。

- b20风险裁决原生阶段已drained：20接受／1两次耗尽，共22次调用；此前主轮失败仍单独unknown。session87414继续非原生registry／raw封签，未释放具体风险汇总。global6已转入既有批准的b40 seed08全窗口评价，custodian session83606，之后顺序运行09／10；新v5评价与b3优化入口仍待严格核验，不为空等新实现而闲置评价池。

- F8纯trigger特征模块SHA `a2278507a67a61644abc875b96ae43d131f45539257863b2ae20af662e193a6d`已完成；root重复17项合成检查通过，模块／测试前后哈希不变，收据`summaries/F8-trigger-feature-offline-readiness-v1.json` SHA `b53a315f35cfd78cb8cf3646896728b4d030bdad9216d564009d71850a13d22a`。三个规则合同SHA `d31b731f35f2a339f535e7fa05cabbf037302232c077d5a1dbf2382a3ecc6148`；初译缺失保留unknown，触发不当质量标签。尚未认证实际特征、选择单一规则或集成runtime；README和just入口同步。

- F8内部来源组已在生成前冻结：`cards/F8-trigger-source-group-split-registration-v1.json` SHA `f09d498c709d61e1cc7a4b85bc80390bf2dcdee26bea340d224e284d2a1a55fc`，proposal SHA `784c2d1cd906dbb45719634e767b983cf826ad4b7520c3dfdbdcf028fd203fc5`。root复算固定哈希／舍入与完整scope；开发19组30窗（代表23／风险7），锁箱10组18窗（代表13／风险5），三seed同组，全部3606cue保留。无跨侧源范围／同episode重叠；部分作品留出风险层为零，不作逐作品风险层验证声明，不按结果补平衡。只释放开发语义结果，留出及可用相减推回留出结果的总汇总保持封存，固定一个trigger后才一次开放；与最终confirmation48严格区分。

- 共同源文诊断helper SHA `3dfbd872a7bbbddd4bfb17846e0ca5e43cceee4a6b226193fafc90608cb753d1`、readiness SHA `200de054d1ac7ef197c5f17d1c81a897d379659b433364b50e68525818a88b6e`：21项合成检查通过，五份相关代码测试前后哈希不变。root前瞻登记`cards/common-source-diagnostic-prospective-registration-v1.json` SHA `75678129c28b58a3fa4347e2b86c4f3b0b0c557e5eb74befd0586b1bf63ffdb1`绑定九张common卡、原匹配C0与五个直接配对；50000次bootstrap及family9仅沿用探索显示，不宣称覆盖新增五项或自适应搜索。实际十二个评价根release及全29原生可见源proof另需外部固定，尚未实际分析。README及just测试入口已加入，未改变原主comparator。

- F8选择性触发器研究设计SHA `84558aed181d0d5fc13c64f6faa9d2217dffb6ce374c4bf1fb77bde327837485`已审查。普遍审校仍需完整三seed及独立纠错／误改／漏改根证据；拟在F8生成和质量暴露前按完整来源组固定开发与内部锁箱留出。只允许推理时局部源文／初译特征，三个事前布尔门，不把审校后标签泄漏给trigger；先锁一个规则再开放留出。实际split尚待，custodian已要求未来留出及可反推标签的F8总汇总暂不释放。内部留出不是最终独立确认；shadow不能证明跳过调用后的实际质量或速度。

- b20 full96 seed08独立终态机械审计SHA `dca35ce3fcd3d63cffc0ce0a0d0d40b08a5a541463987772fde2b679eb7d736d`：34场景／4297cue／231批全部首试交付，EOS未截断，96窗480计分ID完整；原生token／prompt／request／raw、saved21与逐cue SRT身份复核相符。完整trial685.607秒，仅探索耗时，语义评价尚待。
- 下一待启动串行队列`cards/execution-queues/v5-next-b3-context-protocol-v1.json` SHA `e36d08f8cd92f82c5efa1ce3138eb970752acbf6bf8f71a4a59a2ae5bb485c62`复用18张已冻结卡：b3 full96优先，其后ctx0／ctx3、joint-json、ordered非JSON、b80/output3072各三seed。必须等当前b20三seed队列终态再启动；首个非零停止，不覆盖旧输出，不作为正式计时。

- 五组补充screen-a卡已另立root gate SHA `5526a6ff634b9ef53803efbdaf347c709554a7929448f25b0b788c081ad026db`；`cards/v5-screen-supplement-v1/` freeze SHA `9e6cde1a68715024da2f6fdbc0a0a91c2b11d1e57b79e344441f3f6df134fc4f`、index SHA `718a67f9fc3556f8dcedec068bf09f9fb6c056cc91a23b231f5e2a2c29252729`。F4 ordered、F9 b80/output3072、common b3／5／20各三seed，共15卡；29场景离线prepare及共同源文几何通过，尚未实跑全部场景。common-b5仅为诊断控制，不是政策C0；两场景资格不推断全29容量。
- F5原生单元诊断custody设计SHA `933227fefa848832e1891678d47aa217daec531300548942456b0f07db70b88a`经审查，授权独立薄adapter及合成测试；复用主intake身份并补原planner／native／mapper阶段证明，不另建调度器。固定源batch frame须在F5新生成前登记；实际辅助语义评价尚未开始。

- v5源文root gate SHA `aeb8608b3790c808b2818ccb3e7c3075b366e6ef47de047277cef95ccea5d20b`已核对并批准：screen-a33卡freeze SHA `434c8c9f0ed7e2b52345ab657c2243ddae8156ccf4556fc2762fc8814e100686`、index `44621d74b61d85f4d4626f3fc0be7c95d21c9c6a43da57e44fdb3242c31d6e1d`；full96九卡freeze `65eb11013fc52d03a036ace1d7a1cdbbe171f27c592e5d3135b9e2930e7ce001`、index `b4f141a975d500c6cc070f509d2cce107a83665e8b4e4787253d81ec5c76f783`。42次源prepare通过，其中6张动态辅助卡仅证明基础源几何，实际辅助选项／扩展及容量须fresh trial。两个scope分别连接实际matched29与original full34控制，不能互换。
- F4新ordered资格完整97.708741秒，54次真实grammar与原始请求／响应核验；F9 b80/output3072完整93.904313秒、四批80／55／80／55，最大input4211、output1527，4211＋3072＋64=7347≤8192。common b3／b5／b20完整流程103.699238／99.597319／95.740452秒；全部本地native／code／cache0／49层offload／SRT和成本核验。三组实际有序可见源逐270cue相同，源范围收据SHA `a305b1089394499f80e080184ceb57be0b8f6c91f2c87ed277824950da9bb622`。仅限定两场景工程资格，root已授权另立F4／F9三seed筛选及common三组诊断卡，尚未冻结补充卡。
- 辅助比较器修订最终稳定：`v2_compare.py` SHA `13e238db651a283d9b1c5e769dc43f9906bb1c94a437ba50fdddbeb75a0b23e5`；59项相关测试通过143.594秒，12文件事前／事后SHA一致，收据SHA `265dcde955866b0b501f757cdaa710274a55cdad6f2853fbb9acd933130b3a9b`，readiness SHA `1b99461d956f5786732776bc8405671e5cb14b880663096b6d2646bad8d6306b`。完整规范化辅助计划参与身份，逐seed产物／原command与ledger成本分别绑定；筛选入口需hash-bound original_trial_attempt_identity或trial-completion产物指针。无辅助身份计算不变，原报告不改。此前一次合成三seed出现两种代码身份与并行r3提升时间相符，但临时快照已清理，未伪称已精确证明原因。
- 新一致性custody／runner已有离线实现，独立审查复现了合法neutral默认被拒及三seed不同main packing可误入同组两项缺口；已授权仅custody／test修复。两个原生合成A／B schema探针仍未调用，需修复复验后同global6池各恰好一次；不会把通过schema探针当真实术语／背景质量证据。

- r3提升完成，收据`summaries/runtime-promotion-r3.json` SHA `db99b566f0e3648e94e13450332dbfd9b22bd8167114d416fcdb1572bffc92fa`，root核对全部8文件后复制，原21模块备份于`implementation-staging/pre-promotion-r3-backup/`。提升后150项相关测试通过6.887秒，收据SHA `b3825fb2aedff88a246174b34b142a7d4c7b1b8406ff541c8ac5c45af3a7fec2`。没有修改delivery／评价核心／风险模块／source projection，也未替换基线。
- 合并stage冻结manifest SHA `297504e0fa5da2dcee27613c6946420d2f187411d54ad4c3d33cfbca636539bc`，132项离线通过；完整34场景C0行为gate SHA `ba9bdd91aece732fde811961362e8f412e4bf25bbb597518f7b5af3546f53eaa`、匹配29场景gate SHA `b6f4dad3ae8f14056408efad1dee43184acc66a73371549e031c0130dbc39cd0`分别核验各自历史源码、token、请求和顺序。stage到live只按提升收据的相对路径／精确SHA连接，不改原gate路径；不声明34→29缓存轨迹或计时等价。
- F4三seed完整终态机械收据SHA `e5727eb285a29c38b26c77ade1f4ab399ed60de7111655562038a34f8adf095f`：各734批，交付724／724／728，失败10／10／6；全部52失败attempt用旧parser重放复现，均EOS且未截断。第三seed完整trial为621.579542秒，先前598.563189秒只是内层命令，已更正口径。正文内部空行作为补充第六类结构失败单列，旧08诊断不改。

- 独立确认collector的显式输出预算／共同源文兼容缺口已完成离线修订：模块SHA `78e8118239fdf56e056bb3af7a451f80c3ae914f7d7228094482a59db47a718f`，收据`summaries/confirmation-collector-output-budget-common-source-compatibility-v1.json` SHA `1414a93539fcb8f4d801b4f9dedeb12806025e0360417887a326917a657c742b`。51项相关回归通过，最终参数／字段矩阵3项通过；锁定候选预算绑定每次真实请求，C0基线仍4096与原packing，使用c0 recipe的候选允许显式不同batch／宏块。宏块实际源ID／次序／正文、只读范围与policy精确核验。保持F7辅助身份和原seal接口；新prepare尚未提升，没有真实confirmation或正式证据。

- F6max32完整机械收据`summaries/F6-terms-proposals-max32-qualification-v1-mechanical.json` SHA `25f2ede8fc68e37a5eda467e0b4b5d9b15e2585f5d72f4ae3d31150f61d26fbb`与曝光补充SHA `5535abf7a03e6c055503f57e0c4f3c9a7bfb984263257790c6ae9ba4fb22156a`通过：完整流程162.399553秒，2辅助＋54主均首试；4条实际建议中2接纳、2因单cue拒绝。6/54批注入均有目标位置逐字出现，0仅只读注入，48零注入；不把max32上限、机械接纳或注入本身当作质量改善。
- F8真实机械收据`summaries/F8-qualification-diagnostic-v1/receipt.json` SHA `7a54d610907b5afb506d10b8d27f8be71ac332d7b1993f1f0884c9295c4add54`通过：54初译＋54源文审校，全部首试EOS且未截断；54第二prompt与实际draft、相同源ID／context精确绑定，108原生tokenize／completion与grammar核验，648 transport文件绑定。两视图各270cue时间／ID一致，2完整SRT；完整流程147.762770秒，命令144.278979秒。无实际语义评价、纠错／误改判断或独立样本增加。
- 新增F5纯单元诊断helper SHA `7142126ef94575550ba1d835690e3e085bd758db532cd3e5b96372b10a4f42bf`，16新增合成＋相关回归共54项通过；root另核16项通过0.463秒。源batch分母与三seed slots冻结，完整单元忠实度和cue归属分开，实际native认证仍由custody补齐。测试已加入共享just入口，未执行实际F5辅助语义评价。

- F4原三seed严格partial intake全部通过，安全收据`evaluation-only/aggregate-reports/F4-original-three-seed-terminal-partial-intake-v1.json` SHA `a7cc973ae72b5922f07c9a263495660e6ab70b2364ad1e3cf2ab606e55f45425`。每seed48完整分母，机械交付零分分别1／2／1，mapping null均0；完整SRT分别19／21／25场景。原始源、保存的pack／render源码、tokenize与原生请求严格重放通过；每次后续阶段和恢复也使用保存源码，`generation_replay_uses_current_code=false`。未调用实际F4裁判，未将失败状态改为成功。
- b10完整96三卡已冻结：`cards/F1-b10-full96-v1/freeze-manifest.json` SHA `5b4b4c9b774304454e27a47ed35c3727fbc9f577ca69dd6e43999eb906d92166`，queue SHA `9cfdf35631c0ef7b34da023fc3c29a43269f8e379d2554e6795a8866371756cb`。每seed34场景／4297cue／444批，三个离线prepare通过。仍未执行；若提升运行模块，须另立新卡并补准确行为连接，不改本冻结版本。
- F6max32真实资格完整退出0，源准备命令61.755秒、主命令97.460秒；完整外层成本及实际术语注入仍由机械审计确认，不能仅相加上述命令冒充完整成本。F8两场景普遍审校资格已启动96913，主语义分母0。
- F6／F7比较器前瞻诊断收据SHA `8d791f8832fa46bc70d80797924efa3f2bb608f24927ee2555273f03141b92ed`复现两个问题：每seed辅助产物指针导致相同配方被识别为不同配方；card配置身份又漏掉顶层辅助准备计划。已授权只修改比较器与其测试，完整规范化计划必须包含mode／预算／来源／顺序／投影／代码等，不通过删除辅助身份绕过。真实辅助产物和成本仍逐seed验证；旧b10汇总已冻结，正式确认仍封存。

- b10三seed配对汇总已完成，overview SHA `d31e0c7b18012119a7066cdc12195fc0d5ce7645d9385270237e37dc333f327a`，主summary SHA `511e894dda720f95d5247bc716f9040bfc7679819055dc430c2732d2cffe03c6`。剧集代表窗Δ+0.3519、区间[+0.0185,+0.7037]；电影−0.0292、区间[−0.1667,+0.2000]，均未达到完整判定门槛；剧集自然度−0.1111。root选择b10作为次级完整96窗扩展，优先b3／b20；这是一项已看screen-a安全汇总后的适应性选择，不是独立确认，也没有搜索全局置信声明。
- F4-flex seed09／10完整失败流程分别608.159／621.580秒（第三seed初记598.563为内层命令，已据外层trial更正），原卡分别在89503／52793终止，未改写或重试旧输出。新的非JSON ordered-text隔离manifest SHA `1408306a1b44716b01fa816d1d0de7b235701c2ab4187b7663d0eae0337e9ba7`，58项离线检查通过；其单行正文及保留双方括号是新协议边界，不追认旧协议失败。当时正在与共同源文／显式输出预算改动合并隔离验证，尚未提升。
- 新风险transport与F8评价桥接的20项针对性测试通过43.222秒、退出0，日志`summaries/offline-new-risk-transport-f8-bridge-v1.log`；此前530项联合测试不包含这两组新入口，不能将其覆盖范围倒写扩大。F8实际before／after视图和新语义诊断尚未执行。

- root前瞻检查发现F9／共同源文若进入独立确认，还需更新collector的显式参数绑定：当前`v2_confirmation_evaluation`将候选`n_predict`固定4096，并只接受旧六字段packing；新候选必须改为绑定锁定卡的明确输出预算／宏块字段，C0仍严格4096与原packing。此为尚未启用参数的已知兼容缺口，不影响现有21运行或已生成结果；未提前放宽原collector。未来提升新prepare前必须同步处理并验证，不能把“能生成”当“确认入口已支持”。
- b20风险transport-v2第一轮22场景中21有效、1在两次有界尝试后因精确引文校验失败，未加重试，失败场景保留unknown。独立复核原协议要求全部22场景，原driver的“主轮全成功”限制只是实现缺口；root已明确补充入口必须执行全部22独立复核，不能因该场景主轮失败而删其复核slot。单个复核意见不能冒充双意见或消除未决。原生任务清理后已先释放b10 seed10评价，session73370，同一global6池。

- F4首seed投影ledger的48评分窗为47 delivered＋1 translation_failed（`F2-W09_E022-S00001-Q054`），schedule为空。该窗按冻结政策记机械0；其余47窗可照常fresh评价。完整流程的10批／10场景失败仍单列，不能因为多数失败位于未计分cue而宣称完整交付。
- F5原生单元／映射诊断设计`summaries/F5-native-unit-span-diagnostic-design-v1.json` SHA `8e95a4877472c9b5444d89119d8a80a1e643abab933aace60631822c255addf1`已审查：在看输出／规划单元／评分前选定与48／96评分ID相交的源batch并去重，保留三seed所有batch slot；原生完整单元忠实度与同一单元的cue／时间归属分别诊断。跨评分窗只在完整源batch的辅助范围判断，不截拼参考或回填主分。纯frame／packet／validator正在新文件实现，尚无实际语义判断。

- F4-flex seed08终态：734批全部尝试，724交付／10失败／50失败target cue，19/29场景完整SRT，runtime退出1，完整流程613.820秒。终态机械诊断SHA `43b9219007119a69d795295ca881fcadccd27d4065bc9b62e18b66dcb90d400b`：20失败响应逐项重放均拒绝、均EOS且未截断；10次多输出下一条只读ID、2次重复末目标、4次空正文、2次行内ID、2次漏ID。未发现当前parser误拒；旧协议不作静默恢复。其余两seed用于验证失败频率及语义潜力，不将当前不完整配方晋级。
- 原15任务队列78538在index6停止。仅包含原卡未尝试任务的`cards/execution-queues/screening-independent-next-v4-unattempted-tail1.json` SHA `282451bdb63c20b983ef8e9a4fa4caa4e0e2868cd0b678a12e2cd3a6fe67246a`已启动89503；没有覆盖失败输出或重跑seed08，任何非零仍停止新尾队列。
- root复核冻结政策SHA409553确认`missing_scores.delivery_failure_semantic=0`。因此F4真实交付失败窗口沿用机械0，不因新失败改成null；只有not_run／评审失败／未决／不可评等真正缺分给0/4上下界。独立partial intake在原始status与完整分母基础上设计，不放宽原始身份或改政策。未落在计分cue的失败仍计入整个流程交付失败，即使48评分窗全部可评。

- F4-flex首seed实际长流程出现资格54批未覆盖的协议失败。已完成545批时有7个失败窗口／14次失败尝试；初步机械重放发现多数为5目标之外又输出第6个只读邻文ID，少量重复最后目标，另有正文约束失败待分类。没有输入／输出触顶证据。保留原始拒绝，不丢弃邻文输出或猜选重复译文来伪装旧协议通过；等待终态后仍完成三seed与完整评分分母，队列停止时仅重排未尝试任务。
- F9最小修订已在`implementation-staging/common-source-output-budget-v1/`完成，待审manifest SHA `31046967bc4cdbda0022546347b5bcca74d984b2115f09dcada4bac313970575`，115项离线检查通过。新staged prepare SHA `80c4d808d498583b932ed80f48a86f5ebe7617d6aec444423fff25ac017ea633`，继承共同源文参数并新增显式输出预留，C0严格4096。原42文件与parent43文件未变、默认全部34场景请求构造仍一致；尚未提升、登记实际卡片或GPU执行。

- 联合`just translation-flow-v2-test`会话55843退出0，530项通过421.517秒，收据`summaries/offline-integration-530-confirmation-risk-v1.json` SHA `b5e0d6b1112d0351ab8a14857b3567ccd5a5897c27d8a36becb4e289d8036579`。覆盖最终confirmation bridge／计时／既有风险模块及原筛选比较；新增risk transport专属测试未在该次just配方中，另有先前独立测试记录，91个早期运行时观测文件到结束无变化；观测不是命令启动前，收据明确此限制。尚未实现的F8新bridge不计入本次覆盖。
- b40三个seed生成全部完成，各106/106批首试、29场景完整交付；安全收据`summaries/F1-b40-three-seed-generation-v4.json` SHA `efb4182c70067cb24c6ad85e59698bbcd671aedb5821ed333b8b18689d8dfed8`。完整流程585.341／583.040／589.986秒，只作探索耗时，不作正式配对。队列已于22:05:30 UTC进入F4-flex首seed，b40待统一三seed评价。
- F9边界调查支持另立b80＋输出3072的容量资格：已知被拒prompt4211＋3072＋64=7347，低于8192；旧4096预留总8371仍保持失败。b40／b60／token600资格最大实测输出826／1162／1241且均EOS，但不能保证b80不触顶。root授权全新隔离staging中的最小显式`n_predict`参数，C0保持4096，现有卡／21代码／GPU队列不变；未来真实资格仍须完整prompt与EOS、全部失败成本检查，不以推算替代通过。

- 后续8方向工程启动审查`summaries/pending-mandatory-directions-engineering-review-v2.json` SHA `2d920c73c0fa46c0d443bf5ba5f1c73a50a90a0b9c95e3b60b4975302fedba21`通过24张卡／队列及完整29场景构造核验。11项相关旧测试＋7项审校失败／预算探针通过；b1／joint-json／natural-dialogue可进入有界筛选，不声称专属native资格或质量通过。F8需真实两场景资格，`cards/F8-universal-review-qualification-v1/execution-queue.json` SHA `127724d66b0c88d484f640ae02a6fa289d96bbd100aaf4557cd1452e0827af2f`已准备，54批／108名义调用／语义分母0，未执行。
- F8同次运行前后评价路由设计`evaluation-only/aggregate-reports/F8-pre-post-evaluation-routing-design-v1.json` SHA `fdcf1cc67989b0fda8475a5ed293d1d5ebf8c05862ea957689cdc9f5b6feffd2`已审查。root授权独立诊断bridge的有限实现及离线测试；默认两视图fresh意见，不开发post意见导入，不改运行中的核心评价代码。前稿不是独立C0、两视图不增加生成样本，成本只计一次；实际诊断调用尚未开始。
- F7辅助字段兼容修订完成：计时模块SHA `f2bf5c471d94e514f3f61abb26303361cf0ba97017f571867c1bc56e912d7f62`，34项计时／统计检查通过；confirmation bridge SHA `b4c2fb89f23c7588d8bc11ae1909e42aefd2794fd4550961458b77209f5b8a8a`，66项相关检查通过。实际辅助元数据审计SHA `7d2201296f26e23d474c06cdc2d35d97ddb54dd17ae2c06f2efa4364e97cc080`中15项相符，完整源码覆盖仍不满足正式计时，保留qualification身份。联合`just translation-flow-v2-test`会话55843运行中，尚未宣称整套通过。
- 阶段成本盘点`summaries/native-trial-cost-inventory-observation-v1.json` SHA `5138da23e9305cebf0e5166657ae341efb962291bab98c772e0d4d913fa12118`记录31个已结束trial外壳（22完整／5部分／4失败），已记录完整流程耗时合计10798.031秒，辅助准备不重复加算。该数不含缺trial外壳的历史C0、正在运行任务及外部评价，不是项目总历时、正式速度或账单成本。

- b10 seed09统一评价封签SHA `9c7226602578f9ff05980b23c07f68985043af252b73d93a40ea2e3b03539fa6`，48主＋48复审＋12裁决共108首试接受，零重试。三seed尚未全封存，不发布单seed成绩。新风险transport-v2已启动b20，22场景／170条既有claim出现只是待核验输入；b3新根23场景／171条同理，不是新增错误计数。global6池继续单一控制。
- 共同源文staging完成：`implementation-staging/common-source-v1/promotion-manifest.json` SHA `17f883acf909a0ea4faa220acb4ee291d61f911491ce8d0e36b3ab224977e2d3`。仅新prepare可选参数及测试，104项离线检查通过；实际34场景×b3/b5/b20×3seed默认构造与旧版一致，4297cue宏块60＋外邻1有相同有序源文。root已审diff，暂不提升，避免使当前及待跑21模块卡片失效；真实完整prompt容量尚待GPU资格。共同源文不消除目标／只读角色、输出竞争和缓存历史差异。
- 独立确认比较分支完成49项测试与编译检查，收据`summaries/confirmation-comparator-offline-readiness-v1.json` SHA `c366c21dcbd30ae57755f9a9c90cc45c797ec0a0c4240d4ae528d6a31dfd4fb8`。专用CLI要求外部登记authority SHA；失败／未运行保留全48窗×3seed分母。确认集仍封存，最后F7辅助元数据兼容修订后还需集成核验。

- 风险transport-v2单次原生探针1任务／1首试／1接受通过，28文件封签及native清理核验通过；只删除API不支持的schema `uniqueItems`，运行时重复／引用约束保留。37项离线检查通过。旧风险失败封签SHA `644149af9b5619acd3b4bd7a5e791cf9117c583bf4486e03f923768ad51d3605`仍保留44拒绝／0意见，账单成本未知。新风险评价待新根继续，不把探针当真实风险准确度证明。
- root对实际F7 source-preparation元数据补查发现`preparation-options.source`比`card.source`额外含`freeze_sha256`；正在将计时／confirmation采集器的整dict相等假设改为严格逐字段＋freeze身份核验。此为采集器兼容问题，没有修改成功F7生成或runtime21，没有实际正式计时／确认样本受影响。

- b10 seed08统一评价已封签：`evaluation-only/F1-b10-universal-screen-a-seed20261008-v4/finalization-manifest.json` SHA `86732aa58039f41bcf849aa772b89896af192c9981ceb745272faa5351f956df`，48主＋48复审＋10裁决共106 fresh首试，零重试／意见导入。等待三seed再汇总。风险transport-v2的37项离线测试通过，唯一原生schema兼容探针53113正在运行，未将合成语义结果作为候选质量。

- b10三seed已完整完成，安全生成收据`summaries/F1-b10-three-seed-generation-v4.json` SHA `510132f48559eb85245a76c1939b453af0180df459b322ec3782eed830297a3f`，各29场景，完整流程594.546／633.099／586.806秒；不是正式配对计时。首seed严格intake已通过并开始统一盲评，driver先前发现旧17声明与完整70文件快照不同，现按准确声明子集＋实际保存字节核对，未将非相关全目录数量差异误作代码不一致。
- 待运行的8组各自三seed队列已冻结，索引`cards/execution-queues/pending-mandatory-directions-v4-index.json` SHA `eeb7a143894e0658645d52e56c2ee6b2131869e590cda9da4d4cf0a8f8fea468`。包括b1、token400／600、joint-json、semantic-partition、natural-dialogue、evidence-scene-card、universal-review；只是待选调度，不预设最优。b1保留每seed3606完整批，相关F5／F7与容量资格明确绑定，无专项资格者不伪称通过。
- 术语一致性诊断模块`v2_consistency.py` SHA `91105706247c769d49927cec995c5e729f21b9137f164e304dbbd1b09021a312`已完成21新增／92相关测试。它只实现三seed并集、A／B packet、引文／曝光／分母校验及原输入重建；实际来源鉴权、单次native schema探针及fresh调度尚未集成执行，不是F6/F7质量证据。设计收据SHA `58d713f7337a2b50878bdf610be987821b54698fa2d5d2029fba7ee02b2f6287`。

- 正式计时模块完成原生卡片格式修订，`v2_timing.py` SHA `704770095145d1bf5e70b2b7387aef1dcc932fa758e5ccb481c23d6a523ac442`。33项计时＋统计检查通过132.337秒，最后2项针对性检查重跑通过。历史真实C0元数据审计`summaries/timing-native-metadata-schema-audit-v1.json` SHA `9a9621789611a0721a4ca7b2373433d865e09b8ace26325c4efc1129acca4024`只作字段对照：874批与cache_n0、完整退出相符，但缺完整trial外壳，且旧43源码快照不等于当前21声明，因此不纳入正式计时。未来独立fresh卡须绑定完整实际快照及安静条件。
- 共同源文诊断设计`summaries/F1-common-source-diagnostic-design-v1.json` SHA `6a47d5409de13eee449fc3a2e8a77750a29159f26c233dfd5d1ca52294520438`已冻结：block60＋外邻各1可让b3/b5/b20每cue看相同有序原文，保持目标边界与尾批；8743项离线检查通过。block20仅适用b5/b20，b3有140批跨块，不能静默使用。真实完整prompt token容量仍未知，未来须原生tokenize检查，不截源；尚无诊断生成或质量结果。

- b20风险评价首轮22个场景均被API `invalid_json_schema`拒绝（`source_event_ids.uniqueItems`不支持），各2次共44拒绝请求、0有效判断，native进程均已清理。原根保留、未派发b3；这不是风险意见或语义失败。修订只投影传输schema，本地唯一性校验不变；新增单次兼容探针与全局确定性schema错误快速停止，修订根另立，不覆盖旧失败。
- b3／b20完整96窗六卡已冻结，freeze SHA `5b088629006891b95931acb93d1d31158cefc2ddb21726727bf8eb48917e74ff`，执行队列SHA `e2f4cbe2a5a84039e5260e3af1e18648fce362c1291887efdad9c8603a34500a`，均在`cards/F1-b3-b20-full96-v1/`。root核验全部34有序场景、六卡及21模块后批准未来串行启动，收据`summaries/F1-full96-root-launch-review-v1.json` SHA `71decb42f9f51dfbbb50e79f3f484b694c891da74f65e6c70e595d69103ac37e`。旧C0完整874×3请求构造／顺序复用证明SHA `b94474696636f214c36ae92dce050df10a979579d7969846e6e98ae3e224f9a9`；不赋予旧运行新生成或新计时身份。

- 筛选解释补充`summaries/F1-matched-three-seed-screening-interpretation-addendum-v1.md` SHA `12e917a297a490f273d2be6f8bb3d052d0708dc245cfb08c255568ee4f5239b5`明确family9是最终最多3锁定候选的6语义＋3计时端点约定，不覆盖全部适应性筛选搜索；正向筛选区间不是搜索全局置信保证。b3风险剧集区间[-0.2222,0]包含0，不是严格负效应证明。
- 独立确认元数据模块`v2_confirmation.py`已完成17项新测试／65项相关测试，模块SHA `21e41bd132b444ffdb26afa8bc1f34a1b36bbb16076663f57dd4f26287d0f0de`；完整执行配置跨seed绑定与原生C0默认项已复核。实际dispatch wrapper、fresh48评价／比较集成仍进行中；没有开放或运行真实confirmation。

- 首次安全配对汇总已解封：`summaries/F1-matched-three-seed-screening-overview-v1.md` SHA `dfcaf746ef09c6437ece60db8537e7515f432bcca5aceca02c9fdb7145132a50`。b3／b20与C0均144/144语义分已知；剧集代表窗差+0.3889／+0.4815，按冻结调整水平计算区间[+0.0370,+0.9074]／[+0.0741,+1.0000]，下界未达+0.25。电影差+0.0125／+0.0458，区间[-0.1083,+0.2667]／[-0.0833,+0.2000]，不能确认非劣0。剧集三个seed均正，剔除单作品仍正；电影跨seed和权重敏感，b3场景等权变负。自然度剧集C0 1.9259→b3 1.8889／b20 1.8519，后续需独立缺陷诊断。风险根仍待fresh关联，不能据均分确认优势。
- root据上述筛选信号决定b3、b20扩至完整96窗／34场景／4297cue各3seed，新卡与完整scope代码行为连接由源负责人准备。不会把旧29场景输出冒充完整34场景，也不把筛选区间当适应性全搜索的总体置信保证。48独立确认继续封存。

- 配对质量解封门已落盘：`evaluation-only/matched-paired-quality-inspection-gate-v1.json` SHA `84c7ff4a976c1911404050edba8ab50c2d92ca6bbedf008f6f88eec657ff4f17`，绑定9个封签、315条复用判断及最终归档／比较核验，并授权已冻结的下一15任务全窗口评价；未开放确认集。
- F6max32独立版本已冻结：`cards/F6-terms-proposals-max32-v1/freeze-manifest.json` SHA `c125c9214b595f634f7e00f18ddca8aa28972cde7a2ca31850575aaf67982a0a`，4卡／4源准备计划，仅将源建议条数16→32；其余模型、预算、21代码、投影和源范围不变。qualification队列SHA `a76390acac3bde100bd12ea6dcc3d0442eb9794397c51b7bdc76e026bc233cac`尚待GPU时段，不能把保存响应的反事实解析视为真实通过。

- 最后匹配输入审计`summaries/matched-workload-complete-archive-three-seeds-v1.json` SHA `7b8731f728de93e4abbcfe5658dc42448f2aac17483391a46d0781606cd34cdd`通过：144组primary／review完整输入和27组实际裁决输入逐字相同、零不匹配。三seed比较器元数据收据SHA `33f262e949826e83bb314541e2319c37bca1c8c8377f4dfa92f59dd1ffd9a9e4`通过。root据事前条件授权b3／b20配对质量解封与冻结风险关联，未改阈值；确认集继续封存。

- F7新版真实机械复核通过：`summaries/F7-evidence-scene-card-qualification-v4-mechanical-r3.json` SHA `111128a1cc5dabc454b6b11855384dc4ce64eeb2d0ca597f6726332ed83fb77d`。54/54批、270cue／2场景；辅助共2背景项，其中1不确定，全部54批实际非零注入和支持原文扩展，27批包含uncertain项，合计283个新增只读cue出现。源证据、顺序、目标和实际prompt/tokenize重构通过；54主＋2辅助均首试，完整流程192.125秒。此前审计误读未保存prompt字段的异常属于审计helper，r3改以实际tokenize请求核对并保留历史。
- F6失败重放`summaries/F6-terms-proposals-qualification-v4-failure-replay-v1.json` SHA `3bef5a1c59f6ad2fa1d276cea5ebf00a833cb352ddaf49d42bcf14c2b7c88948`确认max16拒绝17／20建议；只将解析上限改32，两条保存响应各有6项eligible，其余因仅单cue出现排除，没有重复／冲突／字段错误。此反事实不是新的模型成功，不重分类旧失败；显式max32新卡待执行。

- 三seed matched48全部封签；第三seal `3d3ade68f320d934a1e9eefcf54fafa49538d40f0903365cdea8263076ddb396`。累计144主评＋144复审＋27实际裁决均精确复用，新增裁判调用0；三个新的29场景生成身份不与旧34场景合并。待完整144输入证明及最后元数据检查通过后，再解封b3／b20配对质量并按已冻结风险关联协议核验。

- 新独立筛选队列已启动78538：`cards/execution-queues/screening-independent-next-v4.json` SHA `8b0fa06706a9a9cf03424419bcc6813f95cf22e2c0153acc8f67ba7dae583f79`，调度收据SHA `fff8724d828c86adcd2bd55d7dd773822ca076f856847af77537d8ecfd607de3`。5组×3seed共15次完整运行，预计8043批，每次29场景／3606cue；输出带`-v4`，没有覆盖旧结果，失败停止后续调度。
- F5新版机械复核通过：`summaries/F5-semantic-partition-qualification-v4-mechanical-r2.json` SHA `2411053b744fb0107201cccd22b70d8a5965b0eeecde8775983f59317f3daf03`。54/54批、270cue、2场景；32真实多cue批、34单元、40合并边界、74多cue成员。140次调用均首试成功；32个实际GBNF逐字与canonical哈希独立重建一致，精确跨度重解析一致。grammar构建合计0.026秒、最大19913bytes／316states；初版审计将canonical object_hash误当raw字符串SHA的假警报已保留并由r2说明纠正。工程资格不证明语义归属。

- 新F5资格完整流程166.905秒，两个场景完整交付；实际多cue映射与grammar机械审计进行中。F6源准备失败，完整失败流程63.253秒、未进入主翻译；具体原因正在按原始响应重放诊断。F7原卡从未执行，已以独立尾队列继续（SHA `295d258a1e03902248db1ebb3e4143e2aa02c9d659386d254fafac49e13d7ed4`），没有重试或覆盖F6。
- 历史代码依赖解析已通过103项独立离线检查，matched模块SHA `4e99717cb93f7a3df8729c979bac242f7f58fff17f361a4e8f50def43a7b7d8d`。第三匹配评估控制器9389恢复。全三seed归档调用审计`summaries/matched-workload-archive-invocation-three-seeds-v1.json` SHA `3c42c5d8ceb30e2e7b0c5b4c925f2881ecaf01f1fc2ea8dfa36e9e699765bbec`；旧协议／helper未改、没有临时回滚新运行器，输出差异仍1／0／2。

- C0匹配三seed完整生成收据`summaries/C0-matched-three-seed-generation.json` SHA `9cf0760c016dbbe793e505721c5738e07611829a1e60ae4a6e63f1c2e2012624`，保留各trial与delivery身份。比较器08／09元数据核验通过，收据`summaries/matched-comparator-metadata-seeds08-09-v1.json` SHA `ff609ef3616ee21a9adc6c2aa9381cd490e7161e34d4ec5e7521bdb9a883a98e`；未读取分数或参考语义。确认／计时前瞻审计87项合成验证通过但发现7项入口契约缺口，见`summaries/confirmation-timing-readiness-v1.json` SHA `295a7911ca2188c3f3c5bf320c47377ae651e9314e965e3adb5b38bb52d754a1`，正以离线模块补齐，确认源仍封存。

- 提升后联合回归436项通过74.455秒，收据`summaries/offline-integration-436-post-promotion.json` SHA `a2cc3f6ee83126332839860c1467bd29b04b14446175efe06d0637e372ed1772`。v4已冻结51卡、3资格卡、8源准备计划、21运行模块；资格freeze SHA `11f1ad237fdb1de3efd21c5f097424427ec6bb43bba13ac3f83039875b8d9c5d`。串行资格队列SHA `62938fdfb4699791ccc4f3dce8dbc62d3faf8edf5d1f302e8121e9960da7489d`，会话40575，评分分母0。
- 第三matched评估尚未开始导入：旧冻结验证协议指向的两个live代码文件在提升后哈希变化。保留协议原字节，正在增加严格的历史依赖解析：只接受已绑定备份中相同原哈希，审计同时记录旧指针和实际归档指针，不将新代码冒充旧执行、不重写旧封签。此前436测试不包含此后兼容修订，需另验。

- 匹配C0全部完成：实际全三seed请求审计`summaries/matched-workload-fresh-three-seeds-v1.json` SHA256 `bdf7b0bc567c55f2949bca257d7eacf36891b68e0704b0f34eb7c090cb843c72`。各734批局部prompt／token／请求完全相同，原生及解析输出差异分别1／0／2批，继续明确matched48分支；差异不解释为质量胜负。08／09各48主评和48复审输入逐项相同，实际裁决8／10也已核验复用，共210旧判断、零新调用，新的29场景生成身份单独保留。
- 新协议已提升，收据`summaries/runtime-promotion-r2.json` SHA256 `bd592f8dd67e6342749f7b0db2f493453a576276bfe8b81945bb90c5d1345a00`。所有17路径先验证原始和staged哈希，15旧文件备份在`implementation-staging/pre-promotion-r2-backup/`，未修改评估或比较器模块。联合回归尚待结果，真实新协议资格尚未开始。

- 新自然度敏感性校准已封签：`evaluation-only/aggregate-reports/fluency-sensitivity-v2.json` SHA256 `548fa7b12de0a04a13b9119e2f7fe3d392a0a930ab4701b8290990af04de315d`；完整性审计SHA256 `d553bc819c43132058f2ab7a378df5dfad7f05f1b5d00785ca46bbafd0e35388`。60/60首试、零unknown；42正常对照无缺陷误报／偏好，18阳性均满足预登记机制、精确引文与依据要求（主类别精确一致15/18，另3次属于事前允许交叉类别）。六阳性对均满足阳性3/3检出＋正常arm3/3无缺陷。只证明这些手写合成构造上的可重复区分，不证明真实F7敏感性；主政策不变，served model／effort与账单成本仍未知。

- F1位置诊断设计`summaries/F1-position-diagnostic-design-v1.json` SHA256 `f193109a5fc325dd79210718ebc81a442cdf9e7ea02896c1bd97cf328a1aa984`已在质量解封前固定。48窗×8种几何共384窗口特征，1920个cue位置元数据不增加评分观测数。C0 10窗同批／38跨2批；b3 32跨2批／16跨3批；b20 40同批／8跨2批。C0／b3窗口平均位置均落中段是几何平均现象，不事后改分层制造差异；保留cue位置向量、跨批与整场景位置，后续仍按窗口、作品及配对seed汇总。
- 匹配C0 seed20261009的734/734 prompt／token／请求／原生输出／解析译文均与旧局部记录相同；累计08–09实际审计`summaries/matched-workload-fresh-seeds20261008-09-v1.json` SHA256 `733c48b45e0f7de77f05ba2ff2cd9d714e8217320cf2714e1e1e9692dc4e9a37`。seed08存在1批差异，matched48分支保持；第三seed仍在运行。比较器原生schema联审发现proof字段与恢复后裁决状态的兼容问题，正在补用实际helper生成的合成fixture验证，尚未用于实际质量比较。

- 匹配C0首seed已完成734/734批首次交付、29完整场景，完整流程633.837秒，安全收据`summaries/C0-matched-seed20261008-generation.json` SHA256 `d8ed1ae253a9f371c05a661a0e10fd7d60f6794440d23eadcefd7d27bbc63789`。实际核对734/734批prompt／token／完整请求相同，但原生响应及解析译文有1批不同，收据`summaries/matched-workload-fresh-seed20261008-v1.json` SHA256 `f2e13eea5c5b2a03fe3c915973d1c5dd699b0007337eef10bdbf4b4011aedb98`。因此启用预冻结matched48分支，不再声称旧34场景生成与新29场景完全等价；差异原因及好坏未推断。逐项完整judge输入一致仍可复用对应判断，是否涉及评分由custody核对。第二、第三seed仍待完成。
- F1-b3三seed盲评也已全部完成：各48主评＋48复审，裁决10／8／8，总314任务／314首试／零重试；质量仍封存。新自然度合成敏感性探针20 arms×3已执行60次接受判断、零传输失败，机制检出／误报结果尚待独立汇总，不能把调用成功当作敏感性通过。
- 资源审计已保存`summaries/windows-gpu-telemetry-qualification-v1.json` SHA256 `07835281de2ee1e7f0b229bbafed826f8a7f9691842dc186fd4e0eebf3d68e28`。b3首seed工作阶段2427/2427采样有Dedicated／Shared读数，Shared为278MiB；现有口径是PID跨adapter合计，不证明物理驻留或paging。一次有界探测确认RTX5080精确LUID及计数器可用，PDH源时间的时基尚未确认（与观测UTC相差8小时），保留原始值。Paging仍unknown，没有启动ETW追踪；不能将shared占用当作paging证明。

- 隔离新版已稳定，尚未提升：`implementation-staging/next-protocols-v1/promotion-manifest-r2.json` SHA256 `2e1b29952c2ee445151b829814ebdb2fd0c94bf98a776b96d8e6dc3de0918108`列17个待合入代码／测试文件；407项离线测试通过41.875秒，收据`offline-integration-407-r2.json` SHA256 `fd9d11deb1ab5bb761b16e45c854ca3c71d984d727afb1158727fb2b675d8049`。原15个既有文件仍与初始副本一致，2个新文件尚不在原工作区。真实GBNF兼容、协议交付和语义质量仍未验证。
- C0新旧代码行为审计通过：`summaries/C0-staged-behavior-reuse-v1.json` SHA256 `a3b44b281250a654a275c9821deafc4931dab245e32fc553c7621d11404c6b91`。两个隔离进程各核对734批×3seed的prompt／历史实际token输入／完整请求／调用顺序及重试、无辅助行为。该证据只支持“相同29场景工作负载下，新增协议没有改变C0构造行为”；不能替代正在进行的旧34场景与新29场景实际输出／完整评估输入验证，不把旧34场景耗时或生成身份改写为新29场景。

- GPU最新状态：F1-b3三seed队列70933已全部成功结束，各1210/1210批首试交付、29完整场景；完整流程700.384／700.602／708.713秒。收据`summaries/F1-b3-three-seed-generation.json` SHA256 `efe9846d77d575c85c9fc925d70a0222daa58060a781f364238d931c4faf8ff0`（耗时精确值以收据为准）。第三seed交付已通知盲评负责人。当前串行匹配C0队列会话64205已启动，journal为`runs/C0-matched-screen-a-three-seeds-v3-queue.jsonl`；开始前复核三卡及17模块实际哈希并确认无遗留llama-server。当前禁止提升隔离源码，待C0三seed完整结束。

- F2源文几何规划已完成：`summaries/F2-source-context-planning-v1.json` SHA256 `45c9b73519af0fca3fc78dd57a631db6124030c9de0917d7a032241654fffe1c`；9种对称／非对称可见范围共6606批范围检查通过，均保留screen-a 29个完整场景／734目标批。邻文8的前后时间延伸中位约27秒，16约56秒。独立cue token加和不能替代完整prompt容量检查。先评价0／1／3，再按趋势选8及必要的8/1、1/8，16作延伸；不提前定最优，不把不同可见总量的差异归因方向本身。

- 当前原工作区联合离线回归383项通过（36.535秒，退出0）；收据`summaries/offline-integration-383.json` SHA256 `ca78b25395d92ae9a2db9eecd0deb7be179830e03922474ac7d8621334d28021`。包含新独立分区grammar／术语建议／场景卡、F8诊断、原生Windows六槽进程保护和风险关联；不包括隔离副本待提升的未来运行器或仍开发的matched评价适配。测试不调用GPU模型、不提供质量证据；单次总数不与历史次数相加。

- 匹配对照验证已预注册：`summaries/matched-workload-validation-v1.json` SHA256 `673dad7728bb99081ddd0e79003519359a883aedaac927e0b0932d5db788a51b`；离线局部身份审计 `summaries/matched-workload-offline-local-identity-v1.json` SHA256 `ccfebe66b2b9661242fb2b66161e4df88299048a0a1d15c36fb8612da56502c1`。三seed各734/734批局部源／上下文／prompt／重建请求一致，完整请求历史不同；实际新token、输出及完整judge packet仍待验证，复用尚未获准。该验证协议不是48窗评估scope，不得改名冒充。
- 待当前b3三seed结束，串行启动`cards/execution-queues/C0-matched-screen-a-three-seeds-v3.json`，SHA256 `f0f130a5366f2f1d3570dc6ce692f4fd24afb241d42fb0cb5566f2b514d2103e`；输出`runs/C0-matched-screen-a-seed20261008`／`09`／`10`，journal为`runs/C0-matched-screen-a-three-seeds-v3-queue.jsonl`。两组完成前原17模块均冻结。差异分支须另立matched48评估scope，严格区分新控制生成与旧donor裁判身份，不把两组C0合成六个seed。
- 差异分支的独立48窗评估scope已在任何质量查看前冻结：`evaluation-only/matched-control-evaluation-scope-v1.json` SHA256 `6b72e98045a99689b58770338fe9639d75877ab270fce97600eb3687e4244ca0`，绑定精确48窗／29场景／3seed、源／参考／政策及队列。原96窗scope不改；只有完整实际输入逐字节相同才复用对应接受判断，裁决输入须等待新争议实际形成后检查，不能预先宣称一致。
- b3首seed已完成1210/1210批首次交付、29/29完整场景，完整流程700.384秒；安全生成收据`summaries/F1-b3-seed20261008-generation.json` SHA256 `e48fbac5d210dd99900870a69c14f51a9fded910ae5d875e783a3996794c4542`。其盲评已开始，第二seed继续生成；不是配对提速或质量结论。
- 自然度侧轨已完成4个合成探针及固定16个C0窗口三次同packet校准，共52任务、52首试、零重试；48校准均无已报缺陷／偏好／未知，出现率无翻转。收据`evaluation-only/aggregate-reports/fluency-C0-calibration-v1.json` SHA256 `9d3154d5327cbe72ac39e1b946dd37151dd5e579a3877430cceaa324ad4ee937`；独立封签审计`fluency-finalization-audit-v1.json` SHA256 `fc8ab524836560eeece7e409f26871dcdc560d9b2c8317562151a511dc78835c`。这只证明这些输入上的重复稳定性；四个明显合成缺陷不能证明细微风格收益的检出力，不能据此关闭F7。52/52原生Windows进程树排空已验证，CLI未返回served model／effort及账单成本，实际服务端身份与费用保持未知，请求配置仍为Sol/high。

- GPU：串行队列 `cards/execution-queues/F1-b20-three-seeds.json` 三项均已成功结束，journal为 `runs/F1-b20-three-seeds-queue.jsonl`。每seed194/194批首试交付、29完整scene／3606cue、48评分窗／240ID；完整流程分别554.579／552.586／556.624秒。范围与原C0计时不同，不能直接算提速。纯生成收据 `summaries/F1-b20-three-seed-generation.json` SHA256 `c5548d08f1fc34fdbdf24689a100079abf809e12393a53b9d8e651b5872e6aef`。GPU当前运行F1-b3三个seed队列（会话70933），journal为 `runs/F1-b3-three-seeds-v3-queue.jsonl`；三seed结束前不修改冻结的17模块；后续启动前再核对真实进程。已完成三seed组的原卡、源码快照和生成不改写。
- C0原选择性复审的三个评估根已封签并保留。候选比较改用事前冻结的全窗口独立复审范围，`evaluation-only/evaluation-scope-universal-v1.json` SHA256 `b747c4d22462d5756e8fff258213a8ba79771fe2f500c56135dc955643d7e209`。C0以有完整来源链的派生根复用原主评及已有复审，仅补缺失复审；不混用新旧复审范围比较。
- C0统一复审三个派生根 `evaluation-only/C0-universal-screening-seed20261008`／`09`／`10` 均已封签，各96/96窗具有接受的独立复审，质量null仍保留。新增115复审＋13有界裁决共128次调用，零重试；原497条接受调用仅导入、原成本不重复计，零新增主评／翻译。三个seal SHA256依次为 `9e17227fe1500d3d4b85e45068352df1a75ddd6d5eff2bfa303cf1ac66b6feea`、`1c6ec567b38f85111bba1e53f98a1d5310bab2402d867c903c71f91432c1cfc4`、`3a93bc5d95dac1fde06c579f076ffbe138ccc9aa5e5435bfa8146d8fc735b646`。安全聚合 `evaluation-only/aggregate-reports/C0-universal-three-seed.json` SHA256 `47ea4883918e6c66bd67dab0ba3a09f4551d015ca11e0cafe4573601d6b28deb`；F1-b20第一seed主评已启动，全局六槽不变。
- 严重错误关联方法已在F1评分前冻结：`evaluation-only/risk-reconciliation-protocol-v1.json` SHA256 `d35571e4d5b4f60ccde72a1abf266b10d7923a2f71949fb0222f6c1221d51a14`。完整三seed配对封签后，统一核对严重错误并集及可关联minor；源文事实、两侧精确译文与已有证据支持的同一根因／新增／恶化／改善／未知分开。基线没有某条裁判记录，不足以证明候选新增；须有实际基线译文支持其不含该错误。一次fresh关联、一次独立复核、争议至多一次裁决，不改原分。方法已获主协调者审查，尚待实现测试及配对输入；调用继续由评估负责人统一六槽安排。
- 计时解释另存 `summaries/timing-interpretation-v1.json`，SHA256 `673560abd02b64ec54dc8236cc595fe82107ff1c9ae3d61e80db7fea44a50de1`。相同冻结工作负载的新会话完整重复可作计时样本，不增加质量seed；暖缓存微基准、复用产物或checkpoint局部恢复不作主计时。真实失败重试全部计费。原政策及60秒／15秒／family9不变。
- F5下一版本 `semantic-structured` 已接入运行器与交付诊断：顺序边界决策由程序推导源单元，模型给出不可改写的原生译文子串分区，再由程序计算跨度。尚未通过真实模型资格，不能将测试通过视为交付成功。新卡另立v3，保留原语义／anchors失败。
- v3运行卡已冻结：`cards/screening-round1-v3/freeze-manifest.json` SHA256 `a3c718e2b27912b12561e1113441ad00f0c648d1c70b8c6cfc0cee2aacb22f59`，48卡；`cards/protocol-qualification-v3/freeze-manifest.json` SHA256 `2d43e7fd6da27fddf99382eb911e2d474fb208ac545a73e3d3c4356168587086`，6资格卡＋2源准备计划。各卡绑定原16模块加structured共17个实际模块。F5 structured两个135cue场景资格已完成但未通过，详情见下方；原4096源术语／背景及b60也已执行，token400／600继续资格检查。下一质量队列 `cards/execution-queues/F1-b3-three-seeds-v3.json` 已冻结，SHA256 `4416ba7783db2ddbd7e808dfbfa16c939cc9b453875112e440bf6deb9f854f80`，尚未启动。
- 当前集成回归 `just translation-flow-v2-test` 290项通过（22.533秒、退出0），含structured、自然度静态契约、统一复审导入／比较与Windows完整性。`summaries/offline-integration-290.json` SHA256 `c2cf45c6a37a33b99d8948e43a1848fd800ec236ff98219056fd935fbf239e36`绑定日志与关键实现；不涵盖后续仍开发中的fluency transport或风险根因关联，也不证明模型质量。
- F5 structured真实资格已结束：54批全部尝试，37交付、14映射不可评、3规划失败，0/2完整SRT；155次completion，完整流程371.211秒。机械诊断显示映射不止遗漏标点，也有词语删除／替换；规划3批均两次输出／context触顶。原记录不修复成成功，独立精确分区grammar模块正在合成验证，未接入当前17模块。
- F6术语／F7局部背景原4096辅助输出资格均在completion之前因输入容量停止，完整耗时52.796／52.649秒，实际提示4107／4114tokens，超过允许4032。另立辅助输出2048的资格卡，主翻译仍4096、源文不截断、max_items16不变；`cards/protocol-qualification-aux2048-v1/freeze-manifest.json` SHA256 `755877203a82426fcf0bca8617e9a4fca8919b25b65826522bd30f71d19cef7a`，两条实际结果分列下文。
- 追加容量资格b60／token400／token600均在两完整场景270cue通过，分别6／8／6批，全部首试；完整流程89.711／89.217／89.733秒。收据 `summaries/F1-capacity-v3-receipts.json` SHA256 `dc155f90df8f6d7cada757a26489763995b2b451b628631869d5b032c007cf63`。这不保证所有筛选场景都可容纳，也不是质量或配对提速证据。
- F6辅助2048已实际发出4次准备调用，但两场景仍失败：重复术语证据不足两条不同cue，另有引用不精确，未进入主翻译。源文侧正在区分术语本身是否重复与模型引用错误；原失败不修复或过滤为成功。F7辅助2048已完整交付54/54批、2完整SRT、153.626秒，但实际背景注入0/54批：W01唯一记录uncertain而省略，M01唯一记录的8条证据不能同时落入局部批。仅为工程通过，不进入背景质量筛选；详见 `summaries/F7-local-background-zero-injection.json`。
- F7范围提醒：当前背景只在全部证据已于本批可见时注入，测试局部复述，不代表完整场景背景。未来独立版本拟将所选背景证据的原始cue加入只读context，保持源顺序、目标ID及严格可见证据检查，明确计入远距／未来源信息和成本；若有收益再做同一只读范围无卡片对照；由于卡片还重复证据引文，该对照只能归因整张卡片，若要单独归因摘要则还需保持重复源文呈现一致。当前术语能测固定全场景约定在局部出现处的一致性，不是滚动记忆。
- 对照范围补验：原C0生成34scene／4297cue，候选screen-a生成29scene／3606cue。旧C0投影只支持带范围限制的探索比较，尚无KV历史不变性证据。已在查看F1质量前决定补跑精确29scene的三seed C0，先比源／prompt／token／请求身份，再比实际输出与完整评估packet；仅逐字节一致才能复用旧判断，不一致则另冻matched48范围并补盲评，不拼造混合96窗生成身份、不改阈值。F1-b20三个seed已完成320次独立调用并封签，质量汇总与风险关联暂缓解封；原96窗C0保持完整供后续96窗扩展。
- 后续协议正于隔离源码副本 `implementation-staging/next-protocols-v1/` 中集成（源清单SHA256 `3b5a0cf45ec9ce5d59d3493cd82040943462c7bde189b2f4ee978726f6da032c`）。原工作区17个运行模块保持不变；只有当前b3与精确匹配C0组结束、源码差异审查和联合验证后才由主协调者提升代码，随后另立新卡。隔离副本不含本轮忽略目录中的评估参考／确认资料或模型权重；不运行GPU。
- 自然度补充诊断协议 `summaries/naturalness-diagnostic-protocol-v1.json` SHA256 `99327af26582b9d24c0ebe8c8ec39a81a2a53e36d6e8dfc2e0e1c459914165e4`及独立 `v2_fluency` 合成测试已完成；真实调用、复审、封签和重复波动统计尚待接入。它只诊断具体阅读缺陷，不改变主量尺、确认阈值或产生赢家。

- 启动核对：本轮目录原不存在；没有遗留Python或llama推理进程。现有工作区有大量未提交／未跟踪文件，全部保留，不重置或自动提交。
- 已重读计划、评估规约、ADR-0005及相关demo／工具链／Windows／验证文档。源文、参考、运行器、交付投影和统计由隔离职责并行推进；模型推理仍由主协调者串行安排。
- 源资产复核：六部剧集未使用集数为13／15／17／13／26／13；四部电影历史分块之外的候选块为78／72／181／94。这不是语义资格通过。
- 电影长片段可能包含历史实验见过的非评分上下文；新评分源事件排除历史可见事件，并记录上下文历史重叠。严格隔离本轮筛选与确认的全部可见范围，不声称电影或上下文完全未见。
- 缓存证据：仅清除slot不能证明清除服务器RAM prompt cache。各候选／seed采用新managed server进程，核验首个completion的`timings.cache_n=0`，随后正常启用缓存；`tokens_cached`不是复用量。
- 运行器使用新schema，避免修改历史P阶段和冻结产物。`decision-policy.json`须等C0的16窗盲重复校准后、任何新候选成绩之前冻结。
- GPU静态检查：RTX5080，驱动617.14，报告总显存16303MiB；查询不是本轮模型加载或长输出通过证据。

产物根：`.local/translation-evaluation/hy30-flow-v2-20261008/`。源文筛选置于`source/`，参考及封存确认置于`evaluation-only/`；实际冻结和命令随完成追加，未完成步骤不得凭入口存在视为通过。

### S0已落盘证据

- 源文已冻结96筛选／48确认、480／240评分cue；筛选34个连续片段、确认20个，每片段80–160cue且最多3评分窗。screen-a／screen-b各36代表＋12风险；16个校准窗覆盖10作品。独立重跑文件逐字节一致，源抽样7项离线测试通过。
- 筛选manifest SHA256：`563a60a4a9cda0f33bdfbe9d2b6b29042ff768cea43d88defeb90af3a3029f67`；freeze SHA256：`9b1aec59496d2e48cd95c44528f94aa1dadd68b729ca28a0c44aa2702dec5e1d`。这是源资格身份，参考尚在双轮复核，可能按事前候补替换评分窗并发布新身份。
- 抽样器自审发现初版先选风险会改变代表性抽样框，已在任何候选成绩前纠正为先概率抽代表窗、再选风险窗；初版保存在`source-preparation-history/`，不冒充最终冻结。历史可见评分事件零重用；2714个历史上下文事件键包含日中两轨溯源元数据，实际可见日文为1357个（筛选903、确认454）。中文轨只用于独立参考溯源，不提供给翻译器。
- 裁判普通合成探针5项预设诊断通过；native grouped探针4项诊断通过，含显式mapping不可评和交付零分。配置Sol/high，CLI0.160.1；未返回服务端模型身份，保持未知。这不证明真实裁判准确率。
- `S0-C0-qualification`第一次仅发生CLI白名单拒绝，未加载模型，0.127秒；新增v2 worker允许项后以`S0-C0-qualification-r2`新目录执行。137cue／28批全部首试交付，完整命令75.605秒，批次耗时合计20.637秒；1个完整场景SRT已导出，137条源序号和时间逐项一致。3个评分窗／15ID仅用于工程映射检查，尚无质量分。
- 首次导出发现worker的transport位于session父目录，旧路径约束误拒绝；新适配器核验session／workload／模型身份并绑定原始请求响应后允许这一精确目录。17项交付测试通过，原始运行不改写。
- `S0-C0-screening-seed20261008`已启动：34场景／874批／96评分窗，按冻结源顺序，附独立源token计数成本。运行命令为`python -B -X utf8 -m experiments.translation_flow.v2_execute --prepared .local/translation-evaluation/hy30-flow-v2-20261008/cards/S0-C0-screening-seed20261008/prepared --output .local/translation-evaluation/hy30-flow-v2-20261008/runs/S0-C0-screening-seed20261008`；恢复时先核对进程、completion与ledger，不重复启动同一目录。

源抽样、参考、worker、交付、统计和准备模块均有新离线测试；汇总数量以最终集成回归为准，不能将开发中的重复测试相加当不同用例。尚未完成16窗真实C0盲重复、decision-policy、F1–F9比较或独立确认。

### 首个完整C0源运行与继续执行

- `S0-C0-screening-seed20261008`已完成874/874批、4297/4297交付cue、34/34完整scene SRT，未重试；这4297条是机械交付分母，原96评分窗仍只有480评分cue，不能混用。独立语义评价尚未完成。
- 完整managed命令738.983秒，其中启动后runtime725.389秒、冷加载6.703秒；批次耗时651.806秒、生成637.640秒；源token测量另21.318秒。此轮不是正常成对性能样本，准备／导出当时未单独实测，完整端到端耗时保持未知。后续`v2_trial`记录准备至导出的完整墙钟，再按事前AB/BA计时卡比较。
- 实际49/49层GPU；整卡采样峰值15718MiB、最低空闲260MiB，server与worker均退出。输入399748／输出86663tokens；这些是全部批次token总量。4297条源cue token中位数10、p90=19、p95=21、最大35，已保存逐cue真实tokenizer身份，后续token分批仍核验完整提示预算。
- `S0-C0-screening-seed20261009`正在同34源片段上执行第二个冻结seed；此前源参考尚未发布，新准备使用qualification阶段，明确不做提前质量结论。只有参考合格发布、源范围一致核验及可追溯重新投影后才能用于语义比较。
- 参考原144窗的初审与独立复审已完成；首批17窗按原同层候补替换，无配额缺口，替补双轮复核仍在执行。最终源／参考身份尚未发布，不以临时通过数宣称参考完成。
- 方法审计发现`series_cluster`／`series_id`接口不一致、作品ID与标题核验混用，已修正并增加合成回归；SAO两片按同系列聚类。校准统计现按类别与代表／风险层拆开，区分严重错误出现／消失和单纯证据措辞变化；不预设阈值。

### 参考与合格源发布

- 新参考144窗／720ID已完成：119窗双轮直接一致，25窗经一次有界fresh裁决解决；20个被拒绝尝试按冻结候补替换（筛选12、封存确认8），没有改变scene范围。原始排除、争议与所有替换链保留，不是从144窗删去难例后缩分母。
- 参考freeze SHA256：`7378e4920817a609c0d4191de280470048dfa2676a7a0eb7b4bc6eff1e6b0c91`。实际请求仍是Sol/high同模型独立调用；没有音画或人工金标准，服务端未返回的模型身份保持未知。
- 参考导出的安全元数据路径曾为绝对路径，与原source manifest的相对路径字节不一致；创建独立`evaluation-only/qualification-compatible.json`归一化派生，SHA256 `4c3ae85159f1ea6a490a8007f52b02e977b23c65c093a2b7b6c8b0288cbd3610`。原参考freeze不改写，派生保留原哈希。
- 合格筛选源发布于`source/screening-qualified-v1/`：96窗／480ID／34scene。manifest SHA256 `da2ff2a616403aa7d3fbee6d3f8064efb5667fc6100aa8b69a480b920e135d6c`；freeze `bc4ee2779504503ebf15b4465f0fa872b2f7ca45d5d459d0e2eaefbf02b4e0c6`。scene文件与原冻结逐字节一致。校准16窗跨10作品保持，3个ID沿替换链更新。
- C0 seed20261009也已完成874/874批、4297/4297cue、34/34scene导出，完整命令719.619秒。seed20261010已启动同源874批；完成后继续保存原运行和合格评分重投影，不重新计算独立样本数。
- 新模块集成140项通过；随后新增冻结候补顺序用例的独立测试通过，最终合并数量待最后稳定代码回归统一记录。16窗盲重复与decision policy仍待完成，未执行候选质量比较。

### S0阶段的历史活跃步骤

1. GPU：`runs/S0-C0-screening-seed20261010/`第三seed命令已成功完成，714.569秒，正在导出及重投影。当前串行运行`runs/F1-capacity-b40-qualification/`；不要并行启动另一个GPU运行。
2. 评价：首seed主评96/96成功，必需58窗盲复审正在执行；之后继续第二、第三seed，全局最多6个CLI。16主评＋32相同packet盲重复已完成，零传输重试。纯聚合入口`evaluation-only/C0-calibration-seed20261008/policy-input-aggregate.json`，SHA256 `b16f0d15545f87bf1f2924c96e4cc8fa32602d66b0a600f699df03ea1583136b`。16窗中4窗有一档语义波动、无两档变化；3窗major出现／消失、无critical出现／消失；48次自然度均为2分。重复只校准同一生成seed，不新增翻译样本。`decision-policy.json`正在按该聚合与前瞻实用目标冻结，不能把噪声估计冒充准确率门槛。
3. 已完成派生：`exports/S0-C0-screening-seed20261008-qualified/`和`...20261009-qualified/`，各96窗／480评分ID、34scene／4297交付cue；仅换合格评分范围，新增推理与计时为0。delivery SHA分别为`34e31170f5dfad68ccdffb3a470a2aa80a0d6f762045a8e06bf4aee8e5e3452e`和`713f3ef1cb0fedd2206960f1813cf5eeb36e032d376af539d505f584c93b631b`。评分窗split不是完整scene身份，重投影明确区分二者。
4. GPU串行资格：`cards/protocol-qualification-v1/`已预登记`F1-capacity-b40`、`F1-capacity-b80`、`F4-id-text-b5`、`F5-semantic-b5`，共同源为W01和M01按冻结顺序的首个scene，单seed20261008。入口`python -B -X utf8 -m experiments.translation_flow.v2_trial --card <卡.json> --output <新目录>`。这些是工程范围，语义评分分母为0，不能用未通过资格淘汰整个假设。b40已启动，其余待串行执行。

源长度几何检查：固定1／3／5／10／20／40／80条分别4297／1441／874／444／231／125／68批；满批分别4297／1421／845／413／198／91／34。几何满批数不证明token容量、翻译质量或效率。

### 判定规则与首批容量资格

- `decision-policy.json`已在任何新增候选质量成绩前冻结，SHA256 `409553d1a5e2cbfb2e329d415a2b0e862b6a248550b5be5812dffcc4f3c85a9e`。确认主终点按seed→窗口→作品→类别汇总，代表／风险分开；预声明类别实际改善下界至少+0.25，通用方案另一类别及效率方案两类别非劣界0。新增已接受critical或未解决的新增实质major损害阻止确认，不以速度补偿。
- 最多三套确认候选在开启确认前统一锁定、不补位；语义六项加时间三项共九项，预留95%家庭置信度。自然度校准满分仅作量尺限制，不能证明没有改善空间。小簇bootstrap与同模型参考／裁判的局限保持。
- 实用速度目标为本轮固定34scene／4297cue完整工作节省至少60秒，独立计时区间半宽至多15秒；先至少四个AB／BA平衡探索配对估计方差，再预冻结全新独立固定重复次数。60秒、15秒及+0.25均是前瞻用途选择，不是校准推导的准确率标准或资源配额。
- 第三C0 seed已验证874/874批、34完整scene、4297精确源锚点；合格重投影delivery SHA256 `c2c156fa6d4f244f0c1b155082e42f125324cf9ce5c4a162f9f44c029ba1d7d6`，新增推理／样本为0。
- b40资格：共同两个135cue源片段，8/8批首试完整交付，完整流程91.425秒。b80首批的真实完整提示4211tokens，高于当前允许4032输入tokens，在completion发送前明确停止；未截源、未改4096输出预算、未回退CPU。这是当前配方容量边界，非质量失败，后续补测b60与源token组织，不能据此关闭大批次方向。
- 当前GPU已转入`F4-id-text-b5-qualification`。首轮质量卡将使用screen-a的48窗／240评分cue，对应29个完整源片段／3606交付cue，三seed；评分窗口不会重新决定分批起点。

### F4／F5首版失败与修订接跑

- 首版F4两个片段54批仅15批交付，完整流程110.597秒，未生成伪完整SRT。原始文本常保留目标ID却将正文置于标记同一行，违反首版独占行契约；正在严格区分格式与ID覆盖问题，准备另立`id-text-flex`协议，不改写旧运行或放宽旧结果。
- 首版F5两个片段54批全部未交付：52批映射不可评、2批规划失败，212次阶段尝试，完整流程247.432秒。已观察到真实多cue规划及联合译文；主要失败是字符计数／单元局部与全局偏移混淆。修订方案拟以原生联合译文的唯一精确子串为边界锚点，由程序推导连续跨度；单cue单元可确定性映射整单元。仍要求全覆盖、无重叠、无重复整段，不能将当前失败归纳为语义单元方向无效。
- GPU当前空闲，正在串行整合新协议与同Hy30的源术语／背景准备路径。新模块离线通过尚未构成新配方真模型资格。下一步先新目录执行修订资格及b60／token容量资格，再进入三seed筛选；旧F4／F5筛选卡的前置资格未满足，不可直接执行。
- 首seed C0评估已完成96主评、58盲复审、12有界裁决，166逻辑任务零重试。终分保留一个语义null及source/reference疑点，不改冻结参考、不缩分母；第二、第三seed评估继续。最终比较应使用终分与完整缺分界，不能使用临时主评。
- 确认源仍封存。最终最多三候选锁定后，需要依据已冻结参考的8次同层替换链单独发布48窗confirmation-qualified源，再开放确认运行；现有screening-qualified发布器不应冒充支持确认。
- 首seed评估的终态完整性封签遇到Windows长路径表示误判：同一job的`\\?\D:\...`与`D:\...`被旧包含关系检查视为不同路径。裁判任务与原始哈希已完成，封签暂未发布；正在单独修复路径规范化并验证真正越界仍被拒绝，不重跑或改写原始裁判结果。

### 第二版修订集成后的历史步骤

- `just translation-flow-v2-test`整体205项通过，日志与当前卡freeze身份在`summaries/offline-integration-205.json`。新增源码与旧运行快照分开；旧源合格发布器已保存至`methods/source-publisher-history/6998dc55f4d057a2af9fcec20abe18f445618fc042bd890c3ae98f1569d0ac01.py`，对应既有源freeze builder哈希。
- 新资格卡`cards/protocol-qualification-v2/`已冻结`id-text-flex`、`semantic-anchors`及独立源术语／背景准备，各自源、实现哈希明确。当前GPU运行`runs/F4-id-text-flex-b5-qualification/`；其他新资格待串行。所有卡仍是工程语义分母0。
- 源准备接入完整trial，额外启动／模型哈希／生成／卸载成本只计一次；完整准备失败不进入主翻译。每批options保留源证据与哈希，原参考不进入准备。辅助4096输出预留的实际容量仍待本机验证。
- 已修复Windows长路径等价表示的包含检查；16项完整性测试加17项评估适配测试通过，其中真实长路径与越界拒绝在原生Windows验证，真实UNC网络I/O未验证。首两C0 seed各166裁判任务均已完成并封签，零重试／零新增补跑调用。首seed seal SHA `0d16844c671c115b7f8dab7d36ba738172432657187adcbe7e0554e6b355bc94`，第二seed `ef0d5a96ea481888a65eecadf06a0f64a02f284f5ba7bccd09da773939574f2a`；第三seed继续。
- 首轮筛选卡v1保留，正在创建v2派生以绑定修订后源码和明确跨seed候选组；不改旧卡。其待执行菜单不是自动穷举网格，后续扩展由三seed质量证据决定。尚无候选质量结论，探索尚未收敛。

### 首个候选筛选启动

- F4 `id-text-flex`资格54/54批全部首次交付成功，两个scene共270cue完整导出；完整流程91.318秒。首次非JSON资格通过不等于语义优势，仍须三seed配对质量筛选。原版失败不改写。
- F5 `semantic-anchors`资格仍未完整通过：有成功交付，但规划ID和精确映射仍有失败；完整命令164.790秒，未伪造完整SRT。后续拟测试固定源顺序的边界规划和精确原译文片段拼接映射，须另立配方，不在现卡中偷偷修复。
- `cards/screening-round1-v2/`已冻结48张待选择运行卡，bundle freeze SHA `cc5e71951e1dfaa8952274365a97f6a9106faff42ee820ff8f103bd2f0126e2d`；显式`candidate_group`跨三个seed稳定，绑定修订后实现哈希。新F4／F5资格依各自真实记录判定，不沿用首版资格。
- GPU当前执行`cards/execution-queues/F1-b20-three-seeds.json`，串行输出`runs/F1-b20-screen-a-seed20261008`、`...20261009`、`...20261010`；队列日志`runs/F1-b20-three-seeds-queue.jsonl`。任一运行失败即停队列供诊断，不能跳过失败扩大成功分母。源为screen-a的48窗／240评分ID，29完整scene／3606交付cue。
- 评估负责人获授权在第三C0 seed终态完成后按落盘次序评价该三seed候选；保持全局6 CLI，严重风险并集复审及终态封签。现在只有资格结果，尚未形成候选质量结论。
- 在任何F1质量任务前发现旧finalizer只看单root风险选择，无法保证分开运行的C0／候选风险并集。现决定固定全窗盲复审：各seed的C0全96窗及候选全部48／96窗均独立复审。原已封签C0版本保留，复用已验证主评／复评，仅补缺少的复评，另建有完整溯源的终分派生；不得直接复制绝对路径账本绕过完整性检查。比较将统一使用全窗复审版本，主量尺与decision policy不变。
- 自然度48/48校准到顶不能关闭F7。已批准独立、仅用于探索的`sol-high-fluency-diagnostic-v1`辅助诊断：可复核语法／搭配／阅读障碍／源文支持语域，与纯措辞偏好分列，不增加主总分、不改变语义优势门、不替代忠实度判断。该侧轨尚在实现，无真实模型调用或结论。

外部v2只读完整freeze校验、其validator自检及首seed合格96窗结构校验均返回0；日志在`summaries/external-corpus-check/`。未改写外部语料，结构通过仍不等于语义正确。

## 已完成的准备审计

- 核对第一轮报告、台账、原始选择元数据、screening／recipes／worker代码、当前ADR和自动评估规约。
- 纠正解释：第一轮仅支持有限具体配方未过筛，不支持1-5-1最优或主要方向充分收敛。原始结果、失败和评分不改写。
- 发现缓存与配方名耦合、旧筛选器写死温度0／1024／±5cue、阶段窗口上限、逐ID投影与新参考构建配额等缺口，已列入计划第7节；尚未修复。
- 只读资产审计支持10作品候选配额，优先未使用剧集及电影新块。机械可选数量不等于高质量参考；新144窗均未发布。
- 当前基线仍为ADR-0005的official30b-cached-v1；历史B0与第二轮C0名称区分，不自动采纳新方案。
- 独立方法审查已完成并修正三项：代表性抽样需冻结随机框／顺序；普遍审校不是选择性审校的收益上限；重复计时需预先确定不依赖有利结果方向的停止规则。新计划与台账6个本地文档链接通过，96／72／24／48配额核对通过；本次仅文档修改，未跑模型或代码测试。

## 初始探索台账

所有方向输入来自尚待冻结的C档；工程资格、48窗初筛、96窗扩展和48窗确认按计划分阶段，不把每项都直接铺到全部样本。资源记录正常保留，不设总调用配额作为探索终止依据。

| ID | 假设／优先级 | 唯一主要变化；固定项 | 输入与资源策略 | 结果／状态 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| S0 | 公平比较与可测量性／前置 | 数据与执行资格；不比较方案优劣 | 已冻结源96＋48；参考替补双轮复核、C0多seed与16窗校准 | 执行中；尚未通过全部前置 | 完成参考资格、评分重投影、盲重复与decision policy |
| F1 | 批次规模／token组织／高 | batch改变；提示、邻文1、采样与缓存固定 | 1/3/5/10/20稀疏锚点，按趋势扩展及插点；3seeds | 未运行；待筛选 | 足够长片段与位置诊断，先写首轮卡 |
| F2 | 上下文长度、方向与相关性／高 | 邻文改变；初轮batch5固定 | 0/1/3起步，按证据向外或非对称扩展 | 未运行；待筛选 | 冻结可见源文范围与场景标签 |
| F3 | 联合理解而不混淆归属／高 | 只改独立值指令；原JSON/grammar固定 | 同源同目标同参数，3seeds | 未运行；待筛选 | 单独版本化提示与配方 |
| F4 | 非JSON交互协议／高 | 协议及必要输出约束联动，不能单独归因JSON | ID标记文本起步，真实覆盖／语义／总耗时 | 未运行；待筛选 | 解析与映射合成资格，再与C0比较 |
| F5 | 真正语义单元／高 | 源文规划、联合翻译和拆回；多步骤整体候选 | 同Hy30源文准备；全部辅助成本计入 | 未运行；待筛选 | 建立源跨度及评估契约，不用旧逐ID投影冒充支持 |
| F6 | 术语／跨批记忆／中高 | 先术语，再场景卡；不读参考 | 连续片段作用域，记录首译错误传播 | 未运行；待筛选 | 源文重复与别名诊断、冻结准备来源 |
| F7 | 风格与背景／中 | 两种提示分别测，不叠加起步 | 既有量尺＋错误证据，防满分误判无收益 | 未运行；待筛选 | 按源场景与测量校准安排 |
| F8 | 审校和局部修订／中 | 先审校潜力，再触发策略 | 小范围普遍审校探针；净改正、误改、漏报及全成本 | 未运行；待筛选 | 定义只用源文／自身译文的独立准备路径 |
| F9 | 容量、reasoning、恢复与效率／条件 | 每轮只改有证据驱动的变量 | 触顶／OOM／稳定难例等触发 | 尚无新触发证据；暂缓 | 主探索中收集实际瓶颈再决定 |

状态：待筛选、有优势待确认、优势已确认、已淘汰、收益饱和、证据不足、暂缓／受阻。淘汰具体配方不等于否证整个方向；试验未运行不得写资源资格通过。

## 执行前待冻结项目

1. 新源文／参考版本，作品与集数／场景名单，源事件和全部可见范围隔离；96窗分为两个均衡48窗筛选子集，另48窗确认封存。
2. 72代表＋24风险筛选的标签／权重；48确认的代表性抽样；候补与不合格替换规则。
3. 连续片段长度、起点、评分位置与诊断偏移；不要绕评分窗重新分批。
4. C0与候选的精确代码、缓存初态、3seeds、token预算和运行顺序。
5. 裁判校准结果与`decision-policy.json`，必须早于查看新候选结果。
6. 首轮运行卡；每轮在结果前记录新增问题、晋级／停止条件，预算只作保护与记录。

## 接跑边界

产物根目录为`.local/translation-evaluation/hy30-flow-v2-20261008/`，已开始S0新实验，具体已完成与活跃运行见本页执行进度。恢复时先查真实目录、进程和台账，不能因计划列有入口就假定已经完成。旧结果位于`hy30-flow-20261007/`，不得覆盖或冒充当前配置。

未来实现按计划分配互不重叠文件所有权；参考／评估agent与源文准备／翻译agent隔离。此次资产审计agent曾意外看到含中文的混合候选行，已停止读取，内容未用于配额或方法选择；它不得被当作后续参考盲译者。主计划不记录该行字幕内容。

达到计划收敛条件后交付报告并停止；若只有投入／外部阻碍导致停止，应仍标“尚未收敛”。不自动替换基线，不自动开展下一轮。

