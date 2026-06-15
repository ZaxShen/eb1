# Graders Reference

> Quality gates for the eb1 analysis pipeline. Each grader is a deterministic or statistical check that runs at a specific pipeline stage. Graders are organized by level — lower levels catch fundamental data corruption; higher levels measure analytical quality.
>
> **Architecture:** Single-node Analyzer (one LLM call per user per window does segment + summarize + classify). HDBSCAN runs as an offline quality layer (periodic, not every run).

---

## Level 0 — Data Integrity

Deterministic checks. If any fails, the pipeline output is corrupt. These should be assertions or fail-fast guards — never silently logged.

| ID | Grader | Stage | What it checks | Pass condition |
|---|---|---|---|---|
| G0.1 | No duplicate message refs | Analyzer | Each `chatMessages` array has unique ObjectIds | `len(ids) == len(set(ids))` for every segment |
| G0.2 | Message existence | Analyzer | Every ObjectId in `chatMessages` exists in `sms_chat_messages` | 0 dangling refs |
| G0.3 | Full message coverage | Analyzer | Union of `chatMessages` across all segments for a user covers all `user`/`assistant` messages in that user's `sms_chats` doc | No gaps. **Overlaps ARE expected** — a message may appear in multiple segments when it covers multiple topics. |
| G0.4 | User-signal linkage | Analyzer | Every segmented `userId` exists in `matching_signals.users` | 0 orphan users |
| G0.5 | Signal stability | signal | `matching_signals.count_documents({})` is stable across idempotent re-runs | Count delta = 0 |
| G0.6 | Signal-PROD parity | signal | Per-status counts in `matching_signals` ≤ PROD `matchings` counts (never more) | No inflation |
| G0.7 | Pre-segmentation completeness | Analyzer | Union of `chatMessages` across all segments covers every message from `_build_flat_history` (all types: user, assistant, automated, team, system-noReply) | 0 missing messages |
| G0.8 | Non-user message uniqueness | Analyzer | Each non-user message (assistant, automated, team, system) appears in at most one segment. Only `type: "user"` may appear in multiple segments (multi-topic overlap). | 0 non-user duplicates |
| G0.9 | Reviewed segment integrity | Analyzer | Segments with `reviewedAt` set must have non-null `trueTopic` and `trueSubTopic`; converse also holds (any review indicator implies all three present) | 0 corrupted reviewed segments |
| G0.10 | Topic/subTopic completeness | Analyzer | Every segment has non-null, non-empty `topic` and `subTopic` | 0 segments with missing topic or subTopic |
| G0.11 | LLM labelConfidence range | Analyzer | Every segment's `labelConfidence` is within [0.0, 1.0] or null (bot-only segments) | 0 out-of-range values |

**Status:** G0.1 implemented (assertion in segmenter). G0.3, G0.7, G0.8, G0.9, G0.10, G0.11 implemented (`pipeline/graders/segmentation_graders.py`, wired to `--step validate`). G0.2, G0.4–G0.6 not yet implemented.

---

## Level 1 — Segmentation Quality

Statistical checks on segment structure. These don't validate topic labels — only that the raw segmentation is reasonable.

| ID | Grader | Stage | What it checks | Expected range |
|---|---|---|---|---|
| G1.1 | Segments per user | Analyzer | Distribution of segment count per user | avg 2–5, max < 100 |
| G1.2 | Min message count | Analyzer | Segments with only 1 message | Should be rare. A single user message must have a bot reply — 1-message segments are suspicious |
| G1.3 | Message count sanity | Analyzer | `sum(len(chatMessages))` for a user vs total `user`/`assistant` messages | Should match or be close. May exceed due to multi-topic overlap. |
| G1.4 | Timestamp ordering | Analyzer | `chatStartedAt < chatEndedAt` for every segment | 0 violations. Note: segments may be non-contiguous in time. |
| G1.5 | No-chat rate | Analyzer | % of sampled users with no `sms_chats` document | ~30% (pre-chatbot cohort). Alert if > 50% |

**Status:** G1.1 checked manually. G1.2 and G1.4 implemented (`pipeline/graders/segmentation_graders.py`, wired to `--step validate`). G1.3, G1.5 not yet automated.

---

## Level 2 — Offline Cluster Quality

Statistical checks on embedding + clustering output. These run periodically as part of the **offline quality layer** (not on every pipeline run).

| ID | Grader | Stage | What it checks | Expected range |
|---|---|---|---|---|
| G2.1 | Noise ratio | offline | % of segments classified as HDBSCAN noise (`label == -1`) | < 40%. Alert if > 40% |
| G2.2 | Cluster count | offline | Number of non-noise clusters | 10–100 for ~5K segments |
| G2.3 | Cluster size distribution | offline | Min/max/avg segments per cluster | No cluster should have > 30% of all segments |
| G2.4 | Silhouette score | offline | Global cluster separation quality | > 0.1 (low but positive = meaningful structure) |
| G2.5 | Intra-topic cohesion | offline | Mean pairwise cosine similarity of summary embeddings within each LLM-assigned topic | Low cohesion = LLM grouping dissimilar things under one label |
| G2.6 | Inter-topic separation | offline | Distance between topic centroids | Nearly identical centroids = redundant topics or LLM can't distinguish |
| G2.7 | Per-segment centroid distance | offline | How far each segment's embedding is from its assigned topic's centroid | Available on every offline run. Fast to compute. |

**Status:** G2.1 and G2.2 implemented in evaluator. G2.3–G2.7 not yet implemented.

---

## Level 3 — Label Quality

Statistical checks on the AI-assigned topic labels. These run after the Analyzer writes segments.

| ID | Grader | Stage | What it checks | Expected range |
|---|---|---|---|---|
| G3.1 | Topic dominance | Analyzer | No single topic > 40% of all segments | Fails if any topic > 40% |
| G3.2 | Topic diversity | Analyzer | Distinct topic count | >= 10 for PROD |
| G3.3 | Low-confidence queue | Analyzer | Segments where `labelConfidence < threshold` (configurable in `analyzer.toml → [routing]`) | Report count. This IS the review queue. |
| G3.4 | Unconfirmed topic count | Analyzer | Count of topics in `sms_chat_taxonomy` where `confirmedBy = null` | Informational. High count on first PROD run is expected |
| G3.5 | Unconfirmed subtopic count | Analyzer | Count of subtopics in `sms_chat_taxonomy` where subtopic `confirmedBy = null` | Informational |
| G3.6 | Cluster-label agreement | offline | % of segments where HDBSCAN cluster label agrees with LLM-assigned topic | Target > 85% after calibration convergence |
| G3.7 | Unlabeled segments | Analyzer | Segments with `topic = null` after Analyzer commit | Must be 0. `null` topic = pipeline bug. Gibberish segments get `topic = "gibberish"`. |
| G3.8 | Label accuracy | review | `topic == trueTopic` where both exist | Only meaningful after human review fills `trueTopic`. Phase 2+ |
| G3.9 | Summary faithfulness | review | LLM judge verifying segment summary accurately reflects source messages | Deferred — requires human calibration first |

**Status:** G3.1–G3.5 implemented in evaluator. G3.6 not yet (requires offline quality data). G3.7–G3.9 not yet automated.

---

## Level 4 — Signal Correlation

Analytical checks that cross-reference pipeline output with `matching_signals`. These validate whether the pipeline produces data useful for the downstream goal (understanding TP vs FP user behavior).

| ID | Grader | Stage | What it checks | Expected |
|---|---|---|---|---|
| G4.1 | User coverage | evaluate | `sms_chat_segments.distinct("userId")` ⊆ `matching_signals.distinct("users")` | Every segmented user has signal |
| G4.2 | Signal coverage | evaluate | % of `matching_signals` users who have ≥ 1 segment | ~70% (pre-chatbot gap) |
| G4.3 | TP/FP topic distribution | evaluate | Compare topic distributions between TP-only and FP-only users | Informational — difference = signal; similarity = noise |

**Status:** None implemented. G4.1–G4.2 are simple queries. G4.3 is the analytical payoff — deferred to Phase 3 (Signal Validation).

---

## Unit Tests

Deterministic functions that must be tested with `pytest`. These cover the logic that graders depend on.

### Signal extraction (`pipeline/sampling/signal_extractor.py`)

| Test | Function | Cases |
|---|---|---|
| Tier A override | `_classify_matching` | ContactExchanged → both TP regardless of acceptanceStatus |
| Tier B filter | `_classify_matching` | Dated with [accepted, accepted] → TP; other combos → skip |
| Tier C per-user | `_classify_matching` | PickTimeFailed: [accepted, null] → [TP, FP]; [null, null] → [FP, FP] |
| Failed-Refused filter | `_classify_matching` | [accepted, rejected] → kept; [null, schedulerViewed] → skipped |
| Malformed users | `_classify_matching` | 0 users → skip; 1 user → skip; 3 users → skip |
| Short acceptanceStatus | `_classify_matching` | 1-element array → padded to [value, None] |
| User signal classification | `_classify_user_signal` | "accepted" → TP; null → FP; "rejected" → FP; "deactivated" → FP; False → FP |

### Segmentation (`pipeline/segmentation/segmenter.py`)

| Test | Function | Cases |
|---|---|---|
| Split-point parsing | `_parse_int_list` | Valid JSON: `[3, 7]`; markdown fences; empty array; malformed string; floats |
| Range generation | `_splits_to_ranges` | No splits → single range; 1 split; multiple splits; n=0; n=1 |
| Duplicate split points | `_splits_to_ranges` | `[5, 5, 5]` → deduplicated by set in `_call_segmenter` |
| Message dedup | `_build_flat_history` | Duplicate `_id` in query result → deduplicated with log warning |
| Segment building | `_build_segments` | Correct `chat` and `chatMessages` field names; timestamp ordering |

### Config loading (`pipeline/config/loader.py`)

| Test | Function | Cases |
|---|---|---|
| Default collection names | `load_analyzer_config` | Missing `[collections]` section → falls back to defaults |
| New field names | `load_analyzer_config` | `col_input_matching` and `col_output_matching_signal` populated |
| Benchmark config | `load_benchmark_config` | Missing file → empty list; valid `[[run]]` entries parsed correctly |

---

## Confidence Signals

Segments carry two confidence scores for quality assessment:

| Signal | Source | Description |
|---|---|---|
| `labelConfidence` | LLM (main pipeline) | Self-reported confidence in topic assignment [0.0–1.0] |
| `cluster.confidence` | HDBSCAN (offline quality) | Cluster membership probability [0.0–1.0], inside the `cluster` object written by the offline quality layer |

---

## Implementation Status

| Level | Total | Implemented | Gap |
|---|---|---|---|
| L0 — Data Integrity | 11 | 7 (G0.1, G0.3, G0.7, G0.8, G0.9, G0.10, G0.11) | 4 |
| L1 — Segmentation Quality | 5 | 2 (G1.2, G1.4) | 3 |
| L2 — Offline Cluster Quality | 7 | 2 | 5 |
| L3 — Label Quality | 9 | 5 | 4 |
| L4 — Signal Correlation | 3 | 0 | 3 |
| **Total** | **35** | **16** | **19** |

Unit tests: **191 passing** (`uv run pytest`).
