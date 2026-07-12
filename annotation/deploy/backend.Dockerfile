# FastAPI backend image for the annotation site.
#
# Build context is the REPO ROOT (the image ships the `annotation` package):
#
#   docker build -f annotation/deploy/backend.Dockerfile -t eb1-annotation-backend .
#
# The root pyproject.toml pins the whole eb1 research stack (torch, hdbscan,
# umap, sentence-transformers, ...) as core deps for the frozen pipeline. The
# annotation backend imports none of them, so this image installs only the
# backend's actual runtime dependencies with uv — keeping it small and
# compiler-free. `requests` is included because real Google SSO verification
# uses `google.auth.transport.requests` at runtime.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN uv venv "$VIRTUAL_ENV" \
    && uv pip install \
        "fastapi>=0.137.0" \
        "uvicorn>=0.49.0" \
        "psycopg[binary]>=3.1" \
        "psycopg-pool>=3.1" \
        "pydantic>=2.0" \
        "google-auth>=2.54.0" \
        "requests>=2.32"

# Application source (the annotation package).
COPY annotation ./annotation

EXPOSE 8000
CMD ["uvicorn", "annotation.backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
