# ADR-0039：文档检查改用 setup-project 自带的 `check_docs.py`

状态：已接受，2026-11-22（用户裁定：直接用 skill 自带的脚本），已实现。
替代关系：
- 取代 [ADR-0031](0031-research-layout-and-lightweight-records.md) R8（机械检查）中由 `scripts/check_docs.py` 承担的部分：研究记录必填标题、本机绝对路径、64 位十六进制串不再有机械检查。`tests/core/test_boundaries.py` 检查 `kototoki/` 不导入 `research` 的部分不变。

范围：`just docs-check` 与 `just docs-affected` 用哪个脚本、检查什么，以及文档为此做的整改。不改产品代码、配方与基线。

## 决定

1. `scripts/check_docs.py` 换成 setup-project skill 自带的版本，不做项目化修改；检查项与规则正文在[文档维护规则·自动检查](../agents/documentation.md#自动检查)。原脚本及其单元测试 `tests/core/test_check_docs.py` 删除。
2. `just docs-affected [base]` 用该脚本的 `--affected` 实现：按模块页页首 `covers` 列出改动命中的页面，只提示，不进门禁。模块页一律在页首声明 `covers`。
3. `docs/agents/documentation.md` 的取舍原则、模块页模板、行为规格模板、体量预算与拆页、随交付同步、自动检查各节与 setup-project 模板一致。
4. 换脚本时按新规则整改现有文档：模块页补齐六节骨架并在超出 16 KB 时拆成枢纽页与子页，行为规格页按四节骨架重排（`kototoki-d8m`），超过 400 字符的段落与表格单元格拆开，跑次记录在 `docs/research/INDEX.md` 直接登记。

## 依据

- 用户要求统一以 setup-project 的规范为准（同 [ADR-0038](0038-setup-project-doc-layout.md)），并选择直接用 skill 自带的脚本，接受失去原脚本独有的检查。
- skill 版脚本支持 `covers` 与 `--affected`，原脚本没有（`kototoki-qez`）。

## 未验证与已知限制

- 失去的检查：研究与跑次记录的必填标题、本机绝对路径、64 位十六进制串与媒体文件名、`kototoki/` 每个模块都被某篇模块页登记、ADR 编号与决定索引一致、活文档里反引号路径存在。这些规则仍写在各自正文里，只靠遵守与评审。
- 以后 setup-project 更新脚本时需手工同步本仓库副本。
