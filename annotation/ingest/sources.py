"""Raw-row streams for the full annotation datasets.

Each stream is a generator of RAW conversation rows in the shape the matching
``pipeline.adapters`` loader expects — nothing here normalizes, touches Postgres,
or holds a whole corpus in memory. The runner (:mod:`annotation.ingest.run`)
consumes a stream, normalizes each row through the adapter, and writes it.

Datasets
--------
- **WildChat** (``allenai/WildChat-1M``) — UNGATED. Streamed straight from the
  14 public parquet shards over ``huggingface_hub.HfFileSystem`` (``hf://``); no
  token required. Rows carry ``conversation_hash`` / ``timestamp`` /
  ``conversation`` (list of ``{role, content}``), matching
  :class:`pipeline.adapters.wildchat.WildChatLoader`.
- **LMSYS** (``lmsys/lmsys-chat-1m``) — GATED. Same parquet-over-HfFileSystem
  path, but the repo requires accepting the dataset terms on the Hub and an
  ``HF_TOKEN`` in the environment. A missing token or unaccepted terms raises a
  clear, actionable :class:`IngestAuthError`. Rows carry ``conversation_id`` /
  ``conversation``, matching :class:`pipeline.adapters.lmsys.LMSYSLoader`.
- **SuperDialseg** — gold-segmented release distributed as a zip on Google Drive
  (see :data:`SUPERDIALSEG_DRIVE_URL`). Dialogues carry ``dialogue_id`` /
  ``utterances`` (each with ``speaker`` / ``text`` / ``segment_id``), matching
  :class:`pipeline.adapters.superdialseg.SuperDialsegLoader`, whose
  ``gold_segments`` recovers the gold boundary spans.

Streams accept ``limit`` so a small live smoke run (e.g. 50 WildChat rows) reads
only the first shard's leading rows instead of the whole corpus.
"""

from __future__ import annotations

import json
import os
import zipfile
from collections.abc import Iterator
from pathlib import Path

WILDCHAT_REPO = "allenai/WildChat-1M"
LMSYS_REPO = "lmsys/lmsys-chat-1m"

# SuperDialseg's gold-segmented release (Jiang et al. 2023). The authors
# distribute the corpus as a zip on Google Drive, linked from the project repo
# https://github.com/Coldog2333/SuperDialseg (see its README's "Download the
# dataset" section for the current Drive link). The PRIMARY path is to download
# it once and point EB1_SUPERDIALSEG_PATH at the local copy (zip or extracted
# dir); EB1_SUPERDIALSEG_GDRIVE_ID overrides the file id for an automated gdown
# fetch.
SUPERDIALSEG_REPO_URL = "https://github.com/Coldog2333/SuperDialseg"


def _superdialseg_gdrive_id() -> str | None:
    """Return the Google Drive file id for the SuperDialseg release, if set."""
    return os.environ.get("EB1_SUPERDIALSEG_GDRIVE_ID")

_BATCH_READ = 256


class IngestAuthError(RuntimeError):
    """Raised when a gated dataset cannot be accessed (missing/invalid token)."""


def _hf_filesystem():
    """Return an ``HfFileSystem``; import is local so offline tests stay light."""
    from huggingface_hub import HfFileSystem

    return HfFileSystem()


def _hf_access_errors() -> tuple[type[BaseException], ...]:
    """Concrete exception types that a gated/invalid HF read can raise.

    Includes the ``huggingface_hub`` HTTP/auth errors plus the ``OSError`` /
    ``ValueError`` that ``pyarrow`` surfaces on a denied or malformed shard, so a
    gate failure is turned into a clear :class:`IngestAuthError` (not a raw
    stack trace) without swallowing ``KeyboardInterrupt`` / ``SystemExit``.
    """
    types: list[type[BaseException]] = [OSError, ValueError]
    try:
        from huggingface_hub.errors import HfHubHTTPError

        types.append(HfHubHTTPError)
    except ImportError:
        pass
    return tuple(types)


def _iter_parquet_rows(
    repo: str, token: str | None, limit: int | None
) -> Iterator[dict]:
    """Yield row dicts from a dataset repo's ``data/*.parquet`` shards in order.

    Reads shard-by-shard in record batches via ``pyarrow`` so memory stays flat
    regardless of corpus size; stops as soon as ``limit`` rows have been yielded.
    """
    import pyarrow.parquet as pq

    fs = _hf_filesystem()
    shards = sorted(fs.glob(f"datasets/{repo}/data/*.parquet"))
    if not shards:
        raise IngestAuthError(
            f"No parquet shards found for {repo!r} on the HuggingFace Hub. "
            "The repo layout may have changed, or access is denied."
        )

    yielded = 0
    for shard in shards:
        with fs.open(shard) as handle:
            parquet = pq.ParquetFile(handle)
            for batch in parquet.iter_batches(batch_size=_BATCH_READ):
                for row in batch.to_pylist():
                    yield row
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return


def wildchat_stream(limit: int | None = None) -> Iterator[dict]:
    """Stream raw WildChat rows from the ungated ``allenai/WildChat-1M`` shards.

    No token is needed. Each row matches ``WildChatLoader`` (``conversation_hash``
    is the conversation id).
    """
    token = os.environ.get("HF_TOKEN") or None
    yield from _iter_parquet_rows(WILDCHAT_REPO, token, limit)


def lmsys_stream(limit: int | None = None) -> Iterator[dict]:
    """Stream raw LMSYS rows from the GATED ``lmsys/lmsys-chat-1m`` shards.

    Requires ``HF_TOKEN`` in the environment AND that the dataset terms have been
    accepted for that account on the Hub. Raises :class:`IngestAuthError` with an
    actionable message when the token is missing or access is denied.
    """
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        raise IngestAuthError(
            "LMSYS-Chat-1M is a GATED HuggingFace dataset. To ingest it:\n"
            "  1. Create a HuggingFace account and accept the dataset terms at\n"
            "     https://huggingface.co/datasets/lmsys/lmsys-chat-1m\n"
            "  2. Create a read token at https://huggingface.co/settings/tokens\n"
            "  3. Export it before running the ingest:\n"
            "       export HF_TOKEN=hf_xxx\n"
            "HF_TOKEN is unset, so LMSYS cannot be downloaded."
        )
    os.environ.setdefault("HF_TOKEN", token)
    try:
        yield from _iter_parquet_rows(LMSYS_REPO, token, limit)
    except IngestAuthError:
        raise
    except _hf_access_errors() as exc:
        raise IngestAuthError(
            "Failed to read LMSYS-Chat-1M from the HuggingFace Hub with the "
            "provided HF_TOKEN. Confirm the token is valid AND that you have "
            "accepted the dataset terms at "
            "https://huggingface.co/datasets/lmsys/lmsys-chat-1m for that "
            f"account.\nUnderlying error: {exc}"
        ) from exc


def _resolve_superdialseg_source() -> Path:
    """Return a local SuperDialseg path, downloading the Drive release if needed.

    Honors ``EB1_SUPERDIALSEG_PATH`` (a zip or an extracted directory). When
    unset, the release is fetched once from Google Drive via ``gdown`` into the
    HuggingFace-style cache under ``~/.cache/eb1/superdialseg``.
    """
    override = os.environ.get("EB1_SUPERDIALSEG_PATH")
    if override:
        path = Path(override).expanduser()
        if not path.exists():
            raise FileNotFoundError(
                f"EB1_SUPERDIALSEG_PATH points at a missing path: {path}"
            )
        return path

    gdrive_id = _superdialseg_gdrive_id()
    if not gdrive_id:
        raise IngestAuthError(
            "SuperDialseg's gold-segmented release must be downloaded from Google "
            f"Drive (linked from {SUPERDIALSEG_REPO_URL}). Either:\n"
            "  - download it and set EB1_SUPERDIALSEG_PATH to the local copy "
            "(zip or extracted directory of *.json/*.jsonl dialogues), OR\n"
            "  - set EB1_SUPERDIALSEG_GDRIVE_ID to the release's Drive file id "
            "(with gdown installed) for an automated fetch."
        )

    cache = Path.home() / ".cache" / "eb1" / "superdialseg"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / "superdialseg.zip"
    if not archive.exists():
        try:
            import gdown
        except ImportError as exc:
            raise IngestAuthError(
                "gdown is required to fetch SuperDialseg from Google Drive "
                "(`uv add gdown`), or set EB1_SUPERDIALSEG_PATH to a local copy."
            ) from exc
        gdown.download(id=gdrive_id, output=str(archive), quiet=False)
    return archive


def _iter_superdialseg_dialogues(source: Path) -> Iterator[dict]:
    """Yield SuperDialseg dialogue dicts from a zip or a directory of ``*.json``.

    Each file is either a JSON list of dialogues or one dialogue object; lines of
    JSON (``.jsonl``) are also accepted. Dialogues are normalized to the
    ``{dialogue_id, utterances:[{speaker, text, segment_id}]}`` shape consumed by
    :class:`pipeline.adapters.superdialseg.SuperDialsegLoader`.
    """
    if source.is_dir():
        for path in sorted(source.rglob("*.json")) + sorted(source.rglob("*.jsonl")):
            yield from _load_superdialseg_file(path.read_text(encoding="utf-8"))
        return
    if source.suffix == ".zip" or zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as zf:
            for name in sorted(zf.namelist()):
                if name.endswith((".json", ".jsonl")) and not name.endswith("/"):
                    yield from _load_superdialseg_file(
                        zf.read(name).decode("utf-8")
                    )
        return
    yield from _load_superdialseg_file(source.read_text(encoding="utf-8"))


def _dialogue_records(parsed: object) -> Iterator[dict]:
    """Yield raw dialogue records from a parsed SuperDialseg JSON payload.

    The gold release nests dialogues under ``{"dial_data": {<variant>: [...]}}``
    (e.g. ``superseg-v2``); a single ``dial_data`` may hold several variant lists.
    A bare list of dialogues or a single dialogue object is also accepted, so the
    already-normalized fixture shape keeps working.
    """
    if isinstance(parsed, dict) and "dial_data" in parsed:
        dial_data = parsed["dial_data"]
        if isinstance(dial_data, dict):
            for variant in dial_data.values():
                if isinstance(variant, list):
                    yield from variant
        elif isinstance(dial_data, list):
            yield from dial_data
        return
    if isinstance(parsed, list):
        yield from parsed
        return
    yield parsed


def _load_superdialseg_file(text: str) -> Iterator[dict]:
    text = text.strip()
    if not text:
        return
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        for line in text.splitlines():
            line = line.strip()
            if line:
                yield _coerce_dialogue(json.loads(line))
        return
    for item in _dialogue_records(parsed):
        yield _coerce_dialogue(item)


def _coerce_dialogue(item: dict) -> dict:
    """Map a raw SuperDialseg record onto ``{dialogue_id, utterances}``.

    Accepts both the gold release's field names and the already-normalized shape.
    ``segment_id`` is derived from the running count of segment-final turns
    (``segmentation_label == 1`` marks a segment's last turn), so consecutive
    equal-``segment_id`` runs are exactly the canonical gold segments recovered by
    :meth:`pipeline.adapters.superdialseg.SuperDialsegLoader.gold_segments`. The
    raw ``topic_id`` does NOT match those boundaries, so it is carried through as
    a naming hint rather than used as the boundary key. Precedence: an explicit
    ``segment_id`` wins; else derive from ``segmentation_label``; else fall back
    to ``topic_id``; else ``0``.
    """
    dialogue_id = (
        item.get("dialogue_id")
        or item.get("dial_id")
        or item.get("id")
        or item.get("conversation_id")
    )
    raw = item.get("utterances") or item.get("turns") or item.get("dialogue") or []
    utterances: list[dict] = []
    running_segment = 0
    for utt in raw:
        if "segment_id" in utt:
            segment_id = utt["segment_id"]
        elif "segmentation_label" in utt:
            segment_id = running_segment
        else:
            segment_id = utt.get("topic_id", 0)
        utterances.append(
            {
                "speaker": utt.get("speaker") or utt.get("role") or "User",
                "text": utt.get("text") or utt.get("content") or utt.get("utterance") or "",
                "segment_id": segment_id,
                "topic_id": utt.get("topic_id"),
            }
        )
        if utt.get("segmentation_label") == 1:
            running_segment += 1
    return {"dialogue_id": str(dialogue_id), "utterances": utterances}


def superdialseg_stream(limit: int | None = None) -> Iterator[dict]:
    """Stream raw SuperDialseg dialogues (incl. gold ``segment_id``s).

    Resolves the corpus from ``EB1_SUPERDIALSEG_PATH`` or the Google Drive
    release, then yields up to ``limit`` dialogue dicts.
    """
    source = _resolve_superdialseg_source()
    for i, dialogue in enumerate(_iter_superdialseg_dialogues(source)):
        if limit is not None and i >= limit:
            return
        yield dialogue


STREAMS = {
    "wildchat": wildchat_stream,
    "lmsys": lmsys_stream,
    "superdialseg": superdialseg_stream,
}
