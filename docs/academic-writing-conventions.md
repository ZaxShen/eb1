# Academic Writing

Rules for every artifact under `docs/papers/**` — conference papers, workshop papers, technical reports, and EB-1 exhibits.

## Voice and Tone

- **Third person, past tense** for Method and Experiments ("We segmented 1,024 conversations"). First person plural is acceptable; avoid first person singular.
- **Active voice by default.** Passive is allowed where the actor is generic or irrelevant ("the embeddings were clustered"), never to hide uncertainty.
- **No marketing language.** Ban: "revolutionary," "cutting-edge," "state-of-the-art" (unless citing a benchmark SOTA), "seamless," "robust" (unless you measured robustness), "industry-leading," "next-generation," "powerful," "exciting."
- **No hedging that hides claims.** "We believe X may potentially help" → either "X improved Y by N%" (with citation) or drop the claim.
- **No rhetorical questions.** "What if we could segment conversations better?" → state the contribution directly.

## Claim-Citation Discipline

Every sentence that asserts a factual claim must fall into exactly one of these buckets:

1. **Own measurement** — backed by an inline source pointer to a file in this repo:
   - Markdown: `<!-- src: reports/2025-12-15_benchmark.md#L44 -->`
   - LaTeX: `% src: reports/2025-12-15_benchmark.md#L44`
2. **Own code behavior** — backed by an inline source pointer to a pipeline file:
   - `<!-- src: pipeline/segmentation/subtopic_validator.py#L12-L30 -->`
3. **External work** — backed by a `\cite{key}` that resolves in `docs/papers/refs.bib`.
4. **Narrative glue** — connective tissue with no factual assertion ("In this section, we describe..."). Does not need a source pointer.

If a claim does not fit 1–3, either:
- Add the source pointer / citation (preferred)
- Rewrite the claim to match the evidence you actually have
- Or flag with `[CITATION NEEDED]` — but **this marker BLOCKS pre-push review** and must be resolved before commit

## [CITATION NEEDED] Marker

Use sparingly and only while drafting. Format:

```markdown
eb1 reduced annotation time by [CITATION NEEDED: need benchmark timing row].
```

- Every marker MUST include a parenthetical hint of what would resolve it
- The PR Reviewer BLOCKs pre-push if any marker remains
- The academic-peer-reviewer MUST list every marker it finds in the review output

## Limitations Section (Mandatory)

Every paper draft and every EB-1 exhibit includes a **Limitations** section or paragraph. No exceptions.

For papers: dedicated `## Limitations` section, at least 3 concrete limitations with honest framing.

For EB-1 exhibits: a **Scope** paragraph at the end naming what the evidence does NOT prove.

"None that we could identify" is never an acceptable Limitations section.

## Numbers

- Report with consistent precision (e.g., "93.4%" throughout, not alternating between "93%" and "93.42%").
- Always include units ("12.3 seconds", not "12.3").
- Confidence intervals or standard deviations when the number is the headline claim.
- Never round up a number to cross a threshold ("94.9%" reported as "95%" — don't).

## Forbidden Constructions

| Instead of… | Write… |
|---|---|
| "significantly improved" (without stat test) | "improved by N%" with test + p-value |
| "performs well" | "achieved F1 of X" |
| "a lot of" / "many" | the actual number |
| "obviously" / "clearly" | remove the word, the claim stands on its own |
| "our novel approach" | describe the approach; let the reader judge novelty |

## Cross-Reference Hygiene

- Figures, tables, sections always referenced by label (`\ref{fig:pipeline}`, `[Section 3](#method)`).
- No "the figure below" — the reviewer may be reading on a different layout.
- Every figure and table gets a caption that is self-contained (readable without the paragraph that references it).
