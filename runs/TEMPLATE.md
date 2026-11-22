# 跑次记录模板

每次产品批量运行后复制下面的骨架到 `runs/<YYYY-MM-DD>-<slug>.md`，并在 [INDEX.md](INDEX.md) 登记一行。规则（匿名、问题去向）见[批量运行与跑次记录](../docs/agents/production-runs.md)。`## ` 二级标题是必填项，`scripts/check_docs.py` 逐字检查。

不写进记录：影片文件名、输入目录名、工作根目录名、含它们的路径、本机绝对路径、64 位哈希、字幕／转写／译文原文、大段日志。

```markdown
# <YYYY-MM-DD> <slug>：<一句话说明这次跑什么>

## 运行
运行日志的 UTC 戳、开始与结束时间、入口（`just subtitles` 或 `python -m kototoki`）、退出码；中断时写原因。

## 版本
commit 短 SHA（工作区有未提交改动时注明改了什么）、engine、配置与默认值的差异、日志首行的 `ffmpeg=`、Strata 版本。

## 输入
输入集的 sha12；文件数与类型构成（带内嵌字幕、纯音频等）；总时长（如可得）。

## 结果
各阶段 done／failed／耗时；发布数；失败按 `failed at <stage>` 归并；显存与内存峰值。表格不超过约 10 行。

## 问题
每条：现象、证据（工作 id、阶段、级别与异常类型、计数）、去向（bead ID／不处理＋理由／待观察＋条件）。没有问题写"无"。
```
