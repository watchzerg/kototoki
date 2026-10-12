# Whisper and Qwen Backend Contracts

Status: exploratory; version-bound observations migrated from prior research
Last updated: 2026-10-03
Scope: inference, alignment, text units, and timing behavior relevant to future adapters.

## Evidence identity

Source: [upstream contract investigation](../../../subtitle-edit-fix/docs/research/2026-10-03-stt-engine-contracts.md), read on 2026-10-03. The original investigation accessed upstream sources on 2026-10-03 and retained a [source manifest](../../../subtitle-edit-fix/docs/artifacts/2026-10-03-stt-engine-contracts/manifest.json). This migration did not rerun inference or independently revalidate upstream code. The observations below apply to these fixed revisions, not arbitrary installed or future releases:

| Upstream | Investigated revision |
| --- | --- |
| OpenAI Whisper | `86098128c0b4f24f0e2aa2994de830614b474227` |
| faster-whisper | `7b99be5376b41cd481dfc52e8caa00a497c3294e` |
| WhisperX | `771b4a14a9486f8fd5aef18ef49e35d639523dd3` |
| Qwen3-ASR | `7c6daf77a2421100f5fb066495372c00129d39ff` |

These pins are evidence references, not Kototoki dependency selections.

## Timestamp sources

| Route | Observed mechanism | Adapter implication |
| --- | --- | --- |
| Whisper segments | Decoded timestamp tokens on an approximately 20 ms grid, plus window offsets | Segment boundaries are not guaranteed subtitle or acoustic boundaries. |
| Whisper native words | Cross-attention alignment, selected heads, filtering, DTW, and heuristic adjustments | Uses the same Whisper model; word probability is not calibrated boundary accuracy. |
| faster-whisper words | CTranslate2 `model.align`, followed by word construction and time adjustments | Not an independent CTC aligner. |
| WhisperX | Separate CTC emissions and trellis/backtracking within supplied ASR regions | Incorrect regions or text constrain what alignment can recover. |
| Qwen ForcedAligner | Timestamp-marker classification followed by `fix_timestamp` | Standard output already contains correction, not untouched argmax predictions. |

Primary references retained from the source: [Whisper timing](https://github.com/openai/whisper/blob/86098128c0b4f24f0e2aa2994de830614b474227/whisper/timing.py), [faster-whisper transcription](https://github.com/SYSTRAN/faster-whisper/blob/7b99be5376b41cd481dfc52e8caa00a497c3294e/faster_whisper/transcribe.py), [WhisperX alignment](https://github.com/m-bain/whisperX/blob/771b4a14a9486f8fd5aef18ef49e35d639523dd3/whisperx/alignment.py), and [Qwen alignment](https://github.com/QwenLM/Qwen3-ASR/blob/7c6daf77a2421100f5fb066495372c00129d39ff/qwen_asr/inference/qwen3_forced_aligner.py).

## faster-whisper: normal and batched calls differ

The fixed source records these differences:

| Setting | Ordinary `WhisperModel.transcribe` | `BatchedInferencePipeline.transcribe` |
| --- | --- | --- |
| Default VAD | Off | On |
| Default `without_timestamps` | False | True |
| Previous text conditioning | True by default | Constructed options set False |
| Temperature retries | May use a fallback sequence | Constructed options retain only the first temperature |
| Hallucination silence threshold | Can participate in decoding | Constructed options set None |
| VAD without explicit options | Ordinary `VadOptions` | Chunk-length speech limit and 160 ms minimum silence |

Long batched input with neither VAD nor explicit clips can fail instead of behaving like an ordinary call. Capture actual resolved options, including `TranscriptionInfo.transcription_options` when available. Matching model and beam size alone does not isolate batching as a performance-only variable.

The [VAD implementation](https://github.com/SYSTRAN/faster-whisper/blob/7b99be5376b41cd481dfc52e8caa00a497c3294e/faster_whisper/vad.py) concatenates selected regions and retains metadata to restore removed silence. In the studied transcription code, a word's midpoint selects a mapping region, and both endpoints use that region's offset. Segment-only mapping differs. The design inference is to flag suspicious words crossing concatenation seams rather than assume a single offset handles every case.

## WhisperX: failure is not always an exception

At the fixed revision, the default Japanese aligner is `jonatasgrosman/wav2vec2-large-xlsr-53-japanese`; Japanese word indexing is character-oriented. Unknown nonblank characters can use wildcard scores. No alignable characters, out-of-audio starts, or failed backtracking can retain original segment timing with empty words. Some missing times can be interpolated.

An adapter should preserve text-only segments in mixed results, identify fallback/interpolation when available, and avoid calling a wildcard placement verified pronunciation. Successful API return does not establish reliable timing for every unit. Exact behavior must be checked against the selected dependency version.

## Qwen: timestamp requests also affect recognition windows

The fixed [ASR wrapper](https://github.com/QwenLM/Qwen3-ASR/blob/7c6daf77a2421100f5fb066495372c00129d39ff/qwen_asr/inference/qwen3_asr.py) uses target chunk durations of 1200 seconds without timestamps and 180 seconds with timestamps. A timestamp request can therefore change ASR context before alignment begins. Missing aligner initialization raises an error for a timestamp request; empty recognition text skips alignment.

The fixed [input utilities](https://github.com/QwenLM/Qwen3-ASR/blob/7c6daf77a2421100f5fb066495372c00129d39ff/qwen_asr/inference/utils.py) normalize input to mono, 16 kHz, float32 and search low-energy cuts around the target boundary. This is not speech detection. Target duration is not a strict maximum. Splitting preserves continuous source regions, but a very short final chunk can be padded to 0.5 seconds.

For a controlled ASR-versus-ASR-plus-alignment experiment, freeze the actual audio windows rather than only toggle timestamp output. Track padding and window origins. The wrapper's concatenated text and alignment units do not constitute a subtitle formatter.

ASR and ForcedAligner initialization have separate device/dtype arguments. Top-level ASR kwargs do not automatically configure FA. A vLLM ASR route still uses a separate Transformers/PyTorch FA path in this wrapper. Record both stages' actual devices.

## Japanese text units and normalization

Whisper's [tokenizer](https://github.com/openai/whisper/blob/86098128c0b4f24f0e2aa2994de830614b474227/whisper/tokenizer.py) accumulates tokens into valid Unicode units for Japanese; these are not necessarily morphological words or single characters. WhisperX character units and Qwen's nagisa words cannot be compared by array index.

The studied Qwen FA uses `nagisa==0.2.11`, retains Unicode letter/number categories and ASCII apostrophes, and removes other characters/empty units. It inserts timestamp markers without adding ordinary spaces. The FA cleaner itself does not apply NFKC, but nagisa preprocessing does; preserve an explicit mapping to original text.

The investigated [FA configuration](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B/blob/c7cbfc2048c462b0d63a45797104fc9db3ad62b7/config.json) uses an 80 ms timestamp category unit. More output decimal places do not imply finer acoustic precision. Its correction selects a longest nondecreasing subsequence and fills anomalous positions from neighbors or interpolation. Monotonic output does not prove correct placement.

## Proposed adapter evidence

When relevant to the selected feature, retain audio sample span, text span, time basis, timing source, original backend response, exposed correction/fallback status, model identity, backend version, and resolved parameters. Preserve unavailable fields as unavailable rather than inventing precision.

Deployment compatibility, model licenses, resource budgets, and behavior on Kototoki inputs remain unverified. See [candidate selection](2026-10-03-model-backend-candidates.md), [time contracts](2026-10-03-stt-pipeline-design.md), and [evaluation](../testing/stt-evaluation.md).
