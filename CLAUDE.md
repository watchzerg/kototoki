# Kototoki

Self-hosted Speech-to-Text (STT) tool: Python + local AI models, native Windows, RTX 5080.
The repo is in the **research/demo phase**, not product development: W0/X0 baselines and
reusable demos exist; backend migration, UI, streaming, packaging are still open.
Inspect current code and the baseline testing guide before changing any baseline component.

## Hard constraints

- **Local only.** Audio and transcripts stay on the user's machine. Do not call external
  inference services unless explicitly asked.
- **GPU-only ASR and forced alignment**, no CPU fallback. VAD may use CPU or GPU
  (see [inference selection](docs/development/inference-selection.md)).
- **Preserve the spoken language** in transcription (Japanese stays Japanese).
- **Keep out of Git and logs:** model weights, caches, recordings, generated transcripts,
  secrets, `.local/`. Do not print audio contents or full transcripts by default.
- **Frozen historical evidence is read-only.** Result reports, `docs/context/*`, ADR history,
  and the Codex-era translation-judge chain (`experiments/translation_judge/`,
  `experiments/translation_flow/v2_*`, `experiments/translation_eval/`, reference prompts)
  contain sha256 self-checks and recorded `gpt-6.1-sol` / `codex-cli` identities. Never
  rename, reformat, or "modernize" them. Add new versioned files instead.
- `reasoning_effort:no_think` in translation code is a Hy-MT2 chat-template token, not an
  agent setting. Never bulk-replace `reasoning_effort`.

## Baseline identities

- **W0**: faster-whisper + new Pyannote segmentation-3.0 + MMS CTC alignment, with WhisperX
  ideas ported (cut-merge, timestamp-free decoding, feature handling).
- **X0**: Qwen-ASR + new Pyannote + the same MMS, adopting only WhisperX ideas compatible
  with Qwen (keep Qwen-native decoding/features). fixed30 and no-VAD cut-merge are separately
  identified controls.
- **Translation** (separate experiment, not part of the STT milestone): Hy-MT2 30B-A3B
  APEX-I-Compact, sampling recipe `official30b-cached-v1`; full-SRT flow baseline is the v3
  recipe `b10-joint` (ADR-0006: 10 targets/batch, 1 neighbour each side, joint-understanding prompt).
- Legacy CLI defaults (old PyanNet / fixed30) are **not** the adopted baselines. Select new
  Pyannote explicitly. See [ADR-0003](docs/adr/0003-new-pyannote-baselines.md).

## Commands (Windows, PowerShell; mise + uv + just)

Use `uv run --locked --offline ...`; the root env has no inference deps, so it cannot run
models. Inspect the real recipe in `justfile` before invoking anything.

- Safe/offline: `just check`, `just test`, `just translation-test`,
  `just translation-flow-test`, `just translation-flow-v2-test`, `just --list`.
- **Heavy, ask first** (GPU, model load, can run for hours): `just x0-demo`,
  `just translation-demo`, `just translation-baseline`, `just translation-srt`, `just translation-flow`,
  `just translation-eval`, W0 via `.local/envs/whisper-latest/Scripts/python.exe -m
  experiments.w0_demo.run`, anything under `experiments.*` that loads a model.
- `.local/gpu.lock` marks a running GPU job. Do not preempt or kill other processes; verify
  real processes (PowerShell `Get-Process`) rather than trusting what a doc says is running.
- `just setup` / `uv sync/add/lock` change the environment (may go online): ask first.

## Task routing (read on demand, not all at once)

Entry point for anything docs-related: [docs/INDEX.md](docs/INDEX.md).

| Task | Read first |
| --- | --- |
| Test / benchmark / compare W0 or X0 | [baseline testing guide](docs/guides/baseline-testing.md), then the demo README, contract, validation record |
| Run or change X0 (segmentation, Qwen input, MMS) | [X0 demo](experiments/x0_demo/README.md) → [contract](docs/specs/x0-reusable-demo.md). Reuse `experiments/x0_demo/`; `x0_flow` and `qwen` are regression references only |
| Run or change W0 (VAD, ASR, alignment) | [W0 demo](experiments/w0_demo/README.md) → [contract](docs/specs/w0-reusable-demo.md). Reuse and update `experiments/w0_demo/`; version changed recipes and record validation before updating baseline docs |
| Translation baseline | model/sampling: [ADR-0005](docs/adr/0005-apex-i-compact-translation-baseline.md); full-SRT flow `b10-joint`: [ADR-0006](docs/adr/0006-b10-joint-translation-flow-baseline.md), `just translation-srt`; [translation demo](experiments/translation_demo/README.md) |
| Translation flow exploration (v4, completed) | [v4 report](docs/research/2026-10-11-hy30-flow-v4-report.md), [v4 ledger](docs/context/2026-10-11-hy30-flow-exploration-v4.md), [`experiments/translation_v4`](experiments/translation_v4/README.md); 1 confirmed recipe `mbr8c` (~6x wall clock), not adopted |
| Translation flow exploration (v3, completed) | [v3 report](docs/research/2026-10-10-hy30-flow-v3-report.md), [v3 plan](docs/plans/hy-mt2-translation-flow-exploration-v3.md), [`experiments/translation_v3`](experiments/translation_v3/README.md); judge profile `claude-opus-5-5-mqm-v1` |
| Old translation evaluations (history) | [evaluation method](docs/testing/translation-model-evaluation.md) + [workflow](docs/agents/subtitle-translation-evaluation.md): frozen Codex-era `sol-high-auto-v1`; never mix those scores with Claude-judged ones |
| Choose or compare STT engines, models, aligners | [inference selection principles](docs/development/inference-selection.md) |
| Dependencies, tool versions, tasks | [toolchain](docs/development/toolchain.md); platform/GPU: [Windows and NVIDIA](docs/development/windows-nvidia.md) |
| Test planning / acceptance evidence | [validation boundaries](docs/testing/validation.md) |
| Implementing behavior | relevant `docs/specs/`, `docs/plans/`; architecture in `docs/architecture/`, `docs/adr/` |
| Resuming work | `docs/context/` handoffs; **verify status against the repo first** |

**v4: completed 2026-10-12** ([v4 report](docs/research/2026-10-11-hy30-flow-v4-report.md)): one recipe confirmed,
`mbr8c` (8 samples per batch, per-cue local chrF-MBR; confirm Δ −0.016 ≈ 4%, mostly series; ~6x wall clock);
`t03` not confirmed. Baseline stays `b10-joint` until the user decides. The v4 confirm set is now opened; any new
confirmation needs a fresh, isolated set.
**v3: completed 2026-10-10** (converged, 0 confirmed recipes; the user then adopted `b10-joint` as an
engineering choice, ADR-0006). Results: [v3 report](docs/research/2026-10-10-hy30-flow-v3-report.md);
history: [v3 ledger](docs/context/2026-10-10-hy30-flow-exploration-v3.md). Its confirmation set is
now opened; any new confirmation needs a fresh, isolated set. Round 2 (v2) is stopped and frozen; its
ledger is 1300+ lines of history, so do not load it whole and never resume its jobs. Use only
the [v1/v2 lessons](docs/research/2026-10-10-hy30-flow-v1-v2-lessons.md) as priors.

Tickets and skills use local Markdown (`.scratch/<feature>/`): see
[issue tracker](docs/agents/issue-tracker.md), [triage labels](docs/agents/triage-labels.md),
[domain rules](docs/agents/domain.md).

## Engineering conventions

- Keep audio loading/preprocessing, model inference, and output handling separate from
  CLI/API/UI; keep model-specific details behind a boundary testable without a model.
- Type hints on public interfaces; explicit data structures for shared transcription results.
- Model path, device, inference options configurable; fail with actionable errors on
  unsupported configs. No model load or download at import time. Model acquisition is
  separate from inference; after provisioning, inference must work offline.
- Validate inputs (missing/unreadable/empty/silent audio, unsupported formats) and clean up
  temp files on success and failure.
- Routine tests stay offline, GPU-free, and use small synthetic fixtures or fake backends.
  For inference changes run a real local smoke test if assets exist; otherwise state that
  real inference is unverified. Record model, device, settings, and sample characteristics
  for any quality/performance measurement.
- Native Windows is the validation target; report macOS as unverified.

## Documentation upkeep

After changing code, config, scripts, or dependencies, check the affected docs (README,
CLAUDE.md, `docs/`) and update only what became inaccurate. No mechanical rewrites or date
refreshes. Record durable technical decisions (ADR) and distinguish proposals from
implemented capability. Docs conventions live in [docs/INDEX.md](docs/INDEX.md).

## Working with Claude Code

- Reply to the user in Simplified Chinese, keeping established English technical terms.
  Code, identifiers, commands, and agent-facing docs are English; human-facing plans,
  guides and reports are Chinese.
- Do not start demos or heavy jobs while the user asked only for investigation or cleanup.
- Large dirs (`.local/`, `.venv/`, `tests/bridge-cohort-test-*`, `docs/research/*appendices`)
  make Grep/Glob slow. Search specific subpaths.
- Delegation: use subagents proactively for bounded research, audits, implementation and
  validation when the benefit outweighs coordination cost; small tightly coupled edits stay
  with the main agent. **Always set `model` explicitly: default `sonnet` (Sonnet 5.5); upgrade
  to `opus` (Opus 5.5) only for complex tasks** (cross-module design, subtle debugging,
  judging-protocol or statistics work). Do not inherit a more expensive parent model.
- Give each subagent scope, context, completion criteria, and file ownership. Writers get
  disjoint files or worktrees; shared config and lockfiles go through one owner. Audit
  agents are read-only. Subagents must not run GPU jobs or demos unless the user asked.
- The main agent reviews and integrates all delegated changes and reports remaining
  uncertainty.
