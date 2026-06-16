# Annotation E2E (Playwright)

End-to-end tests that drive the **real** annotation stack in a real browser:

```
Chromium  ->  Vite frontend (:5273)  ->  /api proxy  ->  FastAPI backend (:8200)  ->  seeded Postgres
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

1. **Postgres** — `docker compose -f annotation/docker-compose.yml up -d --wait`
   starts the `postgres:18-alpine` service on host port 5544, then
   `docker exec eb1-annotation-pg createdb -U eb1 eb1_annotation_e2e` creates the
   dedicated e2e database (idempotent — a no-op if it already exists).
2. **Seed** — runs `e2e/fixtures/seed_e2e.py`, which applies the schema and seeds
   each dataset from its committed sample (no LLM, no network): one
   whole-conversation `predicted` segment per conversation.
3. **Backend** — `uv run uvicorn annotation.backend.app:app --port 8200` with
   `EB1_ANNOTATION_DSN` pointed at that database.
4. **Frontend** — `vite` dev server on the test port with `VITE_API_PORT=8200`,
   which proxies `/api` to the backend.

> **Dedicated, reset-on-run DB.** The harness defaults `EB1_ANNOTATION_DSN` to
> `postgresql://eb1:eb1@localhost:5544/eb1_annotation_e2e` — a throwaway DB on the
> same container, **never** the production `eb1_annotation` DB. The seed RESETS it
> on every run, so it must never point at production labeling data. An explicit
> `EB1_ANNOTATION_DSN` override (to another non-prod DB) still wins.

`reuseExistingServer` is on locally (fast reruns) and off in CI (`CI=1`).

## The seeded fixture

`e2e/fixtures/samples/*.jsonl` are tiny committed corpora (two conversations per
dataset) in each adapter's native shape. `seed_e2e.py` normalizes each through
its adapter and seeds one whole-conversation segment per conversation, labeled
`mock_topic`. Counts are stable, so specs can assert exact numbers.

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
