# 01 编排器接入标准库 logging

Status: resolved
Type: task
Blocked by: —

## 范围

规格见 [spec.md](../spec.md) §3.1、§3.3、§3.4、§3.5、§3.6。

- `kototoki/job.py`：删除 `RunLog`，改为在 `job.run` 里配置标准库 `logging`：logger 根名 `kototoki`；一个 `FileHandler`（`<output_dir>/.work/run-<UTC戳>.log`，UTF-8，`\n`）＋一个 `StreamHandler`（`console` 参数，默认 `sys.stdout`）；两者同一 Formatter、同为 INFO；`run` 结束（含异常）时移除并关闭 handler，避免测试里多次 `run` 累积 handler 与 Windows 文件占用。
- 格式：`%(asctime)s [%(elapsed)8.1fs] %(levelname)-8s %(message)s`，`asctime` 为 UTC `YYYY-MM-DD HH:MM:SSZ`，`elapsed` 为自 `run` 开始的秒数（用 `logging.Filter` 或 LogRecord factory 注入）；第三方 logger（名字不以 `kototoki` 开头）的记录在消息前加 `[<logger 名首段>]`。
- `_Context.log`／`ctx.log(...)` 全部改为模块 logger `logging.getLogger("kototoki.job")`：进度与计数 `info`；"被用户改动跳过"、"大小仍在变化"、"final file(s) changed by user, not overwritten" 改 `warning` 且消息里去掉 `WARNING` 字样；`ctx.fail` 改 `error`，`error` 非 None 时带 `exc_info=error`（traceback 进文件与控制台）。
- worker 子进程退出后统计 `run-<戳>-<stage>.stderr.log` 中以 `WARNING`／`ERROR` 为级别字段的行数（按本票格式，列 3），非零时 `warning("[%s] %d warning/error line(s), see %s", ...)`。
- `kototoki/__main__.py` 的启动期 `print(..., file=sys.stderr)` 不动。
- 不做：DEBUG 分叉、配置键、改 `failure.json`／协议／产物、`experiments/*`。

## 完成标准

- `just test` 全绿；`tests/core/test_job.py` 现有子串断言保留，另加用例：文件与控制台逐行相同；告警行级别为 `WARNING` 且不含 "WARNING" 措辞以外的变化；失败行为 `ERROR` 且文件里有 traceback；两次 `run` 后 `logging.getLogger("kototoki")` 没有残留 handler；第三方 logger 的记录带前缀。
- `kototoki/job.py` 仍不导入任何推理库（现有禁止导入测试守门）。
- 代码注释与票据评论用简体中文；标识符英文。

## 文件所有权

`kototoki/job.py`、`tests/core/test_job.py`、`tests/core/test_translate_degrade.py`（若断言需随措辞调整）。

## Comments

- 2026-10-18 实现完成（Opus 5.5）：
  - 实现：`kototoki/job.py` 删除 `RunLog`，新增私有上下文管理器 `_run_logging`，`run` 期间在 **root logger** 上挂两个 `StreamHandler`（一个写 `.work/run-<UTC戳>.log`，以 `open(..., encoding="utf-8", newline="\n")` 打开以保证 Windows 上也是 `\n`；标准 `FileHandler` 不能指定 newline，故未直接用它；另一个写 `console`，默认 `sys.stdout`），同一 Formatter、同为 INFO；`kototoki` logger 临时设 INFO，退出（含异常）时恢复级别、摘下并关闭 handler、关文件。root 级别不动（默认 WARNING），所以第三方库只有 WARNING 及以上进日志。
  - 格式 `%(asctime)s [%(elapsed)8.1fs] %(levelname)-8s %(message)s`，墙钟 UTC `YYYY-MM-DD HH:MM:SSZ`；`elapsed` 与第三方前缀 `[<logger 名首段>]` 都在 Formatter 子类 `_RunFormatter.formatMessage` 里注入（按 `record.created` 计算，两个 handler 输出逐字相同；`record.message` 每次 format 都重建，前缀不会叠加）。判断"自己的 logger"用名字首段等于 `kototoki`。
  - `ctx.log` 全部改为 `logging.getLogger("kototoki.job")`：进度／计数／耗时 `info`；"size still changing"、扫描期与发布期"final file(s) changed by user"三处改 `warning` 并去掉消息里的 `WARNING`；`_Context.fail` 改 `error` 并带 `exc_info=error`（`error` 为 None 时无 traceback）。`_Context` 去掉 `log` 字段。
  - `_launch` 在打开 stderr 文件时记下偏移，worker 退出后只读本次启动追加的部分，统计符合本格式且级别为 WARNING／ERROR（及 CRITICAL）的行；非零时记 `warning("[<stage>] N warning/error line(s), see run-<戳>-<stage>.stderr.log")`。tqdm、裸 traceback 等非本格式行不计。
  - `__main__.py`、`failure.json`、协议、产物、`experiments/*` 未动；文档未动（归票据 04）。
- 自动检查：`just test` 355 个测试全部通过（原 349 + 新增 `RunLogTests` 6 个：文件与控制台逐行相同且每行符合格式、文件无 `\r`；告警行级别为 WARNING 且消息不含 "WARNING"；失败行为 ERROR 且文件含 traceback；两次 `run` 后 root 与 `kototoki` 的 handler 与级别恢复原状；第三方 logger 记录带 `[transformers]` 前缀、低于 WARNING 的第三方记录被丢弃；伪 worker 往 stderr 写入本格式 WARNING 与非本格式噪声时只计 1 行）。`tests/core/test_translate_degrade.py` 未改，仍通过。`just check` 通过。导入守门测试仍通过（`job.py` 只新增 `logging`、`re`）。
- 未验证：真实 GPU 运行下 worker stderr 的计数（真 worker 要到票据 03 才按本格式写 stderr，在此之前计数恒为 0）；控制台在非 UTF-8 代码页下的显示（沿用 `__main__` 的 `backslashreplace`，未单独测）。另注意：`exc_info` 会把异常完整消息写进日志，规格 §3.6 的"首行消息截断 200 字符"本票未做（失败行本身只记异常类型）；异常消息不含正文这一点依赖票据 02 对 `StepFailed` 的审计。
