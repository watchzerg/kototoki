# 01 跨盘发布失败与审计顺序

Status: resolved
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

### 2026-11-16 方向已定（用户拍板）

1. **发布实现**：双语字幕直接用 `atomic_write_text` 写到源文件旁，也就是先在目标目录写临时文件、fsync，再原子替换。只有一条代码路径，不判断是否跨盘，也不依赖 WinError 17／EXDEV 映射。只有最终的 `<stem>.ja-zh.srt` 写到目标目录；音频、VAD 等中间产物仍只写在工作目录。
2. **工作目录暂存保留**：`<work_id>/publish/<名>.ja-zh.srt` 照写，作为工作目录内的副本，供人工恢复和 sha256 对照。
3. **审计顺序**：`record_published`（`published.json`）改到源文件旁的字幕写成功之后再写；写字幕失败时不写审计记录。
4. **工作目录不跟随输入盘**：默认布局不变。输入常在外接盘或 NAS，中间产物不能回写到远端。原候选方向里的这一项删除，不另开票。

已核实：没有代码读取 `published.json`（ADR-0020），所以失败时留下的错误审计记录不会影响续跑；续跑时计划直接走到 publish，不跑 GPU。ADR-0020 只规定字幕发布到源文件旁，没规定经工作目录中转，因此不需要新 ADR。

完成标准：
- `job.publish()` 按 1–3 实现。
- 测试断言：最终字幕的临时文件与最终字幕在同一目录；写字幕失败时不产生 `published.json`；`publish/` 下的副本仍然存在。
- 同步更新文档：技术设计 §发布、`docs/architecture/modules/artifact-contract.md`（`record_published` 的时机）、`docs/architecture/modules/batch-orchestration.md`（publish 步骤）。
- `just test` 通过。

## Answer

2026-11-16 已实现：
- `job.publish()`：先 `write_srt` 写副本到 `<work_id>/publish/`，再 `write_srt` 原子写到源文件旁（临时文件建在目标目录内），成功后才 `record_published`，记录的 sha256 取自源文件旁那份。
- 测试 `tests/core/test_job.py` `PublishTests`：工作目录副本保留且 sha256 一致；打桩"跨目录替换即抛 EXDEV"时发布仍成功、目标目录不留 `.tmp`；写源文件旁失败时记 publish 失败、不写 `published.json`、副本仍在。这三处断言在旧代码上都失败（已验证）。
- 文档：技术设计 §发布与工作目录树、模块边界、`batch-orchestration.md`、`artifact-contract.md`。
- 自动检查：`just gate-core` 通过。未验证：没有实际在跨盘输入上跑产品入口（要占 GPU，未申请）；本批 228 份字幕已经人工拷出，不需要补发布。
