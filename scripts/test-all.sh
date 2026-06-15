#!/usr/bin/env bash
# Unified test runner: every layer of the testing trophy, fail-fast, one command.
#
#   backend unit  -> uv run pytest tests/
#   frontend unit -> npm run test         (vitest: logic + MSW component)
#   e2e           -> npm run test:e2e      (Playwright: real backend+frontend)
#   contract      -> npm run types:check   (OpenAPI -> TS, fails on drift)
#
# Non-zero exit on any failure. See docs/TESTING.md for which layer to add a
# test at. The e2e layer needs a Chromium browser:
#   (cd annotation/frontend && npx playwright install chromium)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> backend: pytest"
uv run pytest tests/ -q

echo "==> frontend: vitest (unit + MSW component)"
(cd annotation/frontend && npm run test)

echo "==> e2e: playwright"
(cd annotation/frontend && npm run test:e2e)

echo "==> contract: openapi types:check"
(cd annotation/frontend && npm run types:check)

echo "==> all green"
