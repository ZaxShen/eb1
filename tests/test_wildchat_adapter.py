"""Offline tests for the WildChat adapter, neutral v4 prompt, and config pinning.

No MongoDB / PostgreSQL / LLM access — the WildChat fixture drives everything.
"""

import json
import tomllib
from datetime import datetime
from pathlib import Path

import pytest

from pipeline.adapters import get_loader
from pipeline.adapters.base import normalize_role
from pipeline.adapters.wildchat import WildChatLoader
from pipeline.prompts.analyzer import load_prompt
from pipeline.segmentation.windowing import _pre_segment

_FIXTURE = Path(__file__).parent / "fixtures" / "wildchat_sample.json"
_CONFIG_DIR = Path(__file__).resolve().parents[1] / "pipeline" / "config"
_NORMALIZED_KEYS = {"_id", "chat", "type", "message", "createdAt"}


@pytest.fixture
def wildchat_rows() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


# ── Role normalization ────────────────────────────────────────────────────────


class TestNormalizeRole:
    def test_user_and_assistant(self):
        assert normalize_role("user") == "user"
        assert normalize_role("assistant") == "assistant"

    def test_aliases_and_case(self):
        assert normalize_role("Human") == "user"
        assert normalize_role(" BOT ") == "assistant"
        assert normalize_role("gpt") == "assistant"

    def test_unknown_role_raises(self):
        with pytest.raises(ValueError):
            normalize_role("system")


# ── Adapter normalization ─────────────────────────────────────────────────────


class TestWildChatLoader:
    def test_maps_to_ordered_normalized_messages(self, wildchat_rows):
        loader = WildChatLoader()
        msgs = loader.load_conversation(wildchat_rows[0])

        assert len(msgs) == 4
        for m in msgs:
            assert set(m.keys()) == _NORMALIZED_KEYS
            assert m["type"] in {"user", "assistant"}
            assert isinstance(m["createdAt"], datetime)

        assert [m["type"] for m in msgs] == [
            "user", "assistant", "user", "assistant",
        ]

    def test_synthetic_ids_and_chat_id(self, wildchat_rows):
        row = wildchat_rows[0]
        msgs = WildChatLoader().load_conversation(row)
        chat_id = row["conversation_hash"]

        assert all(m["chat"] == chat_id for m in msgs)
        assert [m["_id"] for m in msgs] == [f"{chat_id}:{i}" for i in range(4)]
        assert str(msgs[0]["_id"]) == f"{chat_id}:0"

    def test_synthesized_timestamps_are_monotonic(self, wildchat_rows):
        msgs = WildChatLoader().load_conversation(wildchat_rows[0])
        ts = [m["createdAt"] for m in msgs]
        assert ts == sorted(ts)
        for i in range(1, len(ts)):
            assert (ts[i] - ts[i - 1]).total_seconds() == 1

    def test_load_conversations_batches(self, wildchat_rows):
        out = WildChatLoader().load_conversations(wildchat_rows)
        assert [len(c) for c in out] == [4, 2]

    def test_registry_returns_loader(self):
        assert isinstance(get_loader("wildchat"), WildChatLoader)

    def test_registry_unknown_raises(self):
        with pytest.raises(ValueError):
            get_loader("nonexistent")


# ── Pre-segmentation on normalized messages (no DB) ───────────────────────────


class TestPreSegmentOnNormalized:
    def test_yields_at_least_one_chunk(self, wildchat_rows):
        msgs = WildChatLoader().load_conversation(wildchat_rows[0])
        chat_ids = [m["chat"] for m in msgs]

        chunks = _pre_segment(msgs, chat_ids)

        assert len(chunks) >= 1
        covered = [m["_id"] for c in chunks for m in c.messages]
        assert len(covered) == len(msgs)
        assert set(covered) == {m["_id"] for m in msgs}


# ── Neutral v4 prompt ─────────────────────────────────────────────────────────


class TestNeutralV4Prompt:
    def test_v4_parses(self):
        tmpl = load_prompt(version="v4")
        assert tmpl.version == "v4"
        assert tmpl.system.strip()
        assert tmpl.user_template.strip()

    def test_v4_user_template_keeps_placeholders(self):
        tmpl = load_prompt(version="v4")
        rendered = tmpl.build_user_prompt(
            previous_segments="(none)",
            n_msgs=4,
            history="[0] [user] hi",
            taxonomy="(open)",
        )
        assert "hi" in rendered

    def test_v4_has_no_acme_tokens(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "pipeline" / "prompts" / "analyzer" / "eb1_prompt_user_v4.md"
        )
        text = path.read_text(encoding="utf-8").lower()
        for token in ["acme", "matchmaking", "yik-yak", "[team]", "[automated]"]:
            assert token.lower() not in text, f"v4 prompt leaks token: {token}"


# ── Production default preserved ──────────────────────────────────────────────


class TestProductionDefaultPreserved:
    def test_v3_still_resolves_acme(self):
        tmpl = load_prompt(version="v3")
        assert "Acme" in tmpl.system

    def test_analyzer_toml_pinned_to_v3(self):
        raw = tomllib.loads(
            (_CONFIG_DIR / "analyzer.toml").read_text(encoding="utf-8")
        )
        assert raw["analyzer"]["prompt_version"] == "v3"

    def test_wildchat_profile_uses_v4(self):
        raw = tomllib.loads(
            (_CONFIG_DIR / "analyzer_wildchat.toml").read_text(encoding="utf-8")
        )
        assert raw["analyzer"]["prompt_version"] == "v4"
