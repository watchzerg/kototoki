# RTX 5080 16 GB：翻译模型量化下载建议

状态：exploratory；公开文件与接口核查完成，显存可行性为估算，未下载权重、未安装引擎、未进行本机推理或翻译质量实测。

最后更新：2026-10-06。

用户随后授权获取五个建议版本，并追加腾讯官方 Hy-MT2 30B-A3B Q4_K_M；六份均已下载并通过大小及完整 SHA256 校验。本地路径、固定文件身份与实际获取状态统一见[翻译模型资产入口](../guides/local-translation-model-assets.md)。下文“未下载”描述本次量化研究本身，不替代该资产记录；原五候选的推理证据见[正式比较](2026-10-06-translation-model-comparison-results.md)，新增官方 Q4 尚未实测。

范围：用户指定的 Tower-Plus-9B、Hy-MT2-7B、Hy-MT2-30B-A3B、TranslateGemma-12B 与 TranslateGemma-27B。假设原生 Windows、RTX 5080、纯文本、一次一个模型、单请求、较短上下文。建议不改变当前原语言 STT 里程碑。

外部来源访问日期均为 2026-10-06。权重字节数来自 Hugging Face 公开 API 的 `siblings[].size`；GB 按十进制，GiB 按二进制。文件体积并不等于实际显存；显存还需容纳 KV cache、计算缓冲、CUDA／驱动与桌面占用。未核查下载后的实际哈希与本机运行日志。

## 五个模型的直接建议

| 模型 | 建议首次下载 | 文件大小 | 对 16 GiB 的判断 |
| --- | --- | --- | --- |
| Tower-Plus-9B | Q8_0 | 9.827 GB／9.15 GiB | 短上下文全 GPU 是合理候选，余量较充足 |
| Hy-MT2-7B | 官方 Q8_0 | 7.982 GB／7.43 GiB | 全 GPU 的合理首选候选，无需优先降到 Q4 |
| Hy-MT2-30B-A3B | 全 GPU 探索选社区 Q3_K_M；官方 Q4_K_M 仅考虑混合运行 | Q3 14.446 GB／13.45 GiB；官方 Q4 18.237 GB／16.98 GiB | Q3 需验证短窗口和质量；官方 Q4 权重本身超过 16 GiB |
| TranslateGemma-12B | Q8_0；更重视余量则 Q6_K | 12.510 GB／11.65 GiB；9.661 GB／9.00 GiB | Q8 可尝试单请求短上下文；Q6 余量更宽 |
| TranslateGemma-27B | 不作为首次选择；想比较大模型可试 Q3_K_L | 14.543 GB／13.54 GiB | 可行性仍取决于缓冲和可用显存，需实测；Q4_K_M 不适合按全 GPU 稳妥方案推荐 |

这些是根据文件体积与运行预算作出的工程推断，不是测出的运行成功率、速度或质量排名。较大模型低位量化与较小模型高位量化的翻译效果不能仅按参数量判断。来源分别见以下发布者文件/API 表。

## Hy-MT2-7B：优先官方 Q8_0

腾讯官方 GGUF revision 为 `ab8472660ac61fac25f1af43fac2599d52a8a775`。[文件树](https://huggingface.co/tencent/Hy-MT2-7B-GGUF/tree/ab8472660ac61fac25f1af43fac2599d52a8a775)、[公开文件 API](https://huggingface.co/api/models/tencent/Hy-MT2-7B-GGUF?blobs=true)

| 精确文件名 | 字节数 | GB |
| --- | ---: | ---: |
| `HY-MT2-7B-Q8_0.gguf` | 7,981,928,896 | 7.982 |
| `HY-MT2-7B-Q6_K.gguf` | 6,164,482,720 | 6.164 |
| `Hy-MT2-7B-Q4_K_M.gguf` | 4,624,648,896 | 4.625 |

建议 [官方 Q8_0](https://huggingface.co/tencent/Hy-MT2-7B-GGUF/blob/ab8472660ac61fac25f1af43fac2599d52a8a775/HY-MT2-7B-Q8_0.gguf)。若已有相同来源与哈希文件可复用，不必重复下载。16 GiB 单模型预算没有迫使它降到 Q4；但并发、长窗口或 ASR 常驻会改变资源条件。模板、采样和量化对指令遵循的影响见[7B 专项报告](2026-10-05-hy-mt2-7b-local-translation.md)。

## Hy-MT2-30B-A3B：修正“Q4 可试”的前提

**官方 Q4_K_M 不能全权重驻留 16 GiB。** 腾讯官方 GGUF 已存在，本次 API revision 为 `fd3dcbb6b31e9e03923ef4f9f42500f74c3851c3`；Q4 文件为 18,236,702,880 bytes，即 16.984 GiB，Q8 为 31,985,729,376 bytes。[官方 GGUF 文件树](https://huggingface.co/tencent/Hy-MT2-30B-A3B-GGUF/tree/fd3dcbb6b31e9e03923ef4f9f42500f74c3851c3)、[公开 API](https://huggingface.co/api/models/tencent/Hy-MT2-30B-A3B-GGUF?blobs=true)

之前笼统说“5080 可以试 Q4”不够准确：对这个官方文件，只能作为兼容后端上的 **GPU＋CPU／RAM 混合运行实验**，且取决于系统内存和配置，不能承诺全 GPU 或速度。这里没有把项目对 ASR／强制对齐的 GPU 要求扩大为禁止所有翻译 offload；两类运行结果必须区分。

`A3B` 指每 token 激活的参数规模，不表示仅保存 3B 权重。其配置为 128 个路由专家、每 token 选择 8 个，另有共享专家；普通运行仍须存放未在当前 token 激活的权重。MoE 的计算量优势不能直接按比例换算为显存节约。[原始模型](https://huggingface.co/tencent/Hy-MT2-30B-A3B)、[官方配置](https://huggingface.co/tencent/Hy-MT2-30B-A3B/raw/main/config.json)

如果想尽量全 GPU，比官方 Q4 更合理的探索文件是社区 **Q3_K_M**：

- [GrahLnn Q3_K_M 文件](https://huggingface.co/GrahLnn/Hy-MT2-30B-A3B-4bit-GGUF/blob/4ae7787177f6d4f2d54ec2d543d9fe5f9114d1c9/Hy-MT2-30B-A3B-Q3_K_M.gguf)，14,446,329,888 bytes＝14.446 GB＝13.454 GiB。这是社区转换；下载后的模板、张量兼容和翻译质量未验证。
- 同仓库 Q2_K 为 11,060,609,056 bytes，余量更宽，但本次没有支持其字幕质量的实测，不以容量为由推荐优先下载。[发布者说明](https://huggingface.co/GrahLnn/Hy-MT2-30B-A3B-4bit-GGUF)、[API](https://huggingface.co/api/models/GrahLnn/Hy-MT2-30B-A3B-4bit-GGUF?blobs=true)

**也不能把“Q4_K_M 不够”简化成所有四位量化都绝无可能。** 社区 mradermacher 的 `Hy-MT2-30B-A3B.i1-IQ4_XS.gguf` 是 16,099,901,952 bytes＝14.994 GiB，理论上权重小于显存，但仅剩约 1 GiB 给桌面、cache 和缓冲；只能算很紧的短窗口实验，不能作为稳妥首次下载建议。API 实际体积与 README 的四舍五入数字不同，本文按字节计算。[发布者](https://huggingface.co/mradermacher/Hy-MT2-30B-A3B-i1-GGUF)、[公开 API](https://huggingface.co/api/models/mradermacher/Hy-MT2-30B-A3B-i1-GGUF?blobs=true)

作为对照，chaos700 的 Q4_K_S 为 17,152,540,512 bytes＝15.975 GiB，几乎占满卡，仍没有实际运行空间。[文件 API](https://huggingface.co/api/models/chaos700/Hy-MT2-30B-A3B-GGUF?blobs=true) 因而选择时必须看精确量化类型和实际文件，不能只看“Q4”两个字。

本次核验的 llama.cpp 最新稳定标签为 [v0.5.0](https://github.com/ggml-org/llama.cpp/releases/tag/v0.5.0)，该标签的[架构注册源码](https://raw.githubusercontent.com/ggml-org/llama.cpp/v0.5.0/src/llama-arch.cpp)已有 `hy_v3`。早期社区说明中的“上游可能不支持、必须打补丁”不能直接沿用；有架构注册仍不等于用户当前 GUI 内置引擎或这些 GGUF 已通过本机验证。

## 推荐的下载与首次运行顺序

优先准备 Hy-MT2-7B Q8、Tower-Plus-9B Q8、TranslateGemma-12B Q8；若12B需要更多并发或显存余量，再选Q6。随后才比较 Hy-MT2-30B Q3 与 TranslateGemma-27B Q3。一次只加载一个，先卸载 STT 模型；纯文本不额外加载视觉组件。

初始显存验证采用单请求、短正文、约 2K–4K 的运行窗口并预留输出，不直接开启几十K窗口。TranslateGemma 的官方 2K 指输入范围，不应误当作输入加输出预算；各模型的上下文和模板边界见后文与原研究。关闭其他占显存工作，检查实际GPU驻留及峰值，再增加窗口／并发。此处为建议，未执行。

## Tower-Plus-9B

原始模型由 Unbabel 发布；本次核查的 GGUF 是 **mradermacher 社区转换**，不是 Unbabel 官方 GGUF。[原始模型](https://huggingface.co/Unbabel/Tower-Plus-9B)、[GGUF 发布者说明](https://huggingface.co/mradermacher/Tower-Plus-9B-GGUF)

GGUF 仓库 revision：`79d27e5fb80c9feb4eb7b29c2469cdcb49b01b0c`。[文件列表](https://huggingface.co/mradermacher/Tower-Plus-9B-GGUF/tree/79d27e5fb80c9feb4eb7b29c2469cdcb49b01b0c)、[公开 API](https://huggingface.co/api/models/mradermacher/Tower-Plus-9B-GGUF?blobs=true)

| 精度 | 精确文件名 | 字节数 | GB |
| --- | --- | ---: | ---: |
| Q8_0 | `Tower-Plus-9B.Q8_0.gguf` | 9,827,149,344 | 9.827 |
| Q6_K | `Tower-Plus-9B.Q6_K.gguf` | 7,589,070,368 | 7.589 |
| Q5_K_M | `Tower-Plus-9B.Q5_K_M.gguf` | 6,647,367,200 | 6.647 |
| Q4_K_M | `Tower-Plus-9B.Q4_K_M.gguf` | 5,761,058,336 | 5.761 |

建议下载 [Q8_0 文件](https://huggingface.co/mradermacher/Tower-Plus-9B-GGUF/blob/79d27e5fb80c9feb4eb7b29c2469cdcb49b01b0c/Tower-Plus-9B.Q8_0.gguf)。原始 BF16 权重约 18.48 GB，权重本身已超过单卡 16 GiB；量化是实际单卡选择。模型基于 Gemma 2 9B，官方上下文 8192 tokens；聊天包装与翻译任务按自己的模板使用。[原始文件与模型卡](https://huggingface.co/Unbabel/Tower-Plus-9B)、[既有接口核查](2026-10-05-tower-plus-9b-local-translation.md)

发布者 README 的 rounded Size/GB 与真实文件列表略有差异，表格采用 API 精确字节数，不抄 README 的 9.9／7.7 GB。

## TranslateGemma-12B

原始模型由 Google 发布；此处 GGUF 是 **bullerwins 社区转换**。它与原始 `google/translategemma-12b-it` 的 Safetensors 发布区分。[原始模型](https://huggingface.co/google/translategemma-12b-it)、[社区模型](https://huggingface.co/bullerwins/translategemma-12b-it-GGUF)

GGUF 仓库 revision：`d7d1d8cc4ff53d4bc883ef33eae3894f07833b63`。[文件列表](https://huggingface.co/bullerwins/translategemma-12b-it-GGUF/tree/d7d1d8cc4ff53d4bc883ef33eae3894f07833b63)、[公开 API](https://huggingface.co/api/models/bullerwins/translategemma-12b-it-GGUF?blobs=true)

| 精度 | 精确文件名 | 字节数 | GB |
| --- | --- | ---: | ---: |
| Q8_0 | `translategemma-12b-it-Q8_0.gguf` | 12,510,227,904 | 12.510 |
| Q6_K | `translategemma-12b-it-Q6_K.gguf` | 9,660,826,944 | 9.661 |
| Q5_K_M | `translategemma-12b-it-Q5_K_M.gguf` | 8,445,052,224 | 8.445 |
| Q4_K_M | `translategemma-12b-it-Q4_K_M.gguf` | 7,300,793,664 | 7.301 |

质量优先、纯文本单请求短上下文可先试 [Q8_0](https://huggingface.co/bullerwins/translategemma-12b-it-GGUF/blob/d7d1d8cc4ff53d4bc883ef33eae3894f07833b63/translategemma-12b-it-Q8_0.gguf)；需要更多显存余量选 [Q6_K](https://huggingface.co/bullerwins/translategemma-12b-it-GGUF/blob/d7d1d8cc4ff53d4bc883ef33eae3894f07833b63/translategemma-12b-it-Q6_K.gguf)。没有必要因显卡只有 16 GB 而默认降至 Q4。

## TranslateGemma-27B

原始模型由 Google 发布；此处也是 **bullerwins 社区 GGUF**。[原始模型](https://huggingface.co/google/translategemma-27b-it)、[社区模型](https://huggingface.co/bullerwins/translategemma-27b-it-GGUF)

GGUF 仓库 revision：`648ab470301440606384471ef4edb1ffc2a4b88c`。[文件列表](https://huggingface.co/bullerwins/translategemma-27b-it-GGUF/tree/648ab470301440606384471ef4edb1ffc2a4b88c)、[公开 API](https://huggingface.co/api/models/bullerwins/translategemma-27b-it-GGUF?blobs=true)

| 精度 | 精确文件名 | 字节数 | GB／GiB |
| --- | --- | ---: | ---: |
| Q8_0 | `translategemma-27b-it-Q8_0.gguf` | 28,707,987,488 | 28.708／26.74 |
| Q6_K | `translategemma-27b-it-Q6_K.gguf` | 22,166,989,472 | 22.167／20.64 |
| Q5_K_M | `translategemma-27b-it-Q5_K_M.gguf` | 19,271,690,912 | 19.272／17.95 |
| Q4_K_M | `translategemma-27b-it-Q4_K_M.gguf` | 16,546,704,032 | 16.547／15.41 |
| Q4_K_S | `translategemma-27b-it-Q4_K_S.gguf` | 15,674,071,712 | 15.674／14.60 |
| Q3_K_L | `translategemma-27b-it-Q3_K_L.gguf` | 14,543,477,408 | 14.543／13.54 |

16.55 **GB** 的 Q4_K_M 文件确实小于 16 **GiB**，不能说“仅权重就超过 16 GiB”；但剩下约 0.59 GiB 尚未扣除桌面、KV cache 与缓冲，全 GPU 不应作为稳妥建议。Q4_K_S 余量也偏紧；短上下文、小 batch、量化 KV 等设置可能改变结果，需本机实测。

若坚持试 27B，可将 [Q3_K_L](https://huggingface.co/bullerwins/translategemma-27b-it-GGUF/blob/648ab470301440606384471ef4edb1ffc2a4b88c/translategemma-27b-it-Q3_K_L.gguf) 作为探索候选。它不是本次最佳翻译质量的结论；建议先用 12B Q8 建立对照。CPU／RAM offload 可拓宽“能启动”的范围，性能与全 GPU 路线需分别报告，不能混用。

## 引擎与模板边界

原生 Windows GGUF 可考虑 llama.cpp 的 Windows CUDA 路线；本次只核查其公开文档，没有核验用户已安装版本或 RTX 5080 实测结果。[Windows 与 CUDA 构建](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)

TranslateGemma 原始模型卡写 **2K tokens 输入上下文**。GGUF 元数据或 Gemma 3 基础配置展示更长上限，不能直接解释为翻译质量在该长上下文获得验证；本次建议小窗口纯文本翻译。其官方模板要求 user content 是恰好一个条目的列表，带 `source_lang_code`、`target_lang_code`、`type` 和待译 `text`；只支持 user／assistant。下载后需要确认应用是否正确渲染这个翻译专用模板，不能只判断 GGUF 是否加载成功。[12B 官方输入与模板](https://huggingface.co/google/translategemma-12b-it)、[27B 官方模型卡](https://huggingface.co/google/translategemma-27b-it)、[既有接口说明](2026-10-05-translategemma-12b-local-translation.md)

llama.cpp server 支持从模型元数据取模板，以及通过 `--jinja`／`--chat-template-file` 指定模板；接口与参数应按实际版本核验。先检查 `/apply-template` 或实际渲染 prompt 中语言代码与译文任务，再做一条短文本 smoke test。[server 模板与预渲染接口](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)

上述建议适用于纯文本，因此没有将图像投影／视觉部分额外文件计入下载清单。字幕翻译如需图像输入，须单独核查所选 GGUF 的图像资产、运行支持与额外显存预算。

相关：[前次三模型比较](2026-10-05-local-translation-model-comparison.md)。本次没有新增项目功能或改变既有 STT 模型选择。
