# UFL Annotation Site

A trimmed data-annotation web app for reviewing and relabeling UFL machine
segments and editing their boundaries (split / merge → gold spans). Modeled on
ufl-dev's `docker-topic-annotation` 3-panel UX, but without Redis / RabbitMQ /
Mongo / Postgres and without auth.

- **`backend/`** — FastAPI + per-dataset SQLite gold store. Reads machine
  segments from `datasets/<name>/output.db`, taxonomy from the metadata
  provider, and writes human gold (corrected topic/subtopic + boundaries).
- **`frontend/`** — React + Vite + TypeScript + Tailwind, a faithful rebuild of
  ufl-dev's 3-column TopicAnnotation UI: resizable queue | color-by-role chat
  thread with labeled segment dividers + boundary split/merge | a Stats /
  Annotation / Fields right rail.

## One-command dev

Two terminals from the repo root:

```bash
# Terminal 1 — backend
uv run uvicorn annotation.backend.app:app --port 8000 --reload

# Terminal 2 — frontend
cd annotation/frontend && npm install && npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend
on port 8000.

See `frontend/README.md` for panel details and keyboard shortcuts.
