# UFL Annotation — Frontend

React + Vite + TypeScript + Tailwind UI for reviewing machine segments,
relabeling topics/subtopics, and editing segment boundaries (split / merge).
It consumes the FastAPI backend in `../backend` through the Vite dev proxy
(`/api` → `http://localhost:8000`).

## Layout

A full-height **3-column resizable** frame (via `react-resizable-panels`), each
column a rounded-xl card, faithfully matching ufl-dev's TopicAnnotation UX. A
slim topbar carries the **dataset picker** and a light/dark theme toggle.

- **SegmentQueue** (left, ~22%) — filterable review queue (review status, topic,
  max-confidence slider) of **segment cards**: avatar + conversation label +
  **color-coded topic / subtopic / sentiment badges** + confidence. The selected
  card is highlighted.
- **SegmentMessages** (center, ~50%) — a chat thread with **bubbles colored by
  role** (assistant=emerald, user=neutral, automated=amber, team=sky). The
  selected segment is delimited by a **divider carrying its topic/subtopic/
  sentiment badges**; the conversation's other segments render as muted,
  clickable context. **Boundary controls**: per-message **split here** and a
  per-segment **merge with previous**, both `POST` to `/boundaries` (REPLACE
  semantics).
- **Right rail** (~28%) — a vertical stack of three cards:
  - **StatisticsPanel** — total / reviewed / unreviewed badges (clickable
    filters) + per-topic mini-bars (`/stats`).
  - **AnnotationPanel** — topic + subtopic selects (subtopic list depends on the
    chosen topic, sourced from `/taxonomy`), **Confirm AI** (copies the predicted
    label into the form), **Save** (`POST /annotate`), Prev/Next chevrons, and an
    optional reviewer-name input.
  - **SegmentFieldsPanel** — read-only list of every segment field (id,
    conversation, chunk_index, message_indices, topic, subtopic, sentiment,
    label_confidence, summary, reviewed).

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Save the current label (`POST /annotate`) |
| `Space` | Confirm the AI label (copies it into the form) |
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
