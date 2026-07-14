"""Streaming corpus ingestion into the annotation PostgreSQL store.

SuperDialseg (from its Google Drive release) is the active corpus for the
current campaign; the WildChat / LMSYS adapters over HuggingFace parquet shards
remain available but dormant. ``sources`` yields raw conversation rows for each
corpus; ``run`` streams those rows through the matching ``pipeline.adapters``
loader and writes each conversation + its messages + one whole-conversation
predicted segment into Postgres in idempotent, resumable batches.
"""
