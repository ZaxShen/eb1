"""Tests for the real document-grounding derivation (``analysis.derive_source_grounding``).

The join/cleaning logic is pure and always runs on tiny inline corpus fixtures.
A final block asserts the COMMITTED artifacts still satisfy the issue #23
invariants (1,322 dialogues, 0 all-null, 4 domains, one pair per distinct doc).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis import derive_source_grounding as d

_ROOT = Path(__file__).resolve().parents[1]
GROUNDING = _ROOT / "analysis" / "superdialseg_grounding.json"
LABEL_MAP = _ROOT / "analysis" / "source_label_map.json"


def test_clean_title_strips_section_and_boilerplate():
    assert (
        d.clean_title("About VA Disability Ratings | Veterans Affairs#1_0")
        == "About VA Disability Ratings"
    )
    assert (
        d.clean_title("Top 5 DMV Mistakes and How to Avoid Them#3_0")
        == "Top 5 DMV Mistakes and How to Avoid Them"
    )
    # An internal " | " is not boilerplate and must survive.
    assert (
        d.clean_title("Benefits Planner: Retirement | Benefits | SSA#2_0")
        == "Benefits Planner: Retirement | Benefits"
    )


def test_index_doc2dial_maps_dialogue_to_single_doc():
    dial_data = {
        "dmv": {"Some Doc#3_0": [{"dial_id": "a", "turns": []}]},
        "ssa": {"Other#1_0": [{"dial_id": "b", "turns": []}]},
    }
    index = d.index_doc2dial(dial_data)
    assert index == {"a": ("dmv", "Some Doc#3_0"), "b": ("ssa", "Other#1_0")}


def test_index_multidoc2dial_first_reference_per_turn():
    dial_data = {
        "va": [
            {
                "dial_id": "m",
                "turns": [
                    {"turn_id": 1, "references": [{"doc_id": "Doc A#1_0"}]},
                    {"turn_id": 2, "references": []},
                    {
                        "turn_id": 3,
                        "references": [{"doc_id": "Doc B#2_0"}, {"doc_id": "Doc C#1_0"}],
                    },
                ],
            }
        ]
    }
    index = d.index_multidoc2dial(dial_data)
    domain, per_turn = index["m"]
    assert domain == "va"
    assert per_turn == {1: "Doc A#1_0", 3: "Doc B#2_0"}


def test_build_grounding_doc2dial_repeats_document():
    dialogues = [{"dial_id": "a", "turns": [{"turn_id": 1}, {"turn_id": 2}]}]
    doc2dial = {"a": ("ssa", "Retirement Benefits | SSA#1_0")}
    grounding, label_map = d.build_grounding(dialogues, doc2dial, {})
    entry = grounding["dialogues"]["a"]
    assert entry == {
        "domain": "ssa",
        "doc_by_turn": ["Retirement Benefits", "Retirement Benefits"],
    }
    assert label_map["pairs"] == [
        {
            "topic": "Social Security",
            "subtopic": "Retirement Benefits",
            "topic_raw": "ssa",
            "subtopic_raw": "Retirement Benefits | SSA#1_0",
        }
    ]


def test_build_grounding_multidoc_per_turn_nulls():
    dialogues = [
        {
            "dial_id": "m",
            "turns": [{"turn_id": 1}, {"turn_id": 2}, {"turn_id": 3}],
        }
    ]
    multidoc = {
        "m": ("va", {1: "Doc A | Veterans Affairs#1_0", 3: "Doc B#2_0"})
    }
    grounding, label_map = d.build_grounding(dialogues, {}, multidoc)
    entry = grounding["dialogues"]["m"]
    assert entry["domain"] == "va"
    assert entry["doc_by_turn"] == ["Doc A", None, "Doc B"]
    assert [p["subtopic"] for p in label_map["pairs"]] == ["Doc A", "Doc B"]


def test_build_grounding_dedups_pair_and_picks_smallest_raw():
    dialogues = [
        {"dial_id": "a", "turns": [{"turn_id": 1}]},
        {"dial_id": "b", "turns": [{"turn_id": 1}]},
    ]
    doc2dial = {
        "a": ("ssa", "Benefits Planner | SSA#2_0"),
        "b": ("ssa", "Benefits Planner | SSA#1_0"),
    }
    _, label_map = d.build_grounding(dialogues, doc2dial, {})
    assert len(label_map["pairs"]) == 1
    assert label_map["pairs"][0]["subtopic_raw"] == "Benefits Planner | SSA#1_0"


def test_build_grounding_unmatched_raises():
    dialogues = [{"dial_id": "ghost", "turns": [{"turn_id": 1}]}]
    with pytest.raises(ValueError, match="ghost"):
        d.build_grounding(dialogues, {}, {})


# --- Committed-artifact invariants (issue #23) -----------------------------


def test_committed_grounding_covers_all_dialogues():
    payload = json.loads(GROUNDING.read_text(encoding="utf-8"))
    assert payload["dataset"] == "superdialseg"
    dialogues = payload["dialogues"]
    assert len(dialogues) == 1322
    domains = {e["domain"] for e in dialogues.values()}
    assert domains == {"ssa", "va", "dmv", "studentaid"}
    nulls_only = sum(
        1 for e in dialogues.values() if all(x is None for x in e["doc_by_turn"])
    )
    assert nulls_only == 0


def test_committed_label_map_one_pair_per_distinct_doc():
    payload = json.loads(LABEL_MAP.read_text(encoding="utf-8"))
    assert payload["dataset"] == "superdialseg"
    pairs = payload["pairs"]
    keys = {(p["topic"], p["subtopic"]) for p in pairs}
    assert len(keys) == len(pairs) == 237
    assert {p["topic"] for p in pairs} == {
        "Social Security",
        "Veterans Affairs",
        "DMV",
        "Student Aid",
    }
