# Academic Integrity

Hard rules for every file under `docs/papers/**`. Violations BLOCK pre-push review.

## No Fabrication

- **No fabricated numbers.** Every numeric claim in prose MUST be backed by an artifact in the repo: a file in `reports/`, `docs/`, or `pipeline/`, cited inline.
- **No fabricated citations.** Every `\cite{key}` MUST resolve to a verified entry in `docs/papers/refs.bib`. Every entry was verified via WebFetch (see `.claude/skills/citation-practice.md`).
- **No fabricated methodology.** The Method section must describe what the code does, not what we wish it did. If the description diverges from the code, rewrite the description or open a task XML to align the code (via SWE).

## Inline Source Pointers (Mandatory)

Every factual claim includes an inline pointer to its source:

- **Markdown**: `<!-- src: path/to/evidence.md#LNN -->` (placed at end of sentence or paragraph)
- **LaTeX**: `% src: path/to/evidence.md#LNN` (placed on the line above the claim)

The `path` is repo-relative. The `#LNN` anchor is optional but strongly preferred for pointing to a specific line number or markdown section.

**External claims** use `\cite{}` and need no inline pointer — the citation IS the source. Inline pointers are for own-work claims (measurements, code behavior, benchmark results).

## [CITATION NEEDED] Marker

- Use only while drafting.
- Format: `[CITATION NEEDED: <what would resolve this>]`
- **BLOCK rule**: any commit to `main` containing this marker is rejected at pre-push by the PR Reviewer.

## Authorship

- Only the `academic-paper-writer` agent may create or edit files under `docs/papers/**`.
- Reviews in `docs/papers/<slug>/reviews/` may only be written by `academic-peer-reviewer`.
- If any other agent (Architect, SWE, CEO, CTO, Secretary) touches `docs/papers/**`, the PR Reviewer BLOCKs with `papers_direct_edit_violation` (Critical).

## Scope Discipline

- Do not overclaim contributions. "We propose X" is a strong statement; back it with a novelty argument and prior-work citations.
- Limitations sections are **mandatory** and must contain ≥ 3 concrete, honest limitations. "None" is not acceptable.
- EB-1 exhibits include a **Scope** paragraph naming what the evidence does NOT prove.

## Review Trigger

When a commit touches `docs/papers/**` with content changes (not just formatting):
- PR Reviewer loads `.claude/skills/academic-writing.md`, `.claude/skills/citation-practice.md`, `.claude/skills/peer-review.md`.
- PR Reviewer spawn-requests `academic-peer-reviewer` on any draft-section addition or rewrite.
- Commit cannot proceed until peer review verdict ≥ WEAK_ACCEPT OR Founder explicitly overrides.
