# Qwen and Crisp Demo Readiness

Status: exploratory; source review only, no local inference or adopted stack
Last updated: 2026-10-03
Scope: official Qwen3-ASR-1.7B and Qwen3-ForcedAligner-0.6B versus CrispASR on native Windows and RTX 5080, with subtitle timing as the primary selection objective.

## Evidence and identity

Planning update: the user requires the latest official documentation/model-card
baseline at demo setup. The [integrated plan](../plans/local-stt-demo-selection.md)
therefore supersedes this snapshot's original-wrapper-first recommendation:
select the currently recommended API/checkpoints for Q0 and retain the original
wrapper only as a labeled diagnostic when useful. Native preprocessing is allowed.
Version-bound observations below remain historical evidence, not execution pins.

All upstream links below were accessed on 2026-10-03. GitHub and Hugging Face metadata were also retrieved directly through their public APIs. No packages, binaries, or weights were installed or run. Existing sibling findings were read as historical evidence, particularly [backend contracts](2026-10-03-stt-backend-contracts.md), [candidate selection](2026-10-03-model-backend-candidates.md), [timestamp failure cases](2026-10-03-timestamp-failure-cases.md), and the [original Crisp survey](../../../subtitle-edit-fix/docs/research/2026-10-03-crisp-backend-selection.md).

“Crisp” resolves here to [CrispStrobe/CrispASR](https://github.com/CrispStrobe/CrispASR), a C++ ggml runtime with CLI, shared library, bindings, and multiple model backends. It is an integration/runtime choice, not a separate Qwen model. This identifies the project matching the earlier Subtitle Edit investigation; it does not prove that any installed binary has the same revision.

| Component | Observed source identity |
| --- | --- |
| Official `qwen-asr` wrapper | GitHub HEAD `7c6daf77a2421100f5fb066495372c00129d39ff`; latest retrieved commit dated 2026-06-26 |
| Official original ASR | `Qwen/Qwen3-ASR-1.7B`, HF revision `7278e1e70fe206f11671096ffdd38061171dd6e5` |
| Official original FA | `Qwen/Qwen3-ForcedAligner-0.6B`, HF revision `c7cbfc2048c462b0d63a45797104fc9db3ad62b7` |
| Official native Transformers ASR | `Qwen/Qwen3-ASR-1.7B-hf`, HF revision `bcd2b5b7f32b480ab5790554cfa8347f246a14f3` |
| Official native Transformers FA | `Qwen/Qwen3-ForcedAligner-0.6B-hf`, HF revision `c07281df297b9905d24a508279258cccf987a064` |
| Crisp release proposed for a new demo | `v0.8.41`, tagged commit `340d7085eaa53c40a46dcb73a6d3d0448a480006`, published 2026-10-02 15:21:50 UTC |
| Crisp base Qwen conversion | `cstr/qwen3-asr-1.7b-GGUF`, HF revision `674df5d44b50a63e7102a18895ed20e3f91de301` |
| Crisp FA conversion | `cstr/qwen3-forced-aligner-0.6b-GGUF`, HF revision `1ec5110602ccab18c878ddebedab0891e290a95c` |
| Possible intended anime conversion | `cstr/qwen3-asr-1.7b-ja-anime-GGUF`, HF revision `1906c1f812b598d5e9dae091c79656d73b41ec28` |

Metadata endpoints: [Qwen commits](https://api.github.com/repos/QwenLM/Qwen3-ASR/commits?per_page=3), [Crisp releases](https://api.github.com/repos/CrispStrobe/CrispASR/releases?per_page=6), [annotated tag](https://api.github.com/repos/CrispStrobe/CrispASR/git/tags/0ad352401c9164e08bc3b7e91fce98df0cb77eba), and HF model APIs for the [original ASR](https://huggingface.co/api/models/Qwen/Qwen3-ASR-1.7B), [original FA](https://huggingface.co/api/models/Qwen/Qwen3-ForcedAligner-0.6B), [native ASR](https://huggingface.co/api/models/Qwen/Qwen3-ASR-1.7B-hf), [native FA](https://huggingface.co/api/models/Qwen/Qwen3-ForcedAligner-0.6B-hf), [base GGUF](https://huggingface.co/api/models/cstr/qwen3-asr-1.7b-GGUF), [FA GGUF](https://huggingface.co/api/models/cstr/qwen3-forced-aligner-0.6b-GGUF), and [anime GGUF](https://huggingface.co/api/models/cstr/qwen3-asr-1.7b-ja-anime-GGUF).

These are repository revisions, not downloaded artifact SHA256 values. Provisioning must additionally record actual filenames, LFS/file hashes, converter identity where available, runtime binary hashes, and resolved dependency versions. HF `lastModified` is not a new training date.

The supplied `1.7b-amine-q8_0` is still an ambiguous user label. The anime GGUF card identifies [jaykwok/Qwen3-ASR-1.7B-JA-Anime-Galgame-hf](https://huggingface.co/jaykwok/Qwen3-ASR-1.7B-JA-Anime-Galgame-hf) as its fine-tuned source and provides `qwen3-asr-1.7b-ja-anime-q8_0.gguf`. This is a plausible resolution, not permission to silently rename the supplied artifact. The official-base f16 candidate resolves to `qwen3-asr-1.7b-f16.gguf`. [Fixed anime conversion card](https://huggingface.co/cstr/qwen3-asr-1.7b-ja-anime-GGUF/blob/1906c1f812b598d5e9dae091c79656d73b41ec28/README.md).

## Route comparison

| Dimension | Official Qwen route | Crisp Qwen route |
| --- | --- | --- |
| Integration boundary | Python model/processor and independent aligner | Native runtime through CLI or persistent shared-library session |
| Weight representation | Official safetensors checkpoint | Third-party GGUF conversion; precision is an additional variable |
| Subtitle packaging | Requires an explicit downstream formatter | Includes formatting and alignment pipelines; these can affect final cue envelopes |
| Controlled experiments | Direct access to text, audio windows, model calls, and processor behavior | CLI/bindings expose many controls, but resolved native pipeline behavior must be inspected |
| Native Windows packaging | PyTorch/Transformers and Japanese tokenizer dependencies need smoke validation | Release includes Windows CUDA/Vulkan CLI, library, and Python wheel assets; runtime success remains unverified |
| Maintenance evidence | Standalone wrapper commit history is sparse; native Transformers integration is another maintenance surface | Six retrieved releases span 2026-09-23 to 2026-10-02, indicating frequent recent publication and version churn |

The [Crisp v0.8.41 release](https://github.com/CrispStrobe/CrispASR/releases/tag/v0.8.41) includes Windows CUDA, CUDA 12.6/13 variants, Vulkan, and bindings. Publication frequency does not establish correctness or predict future support. Pin one release throughout tuning rather than mix a moving `main` with release binaries.

The original [Qwen wrapper configuration](https://github.com/QwenLM/Qwen3-ASR/blob/7c6daf77a2421100f5fb066495372c00129d39ff/pyproject.toml) identifies package `0.0.6` and pins Transformers `4.57.6`, `nagisa==0.2.11`, and Accelerate `1.12.0`; vLLM is optional. The [official native ASR card](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf) currently specifies Transformers `>=5.13.0`, direct generation, language/prompt helpers, and compilation support. These are distinct API/environment routes. The `-hf` naming is not evidence of a newly trained successor or byte-identical weights.

Recommendation: first establish the original official wrapper as the reference matching the fixed contract investigation; evaluate native `-hf` separately if its Windows environment passes provisioning and GPU smoke checks. Use explicit GPU placement for ASR and FA, rather than copy model-card `device_map="auto"` examples. Do not make optional FlashAttention, vLLM, or compilation prerequisites for the initial Windows experiment. They are later performance experiments; no native Windows compatibility was demonstrated here.

## Controls that matter to timing

The [official wrapper code](https://github.com/QwenLM/Qwen3-ASR/blob/7c6daf77a2421100f5fb066495372c00129d39ff/qwen_asr/inference/qwen3_asr.py) exposes context, language, inference batch limit, and generated-token limit. Its high-level transcribe signature does not expose a universal Whisper-like decoding grid. Timestamp mode changes the recognition window target from 1200 to 180 seconds; therefore a timestamp on/off comparison can change ASR context as well as add FA. Fix externally prepared windows when isolating alignment. Decode caps must be large enough to avoid truncation and recorded explicitly.

The [Crisp CLI reference](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/docs/cli.md) exposes fallback chunk size, aligner selection, standalone alignment, temperature, seed, beam width, token cap, hotwords, and formatting settings. Start greedy with no prompt. Confirm each requested option reaches the Qwen backend before tuning it. `--align-only` supports fixed reference text and preserved SRT cue structure, making it useful for diagnostic alignment; output must go to a new file. CLI SRT is already a formatted pipeline output, so retain word/full JSON alongside it.

Turning VAD off is insufficient to guarantee identical input selection. [Crisp environment variables](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/docs/environment-variables.md) document a default energy silence gate for chunked no-VAD audio and VAD failover behavior. For a controlled continuous-input arm, inspect selected windows and set `CRISPASR_ENERGY_SILENCE_GATE=0` when the intended design requires every window to reach ASR. Record that change; a native-default pipeline comparison should retain and report defaults instead. This is an experiment control, not a recommendation to permanently remove silence rejection.

GPU initialization can choose a compiled accelerator or CPU. Require logged GPU device selection for both ASR and FA and treat automatic CPU fallback as an invalid candidate run. The [Qwen native context interface](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/qwen3_asr.h) carries `use_gpu`; ASR success alone does not prove aligner placement. [Bindings documentation](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/docs/bindings.md) exposes sessions and alignment, but timestamp units differ across language bindings. Python converts C ABI centiseconds to seconds and preserves missing-time sentinels; verify the selected boundary instead of guessing units.

The current [Crisp FA correction](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/core/qwen3_forced_aligner.h) identifies itself as an exact port of the official correction at Qwen revision `7c6daf77…`. [Qwen native inference source](https://github.com/CrispStrobe/CrispASR/blob/v0.8.41/src/qwen3_asr.cpp) hardcodes an 80 ms timestamp category unit and notes material differences from the former correction. Historical Crisp v0.8.32 correction findings therefore motivate regression cases, not a claim that v0.8.41 still has that exact defect. Monotonic corrected output still does not establish acoustically correct boundaries.

## Recommended experiment arms

These are proposed controls for the parent demo plan, not executed experiments:

The [integrated demo plan](../plans/local-stt-demo-selection.md) owns the final
budget/sequence: Q-O maps to Q0, Q-C to Q1, and Q-C8 to Q1-q8. Other arms below
are conditional probes, not a second mandatory sweep.

1. **Q-O reference:** original official Qwen3-ASR-1.7B in a supported half precision, plus original official FA-0.6B on GPU. Fix Japanese language, PCM and external continuous windows; batch 1, no prompt, sufficiently high token cap. Capture text and native aligned units before shared formatting.
2. **Q-C conversion comparison:** Crisp v0.8.41 with official-base ASR f16 GGUF and FA f16 GGUF, same source windows and shared formatter. Keep backend selection explicit. A mismatch may involve conversion, preprocessing, decoding, tokenization, or correction; it is not automatically a model-family difference.
3. **Q-C8 precision comparison:** change only base ASR f16 to q8_0, keeping FA f16. Test FA q8_0 later as its own factor; jointly quantizing both initially loses attribution.
4. **Q-CA domain comparison:** optional confirmed JA-Anime q8_0 ASR plus unchanged FA f16. Treat checkpoint and precision changes separately from official base. Do not rank it from converter-card marketing.
5. **Q-H interface comparison:** optional official `-hf` ASR/FA in a separate compatible Transformers environment. Pin processors and generation settings and compare with Q-O before treating it as a replacement reference.

For Q-O and Q-C, include an **oracle-text FA diagnostic** with human-verified spoken text and identical audio windows, and a second FA diagnostic on a frozen ASR transcript. These disentangle alignment failure from recognizer text error. Oracle text is evaluation evidence, never a prompt or transcript input in the blind recognition leaderboard. Japanese units differ between processors; compare text-span/cue-envelope mappings rather than matching word arrays by index.

Run each route's **native-default long-input pipeline** separately after fixed-window screening. This quantifies practical packaging and defaults while avoiding a false claim that the same nominal model establishes a controlled comparison. Include leading silence, long internal gaps, repeated short utterances, music, overlapping dialogue, boundary-crossing speech, and failed/empty alignment cases from the FateStay corpus and historical regression taxonomy. Timing outliers and missing coverage remain failures even when the API returns successfully.

Prioritize window duration and boundary handling before large sampling grids. Proposed development-only sweep: continuous 30/60/120/180 s windows, then bounded leading/trailing context variations for alignment, token caps that eliminate clipping, and precision. Select using the parent plan's cue timing tails and coverage guardrails; retune on development inputs only. Prompts/hotwords and beam search follow only when identifiable recognition errors justify them. GPU batch/residency/attention choices follow timing-quality screening and require peak-memory evidence.

## Judgment and remaining unknowns

Both official Qwen + FA and Crisp Qwen + FA merit the initial shortlist. Official Python offers the clearest reference boundary for diagnosing timing; Crisp offers a concrete native packaging comparison and precision options. Neither has demonstrated Kototoki timing acceptance or RTX 5080 end-to-end reliability in this review.

ASR and FA both cover Japanese in [official documentation](https://github.com/QwenLM/Qwen3-ASR), but ASR's song/BGM claims do not extend FA's speech-only support declaration. The [FA evaluation card](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B) reports aggregate alignment measures; it does not establish subtitle P95/P99 tails on animation. Raw/Concat-300s Japanese results and a missing WhisperX Japanese table cell cannot justify a claim that Qwen already beats WhisperX on this workload.

No measured memory, speed, Windows install success, conversion equivalence, or subtitle offset winner is established. The default [FateStay reference](../testing/fatestay-reference.md), [evaluation protocol](../testing/stt-evaluation.md), and [inference constraints](../development/inference-selection.md) remain authoritative. New experiments must preserve immutable source hashes and keep all private audio, transcripts, and model assets out of Git.
