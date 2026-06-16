# UFL Annotation Site

A data-annotation web app for **user/conversation-level** review of UFL machine
segments: browse conversations, read each one's full chat stream with all its
segments overlaid inline, relabel topics/subtopics, and edit boundaries
(split / merge → gold spans). Server-side paginated + searchable so it scales to
the full datasets (~1.85M conversations).

- **`backend/`** — FastAPI on **PostgreSQL** (one DB holding every dataset's
  conversations, messages, predicted seed segments, human gold, and taxonomy).
  The connection comes from `EB1_ANNOTATION_DSN`; bring the database up with
  `docker compose -f annotation/docker-compose.yml up -d`. See
  `architecture/manual/decisions/1-annotation-postgres.md`.
- **`frontend/`** — React + Vite + TypeScript + Tailwind: a resizable
  **conversation queue** | the selected conversation's **full color-by-role chat
  stream with all segments as inline labeled dividers** + boundary split/merge |
  a Stats / Annotation / Fields right rail acting on the selected segment.

## One-command dev

Two terminals from the repo root (start Postgres first):

```bash
# Once — bring up the annotation Postgres
docker compose -f annotation/docker-compose.yml up -d
export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation

# Terminal 1 — backend
uv run uvicorn annotation.backend.app:app --port 8000 --reload

# Terminal 2 — frontend
cd annotation/frontend && npm install && npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend
on port 8000.

See `frontend/README.md` for panel details and keyboard shortcuts.

## Google SSO (optional)

SSO is **env-gated**. With no Client ID configured the app runs exactly as
above — no sign-in, manual `reviewed_by`. When a Client ID is configured the app
**requires** Google sign-in, the backend **verifies** the ID token server-side,
and `reviewed_by` becomes the verified Google account name (read-only; the
client value is ignored). Only the public Client ID is used — there is **no
client secret**.

### One-time Google Cloud Console setup (operator)

1. In [Google Cloud Console](https://console.cloud.google.com/) → **APIs &
   Services → Credentials**, create an **OAuth 2.0 Client ID** of type **Web
   application**.
2. Under **Authorized JavaScript origins** add `http://localhost:5173` (and any
   deployed origin).
3. Copy the generated **Client ID** (e.g.
   `1234567890-abcdefg.apps.googleusercontent.com`). No client secret is needed.

### Enabling it

Set the **same** Client ID on both sides:

```bash
# Backend — verifies the ID token against this audience
export GOOGLE_CLIENT_ID=1234567890-abcdefg.apps.googleusercontent.com
uv run uvicorn annotation.backend.app:app --port 8000 --reload

# Frontend — Vite reads it at build/dev time (see frontend/.env.example)
cd annotation/frontend
echo 'VITE_GOOGLE_CLIENT_ID=1234567890-abcdefg.apps.googleusercontent.com' > .env.local
npm run dev
```

| Variable | Where | Effect |
|---|---|---|
| `GOOGLE_CLIENT_ID` | backend env | Audience for ID-token verification; when set, all `/api/datasets/...` endpoints require a valid `Authorization: Bearer <id_token>`. |
| `VITE_GOOGLE_CLIENT_ID` | frontend env | When set, the app is gated behind Google sign-in and sends the ID token as `Authorization: Bearer`. |

`GET /api/auth/config` (unauthenticated) reports `{"sso_enabled": <bool>}`.

> Live Google sign-in requires the operator's real Client ID and is not
> exercisable offline. The backend gate / `reviewed_by` override and the
> frontend gate / token-attach logic are covered by tests with a mocked
> verifier (`tests/test_annotation_auth.py`, `frontend/src/auth/*.test.tsx`).
