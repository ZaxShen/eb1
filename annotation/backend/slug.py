"""Canonical topic/subtopic slug normalization for annotator-facing labels.

Every topic/subtopic the annotation site stores is normalized to SQL-slug style:
lowercase ``snake_case`` with runs of non-alphanumeric characters collapsed to a
single underscore. This keeps free-typed and picked labels from fragmenting the
taxonomy (e.g. "Veterans Affairs", "veterans affairs" and "Veterans-Affairs" all
resolve to ``veterans_affairs``), which matters for inter-annotator agreement.

Pure standard library and dependency-free on purpose: the taxonomy loader
(``annotation.load_taxonomy``) and the backend save/create/rename write paths
share this one helper so the canonical form is defined in exactly one place.
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(label: str) -> str:
    """Normalize ``label`` to lowercase ``snake_case``.

    Lowercases, collapses every run of non-alphanumeric characters (spaces,
    punctuation, ``&``, ``/``, unicode dashes, …) to a single underscore, and
    strips leading/trailing underscores::

        slugify("Veterans Affairs")                 -> "veterans_affairs"
        slugify("Disability & Retirement Benefits") -> "disability_retirement_benefits"

    Idempotent: ``slugify(slugify(x)) == slugify(x)``. Raises ``ValueError`` when
    the input has no alphanumeric content (normalizes to the empty string).
    """
    slug = _NON_ALNUM.sub("_", label.lower()).strip("_")
    if not slug:
        raise ValueError(f"label {label!r} normalizes to an empty slug")
    return slug
