# ADR-0029：产品翻译（配方 `q3-translate-v1`）

状态：已接受。2026-11-18 按主题合并（用户授权）：并入 ADR-0019、ADR-0022 第 3–5 点，原文见 git 历史（提交 807de3e 及之前）。
范围：产品包 `kototoki/translate/` 的请求规则、回复判定、失败路径与配方身份，`kototoki/merge.py` 对未翻译 cue 的输出，以及 `kototoki/strata.py` 的 Strata 生命周期与 names／translate 共用的 session。切包 `dp10-cut` 的规则见 [ADR-0021](0021-q3-strata-names-baseline.md)，专名表的建法见 [ADR-0028](0028-names-accept-empty-table.md)；本文不重复。

## 决定

### 请求规则

1. 每部影片的 `ja.srt` 是一个场景，按基线 Q3（[ADR-0021](0021-q3-strata-names-baseline.md)）的翻译规则组请求：切包 `dp10-cut`（`gap-pack-v2`，切包规则见 ADR-0021）；邻文 `wide-context-v1`（前 20、后 5 条，只按条数取到场景边，可见超过 35 条时先去后邻）；提示 `qwen-joint-v1`；专名注入 `qwen-name-table-v1`（过滤 `window`）；模型 Strata 上的 `qwen3.8-flash-next-iq3_s`；chat completions、不用 grammar、思考关闭、采样 0.7／0.8／20；每个请求最多两次尝试（seed、seed＋1）。
2. 首个请求即全部合格的批次，请求体与研究侧 Q3 逐字节相同。产品里没有 Hy-MT2 后端、H0 配方与相关开关，也没有迁移垫片。
3. 切包时 `ja.srt` 的每条日文 cue 就是一个翻译单元；译文按 cue ID 一一对应。

### 专名注入

1. **只注入、不替换；建表必开。** 没有发布时专名替换，没有 `[names] enabled`。注入行取自该片 `name-table.json`：只取 `confidence: high` 的实体，每个 `forms[]` 一行 `{ja → zh}`，按 `ja` 去重，跳过空写法。
2. 注入行的 SHA256（`names_sha256`）进翻译身份与 run 目录键：手改表只要改到注入行就另起 run、重译该片；只改 medium／low 条目不触发重译。
3. 建表终态失败得到空表，翻译照常进行、不注入（建表规则见 ADR-0028）。

### 按条收下

1. **结构失败才算这次尝试失败。** 回复被截断（`finish_reason == length`）、HTTP 报超出 context、不是 JSON、不是恰好一个 `translations` 对象，这次尝试失败，换下一个 seed（超出 context 不换，直接终态）。
2. **结构合法即按条判。** 值为非空字符串且不含空行的 cue 收下；缺失（`missing`）、空串或非字符串（`empty`）、含空行（`blank_line`）的 cue 记为未解决；多出的 ID 与 ID 顺序不看，多出的个数只进尝试记录。一条都没收下的尝试计为失败（`unresolved`），换下一个 seed。

### 只追问没解决的 cue

1. 节点是场景内连续的一段待译 cue，初始节点即切包产出的批次，每个节点最多两次尝试（seed、seed＋1）。
2. 某次尝试收下至少 1 条，节点结束；未解决的 cue 按场景顺序切成最大连续段，每段成为子节点 `父ID.1`、`父ID.2`…。
3. 两次都失败时，多于 1 条的节点对半拆成 `父ID.a`／`父ID.b`（奇数条时前半多 1 条）；只有 1 条的节点，该 cue 不出中文。
4. 子节点用同一条邻文规则、同一专名注入规则，seed 从原 seed 起。子节点必比父节点小，过程必然终止。

### 不出中文的 cue

1. 不出中文的 cue 只输出日文一行：译文映射里它的值为 `None`（JSON `null`），空串仍然非法；合并时该条只有日文一行，不把日文抄进中文行。
2. 原因记为该 cue 最后一次未解决的类别（`missing`／`empty`／`blank_line`），没有按条结果时记失败种类（`parse`／`limit`／`context`）。
3. 计数叫"未翻译"：`TranslateResult.untranslated_count`、`report.json` 的 `untranslated_cues`、`published.json` 的 `translate_untranslated_cues`、发布行与汇总的 `untranslated cue(s)`。

### 基础设施失败

传输中断、OOM、服务错误、服务起不来按基础设施失败处理：停掉 Strata、重新启动，同一次调用内最多重启 2 次。`StrataRefused`（身份不符、已有别的 launch 在服务、专家区退到 mmap）不重试：共享 session 置为不可用，本批其余需要模型的影片在 names 与 translate 都直接失败。

### Strata session

1. **Strata 由产品自动启停，names 与 translate 共用一个 session。** 整批只启动一次：第一次真正需要请求模型时启动（可能在 names，也可能在 translate），两个阶段之间不停；整批结束、出错或编排被中断时执行 `strata launch --stop`，再核实 `--status` 为空、空闲显存回到 14000 MiB，核实失败记 ERROR 与 `strata-final.json`。没有影片需要模型时不启动 Strata。产品任何阶段都不启动 llama-server、不加载 27B。GPU 锁照常记录 Strata 的 pid。
2. **启动前检查。**
   - `strata launch --status` 必须为空（不抢占、不替别人停）。
   - 空闲显存达到 14000 MiB。
   - 可用内存轮询到 ≥ 52 GiB（Windows `GlobalMemoryStatusEx`；专家区要 46.84 GiB 常驻内存，分配前引擎自己还先占约 4.8 GiB）；等满 180 s 仍不够只记 WARNING 照常启动。
3. **启动命令** `strata launch --no-tui --model iq3_s`。不带参数的 `strata launch` 会打开交互向导，子进程里（或带 `--no-tui`）不点名 `--preset`／`--model` 时以退出码 2 拒绝；`--model iq3_s` 正是默认选择本身，其计划与默认启动逐行相同（`IQ3_S 128K`、DFlash2、图片读取器在 CPU、本机 8080，等价于 `--model iq3_s --context 128k --vision cpu --tune skip --access local --port 8080`）。
4. **接入检查**（身份见「身份」一节）：等到唯一一个 ready 的 launch 后逐项核对：版本 0.2.12／build 0.1.58、本机 8080、run config 模型名与 `--max-context 131072`、DFlash2、`/v1/models`、`/v1/status` 原生上下文 131072，不符即停掉并拒绝。DFlash2 取自本次启动写进服务日志的 `[strata] drafting:` 一行（须为 DFlash2）；不按 run config 参数判断，因为 Strata 总会给引擎传 `--mtp <权重目录>`，会把默认启动误认成 MTP。
5. **专家区检查。** ready 后读本次启动写进 `%LOCALAPPDATA%\Strata\launch\<name>.engine.log` 的新内容，判断专家区在内存（`ram`）还是退到 mmap 从 SSD 读（`mmap`，答案不变、慢约 5 倍），记进 `strata.json` 的 `expert_arena`。只有日志记有 `expert arena: locked`（全部专家锁进内存）且没有退到 mmap 的记录才算 `ram`；`mmap` 或无法确认时停掉 Strata 并拒绝（`StrataRefused`，本批不再重试）。
6. **生命周期在中间层 `kototoki/strata.py`**（与 `local_client.py` 同层，不属基础层）：`StrataServer`、`StrataRefused`、Strata 身份常量（模型名、版本、引擎 build、默认启动的解析值）与共享 `Session`（整批一个、启动计数、`unavailable`、`ensure_started`／`stop`、`on_server_pid`）。编排器持有 `Session` 并传给两个阶段；`names` 与翻译子系统互不导入；翻译子系统保留自己的同调用内重启与降级逻辑，只是改用共享的 session。
7. **失败计数。** 建表请求遇到传输失败、HTTP 错误、OOM：停掉 Strata，该影片 `names` 阶段文件级失败（`failure.json`），下一个需要模型的影片再启动。Strata 启动失败整批累计 3 次即 `unavailable`，其余需要模型的影片在两个阶段都直接失败；成功的启动不设整批上限。
8. Strata 安装与模型下载在仓库外，由用户维护（[依赖布局](../development/dependencies.md)）；版本不是 0.2.12／build 0.1.58 时拒绝运行，升级等于换身份，须新决定。

### 配置与产物

1. `[translate]` 只有 `seed`（须为正整数，Strata 不接受 0）；模型由 Strata 管理，端口固定 8080。写了已删除的键（`model`、`port`、`[names] enabled` 等）按未知键报错，不做兼容垫片。
2. 翻译身份 = `{ja_srt_sha256, recipe_hash, seed, names_sha256}`。run 目录 `translate/srt-<sha12>/q3-translate-v1__s<seed>__n<names_sha12>/`，节点日志 `nodes.jsonl`，`report.json` 的 schema 为 `kototoki-translate-report-v2`。
3. 配方变即翻译身份变，旧 run 目录不再读取，下次运行重译。已发布的字幕按 [ADR-0007](0007-bilingual-subtitle-pipeline-architecture.md) 的发布规则照旧跳过（源文件旁已有字幕即不动），要重做须先删掉该字幕。
4. [ADR-0008](0008-no-multi-translation-selection.md) 继续适用：两次可靠性尝试、按条追问与对半拆分都不是"翻译多次再挑选"；按条取第一个合格译文、不比较不同尝试。

## 身份

- 当前配方 `q3-translate-v1`，`RECIPE_HASH` `865bcd1d06f0cc7af83a02f90d0ff2ae5c1fca012695d28e1dbbe4b4f0325964`，由 `tests/core/test_translate_recipes.py` 钉住（`kototoki/translate/recipes.py` 的 `RECIPE`；`rule`、`validation`、`overflow` 字段描述本文的按条收下规则）。
- 历史配方 `q2-degrade-v1`，hash `332649cf98662e42cccc31485792104c3ce6303e6cd634ef42ef85839ee9310d`：10→5→1 降级、单条仍失败保留日文、含空行按解析失败处理；已被 `q3-translate-v1` 取代，只作历史身份。其前任 `dp10-cut-degrade-v1` 见 ADR-0021。
- 运行时身份：Strata 0.2.12、引擎 build 0.1.58、默认启动（IQ3_S、128K、DFlash2、本机 8080）、模型 `qwen3.8-flash-next-iq3_s`，与基线 Q3 同（ADR-0021）。

## 依据

- 首次大批量运行（2026-11-12～11-15，228 部）：失败尝试 121 次，全部是格式类，没有一次是模型拒绝翻译；空值 82 次，全在第 1 次尝试，换 seed 后几乎都通过。旧规则下一条空值让整批约 10 条全部重来，所以改为按条收下、只追问未解决的 cue。
- 空串不当合法答案：空值 cue 多是上一句的碎尾（「した」「でした」），但也有实义台词（「何でしょうか?」），直接放行可能悄悄丢台词，所以记为未解决、单独再问。
- 只改失败路径：首个请求即全部合格的批次请求体不变，因此不做翻译质量评估（用户裁定）。
- 产品与基线不应分叉（用户 2026-11-08 决定）：产品翻译即 Q 链规则，Strata 的外部服务后端、无 grammar 的失败路径、两种服务不得同时驻留等进产品前置项由本文逐项给出做法。
- 共用一个 session：names 与翻译同为 Strata 请求后，产品只剩一种推理服务，省去"停 llama-server → 等显存和内存释放 → 启 Strata"这一步交接；2026-11-08 整片变慢（专家区退到 mmap，每包约 16 s 对约 3 s）的起因之一正是这一步。整机内存峰值 60.4–62.4 GiB（共 63.9），可行。
- 抽取 `kototoki/strata.py` 是第二个使用者出现后的正当抽取（[模块边界](../architecture/module-boundaries.md#产品包的责任边界)）。

## 未验证与已知限制

- 按条收下与追问路径只经伪客户端离线测试，没有在 GPU 上运行；追问请求只有未解决的 cue 作待译、其余可见台词作只读邻文，模型在这种窗口下的译文质量没有裁判证据；单独再问的碎尾 cue 有多少最终仍不出中文，未知。
- Strata 的请求不复现（同 seed 约半数 cue 不同），重跑不保证同一译文。
- 产品进程被强杀时 Strata 可能留在后台：下次运行会因 `--status` 非空而拒绝，需手动 `strata launch --stop`。
- 失败路径（`count_tokens` 退路、`StrataRefused` 让两个阶段都失败等）只经伪服务测试。

## 沿革

- 2026-11-08 ADR-0019：产品翻译切到 Q2，Strata 由产品自动启停，只注入不替换，10→5→1 降级，配方 `q2-degrade-v1`。
- 2026-11-09 ADR-0022：names 与翻译共用一个 Strata session，生命周期下沉到 `kototoki/strata.py`。
- 2026-11-17 ADR-0029：改为按条收下、只追问没解决的 cue，不出中文的 cue 只输出日文一行，配方 `q3-translate-v1`。
- 2026-11-18 按主题合并 ADR-0019、ADR-0022 第 3–5 点入本文。
