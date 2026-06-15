"""Load pipeline/config/ files into typed dataclasses."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline.segmentation.preprocessing import _slug_to_display_name

if TYPE_CHECKING:
    from db.repositories.taxonomy import TaxonomyRepository

_CONFIG_DIR = Path(__file__).parent
log = logging.getLogger(__name__)


@dataclass
class AnalyzerConfig:
    # [analyzer]
    model: str
    prompt_version: str       # "latest" or "v1", "v2", etc.
    bot_prompt_version: str   # prompt for bot-only LLM calls (e.g. "bot_v1")
    temperature: float    # LLM temperature
    base_url: str         # empty = local Ollama; URL = Vercel/OpenAI-compatible
    drop_existing: bool   # drop unreviewed sms_chat_segments docs before running
    drop_reviewed: bool   # also drop reviewed segments (trueTopic/trueSubTopic set) — DESTRUCTIVE
    seg_concurrency: int  # parallel LLM calls; keep ≤ Ollama num_parallel
    benchmark_mode: bool  # when true, writes analyzerMeta to each segment
    window_size: int      # max messages per LLM call; 0 = no windowing (send all)
    bot_gap_seconds: int  # gap between non-user msgs to start a new bot-only chunk
    user_window_days: int # days after a user message to include in the LLM chunk

    # [routing]
    cluster_confidence_threshold: float  # confidence threshold for HDBSCAN cluster membership
    template_match_threshold: float      # min difflib similarity for bot-only template matching

    # [pipeline]
    user_limit: int  # 0 = all users
    relabel: bool    # re-classify existing segments without re-segmenting

    # [collections] — configurable collection names for input/output DBs
    col_input_user: str                  # User documents (source)
    col_input_chat: str                  # Chat session documents (source)
    col_input_chat_message: str          # chat_messages documents (source)
    col_input_matching: str              # matchings documents (source — PROD)
    col_input_message_template: str      # message_templates (PROD — read-only)
    col_output_chat_segment: str         # sms_chat_segments documents (pipeline output)
    col_output_matching_signal: str      # matching_signals documents (pipeline output — local)
    col_output_template_classification: str  # message_template_classifications (local)
    col_output_chat_taxonomy: str            # sms_chat_taxonomy (used by segmenter._ensure_taxonomy_entry)  # noqa: E501

    # [benchmark] — set at runtime by run_benchmark(), not from TOML
    run_id: str = ""
    pure_llm: bool = False  # bypass all preprocessing — pure V3 prompt

    @property
    def seg_model(self) -> str:
        """Backward-compat alias — use .model instead."""
        return self.model


@dataclass
class ClusteringConfig:
    # [embedder]
    embedder_model: str
    cache_dir: str
    batch_size: int

    # [clusterer]
    umap_n_components: int
    umap_n_neighbors: int
    umap_min_dist: float
    hdbscan_min_cluster_size: int
    hdbscan_min_samples: int


# ── Taxonomy ───────────────────────────────────────────────────────────────────


@dataclass
class SubtopicEntry:
    description: str = ""
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    created_by: str | None = None
    updated_by: str | None = None


@dataclass
class TaxonomyTopic:
    description: str = ""
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    created_by: str | None = None
    updated_by: str | None = None
    subtopics: dict[str, SubtopicEntry] = field(default_factory=dict)


def _load_taxonomy(repo: TaxonomyRepository, type_filter: str) -> dict[str, TaxonomyTopic]:
    """Load taxonomy from PostgreSQL by type ('user' or 'bot').

    Returns a dict keyed by topic slug with descriptions and subtopics.
    """
    result: dict[str, TaxonomyTopic] = {}
    for topic in repo.load_topics(type_filter):
        subtopics: dict[str, SubtopicEntry] = {}
        for sub in topic.get("subtopics") or []:
            subtopics[sub["slug"]] = SubtopicEntry(
                description=sub.get("description", ""),
                confirmed_by=sub.get("confirmed_by"),
                confirmed_at=sub.get("confirmed_at"),
                created_by=sub.get("created_by"),
                updated_by=sub.get("updated_by"),
            )
        result[topic["slug"]] = TaxonomyTopic(
            description=topic.get("description", ""),
            confirmed_by=topic.get("confirmed_by"),
            confirmed_at=topic.get("confirmed_at"),
            created_by=topic.get("created_by"),
            updated_by=topic.get("updated_by"),
            subtopics=subtopics,
        )
    return result


def load_taxonomy_from_db(repo: TaxonomyRepository) -> dict[str, TaxonomyTopic]:
    return _load_taxonomy(repo, "user")


# ── Derived taxonomy constants ────────────────────────────────────────────────
# Populated at runtime by ``init_taxonomy(repo)`` before the pipeline runs.
# Importers access them by name; the underlying dicts are mutated in place.

# Safety: these dicts are cleared+repopulated only between segmenter batches
# (after all concurrent workers complete). Do NOT call init_taxonomy() or
# _refresh_if_stale() while workers are reading these dicts.
INITIAL_TAXONOMY: dict[str, str] = {}
KNOWN_SUBTOPICS: dict[str, set[str]] = {}
SUBTOPIC_DESCRIPTIONS: dict[str, dict[str, str]] = {}
TOPIC_CONFIRMED: dict[str, str | None] = {}
SUBTOPIC_CONFIRMED: dict[str, dict[str, str | None]] = {}

_taxonomy_loaded_at = None  # datetime | None — set by init_taxonomy()


def _populate_taxonomy_dicts(
    taxonomy: dict[str, TaxonomyTopic],
    targets: tuple[dict, dict, dict, dict, dict],
) -> None:
    """Clear and repopulate five taxonomy dicts from a loaded taxonomy."""
    tax, known_sub, sub_desc, topic_conf, sub_conf = targets
    for d in targets:
        d.clear()
    for slug, entry in taxonomy.items():
        tax[slug] = entry.description
        known_sub[slug] = set(entry.subtopics.keys())
        sub_desc[slug] = {s: e.description for s, e in entry.subtopics.items()}
        topic_conf[slug] = entry.confirmed_by
        sub_conf[slug] = {s: e.confirmed_by for s, e in entry.subtopics.items()}


_USER_TARGETS = (
    INITIAL_TAXONOMY, KNOWN_SUBTOPICS, SUBTOPIC_DESCRIPTIONS,
    TOPIC_CONFIRMED, SUBTOPIC_CONFIRMED,
)


def init_taxonomy(repo: TaxonomyRepository) -> None:
    """Load user taxonomy from PG and populate module-level constants.

    Must be called once at pipeline startup. Safe to call multiple times.
    """
    global _taxonomy_loaded_at
    from datetime import datetime, timezone

    taxonomy = load_taxonomy_from_db(repo)
    if not taxonomy:
        raise RuntimeError(
            "No rows found in 'eb1_taxonomy_topics' (type=user). "
            "Seed the taxonomy first (see pipeline/config/loader.py)."
        )
    _populate_taxonomy_dicts(taxonomy, _USER_TARGETS)
    _taxonomy_loaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    log.info("[config] Loaded %d topics from eb1_taxonomy_topics", len(taxonomy))


# ── Template taxonomy (bot segments) ──────────────────────────────────────────

def load_template_taxonomy_from_db(repo: TaxonomyRepository) -> dict[str, TaxonomyTopic]:
    return _load_taxonomy(repo, "bot")




def _save_taxonomy_to_db(
    repo: TaxonomyRepository,
    taxonomy: dict[str, TaxonomyTopic],
    *,
    taxonomy_type: str,
) -> None:
    """Append-only upsert of taxonomy topics to PostgreSQL.

    Builds the topics list expected by repo.batch_upsert().
    """
    topics_list = []
    for slug, topic in sorted(taxonomy.items()):
        subtopics_list = [
            {
                "slug": sub_slug,
                "name": _slug_to_display_name(sub_slug),
                "description": sub_entry.description,
                "confirmed_by": sub_entry.confirmed_by,
                "confirmed_at": sub_entry.confirmed_at,
                "created_by": sub_entry.created_by,
                "updated_by": sub_entry.updated_by,
            }
            for sub_slug, sub_entry in sorted(topic.subtopics.items())
        ]
        topics_list.append(
            {
                "slug": slug,
                "name": _slug_to_display_name(slug),
                "description": topic.description,
                "confirmed_by": topic.confirmed_by,
                "confirmed_at": topic.confirmed_at,
                "created_by": topic.created_by,
                "updated_by": topic.updated_by,
                "subtopics": subtopics_list,
            }
        )

    if topics_list:
        repo.batch_upsert(topics_list, taxonomy_type)


def save_taxonomy_to_db(
    repo: TaxonomyRepository, taxonomy: dict[str, TaxonomyTopic],
) -> None:
    """Append-only upsert of user taxonomy topics."""
    _save_taxonomy_to_db(repo, taxonomy, taxonomy_type="user")


def save_template_taxonomy_to_db(
    repo: TaxonomyRepository, taxonomy: dict[str, TaxonomyTopic],
) -> None:
    """Append-only upsert of bot taxonomy topics."""
    _save_taxonomy_to_db(repo, taxonomy, taxonomy_type="bot")


# ── Derived bot taxonomy constants (from eb1_taxonomy_topics where type=bot) ──

BOT_TAXONOMY: dict[str, str] = {}
BOT_KNOWN_SUBTOPICS: dict[str, set[str]] = {}
BOT_SUBTOPIC_DESCRIPTIONS: dict[str, dict[str, str]] = {}
BOT_TOPIC_CONFIRMED: dict[str, str | None] = {}
BOT_SUBTOPIC_CONFIRMED: dict[str, dict[str, str | None]] = {}

_template_taxonomy_loaded_at = None  # datetime | None

_BOT_TARGETS = (
    BOT_TAXONOMY, BOT_KNOWN_SUBTOPICS, BOT_SUBTOPIC_DESCRIPTIONS,
    BOT_TOPIC_CONFIRMED, BOT_SUBTOPIC_CONFIRMED,
)


def init_template_taxonomy(repo: TaxonomyRepository) -> None:
    """Load template taxonomy from PG and populate BOT_* constants.

    Must be called once at pipeline startup alongside ``init_taxonomy(repo)``.
    Safe to call multiple times.
    """
    global _template_taxonomy_loaded_at
    from datetime import datetime, timezone

    taxonomy = load_template_taxonomy_from_db(repo)
    _populate_taxonomy_dicts(taxonomy, _BOT_TARGETS)
    _template_taxonomy_loaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    log.info("[config] Loaded %d bot topics from eb1_taxonomy_topics (type=bot)", len(taxonomy))

    # ── Global uniqueness check ───────────────────────────────────────
    # ZERO duplicate slugs across both taxonomies. Every topic and every
    # subtopic must be globally unique — no slug may appear anywhere
    # else as a topic or subtopic in either taxonomy.  Fail fast.
    if INITIAL_TAXONOMY:
        user_slugs: dict[str, str] = {}
        for t in INITIAL_TAXONOMY:
            user_slugs[t] = f"topic '{t}'"
            for s in KNOWN_SUBTOPICS.get(t, set()):
                if s in user_slugs:
                    raise RuntimeError(
                        f"Intra-taxonomy uniqueness violation: "
                        f"'{s}' is both {user_slugs[s]} and "
                        f"subtopic under '{t}' in eb1_taxonomy_topics."
                    )
                user_slugs[s] = f"subtopic '{s}' under '{t}'"

        bot_slugs: dict[str, str] = {}
        for t in BOT_TAXONOMY:
            bot_slugs[t] = f"topic '{t}'"
            for s in BOT_KNOWN_SUBTOPICS.get(t, set()):
                if s in bot_slugs:
                    raise RuntimeError(
                        f"Intra-taxonomy uniqueness violation: "
                        f"'{s}' is both {bot_slugs[s]} and "
                        f"subtopic under '{t}' in eb1_taxonomy_topics (type=bot)."
                    )
                bot_slugs[s] = f"subtopic '{s}' under '{t}'"

        overlap = set(user_slugs.keys()) & set(bot_slugs.keys())
        if overlap:
            details = [
                f"  '{s}': user={user_slugs[s]}, bot={bot_slugs[s]}"
                for s in sorted(overlap)
            ]
            raise RuntimeError(
                "Global taxonomy uniqueness violation — "
                "slug(s) exist in BOTH taxonomies:\n"
                + "\n".join(details)
                + "\nEvery topic and subtopic must be globally "
                "unique across user and bot taxonomies in eb1_taxonomy_topics."
            )


# ── Taxonomy freshness checking ───────────────────────────────────────────────


def _refresh_if_stale(repo: TaxonomyRepository, type_filter: str, loaded_at, init_fn) -> bool:
    """Reload taxonomy if external changes detected since last load."""
    if loaded_at is None:
        init_fn(repo)
        return True
    latest = repo.get_max_updated_at(type_filter)
    if latest is not None:
        if latest.tzinfo is not None:
            latest = latest.replace(tzinfo=None)
        if latest > loaded_at:
            init_fn(repo)
            return True
    return False


def refresh_taxonomy_if_stale(repo: TaxonomyRepository) -> bool:
    return _refresh_if_stale(repo, "user", _taxonomy_loaded_at, init_taxonomy)


def refresh_template_taxonomy_if_stale(repo: TaxonomyRepository) -> bool:
    return _refresh_if_stale(repo, "bot", _template_taxonomy_loaded_at, init_template_taxonomy)


# ── analyzer.toml ──────────────────────────────────────────────────────────────


def load_analyzer_config() -> AnalyzerConfig:
    """Load and parse pipeline/config/analyzer.toml."""
    with open(_CONFIG_DIR / "analyzer.toml", "rb") as f:
        raw = tomllib.load(f)

    a    = raw["analyzer"]
    r    = raw.get("routing", {})
    p    = raw["pipeline"]
    cols = raw.get("collections", {})

    return AnalyzerConfig(
        model=a["model"],
        prompt_version=a.get("prompt_version", "latest"),
        bot_prompt_version=a.get("bot_prompt_version", "bot_v1"),
        temperature=a.get("temperature", 0.1),
        base_url=a.get("base_url", ""),
        drop_existing=a["drop_existing"],
        drop_reviewed=a["drop_reviewed"],
        seg_concurrency=a.get("concurrency", 4),
        benchmark_mode=a.get("benchmark_mode", False),
        window_size=a.get("window_size", 0),
        bot_gap_seconds=a.get("bot_gap_seconds", 60),
        user_window_days=a.get("user_window_days", 7),
        pure_llm=a.get("pure_llm", False),
        cluster_confidence_threshold=r.get("cluster_confidence_threshold", 0.6),
        template_match_threshold=r.get("template_match_threshold", 0.8),
        user_limit=p["user_limit"],
        relabel=p.get("relabel", False),
        col_input_user=cols.get("input_user", "users"),
        col_input_chat=cols.get("input_chat", "sms_chats"),
        col_input_chat_message=cols.get("input_chat_message", "sms_chat_messages"),
        col_input_matching=cols.get("input_matching", "matchings"),
        col_input_message_template=cols.get("input_message_template", "message_templates"),
        col_output_chat_segment=cols.get("output_chat_segment", "sms_chat_segments"),
        col_output_matching_signal=cols.get("output_matching_signal", "matching_signals"),
        col_output_template_classification=cols.get(
            "output_template_classification",
            "message_template_classifications",
        ),
        col_output_chat_taxonomy=cols.get(
            "output_chat_taxonomy",
            "sms_chat_taxonomy",
        ),
    )


# ── clustering.toml ────────────────────────────────────────────────────────────


def load_clustering_config() -> ClusteringConfig:
    """Load and parse pipeline/config/clustering.toml."""
    with open(_CONFIG_DIR / "clustering.toml", "rb") as f:
        raw = tomllib.load(f)

    e   = raw["embedder"]
    c   = raw["clusterer"]

    return ClusteringConfig(
        embedder_model=e["model"],
        cache_dir=e["cache_dir"],
        batch_size=e["batch_size"],
        umap_n_components=c["umap_n_components"],
        umap_n_neighbors=c["umap_n_neighbors"],
        umap_min_dist=c["umap_min_dist"],
        hdbscan_min_cluster_size=c["hdbscan_min_cluster_size"],
        hdbscan_min_samples=c["hdbscan_min_samples"],
    )


# ── benchmark.toml ────────────────────────────────────────────────────────────


@dataclass
class BenchmarkRun:
    model: str
    temperature: float
    base_url: str  # empty = local Ollama; URL = Vercel/OpenAI-compatible
    user_prompt: str = "latest"
    bot_prompt: str = "bot_v1"
    summary: str = ""  # per-model description (stored in eb1_benchmark_runs)
    parameters: dict | None = None  # extra model params (top_p, etc.)


@dataclass
class BenchmarkConfig:
    group_id: str            # group name — shared across all models
    user_sample: float       # 0.0–1.0 fraction of reviewed users to benchmark (1.0 = all)
    cluster: bool  # run HDBSCAN after each LLM run
    user_prompt: str = "latest"   # global default for user prompt
    bot_prompt: str = "bot_v1"    # global default for bot prompt
    type: str = ""           # e.g. 'model_benchmark', 'hyperparameter_search'
    objective: str = ""      # what this group tests
    runs: list[BenchmarkRun] = field(default_factory=list)


def load_benchmark_config() -> BenchmarkConfig:
    """Load pipeline/config/benchmark.toml.

    Returns BenchmarkConfig with run metadata, user_sample, cluster flag, and runs.
    Returns empty config if file is missing.
    """
    path = _CONFIG_DIR / "benchmark.toml"
    if not path.exists():
        return BenchmarkConfig(run_id="", user_sample=1.0, cluster=False)
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    run_id = raw.get("group_id", raw.get("run_id", ""))
    user_sample = raw.get("user_sample", 1.0)
    cluster = raw.get("cluster", False)
    bench_type = raw.get("type", "")
    objective = raw.get("objective", "")
    global_user_prompt = raw.get("user_prompt", raw.get("prompt", "latest"))
    global_bot_prompt = raw.get("bot_prompt", "bot_v1")
    global_temperature = raw.get("temperature", 0.0)
    global_base_url = raw.get("base_url", "")
    runs = [
        BenchmarkRun(
            model=r["model"],
            temperature=r.get("temperature", global_temperature),
            base_url=r.get("base_url", global_base_url),
            user_prompt=r.get("user_prompt", global_user_prompt),
            bot_prompt=r.get("bot_prompt", global_bot_prompt),
            summary=r.get("summary", ""),
            parameters=r.get("parameters"),
        )
        for r in raw.get("run", [])
    ]
    return BenchmarkConfig(
        group_id=run_id,
        user_sample=user_sample,
        cluster=cluster,
        user_prompt=global_user_prompt,
        bot_prompt=global_bot_prompt,
        type=bench_type,
        objective=objective,
        runs=runs,
    )
