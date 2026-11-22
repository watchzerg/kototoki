# 2026-10-20 专名一致性产品路径验收

## 时间
2026-10-20（本地 00:28–00:30 运行）。产品 `kototoki/names/`、`kototoki/llama_server.py` 与编排接入在工作树中，验收本身未改代码、参数、提示或配方。

## 对象
原 ADR-0014（现并入 [ADR-0028](../../adr/0028-names-accept-empty-table.md)）把专名一致性（建表加发布时程序替换）移植进产品 `names` 阶段后的整片行为，对照研究期冻结配置（[专名一致性研究](../2026-10-name-consistency.md)）。后来该替换从产品中撤掉，表改为只经翻译注入（[ADR-0029](../../adr/0029-translate-per-cue-resolution.md)，原 ADR-0019），此记录保留为移植时点的验收。

## 环境与版本
建表模型 `unsloth/Qwen3.8-27B-GGUF` 的 `UD-IQ3_S`（revision `4ca72078`），llama.cpp b11669（CUDA 13.4）llama-server，`-c 20480`、`--reasoning off`，66／66 层驻留 GPU；提示 `build-table-prompt-v5`。RTX 5080；运行前无 GPU 进程与锁，空闲显存约 15 GB。

## 测试
- 素材：2 部日语电影（HF II／III）的 w0 整片输出（1099／1219 条 cue），`[names]` 取默认（启用）；翻译 run 为已有的 H0 产物。
- 入口：整批 `python -m kototoki`；STT 与翻译按身份跳过，names 建表后重新发布。运行前备份两部最终 `zh.srt`、`ja.srt` 与 `published.json` 作"替换前"基线。
- 判据（原 ADR-0014 四条）：① 退出码 0、两表 `build.status` 为 ok、替换 cue 数 > 0；② 研究脚本 `apply_table measure` 的不一致率两部都下降；③ 研究脚本 `apply_table` 默认参数在产品表上的输出与发布 `zh.srt` 逐字节相同；④ 列出改动最密的 5 分钟片段供用户抽看。

## 结果
- ① 满足：退出码 0，两表都第一次尝试成功；替换 cue 数 HF II 55、HF III 32；无 WARNING、无重试、无 server 重启。整次运行 117 s（names 阶段约 106 s，翻译读回 0.1 s 未起 Hy-MT2）；整机显存峰值 13445 MiB（含约 0.95 GiB 桌面），整片提示 13–15K tokens 下峰值不升。
- 建表：HF II 提示 13.2K／生成 2.4K tokens，49.5 s，条目 20 个；HF III 14.6K／1.8K，40.5 s，条目 15 个。程序兜底删去的是罗马字 `zh_variants`、称呼词（如"父さん"）与日文写法形状不合格项。
- ② 满足：不一致率 HF II 0.151 → 0.135，HF III 0.121 → 0.094。限制：`measure` 的 term 集合替换后缩小（14 → 11、12 → 11），不是同一组 term 上的严格前后对比；マスター、シンジ、トウサカ等异写替换前后不变。
- ③ 满足：产品发布的 `zh.srt` 与研究脚本默认参数的输出逐字节相同，审计汇总与逐实体统计也相同。
- 全部替换来自统计层（变体层 0）；`published.json.sources` 新增 `names`、`names_apply` 两键，`translate` 身份不变。
- ④ 改动最密的 5 分钟片段清单已列出，待用户抽看。

## 结论
原 ADR-0014 的判据 ①②③ 全部满足，产品实现与研究冻结配置一致。未覆盖：改动逐行评审、表条目人工核对、x0 与其他作品、失败路径的真实运行、建表可重复性。
