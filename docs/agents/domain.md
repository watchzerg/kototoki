# Domain docs

This repository uses a single domain context.

## Read relevant context

- Canonical glossary: `docs/glossary/GLOSSARY.md`.
- Technical decisions: relevant ADRs under `docs/adr/`.
- Document routing and conventions: `docs/INDEX.md`.

If the glossary is absent, proceed silently. Create it only when
domain terms are resolved. Existing ADRs remain in their current location.

When a skill refers to the root `GLOSSARY.md`, use
`docs/glossary/GLOSSARY.md` in this repository.

## Vocabulary and decisions

Use established glossary terms when naming domain concepts in tickets,
code, tests, and proposals. Identify unresolved terminology for
domain modeling.

Surface conflicts with relevant ADRs explicitly, naming the decision
and explaining why reconsideration is proposed. Distinguish proposals
from adopted decisions.
