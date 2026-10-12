# 翻译比较执行接跑记录

状态：计划执行完成；报告已交付，质量比较为暂定，408/415 有语义终分。

## 完成交付

- [中文结果报告](../research/2026-10-06-translation-model-comparison-results.md)；本地机器报告为运行根目录 `report/report.md` 与 `report/metrics.json`，复现为 `reproduction.md`。
- 415 个预期候选窗口全部有终态，五候选各 83 窗口／414 IDs。408 有语义终分；TG 映射 null 6 项、Hy7 `06-3-3` 裁决未决 1 项。没有待执行的必需裁判任务。
- 主评 409、复评 399、裁决 119 项全部有效返回；940 次实际 fresh gpt-6.1-sol/high 调用包含 13 次失败及有限重试，0 项准备后未派发。119 项初始分歧中 31 项改变语义或自然度分数。
- 最终账本 SHA256：`793766c4794208a6eba196c629b13b8e283316ea35dbd0cd7d7254df6935e72c`；summary：`1e897604331c3e6b2b1ccc8a193bd979f17e1a84a9042492db487d9497e85f21`。
- 完整裁判审计：`test-eval-v1/subagent-execution/execution-final-audit.json`。两项主评 raw 后写例外已保留，不声称原始响应哈希全部闭合。未决项按冻结规约终结，不追加语义重试。
- 接跑时先核对报告与最终审计；本轮无待续推理。后续修复／CLI 迁移／新参数评估使用独立版本及新目录，保留本轮证据。

## 过程记录（以下保留各阶段当时状态）

阶段 1–3 完成。`dev-eval-token-v1/` 的 44 主评＋44 盲复评＋10 裁决全部一次有效，
48 个预期候选窗口完整保留；44 有语义终分，TG 两候选各 2 映射 null。
10 个初始争议均裁决收尾，4 个分数变化；这仅是开发闭环，不用于 test 排名。
冻结清单为 `.local/translation-evaluation/20261006-v1/freeze.json`，SHA256：
`d23853bc140713bb305702fe08ddc5f387c116852a1a0694f5fcd842235f84ad`。
145 个冻结文件核验无变化；源码／当时文档在 `freeze-source/`，复现见 `reproduction.md`。

完整 test 七阶段已结束，原生输出 `test-v1/`，TG 映射输出 `test-map-v1/`，
调度账本 `test-v1-schedule.json`，shell session `96738` 已 exit 0，当前无该套模型服务需接跑。
五候选原生均 83/83；TG12 映射 81/83、TG27 79/83，6 个不可评保留 null。
`test-transport-audit.json` 独立核对七阶段全部源码／输入范围、真实 token 及响应记录。
`prepare_fixed_test.py` 已完成，三份逐 ID validator 均 exit 0，TG 显式不适用该格式并走分组契约。
统一五候选 `test-eval-v1/` 保留 415 个预期候选窗口，409 项可评主评任务已导出；
prompt 与 runner SHA 均匹配冻结。由 `/root/judge_resume` 调度 fresh
`gpt-6.1-sol / high / fork_turns=none` 主评、共同并集盲复评与必要单次裁决。
每窗全新子 agent，裁判并发最多 16，分工只写各自任务输出；应核对目录与子 agent 实际状态后接跑。
正式本地执行后已完整重新扫描五份模型 SHA256，全部与冻结身份一致，见 `weights-posttest-verification.json`。
正式主评 409/409、共同窗口盲复评 399/399 已有效完成；119 项分歧进入单次裁决。
用户已升级 Codex CLI，但本轮保持已冻结且可用的子 agent 执行面，不中途混换。
早期 CLI 0.147.0 失败仅代表当时版本／账户路径，不能据此断言升级后的 CLI 仍不可用。
恢复时旧协调器及裁判不再活动，`/root/judge_resume` 已按既有调用账本恢复；已有原始响应先导入，已实际派发但无响应的请求按传输中断保留原尝试并仅使用剩余预算。
两项主评存在导入后数秒的原文件后写：A/M04-2 仅摘要变化，B/10-3-3 仅一条错误理由与摘要变化，分数与严重错误签名不变。原接受记录及后续评估仍采用 canonical；原始旧字节缺失是证据限制，不覆盖哈希或重新语义评分。逐字段审计见 `test-eval-v1/subagent-execution/primary-later-write-diff.json`。
外部语料正式运行后再核验 2,479 文件通过，见 `corpus-verification-posttest.log`；冻结 145 文件再次核验无变化。
随后生成中文正式报告并核对完整分母；不要再修改冻结推理／评分代码，工程修复须另记版本。

下列较早记录保留为开发过程，不覆盖本节最新状态。

## 当前证据

- 运行根目录：`.local/translation-evaluation/20261006-v1/`。
- `corpus-verification.json`：2,479 个冻结文件全部通过，无额外文件。
- 外部结构 validator 自测通过；五模型 manifest 均为 verified，完整哈希沿用资产获取记录。
- GPU：RTX 5080，驱动 616.92，16,303 MiB；准备时整卡占用约 1,796 MiB。
- llama.cpp 稳定 v0.6.0 指向 b11429／d81235049；Windows CUDA 13.4 x64 引擎与 runtime 位于 `.local/tools/llama-b11429-cuda13.4/`。两个 ZIP 的 SHA256 与官方 digest 一致；Hy7 宿主服务加载成功，日志加载约 3.66 秒。
- 三套家族适配器位于 `experiments/translation_demo/`，评估模块位于 `experiments/translation_eval/`；均在实现中，尚未通过运行验收。
- Codex CLI 0.147.0 的四项合成探针均返回指定模型不受当前 ChatGPT 账号 CLI 支持（HTTP 400），未替换模型。改为本会话显式 `gpt-6.1-sol / high`、`fork_turns=none` 子 agent 执行面探测，CLI 失败原件保留在 `judge-probe/`。
- Hy7 首轮完整 smoke 为 14/15 结构交付，`05-1-1` ID 缺失失败保留在 `smoke-v1/`；仅增加 GBNF 的开发修复仍触顶，保存在 `dev-05-gbnf-v2/`，继续源文侧提示修复，不读取参考或裁判反馈。
- 评估器 8 项离线测试、翻译器首版 9 项离线测试通过。`dev16.jsonl` 为全部 smoke 加四条计分 `11-1-2`，共 16 窗口／79 IDs，不与 test 混计。
- 沙箱启动的 llama 进程出现监听但 loopback 不可达；宿主侧启动及请求正常。真实推理使用 `require_escalated`，仅连接本机 127.0.0.1；保留先前启动失败，不并发加载模型。

## 开发验证进展

- `dev-v3/hy-mt2-7b-q8/` 与 `dev-v3/tower-plus-9b-q8/`：同一 dev16，均 16/16 结构交付；源码与完整 prompt 随运行保存。初步整卡峰值分别 9,948／12,562 MiB，不是模型独占显存。
- `dev-v3-runtime2/translategemma-12b-q8/` 与 `translategemma-27b-q3-k-l/`：均 16/16 原生段落交付，尚不代表计分映射成功；模型层分别 49/49 与 63/63 GPU offload，整卡峰值 13,837／15,709 MiB。
- TranslateGemma 服务自动聊天 parser 不支持其 typed-content 模板；仅关闭未使用聊天端点的 Jinja parser，实际 `/completion` 仍传原生翻译 prompt。两模型真实 GGUF Jinja 与 adapter 逐字节对照通过，见 `template-validation.json`。
- 显式语言适配是 `ja→zh-Hans`：两个 GGUF 的语言表含 `zh-Hans` 而无 `zh-CN`，与冻结输入目标一致；不是静默默认语言。
- `dev-map-v1/`：Hy7 原样全文复制映射失败为 TG12 16/16、TG27 15/16，不可评保留，未修补候选译文。`dev-map-v2/` 在开发验证 Tower 纯边界锚点方法，由程序提取原生字符区间。
- Hy30 固定 GGUF 的 47 个 `exp_probs_b.bias` 与 b11429 loader 读取名称不匹配；独立标识的兼容核心 DLL 已构建，权重不改，证据在 `hy30-compat/`。`dev-v3-hy30compat/hy-mt2-30b-a3b-q3-k-m/` 已 16/16 交付，49/49 层 GPU offload；只修改偏置张量名称 fallback，原 CUDA DLL 保持字节一致。
- `judge-subagent-probe/`：四项真实独立 Sol/high 合成判断通过。`dev-eval-ab/` 正在执行 Hy7／Tower 的 32 个开发包主评及后续独立复评；映射开发不读取该目录。

### 当前有效开发配方

`dev-map-v4/` 的 `native-scored-groups-gbnf-v4` 按源文中的计分／非计分连续区间分组，允许计分组内合句；不把同一段复制给多个 IDs。TG12 为 14/16 可靠映射、2 不可评；TG27 为 15/16、1 不可评。两者 16/16 原生生成记录全部保留。旧 v1/v2/v3 映射失败与成本仍分别在各自目录，不能只报最新成功成本。

`dev-eval-ab/` 已完成 32 主评＋32 盲复评＋8 单次裁决，无 schema/transport 重试，无最终语义缺分；8 个初始分歧均有终态。墙钟约 677.80 秒，任务累计时延含调度；费用／token／服务端模型版本未暴露，保持未知。`dev-eval-c/` 已完成 16 主评＋16 盲复评＋6 裁决，39 次调用包含一次 JSON 格式重试，全部收尾；墙钟约 600.64 秒。这些仅证明开发闭环已运行，不用于正式 test 排名。

`dev-eval-de/` 首批 16 次调用有 8 次被旧证据校验拒绝：语义漏译在仍含其他中文的组内没有可引用的候选片段。按规约“缺失文本允许空候选引用”统一修正 per-ID 与分组校验，仍要求逐字源文证据及说明，其他错误仍要求候选引用；评分锚点不变。旧目录完整保留，未派发的 13 项为 `interrupted_development`，不冒充裁判失败；旧调用成本保留。新 `dev-eval-de-v2/` 使用相同候选原件重新派发全部 29 项 fresh 主评并执行复评／裁决。修正证据见 `evidence-v2-validation.json`；新 prompt SHA256 为 `1f6312a5968b491f41b5c9ef7e5469fa93f631675c2ec2a64c36ca402c99ce9a`。正式 test 全五候选将使用同一冻结版本。

所有五个版本原生模板已与本地 GGUF Jinja 对照通过，分别见 `template-validation.json` 与 `template-validation-other.json`。Hy30 的真实 GPU 16/16 smoke/dev 通过；原始 766 tensor 的无分配加载和有／无后缀两合成文件也通过。

实测本地运行包装入口为 `python -m experiments.translation_demo_runtime`；实际命令见各 runtime 目录。不得复用已有输出目录覆盖旧尝试；冻结前开发运行保留独立版本。

### 冻结前 token 传输修正

实际服务响应显示 Tower 与两个 TG 的 `/completion` 字符串 prompt 被服务器自动再加一个 BOS，
与 adapter／GGUF Jinja 文本逐字相同并不等于实际模型输入一致。`dev-eval-de-v2/` 已派发的
12 项 fresh 主评全部通过后停止新增派发，17 项记开发中断；保留 114.24 秒墙钟及 855.57 秒任务时延。
已修正为 `/tokenize(add_special=false, parse_special=true)` 的整数 token 数组直接提交，
`dev-token-v1/` 五候选全部 16/16 原生交付；`dev-token-map-v1/` 两个 TG 各 14/16 可评、2 不可评。
七个阶段的全部实际 prompt、token 数、来源哈希及重试预算均通过，证据为 `token-transport-audit.json`。
Hy7／Hy30 新旧计分译文分别 16/16 完全相同，原开发语义闭环仍是开发证据，未复制旧评分到新运行；
Tower 有 11/16 译文变化，与两个 TG 一起在 `dev-eval-token-v1/` 重新评估。
该目录已 44/44 全新主评一次成功，正在共同 16 窗口的 44 次盲复评及必要裁决；四个映射 null 保留。
旧运行不覆盖，正式 test 仍未开始。当前离线 60 项检查通过，冻结前语料 2,479 文件再次核验通过。

全局冻结入口已准备为运行根目录的 `freeze_comparison.py`；须等上述语义闭环完成再执行 `freeze`。
`run_local_suite.py` 顺序运行五原生加两映射阶段；正式阶段目录约定为 `test-v1/`、`test-map-v1/`。
`prepare_fixed_test.py` 在核验冻结后准备统一五候选评估 `test-eval-v1/`，并保存外部逐 ID validator 结果；
TG 使用独立分组契约。`reproduction.md` 记录新目录复现方式，不覆盖既有证据。

## 实施边界与下一步

保留五候选身份，逐个加载 GPU。TranslateGemma 使用实际 GGUF 支持的 `ja→zh-Hans` 模板；完整窗口段落输出经本地辅助模型作纯字符跨度关联，不允许改写、参考答案或裁判反馈进入映射。映射无法确定时保留不可评终态。

先完成适配器、账本、裁判执行器的离线验证，再五版本 smoke 和四条计分 dev 边界，完成实际主评／复评／裁决闭环后冻结配置。尚未启动正式 test，不得提前依据 test 反馈调整配方。

接跑须检查实际进程与文件，不因本记录推定后台任务仍存活；所有失败尝试、下载或运行中断保留证据。当前没有模型质量成绩。
