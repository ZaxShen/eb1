"""Google SSO for the annotation backend — env-gated, server-side verification.

SSO is **on** only when ``GOOGLE_CLIENT_ID`` is set in the environment. When it
is unset the backend runs in today's no-auth manual mode (local dev), and
``require_identity`` resolves to ``None``.

When on, every ``/api/datasets/...`` endpoint requires an ``Authorization:
Bearer <id_token>`` header. The ID token is verified server-side against
Google's public keys with ``GOOGLE_CLIENT_ID`` as the audience; the verified
identity's name becomes ``reviewed_by``. Only the public Client ID is used — no
client secret.

``_verify_oauth2_token`` is module-level so tests can monkeypatch it without
hitting the network.
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException
from google.auth.exceptions import GoogleAuthError
from pydantic import BaseModel


class Identity(BaseModel):
    """A verified Google identity extracted from an ID token."""

    name: str
    email: str
    sub: str


def sso_enabled() -> bool:
    """True when ``GOOGLE_CLIENT_ID`` is configured (SSO required)."""
    return bool(os.environ.get("GOOGLE_CLIENT_ID"))


def _verify_oauth2_token(token: str, audience: str) -> dict:
    """Verify a Google ID token against the public keys. Monkeypatched in tests.

    The transport import is deferred so the module loads (and tests that stub
    this function run) without the optional ``requests`` HTTP dependency.
    """
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    return google_id_token.verify_oauth2_token(
        token, google_requests.Request(), audience
    )


def verify_bearer(authorization: str | None) -> Identity:
    """Verify a ``Bearer`` ID token and return the identity. 401 on missing/invalid."""
    audience = os.environ.get("GOOGLE_CLIENT_ID")
    if not audience:
        raise HTTPException(status_code=401, detail="SSO not configured")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization[len("bearer ") :].strip()
    try:
        claims = _verify_oauth2_token(token, audience)
    except (GoogleAuthError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    return Identity(
        name=claims.get("name") or claims.get("email") or claims.get("sub", ""),
        email=claims.get("email", ""),
        sub=claims.get("sub", ""),
    )


def require_identity(authorization: str | None = Header(default=None)) -> Identity | None:
    """FastAPI dependency: ``None`` when SSO off, else the verified identity (401)."""
    if not sso_enabled():
        return None
    return verify_bearer(authorization)
