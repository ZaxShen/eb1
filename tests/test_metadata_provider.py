"""Tests for the per-dataset SQLite metadata layer."""

from __future__ import annotations

from pipeline.metadata.provider import SqliteDatasetProvider
from pipeline.metadata.seed_wildchat import seed


def test_seed_roundtrip_dataset_config(tmp_path):
    db = tmp_path / "metadata.db"
    seed(db)

    provider = SqliteDatasetProvider(db)
    config = provider.dataset_config()

    assert config.name == "wildchat"
    assert config.prompt_profile == "v4"
    assert config.taxonomy_mode == "open"
    assert config.role_map == {"user": "user", "assistant": "assistant"}
    assert config.accelerators == {
        "p1": False,
        "p3": False,
        "p4": False,
        "templates": False,
    }
    assert all(v is False for v in config.accelerators.values())


def test_seed_empty_taxonomy_and_rules(tmp_path):
    db = tmp_path / "metadata.db"
    seed(db)
    provider = SqliteDatasetProvider(db)

    assert provider.taxonomy("user") == []
    assert provider.taxonomy("bot") == []
    assert provider.accelerator_rules() == []
    assert provider.topic_filters() == []
    assert provider.preprocessing_rules() == []


def test_missing_db_raises(tmp_path):
    try:
        SqliteDatasetProvider(tmp_path / "nope.db")
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError for missing metadata DB")
