# 实测性能与资源汇总

当前W0／X0测试见[标准基线测试指南](../../docs/guides/baseline-testing.md)。本工具读取历史harness manifest；demo的result.json不是该manifest，不能直接作为此CLI输入。当前demo成本读取其实际阶段与进程记录。

这是只读、标准库入口。明确传入root GPU harness的manifest列表，生成新私有JSON；不扫描结果目录、不读参考字幕、不推理、不下载、不修改环境或建立质量排名。

```powershell
.venv/Scripts/python.exe -m experiments.performance `
  .local/results/<chapter07-repeat1>/manifest.json `
  .local/results/<chapter07-repeat2>/manifest.json `
  .local/results/<chapter07-repeat3>/manifest.json `
  --output .local/analysis/performance-dev/chapter07-three-fresh-r1.json
```

整片最多两次的实验由主agent另行排队；待每次harness完成后，将其manifest明确加入列表即可。不同音频、配置、model/source/runtime identity或实际GPU/driver会分组；三次重复不能证明总体延迟尾部。入口API为 `build_report(paths: list[Path]) -> dict`，命令行输出只含计数和私有报告路径。

报告保留每一个传入的成功、失败、运行中或缺失尝试。`actual_wall_seconds`来自实际harness；读取WAV帧数和采样率，并核对实际文件SHA256与harness，以绑定duration。`attempt_wall_per_input_duration`只表示本次已花费时间与输入时长的比，失败或replay不能作为完整处理速度。仅明确无推理复用、fresh subprocess、成功完成且音频身份匹配的完整路线进入 `fresh_complete_pipeline_rtf` 和重复组速度统计。重复传同一manifest保留记录，但不计为新的实际重复。

`cached_inference`、`cache_reused`及分stage复用标记均检查；Crisp已识别ASR+新FA replay、Qwen `config.asr_only=true`都属于component，完整流水线RTF为空。模型下载缓存不算推理复用。新进程也不证明OS文件缓存冷启动。stage计时字典原样记录，nested timer、已缓存ASR或加载时间不会被相加冒充一次新流水线耗时。当前入口适配root已有Whisper、Qwen与Crisp结果结构；未知缓存字段或未知输入格式会保留限制而不猜测。

X0跨家族fresh流程会核对 `pipeline.source_files` 的实际执行快照hash，并核对所有stage output实际SHA256、完成状态、同次ASR input身份及明确fresh标记；ASR artifact的model/config/environment/source identity进入整个重复组identity。只声明fresh而缺失这些绑定证据时，不进入完整fresh RTF。CTC复用**同次新识别**的ASR是该完整流程的一部分，不混同于历史缓存。完整stage命令、路径与output SHA保留在私有provenance，stage timer单独保存；仅核对过的每次运行中间文件路径会替换为稳定stage角色，以免不同输出目录拆散相同配置。ASR参数、模型、padding等改变仍会分组。原文与timed-units hash单独用于结果稳定性，不把有不同运行计时的完整stage artifact hash误当配置差异。

`gpu_sampling`处理root的6列nvidia-smi CSV（timestamp/name/driver/memory/utilization/power），逐device记录采样min/max、第一点proxy、采样间隔和查询失败。其memory MB沿用nvidia-smi原值；包含桌面和其他进程，首点或minimum都不是实际测得的空闲基线，不能解读成模型独占峰值。短峰可能漏采，不能由max减proxy推出精确模型显存。Torch分配器峰值若adapter提供，则留在stage字典，和whole-device采样不同口径。

`identity`保留audio/model/config/source/environment/runtime/platform/hardware实际记录，`identity_missing_fields`公开缺失；比较时不混入wall或瞬时利用率。Whisper的有效decoding/VAD参数保留，检测到的语言概率等输出值不当作配置。`output_stability`只输出原始完整text与完整timed-units的SHA256及计数，不输出转写。相同hash只证明这些重复的输出一致，不证明准确率。root捕获的源码范围不等于所有transitive依赖冻结，报告明确保留这项边界。

验证：`.venv/Scripts/python.exe -m unittest discover -s experiments/performance -p test_*.py`。14项离线测试覆盖真实6列CSV、缺失/N/A样本、失败记账、fresh/cached/staged区分、音频身份变更、配置/源码变更、精确输出稳定性、重复清单去重、Qwen ASR-only以及X0中间路径规范化和ASR artifact/model/config绑定。小型合成测试文件仅临时放在 `.local/analysis/performance-dev/`；无GPU或依赖安装。实际CPU-only核查已通过4个明确开发manifest及 `x0-fresh-ch07-r1`，没有扫描或读取保留集。
