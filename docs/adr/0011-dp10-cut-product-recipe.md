# ADR-0011：产品翻译配方改为 dp10-cut-degrade-v1

状态：已接受。  
日期：2026-10-18。  
替代：[ADR-0007](0007-bilingual-subtitle-pipeline-architecture.md) 决定 4 与 [ADR-0010](0010-dp10-cut-translation-flow-baseline.md)"后续"中关于产品配方 `b10-joint-degrade-v1` 的部分。[ADR-0006](0006-b10-joint-translation-flow-baseline.md) 的 joint 提示、[ADR-0005](0005-apex-i-compact-translation-baseline.md) 的模型、引擎、采样（`official30b-cached-v1`）、context 与运行时参数，以及 ADR-0007 的三级降级（拆批→单条→保留日文）**全部保持不变**。  
范围：产品包 `kototoki/translate/` 的翻译配方。研究侧基线仍是 ADR-0010 的 `dp10-cut`，本决定只是把它同步到产品。

## 决定

用户裁定把研究侧已采纳的 `dp10-cut` 切包与邻文规则合并到产品：

- 产品配方改名 `dp10-cut-degrade-v1`：字段与 v3 `dp10-cut` 相同（`gap_pack` 即 ADR-0010 的全部参数），只把 `fixed.overflow` 换成 `degrade-10-5-1-keep-source`。与 `b10-joint-degrade-v1` 对 `b10-joint` 的关系完全相同。
- 切包与邻文按 ADR-0010：每批待译 ≤10 条、可见 ≤12 条，动态规划选切法，切点按停顿分级加罚，≥20 s 必切；前一条邻文在停顿 <5 s 时可见，后一条只在 <1 s 时可见。停顿取自 `ja.srt` 自身的时间轴，只比较长短，不做坐标换算。
- 降级的子批次（前后两半、单条）与原批次用同一条邻文规则；拆法不变。
- 不迁移旧结果，不加兼容开关：新配方名另起 run 子目录，旧目录保留。`RECIPE_HASH` 变化使所有已交付影片的 translate 阶段身份过期，下次整批运行会对它们重译并重新发布（用户改过且非 `force` 的最终文件照常被发布前置判定挡住）。用户 2026-10-18 明确接受这一代价。

## 身份与入口

- 配方：`kototoki/translate/recipes.py` 的 `DP10_CUT_DEGRADE_V1`（`PRODUCT`），hash `086754ca751365c21840742511bf39eaa621b8fc2f5a630372f22661fc86158e`；同文件 `DP10_CUT` 的 hash 必须等于 v3 `dp10-cut` 的 `ee72ce6683c89e5a1f83fd7ba99f54f3683966deed0e526c193780ad8c500b70`，证明移植没有改身份。`b10-joint`（`2ba68054…0969a`）与 `b10-joint-degrade-v1`（`994c0d03…95fe`）保留并钉住，作旧 run 目录的身份对照。全部由 `tests/test_translate_recipes.py` 固定。
- run 目录：`translate/srt-<sha12>/dp10-cut-degrade-v1__s<seed>/`。
- 入口不变：`python -m kototoki`，翻译阶段自动使用新配方。

## 证据与已知代价（如实记录）

- **质量证据与 ADR-0010 相同：没有。** 没有裁判对比；质量按 ADR-0010 的推定（介于 dp6-grp 与 b10-joint 之间、切点偏向停顿）。v8 对包内语序的探索已关闭，不影响本决定。
- 产品 `build_batches` 与 v3 `dp10-cut` 在同一 SRT 上切包、邻文、提示与请求逐字节相同（`tests/test_translate_recipes.py`，含随机场景）。
- 两部整片现有 `ja.srt`（HF II／III × w0／x0，`.local/bilingual-fullfilm-08/`）离线切包：

  | 文件 | 条数 | 请求 b10 → dp10 | 平均每批 | 跨 ≥10 s 的批 | 切点在 ≥1 s 停顿 | <6 条的批 | 可见前邻／后邻 |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | HF II w0 | 1056 | 106 → 143 | 9.96 → 7.38 | 47% → 19% | 70% → 94% | 0 → 24% | 49／9 |
  | HF III w0 | 1188 | 119 → 147 | 9.98 → 8.08 | 55% → 24% | 69% → 92% | 0 → 10% | 57／11 |
  | HF II x0 | 1154 | 116 → 150 | 9.95 → 7.69 | 44% → 19% | 61% → 97% | 1% → 19% | 59／5 |
  | HF III x0 | 1263 | 127 → 152 | 9.94 → 8.31 | 50% → 24% | 62% → 93% | 1% → 9% | 61／11 |

  没有批次跨 ≥20 s 停顿。请求数增加约 20–35%；因切点多落在 ≥1 s 停顿上，可见的后邻由每批 1 条降到几乎没有。
- 真实运行（2026-10-18，`python -m kototoki .local/bilingual-fullfilm-08/w0.toml`，两部影片经编排器整批运行；STT 产物因票据 10–12 的身份变化一并重跑）：HF III 1219 条 → 147 批（平均 8.29 条），单 session 147 次请求全部一次接受，翻译墙钟 200 s；HF II 1099 条 → 149 批（平均 7.38 条），149 次请求全部一次接受，但第 96 批起生成速度由约 175 tok/s 跌到约 4 tok/s 并持续到结束，翻译墙钟 2906 s。两部降级批次 0、回退 cue 0、无重启，`zh.srt`／`ja-zh.srt` 全部发布。慢化期间 server 峰值显存 15955 MiB（启动前空闲 15263 MiB），请求形状与快的批次相同；最可能是显存触顶后回落到系统内存（模块页已记的桌面显存漂移限制），**与配方无关但未验证**。

## 后续

- 回退 cue 与降级在真实数据上的表现随整片运行记入票据与模块页。
- 若之后要验证质量，以 `b10-joint-degrade-v1` 的旧 run 目录为对照（同一 `ja.srt`、同 seed），确认须用全新隔离的集合。
