# Strata＋Qwen3.8-Flash-Next（IQ3_S）用法调研：能否接到 Q1 的翻译步

状态：调研完成（2026-11-08），**未跑任何 GPU 作业、未启动 Strata**；文中带"未验证"的条目须由 [v12 立项文档](2026-11-08-strata-flash-next-v12.md)的 smoke 核实。  
范围：只回答两件事——本机装好的 Strata 怎么启停和调用；用它代替 Q1 里的 llama-server＋Qwen3.8-27B 做"最后一步翻译"需要改什么、有哪些不可避免的差异。不改产品 `kototoki/`，不改基线身份。  
来源（均为本机安装件，读于 2026-11-08）：

- `strata --version`：`strata 0.2.12 (build 0.1.58; python 3.12.15)`，安装于 `%LOCALAPPDATA%\Strata\terminal\current`；引擎组件 `components\engine\0.1.58-windows-x86_64-cuda-cuda13`。
- 随包文档 `docs/TERMINAL_LAUNCH.md`、`README.txt`，以及各子命令的 `--help`。
- 服务端源码 `serve/server.py`（路由、采样参数、思考控制）、`serve/structured.py`（结构化输出）、`setup.py`（模型规格表）。
- 本机状态文件：`launch/iq3_s-128k.json`（run config）、`launch/iq3_s-128k.choices.json`、`launch/iq3_s-128k.tune.json`（调优结果）。API key 等凭据未读出、未记录。
- 上游仓库：<https://github.com/Niko1221/Strata/>（本文没有另读在线文档；本机文档与源码已覆盖需要的内容）。

## 1. Strata 是什么

- 一个自带 Python 的本地推理服务＋终端客户端。`strata launch` 一条命令完成"选模型 → 下载 → 调优 → 启动服务 → 打开监视器"。
- 引擎是 Strata 自己的原生引擎（`component:strata-engine`），**不是 llama-server**。它面向大 MoE 模型：专家权重放在内存，显存里放专家缓存（`--expert-cache auto`），按需经 PCIe 搬运；带 MTP 草稿层做投机解码（`--spec 4`），也可选 DFlash2 草稿器。
- 对外是 OpenAI／Anthropic 兼容的 HTTP 服务（§4）。

## 2. 本机现状

| 项 | 值 |
| --- | --- |
| 模型 | `qwen3.8-flash-next-iq3_s`：ISTA-DASLab 的 `Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S` 两个分片，存于 `D:\Strata\Strata-data\models\IQ3_S\` |
| 规格（`setup.py`） | 下载 83.6 GB，需约 62 GB 内存；Strata 的说明是"3.5-bit i-quant，质量最好（在公开基准上与完整模型相当），最慢，需要 64 GB 且几乎不跑别的程序的 PC"。512 个专家的 MoE（Coder 版注释"保留 512 个专家中的 256 个"）。"与 BF16 相当"是供应方说法，未在本项目验证 |
| 已保存的 launch | `iq3_s-128k`（调优预设名 `IQ3_S 128K`）：context 131072，KV int8（常驻 32768），MTP 投机 `--spec 4 --spec-min-p 0.5`，图片读取在 CPU，**access `lan`（监听 0.0.0.0:8080）且设有 API key** |
| 调优实测（`tune.json`，quick） | decode 约 106 tok/s，prefill 约 2100 tok/s（长 prompt 约 3950），TTFT 1.95 s，加载 73 s；**内存峰值 51.4 GB、显存 15.6 GB／16.3 GB** |
| 运行状态 | 本次调研时未在运行（`procs/7444.json` 是旧记录，进程已不存在） |

由上表得出的硬约束：Strata 运行时几乎占满 5080 的显存和 64 GB 内存的八成，**不能与任何 llama-server（Qwen3.8-27B 建表、Hy-MT2 翻译）同时运行**，只能串行。

## 3. 启停与状态

建议给翻译另存一个只监听本机、关闭图片、单并发的预设，不动现有的 `iq3_s-128k`：

```powershell
# 先看计划：确认不会下载任何东西（应显示 0）
strata launch --plan --family qwen --model iq3_s --context 32k --parallel 1 --vision off --drafting mtp --access local --no-api-key

# 启动并保存为预设，打印地址后返回（服务留在后台）
strata launch --family qwen --model iq3_s --context 32k --parallel 1 --vision off --drafting mtp `
              --tune skip --access local --no-api-key --save-preset "kototoki-translate" --no-tui --yes

strata launch --status            # 正在服务什么
strata status --json              # 一次只读遥测快照
strata launch --stop              # 卸载模型、释放显存
```

选择理由：

- `--access local`：只绑 127.0.0.1，符合"本地运行"不变量；现有预设是 `lan`（0.0.0.0），做研究时不要用它。只监听本机时可以不设 key（`--no-api-key`）；若保留 key，客户端须带 `Authorization: Bearer <key>`（未验证头的具体形式，`strata connect --show-key` 可看），key 不进 Git 与日志。
- `--context 32k`：Q1 的 context 是 16384，32k 足够且比 128k 少占内存。换 context 后旧调优结果不复用，`--tune skip` 直接用默认值（调优只影响速度）。
- `--parallel 1`：与 Q1 的串行请求一致，也排除并发对输出的影响。
- `--drafting mtp`：现有 run config 用的就是 MTP；`auto` 在 Flash-Next 上会选 DFlash2，并首次下载 1.2 GB 草稿器。
- `--vision off`：翻译不读图，省约 0.9 GB 内存。
- 想在前台跑、终端关掉就停：`strata serve --profile <run config>`；后台托管：`strata runtime start|status|stop`。
- 只做客户端测试、不占 GPU：`strata serve --engine mock --profile <run config>` 起一个脚本化假引擎。

只有 `strata launch` 与 `strata update` 会联网下载，`serve`／`runtime`／`monitor` 不会。

## 4. HTTP 接口

路由（`serve/server.py`）：`/v1/chat/completions`、`/v1/messages`、`/v1/responses`、`/v1/messages/count_tokens`、`/v1/models`、`/v1/status`、`/metrics`、`/v1/telemetry`，另有 `/v1/load`、`/v1/unload`、`/v1/vram`。

`/v1/chat/completions` 识别的请求字段：

| 字段 | 行为 |
| --- | --- |
| `temperature` | >0 时采样；0 或缺省为贪心 |
| `top_p` | <1 时生效 |
| `top_k` | **最多 64**：0（关）或 >64 都按 64 处理。Q1 用 20，不受影响 |
| `min_p` | (0, 1] 时生效 |
| `repetition_penalty`／`repeat_penalty`、`frequency_penalty`、`presence_penalty` | 非默认值时生效，窗口默认最近 64 token（`penalty_last_n`） |
| `seed` | **只接受正整数**；0 或缺省为不定 |
| `max_tokens`／`max_completion_tokens` | 0 或 −1 表示用完剩余 context |
| `chat_template_kwargs.enable_thinking` | `false` 关思考；也认 `reasoning_effort`、`thinking_budget_tokens`／`reasoning_budget_tokens` |
| `response_format` | `json_object`／`json_schema`，方式是 **"提示＋事后校验"**（会改动 messages），失败即报错、不重试 |
| `logprobs` | 支持（多卡 split 引擎除外） |

响应里有 llama.cpp 形式的 `timings`（含 `cache_n`、`prompt_n`）和 `usage`。

**没有的东西**（对接 Q1 最关键）：

- **没有 GBNF 语法约束解码**：`structured.py` 开头写明 "The native engine has no grammar decoder"。请求里的 `grammar` 字段不会生效（是静默忽略还是报 400，未验证）。
- **没有 llama.cpp 的 `/apply-template` 与 `/tokenize`**。能"渲染模板并计 token"的只有 Anthropic 方言的 `/v1/messages/count_tokens`。
- 有自己的会话缓存（前缀复用），不读 `cache_prompt`。

两项会影响复现的自动行为：

- **推理循环自救**：检测到生成陷入重复时，服务端会把该请求的 `temperature` 提到 ≥1.0、`presence_penalty` 提到 ≥1.5 再续写（计数记在 `reasoning_recoveries`）。non-thinking 的翻译请求是否会触发，未验证。
- logits 出现非有限值时，回复以 `finish_reason: "length"` 结束，下一请求从头读 prompt。

## 5. 接到 Q1 的翻译步：差异与做法

Q1 的翻译步是 `experiments/translation_v3/qwen.py`：由 `kototoki.llama_server.ManagedServer` 起 llama-server b11669（Qwen3.8-27B UD-IQ3_S，`--jinja --reasoning off`），每个包发一次 `/v1/chat/completions`，带 ID GBNF 语法，用 `/apply-template`＋`/tokenize` 先查输入预算，失败后换 seed＋1 重试一次。换成 Strata 时逐项对照如下：

| 环节 | Q1 现状 | Strata 下的做法 |
| --- | --- | --- |
| 服务生命周期 | `ManagedServer` 启动并独占 llama-server，进 Job Object，v3 `gpu.lock` | 不能由 `ManagedServer` 启动。实验代码改为"附着"已运行的 Strata：开跑前用 `strata launch --status --output json` 与 `/v1/models` 核对模型名 `qwen3.8-flash-next-iq3_s`、context、drafting，并把这些写进 run 身份；仍然持有 v3 `gpu.lock`；启停由执行者用 §3 的命令完成 |
| 输出格式约束 | GBNF：只能生成合法的 ID JSON | **无法约束**。保留 `qwen.parse`（ID 集合、非空、顺序）事后校验，失败按原规则换 seed 重试一次。格式失败率是新的必报终点。不用 `response_format`，因为它会改 prompt，两臂就不再是同一提示 |
| 输入预算 | `/apply-template`＋`/tokenize`，超 16384 预算即记失败 | 没有这两个端点。服务端 context 32k 远大于 Q1 包的输入，直接发送；以响应里的 `usage.prompt_tokens` 记录输入长度，并标出超过 Q1 预算的包（两臂切包相同，正常不会出现） |
| 首个请求缓存检查 | 要求 `timings.cache_n == 0` | Strata 也回 `cache_n`；附着到已运行的服务时，首个请求可能命中上次的缓存，所以改为只记录、不作失败 |
| 思考 | 服务端 `--reasoning off`，请求带 `enable_thinking: false` | 服务端无全局开关，**每个请求都必须带** `chat_template_kwargs: {"enable_thinking": false}`；smoke 须核实 `reasoning_content` 为空、`reasoning_tokens` 为 0 |
| 采样 | `0.7／0.8／20／0`，presence 0，`seed` | 原样可用（`top_k` 20 ≤ 64）。`seed` 须 >0（Q1 的 seed 都满足） |
| 专名表 | 产品 `names` 用 Qwen3.8-27B 建表，再注入 Q1 | 建表**不换模型**，仍是产品 names 阶段；只换翻译模型。两者不能同时驻留，须先建表、停 llama-server、再起 Strata。研究里 v11 已建好的表直接复用 |
| 产品接入 | — | 本次不做。若要进产品，需要在 `kototoki/` 新增"外部 OpenAI 兼容服务"后端并处理无 grammar 的失败路径，另立项 |

## 6. 最小手工检查（需用户授权后执行）

启动 §3 的预设后，发一个 non-thinking 请求，看是否返回干净的 JSON、`reasoning_content` 是否为空、两次同 seed 是否相同：

```powershell
$body = @{
  model = "qwen3.8-flash-next-iq3_s"
  messages = @(@{ role = "system"; content = "把用户给出的日文译成简体中文，只输出 JSON：{`"1`": `"译文`"}" },
               @{ role = "user"; content = "{`"1`": `"今日はいい天気ですね。`"}" })
  temperature = 0.7; top_p = 0.8; top_k = 20; min_p = 0.0; presence_penalty = 0.0; seed = 20261011
  max_tokens = 256; chat_template_kwargs = @{ enable_thinking = $false }; stream = $false
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri http://127.0.0.1:8080/v1/chat/completions -Method Post -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

## 7. 未验证项

- 请求里的 `grammar` 字段是被忽略还是被拒绝。
- `enable_thinking: false` 在 Flash-Next 的模板上是否完全关闭思考。
- 投机解码（MTP）＋采样下，同 seed、同 prompt 是否逐字复现。Q1 的 llama-server 有约 24% 的单元不复现（v11 §8 第 5 项）。
- 推理循环自救在 non-thinking 翻译请求上会不会触发、多久触发一次。
- 无 grammar 时 ID JSON 的格式失败率。
- 32k context、`--parallel 1`、`--vision off` 下的实际内存与显存峰值，以及整片墙钟。
- 供应方"IQ3_S 与 BF16 相当"的说法，以及 Flash-Next 的日译中质量是否优于 Qwen3.8-27B。后者是 v12 要回答的问题。
