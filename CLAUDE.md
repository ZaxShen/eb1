# eb1 — Research + Paper Workspace for eb1

## What This Project Is

A Python-only research offshoot of the eb1 pipeline. Its **core goal** is a **conference / workshop paper** about the eb1 method — currently targeting **NLP4ConvAI 2026** (October submission) on eb1-as-LLM-memory-system under long-context topic drift; segmentation F1 is instrumental, memory-task accuracy is the headline.

Secondary: **internal technical reports** — short pieces explaining parts of the pipeline for stakeholders, produced on request.

The underlying pipeline (`pipeline/`, `db/`, `config/`, `tests/`) is a **frozen snapshot of eb1**. Code here exists as evidence — it gets read, described, and cited, not actively re-developed. Source edits are reserved for the rare case where a paper claim requires a fresh measurement script.

## Reference Docs

| Topic | File |
|---|---|
| What eb1 is, architecture, schema, commands | `docs/project-domain.md` |
| Paper-track decision log (venues, scope, reframes) | `docs/papers/ACADEMIC_LOG.md` |
| Pending dataset verification (WildChat / LMSYS / SuperDialseg) | `docs/papers/datasets-to-review.md` |
| Roundtable transcripts | `docs/papers/roundtables/` |
| Paper draft (anonymous ACL) | `docs/papers/drafts/cmlu-acl-2026-04-21.pdf` |
| Academic writing + citation + integrity rules | `docs/academic-writing-conventions.md`, `docs/citation-conventions.md`, `docs/academic-integrity.md` |
| Paper structure + drafting + peer-review checklists | `docs/paper-structure.md`, `docs/paper-drafting-checklist.md`, `docs/peer-review-checklist.md` |
| LaTeX build | `docs/latex-build.md` |
| eb1 benefits / paper seed material | `docs/eb1_BENEFITS.md` |
| eb1 ERD / schemas / graders / taxonomy | `docs/erd.md`, `docs/schemas.md`, `docs/GRADERS.md`, `docs/user_taxonomy.md` |
| eb1 design history + benchmark proposals | `docs/notion/Versions ...md`, `docs/pipeline-improvement-proposals.md` |
| Downstream consumer (Dynamic User Profile) | `docs/dynamic-user-profile.md` |
| LLM benchmark pricing (2026-03-17) | `docs/llm-benchmark-pricing.md` |
| BERTopic per-domain baseline (setup + results) | `docs/bertopic-baseline.md` |
| Prod deployment numbers | `docs/production-deployment.md` |

## Project Structure

```
pipeline/       Python pipeline — LLM Analyzer, graders, evaluation (frozen, read-only)
db/             PostgreSQL repositories + MongoDB read-only client
config/         Pydantic settings loader (reads .env)
tests/          pytest suite (300+ tests, no DB/LLM required)
docs/           Architecture, benchmark results, ERD, grader specs, paper reference material
  papers/         Paper drafts, roundtables, ACADEMIC log, refs.bib
  notion/         Notion-exported working docs
  architecture/   Pipeline flowcharts
  eb1_BENEFITS.md What eb1 delivers (paper/exhibit seed material)
reports/        Benchmark evaluation logs from prior runs
```

## Code Style

- Code should be self-documenting. Avoid unnecessary comments.
- Use emoji-prefixed commit messages (Conventional Commits style).

## Verification Commands

```bash
uv run ruff check pipeline/ db/ tests/
uv run pytest tests/ -v
```

## Workflow

Single-operator workspace using the tmb Claude Code plugin. No local agent hierarchy — tmb provides planning, roundtable, SWE-via-worktree, scan, monitor, review.

## Phase Status

**Research + writing phase.** eb1 pipeline frozen; eb1 consumes it as evidence.

| Track | Status | Next |
|---|---|---|
| Conference paper (NLP4ConvAI 2026, Oct submission) | Active — core | Founder verifies dataset shortlist (`docs/papers/datasets-to-review.md`); freeze primary corpus (WildChat vs LMSYS-Chat-1M) |
| Technical reports | Ad-hoc | On Founder request |
