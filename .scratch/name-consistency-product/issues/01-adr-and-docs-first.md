# 01 ADR-0014 与模块边界先行

Status: done
Type: task
Blocked by: —

## 背景

ADR-0013 第 3 条"不进产品"须由新 ADR 替代后才能动产品代码；模块边界要求在只有一个适配器的位置新建接缝前先写明第二个使用者（`kototoki/llama_server.py` 将同时服务翻译与建表）。设计见 [docs/changes/name-consistency-product.md](../../../docs/changes/name-consistency-product.md) §0、§3.1、§7。纯文档小票；模块页与规格正文的改写等代码有行为后由 06、09 做。

## 范围

1. `docs/adr/0014-name-consistency-in-product.md`：状态 accepted（2026-10-19）；只替代 ADR-0013 第 3 条，第 1、2 条保持；如实记录证据（161 处、89%／2.5%、成对 88／20／3、无 MQM）与用户的裁定（设计稿 §7 六条）；决定项：阶段位置、失败即空表、`[names] enabled`、已交付影片重新发布、"改表重跑"形态、验收只看总体正向。ADR-0013 加一句反向链接（"第 3 条已被 ADR-0014 替代"），其余不改。
2. `docs/architecture/module-boundaries.md`：职责表加"共享 llama-server 生命周期（`kototoki/llama_server.py`：`ServerSpec`、`ManagedServer`、`LlamaClient`）"与"专名表建表与替换（`kototoki/names/`）"两行（消费方分别为翻译子系统＋names、编排器）；依赖方向加 names 的规则（只依赖基础层与 `llama_server`，不导入 torch、`experiments.*`；编排经 importlib 导入；`plan` 延迟导入 `names.recipes` 取 hash）；接缝一节写明 `ManagedServer` 的第二个使用者，并说明翻译 `Session` 不共享。
3. `kototoki.toml.example` 加 `[names]` 节（设计稿 §3.5）。
4. `docs/INDEX.md` 登记 ADR-0014。

## 完成标准

- 上述四处就位；`just docs-check` 对新增与改动文件没有断链（已有的冻结文档断链不计）。

## 文件所有权

`docs/adr/0014-*.md`、`docs/adr/0013-*.md`（只加一句）、`docs/architecture/module-boundaries.md`、`docs/INDEX.md`、`kototoki.toml.example`。

## Comments

2026-10-19 执行记录（agent）：四项范围已完成——新增 ADR-0014；ADR-0013 关系行加反向链接；module-boundaries 职责表加两行、依赖方向加一条（含三小条）、接缝一节写明第二个使用者；`kototoki.toml.example` 加 `[names]`；`docs/INDEX.md` 登记（置于 ADR-0013 之上，保持倒序）。`check_docs.py` 对上述文件无新增断链。ADR 正文不链接设计稿（吸收后会删除），只用路径文字。
