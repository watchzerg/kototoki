# ASR 静音概率测量（asr_nospeech）

[batch-run-fixes 票 09](../../.scratch/batch-run-fixes/issues/09-short-window-asr-overflow.md) 第二层的测量：逐窗取 Whisper 的 `no_speech_prob`，与 `asr.json` 已有的 `avg_logprob`、字速、窗口能量放在一起，看"静音概率高且置信度低 → 整窗丢弃"这条通行规则在不同阈值下拦下哪些窗口。

本包只读调用 `kototoki.*`，并复用 `experiments.asr_robustness_v14.common.gpu_lock`，不改产品代码。产物写 `.local/asr-nospeech/`，其中含窗口文字，不进 Git。

数据：

- 首次大批量运行的工作目录（`.local/work/jav_best_copy-15fff3e12253/`、`D:/jav_best_copy_work/`）：幻听多，没有参考字幕。
- 两部样本片 HF II、HF III（v14 的对照工作目录）：有参考字幕，用来查误杀——被拦下的窗口如果与参考 cue 在时间上重叠，就可能是真话。

做法：与产品相同的模型、特征和提示，编码后只解码一步（`max_length=1`、`return_no_speech_prob=True`）。`probe` 已核对过两点：63 个窗口的完整解码与产品 trace 逐 token 相同；单步解码与完整解码的 `no_speech_prob` 差值为 0。因此不必重跑约 10 小时的完整解码。

从仓库根目录运行：`.venv/Scripts/python.exe -X utf8 -m experiments.asr_nospeech <子命令>`。

| 子命令 | 作用 | 资源 |
| --- | --- | --- |
| `probe [--per-file N]` | 在 3 个文件上核对完整解码与产品 trace、单步与完整解码的 `no_speech_prob` | GPU |
| `measure` | 全部工作目录逐窗测量，每个文件写 `measure/<work_id>.jsonl`；已有的跳过，可续跑；持 `.local/gpu.lock` | GPU |
| `report` | 汇总为 `rows.jsonl` 与 `report.md` | 离线 |

## 结论（2026-11-18）

230 个文件、60392 个非空窗口，用时 92 分钟。`no_speech_prob`／`avg_logprob` 规则拦不住 Whisper 编出的结尾套话：Whisper 对这些套话很有把握，窗口越长静音概率越低。这条规则主要拦下的是「ああああ」类真实叫声；只看静音概率还会误杀歌词。因此该规则不进产品，产品改用整窗幻听句匹配，见 [ADR-0030](../../docs/adr/0030-asr-window-plausibility-guard.md)。数字见[票据 09](../../.scratch/batch-run-fixes/issues/09-short-window-asr-overflow.md) 的 Comments。
