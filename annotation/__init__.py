"""Annotation web app for reviewing pipeline segments and editing boundaries.

A data-relabeling site: a FastAPI backend on PostgreSQL plus a React+Vite
frontend. One Postgres database (addressed by ``EB1_ANNOTATION_DSN``, stood up
via ``annotation/docker-compose.yml``) holds every dataset's conversations,
messages, predicted seed segments, taxonomy, and the human gold layer (corrected
topics/subtopics and boundaries) so the tool scales to the full datasets.
"""
