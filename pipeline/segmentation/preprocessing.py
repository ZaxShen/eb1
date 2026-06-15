"""
Preprocessing utilities for LLM-ready message preparation.

Functions here operate on raw message dicts and produce cleaned copies
suitable for passing to the segmenter LLM.  Originals are NEVER mutated.
"""

import logging
import re
from typing import Any


def _normalize_slug(s: str) -> str:
    """Normalize an LLM-generated topic/subTopic slug to strict snake_case.

    Strips whitespace, lowercases, replaces hyphens and spaces with underscores,
    collapses consecutive underscores, and strips leading/trailing underscores.
    """
    s = s.strip().lower()
    s = re.sub(r"[-\s]+", "_", s)   # hyphens and spaces → underscore
    s = re.sub(r"_+", "_", s)        # collapse multiple underscores
    s = s.strip("_")                  # strip leading/trailing underscores
    return s


def _slug_to_display_name(slug: str) -> str:
    """Convert a snake_case slug to a human-readable display name.

    Example: "match_feedback" → "Match Feedback"
    """
    if not slug:
        return ""
    return slug.replace("_", " ").title()

log = logging.getLogger(__name__)

# ── Link / media preprocessing (LLM only — never written to DB) ──────────────

_URL_RE = re.compile(r"https?://[^\s<>\")\]]+")

# Domain → token mapping for Pass 3 (URL replacement).
# Order matters: first match wins.  Checked with `domain.endswith(...)`.
_DOMAIN_TOKENS: list[tuple[str, str]] = [
    ("l.ditt.ai", "[link]"),
    ("ditt.ai", "[link]"),
    ("acme.ai", "[link]"),
    ("youtube.com", "[youtube link]"),
    ("youtu.be", "[youtube link]"),
    ("instagram.com", "[instagram link]"),
    ("tiktok.com", "[tiktok link]"),
    ("spotify.com", "[spotify link]"),
    ("firebasestorage.googleapis.com", "[image]"),
    ("storage.googleapis.com", "[image]"),
]

# Matches the structured user-upload format from PROD:
#   NOTE: User uploaded N image(s). User Message: <text> Image URL(s): <url>
_USER_UPLOAD_RE = re.compile(
    r"^NOTE:\s*User uploaded (?:an|\d+) image\(?s?\)?\.\s*"
    r"User Message:\s*(.*?)\s*"
    r"Image URLs?:\s*.*$",
    re.DOTALL,
)

_MEDIA_WRAPPER_RE = re.compile(
    r"\[media:\s*(https?://[^\]]+)\]",
)

_REACTION_PREFIXES = (
    "Loved ", "Liked ", "Disliked ",
    "Laughed at ", "Emphasized ", "Questioned ",
)


def _url_to_token(url: str) -> str:
    """Map a URL to its semantic token based on domain."""
    domain = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    for suffix, token in _DOMAIN_TOKENS:
        if domain.endswith(suffix):
            if token == "[image]" and url.lower().endswith(".vcf"):
                return "[contact card]"
            return token
    return "[link]"


def _is_image_only_message(msg: dict) -> bool:
    """True if the message is solely an image/media URL with no real text."""
    text = (msg.get("message") or "").strip()
    # Raw URL that resolves to [image]
    if _URL_RE.fullmatch(text):
        return _url_to_token(text) == "[image]"
    # [media: <url>] wrapper only
    m = _MEDIA_WRAPPER_RE.fullmatch(text)
    if m:
        return _url_to_token(m.group(1)) in ("[image]", "[contact card]")
    return False


def _replace_urls(text: str) -> str:
    """Replace all URLs in *text* with semantic tokens."""
    # First handle [media: <url>] wrappers
    def _media_repl(m: re.Match) -> str:
        return _url_to_token(m.group(1))
    text = _MEDIA_WRAPPER_RE.sub(_media_repl, text)
    # Then handle bare URLs
    text = _URL_RE.sub(lambda m: _url_to_token(m.group(0)), text)
    return text


def _clean_user_upload(text: str) -> str:
    """Reformat a user-upload message: keep user text, strip URL."""
    m = _USER_UPLOAD_RE.match(text)
    if not m:
        return _replace_urls(text)
    user_text = m.group(1).strip()
    # Extract count from the original text
    count_m = re.search(r"uploaded (\d+) image", text)
    if count_m and int(count_m.group(1)) > 1:
        prefix = f"User uploaded {count_m.group(1)} image(s)"
    else:
        prefix = "User uploaded an image"
    if user_text:
        return f'{prefix}: "{user_text}" [image]'
    return f"{prefix} [image]"


def _preprocess_for_llm(
    messages: list[dict],
    chat_ids: list[Any],
) -> tuple[list[dict], list[Any], list[int], dict[int, int]]:
    """Create LLM-ready copies of messages.  Originals are NEVER mutated.

    Three passes:
      1. Bot image-only messages → absorbed into preceding message as
         ``[image]`` tag; the message is removed from the list.
      2. User image uploads → cleaned format, URL stripped.
      3. All remaining URLs → replaced with semantic tokens.

    Returns:
        llm_messages:  Preprocessed message dicts (shallow copies with
                       modified ``"message"`` field).  May be shorter than
                       the input list (Pass 1 removes messages).
        llm_chat_ids:  Parallel chat-id list matching *llm_messages*.
        index_map:     ``index_map[new_idx] = original_idx`` so that LLM
                       ``messageIndices`` can be mapped back to the
                       original message list for DB writes.
        absorbed_into: ``{absorbed_orig_idx: predecessor_orig_idx}`` — maps
                       each absorbed message's original index to the
                       predecessor it was merged into, so the caller can
                       include the absorbed message's _id in the same
                       segment as its predecessor.
    """
    n = len(messages)

    # ── Pass 1: absorb bot image-only messages into preceding ────────────
    # Build a list of (original_index, message_copy) pairs, skipping
    # absorbed messages and tagging their predecessor.
    keep: list[tuple[int, dict]] = []   # (orig_idx, msg_copy)
    keep_cids: list[Any] = []
    absorbed_into: dict[int, int] = {}  # {absorbed_orig_idx: predecessor_orig_idx}

    for i in range(n):
        if i in absorbed_into:
            continue
        msg = messages[i]
        msg_type = msg.get("type", "")
        if (
            msg_type != "user"
            and _is_image_only_message(msg)
        ):
            # Try to merge into preceding message
            if keep:
                prev_idx, prev_copy = keep[-1]
                prev_copy["message"] = prev_copy["message"] + " [image]"
                absorbed_into[i] = prev_idx
            else:
                # No preceding message — keep as standalone [image]
                keep.append((i, {**msg, "message": "[image]"}))
                keep_cids.append(chat_ids[i])
                continue
            continue
        keep.append((i, {**msg}))  # shallow copy
        keep_cids.append(chat_ids[i])

    # ── Pass 2 & 3: clean text on all remaining messages ─────────────────
    index_map: list[int] = []
    llm_messages: list[dict] = []
    llm_chat_ids: list[Any] = []

    for (orig_idx, msg_copy), cid in zip(keep, keep_cids):
        text = msg_copy.get("message") or ""
        msg_type = msg_copy.get("type", "")

        # Pass 2: user image uploads
        if msg_type == "user" and text.startswith("NOTE: User uploaded"):
            msg_copy["message"] = _clean_user_upload(text)
        else:
            # Pass 3: replace remaining URLs
            msg_copy["message"] = _replace_urls(text)

        llm_messages.append(msg_copy)
        llm_chat_ids.append(cid)
        index_map.append(orig_idx)

    if absorbed_into:
        log.debug(
            "Preprocessing: absorbed %d bot image-only message(s) into "
            "preceding messages.",
            len(absorbed_into),
        )

    return llm_messages, llm_chat_ids, index_map, absorbed_into


def _is_imessage_reaction(msg: dict) -> bool:
    """True if the message is an iMessage tapback reaction (e.g. 'Loved "..."')."""
    text = msg.get("message") or ""
    return text.startswith(_REACTION_PREFIXES)
