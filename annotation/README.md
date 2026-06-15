# UFL Annotation Site

A trimmed data-annotation web app for **user/conversation-level** review of UFL
machine segments: browse conversations, read each one's full chat stream with
all its segments overlaid inline, relabel topics/subtopics, and edit boundaries
(split / merge → gold spans). Without Redis / RabbitMQ / Mongo / Postgres and
without auth.

- **`backend/`** — FastAPI + per-dataset SQLite gold store. Reads machine
  segments from `datasets/<name>/output.db`, taxonomy from the metadata
  provider, and writes human gold (corrected topic/subtopic + boundaries).
- **`frontend/`** — React + Vite + TypeScript + Tailwind: a resizable
  **conversation queue** | the selected conversation's **full color-by-role chat
  stream with all segments as inline labeled dividers** + boundary split/merge |
  a Stats / Annotation / Fields right rail acting on the selected segment.

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
