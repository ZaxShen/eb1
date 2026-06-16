# eb1 Annotation — Frontend

React + Vite + TypeScript + Tailwind UI for **user/conversation-level** review:
browse conversations, read each one's full chat stream with all its machine
segments overlaid inline, relabel topics/subtopics, and edit segment boundaries
(split / merge). It consumes the FastAPI backend in `../backend` through the
Vite dev proxy (`/api` → `http://localhost:8000`).

## Layout

A full-height **3-column resizable** frame (via `react-resizable-panels`), each
column a rounded-xl card. A slim topbar carries the **dataset picker** and a
light/dark theme toggle.

- **ConversationQueue** (left, ~22%) — filterable list (review status, topic) of
  **conversation cards**, one per conversation/user: avatar + conversation id +
  **color-coded topic badges** + message / segment counts + reviewed indicator.
  Selecting a card loads that conversation's stream. Sourced from
  `/conversations`.
- **ConversationStream** (center, ~50%) — the selected conversation's **full
  message stream** with **bubbles colored by role** (semantic role tokens) and
  **every segment overlaid inline**: each segment opens with a **labeled divider
  carrying its topic/subtopic/sentiment badges**, and clicking a segment region
  selects it for the right rail. **Boundary controls**: per-message **split
  here** and a per-segment **merge with previous**, both `POST` to `/boundaries`
  (REPLACE semantics). Sourced from `/conversations/{conv}`.
- **Right rail** (~28%) — a vertical stack of three cards, acting on the segment
  selected in the stream:
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
| `←` / `→` | Previous / next conversation in the queue |

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
