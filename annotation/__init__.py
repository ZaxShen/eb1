"""Annotation web app for reviewing pipeline segments and editing boundaries.

A trimmed, offline-friendly relabeling site modeled on ufl-dev's
docker-topic-annotation: a FastAPI backend over per-dataset SQLite plus a
React+Vite frontend. The backend reads segments the universal runner writes to
``datasets/<name>/output.db``, conversation messages from the dataset sample
(via the adapter), and taxonomy from ``datasets/<name>/metadata.db``; it writes
human gold (corrected topics/subtopics and boundaries) to a per-dataset
``datasets/<name>/gold.db``.
"""
