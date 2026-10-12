# 本地翻译模型资产与复用入口

状态：九个 GGUF 获取完成（原六个＋Hy30 APEX-I-Compact、i1-Q3_K_L、i1-Q3_K_M）；字节数与完整 SHA256 均已核验通过。  
最后更新：2026-10-07。
范围：使用 `hf download` 获取的九个本地翻译模型资产，供后续实验复用；资产获取不代表推理、GPU兼容或翻译质量已验证。

## 后续 session 从这里开始

当前字幕翻译基线已采纳 **Hy-MT2 30B-A3B APEX-I-Compact**（`hy-mt2-30b-a3b-apex-i-compact`），见[ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md)；运行须使用[demo 中的显式兼容引擎命令](../../experiments/translation_demo/README.md)，APEX 的资产记录位于下方新增三款清单。此前 Q3_K_M 与其他资产继续保留为对照，历史决定见[ADR-0004](../adr/0004-hy-mt2-translation-baseline.md)。

模型目录：`D:/AI_Projects/kototoki/.local/models/translation/`。运行前读取
原六个资产的 `D:/AI_Projects/kototoki/.local/manifests/translation-download-plan.json`；新增三个量化候选读取
`D:/AI_Projects/kototoki/.local/manifests/hy30-shortlist-downloads.json`。确认目标条目为
`status: verified`，再使用该条目的 `directory` 与 `file`。不要仅凭文件存在判断下载完成。

`.local/` 已被 Git 忽略，包含权重、HF缓存、下载元数据和机器可读清单；本文及
[文档索引](../INDEX.md)提供长期检索入口。仓库迁移后需同步迁移模型目录或重新获取，不能认为 Git 会保存权重。

## 固定文件与身份

| 模型／精度 | 本地子目录与文件 | 发布仓库 | 字节数 |
| --- | --- | --- | ---: |
| Hy-MT2-7B Q8_0 | `hy-mt2-7b-q8/HY-MT2-7B-Q8_0.gguf` | [腾讯官方](https://huggingface.co/tencent/Hy-MT2-7B-GGUF) | 7,981,928,896 |
| Tower-Plus-9B Q8_0 | `tower-plus-9b-q8/Tower-Plus-9B.Q8_0.gguf` | [mradermacher 社区转换](https://huggingface.co/mradermacher/Tower-Plus-9B-GGUF) | 9,827,149,344 |
| TranslateGemma-12B Q8_0 | `translategemma-12b-q8/translategemma-12b-it-Q8_0.gguf` | [bullerwins 社区转换](https://huggingface.co/bullerwins/translategemma-12b-it-GGUF) | 12,510,227,904 |
| Hy-MT2-30B-A3B Q3_K_M | `hy-mt2-30b-a3b-q3-k-m/Hy-MT2-30B-A3B-Q3_K_M.gguf` | [GrahLnn 社区转换](https://huggingface.co/GrahLnn/Hy-MT2-30B-A3B-4bit-GGUF) | 14,446,329,888 |
| TranslateGemma-27B Q3_K_L | `translategemma-27b-q3-k-l/translategemma-27b-it-Q3_K_L.gguf` | [bullerwins 社区转换](https://huggingface.co/bullerwins/translategemma-27b-it-GGUF) | 14,543,477,408 |
| Hy-MT2-30B-A3B 官方 Q4_K_M | `hy-mt2-30b-a3b-q4-k-m-official/Hy-MT2-30B-A3B-Q4_K_M.gguf` | [腾讯官方](https://huggingface.co/tencent/Hy-MT2-30B-A3B-GGUF) | 18,236,702,880 |
| Hy-MT2-30B-A3B APEX-I-Compact | `hy-mt2-30b-a3b-apex-i-compact/Hy-MT2-30B-A3B-APEX-I-Compact.gguf` | [alphaZimuth 混合量化](https://huggingface.co/alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF) | 15,035,838,080 |
| Hy-MT2-30B-A3B i1-Q3_K_L | `hy-mt2-30b-a3b-i1-q3-k-l/Hy-MT2-30B-A3B.i1-Q3_K_L.gguf` | [mradermacher imatrix](https://huggingface.co/mradermacher/Hy-MT2-30B-A3B-i1-GGUF) | 15,644,000,768 |
| Hy-MT2-30B-A3B i1-Q3_K_M | `hy-mt2-30b-a3b-i1-q3-k-m/Hy-MT2-30B-A3B.i1-Q3_K_M.gguf` | [mradermacher imatrix](https://huggingface.co/mradermacher/Hy-MT2-30B-A3B-i1-GGUF) | 14,446,330,368 |

以上路径相对于模型根目录；九份合计 122,671,985,536 bytes，约 122.67 GB。新增三份合计 45,126,169,216 bytes，约 45.13 GB／42.03 GiB。

| 模型 | 固定发布 revision | 上游 SHA256，下载后须与本地一致 |
| --- | --- | --- |
| Hy-MT2-7B | `ab8472660ac61fac25f1af43fac2599d52a8a775` | `58b3ad55dd6f6fa08c695cddc34fb5f8f708a844f78ae10508071914b0ed67c0` |
| Tower-Plus-9B | `79d27e5fb80c9feb4eb7b29c2469cdcb49b01b0c` | `715482435090af7e4cc84d3caf9503793779d95db7ee4b41293171ff7ca136de` |
| TranslateGemma-12B | `d7d1d8cc4ff53d4bc883ef33eae3894f07833b63` | `a1c57a783142858a6c992739793692cf9afbaaf738aa0993ada93fa9472ecbe1` |
| Hy-MT2-30B-A3B 社区 Q3_K_M | `4ae7787177f6d4f2d54ec2d543d9fe5f9114d1c9` | `9398dedb6f783963f0e9b7fc6ecb16a0158a92aa9a4c0a25eab29ba9704c19d5` |
| TranslateGemma-27B | `648ab470301440606384471ef4edb1ffc2a4b88c` | `70fa50c334202a2b6f4ad2994f00808a04c3e8cf283f286b09c62bd6f222f486` |
| Hy-MT2-30B-A3B 官方 Q4_K_M | `fd3dcbb6b31e9e03923ef4f9f42500f74c3851c3` | `bb44b11bb0f7cd3d1321645b41e911cd3de2e473731227fc6bf37aa18b543f88` |
| Hy-MT2-30B-A3B APEX-I-Compact | `312cce865e03a0718e36cfd1077e6307957aef72` | `8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a` |
| Hy-MT2-30B-A3B i1-Q3_K_L | `c36beb0d9a93b2790313f6beff90482b492ce820` | `e63046e3379cc2cd43116146c42c2b433e8a6a7d86e85b13924f4a479c94395b` |
| Hy-MT2-30B-A3B i1-Q3_K_M | `c36beb0d9a93b2790313f6beff90482b492ce820` | `a70d7755b52cc96999c9d5645f881647c598967a5142b0177d7a6c018a4a3a46` |

来源为 2026-10-06 各仓库固定 revision 的 HF API `?blobs=true` 返回的 LFS SHA256与字节数。
这是发布文件身份核验，不证明社区转换与原始模型张量逐项等价。

原五个条目已完成大小与完整 SHA256 核查，随后完成[五候选固定 test](../research/2026-10-06-translation-model-comparison-results.md)；其运行与质量证据不扩展到新增 Q4。

2026-10-06 新增官方 Q4_K_M，使用本机 `hf download` 完成下载，正式文件大小与完整本地 SHA256 均匹配上表。
六个清单条目现均为 `status: verified`；新增下载阶段只核验 Q4，后续追加对照又完整核验了 Q3／Q4 两份权重，其他四份未重复读取。
官方 Q4 的资产 ID 为 `hy-mt2-30b-a3b-q4-k-m-official`，已加入 demo 的 `--candidate` 选项；显式部分 offload 的 15 窗口 smoke 已通过。与 Q3 的完整质量／性能比较见[实测报告](../research/2026-10-06-hy30-q3-q4-comparison-results.md)：两候选各 83/83 终分，Q4 38/49 层 GPU 的三轮中位耗时为 Q3 的 4.18 倍，用户当时继续保留 Q3 基线；后续 APEX-I-Compact 采纳由 ADR-0005 记录。

## 获取、恢复与核验

本机 `hf version` 为 **2.1.1**。实际调用形状如下，只取指定 GGUF，不下载全部精度：

```powershell
hf download '<repo>' '<filename>' --revision '<fixed-sha>' --local-dir '<absolute-model-directory>' --quiet
```

新增官方 Q4 的精确下载命令：

```powershell
hf download 'tencent/Hy-MT2-30B-A3B-GGUF' 'Hy-MT2-30B-A3B-Q4_K_M.gguf' --revision 'fd3dcbb6b31e9e03923ef4f9f42500f74c3851c3' --local-dir 'D:/AI_Projects/kototoki/.local/models/translation/hy-mt2-30b-a3b-q4-k-m-official' --quiet
```

只恢复或重新校验官方 Q4 时，可运行 `.local/downloads/download-official-hy30-q4.ps1`；它固定上述身份，下载并校验大小及完整 SHA256 后更新同一资产清单，保留原五条记录。

本次批处理与断点恢复入口位于本地忽略目录：

```powershell
# From D:/AI_Projects/kototoki
& './.local/downloads/download-translation-models.ps1'
```

脚本逐项调用 `hf download`，下载后用 `Get-Item` 校验字节数，并以
`Get-FileHash -Algorithm SHA256` 核验完整内容。只有两项相符才写入 `status: verified`
及 `verified_at_utc`。单项失败会记录 `error` 并继续其他文件，最后返回非零退出码。
恢复时仍使用相同 revision、文件和 local-dir，让 HF 复用下载元数据和已有文件；不加
`--force-download`。重新校验已有完整文件也会读取全部内容，耗时与磁盘有关。

脚本将 `HF_HOME` 和 `HF_XET_CACHE` 指向项目 `.local/cache/huggingface/`，
避免在用户目录新增大型模型缓存；隐式 token 被关闭，使用公开 GGUF 仓库下载。
HF CLI 的可选 skill 提示和匿名请求提醒本身不是下载失败。

本次传输期间观察到 Windows 目录查询的 `Length` 暂时为 0，而用共享读取方式打开
同一个 `.incomplete` 文件后，`FileStream.Length` 显示实际长度持续增长。遇到该现象，
先检查原进程和实际文件句柄，不应仅凭目录长度或 lock 文件判断停滞，也不要启动重复下载。
最终仍以正式文件的大小和完整 SHA256 为准。

脚本与清单是本机获取记录，未作为通用产品 provisioning 接口。它们不随 Git 分发；
如果本地脚本不存在，可按上表和命令形状逐项恢复，并重新计算SHA256。

## 后续推理的边界

### 用户选择的新增量化候选（已下载并校验）

用户已执行本地脚本 `.local/downloads/download-hy30-shortlist.ps1`，完成[量化短名单](../research/2026-10-06-hy30-5080-quantization-shortlist.md)的 1、2、4：APEX-I-Compact、mradermacher i1-Q3_K_L、i1-Q3_K_M。恢复或重新校验命令：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'D:\AI_Projects\kototoki\.local\downloads\download-hy30-shortlist.ps1'
```

脚本固定各自 revision、字节数和 SHA256，依次调用 `hf download` 并保留进度显示；可以重新执行以复用已有下载数据。下载到既有模型根目录下的三个独立子目录，不覆盖 GrahLnn Q3 文件。结果单独写入 `.local/manifests/hy30-shortlist-downloads.json`，只有完整校验通过才标记 `verified`，不修改原六模型清单。加 `-PlanOnly` 可离线查看计划，不下载、不写清单。本地忽略脚本不随 Git 分发，固定身份可从上表恢复。

2026-10-06 用户确认下载与 SHA256 校验完成；清单三项均为 `verified`、`error: null`。脚本记录的完整哈希核验时间如下。当时文档更新再次核对了三个实际文件的存在、字节数与清单身份，没有重复读取约 45 GB 权重计算哈希。

| 资产 | 核验时间（UTC） | 核验时间（Asia/Singapore） |
| --- | --- | --- |
| APEX-I-Compact | 2026-10-06 11:19:31 | 2026-10-06 19:19:31 |
| i1-Q3_K_L | 2026-10-06 12:11:33 | 2026-10-06 20:11:33 |
| i1-Q3_K_M | 2026-10-06 13:00:21 | 2026-10-06 21:00:21 |

三个新增资产已接入 demo，并在[四量化比较](../research/2026-10-07-hy30-four-quantization-results.md)中重新核验完整 SHA256、tokenizer、模板、结构和张量类型，完成旧集／新增集质量、四轮性能及正式长跑。报告保留精确资产与兼容引擎身份、显存余量、失败及运行状态变化；loader 49/49 层 offload 不证明权重始终物理驻留。原始历史见[执行记录](../context/2026-10-06-hy30-four-execution.md)；用户在交付后采纳 APEX-I-Compact，当前基线见[ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md)，GrahLnn Q3 继续保留为历史对照资产。

### 推理验证

量化选择原因及 5080 显存预算见[五模型量化研究](../research/2026-10-06-translation-5080-quantization.md)。
原五候选比较的30B使用社区 Q3_K_M，27B使用 Q3_K_L。新增官方30B Q4_K_M 保留独立身份，
已完成显式部分 offload 对照，具体结论见上述实测报告，不能沿用 Q3 的全 GPU 性能或质量结论；候选容量与兼容边界见[Q4 调查](../research/2026-10-06-hy-mt2-30b-q4-candidates.md)。

一次加载一个模型，记录实际引擎版本、模板、GPU驻留、窗口与峰值显存。TranslateGemma
需要其翻译专用语言字段／模板，GGUF能加载不等于任务适配正确。详细接口见
[三模型对比](../research/2026-10-05-local-translation-model-comparison.md)及其专项报告。
资产获取与推理证据分开记录；此次 Q3／Q4 追加对照使用独立目录，模型权重保持原样。
