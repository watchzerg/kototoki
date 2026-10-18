# 同一句话小组内语序重排：划组统计与 v8 离线工具（reorder_groups）

纯 CPU、不加载模型、不占 GPU。划组规则 R2+ 的唯一实现在 `translation_v3/batching.py`（`sentence_groups`、`sentence_joined`、`ends_sentence`），本目录只导入它。结论与口径见[划组离线统计](../../docs/research/2026-10-18-reorder-group-offline-stats.md)与 [v8 研究文档](../../docs/research/2026-10-18-group-reorder-v8.md)。

只导入 `translation_v3`（配方、`build_batches`、划组、`load_run_translations`）与 `scene_batching_v6.sim7`（dev 与产品 `ja.srt` 的加载），不修改它们。`.local/` 里的 dev 集、产品 `ja.srt` 与 run 目录只读；`--json` 输出放 `.local/` 下，不入库。

| 脚本 | 作用 |
| --- | --- |
| `stats.py` | 在 `dp10-cut` 的包内按停顿门槛与句末标点划组（R1、R2、R2+），统计小组大小、被切点截断的比例、行尾标点与门槛敏感性 |
| `checks.py` | v8 §4.4 重排率与 §4.5 显示校验器：读一个或两个 run 目录的译文与场景时间，按配方切包、包内 R2+ 划组 |
| `coverage.py` | v8 票据 01：`grp1` 注入 `groups` 的包比例与每包输入 token 增量 |

```bash
PYTHONPATH=. python -X utf8 -m experiments.reorder_groups.stats --local-root <有 .local 的 checkout>/.local [--json <输出.json>]
PYTHONPATH=. python -X utf8 -m experiments.reorder_groups.checks --local-root <...>/.local --set dev|product --recipe grp1 \
    [--control <对照 run 目录>] [--candidate <候选 run 目录>] [--gap 1.0] [--json <输出.json>]
PYTHONPATH=. python -X utf8 -m experiments.reorder_groups.coverage --local-root <...>/.local --validate <run 目录> [--json <输出.json>]
python -X utf8 -m unittest discover -s experiments/reorder_groups -t . -p "test_*.py"
```

## 重排率与显示校验（`checks.py`）

- 小组：按 `--recipe` 切包（配方带 `groups` 时用其门槛，否则用 `--gap`），所以 `dp10-cut` 对照与 `grp1` 候选的小组完全相同。只看两侧 run 都覆盖的场景；任一侧缺译文（失败场景）的组跳过并计数。
- 字数：去掉空白与 Unicode 标点／符号（P*、S* 类）后的字符数。
- 重排率：多 cue 组内各条字数占比向量的 L1 差 ≥ 阈值记为重排，报 0.1／0.2／0.3，主阈值 **0.2**。依据：两条都逐 ID 归属、只换了提示或切包的同 seed run（v4 `c0` 对 `b10-joint`、v7 `b10-joint-ctl` 对 `dp6-grp`，各 3 seed）之间，≥0.1 的组占 22–30%（改写噪声为主），≥0.2 占 1.6–6%，≥0.3 占 0–2%；0.2 把噪声压到个位数、仍能看到"一两个字的成分挪到相邻行"。另报译文逐字不同的多 cue 组比例（上界；上述严格对严格的配对里已达 85–94%，区分力很弱），以及单条组 cue 的逐字不同条数，按所在包有无多 cue 组分开（无组包的 prompt 与对照逐字相同，固定 seed 时应为 0；有组包换了 joint 句，单条组也可能变）。
- 显示校验：每条 cue 读速 = 字数 ÷ 时长（秒），报 p50／p90／p99 与读速 > **9 字/秒** 的 cue 比例。阈值取 Netflix 简体中文字幕规范的成人节目上限（9 字/秒，儿童 7 字/秒）；本仓库没有自己的读速规范。上述严格配方在 dev 上 p50 约 4.4–4.8、p90 约 6.3–7.3、p99 约 8.4–11.7 字/秒，超过 9 字/秒的 cue 约 0.4–2.2%。占比偏差：多 cue 组内每条"字数占比 − 时长占比"绝对值的最大者 ≥ **0.3** 记为失衡组（§4.5 指定）；严格配方上约 0–2.5%。缺时间戳或时长 ≤0 的 cue 不计读速，含这类 cue 的组不计偏差。

## 注入覆盖与 token 增量（`coverage.py`）

- 每个 `dp10-cut` 批次分别按 `dp10-cut` 与 `grp1` 渲染完整 prompt，差值拆成"joint 句 v1→v2"与"groups 行"；并报含多 cue 组（即注入）的包比例与多 cue 组覆盖的 cue 比例，以及 `grp1` 超出输入上限 4032 的批次数。
- token 计数：从翻译 GGUF 的文件头读 `tokenizer.ggml.*`（不读权重），按 llama.cpp `hunyuan-dense` 预分词规则用 `tokenizers` 重建 BPE；`--validate` 用已有 run 的 `/tokenize` 交换记录（服务器返回的 token ID，即 translation_v3 的计数方式）逐 ID 核对，结果写在输出的 `tokenizer_check`。
