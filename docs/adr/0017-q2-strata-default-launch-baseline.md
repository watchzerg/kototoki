# ADR-0017：Q 线基线改为 Q2（Q1 配方＋Strata Flash-Next，不加参数启动，DFlash2）

状态：已接受（2026-11-08）。  
日期：2026-11-08。  
部分替代：[ADR-0016](0016-q1-translation-baseline.md) 中"Q 线当前基线是 Q1"这一点。Q1 的身份定义（建表、只注入 high、不替换）**保持不变**，Q2 直接沿用；Q1 与 v12 的 F1 保留为可引用的历史身份。[ADR-0015](0015-two-translation-baselines.md) 的 H0 部分、"新测试须写明对照"的规则，以及 [ADR-0008](0008-no-multi-translation-selection.md)，对 Q2 同样适用。  
范围：只给 Q 线换基线并固定 Q2 的身份。不改产品 `kototoki/`（产品继续用 H0），不决定产品是否改用 Q 线，不开封确认集。

## 决定

[第十二轮（v12）](../research/2026-11-08-strata-flash-next-v12.md)结题，用户裁定 §8 第 6 项为 (b)，F1 成为候选。之后用户 2026-11-08 决定直接换基线，并给出两点要求：

- 草稿器用 **DFlash2**，不用 v12 里的 MTP；
- 用本机 Strata 当前的最优配置。不加参数时 Strata 就采用自动检测出的最优配置，所以**启动时不加任何参数**。

因此 Q 线的当前基线从 Q1 改为 **Q2**：Q1 的配方规则不变，翻译模型换成 Strata 上的 Qwen3.8-Flash-Next IQ3_S，服务用不带参数的 `strata launch` 启动。以后新的 Q 线测试默认以 Q2 为对照；引用 Q1、Q0 或 F1 时须写明。

## 身份

与 Q1 一样，Q2 是**一条组配方的规则**，不是一个固定 hash。规则如下：

1. 先按 [ADR-0016](0016-q1-translation-baseline.md) 的规则拼出该输入的 Q1 配方（建表 → 只注入 high → 不替换）。
2. 改两处：
   - `model` 设为 `qwen3.8-flash-next-iq3_s`；
   - `qwen_options` 加 `strata_launch: "default"`。
3. 其余不变：切包、邻文、提示、采样都与 `qwen-wide` 相同，采样仍是 `temperature 0.7, top_p 0.8, top_k 20`，seed 步长也不变。

`experiments/scene_batching_v6/v12.py` 的 `strata_recipe_data(q1, name, comment, launch="default")` 就是这条规则。

- **服务**：Strata 0.2.12，引擎 build 0.1.58。在 PowerShell 里运行不带参数的 `strata launch`。2026-11-08 的 `--plan` 显示，它在本机解析为：
  - 模型 IQ3_S，上下文 128K；
  - 图片读取器放在 CPU，并发按显卡自动适配；
  - 投机解码用 **DFlash2**；
  - 只允许本机访问，端口 8080，tune 为 skip；
  - 无需下载。

  本机做过一次 quick tune（2026-11-07，288 s），结果是 `default_confirmed / already_fastest`，`settings.args {}`：默认配置已是最快，没有需要额外加的参数。
- **请求**：与 v12 的 F1 相同：
  - 走 chat completions；
  - 不用 grammar，思考关闭；
  - 每包最多试两次（seed 和 seed＋1）；
  - 某包两次都失败时，只空出该包的 cue，整片照常交付。
- **接入检查**：`strata.probe(port, "default")` 依次核实以下几项，不符就拒绝运行。它不检查 preset 名，也不限制并发数。
  - 版本；
  - 端口 8080 上只有一个 ready 的本机实例；
  - run config 里的模型名、`--max-context 131072`，草稿器是 DFlash2；
  - `/v1/models`；
  - `/v1/status` 显示原生上下文为 131072。
- **配方身份**：`recipe_hash` 记录的是"不加参数启动"及上面解析出的取值（`strata.DEFAULT_RESOLVED`），每次运行在 `runtime/session-NN/strata.json` 里另记实际的 run config 和并发数。
- **在 v11 输入上的实例**：只算出了 hash，配方文件没有写到磁盘：
  - 产品 HF II／III：由 `q0-names-high` 得到 `86b61ec93da4ad38fc0ff709bb973a8b659660ab6dc1b3be08f068b91be908b7`；
  - dev 15 部：由 `qwen-names-dev-high` 得到 `4c3d0f70a94e43207dbe439893284d078993a041bf5ebb3dd378aefeb42b0499`。
- **运行顺序**：
  1. 用 llama-server 建表。建表结束后停掉，Strata 与 llama-server 不得同时驻留。
  2. 运行 `strata launch`。
  3. 运行 `python -m experiments.translation_v3 translate-srt --recipe <Q2 配方> …`（只连接服务，不负责启动）。
  4. 运行 `strata launch --stop`，并核实显存已经释放。
- **已知缺口**：沿用 ADR-0016——给一份新的 SRT 生成 Q1 配方，目前没有通用入口，Q2 也就同样没有。

## 证据（如实记录）

质量证据全部来自 v12 的 **F1**。F1 与 Q2 的配方规则相同，但启动配置不同：F1 用 `kototoki-translate` 预设，上下文 32K、并发 1、关闭图片读取器、草稿器 MTP。对照都是 Q1。

- **dev**：accuracy 剧集 −0.186［−0.231, −0.142］、电影 −0.126［−0.173, −0.078］，两类都显著改善。
- **产品 ASR 源**：
  - 全体 −0.269［−0.340, −0.201］，三桶都显著改善；
  - 人名错误 79 对 89，差值上界 +0.0006，用户认定为边界噪声；
  - 不一致率 0.0175 对 0.0273。
- **可行性**：1599 包交付失败 0，墙钟比 Q1 快 26–29%。

**Q2 本身的启动配置没有跑过任何翻译**，下面几点都是未验证的推断：

- **草稿器**：投机解码在原理上只影响速度，不改变输出分布，但 Strata 的实现没有验证过。
- **内存**：128K 上下文的 KV 和放在 CPU 的图片读取器都会多占内存。v12 时整机内存峰值已到 63.5／63.9 GiB，DFlash2 草稿器还会多用约 0.8 GB 显存（v12 显存峰值 16.1／16.3 GB）。Strata 会按显卡自动适配，但能否在本机稳定跑完整片，需要实测。
- **并发**：流水线每次只发一个请求，自动适配出的并发数不会改变请求内容；但并发批处理的数值路径可能不同。同 seed 本来就不复现（v12 A/A 中约 49% 的 cue 不同），这一点让配对比较的噪声底更难估计。

## 后果

- Q 线测试的默认对照换成 Q2。报告里写清用的是哪个输入的 Q2 实例、它的 hash，以及 `strata.json` 里实际观测到的并发数；dev 上的对照仍须同期重判。
- **建议第一次使用前先跑一次 smoke**（GPU 作业，须先问）。smoke 看三件事：
  - 整机内存和显存峰值；
  - 首次格式失败数和交付失败数；
  - 每包耗时。

  如果 smoke 内存溢出或失败率明显高于 F1，是否退回 v12 的 `kototoki-translate` 启动配置，由用户决定。
- v12 的 MTP 对 DFlash2 代价对比（v12 §8 第 5 项）不再单独立项，由上面的 smoke 和以后的运行记录代替。
- 产品继续用 H0。如果 Q 线将来进入产品，还需要另行解决两件事，并写进那时的 ADR：
  - 新的"外部 OpenAI 兼容服务"后端，以及不用 grammar 时的失败路径；
  - Q 链没有替换阶段，而 H0 链有。
