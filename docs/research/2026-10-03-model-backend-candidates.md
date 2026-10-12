# Model and Backend Candidates

Status: exploratory; inherited shortlist, no backend or model adopted
Last updated: 2026-10-03
Scope: local STT selection, informed by prior Japanese/NVIDIA research.

## Provenance

Adapted from the following sibling investigations, read on 2026-10-03. Their external research date is 2026-10-03; this migration preserves historical findings rather than asserting current release status or newly verified compatibility:

- [Whisper and Qwen model selection](../../../subtitle-edit-fix/docs/research/2026-10-03-whisper-qwen-model-selection.md).
- [GPU engine selection](../../../subtitle-edit-fix/docs/research/2026-10-03-gpu-asr-engine-selection.md).
- [Crisp backend and checkpoint survey](../../../subtitle-edit-fix/docs/research/2026-10-03-crisp-backend-selection.md).
- [SE WhisperX packaging correction](../../../subtitle-edit-fix/docs/research/2026-10-03-se-whisperx-packaging.md).

Original release metadata, model cards, and benchmark references remain linked from those reports. This document omits transient latest-release tables. Consult [backend contracts](2026-10-03-stt-backend-contracts.md) for fixed source revisions.

## Separate selection dimensions

Current investigation priorities are defined by the user's
[inference selection principles](../development/inference-selection.md), including
GPU-only execution on the user's RTX 5080 and the preferred Whisper/Qwen variants.
The inherited table below preserves research context; it does not replace those
priorities or establish a final selection.

A model checkpoint, runtime, conversion/quantization, aligner, and application writer are separate choices. An updated package or converted file is not necessarily a newly trained model. Same model names do not prove identical weights, preprocessing, decoding, or output timing.

| Inherited candidate | Why the earlier research retained it | Remaining checks before adoption |
| --- | --- | --- |
| Whisper large-v3 + ordinary faster-whisper | Accessible Python boundary and native segment/word outputs; proposed engineering baseline | Native Windows GPU execution, selected CTranslate2 dependencies, target-language accuracy, timing and memory |
| Whisper large-v3-turbo + faster-whisper | Speed-oriented comparison to full large-v3 | Quality/omissions on identical inputs; no assumption of equal quality because it is newer |
| Qwen3-ASR-1.7B + official Transformers wrapper | A reference route with fewer third-party conversion variables | Complete Windows dependency installation, actual device/dtype, text quality, long-input behavior |
| Qwen3-ForcedAligner-0.6B | Independent optional timing stage for fixed text | Language/tokenization contract, failure rate, timing tails, separate device and model residency |
| WhisperX + Japanese CTC aligner | Comparison for independent alignment | ASR/CTC dependencies and devices, exact language model, fallback semantics |
| whisper.cpp | Alternative when native distribution becomes a priority | Conversion identity, API integration, timing method and measured deployment benefit |
| CrispASR / Qwen C++ ports | Existing native distribution and end-to-end comparison routes | Per-backend conversion, VAD, alignment, writer, actual devices, and access to diagnostic outputs |

The earlier proposal to start with full large-v3 and compare Qwen1.7B was an engineering judgment, not evidence of a universal Japanese winner. Kototoki has not selected either. A text-only milestone need not add FA merely because a candidate supports it.

## Broader Japanese candidates

The historical Crisp survey identified Cohere's base `cohere-transcribe-03-2026` and NVIDIA's specifically Japanese `parakeet-tdt_ctc-0.6b-ja` as additional leads. Fun-ASR Nano, SenseVoiceSmall, and Granite base were supplementary leads; MOSS's joint transcription/timing/speaker approach was a research topic. These names do not establish native Python/Windows integration or target-workload quality.

Preserve checkpoint-level distinctions from the source: Parakeet's multilingual v3 was not the Japanese checkpoint; Granite PLUS did not inherit the base model's Japanese coverage. UI language dropdowns were not sufficient evidence of model capability. ASR and aligner language support must both be checked; the source found a possible non-Japanese default aligner for Cohere in SE.

External small-sample Japanese studies favored different models on different datasets. Some compared turbo but omitted full large-v3, used sentence-macro CER, lacked pinned weights, or used a different runtime/hardware. Their figures should not be merged into a leaderboard or transferred to anime, converted GGUF models, or this machine. The original reports retain the exact sources and limitations.

## Deployment lessons to preserve

- Upstream CUDA support does not prove that a packaged application contains GPU-enabled dependencies. The SE packaging investigation found CPU PyTorch in the studied standalone WhisperX distribution; that is a package-specific observation, not a claim that upstream WhisperX cannot use CUDA.
- The earlier research found differing CUDA/cuDNN guidance between faster-whisper and CTranslate2 documentation. Choose and verify one concrete release combination; do not copy a mixture of installation snippets.
- The studied vLLM deployment guidance required Linux/WSL rather than native Windows. Recheck that guidance if considering it; WSL is not an implicit Kototoki prerequisite.
- A successful ASR GPU stage says nothing by itself about the aligner's device. Record both, including any fallback.
- The source project's approximately 16 GiB RTX 5080 context is historical, not a minimum requirement or a measured memory budget for Kototoki.

## Adoption checklist

Before implementing a selected candidate, verify its current primary documentation, exact Python/runtime compatibility, model license and redistribution terms, checkpoint revision, conversion provenance, and offline acquisition procedure. Then validate on native Windows with a permitted sample and actual requested device. Keep asset acquisition separate from normal inference.

Compare original-language text, missing/hallucinated speech, required timing, and performance using the [evaluation protocol](../testing/stt-evaluation.md). Fix input windows and postprocessing when isolating a model change. Capture real resolved parameters rather than UI labels.

For new Kototoki comparisons, use the user-designated [FateStay primary reference](../testing/fatestay-reference.md) by default. Its video remains in `D:/movie/`; the original Japanese text SRT is the scoring reference, with SHA256 checks before and after use. Historical two-film experiments do not require routinely evaluating both older movies.

Record an adopted choice and rationale in an ADR only after a decision is made. Existing [platform](../development/windows-nvidia.md) and [toolchain](../development/toolchain.md) documents remain authoritative; this shortlist supplies no install commands, dependency pins, universal quality ranking, or verified configuration.
