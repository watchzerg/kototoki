# 01 离线实现：v11 根目录、asr10 参数化、跨段截断选项、diff 工具、测试

Status: resolved
Type: 离线
Stage: A
Blocked by: —

范围、终点与门见研究文档 §4／§5（docs/research/2026-10-22-q0-product-route-v11.md）。

## 执行记录

- 2026-10-23 开工前核对：GPU 空闲（nvidia-smi 859 MiB 已用、0%），无 llama／python 进程，无 `.local/gpu.lock`。基线测试 47 项通过（test_v10、test_qwen、test_recipes）。
- 设计取舍（执行者补的实现细节）：
  - **跨段截断**放在 `wide_context` 里而不是 `qwen_options`：它是邻文规则（`batching._neighbours`），与提示无关。新键 `silence_gap`（秒）可选；带键时版本 `wide-context-v2`，不带时 v1 且 hash 不变（`qwen-wide` 仍 `719237b9…`、`dp10-cut` 仍 `ee72ce66…`）。规则：从包首尾向外取邻文，遇 ≥G 静默即停；包内静默不影响；再按条数与 `max_visible` 截（后侧先去）。
  - **N\* 可能的修订（§4.1 规则 c）**提前做成开关：`qwen_options.names.filter: "targets"`（只看待译 cue 的文本命中）自动改用 `qwen-name-table-v2` 表头（多一句"只在原文出现该写法的位置使用，不要把代词、称呼或省略的主语改成名字"）；`window`／`all` 行为与 v1 逐字相同。规则 (a) 只需在建注入表时过滤 `confidence: high`，不改 qwen.py。
  - **产品侧 diff**：`asr10.plan(skip_identical=True)` 把两臂文本逐字相同的单元移出计划、写进 `plan.json.identical`；A／B 侧抽签对每个单元都抽（与不跳过时同一抽签）。`asr10.estimate` → `summarize`：相同单元按 Δ＝0 计入 `n`、`delta`、CI90 与 `tie`，`mean_px/py`、偏好、critical／addition／人名计数只算已判单元（相同单元的惩罚未知，不填 0），并报 `n_judged`／`n_identical`／`identical_delta_zero`。
  - **dev 侧 diff**：mqm 裁判按固定的 4 窗包判、各 run 共用包组成，为保"同包"不拆包：`copy_identical_packets` 把对照已判且 20 条 cue 全部相同的包的判分复制到候选的裁判目录（候选包 id 按 `judge.plan_packets` 同一公式算，`surface: copied-identical`，meta 成本 0），其余包照常 `judge-run`（已有结果文件的包会被跳过）；`compare11` 在配对统计前把相同 cue 的候选行换成对照行（Δ＝0），人名相关错误计数同口径，并附两臂 dev 不一致率（`v9.name_errors`）。`v9.compare` 的后半段抽成 `report_from_rows` 供复用，行为不变。
  - `asr10` 各函数本已可传 `root`／`seeds`，只有 `delivery_failures` 缺 `seeds`，补上；v10 默认不变。
- 代码：`experiments/translation_v3/{batching,recipes,qwen}.py`，`experiments/scene_batching_v6/{v11,asr10,v9,__main__}.py`，测试 `test_v11.py`（9 项）。CLI：`--round v11` 跑 v9／v10 命令；新命令 `copy-run`、`copy-identical`、`compare11`、`product <plan|judge|estimate|inconsistency|replace|failures>`。
- 产物根目录 `.local/q0-product-route-v11/` 已建（`recipes/ runs/ checks/ summaries/ logs/ smoke/ A/ C/{root,zh,judge,logs}`）。配方已写：`C/root/recipes/seg10.json` 与 `recipes/seg10.json`（hash `14fef2f7…`）、`C/root/recipes/q0-names.json`（产品表，hash `18fcac59…`，与 v10 D 相同）。脚本模板 `logs/{gen-queue,judge-queue,c-translate}.sh`（judge-queue 支持 `recipe:seed:against` 先 copy-identical）。
- 自动检查：`test_v11` 9 项＋`test_v10`／`test_v9`／`test_qwen`／`test_recipes` 共 64 项通过；`translation_v3` 全套 78 项通过；`test_v6`／`test_v7` 31 项通过；`--round v11 status` 可用。待填标记仅剩 `workflow.md` 的"按需"项，时机未到。
- 未验证：真实 server 上 `targets` 过滤与 `seg10` 邻文的端到端（04／08 的 smoke 覆盖）；`copy_identical_packets` 在真实裁判目录上的行为（04 首次使用时核对包数）。

## Answer

完成。跨段截断＝`wide_context.silence_gap`（`wide-context-v2`，旧 hash 不变）；N\* 修订开关＝`names.filter: "targets"`＋`qwen-name-table-v2` 表头；产品 diff＝`plan(skip_identical)`＋`summarize` 的 Δ＝0 计入；dev diff＝复制全同包的判分＋`compare11` 相同 cue Δ＝0；`asr10` 根目录与 seed 可传参；`--round v11` CLI；离线测试 9 项新增、相关 173 项通过。文档：两份 README 已更新。
