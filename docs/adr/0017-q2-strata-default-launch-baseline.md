# ADR-0017：Q 线基线 Q2（Q1 配方规则＋Strata Flash-Next，不加参数启动，DFlash2）

状态：已接受。合并整理于 2026-11-08（并入 ADR-0016 的有效条款；历次变更见[决定索引·演进链](INDEX.md#演进链)，原文见 Git 历史）。自 2026-11-08 起 Q2 为唯一翻译基线（[ADR-0018](0018-q2-sole-translation-baseline.md)），第 2 点扩展到所有新的翻译测试。  
范围：固定 Q 线当前基线 Q2 的身份。不改产品 `kototoki/`（产品继续用 H0），不决定产品是否改用 Q 线，不开封确认集。

## 决定

1. Q 线当前基线为 **Q2**：Q1 配方规则＋翻译模型 Strata 上的 Qwen3.8-Flash-Next IQ3_S，服务用**不带任何参数**的 `strata launch`（自动检测出的最优配置），草稿器 **DFlash2**，不用 MTP。
2. 以后新的 Q 线测试默认以 Q2 为对照（框架规则见 [ADR-0015](0015-two-translation-baselines.md)）；引用 Q1、Q0 或 F1 须写明。
3. [ADR-0008](0008-no-multi-translation-selection.md) 对 Q2 同样适用。

## 身份

Q2 是**一条组配方的规则**，不是固定 hash：对每个输入先拼出该输入的 Q1 配方，再改两处，其余不变。

**Q1 配方规则**（Q2 的内核）：

- 基础配方：Q0＝`qwen-wide`（[ADR-0015](0015-two-translation-baselines.md)），切包、邻文、提示与采样都不变。
- 建表：产品 `kototoki/names` 的建表（[ADR-0014](0014-name-consistency-in-product.md)），提示 `build-table-prompt-v5`，`BUILD_RECIPE_HASH` 为 `5b8d1b76da757bb26aa3d3fb894c1963935a308b6ef4eb7c75edeaa2d44c9e50`，与产品同一模型、同一参数；建表输入就是待翻译的那份日语。
- 注入：`qwen_options.names = {"filter": "window", "tables": {work_id: rows}}`，表头 `qwen-name-table-v1`。`rows` 只取表里 `confidence: high` 的实体；每个实体的每个 `forms[]` 取一行 `{source: form.ja, translation: form.zh}`；按 `ja` 去重，跳过 `ja` 或 `zh` 为空的写法。取法即 `experiments/scene_batching_v6/names11.py` 的 `product_tables("high")`（产品 ASR 源）与 `nstar_tables("high")`（dev 源）。
- 没有事后替换：译文直接作为结果，不再跑 `names` 替换（注入后再替换与只注入的输出逐字节相同）。
- 不按输入来源区分：产品 ASR 源与 dev 干净源一律用同一条规则。
- 引用 Q1 对照时的实例：产品 HF II／III 的 `q0-names-high`，hash `c10e143a65c50277daede28a2f3d3e79adc0db53b1db6a4398e0c9f6720f30e8`；dev 15 部的 `qwen-names-dev-high`，hash `9c444d3c…`。

**Q2 的两处改动**：`model` 设为 `qwen3.8-flash-next-iq3_s`；`qwen_options` 加 `strata_launch: "default"`。规则实现是 `experiments/scene_batching_v6/v12.py` 的 `strata_recipe_data(q1, name, comment, launch="default")`。采样仍是 `temperature 0.7, top_p 0.8, top_k 20`，seed 步长不变。

**服务**：Strata 0.2.12，引擎 build 0.1.58，在 PowerShell 里运行不带参数的 `strata launch`。2026-11-08 的 `--plan` 显示它在本机解析为：模型 IQ3_S、上下文 128K；图片读取器放 CPU，并发按显卡自动适配；投机解码 DFlash2；只允许本机访问，端口 8080，tune 为 skip；无需下载。本机 quick tune（2026-11-07，288 s）结果为 `default_confirmed / already_fastest`，`settings.args {}`，默认配置已是最快。

**请求**：走 chat completions，不用 grammar，思考关闭；每包最多试两次（seed 与 seed＋1）；某包两次都失败时只空出该包的 cue，整片照常交付。

**接入检查**：`strata.probe(port, "default")` 依次核实版本、端口 8080 上只有一个 ready 的本机实例、run config 里的模型名与 `--max-context 131072` 与草稿器 DFlash2、`/v1/models`、`/v1/status` 显示原生上下文 131072，不符就拒绝运行。它不检查 preset 名，也不限制并发数。

**配方身份**：`recipe_hash` 记录"不加参数启动"及上面解析出的取值（`strata.DEFAULT_RESOLVED`），每次运行在 `runtime/session-NN/strata.json` 另记实际 run config 与并发数。v11 输入上的实例只算出 hash，配方文件未写到磁盘：产品 HF II／III 为 `86b61ec93da4ad38fc0ff709bb973a8b659660ab6dc1b3be08f068b91be908b7`（由 `q0-names-high` 得到），dev 15 部为 `4c3d0f70a94e43207dbe439893284d078993a041bf5ebb3dd378aefeb42b0499`（由 `qwen-names-dev-high` 得到）。

**运行顺序**：① 用 llama-server 建表，建完停掉（Strata 与 llama-server 不得同时驻留）；② `strata launch`；③ `python -m experiments.translation_v3 translate-srt --recipe <Q2 配方> …`（只连接服务，不负责启动）；④ `strata launch --stop` 并核实显存已释放。

## 依据

质量证据来自[第十二轮（v12）](../research/2026-11-08-strata-flash-next-v12.md)的 **F1**：配方规则与 Q2 相同，启动配置不同（`kototoki-translate` 预设，上下文 32K、并发 1、关闭图片读取器、草稿器 MTP）。对照为 Q1，裁判 profile 不变，Δ＝候选 − 对照，越小越好，括号内 CI90。

- dev：accuracy 剧集 −0.186［−0.231, −0.142］、电影 −0.126［−0.173, −0.078］，两类都显著改善。
- 产品 ASR 源：全体 −0.269［−0.340, −0.201］，三桶都显著改善；人名错误 79 对 89，差值上界 +0.0006，用户认定为边界噪声；不一致率 0.0175 对 0.0273。
- 可行性：1599 包交付失败 0，墙钟比 Q1 快 26–29%。
- Q1 的注入规则在产品 ASR 源上相对 Q0＋替换非劣（全体 −0.050［−0.116, +0.020］，人名相关错误 120 降到 72，不一致率 0.027 对 0.050）；在 dev 干净源上比 Q0 差（表里的错条目多数标 high），用户已知并接受。

## 约束与未关闭项

- **Q2 本身的启动配置没有跑过任何翻译**，以下为未验证推断：
  - 草稿器：投机解码在原理上只影响速度、不改输出分布，Strata 的实现未验证。
  - 内存：128K 上下文的 KV 与放在 CPU 的图片读取器会多占内存；v12 整机内存峰值已到 63.5／63.9 GiB，DFlash2 草稿器还多用约 0.8 GB 显存（v12 显存峰值 16.1／16.3 GB）；能否在本机稳定跑完整片需实测。
  - 并发：流水线每次只发一个请求，自动适配出的并发不改变请求内容，但并发批处理的数值路径可能不同；同 seed 本就不复现（v12 A/A 约 49% 的 cue 不同），噪声底更难估计。
- **第一次使用前建议先跑 smoke**（GPU 作业，须先问），看整机内存与显存峰值、首次格式失败数与交付失败数、每包耗时。若内存溢出或失败率明显高于 F1，是否退回 v12 的 `kototoki-translate` 启动配置由用户决定。
- **已知缺口**：给一份新的 SRT 生成 Q1／Q2 配方没有通用入口（`product_tables` 只读 `asr10.FILMS`，`nstar_tables` 只读 v10 的 dev 表）；在新输入上跑之前须补"给定 `name-table.json` → 写出 Q1 配方"的小工具并补测试。
- Q1 在 dev 上以其为对照时，对照本身的人名与指代错误偏多；其质量取决于产品建表质量，建表质量线是否另立项未裁定。
- 产品继续用 H0。Q 线进产品还需另行解决：新的"外部 OpenAI 兼容服务"后端与不用 grammar 时的失败路径；Q 链没有替换阶段而 H0 链有。这些须写进那时的 ADR。
