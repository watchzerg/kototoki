# Hy-MT2 30B-A3B：RTX 5080 16GB 的 Q4 候选

状态：exploratory；保留首次 Q4 候选调查。随后腾讯官方 Q4_K_M 已完成实测，结果见[Q3／Q4 对照](2026-10-06-hy30-q3-q4-comparison-results.md)；用户继续保留 Q3 基线。当前候选排序与容量预估见[更新后的量化候选清单](2026-10-06-hy30-5080-quantization-shortlist.md)。  
最后更新：2026-10-06。  
范围：腾讯原始 `Hy-MT2-30B-A3B` 的公开 GGUF，重点为 Q4_K_M、Q4_K_S、IQ4_XS、IQ4_NL、Q4_0、Q4_1；原生 Windows／RTX 5080 16GB。所有外部来源访问日期为 2026-10-06。

用户随后要求聚焦腾讯官方版本，已获取固定 revision `fd3dcbb6b31e9e03923ef4f9f42500f74c3851c3` 的 `Hy-MT2-30B-A3B-Q4_K_M.gguf`；完整本地 SHA256 为 `bb44b11bb0f7cd3d1321645b41e911cd3de2e473731227fc6bf37aa18b543f88`，与上游一致。资产路径与恢复方式见[本地资产指南](../guides/local-translation-model-assets.md)。下文社区候选排序保留为调查建议，不代表后续采用或下载顺序。

下文显存余量和试验顺序反映首次调查时的证据。用户随后指出桌面／Chrome 占用会波动，因此更新清单采用权重、KV cache 与运行缓冲的预算估算，不以某次整卡峰值排除临界候选。

## 首次调查的结论与试验顺序

**Q4 中优先试 mradermacher 的 imatrix IQ4_XS，但它是显存紧张的实验候选，不能承诺沿用现有配置全 GPU 成功。** 常规 Q4_K_S、Q4_0 几乎占满显存；Q4_K_M、Q4_1 更大，需要 GPU／CPU RAM 混合运行或更大显存。用户已认可的 Q3_K_M 应保留为质量与性能对照；现有结果不支持宣布某个 Q4 的字幕质量更好。[发布者文件树](https://huggingface.co/mradermacher/Hy-MT2-30B-A3B-i1-GGUF/tree/c36beb0d9a93b2790313f6beff90482b492ce820)、[既有本机比较](2026-10-06-translation-model-comparison-results.md)

若接受混合运行，可先试 i1-IQ4_XS，随后试 i1-Q4_K_S 或官方 Q4_K_M；前者较小，后者官方来源更清晰。这个顺序考虑文件体积和来源，不构成翻译质量排名。没有充分理由优先 Q4_0／Q4_1：前者没有显存余量优势，后者体积甚至超过 Q4_K_M。[imatrix 发布者说明](https://huggingface.co/mradermacher/Hy-MT2-30B-A3B-i1-GGUF/blob/c36beb0d9a93b2790313f6beff90482b492ce820/README.md)、[官方文件树](https://huggingface.co/tencent/Hy-MT2-30B-A3B-GGUF/tree/fd3dcbb6b31e9e03923ef4f9f42500f74c3851c3)

## 精确文件与容量

下表字节数来自 HF API `siblings[].size`；GiB 按 `bytes / 2^30`，不是十进制 GB。文件包含元数据及可能留在主机上的张量，**文件大小不是实际 GPU model buffer 或整卡峰值**；此处据其作筛选，不能据其单独证明能运行。

| 类型／来源 | 精确文件名 | 字节数 | GiB | 5080 判断（推断，未测） |
| --- | --- | ---: | ---: | --- |
| IQ4_XS，mradermacher i1 | `Hy-MT2-30B-A3B.i1-IQ4_XS.gguf` | 16,099,901,952 | 14.994 | 本次最小标准 Q4 候选；同配方全 GPU 余量不足，先准备短上下文／小 batch 或少量 offload |
| IQ4_XS，mradermacher static | `Hy-MT2-30B-A3B.IQ4_XS.gguf` | 16,260,628,736 | 15.144 | 比 i1 大约 153 MiB，更紧；不能推断其日译中质量差于 i1 |
| Q4_0，mradermacher i1 | `Hy-MT2-30B-A3B.i1-Q4_0.gguf` | 17,087,726,080 | 15.914 | 文件约 16,296 MiB，与本机总显存 16,303 MiB 接近；不适合作全 GPU 建议 |
| Q4_K_S，mradermacher i1 | `Hy-MT2-30B-A3B.i1-Q4_K_S.gguf` | 17,152,541,184 | 15.975 | 缺少 cache／计算缓冲空间；混合运行候选 |
| Q4_K_M，腾讯官方 | `Hy-MT2-30B-A3B-Q4_K_M.gguf` | 18,236,702,880 | 16.984 | 混合运行候选 |
| Q4_K_M，mradermacher i1 | `Hy-MT2-30B-A3B.i1-Q4_K_M.gguf` | 18,236,703,232 | 16.984 | imatrix 版本，容量与官方基本相同；混合运行候选 |
| Q4_1，mradermacher i1 | `Hy-MT2-30B-A3B.i1-Q4_1.gguf` | 18,886,230,528 | 17.589 | 混合运行候选，没有本次支持其优先级的质量证据 |
| IQ4_NL | 本次未找到原始模型对应的发布文件 | — | — | 运行时支持该类型，不等于已有人发布此模型的文件 |

表格来源：[i1 API](https://huggingface.co/api/models/mradermacher/Hy-MT2-30B-A3B-i1-GGUF?blobs=true)、[static API](https://huggingface.co/api/models/mradermacher/Hy-MT2-30B-A3B-GGUF?blobs=true)、[官方 API](https://huggingface.co/api/models/tencent/Hy-MT2-30B-A3B-GGUF?blobs=true)。查证时 revision 分别为 `c36beb0d9a93b2790313f6beff90482b492ce820`、`61904f7a86beb646d4682be9f46fbf0e3eb338df`、`fd3dcbb6b31e9e03923ef4f9f42500f74c3851c3`。

优先 IQ4_XS 的[固定文件入口](https://huggingface.co/mradermacher/Hy-MT2-30B-A3B-i1-GGUF/blob/c36beb0d9a93b2790313f6beff90482b492ce820/Hy-MT2-30B-A3B.i1-IQ4_XS.gguf)对应上游 SHA256：`b9915000ae92018f0d02e0a51b7e4a61727a28e3cbc9d540ff7ab9eb954382a8`。本次只核实上游元数据，没有下载后完整哈希验证。

其他仓库没有解开常规 Q4 的容量问题：chaos700 Q4_K_S 为 17,152,540,512 bytes；GrahLnn Q4_K_M 为 18,236,702,752 bytes；AngelSlim Q4_K_M 为 18,236,702,880 bytes。不同发布者文件的大小接近，不证明内容、转换方式或兼容性相同。[chaos700 API](https://huggingface.co/api/models/chaos700/Hy-MT2-30B-A3B-GGUF?blobs=true)、[GrahLnn API](https://huggingface.co/api/models/GrahLnn/Hy-MT2-30B-A3B-4bit-GGUF?blobs=true)、[AngelSlim API](https://huggingface.co/api/models/AngelSlim/Hy-MT2-30B-A3B-GGUF?blobs=true)

IQ4_NL 的“未找到”限于本次 HF 名称搜索及原始权重 GGUF 发布仓库核查，不表示全球不存在或未来不会发布；没有把 uncensored／heretic 等修改权重模型当作原模型的量化版本。[HF 搜索 API](https://huggingface.co/api/models?search=Hy-MT2-30B-A3B&limit=100)

## imatrix 与质量证据

i1 仓库明确自述为 weighted/imatrix quants，并提供 `Hy-MT2-30B-A3B.imatrix.gguf`（120,510,848 bytes）。发布者通用 FAQ 解释 `i1` 是“imatrix type 1”，其数据约 160k tokens，以英文为主，包含故事片段及 `groups_merged.txt` 等；没有公布完整数据。**该 Hy 专属模型卡没有给出具体校准语料版本、完整生成命令或日译中评测**，因此只能核实使用 imatrix 的声明与文件，不能认定其对日语字幕优于 static 或已测 Q3。[i1 模型卡](https://huggingface.co/mradermacher/Hy-MT2-30B-A3B-i1-GGUF/blob/c36beb0d9a93b2790313f6beff90482b492ce820/README.md)、[发布者 FAQ](https://huggingface.co/mradermacher/model_requests)

llama.cpp 的 imatrix 是由模型与校准文本计算的重要性信息，量化时使用；已量化模型正常推理无需额外加载 imatrix 文件。量化类型说明和其他模型的 perplexity 表不能替代本模型日译中测试。[llama.cpp v0.6.0 imatrix 文档](https://github.com/ggml-org/llama.cpp/blob/v0.6.0/tools/imatrix/README.md)、[量化工具](https://github.com/ggml-org/llama.cpp/blob/v0.6.0/tools/quantize/quantize.cpp)

## 显存与兼容性边界

现有 Q3_K_M 在本机 context 4096、llama.cpp b11429／v0.6.0、CUDA 13.4 配方完成固定 test，整卡采样峰值为 **15,271 MiB**，总显存 **16,303 MiB**，只剩约 **1,032 MiB**。i1-IQ4_XS 文件比现有 Q3 大约 **1,577 MiB**。若其他内存开销近似不变，简单增量估计会超出现有余量约 545 MiB；这是容量警示，**不是实测峰值预测**，因为不同转换、张量分配、内核、cache 与 batch 会改变 GPU 缓冲。[既有本机比较及复现配方](2026-10-06-translation-model-comparison-results.md)、[既有 Q3 身份](../guides/local-translation-model-assets.md)

更强的 Q4_K_M 容量证据是 GrahLnn 发布者实测：RTX 4090／WSL／patched llama.cpp、49/49 layers offloaded 时，**GPU model buffer 已为 17,254.26 MiB**，尚未计全部运行开销，超过本机总显存。这是该发布文件在另一环境的观测，不能冒充 Windows 5080 实测。[固定 revision 的发布者运行记录](https://huggingface.co/GrahLnn/Hy-MT2-30B-A3B-4bit-GGUF/blob/4ae7787177f6d4f2d54ec2d543d9fe5f9114d1c9/README.md)

v0.6.0 上游已注册 `hy_v3`，量化工具列出上述六种类型，CUDA 源码含 IQ4_XS／IQ4_NL 支持。然而现有 GrahLnn Q3 实际需要独立 bias tensor-name loader 兼容 DLL；**其他发布者 GGUF 不能默认沿用该 DLL，也不能因有架构支持便宣称文件加载成功**。后续须逐文件核对张量 schema、模板、GPU offload 日志、峰值与短文本输出。[架构注册](https://github.com/ggml-org/llama.cpp/blob/v0.6.0/src/llama-arch.cpp)、[量化类型](https://github.com/ggml-org/llama.cpp/blob/v0.6.0/tools/quantize/quantize.cpp)、[CUDA 实现](https://github.com/ggml-org/llama.cpp/blob/v0.6.0/ggml/src/ggml-cuda/mmq.cuh)、[本机兼容记录](2026-10-06-translation-model-comparison-results.md)

短上下文、小 batch、量化 KV 或少量 expert／layer offload 是后续可测选项，不是已确认可用方案；须记录是否全 GPU、运行时间与质量，不能把混合运行与现有 Q3 的全 GPU 性能直接等同。

## 另一个较小候选：APEX-I-Compact

`alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF` 的 `Hy-MT2-30B-A3B-APEX-I-Compact.gguf` 为 **15,035,838,080 bytes＝14.003 GiB**，比 i1-IQ4_XS 更小，但它是 APEX 分档混合量化，不能称为标准 Q4。发布者自述使用多语言翻译校准集；其基准是 RTX 3060 Laptop 12GB、`n_cpu_moe=13` 的混合运行，未证明 5080 全 GPU 或优于现有 Q3。可作为独立后续实验候选。[固定 revision 文件树](https://huggingface.co/alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF/tree/312cce865e03a0718e36cfd1077e6307957aef72)、[发布者说明与基准](https://huggingface.co/alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF/blob/312cce865e03a0718e36cfd1077e6307957aef72/README.md)、[文件 API](https://huggingface.co/api/models/alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF?blobs=true)

相关：[前次五模型量化调查](2026-10-06-translation-5080-quantization.md)。本次新增研究不改变 STT 里程碑、模型资产或现有推理配置。
