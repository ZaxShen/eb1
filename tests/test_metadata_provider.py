"""Tests for the per-dataset SQLite metadata layer."""

from __future__ import annotations

import json
import sqlite3

from pipeline.metadata.provider import SqliteDatasetProvider, init_db
from pipeline.metadata.seed_wildchat import seed


def _make_db(tmp_path, dataset):
    """Build a tiny ``datasets/<dataset>/metadata.db`` with a couple taxonomy rows."""
    db = tmp_path / "datasets" / dataset / "metadata.db"
    init_db(db)
    conn = sqlite3.connect(str(db))
    try:
        conn.executemany(
            "INSERT INTO taxonomy (kind, topic, subtopic, description) "
            "VALUES (?, ?, ?, ?)",
            [
                ("user", "db-utopic", "db-usub", "from sqlite"),
                ("bot", "db-btopic", "db-bsub", "from sqlite"),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return db


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


def test_taxonomy_json_present_loaded_and_kind_filtered(tmp_path, monkeypatch):
    db = _make_db(tmp_path, "demo")
    tax_dir = tmp_path / "config" / "taxonomy"
    tax_dir.mkdir(parents=True)
    (tax_dir / "demo.json").write_text(
        json.dumps(
            {
                "dataset": "demo",
                "kind_default": "user",
                "entries": [
                    {"kind": "user", "topic": "Cooking", "subtopic": "Baking",
                     "description": "from json"},
                    {"kind": "bot", "topic": "Refusal", "subtopic": None,
                     "description": "from json"},
                ],
            }
        ),
        encoding="utf-8",
    )
    provider = SqliteDatasetProvider(db, taxonomy_dir=tax_dir)

    def _boom(*_a, **_k):
        raise AssertionError("SQLite must not be consulted when JSON is present")

    monkeypatch.setattr(provider, "_connect", _boom)

    user = provider.taxonomy("user")
    assert user == [
        {"kind": "user", "topic": "Cooking", "subtopic": "Baking",
         "description": "from json"}
    ]
    bot = provider.taxonomy("bot")
    assert bot == [
        {"kind": "bot", "topic": "Refusal", "subtopic": None,
         "description": "from json"}
    ]


def test_taxonomy_json_absent_falls_back_to_sqlite(tmp_path):
    db = _make_db(tmp_path, "demo")
    empty_dir = tmp_path / "config" / "taxonomy"
    empty_dir.mkdir(parents=True)
    provider = SqliteDatasetProvider(db, taxonomy_dir=empty_dir)

    user = provider.taxonomy("user")
    assert len(user) == 1
    assert user[0]["topic"] == "db-utopic"
    assert user[0]["description"] == "from sqlite"
    assert provider.taxonomy("bot")[0]["topic"] == "db-btopic"


def test_taxonomy_malformed_json_falls_back_no_raise(tmp_path):
    db = _make_db(tmp_path, "demo")
    tax_dir = tmp_path / "config" / "taxonomy"
    tax_dir.mkdir(parents=True)
    (tax_dir / "demo.json").write_text("{ not valid json", encoding="utf-8")
    provider = SqliteDatasetProvider(db, taxonomy_dir=tax_dir)

    user = provider.taxonomy("user")
    assert user[0]["topic"] == "db-utopic"
