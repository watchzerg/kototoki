# ADR-0019：产品翻译切到 Q2（Strata 自动启停、只注入不替换、10→5→1 降级）

状态：已接受（2026-11-08，用户决定）。替代 [ADR-0007](0007-bilingual-subtitle-pipeline-architecture.md) 第 3 点中"翻译与建表用独立进程的官方 llama.cpp"里的翻译部分、[ADR-0010](0010-dp10-cut-translation-flow-baseline.md) 第 6、7 点（产品配方 `dp10-cut-degrade-v1` 与其 run 目录）、[ADR-0014](0014-name-consistency-in-product.md) 第 3 点中的"发布时替换"、第 5 点（`[names] enabled`）、第 6 点（`names_apply`）与第 7 点（手改表只重做替换）；[ADR-0018](0018-q2-sole-translation-baseline.md) 第 3 点"产品当前的翻译实现"一项随之失效。  
范围：产品包 `kototoki/` 的翻译实现与专名表的用法。不改 Q2 的身份（[ADR-0017](0017-q2-strata-default-launch-baseline.md)），不改建表配方，不开封确认集。

## 决定

1. **产品翻译即 Q2 规则。** 每部影片的 `ja.srt` 是一个场景，按 Q2 组请求：切包 `dp10-cut`（gap-pack-v2，参数同 ADR-0010 第 2–3 点），邻文 `wide-context-v1`（前 20、后 5 条只按条数取到场景边，可见超过 35 条时先去后邻），提示 `qwen-joint-v1`，专名注入 `qwen-name-table-v1`（过滤 `window`），模型 Strata 上的 `qwen3.8-flash-next-iq3_s`，chat completions、不用 grammar、思考关闭、采样 0.7／0.8／20，每包最多两次（seed、seed＋1）。正常包的请求体与研究侧 `experiments/translation_v3/strata.py::request_body(qwen.messages(…))` 逐字节相同。产品里不再有 Hy-MT2 后端、H0 配方与相关开关，也没有迁移垫片。
2. **Strata 由产品自动启停，不与 llama-server 同时驻留。**
   - names 阶段整批用 llama-server 建表，建完即停 server。
   - 翻译阶段第一次真正需要请求模型时：`strata launch --status` 必须为空（不抢占、不替别人停）；空闲显存达到 14000 MiB（names 的 server 已释放）；可用内存轮询到 ≥ 52 GiB（Windows `GlobalMemoryStatusEx`；专家区要 46.84 GiB 常驻内存，分配前引擎自己还先占约 4.8 GiB，建表进程的内存可能还在释放；等满 180 s 仍不够只记 WARNING 照常启动）；执行 `strata launch --no-tui --model iq3_s`；等到唯一一个 ready 的 launch 后按 ADR-0017 的接入检查核对（版本 0.2.12／build 0.1.58、本机 8080、run config 模型名与 `--max-context 131072`、DFlash2（起草方式取自本次启动写进服务日志的 `[strata] drafting:` 一行（须为 DFlash2；Strata 总会给引擎传 `--mtp <权重目录>`，按 run config 参数判断会把默认启动误认成 MTP，2026-11-08 首次 smoke 实测））、`/v1/models`、`/v1/status` 原生上下文 131072），不符即停掉并拒绝；ready 后读本次启动写进 `%LOCALAPPDATA%\Strata\launch\<name>.engine.log` 的新内容，判断专家区在内存（`ram`）还是退到 mmap 从 SSD 读（`mmap`，答案不变、慢约 5 倍），记进 `strata.json` 的 `expert_arena`；只有日志记有 `expert arena: locked`（全部专家锁进内存）且没有退到 mmap 的记录才算 `ram`，`mmap` 或无法确认时停掉 Strata 并拒绝（`StrataRefused`，本批不再重试）（2026-11-08 整片实测：内存不够时专家退到 mmap，每包约 16 s 对约 3 s）。
   - 整批结束、出错或编排被中断时执行 `strata launch --stop`，再核实 `--status` 为空、空闲显存回到 14000 MiB；核实失败记 ERROR 与 `strata-final.json`。不需要翻译时不启动 Strata。
   - `--no-tui --model iq3_s` 不改启动配置：不带任何参数的 `strata launch` 会打开交互向导，子进程里（或带 `--no-tui`）不点名 `--preset`／`--model` 时以退出码 2 拒绝（2026-11-08 首次 smoke 实测）；`--model iq3_s` 正是默认选择本身。2026-11-08 本机 `strata launch --plan` 与 `strata launch --no-tui --model iq3_s --plan` 的计划逐行相同（`IQ3_S 128K`、DFlash2、图片读取器在 CPU、并发按卡适配、本机 8080、tune skip，Strata 自己写明等价于 `--model iq3_s --context 128k --vision cpu --tune skip --access local --port 8080`），只差前者多一行"未点名模型，按本机内存选了 IQ3_S"的提示。接入检查仍逐项核对 ADR-0017 的身份。
3. **只注入、不替换；建表必开。** 删除发布时专名替换（替换函数、`names-apply.json`、替换配方与 `names_apply` 身份键）与 `[names] enabled`。注入行按 Q1 规则取自该片 `name-table.json`：只取 `confidence: high` 的实体，每个 `forms[]` 一行 `{ja → zh}`，按 `ja` 去重，跳过空写法。注入行的 SHA256（`names_sha256`）进翻译身份与 run 目录键：**手改表（只要改到注入行）即另起 run、重译该片**；只改 medium／low 条目不触发重译。建表终态失败得到空表，翻译照常进行、不注入。
4. **失败路径。** 一个包两次尝试都失败（生成触顶、解析失败、HTTP 报超出 context）时按 10→5→1 拆批（前后两半、单条，邻文规则与原包相同），单条仍失败只保留日文并计入回退报告；这是研究侧 Q2"只空出该包"之外产品新增的唯一差别。传输中断、OOM、服务错误、服务起不来按基础设施失败处理：停掉 Strata、重新启动，最多重启 2 次；身份不符或已有别的 launch 在服务直接拒绝，本批其余需要模型的影片不再尝试。校验沿用产品原规则：在研究侧的 ID 集合、顺序、非空之外，另拒绝含空行的译文（按解析失败处理）。
5. **配方身份。** 产品配方 `q2-degrade-v1`（`kototoki/translate/recipes.py` 的 `RECIPE`），`RECIPE_HASH` = `332649cf98662e42cccc31485792104c3ce6303e6cd634ef42ef85839ee9310d`，由 `tests/core/test_translate_recipes.py` 钉住。翻译身份 = `{ja_srt_sha256, recipe_hash, seed, names_sha256}`；run 目录 `translate/srt-<sha12>/q2-degrade-v1__s<seed>__n<names_sha12>/`。旧 `dp10-cut-degrade-v1` 的 run 目录与 `names-apply.json` 原样留在工作目录、不再读取；已发布影片因 `sources` 不再匹配，下次整批运行重新翻译并发布。
6. **配置。** `[translate]` 只剩 `seed`（须为正整数，Strata 不接受 0）；`model`、`port` 删除（模型由 Strata 管理，端口固定 8080）。`[names] enabled` 删除。旧配置文件写了这些键会按"未知键"报错。

## 依据

- 用户决定（2026-11-08）：基线已是 Q2（ADR-0018），产品与基线不应再分叉；ADR-0017 列出的进产品前置项（外部服务后端、无 grammar 的失败路径、Q 链没有替换、两种服务不得同时驻留）由本决定逐项给出做法。
- 质量证据仍是 v12 F1（ADR-0017）：同一配方规则，F1 用 MTP 启动；1599 包交付失败 0。
- 专名表的用途从"发布时替换"改为"翻译时注入"，与 Q1／Q2 的研究设定一致（ADR-0017 的 Q1 规则：注入后再替换与只注入的输出逐字节相同，因而不留替换）。

## 约束与未关闭项

- **Q2 启动配置首用**（2026-11-08，细节见[翻译子系统模块页](../architecture/modules/translation-subsystem.md#代码与验证入口)）：smoke 与一部整片（HF-II）都通过，格式失败 0、交付失败 0、回退 0，显存峰值 16.1 GB、内存峰值 42.6–42.9 GiB；但每包约 16 s，约为 v12 F1（MTP、32k）的 6 倍，整片翻译 2498 s 对约 420 s。原因是启动时整机内存差 2.21 GiB 放不下 46.84 GiB 专家区，引擎退到 mmap 从 SSD 读专家；同一配置内存充足时调优实测 decode 106 tok/s。DFlash2 确在使用（接受率 88%）；前缀缓存不命中是 Strata 只复用对话续写的设计，v12 同样如此。
- 降级路径只经伪客户端离线验证；Strata 的请求不复现（同 seed 约半数 cue 不同，ADR-0017），重跑不保证同一译文。
- 产品进程被强杀时 Strata 可能留在后台：下次运行会因 `--status` 非空而拒绝，需手动 `strata launch --stop`。
- Strata 安装与模型下载在仓库外，由用户维护（[依赖布局](../development/dependencies.md)）；版本不是 0.2.12／build 0.1.58 时拒绝运行，升级等于换身份，须新决定。
- [ADR-0008](0008-no-multi-translation-selection.md) 继续适用：两次可靠性尝试与 10→5→1 降级不是"翻译多次再挑选"。
