# Citation Practice

One shared reference database: `docs/papers/refs.bib`. Every paper and every EB-1 exhibit pulls from this file. Duplicate entries are a review BLOCK.

## Key Format

`firstauthor_year_slug` — all lowercase, underscore-separated.

| Source | Key example |
|---|---|
| Devlin et al. 2019, BERT | `devlin_2019_bert` |
| Reimers & Gurevych 2019, SBERT | `reimers_2019_sbert` |
| McInnes et al. 2017, HDBSCAN | `mcinnes_2017_hdbscan` |
| Smith 2024, "eb1: Segmentation..." | `smith_2024_eb1_segmentation` |

Rules:
- **First author's last name only.** No initials. ASCII only (transliterate non-ASCII names).
- **Year is the publication year**, not the arXiv submission year if different.
- **Slug is 1–3 words** from the title, meaningful, not generic ("paper", "method").
- **If two papers by the same first author in the same year**, disambiguate with `firstauthor_yearA_slug`, `firstauthor_yearB_slug`.

## Required Fields

Every entry must include:

```bibtex
@inproceedings{firstauthor_year_slug,
  author    = {Last, First and Last, First and ...},
  title     = {Exact Title of the Paper},
  booktitle = {Proceedings of ...},
  year      = {YYYY},
  url       = {https://...},
  pages     = {N--M},           % optional but preferred
  doi       = {10.xxxx/yyyy},   % if available
}
```

For journals use `@article` with `journal`, `volume`, `number`. For arXiv preprints use `@misc` with `howpublished = {arXiv:2401.12345}`.

## Verification (Mandatory Before Committing an Entry)

Every new entry MUST be verified via WebFetch against one of:

- arXiv abstract page (`https://arxiv.org/abs/XXXX.XXXXX`)
- DOI resolver (`https://doi.org/...`)
- ACL Anthology (`https://aclanthology.org/...`)
- Venue proceedings page

The WebFetch must confirm the title, year, and at minimum the first author. Paste the verification URL into the `url` field.

**A commit that adds a `\cite{key}` without a corresponding verified `refs.bib` entry is a pre-push BLOCK.**

## Allowed Citation Sources

- Peer-reviewed venues (conferences, journals, workshops)
- arXiv preprints (when no peer-reviewed version exists — flag as preprint in text if the claim is load-bearing)
- Government / regulatory documents (USCIS, 8 CFR, NIST)
- Books and book chapters
- **NOT allowed as a citation:** blog posts, tweets, Medium articles, LLM chat logs, corporate marketing pages. These can be mentioned in-text with a footnote URL but never wrapped in `\cite{}`.

## In-Text Citation Style

Default to the venue's style; if unknown, use natbib-style:

- `\citet{devlin_2019_bert}` — "Devlin et al. (2019) propose..."
- `\citep{devlin_2019_bert}` — "...pretrained transformers (Devlin et al., 2019)"
- `\citep{a, b, c}` — multi-citation

For Markdown drafts, use the LaTeX form inline (the pandoc pipeline will render it at build time).

## Citation Load

- Related Work: aim for 20–40 citations for a full paper, 8–15 for a workshop paper.
- Method and Experiments: cite only when the technique is not the paper's own contribution.
- Introduction: 5–10 citations to frame the problem and position the contribution.

## refs.bib Organization

- Alphabetical by citation key — makes deduplication obvious.
- One entry per paper, even if cited from multiple drafts.
- Comments allowed above an entry for disambiguation: `% Not to be confused with Smith 2024b`.
- No orphan entries (entries not cited by any paper) — remove them during peer review.
