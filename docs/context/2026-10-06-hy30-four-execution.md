# Hy30 四量化大规模比较接跑记录

> 2026-10-07 后续采纳更新：用户在完整报告交付后明确采用 **Hy-MT2 30B-A3B APEX-I-Compact**（`hy-mt2-30b-a3b-apex-i-compact`）作为当前字幕翻译基线。新决定与入口见[ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md)及[翻译 demo](../../experiments/translation_demo/README.md)。以下状态、时间顺序、SHA 和“当前 Q3_K_M 基线不变”等表述保持历史原文，描述本轮交付时状态；原报告、附录及 `.local/` 冻结证据不改。新的基线运行使用新输出身份，不恢复或覆盖本轮已终结任务。

状态：已完成交付及最终核验。当前 Q3_K_M 基线不变，未执行替换。下列较早记录保留当时状态，不是当前进度。

最终关闭：主控已逐项读取35项需求矩阵及独立公开报告复核；268项最终核验通过，411个本地链接有效，24份公开文件身份匹配。权威矩阵为 [最终需求核验](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/final-delivery-requirement-audit-v1/final-observation-v2/findings.md)，audit SHA8f55474a4f0bf1084b9a6f9b7d99cf88692f3f3e57d6cc8ef92e35d37326d8d3、seal SHA7cc30d8923d8852ac34f07e4e2c7e0ee076bc85da81aaf0fbd0f7010f4776d01。24个正式任务为4预检＋16性能＋4长跑；20完成与基线4次性能失败均有真实终态，无待执行项，32个去重运行包含工程历史。历史7并发/10.390877秒偏差、裁判CPU/网络与返回身份/实际账单不可观测等限制保持披露；完成交付不代表历史协议完全合规。公开报告不含私有字幕或裁判原文。方案、评估入口、README、INDEX、资产指南、demo及agent流程状态已更新；70个冻结Python源未变。没有活动模型/裁判需恢复，后续新实验按公开复现入口建立新身份，禁止覆盖本轮历史。

当前交付：[完整中文报告](../research/2026-10-07-hy30-four-quantization-results.md)、[复现入口](../research/2026-10-07-hy30-four-quantization-results-appendices/reproduction.md)。正文SHA ddff3a107684dc3dcaf84a4f0057bcf12a7637b401c21ce3cac0afa5da4b3e0a；23个附录文件覆盖质量、性能、正式稳定性、图表、精确身份及机器证据。公开精简numeric SHA9c13c2115b05683aa480afbf8d01844a3eed03f81fd73cf4963ae16769d244c2、formal-stability-numeric SHA8f5a6edb6b0fd27904277c8057d99e3de451f618fe85f6273df758cce1adde9b、source-map SHAe8c9f0ea55c5ab22cbe051b05cb9c642de9c173c8c594c2a4c08a10ddeddff39。final-public-report-review-v1权威v2检查974/974及原82项有效检查全部通过，seal327f2969a865a15d7c8fea062432eae489425d5efd5d61ffbb98cebcacdcead5。公开文档更新后实际新增集隔离复算exit0/chunkfd5f80，全部四输出字节与原件一致，未新增质量样本；完整证据在final-reproduction-entry-v1/parent-postpublication-expanded-01。没有活动推理或裁判需要接跑，不应重新分发原任务。最终需求矩阵已封存于final-delivery-requirement-audit-v1/final-observation-v2，关闭结论见上段。

公开报告已迁入`docs/research/2026-10-07-hy30-four-quantization-results.md` SHA ddff3a107684dc3dcaf84a4f0057bcf12a7637b401c21ce3cac0afa5da4b3e0a及23个附录/图像文件，原v7/publication-ready-v1保持封存；README、INDEX、方案、评估总入口、资产指南、demoREADME已更新导航。方案暂为“实测与评估完成，交付核验中”，goal未完成。implementation_audit独占final-delivery-requirement-audit-v1审阅全部明确要求/公开链接；evaluation_missingness独占final-public-report-review-v1复核解释、数值与隐私。主控发现公开两份numeric JSON约54MB且numeric-evidence仍有v6遗留formal_stability_final_integration/goal_complete元字段，已交paired_statistics在新public-numeric-correction-v1准备紧凑投影和source-map更正，尚未替换公开文件。不得改原ready、原始账本或历史源；主报告本身已含完整4款正式stress且无PENDING。最终所有改动校验及方案/接跑状态关闭后才能complete。

最终四款正式长跑审计与图QA均已完成：i1-L findings SHA31cf8d2e5d958efcfd3a27f367920ac67612102aa45d226af55311a2a636f968，effective最终用v4 SHA68fc033e6d7017d0872d527d21178b3065a19c74ad5a57c9b1d134f0feba691a。四款正式repeat共7690/7201.395091秒全部首试，无显式OOM，i1-L此次无慢尾但历史慢态仍保留。formal-stability-plot-qa-v1/release.json确认全部8图原尺寸可发布，0004–0007为新stress，0000–0003重复旧正式preflight；probe点图例遮挡是已披露非阻断限制，CSV完整。原生释放封存formal-stability-final-release-verification-v1/FINAL-SEAL.json SHA2b1e2a4137da24324b51a92476a7d5f60d3a9c818d3ac30d9a024e3dd119b9ee，174原文件及174快照发布前全部精确匹配。新聚合独立audit实际session25542初次exit1/chunkecdfe6，1419465检查中5项是审计口径误判（4个iterations列表包括warm/probe、1个读取已被v4修正的旧effective）；evaluation_missingness正在仅定向更正并保留原审计，无需重扫全部。paired_statistics的v7prepared-v1已准备公开相对链接与复现命令，待更正seal生成publication-ready-v1，再由主控发布并完成公共文档/最终需求审计；勿提前标完成。

2026-10-07 最终后处理推进：新8run聚合原工具session25922实际exit0/chunk804d6d，证明preflight/formal-stability-aggregate-tool-terminal.json；使用已核验缓存Python的绘图实际exit0/chunk4fa066，8图位于report/formal-stability-completion-v4-plots-v1，证明preflight/formal-stability-plots-tool-terminal.json。evaluation_missingness已获聚合审计放行，独占formal-stability-aggregate-audit-v1；demo_integration独占formal-stability-plot-qa-v1完成8图及输入SHA检查；主控已查看最后i1-L曲线。完整后台重叠complete-v1已完成并由主控读completion-readout：仅基线与408个arb attempt重叠1289.578652秒，另三款0；29527资源样本，judge/server CPU和network未计量保持null。原生排空观察06:42:55–59已无相关进程及8080监听，GPU511/free15467/util0，最终冻结源核验尚待封存。i1-L原始主审计11784检查通过，但agent私有末任务边界helper误用字面换行导致补充guard误报，正在追加明确更正而不重扫原始请求；不要将初始假失败当GPU失败。正式公开文档仍等最终审计与v7交付。

2026-10-07 06:40 UTC 四款正式稳定性全部调度完成：最后 i1-L 于06:39:00.423940完成，1957次repeat、1800.1094109999249秒，runtime报告exit0及server/worker退出；原GPU工具session44736已实际返回exit0（chunk1b0be1），不得重启。comparison_harness仅增量独立审计i1-L；judge_throughput获准生成完整四款后台重叠complete-v1；implementation_audit负责新的formal-stability-final-release-verification-v1原生排空与冻结源核验。原aggregator已启动新8run汇总，实际工具session25922仍在运行，输出report/formal-stability-completion-v4；尚未启动绘图。paired_statistics独占新integrated-report-v7整合终稿，等待最后审计和新图QA。质量、旧16性能、参考均保持终态，不重跑。公开报告及方案导航尚未交付，goal保持active。

2026-10-07 06:12 UTC APEX独立终态审计通过，主控已读`formal-stability-terminal-audit-v1/hy-mt2-30b-a3b-apex-i-compact/findings.md` SHAff923d8ae752aefc5131002f0b2ac62bcc7fef4afe6f120b3968a60232a92713。11658主/11636有效设置检查、19609证据SHA，1936repeat首试成功/1800.2921446秒，无失败/重试/OOM/遗漏；p50/p95/p99=.730489/.756326/.763718秒，前中后60/末120 p50=.741653/.731093/.728848/.728919，无持续慢尾；peak15723/free255，shared84MiB，preload790相对原performance553差237<512；released736/free15242，比preload低54，如实报告，不改成790。coldload6.634191/load→工件1810.104301秒，49/49 GPU，不断言物理驻留。schedulecompleted06:07:12.525089、i1-Lstarted06:07:12.566383，quality已早结束无judge重叠。baseline/i1-M所有审计/脚本原SHA不变。原44736实际poll仍live（chunk9bb06b），06:10:33 i1-L149repeat、GPU15822/free156；当前无待接收子任务，等最后一款真实终态后增量审计和完整后处理，不重复前三款原始审计。

2026-10-07 06:08 UTC 正式长跑已3/4调度终态：APEX1936repeat/1800.2921446秒，runtimeexit0、owned server/worker均退出，cleanup06:06:27.844330；06:07:37观察为completed3/started1，i1-L已started，原44736真实poll存活chunk851a16。已给comparison_harness放行仅APEX增量完整审计（新候选子目录），此前baseline/i1-M证据不改；不得读活动i1-L或提前标全目标完成。主控从runtime观察尚不代替独立APEX验收。最终仍需i1-L≥1800秒和终态、原44736实际退出与native排空、新8run聚合+8图QA（采用已验证缓存Python修正argv）、新stress完整后台重叠、正式24taskID联合完成核验，随后公开报告/附录/导航/方案更新及末次完成矩阵。所有质量/性能/参考/真实统计复算已经终态，不重复分发。

2026-10-07 05:58 UTC 质量概览图与最终绘图runtime修正已封存，主控已视觉查看v2 PNG（两类别配对分差、95%/99.1667%CI、覆盖与敏感性文字，无裁切重叠）及读runtime-addendum-v1.md。入口`report-draft-preparation/publication-figures-v1/expanded-semantic-paired-difference-v2.png`（同名SVG），caption.md、figure-identity-v2.json、render-qa.json、evidence-sha256.json已齐；v1保留。最终stress后处理应分别执行原aggregator，再按runtime-addendum-v1.json用实际缓存Python3.12.15/matplotlib3.11.2直接调用原SHA14c9cec...的plot_performance.py；输出仍`report/formal-stability-completion-v4-plots-v1`，原script/contract未改，禁止提前跑。修正命令不经过resolver/安装/网络，自行MPLCONFIGDIR写output。原44736实际poll存活chunk8c12d8，05:57:29 APEX1358repeat，GPU15723/free255，2completed/1started/1pending；所有当前子任务已完成，无待接收产物，等原APEX终态后增量审计。

2026-10-07 05:55 UTC 质量概览绘图发现真实缓存查找问题：demo_integration原offline uv尝试先sandbox AccessDenied，按规则escalated+workspacecache重试后resolver称matplotlib未缓存；主控只读找到实际已有环境 `.local/cache/root-uv/archive-v0/uj2yqvDB3GlcC1VJD6DxQ/`，pyvenv Python3.12.15/uv0.8.15，site-packages实际matplotlib3.11.2/numpy2.5.3。已让agent直接用该Scripts/python.exe -B并设置所属工作区MPLCONFIGDIR，不下载/不改源。其将追加runtime-addendum-v1说明最终stress绘图的修正argv；现有`formal-stability-report-preparation-v1`封存script/contract不修改，最终不要盲信其uv0.12.22 resolver命令可复用，应按新实际环境单独aggregate+plot或另建版本。原44736继续实际存活chunk0f5131；05:54:35 APEX1170repeat、GPU15723/free255，仍2completed/1started/1pending。

2026-10-07 05:52 UTC 原44736继续实际存活（chunkbbbc88），APEX976repeat、GPU15723/free255，正式2completed/1started/1pending；尚待APEX与i1-L终态，勿重启或提前聚合新stress。demo_integration新增独占 `report-draft-preparation/publication-figures-v1/` 制作新增质量两类别配对差值及95%/99.1667%CI静态概览图，只读已定summary、不重算bootstrap/评审、不读活动stress。待图像交付后主控视觉核验并在最终报告嵌入；详细表与完整分母缺分界保留，校正CI不能改成准确率或把小正下界夸大。

2026-10-07 05:44 UTC 两套真实离线统计复算独立验证完成：`final-reproduction-entry-v1/parent-real-replay-verification-v1/补充说明.md`主控已读；verification SHA3a4eea72b819782d95989cfbd23ae237760f6523692877fdb413f9eb320fbf6f，seal d976f5ec35608f681e29ef42d86eb4b86442e9f808a2185496ca3b061437434d。两轨各summary/report/config/executed-source全字节一致，expanded summary SHAb4e46e31d897ee1580571ad2937fec1ff7aa4f5c19694ebd02da4b523e180412；12输入hash与每次12隔离导入匹配。原README/seal及388文件不变；最终引用README时同时链接后续补充，不再称真实复算未执行。未重跑GPU、裁判或增加样本，性能/图像复算仍未走capsule（已有原正式汇总与QA）。原44736复验存活chunk5719c2；05:43:13 APEX435repeat、GPU15723/free255MiB，正式2completed/1started/1pending。已读35项旧matrix，质量/账目项现有终态证据完备，但该snapshot-03本身过时，最终总矩阵需在剩余长跑与公开交付后新建，不能拿旧准备状态当最终验收。

2026-10-07 05:41 UTC i1-M正式长跑增量审计已通过并由主控读findings：`formal-stability-terminal-audit-v1/hy-mt2-30b-a3b-i1-q3-k-m/findings.md` SHA01f4b55fd0194980d20ffb8b81b4e371534778ff050a1791533c6cc027db793b，主11916/effective11894检查、20039证据SHA；1979repeat首试成功，p50/p95/p99=.689914/.722253/.744927秒，peak15247/free731、released790，无尾段降速/正式judge重叠。baseline证据不变。APEX05:40:26为257次repeat、GPU15723/free255，原44736实际存活chunkc96956。复现入口`final-reproduction-entry-v1/README.md`主控已读，seal f7324170f8d800f207092850957c7b130871d0b5702266fb3bfbd20be1637f9a，capsule-04保留49源副本/174快照；主控另真实执行两个隔离离线统计命令：parent-recompute-regression-01 exit0/chunk128fee，完整summary字节与原SHA2d3b128f33c8e7c82f22c31bd49a972156fef9600764d2f86b390a5894084beb完全相同；parent-recompute-expanded-01 exit0/chunkeab01e，implementation_audit正在新parent-real-replay-verification-v1补核全部结果与输入/导入身份，不修改旧README/seal。未新增推理/裁判/质量样本；最终报告应引用补充说明，不能仍声称仅合成验证。新的GPU复跑模板使用新freeze，不复用旧watcher；原身份保护保持严格。

2026-10-07 05:37 UTC 正式稳定性已2/4终态：i1-M1979repeat/1800.8024319秒，runtimeexit0，owned worker/server均退出，cleanup05:34:41.001441，released790/free15188；已给comparison_harness放行只增量审计该候选，baseline不重审。APEX原队列已started，05:37:10观测47次repeat、GPU15723/free255MiB，i1-L pending；原GPU44736实际poll仍live（chunk314b99），不得重启。主控完整读`report-draft-preparation/integrated-report-v6/report.md` SHAa2269d7e56456bb696b37fe12a3608337ee89450f197780d806da65bd53f2ddd；来源31/检查110，最终来源映射用source-map-ready.json，原初稿映射保留。新增parent-review.md记最终迁入公开报告、精确调用口径、正式stress及复现和导航整合事项。新的baseline后台重叠`formal-stability-background-overlap-v1/baseline-v1/report.md`主控已读：monitor1845.675932秒，CLIunion1289.578652秒、408arb attempts、peak6；reservation1411.825250秒，不能当实际请求，judgeCPU/network未采。judge_throughput已完成并等待其余3款全终态后release complete-v1；baseline证据保持immutable。implementation_audit离线capsule已有49精确源文件/16import/27synthetic测试通过，尚待最终说明和seal。最终文档不在GPU退出前改动。

2026-10-07 05:30 UTC 主控已读新增质量终态正文和独立解释报告：`report-draft-preparation/expanded-quality-fragment-v1/terminal-render-v1/report-fragment.md` SHA1556e5800d50cb2b58f8accbd68db69131764d83f84ed8bd3b7cec530499cfb4，完整附录60作品行/8类别行/536源侧切片，独立647项检查与8项合成测试通过；`quality-interpretation-review-v1/review.md` SHA54c50811dc013a0e71282f21dee41b7aa35f38e639c7c2296adbac3eae7e5ecd。APEX剧集六比较CI下界0.000067067仅略高零，电影校正下界数值零、合并系列CI[-0.025,0.15]，不得泛称双类别获胜。paired_statistics继续独占新`integrated-report-v6/`整合可发布正文及附录，正式稳定性/最终复现待主控补入；judge_throughput独占新`formal-stability-background-overlap-v1/`，先准备并核验已终态baseline的实际裁判重叠，其余三款待终态释放。implementation_audit继续制作隔离的离线统计复现入口及新身份推理重跑说明，不改变旧freeze或原文件。GPU44736实际poll仍存活（chunk0ccdeb），05:27:52观测i1-M1520成功repeat、completed1/started1/pending2，无新失败；不可重启。用户进度问询已简答整体粗估85–90%、机械/质量100%、正式长跑1/4，未暂停任务。

2026-10-07 05:22 UTC 新增质量独立审计权威v2已通过，主控读report/summary：`formal-expanded-quality-audit-v1/final-audit-summary-v2.json` SHA9a259ba23ef2f7fd77cd909e67e5ca225eac1c1874b94456baae6d242eb4a439；初始68094/68098中4个错误first-success假设全部由两次既有schema有界重试解释并25项定向核验，208项补充统计通过，剩余问题0，初始失败审计原样保留。终分4792/4800、共同1195/1200、4合法未决+其余源疑问空分；8791job/8793attempt完整。改分定义核对64/64通过，`metric-definition-reconciliation-v1`：stats含null转换、helper仅两端数值可比，非冻结缺陷，主控已读说明。已给paired_statistics明确terminal/audit release，正在 `report-draft-preparation/expanded-quality-fragment-v1/` 制作真实allowlist并render；不得引用初始4失败summary冒充最终结论。methods/accounting终稿片段在 `report-draft-preparation/final-methods-accounting-v1/`，主控读section，29来源hash核验，最终集成须移除其当前1/4进度描述并链接独立GPU后台重叠证据。baseline正式长跑审计完成10949主+10928有效参数检查、18427文件：1818repeat/1800.191s全首试、peak15247/free731、idle/release790，共同初始553差237未越512。采用 `formal-stability-terminal-audit-v1/hy-mt2-30b-a3b-q3-k-m/findings-v2.md` SHA4703bab95131827b76ca768aeebc78510493e9c6960bd15073c9bfd4ae67e105；v2纠正审计wall05:14时quality已结束的背景描述，原文保留。后续只增量审核新终态候选。GPU44736原handle继续，05:21:33 i1-M1089重复已落盘，completed1/started1/pending2；用observe-v2.py，不用旧tail版本。implementation_audit独占 `final-reproduction-entry-v1/` 解决最终修改被冻结文档后原绝对路径freeze拒绝复现的问题，准备隔离/新身份安全复现入口，不允许临时覆写原文档或放松hash。evaluation_missingness独占 `report-draft-preparation/quality-interpretation-review-v1/` 独立解释已定质量、CI与代价，未新增判分，采纳仍待正式stress。全部后续源/方案更新继续等GPU44736终止。

2026-10-07 05:06 UTC 正式稳定性首款已completed05:03:45.787648，i1-M随后started05:03:45.874586；GPU44736原handle仍存活。baseline repeated phase1818次/1800.1911036秒，runtime translation_exit0，两owned进程退出，cleanup05:02:56.935469、最后released790/free15188MiB。05:05旧observer因仅tail262KiB而丢失超长completed行，误将baseline显示pending；主控完整逐行投影确认实际completed，已派comparison_harness新增observe-v2.py修复，保留旧观测；不要据旧observer误重启。新增质量独立审计evaluation_missingness原tool45479仍活跃，terminal guard通过，8791job全hash校验未完成，无报错也无pass；不从安静输出推断挂起或重跑。metadata-readiness检查exit0（chunkd3791f），新 `final-delivery-audit-readiness-v2/final-terminal-observation-01` 仅表示旧16性能/质量后处理已终态，不覆盖新stress或完整验收。历史全pipeline peak7已核实两段2026-10-06 15:39:52.922756–56.223291、15:39:56.241505–15:40:03.331847，共10.390877秒（dev恢复1+reference6），无用户豁免证据，属于全局六路要求偏差；主控读execution-complete及disclosure-v2，最终必须透明披露。全phaseusage补充 `judge-probe/full-pipeline-accounting-v1/all-phase-usage-supplement.json` SHA207b68824f68a06bb937b52130c1f227b2277df6a93f5d79b6f49617d1df658f，latest seal915da49bb962033981d26d99e6b67f49535696d831cecf9035895db2d15adbe5；12910 CLI attempts+4 fresh subagent调用不冒称provider计费请求数，tokens非金额。原46340/39632已成功终止，不再poll。主控已读新增最终stats report但未发布质量结论；paired_statistics仍等真实独立审计pass再render终态片段。

2026-10-07 04:59 UTC 质量全流水线已真实完成：原watcher46340实际exit0/chunke52806，不再poll该handle；裁决completed04:54:25.261386、finalize04:55:03.343439、quality-report-tables与pipeline04:55:45.056437。原生验证escalated exit0/chunk9ed5fa：`formal-quality-terminal-verification-v1/actual-watcher-46340-terminal.json` SHAed359ad4cad3750d0bdd02bad288c6207c22a4251422e80e757edf31cda8517c；`verification-20261007T045614-b5b12081c31d49de92cbd8404819b24b/native-lock-proof.json`实际获取释放global/scheduler、两次CIM无owned/qualityscope残留，历史锁bytes未变。主控已读native proof及新增stats report；evaluation_missingness已收到真实proof并执行guarded完整审计，尚待结果。新增质量为824裁决全成功无重试，arb账目summary SHA223b0fc0baf19b5076af44f208d83a16e0891575782323a450d6719bfa1e553d，worker15687.082169秒/scheduler2622.222671/18.854jobmin/peak6。完整pipeline账目已生成，summary SHA233a95d7a92bd922951689948f99467326940a763c36735ffeb5e4dd62db5855，主控已读两report；全历史CLI peak7需judge_throughput追加确切时段/任务/规约适用说明，不能无证据称已授权超六。合并性能质量表按既定exact argv成功：tool39632 exit0/chunk505a77，输出 `report-table-preparation/formal-tables-with-performance-v4`，proof `preflight/formal-tables-with-performance-v4-tool-terminal.json`。原GPU稳定性44736仍运行，不能修改其冻结源码或方案；首个baseline尚未终结。最终新增质量片段要等独立审计通过后再给paired_statistics真实release，不把parent已读stats当完整验收。

2026-10-07 04:40 UTC 原watcher46340与正式stability44736均实际handle复验存活；04:39:08裁决553/824成功、expanded8520job/8522attempt，尚无新增裁决重试。04:39:28新stability轻量观察为baseline started、其余3pending，第398次重复1/1成功，phase未结束、runtime未终态；新鲜GPU15247/free731MiB、shared84MiB，观察不等于30分钟验收。observer入口 `formal-stability-completion-preparation-v1/observe.py --record`，只读既有监测。终态quality helper准备完成 `formal-quality-terminal-verification-v1/verify_terminal.py` SHA0c8f4d1f5b5e4acd89e44c5ff9bc95fb3e2d4dd1e852a03fe8158a0c7dbf4f7a，10项离线scope/PIDreuse检查通过，尚未CIM/锁获取；真实46340退出0后，保存actual terminal JSON，再escalated运行helper取得native-lock-proof，随后才能执行 `formal-expanded-quality-audit-v1/guarded_run.py`，禁止直接跑核心审计。implementation_audit正修正旧FINAL_CHECK_COMMANDS中的直接调用示例为新v2文件，保留旧seal。新稳定性后处理准备 `formal-stability-report-preparation-v1/report-after-terminal.ps1` 主控已读：只等4任务终态后新聚合8run（4正式preflight+4stress）及8图，不覆盖旧28run。paired_statistics独占新 `report-draft-preparation/expanded-quality-fragment-v1/` 准备可读切片表生成器，尚未读活动终评，等待parent terminal/audit release。35项完成条件矩阵 `final-requirement-matrix-v1/snapshot-03` 保留全部scope，不能用准备状态当最终完成。

2026-10-07 04:33 UTC 正式稳定性补跑已启动：实际tool44736存活，exact `formal-stability-completion-preparation-v1/launch-v2.ps1` SHA743106f414532e2ae0bb53d84463bd8ebeac8edcbde164bf41d54127dc3fa8e0，manifest-v2 SHAa3008df778b8442ff3983ffa5f4eb44dfa2fd33bf971fd8bbb35d48106e222c6；输出 `formal-stability-completion-v4`，日志 `preflight/formal-stability-completion-v4.log`。使用原formal-freeze-v4和四个真实formal-preflight-identity-v4父attempt，独立串行baseline→i1-M→APEX→i1-L、各repeat1800秒，不重复性能轮、不导出质量、不改历史。启动前escalated Windows观察已保存在准备目录prelaunch-host-observation.json：8080无listener，GPU790MiB/util0，process匹配仅查询自身的两个pwsh；无modelserver。禁止重复启动44736；原质量watcher46340继续，04:30:52裁决387/824成功。两者都终态前不得修改被冻结源码/方案；handoff不在其冻结中。外部v2完整性最终核验通过，主控读findings：2479清单文件+根manifest、320实际使用文件全匹配，证据 `final-external-v2-readonly-audit-v1/final-external-integrity.json` SHA cb9ba786eaf9fc934c17340ec710deb06c14011ef2a516fc46ad3ecbf4f10f73。后续新稳定性可用原聚合器新目录生成4预检+4stress八run补充，不重写已封存28run性能汇总；最终合并调度证据，不把独立branch中性能not_run误作原性能未完成。

2026-10-07 04:26 UTC 接跑核验：原 watcher46340 实际 handle 仍存活（chunk bee6d8），04:24:59 观测新增裁决279/824成功，主评4799及复评3168已完成，仍仅前述两次恢复重试。paired_statistics 已完成 `report-draft-preparation/formal-performance-fragment-v1/report-fragment-final.md`（SHA1ab6631412d90ea6ee8f787c525c70a87cbf130bf1348c2ada6828b66580cf96），主控已读正文；性能旧聚合与28图保持不可变。重新核对方案5/6/9节后，为补齐正式冻结日程中的4个stability任务，已委派comparison_harness独占 `formal-stability-completion-preparation-v1/` 准备相同冻结配方下四款串行各>=30分钟的安全命令；尚未启动，不把工程长跑冒充正式任务。implementation_audit独占 `final-requirement-matrix-v1/` 准备逐项交付核对。evaluation_missingness已完成 `formal-expanded-quality-audit-v1/` 审计脚本准备，尚未读取活动终评或执行审计；须等watcher真实exit0、全局六CLI与scheduler原生锁释放证明及终评/统计/术语全部completed后再通知执行。最终报告、正式稳定性、终态质量审计及文档导航仍未完成，goal保持active。

2026-10-07 04:12 UTC 新增裁决已进入原队列：expanded-prepare-adjudication completed04:09:53.699111/exit0，expanded-adjudication started04:10:00.401009、running04:10:00.463967/PID17212；原watcher46340存活，04:11:07已17成功。主控仅白名单读取jobs-adjudication.jsonl：824任务，c01=198/c02=206/c03=200/c04=220，SHA6d4d1d526a77ac44c3f50cdccd57f434308e04419bc7c12ae46401b772624868，未读dispute语义。已通知judge_throughput在原review账目目录追加选中分母/forecast，不覆写历史。注意evaluation/formal-expanded-v4已存在的final.jsonl/summary/report可能为中间准备态，必须等真正expanded-finalize completed再读作最终质量；勿仅凭文件存在当终评完成。paired_statistics继续性能章节。原GPU/汇总/绘图均已终态，不重复启动；最终新质量、术语、统计、含性能表及交付审计仍待完成。

2026-10-07 04:10 UTC 新增review阶段completed04:06:52.102142UTC/exit0；3168job/3169attempt全成功含1恢复重试。judge_throughput完整metadata审计已完成，主控读report及closure：scheduler9756.436923秒、worker58470.934405秒、stage monotonic10005.684555秒、UTCspan10007.459777秒，不混时钟；3169独立cwd/explicitSolhigh/noTools，19014terminalhash匹配、19016总输入hash。closure-summary SHA b480e1cea94f79f9c03c8b27d8f5e7576a871d59c6998d7a5d03403c60fff4d1。原watcher46340仍存活，04:09最新事件review completed，仲裁分母尚未生成/核验，不重复启动。background agent完成formal-performance-background-overlap-v1，主控已读appendix：固定GPU监测cutoff03:33:01.526423，16session/123409samples/8016请求元数据，33277检查通过；R1无正式请求，R2/R3/R4重叠8605.095/8525.973/4382.153秒，max6；judge CPU/networkbytes不可测null，RAM不作因果。paired_statistics仍整理formal-performance-fragment-v1，已通知纳入background附录；其余子任务完成。后续等自动select-adjudication实际清单，再通知judge_throughput追加forecast；不提前读live语义结果。

2026-10-07 04:05 UTC 新增review3168逻辑任务全部succeeded／3169attempts（一次已恢复validator重试），但原watcher46340仍在stage收尾，latest journal仍expanded-review running；勿重复分发或仅凭任务全成功宣告阶段完成。judge_throughput已接任务独占judge-probe/formal-expanded-review-final-accounting-v1做metadata账目，等待stage完成及后续裁决清单。性能aggregate独立审计6062460＋92检查通过，主控已读findings；audit SHA b9a4e3cd4be51a29587aa56d242b04d7f5519821bd11a8a54b138e61bdbeeb58，supplement SHA b1c59967d1bc2274475de3e4c686ada5e5e56716cdbc456ea5b18d9d3a8cc0c9。正式schedule的stability4仍not_run；工程4次>=30min独立报告，不能称正式freeze全调度完成；工程/正式recipe/engine/DLL相同但6同名source差异已记录。plotQA全部28原尺寸及三输入hash绑定完成，主控已读README及binding、另查看0007stress和0027baseline4；图例遮挡/失败点未单独标色等限制保留。performance_load_overlap新agent独占formal-performance-background-overlap-v1，按固定最终GPUcutoff提取裁判重叠和背景内存；paired_statistics独占report-draft-preparation/formal-performance-fragment-v1整理最终性能章。implementation_audit/demo_integration本次任务已结束。原全部GPU/aggregation/plot tools已terminal，仅46340继续；冻结源码仍不改。

2026-10-07 03:55 UTC 绘图恢复已成功：tool48633 exit0/chunke44794，28张PNG与plot-identity.json均在report/formal-performance-v4-plots-recovery-v1。preflight/formal-performance-plots-recovery-v1-tool-terminal.json保留proof，原failed目录及log保留。plotter源码SHA14c9cec90cf104565cf1c42fa22c4d1f866706f595b1b7c7959ef4867628342c未改，输入performance SHA dd99ea259e9760105ff29ca29ae42288bc70018fe561756878ede4ce7a629f95，curves SHA a2dbcb0d84c78d87665f1407c3e246f05e6b0d0e99d40c72bfd6840c935452c8，alignment SHA36daa773bda67313331d6e9e5d9a0c0bc3469960c5a2d2bace010aa823a55835。主控已视觉检查0024 i1-L4，demo_integration独占formal-performance-plot-qa-v1检查全部28图，待接收；implementation_audit仍负责aggregate审计。原watcher46340复验存活，03:54:32复评3014／3168成功，仍一次复评恢复重试。不要再poll已terminal的33120／48633，继续原质量流程并等待两个审计任务。

2026-10-07 03:53 UTC 性能aggregate成功：tool33120 exit0/chunke377d1，完整report/formal-performance-v4五文件落盘，performance.json约466.8MB；主控已读engineering-report，28runs包含工程8＋继承正式preflight4＋正式16，基线四轮失败均排除有效比值。新集有效median i1-M951.632052秒、APEX1007.9254605秒、i1-L5238.6441395秒，范围保留i1-L第四轮快状态。implementation_audit独占formal-performance-aggregation-audit-v1独立核验，待接收。原exactplot命令exit1/chunka4019f缺matplotlib，原空目录report/formal-performance-v4-plots及失败log保留；未改冻结脚本或根依赖。已escalated启动uv isolated/no-project、projectpython、matplotlib==3.11.2绘图恢复，tool48633活跃，log preflight/formal-performance-plots-recovery-v1.log，新输出report/formal-performance-v4-plots-recovery-v1，不可覆盖或重复启动。汇总tool证据preflight/formal-performance-aggregation-v4-tool-terminal.json。原watcher46340继续存活，03:50:04复评2921／3168成功。下一步等48633终态并检查全部曲线/identity，等待质量复评及自动裁决。

2026-10-07 03:39 UTC 第四轮审计完成且主控已读findings.md（SHA551d8df8bb9ce6ae2ed9728117fee8c63997c0feac5881dd6345371212dded06）：15625检查通过／15528证据身份，原ledger全字段与窗口canonical一致，四轮结构化输出hash一致，24历史summary seal不变。audit SHA bb3adcd2f187dd242a66ab41a01ebeb816c45fff6d103511b8003ed2a79248f6；summary SHA074a31865d51b4ec56f094b4670427f10f4aa47febddb494def09b11a74cfdce。正式离线性能aggregator已按readiness-v2 exactargv启动，真实tool session33120仍活跃，log=preflight/formal-performance-aggregation-v4.log，目标report/formal-performance-v4；不得重复启动／覆盖。聚合包含各自冻结身份下的engineering-preflight-v1、engineering-stability-v1、formal-performance-v4，仅正式完整干净四轮用于速度比较。原watcher46340存活，03:36:51新增review2677／3168成功。子任务全部完成；下一步等待33120终态核验结果并执行既定plotter/逐图QA，继续原质量流程。

2026-10-07 03:34 UTC 正式性能全部16终态：原GPU66914已退出1（chunk7d94fa，commands-v6.ps1保留Stage not fully successful），12 completed／4 baseline failed，无活动GPU任务；tool证明preflight/formal-performance-v6-tool-terminal.json。基线第四轮旧83成功wall57.404420秒，新1199成功＋1失败／未执行0，wall968.047831秒，retry5.127796899993秒，load7.083109800005秒，runtime1076.957387699978秒；49／49、禁止CPU，两owned进程退出，cleanup03:32:59.517495 UTC。投影formal-live-observations/baseline-round4-completion.json绑定四源hash。主控已核对16个runtime均server/worker_exited=true及noCPU。已委派comparison_harness独占formal-round4-terminal-audit-v1做完整第四轮及跨四轮一致性审计，待接收后运行正式性能aggregator（目标report/formal-performance-v4目前不存在）。原watcher46340仍存活，后续复评／裁决继续；不要再poll已经terminal的66914，不重复推理。

2026-10-07 03:28 UTC 基线第四轮同窗失败已复现：H30-W06_E002-B0028两次input533/output1024、stop_type=limit、truncated=false，error为Generation reached output/context limit，attempt耗时5.256009800010／5.127796899993秒，窗口总耗时10.383936799946秒。投影formal-live-observations/baseline-round4-failed-window.json保留请求hash与原ledger路径；整轮仍在执行，不能用该投影冒充完整终态。GPU66914／watcher46340均实际handle存活，03:28:35新增888成功＋1失败，旧83成功；资源phasepeak14966/minfree1012 MiB/shared84 MiB。四次同窗输出上限失败不等于OOM，四轮有效baseline速度比预期不可用，完整观察耗时仍须报告。

2026-10-07 03:22 UTC 接跑：原GPU66914及watcher46340均经实际handle复验存活；基线第四轮持续运行，03:20:26新集303／1200成功（旧83完成）。新增复评03:21:46为2393／3168成功，两个阶段累计仅各一次已恢复validator重试。paired_statistics完成integrated-report-v5，主控已读report-final-draft.md，SHA ed889b8aa4c69c1cd398fec70147782e4772c41f47423db8d8c7f55b0b90fd49；最新账目附录accounting-appendix-through-i1m4.md、来源evidence-map-through-i1m4.json及bundle-validation.json，纳入15终态投影但不读base4活动结果或review语义。所有子任务已结束。该稿仍是准备稿；待新增终评、16轮总账与正式plots后整合，不应直接发布。继续原进程，保持冻结文件不变。

2026-10-07 03:16 UTC i1-M第四轮已completed：旧83／新增1200全部首次成功，零失败／重试／未执行／OOM标记；旧wall57.610673秒、新wall962.724054秒，新增p50/p95/p99为0.796427849971／0.936468519957／0.999179167977秒。加载7.628387900069秒、总会话1072.429037899943秒；49／49 offload、禁止CPU，owned server/worker均退出，cleanup完成03:14:31.105251 UTC。完整源哈希及资源摘要保存 formal-live-observations/i1m-round4-completion.json。性能15／16终态（12成功、3基线失败），原GPU66914已进入最后的基线第四轮；原watcher46340复验存活。paired_statistics正在独占integrated-report-v5准备更精简中文稿，含i1-L第四轮完整波动证据；不读活动语义结果，不改冻结文件。等最后一轮终态后再审计第四轮和执行正式性能汇总。

2026-10-07 03:00 UTC 接跑更新：原GPU66914／watcher46340均复验存活；i1-M第四轮旧83完成、新增117／1200首次成功，phase历史peak14966／minfree1012 MiB、shared84 MiB。新增复评1963／3168成功，仍仅一次复评恢复重试；性能14／16终态。观测 `formal-live-observations/quality-20261007T025937606276Z.json`、`observation-20261007T025947628944Z.json`。无待接收子任务。主控复核readiness-v2 contracts的manual_performance_aggregation exact argv及模块多freeze路径：工程preflight/stability保留但只有formal-freeze-v4完整干净四轮可作速度比较；正式aggregate须等16终态及释放核查，目标不存在时独占创建。原有两条流程继续，无实现修改或重跑。

2026-10-07 02:57 UTC APEX第四轮completed：83＋1,200均首次成功、零失败／未执行／重试／OOM标记；旧wall60.712186秒、新wall1017.646092秒，新增p50/p95/p99为0.843481349992／0.982956830092／1.076520707047秒。加载7.036975000054秒，总会话1129.984515299904秒，49／49 offload、禁止CPU、两owned进程均退出。idle/released均507 MiB；新阶段peak15511／minfree467 MiB，monitor error null。`formal-live-observations/apex-round4-completion.json` 绑定旧summary `afa6db76a5bf0ecdf2311112b0cd0e163e8a9b1df7b79780b66db808f2badbca`、新summary `c9780478d7b69cb02e4582224fa233c148712ccb42b257f1aa57c9224238155b`、runtime `f0da1bab451c2200f837500e9df30e2613882ef411e098791fdbba99f9d9bccb`、resources `d26f6925305d08cd81cc0b2f42a0d564d4522b4fddd830ac94eb619fb2396d82`。性能14／16终态（成功11、基线失败3），原GPU66914进入i1-M第四轮，之后基线第四轮；勿重启。原watcher46340继续存活，02:54:34新增复评1868／3168成功，仍仅一次复评恢复重试。所有已有子任务均结束；待全部16终态后核对第四轮全账、完整aggregation／plots，不提前写正式汇总。

2026-10-07 02:43 UTC i1-L第四轮完整审计已接收并由主控阅读：`formal-i1l-round4-terminal-resource-audit-v1/interpretation.json` 绑定summary SHA `3de509c9fb464d3407d5665b92c5569fd77e0059b3d65a7d3384ab31ee2d8f0d`、matched-expanded SHA `3ac48578bdaff07d849ca0de4523ff675ec1ca40a98a01d15eee922d587780e5`。1284含warmup全部首次成功，四轮对应actual request SHA／token IDs／长度／有效参数／canonical输出hash完全一致，并独立核对worker hash；早期114窗不变。第四轮1200窗全部快：decode median221.434、min187.634 tokens/s，12个100窗块中位217.130–225.207，无低于30或本轮首30中位85%的窗；相对前三轮同窗中位最低5.31686倍，median6.22571。shared340／dedicated15346.152 MiB恒定，peak15852／free126，fresh采样与PID唯一性通过。cleanup后64.249秒才下次APEX load。监测总长1104.164833秒（18.40分钟），短于此前repeat慢尾起点1592.513秒，负载也不同，不能声明30分钟慢尾已解决。无待接收子任务。原GPU66914／watcher46340继续存活；02:42:34新增复评1618／3168成功（一次恢复重试），02:42:44 APEX第四轮旧83、新增286／1200成功，性能13／16终态。

2026-10-07 02:38 UTC i1-L第四轮completed：旧83＋新增1,200均首次成功、零失败／未执行／重试／OOM标记，49／49 offload和禁止CPU保持，原server/worker均退出。旧wall59.019191秒；新增wall993.221850秒，p50/p95/p99为0.824492849992／0.960476939974／1.035930033914秒（前三轮新增约5239秒，必须保留轮间大幅波动）。加载7.610314200050秒，总会话1,104.248419799958秒，phase peak15,852／minfree126 MiB，idle602／released507 MiB，monitor error null。投影 `formal-live-observations/i1l-round4-completion.json` 绑定旧summary SHA `8889305330eeae93cb466451ab610ff048c2bdeee7adb0ee2352b66a7334b669`、新summary `f5ef6eb69266cb3ac18cff60cfa0f79bfd8053482be3d07e3dbd6e0d2e20c158`、runtime `3c316bb9b6611fd1c67d52d9cfb017a5757a612b95b28a7cd7d475ad2ade565b`、resource `210d0152d4b365bacfb2650db944e0585c71120a1e2d7841e38bfd5b740f1ca1`。性能13／16终态（成功10、基线失败3），原GPU66914已进入APEX第四轮，原watcher46340仍存活；02:36:39新增复评1,509／3,168成功，仅一次已恢复复评重试。已委派demo_integration独占 `formal-i1l-round4-terminal-resource-audit-v1/` 核对整轮快状态持续、同窗参数／输出hash、资源与释放，待接收；不能仅凭本轮恢复而忽略此前稳定性慢尾或宣称根因已查明。

2026-10-07 02:26 UTC 新增复评首个重试已恢复：`review/c02/H30-W03_E020-B0039` attempt1于02:24:18.112152至02:24:34.610353 UTC、CLI exit0/transport completed、16.496432500076秒，validator为 `source evidence is not in supplied IDs`，access_failure=null；fresh attempt2于02:24:34.624542至02:24:53.786172、19.161405800027秒成功。请求均sol/high、无tool events、返回身份不可见，两个隔离cwd不同。此为裁判ID证据验证重试，不是翻译失败／额度阻碍，不增加质量样本数。投影 `formal-live-observations/expanded-review-first-retry.json` 绑定job SHA `8120b5c0cfee0bcd83848f0db47c7a75f652981f544c4ba654e2b9d857e84c97`；此前主评一个重试仍保留。02:25:21新增复评1,288／3,168成功、expanded全部记录6,087job／6,089attempt；02:25:30 i1-L第四轮新增419／1,200成功，shared340 MiB／peak15,852／minfree126。原66914／46340均复验存活，无待接收子任务。第四轮前缀审计summary SHA补记 `45725d7258a6ef3e443dbe8259c6024fe8a5d7bd217302e521d6c0e58c65283c`。

2026-10-07 02:24 UTC 两项审计已接收并由主控阅读，无待接收子任务。第三轮 `formal-round3-terminal-audit-v1/findings.md` SHA `6b78203129bebd80e36521424bc50e0e011b88796c55a3ba4b5cd0a3cc8a7f49`、audit SHA `8a23b6c4542f72b14ca3a66ae12ea8904392bad4c09026d68c127c72215c8e0f`，15,599检查通过；四款均83＋1200全尝试，基线失败会话不可作有效速度，另外三款均首次成功。前三轮canonical输出hash同窗一致（含基线失败空输出，不等于成功），最终四轮仍需核验。i1-L应采用phase15898峰值而非runtime顶层15897；UTC新增完整wall5246.743039与另存perf_counter调用5245.1758756相差1.5671634秒，保留钟域／范围区别，不替代原值。

i1-L第四轮早期审计 `formal-i1l-round4-initial-resource-audit-v1/summary.json` 绑定snapshot SHA `c830325660bcfaf8012ab9d3be511e6c1fe01dcd5ecb5a7a7f153823930f83bc`，范围固定warm1＋旧83＋新30，截止02:20:26.117298 UTC。全部输入token IDs／输入输出数／参数／engine/exe/DLL／49层offload与前三轮一致、cache_n0。旧83 decode中位221.850 tokens/s（此前35.75–36.34），新30为217.544（此前R1/R2约35.7），对应每窗速度比约6.1倍。shared340 MiB且dedicated约多56 MiB，ambient602高于此前553/548，前缀余量126反而低于此前136，因此不能仅用显存余量解释速度差；当前仅前缀，不是整轮快结论。需要第四轮完整终态审计确认是否持续和释放情况。原GPU66914／watcher46340继续，02:22观测新增复评1225／3168、i1-L第四轮新增183／1200，均无新增失败。

2026-10-07 02:20 UTC 新观察：i1-L第四轮02:18:40附近进入后，02:20:27已完成旧83＋新增31，明显较前三轮初始快；此处只是运行前缀，不是完整性能结论。资源前缀peak15,852／minfree126 MiB，shared356,515,840 bytes（340 MiB），不同于之前396／430 MiB。已委派demo_integration独占 `formal-i1l-round4-initial-resource-audit-v1/` 冻结warm1＋旧83＋最多前30新窗元数据，核对与R1–R3同窗token／输入／输出长度／参数／engine及资源时序，无GPU干预或因果预设；待接收。comparison_harness第三轮审计也仍待接收，两者目录分离。原66914／46340均刚轮询存活，新增复评1,186／3,168成功；快照 `quality-20261007T022017808958Z.json`、`observation-20261007T022027053007Z.json`。

2026-10-07 02:19 UTC 前三轮全终态：i1-M第三轮completed，83＋1,200均首次成功、零失败／未执行／重试／OOM标记；旧墙钟57.320118秒，新增958.433027秒，新增p50/p95/p99为0.791534550022／0.932123369997／1.004673537002秒。加载7.580521299969秒，总会话1,067.888677200070秒，49／49 offload、禁止CPU，两owned进程均退出；idle/released均602 MiB、peak15,062／minfree916 MiB、monitor error null。`formal-live-observations/i1m-round3-completion.json` 绑定四源SHA，新增summary `4cdf244878a962497016ee887a213db1a2ac9ed3e6ab06bfbec67c23212c4095`、runtime `7cd7fcb35d34d6ed769781c730f8c143f655725de6950f99419d08d12d780fe8`。性能12／16终态（成功9、基线失败3），原GPU66914已启动第四轮i1-L，勿重启。原watcher46340存活，02:17:33新增复评1,128／3,168成功、无复评重试。已委派comparison_harness独占 `formal-round3-terminal-audit-v1/` 核验第三轮四款完整身份／顺序／计时／失败／资源与释放，复用i1-L已完成专门诊断；待接收结果，不额外调用GPU或裁判。

2026-10-07 02:09 UTC 整合准备稿已接收：`report-draft-preparation/integrated-report-v4/report.md`（SHA `4f7ab05d786c654d069245265695040cf3ad35eaa19b2cf8fa6b25fc332acab6`）、evidence-map（SHA `cba929923ec81780b251780b5630eeb5387974e0c649826cd255e98ae654d45c`）及validation（SHA `6bdd1d7b8eaa032be7176a694a56fe141524fb15717b708ef5cde81746493b2f`）绑定29份来源，已核对候选key。主控阅读主要章节并新增parent-review.md记录最终整合事项；不要原样发布素材里的审计者自述、过时运行进度或PENDING，不把准备稿当最终验收。最终正文需模型可读名称、中文类别、正式新增与四轮主表／图，详细账目放附录。无待接收子任务；原GPU66914／watcher46340仍存活，02:07:32新增复评932／3,168成功，02:07:41 i1-M第三轮新增470／1,200成功。

2026-10-07 02:04 UTC 接跑更新：原GPU66914／watcher46340复验存活，i1-M第三轮旧83、新增207／1,200首次成功，采样peak15,062／minfree916 MiB、shared84 MiB；新增复评869／3,168成功，尚无复评重试，完整性能11／16终态。最新快照 `formal-live-observations/quality-20261007T020407555453Z.json`、`observation-20261007T020416078359Z.json`。已委派paired_statistics独占新目录 `report-draft-preparation/integrated-report-v4/` 整合已审计的参考、工程／稳定性、旧质量和限制章节，只作待交付草稿；新增最终质量、四轮汇总及建议必须明确留空，待接收后主控审阅。不得把草稿当最终报告、重跑统计或调用额外评审。APEX第三轮resource-summary已读：4,486采样、worker_error=null，idle/released均602 MiB；全卡peak15,592／minfree386 MiB，load15,478／500。原始资源SHA绑定于apex-round3-completion投影。

2026-10-07 02:00 UTC APEX第三轮已completed：83＋1,200均首次成功、零失败／未执行／重试／OOM标记；旧墙钟59.436216秒，新增墙钟1,011.114874秒、p50/p95/p99为0.838866000006／0.985081764916／1.059086769059秒。加载6.714106300031秒，总会话1,121.830726600019秒，49／49 offload、cpu_offload_allowed=false，原server/worker均退出。投影 `formal-live-observations/apex-round3-completion.json` 绑定四源SHA；新增summary `1f13c0b0b5c7f3a95ff41ce35854f46da9c38e89659121710f3bcd67a4876cb3`、runtime `18a7b3dd9d5d049b38209540208420c5e3d7ea9b9b3dcdab8053acffddedbea2`。累计11／16性能终态（成功8、基线失败3），原GPU66914进入i1-M第三轮；原watcher46340继续，02:00:28新增复评794／3,168成功，尚无复评重试。用户另询问简短进度，已解释全量首轮机械检查100%、当时性能窗口位置约67%、复评约22%及剩余工作；这只是状态询问，未暂停或更改目标。

2026-10-07 01:52 UTC 接跑更新：原GPU66914／watcher46340均已再次轮询确认存活，未重启。性能10／16终态（成功7、基线失败3），APEX第三轮旧83完成、新增674／1,200首次成功，采样peak15,592／minfree386 MiB、shared84 MiB。新增fresh复评629／3,168成功，仍只有主评已记录的一次验证重试，没有新增复评重试。快照 `formal-live-observations/quality-20261007T015137545877Z.json`、`observation-20261007T015145396977Z.json`。所有已委派审计均完成，无待接收子任务；继续等待原队列和最终完整证据，勿重启或提前标记完成。

2026-10-07 01:46 UTC i1-L第三轮完整资源审计已接收并由主控核对：`formal-i1l-round3-terminal-resource-audit-v1/interpretation.json` 绑定summary SHA256 `1204381e4b9ccacf2a80e3daf326ca274c9a8bd4410e6ba63a918edbc06b8fe7`，matched-expanded-windows SHA256 `69570132e7ab8294a03b1de0433abc22c68bbc3ed9c7f57d9502259112b08100`。1,284次含warmup均首次成功，R1/R2全部对应prompt/token IDs／输入输出token数／有效参数／engine身份一致，早期110窗快照保持一致。新增第6、10–33、35共26窗解码率低于前两轮同窗中位数85%；连续10–33段129.286秒。第36至1200共1,165窗恢复，最低同窗倍率0.966924、median1.012457，shared仍固定430 MiB，故shared增长不等于持续降速／paging／OOM。新增整集墙钟相对前两轮均值仅+0.154599%。全卡峰值15,898／余量80 MiB；原owned进程退出后released602 MiB、相对idle548多54 MiB归属未知，下一APEX load晚于cleanup65.004秒，采样仅约2秒不能证明物理显存完全复原。无剩余子任务；原GPU66914／watcher46340继续运行，01:44:19新增复评478／3,168成功，01:44:26 APEX第三轮旧83、新增148成功。

2026-10-07 01:42 UTC 性能进展：i1-L第三轮已completed，旧83＋新增1,200均首次成功、无重试／未执行／OOM标记，49／49 offload、cpu_offload_allowed=false，原server/worker均退出（cleanup01:40:12.808679至01:40:15.388150 UTC；server_exit1为受控清理）。旧墙钟301.008826秒；新增墙钟5,246.743039秒、p50/p95/p99为4.344097149966／5.225875229947／5.756216976960秒；冷加载7.208123399992秒，总会话5,600.90020569996秒。投影 `formal-live-observations/i1l-round3-completion.json` 保存四源SHA，新增summary SHA为 `0b4e04ddea0745946342c81fcd82bd14fe5da9a590e8c9bbf77d739844202059`、runtime SHA为 `7c8f4a106f43fed5db687f7306b56449876ba4b9307894550de1598b23bcb2f2`。累计10／16终态（成功7、基线失败3），原GPU66914已进入APEX第三轮；01:41:31观测APEX旧3＋warm1已成功。主控已委派demo_integration独占 `formal-i1l-round3-terminal-resource-audit-v1/` 核对完整1200降速／恢复／资源释放，与前两轮及早期前缀比较，待接收结果；不能仅从完整中位数认定无尾部问题。原watcher46340仍存活，01:37:41新增复评341／3,168成功、无新增重试。

2026-10-07 01:31 UTC 交付准备审计已接收：`final-delivery-audit-readiness-v2/README.md` 已由主控阅读，`observation-02/{readiness.json,artifact-contracts-v2.json}` 保留全部最终要求并修正旧准备材料的v6入口，实际输出仍为formal*-v4。7份发布源pin一致，8项synthetic测试通过；此工具始终 `goal_complete=false/final_audit_performed=false`，仅证明准备检查，不代替逐项最终审计。后续性能全16终态后从contracts读取完整aggregator argv（三个engineering/formal attempt），再运行正式图／含性能表；术语两轨和quality-report-tables由watcher自动运行，不重复启动。当前无待接收子任务，原GPU66914／watcher46340已复验存活；01:30:27 i1-L第三轮新增1,076／1,200成功，仍9／16性能终态。后续应收取i1-L第三轮完整墙钟／资源／释放证据及新增复评终态，不改冻结源码和方案。

2026-10-07 01:26 UTC 主评／复评范围审计完成：`judge-probe/formal-expanded-primary-final-accounting-v1/report.md` 已由主控阅读，summary SHA256 `c0aac7ff3fa2ee991925c072f37a4b715221884dd7b72c6d76996410eae7532f`、report SHA256 `d294e039c93ff43b46c3cb121e1cb9798cd4c66ba373ca6ff613eb42984fc28b`。新增主评于01:17:27.702 UTC exit0；stage墙钟12,418.032秒、scheduler12,255.169秒、worker累计73,428.491秒，4,799job／4,800attempt，19,200证据哈希匹配终态记录。全部请求sol/high，返回身份未暴露，不能当成已验证返回身份。实际fresh复评3,168个唯一job、每候选792；每作品固定16／80共240窗，风险union704、重叠152、额外552，共792窗，不能缩回960次最低调用数。机械失败窗口未选复评，完整4,800分母保留。元数据审计首次意外打印一行nested candidate response/prompt的限制已透明记录；审计者不担任盲语义评审，未据此评分或改变输入／选样。按初期约20job/min仅复评约2.6小时，另加编排余量和未知裁决，不是完成承诺。GPU01:25:40时i1-L第三轮新增1,010／1,200成功；原66914／46340继续运行。另委派implementation_audit独占新目录 `final-delivery-audit-readiness-v2/` 核查交付清单及v6复现入口，待接收；不得提前将准备审计当最终验收。

2026-10-07 01:21 UTC 接跑更新：新增主评4,799个逻辑任务全部成功、4,800次尝试（仅一次已恢复的证据ID校验重试），完整候选窗口分母4,800仍含一个基线未交付窗口。主评已正式收尾，expanded-select-review于01:19:59.314832 UTC完成，expanded-review于01:20:04.704448 UTC运行PID50784，01:21:01已有19个复评成功。原watcher46340继续持有全局六CLI队列，不重复分发；已委派judge_throughput只读核算主评终态吞吐和实际复评选择，独占私有目录 `judge-probe/formal-expanded-primary-final-accounting-v1/`，待接收结果。GPU66914继续i1-L第三轮，旧83成功、新增947／1,200成功；性能9／16终态，历史资源峰值15,898 MiB／最低余量80 MiB／shared430 MiB。观测 `formal-live-observations/quality-20261007T012101333836Z.json`、`observation-20261007T012108087743Z.json`。复评、必要裁决、剩余性能及最终报告尚未完成。

2026-10-07 01:00 UTC 接跑更新：原GPU66914／watcher46340均复验存活，不重启。新增主评4,480／4,799成功、4,481次尝试，仍只有已记录的一次验证重试；新增fresh复评尚未开始。性能仍9／16终态（成功6、基线失败3），i1-L第三轮旧83成功、新增671／1,200成功，资源历史采样峰值15,898 MiB／最低余量80 MiB／shared430 MiB。观测 `formal-live-observations/quality-20261007T010018794591Z.json`、`observation-20261007T010025416680Z.json`。未变更冻结配方和源码；后续关注expanded-primary终态、自动复评选择及吞吐证据，不能因主评接近结束而省略复评／裁决。

2026-10-07 00:31 UTC 接跑更新：原GPU66914和watcher46340均再次确认存活，继续原队列。新增主评3,790／4,799成功、3,791次尝试，尚未进入新增复评；四轮性能仍9／16终态（成功6、基线输出上限失败3），i1-L第三轮旧83成功、新增271／1,200成功。资源采样峰值15,898 MiB／最低余量80 MiB、shared峰值430 MiB，未因降速干预配方。快照 `formal-live-observations/quality-20261007T003057742149Z.json`、`observation-20261007T003103708420Z.json`。早期资源审计已终结，无待接收子任务；其summary SHA256为 `831b99d554d38f94dd1cae3d13c4ea5eae27b6a8878c5cab504f6ec740b5e302`，snapshot SHA256为 `705a04b7ae347a7e59adf96d45494d0a0b25099a043262ccad248c54e19e3222`。不要重启已运行流程或将当前前缀观察替代终态证据。

2026-10-07 00:17 UTC 资源审计更新：`formal-i1l-round3-initial-resource-audit-v1/summary.json` 已完成并由主控阅读；证据截止00:14:51.730834 UTC，仅覆盖warmup1＋旧83＋新26，不能外推完整轮次。相同新增26窗墙钟中位数本轮5.2454秒、前两轮3.9288／3.9120秒，decode中位数26.7557／35.6483／35.7145 tokens/s。新增第6窗期间shared396→430 MiB、dedicated约降34 MiB；第7窗短暂恢复，第10窗起已观察17窗连续低于30 tokens/s。该前缀采样峰值15,898 MiB／最低余量80 MiB，前两轮对应前缀15,842／136；初始ambient本轮548 MiB、前两轮553 MiB。输入tokens、参数、输出token数、引擎身份及49／49 offload一致，均首次成功、无显式OOM；采样有效。共享分配与降速的时间关联不能证明物理paging、OOM或CPU fallback，未干预运行，后续仍需完整1200及释放终态审计。原66914／46340继续活跃，00:16:55新增主评3,485／4,799成功、3,486尝试。

2026-10-07 00:15 UTC 接跑更新：原 GPU66914／watcher46340 均复验存活，不重复分发。新增主评3,430／4,799成功、3,431次尝试，仍仅已记录的一次证据ID校验重试；完整候选窗口分母4,800不变。性能累计9／16终态，i1-L第三轮旧83已交付、新增24已交付；运行中采样峰值15,898 MiB、最低余量80 MiB、shared峰值450,887,680 bytes。此处不是终态或OOM证明。快照 `formal-live-observations/quality-20261007T001435701860Z.json`、`observation-20261007T001441823121Z.json`。已向 `/root/demo_integration` 委派第三轮早期资源与时延只读核查，仅写新目录 `formal-i1l-round3-initial-resource-audit-v1/`，不得修改冻结文件、启动额外推理／评审或读取质量语义；后续接跑需接收其结果。

2026-10-07 00:07 UTC 更新：基线第三轮已 failed终态，旧83成功、新增1,199成功＋1输出上限失败、not_run=0，两子进程均已退出。旧／新增墙钟55.828437／949.686508秒，新增p50／p95／p99为0.7781773001／0.9056657301／0.9809827470秒；一次重试4.9454023000秒，冷加载6.1570416000秒，49／49 offload、cpu_offload_allowed=false。新增phase峰值15,007 MiB／最低余量971 MiB，released峰值548 MiB（idle538 MiB）；无OOM标记。终态投影与四份源哈希 `formal-live-observations/baseline-round3-terminal.json`，失败整会话仍排除有效速度证据。累计9／16候选轮次终态（成功6、基线失败3），原GPU66914已进入i1-L第三轮；原watcher46340活跃，新增主评3,243／4,799成功、3,244次尝试。快照 `quality-20261007T000656982316Z.json`、`observation-20261007T000702472507Z.json` 均在 `formal-live-observations/`。

2026-10-07 00:01 UTC 更新：基线第三轮同一窗口 `H30-W06_E002-B0028` 再次两次达到1,024 output token上限；input533、stop_type=limit、truncated=false，窗口9.8881355000秒，第二次4.9454023000秒。原始窗口哈希 `46e09ccafedc9cc03d0badfba73368b3a8508897bba6ea522484fa9c5794f1c9`，投影 `formal-live-observations/baseline-round3-output-limit-failure.json`。保留失败／重试成本，不判OOM，不改配置或替换首轮质量输入。第三轮仍在继续其余窗口，不能提前标为终态；00:00:58观测旧83成功、新增804成功＋1失败，原GPU66914存活。原watcher46340同样存活，新增主评3,107成功／3,108次尝试，仍只有已记录的一次证据ID校验重试。

23:57 UTC 评审重试记录：新增主评首次出现额外尝试，`primary/c04/H30-W10_E007-B0042` 第一次CLI正常返回，但被校验器以 `source evidence is not in supplied IDs` 拒绝；第二次有界尝试成功，两次耗时21.8719519001／25.2930070000秒，无access_failure或tool_events，requested配置不变。原始两次响应保留在job目录，投影及job哈希 `formal-live-observations/expanded-primary-first-retry.json`。这是裁判证据ID验证重试，不是翻译失败或额度失败；样本数不增加。23:57观测新增主评3,007成功／3,008次尝试，完整目标仍4,799个主评任务、4,800候选窗口；基线第三轮新增530／1,200已成功，原66914／46340均存活。

23:54 UTC 审计更新：第二轮独立只读审计已完成并由主控阅读，15,580项检查全部通过，无新增阻断项，见 `formal-round2-terminal-audit-v1/findings.md`（SHA256 `c2d1a277a95f45945f3179d3481848e360faac6ca908e654bd39446c3247acaa`）、`audit.json`（SHA256 `722b8f096a69ddff20e7a146d9c6ac12d6456914d85407ec34f6505fd8597ff6`）。完整83＋1,200分母、冻结顺序、逐窗token与配方、12个相关源码并集、33个DLL身份、时序、清理和资源phase均一致；基线失败整会话继续排除有效速度证据。i1-M第二轮新集phase峰值15,024 MiB，高于runtime顶层15,012 MiB，汇总采用phase证据。审计未读取第三轮或质量语义。23:53观测原GPU66914／watcher46340仍活跃，基线第三轮旧83成功、新增270／1,200成功，新增主评2,931／4,799首次成功。

23:49 UTC 更新：APEX第二轮已 completed，83＋1,200全部首次成功，零失败／缺失／重试，旧／新增完整墙钟59.472434／1,000.753622秒，新增p50／p95／p99为0.8295387500／0.9702386750／1.0601889230秒，冷加载6.6674595999秒。49／49 offload、cpu_offload_allowed=false，两子进程已退出；采样峰值15,542 MiB／最低余量436 MiB，released538 MiB（idle553 MiB）。摘要及四份源哈希 `formal-live-observations/apex-round2-completion.json`。四款第二轮均已终结，累计8／16终态（成功6、基线输出上限失败2），原GPU66914进入基线第三轮。已向 `/root/comparison_harness` 委派第二轮独立只读审计，仅写 `formal-round2-terminal-audit-v1/`；不得读写第三轮或额外调用裁判／GPU。原watcher46340存活，23:48:42新增主评首次成功2,815／4,799。快照 `quality-20261006T234842786283Z.json`、`observation-20261006T234848077256Z.json` 均在 `formal-live-observations/`。

23:40 UTC 后处理调度核查：`formal-launch-manifest-v6.json` 的 `overlap.commands` 已包含两个分轨的术语诊断及 `quality-report-tables`，原watcher46340会在后续阶段自动执行；不能因目前报告目录尚不存在而手动重复分发。性能汇总、性能图及含性能的可选表格仍应在对应先决条件满足后检查实际产物再执行。原GPU66914／watcher46340本次均存活，APEX第二轮旧83已完成、新增659／1,200首次成功；新增主评2,615／4,799首次成功。快照 `formal-live-observations/quality-20261006T234022604867Z.json`、`observation-20261006T234027629200Z.json`。

23:30 UTC 更新：i1-L第二轮已 completed，旧83和新增1,200全部首次成功，零失败／缺失／重试，两个子进程均已退出。逐集墙钟303.053276／5,238.609568秒；新增逐窗p50／p95／p99为4.3452611000／5.1755698900／5.6766879060秒，冷加载7.1185004000秒。实际49／49 offload、cpu_offload_allowed=false；采样峰值15,842 MiB、最低余量136 MiB，released回到idle基准553 MiB。终态摘要及四份源文件SHA256已保存 `formal-live-observations/i1l-round2-completion.json`。性能终态现7／16（成功5、基线输出上限失败2），原GPU66914已进入APEX第二轮；原watcher46340仍存活，新增主评23:29:42观测首次成功2,351／4,799，尚未进入新增复评。最新快照 `quality-20261006T232942175195Z.json`、`observation-20261006T232946749429Z.json` 均在 `formal-live-observations/`。完整比较仍未完成，勿重复启动原流程或改动冻结配置。

23:04 UTC 接跑更新：原 GPU 会话66914和质量 watcher46340均已复验存活，继续原流程，不重复启动。新增集主评已首次成功1,737／4,799，expected候选窗口仍为4,800；尚未进入新增集fresh复评和裁决。四轮性能终态仍为6／16（成功4、基线输出上限失败2）；i1-L第二轮旧83全部首次成功、新增874／1,200首次成功，推理阶段采样峰值15,842 MiB、最低余量136 MiB、shared峰值396 MiB。此处是运行中观测，不能替代终态或视作OOM证据。证据为 `formal-live-observations/quality-20261006T230430910626Z.json` 和 `observation-20261006T230435851952Z.json`。冻结源码、输入与配方未改；完整四轮、新增评估和最终报告仍待完成。

22:34 UTC 接跑更新：原 GPU 会话66914和质量 watcher46340均在本次轮询中确认存活，不能重复启动。四轮性能共16个候选轮次，目前终态6个（成功4、基线失败2），i1-L第二轮正在运行：旧83全部首次成功、新增468／1,200首次成功；截至22:33:55采样峰值15,842 MiB、最低余量136 MiB、shared计数396 MiB，仍是阶段观测。新增主评已首次成功1,009／4,799，后续fresh复审和裁决尚未开始，expected候选窗口仍4,800。最新观察在 `formal-live-observations/quality-20261006T223351667901Z.json` 与 `observation-20261006T223355176121Z.json`。约30分钟新增主评吞吐检查已保存 `judge-probe/formal-expanded-primary-partial-throughput-v1.json`：700任务／1,793.959738秒，23.4119 jobs/min；线性剩余主评情景不含复审风险增量／裁决／重试，也不是额度或工期保证。所有冻结源码、方案和输入保持原样，最终交付尚未完成。

22:11 UTC 更新：旧集中文质量章节已生成并由主控阅读，待完整结果集成：`report-draft-preparation/regression-quality-fragment-v1/report-fragment-final.md`（SHA256 `6c05f3084d5e1b3e8d19a03a31a74ff5ccfb4ac6f0320de34aa990790dc0ce71`），同目录 `numeric-tables.json` 保存全精度表、`evidence-sha256.json` 绑定37份证据。章节覆盖15作品、2类别、6预指定配对、严重错误、共同覆盖与缺分界、复审和相同译文波动；未重跑裁判／bootstrap。六个主95%区间均包含零或触零，不支持从旧集宣称稳定优于基线，也不证明等效。不能替代待完成的新增集和四轮性能报告。22:10 UTC 原句柄66914／46340复验仍存活；新增主评472／4,799首次成功，i1-L第二轮新增129／1,200首次成功。

22:02 UTC 更新：旧集只读独立审计完成，主审 4,829 项、统计／错误分母 94 项、冻结评分资格 9 项均通过，见 `formal-regression-quality-audit-v1/completion.json`。口径澄清：305 是 scored 状态数；13 reference_suspect 和 13 source_ambiguous 仍有按冻结规则接受的语义终分，故有效语义终分为 331／332，唯一 null 是 c03 的 10-2-1，四候选共同语义覆盖 82／83。状态疑问不等于一概删除评分；完整分母和缺分界均保留。607 次调用的 requested 配置均为 gpt-6.1-sol/high，返回模型／effort 身份不可见，不能声称已核验返回身份。

基线第二轮已 failed 终结：旧集 83 成功，新增集 1,199 成功＋1 输出上限失败，not_run=0；完整终态证据 `formal-live-observations/baseline-round2-terminal.json`，该失败会话按冻结规则排除有效速度比较。22:00 UTC 观测 i1-L 第二轮正在执行旧集，新增主评已首次成功 248／4,799；原 GPU66914 与 watcher46340 均已复验存活，不得重复启动。以下保留此前阶段记录。

21:50 UTC 更新：旧集正式评估已 finalize exit0，完整 332 行＝305 scored＋13 reference_suspect＋14 source_ambiguous，无 unresolved／裁判调用缺失。332 主评、224 fresh 复评、51 裁决均首次成功；复评墙钟 660.9240774 秒、20.3352 jobs/min。旧集统计及相同译文诊断均 exit0，阶段观察 `formal-live-observations/regression-quality-final-stage-observation.json`；完整独立质量／缺分审计正在 `formal-regression-quality-audit-v1/` 进行。新增集主评于 21:50:29 UTC 启动，实际 4,799 jobs、expected 4,800 行；六 CLI 全局预算仍由原 watcher46340持有。

基线第二轮出现与首轮同一个 H30-W06_E002-B0028 窗口失败：两次均 input533／output1024、stop_type limit，窗口总耗时 9.9253178 秒；证据 `formal-live-observations/baseline-round2-output-limit-failure.json`。这是 output 上限失败，不是 OOM；保持配置、全分母与重试成本，不以该失败轮作更快证据。GPU 原会话66914继续其余窗口，不修补或替换首轮译文。

21:38 UTC 更新：正式旧集主评 332／332 全部首次成功，21:36:18 exit0；阶段墙钟 834.9373455 秒，实测 23.8581 jobs/min，证据 `judge-probe/formal-regression-primary-throughput-v1.json`。fresh 复评实际 224 个任务（每款 56），已于 21:36:30 启动，21:38 观测成功 31／224、无重试；新增集主评仍待旧集后续阶段。复评范围与更新的工作量情景见 `judge-probe/formal-regression-review-scope-v1.json`，不能以主评速率线性情景当 ETA／额度保证。

第二轮 i1-M 已 completed：83＋1,200 全部首次成功，墙钟分别 56.467682／943.037095 秒，冷加载 7.1300224 秒；49／49 offload，两进程已退出，采样峰值 15,024 MiB／最低余量 954 MiB，released 回到 553 MiB。摘要 `formal-live-observations/i1m-round2-completion.json`。66914 现执行基线第二轮，46340 正在旧集复评，两个原句柄均实际核验存活；不得重复启动。以下按时间保留此前阶段记录。

21:27 UTC 更新：首轮独立终态审计完成，`formal-round1-terminal-audit-v1/final-audit.json` 的 5,285 项检查通过，记录 15,488 份证据文件哈希，无新增阻断。审计核验所有首轮窗口输入／配方、覆盖、耐久终态时间、资源分阶段峰值和清理；基线 failed 会话的两个集合均按冻结策略排除有效速度比较。审计器最初 DLL map 键域不一致所致假失败及修正证明均保留，以 final-audit.json 为最终结果。正式旧集主评 122／332 已成功、122 次尝试；第二轮 i1-M 旧集 83／83、新增集 459／1,200 首次成功。66914 与 46340 均实际核验存活。

当前执行摘要（2026-10-06 21:22 UTC）：四款工程预检、各 30 分钟稳定性和 dev 语义评估已完成。新增参考 1,200 窗／6,000 个计分 IDs（15 部作品各 80 窗）已完成双轮复核／必要裁决并成功冻结，独立最终源审计通过。参考共审核 1,428 个不同窗口、3,187 次调用，均一次成功；最终质量样本只计 1,200。

21:22 UTC 活跃句柄复验：66914 推理和 46340 watcher 均仍存活。四款首轮已终结（三成功、一基线单窗失败），当前为 i1-M 第二轮，旧集 83／83、新增集 26／1,200 已首次成功。i1-L 首轮全 83＋1,200 首次成功，无 OOM／重试；旧集墙钟 304.201971 秒，新增集 5238.678711 秒，冷加载 7.1560041 秒，49／49 offload、两进程已退出。终态摘要见 `formal-live-observations/i1l-round1-completion.json`，资源摘要见 `i1l-round1-resource-summary.json`（采样峰值 15,846 MiB、最低空闲 132 MiB；不要以 runtime 顶层的不同采集值 15,842 替代）。独立首轮终态审计正在 `formal-round1-terminal-audit-v1/` 进行。

watcher 已于 21:19:59 UTC 完成四款首轮终态屏障，八份导出、旧集／新增集评估准备全部 exit0。旧集主评于 21:22:23 UTC 启动，21:25 UTC 已有 61／332 个 durable 成功任务，61 次尝试均请求 `gpt-6.1-sol/high`。旧集 expected／主评 jobs 均 332；新增集 expected 4,800、实际主评 jobs 4,799，基线未交付一窗仍保留完整分母、按交付失败处理。新增集主评尚未启动。以 `formal-quality-overlap-v4/stage-journal.jsonl` 为阶段事实源；不得重复启动两条流程或额外并发裁判。无正文观察器 `observe_quality.py` 读取递归的 `judge-execution/<phase>/<candidate>/<window>/job.json`，不可用单层 glob 误判无产出；首份摘要 `formal-live-observations/quality-20261006T212503088885Z.json`。最新 GPU 快照 `formal-live-observations/observation-20261006T212357762229Z.json`（第二轮 i1-M 新增集 185／1,200）。保持已冻结源码／配方和原运行目录，此前各时间点快照均保留。

正式四轮性能正在执行，实际 tool session **66914**；输出 `formal-performance-v4/`。APEX 第一轮已真实 completed：旧集 83／83、新增集 1,200／1,200，零失败／缺失／重试，实际 offload 49／49，原 server/worker 已退出。逐集墙钟分别 59.419309 秒和 1004.736047 秒，冷进程加载另计 7.1234115 秒；这里只是一款的一轮，不能作为四轮相对排名。i1-Q3_K_M 第一轮也已 completed：83＋1,200 均成功、无重试、49／49 offload，原进程已退出；完整计时见 `formal-live-observations/i1m-round1-completion.json`。基线第一轮已 failed 终态：旧集 83／83 成功，新增集全 1,200 已尝试，其中 1,199 成功、1 个 H30-W06_E002-B0028 两次均达到 1,024 output token 上限（不是 OOM 证据），合计一次重试；原进程已释放。旧集墙钟 55.85737 秒，新增集全覆盖含失败墙钟 950.745491 秒，后者不能当作完整成功运行的速度证据。详细证据 `formal-live-observations/baseline-round1-terminal.json`。i1-L 第一轮现已 completed，当前进入 **i1-Q3_K_M 第二轮**（详见顶部最新记录）。

质量 watcher 实际 tool session **46340** 仍存活，持有全局六 CLI 额度；四款第一轮终态屏障与八份导出已完成，正在准备正式评估，后续自动执行完整主评／fresh 复评／有界裁决。不得重复启动上述两条流程或额外并发裁判。先轮询真实句柄并核对 schedule-ledger；已有目录不代表已完成或可以重启。

正式 freeze SHA256 `819e918ced141c5f89203c1f317927b167d466cf7c9afcbf8ab4d5e58b95e559`，参考 freeze SHA256 `456b3828b3583bde36564d6f55ebaba58a46dd3b10f4cdf658c182b753d7708f`。启动入口为 `formal-launch-preparation/commands-v6.ps1`（SHA256 `f02653e1dda34a2a85cc881396875f08e0d27efefb59935a31d7722086e573ea`），含四预检／性能函数；当前两条长任务已启动，不再次调用。

参考 v1 LF／CRLF 与 v2 Windows 控制锁发布失败历史保留；两项最小修复已应用，宿主完整 196 项回归通过，三份 v2 未发布导出精确归档。成功 v3 tool36707 exit0，30,191 冻结文件及 19,947 项独立源检查通过。关键成功／审计入口：`corpus-boundary-fixes/post-review-execution-v3/completed-6736664a84be4f2baec92f7e50ccb6a1.json`、`corpus-audit/final-source-audit-preparation/final-source-audit-20261006T183745233032Z.json`。最新应用 manifest 的 `source_boundary` 描述 v3，继承的 `application_boundary` 为历史。

轻量实时观测入口 `observe_formal.py` 不输出字幕正文，按时间戳保存在 `formal-live-observations/`。APEX 首轮完整摘要为 `formal-live-observations/apex-round1-completion.json`。质量、剩余十二个未终结候选轮次、最终统计和中文报告尚未完成；当前 Q3_K_M 基线不变，goal active。

新增只读核查：`formal-failure-route-audit-v1/findings.md` 证明基线单窗输出上限失败不会阻断其他候选／轮次或 watcher；质量保留全分母，未交付窗口记 mechanical delivery_zero，不伪造 LLM 质量判断。有效速度汇总要求会话 completed 且 workload.failed=0；基线失败会话的两个集合均保守排除，缺少四轮成功基线时倍率保持 null，不把覆盖完成标志误当成功。

19:50 UTC，i1-L 第一轮旧集已交付 46／83，明显较慢；推理资源采样峰值 15,840 MiB、最低空闲 138 MiB、共享 GPU 峰值 415,236,096 bytes（约 396 MiB），尚无 OOM 证据。独立只读早期资源审计由 /root/demo_integration 进行，私有目录 `formal-i1l-initial-resource-audit-v1/`；不改冻结配方、不中断 GPU、不读参考或译文语义。两条长期会话仍为 66914 和 46340。

19:54 UTC 接续：i1-L 旧集 83／83 全部首次成功，阶段墙钟 304.201971 秒；新增集已交付 41／1,200，继续原全 GPU 配方。只读审计已完成于 `formal-i1l-initial-resource-audit-v1/initial-analysis.json`：审计范围仅首个 warmup＋前 55 个旧窗口，slow 从 warmup 起，输入 token IDs／有效参数与其他三款同窗一致、49／49 offload。共享分配约 396 MiB，不能据此断言物理迁移、CPU fallback 或 OOM；根因未确定。全量结果仍在生成，勿把这个初期审计当全量质量或性能结果。

权威范围见[执行方案](../plans/hy30-four-quantization-comparison.md)及[自动评估流程](../agents/subtitle-translation-evaluation.md)。本轮目录为 `.local/translation-evaluation/hy30-four-20261006/`，旧运行目录保持原样。

## 已核验事实

- 外部 v2 库只读复验通过：2,479 文件，无哈希变化及额外文件；证据为 `preflight/corpus-verification.json`。外部结构 validator 自测通过。
- 当前 GPU 为 RTX 5080，UUID `GPU-aae9a94b-6362-eac8-6328-a2733d553dca`，总显存 16,303 MiB，驱动 617.14。旧比较驱动为 616.92，本轮不复用旧性能或质量分数。
- 启动检查未发现运行中的 `llama-server`。后续必须重新检查实际进程，不能由本记录推断当前状态。
- 四款完整权重 SHA256 与 metadata 审计通过，证据 `assets/`。tokenizer／模板／架构一致；router bias 命名差异由兼容 loader 的既有别名分支支持。四款实际 GPU 兼容已通过下述统一预检。
- 独立扩集初始候选 1,200 窗／6,000 IDs、每作品 80 窗，另存 13,313 个不重叠候补。`corpus-audit/deterministic-audit.json` 独立核验源事件、日中映射、抽样顺序和旧集排除通过；无审核的 freeze 请求被正确拒绝。
- `judge-probe/` 四个 fresh Sol/high subagent 探针和 CLI 0.160.1 探针通过。CLI 六并发合成任务 16.83 秒、真实参考六窗口 55.92 秒，均无重试；微型探针不构成工期保证。真实速率线性外推含 20% 余量，最低 8,592 审阅任务约 26.69 小时，未含风险并集增量、裁决、候补、dev 及失败重试；后续以持续吞吐更新。
- 全量初审已完成：`experiments.translation_reference_judge`，`--phase primary --workers 6 --timeout 300`，shell session `61348` 已 exit 0，日志 `preflight/reference-primary-01.log`。不得重复分发已成功任务。
- 基线 `dev/smoke-baseline-01` 15/15、`dev/full-baseline-01` 41/41 交付；49/49 层 GPU，整卡采样峰值分别 15,479／15,477 MiB。这些为准备阶段证据，不代替正式四轮性能、质量或长期稳定性。
- 同一 `engineering-freeze-v1` 下四款统一工程预检已完成：每款预热 1＋smoke 15＋dev 41＋容量探针 1，共 58/58，无重试／OOM。`dev-audit/final-audit-summary.json` 独立核验 232 对 tokenize/completion、16 个 props 请求及四方输入／参数／源码／引擎身份一致。
- 四款统一 dev 墙钟依次为基线 27.510 秒、i1-M 27.579 秒、APEX 30.905 秒、i1-L 147.412 秒；对应 dev 整卡采样峰值／最低空闲为 15,294/684、15,294/684、15,581/397、15,863/115 MiB。49/49 层 GPU 日志均通过；共享内存计数可见，不仅凭慢或共享分配判 OOM／迁移。
- 工程长跑已完成：`engineering-stability-v1`，`--stage stability --resume-from engineering-preflight-v1`；shell session `14769` 已 exit 0，日志 `preflight/engineering-stability-v1.log`。每款至少 1,800 秒连续重复同一 dev 源窗，单独计数，不增加质量样本。
- 完整 dev 的 164 个匿名主评 packet 已准备于 `evaluation/dev-v1`，候选映射单独保存在 `candidate-alias-key.json`，不得送入裁判。
- 历史队列 `run_queued_review_stages.py`／session `97381` 已因 dev 路径误判退出；状态账本 `review-stage-pipeline-v1/ledger.jsonl` 保留原样，不再启动。单项恢复补齐主评，参考第二轮及后续 dev 使用新的独立启动器，见下文。
- 持续参考吞吐的 55 个新任务样本约 13.47 窗／分钟，含 20% 余量的双轮参考估算约 3.56 小时；最低整体审阅工作量借用同速率约 12.76 小时，后续候选评分速度仍须实测。共享周额度曾观测已用 93%，当时调用仍允许；`preflight/usage-observation-01.json` 保存时间与边界，不能由百分比换算任务余额。
- 初始新增参考双轮调用已完成，尚未完成意见协调、替补审核或最终冻结；正式 test／扩集推理及评分尚未开始。工程冻结不等于正式语料与配方冻结。

## 执行与恢复约束

1. 先核对实际目录、任务调用身份及 worker 状态，再恢复。已分发任务不得重复启动；原始响应必须先落盘，再登记成功。
2. GPU 由主协调者串行运行；参考构建者与盲评者不读取模型身份、性能或其他候选输出。独立评审显式使用 `gpt-6.1-sol / high / fork_turns=none`。
3. 扩集目标为 1,200 新窗口，与旧 83 窗口分开。参考双轮复核、必要裁决和源事件去重完成后才允许冻结模型输入并开展正式推理。
4. 保留加载、预热、逐窗时间、资源曲线和失败；不降低全 GPU 主轨设置，不因失败提前停止其他可执行工作。
5. 正式冻结文件 `freeze.json` 尚未生成；当前准备状态不代表阶段 C 完成。必需工作完成前不得把 goal 标记完成。

## 尚未完成

四轮正式推理、全量主评／盲复评／裁决、统计复核及最终中文报告。参考语义审核、dev 语义联调、资产完整哈希与 metadata 审计、四款完整 smoke/dev、各款至少 30 分钟稳定性已完成。

## 最新观测与待接续修复

2026-10-06 14:30 UTC，初审已成功 516 窗（含最初 6 窗探针），未见终态失败。后续以 `judge-probe/bulk-reference-monitor-latest.json` 和 `preflight/live-stage-status.json` 的时间戳为准；单轮 accept／edit／exclude 计数不代表最终可用参考。

正式冻结前需在活跃执行的安全边界补齐最终模型输入语言字段、裁决提示与非空解释校验，并复核最终选集。候补替换后仍要求每窗两轮 fresh 审核。拟议修补保存在 `corpus-boundary-fixes/`；额度熔断拟议修补保存在 `judge-circuitbreaker-design/`，未应用前不宣称已有能力。

性能汇总器及配对统计接受独立离线验证；新增文件尚须纳入正式冻结。当前工程冻结中的源码文件应保持原样，直到正在运行的稳定性任务结束。

2026-10-06 14:48 UTC，基线稳定性 session 已完成并卸载，调度器开始 i1-Q3_K_M。
基线固定源窗阶段 1,800.253 秒、2,003 次请求全部成功、无 OOM；后半／前半请求中位延迟比约 1.0051。
`engineering-aggregation-checkpoint-v2` 的读取开始于 session 最终落盘前，故其中顶层仍标 `started`、
`stability_passed:false`；这份进行中快照保留原样，四款终结后另建汇总目录，不覆盖它。

整合后的 156 项离线测试通过（`preflight/offline-integrated-02.log`）。性能汇总独立审计修复了缺失引擎成本
伪零和“满 30 分钟”与“稳定性通过”混淆，13 项模块与 8 项独立检查通过。
相同译文的独立评分差异诊断已实现，拒绝覆盖已有输出目录；最终正式冻结需显式包含该模块、性能汇总模块及测试。
正式命令草案位于 `formal-launch-preparation/`，加载 PowerShell 文件只定义函数，不自动运行。
候选裁判旧记录的恢复哈希补丁也尚未应用，见 `judge-circuitbreaker-design/candidate-integrity-design.md`。

三份待应用修补已在 `boundary-integration-validation/shadow/` 隔离副本合并，35 个 hunk 无冲突、
93 项离线检查通过；活动源码及现有冻结快照的字节不变。统一补丁是
`boundary-integration-validation/combined-ready.patch`，应用前必须核对该目录中的 base 哈希与安全步骤。
应用时必须确认所有活跃相关进程已终结，不能只凭旧状态或 lock 文件推断；最新句柄见下文及 preparation-state.json。
旧 dev 成功记录若缺首次接受时的响应哈希，仅能建立明确标记为“当前观察”的离线基线，不能补造历史身份。
新调度的非零退出可能包含熔断后的 `not_run`，后续新流水线须核对完整任务终态后再派发依赖阶段；
当前 `review-stage-pipeline-v1` 属于历史运行源码，保持原样。

正式启动准备已更新至 `formal-launch-preparation/formal-launch-manifest-v3.json` 与
`commands-v3.ps1`；旧修订保留。`check_ready_v2.py` 分别报告语料硬门槛、各候选工程终态和 dev 裁判限制，
仅显式、已有完整证据的终态失败可走对应继续路径，活动／未开始／缺证据仍阻止派发。

2026-10-06 15:17 UTC，初审全部 1,200／1,200 成功、零重试／终态失败，session 61348 已核对 exit 0。
首轮 697 接受、348 修改、155 排除，均待独立第二轮及必要裁决；不是最终通过／排除数。
完整调度摘要为 `corpus/hy30-expanded-v1/reference-execution/schedules/primary-2026-10-06T15-17-17.283867_00-00-summary.json`。
剔除六项早期探针后，1,194 项实际窗口耗时 4,973.63 秒，14.404 项／分钟；
不可变吞吐快照在 `judge-probe/reference-primary-complete.json`，费用未知。

队列于 15:17:35 UTC 开始完整 dev 的 164 项匿名主评。`monitor_dev_judges.py` 读取传输元数据，
分阶段维护 `judge-probe/dev-throughput-latest.json`；初期小样本速率仅供观测，待完整阶段后更新正式预算。
`monitor_stages.py` 区分当前选中窗口与全部历史参考判断，候补替换后不混淆样本分母。
i1-Q3_K_M 的固定源窗阶段于 15:19 UTC 完成 1,800.264 秒／2,041 次请求，全部成功、无 OOM；
后续以调度终态和进程卸载记录为准。

2026-10-06 15:45 UTC，旧队列 97381 已 exit 1：dev 子进程在 163／164 成功后因 Windows
并发目录创建触发路径比较误判而 exit 2，未启动后续参考复核。最小复现证实物理路径未越界，
但 `resolve()` 的 extended-length 前缀与普通根路径词法比较不一致；正式修复仍在隔离副本验证。
`dev-primary-recovery-one-v1` 用单 worker 仅补发从未调用的一项，91294 已 exit 0；此前 489 个
原始响应／规范化结果／账本文件 SHA256 全部未变。dev 主评现为 164／164 成功、零传输重试。
实际两次调用阶段合计 587.26 秒，16.756 项／分钟；另列约 760 秒诊断等待，不混入正常调用吞吐。
完整主评吞吐快照见 `judge-probe/dev-throughput-latest.json`。离线风险并集及作品分层抽样选中
30／41 窗，四款同窗合计 120 项必需盲复评，尚未调用。

独立参考第二轮已通过 `launch_reference_review_v2.py` 启动，shell session 28852，子进程 PID 69892，
六并发 fresh Sol/high；截至 15:44 UTC 已 203／1,200 成功，未终结。不能重复派发旧队列。
APEX 工程长跑同期仍运行，1,522 次成功、零失败／OOM；i1-L 尚待串行调度。
当前安全源码修改边界必须等待 14769 和 28852 真正终结；61348、97381、91294 已核对终态。
三补丁联合修订尚须加入路径修复后重新验证；原 combined-ready.patch 保留，不冒充最新版。
正式 v3 watcher 拟在四款第一轮全终态后封存并评分，GPU 后三轮串行继续；尚未执行。

15:56 UTC 接续：APEX 连续阶段已完成 1,800.498 秒／1,929 次请求，全部成功、无 OOM；
i1-L 已进入连续阶段，14769 尚未终结。参考第二轮 372／1,200 成功、零传输失败，
实测速率 14.40 项／分钟；`monitor_reference_review.py` 提供独立传输进度与 stdout 一致性观察。
修复的最新已完成联合版本为 `boundary-integration-validation/revision-v2/`，100 项检查通过；
该版本仍未应用，下一修订还将加入通用质量导出器的首轮恢复尾段隔离及统计输出拒绝覆盖保护。
正式 watcher 正常首轮快照已独立验证 332／4,800 完整分母；三项中断边界检查已修正，17 项测试通过，
最新准备身份须查 `formal-launch-preparation/` 的修订记录，不能沿用旧 hash。
dev 后续拟使用 `evaluation/dev-continuation-v2` 独立副本，仅执行 120 项必需复评及有界裁决；
尚未派发，启动器在准备目录中，正式 readiness 路径也需随之更新。不要恢复已失败的旧队列。

16:06 UTC：14769、28852 均已再次通过工具 handle 确认仍运行。i1-L 连续阶段 875 次成功、零失败；
参考第二轮已落盘 523 个响应，未终结。已有三款固定窗长跑不替代正式多样输入的四轮验证。
最终联合补丁已在 `boundary-integration-validation/revision-v3/` 完成 120 项私有组合检查，
SHA256 `2b98ea7445de5a96a57e08905ce16856cef8eb0b816359b7c2f6d2255e321f70`，尚未应用。
应用步骤以该版 `findings.md` 为准，必须先确认上述两会话与相关子进程排空，再保存源码原字节和校验。

只读进程身份捕获在 `preflight/live-owned-process-identities-01.json`，记录本实验 21 个实时进程的
PID／创建时间／父子关系。**工具 session ID 不是 Windows PID**；未执行的 dev 启动器曾有此检查错误，
已在私有准备版修正并增加回归。终态时须补充实际进程排空证据，不能只检查 14769／28852 同号 PID。
dev 与参考后续启动器正在共用本轮 `.judge-global-six.lock` 原生锁，后续六并发网络阶段严格串行。
`report-table-preparation/` 已交付隐私安全表格生成器，11 项合成测试通过；须纳入正式冻结。
正式准备在向 v4 更新，以引用独立 dev continuation 目录和源侧术语清单；待所有相关 agent 交付最终身份后才启动。

16:32 UTC：工程长跑 14769 已核验 exit 0，四款服务及 worker 均已退出、无 CPU offload。
独立完整聚合 95887 与绘图 40755 均 exit 0；`engineering-aggregation-complete-v1/` 保存 142 MB 原始汇总、
资源／窗口对齐 CSV、来源身份与 `stability-checkpoint.json`；`engineering-plots-complete-v1/` 保存八幅图与绘图身份。
绘图已修正为 exact attempt＋task＋candidate 对齐，旧脚本保存在 `plot-source-history/`，两项隔离测试通过。
基线与 i1-L 长跑图已进行视觉检查。工程聚合中的正式比较项尚无数据，不能作为正式性能结论。

四款基线／i1-M／APEX／i1-L 请求数为 2003／2041／1929／1782，合计 7755，全部首次成功、无明确 OOM；
各阶段时长为 1800.253／1800.264／1800.498／1803.131 秒。i1-L 最后第三段 p95 3.903 秒、p99 5.052 秒，
前段 p95 0.743 秒；同款输入 461、输出 103 tokens 不变。最低空闲显存 50 MiB，共享分配从约 340 升至 430 MiB。
这支持资源压力与降速的时间关联，不能直接证明 OOM／物理迁移。前后半中位数近似不变会掩盖末段问题，须报告尾部与曲线。

后续私有控制器已修正并独立核验异常路径的 Windows Job 子进程排空，以及已冻结语料恢复身份校验。
corpus 驱动当前 SHA `ceae15c1036faf68e8be63c4ad3f1ca6257de1dba264fcd22af4d73818042b1c`，命令见 `POST_REVIEW_COMMANDS.md`。
v4 发布身份在 `formal-launch-preparation/revision-v4-release-command-snapshot.json`；dev 启动器接受有证据的
成功有界裁决 `resolved=false` 为终态空分，不强迫解决或继续追加裁判。其余不完整传输仍阻断依赖阶段。
源码补丁尚未应用，唯一当前安全边界等待句柄为 28852；终态后还需真实 PID 排空与锁核验。


## 2026-10-06 17:16 UTC 参考协调阶段

初次机械协调已 exit 0，生成 273 个有界参考裁决任务；session 7479 正在串行六 worker 运行这些任务，尚未开始候补替换。参考账本写入的初始 `judge_failed` 且 `attempts=[]` 表示任务尚在执行，不能当作终态失败；以子步骤退出与实际 attempts 为准。不得启动第二份 driver。实际 dev 锁预约 ID 非空且 PID 48224 为正整数，acquired/released 一致，原生排空另见 `preflight/dev-continuation-v2-native-drain.json`。

dev 吞吐完整证据为 `judge-probe/dev-continuation-complete.json`：120 项复评 428.745 秒、29 项裁决 121.735 秒，均无额外 attempt。v5 门禁独立审计为 `formal-readiness-v5-independent-audit/findings.md`；正式 83＋1200 两套推理和 4 轮性能仍未启动。


## 2026-10-06 17:37 UTC 首批裁决及替补

Session **7479** 继续运行。首批 273 项参考裁决全部成功，协调后为 agreed 796、adjudicated 218、excluded 186；第一次替换补入 186 窗，shortfalls 为空。当前正在对这 186 个新窗口执行 primary，之后由同一 driver 执行 fresh review 及必要裁决／进一步补样。原始范围保存于 `audit/selected-before-replacement-0000.jsonl`、`audit/review-jobs-before-replacement-0000.jsonl`，替换账本为 `audit/replacements.jsonl`。`inference_allowed` 仍为 false。

报告私有工程章节草稿位于 `report-draft-preparation/engineering-results-draft-v2.md`，精确资产与引擎身份位于同目录 `exact-identity-appendix.md/json`。这些仅包含已完成工程结果，正式质量与四轮性能均为 PENDING；不能当作最终报告交付。


## 2026-10-06 17:44 UTC 已确认的未来冻结检查误拦截

替换 186 窗后的独立源审计完整通过，包括外部 v2 2,479 文件保持不变。发现 `prepare.py:388` 将 corpus 中实际执行的 CRLF 提示词哈希与原始 LF 源文件哈希直接比较，最终 freeze 会误报变化。归一化后字节完全一致，当前及既有审核的 actual prompt 指纹均正确。证据在 `corpus-audit/replacement-0000-readonly/findings.md`。

不要修改仍在 session7479 中运行的 45 份源码、提示词、manifest 或 driver。implementation_audit 正在 `boundary-integration-validation/reference-prompt-newline/` 准备严格 CRLF→LF 哈希等价修复与负向检查。优先等待当前 driver 自然停在最终 freeze，再核验进程／锁排空、应用实际项目修复并创建新的 applied manifest／post-review-execution-v2 状态；保留旧v1全过程。已审核成功窗口不重新派发。修复尚未应用，不能据此宣称最终参考已冻结。


## 2026-10-06 17:50 UTC 替补第二轮与未应用修复

186 个替补第一轮均首次成功，阶段 702.035 秒；第二轮在 17:48:41 UTC 启动，session7479 仍活动。精确任务文件在 `post-review-execution-v1/dispatch/`，不得另起审核。原生进程创建身份保存在 `preflight/reference-post-review-v1-live-process-identities.json`。

换行修复已封存为 `boundary-integration-validation/reference-prompt-newline/prompt-newline.unapplied.patch`，SHA `09dff84b9269cc62ad1c4166c05b135fb7c84f0aaaf11ed0159c59dd07e2e76b`，仅改 prepare.py 和对应测试，20 项私有测试通过。尚未应用。安全边界及 v2 ancestry 操作见同目录 `BOUNDARY_AND_RESUME.md`；prospective manifest 边界为 false，不得冒充已应用身份。必须保留最初2400审核证明与旧v1，新的v2完整门禁只能描述最终选集。


## 2026-10-06 18:05 UTC 第二批32窗口替补

首批186替补的双轮审核与46项必要裁决均完成；协调结果 agreed910、adjudicated258、excluded32。第二次替换0001补入32窗，shortfalls为空；同一session7479在18:04:50 UTC启动这32窗primary，之后继续fresh review及必要裁决。最终1200冻结仍未完成。累计替换记录与每代before snapshots均保留，不重复计作质量样本。

## 正式运行轻量观测

私有只读脚本 `.local/translation-evaluation/hy30-four-20261006/observe_formal.py` 汇总逐集已交付／失败／尝试数量和推理阶段显存采样边界，不输出字幕正文；每次写入新的 `formal-live-observations/observation-*.json`，不修改冻结或模型产物。它只证明观察时的文件进展，进程仍须通过实际 tool session 66914／46340 轮询确认。未完成轮次不得用于速度排名。










