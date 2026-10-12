# Hy-MT2 30B-A3B Q3／Q4 对照

> 2026-10-07 后续采纳：用户在后续四量化报告交付后明确采纳 APEX-I-Compact，当前决定见[ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md)，运行复用[当前 demo](../../experiments/translation_demo/README.md)。下文“保留 Q3 基线”描述本轮完成时的历史决定；Q3／Q4 的冻结输入、结果及统计对照保持原身份。

状态：已完成。日期：2026-10-06。

[结果报告](../research/2026-10-06-hy30-q3-q4-comparison-results.md)：两候选各 83/83 终分；Q4 三次生成中位耗时为 Q3 的 4.18 倍，剧集基本持平、电影样本均分较高但配对区间跨零。保留 Q3 基线。

用户要求沿用此前五候选的评估方式，比较已采纳社区 Q3_K_M 与新下载腾讯官方 Q4_K_M 的执行速度和翻译质量。基线身份见 [ADR-0004](../adr/0004-hy-mt2-translation-baseline.md)，资产见[模型指南](../guides/local-translation-model-assets.md)。两份文件发布者及量化制作过程不同，本实验比较具体资产，不能将全部差异归因于位宽。

## 冻结范围

- 使用相同 `V2-native-adapted` 输入、完整固定 test 83 窗口／414 个计分 IDs；smoke 15 窗口仅作开发检查，不计入质量总分。test 已在此前用于比较，本轮不是未使用过的测试集。
- 使用同一 llama.cpp b11429／CUDA 13.4 兼容引擎。Q3 与 Q4 的 GGUF 模板逐字相同；原生模板、GBNF、token IDs 传输及解码参数沿用基线，无参考、裁判反馈或跨窗记忆进入翻译器。
- Q3 请求 99 层，实际 49/49 GPU；Q4 显式 `--layers 38 --allow-cpu-offload`，实际 38/49 GPU。Q4 smoke 在 server ready 后的整卡采样峰值 15,550／16,303 MiB，据此保留约 750 MiB 余量，不声称此层数是最优速度配置。
- 温度 0、seed 20261006、输出上限 1024、context 4096、batch 256、ubatch 128、单槽、flash attention on、fit off、最多两次相同请求。

## 计时与评分

预先固定执行顺序：Q3、Q4、Q4、Q3、Q3、Q4，各跑三次完整 test；每次单独启动和结束服务器。每个候选第一次运行用于质量评估，不能从多次输出挑选优胜译文。重复只估计性能波动，不增加质量样本数。

追加 Q3 同样 38 层 GPU 的单次速度对照，帮助观察层级 offload 的影响，不作为第三个质量候选。加载、生成、窗口流水线耗时（含 tokenize／重试）、prompt／decode tokens、ready 后采样峰值显存及实际层数分开记录；进程启动后的加载时间不能等同于清空操作系统文件缓存后的冷盘加载。

质量沿用 [sol-high-auto-v1](../agents/subtitle-translation-evaluation.md)：全量机械检查、两候选共 166 次 fresh Sol/high 主评、固定抽样与风险窗口并集盲复评、一次有界争议裁决、确定性汇总。两候选均重新评分，不直接拼接旧 Q3 分数。按作品等权，剧集／电影分开，保留缺分上下界及完整失败分母。

之前已通过的同配置合成裁判探针及 dev 闭环作为已验证前置证据，离线检查本轮重跑。每项裁判有独立上下文、匿名候选、原始响应与 invocation 身份；同模型复评不代表独立模型家族验证或人工准确率。

## 产物与完成条件

独立目录：`.local/translation-evaluation/20261006-hy30-q3-q4/`。`freeze.json` 在 test 前记录权重、数据、源码和引擎哈希，`run_comparison.py` 保留运行顺序；原始语料保持只读，旧五候选结果保持原样。

全部生成运行、必需裁判与确定性汇总完成后发布中文结果，核对每个预期窗口和失败记录，并更新评估入口及受影响资产说明。是否更换 Q3 基线另由用户决定；本轮比较本身不改变已采纳基线。
