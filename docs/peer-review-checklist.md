# Peer Review Protocol

The academic-peer-reviewer reads a draft, runs the checks below, and writes a review file. The reviewer NEVER edits the draft itself.

## Inputs

- Target draft: `docs/papers/<slug>/paper.md` (and `paper.tex` if present)
- Shared references: `docs/papers/refs.bib`
- Code the paper cites: `pipeline/`, `db/`, `reports/`
- Any prior reviews: `docs/papers/<slug>/reviews/`

## Output

Write a review file at:

```
docs/papers/<slug>/reviews/<YYYY-MM-DD>_<slug>.md
```

Use today's date (absolute date, not relative). If a review from today already exists, append `_v2`, `_v3`, etc.

## Review Structure (mandatory sections)

```markdown
# Peer Review — <slug> — <YYYY-MM-DD>

**Reviewer:** academic-peer-reviewer
**Draft SHA:** <git rev-parse HEAD:docs/papers/<slug>/paper.md>
**Target venue:** <from the draft's notes/ or INDEX>
**Overall verdict:** STRONG_REJECT | REJECT | WEAK_REJECT | WEAK_ACCEPT | ACCEPT

## Summary

<3–5 sentences: what the paper claims, what evidence it offers, what the
reviewer's main concern is.>

## Checks

### 1. Contribution clarity

<Is the contribution list specific and verifiable? Does the abstract match it?>

### 2. Citation resolution

<Every \cite{} in the draft was checked against refs.bib. List unresolved
citations here. Also list refs.bib entries that no draft cites (orphans).>

- UNRESOLVED: `\cite{foo_2024_bar}` on line 123 — key missing from refs.bib
- ORPHAN: `smith_2022_old` — no longer cited

### 3. Numeric claim sourcing

<Every numeric claim must have an inline src: pointer. List violations.>

- LINE 42: "reduced annotation time by 30%" — no src: pointer
- LINE 87: "F1 of 0.834" — src: points to reports/... but file does not contain that number

### 4. [CITATION NEEDED] markers

<List every occurrence. If > 0, the draft is NOT ready for pre-push.>

### 5. Method reproducibility

<Could an external reader re-run the method from the description alone?
Flag ambiguities: undefined symbols, unstated hyperparameters, missing
dataset details.>

### 6. Statistical validity

<For every comparative claim ("X outperforms Y"): is there a test? A CI? An
effect size? Are baselines fair?>

### 7. Limitations honesty

<Does the Limitations section acknowledge real limitations, or is it a
strawman list? "We only evaluated on English" is real; "More data would
help" is filler.>

### 8. Venue fit

<Does the paper match the target venue's scope, page budget, anonymization,
and expected rigor?>

### 9. Ethics and harm

<Any privacy, consent, or dual-use concerns? Is user data handled with care?
(eb1's eb1 pipeline processes user feedback — privacy framing is load-bearing.)>

### 10. Prose quality

<No marketing language; imperative / declarative tone; figures have
self-contained captions; cross-references by label.>

## Action Items (ordered by severity)

1. **BLOCK** — <description, file:line, what would resolve it>
2. **MAJOR** — <description>
3. **MINOR** — <description>

## Suggested revisions (not mandatory)

<Ideas that would strengthen the paper but don't block acceptance.>
```

## Severity Definitions

- **BLOCK** — the draft cannot be pushed to main or submitted in its current form. Unresolved `\cite{}`, `[CITATION NEEDED]` markers, unsourced numeric claims, overclaimed contributions, factually wrong Method description, missing Limitations.
- **MAJOR** — the paper would likely be rejected in external review if submitted today. Weak baselines, insufficient statistical evidence, unclear contribution, Related Work gaps.
- **MINOR** — prose, figure quality, citation-count, specific phrasing.

## Verdict Calibration

- STRONG_REJECT — fundamental methodological flaw, or the contribution does not exist as claimed.
- REJECT — significant BLOCK findings; major rewrite needed.
- WEAK_REJECT — MAJOR findings that could be addressed with ~1–2 weeks of work.
- WEAK_ACCEPT — no BLOCKs; a few MAJORs that can be resolved in revision.
- ACCEPT — no BLOCKs, no MAJORs; MINOR issues only.

## After Writing the Review

Append a one-line summary to `bro/ACADEMIC.md` under today's date:

```
- <YYYY-MM-DD> Peer review: <slug> — <verdict>. <n> blocks, <n> majors. Review: docs/papers/<slug>/reviews/<YYYY-MM-DD>_<slug>.md
```

The review is now on record. The paper-writer reads it and revises; the cycle repeats until verdict ≥ WEAK_ACCEPT.
