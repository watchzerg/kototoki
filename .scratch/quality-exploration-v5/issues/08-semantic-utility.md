# 08 语义效用函数替代 chrF

Status: resolved
Type: research
Blocked by: 07

## 范围

- 用本地 embedding（候选由执行会话从已有本地模型或小型多语 embedding 中选；权重按研究文档 §3 下载预授权条件自行下载，记录来源、许可与 sha256）计算样本间相似度作 MBR 效用，与 chrF 在同一批样本上比较选择结果与 MQM 分。
- 只换选择器，不换生成；N 取 07 的最优值。

## 预算

- 不新增真实生成，只在 07 的样本上换选择器；裁判只评选择结果不同的 cue 所在窗口。

## 完成标准

- 同样本下 chrF 选择 vs 语义选择的 Δ、SE、类别；选择器耗时；两者选中不同样本的比例。

## 文件所有权

`experiments/translation_v4/mbr.py` 扩展或 `experiments/quality_v5/`；研究文档。

## 执行记录

- 2026-10-16 claimed（07 已结题，N 取 8）。计划：
  - 模型：`BAAI/bge-m3`（MIT，revision `5617a9f6…`，2.29 GB，dense CLS 池化；中日英多语、中文语义相似度强），下载到 `.local/models/embedding-v5/bge-m3/`，manifest 带逐文件 sha256（`bge-m3-ready.json`）；本轮累计下载 9.5 GB（≤30 GB）。走 HTTPS（`HF_HUB_DISABLE_XET=1`）。根 `.venv` 已有 torch 2.11＋transformers 5.19，不装新包。
  - 选择器：`experiments/quality_v5/mbr_semantic.py`，同一批 mbr8 样本逐条选与其余样本平均余弦最高者（并列取最小序号），伪 run `mbr8s`，配方 = `derived_recipe(mbr8, "mbr8s", 8, "mbr-emb-bge-m3-cue")`。
  - 裁判只评不同的窗口：窗口内任一 cue（计分或上下文）的译文与同 seed 的 `mbr8c` 不同，就用 v4 `judge(reference=子集)` 判；其余窗口译文与上下文完全相同，复制 mbr8c 的判分（单独一个标明来源的合成包文件）。主比较 `compare --candidate mbr8s --control mbr8c`（同样本下语义 vs chrF），另报相对 b10-joint。

- 2026-10-16 10:25 下载完成：bge-m3 2.29 GB、9 个文件（`bge-m3-ready.json` 记逐文件 sha256）。
- 2026-10-16 10:28 v3 配方只接受 chrF 选择器（`recipes.py` 校验），伪 run 改按 07 早停的做法：沿用 mbr8c 配方与 hash（701c04a4…），只换 name，`pseudo.selector` 记 `mbr-emb-bge-m3-cue`。
- 2026-10-16 10:30 6 个 seed 派生 `mbr8s`（GPU 前核对无 gpu.lock、无 llama／python GPU 进程）：与 chrF 逐条选择选中不同译文的 cue 占 20.0–21.7%；每 run 7000–7700 条不同样本文本，embedding 1.5–1.8 s（首个 run 含模型加载 14.8 s）；显存未测。
- 2026-10-16 10:30 只判不同窗口（`experiments/quality_v5/diff_judge.py`）：按"计分 cue 或上下文任一不同"算 97% 窗口不同（上下文 13 条），几乎省不了；按票据"选择结果不同的 cue 所在窗口"只看计分 cue，约 67% 窗口不同，其余 33% 复制 mbr8c 判分（近似：这些窗口的上下文 cue 可能不同，上下文不计分）。
- 2026-10-16 10:53 dev 3 run 判完（每 run 59–63 包、448–475 s，无错误）。
  - `compare --candidate mbr8s --control mbr8c`（同样本下语义 vs chrF）：Δ −0.0138（剧集 −0.020、电影 −0.008），SE 0.0072，CI95 [−0.028, +0.000]，p 0.026，门槛全过，`promising`。
  - 相对 b10-joint：Δ −0.0351（剧集 −0.049、电影 −0.022），SE 0.0126，p 0.003，`promising`。
- 2026-10-16 10:54 判独立重复 seed（2026102x）3 run。
- 2026-10-16 10:58 选择器耗时（每 dev run，约 1700–1900 条 cue，CPU 单线程）：chrF 逐条 3.0–3.4 s；语义 = embedding 1.5–1.8 s（GPU）＋纯 Python 余弦选择 4.6–5.3 s（可向量化），模型加载约 13 s／进程。对比生成本身（mbr8 一个 dev run 1615 s）都可忽略。

- 2026-10-16 11:18 重复 3 run 判完（54–63 包、397–565 s，无错误）。
  - 语义 vs chrF（`--candidate-replicate --control-replicate --control mbr8c`）：Δ −0.0138（剧集 −0.015、电影 −0.013），SE 0.0093，p 0.064，门槛全过，`promising`；点估计与 dev 完全一致。
  - 相对 b10-joint：`--candidate-replicate` Δ −0.0444（p 0.0003）；再加 `--control-replicate` Δ −0.0381（剧集 −0.054、电影 −0.022），SE 0.0125，p 0.001，`promising`。
  - → **复现通过**，两类都为负。mbr8s 列为确认候选；确认集等 09、10 的 dev 筛选结束后统一建（Holm 家族一起检验，确认集只建一次、只开封一次）。
- 2026-10-16 裁判合计 6 run、364 包（约 $36），无错误、无阻塞；GPU 只有 embedding（约 25 s）。

## Answer

**结论：语义效用（bge-m3 余弦）在同一批 8 个样本上优于 chrF，dev 与独立重复 seed 都复现；`mbr8s` 列为确认候选，确认留到 09／10 筛选后统一做。**

| 比较（dev 3 seed） | Δ（剧集／电影） | SE | p | 判定 |
| --- | --- | --- | --- | --- |
| mbr8s vs mbr8c（dev） | −0.014（−0.020／−0.008） | 0.0072 | 0.026 | promising |
| mbr8s vs mbr8c（重复 seed，双方重复） | −0.014（−0.015／−0.013） | 0.0093 | 0.064 | promising |
| mbr8s vs b10-joint（dev） | −0.035（−0.049／−0.022） | 0.0126 | 0.003 | promising |
| mbr8s vs b10-joint（重复 seed，双方重复） | −0.038（−0.054／−0.022） | 0.0125 | 0.001 | promising |

- 选中不同样本的比例：cue 层面 20.0–21.7%；按计分 cue 计窗口层面约 64–67%。
- 选择器耗时（每 dev run）：chrF 3.0–3.4 s；语义 embedding 1.5–1.8 s＋余弦选择 4.6–5.3 s（纯 Python），模型加载约 13 s；相对生成（mbr8 约 1615 s／run）可忽略。生成成本与 mbr8c 相同（6.15 倍对照）。
- 裁判只评计分 cue 不同的窗口（约 2／3），其余复制 mbr8c 判分（上下文可能不同，属近似）；类别分值、critical、风险上界、交付门槛全过。
- 一致率（04 指标，不一致率相对 b10-joint）：mbr8s +0.006（dev）／−0.001（重复），与 mbr8c（+0.006／−0.001）相同，未触及 +0.02 护栏（`08/consistency.json`）。
- 未做：确认集未建（待 09／10）；显存未测（bge-m3 FP16，2.3 GB 权重）。
- 产物：`experiments/quality_v5/mbr_semantic.py`、`diff_judge.py`；模型 `.local/models/embedding-v5/bge-m3/`（MIT，revision `5617a9f6…`，sha256 见 `bge-m3-ready.json`）；run `.local/quality-exploration-v5/07/root/runs/mbr8s__*`；日志 `.local/quality-exploration-v5/08/`。

## Comments

- 2026-10-16 建票。
