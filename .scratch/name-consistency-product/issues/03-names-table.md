# 03 建表模块：`kototoki/names/recipes.py` 与 `names/table.py`

Status: done
Type: task
Blocked by: 01

## 背景

移植 `experiments/name_consistency/build_table.py` 的冻结配置（提示 v5、no-think 采样、`name-table-v2` schema、程序兜底全开）到产品。设计见增量说明 §3.1、§3.3。本票不碰编排、配置与计划，不依赖票据 02 的最终接口：对 server 的调用只经 `chat(body) -> dict` 与 `tokenize(text) -> int` 两个可注入回调，06 再接 `LlamaClient.chat_completion`／`tokenize`。

## 范围

- `kototoki/names/recipes.py`：`BUILD` 配方字典（`prompt_version: build-table-prompt-v5`、`prompt_sha256`、`sampling`、`response_schema_sha256`、`max_tokens 4096`、`reasoning: off`、`context 20480`、`prompt_budget`（20480 − 4096 − 512）、`normalize`（zh 形状、称呼词黑名单版本、`min_high_person_cues 3`、日文写法形状、`max_forms 12`、`max_items 8`、`max_zh_len 12`、`max_ja_len 20`）、`attempts 2`、`seed_step 1`、`model_asset`（文件名、size、sha256））；`BUILD_RECIPE_HASH = kototoki.recipes.recipe_hash(BUILD)`。`NAMES_SPEC`（给票据 02 的 `ServerSpec`：Qwen 资产、`layers 99`、`context 20480`、`extra_args ("-b","512","-ub","512","-fa","on","--jinja","--reasoning","off","--no-webui")`、`min_free_mib` 初值 13000、端口来自配置）。
- `kototoki/names/table.py`：从 `build_table.py` 复制 `SYSTEM_PROMPT`（逐字节）、`USER_TEMPLATE`、`SAMPLING`、`RESPONSE_SCHEMA`、`KINDS`／`CONFIDENCES`、`HONORIFIC_JA` 与前后缀表、`ZH_SHAPE`／`JA_SHAPE` 等常量，`build_messages`（输入 `SourceDocument`：行为 `编号<TAB>文本`，多行文本内的换行替换为空格，编号取 SRT 编号）、`_json_text`、`_strings`、`_clean_zh`、`_clean_ja`、`is_honorific`、`_forms`、`_clean_forms_ja`、`_zh_variants`、`_downgrade_thin_person`、`parse_reply`。去掉 argparse、`--think`、`--renormalize`、`--dry-run`、`post_chat`、落盘。
- `build_table(document, chat, tokenize, seed) -> BuildResult`：`tokenize(text) -> int` 对渲染后的 user 消息计数，超过 `prompt_budget` 返回 `status="too_long"` 的空表；否则构造请求体（`messages`、采样、`seed + attempt − 1`、`max_tokens`、`response_format json_schema`、`chat_template_kwargs {"enable_thinking": false}`、`stream false`），最多两次；`finish_reason == length` 或 `parse_reply` 抛 `ValueError` 即下一次；两次都失败返回 `status="failed"` 并带最后错误首行。返回 payload：`schema`、`prompt_version`、`work_guess`、`entries`、`meta`（seed、attempt、三类 dropped、prompt／completion tokens、秒数）、`build`。零条目文档不调用 `chat`。

## 完成标准

- `tests/core/test_names_table.py`：从 `experiments/name_consistency/test_build_table.py` 移植 Render／Parse／Cap／Shape／Honorific／PromptV5／JaShape／Confidence 全部用例（改 import，不导入 experiments）；新增：预算超限不调用 `chat`、首次 length 第二次成功且 seed+1、两次失败返回 `failed` 空表、零条目不调用、多行 cue 文本换行替换。
- `tests/core/test_names_recipes.py`：`SYSTEM_PROMPT` sha256 钉子（取自 `experiments/name_consistency/build_table.py` 的当前文本，测试里写死十六进制，不导入 experiments）、`BUILD_RECIPE_HASH` 钉子、`RESPONSE_SCHEMA` 与研究期逐字节相同（同样以 sha 钉）。
- `just test` 全绿；`kototoki/names/` 不导入 torch、`experiments.*`。

## 文件所有权

`kototoki/names/__init__.py`（本票只建空包说明，接口由 06 填）、`kototoki/names/recipes.py`、`kototoki/names/table.py`、`tests/core/test_names_table.py`、`tests/core/test_names_recipes.py`。

## Comments

