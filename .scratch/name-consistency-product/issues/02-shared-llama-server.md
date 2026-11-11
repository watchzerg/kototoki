# 02 抽出共享 llama-server 模块（只抽 server 与 client，不动 Session）

Status: done
Type: task
Blocked by: 01

## 背景

翻译子系统的 `translate/server.py`（`ManagedServer`、显存轮询、驻留校验）与 `translate/client.py`（`LlamaClient`）只服务 Hy-MT2。建表阶段要用同一套生命周期起 Qwen3.8-27B：不同模型资产、`-c 20480`、`--jinja --reasoning off`、chat completions 接口、不同显存阈值。设计见增量说明 §3.1。review 后缩小：翻译的 `generate.Session` 不抽通用版，names 自己写一个最小 session（06）。

## 范围

- 新建 `kototoki/llama_server.py`（中间层，不属基础层）：
  - `ServerSpec`（frozen dataclass）：`candidate`、`model_asset`（repo／revision／file／size／sha256）、`layers`、`context`、`extra_args: tuple[str, ...]`（放在 `-c`／`-np`／`-ngl` 之后、`--no-webui`／`--log-file`／`-lv` 之前）、`min_free_mib`、`load_timeout_s`。
  - `ManagedServer(runtime_dir, spec, *, engine, model, port, model_cache, on_pid)`：现有逻辑原样搬入；`server_command(spec, engine, model, port, log_file)`；`check_model(model, spec, cache)`；`identity["candidate"]`／`["asset"]` 取自 spec。
  - `LlamaClient` 搬入，新增 `chat_completion(body) -> dict`（`POST /v1/chat/completions`，同一 trace 机制，文件名前缀 `chat-NN`）；`tokenize`、`completion` 不变。
  - `InfraFailure`、`explicit_oom`、`nvidia_smi`、`wait_for_free_vram`、`residency_evidence`、`validate_residency`、`loader_logs`、`port_free`、`check_engine` 搬入。
- `kototoki/translate/server.py` 只留 `TRANSLATE_SPEC = ServerSpec(candidate="hy-mt2-30b-a3b-apex-i-compact", model_asset=MODEL_ASSET, layers=99, context=CONTEXT_SIZE, extra_args=("-b","256","-ub","128","-t","8","-tb","8","-ctk","f16","-ctv","f16","--cache-ram","8192","-fa","on","--fit","off"), min_free_mib=14700, load_timeout_s=180)` 与 `MODEL_ASSET`（仍由 `tests/core/test_assets_manifest.py` 钉住）；`generate.Session._managed_server` 改为 `ManagedServer(runtime_dir, TRANSLATE_SPEC, …)`。
- 测试：`tests/core/test_translate_server.py` 中与翻译无关的用例平移到 `tests/core/test_llama_server.py`（驻留解析、显存轮询、OOM 识别、引擎核对、`server_stop`）；翻译冻结命令行与模型核对的用例留在原文件，断言不改。

## 完成标准

- `just test` 全绿；`tests/core/test_translate.py`、`test_translate_degrade.py`、`test_translate_recipes.py` 零改动；`test_translate_server.py` 只改 import 与构造参数，断言不改（`git diff` 可核）。
- 翻译命令行钉子通过，证明 `server_command` 逐字节不变；`engine.json`／`engine-final.json` 字段集合与 `SESSION_ENGINE_KEYS` 不变。
- `kototoki.llama_server` 不导入 torch、`experiments.*`，不被基础层导入（`test_job.py` 禁止导入清单仍成立）。
- 翻译子系统模块页"实现设计"表更新 server／client 来源两行。

## 文件所有权

`kototoki/llama_server.py`（新）、`kototoki/translate/{server,client,generate}.py`（generate 只改 `_managed_server` 一处）、`tests/core/test_llama_server.py`（新）、`tests/core/test_translate_server.py`、`docs/architecture/modules/translation-subsystem.md`。

## Comments

