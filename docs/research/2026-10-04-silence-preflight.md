# 数字静音预检

状态：探索性实测完成；单一合成输入，不是真实环境静音稳健性结论  
日期：2026-10-04  
范围：原生 Windows RTX 5080，已冻结版本的 W0、W1-native、Q0、Crisp。

输入由标准库生成：10 秒、16000 Hz、mono PCM16，160000 个全零样本。
WAV SHA256 `ee7bea4232762775f8fce9b3e27e4d3948c8ac6a45a87ca769f703d6eed0b448`。
资产、生成测试和来源见[语料冻结](../testing/2026-10-04-corpus-freeze.md)。
没有使用电影中的音乐片段代替数字静音，也没有加入参考文字提示。

| 配置及 run ID | 规范化插入字符 | 行为与限制 |
| --- | ---: | --- |
| W0 原生 `w0-silence-cuda-native-r1` | 14 | 无 VAD 的原生 CUDA ASR 返回文字；数字零输入证明这些字不是输入语音 |
| W1-native `w1native-silence-cuda-r1` | 0 | GPU Pyannote VAD 过滤后输出空；此例不能用于证明后续 ASR/FA 实际执行 |
| Q0 原生 `q0-silence-cuda-native-r1` | 2 | ASR 与 FA CUDA 路径完成，仍产生非标点文字 |
| Crisp 原生 VAD `q1-silence-vulkan-native-r1` | 0 | 正确报告无语音，但 CLI 不生成 JSON；适配器记录 `native_vad_no_speech_no_json`，不是 ASR 成功证据 |
| Crisp 无 VAD、ASR-only `q1-silence-vulkan-novad-asr-r1` | 2 | Vulkan ASR 返回文字；FA 未请求，不能当完整流水线预检 |

每行仅一次新进程推理，原始模型、参数、设备观察、时间和日志保存在 `.local/results/<run-id>/`。
统一评分为 `score-eval2.json`，参考 `.local/references/synthetic-silence-10s.json`。
空参考 N=0，CER、删除率、时间覆盖和成功率均未定义；只报告插入数，不制造 0% CER。
规范化移除标点，完整原生文字保留在私有结果中。这里没有估计每小时幻觉事件率。

这些结果要求后续实现明确处理全零/无语音输入和正常空结果，区分“无语音”与“推理异常/接口无文件”。
原生基线保持不变，没有事后加静音门槛使分数变好。全零检查不能替代真实背景音乐、噪声、弱语音
和 VAD 漏识别评估；已有原生 VAD 对开场弱语音的漏检仍须与静音收益一起报告。

版本和模型身份见 [Whisper](2026-10-04-whisper-execution.md)、
[Qwen](2026-10-04-qwen-execution.md)、[Crisp](2026-10-04-crisp-execution.md)。

## 最终配置的补充检查

整片和正式测速结束后，以同一全零输入、各一次新调用复核最终两套配置；没有加静音过滤器或改参数。

| 配置及 run ID | 规范化插入字符 | 结果 |
| --- | ---: | --- |
| W0 无前文 `s2-w0-silence-r1` | 14 | CUDA ASR 完成；关闭前文没有解决数字静音幻觉 |
| W1 归一化标准 CTC `s2-w1norm-silence-r1` | 0 | 原生 GPU VAD 后空结果；ASR/FA 无实际 forward，此例不证明这些阶段执行 |

两次均保持原始字幕 SHA，不计入正式三次重复测速或质量样本。分数为各运行目录的
`score-eval2.json`；N0、CER未定义。W1的通用“全部阶段实际执行”检查不会通过空输入路径，
这是预期不派发，不是CPU回退或本例对齐失败。后续产品须保留正常空结果的明确语义。
