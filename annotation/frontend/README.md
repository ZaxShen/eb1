# UFL Annotation — Frontend

React + Vite + TypeScript + Tailwind UI for reviewing machine segments,
relabeling topics/subtopics, and editing segment boundaries (split / merge).
It consumes the FastAPI backend in `../backend` through the Vite dev proxy
(`/api` → `http://localhost:8000`).

## Layout

Three panels, mirroring ufl-dev's annotation UX:

- **SegmentQueue** (left) — filterable review queue (status, topic, max
  confidence). Click a segment to load it.
- **ConversationView** (center) — the full message thread with the selected
  segment highlighted. Per-span controls **split here** (start a new span at a
  message) and **merge prev** (combine adjacent spans) `POST` to `/boundaries`.
- **AnnotationPanel** (right) — topic + subtopic selects (subtopic list depends
  on the chosen topic, sourced from `/taxonomy`), **Confirm AI label**, **Save**
  (`POST /annotate`), and an optional free-text reviewer-name field.

A **StatsBar** across the top shows reviewed / unreviewed and per-topic counts.

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Save the current label |
| `Space` | Confirm the AI label as-is |
| `←` / `→` | Previous / next segment in the queue |

(Shortcuts are ignored while typing in an input or select.)

## One-command dev

Run the backend and the frontend in two terminals.

**Terminal 1 — backend** (from the repo root):

```bash
uv run uvicorn annotation.backend.app:app --port 8000 --reload
```

**Terminal 2 — frontend** (from this directory):

```bash
npm install   # first time only
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api` to the backend on
port 8000, so no CORS or extra config is needed.

## Build

```bash
npm ci
npm run build   # tsc -b && vite build → dist/
```
