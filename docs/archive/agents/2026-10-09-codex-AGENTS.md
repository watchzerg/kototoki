---
status: archived (superseded by root CLAUDE.md on 2026-10-09)
---

<!-- Original Codex-era AGENTS.md, preserved verbatim below. Historical reference only. -->

# Agent Instructions

## Project scope

Kototoki is a self-hosted Speech-to-Text (STT) tool built primarily with Python
and local AI models. The current milestone is audio transcription.

- Run speech recognition locally. Keep audio and transcripts on the user's
  machine by default; external inference services require an explicit request.
- The separate subtitle-translation experiment has adopted Hy-MT2 30B-A3B
  APEX-I-Compact as its baseline. Translation is not integrated into the current STT
  milestone. Preserve the spoken language in transcription; keep translation
  work within its explicitly requested scope.
- Native Windows on the user's RTX 5080 is the primary target. ASR and forced
  alignment engine selection is GPU-only, without CPU fallback, and is not
  limited to CUDA. VAD may use CPU or GPU; see the inference selection principles
  linked below for selection criteria.
  The repository is at an early stage. W0/X0 experiment baselines and reusable
  demos are established; product backend migration, UI, streaming, packaging,
  and broader GPU compatibility remain open. Inspect current code and the
  baseline testing guide before selecting or changing a baseline component.

## Working process

1. Read the relevant code, README, and dependency/tool configuration before
   editing. Treat repository configuration as the source of truth for commands.
2. Implement the smallest complete change that satisfies the requested task.
   For initial implementation, prefer a working local audio-to-text path before
   adding optional capabilities or general-purpose infrastructure.
3. Verify the affected behavior using the available checks. Report what passed,
   what could not be run, and any remaining limitations.
4. After every change to project code, configuration, dependencies, scripts, or
   other project artifacts, review the existing documentation affected by that
   change, including README, AGENTS.md, and relevant docs/ entries. Update the
   authoritative text and affected references only when they are no longer
   accurate or complete. If no documentation change is needed, leave it unchanged;
   do not mechanically rewrite text or refresh dates. Record adopted technical
   decisions and their reasons when they affect future work, distinguishing
   proposals from implemented capabilities.

## Agent delegation

- Proactively delegate when the expected benefit outweighs coordination overhead.
  The primary agent should focus on planning, synthesis, analysis, integration,
  and final conclusions; delegate bounded research, implementation, and validation
  work where useful. Small, tightly coupled edits may be handled directly.
- Subagents may delegate further when worthwhile. Pass down the task scope,
  relevant context, completion criteria, write ownership, and these delegation
  constraints at every level.
- Choose each subagent's model and reasoning effort to fit the task. The maximum
  permitted configuration is `gpt-6.1-sol` with `high` reasoning effort. Use that
  model or less capable Sol/Luna alternatives, with effort no higher than `high`.
  Astra models are prohibited. Set allowed model/effort explicitly when spawning
  rather than inheriting a parent configuration that could exceed these limits.
- Prevent concurrent write conflicts: assign disjoint file ownership or isolated
  worktrees, serialize overlapping edits, and coordinate shared configuration and
  lockfile changes through one owner. Subagents must preserve others' changes
  and report any needed edits outside their assigned scope before making them.
- The primary agent remains responsible for reconciling findings, reviewing and
  integrating delegated changes, verifying the combined result, and reporting
  conclusions and remaining uncertainty to the user.

## Documentation routing

The W0/X0 demo routing below is temporary guidance for the evaluation phase.
When the project stabilizes, replace it with production entry points and remove
obsolete guide links together.

- Before testing, benchmarking, or comparing current W0/X0 baselines, read
  [baseline testing guide](docs/guides/baseline-testing.md), then the selected
  demo README, contract, and validation record. Use the canonical demos for
  fresh baseline inference; use frozen historical runners only for explicitly
  identified historical reproduction. Both adopted baselines now use new Pyannote;
  read [ADR-0003](docs/adr/0003-new-pyannote-baselines.md) for model identity and
  the distinction between adopted components and unchanged legacy CLI defaults.
- Before running or developing current X0, changing segmentation or Qwen input
  handling, or connecting MMS, read [X0 demo](experiments/x0_demo/README.md) and
  its linked contract. Reuse `experiments/x0_demo/`; keep historical `x0_flow`
  and `qwen` experiments as regression references. X0 uses new Pyannote and MMS;
  retain fixed30 and no-VAD cut-merge as separately identified controls.
  Adopt only WhisperX flow ideas compatible with Qwen:
  retain equivalent native decoding and feature handling instead of copying
  Whisper-specific logic. Low-energy cut-merge is an extra experiment, not a
  required baseline step or a literal WhisperX transplant.
- Before running or benchmarking current W0, changing its implementation,
  replacing its VAD, or tuning its ASR/alignment behavior,
  read [W0 demo](experiments/w0_demo/README.md) and its linked contract.
  Reuse and update `experiments/w0_demo/`; preserve historical experiment code
  and results as regression references. Version changed recipes and record
  validation evidence before updating the current baseline documentation.
- Read [docs/INDEX.md](docs/INDEX.md) when locating, creating, or updating project
  documentation. It defines directory purposes, document conventions, and links
  to current documents. Read relevant files on demand rather than loading all docs.
- Before discussing, optimizing, or running the subtitle-translation baseline,
  read [ADR-0005](docs/adr/0005-apex-i-compact-translation-baseline.md) and the
  [translation demo](experiments/translation_demo/README.md). Use the adopted
  Hy-MT2 30B-A3B APEX-I-Compact identity and explicit compatible engine as the reference;
  version changes and preserve the frozen comparison evidence.
- Before evaluating subtitle translations, comparing translation models, or
  reviewing judge results, follow [translation evaluation](docs/testing/translation-model-evaluation.md)
  and its mandatory [agent workflow](docs/agents/subtitle-translation-evaluation.md).
- Before implementing behavior, consult relevant `docs/specs/` and `docs/plans/`;
  when resuming work, consult applicable `docs/context/` handoffs and verify their
  status against the repository.
- For component boundaries or technical choices, consult `docs/architecture/`
  and `docs/adr/`; for investigations and comparisons, consult `docs/research/`.
- Before researching, comparing, demoing, or adopting an STT engine, model,
  precision, or aligner, read [inference selection principles](docs/development/inference-selection.md)
  for the user's preferred candidates, model-size priorities, and experiment scope.
- For domain terminology or naming, consult `docs/glossary/`; for setup and
  operation, `docs/guides/`; for evaluation and validation, `docs/testing/`.
- For dependencies, tool versions, or task commands, read
  [Python toolchain](docs/development/toolchain.md). For platform behavior,
  subprocesses, or GPU setup, read
  [Windows and NVIDIA](docs/development/windows-nvidia.md). For test planning or
  interpreting acceptance evidence, read [validation boundaries](docs/testing/validation.md).
- Maintain affected documents and index links with the change. Treat
  `docs/archive/` as historical reference and distinguish drafts, recommendations,
  and superseded decisions from current requirements. Empty categories impose no
  additional requirements and need not be populated for unrelated tasks.

## Python and architecture

- Use mise for project tool selection, uv for Python and dependencies, and just
  for shared task entry points once configured. These tools are installed on the
  user's machine; the lightweight demo toolchain is configured. Use the uv project
  environment for Python execution and inspect actual recipes before invoking them.
- Separate audio loading/preprocessing, model inference, and output handling
  from the CLI, API, or UI as those components are introduced. Keep model-specific
  details behind a small boundary that can be tested without loading a model.
- Use type hints for public interfaces and explicit data structures for shared
  transcription results. Add timestamps or other metadata when required by the
  task and supported by the backend.
- Make model location, device selection, and relevant inference options
  configurable. Report unsupported configurations with actionable errors.
- Avoid loading models or downloading assets at module import time. Reuse loaded
  models when processing multiple inputs within a session.

## Audio, models, and privacy

- Validate inputs and handle missing/unreadable files, unsupported formats,
  empty or silent audio, and inference failures deliberately.
- Match sample rate, channels, and input representation to the selected backend's
  requirements. Keep preprocessing explicit and preserve source audio.
- Keep model acquisition separate from normal inference. Document required
  downloads, model licenses, and system dependencies when introducing them.
  Once assets are provisioned, the transcription path should work offline.
- Keep model weights, caches, recordings, generated transcripts, and secrets out
  of Git. Use small synthetic or explicitly redistributable test fixtures.
- Avoid logging audio contents or full transcripts by default. Clean up temporary
  audio files when processing finishes or fails.

## Verification

- Keep routine tests offline and independent of a GPU or large model download.
  Test preprocessing and output behavior with small fixtures and a fake backend.
- For inference changes, run a real local model smoke test when assets are
  available; otherwise explicitly report that real inference remains unverified.
- When measuring quality or performance, record the model, device, relevant
  settings, and audio sample characteristics so results can be reproduced.

## Environment and communication

- Honor the active execution and approval policy. If an operation requires
  approval, use the environment's supported approval mechanism; never bypass it.
- On Windows, use PowerShell-compatible commands and quote literal paths and
  arguments. Validate platform-sensitive changes on native Windows; report
  macOS compatibility as unverified unless tested.
- Use English for agent-facing instructions, code identifiers, and tool/skill
  interactions. Communicate with the user in Simplified Chinese while preserving
  established English technical terms.

## Agent skills

### Issue tracker

Before reading, creating, or updating tickets, read
[local Markdown conventions](docs/agents/issue-tracker.md).

### Triage labels

Before triaging tickets, read
[triage status vocabulary](docs/agents/triage-labels.md).

### Domain docs

Before exploring domain concepts or proposing technical decisions, read
[single-context domain rules](docs/agents/domain.md).
