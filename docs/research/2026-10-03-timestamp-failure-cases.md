# Timestamp Failure Cases and Engineering Lessons

Status: concluded historical synthesis; remedies remain unvalidated for Kototoki
Last updated: 2026-10-03
Scope: mechanisms observed in the sibling project's bounded timing investigation.

## Evidence and limits

Adapted from [causal diagnosis](../../../subtitle-edit-fix/docs/research/2026-10-03-subtitle-timing-causal-diagnosis.md), read on 2026-10-03. That report links original outputs, instrumentation, controlled replays, and independent audits. This migration did not reproduce those experiments.

Historical runtime evidence concerns Subtitle Edit 5.2.0, Crisp 0.8.32 (fixed source `e2a356146e36bc1cc0410edefb01990448766979`), and the recorded Purfview r245.4 workflow. Later application snapshots have different identities; see [application comparison](2026-10-03-stt-application-comparison.md). No claim here establishes the same behavior in newer releases or in Kototoki.

The source used fixed Japanese media and edited Chinese ASS references. These references support display-time comparisons, not Japanese text ground truth or precise acoustic boundaries. Numerical examples below illustrate bounded mechanisms, not overall model rankings. Original media and complete transcripts were not copied.

Those are historical evidence limits. New Kototoki evaluation instead defaults to
the [FateStay video and original Japanese text SRT](../testing/fatestay-reference.md)
designated by the user; the older two-film corpus is not a routine requirement.

## Cases worth carrying forward

| Case | Historical observation | Supported lesson and limit |
| --- | --- | --- |
| Long cue shortened from its end | SE Adjust timings changed a 35.740 s interval from 1353.760–1389.500 to 1381.500–1389.500, retaining the final 8 s | A display policy can move start by 27.740 s. Disabling that branch avoids this rewrite, not upstream timing failures. |
| Raw alignment already abnormal | In one fixed-audio/text comparison, Crisp f16 and an official CPU F32 reference using the same numerical GGUF weights agreed at 17 of 18 raw positions; the first unit remained unreliable | Errors can precede application import and correction. This did not establish equivalence to the original HF checkpoint or prove the hypothesized transcript was entirely correct. |
| Correction changes appearance, not acoustic evidence | A 2×2 replay of fixed raw predictions and two postprocessors isolated leading-fill differences; a changed raw category could also alter the selected nondecreasing chain | Preserve raw versus corrected results where exposed. No negative durations is insufficient proof of synchronization. |
| Full workflow hides bad alignment with fallback | The studied Crisp full-ASR path accepted words only when the last end exceeded the first start; otherwise it retained the slice seed and writer-based proportional timing | Whole-span validity does not guarantee internal word validity. Align-only and full recognition have different failure behavior. |
| Remote input changes early recognition | Identical prefix PCM produced different early results in longer/different full inputs; a fixed upstream global log-Mel floor mechanism was numerically reproduced | Matching a local audio prefix does not prove identical model input conditions. Upstream feature reproduction was not a byte-level proof of the installed wrapper's internal features. |
| Writer broadens display intervals | Fixed words packaged differently changed cue envelopes; original CLI SRT already contained packaging effects before SE import | Save native words separately from formatted output. Do not attribute every final SRT error to the UI or ASR. |
| Import modifies overlapping cues | Three measured SE STT-import end trims were 40, 80, and 20 ms | Import is a processing stage. These changes were not proved acoustically worse and cannot explain all multi-second errors. |

Detailed evidence entry points: [official-reference and postprocessor replay](../../../subtitle-edit-fix/docs/artifacts/2026-10-02-timing-crosscheck/instrumented-cpu/official-reference/stageI-report.md), [full ASR versus align-only path](../../../subtitle-edit-fix/docs/artifacts/2026-10-02-timing-crosscheck/source/full-vs-align-only-path-audit.md), and [responsibility audit](../../../subtitle-edit-fix/docs/artifacts/2026-10-02-timing-crosscheck/instrumented-cpu/diagnostic-responsibility-audit/report.md).

## Failed improvements are reusable evidence

The source did not find one general configuration fix. Smaller chunks, VAD changes, revised formatting, alternative alignment, and text preprocessing produced local gains and new regressions. Preserve these boundaries instead of inheriting a recommended magic parameter:

- Removing extra spaces from Japanese FA input improved a controlled short case, but subsequent long-input validation did not establish a general repair. Removing punctuation or changing segmentation also had mixed effects.
- The [CTC full-input evaluation](../../../subtitle-edit-fix/docs/experiments/2026-10-02-ctc-full-validation.md) improved some examples while losing output containing out-of-vocabulary text and introducing other multi-second errors. Elimination of zero/negative durations did not establish success.
- Disabling external VAD did not disable Whisper decoder no-speech decisions. Some recovered speech and remaining omissions coexisted; per-omission causality was not fully established.
- High recognition scores did not guarantee accurate word boundaries. Confidence, retry temperature, and zero-duration counts were insufficient as standalone timing-quality indicators.

## Diagnostic routing for future work

| Symptom | First boundaries to inspect |
| --- | --- |
| Nearly constant shift | Source/stream origin, crop offset, padding and enhancement latency |
| Increasing drift | Sample-rate/time-base interpretation, accumulated rounding, duration arithmetic |
| Sudden shift after a window | Missing/double offset, silence map, skipped window, overlap reconciliation |
| Local bad words | Recognition timing, alignment text/window, raw prediction and correction |
| Very long displayed cue | Original word envelope, internal silence, short-tail merging and display policy |
| Missing speech | Audio selection, VAD, decoder skips, ASR omission, downstream text deletion |

This table is a proposed investigation order, not a diagnosis of an unobserved failure. Capture the earliest available intermediate result and locate the first change. Avoid rerunning expensive inference when a fixed-result formatter replay can isolate the question.

## Implications for tests and interfaces

When the relevant feature is implemented, small synthetic cases can cover piecewise time mapping, leading padding, a short tail after long silence, mixed text-only/word-bearing segments, out-of-order times, Unicode normalization, and failure fallback. These test structural contracts, not acoustic accuracy.

Keep timing provenance and original text, expose uncertainty, and separate acoustic intervals from display policy. Do not delete failed units to improve quality statistics. See [pipeline proposals](2026-10-03-stt-pipeline-design.md) and [evaluation methodology](../testing/stt-evaluation.md).
