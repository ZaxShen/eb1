"""Per-dataset SQLite metadata layer for the universal eb1 pipeline.

Every domain knob the segmentation engine consumes — role map, prompt profile,
taxonomy, P1/P3/P4 accelerator rules, topic filters, preprocessing rules — lives
in a per-dataset ``datasets/<name>/metadata.db`` SQLite file. The pipeline loads
these at runtime as ordinary variables via :class:`SqliteDatasetProvider`, so the
same engine runs against any dataset by swapping its metadata DB.

Empty rule sets make accelerators cleanly no-op; an open ``taxonomy_mode`` lets
discovered topics flow straight to the run output without an upsert.
"""

from __future__ import annotations

from pipeline.metadata.provider import (
    DatasetConfig,
    MetadataProvider,
    SqliteDatasetProvider,
)

__all__ = [
    "DatasetConfig",
    "MetadataProvider",
    "SqliteDatasetProvider",
]
