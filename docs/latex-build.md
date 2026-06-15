# LaTeX Build Pipeline

Papers are drafted in Markdown (`paper.md`) for speed and diffability. When a venue requires LaTeX, pandoc converts to `paper.tex`, and `latexmk` or `pdflatex` produces the PDF.

## Toolchain

Required:
- `pandoc` (≥ 3.0) — Markdown → LaTeX conversion
- `latexmk` OR `pdflatex` + `bibtex` — PDF build

Install check:

```bash
pandoc --version
latexmk --version || pdflatex --version
```

If missing on macOS: `brew install pandoc basictex` (BasicTeX is ~100MB; MacTeX is the full distro at ~4GB — either works).

If the toolchain is unavailable, ship a Markdown-only draft plus a top-note explaining the build is deferred.

## Directory Layout

```
docs/papers/<slug>/
  paper.md           source Markdown draft
  paper.tex          generated LaTeX (do not hand-edit after regen)
  paper.pdf          built PDF (gitignored)
  figures/
    fig_method_pipeline.pdf
    fig_results_ablation.svg
  notes/
    venue.md         target venue, deadlines
    outline.md       drafting scratchpad
  reviews/
    2026-05-01_<slug>.md
```

`docs/papers/refs.bib` is shared across every paper.

## Pandoc Invocation (canonical)

Run from the repo root:

```bash
pandoc \
  docs/papers/<slug>/paper.md \
  --from markdown+tex_math_dollars+raw_tex+citations \
  --to latex \
  --standalone \
  --bibliography=docs/papers/refs.bib \
  --citeproc \
  --resource-path=docs/papers/<slug> \
  --output=docs/papers/<slug>/paper.tex
```

Flags:
- `--standalone` — produces a full document with `\documentclass`
- `--citeproc` — resolves `[@key]` Markdown citations into LaTeX `\cite{}`
- `--resource-path` — lets `![caption](figures/foo.pdf)` resolve relative to the slug

To target a specific venue's `.sty`:

```bash
pandoc ... \
  --template=docs/papers/<slug>/venue_template.tex \
  --variable=documentclass:acl
```

## PDF Build

```bash
cd docs/papers/<slug>
latexmk -pdf -interaction=nonstopmode paper.tex
```

Or explicit sequence if `latexmk` is unavailable:

```bash
pdflatex paper.tex
bibtex paper
pdflatex paper.tex
pdflatex paper.tex
```

(The double `pdflatex` after `bibtex` resolves forward references.)

## Figures

- **pdf / svg** for diagrams → pandoc passes through; LaTeX handles pdf natively, svg needs `inkscape` or pre-conversion.
- **png** for raster → works everywhere.
- Include in Markdown: `![Pipeline overview](figures/fig_method_pipeline.pdf){#fig:pipeline width=80%}`
- Reference in text: `[Figure @fig:pipeline](#fig:pipeline)` (pandoc-crossref style) or plain `Figure 1`.

## Common Gotchas

| Symptom | Cause | Fix |
|---|---|---|
| `\cite{}` renders as `[?]` in PDF | bibtex not re-run after adding entry | Run `bibtex paper && pdflatex paper.tex` twice |
| Figure not found | `--resource-path` missing | Add `--resource-path=docs/papers/<slug>` |
| Unicode errors (em-dash, smart quotes) | LaTeX default encoding | Add `\usepackage[utf8]{inputenc}` to template, or use `--lua-filter` to normalize |
| Math renders as literal `$x$` | Markdown extension missing | Use `--from markdown+tex_math_dollars` |
| Acronyms in `\cite{}` uppercased | pandoc citeproc quirk | Pre-escape keys in refs.bib, or use `\citeNP{key}` |
| `paper.tex` gets re-edited by hand | Workflow violation — edits get overwritten on next `pandoc` run | Edit only `paper.md`; regenerate `paper.tex`. If a venue-specific tex hack is unavoidable, isolate it in `venue_template.tex`. |

## Reproducibility

Commit both `paper.md` AND `paper.tex`. The `.tex` file is a generated artifact, but committing it lets reviewers who don't have pandoc installed still build the PDF. Add a one-line note at the top of `paper.tex`:

```latex
% Generated from paper.md via pandoc. Do not hand-edit.
```

Do NOT commit `paper.pdf` — it's in `.gitignore`. Rebuild locally.

## Verification Before Commit

1. `pandoc ... → paper.tex` runs without warnings.
2. `latexmk -pdf paper.tex` produces a PDF with zero `[?]` citation markers.
3. All figures render (open the PDF, scan each page).
4. Word count within venue budget (`pdftotext paper.pdf - | wc -w`).
