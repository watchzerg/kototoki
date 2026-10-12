# Validation Boundaries

Status: accepted conventions; offline demo checks implemented, real-run scope tracked separately
Last updated: 2026-10-05
Scope: evidence required for Python code and local inference changes.

修改或测试当前W0／X0时，先读[标准基线测试指南](../guides/baseline-testing.md)，复用对应demo，
按各自契约检验源坐标和完整文字，以各自验证记录为已测起点；共享MMS变更同时验证两条调用路径。
行为改变须另建 recipe／运行身份并记录验证；两窗通过不等于十二窗、整片或新 VAD 已验收。

| Boundary | What to verify | What passing does not prove |
| --- | --- | --- |
| Fast offline checks | Pure transformations, input validation, output contracts, and error handling with fixtures or a fake inference boundary. | Real model compatibility or GPU execution. |
| Local integration | Actual changed boundaries such as audio decoding, files, configuration, subprocesses, and cleanup in isolated temporary locations. | Transcription accuracy or performance on user recordings. |
| Real model smoke test | Load provisioned assets and transcribe a small permitted sample using the selected backend and actual device. | Accuracy across languages, workloads, or hardware. |
| Quality/performance evaluation | A defined sample set, reference text when scoring accuracy, model/settings, hardware, latency, and memory measurements. | Performance or quality outside the evaluated conditions. |

Select checks based on changed behavior; documentation-only edits need link and
consistency checks, not a model run. Test public observable contracts instead of
mirroring implementation details.

Keep routine verification offline and independent of large assets. Make checks
requiring model assets or GPU resources explicit and separate. Missing prerequisites,
skipped checks, zero selected tests, and mocked inference are not passing evidence
for real inference. When a required check cannot run, report the unverified scope.

For GPU evidence, record Windows version, GPU and driver, Python/backend versions,
model identifier or local artifact revision, relevant runtime libraries, actual
device, precision, sample characteristics, and outcome. Distinguish model load
time from transcription time when reporting latency.

Use small synthetic or redistributable samples and preserve provenance. Keep user
audio and full transcripts out of routine logs and committed test reports.

For recognition accuracy, timing, coverage, and performance comparisons, consult
the proposed [STT evaluation protocol](stt-evaluation.md). It adapts historical
research methodology; its examples do not establish accepted product thresholds
or evidence that Kototoki inference has been tested. For real-model quality
evaluation, follow the accepted [reference policy](fatestay-reference.md).

当前主参考为 Heaven’s Feel II、III 的原版内嵌日文 SRT；I 的双语提取字幕可信度较低，
Black Panther 的日语配音/字幕可信度最低，两者只作补充，不能混入主参考排名。
直接识别影片目录已有的日语音频，不重复提取视频音轨；按后端需要生成派生 PCM，
保留输入身份和时间映射。遵守素材只读保护及评估前后字幕哈希检查。
字幕来源可信不代表已完成人工声学边界验证，旧单片结果也不代表两片主参考已验证。
