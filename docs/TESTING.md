# Testing

The annotation app is tested as a **trophy**: a lot of fast unit tests, a solid
band of component + contract tests, and a thin top of end-to-end flows. Each
layer catches a different class of bug; together they catch the cross-stack
integration bugs (frontend rendering the wrong backend field) that any single
layer misses.

## The layers

| Layer | Where | Runs | Catches |
|---|---|---|---|
| **Static** | TypeScript (`tsc -b`), `ruff` | `npm run build`, `uv run ruff check` | type errors, dead imports, lint |
| **Backend unit** | `tests/` (pytest) | `uv run pytest tests/` | route logic, seeding, segmentation/eval math |
| **Frontend unit** | `src/**/*.test.ts(x)` (vitest) | `npm run test` | client logic: boundary math, history, api client, auth |
| **Component (MSW)** | `src/**/*.test.tsx` via `renderWithProviders` + MSW | `npm run test` | real components rendering *realistic* `/api` responses — wrong-field / shape bugs |
| **Contract (OpenAPI → TS)** | `scripts/gen-types.mjs` → `src/api/schema.d.ts` | `npm run types:check` | frontend/backend **field drift** (rename a backend field → fails) |
| **E2E (Playwright)** | `annotation/frontend/e2e/` | `npm run test:e2e` | the whole stack in a real browser against a seeded SQLite fixture |

The component and contract layers exist specifically because a backend field
rename used to slip through: a unit test mocks its own data (so it agrees with
itself), and E2E is slow to run on every change. MSW component tests render the
**real** component against a realistic payload, and the contract layer makes a
renamed backend field a compile error (`tsc`) **and** a `types:check` failure.

## Running each layer

```bash
# backend unit
uv run pytest tests/ -q

# frontend unit + component (MSW)
cd annotation/frontend && npm run test

# contract — regenerate types from the live FastAPI schema, fail on drift
cd annotation/frontend && npm run types:gen     # write openapi.json + schema.d.ts
cd annotation/frontend && npm run types:check   # regen + git diff --exit-code

# e2e (needs a browser once)
cd annotation/frontend && npx playwright install chromium
cd annotation/frontend && npm run test:e2e

# everything, fail-fast, one command (from the repo root)
bash scripts/test-all.sh
```

Run `scripts/test-all.sh` locally before pushing. (CI is deferred for now — wire `.github/workflows/` to call the same script when you want it.)

## Frontend-vs-backend bisection

When something is wrong on screen, localize it before you fix it:

1. **Reproduce in E2E.** Add (or run) a Playwright spec that drives the flow.
   If it reproduces, you have a deterministic repro against the seeded fixture.
2. **Curl the API directly** for the same data the UI requested. With the E2E
   backend up (port 8200), e.g.:

   ```bash
   curl -s localhost:8200/api/datasets/wildchat/conversations/<id> | jq .
   ```

3. **Localize:**
   - **API response is correct, screen is wrong → frontend bug.** Reproduce it
     cheaply at the **component (MSW)** layer: feed the component the correct
     payload and assert the render. Fix the component, lock it with that test.
   - **API response is wrong → backend bug.** Reproduce it at the **pytest**
     layer against the seeded fixture. Fix the route/model, lock it with that
     test. If a field changed shape, run `npm run types:gen` so the contract
     reflects it.

This is the loop that turns "the segments look wrong" into "the `/conversations`
response is right but `ConversationStream` reads `gold_segments` where it should
read `segments`" — a one-line component test, not a stack-wide hunt.

## Per-feature checklist

**New UI operation** (button, panel, interaction):

- [ ] **Unit** — pure logic (boundary math, state reducers) in a `*.test.ts`.
- [ ] **Component (MSW)** — render the component via `renderWithProviders`
      against a realistic handler in `src/test/msw/handlers.ts`; assert the
      rendered output matches the response. Add/extend a handler if the op hits
      a new endpoint.
- [ ] **E2E** — one Playwright flow in `e2e/specs/` driving the operation
      through the real stack (add a page-object method in `e2e/pages/` first).

**New backend endpoint** (or changed response shape):

- [ ] **pytest** — a `tests/` test for the route against the seeded fixture.
- [ ] **Regenerate types** — `npm run types:gen`, commit the updated
      `annotation/backend/openapi.json` + `src/api/schema.d.ts`. `types:check`
      then fails for anyone whose frontend types drift from the schema.
- [ ] If the frontend consumes it, add an MSW handler + a component test.

Keep every committed test **GREEN against current behavior**. A flow that is
known-broken gets its test in the increment that fixes it, not before.
