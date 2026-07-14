"""Export a dataset's taxonomy from the annotation DB to a per-dataset JSON file.

The annotation Postgres ``taxonomy`` table is the canonical source; the pipeline
consumes the exported ``config/taxonomy/{dataset}.json`` (task 16b). Run::

    python -m annotation.export_taxonomy --dataset superdialseg

writing ``config/taxonomy/superdialseg.json`` with the deterministic shape::

    {"dataset": ..., "kind_default": "user",
     "entries": [{"kind", "topic", "subtopic", "description"}, ...]}

entries sorted by (kind, topic, subtopic) so the file is byte-stable for a given
DB state. The DSN is read from ``EB1_ANNOTATION_DSN`` (see ``annotation.backend.config``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from annotation.backend import db

DEFAULT_OUT_DIR = Path("config/taxonomy")


def export_to_file(dataset: str, out: Path) -> dict:
    """Write ``dataset``'s taxonomy export JSON to ``out`` and return the payload."""
    payload = db.export_taxonomy(dataset)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export a dataset's taxonomy from the annotation DB to JSON."
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    out = args.out or DEFAULT_OUT_DIR / f"{args.dataset}.json"
    try:
        payload = export_to_file(args.dataset, out)
    finally:
        db.reset_pool()
    print(f"wrote {len(payload['entries'])} entries -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
