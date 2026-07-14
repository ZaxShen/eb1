"""Canonical topic/subtopic slug normalization (shared by routes + CLIs).

Every annotator-facing topic/subtopic — picked, typed, or system-loaded — is
stored as a lowercase snake_case slug so labels never fragment by casing or
punctuation (``"Veterans Affairs!"`` and ``"veterans_affairs"`` are one topic).
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(label: str) -> str:
    """Normalize a label to a lowercase snake_case slug.

    Lowercases, collapses each run of non-alphanumeric characters to a single
    underscore, and strips leading/trailing underscores. Raises ``ValueError``
    when the input is empty or slugifies to nothing (pure punctuation).
    """
    slug = _NON_ALNUM.sub("_", label.lower()).strip("_")
    if not slug:
        raise ValueError(f"label {label!r} is empty after normalization")
    return slug
