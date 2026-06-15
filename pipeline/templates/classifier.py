"""
Template classification pipeline.

Fetches message templates from PROD, classifies each via LLM, and stores
results in the local DB for bot-only segment enrichment.

Bot topics are stored in sms_chat_taxonomy with type="bot".
New topics/subtopics discovered by the LLM are upserted there
automatically so future runs reuse them.

Usage:
    uv run python -m pipeline --classify-templates
"""

import json
import logging
import os
import re
from typing import TYPE_CHECKING, Any

from pymongo.database import Database

from pipeline.config.loader import (
    AnalyzerConfig,
    SubtopicEntry,
    TaxonomyTopic,
    load_template_taxonomy_from_db,
    save_template_taxonomy_to_db,
)

if TYPE_CHECKING:
    from db.repositories.taxonomy import TaxonomyRepository
    from db.repositories.templates import TemplateMappingRepository

log = logging.getLogger(__name__)

_client_cache: dict[tuple[str, str], Any] = {}


def _get_openai_client(api_key: str, base_url: str) -> Any:
    key = (api_key, base_url)
    if key not in _client_cache:
        from openai import OpenAI
        _client_cache[key] = OpenAI(api_key=api_key, base_url=base_url)
    return _client_cache[key]


# ── Template fetching ────────────────────────────────────────────────────────


def fetch_templates(
    input_db: Database, cfg: AnalyzerConfig,
) -> list[dict]:
    """Fetch message templates from PROD that have imessageContent.

    Returns a list of dicts:
        {_id, name, messages: list[str], full_text: str}

    Queries all docs with imessageContent (including drafts). Extracts
    text from imessageContent[].message fields. Templates where no text
    can be extracted (media-only) are skipped with a warning.
    """
    col = input_db[cfg.col_input_message_template]
    cursor = col.find(
        {"imessageContent": {"$exists": True, "$not": {"$size": 0}}},
        {"_id": 1, "name": 1, "imessageContent": 1},
    )

    templates: list[dict] = []
    skipped_no_list = 0
    skipped_no_text = 0

    for doc in cursor:
        imsg = doc.get("imessageContent")
        if not imsg or not isinstance(imsg, list):
            skipped_no_list += 1
            continue

        # Extract text from all possible fields
        messages: list[str] = []
        for obj in imsg:
            if not isinstance(obj, dict):
                continue
            # Try 'message' first, fall back to 'text' or 'content'
            text = (
                obj.get("message")
                or obj.get("text")
                or obj.get("content")
                or ""
            )
            if text and isinstance(text, str):
                messages.append(text)

        if not messages:
            skipped_no_text += 1
            log.debug(
                "Template '%s' (%s) — no text in imessageContent, "
                "keys: %s",
                doc.get("name", "?"),
                doc["_id"],
                [list(o.keys()) for o in imsg if isinstance(o, dict)],
            )
            continue

        templates.append({
            "_id": doc["_id"],
            "name": doc.get("name", ""),
            "messages": messages,
            "full_text": "\n".join(messages),
        })

    log.info(
        "Fetched %d templates with text. "
        "Skipped: %d no-list, %d no-text (media-only).",
        len(templates), skipped_no_list, skipped_no_text,
    )
    return templates


# ── Taxonomy formatting ──────────────────────────────────────────────────────


def _build_template_taxonomy_text(
    taxonomy: dict[str, TaxonomyTopic],
) -> str:
    """Format template_taxonomy.yaml for LLM prompt context."""
    if not taxonomy:
        return "  (no existing topics yet — create new ones as needed)"
    parts: list[str] = []
    for slug, topic in taxonomy.items():
        part = f"  - {slug}: {topic.description}"
        if topic.subtopics:
            sub_lines = [
                f"      - {s}: {e.description}"
                for s, e in topic.subtopics.items()
            ]
            part += "\n    Subtopics:\n" + "\n".join(sub_lines)
        parts.append(part)
    return "\n".join(parts)


_SYSTEM_PROMPT = """You are a template classifier for Acme, \
a university matchmaking app.

Given an automated message template, classify it with:
- topic: a snake_case topic slug describing the template's purpose
- subTopic: a snake_case subTopic slug for more detail
- summary: one sentence describing what this template communicates \
to the user

Use the existing topics below when they fit. If no existing topic \
fits, create a new descriptive snake_case slug. Every template \
MUST be classified.

## Existing Topics
{taxonomy}

Respond with JSON only: {{"topic": "...", "subTopic": "...", \
"summary": "..."}}"""


# ── LLM classification ──────────────────────────────────────────────────────


def classify_one(
    model: str,
    template_text: str,
    taxonomy_text: str,
    temperature: float,
    base_url: str,
) -> dict | None:
    """Classify a single template via LLM. Returns parsed dict or None."""
    api_key = (
        os.environ.get("AI_GATEWAY_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("VERCEL_API_KEY", "")
    )
    client = _get_openai_client(api_key, base_url)

    system = _SYSTEM_PROMPT.format(taxonomy=taxonomy_text)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": template_text},
    ]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        raw = response.choices[0].message.content or ""
    except Exception as exc:
        log.warning("LLM call failed for template: %s", exc)
        return None

    return _parse_classification(raw)


def _parse_classification(raw: str) -> dict | None:
    """Parse LLM JSON response into {topic, subTopic, summary}.

    Accepts any topic/subTopic — no taxonomy validation.
    Returns None only on parse failure or missing fields.
    """
    # Strip markdown fences
    cleaned = re.sub(r"```[a-z]*\n?", "", raw).strip()
    cleaned = cleaned.rstrip("```").strip()

    # Find JSON object
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        log.warning(
            "Template classification parse failed — no JSON found. "
            "Raw: %s", raw[:300],
        )
        return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as exc:
        log.warning(
            "Template classification JSON decode error: %s. "
            "Raw: %s", exc, raw[:300],
        )
        return None

    topic = data.get("topic")
    sub_topic = data.get("subTopic")
    summary = data.get("summary")

    if not topic or not sub_topic or not summary:
        log.warning(
            "Template classification missing fields: %s", data,
        )
        return None

    return {
        "topic": topic,
        "subTopic": sub_topic,
        "summary": summary,
    }


# ── Orchestrator ─────────────────────────────────────────────────────────────


def _update_template_taxonomy(
    taxonomy: dict[str, TaxonomyTopic],
    topic: str,
    sub_topic: str,
    summary: str,
) -> bool:
    """Add topic/subTopic to template taxonomy if new.

    Returns True if the taxonomy was modified (needs saving).
    """
    changed = False
    if topic not in taxonomy:
        taxonomy[topic] = TaxonomyTopic(
            description=summary,
            subtopics={sub_topic: SubtopicEntry(description=summary, confirmed_by=None)},
        )
        changed = True
    elif sub_topic not in taxonomy[topic].subtopics:
        taxonomy[topic].subtopics[sub_topic] = SubtopicEntry(
            description=summary, confirmed_by=None
        )
        changed = True
    return changed


def _save_classification(
    template_repo: "TemplateMappingRepository",
    template_id: str,
    name: str,
    topic_slug: str,
    subtopic_slug: str,
    summary: str,
    messages: list[str],
) -> None:
    """Persist a single template classification result to PG."""
    template_repo.upsert(
        template_id=template_id,
        topic_slug=topic_slug,
        subtopic_slug=subtopic_slug,
        name=name,
        summary=summary,
        messages=messages,
    )


def run_template_classifier(
    input_db: Database,
    cfg: AnalyzerConfig,
    template_repo: "TemplateMappingRepository | None" = None,
    taxonomy_repo: "TaxonomyRepository | None" = None,
) -> dict:
    """Fetch templates from PROD, classify via LLM, write to PG.

    Uses sms_chat_taxonomy (type="bot") as LLM context. New topics/subtopics
    discovered during classification are upserted to PG.

    Idempotent — skips templates already present in eb1_template_mappings (PG).

    Args:
        input_db: PROD MongoDB (read-only — fetches message_templates).
        cfg: pipeline configuration.
        template_repo: PG repository for eb1_template_mappings writes.
        taxonomy_repo: PG repository for taxonomy reads/writes.

    Returns: {templates_fetched, templates_classified, templates_skipped}
    """
    templates = fetch_templates(input_db, cfg)
    if not templates:
        log.warning("No templates found with imessageContent.")
        return {
            "templates_fetched": 0,
            "templates_classified": 0,
            "templates_skipped": 0,
        }

    # Check which templates are already classified (idempotency)
    if template_repo is not None:
        existing_ids = template_repo.existing_template_ids()
    else:
        existing_ids = set()
    log.info(
        "%d templates already classified — will skip.",
        len(existing_ids),
    )

    # Load template taxonomy from PG (grows as new topics are discovered)
    tmpl_taxonomy = load_template_taxonomy_from_db(taxonomy_repo) if taxonomy_repo else {}
    log.info(
        "Template taxonomy: %d existing topics.",
        len(tmpl_taxonomy),
    )
    taxonomy_text = _build_template_taxonomy_text(tmpl_taxonomy)

    classified = 0
    skipped = 0
    taxonomy_changed = False

    for tmpl in templates:
        template_id = str(tmpl["_id"])
        if template_id in existing_ids:
            skipped += 1
            continue

        result = classify_one(
            model=cfg.model,
            template_text=tmpl["full_text"],
            taxonomy_text=taxonomy_text,
            temperature=cfg.temperature,
            base_url=cfg.base_url,
        )
        if result is None:
            log.warning(
                "Skipping template '%s' — classification failed.",
                tmpl["name"],
            )
            skipped += 1
            continue

        # Update template taxonomy with new topics/subtopics
        if _update_template_taxonomy(
            tmpl_taxonomy,
            result["topic"],
            result["subTopic"],
            result["summary"],
        ):
            taxonomy_changed = True
            # Rebuild prompt text so next template sees new topics
            taxonomy_text = _build_template_taxonomy_text(tmpl_taxonomy)

        if template_repo is not None:
            _save_classification(
                template_repo=template_repo,
                template_id=template_id,
                name=tmpl["name"],
                topic_slug=result["topic"],
                subtopic_slug=result["subTopic"],
                summary=result["summary"],
                messages=tmpl["messages"],
            )
        classified += 1
        log.info(
            "Classified template '%s' -> %s / %s",
            tmpl["name"], result["topic"], result["subTopic"],
        )

    # Persist taxonomy changes to PG
    if taxonomy_changed and taxonomy_repo is not None:
        save_template_taxonomy_to_db(taxonomy_repo, tmpl_taxonomy)
        log.info(
            "Template taxonomy updated: %d topics.",
            len(tmpl_taxonomy),
        )

    log.info(
        "Template classification complete: %d fetched, "
        "%d classified, %d skipped.",
        len(templates), classified, skipped,
    )
    return {
        "templates_fetched": len(templates),
        "templates_classified": classified,
        "templates_skipped": skipped,
    }
