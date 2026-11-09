# ADR-0022：产品建表切到 Strata（对齐基线 Q3；names 与翻译共用一个 Strata session）

状态：已接受（2026-11-09，用户决定，依据[计划](../plans/product-names-on-strata.md)；实现、离线验收与 GPU 验证的结果记在计划 §7）。替代 [ADR-0014](0014-name-consistency-in-product.md) 第 3 点中的建表模型与 llama-server 部分（阶段位置不变）、[ADR-0019](0019-product-translation-q2.md) 第 2 点中"names 阶段整批用 llama-server 建表、两者不同时驻留"、[ADR-0007](0007-bilingual-subtitle-pipeline-architecture.md) 第 3 点中剩下的"建表用独立进程的官方 llama.cpp"。[ADR-0021](0021-q3-strata-names-baseline.md) 正文不变，其"不改产品"的范围说明自本日起由本 ADR 接续。  
范围：产品包 `kototoki/` 的 `names` 阶段用什么建表、Strata 由谁持有与启停。不改 Q3 的建表规则与 Q2 的翻译配方 `q2-degrade-v1`，不改 `experiments/`，不开封确认集。

## 决定

1. **产品建表即 Q3 的建表规则。** `names` 阶段在 Strata 上用 `qwen3.8-flash-next-iq3_s` 建表，请求体与 seed 序列与 v13 的 `names-strata-v4`（`experiments/scene_batching_v6/v13.py` 的 `NamesClient`＋`build_one`）逐字节一致：
   - 提示 v5、JSON schema、采样（0.7／0.8／20、`presence_penalty` 1.5）、归一兜底不变；`max_tokens` 8192、context 24576（提示预算 24576 − 8192 − 512 = 15872，数值与此前相同）；
   - 请求不带 `response_format`，带 `chat_template_kwargs.enable_thinking: false` 与 `model`，非流式；
   - 预算检查走 `/v1/messages/count_tokens`：system 与 user 两段各作一条 user 消息计数再相加，超预算（`too_long`）不发请求、写空表。该端点不可用（HTTP／传输错误、响应形状不符）时退路与 v13 相同：本 session 内不再预检、计数按 0，只记录 `usage.prompt_tokens`，超预算只标记不失败，运行日志一行 WARNING；
   - 失败后依次换 seed：请求用 seed、seed＋1、…、seed＋4，最多 5 个请求，取第一张合格的表即停，不在多张表里挑选（[ADR-0008](0008-no-multi-translation-selection.md)）。实现复用 `table.build_table`（两次一组：seed、seed＋1），外层在结果为 `failed` 且还有请求额度时以 seed＋2k 再调一次，第 6 次尝试（seed＋5）不发请求，与 v13 `build_one` 相同；
   - 5 次都失败写 `build.status = failed` 的空表，影片照常翻译、不注入，同现行规则。
   产品代码不导入 `experiments.*`；等价由 `tests/core/` 导入 v13 做逐字节对照守门。
2. **新建表配方 `q3-names-v1`。** `kototoki/names/recipes.py` 的 `BUILD` 改为该配方，`BUILD_RECIPE_HASH` 由 `tests/core/test_names_recipes.py` 钉住。它与 `names-strata-v4`（`38cb7bcd…`）的对应关系：
   - 相同：建表块（提示 v5 的 sha256、schema sha256、采样、`max_tokens` 8192、`reasoning off`、context 24576 与预算 15872、归一规则与常量、`attempts` 5、`seed_step` 1）、模型 `qwen3.8-flash-next-iq3_s`、运行时身份（Strata 0.2.12、引擎 build 0.1.58、`launch: default` 与其解析值、kv `int8`；取值与翻译配方 `q2-degrade-v1` 的 `runtime` 相同，kv 以接入时 `strata.json` 记录的观测值为据）、请求形状（无 `response_format`、`enable_thinking: false`）；
   - 不同：不含研究侧的说明字段（`prompt_budget_check`、`retries` 两段文字），因此 hash 不同；不含 llama.cpp 的 `model_asset`。
   表的身份仍是 `{ja_srt_sha256, recipe_hash, seed}`：配方一变，旧 `name-table.json` 全部失效、重建；注入行变则 `names_sha256` 变、重译。不迁移旧产物。
3. **names 与翻译共用一个 Strata session。** 整批只启动一次：第一次真正需要模型时启动（可能在 names，也可能在 translate），两阶段之间不停；整批结束、出错或编排被中断时 `strata launch --stop` 并核实 status 为空、显存释放；没有影片需要模型时不启动。启动前检查（status 为空、空闲显存 ≥14000 MiB、可用内存 ≥52 GiB）、接入检查（ADR-0017／ADR-0019）与专家区检查（必须 `ram`）不变。GPU 锁照常记录 Strata 的 pid。产品任何阶段都不再启动 llama-server、不加载 27B。
4. **Strata 生命周期下沉到中间层 `kototoki/strata.py`**（与 `llama_server.py` 同层，不属基础层）：`StrataServer`、`StrataRefused`、Strata 身份常量（模型名、版本、引擎 build、默认启动的解析值）与共享 `Session`（整批一个、启动计数、`unavailable`、`ensure_started`／`stop`、`on_server_pid`）。编排器持有 `Session` 并传给两个阶段；`names` 与翻译子系统互不导入；翻译子系统保留自己的同调用内重启与降级逻辑，只是改用共享的 session。这是第二个使用者出现后的正当抽取（[模块边界·接缝](../architecture/module-boundaries.md#产品包的责任边界)）。研究侧 `experiments/translation_v3/strata.py` 与 `scene_batching_v6/v13.py` 仍从 `kototoki.translate.strata` 导入 `drafting_from_log`、`StrataServer` 等名字，`experiments/` 不改，因此该模块保留为只做再导出的研究侧导入路径，产品内不使用（是否改研究侧导入另由用户裁定）。
5. **失败路径。**
   - 建表请求遇到传输失败、HTTP 错误、OOM：停掉 Strata，该影片 `names` 阶段文件级失败（`failure.json`），下一个需要模型的影片再启动。
   - 成功的启动不设整批上限（翻译"同调用内最多重启 2 次"仍是翻译自己的规则，行为不变）；Strata **启动失败**整批累计 3 次即 `unavailable`（与翻译"3 次连续 `server_start` 即放弃"、names 此前"整批最多 3 次启动"同量），其余需要模型的影片在两个阶段都直接失败。
   - `StrataRefused`（身份不符、已有别的 launch 在服务、专家区退到 mmap）不重试：共享 session 置为不可用，本批其余需要模型的影片在 names 与 translate 都直接失败。
6. **删除与保留。**
   - 删除产品里 names 的 llama-server 路径：`NAMES_SERVER`、`NAMES_SPEC`、names 自己的 `Session`、`BUILD["model_asset"]`、`<work root>/names-sessions/`；配置键 `[names] model`、`[names] port`、`[paths] llama_server` 与默认的 27B 模型路径（产品已无其他使用者）。写了这些键的旧配置按未知键报错，不做兼容垫片。
   - 保留 `kototoki/llama_server.py`：翻译与 names 的客户端用 `LlamaClient`，翻译另用 `InfraFailure`、`wait_for_free_vram`／`nvidia_smi`、`explicit_oom`；`ServerSpec`、`ManagedServer` 与驻留校验只剩研究侧 `experiments/translation_v3/qwen.py` 使用，留在原文件、不挪不删，产品不再使用。
   - 保留 `assets.toml` 的 llama.cpp 工具与 `unsloth/Qwen3.8-27B-GGUF` 条目（研究侧 Q0／Q1 与 H0 对照用），`just install`／`fetch-models` 行为不改；`experiments/` 不动。
   - `scripts/smoke/names_product.py` 改走 Strata（走共享 `Session`，核对 `expert_arena` 为 `ram`、`--stop` 后显存释放、建表 `ok`、全程没有 llama-server 进程）。

## 依据

- 用户 2026-11-09 采纳 Q3 为唯一翻译基线（ADR-0021）后，基线的表由 Strata 建、产品的表仍由 27B＋llama-server 建，两者不一致（[决定索引·未关闭项](INDEX.md#未关闭项)，本 ADR 关闭）。
- 切换后产品只剩 Strata 一种推理服务：去掉 names 的 llama-server 生命周期、27B 模型配置与资产核对，以及"停 llama-server → 等显存、等内存释放 → 启 Strata"这一步交接——2026-11-08 整片变慢（专家区退到 mmap）的起因之一就是这一步。
- 可行性：v13 的 GPU 入口已在一个 `StrataServer` session 里先建表、再翻译，整机内存峰值 60.4–62.4 GiB（共 63.9），见 [v13 报告](../research/2026-11-08-names-on-strata-v13.md)。
- Q3 建表的质量证据与已知风险（dev 剧集 wrong-referent 显著变差、同一部片两次建表写法 Jaccard 0.56／0.48）见 ADR-0021，用户已知并接受。

## 影响

- 配置：删三个键；默认模型目录只剩 STT 模型。
- 产物：所有旧 `name-table.json` 因配方 hash 变化失效、重建；注入行变化使翻译身份变化，未发布的影片重译，已发布的影片按 ADR-0020 跳过（源文件旁有字幕即不动）。
- 资源：names 阶段现在也要求 Strata 的启动条件（空闲显存 ≥14000 MiB、可用内存 ≥52 GiB）；整批只加载一次模型。
- 研究侧不受影响：`experiments/` 不改，`assets.toml` 条目保留，`kototoki.translate.strata` 导入路径保留。

## 未验证

- 产品路径的真实运行（smoke 与一部整片）在计划 §7 记录；运行前只经伪服务测试。
- `count_tokens` 退路、5 次都失败、`StrataRefused` 让两个阶段都失败等失败路径只经伪服务测试。
