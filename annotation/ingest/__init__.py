"""Streaming full-dataset ingestion into the annotation PostgreSQL store.

``sources`` yields raw conversation rows for each corpus (WildChat / LMSYS over
HuggingFace parquet shards; SuperDialseg from its Google Drive release); ``run``
streams those rows through the matching ``pipeline.adapters`` loader and writes
each conversation + its messages + one whole-conversation predicted segment into
Postgres in idempotent, resumable batches.
"""
