# 文档发布后的离线复算与新实验入口

本入口保留原冻结身份和全部历史字节。隔离导入及合成校验已完成；后续真实旧／新统计各复算一次，四项完整输出均与原产物逐字节一致，详见末节。它没有重跑 GPU 或裁判。原实验的推理冻结为 `formal-freeze-v4/freeze.json`，SHA256 为 `819e918ced141c5f89203c1f317927b167d466cf7c9afcbf8ab4d5e58b95e559`。

`experiments/translation_four_quantization/__main__.py:98` 的 `verify_freeze()` 会校验 `source_sha256` 所列原绝对路径以及 `source_snapshots`。公开计划／评测文档更新后，旧 `run`、`export-quality` 和 v6 watcher 应拒绝执行。不要修改旧冻结清单、临时换回旧文档或忽略该错误。源码快照用于历史证据；旧推理冻结不能被宣称为文档更新后仍可原样执行的冻结。

## 已验证的离线入口

在项目根目录使用现有 Python 环境；下列路径均为本机真实路径。所有输出目录必须尚不存在。

```powershell
Set-Location -LiteralPath 'D:\AI_Projects\kototoki'
$pythonExe = 'D:\AI_Projects\kototoki\.venv\Scripts\python.exe'
$runRoot = 'D:\AI_Projects\kototoki\.local\translation-evaluation\hy30-four-20261006'
$replayHome = Join-Path $runRoot 'final-reproduction-entry-v1'
$replayScript = Join-Path $replayHome 'snapshot_replay.py'

# 可直接使用已封存的 capsule-04；probe 不读取候选译文或裁判内容。
& $pythonExe '-B' '-X' 'utf8' $replayScript 'replay' '--capsule' (Join-Path $replayHome 'capsule-04') '--action' 'probe' '--output' (Join-Path $replayHome 'user-probe-01')
if ($LASTEXITCODE -ne 0) { throw 'Snapshot import verification failed' }

# 27 项冻结测试，仅使用合成数据；包含更新公开文档后的严格拒绝测试。
& $pythonExe '-B' '-X' 'utf8' $replayScript 'replay' '--capsule' (Join-Path $replayHome 'capsule-04') '--action' 'selftest' '--output' (Join-Path $replayHome 'user-selftest-01')
if ($LASTEXITCODE -ne 0) { throw 'Offline synthetic validation failed' }
```

如需新的导入副本，执行以下命令；它仅复制快照中的源码／文档，不复制语料或模型。每个副本拥有自己的 `replay-binding.json` 身份，绝不称为原推理冻结。

```powershell
& $pythonExe '-B' '-X' 'utf8' $replayScript 'prepare' '--freeze' (Join-Path $runRoot 'formal-freeze-v4\freeze.json') '--output' (Join-Path $replayHome 'user-capsule-01')
if ($LASTEXITCODE -ne 0) { throw 'Historical snapshot validation failed' }
```

`prepare` 校验全部 174 个历史快照，复制其中 49 个项目源码／文档文件。子进程使用 `-I -S -B`，项目模块只能从已绑定副本导入，禁止网络和进一步子进程启动。每次执行重新检查原冻结字节、全部历史快照与副本，并在 `execution-proof.json` 记录实际导入文件、原路径、快照路径和 SHA256。Python 版本／可执行文件哈希记录在副本清单中；这不代表已冻结整个操作系统或 Python 标准库。

## 真实已审计数据的复算命令

下面是读取已完成评测数据的离线命令。旧／新统计已由后续真实验证执行，性能复算仍只是入口，不宣称已经执行。输出都是新目录。统计程序采用原配置中的全分母、基线、series 和固定 bootstrap 设置；性能程序保留原 attempt／freeze 的绝对路径，校验记录配置全部输入哈希（执行前后）以及原账本的不可变产物哈希。

```powershell
& $pythonExe '-B' '-X' 'utf8' $replayScript 'replay' '--capsule' (Join-Path $replayHome 'capsule-04') '--action' 'statistics' '--config' (Join-Path $runRoot 'report\formal-regression-statistics-v4\statistics-config.json') '--output' (Join-Path $replayHome 'recompute-regression-01')
if ($LASTEXITCODE -ne 0) { throw 'Regression recomputation failed' }

& $pythonExe '-B' '-X' 'utf8' $replayScript 'replay' '--capsule' (Join-Path $replayHome 'capsule-04') '--action' 'statistics' '--config' (Join-Path $runRoot 'report\formal-expanded-statistics-v4\statistics-config.json') '--output' (Join-Path $replayHome 'recompute-expanded-01')
if ($LASTEXITCODE -ne 0) { throw 'Expanded recomputation failed' }

& $pythonExe '-B' '-X' 'utf8' $replayScript 'replay' '--capsule' (Join-Path $replayHome 'capsule-04') '--action' 'performance' '--config' (Join-Path $runRoot 'report\formal-performance-v4\source-config-snapshot.json') '--output' (Join-Path $replayHome 'recompute-performance-28runs-01')
if ($LASTEXITCODE -ne 0) { throw 'Performance recomputation failed' }
```

最后一个配置只复算原 28 个运行（含其 engineering 历史）；它不包含后来单独运行的 `formal-stability-completion-v4`。要复算含正式压力补跑的最终汇总，应使用最终汇总自己封存的 `source-config-snapshot.json`，保持其中完整 attempts 列表，不向旧配置偷偷添加路径。执行源码哈希不一致或输入变动都会拒绝；无法满足时需要新的复算身份和明确差异说明。

离线复算调用现有统计／性能 CLI；这两个数据消费者不调用推理门禁。原门禁保持严格且没有被绕过用于推理。比较重新生成报告的数值、覆盖率、分母与声明范围；时间戳、源码副本路径及复算身份发生变化，因此不保证所有输出文件逐字节相同。此入口不重新生成裁判意见、术语诊断、图表或人工表格；那些产物的原配置、执行源码和审计证据仍按各自交付清单保留。它也不是跨机器可移植的完整实验包：原语料／attempt 的绝对路径必须仍可读，否则明确拒绝。

## 将来重新进行 GPU 推理：新冻结、新运行身份

以下为现有 CLI 支持的未来命令模板，**此模板不是新的已执行 GPU 结果，须核验没有 GPU 会话或原生子进程占用，并遵循当时有效的任务授权与权限规则**。它保持旧输入、模型、engine、DLL、recipe 的内容身份，冻结发布后的公开文档到新的快照。旧结果不作为新运行历史，也不取代新结果。输入使用旧冻结的 `source-inputs` 副本，因此不依赖原输入库路径的文档状态。

```powershell
# 沿用上一节的 $pythonExe / $runRoot；从项目根目录调用现有 CLI。
$oldFreezePath = Join-Path $runRoot 'formal-freeze-v4\freeze.json'
$oldFreeze = Get-Content -LiteralPath $oldFreezePath -Raw | ConvertFrom-Json
$freshRoot = Join-Path $runRoot 'fresh-reproduction-after-doc-publication-v1'
if (Test-Path -LiteralPath $freshRoot) { throw 'Use a new empty reproduction identity' }

# 同一算法复跑前要求所有历史 Python 源码仍是原字节；文档允许发布后改变。
foreach ($entry in $oldFreeze.source_sha256.PSObject.Properties) {
  if ([IO.Path]::GetExtension($entry.Name) -eq '.py' -and (Get-FileHash -LiteralPath $entry.Name -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) { throw "Python source changed: $($entry.Name)" }
}
$freezeArgs = @('-B','-X','utf8','-m','experiments.translation_four_quantization','freeze',
  '--smoke',$oldFreeze.inputs.smoke.path,'--dev',$oldFreeze.inputs.dev.path,
  '--regression',$oldFreeze.inputs.regression.path,'--expanded',$oldFreeze.inputs.expanded.path,
  '--expanded-corpus-freeze',$oldFreeze.expanded_corpus_gate.path,
  '--engine',$oldFreeze.engine,'--engine-identity',$oldFreeze.engine_identity,
  '--output-dir',(Join-Path $freshRoot 'freeze'))
foreach ($entry in $oldFreeze.asset_manifests) { $freezeArgs += @('--asset-manifest',$entry.path) }
foreach ($entry in $oldFreeze.source_sha256.PSObject.Properties) { $freezeArgs += @('--freeze-file',$entry.Name) }
& $pythonExe @freezeArgs
if ($LASTEXITCODE -ne 0) { throw 'New freeze refused; retain partial evidence' }

$newFreezePath = Join-Path $freshRoot 'freeze\freeze.json'
$newFreeze = Get-Content -LiteralPath $newFreezePath -Raw | ConvertFrom-Json
foreach ($name in @('smoke','dev','regression','expanded')) {
  if ($newFreeze.inputs.$name.sha256 -ne $oldFreeze.inputs.$name.sha256) { throw "New input content differs: $name" }
}
foreach ($name in @('engine_sha256','engine_identity_sha256','candidate_ids','assets','recipe','dll_sha256','asset_manifests','rotation','stability_seconds','pollution_criteria')) {
  if (($newFreeze.$name | ConvertTo-Json -Depth 50 -Compress) -ne ($oldFreeze.$name | ConvertTo-Json -Depth 50 -Compress)) { throw "New technical identity differs: $name" }
}
if ((Get-FileHash -LiteralPath $newFreezePath -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $oldFreezePath -Algorithm SHA256).Hash) { throw 'New identity was not created' }

# 新的 all 阶段从头执行 preflight + 四轮 performance + 四个 stability；不带旧 --resume-from。
& $pythonExe '-B' '-X' 'utf8' '-m' 'experiments.translation_four_quantization' 'run' '--freeze' $newFreezePath '--stage' 'all' '--output-dir' (Join-Path $freshRoot 'gpu-attempt') '--port' '8080'
if ($LASTEXITCODE -ne 0) { throw 'New attempt incomplete; preserve failures and use its own immutable recovery lineage' }
```

新冻结的时间戳、输入副本路径、来源文档哈希和最终 SHA256 会不同；这是声明的新身份，不能冒充 `819e918c…`。新冻结后再次修改被绑定的文件仍会被严格拒绝。源码或模型有变化时，上面的“同一技术身份”模板应拒绝，不应为了让它通过而删掉校验。

该 GPU 命令重新执行翻译、性能与稳定性，不自动重新评价翻译质量。完整新质量实验仍需新 alias／首轮质量导出、新 expected inventory、新独立裁判／复审／仲裁目录、共享全局六 worker 锁及新的发布门禁。旧 `watch_round1_v6.py` 与旧 launch manifest 固定绑定原路径、原冻结和阶段证明，不能直接换一个参数冒充通用新实验入口。本交付不声称原 sealed GPU＋judge 全流水线能够在公开文档演进后原身份精确重放；其源码快照、原账本、原输入、裁判调用 provenance 和最终审计保持可查。新完整质量流水线必须按当时评测工作流准备新的 launch 身份，再运行独立审计。

## 验证证据与边界

权威验证为 [合成执行证明](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/final-reproduction-entry-v1/validation-04/execution-proof.json) 和 [边界验证](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/final-reproduction-entry-v1/adversarial-validation-02/validation.json)：27 项冻结合成测试通过；修改合成绝对路径文档、导入未绑定模块、篡改源码副本、修改清单以接受篡改源码、声明错误历史快照这五种情况均拒绝。16 个实际项目模块的导入路径／哈希均绑定冻结源码，49 个原项目文件以及原冻结＋174 个历史快照在测试前后字节不变。下述验证目录及 `capsule-04` 均位于前文定义的 `$replayHome`，不相对于本公开文档目录。`validation-01` 保留最初夹具语言字段缺失的失败；旧副本和 helper 前像保留，最终可用版本为 `capsule-04`。

这一证明不等于最终实验通过，也不覆盖新 GPU 推理或新裁判调用。更新公开 docs/INDEX、计划和评测指南时，可以链接本文件作为可用离线入口，并将旧运行命令标注为历史 provenance。

## 已完成的真实统计复算

实际执行了 `capsule-04` 的两次离线统计复算。独立只读验证已通过：regression 与 expanded 各自的 **完整 summary.json、report.md、statistics-config.json、执行源码副本这四个产物均与原产物逐字节一致**；两个 JSON 产物也分别进行完整解析值比较，没有只挑选部分指标。

| 范围 | 新产物目录 | 完整 summary SHA256 | 结果 |
| --- | --- | --- | --- |
| regression | [实际复算目录](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/final-reproduction-entry-v1/parent-recompute-regression-01/result/) | `2d3b128f33c8e7c82f22c31bd49a972156fef9600764d2f86b390a5894084beb` | 全字节／全 JSON 一致 |
| expanded | [实际复算目录](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/final-reproduction-entry-v1/parent-recompute-expanded-01/result/) | `b4e46e31d897ee1580571ad2937fec1ff7aa4f5c19694ebd02da4b523e180412` | 全字节／全 JSON 一致 |

两次 launcher 均记录 exit 0，执行 action 为 `statistics`；实际使用 `-I -S -B`，Python 3.12.15 的可执行文件哈希与副本清单一致。每次 12 个实际项目模块／命名空间全部位于隔离目录，其源码字节与原冻结快照一致；实际执行统计源码 SHA256 为 `9961059f5ea7a10317e0826f02b55b0504195aad1da635e7a3b520599b02a6e5`。两套共 12 条输入哈希记录与原配置／原 summary／重算 summary 一致。配置中的 bootstrap、基线和共享 series 未改变。具体输入、导入来源、完整输出哈希与 launcher／execution proof 哈希均列于 [真实复算验证](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/final-reproduction-entry-v1/parent-real-replay-verification-v1/verification.json>)。

原 [历史入口](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/final-reproduction-entry-v1/README.md>) 及 [原封存清单](<D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/final-reproduction-entry-v1/FINAL-SEAL.json>) 中“尚未执行真实复算”的表述准确描述当时状态；**从本补充的后续验证起，两套真实统计复算已完成并验证一致**。本补充更新该时间性状态，保留原文件及其封存身份。原 seal SHA256 仍为 `f7324170f8d800f207092850957c7b130871d0b5702266fb3bfbd20be1637f9a`，其中 388 个文件已重新校验全部不变。

上述补充没有重新运行任何 producer，没有读取活动 GPU，也没有启动 GPU／裁判／网络或新增质量样本。它不同于先前 27 项合成测试：这里核对实际已完成评测数据及实际输出。该历史补充形成时尚未更新公开文档；随后发布后的实际复算见下段。性能汇总、术语诊断、图表、人工表格及全新 GPU＋judge 实验没有在该补充中重算或验证。

公开报告及相关方案／评测／流程文档实际修改后，主控又按同一隔离入口复算了一次新增集统计，实际 exit 0（tool chunk `fd5f80`），12 个项目导入绑定历史快照；完整四个输出文件再次与原产物逐字节相同，summary SHA 仍为 `b4e46e31d897ee1580571ad2937fec1ff7aa4f5c19694ebd02da4b523e180412`。这验证了当前公开文档变更后的离线统计入口，不是新的翻译或评分。见[执行证明](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/final-reproduction-entry-v1/parent-postpublication-expanded-01/execution-proof.json)和[完整文件比较](D:/AI_Projects/kototoki/.local/translation-evaluation/hy30-four-20261006/final-reproduction-entry-v1/parent-postpublication-expanded-01/parent-postpublication-comparison.json)。


## 已验证缓存环境中的离线绘图

绘图缓存环境为 Python 3.12.15、matplotlib 3.11.2、numpy 2.5.3。以下只重排已有资源数据，输出路径须不存在；它不运行模型或统计 bootstrap，绘图器将 MPLCONFIGDIR 写在新输出目录内，不写用户缓存。

```powershell
Set-Location -LiteralPath 'D:/AI_Projects/kototoki'
& 'D:/AI_Projects/kototoki/.local/cache/root-uv/archive-v0/uj2yqvDB3GlcC1VJD6DxQ/Scripts/python.exe' `
  -B -X utf8 '.local/translation-evaluation/hy30-four-20261006/plot_performance.py' `
  --input '.local/translation-evaluation/hy30-four-20261006/report/formal-stability-completion-v4' `
  --output '.local/translation-evaluation/hy30-four-20261006/report/user-stability-plots-01' `
  --label '正式冻结稳定性与继承预检资源观测'
if ($LASTEXITCODE -ne 0) { throw 'Plot rendering failed; preserve output history and select a fresh output identity' }
```

绘图器 SHA256 为 14c9cec90cf104565cf1c42fa22c4d1f866706f595b1b7c7959ef4867628342c。缓存环境及实际调用身份见本机 runtime-addendum-v1.json；本公开命令使用新目录，不重用原图目录。配对质量图直接发布已封存 v2 PNG／SVG，不把原固定输出脚本当可覆盖历史的通用命令。
