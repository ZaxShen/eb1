# eb1 Annotation Site

A data-annotation web app for **user/conversation-level** review of eb1 machine
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

## Ingesting the full datasets

`annotation.ingest.run` streams a full corpus into the Postgres store. Each
conversation lands as its messages **plus exactly one whole-conversation
`source='predicted'` segment** spanning every message index (topic `NULL`) — the
seed annotators segment from. SuperDialseg additionally writes its gold
`segment_id` boundaries as `source='gold'` segments. The run is **batched,
idempotent** (`UNIQUE(dataset, ext_id)` upsert; already-loaded conversations are
skipped) and **resumable** (re-run to continue after an interruption); progress
prints every batch.

```bash
docker compose -f annotation/docker-compose.yml up -d
export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation

# WildChat — UNGATED, no token needed. --limit for a quick smoke test.
python -m annotation.ingest.run --dataset wildchat --limit 50
python -m annotation.ingest.run --dataset wildchat            # full ~838K convs

# SuperDialseg — gold-segmented (see the Drive source below).
python -m annotation.ingest.run --dataset superdialseg

# LMSYS — GATED; requires HF_TOKEN (see below).
export HF_TOKEN=hf_xxx
python -m annotation.ingest.run --dataset lmsys
```

Flags: `--limit N` (cap conversations), `--batch N` (conversations per upsert
transaction, default 1000), `--no-skip-existing` (force re-upsert instead of
skipping already-loaded ext_ids).

| Dataset | Source | Access |
|---|---|---|
| `wildchat` | `allenai/WildChat-1M` — 14 public parquet shards over `huggingface_hub.HfFileSystem` | **Ungated** — no token |
| `lmsys` | `lmsys/lmsys-chat-1m` parquet shards over `HfFileSystem` | **Gated** — `HF_TOKEN` + accepted terms |
| `superdialseg` | Gold-segmented release (Jiang et al. 2023) on Google Drive, linked from [Coldog2333/SuperDialseg](https://github.com/Coldog2333/SuperDialseg) | Local copy via `EB1_SUPERDIALSEG_PATH`, or `gdown` from Drive |

**LMSYS (`HF_TOKEN`):** LMSYS-Chat-1M is HuggingFace-gated. (1) Accept the
dataset terms at <https://huggingface.co/datasets/lmsys/lmsys-chat-1m> with your
HuggingFace account, (2) create a read token at
<https://huggingface.co/settings/tokens>, (3) `export HF_TOKEN=hf_xxx` before the
run. The ingester raises a clear, actionable error if the token is missing or
the terms have not been accepted.

**SuperDialseg (Drive):** the gold-segmented corpus is distributed as an archive
on Google Drive (linked from the [SuperDialseg
repo](https://github.com/Coldog2333/SuperDialseg)'s "Download the dataset"
section). Download it once and point `EB1_SUPERDIALSEG_PATH` at the local copy
(the zip or its extracted directory of `*.json`/`*.jsonl` dialogues). For an
automated fetch instead, set `EB1_SUPERDIALSEG_GDRIVE_ID` to the release's Drive
file id (with `gdown` installed).

## Production deployment

To run the site on the public internet (single GCP VM, docker compose, Caddy
TLS, Google SSO with an email allowlist), see
[`deploy/RUNBOOK.md`](deploy/RUNBOOK.md). The `deploy/` directory holds the
production Dockerfiles, `docker-compose.prod.yml`, Caddy config, `.env.example`,
and the provisioning + GCS-backup scripts — all inert until the operator runs
them per the runbook.

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
