"""Runtime loader for per-dataset SQLite metadata.

:class:`MetadataProvider` is the contract the universal pipeline reads through;
:class:`SqliteDatasetProvider` is the SQLite-backed implementation that loads a
``datasets/<name>/metadata.db`` file. Getters return plain Python structures
(dataclasses, dicts, lists) so the engine treats metadata as ordinary variables.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_TAXONOMY_DIR = Path(__file__).resolve().parents[2] / "config" / "taxonomy"


@dataclass
class DatasetConfig:
    """Loaded ``dataset`` row — the per-dataset runtime knobs.

    ``role_map`` maps corpus role labels to pipeline message types; ``accelerators``
    toggles the P1/P3/P4/template accelerators (all false → universal data path).
    """

    name: str
    description: str = ""
    role_map: dict[str, str] = field(default_factory=dict)
    prompt_profile: str = "v4"
    taxonomy_mode: str = "open"
    accelerators: dict[str, bool] = field(default_factory=dict)


@runtime_checkable
class MetadataProvider(Protocol):
    """Reads a dataset's externalized domain knobs at runtime."""

    def dataset_config(self) -> DatasetConfig:
        """Return the dataset config row as a :class:`DatasetConfig`."""
        ...

    def taxonomy(self, kind: str) -> list[dict]:
        """Return taxonomy rows for ``kind`` ("user" | "bot")."""
        ...

    def accelerator_rules(self) -> list[dict]:
        """Return all accelerator (P1/P4) rules."""
        ...

    def topic_filters(self) -> list[dict]:
        """Return all P3 topic-filter rows."""
        ...

    def preprocessing_rules(self) -> list[dict]:
        """Return all preprocessing rules."""
        ...


def init_db(db_path: str | Path) -> None:
    """Create the metadata schema in ``db_path`` (idempotent)."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


class SqliteDatasetProvider:
    """SQLite-backed :class:`MetadataProvider` for one dataset's metadata.db."""

    def __init__(
        self, db_path: str | Path, taxonomy_dir: str | Path | None = None
    ) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Metadata DB not found: {self.db_path}")
        self.taxonomy_dir = (
            Path(taxonomy_dir) if taxonomy_dir is not None else DEFAULT_TAXONOMY_DIR
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def dataset_config(self) -> DatasetConfig:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM dataset LIMIT 1").fetchone()
        finally:
            conn.close()
        if row is None:
            raise ValueError(f"No dataset row in {self.db_path}")
        return DatasetConfig(
            name=row["name"],
            description=row["description"] or "",
            role_map=json.loads(row["role_map"]) if row["role_map"] else {},
            prompt_profile=row["prompt_profile"] or "v4",
            taxonomy_mode=row["taxonomy_mode"] or "open",
            accelerators=json.loads(row["accelerators"]) if row["accelerators"] else {},
        )

    def taxonomy(self, kind: str) -> list[dict]:
        json_rows = self._load_taxonomy_json(self.db_path.parent.name, kind)
        if json_rows is not None:
            return json_rows
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM taxonomy WHERE kind = ? ORDER BY id", (kind,)
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def _load_taxonomy_json(self, dataset: str, kind: str) -> list[dict] | None:
        """Return kind-filtered entries from the exported JSON, or ``None``.

        ``None`` signals "no usable JSON" (missing/empty/malformed) so the caller
        falls back to SQLite; a present, parseable export yields a (possibly empty)
        list and short-circuits the DB read.
        """
        json_path = self.taxonomy_dir / f"{dataset}.json"
        if not json_path.is_file():
            return None
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            entries = payload["entries"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if not isinstance(entries, list):
            return None
        return [
            {
                "kind": e.get("kind"),
                "topic": e.get("topic"),
                "subtopic": e.get("subtopic"),
                "description": e.get("description"),
            }
            for e in entries
            if isinstance(e, dict) and e.get("kind") == kind
        ]

    def accelerator_rules(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM accelerator_rule ORDER BY position, id"
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def topic_filters(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM topic_filter ORDER BY id").fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def preprocessing_rules(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM preprocessing_rule ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
