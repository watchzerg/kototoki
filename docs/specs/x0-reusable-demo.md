# X0 可复用 demo 契约

状态：demo 已实现；已采纳 newPyannote 基准线，代码默认参数迁移尚未实施  
最后更新：2026-10-05  
范围：原生 Windows、本地 Qwen-ASR＋MMS 日语 CTC，既有离线环境。

## 入口与采用范围

持续迭代入口为 `experiments/x0_demo/`，使用方式由其 [README](../../experiments/x0_demo/README.md) 维护。
历史 `qwen/`、`x0_flow/` 和 `japanese_ctc/` 保留为回归证据；未来 X0 改动归入本 demo。
当前采用依据与边界见[ADR-0003](../adr/0003-new-pyannote-baselines.md)；
fixed30／cut-merge 的早期流程依据保留于[ADR-0002](../adr/0002-x0-demo-flow.md)。
有限样本显著涨分不是建立 demo 或吸收流程设计的必要条件；正确性与无隐式数据损失必须验证。

当前 X0 基准线为 Qwen-ASR＋newPyannote＋MMS CTC，无降噪、无人声分离，保留日语原文。
只吸收适用于 Qwen 的 WhisperX 思路：检测后的源窗口切分合并、逐块独立纯文字识别后对齐和原生特征契约；
独立识别与原生特征已有等价行为，不复制 Whisper Mel、补零、特殊 token 或 CT2 参数。
当前使用显式 `--segmentation vad --vad-manifest PATH` 和 `x0-demo-vad-source-windows-v1`，
必须连同 `vad_id=pyannote-current`、外部 VAD recipe、模型及设备区分具体基线。
newPyannote 使用 segmentation-3.0 powerset 原生检测，onset／offset 0.5、min_duration_on／off 0；
源区间取整数样本并集，超长区间硬切，再按原跨度贪心合并到最多30秒，不照搬旧 PyanNet min-cut。
本次仅更新文档，代码无参数默认仍为无 VAD 的 `x0-demo-fixed30-v1`，作为历史／回归身份。
无 VAD 的低能量 `x0-demo-cut-merge-v1` 保留全部样本，是独立对照策略，不是 newPyannote 切分合并或直接 WhisperX 移植。

## 输入、分段与特征

- 输入为已准备的 mono／16kHz／PCM16 WAV 和非负、有限源偏移；保留源文件。
- 分段以整数 `start_sample/end_sample` 为权威；原有 fixed30／cut-merge 构成原音频完整连续分区，每个样本恰好使用一次，无删除、重叠或重排。每块最多480000样本，保留任意长度尾段。
- `fixed30` 每480000样本分块，最后一块保留实际长度。
- `cut-merge` 的候选切点来自每个非末尾5秒区域内的100ms低能量位置，并列取最后位置，最后不超过5秒的区域直接保留到末尾；切成连续原音频小段，再按原跨度贪心合并到最多30秒。没有静音阈值、语音分类或非语音删除；保存候选与合并成员，便于独立更换候选策略。
- Qwen 按块调用自己的 processor，固定日语、BF16、SDPA、batch1、greedy、max4096，各块独立，不传前文。
- 特征处理保留 Qwen 自身的有效长度、mask、补齐和音频 token 规则；不添加 Whisper 的30秒波形补齐、Mel资产、特殊token或CT2参数。
- ASR完整文字、原始token、实际PCM与输入／输出设备证据必须可追溯；生成触顶保留文字并明确标记，不算完整成功。

当前基线及其他独立 VAD 配方导入由外部流程产生的 `schema_version=1`、`status=ok` manifest；不在 X0 中加载 VAD。
完整基线运行须先新执行外部检测再执行 Qwen／MMS；复用已有 manifest 的运行必须标记为隔离回归。
必须核对 WAV 文件与 PCM SHA256、采样率、声道数、样本数、时长和源偏移；冻结原始字节与 hash，
每阶段重验。manifest 保存 `vad_id`、VAD recipe、参数／设备／资产 `metadata`、load／inference `stages`，
以及按 WAV 本地秒排序的源窗口和成员 `segments`。

窗口必须有序、互不重叠、范围有效且最多480000样本。成对显式整数边界直接用于裁剪，秒坐标须与其一致；
无整数时使用与 W0 相同的秒乘采样率向下取整。窗口内部间隔保留原波形；窗口外样本可丢弃，
显式保存 `retained_samples`／`removed_samples`。Qwen 与 MMS 使用同一整数裁剪；不拼接或重排波形。
空窗口表是合法的无语音结果：空文字、空 units、完整输入源范围，ASR／MMS 明确跳过模型加载。
VAD 配方不通过默认全样本守恒检查，改用有序不重叠的源样本检查；原有配方继续执行全样本守恒检查。

## MMS 和输出

复用 `experiments/w0_demo/alignment.py::MmsAligner`，不复制第二套 MMS。
模型、日语adapter／head校验、归一化、CUDA FP32、标准CTC及TF32作用域与W0共用。
X0 显式传同一整数样本窗和完整文字，MMS 不经浮点秒重新取整裁剪，避免任意尾段丢一个样本。
历史 PyanNet W0 不带整数字段时保持原秒坐标行为；当前两条 newPyannote 基线共用整数源窗口。

每个原字符恰好映射一次；OOV／对齐失败保留为 `text_only`，失败记录不能因完整结果写出而消失。
有效时间映射回输入源偏移。输出为完整JSON、原文、阶段记录及身份；字幕显示层复用既有writer，不复制WhisperX句切／插值。

## 运行与故障

单命令入口使用项目轻量Python环境，在固定Qwen与MMS环境中顺序启动子阶段。
环境差异显式记录，不安装、升级或下载；ASR／MMS只使用GPU，失败不转CPU。
全次运行持有共用GPU锁，模型跨阶段释放；子进程退出后才释放锁。
输入、模型与解释器可配置，unsupported配置给出明确错误；模块导入不加载模型。

每次使用 `.local/x0-demo/` 下新目录，拒绝覆盖。源码／输入／模型／环境、分段策略及阶段完整进程墙钟分别记录。
缓存、临时文件、日志、全文只写入私有工作区。失败保留已完成阶段及诊断，清理活跃进程和锁。
空文件或不支持格式明确拒绝；fixed30／cut-merge 静音音频按其无 VAD 历史契约处理，不能悄悄检测后删除。
当前 newPyannote 及其他显式 VAD 配方按外部检测窗口处理，包括空检测；窗口外样本删除须记账。
外部 VAD 耗时记录于 `vad_provenance.precomputed_stages`，执行身份为 `precomputed_external_manifest`，
不计入 X0 自身阶段或父入口墙钟。完整端到端成本由比较父流程累计外部 VAD 完整进程与 X0 墙钟；
不能把读取 manifest 当作新 VAD 推理或用 X0 自身耗时宣称整条路线提速。

## 验收

1. 离线验证任意尾样本、30秒上限、候选分段的真实合并、fixed30／cut-merge 的全部样本守恒、独立请求、全文／text_only、源偏移和异常清理；VAD 路径允许过滤窗口外音频，按第6项检查源窗口与删除样本记账。
2. 使用既有本机模型重新执行基准和cut-merge；核对实际GPU、Qwen特征输入、MMS同源样本和模型／源码身份。
3. 固定30秒与历史同窗结果比较完整文字、时间单元与token，确认复用边界未引入意外改变；新分段行为另记，允许有取舍，不以必须涨分作为通过条件。
4. 共享MMS新增整数接口的测试与W0旧接口回归通过；保留历史源码快照和结果。
5. 更新README、索引、架构、路由及验证记录；小样本运行不等于整片或正式产品后端验收。
6. VAD 扩展额外验证身份／offset 拒绝、排序／重叠／上限、显式整数样本精度、冻结证据、
   内部间隔保留及删除样本数、空检测不加载模型、外部与当前进程成本分离；真实 GPU 结果由独立比较记录维护。

第2、3项的早期验证针对 fixed30／cut-merge，不等于 newPyannote 已证明一般质量提升。
最新 newPyannote 两片整片证据见[整片报告](../research/2026-10-05-fullfilm-segmentation-comparison.md)，
其中 X0 采用依据是本轮稳定性与成本，配对剔除后未显示总体文字或时间优势，未对照整片 fixed30。
整片 worker 的逐段失败后继续只属于独立实验；canonical demo 生成触顶仍非零退出。
