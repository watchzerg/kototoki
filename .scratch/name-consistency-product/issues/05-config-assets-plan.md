# 05 配置、资产清单、阶段计划与产物常量接入

Status: done
Type: task
Blocked by: 01

## 背景

names 阶段要进配置、清单、阶段链与 `published.json` 的 `sources`。设计见增量说明 §3.2、§3.4、§3.5。review 后简化：建表没有 run 目录，身份由 `plan.py` 自己算，不设 `names.plan`；对 `kototoki.names` 的唯一依赖是延迟导入 `kototoki.names.recipes` 取两个 hash，测试用 `sys.modules` 里的伪模块（与翻译阶段做法相同），因此不依赖 03。

## 范围

- `kototoki/config.py`：`DEFAULTS["names"] = {"model": "glossary-v1/Qwen3.8-27B-UD-IQ3_S.gguf", "port": 8081, "seed": 20261019, "enabled": True}`；`MODEL_KEYS` 加 `("names", "model")`；`Models.names`；`NamesConfig(port, seed, enabled)`；`Config.names`。
- `assets.toml`：`[models."qwen3.8-27b-ud-iq3_s"]` `dir = "glossary-v1"`、`repo = "unsloth/Qwen3.8-27B-GGUF"`、`revision = "4ca720788d1e01f1bff70c033e0d0028fd02e502"`、files `"Qwen3.8-27B-UD-IQ3_S.gguf" = { sha256 = "d847e2c1e4aa276e4b7b8e9ad7628050e61e165d49ab995407bc36677a6f3864", size = 12040883104 }`；`docs/development/dependencies.md` 当前实现一节加一行。`tests/core/test_assets_manifest.py` 钉"清单文件名 == `config.py` 默认路径的文件名"（模型常量的钉子由 06 补，因常量在 03 的 `names/recipes.py`）。
- `kototoki/artifacts.py`：`NAME_TABLE = "name-table.json"`、`NAMES_APPLY = "names-apply.json"`；`STAGE_ARTIFACTS` 加 `NAME_TABLE`。
- `kototoki/plan.py`：`STAGES = (*GPU_STAGES, "cues", "names", "translate")`；`STAGE_OUTPUT["names"] = artifacts.NAME_TABLE`；`IDENTITY_KEY["names"] = "names"`；`names_identity(ja_srt_sha256, config) -> {"ja_srt_sha256", "recipe_hash": BUILD_RECIPE_HASH, "seed": config.names.seed}`、`names_apply_identity(table_sha256) -> derived_identity(upstream={NAME_TABLE: sha}, recipe_hash=APPLY_RECIPE_HASH)`（两个 hash 经 `importlib.import_module("kototoki.names.recipes")` 延迟取）；`_check_from`：`config.names.enabled` 为假时跳过 names；为真时算 `ids["names"]`（`ja.srt` 的 sha256 在此读一次）、`is_current(name-table.json)`，当前时再算 `ids["names_apply"]`。`Plan.sources` 的键在 enabled 时为 `(probe, vad, asr, align, ja_cues, names, names_apply, translate)`。无语音路径不变。

## 完成标准

- `tests/core/test_config.py`：`[names]` 默认值、相对 `models_root` 解析、未知键报错、`enabled` 必须是布尔。
- `tests/core/test_plan.py`（伪 `kototoki.names.recipes` 提供两个 hash）：阶段链 cues → names → translate；`names` 不当前停在 names；表当前而文件 sha 变化（改 `entries`）时 `stage == translate` 且 `sources["names_apply"]` 变化；`enabled=false` 时链与 `sources` 和今天相同（现有用例不改即通过）；`advance` 从 names 继续。
- `tests/core/test_artifacts.py`：常量存在、`write_failure` 列出 `name-table.json`。
- 离线核对四个现有整片工作目录（`.local/bilingual-fullfilm-08/out-*/.work/`，用临时脚本调用 `plan.next_stage`，不进 Git）：`enabled=false` 时全部 `done`；`enabled=true` 时全部停在 `names`。结果写进本票 Comments。
- `just test` 全绿。

## 文件所有权

`kototoki/config.py`、`kototoki/plan.py`、`kototoki/artifacts.py`、`assets.toml`、`docs/development/dependencies.md`、`tests/core/test_config.py`、`tests/core/test_plan.py`、`tests/core/test_artifacts.py`、`tests/core/test_assets_manifest.py`。

## Comments


### 2026-10-19 实现与离线核对（agent，未 commit）

- 实现按范围；core 门禁（`unittest discover -s tests/core`）407 项全绿。
- 偏离与补充（均小）：
  - `kototoki.toml.example` 加 `[names]` 节：`ExampleFileTests` 要求示例列出全部 `DEFAULTS` 键，不加即红。
  - `tests/core/test_job.py` 的 `JobCase` 配置加 `[names] enabled = false`（一行，带注释）：编排尚未接入 names，默认 `enabled=true` 会让所有 job／translate_degrade 用例停在 names；06 换成伪 names 模块时去掉。
  - `plan._publish_state` 比较 `names`／`names_apply` 两键时，期望里没有也比（记录里有则不匹配）：增量说明 §3.4 要求"从 true 改 false 触发重新发布"，原先只比期望里的键，会判 `done`。
  - `dependencies.md`：当前实现一节"六个模型目录"改"七个"并加一条 `qwen3.8-27b-ud-iq3_s`。
  - `Plan.sources` 仍不持有 config：`identities` 有 `names` 键即含 `names`／`names_apply`。stage 为 `names`（表不当前）时 `identities` 尚无 `names_apply`，此时读 `sources` 会 KeyError（与 stage 为 vad 时同理；`sources` 只在 translate／publish／done 使用）。
- 离线核对（临时脚本在 scratchpad，不进仓库；只读 `.local`，模型 SHA 缓存复制到临时目录；伪 `kototoki.names.recipes`；`next_stage` 用真实 `kototoki.translate.plan`）：

  | 工作目录 | enabled=false | enabled=true |
  | --- | --- | --- |
  | out-w0 / `8d2f3e76dd0c`（Heaven's Feel II） | done | names |
  | out-w0 / `fb2e0da74018`（Heaven's Feel III） | done | names |
  | out-x0 / `8d2f3e76dd0c` | vad | vad |
  | out-x0 / `fb2e0da74018` | vad | vad |

  w0 两个目录与预期一致。x0 两个目录的结果与 names 无关：`vad.json` 身份里的 `upstream[audio-16k.wav]`（`c203f952…`）≠ 当前 `probe.json` 的 `extract.pcm_sha256`（`ee4e2da3…`，与 w0 相同），即 x0 的 vad 产物来自较早一次抽取，按当前身份本就不当前（enabled 取何值结果相同）。x0 目录因此不能用来验证 names 停点；08 验收只用 w0。