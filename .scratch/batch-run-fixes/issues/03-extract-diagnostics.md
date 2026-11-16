# 03 extract 诊断：按级别统计解码错误、限制日志体积

Status: needs-triage
Type: task
Blocked by: —

## 现象

1. **调试信息被当成错误**：15 个文件的 `extract.log` 里各有约 25 万～67 万条 `[aac @ ...] ChannelElement X.Y missing`，排查时一度判为"解码错误洪流"。用 `-loglevel level+verbose` 重解码其中一个文件的归档音轨确认，这条消息是 **`[verbose]` 级**；含义是之前某个坏帧让解码器误分配了多余的声道元素，之后每帧都提示"该元素本帧没出现"。真实的 `[error]` 级消息（`Error submitting packet to decoder`、`channel element N.N duplicate`、`Reserved bit set` 等）每个文件只有 75–244 条，真实立体声元素缺失仅 0–15 帧。
2. **日志无上限**：`derive_pcm16k` 把 ffmpeg 的 verbose stderr 整份写进 `extract.log`（`media.py` 约 410–412 行）。单个文件最大 2.2 GB，本批工作目录里 `extract.log` 合计约 20 GB，其中绝大部分就是上面那条 verbose 消息。
3. 同时 stderr 是 `subprocess.run(capture_output=True)` 整段读进内存的字符串（`_run`），GB 级时内存占用也是问题（本批没出事，但没有保护）。

## 原因

- `derive_command` 用 `-loglevel verbose`（为了拿到 swr 的补偿报告 `adding/discarding N audio samples`，`parse_compensation` 依赖它），但没有加 `level` 前缀，事后无法按级别区分。
- 程序目前不统计解码错误，人工排查只能 grep 全文，看到行数就误判。

## 影响

- 无法从日志判断"解码到底坏了多少"；真正严重的（有个文件真实错误 10 万条以上、立体声元素缺失 32 万帧）和无害的混在一起。
- 磁盘：一个 232 文件的批次光日志就 20 GB。

## 候选方向（待讨论）

- ffmpeg 改用 `-loglevel level+verbose`，每行带 `[error]`/`[warning]`/`[verbose]` 标签；程序统计 error/warning 条数（以及可推算的丢包时长），写进 `probe.json` 的诊断字段，超阈值时告警（与 04 衔接）。
- `extract.log` 落盘前压缩：同类行（去掉地址和数字后）合并计数，只保留首尾 N 行、全部 error 行、补偿事件；或流式读 stderr 边读边汇总，避免整段进内存。
- `parse_compensation` 需要的 swr 行必须保留（或改为流式解析时直接累加）。
- 改变 `extract.log` 的格式与 `probe.json` 字段 → 先改模块页；抽取配方 hash 是否受影响要核实。

## 证据

- 封存目录各文件的 `_samples/extract-log-sample.txt`（消息类型计数、真实错误样例）。
- 15 个"洪流"文件中 9 个未封存，work_id 见台账 A2；未封存的在 `.local/work/jav_best_copy-15fff3e12253/`。
- 台账 §A2、§A3 与"2026-11-16 复查"。

## Comments
