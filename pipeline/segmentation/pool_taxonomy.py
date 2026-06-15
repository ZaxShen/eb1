"""
Proposal 3: Pool-specific taxonomy filtering.

Splits the full taxonomy by user pool so the LLM sees only relevant topics.
Reduces the decision space → better precision, fewer cross-pool hallucinations.

Pool membership is determined from the user's MongoDB document (the `pool` or
`pools` field). Each pool has a predefined set of relevant topics. Topics not
in the pool's allowed set are excluded from the LLM prompt.
"""

import logging

log = logging.getLogger(__name__)


# ── Pool → topic mappings ────────────────────────────────────────────────────
# These define which topics are relevant for each pool. Topics not listed
# are excluded from the LLM prompt for users in that pool.
# None = no filtering (all topics included).

POOL_TOPIC_FILTER: dict[str, set[str] | None] = {
    "wednesday": {
        "pre_match_inquiry",
        "post_match_inquiry",
        "scheduling",
        "matching",
        "account_management",
        "technical_issues",
        "complaints_or_support",
        "urgent_safety_issues",
        "gibberish",
    },
    "yik-yak": {
        "pre_match_inquiry",
        "post_match_inquiry",
        "event_inquiry",
        "matching",
        "account_management",
        "technical_issues",
        "complaints_or_support",
        "urgent_safety_issues",
        "gibberish",
    },
}

# Same structure for bot taxonomy
POOL_BOT_TOPIC_FILTER: dict[str, set[str] | None] = {
    "wednesday": {
        "scheduling",
        "matching",
        "onboarding",
        "account",
        "system",
        "promotions",
    },
    "yik-yak": {
        "events",
        "matching",
        "onboarding",
        "account",
        "system",
        "promotions",
    },
}


def get_user_pool(user_doc: dict | None) -> str | None:
    """Extract pool identifier from a MongoDB user document.

    Checks `pool` (string) and `pools` (list) fields.
    Returns the first pool found, or None if no pool info.
    """
    if user_doc is None:
        return None

    pool = user_doc.get("pool")
    if pool and isinstance(pool, str):
        return pool.lower()

    pools = user_doc.get("pools")
    if pools and isinstance(pools, list) and len(pools) > 0:
        return str(pools[0]).lower()

    return None


def filter_taxonomy_for_pool(
    taxonomy: dict[str, str],
    subtopic_descriptions: dict[str, dict[str, str]],
    pool: str | None,
    *,
    is_bot: bool = False,
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Filter taxonomy to only topics relevant to the given pool.

    Returns (filtered_taxonomy, filtered_subtopic_descriptions).
    If pool is None or not in the filter map, returns the full taxonomy.
    """
    filter_map = POOL_BOT_TOPIC_FILTER if is_bot else POOL_TOPIC_FILTER

    if pool is None or pool not in filter_map:
        return taxonomy, subtopic_descriptions

    allowed_topics = filter_map[pool]
    if allowed_topics is None:
        return taxonomy, subtopic_descriptions

    filtered_tax = {
        slug: desc for slug, desc in taxonomy.items()
        if slug in allowed_topics
    }
    filtered_sub_desc = {
        slug: descs for slug, descs in subtopic_descriptions.items()
        if slug in allowed_topics
    }

    excluded = set(taxonomy.keys()) - set(filtered_tax.keys())
    if excluded:
        log.info(
            "P3: Pool '%s' — excluded %d topic(s) from %s taxonomy: %s",
            pool,
            len(excluded),
            "bot" if is_bot else "user",
            sorted(excluded),
        )

    return filtered_tax, filtered_sub_desc


def build_pool_taxonomy_lines(
    taxonomy: dict[str, str],
    subtopic_descriptions: dict[str, dict[str, str]],
    pool: str | None,
    *,
    is_bot: bool = False,
) -> tuple[str, str]:
    """Build taxonomy_lines and topic_options strings filtered by pool.

    Returns (taxonomy_lines, topic_options) ready for prompt insertion.
    """
    filtered_tax, filtered_sub_desc = filter_taxonomy_for_pool(
        taxonomy, subtopic_descriptions, pool, is_bot=is_bot,
    )

    taxonomy_parts = []
    for slug, desc in filtered_tax.items():
        sub_descs = filtered_sub_desc.get(slug, {})
        part = f"  • {slug}: {desc}"
        if sub_descs:
            sub_lines = [f"      - {s}: {d}" for s, d in sub_descs.items()]
            part += "\n    Subtopics:\n" + "\n".join(sub_lines)
        taxonomy_parts.append(part)

    taxonomy_lines = "\n".join(taxonomy_parts)
    topic_options = " | ".join(filtered_tax.keys()) + " | <new_snake_case_topic>"

    return taxonomy_lines, topic_options
