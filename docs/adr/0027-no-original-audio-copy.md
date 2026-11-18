# ADR-0027：不再流复制原始音轨

状态：已接受（2026-11-17，用户决定，起因 batch-run-fixes 票据 05）、已实现（同日）。替代 [ADR-0007](0007-bilingual-subtitle-pipeline-architecture.md) 第 7 点中间产物里的"原始编码音轨流复制"与第 8 点"流复制的原始音轨只作归档"，以及 2026-10-13 设计裁定"音频产物：原始编码流复制保留"（历史记录（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`））。
范围：产品包 `kototoki/` 的 extract 阶段产物。不改派生 WAV 的命令、`MEDIA` 配方与 hash、PCM 身份及任何下游配方。

## 决定

1. **视频输入也不流复制原始音轨。** extract 对视频与音频输入相同：只从输入容器解码派生 `audio-16k.wav`（命令不变），写 `extract.log`；不再写 `audio.<ext>`。删除 `media.extract_original`、`copy_command`、容器映射 `CONTAINERS` 与 `artifacts.AUDIO_COPY_STEM`。
2. **`probe.json` 的 `extract` 记录去掉 `audio_copy` 字段。** 续跑判定只看 `probe.json` 身份与 `audio-16k.wav`，从来不读该字段，因此已有工作目录照常跳过 extract；旧工作目录里留下的 `audio.<ext>` 不清理、不迁移。

## 依据

- **副本没有使用者。** 流复制产物从一开始就"只作归档"，模型输入直接从输入容器解码（容器带时间戳），没有任何阶段读它。ADR-0020 之后源文件留在原地、工作目录不交付，副本只是源文件里已有数据的重复。
- **它让可出字幕的文件整片失败。** 2026-11-12～15 的 232 片批次中，JUFD-732（work_id 084410474fc8）的 AAC 音轨有 3 个坏包：复制到 m4a 时 `aac_adtstoasc` 报 `Error parsing ADTS frame header!` 退出，`MediaError` 让整片判失败；解码路径能跳过坏包（台账记录对源文件 `-f null` 解码退出码为 0）。
- **它多读一遍源文件。** 这批从移动硬盘抽取约 4 h／232 片，瓶颈在 USB 盘 I/O；mp4 音视频交错存放，单抽音轨也基本读完整个文件。

## 考虑过的方案

- **复制失败降级为告警、继续派生**：保留副本的代价，只修失败。用户裁定：副本本身不需要。
- **先流复制到 `.mka`，后续从副本派生**：派生输入从容器换成副本，PCM 可能不再逐字节一致（mp4 编辑列表里的 AAC priming、Matroska 毫秒时间戳取整、采样率纠正依据的时间戳），需要新 `MEDIA` 版本与验证；坏包在 Matroska 封装时可能同样触发 `aac_adtstoasc`，而副本成了必经输入后无法降级。未采纳。

## 验证

`just test`（core）与 `just test-full` 通过：视频输入（FLAC、大小端 PCM）的工作目录只有 `audio-16k.wav` 与 `extract.log`，批次编排的工作目录里没有 `audio.*`，`Extract` 记录不含 `audio_copy`。派生命令未改，`MEDIA` hash 的钉住测试不变。

## 未验证

- JUFD-732 本片重跑：源盘不在线，未复现；预期 extract 成功（解码可跳过坏包），坏包按 batch-run-fixes 03 记入 `extract.log` 与告警。
- 抽取阶段实际省下的时间：未测量。
