# Paper Structure

Every paper, EB-1 exhibit, and technical report under `docs/papers/` follows the same directory layout.

## Canonical Layout

```
docs/papers/
  refs.bib                        shared BibTeX database (one file for all papers)
  eb1/
    INDEX.md                      manifest: criterion → exhibit → status
    README.md                     1-page overview of the EB-1 workspace
    <criterion-slug>.md           one file per criterion drafted (e.g., original-contribution.md)
    reviews/
      <YYYY-MM-DD>_<slug>.md
    figures/
      fig_<section>_<desc>.{pdf,svg,png}
  <paper-slug>/                   one directory per paper or technical report
    paper.md                      canonical Markdown draft (source of truth)
    paper.tex                     generated from paper.md via pandoc (committed, not hand-edited)
    paper.pdf                     NOT committed (gitignored)
    figures/
      fig_<section>_<desc>.{pdf,svg,png}
    notes/
      venue.md                    target venue, deadlines, page budget
      outline.md                  drafting scratchpad
    reviews/
      <YYYY-MM-DD>_<paper-slug>.md
```

## Naming

- **Paper slugs** are `kebab-case`, descriptive, and stable: `eb1-segmentation`, `eb1-taxonomy-discovery`, `deterministic-bypasses`.
- **EB-1 exhibit slugs** match the criterion concept, not the regulation number: `original-contribution`, `authorship`, `judging`.
- **Review files** use `<YYYY-MM-DD>_<slug>.md`. Multiple reviews in one day append `_v2`, `_v3`.
- **Figure files** follow `fig_<section>_<desc>.{pdf,svg,png}` — see `.claude/rules/naming-conventions.md`.

## One Slug, One Directory

- Each paper owns exactly one directory. Do not split a paper across multiple slugs.
- Do not put two papers in the same directory, even if they share data — create two slugs and let `refs.bib` be the shared surface.

## refs.bib Is Shared, Not Per-Paper

- Every paper and every EB-1 exhibit cites from `docs/papers/refs.bib` (one file, repo-wide).
- Adding a new entry is a separate concern from drafting — verify it first (see `.claude/skills/citation-practice.md`) and commit the refs.bib change in its own commit or alongside the draft that first cites it.
- Duplicate entries (same key, or same paper under different keys) are a review BLOCK.

## New Paper / Exhibit — Minimum Scaffolding

Before drafting begins, create:

1. `docs/papers/<slug>/paper.md` with a header skeleton (Abstract, Intro, ...)
2. `docs/papers/<slug>/notes/venue.md` naming the target venue and deadline
3. `docs/papers/<slug>/reviews/` (empty directory, add a `.gitkeep`)

## What Does NOT Belong Here

- Source code (even analysis scripts) — belongs in `pipeline/` and comes through SWE.
- Raw data dumps — belongs in `reports/` or elsewhere; `docs/papers/` references them.
- Personal notes / drafts that aren't about these papers — use a scratch directory outside the repo.

## Gitignore

`paper.pdf` files are build artifacts and are excluded via `.gitignore`. Everything else under `docs/papers/<slug>/` is committed.
