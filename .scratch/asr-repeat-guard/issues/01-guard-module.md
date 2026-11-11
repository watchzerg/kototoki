# 01 纯函数模块 kototoki/guard.py 与单元测试

Status: resolved
Type: task
Blocked by: —

范围与终点见计划 §4 票据 01（docs/plans/asr-repeat-guard.md）。含与研究侧 `repeat.py` 的等价守门测试；接口形状先写进模块边界与 STT worker 页。

## 执行记录

- 2026-11-11：先改接口文档（模块边界加 `guard` 一行与基础层清单、STT worker 页"接口与依赖"加守卫接口），再写 `kototoki/guard.py`（`RULE`、`check`、`apply`）与 `tests/core/test_guard.py`（17 个固定文本＋300 个固定种子生成文本与研究侧 `repeat.flagged`／`repeat.collapse` 等价）。
- 调整：配方块、新 id 与重钉 hash 从 02 提前到本票——`guard.RULE` 直接取 `recipes.W0["guard"]`（配方值仍只写在 `recipes.py` 一处），没有配方块就没有参数来源。W0 `b73198fa…3e76`，CROSS `d29b138b…717f`。
- 无法规范化的文字（跨簇 NFKC 组合）按不命中处理，不让整个文件失败。
- `just test`：623 项通过。

## Answer

完成。`guard.apply` 的记录形状：`{rule, action, period, copies, removed_raw_chars}`；`blank` 时返回的文字仍是原文。02 之前产品配方已带 `guard` 块但 worker 尚未接入（中间提交）。
