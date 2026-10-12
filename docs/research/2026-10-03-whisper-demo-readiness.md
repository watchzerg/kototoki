# Whisper Demo Readiness for Timing-First Evaluation

Status: exploratory; source inspection complete, native GPU execution unverified
Last updated: 2026-10-03
Scope: faster-whisper large-v3 and WhisperX Japanese alignment for a native Windows RTX 5080 demo. No dependencies, models, or inference were installed or run.

## Recommendation

Planning update: the [integrated plan](../plans/local-stt-demo-selection.md) follows
the user's latest-documentation requirement. Refresh official docs and model cards
at setup, evaluate native/recommended pipelines first, then controlled components.
The version snapshots and suggested order below are research evidence, not a
requirement to use older interfaces or exclude built-in/justified preprocessing.

Retain large-v3 as the first Whisper checkpoint. Compare ordinary faster-whisper
native timing against the **same saved ASR text and regions** passed to WhisperX's
Japanese CTC aligner. Then evaluate stock WhisperX as a separate complete workflow.
This separates alignment gains from recognition/windowing differences. WhisperX
is a faster-whisper/CTranslate2 integration plus independent alignment, rather
than another independent Whisper inference engine.

Excluding denoising, source separation, diarization, and external VAD tuning from
the first comparison is reasonable. It is not reasonable to describe every
candidate's default workflow as VAD-free. Native window planning remains required.
The resulting recommendation is an experiment shortlist, not an adopted backend
or an established quality ranking.

Related: [selection priorities](../development/inference-selection.md),
[backend contracts](2026-10-03-stt-backend-contracts.md),
[application comparison](2026-10-03-stt-application-comparison.md),
[historical failure cases](2026-10-03-timestamp-failure-cases.md),
[evaluation protocol](../testing/stt-evaluation.md), and
[FateStay reference](../testing/fatestay-reference.md).

## Version and model identity

All external sources below were accessed on **2026-10-03**. GitHub release dates
and commits were read through the public GitHub REST API; model revisions were
read through the public Hugging Face model API. These are candidate evidence pins,
not installed dependency selections.

| Component | Observed identity | Evidence and implication |
| --- | --- | --- |
| faster-whisper stable | v1.2.1, published 2025-10-31; commit `65882eee9f5cdbeeb2d877f1131d48cf241b327d` | [Release](https://github.com/SYSTRAN/faster-whisper/releases/tag/v1.2.1); sensible stable demo candidate. |
| faster-whisper master | `7b99be5376b41cd481dfc52e8caa00a497c3294e`, commit date 2026-10-01 | [Commit](https://github.com/SYSTRAN/faster-whisper/commit/7b99be5376b41cd481dfc52e8caa00a497c3294e); matches the inherited contract investigation's source pin. |
| WhisperX stable | v3.8.6, published 2026-05-25; commit `3ccc17b8de34f305300f8a3fd3c9f76ba820c0d0` | [Release](https://github.com/m-bain/whisperX/releases/tag/v3.8.6); stable behavior inspected here. |
| WhisperX main | version declaration 3.8.7rc1; `771b4a14a9486f8fd5aef18ef49e35d639523dd3`, commit date 2026-09-26 | [Fixed metadata](https://github.com/m-bain/whisperX/blob/771b4a14a9486f8fd5aef18ef49e35d639523dd3/pyproject.toml); inherited backend-contract pin is main, not stable 3.8.6. |
| CTranslate2 stable | v4.8.2, published 2026-08-31; `d44d2d069eb88c7b7804da864c10c201501cb4a9` | [Release](https://github.com/OpenNMT/CTranslate2/releases/tag/v4.8.2); test one exact compatible dependency resolution. |
| CT2 large-v3 checkpoint | `Systran/faster-whisper-large-v3`, HF revision `edaa852ec7e145841d8ffdb056a99866b5f0a478` | [Model](https://huggingface.co/Systran/faster-whisper-large-v3); pin the converted artifact and tokenizer, not just the alias `large-v3`. Model API identifies MIT license. |
| Default Japanese CTC aligner | `jonatasgrosman/wav2vec2-large-xlsr-53-japanese`, HF revision `cf031e020336460d15a417eba710bbc5bb43be9a` | [Model card](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-japanese); Apache-2.0, 16 kHz input. API last-modified 2022-12-14. |

Recent commits and releases show both wrappers are maintained; they do not supply
a rigorous release-cadence forecast. The aligner is an older Japanese ASR
checkpoint used for CTC alignment. Its age and Common Voice ASR metrics do not
determine anime alignment quality. Freeze revisions before measurement, and do
not compare an unpinned master build against a stable package under one name.

Public metadata endpoints used: [faster-whisper stable release](https://api.github.com/repos/SYSTRAN/faster-whisper/releases/latest),
[WhisperX stable release](https://api.github.com/repos/m-bain/whisperX/releases/latest),
[CTranslate2 stable release](https://api.github.com/repos/OpenNMT/CTranslate2/releases/latest),
[large-v3 model identity](https://huggingface.co/api/models/Systran/faster-whisper-large-v3),
and [Japanese aligner identity](https://huggingface.co/api/models/jonatasgrosman/wav2vec2-large-xlsr-53-japanese).

## Observed upstream boundaries

### Ordinary faster-whisper and batched faster-whisper

The [stable transcription source](https://github.com/SYSTRAN/faster-whisper/blob/65882eee9f5cdbeeb2d877f1131d48cf241b327d/faster_whisper/transcribe.py)
exposes separate ordinary and batched APIs. Ordinary transcription defaults to
VAD off, decoded timestamps enabled, and previous-text conditioning enabled.
Native words use CTranslate2 alignment of Whisper attention, rather than a
separate CTC model. Timestamp precision is declared as 20 ms; this is not an
accuracy guarantee.

Batched transcription defaults to VAD on and timestamp decoding off. It forces
previous-text conditioning off, keeps only the first temperature, and disables
the hallucination-silence threshold. Several accepted keyword arguments are
unused. With long audio, VAD off requires explicit clips; clips exceeding 30 s
warn that only their first 30 s is transcribed. Its clip dictionaries use seconds
at the public boundary, while internal VAD regions use samples.

Therefore batching is a later throughput experiment with separately declared
semantics. Save `TranscriptionInfo.transcription_options`, VAD options, original
segments, words, and actual executed input spans. Turning external VAD off does
not turn decoder no-speech decisions off.

### WhisperX stable full pipeline

The [stable ASR source](https://github.com/m-bain/whisperX/blob/3ccc17b8de34f305300f8a3fd3c9f76ba820c0d0/whisperx/asr.py)
subclasses faster-whisper and generates text with CTranslate2. Full `transcribe`
unconditionally calls its VAD model and merges regions; supported named methods
are Pyannote and Silero. There is no named no-VAD mode. A manually supplied VAD
object can replace detection, but that is a custom experimental integration.

Pre-alignment segment times are VAD-region envelopes. Defaults include 30 s
chunks, onset 0.500, offset 0.363, beam 5, timestamp decoding off, and previous
text conditioning off. In this version's batched generator, beam, patience,
length penalty, suppression, and repetition options reach `generate`. Several
options in its `TranscriptionOptions` structure, including fallback-temperature
and no-speech thresholds, do not drive that generator. CLI visibility alone
does not prove a parameter changes inference.

The stable full pipeline should consequently be tested as a distinct integration
arm, with its mandatory internal VAD documented. Use standalone `whisperx.align`
after ordinary faster-whisper for the initial alignment-only comparison.

### Japanese alignment and offline assets

The [stable alignment source](https://github.com/m-bain/whisperX/blob/3ccc17b8de34f305300f8a3fd3c9f76ba820c0d0/whisperx/alignment.py)
selects the Japanese checkpoint listed above and explicitly moves the model to
the requested device. Japanese indexing is character-oriented. Alignment reads
only each supplied segment's audio interval: it cannot recover speech outside
that interval. Unknown characters can receive wildcard placement. No alignable
content, invalid regions, or failed backtracking can retain original segment
times with empty words. Missing times can be interpolated; default is nearest.
The CLI also exposes linear and ignore choices. Return character alignments for
diagnostic evaluation, and retain text-bearing failures rather than flattening
them away.

The function loads NLTK `punkt_tab`; when absent it calls `nltk.download` during
alignment. Provision that resource explicitly before the offline run, alongside
weights/tokenizers. The normal alignment result is already processed; it does
not expose complete raw CTC emissions or per-unit interpolation provenance.
Instrumentation, if required, is a separately pinned experiment.

Do not interpret the returned `score` as calibrated timing correctness. NLTK
sentence segmentation and the engine's SRT writer can also change cue grouping.
Compare cached word/character results through one common formatter before using
different stock SRT files as a quality ranking.

## Native Windows GPU readiness

| Boundary | Observed evidence | Required local proof |
| --- | --- | --- |
| CTranslate2 ASR | [Installation docs](https://opennmt.net/CTranslate2/installation.html) publish Windows x86-64 GPU wheels and require Visual C++ runtime. [faster-whisper README](https://github.com/SYSTRAN/faster-whisper/blob/7b99be5376b41cd481dfc52e8caa00a497c3294e/README.md) says CUDA 12 cuBLAS and cuDNN 9. CT2 installation prose still says cuDNN 8. | Resolve this documented mismatch against the exact wheel/build, loaded DLLs, and real large-v3 execution. Do not combine older compatibility workarounds with a Blackwell baseline. |
| PyTorch CTC alignment | [PyTorch 2.7 release notes](https://github.com/pytorch/pytorch/releases/tag/v2.7.0) introduce Blackwell support and CUDA 12.8 build changes; WhisperX stable requires torch/torchaudio `~=2.8.0`. | Pin matching native Windows CUDA wheels; verify CUDA kernels, actual model/input device, and FA smoke independently from CT2. |
| WhisperX dependency resolution | [Stable metadata](https://github.com/m-bain/whisperX/blob/3ccc17b8de34f305300f8a3fd3c9f76ba820c0d0/pyproject.toml) requires Python >=3.10,<3.14, faster-whisper>=1.2.0, CT2>=4.5.0, torch/torchaudio~=2.8.0, torchvision~=0.23.0, and HF hub<1.0.0. Triton is Linux-only; pyannote and TorchCodec remain dependency surface even when diarization is unused. | Choose an explicit compatible Windows resolution. Isolate this demo environment from the Qwen dependency resolution. |
| Windows uv sources | Stable metadata CUDA-source markers recognize `x86_64`, but not `AMD64`; its non-x86_64 marker selects CPU wheels. [Fixed main metadata](https://github.com/m-bain/whisperX/blob/771b4a14a9486f8fd5aef18ef49e35d639523dd3/pyproject.toml) adds `AMD64`. | Check `platform.machine()` and explicitly select CUDA PyTorch sources for the native Windows demo. An upstream `uv sync` is not sufficient evidence of GPU setup. |
| Distributed SE WhisperX package | [Historical packaging audit](../../../subtitle-edit-fix/docs/research/2026-10-03-se-whisperx-packaging.md) found CPU PyTorch in the investigated standalone Windows build. | Use the separately provisioned upstream Python CUDA route for this GPU-only comparison; an SE package name does not establish GPU execution. |

The upstream PyTorch release announcement is readiness evidence, not proof that
this exact RTX 5080, Windows driver, CT2 wheel, and CTC model combination works.
Capture CT2's resolved compute type and GPU plus PyTorch model/input devices.
Fail explicitly if the requested inference device is unavailable. CPU audio
handling and CTC trellis/postprocessing do not constitute CPU model fallback.
Measure actual total GPU peak memory; PyTorch's allocator cannot account for all
CTranslate2 allocations.

## Bounded experimental arms

Arm IDs follow the [integrated demo plan](../plans/local-stt-demo-selection.md).
That plan owns the final experiment budget and sequence; probes below are options
within that budget, not an additional mandatory sweep.

| Arm | ASR | Timing | Purpose |
| --- | --- | --- | --- |
| W0 | Ordinary faster-whisper, large-v3 CT2, CUDA float16, Japanese, transcribe | Native segments and words | Minimal engineering baseline with no external VAD. |
| W1 | Reuse W0 saved recognition and regions | WhisperX Japanese CTC on CUDA | Isolate independent alignment without changing recognition text. |
| W1-native | Stock WhisperX large-v3, fixed stable version | Its internal VAD regions + same Japanese CTC | Measure the complete integration, including different recognition/windowing. |
| W2, optional | Reuse fixed recognition text/windows from a finalist | Qwen ForcedAligner on CUDA | Cross-family diagnostic if existing assets and execution budget make it cheap; not a mandatory expanded factorial. |

For W1, first use W0 regions unchanged. If clipping causes failures, predeclare
0.25 s and 0.50 s padding variants, derived only from predicted regions and
clamped to audio duration. Save actual regions and original times; adjacent
expanded regions can overlap. Padding is a substantive configuration change,
not a post-hoc repair using reference subtitle times.

Separately, a small aligner-only diagnostic may use reviewed reference text and
fixed broad audio windows to measure aligner potential. Mark this as oracle-text
alignment, exclude it from end-to-end ASR quality, and never use reference cue
edges as the aligner's search bounds for the main score.

The [application studies](2026-10-03-stt-application-comparison.md) support these
controls: SE changes times after engine output; VideoLingo flattens unit
provenance and adds display policies; pyvideotrans can lose mixed text-only
segments. Their full workflows are informative integration references rather
than ready-made fair benchmark drivers.

## Parameter search proposal

This is a small sequential search, not an exhaustive claim of global optimum.
Use a frozen development set; promote only shortlisted configurations to held-out
scenes and the full FateStay input. Do not tune on the final test report.

1. **Control run:** W0 uses beam 5, temperature 0, previous-text conditioning off,
   prompt/hotwords empty, VAD off, timestamps on, and words on. Also record a
   library-default ordinary run as a diagnostic reference. W1 initially reuses
   the control recognition. W1-native records its actual fixed defaults and executed
   generation options.
2. **Recognition choices:** W0 tests beam {1,5} crossed with previous-text
   conditioning {off,on}. Test the ordinary fallback-temperature schedule only
   when repeats, omissions, or low-confidence failure justify it. Investigate
   decoder no-speech options on preselected weak/short-speech and silence cases;
   disabling skips must be checked for new hallucinations. W1-native tests only
   generator-effective beam options at this stage.
3. **Alignment choices:** Compare W1 padding {0,0.25,0.50 s}. Compare nearest and
   linear interpolation against ignore on fixed text/regions, reporting missing
   units and coverage. Interpolation gains must not conceal failures. Do not
   search arbitrary text-cleaning combinations before a diagnosed problem.
4. **Workflow choices:** Only for promising W1-native results or clear region failures,
   test chunk sizes {15,30 s} and one separately labeled Pyannote/Silero contrast.
   This is a later internal VAD/windowing experiment; stop when added complexity
   lacks held-out timing benefit. Stock thresholds are the control, not presumed
   optimal values.
5. **Resource choices:** After quality finalists, test float16 versus
   int8_float16 for W0/W1 ASR if supported, and batch {1,4,8} for W1-native. Do not shrink
   the model just for an initial speed result. Compare sequential ASR-then-FA
   residency with concurrent residency only when necessary, preserving outputs
   and measuring total VRAM and end-to-end time.

Some native word-timestamp paths can affect window progression. Freeze the saved
ASR output when isolating aligners rather than assuming two recognition calls
that differ only in timing flags necessarily produce identical text.

Pick the best observed feasible configuration using the main plan's timing-first
criteria, coverage gates, recognition guardrails, and held-out validation. Keep
all failed or missing items in the denominator. Report a Pareto comparison when
small timing differences do not justify an accuracy, stability, or integration
regression. Large-v2 and the unresolved `anime.ja` artifact are later challengers
only if the large-v3 results leave a concrete quality gap.

## Remaining unknowns and verification

- Native Windows GPU load/inference, compatible DLL resolution, dependency lock,
  cold/warm speed, and total VRAM have not been measured.
- Default Japanese CTC alignment quality on FateStay is unknown; wildcard,
  interpolation, and text mismatch can create large local tails.
- No source establishes that stock WhisperX outperforms controlled
  faster-whisper plus the same aligner on this corpus.
- Stable v3.8.6 and main 3.8.7rc1 differ. New interleaved-context functionality
  advertised by main must be a separate later version experiment.
- Offline inference requires more than cached model weights: verify tokenizers,
  feature configuration, NLTK resources, and optional VAD assets after acquisition.
- Source/API inspection and documentation consistency checks were performed.
  Model smoke tests, audio processing, and quality measurements were not run.
