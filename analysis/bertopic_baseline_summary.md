# Per-domain BERTopic baseline vs grounded gold taxonomy

## Topic-level (domain -> nav category)

| domain | gold labels | clusters found | outlier % | acc all | acc clustered | NMI | ARI |
|---|---|---|---|---|---|---|---|
| dmv | 7 | 32 | 10.09 | 0.7559 | 0.8407 | 0.3844 | 0.1053 |
| ssa | 8 | 37 | 18.88 | 0.6784 | 0.8362 | 0.4083 | 0.0889 |
| studentaid | 5 | 25 | 15.39 | 0.7361 | 0.87 | 0.4901 | 0.1711 |
| va | 10 | 31 | 14.62 | 0.7115 | 0.8333 | 0.4647 | 0.1594 |

## Subtopic-level (domain -> source document)

| domain | gold labels | clusters found | outlier % | acc all | acc clustered | NMI | ARI |
|---|---|---|---|---|---|---|---|
| dmv | 51 | 32 | 10.09 | 0.5481 | 0.6096 | 0.6826 | 0.4069 |
| ssa | 43 | 37 | 18.88 | 0.5007 | 0.6173 | 0.669 | 0.3247 |
| studentaid | 50 | 25 | 15.39 | 0.5466 | 0.646 | 0.7494 | 0.4277 |
| va | 93 | 31 | 14.62 | 0.4032 | 0.4722 | 0.6471 | 0.2953 |

## Methods

One independent BERTopic model is fit per domain (dmv / ssa / studentaid / va); domain is a known deployment attribute, so classification is within-domain. Each discovered cluster is mapped to the majority gold label among its members (majority mapping = best case for an unsupervised model), then scored against the real document-grounded taxonomy at topic and subtopic granularity. Outliers (cluster -1) count as wrong in acc-all; acc-clustered, NMI and ARI cover non-outlier segments only. Corpus: 5,342 segments from the prod superdialseg export (2026-07-17). Embedder: sentence-transformers/all-MiniLM-L6-v2. UMAP: UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric=cosine, random_state=42). HDBSCAN: HDBSCAN(min_cluster_size=15, metric=euclidean, cluster_selection_method=eom). Seed: 42.

## Findings

Averaged across the four domains, best-case majority mapping recovers the grounded taxonomy at acc-all 0.7205 (NMI 0.4369) at topic granularity versus acc-all 0.4997 (NMI 0.687) at subtopic granularity. Unsupervised clusters align more coarsely than the fine-grained per-document subtopics, and even the topic-level ceiling sits well below a supervised classifier because BERTopic discovers its own partition rather than the real site-navigation categories. This is the honest unsupervised baseline the grounded taxonomy is meant to beat.
