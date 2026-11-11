# 地图

## 接跑手册

1. 读计划 §7，找第一张未 resolved、且 Blocked by 全部 resolved 的票据，读它的 `## 执行记录`。状态以文件为准。
2. 顺序：01 ADR 与文档先行 → 02 锁冲突与协议读侧 → 03 身份补洞 → 04 Strata 额度与 Session 接口 → 05 拆 llama_server → 06 cross 路径 → 07 job 瘦身（等 02、04、05）→ 08 时间轴与小重复 → 09 核心测试不导入研究代码（等 05）→ 10 GPU 验证与收尾。
3. 每完成一张票据：票据写 Answer 并标 resolved；本文 Decisions-so-far 加一行；计划 §7 加一行；Git 提交（中文、签名）。
4. GPU 只在 10：开跑前 `Get-Process`（无 llama-server、无别的 Strata、无 GPU 作业）、读 `.local/gpu.lock`、可用内存 ≥52 GiB、`strata launch --plan` 下载量为 0。不杀进程、不关用户程序。
5. 需要裁定的事写计划 §8，不中途问。
6. 在 Windows 上用 Python 写文件一律 `newline='\n'`；仓库行尾 LF。

## Notes

- 计划 §2 的行号取自 2026-11-11 的 `c639b22`，动手前以当时源码为准。
- 除 MEDIA 外任何配方 hash 都不得变；票据 03 第一步先把 MEDIA、VAD、MMS、CUES、EMBEDDED 钉住，之后每张票据以此为门。
- `translation_v3/strata.py` 与 `scene_batching_v6/v13.py` 是基线 Q3 的实现：只改导入行，改完跑它们的离线测试。
- `just docs-check` 在 main 上本就失败 44 处冻结外链，只看新增条目。
- `just gate-core` 按契约不可能通过（lint、typecheck 未接入），逐项跑。

## Decisions-so-far

- 拆法调整（2026-11-11）：票据 03 的第一步（钉住 MEDIA、VAD、MMS、CUES、EMBEDDED hash）提前到 01 之后、其余代码票据之前单独落地，理由：02–08 分三个 worktree 并行（A：02→03；B：04→05；C：06→08），每个 worktree 都要以这组钉住的 hash 为门。07、09 在前六张合并后做。
- `Session` 接口定为 `Session.label`（`<runtime_root.name>/session-NN`）＋`Session.client(trace_dir, *, timeout)`，不是计划 §4 写的 `client(trace_root, timeout)`：翻译的 trace 目录是 `<run>/transport/session-<run 内序号>`，与 names 的 `<work>/<TRANSPORT_DIR>/<runtime>/session-NN` 布局不同，按 §3 第 9 条两者都不能变。

## Fog

- （已查清，2026-11-11）研究侧离线测试用根 `.venv/Scripts/python.exe -X utf8 -m unittest discover -s experiments/<包> -t . -p 'test_*.py'` 能跑。改动前基线（c639b22）：translation_v3 90 OK；quality_v5 101 OK；asr_robustness_v14 49 OK；asr_robustness_v15 32 OK；analysis 47 OK；fullfilm_comparison 49 OK（跳过 12）；vad_comparison 38 OK；scene_batching_v6 81 项中 test_v13 本就 3 失败 1 错误（`VariantTest.test_hashes`、`ClientTest.test_body_drops_response_format_and_states_no_thinking`、`IdentityTest.test_product_build_hash_unchanged_and_s1_separate`、`VariantTest.test_v3_keeps_response_format_and_502_is_a_failed_attempt`，ADR-0022 改产品建表后遗留）；components 目录不可导入。之后只看相对这个基线的新增失败。
- 基线：`just test` 651 OK，`just test-full` 17 OK，`just docs-check` 44 处失败（日志 47 行），`just check-toolchain` 失败（uv 0.13.0，mise.toml 钉 0.12.22；改环境才能修，不动，写进计划 §8）。

- 研究侧各包的离线测试用哪个解释器能跑（legacy 3.12 无依赖环境导入不了产品包的可能性）：票据 05 首次碰到时查清并记在这里。

## 结束状态（2026-11-11）

- 10 张票据全部 resolved；逐票据结果与完成报告在计划 §7，待裁定项在计划 §8。
- 并行 worktree 已移除；分支 `ac-a`…`ac-e` 保留（内容已逐提交 cherry-pick 进 `architecture-cleanup`）。
