# 03 L1 门：主 seed 20261011 三臂各 1 run、全集裁判、三组配对与关门判定

Status: resolved
Type: task
Blocked by: 02

## 执行记录

- 2026-10-21 claimed。启动前 GPU 空闲、无锁。顺序生成 `dp10-cut`、`qwen-narrow`、`qwen-wide`（seed 20261011，块 0：14 场景、1844 条评分 cue、218 包）。三个 run 均 complete、单 session、无重试、无失败。`check-batches --seed 20261011`：三臂 run 文件中的目标 ID 序列彼此相同且与计划相同。
- 全集裁判（`judge-run`，`claude-opus-5-5-mqm-v1`，每套 93 包，并行 4）：三套全部完成，未遇配额阻塞；标价 $10.11／$9.85／$9.77，合计 $29.72。
- `compare9`：三组配对 → `summaries/v9-{qwen-narrow,qwen-wide}-vs-dp10-cut.json`、`v9-qwen-wide-vs-qwen-narrow.json`。
- 次要终点：`analyze9 names|leak|reading --seeds 20261011` → `summaries/v9-names-s20261011.json`、`v9-leak-s20261011.json`、`reading/qwen-narrow-vs-dp10-cut-s20261011.json`。
- 人工阅读委派给子 agent（opus，只读，写 `reading/manual-s20261011.json`），主会话抽查 1 包（`W03_E001-b0014` 的否定命令被 Qwen 译反）属实。

## 方法细节

- 专名错误抽取：裁判错误的 `evidence_zh` 命中 `人名|名字|姓名|称呼|译名|名称|专名|角色名|昵称|地名|音译` 即计（任何类别）。不一致率：`quality_v5.consistency.analyze_work` 在每作品已覆盖的 cue 上按窗口顺序跑（不做替换），类别内作品等权。
- 泄漏检测：每个宽包目标 cue，取其只读邻文参考中文的汉字 3-gram 与数字串，去掉本 cue 参考中文／日文里已有的；某臂译文含其一即标记。三臂都用同一组宽邻文检测，narrow 与对照给出偶然重合率。只在 wide 命中的 19 条人工分类。
- 人工阅读：主 seed 上 `qwen-narrow` 与 `dp10-cut` 包内 accuracy 惩罚差绝对值最大的各 10 包（剧集、电影）。

## 结果（主 seed，单 run；Δ = 候选 − 对照，CI90 窗口 bootstrap）

| 配对 | 剧集 accuracy Δ | 电影 accuracy Δ | 关门 |
| --- | --- | --- | --- |
| qwen-narrow − dp10-cut | −0.091［−0.176, −0.008］ | −0.178［−0.271, −0.086］ | 否 |
| qwen-wide − dp10-cut | −0.162［−0.243, −0.081］ | −0.160［−0.252, −0.073］ | 否 |
| qwen-wide − qwen-narrow | −0.071［−0.138, −0.005］ | +0.018［−0.052, +0.089］ | — |

对照水平：剧集 0.507、电影 0.489。分项（narrow／wide 对对照）：mistranslation、addition、wrong-referent（电影）、major+、critical 下降；**unnatural 上升**（narrow 剧集 +0.040［+0.022, +0.059］、电影 +0.018；wide +0.022／+0.014），fluency 总分 narrow 剧集显著变差；register 略好；cue-attribution 三臂均为 0。

专名：名称相关裁判错误 dp10-cut 24 条（剧集 12、电影 12）、narrow 29（21、8）、wide 28（19、9）；不一致率（类别均值）对照 0.048、narrow 0.044、wide 0.039。

泄漏：标记率 wide 3.4%／4.2%（剧集／电影），narrow 2.9%／3.7%，对照 4.0%／4.9%——不高于偶然重合；wide 独有 19 条人工分类：真泄漏 0、合理补全 4、误报 15。

人工阅读 20 包：Qwen 更好 17（剧集 8、电影 9）、Hy 更好 2、各有问题 0、裁判争议 1；裁判方向与阅读一致 19／20。Hy 失分集中在极性反转、主语／指代错、方言与片假名误读（把外来词或专名音译成无意义字串）、补完未完句；Qwen 的问题是翻译腔、生硬直译与句末语气词，致命错较少。

代价：墙钟 Hy 294 s、narrow 847 s（2.9×）、wide 913 s（3.1×）；载入 8.1／5.1／5.2 s；生成 194／59.9／59.6 tok/s；输入 token 141K／150K／293K；输出 37.0K／43.8K／44.1K；显存峰值 15875／12740／13249 MiB；重试、降级、交付失败均 0。

## 预算

GPU run 4／10；裁判 $29.72／$100。

## Answer

**两个 Qwen 臂都未关门，且在单 seed 上两类 accuracy 都显著好于 Hy-MT2 dp10-cut**（narrow 剧集 −0.091、电影 −0.178；wide −0.162／−0.160；相对对照约 −18% 到 −36%）。代价是 fluency 中 unnatural 显著上升、墙钟约 3 倍。宽邻文相对窄邻文剧集显著改善、电影无差异；无泄漏证据。人工阅读 17／20 支持 Qwen。按 §5 进入 04（两个存活臂与对照补 seed 20261012、20261013）。单 seed 结论不作判定。
