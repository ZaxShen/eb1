"""
Step 0 (pre-pipeline): Signal Extraction

Queries PROD matchings for the two highest-fidelity signal sources:
  - ContactExchanged: bilateral TP (users exchanged contact info)
  - Failed - Refused: explicit rejection (at least one user rejected)

Classifies each user within the matching as TP or FP, and writes one
matching_signals document per matching to the local DB. Each document
includes the raw acceptanceStatus for future FP subcategory analysis.

The collection is idempotent — drop and regenerate anytime.

Run standalone:
    uv run python -m pipeline --step signal
"""

import logging

from bson import ObjectId
from pymongo.database import Database

from pipeline.config.loader import AnalyzerConfig

log = logging.getLogger(__name__)

SIGNAL_STATUSES = [
    "ContactExchanged",
    "Failed - Refused",
]


def run_signal_extraction(
    input_db: Database,
    output_db: Database,
    cfg: AnalyzerConfig,
    **_,
) -> dict[str, int]:
    """
    Extract TP/FP signals from PROD matchings → local matching_signals.

    input_db  — PROD (read-only: matchings)
    output_db — local (write: matching_signals)

    Returns counts: matchings_queried, signals_written, skipped, tp_signals, fp_signals.
    """
    col_in = input_db[cfg.col_input_matching]
    col_out = output_db[cfg.col_output_matching_signal]

    # Idempotent: clear and regenerate (delete_many preserves indexes)
    existing = col_out.count_documents({})
    if existing > 0:
        log.info(
            "Clearing %d existing matching_signals documents (idempotent regeneration).",
            existing,
        )
        col_out.delete_many({})

    # Step 1: Query signal-carrying matchings
    cursor = col_in.find({"status": {"$in": SIGNAL_STATUSES}})
    matchings = list(cursor)
    log.info("Queried %d signal-carrying matchings from PROD.", len(matchings))

    # Step 2: Classify and build signal documents
    signals = []
    skipped = 0
    status_counts: dict[str, int] = {}

    for m in matchings:
        doc = _classify_matching(m)
        if doc is None:
            skipped += 1
            continue
        signals.append(doc)
        status_counts[m["status"]] = status_counts.get(m["status"], 0) + 1

    # Step 3: Write to matching_signals
    if signals:
        col_out.insert_many(signals)

    log.info(
        "Signal extraction done. queried=%d written=%d skipped=%d",
        len(matchings), len(signals), skipped,
    )
    for status, count in sorted(status_counts.items()):
        log.info("  %s: %d", status, count)

    # Log TP/FP distribution
    tp_count = sum(doc["signal"].count("TP") for doc in signals)
    fp_count = sum(doc["signal"].count("FP") for doc in signals)
    total_signals = tp_count + fp_count
    if total_signals > 0:
        log.info(
            "Signal distribution: TP=%d (%.1f%%) FP=%d (%.1f%%)",
            tp_count, 100 * tp_count / total_signals,
            fp_count, 100 * fp_count / total_signals,
        )

    return {
        "matchings_queried": len(matchings),
        "signals_written": len(signals),
        "skipped": skipped,
        "tp_signals": tp_count,
        "fp_signals": fp_count,
    }


def _classify_matching(m: dict) -> dict | None:
    """
    Classify a single matching into a matching_signals document.

    Two rules:
      - ContactExchanged: both users = TP (regardless of acceptanceStatus)
      - Failed - Refused: collect where at least one acceptanceStatus is
        "rejected"; per-user: accepted → TP, everything else → FP

    Returns None if the matching should be skipped.
    """
    status = m["status"]
    users = m.get("users", [])
    acceptance = list(m.get("acceptanceStatus", []))

    # Guard: matchings must have exactly 2 users
    if len(users) != 2:
        log.warning("Matching %s has %d users (expected 2), skipping.", m["_id"], len(users))
        return None

    # Pad acceptanceStatus to length 2 if short (defensive)
    while len(acceptance) < 2:
        acceptance.append(None)

    if status == "ContactExchanged":
        signal = ["TP", "TP"]

    elif status == "Failed - Refused":
        # Only collect where at least one user explicitly rejected
        if "rejected" not in acceptance:
            return None
        signal = [_classify_user_signal(acceptance[i]) for i in range(2)]

    else:
        return None  # Unknown status — shouldn't happen

    return {
        "_id": ObjectId(),
        "matchingId": m["_id"],
        "users": list(users),
        "signal": signal,
        "matchingStatus": status,
        "acceptanceStatus": list(acceptance),  # raw values for FP subcategory analysis
        "createdAt": m.get("createdAt"),
    }


def _classify_user_signal(acceptance_value) -> str:
    """
    Classify a single user's acceptanceStatus value.

    "accepted" → TP
    Everything else → FP (null, rejected, schedulerViewed,
    schedulerOperated, cancelled, deactivated, paused, False)
    """
    if acceptance_value == "accepted":
        return "TP"
    return "FP"
