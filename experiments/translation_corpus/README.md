# 新增字幕窗口与参考复核

本模块从只读外部 v2 库创建独立 `hy30-expanded-v1` 候选语料，服务于
[四量化对比方案](../../docs/plans/hy30-four-quantization-comparison.md)。
只处理语料，不执行候选模型推理。新语料经过复核前不能称为正式参考。

从仓库根目录使用 uv 项目 Python：

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_corpus prepare `
  --corpus 'D:/subtitle-samples/翻译模型评估库_v2' `
  --output '.local/translation-evaluation/<run-id>/corpus/hy30-expanded-v1'
```

输出目录必须是新目录。源库不写入；字幕、参考、复核响应全部留在忽略目录。
`staging/selected-candidates.jsonl` 是待审候选，`staging/reserve-candidates.jsonl`
是冻结候补顺序；不能送给翻译模型。`review-packets/` 只含最终允许的七条日文
上下文和中间五条待审中文。前后上下文中文不提供；不读取模型输出。

抽样先以固定 seed 的随机起点划分互不重叠的七单元块，再做概率抽样。
剧集排除旧 dev/test 的整集，按季和集序分八个连续位置层，每层随机一集、
每集随机十窗。电影按对白配对进度十等分、每层随机八窗。
所有窗口及候补的全部日中源事件均检查不重叠；电影旧上下文和既有隔离窗口
源事件也排除，天气之子继续整片隔离。配对只依赖明确语言轨和唯一同起点，
并要求两侧 SRT 源序号连续；这只是机械候选，语义由双轮复核判断。

`audit/strata.json` 保存抽样框和同层顺序，`audit/exclusions.jsonl` 保存机械
拒绝理由，`audit/overlap.json` 保存全 context 检查。概率针对机械合格的块框，
不代表所有可能滑动窗口的概率；复核后筛选会改变可用场景范围，必须报告拒绝率。

调度器按 `review-jobs.jsonl` 执行，每条 job 用独立 `gpt-6.1-sol / high`
请求和 `reference-review-prompt.md`。primary 和 review 都读相同原始 packet，
第二轮不能看第一轮。`validate_review(row,result)` 校验响应及修改追溯。
同模型双轮不是人工金标准或不同模型家族的独立验证。

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_corpus reconcile --output '<corpus-output>'
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_corpus replace-excluded --output '<corpus-output>'
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_corpus freeze --output '<corpus-output>'
& '.venv/Scripts/python.exe' -X utf8 -m unittest tests.test_translation_corpus -v
```

`reconcile` 保存逐窗终态，分歧写入 `adjudication-jobs.jsonl`，仅允许一次有界
裁决。裁决使用独立的 `reference-adjudication-prompt.md`，明确允许阅读匿名意见；
primary/review 原提示词及组装字节保持不变。裁决理由不能为空，未决必须隔离。
`replace-excluded` 严格按同层候补顺序替换隔离窗口，
先同集、耗尽后才用同作品同层预定额外集；新窗口仍须两轮独立复核。
所有旧决定和替换历史保留，候补耗尽会明确报告短缺。

`freeze` 要求全部 1,200 窗口、每作品 80 窗均已双轮接受或经裁决解决，并核验
每次请求的 Sol/high/fresh 证据、原始响应和最终响应哈希。任一缺失会阻止发布
最终输入。冻结和补样前核对当前完整窗口、packet 与原抽样框一致，
禁止通过改写 staging 或已冻结语料改变来源。最终输入明确声明 `ja` 到 `zh-Hans`
的五字段 demo 契约。`freeze-manifest.json` 是成功发布标记，绑定
`model-input/expanded.jsonl`、`reference/expanded.jsonl`、来源清单及全部实质证据。
后段失败可能留下尚未发布的导出文件；先核验进程与锁已释放、保存精确哈希并将这些
中间产物归档到语料目录外，再以新执行身份重试，不覆盖既有产物。根目录的
`.reference-orchestration.lock` 和 `.judge-scheduler.lock` 是瞬态控制文件，明确记录为
排除项；其他文件的读取或哈希失败仍阻止发布。最终输入只有日文 context
和 translate_ids，不带中文、复核意见或风险标签。

执行证据由独立参考裁判运输器写入
`reference-execution/<phase>/<window_id>/job.json`。程序验证结构、ID、哈希和
修改引用，无法证明复核推理正确；参考和源字幕仍有文本审阅的限制。

初始 `builder-snapshot/` 保留原字节；最终代码另存
`final-freeze-snapshots/<完整内容身份 SHA256>/`，已有内容身份目录不覆盖。
冻结清单包含初始与最终快照的路径和哈希，便于区分抽样阶段与最终冻结阶段。
# 第二轮长源片段参考

第二轮96筛选＋48确认使用独立版本，不更改下方历史1200窗冻结要求。
源文入口为`python -m experiments.translation_corpus.flow_v2_source --help`，
源manifest、日文scene、候补顺序与评分位置分别冻结，确认语义封存在评估目录。
`flow_v2_reference.py`按显式配额准备、双轮复核、裁决与候补并发布新参考身份；
沿用独立Sol/high请求及原始／canonical哈希证据，不将参考传入翻译准备。
源冻结不代表参考通过，当前资格与拒绝率以[第二轮台账](../../docs/context/2026-10-08-hy30-flow-exploration-v2.md)为准。

`python -m experiments.translation_corpus.flow_v2_qualified --help`将最终参考资格的元数据发布为
新的源文合格版本；仅接收已接受ID与候补链，scene日文字节不变，原源freeze不覆盖。
参考或确认语义不进入源文负责人或翻译器，合格标记仍不等于候选质量通过。
默认发布`screening`的96窗，`--role confirmation`独立发布48个代表性确认窗，
同样核验角色、候补顺序和scene字节；确认角色不复制筛选校准窗。
实际确认发布仍须等最终候选统一锁定，不能因代码支持就提前开启封存确认。
