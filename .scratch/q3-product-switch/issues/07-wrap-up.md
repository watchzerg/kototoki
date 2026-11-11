# 07 收尾：§7 结果、待填标记、残留检查、计划状态 done

Status: resolved
Type: task
Blocked by: 06

范围、终点与门见计划 §4 第 7 张票据（docs/plans/product-names-on-strata.md）。

- 搜待填标记；grep `kototoki/` 残留的 llama-server／27B／`NAMES_SERVER`。
- 完成报告区分已实现、自动检查、GPU 结果、未验证项。

## 执行记录

- 2026-11-09 待填标记搜索（文档维护规则的命令，排除 `.local`／`.venv`／`.scratch`）：只剩 `docs/development/workflow.md:57`（按需：有发布流程时写），时机未到，原样保留。
- `kototoki/` 残留检查：无 `NAMES_SERVER`／`NAMES_SPEC`／`model_asset`／`names-sessions`／`glossary-v1`；“llama-server”“27B”只出现在说明文字里（config 说明“没有 `[paths] llama_server`”、`names/recipes.py` 与 `table.py` 解释与 27B 时期的差别）；`kototoki.llama_server` 的使用只剩 `LlamaClient`、`InfraFailure`、`explicit_oom`、`nvidia_smi`、`wait_for_free_vram`，`ManagedServer` 无产品使用者。
- 票据 06 未执行（GPU 门未过），计划状态不能改 done：改为“停在票据 06”，§7 写完成报告（已实现、自动检查、GPU 结果、未验证项分列）、各票据提交号，§8 第 2 条记内存门；`docs/INDEX.md` 的计划条目同步。签名：提交用 ssh 签名、`commit.gpgsign=true`，本机未配 `allowedSignersFile` 故 `%G?` 显示 N，签名本身未失败。

## Answer

收尾完成，计划停在票据 06（GPU 验证）：代码与文档全部交付、离线门全过，真实运行待内存满足 52 GiB 后由用户重跑。
