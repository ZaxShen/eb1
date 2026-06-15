# Annotation E2E (Playwright)

End-to-end tests that drive the **real** annotation stack in a real browser:

```
Chromium  ->  Vite frontend (:5273)  ->  /api proxy  ->  FastAPI backend (:8200)  ->  seeded SQLite fixture
```

This is the layer that catches cross-stack integration bugs — e.g. the frontend
rendering the wrong backend field — that unit/component layers can't see.

## Run

From `annotation/frontend`:

```bash
npm ci
npm run test:e2e:install   # one-time: downloads the Chromium browser
npm run test:e2e           # boots backend + frontend itself, then runs the specs
```

`playwright.config.ts`'s `webServer` boots everything for you:

1. **Seed** — runs `e2e/fixtures/seed_e2e.py`, rebuilding a fresh fixture tree
   under `e2e/.datasets/` (gitignored). It seeds each dataset's `metadata.db`
   (`pipeline.metadata.seed_*`) and runs `pipeline.run_dataset` with the **mock**
   analyzer (no LLM, no network) to produce deterministic `output.db` segments.
2. **Backend** — `uv run uvicorn annotation.backend.app:app --port 8200` with
   `EB1_DATASETS_DIR=e2e/.datasets`, so the backend reads ONLY the fixture and
   never touches the repo's real `datasets/`.
3. **Frontend** — `vite` dev server on the test port with `VITE_API_PORT=8200`,
   which proxies `/api` to the backend.

`reuseExistingServer` is on locally (fast reruns) and off in CI (`CI=1`).

## The seeded fixture

`e2e/fixtures/samples/*.jsonl` are tiny committed corpora (two conversations per
dataset) in each adapter's native shape. `seed_e2e.py` copies them in, seeds
metadata, and runs the mock analyzer — yielding one segment per user-engaged
chunk. Counts are stable, so specs can assert exact numbers.

Datasets built: `wildchat`, `superdialseg`.

## Adding a spec or page-object method per feature

- **Page object** (`e2e/pages/AnnotationPage.ts`) is the single source of UI
  interactions. Add the action there first (e.g. a new `splitAt`/`relabel`
  variant), preferring accessible roles + visible text over test-only
  attributes, then call it from specs. Keep actions reusable even if only one
  spec uses them yet.
- **Spec** (`e2e/specs/*.spec.ts`) — one `test.describe` per feature. Keep specs
  GREEN: only assert flows that currently work. A flow that is known-broken
  (e.g. re-segment) gets its spec in the increment that fixes it, not before.
- If a feature needs new fixture data, extend the committed `samples/*.jsonl`
  (keep them tiny and deterministic) rather than reaching for live data.
