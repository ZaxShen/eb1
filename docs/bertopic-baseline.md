# Per-Domain BERTopic Baseline

> Run 2026-07-17 (`analysis/bertopic_per_domain.py`, merged PR #53).
> Task: unsupervised topic discovery over SuperDialseg segments, scored against the
> real document-grounded gold taxonomy at topic and subtopic granularity.
> Every metric below is transcribed from `analysis/bertopic_baseline_results.json`.

---

## 1. Purpose

This is the unsupervised baseline for the NLP4ConvAI paper. It exists to be
contrasted against the deterministic document grounding that produced the gold
taxonomy (domain → site-nav category → source document): the grounded labels are
recovered from the corpus provenance, not clustered.

BERTopic is unsupervised — it cannot classify segments into a *given* taxonomy.
To score it fairly we give it its best case: fit a model, then map each
discovered cluster to the majority gold label among its members (majority-vote
cluster → gold mapping) and score that mapping. This is an optimistic upper
bound on what unsupervised clustering could deliver, and it is the honest
baseline the grounded taxonomy is meant to beat.

---

## 2. Corpus

5,342 SuperDialseg segments exported from the prod annotation DB on 2026-07-17
(`source='gold'`, `dataset='superdialseg'`, zero null labels). Gold labels are the
grounded source labels: **topic = site-nav category**, **subtopic = source
document**.

| Domain | Segments | Gold topics | Gold subtopics |
|---|---|---|---|
| dmv | 1487 | 7 | 51 |
| ssa | 1340 | 8 | 43 |
| studentaid | 955 | 5 | 50 |
| va | 1560 | 10 | 93 |
| **Total** | **5342** | — | — |

Domain is a known deployment attribute (a DMV agent never fields SSA chats), so
classification is always within-domain.

---

## 3. Method

Four independent BERTopic models are fit, one per domain, each with its own
embedding space — this simulates independent real-world deployments rather than a
single shared model.

| Stage | Configuration |
|---|---|
| Embedder | `sentence-transformers/all-MiniLM-L6-v2` |
| Dimensionality reduction | `UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric=cosine, random_state=42)` |
| Clustering | `HDBSCAN(min_cluster_size=15, metric=euclidean, cluster_selection_method=eom)` |
| Seed | 42 |

Scoring:

- **Mapping** — each non-outlier cluster is mapped to the majority gold label
  among its members (best case for an unsupervised model).
- **accuracy (all)** — HDBSCAN outliers (cluster `-1`) count as wrong.
- **accuracy (clustered)** — outliers excluded.
- **NMI / ARI** — computed over non-outlier segments only.

---

## 4. Results

### Topic level (domain → nav category)

| Domain | Gold labels | Clusters found | Outlier % | Accuracy (all) | Accuracy (clustered) | NMI | ARI |
|---|---|---|---|---|---|---|---|
| dmv | 7 | 32 | 10.09 | 0.7559 | 0.8407 | 0.3844 | 0.1053 |
| ssa | 8 | 37 | 18.88 | 0.6784 | 0.8362 | 0.4083 | 0.0889 |
| studentaid | 5 | 25 | 15.39 | 0.7361 | 0.87 | 0.4901 | 0.1711 |
| va | 10 | 31 | 14.62 | 0.7115 | 0.8333 | 0.4647 | 0.1594 |

### Subtopic level (domain → source document)

| Domain | Gold labels | Clusters found | Outlier % | Accuracy (all) | Accuracy (clustered) | NMI | ARI |
|---|---|---|---|---|---|---|---|
| dmv | 51 | 32 | 10.09 | 0.5481 | 0.6096 | 0.6826 | 0.4069 |
| ssa | 43 | 37 | 18.88 | 0.5007 | 0.6173 | 0.669 | 0.3247 |
| studentaid | 50 | 25 | 15.39 | 0.5466 | 0.646 | 0.7494 | 0.4277 |
| va | 93 | 31 | 14.62 | 0.4032 | 0.4722 | 0.6471 | 0.2953 |

---

## 5. Interpretation

At topic granularity, best-case majority mapping tops out at 0.68–0.76 accuracy
(all) even though the mapping is chosen after the fact — the unsupervised
partition simply does not line up with the real site-navigation categories. At
subtopic granularity accuracy degrades to 0.40–0.55, worst on va, whose 93 source
documents are the finest gold cardinality. Notably NMI is *higher* at subtopic
granularity (0.6471–0.7494) than at topic granularity (0.3844–0.4901): the
clusters do align with document-level structure, but there are far too few of
them to name or match 43–93 classes, so accuracy collapses. This is exactly why
the production design takes labels from deterministic grounding, has humans only
validate, and keeps BERTopic purely as the comparison baseline rather than a
labeler.

---

## 6. Artifacts & Reproduction

| Artifact | Path |
|---|---|
| Runner script | `analysis/bertopic_per_domain.py` |
| Full results (source of every number above) | `analysis/bertopic_baseline_results.json` |
| Terse run summary | `analysis/bertopic_baseline_summary.md` |

Reproduction:

1. Create a venv with `bertopic` + `sentence-transformers` (MiniLM downloads on
   first use).
2. Export the corpus from the annotation DB — segments joined to their messages,
   filtered to `source='gold'` and `dataset='superdialseg'`, emitting per-segment
   text plus grounded topic/subtopic labels.
3. Run:

   ```bash
   python analysis/bertopic_per_domain.py \
     --input <export.json> \
     --output analysis/bertopic_baseline_results.json
   ```

The seed is fixed at 42 and the results JSON is committed, so re-running is
optional — the committed artifact is the reference of record.
