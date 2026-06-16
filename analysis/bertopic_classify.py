"""Hierarchical BERTopic runner for SuperDialseg gold-segment classification.

Fits a hierarchical BERTopic model on the concatenated utterance text of each
gold segment and assigns a coarse ``topic`` (parent cluster) plus a fine
``subtopic`` (leaf cluster), named from c-TF-IDF top keywords. The reference
topic-classification labels humans review into gold.

All heavy dependencies (bertopic, sentence-transformers, umap, hdbscan, sklearn)
are imported lazily INSIDE the functions so ``import analysis.bertopic_classify``
works without the ``bertopic`` optional-dependency group installed.
"""

from __future__ import annotations

import argparse
import logging

from annotation.backend import db

log = logging.getLogger(__name__)

EMBED_MODEL = "all-MiniLM-L6-v2"
UNCLASSIFIED = "unclassified"
_TOP_KEYWORDS = 4


def _topic_name(model, topic_id: int) -> str:
    """Name a topic from its top c-TF-IDF keywords (or 'unclassified')."""
    if topic_id == -1:
        return UNCLASSIFIED
    words = model.get_topic(topic_id)
    if not words:
        return UNCLASSIFIED
    return " / ".join(w for w, _ in words[:_TOP_KEYWORDS])


def classify_segments(
    texts: list[str],
    *,
    embeddings=None,
    random_state: int = 42,
    min_topic_size: int = 10,
) -> list[tuple[str, str]]:
    """Classify ``texts`` into ``(topic, subtopic)`` via hierarchical BERTopic.

    When ``embeddings`` is ``None`` the texts are embedded with SentenceTransformer
    ``all-MiniLM-L6-v2``; when precomputed ``embeddings`` are passed, sentence-
    transformers is NOT imported (lets tests run torch-free). UMAP is seeded with
    ``random_state`` and HDBSCAN uses ``min_cluster_size=min_topic_size`` for
    reproducibility.

    The leaf cluster is the ``subtopic``; a coarser parent cluster (reduced to
    ``~sqrt(n_leaf_topics)`` topics) is the ``topic``. Both are named from c-TF-IDF
    top keywords; outliers (topic id ``-1``) become ``'unclassified'``. Returns one
    order-aligned ``(topic, subtopic)`` per input text.
    """
    if not texts:
        return []

    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from umap import UMAP

    if embeddings is None:
        from sentence_transformers import SentenceTransformer

        embeddings = SentenceTransformer(EMBED_MODEL).encode(
            texts, show_progress_bar=False
        )

    umap_model = UMAP(
        n_neighbors=min(15, max(2, len(texts) - 1)),
        n_components=min(5, max(2, len(texts) - 2)),
        min_dist=0.0,
        metric="cosine",
        random_state=random_state,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=min_topic_size,
        metric="euclidean",
        cluster_selection_method="eom",
        prediction_data=True,
    )
    model = BERTopic(
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        min_topic_size=min_topic_size,
        calculate_probabilities=False,
        verbose=False,
    )

    leaf_topics, _ = model.fit_transform(texts, embeddings)

    leaf_ids = [t for t in set(leaf_topics) if t != -1]
    parent_of = _build_parent_map(model, texts, embeddings, leaf_ids, random_state)

    leaf_name: dict[int, str] = {-1: UNCLASSIFIED}
    for tid in leaf_ids:
        leaf_name[tid] = _topic_name(model, tid)

    out: list[tuple[str, str]] = []
    for leaf in leaf_topics:
        sub = leaf_name.get(leaf, UNCLASSIFIED)
        top = parent_of.get(leaf, sub)
        out.append((top, sub))
    return out


def _build_parent_map(
    model, texts, embeddings, leaf_ids, random_state
) -> dict[int, str]:
    """Map each leaf topic id to a coarser parent-topic name.

    Reduces the fitted model to ``~sqrt(n_leaf_topics)`` topics on a copy and reads
    the leaf->parent assignment from the resulting topic mapping; falls back to the
    leaf's own name when reduction is degenerate (<2 leaf topics).
    """
    import math

    n_leaf = len(leaf_ids)
    if n_leaf < 2:
        return {tid: _topic_name(model, tid) for tid in leaf_ids}

    n_parent = max(2, round(math.sqrt(n_leaf)))
    if n_parent >= n_leaf:
        return {tid: _topic_name(model, tid) for tid in leaf_ids}

    try:
        reduced = model.reduce_topics(texts, nr_topics=n_parent, embeddings=embeddings)
        mappings = reduced.topic_mapper_.get_mappings()
    except (ValueError, IndexError, KeyError, RuntimeError):
        log.warning("topic reduction failed; using leaf names as parents")
        return {tid: _topic_name(model, tid) for tid in leaf_ids}

    parent_of: dict[int, str] = {}
    for tid in leaf_ids:
        parent_id = mappings.get(tid, tid)
        parent_of[tid] = _topic_name(reduced, parent_id)
    return parent_of


def run(dataset: str, *, min_topic_size: int = 10) -> int:
    """Classify a dataset's gold segments and write bertopic labels to the DB.

    Loads concatenated gold-segment texts, runs :func:`classify_segments`, and
    writes order-aligned ``{segment_id, topic, subtopic}`` rows. Returns the number
    of rows written.
    """
    rows = db.gold_segment_texts(dataset)
    texts = [r["text"] for r in rows]
    labels = classify_segments(texts, min_topic_size=min_topic_size)

    updates = [
        {"segment_id": row["segment_id"], "topic": topic, "subtopic": subtopic}
        for row, (topic, subtopic) in zip(rows, labels, strict=True)
    ]
    written = db.write_bertopic_labels(updates)
    distinct_topics = len({topic for topic, _ in labels})
    log.info(
        "bertopic classified %d segments into %d distinct topics (dataset=%s)",
        len(rows),
        distinct_topics,
        dataset,
    )
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="dataset name to classify")
    parser.add_argument(
        "--min-topic-size",
        type=int,
        default=10,
        help="HDBSCAN min_cluster_size / BERTopic min_topic_size",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    written = run(args.dataset, min_topic_size=args.min_topic_size)
    print(f"Wrote bertopic labels for {written} gold segment(s) in {args.dataset!r}.")


if __name__ == "__main__":
    main()
