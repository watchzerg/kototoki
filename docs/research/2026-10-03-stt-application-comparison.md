# STT Application Comparison

Status: concluded historical comparison; implementation suggestions are exploratory
Last updated: 2026-10-03
Scope: selected local STT and timing paths in three investigated application snapshots.

## Sources and identity

Adapted from the [Subtitle Edit report](../../../subtitle-edit-fix/docs/research/2026-10-03-stt-subtitleedit.md), [VideoLingo report](../../../subtitle-edit-fix/docs/research/2026-10-03-stt-videolingo.md), [pyvideotrans report](../../../subtitle-edit-fix/docs/research/2026-10-03-stt-pyvideotrans.md), and [bounded evidence audit](../../../subtitle-edit-fix/docs/research/2026-10-03-stt-evidence-audit.md), read on 2026-10-03. The original survey date was 2026-10-03. This migration did not rerun applications or repeat the source audit.

The three studied local source directories lacked Git metadata. Version declarations were not verified release identities or clean-checkout evidence. The [70-file source manifest](../../../subtitle-edit-fix/docs/artifacts/2026-10-03-stt-survey/source-manifest.json) retains file hashes; detailed reports retain code locations. Current files at those paths may change.

In particular, the SE snapshot declared application v5.3.0-beta20, while its library project declared 5.2.0. Download code referred to Crisp 0.8.41 and WhisperX standalone103. Historical runtime measurements used SE 5.2.0/Crisp 0.8.32 and must remain separate. Current pyvideotrans `_stt_utils.py` had an added empty-list guard relative to the older fixed v4.14 attachment; the older crash condition cannot be carried forward unchanged.

## Compared responsibilities

| Dimension | Subtitle Edit | VideoLingo | pyvideotrans |
| --- | --- | --- | --- |
| Organization | Multiple engine adapters, often external executables, then editor import | Recognition/alignment followed by text segmentation and subtitle generation | Multiple recognition backends sharing segmentation/cleanup |
| Whisper route studied | Several executables with different formats and timing mechanisms | Local WhisperX recognition and independent alignment | Built-in faster-whisper/OpenAI Whisper native words, then common resegmentation |
| Qwen route studied | Crisp full workflow and Qwen CPP JSON take different paths | ASR and FA run in separate phases/windows | Explicit Japanese enables FA; auto/unspecified language can use a different path |
| Windowing | Much is delegated to the selected engine | Coarse media chunks and inner model windows are distinct; Qwen VAD trims edges | Qwen alignment and non-alignment branches have different window planning |
| Time after inference | Engine writer plus import/postprocessing/display rules | Flattened words mapped back from text segmentation | Word grouping followed by common overlap/invalid-cue cleanup |

These are selected snapshot paths, not complete feature inventories or proof of what any previous user task executed.

## Subtitle Edit: adapters do not share one timing policy

The historical Crisp path included slicing, recognition, FA, an acceptance gate, fallback, and a writer before SE import. Current SE's generic SRT import and Qwen CPP JSON path did not use exactly the same overlap handling. Post processing and Adjust timings were separate controls; switching one off did not imply preservation of all engine times.

Transferable lesson: preserve the backend response before import and track every subsequent rewrite. Model, executable, writer, import, and display policy need separate identities. The [packaging correction](../../../subtitle-edit-fix/docs/research/2026-10-03-se-whisperx-packaging.md) also shows why an upstream library's GPU capability cannot stand in for verification of a distributed application's package.

## VideoLingo: text matching is not acoustic alignment

The studied pipeline could recognize raw audio while aligning separated vocals, so enhancement was not one common upstream transform. It flattened word results before later text segmentation, losing window provenance. Its later `align_timestamp` step matched text to existing word indices; it did not read audio or perform a second forced alignment.

Taking the first and last word of a textual sentence can enclose a long silence. The studied code also extended a cue to the next start for gaps below one second, including source-only output. That small-gap policy alone could not explain a previously observed approximately 108-second cue; the original run lacked complete word-level/version binding.

The cache included several input/settings identities but not every model revision and preprocessing/windowing parameter. File-existence shortcuts could also skip work. Transferable lessons: retain window/unit provenance, test cache invalidation explicitly, record actual cache use, and apply temporal constraints as well as textual sentence rules.

## pyvideotrans: shared formatting can affect multiple backends

The ordinary `_resegment` could merge a short tail into a previous cue without checking the gap or total duration. Some punctuation paths bypassed nominal duration limits. Historical synthetic replays produced 61/61.5-second display cues. This proves a mechanism, not the origin of a particular user's misplaced word.

Only the all-words-empty case received a full segment-level fallback. In mixed results, text-bearing segments without words could disappear when flattening the remaining words. Later `_post_fix` could truncate overlaps and delete nonpositive intervals, removing text while making the remaining geometry appear legal.

Transferable lessons: preserve text-only segments, validate constraints after every merge, save original results before mutable formatting, and record deletion/correction events. Explicit language settings can change processing paths, so resolved backend options matter more than UI labels.

The source project's user-output attribution had a screenshot/log conflict between Qwen and faster-whisper. Retain that uncertainty; those output comparisons do not establish a verified Qwen-versus-Qwen experiment.

## What to reuse in Kototoki

Use small model adapters, explicit audio/time coordinates, optional independent alignment, and separate output formatting. Borrow failure cases as test ideas and observed boundaries as design questions. Do not copy each application's full workflow, numerical defaults, cloud stages, translation, dubbing, or LLM dependencies into a local transcription milestone.

The [pipeline reference](2026-10-03-stt-pipeline-design.md) owns proposed common contracts; [failure cases](2026-10-03-timestamp-failure-cases.md) own the historical diagnostic lessons. None of these studies measured a new Kototoki quality or performance result.
