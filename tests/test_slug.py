"""Pure unit tests for ``annotation.backend.slug.slugify`` (no DB, no network)."""

from __future__ import annotations

import pytest

from annotation.backend.slug import slugify


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Veterans Affairs", "veterans_affairs"),
        ("Disability & Retirement Benefits", "disability_retirement_benefits"),
        ("Vehicle Registration & ID", "vehicle_registration_id"),
        ("UPPER CASE", "upper_case"),
        ("  leading/trailing  ", "leading_trailing"),
        ("multiple   spaces", "multiple_spaces"),
        ("punctuation!!!heavy???", "punctuation_heavy"),
        ("already_snake_case", "already_snake_case"),
    ],
)
def test_slugify_examples(label, expected):
    assert slugify(label) == expected


def test_slugify_collapses_unicode_dashes():
    assert slugify("Appeals — Hearings") == "appeals_hearings"
    assert slugify("en–dash") == "en_dash"


def test_slugify_collapses_runs_and_strips_edges():
    assert slugify("__Foo -- Bar__") == "foo_bar"


@pytest.mark.parametrize("label", ["", "   ", "&&&", "—–", "!!!"])
def test_slugify_empty_raises(label):
    with pytest.raises(ValueError):
        slugify(label)


@pytest.mark.parametrize(
    "label",
    ["Veterans Affairs", "Disability & Retirement Benefits", "Vehicle Registration & ID"],
)
def test_slugify_idempotent(label):
    once = slugify(label)
    assert slugify(once) == once
