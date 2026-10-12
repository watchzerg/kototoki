# STT Pipeline Design Reference

Status: exploratory; migrated research, not an adopted architecture
Last updated: 2026-10-03
Scope: local audio transcription, with optional timestamp and future subtitle concerns.

## Provenance and reading order

Adapted from the sibling project's [pipeline survey](../../../subtitle-edit-fix/docs/research/2026-10-03-stt-pipeline-and-design.md), read on 2026-10-03. Its investigation focused on Japanese video subtitles. Kototoki currently requires local transcription; this migration does not establish Japanese-only support, subtitle export, translation, streaming, or a chosen backend.

This is a synthesis of existing research, not new source verification or inference. External source access dates and version claims belong to the original investigations. Detailed experiments and attachments remain in `subtitle-edit-fix`; sibling links require that checkout alongside Kototoki. The explanations here are readable without it, but independent reproduction requires the original evidence.

Read the [backend contracts](2026-10-03-stt-backend-contracts.md) before implementing an adapter, [failure cases](2026-10-03-timestamp-failure-cases.md) before adding time correction, and [evaluation protocol](../testing/stt-evaluation.md) before measuring quality. [Model candidates](2026-10-03-model-backend-candidates.md) and [application comparison](2026-10-03-stt-application-comparison.md) supply alternatives, not decisions.

## Separate responsibilities

| Responsibility | Inputs and outputs | Important distinction |
| --- | --- | --- |
| Audio loading | Selected input/stream to decoded samples and metadata | Actual decoder input matters more than an intermediate filename. Preserve source audio. |
| Preprocessing | Samples to backend-compatible rate, channels, and representation | Correct resampling differs from changing a sample-rate label. Enhancement is optional and can alter speech. |
| Window planning | Samples to identified input windows | VAD regions, model windows, and displayed subtitle cues are different units. Backends may also split internally. |
| Recognition | Audio window to original-language text and available native timing | Accurate text does not imply accurate time. |
| Optional forced alignment | Audio plus fixed text to estimated text boundaries | Alignment estimates placement; it does not verify the text or restore omitted speech. |
| Coordinate restoration | Local or compressed-audio timing to source timing | Continuous slices use offsets; silence-concatenated audio needs a piecewise map. |
| Output | Transcription results to the selected output format | Future subtitle grouping and reading-time adjustments should not overwrite recognition evidence. |

These are responsibilities, not a mandatory sequence of separately deployed components. Alignment can run per window or after text assembly. A plain-text milestone need not load an aligner or implement subtitle layout. Keep the first implementation small: audio input, one replaceable inference boundary, explicit results, and output handling, consistent with [AGENTS.md](../../AGENTS.md).

## Proposed time and text contracts

These proposals should be adopted in a spec or ADR only when the relevant behavior is introduced.

1. Describe continuous windows with integer sample intervals `[start_sample, end_sample)`. Convert to seconds at backend boundaries instead of accumulating rounded durations. Record sample rate and actual sample count.
2. Make the time origin explicit. If a slice starts at source second 100 and receives 0.4 seconds of leading padding, local second 1 maps to source second 100.6. Padded samples are not original audio.
3. For removed silence, retain a piecewise mapping. Concatenating source `[10,12)` and `[20,23)` into local `[0,5)` maps local 2.5 to source 20.5, not 12.5. Flag words crossing a concatenation boundary.
4. Preserve raw recognition text separately from aligner-normalized text and display text. Unicode normalization, punctuation removal, Japanese segmentation, and number formatting require explicit span mappings when timing is reused.
5. Distinguish native estimates, independent alignment, interpolation, coarse fallback, and display adjustment. If a backend does not expose raw predictions, mark them unavailable; do not label its already-corrected API response as raw model output.
6. Preserve recognized text when timing fails. A coarse segment interval can be a declared fallback; proportional allocation must not be presented as measured word timing.
7. If subtitle output is later added, keep cue membership by stable text-unit IDs and preserve acoustic versus display intervals. Apply pause and duration checks after every merge, including short-tail merges.

For media input, also retain selected stream identity and media/PCM origins. Video PTS, decoded sample time, slice-local time, and final display time are not automatically identical.

## Implementation implications

The historical findings favor keeping model-specific behavior behind a small adapter and retaining enough optional diagnostic output to locate the first failing stage. They do not justify building a general workflow engine before a working transcription path exists.

VAD filtering, shorter windows, quantization, batching, prompts, enhancement, and independent alignment each introduce separate quality tradeoffs. Evaluate one change at a time before combining them. Shorter windows can reduce context; VAD can remove weak speech; batching may change more than throughput.

If caching is introduced, identify audio, preprocessing, model revision, backend version, resolved parameters, language, and timing semantics. Record cache hits separately from inference runs. Existing output files alone are not proof that a requested configuration was executed.

Diagnostic recording must remain deliberate: keep private audio and complete transcripts outside Git and routine logs. Do not migrate the old project's recordings, experiment permissions, installation paths, or session tasks.

## Open decisions

- Required timestamp granularity and output formats.
- Product language coverage and evaluation coverage beyond the user-designated
  [FateStay default corpus](../testing/fatestay-reference.md). The initial local
  evaluation input and primary Japanese reference are now selected.
- Backend/model selection and verified native Windows GPU dependencies.
- Whether native timing warrants an additional alignment model.
- Windowing and failure behavior under real long-input conditions.

The [Windows constraints](../development/windows-nvidia.md) and [toolchain conventions](../development/toolchain.md) remain authoritative. No imported recommendation establishes a tested deployment or quality ranking.
