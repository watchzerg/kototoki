# 产物交接

[跨模块流程](../collaborations.md)的子页：各阶段之间经工作目录交接哪些文件，以及日文 cue 为什么是 STT 与翻译的交界（原技术设计 §4、§5.1）。最终产物、发布与重做从用户角度见[中日双语字幕批量生产流水线](../../behaviors/bilingual-subtitle-pipeline.md#运行一批)；阶段顺序见[阶段链与调度](stage-chain-and-scheduling.md)。

## 产物：中间产物与最终产物

最终产物只有写在源文件旁的双语字幕，其余全在工作目录（ADR-0007「工作目录」）；工作根与 `<id>` 的组成见[运行一批](../../behaviors/bilingual-subtitle-pipeline.md#运行一批)，路径、身份与原子写的权威正文是[产物契约][art]。

```
<work_dir>/
  cache/                 HF_HOME／TORCH_HOME 与 model-verification.json，各目标目录共用
  <input_dir 末段名>-<sha12>/    <work root>
    lock、input.json、index.json、jobs-<stage>.json
    strata-sessions/     names 与翻译共用的 Strata session 证据
    run-<戳>.log、run-<戳>-<stage>.stderr.log
    <id>/
      probe.json、audio-16k.wav、extract.log
      vad.json、asr.json（cross 另有 asr-w0.json、asr-x0.json、asr-judge.json，只作审计）、align.json
      ja-cues.json 或 ja-embedded.json（内嵌字幕路径）、ja.srt
      name-table.json、names/transport/…
      translate/srt-<sha12>/<配方名>__s<seed>__n<表sha12>/   翻译 run，可续跑
      publish/<stem>.ja-zh.srt   发布字幕的工作目录副本
      published.json       审计记录，不参与是否发布的判定
      failure.json         任一阶段失败时写
```

交接规则：

- **每个产物带输入身份与配方 hash**；身份匹配即跳过，不匹配时原地原子替换（`translate/` 按键另开目录，旧目录保留）。身份的组成规则在[产物契约][art]，各阶段的期望身份在[阶段计划][plan]。
- **坐标系**：`vad.json`、`asr.json`、`align.json` 用 WAV 本地坐标，offset 只在 ja-cues 阶段加一次，cue 时间即最终 SRT 时间（完整约定见[产物契约][art]）。
- 发布、产物保留、专名表人工校对与日志规则是用户可见行为，见[中日双语字幕批量生产流水线](../../behaviors/bilingual-subtitle-pipeline.md#操作与可观察结果)。

## 日文 cue：STT 与翻译的交界

### 翻译输入为什么是 `ja.srt`

逐条翻译日文 cue，每条中文直接继承那条日文的编号与时间，双语合并只是拼接；翻译 ASR 窗口的整段日文需要把中文切回各句时间，没有可靠方法（[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)）。因此**cue 切分质量同时决定日文字幕可读性与翻译上下文**。切分规则见[日文 cue](../modules/japanese-cues.md) 与[切分规则](../../behaviors/bilingual-subtitle-pipeline.md#切分规则)。

[art]: ../modules/artifact-contract.md
[plan]: ../modules/stage-plan.md
