"""Universal, additive end-to-end runner for the per-dataset pipeline.

Reuses the existing core unchanged:

    adapter (pipeline.adapters.get_loader)
      -> windowing._pre_segment (deterministic chunking)
      -> v4 prompt (pipeline.prompts.analyzer.load_prompt)
      -> analyzer backend (claude_p | mock)
      -> parse {"segments": [...]}
      -> write datasets/<name>/output.db (SQLite) + print a summary

This path does NOT touch the production ``segmenter._process_one`` / Postgres /
Mongo flow. The only network call is ``claude -p`` (when ``--analyzer claude_p``).

Run::

    python -m pipeline.run_dataset --dataset wildchat \
        --sample datasets/wildchat/sample.jsonl --model haiku --limit 1 \
        --analyzer claude_p
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from pipeline.adapters import get_loader
from pipeline.analyzer_backends import get_analyzer
from pipeline.metadata.provider import DatasetConfig, SqliteDatasetProvider
from pipeline.prompts.analyzer import load_prompt
from pipeline.segmentation.windowing import PreSegmentChunk, _pre_segment

_OUTPUT_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_segment (
    id            INTEGER PRIMARY KEY,
    dataset       TEXT,
    conversation  TEXT,
    chunk_index   INTEGER,
    message_indices TEXT,
    summary       TEXT,
    topic         TEXT,
    subtopic      TEXT,
    sentiment     TEXT,
    label_confidence REAL,
    raw           TEXT
);
"""


def load_sample(path: str | Path) -> list[dict]:
    """Read a JSONL sample file into a list of raw corpus rows."""
    rows: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def render_history(chunk: PreSegmentChunk) -> tuple[str, int]:
    """Render a chunk's messages as ``[type] message`` lines for the v4 prompt.

    Returns the joined history block and the message count.
    """
    lines = [f"[{m['type']}] {m['message']}" for m in chunk.messages]
    return "\n".join(lines), len(lines)


def build_prompt(chunk: PreSegmentChunk, config: DatasetConfig) -> tuple[str, str]:
    """Build the v4 (system, user) prompts for one user-engaged chunk.

    Open taxonomy: minimal taxonomy text and empty previous segments. The system
    prompt is returned so the claude_p backend can override its default persona.
    """
    template = load_prompt(config.prompt_profile, kind="user")
    history, n_msgs = render_history(chunk)
    user_prompt = template.build_user_prompt(
        previous_segments="(none)",
        n_msgs=n_msgs,
        history=history,
        taxonomy="(open taxonomy — propose new snake_case topics as needed)",
        topic_options="",
    )
    return template.build_system_prompt(), user_prompt


def parse_segments(text: str) -> list[dict]:
    """Parse an analyzer response into a list of segment dicts."""
    data = json.loads(text)
    segments = data.get("segments")
    if not isinstance(segments, list):
        raise ValueError("Analyzer response missing a 'segments' list.")
    return segments


def write_output(db_path: str | Path, records: list[dict]) -> None:
    """Write run segments to the per-dataset output SQLite DB."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_OUTPUT_SCHEMA)
        conn.execute("DELETE FROM run_segment")
        for rec in records:
            conn.execute(
                "INSERT INTO run_segment "
                "(dataset, conversation, chunk_index, message_indices, summary, "
                "topic, subtopic, sentiment, label_confidence, raw) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec["dataset"],
                    rec["conversation"],
                    rec["chunk_index"],
                    json.dumps(rec["message_indices"]),
                    rec["summary"],
                    rec["topic"],
                    rec["subtopic"],
                    rec["sentiment"],
                    rec["label_confidence"],
                    json.dumps(rec["raw"]),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def run(
    dataset: str,
    sample: str | Path,
    analyzer: str = "mock",
    model: str = "haiku",
    limit: int | None = None,
    metadata_db: str | Path | None = None,
    output_db: str | Path | None = None,
) -> dict:
    """Run the universal pipeline over a sample and write segments.

    Returns a summary dict: ``{conversations, segments, topics, output_db}``.
    """
    provider = SqliteDatasetProvider(
        metadata_db or Path("datasets") / dataset / "metadata.db"
    )
    config = provider.dataset_config()
    loader = get_loader(dataset)
    analyze = get_analyzer(analyzer)

    rows = load_sample(sample)
    if limit is not None:
        rows = rows[:limit]

    records: list[dict] = []
    conversations = 0
    for row in rows:
        messages = loader.load_conversation(row)
        if not messages:
            continue
        conversations += 1
        conversation_id = messages[0]["chat"]
        chat_ids = [m["chat"] for m in messages]
        chunks = _pre_segment(messages, chat_ids)

        for chunk_index, chunk in enumerate(chunks):
            if chunk.kind != "user_engaged":
                continue
            system_prompt, user_prompt = build_prompt(chunk, config)
            response = analyze(user_prompt, model, system=system_prompt)
            for seg in parse_segments(response):
                records.append({
                    "dataset": dataset,
                    "conversation": conversation_id,
                    "chunk_index": chunk_index,
                    "message_indices": seg.get("messageIndices", []),
                    "summary": seg.get("summary", ""),
                    "topic": seg.get("topic", ""),
                    "subtopic": seg.get("subTopic", ""),
                    "sentiment": seg.get("sentiment", ""),
                    "label_confidence": seg.get("labelConfidence"),
                    "raw": seg,
                })

    out_db = output_db or Path("datasets") / dataset / "output.db"
    write_output(out_db, records)

    topics = sorted({r["topic"] for r in records if r["topic"]})
    return {
        "conversations": conversations,
        "segments": len(records),
        "topics": topics,
        "output_db": str(out_db),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Universal per-dataset pipeline runner.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--model", default="haiku")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--analyzer", default="mock", choices=["claude_p", "mock"])
    parser.add_argument("--metadata-db", default=None)
    parser.add_argument("--output-db", default=None)
    args = parser.parse_args()

    summary = run(
        dataset=args.dataset,
        sample=args.sample,
        analyzer=args.analyzer,
        model=args.model,
        limit=args.limit,
        metadata_db=args.metadata_db,
        output_db=args.output_db,
    )

    print(f"Dataset:       {args.dataset}")
    print(f"Analyzer:      {args.analyzer} (model={args.model})")
    print(f"Conversations: {summary['conversations']}")
    print(f"Segments:      {summary['segments']}")
    print(f"Sample topics: {', '.join(summary['topics'][:10]) or '(none)'}")
    print(f"Output DB:     {summary['output_db']}")


if __name__ == "__main__":
    main()
