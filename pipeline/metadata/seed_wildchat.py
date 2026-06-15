"""Seed ``datasets/wildchat/metadata.db`` with the WildChat dataset config.

WildChat is a two-role public corpus with no Acme-specific accelerators, so the
seed registers an open-taxonomy, accelerator-free profile: the universal data
path runs with every accelerator off and discovered topics flow to the run
output unfiltered.

Run::

    python -m pipeline.metadata.seed_wildchat
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pipeline.metadata.provider import init_db

DB_PATH = Path("datasets/wildchat/metadata.db")

ROLE_MAP = {"user": "user", "assistant": "assistant"}
ACCELERATORS = {"p1": False, "p3": False, "p4": False, "templates": False}


def seed(db_path: str | Path = DB_PATH) -> Path:
    """Build the WildChat metadata DB and return its path."""
    path = Path(db_path)
    init_db(path)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("DELETE FROM dataset")
        conn.execute(
            "INSERT INTO dataset "
            "(name, description, role_map, prompt_profile, taxonomy_mode, accelerators) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "wildchat",
                "WildChat public user-assistant conversations (open taxonomy MVP).",
                json.dumps(ROLE_MAP),
                "v4",
                "open",
                json.dumps(ACCELERATORS),
            ),
        )
        # Open taxonomy + accelerator-free: taxonomy / rule tables stay empty.
        conn.commit()
    finally:
        conn.close()
    return path


def main() -> None:
    path = seed()
    print(f"Seeded WildChat metadata -> {path}")


if __name__ == "__main__":
    main()
