"""
Offline Quality Layer — embed → UMAP + HDBSCAN → cluster object write-back.

This command is NOT part of the regular pipeline steps. Run it periodically to
measure cluster quality and route low-confidence segments for human review.

Steps:
  1. Fetch all segments with non-null `summary` from sms_chat_segments
  2. Embed summaries with sentence-transformers (cached to .cache/embeddings/embeddings.npz)
  3. Reduce dimensions with UMAP
  4. Cluster reduced embeddings with HDBSCAN
  5. Write `cluster` object (id, confidence, topic, sub_topic, runAt) back to each segment

Run:
    uv run python -m pipeline --offline-quality
"""

import hashlib
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import hdbscan
import numpy as np
from sentence_transformers import SentenceTransformer
from umap import UMAP

from pipeline.config.loader import AnalyzerConfig, ClusteringConfig

log = logging.getLogger(__name__)

# TOML defaults are tuned for ~5K segments.  When the actual collection is
# smaller we scale UMAP + HDBSCAN params down so the algorithm can still
# form meaningful clusters instead of marking everything as noise.
_SCALE_THRESHOLD = 500  # below this, auto-scale kicks in


def _auto_scale_params(cfg: ClusteringConfig, n_docs: int) -> ClusteringConfig:
    """Return a *copy* of ``cfg`` with UMAP/HDBSCAN params scaled for ``n_docs``.

    Rules (applied only when ``n_docs < _SCALE_THRESHOLD``):
      - hdbscan_min_cluster_size : max(3, n_docs // 10)
      - hdbscan_min_samples      : max(2, min(cfg…, n_docs // 20))
      - umap_n_neighbors          : max(3, min(cfg…, n_docs // 4))
      - umap_n_components         : max(2, min(cfg…, n_docs // 6))
    """
    if n_docs >= _SCALE_THRESHOLD:
        return cfg  # use TOML defaults as-is

    from dataclasses import replace
    scaled = replace(
        cfg,
        hdbscan_min_cluster_size=max(3, n_docs // 10),
        hdbscan_min_samples=max(2, min(cfg.hdbscan_min_samples, n_docs // 20)),
        umap_n_neighbors=max(3, min(cfg.umap_n_neighbors, n_docs // 4)),
        umap_n_components=max(2, min(cfg.umap_n_components, n_docs // 6)),
    )
    log.info(
        "Auto-scaled clustering params for %d segments: "
        "min_cluster_size=%d, min_samples=%d, "
        "umap_neighbors=%d, umap_components=%d",
        n_docs,
        scaled.hdbscan_min_cluster_size,
        scaled.hdbscan_min_samples,
        scaled.umap_n_neighbors,
        scaled.umap_n_components,
    )
    return scaled


# ── Cache helpers ─────────────────────────────────────────────────────────────


def _segment_id_hash(seg_ids: list) -> str:
    """Compute a stable hash of the sorted segment ID list for cache staleness check."""
    id_bytes = ",".join(str(sid) for sid in sorted(str(s) for s in seg_ids)).encode()
    return hashlib.sha256(id_bytes).hexdigest()


def _load_cache(cache_dir: str) -> tuple[np.ndarray | None, str | None]:
    """
    Load cached embeddings and their ID hash from disk.

    Returns (embeddings, id_hash) if a valid cache exists, or (None, None).
    """
    emb_path = Path(cache_dir) / "embeddings.npz"
    if not emb_path.exists():
        return None, None
    try:
        data = np.load(emb_path, allow_pickle=False)
        embeddings = data["embeddings"]
        id_hash = str(data["id_hash"]) if "id_hash" in data else None
        return embeddings, id_hash
    except Exception as exc:
        log.warning("Failed to load embeddings cache from %s: %s", emb_path, exc)
        return None, None


def _save_cache(cache_dir: str, embeddings: np.ndarray, id_hash: str) -> None:
    """Save embeddings and ID hash to .cache/embeddings/embeddings.npz."""
    emb_path = Path(cache_dir) / "embeddings.npz"
    try:
        emb_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(emb_path, embeddings=embeddings, id_hash=np.array(id_hash))
        log.info("Embeddings cache saved to %s (%d vectors)", emb_path, len(embeddings))
    except Exception as exc:
        log.warning("Failed to save embeddings cache to %s: %s", emb_path, exc)


# ── Core function ─────────────────────────────────────────────────────────────


def run_offline_quality(
    segment_repo,
    cfg: ClusteringConfig,
    analyzer_cfg: AnalyzerConfig,
    *,
    user_engaged_only: bool = True,
) -> dict:
    """Run the offline quality layer: embed summaries → UMAP + HDBSCAN → write cluster object.

    Args:
        segment_repo: SegmentRepository or BenchmarkSegmentRepository.
                      Must support find_with_summary() and bulk_update_clusters().
        cfg:          ClusteringConfig (embedder model, UMAP/HDBSCAN params, cache dir).
        analyzer_cfg: AnalyzerConfig   (collection names, routing thresholds).
        user_engaged_only: When True, only cluster user-engaged segments.

    Returns:
        counts: segments_processed, clusters_found, noise_count, avg_cluster_confidence
    """

    # ── 1. Fetch segments with non-null summaries ─────────────────────────────
    pool_label = "user-engaged" if user_engaged_only else "all"
    log.info("Fetching %s segments with non-null summaries…", pool_label)
    raw_docs = segment_repo.find_with_summary()
    if user_engaged_only:
        raw_docs = [d for d in raw_docs if d.get("has_user_engagement")]
    n_docs = len(raw_docs)
    log.info("Found %d %s segments with summaries.", n_docs, pool_label)

    if n_docs == 0:
        log.warning("No segments with summaries found. Offline quality step skipped.")
        return {
            "segments_processed": 0,
            "clusters_found": 0,
            "noise_count": 0,
            "avg_cluster_confidence": 0.0,
            "downgraded_count": 0,
        }

    seg_ids = [doc["id"] for doc in raw_docs]
    summaries = [doc["summary"] for doc in raw_docs]

    # ── Auto-scale clustering params for small collections ──────────────────
    cfg = _auto_scale_params(cfg, n_docs)

    # ── 2. Embed summaries (with cache) ───────────────────────────────────────
    current_hash = _segment_id_hash(seg_ids)
    cached_embeddings, cached_hash = _load_cache(cfg.cache_dir)

    if cached_embeddings is not None and cached_hash == current_hash:
        log.info(
            "Using cached embeddings (%d vectors). Cache is up to date.",
            len(cached_embeddings),
        )
        embeddings = cached_embeddings
    else:
        if cached_embeddings is not None:
            log.info(
                "Embeddings cache is stale (segment set changed). Re-embedding %d summaries…",
                n_docs,
            )
        else:
            log.info("No embeddings cache found. Embedding %d summaries…", n_docs)

        log.info("Loading sentence-transformer model: %s", cfg.embedder_model)
        model = SentenceTransformer(cfg.embedder_model)
        embeddings = model.encode(
            summaries,
            batch_size=cfg.batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
        )
        log.info("Embeddings computed: shape=%s", embeddings.shape)
        _save_cache(cfg.cache_dir, embeddings, current_hash)

    # ── 3. UMAP dimensionality reduction ─────────────────────────────────────
    log.info(
        "Running UMAP: n_components=%d, n_neighbors=%d, min_dist=%.3f",
        cfg.umap_n_components,
        cfg.umap_n_neighbors,
        cfg.umap_min_dist,
    )
    reducer = UMAP(
        n_components=cfg.umap_n_components,
        n_neighbors=cfg.umap_n_neighbors,
        min_dist=cfg.umap_min_dist,
        random_state=42,
        low_memory=False,
    )
    reduced = reducer.fit_transform(embeddings)
    log.info("UMAP done: reduced shape=%s", reduced.shape)

    # ── 4. HDBSCAN clustering ─────────────────────────────────────────────────
    log.info(
        "Running HDBSCAN: min_cluster_size=%d, min_samples=%d",
        cfg.hdbscan_min_cluster_size,
        cfg.hdbscan_min_samples,
    )
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=cfg.hdbscan_min_cluster_size,
        min_samples=cfg.hdbscan_min_samples,
        prediction_data=True,
    )
    clusterer.fit(reduced)

    labels: np.ndarray = clusterer.labels_
    probabilities: np.ndarray = clusterer.probabilities_

    n_clusters = int(labels.max()) + 1 if labels.max() >= 0 else 0
    noise_count = int((labels == -1).sum())
    noise_ratio = noise_count / n_docs if n_docs > 0 else 0.0

    # Noise points get probability 0.0 from HDBSCAN — correct by convention
    avg_confidence = float(probabilities.mean()) if len(probabilities) > 0 else 0.0

    log.info(
        "HDBSCAN done: clusters=%d, noise=%d (%.1f%%), avg_confidence=%.3f",
        n_clusters,
        noise_count,
        noise_ratio * 100,
        avg_confidence,
    )

    # ── 5. Majority-vote cluster labels ──────────────────────────────────────
    # For each cluster, the most frequent LLM-assigned (topic, sub_topic) pair
    # becomes the cluster label.  Noise points (cluster -1) get None/None.
    cluster_members: dict[int, list[tuple[str | None, str | None]]] = defaultdict(list)
    for doc, label in zip(raw_docs, labels):
        cid = int(label)
        if cid >= 0:
            cluster_members[cid].append(
                (doc.get("topic"), doc.get("sub_topic")),
            )

    cluster_labels: dict[int, tuple[str | None, str | None, float]] = {}
    for cid in sorted(cluster_members):
        members = cluster_members[cid]
        pair_counts = Counter(members)
        (majority_topic, majority_sub), majority_count = pair_counts.most_common(1)[0]
        purity = majority_count / len(members)
        cluster_labels[cid] = (majority_topic, majority_sub, purity)
        log.info(
            "Cluster %d: %d segs → %s/%s (purity=%.0f%%)",
            cid, len(members), majority_topic, majority_sub, purity * 100,
        )

    # ── 6. Write cluster object back to PostgreSQL ────────────────────────────
    log.info("Writing cluster object to %d segments…", n_docs)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    updates: list[tuple[int, dict]] = []
    for doc, label, prob in zip(raw_docs, labels, probabilities):
        cid = int(label)
        if cid >= 0:
            c_topic, c_sub, c_purity = cluster_labels[cid]
        else:
            c_topic, c_sub, c_purity = None, None, 0.0

        updates.append((
            doc["id"],
            {
                "id": cid,
                "confidence": float(prob),
                "topic": c_topic,
                "sub_topic": c_sub,
                "purity": round(c_purity, 4),
                "run_at": now.isoformat(),
            },
        ))

    if updates:
        written = segment_repo.bulk_update_clusters(updates)
        log.info("cluster written: %d segments updated", written)

    # ── Agreement metric (G3.6) ────────────────────────────────────────────
    # % of non-noise segments where the LLM topic matches the cluster label
    agree = 0
    non_noise = 0
    for doc, label in zip(raw_docs, labels):
        cid = int(label)
        if cid < 0:
            continue
        non_noise += 1
        c_topic = cluster_labels[cid][0]
        if doc.get("topic") == c_topic:
            agree += 1
    agreement_pct = (agree / non_noise * 100) if non_noise else 0.0
    log.info(
        "Label-cluster agreement (G3.6): %d/%d = %.1f%%",
        agree, non_noise, agreement_pct,
    )

    counts = {
        "segments_processed": n_docs,
        "clusters_found": n_clusters,
        "noise_count": noise_count,
        "avg_cluster_confidence": round(avg_confidence, 4),
        "label_cluster_agreement": round(agreement_pct, 1),
    }
    log.info("Offline quality complete: %s", counts)
    return counts
