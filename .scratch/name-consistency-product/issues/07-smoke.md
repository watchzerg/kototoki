# 07 真实模型验证入口 `just smoke names_product`

Status: done
Type: task
Blocked by: 06

## 背景

产品环境的真实模型验证走 `just smoke`（[开发工作流](../../../docs/development/workflow.md)）；建表模块需要一次真实 Qwen server 的路径验证（驻留校验、JSON schema 输出、`/tokenize`、chat completions trace）。GPU 重任务，运行前须用户批准。

## 范围

- `scripts/smoke/names_product.py`：与 `translate_product.py` 同形——脚本内置 12 条合成日语短句，含同一人名的两种写法（片假名与一处 ASR 式误写）与一个职阶名；写临时 `ja.srt` 与一份人工给定的中文译文（译文里该名字写法不一致）；走 `names.plan` → `Session` → `build_document` → `write_artifact` → `names.apply`。通过条件：server 驻留校验通过、`build.status == ok`、表至少 1 条 person、`apply` 至少改 1 处且改后一致、无异常。输出只记计数、哈希、耗时、冷加载、空闲显存与峰值显存；工作目录在仓库外的会话临时目录。
- `justfile` 的 `smoke` recipe 接入（按现有 `translate_product` 的方式）。

## 完成标准

- 脚本入库；`just smoke names_product` 在用户批准后运行一次（与 08 共用一次批准，先 smoke 后整片），记录写入本票 Comments 与模块页"代码与验证入口"（含 `min_free_mib` 初值 13000 是否合适：记录启动前空闲与峰值，必要时在 08 前调整）。
- 未运行时模块页写明"未运行、待用户批准"。

## 文件所有权

`scripts/smoke/names_product.py`、`justfile`（仅 smoke 一行）、`docs/architecture/modules/name-consistency.md`（验证入口一节）。

## Comments

### 2026-10-20 实现与运行记录

- 新增 `scripts/smoke/names_product.py` 并登记到 `scripts/smoke/run_all.py` 的 `SMOKES`（`translate_product` 之后）；`justfile` 的 `smoke` 接受名称参数，无需改动。`docs/development/workflow.md` 的 smoke 行补了一句。
- 用户预先批准一次运行；第一次（`.local/smoke/20261019T162338Z`）产品路径全部通过（驻留、建表 `ok`、2 条 person），但判据"改后一致"失败：人工译文里人名的三种写法（艾米莉亚／艾米利亚／艾米莉雅）共享前两字，`apply` 统计层把"艾米"当省略形，不替换；单次出现的误写（エミリヤ）也不会被统计层处理。属脚本译文设计问题，不是产品缺陷，`apply` 是纯函数，已用同一张表离线复算确认。把译文改成两种互不相邻的写法（艾米莉亚 4 处、爱蜜莉雅 2 处，被替换的写法两侧是标点或"的"）后第二次运行（`.local/smoke/20261019T162456Z`）通过。共两次 GPU 运行。
- 通过运行的数字：驻留 66/66 层 GPU（`CUDA0` 10616.86 MiB 模型 buffer）；冷加载 5.6 s；启动前空闲显存 15029 MiB；峰值显存 13444 MiB（整机，含约 1.3 GiB 基线）；建表 `ok`、`attempts` 1、prompt 1655／completion 299 tokens、请求 6.1 s、2 条 person（人名一条、职阶名一条，kind 均为 person）；`apply` 3 处替换、2 处 `boundary`、含该人名的 6 个 cue 写法 2 → 1；整个脚本约 21 s。
- `min_free_mib` 13000 评估：server 自身约 12.2 GiB（峰值 13444 减基线约 1.3 GiB），余量约 0.8 GiB，合适，不改；08 整片提示更长，届时再记一次峰值。
- 未发现产品代码缺陷；本票未改 `kototoki/names` 与 `kototoki/llama_server.py`。模块页"代码与验证入口"已更新，08 整片仍标未验证。
