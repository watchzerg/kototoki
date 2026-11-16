# 03 extract 诊断：按级别统计解码错误、限制日志体积

Status: resolved
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

### 2026-11-16 方向已定（用户拍板）

1. **ffmpeg 日志级别**：`derive_command` 改用 `-loglevel level+verbose`，每行带级别标签；`parse_compensation` 的正则不锚定行首，不受影响。
2. **流式读取 stderr**：边读边统计、边写 `extract.log`，不再把整段 stderr 读进内存。
3. **统计内容**：按级别计条数（error、warning）；按消息类型计数（去掉地址与数字后归一），每类留首条样例。不推算"真实声道元素缺失帧数"（只对立体声好做）；不另算丢包时长（丢包造成的时间戳间隙已由 `aresample=async=1` 补齐并计入 `net_padding_s`）。
4. **`extract.log` 写法**：命令行、ffmpeg 头部信息、swr 补偿行、结束统计行全部保留；error／warning 行只留前 100 条与后 100 条，中间写省略条数；verbose 行不逐行写，末尾附按类型的计数表。不加写全量原始日志的开关。
5. **诊断落点**：计数写进 `probe.json` 的 `extract.diagnostics`（产物契约变化，先改模块页）；error 条数 > 0 的文件在运行日志里各写一条 **WARNING**。判失败与阈值留给 04。
6. **不升 `MEDIA` 版本**：日志级别与日志格式不在 `recipes.MEDIA` 里，PCM 不变；已有工作目录跳过 extract，不补 `diagnostics`。03 的诊断只写不读，不需要兼容旧数据；04 若要读再定。
7. **现有日志**：`.local/work/jav_best_copy-15fff3e12253/` 下各工作目录的 `extract.log` 直接删除（只删这个文件）；封存目录 `D:\jav_best_copy_work\` 不动。

## Answer

2026-11-16 已实现：
- `media.derive_command` 改 `-loglevel level+verbose`；`derive_pcm16k` 经 `_run_decode` 用 `Popen` 流式读 stderr，`digest_decode_log` 边读边写精简的 `extract.log`、按级别与类型计数（逐字重复的 verbose 行按原文缓存，只计条数，上限 5 万条）。swr 补偿样本数改为边读边累加，`parse_compensation` 只从保留行里取结束统计，结果不变。
- `Extract.diagnostics` → `probe.json` 的 `extract.diagnostics`：`levels`、`decode_errors`（ffmpeg 结束统计）、前 20 类 error／warning `messages`（`level`、`count`、`pattern`、`example`）。有 error 行时 `Extract.warnings` 加 `ffmpeg reported N error line(s) while decoding; see extract.log`，编排照常写成运行日志 WARNING（跳过 extract 时从 `probe.json` 重放）。
- `MEDIA` 不变（仍 `media-pcm16k-v2`），PCM 不变。
- 文档：`docs/architecture/modules/config-and-media.md`（"解码日志"一段；为守住 12000 字预算顺带压缩了几处措辞，内容不变）。
- 测试：`tests/core/test_media.py` `DecodeLogTests`（刷屏 verbose 只计数、结束统计与 swr 行保留并供补偿解析、error／warning 前后各 100 条、≤200 条全写、类型排序与上限、缓存溢出后计数不丢、`\r` 进度行与无级别行）；`tests/full/test_media_ffmpeg.py` `DecodeLogTests`（真实 ffmpeg：干净片段 0 错误且结束统计保留；确定性损坏的 AAC 报出 `decode_errors` 与告警）。
- 离线验证（产品 `probe` + `derive_pcm16k`，封存的 `audio.m4a`，纯 CPU）：

  | work_id | 原 `extract.log` | 新 `extract.log` | error 行 | warning 行 | `decode_errors` |
  | --- | --- | --- | --- | --- | --- |
  | d99fbd9dfb8d（正常） | — | 17 KB | 0 | 0 | 0 |
  | 6a3f71d9853f（verbose 刷屏 3668 万行） | 1.96 GB | 74 KB | 87 | 10 | 37 |
  | 7c97f3c8abd1（最严重） | — | 164 KB | 158314 | 1364220 | 63923 |

- 决定 4 的修订（2026-11-17，用户拍板）：swr 补偿行原定全部保留，最严重文件因此仍有 40 MB；改为与 error／warning 一样留前后各 100 条（样本数全数累加），该文件降到 164 KB，补偿统计与改前逐位相同。
- 耗时：精简本身几乎不加时（1 h 切片：只读管道 64 s，读管道并精简 62 s）；慢在 ffmpeg 自己输出数百万行 verbose（同一切片 stderr 丢弃 24 s、写文件 104 s）。旧实现同样整段走管道，因此不是回归；要拿 swr 与结束统计就得开 verbose。
- 自动检查：`just test`（766）、`just check`、`just docs-check` 通过；`just test-full`（19）通过。
