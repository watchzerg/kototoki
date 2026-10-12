# Hy-MT2 30B-A3B：RTX 5080 16GB 的量化候选短名单

状态：exploratory；公开文件、发布者声明与精确身份核查完成；用户随后下载候选 1、2、4 并通过完整 SHA256，尚未运行新增推理。  
最后更新：2026-10-06。  
范围：腾讯原始 `tencent/Hy-MT2-30B-A3B` 的较大 Q3、较小 Q4 与混合量化，目标为原生 Windows／RTX 5080 16GB。所有外部来源访问日期为 2026-10-06。排序表示后续试验优先级，不表示已经证实的翻译质量排名。

当前采纳身份仍由 [ADR-0004](../adr/0004-hy-mt2-translation-baseline.md)维护。官方 Q4_K_M 已完成本机对照：38/49 层 GPU，生成中位耗时为当前全 GPU Q3 的 4.18 倍，未证明全面稳定的质量优势。本调查继续寻找能接近全 GPU 的中间档，不更换基线。[本机对照](2026-10-06-hy30-q3-q4-comparison-results.md)

## 优先试什么

**优先试 APEX-I-Compact，其次 i1-Q3_K_L，再试 i1-IQ4_XS。** 三者都保留为值得实测的候选；不能用某次 Chrome／桌面叠加后的整卡峰值，直接判定哪个永远装不下。APEX 有翻译定向校准声明且体积最接近当前 Q3；Q3_K_L 是明确的较大 Q3；IQ4_XS 是本次核实的最小标准 Q4 家族候选。是否全 GPU、实际耗时与日译中质量，均待本机加载和翻译验证。

| 顺序 | 候选与固定文件入口 | 精确字节数 | GiB | 与当前 Q3 的文件差额 | 试验价值及未决项 |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | [alphaZimuth APEX-I-Compact](https://huggingface.co/alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF/blob/312cce865e03a0718e36cfd1077e6307957aef72/Hy-MT2-30B-A3B-APEX-I-Compact.gguf) | 15,035,838,080 | 14.003 | +562.20 MiB | 翻译定向 imatrix／混合量化；最接近当前体积的升级探索，精确 Hy 张量配方未公开核实 |
| 2 | [mradermacher i1-Q3_K_L](https://huggingface.co/mradermacher/Hy-MT2-30B-A3B-i1-GGUF/blob/c36beb0d9a93b2790313f6beff90482b492ce820/Hy-MT2-30B-A3B.i1-Q3_K_L.gguf) | 15,644,000,768 | 14.570 | +1,142.19 MiB | 较大 Q3＋imatrix；发布者通用校准以英文为主，本文件具体语料未披露，日译中收益未知 |
| 3 | [mradermacher i1-IQ4_XS](https://huggingface.co/mradermacher/Hy-MT2-30B-A3B-i1-GGUF/blob/c36beb0d9a93b2790313f6beff90482b492ce820/Hy-MT2-30B-A3B.i1-IQ4_XS.gguf) | 16,099,901,952 | 14.994 | +1,576.97 MiB | 较小 Q4；16GB 边界候选，尤其需要检查上下文／计算开销 |
| 4 | [mradermacher i1-Q3_K_M](https://huggingface.co/mradermacher/Hy-MT2-30B-A3B-i1-GGUF/blob/c36beb0d9a93b2790313f6beff90482b492ce820/Hy-MT2-30B-A3B.i1-Q3_K_M.gguf) | 14,446,330,368 | 13.454 | +480 bytes | 几乎同体积的校准替代；探索不增加体积的质量收益，跨发布者转换差异仍会混杂，不能单独归因于 imatrix |
| 5 | [mradermacher i1-IQ3_M](https://huggingface.co/mradermacher/Hy-MT2-30B-A3B-i1-GGUF/blob/c36beb0d9a93b2790313f6beff90482b492ce820/Hy-MT2-30B-A3B.i1-IQ3_M.gguf) | 13,261,775,360 | 12.351 | −1,129.68 MiB | 更小的效率对照；不是“更大 Q3”，也不能凭 IQ 名称断言更好 |
| 6 | [mradermacher static Q3_K_L](https://huggingface.co/mradermacher/Hy-MT2-30B-A3B-GGUF/blob/61904f7a86beb646d4682be9f46fbf0e3eb338df/Hy-MT2-30B-A3B.Q3_K_L.gguf) | 15,644,000,512 | 14.570 | +1,142.19 MiB | 无 imatrix 声明的配对对照；有助于检验英文校准是否适合本任务 |
| 7 | [mradermacher static IQ4_XS](https://huggingface.co/mradermacher/Hy-MT2-30B-A3B-GGUF/blob/61904f7a86beb646d4682be9f46fbf0e3eb338df/Hy-MT2-30B-A3B.IQ4_XS.gguf) | 16,260,628,736 | 15.144 | +1,730.25 MiB | 比 i1 约大 153.28 MiB，容量更紧，作为配对对照保留 |
| 效率补充 | [alphaZimuth APEX-I-Nano](https://huggingface.co/alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF/blob/312cce865e03a0718e36cfd1077e6307957aef72/Hy-MT2-30B-A3B-APEX-I-Nano.gguf) | 12,447,420,032 | 11.593 | −1,906.31 MiB | 更小混合档；有余量但质量代价未知，非优先容量升级 |

字节数及 SHA256 来自发布者 HF API： [APEX](https://huggingface.co/api/models/alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF?blobs=true)、[i1](https://huggingface.co/api/models/mradermacher/Hy-MT2-30B-A3B-i1-GGUF?blobs=true)、[static](https://huggingface.co/api/models/mradermacher/Hy-MT2-30B-A3B-GGUF?blobs=true)。上表链接固定 revision；API 的 `main` 后续可能变化。当前基线为 [GrahLnn Q3_K_M](https://huggingface.co/GrahLnn/Hy-MT2-30B-A3B-4bit-GGUF/blob/4ae7787177f6d4f2d54ec2d543d9fe5f9114d1c9/Hy-MT2-30B-A3B-Q3_K_M.gguf)，14,446,329,888 bytes＝13.454 GiB。后续获取状态：候选 1、2、4 已由用户执行下载脚本并通过完整 SHA256；本地路径与核验记录见[资产指南](../guides/local-translation-model-assets.md)。其余新候选仍只有上游元数据核验。

## 用模型、KV 与计算开销估容量

以下是**容量规划启发式，不是统一标准或实际峰值预测**：以文件 GiB 作保守起点，加 context 4096 配方的 KV 约 0.375 GiB，再暂留 0.2–0.5 GiB 给计算／CUDA 等开销，合计约“文件＋0.6–0.9 GiB”。桌面、浏览器及其他程序的占用另外随当时环境变化。文件含可能不进入 GPU 的数据，各量化的张量分配、内核和缓冲也可能不同；规划数只能帮助安排实测。

| 候选 | 文件＋0.6–0.9 GiB | 对标 nominal 16 GiB 的规划判断 |
| --- | ---: | --- |
| APEX-I-Compact | 14.60–14.90 GiB | 有希望全 GPU，优先验证 |
| i1-Q3_K_L | 15.17–15.47 GiB | 有希望全 GPU，需控制其他占用 |
| i1-IQ4_XS | 15.59–15.89 GiB | 很接近边界，保留测试；可能需减 context／batch 或少量 offload |
| static IQ4_XS | 15.74–16.04 GiB | 更紧的边界对照 |

已测当前 Q3 的 CUDA model buffer 为 13,670.82 MiB，与文件换算 13,777.09 MiB 并不相等；不能把这种差额无条件套到其他 GGUF。KV 和 compute 也应逐次读取引擎日志。已有官方 Q4 的部分 offload 结果说明混合运行可能明显增加耗时，但其 4.18 倍不能外推为所有 IQ4／APEX 的倍率。[本机配置与对照](2026-10-06-hy30-q3-q4-comparison-results.md)

即使全部层驻留 GPU，不同量化类型的 CUDA 内核也可能有不同吞吐；更小文件或更低位数不保证更快。因此后续仍需同输入的加载、生成耗时与质量对照。

## 发布者、校准和来源可信度

| 发布者 | 可核实的公开背景 | 本模型来源与校准证据 | 缺口及判断 |
| --- | --- | --- | --- |
| 腾讯／Hunyuan | 原始模型发布组织；[原始模型](https://huggingface.co/tencent/Hy-MT2-30B-A3B)及[官方 GGUF](https://huggingface.co/tencent/Hy-MT2-30B-A3B-GGUF) | 原始 BF16／官方 Q4_K_M；官方来源最清晰 | 官方身份不等于更适合16GB；已测 Q4 保留对照 |
| mradermacher | 当前[账号 API](https://huggingface.co/api/users/mradermacher/overview)显示 `team mradermacher`；[FAQ](https://huggingface.co/mradermacher/model_requests/blob/b5a9f3f80654783594a6fe4b1fe7d698a8411590/README.md)自述为团队共用化名，2024年开始量化，nicoboss提供计算资源；模型卡致谢 nethype GmbH | 模型卡直接列 `base_model: tencent/Hy-MT2-30B-A3B`，i1自述weighted/imatrix，另发布120,510,848-byte imatrix文件；static单独标明 | 通用校准约160k tokens，以英文故事片段和groups_merged等为主，完整集未公开；该Hy卡没有模型专属数据版本、生成命令、上游固定revision或日译中成绩。不能把团队化名映射到网上同名真人或推断资历 |
| alphaZimuth | [账号 API](https://huggingface.co/api/users/alphaZimuth/overview)显示 `XYLong`，无组织；公开个人简介不是雇主或专业认证 | [固定模型卡](https://huggingface.co/alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF/blob/312cce865e03a0718e36cfd1077e6307957aef72/README.md)声明腾讯BF16→hy3-port GGUF→APEX＋多语言翻译imatrix；2026-07加入I系列，2026-09-11重命名 | 未公开完整校准集、语言比例、样本／token数、固定生成命令或可复算日译中质量表。其PPL与多LLM偏好为发布者自述。通用APEX默认配方不证明此Hy文件的逐张量类型 |
| GrahLnn | [账号 API](https://huggingface.co/api/users/GrahLnn/overview)只有同名显示名，未公开组织／简介；不能推断职业背景 | [固定模型卡](https://huggingface.co/GrahLnn/Hy-MT2-30B-A3B-4bit-GGUF/blob/4ae7787177f6d4f2d54ec2d543d9fe5f9114d1c9/README.md)提供转换源GGUF、HYV3补丁及4090/WSL运行数据；本项目已下载并验证Q3 | 未声明本Q3使用imatrix或具体校准数据；本项目实测是其适用性的直接证据 |

APEX-I 的发布者对照采用 RTX 3060 Laptop 12GB、llama.cpp b10056、Compact `n_cpu_moe=13`，TG128约56.16 tok/s。这是另一个设备和CPU expert offload配方，不能作为5080全GPU速度或字幕质量证据。APEX framework来自[LocalAI apex-quant](https://github.com/localai-org/apex-quant)；发布者不是因此就成为LocalAI成员。[固定模型卡](https://huggingface.co/alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF/blob/312cce865e03a0718e36cfd1077e6307957aef72/README.md)

imatrix 是量化阶段的重要性校准资料，已量化文件正常推理无需再加载它；存在imatrix也不等于没有量化损失或自动提升所有语言。mradermacher FAQ明确提醒其英文为主校准对其他语言可能不利；本任务日译中必须实测，不采用模型卡“beats Q3”之类通用描述作为排名。[发布者FAQ](https://huggingface.co/mradermacher/model_requests/blob/b5a9f3f80654783594a6fe4b1fe7d698a8411590/README.md)、[llama.cpp imatrix说明](https://github.com/ggml-org/llama.cpp/blob/v0.6.0/tools/imatrix/README.md)

## 其他发布物为什么没进入前三

- 常规 Q4_K_S 约15.975 GiB文件，官方 Q4_K_M约16.984 GiB文件；其文件＋KV／compute预算已经越过16GiB目标。较小标准Q4的重点是IQ4_XS。[既有Q4精确表](2026-10-06-hy-mt2-30b-q4-candidates.md)
- [Reza2kn NVFP4-Experts GGUF](https://huggingface.co/Reza2kn/Hy-MT2-30B-A3B-NVFP4-GGUF/blob/4ab3dd8178a10cf6740d6dea01cd48ad809b8fb7/README.md)为19,353,433,056 bytes＝18.024 GiB，比官方Q4还大。它公开了来源revision、ModelOpt／llama.cpp commit及240条英／波斯语Wikipedia校准（65,487 tokens），来源链较完整；其5080 Laptop16GB实测仍为38层GPU。英／波斯语结果不能代替日译中。作者[公开账号](https://huggingface.co/Reza2kn)显示名Reza Sayar，发布波斯语ASR及量化项目；这不证明特定学术或任职背景。
- [Intel AutoRound int4](https://huggingface.co/Intel/Hy-MT2-30B-A3B-int4-AutoRound/blob/e3a5c655608f635a874a3bbadde9131d9687356d/README.md)为六个safetensors权重文件合计16,494,221,072 bytes＝15.361 GiB，属于另一个运行栈；卡给出group128／symmetric／200 iterations命令，但没有本机Windows5080验证或日译中数据。不能直接接入现有GGUF配方。[API](https://huggingface.co/api/models/Intel/Hy-MT2-30B-A3B-int4-AutoRound?blobs=true)
- [caelunshun NVFP4-FP8BLOCK](https://huggingface.co/caelunshun/Hy-MT2-30B-A3B-NVFP4-FP8BLOCK/tree/8d9c5897a6368342cec64dbbba5bbd5c13e7d99c)的safetensors为18,065,307,552 bytes＝16.825 GiB，本次API未见模型卡；容量及验证链不支持立即优先。[API](https://huggingface.co/api/models/caelunshun/Hy-MT2-30B-A3B-NVFP4-FP8BLOCK?blobs=true)
- AngelSlim、botp和Abu-Dju的Q4_K_M上游SHA256均与腾讯官方 `bb44b11b…43f88`相同，属于同一文件身份的下载来源，不算三个新量化。litigerking、chaos700等提供不同哈希的常规Q3／Q4，但没有解决本次中间档体积问题。[AngelSlim API](https://huggingface.co/api/models/AngelSlim/Hy-MT2-30B-A3B-GGUF?blobs=true)、[botp API](https://huggingface.co/api/models/botp/Hy-MT2-30B-A3B-GGUF?blobs=true)、[Abu-Dju API](https://huggingface.co/api/models/Abu-Dju/Hy-MT2-30B-A3B-GGUF?blobs=true)
- MLX／MLX Mixed档不是当前原生Windows CUDA／GGUF直接替换。OS-Software的heretic、alphaZimuth Uncensored及相关派生仓库修改原模型身份；katya228 ru-jp等任务修改版本也不作为原腾讯权重的直接量化对照。[本次HF搜索API](https://huggingface.co/api/models?search=Hy-MT2-30B-A3B&limit=100)

本次搜索API返回46个仓库，并核对原始模型GGUF文件树及Q3_K_L／IQ4_NL搜索。未找到原模型发布的IQ4_NL或Q3_K_XL文件；这是限定范围内的“未找到”，不是全球不存在证明。mradermacher卡里的注释出现 `small-IQ4_NL`，但该仓库实际siblings没有对应文件，不能当作可下载候选。[i1 API](https://huggingface.co/api/models/mradermacher/Hy-MT2-30B-A3B-i1-GGUF?blobs=true)

## 固定身份与后续验证边界

前三及校准对照的上游SHA256如下；下载时仍需计算本地完整哈希：

| 候选 | 上游SHA256 |
| --- | --- |
| APEX-I-Compact | `8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a` |
| i1-Q3_K_L | `e63046e3379cc2cd43116146c42c2b433e8a6a7d86e85b13924f4a479c94395b` |
| i1-IQ4_XS | `b9915000ae92018f0d02e0a51b7e4a61727a28e3cbc9d540ff7ab9eb954382a8` |
| i1-Q3_K_M | `a70d7755b52cc96999c9d5645f881647c598967a5142b0177d7a6c018a4a3a46` |
| i1-IQ3_M | `e22428bfd5ccb3a2be8f71c4e890c1002a8d14f815b2b2002d42f045df899dd9` |

后续若获得执行授权，先核对文件schema、HYV3 loader／bias名称、模板和引擎支持，再读取GPU model／KV／compute日志及完整offload状态。现有GrahLnn兼容DLL不能默认适用所有GGUF。量化比较建立新配方、新输出目录，保留当前基线；此前test已用于优化讨论，任何继续利用它的比较须标明test-informed。[ADR-0004](../adr/0004-hy-mt2-translation-baseline.md)

小型HF元数据、模型卡及作者API快照保存在 `.local/translation-research/20261006-shortlist/`，没有权重内容。首次调查只写研究文档；后续已获取候选 1、2、4，资产记录见上述指南，引擎与推理配置未改变。
