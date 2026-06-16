"""Tests for the hierarchical BERTopic runner.

Two layers:

- An orchestration test that monkeypatches ``classify_segments`` and the two DB
  helpers, so ``run`` is exercised torch-free and without a database.
- A classify test guarded by ``pytest.importorskip("bertopic")`` that fits real
  BERTopic on ~40 synthetic docs using SEEDED precomputed embeddings (so
  sentence-transformers is never imported). Skips when the extra is absent.
"""

from __future__ import annotations

import pytest

from analysis import bertopic_classify


def test_run_loads_classifies_and_writes_aligned_rows(monkeypatch):
    rows = [
        {"segment_id": 11, "conversation": "c1", "text": "reset my password"},
        {"segment_id": 22, "conversation": "c1", "text": "my billing plan"},
        {"segment_id": 33, "conversation": "c2", "text": "shipping status"},
    ]
    captured: dict = {}

    def fake_gold_segment_texts(dataset):
        captured["dataset"] = dataset
        return rows

    def fake_classify_segments(texts, *, min_topic_size=10):
        captured["texts"] = texts
        captured["min_topic_size"] = min_topic_size
        return [
            ("account / password", "password reset"),
            ("account / billing", "billing plan"),
            ("orders / shipping", "shipping status"),
        ]

    def fake_write(updates):
        captured["updates"] = updates
        return len(updates)

    monkeypatch.setattr(bertopic_classify.db, "gold_segment_texts", fake_gold_segment_texts)
    monkeypatch.setattr(bertopic_classify, "classify_segments", fake_classify_segments)
    monkeypatch.setattr(bertopic_classify.db, "write_bertopic_labels", fake_write)

    written = bertopic_classify.run("superdialseg", min_topic_size=5)

    assert written == 3
    assert captured["dataset"] == "superdialseg"
    assert captured["texts"] == ["reset my password", "my billing plan", "shipping status"]
    assert captured["min_topic_size"] == 5
    assert captured["updates"] == [
        {"segment_id": 11, "topic": "account / password", "subtopic": "password reset"},
        {"segment_id": 22, "topic": "account / billing", "subtopic": "billing plan"},
        {"segment_id": 33, "topic": "orders / shipping", "subtopic": "shipping status"},
    ]


def test_run_empty_dataset(monkeypatch):
    monkeypatch.setattr(bertopic_classify.db, "gold_segment_texts", lambda dataset: [])
    monkeypatch.setattr(bertopic_classify, "classify_segments", lambda texts, **kw: [])
    monkeypatch.setattr(bertopic_classify.db, "write_bertopic_labels", lambda rows: len(rows))
    assert bertopic_classify.run("empty") == 0


def test_classify_segments_empty_returns_empty():
    assert bertopic_classify.classify_segments([]) == []


def test_classify_segments_with_precomputed_embeddings():
    pytest.importorskip("bertopic")
    import numpy as np

    rng = np.random.default_rng(42)
    groups = [
        ("password login account reset credentials", np.array([3.0, 0.0, 0.0])),
        ("billing invoice payment plan subscription", np.array([0.0, 3.0, 0.0])),
        ("shipping delivery tracking order package", np.array([0.0, 0.0, 3.0])),
    ]
    texts: list[str] = []
    vectors: list[np.ndarray] = []
    for _ in range(14):
        for words, center in groups:
            texts.append(words)
            vectors.append(center + rng.normal(0.0, 0.05, size=3))
    texts = texts[:40]
    vectors = vectors[:40]
    embeddings = np.asarray(vectors, dtype=np.float32)

    labels = bertopic_classify.classify_segments(
        texts, embeddings=embeddings, random_state=42, min_topic_size=3
    )

    assert len(labels) == 40
    for label in labels:
        assert isinstance(label, tuple)
        assert len(label) == 2
        topic, subtopic = label
        assert isinstance(topic, str)
        assert isinstance(subtopic, str)
