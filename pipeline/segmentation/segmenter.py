"""
Step 1: Segmenter

Each user has exactly one sms_chats document containing all their sms_chat_messages.
This step fetches that single chat session, feeds all its messages to the LLM
to identify topic-switch boundaries, and produces one or more sms_chat_segments
documents per user.

Each identified segment becomes an sms_chat_segments document in MongoDB with:
  userId, chat, chatMessages, chatStartedAt, createdAt

chatMessages holds the exact sms_chat_messages._id references that make up the
segment — no text is copied.  chat is a single sms_chats._id since 1 user = 1
sms_chats document.

All classification fields (topic, cluster, etc.) are null until the Analyzer runs.

Config knobs (pipeline/config/analyzer.toml):
  drop_existing = true  → drop only UNREVIEWED segments (true_topic/true_sub_topic = null)
  drop_reviewed = true  → DEPRECATED — reviewed segments are immutable; flag is ignored

Run standalone:
    uv run python -m pipeline --step segment
"""

import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from pipeline.config.loader import (
    BOT_KNOWN_SUBTOPICS,
    BOT_SUBTOPIC_CONFIRMED,
    BOT_SUBTOPIC_DESCRIPTIONS,
    BOT_TAXONOMY,
    BOT_TOPIC_CONFIRMED,
    INITIAL_TAXONOMY,
    KNOWN_SUBTOPICS,
    SUBTOPIC_CONFIRMED,
    SUBTOPIC_DESCRIPTIONS,
    TOPIC_CONFIRMED,
    AnalyzerConfig,
    refresh_taxonomy_if_stale,
    refresh_template_taxonomy_if_stale,
)
from pipeline.prompts.analyzer import load_prompt
from pipeline.segmentation.bot_processor import (
    _build_bot_only_segments,
    _load_template_classifications,
)
from pipeline.segmentation.deterministic_rules import (
    classify_first_automated_chunk,
    classify_scheduling_chunk,
    is_first_automated_chunk,
    is_scheduling_chunk,
)
from pipeline.segmentation.pool_taxonomy import (
    build_pool_taxonomy_lines,
    get_user_pool,
)
from pipeline.segmentation.preprocessing import (
    _is_imessage_reaction,
    _normalize_slug,
    _preprocess_for_llm,
    _slug_to_display_name,
)
from pipeline.segmentation.subtopic_validator import batch_validate_subtopics
from pipeline.segmentation.windowing import (
    _build_context_string,
    _build_flat_history,
    _load_previous_segments,
    _pre_segment,
    _window_chat_ids,
    _window_messages,
)

log = logging.getLogger(__name__)

_BOT_TO_USER_REMAP = {
    "non_event_match_notification": "post_match_inquiry",
    "non_event_onboarding":         "pre_match_inquiry",
    "status_notification":           "pre_match_inquiry",
    "promotion_notification":        "pre_match_inquiry",
}
_DEFAULT_USER_TOPIC = "post_match_inquiry"
_DEFAULT_BOT_TOPIC = "status_notification"


def _remap_topic(
    topic: str,
    sub_topic: str,
    user_id: Any,
    direction: str,
    remap_repo=None,
    config_id: int | None = None,
) -> tuple[str, str]:
    """Remap a topic to the correct taxonomy and log to PostgreSQL.

    direction: 'bot_to_user' or 'user_to_bot'
    """
    if direction == "bot_to_user":
        remapped = _BOT_TO_USER_REMAP.get(topic)
        if remapped is None and topic.startswith("event_"):
            remapped = "event_inquiry"
        if remapped is None:
            remapped = _DEFAULT_USER_TOPIC
    else:
        remapped = _DEFAULT_BOT_TOPIC

    log.warning(
        "Taxonomy remap (%s): user=%s '%s/%s' → '%s/%s'",
        direction, user_id, topic, sub_topic, remapped, sub_topic,
    )

    if remap_repo is not None:
        try:
            remap_repo.log_remap(
                user_id=str(user_id),
                direction=direction,
                original_topic=topic,
                original_sub_topic=sub_topic,
                remapped_topic=remapped,
                config_id=config_id,
            )
        except Exception:
            log.debug("Failed to log taxonomy remap to PG", exc_info=True)

    return remapped, sub_topic


def _has_taxonomy_violations(segments: list[dict], bot_only: bool) -> bool:
    """Check if any segment carries a topic from the wrong taxonomy."""
    for seg in segments:
        topic = seg.get("topic")
        if not topic:
            continue
        if not bot_only and topic in BOT_TAXONOMY and topic not in INITIAL_TAXONOMY:
            return True
        if bot_only and topic in INITIAL_TAXONOMY and topic not in BOT_TAXONOMY:
            return True
    return False


# ── Public entry point ────────────────────────────────────────────────────────


def run_segmenter(
    input_db: Database,
    output_db: Database | None,
    cfg: AnalyzerConfig,
    limit: int | None = None,
    base_url: str = "",
    user_ids: list | None = None,
    segment_repo=None,
    signal_repo=None,
    taxonomy_repo=None,
    template_repo=None,
    config_id: int | None = None,
    remap_repo=None,
) -> dict[str, int]:
    """
    Segment all users' Chat Histories into sms_chat_segments documents.

    input_db  — source of users / chats / sms_chat_messages (may be PROD)
    output_db — target for sms_chat_segments reads and writes (always local)
    user_ids  — when set, process only these specific user IDs (skip
                matching_signals sampling). Used by --rerun-user.

    LLM calls are parallelised with ThreadPoolExecutor (cfg.seg_concurrency workers).
    pymongo is thread-safe; each worker does its own insert after the LLM call.

    Returns:
        counts: users_processed, users_skipped, segments_created.
    """
    if config_id is None:
        raise ValueError(
            "config_id is required. Call PipelineConfigRepository.get_or_create() "
            "before running the segmenter."
        )

    client = None  # reserved for future local LLM support

    # Load versioned prompts — separate prompts for user-engaged and bot-only
    prompt = load_prompt(cfg.prompt_version, kind="user")
    system_prompt = prompt.build_system_prompt()
    bot_prompt = load_prompt(cfg.bot_prompt_version, kind="bot")
    bot_system_prompt = bot_prompt.build_system_prompt()
    log.info("Prompt version: %s (bot: %s)", cfg.prompt_version, cfg.bot_prompt_version)

    if cfg.drop_existing and not user_ids:
        if cfg.drop_reviewed:
            log.critical(
                "drop_reviewed=true IGNORED — reviewed segments are immutable. "
                "Only unreviewed segments will be cleared."
            )
        deleted = segment_repo.delete_unreviewed_all()
        log.info(
            "drop_existing=true — cleared %d unreviewed sms_chat_segments documents.",
            deleted,
        )

    # Load classified templates for bot-only segment enrichment (read-only, thread-safe)
    classified_templates = _load_template_classifications(template_repo)
    log.info(
        "Loaded %d classified templates for bot-only matching.",
        len(classified_templates),
    )

    # Determine which users to process
    if user_ids:
        all_users = [{"_id": uid} for uid in user_ids]
        log.info("Rerun mode: processing %d specific user(s).", len(all_users))
    else:
        # Sample users from matching_signals (PG — read-only)
        sampled_user_ids = signal_repo.distinct_users()
        if not sampled_user_ids:
            log.warning("No matching_signals found. Run --step signal first.")
            return {"users_processed": 0, "users_skipped": 0, "segments_created": 0}
        log.info("Sampled %d distinct users from matching_signals.", len(sampled_user_ids))
        all_users = [{"_id": uid} for uid in sampled_user_ids]
        if limit:
            all_users = all_users[:limit]

    # All prompt versions use the v2+ path which handles already-processed users
    # via incremental mode inside _process_one (new messages only + context from
    # previous segments).
    to_process = [u["_id"] for u in all_users]
    users_skipped = 0

    log.info(
        "Segmenter: %d users to process, %d skipped (already done), concurrency=%d",
        len(to_process), users_skipped, cfg.seg_concurrency,
    )

    # Counters updated from worker threads
    users_processed = 0
    users_no_chat = 0
    segments_created = 0
    counter_lock = threading.Lock()

    def _process_one(user_id: Any) -> None:
        nonlocal users_no_chat, users_skipped
        # Convert string user IDs (from PG) to ObjectId for MongoDB PROD queries
        mongo_uid = ObjectId(user_id) if isinstance(user_id, str) else user_id
        chat = input_db[cfg.col_input_chat].find_one({"user": mongo_uid})
        if not chat:
            log.warning("User %s has no sms_chat in input DB — skipping.", user_id)
            with counter_lock:
                users_no_chat += 1
            return

        all_msgs, chat_id_per_msg = _build_flat_history(input_db, chat, cfg)
        if not all_msgs:
            return

        # ── P3: Pool-specific taxonomy ──────────────────────────────────
        user_doc = input_db[cfg.col_input_user].find_one({"_id": mongo_uid})
        user_pool = get_user_pool(user_doc)

        # User taxonomy — filtered by pool (P3)
        taxonomy_lines, topic_options = build_pool_taxonomy_lines(
            INITIAL_TAXONOMY, SUBTOPIC_DESCRIPTIONS, user_pool,
        )

        # Bot taxonomy — filtered by pool (P3)
        bot_taxonomy_lines, bot_topic_options = build_pool_taxonomy_lines(
            BOT_TAXONOMY, BOT_SUBTOPIC_DESCRIPTIONS, user_pool, is_bot=True,
        )
        if not bot_taxonomy_lines:
            bot_taxonomy_lines = taxonomy_lines
            bot_topic_options = topic_options

        # Incremental mode: filter to only new messages when user already has segments.
        # Uses the latest segment's chat_ended_at as a cutoff and passes existing
        # segment summaries as LLM context for continuity.
        previous_context = ""
        msgs_to_process = all_msgs
        chat_ids_to_process = chat_id_per_msg
        is_incremental = False

        previous_context = _load_previous_segments(
            segment_repo, user_id, cfg
        )
        if previous_context:
            latest_seg = segment_repo.latest_segment_for_user(str(user_id))
            if latest_seg and latest_seg.get("chat_ended_at"):
                cutoff_ts = latest_seg["chat_ended_at"]
                # PG returns timezone-aware; MongoDB PROD timestamps are naive
                if cutoff_ts.tzinfo is not None:
                    cutoff_ts = cutoff_ts.replace(tzinfo=None)
                new_pairs = [
                    (m, c)
                    for m, c in zip(all_msgs, chat_id_per_msg)
                    if (m.get("createdAt") or cutoff_ts) > cutoff_ts
                ]
                if not new_pairs:
                    log.debug(
                        "User %s — no new messages since last segment; skipping.",
                        user_id,
                    )
                    with counter_lock:
                        users_skipped += 1
                    return
                msgs_to_process, chat_ids_to_process = zip(*new_pairs)
                msgs_to_process = list(msgs_to_process)
                chat_ids_to_process = list(chat_ids_to_process)
                is_incremental = True
                log.info(
                    "User %s — incremental mode: %d new messages (of %d total).",
                    user_id, len(msgs_to_process), len(all_msgs),
                )

        segments: list[dict] = []
        running_context = previous_context

        if cfg.pure_llm:
            # ── Pure LLM mode: skip all preprocessing ─────────────
            # Send ALL messages through V3 user prompt as a single stream.
            # No bot/user splitting, no template matching, no bot-only routing.
            log.info(
                "User %s — PURE LLM mode: %d message(s), skipping pre-segmentation",
                user_id, len(msgs_to_process),
            )

            windows = _window_messages(msgs_to_process, cfg.window_size)
            win_chat_id_lists = _window_chat_ids(
                chat_ids_to_process, msgs_to_process, cfg.window_size,
            )

            for win_idx, (win_msgs, win_cids) in enumerate(
                zip(windows, win_chat_id_lists)
            ):
                pp_msgs, pp_cids, idx_map, absorbed = _preprocess_for_llm(
                    win_msgs, win_cids,
                )
                history_str, included_pp, _ = _format_history(
                    pp_msgs, pp_cids, offset=0,
                )
                n = len(included_pp)

                user_prompt = prompt.build_user_prompt(
                    n_msgs=n,
                    history=history_str,
                    taxonomy=taxonomy_lines,
                    topic_options=topic_options,
                    previous_segments=running_context,
                )
                win_segments = _call_and_build(
                    client, cfg, system_prompt, user_prompt, n, base_url,
                    user_id, win_msgs, win_cids, idx_map, absorbed,
                    taxonomy_repo=taxonomy_repo, remap_repo=remap_repo,
                    config_id=config_id, pure_llm=True,
                    fallback_label=f"pure LLM window {win_idx}",
                )

                segments.extend(win_segments)

                if win_segments:
                    running_context = _build_context_string(
                        running_context, win_segments, 0,
                    )

        else:
            # ── Normal mode: two-pass pre-segmentation + routing ──
            chunks = _pre_segment(
                msgs_to_process,
                chat_ids_to_process,
                bot_gap_seconds=cfg.bot_gap_seconds,
                user_window_days=cfg.user_window_days,
            )
            n_bot = sum(1 for c in chunks if c.kind == "bot_only")
            n_engaged = sum(1 for c in chunks if c.kind == "user_engaged")
            log.info(
                "User %s — %s: %d message(s) → %d chunks (%d bot-only, %d user-engaged)",
                user_id,
                "incremental" if is_incremental else "backfill",
                len(msgs_to_process),
                len(chunks),
                n_bot,
                n_engaged,
            )

            # Identify bot-only chunks that precede a user-engaged chunk.
            # These will be prepended into the user-engaged LLM call so the
            # LLM sees bot prompts + user responses together (one segment).
            # Only standalone bot chunks (no following user response) go
            # through the bot-only prompt path.
            prepended_bot_chunks: set[int] = set()
            for c in chunks:
                if c.kind == "user_engaged" and c.preceding_bot_chunk is not None:
                    prepended_bot_chunks.add(id(c.preceding_bot_chunk))

            # ── P4: Track whether first scheduling has been seen ──
            has_seen_scheduling = False

            for chunk_idx, chunk in enumerate(chunks):
                if chunk.kind == "bot_only":
                    if id(chunk) in prepended_bot_chunks:
                        log.debug(
                            "User %s — skipping bot-only chunk (%d msgs) "
                            "— will prepend to following user-engaged chunk.",
                            user_id, len(chunk.messages),
                        )
                        continue

                    # ── P1: Skip LLM for first automated segment ──
                    if is_first_automated_chunk(chunk, chunk_idx):
                        p1_segs = classify_first_automated_chunk(user_id, chunk)
                        if p1_segs:
                            segments.extend(p1_segs)
                            running_context = _build_context_string(
                                running_context, p1_segs, 0,
                            )
                            continue

                    # ── P4: Deterministic scheduling rules ──
                    if is_scheduling_chunk(chunk):
                        p4_segs = classify_scheduling_chunk(
                            user_id, chunk,
                            is_first_scheduling=not has_seen_scheduling,
                        )
                        if p4_segs:
                            has_seen_scheduling = True
                            segments.extend(p4_segs)
                            running_context = _build_context_string(
                                running_context, p4_segs, 0,
                            )
                            continue

                    # Standalone bot-only chunk (no user response follows).
                    # Process through bot prompt path.
                    all_automated = all(
                        m.get("type") == "automated"
                        for m in chunk.messages
                    )
                    template_matched = False
                    if all_automated:
                        bot_segs = _build_bot_only_segments(
                            user_id, chunk,
                            templates=classified_templates,
                            template_match_threshold=cfg.template_match_threshold,
                        )
                        # Only use template result if a topic was actually assigned
                        if bot_segs and bot_segs[0].get("topic") is not None:
                            segments.extend(bot_segs)
                            template_matched = True
                            running_context = _build_context_string(
                                running_context, bot_segs, 0,
                            )
                        else:
                            log.debug(
                                "User %s — automated chunk had no template match; "
                                "routing to LLM.",
                                user_id,
                            )

                    if not template_matched:
                        # Send to LLM with bot prompt + bot taxonomy
                        orig_msgs = list(chunk.messages)
                        orig_cids = list(chunk.chat_ids)
                        pp_msgs, pp_cids, idx_map, absorbed = _preprocess_for_llm(
                            orig_msgs, orig_cids,
                        )
                        history_str, included_pp, _ = _format_history(
                            pp_msgs, pp_cids, offset=0,
                        )
                        n = len(included_pp)
                        user_prompt = bot_prompt.build_user_prompt(
                            n_msgs=n,
                            history=history_str,
                            taxonomy=bot_taxonomy_lines,
                            topic_options=bot_topic_options,
                            previous_segments=running_context,
                        )
                        win_segments = _call_and_build(
                            client, cfg, bot_system_prompt, user_prompt,
                            n, base_url, user_id, orig_msgs, orig_cids,
                            idx_map, absorbed,
                            taxonomy_repo=taxonomy_repo, remap_repo=remap_repo,
                            config_id=config_id, bot_only=True,
                            fallback_label="bot-only chunk",
                        )
                        segments.extend(win_segments)
                        if win_segments:
                            running_context = _build_context_string(
                                running_context, win_segments, 0,
                            )

                elif chunk.kind == "user_engaged":
                    # Prepend preceding bot messages so the LLM sees bot
                    # prompts + user responses together as one interaction.
                    llm_messages = list(chunk.messages)
                    llm_chat_ids = list(chunk.chat_ids)
                    if chunk.preceding_bot_chunk is not None:
                        llm_messages = (
                            list(chunk.preceding_bot_chunk.messages)
                            + llm_messages
                        )
                        llm_chat_ids = (
                            list(chunk.preceding_bot_chunk.chat_ids)
                            + llm_chat_ids
                        )

                    # Apply existing windowing within this combined chunk
                    windows = _window_messages(llm_messages, cfg.window_size)
                    win_chat_id_lists = _window_chat_ids(
                        llm_chat_ids, llm_messages, cfg.window_size,
                    )

                    for win_idx, (win_msgs, win_cids) in enumerate(
                        zip(windows, win_chat_id_lists)
                    ):
                        pp_msgs, pp_cids, idx_map, absorbed = _preprocess_for_llm(
                            win_msgs, win_cids,
                        )
                        history_str, included_pp, _ = _format_history(
                            pp_msgs, pp_cids, offset=0,
                        )
                        n = len(included_pp)

                        user_prompt = prompt.build_user_prompt(
                            n_msgs=n,
                            history=history_str,
                            taxonomy=taxonomy_lines,
                            topic_options=topic_options,
                            previous_segments=running_context,
                        )
                        win_segments = _call_and_build(
                            client, cfg, system_prompt, user_prompt, n, base_url,
                            user_id, win_msgs, win_cids, idx_map, absorbed,
                            taxonomy_repo=taxonomy_repo, remap_repo=remap_repo,
                            config_id=config_id,
                            fallback_label="user-engaged chunk",
                        )

                        segments.extend(win_segments)

                        if win_segments:
                            running_context = _build_context_string(
                                running_context, win_segments, 0,
                            )

        if not segments:
            return

        # ── P2: Validate new subtopics against GT ──────────────────────
        gt_segments = None
        if segment_repo is not None:
            try:
                gt_segments = segment_repo.find_reviewed_for_user(str(user_id))
            except Exception:
                log.debug("P2: Could not load GT segments for user %s", user_id)
        batch_validate_subtopics(
            segments, KNOWN_SUBTOPICS,
            gt_segments=gt_segments,
        )

        # Post-segmentation invariant 1: no duplicate message IDs in any segment
        for seg in segments:
            msg_ids = seg["chat_messages"]
            if len(msg_ids) != len(set(msg_ids)):
                raise ValueError(
                    f"Duplicate chat_messages in segment for user {user_id}: "
                    f"{len(msg_ids)} total, {len(set(msg_ids))} unique"
                )

        # Post-segmentation invariant 2: every processed message in at least one segment
        segmented_ids: set[str] = set()
        for seg in segments:
            segmented_ids.update(seg["chat_messages"])
        expected_ids = {str(m["_id"]) for m in msgs_to_process}
        missing = expected_ids - segmented_ids
        if missing:
            raise ValueError(
                f"Message loss for user {user_id}: "
                f"{len(missing)}/{len(expected_ids)} messages not in any segment"
            )

        for seg in segments:
            seg["config_id"] = config_id

        try:
            segment_repo.insert_many(segments)
        except Exception:
            seg_ids = [s["id"] for s in segments if "id" in s]
            if seg_ids:
                try:
                    segment_repo.delete_by_ids(seg_ids)
                    log.warning(
                        "User %s: cleaned up %d partial segments after write failure.",
                        user_id, len(seg_ids),
                    )
                except Exception:
                    log.error(
                        "User %s: FAILED to clean up partial segments after write failure. "
                        "Manual cleanup may be needed.",
                        user_id, exc_info=True,
                    )
            raise
        log.info("User %s → %d segment(s)", user_id, len(segments))

        nonlocal users_processed, segments_created
        with counter_lock:
            users_processed += 1
            segments_created += len(segments)

    # Process in batches so the main thread can check taxonomy freshness between
    # batches. All workers in a batch complete before the freshness check runs,
    # so init_taxonomy's .clear() + .update() never races with worker reads.
    FRESHNESS_BATCH = max(cfg.seg_concurrency * 4, 20)

    with ThreadPoolExecutor(max_workers=cfg.seg_concurrency) as pool:
        for batch_start in range(0, len(to_process), FRESHNESS_BATCH):
            # Check taxonomy freshness between batches (main thread only)
            if batch_start > 0:
                refreshed = refresh_taxonomy_if_stale(taxonomy_repo)
                refreshed |= refresh_template_taxonomy_if_stale(taxonomy_repo)
                if refreshed:
                    log.info(
                        "Taxonomy cache refreshed (external changes detected) "
                        "before batch starting at user %d/%d.",
                        batch_start, len(to_process),
                    )

            batch = to_process[batch_start:batch_start + FRESHNESS_BATCH]
            futures = {pool.submit(_process_one, uid): uid for uid in batch}
            for future in as_completed(futures):
                exc = future.exception()
                if exc:
                    uid = futures[future]
                    log.error("Worker failed for user %s: %s", uid, exc, exc_info=exc)

    log.info(
        "Segmenter done. processed=%d skipped=%d no_chat=%d segments=%d",
        users_processed, users_skipped, users_no_chat, segments_created,
    )
    return {
        "users_processed": users_processed,
        "users_skipped": users_skipped,
        "users_no_chat": users_no_chat,
        "segments_created": segments_created,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────


def _remap_llm_indices(
    llm_segments: list[dict],
    index_map: list[int],
) -> list[dict]:
    """Remap LLM messageIndices from preprocessed → original positions.

    After ``_preprocess_for_llm`` removes messages (e.g. bot image-only),
    the LLM's 0-based indices refer to the shorter preprocessed list.
    This function translates them back to the original message list so
    that ``_build_segments_from_llm`` can look up the correct ``_id`` refs.

    Returns a new list of segment dicts with remapped ``messageIndices``.
    """
    remapped: list[dict] = []
    for seg in llm_segments:
        seg_copy = dict(seg)
        valid_indices = []
        for i in seg["messageIndices"]:
            if i < len(index_map):
                valid_indices.append(index_map[i])
            else:
                log.warning(
                    "LLM returned out-of-bounds index %d (max=%d) — dropped.",
                    i, len(index_map) - 1,
                )
        seg_copy["messageIndices"] = valid_indices
        remapped.append(seg_copy)
    return remapped


def _format_history(
    messages: list[dict],
    chat_ids: list[Any],
    offset: int = 0,
) -> tuple[str, list[dict], list[Any]]:
    """
    Build a numbered message list for the LLM prompt.
    Includes ALL messages — no truncation (Bug 3 fix, Phase 2a).

    offset: base index added to each message number. When windowing, the
            LLM still receives 0-based indices within the window (the prompt
            says "0-based indices"), but the offset is used for logging only.
            The index displayed is local (0-based within the window) so that
            the LLM's returned messageIndices can be mapped back correctly.

    Returns (formatted_str, included_messages, included_chat_ids).
    """
    lines: list[str] = []
    for i, msg in enumerate(messages):
        lines.append(f"{i} [{msg.get('type', '?')}]: {msg.get('message', '')}")

    return "\n".join(lines), list(messages), list(chat_ids)


def _call_analyzer(
    client: Any,
    model: str,
    system_prompt: str,
    user_prompt: str,
    n_msgs: int,
    temperature: float = 0.1,
    base_url: str = "",
) -> list[dict]:
    """Call LLM and return list of segment dicts or [] on error.

    The LLM returns a JSON object with a "segments" array where each
    element carries messageIndices, summary, topic, subTopic, labelConfidence,
    and optionally sentiment, botPromptCount, and userResponseCount.

    Parses defensively — markdown fences stripped, object envelope unwrapped,
    and each segment validated for required fields before inclusion.
    """
    if n_msgs == 0:
        return []
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        if base_url:
            raw = _call_openai_compat(model, messages, temperature, base_url)
        else:
            response = client.chat(
                model=model,
                messages=messages,
                options={"temperature": temperature},
            )
            raw = response["message"]["content"]

        segments = _parse_llm_segments(raw, n_msgs)
        log.debug("LLM analyzer: parsed %d segment(s) from LLM output.", len(segments))
        return segments

    except Exception as exc:
        log.warning(
            "LLM analyzer call failed (%s) — caller will fall back to single segment.",
            exc,
        )
        return []


def _parse_llm_segments(raw: str, n_msgs: int) -> list[dict]:
    """Extract and validate the segments array from a LLM response.

    Strips markdown fences, locates the JSON object, unwraps the "segments"
    key, and validates each segment for required fields and index bounds.
    Logs diagnostics on parse failure (Architecture Invariant 11 — no silent
    swallowing).
    """
    # Strip markdown code fences if present
    cleaned = re.sub(r"```[a-z]*\n?", "", raw).strip()
    cleaned = cleaned.rstrip("```").strip()

    # Find the outermost JSON object
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        log.error(
            "LLM parse failed — no JSON object found. "
            "raw length=%d, first 500 chars: %s",
            len(raw), raw[:500],
        )
        return []

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as exc:
        log.error(
            "LLM parse failed — JSON decode error: %s. "
            "raw length=%d, first 500 chars: %s",
            exc, len(raw), raw[:500],
        )
        return []

    raw_segments = data.get("segments")
    if not isinstance(raw_segments, list):
        log.error(
            "LLM parse failed — 'segments' key missing or not a list. "
            "keys found: %s, raw length=%d, first 500 chars: %s",
            list(data.keys()), len(raw), raw[:500],
        )
        return []

    valid: list[dict] = []
    required_fields = {
        "messageIndices", "summary", "topic", "subTopic",
        "labelConfidence",
    }
    valid_sentiments = {"positive", "negative", "neutral", "mixed"}

    for i, seg in enumerate(raw_segments):
        if not isinstance(seg, dict):
            log.warning("LLM segment[%d] is not a dict — skipping.", i)
            continue
        missing = required_fields - set(seg.keys())
        if missing:
            log.warning("LLM segment[%d] missing fields %s — skipping.", i, missing)
            continue
        indices = seg.get("messageIndices")
        if not isinstance(indices, list) or not indices:
            log.warning("LLM segment[%d] has empty or invalid messageIndices — skipping.", i)
            continue
        # Validate indices are in-bounds integers
        clamped = [
            int(idx) for idx in indices
            if isinstance(idx, (int, float)) and 0 <= int(idx) < n_msgs
        ]
        if not clamped:
            log.warning(
                "LLM segment[%d] has no valid in-bounds messageIndices (n_msgs=%d) — skipping.",
                i, n_msgs,
            )
            continue
        # Normalize sentiment if present; None when absent (bot-only segments)
        raw_sentiment = seg.get("sentiment")
        if raw_sentiment is not None:
            sentiment = str(raw_sentiment).lower()
            if sentiment not in valid_sentiments:
                log.warning(
                    "LLM segment[%d] unknown sentiment %r — defaulting to 'neutral'.",
                    i, sentiment,
                )
                sentiment = "neutral"
        else:
            sentiment = None
        # Normalize labelConfidence to float in [0.0, 1.0)
        # LLM-generated confidence must never reach 1.0 (absolute certainty).
        _MAX_LLM_CONFIDENCE = 0.99
        try:
            label_confidence = float(seg.get("labelConfidence", 0.0))
            if label_confidence >= 1.0:
                log.warning(
                    "LLM segment[%d] labelConfidence=%.2f >= 1.0 — clamping to %.2f.",
                    i, label_confidence, _MAX_LLM_CONFIDENCE,
                )
            label_confidence = max(0.0, min(_MAX_LLM_CONFIDENCE, label_confidence))
        except (TypeError, ValueError):
            label_confidence = 0.0

        # Parse optional engagement counts (LLM may omit)
        bot_q_raw = seg.get("botPromptCount")
        user_a_raw = seg.get("userResponseCount")
        try:
            bot_q = max(0, int(bot_q_raw)) if bot_q_raw is not None else None
        except (TypeError, ValueError):
            bot_q = None
        try:
            user_a = max(0, int(user_a_raw)) if user_a_raw is not None else None
        except (TypeError, ValueError):
            user_a = None

        topic = _normalize_slug(str(seg.get("topic", "")))
        sub_topic = _normalize_slug(str(seg.get("subTopic", "")))

        # Guard: both topic and subTopic are mandatory
        if not topic:
            log.warning("LLM segment[%d] has empty topic — skipping.", i)
            continue
        if not sub_topic:
            log.warning(
                "LLM segment[%d] has topic '%s' but empty subTopic — skipping.",
                i, topic,
            )
            continue

        valid.append({
            "messageIndices": clamped,
            "summary": str(seg.get("summary", "")),
            "topic": topic,
            "subTopic": sub_topic,
            "sentiment": sentiment,
            "labelConfidence": label_confidence,
            "botPromptCount": bot_q,
            "userResponseCount": user_a,
        })

    return valid


def _dedup_non_user_across_segments(
    segments: list[dict],
    messages: list[dict],
) -> int:
    """Remove non-user messages that appear in multiple segments.

    User messages (type="user") may appear in multiple segments because a single
    user message can cover multiple topics.  All other types (assistant, automated,
    team, system) must appear in exactly one segment.

    When a non-user message appears in N segments, it is kept in the segment whose
    other messages are closest by index (proximity score: count of other messages
    within ±3 indices).  Tie-break: lowest segment index (LLM's primary grouping).

    Mutates *segments* in place: removes ObjectIds from ``chatMessages``,
    recalculates ``chatStartedAt``/``chatEndedAt``, and drops any segment that
    becomes empty.

    Returns the number of individual removals performed.
    """
    if not segments or not messages:
        return 0

    id_to_idx: dict = {m["_id"]: i for i, m in enumerate(messages)}
    id_to_msg: dict = {m["_id"]: m for m in messages}

    # Map each message ObjectId → list of segment indices that contain it
    mid_to_seg_indices: dict = {}
    for si, seg in enumerate(segments):
        for mid in seg["chat_messages"]:
            mid_to_seg_indices.setdefault(mid, []).append(si)

    removed = 0
    affected_seg_indices: set[int] = set()
    seg_drop: dict[int, set] = {}

    for mid, seg_indices in mid_to_seg_indices.items():
        if len(seg_indices) <= 1:
            continue

        msg = id_to_msg.get(mid)
        if msg is None:
            continue
        if msg.get("type") == "user":
            continue  # user messages allowed in multiple segments

        idx = id_to_idx[mid]

        # Score each candidate segment by proximity: how many of its OTHER
        # messages fall within ±3 indices of this message?
        best_si = seg_indices[0]
        best_score = -1
        for si in seg_indices:
            other_indices = [
                id_to_idx[m]
                for m in segments[si]["chat_messages"]
                if m in id_to_idx and m != mid
            ]
            score = sum(1 for oi in other_indices if abs(oi - idx) <= 3)
            if score > best_score:
                best_score = score
                best_si = si

        # Record which message to drop from every segment except the best
        for si in seg_indices:
            if si != best_si:
                seg_drop.setdefault(si, set()).add(mid)
                affected_seg_indices.add(si)
                removed += 1

    # Apply drops in bulk — O(n) list comprehension per affected segment
    for si, drop_set in seg_drop.items():
        segments[si]["chat_messages"] = [
            mid for mid in segments[si]["chat_messages"] if mid not in drop_set
        ]

    # Recalculate timestamps for affected segments and drop empties
    for si in affected_seg_indices:
        seg = segments[si]
        if not seg["chat_messages"]:
            continue  # will be pruned below
        seg_msgs = [id_to_msg[m] for m in seg["chat_messages"] if m in id_to_msg]
        timestamps = [m.get("createdAt") for m in seg_msgs if m.get("createdAt") is not None]
        if timestamps:
            seg["chat_started_at"] = min(timestamps)
            seg["chat_ended_at"] = max(timestamps)

    segments[:] = [s for s in segments if s["chat_messages"]]

    if removed:
        log.info("Dedup: removed %d non-user duplicate(s) across segments.", removed)

    return removed


def _find_bot_failure_indices(messages: list[dict]) -> set[int]:
    """Find indices of user messages that received no bot reply.

    A user message at index i is a "bot failure" when:
    - No assistant/automated/team message follows before the next
      user message or end of the conversation, AND
    - No [Tool Call] noReply system message explains the silence.
    - The message is NOT an iMessage reaction (tapback) — reactions
      don't expect a bot reply.

    Returns a set of 0-based message indices.
    """
    _reply_types = {"assistant", "automated", "team"}
    failures: set[int] = set()
    for i, msg in enumerate(messages):
        if msg.get("type") != "user":
            continue
        if _is_imessage_reaction(msg):
            continue  # reactions don't expect a bot reply
        got_reply = False
        has_noreply = False
        for j in range(i + 1, len(messages)):
            next_type = messages[j].get("type", "")
            if next_type == "user":
                break
            if next_type in _reply_types:
                got_reply = True
                break
            if (
                next_type == "system"
                and messages[j].get("message") == "[Tool Call] noReply"
            ):
                has_noreply = True
                break
        if not got_reply and not has_noreply:
            failures.add(i)
    return failures


_taxonomy_lock = threading.Lock()


def _ensure_taxonomy_entry(
    taxonomy_repo,
    topic: str,
    sub_topic: str,
    cfg,
    *,
    bot_only: bool = False,
) -> None:
    """Check if topic/subtopic exists in the relevant taxonomy; upsert if missing.

    Requires a non-empty topic. If topic is empty/falsy, returns immediately.
    If sub_topic is empty, only the topic is checked/upserted.

    Called for EVERY segment the LLM produces. Routes to the correct taxonomy
    based on ``bot_only``:

    - ``bot_only=False`` (default): checks ``INITIAL_TAXONOMY`` / ``KNOWN_SUBTOPICS``
      and writes to ``sms_chat_taxonomy`` with ``type: "user"``.
    - ``bot_only=True``: checks ``BOT_TAXONOMY`` / ``BOT_KNOWN_SUBTOPICS`` and writes
      to ``sms_chat_taxonomy`` with ``type: "bot"``. This covers unmatched automated
      messages that fell through to the LLM — new bot topics need ``confirmedBy: null``
      just like user topics.

    Thread-safe — segmenter runs concurrent LLM workers.
    """
    if bot_only:
        topic_dict = BOT_TAXONOMY
        subs_dict = BOT_KNOWN_SUBTOPICS
        sub_desc_dict = BOT_SUBTOPIC_DESCRIPTIONS
        topic_conf_dict = BOT_TOPIC_CONFIRMED
        sub_conf_dict = BOT_SUBTOPIC_CONFIRMED
        taxonomy_type = "bot"
        label = "template taxonomy"
    else:
        topic_dict = INITIAL_TAXONOMY
        subs_dict = KNOWN_SUBTOPICS
        sub_desc_dict = SUBTOPIC_DESCRIPTIONS
        topic_conf_dict = TOPIC_CONFIRMED
        sub_conf_dict = SUBTOPIC_CONFIRMED
        taxonomy_type = "user"
        label = "taxonomy"

    if not topic:
        return  # No topic — nothing to upsert

    # Identify the OTHER taxonomy's in-memory dicts for cross-checks.
    other_topic_dict = INITIAL_TAXONOMY if bot_only else BOT_TAXONOMY
    other_subs_dict = KNOWN_SUBTOPICS if bot_only else BOT_KNOWN_SUBTOPICS

    topic_is_new = topic not in topic_dict
    sub_is_new = sub_topic and sub_topic not in subs_dict.get(topic, set())

    if not topic_is_new and not sub_is_new:
        return  # Both exist in the correct taxonomy — nothing to do

    with _taxonomy_lock:
        # Double-check after acquiring lock (another thread may have just added it)
        topic_is_new = topic not in topic_dict
        sub_is_new = sub_topic not in subs_dict.get(topic, set())

        # ── Global uniqueness constraint ──────────────────────────────
        # ZERO duplicates across both taxonomies. Every topic and
        # subtopic slug must be globally unique.

        # Collect all slugs from the OTHER taxonomy for O(1) lookup
        other_all_slugs: set[str] = set(other_topic_dict.keys())
        for _subs in other_subs_dict.values():
            other_all_slugs.update(_subs)

        # Block new topic if slug exists anywhere in other taxonomy
        if topic_is_new and topic in other_all_slugs:
            other_label = "user" if bot_only else "bot/template"
            log.error(
                "Global uniqueness violation: '%s' already exists "
                "in %s taxonomy — refusing to create in %s.",
                topic, other_label, label,
            )
            return

        # Block new subtopic if slug exists anywhere in other taxonomy
        if sub_is_new and sub_topic and sub_topic in other_all_slugs:
            other_label = "user" if bot_only else "bot/template"
            log.error(
                "Global uniqueness violation: subtopic '%s' already "
                "exists in %s taxonomy — refusing to create in %s.",
                sub_topic, other_label, label,
            )
            return

        # Also check: does the slug collide with topics/subtopics
        # in our OWN taxonomy under a DIFFERENT parent?
        # (subtopic slug must not duplicate any topic slug in either taxonomy)
        all_own_topics: set[str] = set(topic_dict.keys())
        if sub_is_new and sub_topic and sub_topic in all_own_topics:
            log.error(
                "Global uniqueness violation: subtopic '%s' collides "
                "with an existing topic slug in %s — refusing.",
                sub_topic, label,
            )
            return
        if topic_is_new:
            # Check new topic doesn't collide with any existing subtopic
            for _subs in subs_dict.values():
                if topic in _subs:
                    log.error(
                        "Global uniqueness violation: topic '%s' "
                        "collides with an existing subtopic in %s "
                        "— refusing.",
                        topic, label,
                    )
                    return

        if not topic_is_new and not sub_is_new:
            return

        if topic_is_new:
            taxonomy_repo.upsert_topic(
                slug=topic,
                name=_slug_to_display_name(topic),
                description="",
                topic_type=taxonomy_type,
                created_by=cfg.model,
                updated_by=cfg.model,
            )
            if sub_topic:
                taxonomy_repo.upsert_subtopic(
                    slug=sub_topic,
                    topic_slug=topic,
                    name=_slug_to_display_name(sub_topic),
                    description="",
                    created_by=cfg.model,
                    updated_by=cfg.model,
                )
            topic_dict[topic] = ""
            subs_dict[topic] = {sub_topic} if sub_topic else set()
            sub_desc_dict[topic] = {sub_topic: ""} if sub_topic else {}
            topic_conf_dict[topic] = None
            sub_conf_dict[topic] = {sub_topic: None} if sub_topic else {}
            log.info(
                "%s auto-upsert: new topic '%s/%s'",
                label.capitalize(), topic, sub_topic,
            )

        elif sub_is_new:
            taxonomy_repo.upsert_subtopic(
                slug=sub_topic,
                topic_slug=topic,
                name=_slug_to_display_name(sub_topic),
                description="",
                created_by=cfg.model,
                updated_by=cfg.model,
            )
            subs_dict.setdefault(topic, set()).add(sub_topic)
            sub_desc_dict.setdefault(topic, {})[sub_topic] = ""
            sub_conf_dict.setdefault(topic, {})[sub_topic] = None
            log.info(
                "%s auto-upsert: new subtopic '%s/%s'",
                label.capitalize(), topic, sub_topic,
            )


def _call_and_build(
    client: Any,
    cfg: AnalyzerConfig,
    system_prompt: str,
    user_prompt: str,
    n_msgs: int,
    base_url: str,
    user_id: Any,
    win_msgs: list[dict],
    win_cids: list[Any],
    idx_map: dict,
    absorbed: dict | None,
    *,
    taxonomy_repo=None,
    remap_repo=None,
    config_id: int | None = None,
    bot_only: bool = False,
    pure_llm: bool = False,
    fallback_label: str = "chunk",
) -> list[dict]:
    """Call LLM, build segments, retry once on taxonomy violations."""
    for attempt in range(2):
        llm_segments = _call_analyzer(
            client, cfg.model, system_prompt, user_prompt, n_msgs,
            cfg.temperature, base_url,
        )
        if not llm_segments:
            log.warning(
                "User %s %s — analyzer returned no segments; "
                "falling back to single segment.",
                user_id, fallback_label,
            )
            ranges = _splits_to_ranges([], len(win_msgs))
            return _build_fallback_segments(user_id, win_msgs, win_cids, ranges)

        llm_segments = _remap_llm_indices(llm_segments, idx_map)
        win_segments = _build_segments_from_llm(
            user_id, win_msgs, win_cids, llm_segments,
            cfg=cfg, bot_only=bot_only, pure_llm=pure_llm,
            absorbed_into=absorbed, taxonomy_repo=taxonomy_repo,
            remap_repo=remap_repo, config_id=config_id,
        )

        if not _has_taxonomy_violations(win_segments, bot_only):
            return win_segments

        if attempt == 0:
            log.info(
                "User %s %s — taxonomy violation detected, retrying LLM",
                user_id, fallback_label,
            )

    # Second attempt still has violations — segments already remapped by
    # _build_segments_from_llm via _remap_topic, so return as-is.
    return win_segments


def _build_segments_from_llm(
    user_id: Any,
    messages: list[dict],
    chat_ids: list[Any],
    llm_segments: list[dict],
    cfg=None,
    *,
    bot_only: bool = False,
    pure_llm: bool = False,
    absorbed_into: dict[int, int] | None = None,
    taxonomy_repo=None,
    remap_repo=None,
    config_id: int | None = None,
) -> list[dict]:
    """Build sms_chat_segments documents from v2 LLM output.

    For each LLM segment:
    - Maps messageIndices to actual chatMessages ObjectId list
    - Derives chatStartedAt / chatEndedAt from message timestamps
    - Populates topic, subTopic, summary, sentiment, labelConfidence from LLM
    - Checks taxonomy and auto-upserts unknown topics/subtopics (requires taxonomy_repo and cfg)
    - Derives hasBotFailure from message sequence analysis
    - Sets all other review/deferred fields to null

    When ``bot_only=True``, taxonomy upserts go to ``sms_chat_template_taxonomy``
    (for unmatched automated messages that fell through to the LLM).

    When ``pure_llm=True``, all deterministic overrides are disabled — the LLM's
    values for labelConfidence, sentiment, and responseRate are kept as-is regardless
    of whether the segment has user engagement.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    segments: list[dict] = []
    bot_failure_indices = _find_bot_failure_indices(messages)

    for llm_seg in llm_segments:
        indices = llm_seg["messageIndices"]
        # Map indices to actual message objects (guard against stale indices)
        seg_msgs = [messages[i] for i in indices if i < len(messages)]
        if not seg_msgs:
            continue

        # Use the first message's chat ref (1 user = 1 sms_chats document)
        first_idx = indices[0] if indices[0] < len(messages) else 0
        chat_id = chat_ids[first_idx]
        chat_messages = [str(m["_id"]) for m in seg_msgs]

        # Include absorbed bot image-only messages whose predecessor is in this segment
        if absorbed_into:
            existing_ids = set(chat_messages)
            seg_orig_indices = set(indices)
            for absorbed_idx, predecessor_idx in absorbed_into.items():
                if predecessor_idx in seg_orig_indices:
                    absorbed_id = str(messages[absorbed_idx]["_id"])
                    if absorbed_id not in existing_ids:
                        chat_messages.append(absorbed_id)
                        existing_ids.add(absorbed_id)

        # Timestamps from actual messages
        first_ts = seg_msgs[0].get("createdAt") or now
        last_ts = seg_msgs[-1].get("createdAt") or now

        # Deterministic engagement: does this segment contain at least one user message?
        has_user_engagement = any(m.get("type") == "user" for m in seg_msgs)

        # Deterministic bot failure: did any user message in this segment go unanswered?
        has_bot_failure = bool(bot_failure_indices & set(indices))

        # Deterministic response rate — always a float, never null.
        # 0.0 = no user engagement, no bot prompts, or LLM omitted counts
        bot_q = llm_seg.get("botPromptCount")
        user_a = llm_seg.get("userResponseCount")
        if not has_user_engagement:
            response_rate = 0.0
        elif bot_q is not None and user_a is not None and bot_q > 0:
            response_rate = min(user_a / bot_q, 1.0)
        else:
            # No bot prompts or LLM omitted counts → nothing to respond to
            response_rate = 0.0

        topic = llm_seg["topic"]
        sub_topic = llm_seg["subTopic"]

        # Guard: user segments must not carry bot-only topics (and vice versa)
        if not bot_only and topic and topic in BOT_TAXONOMY and topic not in INITIAL_TAXONOMY:
            topic, sub_topic = _remap_topic(
                topic, sub_topic, user_id, "bot_to_user",
                remap_repo, config_id,
            )
        elif bot_only and topic and topic in INITIAL_TAXONOMY and topic not in BOT_TAXONOMY:
            topic, sub_topic = _remap_topic(
                topic, sub_topic, user_id, "user_to_bot",
                remap_repo, config_id,
            )

        # Check taxonomy and auto-upsert if topic/subtopic is unknown
        if taxonomy_repo is not None and cfg is not None:
            _ensure_taxonomy_entry(
                taxonomy_repo, topic, sub_topic, cfg, bot_only=bot_only,
            )
            # If upsert was blocked (collision), null out to avoid FK violation
            td = BOT_TAXONOMY if bot_only else INITIAL_TAXONOMY
            sd = BOT_KNOWN_SUBTOPICS if bot_only else KNOWN_SUBTOPICS
            if topic and topic not in td:
                log.warning("Topic '%s' blocked by collision — nulling", topic)
                topic = None
                sub_topic = None
            elif sub_topic and sub_topic not in sd.get(topic, set()):
                log.warning("Subtopic '%s/%s' blocked — nulling sub", topic, sub_topic)
                sub_topic = None

        # No user engagement → deterministic 1.0 confidence (not LLM-derived)
        # In pure_llm mode, always use the LLM's confidence — no overrides.
        if pure_llm:
            label_confidence = llm_seg["labelConfidence"]
        else:
            label_confidence = 1.0 if not has_user_engagement else llm_seg["labelConfidence"]

        segments.append({
            # — identity —
            "user_id":            str(user_id),
            "chat_id":            str(chat_id),
            "chat_messages":      chat_messages,
            # — confidence signals —
            "cluster":            None,
            "label_confidence":   label_confidence,
            # — labels —
            "topic":              topic,
            "sub_topic":          sub_topic,
            "summary":            llm_seg["summary"],
            # — sentiment (None when no user msgs unless pure_llm) —
            "sentiment": (
                llm_seg.get("sentiment")
                if (has_user_engagement or pure_llm) else None
            ),
            # — engagement —
            "has_user_engagement": has_user_engagement,
            "has_bot_failure":    has_bot_failure,
            "response_rate":      response_rate,
            # — timestamps —
            "chat_started_at":    first_ts,
            "chat_ended_at":      last_ts,
            "classified_at":      now,
        })

    # ── Dedup: non-user messages must appear in exactly one segment ──
    _dedup_non_user_across_segments(segments, messages)

    # ── Orphan rescue: append messages the LLM failed to reference ──
    referenced = set()
    for llm_seg in llm_segments:
        referenced.update(llm_seg["messageIndices"])
    all_indices = set(range(len(messages)))
    orphans = sorted(all_indices - referenced)

    if orphans:
        log.warning(
            "User %s — LLM dropped %d message index(es): %s. "
            "Appending to nearest segment.",
            user_id, len(orphans), orphans,
        )

        if not segments:
            # No segments yet — create a single catchall segment for all orphans
            orphan_msgs = [messages[idx] for idx in orphans]
            first_ts = orphan_msgs[0].get("createdAt") or now
            last_ts = orphan_msgs[-1].get("createdAt") or now
            chat_id = chat_ids[orphans[0]] if orphans[0] < len(chat_ids) else chat_ids[0]
            segments.append({
                "user_id":             str(user_id),
                "chat_id":             str(chat_id),
                "chat_messages":       [str(m["_id"]) for m in orphan_msgs],
                "cluster":             None,
                "label_confidence":    None,
                "topic":               "unclassified",
                "sub_topic":           "unclassified",
                "summary":             None,
                "sentiment":           None,
                "has_user_engagement": any(m.get("type") == "user" for m in orphan_msgs),
                "has_bot_failure":     False,
                "response_rate":       0.0,
                "chat_started_at":     first_ts,
                "chat_ended_at":       last_ts,
                "classified_at":       now,
            })
        else:
            # Precompute: map message _id (as str) → index for fast lookup
            # chat_messages stores str IDs, so keys must also be strings
            id_to_idx = {str(messages[j]["_id"]): j for j in range(len(messages))}

            # Build per-segment index sets once (chat_messages now holds str IDs)
            seg_index_sets: list[set[int]] = []
            for seg in segments:
                seg_index_sets.append({
                    id_to_idx[mid]
                    for mid in seg["chat_messages"]
                    if mid in id_to_idx
                })

            for idx in orphans:
                msg = messages[idx]

                # Find the segment whose index range is closest
                best_seg_i = 0
                best_dist = float("inf")
                for si, idx_set in enumerate(seg_index_sets):
                    if not idx_set:
                        continue
                    dist = min(abs(idx - j) for j in idx_set)
                    if dist < best_dist:
                        best_dist = dist
                        best_seg_i = si

                seg = segments[best_seg_i]
                orphan_id = str(msg["_id"])
                if orphan_id not in set(seg["chat_messages"]):
                    seg["chat_messages"].append(orphan_id)
                seg_index_sets[best_seg_i].add(idx)

                # Update timestamps if orphan extends the range
                ts = msg.get("createdAt")
                if ts is not None:
                    if ts < seg["chat_started_at"]:
                        seg["chat_started_at"] = ts
                    if ts > seg["chat_ended_at"]:
                        seg["chat_ended_at"] = ts

    return segments


_client_cache: dict[tuple[str, str], Any] = {}

# LLM call stats — reset per run via reset_llm_stats()
_llm_stats_lock = threading.Lock()
_llm_call_count = 0
_llm_total_latency_ms = 0.0


def reset_llm_stats() -> None:
    """Reset LLM call counters. Call before each benchmark model run."""
    global _llm_call_count, _llm_total_latency_ms
    with _llm_stats_lock:
        _llm_call_count = 0
        _llm_total_latency_ms = 0.0


def get_llm_stats() -> dict:
    """Return LLM call count and average latency."""
    with _llm_stats_lock:
        count = _llm_call_count
        total = _llm_total_latency_ms
    return {
        "llm_call_count": count,
        "avg_llm_latency_ms": round(total / count, 1) if count else 0.0,
    }


def _get_openai_client(api_key: str, base_url: str) -> Any:
    key = (api_key, base_url)
    if key not in _client_cache:
        from openai import OpenAI
        _client_cache[key] = OpenAI(api_key=api_key, base_url=base_url)
    return _client_cache[key]


def _call_openai_compat(
    model: str, messages: list[dict], temperature: float, base_url: str,
) -> str:
    """Call an OpenAI-compatible API (Vercel AI Gateway, OpenAI, etc.).

    Auth priority: AI_GATEWAY_API_KEY > OPENAI_API_KEY > VERCEL_API_KEY (legacy).
    """
    import time as _time
    global _llm_call_count, _llm_total_latency_ms
    api_key = (
        os.environ.get("AI_GATEWAY_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("VERCEL_API_KEY", "")
    )
    client = _get_openai_client(api_key, base_url)
    t0 = _time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    elapsed_ms = (_time.perf_counter() - t0) * 1000
    with _llm_stats_lock:
        _llm_call_count += 1
        _llm_total_latency_ms += elapsed_ms
    return response.choices[0].message.content or ""


def _splits_to_ranges(split_points: list[int], n: int) -> list[tuple[int, int]]:
    """Convert split-point indices to (start, end_inclusive) ranges."""
    if not split_points or n == 0:
        return [(0, n - 1)] if n > 0 else []
    boundaries = [0] + sorted(split_points) + [n]
    return [(boundaries[i], boundaries[i + 1] - 1) for i in range(len(boundaries) - 1)]


def _build_fallback_segments(
    user_id: Any,
    messages: list[dict],
    chat_ids: list[Any],
    ranges: list[tuple[int, int]],
) -> list[dict]:
    """Build sms_chat_segments documents from message index ranges."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    segments: list[dict] = []
    bot_failure_indices = _find_bot_failure_indices(messages)

    for _, (start, end) in enumerate(ranges):
        seg_msgs    = messages[start : end + 1]
        seg_chat_ids = chat_ids[start : end + 1]
        if not seg_msgs:
            continue

        # Single chat ref since 1 user = 1 sms_chats document
        chat_id              = seg_chat_ids[0]
        chat_messages        = [str(m["_id"]) for m in seg_msgs]
        first_ts             = seg_msgs[0].get("createdAt") or now
        last_ts              = seg_msgs[-1].get("createdAt") or now
        has_user_engagement  = any(m.get("type") == "user" for m in seg_msgs)
        seg_indices          = set(range(start, end + 1))
        has_bot_failure      = bool(bot_failure_indices & seg_indices)
        response_rate        = 0.0   # No LLM output in fallback path

        segments.append({
            # — identity —
            "user_id":            str(user_id),
            "chat_id":            str(chat_id),
            "chat_messages":      chat_messages,
            # — confidence signals —
            "cluster":            None,
            "label_confidence":   1.0 if not has_user_engagement else None,
            # — labels —
            "topic":              "unclassified",
            "sub_topic":          "unclassified",
            "summary":            None,
            # — deferred —
            "sentiment":          None,
            # — engagement —
            "has_user_engagement": has_user_engagement,
            "has_bot_failure":    has_bot_failure,
            "response_rate":      response_rate,
            # — timestamps —
            "chat_started_at":    first_ts,
            "chat_ended_at":      last_ts,
            "classified_at":      None,
        })

    return segments

