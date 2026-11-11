# Issue tracker: Local Markdown

Track tasks as Markdown under `.scratch/<feature-slug>/`. The directory is tracked in Git
(since 2026-11-11): commit specs and tickets together with the work they describe.

## Conventions

- Feature spec: `.scratch/<feature-slug>/spec.md`. The spec is the plan: scope, tickets,
  gates, progress and open questions live there. Do not add files to `docs/plans/`.
- Execution prompts and acceptance scripts for the feature live in the same directory.
- Tickets: `.scratch/<feature-slug>/issues/<NN>-<slug>.md`.
  Start numbering at `01`; use one file per ticket.
- Record triage state near the top as `Status: <value>`.
  Use the vocabulary in [triage-labels.md](triage-labels.md).
- Append discussion under `## Comments`.
- Write human-facing specs, tickets, and comments in Simplified Chinese.

A feature directory is editable while the work is in progress. Once its spec is
`resolved` (or stopped), the whole directory is frozen evidence: do not rewrite, rename
or reformat it; follow-up work gets a new `<feature-slug>`.

The same privacy rules as the rest of the repository apply: no secrets, recordings,
transcripts or subtitle text beyond short inline examples.

Existing accepted specifications in `docs/specs/` remain authoritative
for their scope. Link to them from feature specs instead of duplicating
requirements. Record accepted durable changes in the relevant project docs.

## Skill operations

- Publish to the issue tracker: create the corresponding local Markdown file.
- Fetch a ticket: read its referenced file. Resolve a numeric ticket ID
  within its feature directory; ask for scope when ambiguous.

## Wayfinding operations

- Map: `.scratch/<feature-slug>/map.md`, containing Notes,
  Decisions-so-far, and Fog.
- Child tickets: use the ticket paths above and record
  `Type: research|prototype|grilling|task`.
- Blocking: record `Blocked by: NN, NN`; a ticket is unblocked
  when every listed blocker is resolved.
- Frontier: select the first numbered unblocked, unclaimed ticket
  whose status is `ready-for-agent`.
- Claim: save `Status: claimed` before starting work.
- Resolve: append the answer under `## Answer`, set `Status: resolved`,
  and add a summary and relative link to the map's Decisions-so-far.

`claimed` and `resolved` are execution states, additional to the
five triage roles.
