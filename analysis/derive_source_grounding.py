"""Derive real document grounding for the SuperDialseg test split (issue #23).

SuperDialseg's ``superseg-v2`` release carries NO source metadata on its turns
(``da`` / ``role`` / ``utterance`` / ``topic_id`` / ``segmentation_label`` only),
but every one of our 1,322 test dialogues joins back to its origin corpus by
``dial_id`` with zero misses: 661 come from **doc2dial** (one grounding document
for the whole dialogue) and 661 from **MultiDoc2Dial** (per-turn document
references). This recovers a REAL topic hierarchy — domain -> cleaned document
title — to replace the BERTopic keyword dumps. Run offline::

    python -m analysis.derive_source_grounding \\
        --superseg segmentation_file_test.json \\
        --doc2dial-zip doc2dial.zip \\
        --multidoc2dial-zip multidoc2dial.zip \\
        --out-grounding analysis/superdialseg_grounding.json \\
        --out-label-map analysis/source_label_map.json

Corpus sources (download once, then this script is reproducible from the
committed artifacts): doc2dial and MultiDoc2Dial ship as zips linked from
https://github.com/Coldog2333/SuperDialseg — doc2dial members
``doc2dial_dial_{train,validation,test}.json`` shaped
``{"dial_data": {domain: {doc_id: [{dial_id, turns}]}}}``; MultiDoc2Dial members
``multidoc2dial/multidoc2dial_dial_{train,validation,test}.json`` shaped
``{"dial_data": {domain: [{dial_id, turns: [{turn_id, references: [{doc_id}]}]}]}}``.

Two artifacts are emitted and committed:

- ``superdialseg_grounding.json`` — per ``dial_id``: the domain code and a
  ``doc_by_turn`` list (0-based turn order, full dialogue length) of cleaned
  document titles (or ``null`` where a turn has no reference).
- ``source_label_map.json`` — the ``annotation.load_taxonomy`` pairs shape, one
  pair per distinct ``(domain, cleaned title)`` so the existing loader ingests
  the real taxonomy unchanged.

Every ``dial_id`` must match exactly one corpus; unmatched ids fail loudly.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path

DATASET = "superdialseg"

DOMAIN_DISPLAY = {
    "ssa": "Social Security",
    "va": "Veterans Affairs",
    "dmv": "DMV",
    "studentaid": "Student Aid",
}

# Trailing site boilerplate to strip from a document title (longest/most-specific
# first so a shorter alias never shadows the full name).
_BOILERPLATE = (
    " | Social Security Administration",
    " | SSA",
    " | Veterans Affairs",
    " | Federal Student Aid",
)

_SECTION_SUFFIX = re.compile(r"#\d+_\d+$")

_DOC2DIAL_MEMBERS = (
    "doc2dial_dial_test.json",
    "doc2dial_dial_train.json",
    "doc2dial_dial_validation.json",
)

_MULTIDOC2DIAL_MEMBERS = (
    "multidoc2dial/multidoc2dial_dial_test.json",
    "multidoc2dial/multidoc2dial_dial_train.json",
    "multidoc2dial/multidoc2dial_dial_validation.json",
)


def clean_title(doc_id: str) -> str:
    """Clean a raw ``doc_id`` into a human document title.

    Strips the trailing ``#<n>_<n>`` section marker and any trailing site
    boilerplate (agency name), then trims::

        clean_title("About VA Disability Ratings | Veterans Affairs#1_0")
            -> "About VA Disability Ratings"
        clean_title("Top 5 DMV Mistakes and How to Avoid Them#3_0")
            -> "Top 5 DMV Mistakes and How to Avoid Them"
    """
    title = _SECTION_SUFFIX.sub("", doc_id)
    for suffix in _BOILERPLATE:
        if title.endswith(suffix):
            title = title[: -len(suffix)]
            break
    return title.strip()


def index_doc2dial(dial_data: dict) -> dict[str, tuple[str, str]]:
    """Map ``dial_id -> (domain, raw doc_id)`` from a doc2dial ``dial_data``."""
    index: dict[str, tuple[str, str]] = {}
    for domain, docs in dial_data.items():
        for doc_id, dialogues in docs.items():
            for dialogue in dialogues:
                index[dialogue["dial_id"]] = (domain, doc_id)
    return index


def index_multidoc2dial(dial_data: dict) -> dict[str, tuple[str, dict[int, str]]]:
    """Map ``dial_id -> (domain, {turn_id: raw doc_id})`` from MultiDoc2Dial.

    A turn's grounding is the ``doc_id`` of its FIRST reference; a turn with no
    references contributes no entry (its turn is later grounded ``null``).
    """
    index: dict[str, tuple[str, dict[int, str]]] = {}
    for domain, dialogues in dial_data.items():
        for dialogue in dialogues:
            per_turn: dict[int, str] = {}
            for turn in dialogue["turns"]:
                references = turn.get("references") or []
                if references:
                    per_turn[turn["turn_id"]] = references[0]["doc_id"]
            index[dialogue["dial_id"]] = (domain, per_turn)
    return index


def _read_zip_members(zip_path: Path, members: tuple[str, ...]) -> list[dict]:
    """Return parsed JSON for each present member (missing members tolerated)."""
    payloads: list[dict] = []
    with zipfile.ZipFile(zip_path) as archive:
        available = set(archive.namelist())
        for member in members:
            if member in available:
                payloads.append(json.loads(archive.read(member)))
    return payloads


def load_doc2dial_index(zip_path: Path) -> dict[str, tuple[str, str]]:
    """Build the doc2dial ``dial_id`` index across all splits in ``zip_path``."""
    index: dict[str, tuple[str, str]] = {}
    for payload in _read_zip_members(zip_path, _DOC2DIAL_MEMBERS):
        index.update(index_doc2dial(payload["dial_data"]))
    return index


def load_multidoc2dial_index(zip_path: Path) -> dict[str, tuple[str, dict[int, str]]]:
    """Build the MultiDoc2Dial ``dial_id`` index across all splits in ``zip_path``."""
    index: dict[str, tuple[str, dict[int, str]]] = {}
    for payload in _read_zip_members(zip_path, _MULTIDOC2DIAL_MEMBERS):
        index.update(index_multidoc2dial(payload["dial_data"]))
    return index


def build_grounding(
    dialogues: list[dict],
    doc2dial_index: dict[str, tuple[str, str]],
    multidoc2dial_index: dict[str, tuple[str, dict[int, str]]],
) -> tuple[dict, dict]:
    """Join superseg dialogues to their source docs; return (grounding, label_map).

    For each superseg dialogue, ``doc_by_turn`` aligns with the dialogue's turn
    order (0-based), matching the annotation DB's message ``idx``. doc2dial
    dialogues repeat their single document across every turn; MultiDoc2Dial
    dialogues resolve each turn via its ``turn_id`` (``null`` when a turn has no
    reference). Raises ``ValueError`` listing any ``dial_id`` that matches no
    corpus (expected: none).
    """
    grounding: dict[str, dict] = {}
    # (domain, cleaned title) -> lexicographically-smallest raw doc_id (stable rep).
    pair_raw: dict[tuple[str, str], str] = {}
    unmatched: list[str] = []

    for dialogue in dialogues:
        dial_id = dialogue["dial_id"]
        turns = dialogue["turns"]
        if dial_id in doc2dial_index:
            domain, raw_doc = doc2dial_index[dial_id]
            title = clean_title(raw_doc)
            doc_by_turn = [title] * len(turns)
            key = (domain, title)
            existing = pair_raw.get(key)
            if existing is None or raw_doc < existing:
                pair_raw[key] = raw_doc
        elif dial_id in multidoc2dial_index:
            domain, per_turn = multidoc2dial_index[dial_id]
            doc_by_turn = []
            for turn in turns:
                raw_doc = per_turn.get(turn["turn_id"])
                if raw_doc is None:
                    doc_by_turn.append(None)
                    continue
                title = clean_title(raw_doc)
                doc_by_turn.append(title)
                key = (domain, title)
                existing = pair_raw.get(key)
                if existing is None or raw_doc < existing:
                    pair_raw[key] = raw_doc
        else:
            unmatched.append(dial_id)
            continue
        grounding[dial_id] = {"domain": domain, "doc_by_turn": doc_by_turn}

    if unmatched:
        raise ValueError(
            f"{len(unmatched)} dial_id(s) matched no corpus: "
            + ", ".join(sorted(unmatched)[:20])
        )

    pairs = [
        {
            "topic": DOMAIN_DISPLAY[domain],
            "subtopic": title,
            "topic_raw": domain,
            "subtopic_raw": raw_doc,
        }
        for (domain, title), raw_doc in pair_raw.items()
    ]
    pairs.sort(key=lambda p: (p["topic"], p["subtopic"]))

    grounding_doc = {"dataset": DATASET, "dialogues": grounding}
    label_map = {"dataset": DATASET, "pairs": pairs}
    return grounding_doc, label_map


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _coverage_summary(grounding_doc: dict, label_map: dict) -> None:
    dialogues = grounding_doc["dialogues"]
    domains: dict[str, int] = {}
    for entry in dialogues.values():
        domains[entry["domain"]] = domains.get(entry["domain"], 0) + 1
    print(f"dialogues grounded: {len(dialogues)}")
    print(f"domains ({len(domains)}):")
    for domain in sorted(domains):
        print(f"  {domain} ({DOMAIN_DISPLAY[domain]}): {domains[domain]}")
    print(f"taxonomy pairs (distinct docs): {len(label_map['pairs'])}")


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive real document grounding for the SuperDialseg test split."
    )
    parser.add_argument("--superseg", type=Path, required=True)
    parser.add_argument("--doc2dial-zip", type=Path, required=True)
    parser.add_argument("--multidoc2dial-zip", type=Path, required=True)
    parser.add_argument("--out-grounding", type=Path, required=True)
    parser.add_argument("--out-label-map", type=Path, required=True)
    args = parser.parse_args(argv)

    superseg = json.loads(args.superseg.read_text(encoding="utf-8"))
    dialogues = superseg["dial_data"]["superseg-v2"]
    doc2dial_index = load_doc2dial_index(args.doc2dial_zip)
    multidoc2dial_index = load_multidoc2dial_index(args.multidoc2dial_zip)

    grounding_doc, label_map = build_grounding(
        dialogues, doc2dial_index, multidoc2dial_index
    )

    _write_json(args.out_grounding, grounding_doc)
    _write_json(args.out_label_map, label_map)

    _coverage_summary(grounding_doc, label_map)
    print(f"wrote {args.out_grounding}")
    print(f"wrote {args.out_label_map}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
