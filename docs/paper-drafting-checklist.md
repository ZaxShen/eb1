# Paper Drafting

Every paper under `docs/papers/<slug>/` uses the same canonical structure. Word counts are targets — venues override, but the section order does not.

## Canonical Sections

| # | Section | Target words | Notes |
|---|---|---|---|
| 1 | Title | ≤ 12 words | Descriptive, not cute. Avoid colons unless genuinely useful. |
| 2 | Abstract | 150 words | Problem, method, key result, limitation, contribution — in that order. |
| 3 | Introduction | 600–900 | Ends with an explicit contribution list (3–5 bullets). |
| 4 | Related Work | 400–700 | Organized by theme, not by paper. Every paragraph cites ≥ 2 works. |
| 5 | Method | 800–1400 | Figures carry the structure. Every mechanism has an inline `src:` pointer to the code. |
| 6 | Experiments | 600–1200 | Includes setup, baselines, metrics, results table(s). |
| 7 | Discussion | 300–600 | What the result means, what it doesn't. |
| 8 | Limitations | 200–400 | Mandatory. At least 3 concrete limitations. |
| 9 | Conclusion | 150–250 | Recap contribution + one forward-looking sentence. No new claims. |
| 10 | References | — | All entries live in `docs/papers/refs.bib`, shared across papers. |

## Venue Overrides (consult first, then adapt)

| Venue family | Word / page budget | Anonymization | Key quirks |
|---|---|---|---|
| ACL / NAACL / EMNLP long | 8 pages + unlimited refs | Anonymous | Ethics statement required |
| ACL workshops | 4–8 pages | Usually anonymous | Lighter review, but same rigor |
| NeurIPS / ICML | 9 pages + refs + appendix | Anonymous | No reviewer appendix expectation |
| CHI | 10 pages | Anonymous | Strong emphasis on HCI contribution |
| arXiv preprint | no limit | Not anonymous | Cite-able immediately; name authors |
| Internal technical report | no limit | Not anonymous | Abbreviate Related Work; expand Method |

If the venue is unknown, draft to **ACL workshop** defaults (8 pages, anonymous) — the safest superset.

## Figures and Tables

- **One figure per mechanism, one table per experiment** is the default density. More figures dilute; fewer figures force text to do too much work.
- Source files live in `docs/papers/<slug>/figures/`. Name as `fig_<section>_<desc>.{pdf,svg,png}` per naming-conventions.
- Prefer vector (pdf/svg) for diagrams, raster (png) only for screenshots or photographs.
- Every table gets a row caption ("Mean ± std over 5 runs") and a data source pointer: `% src: reports/...`.

## Contribution List Discipline

The Introduction's contribution list is the paper's contract with the reviewer. Rules:

- 3–5 bullets (fewer = underclaim, more = scope sprawl).
- Each bullet names an artifact the reader can verify (a method, a dataset, a measurement, a theoretical result).
- No bullet says "We show X is important" — that's a motivation, not a contribution.
- No bullet says "We build a system" — name what is novel about the system.

## Drafting Order

Counter-intuitive but cheaper: draft in **6 → 5 → 4 → 7 → 8 → 3 → 2 → 1** order.

- Experiments first anchors the rest in measurable reality.
- Method follows because the experiments tell you what needs explaining.
- Related Work next — now you know what to compare against.
- Discussion and Limitations before Introduction — the intro is easier when you know the punchline.
- Abstract and Title last.

## First Draft Checklist (before requesting peer review)

- [ ] Every section has content; no `<!-- TODO -->` placeholders remain.
- [ ] Every numeric claim has a `<!-- src: -->` pointer.
- [ ] Every `\cite{}` key exists in `docs/papers/refs.bib`.
- [ ] No `[CITATION NEEDED]` markers.
- [ ] Limitations section has ≥ 3 items.
- [ ] Contribution list matches what Experiments actually measured.
- [ ] Abstract word count within 10 of target (usually 150).
- [ ] All figures render (build to PDF if LaTeX; view in Markdown preview otherwise).
