# 01 跨盘发布失败与审计顺序

Status: needs-triage
Type: task
Blocked by: —

## 现象

批次结束时 `[summary] 232 file(s): 0 published ... 232 failed`：除抽取失败的 4 个外，228 个文件全部在 publish 失败，错误一致：

```
OSError: [WinError 17] The system cannot move the file to a different disk drive:
'D:\...\.local\work\<root>\<work_id>\publish\<视频名>.ja-zh.srt' -> 'E:\...\<视频名>.ja-zh.srt'
```

双语字幕本身完整留在 `<work_id>/publish/`，sha256 与 `published.json` 一致（人工拷出后核对过）。

## 原因

- 发布路径：`job.py` `publish()`（约 641–664 行）先把 SRT 写到工作目录的 `publish/` 暂存，再 `artifacts.replace_with_retry(staged, video.final)`，底层是 `os.replace`。
- 工作目录默认在仓库内（D 盘），输入目录在外接盘（E 盘）。Windows 的 `os.replace` 不能跨卷，必然失败。同盘输入（以往的验证都是）不会触发，所以测试与 smoke 都没覆盖到。
- 连带问题：`artifacts.record_published(...)`（审计，写 `published.json`）在移动**之前**调用（约 654 行）。移动失败时，`published.json` 仍声称已发布到目标路径、并带着 sha256。
- 连带问题：`ctx.summary.fallback_cues += fallback` 也在移动成功之后（见 06）。

## 影响

- 只要工作目录与输入不在同一盘，整批 0 发布；GPU 阶段已全部跑完，结果只能人工捞。
- 审计记录与事实不符，后续"已发布/已存在"判断可能被误导（需核实续跑时是否读 `published.json`）。

## 候选方向（待讨论）

- 跨盘时先复制到**目标目录**下的同名临时文件（写完 fsync），再在目标盘内 `os.replace` 成原子替换；同盘仍直接 `os.replace`。
- 审计改为移动成功后再写，或失败时删除/标记。
- 测试：打桩 `os.replace` 抛 `OSError(errno.EXDEV)`（Windows 上为 WinError 17，需确认 errno 映射）；或用两个不同盘的临时目录（CI 不一定有）。
- 待定：工作目录是否应默认跟随输入盘（会改变默认布局，另议）。

## 证据

- 运行日志 `run-20261114T235704Z.log` 末尾 228 条 `[publish] FAILED ... OSError`。
- 台账 §B1。

## Comments
