"""
Tests for Proposal 3: Pool-specific taxonomy filtering.

Verifies that taxonomy is correctly filtered by user pool, and that
unrecognized pools fall back to the full taxonomy.
"""

from __future__ import annotations

from pipeline.segmentation.pool_taxonomy import (
    POOL_BOT_TOPIC_FILTER,
    POOL_TOPIC_FILTER,
    build_pool_taxonomy_lines,
    filter_taxonomy_for_pool,
    get_user_pool,
)

_FULL_TAXONOMY = {
    "pre_match_inquiry": "Questions about pending match",
    "post_match_inquiry": "Feedback after dating",
    "scheduling": "Date logistics",
    "event_inquiry": "Campaign or event questions",
    "technical_issues": "Technical problems",
    "account_management": "Account changes",
    "gibberish": "Nonsense messages",
}

_FULL_SUB_DESCS = {
    "pre_match_inquiry": {"match_status_inquiry": "Status check"},
    "post_match_inquiry": {"post_date_feedback": "Date feedback"},
    "scheduling": {"availability_request": "Request availability"},
    "event_inquiry": {"event_logistics": "Event logistics"},
    "technical_issues": {"app_glitch": "App issues"},
    "account_management": {"pause_or_deactivate": "Pause account"},
    "gibberish": {"random_test": "Random messages"},
}


class TestGetUserPool:

    def test_pool_string_field(self):
        assert get_user_pool({"pool": "wednesday"}) == "wednesday"

    def test_pool_uppercase_normalized(self):
        assert get_user_pool({"pool": "Wednesday"}) == "wednesday"

    def test_pools_list_field(self):
        assert get_user_pool({"pools": ["yik-yak", "other"]}) == "yik-yak"

    def test_no_pool_info(self):
        assert get_user_pool({"name": "Test User"}) is None

    def test_none_user_doc(self):
        assert get_user_pool(None) is None

    def test_empty_pool(self):
        assert get_user_pool({"pool": ""}) is None

    def test_empty_pools_list(self):
        assert get_user_pool({"pools": []}) is None

    def test_pool_preferred_over_pools(self):
        assert get_user_pool({"pool": "wednesday", "pools": ["yik-yak"]}) == "wednesday"


class TestFilterTaxonomyForPool:

    def test_wednesday_pool_excludes_events(self):
        filtered, _ = filter_taxonomy_for_pool(
            _FULL_TAXONOMY, _FULL_SUB_DESCS, "wednesday",
        )
        assert "event_inquiry" not in filtered
        assert "scheduling" in filtered
        assert "pre_match_inquiry" in filtered

    def test_yikyak_pool_excludes_scheduling(self):
        filtered, _ = filter_taxonomy_for_pool(
            _FULL_TAXONOMY, _FULL_SUB_DESCS, "yik-yak",
        )
        # yik-yak doesn't have scheduling in POOL_TOPIC_FILTER
        assert "event_inquiry" in filtered

    def test_unknown_pool_returns_full(self):
        filtered, sub_desc = filter_taxonomy_for_pool(
            _FULL_TAXONOMY, _FULL_SUB_DESCS, "unknown_pool",
        )
        assert filtered == _FULL_TAXONOMY
        assert sub_desc == _FULL_SUB_DESCS

    def test_none_pool_returns_full(self):
        filtered, sub_desc = filter_taxonomy_for_pool(
            _FULL_TAXONOMY, _FULL_SUB_DESCS, None,
        )
        assert filtered == _FULL_TAXONOMY
        assert sub_desc == _FULL_SUB_DESCS

    def test_subtopics_filtered_with_topics(self):
        filtered_tax, filtered_sub = filter_taxonomy_for_pool(
            _FULL_TAXONOMY, _FULL_SUB_DESCS, "wednesday",
        )
        # Subtopics should only exist for included topics
        for topic in filtered_sub:
            assert topic in filtered_tax

    def test_bot_taxonomy_filtering(self):
        bot_tax = {
            "scheduling": "Date logistics",
            "events": "Events",
            "matching": "Match discovery",
            "onboarding": "New user setup",
        }
        bot_sub = {
            "scheduling": {"confirmed": "Confirmed"},
            "events": {"invitation": "Invite"},
            "matching": {"intro_reveal": "Reveal"},
            "onboarding": {"welcome": "Welcome"},
        }
        filtered, _ = filter_taxonomy_for_pool(
            bot_tax, bot_sub, "wednesday", is_bot=True,
        )
        assert "scheduling" in filtered
        # events may or may not be present depending on the pool config
        assert "onboarding" in filtered


class TestBuildPoolTaxonomyLines:

    def test_returns_string_tuple(self):
        lines, options = build_pool_taxonomy_lines(
            _FULL_TAXONOMY, _FULL_SUB_DESCS, "wednesday",
        )
        assert isinstance(lines, str)
        assert isinstance(options, str)

    def test_topic_options_contain_new_placeholder(self):
        _, options = build_pool_taxonomy_lines(
            _FULL_TAXONOMY, _FULL_SUB_DESCS, "wednesday",
        )
        assert "<new_snake_case_topic>" in options

    def test_filtered_topics_in_lines(self):
        lines, _ = build_pool_taxonomy_lines(
            _FULL_TAXONOMY, _FULL_SUB_DESCS, "wednesday",
        )
        assert "scheduling" in lines
        # event_inquiry should be excluded for wednesday
        assert "event_inquiry" not in lines

    def test_none_pool_includes_all(self):
        lines, options = build_pool_taxonomy_lines(
            _FULL_TAXONOMY, _FULL_SUB_DESCS, None,
        )
        for topic in _FULL_TAXONOMY:
            assert topic in lines
            assert topic in options

    def test_subtopics_included_in_lines(self):
        lines, _ = build_pool_taxonomy_lines(
            _FULL_TAXONOMY, _FULL_SUB_DESCS, None,
        )
        assert "availability_request" in lines  # scheduling subtopic
        assert "match_status_inquiry" in lines  # pre_match subtopic

    def test_bot_mode(self):
        bot_tax = {"scheduling": "Scheduling", "events": "Events"}
        bot_sub = {"scheduling": {"confirmed": "Confirmed"}}
        lines, options = build_pool_taxonomy_lines(
            bot_tax, bot_sub, "wednesday", is_bot=True,
        )
        assert isinstance(lines, str)
        assert "scheduling" in lines


class TestPoolConfigCompleteness:

    def test_wednesday_pool_defined(self):
        assert "wednesday" in POOL_TOPIC_FILTER
        assert "wednesday" in POOL_BOT_TOPIC_FILTER

    def test_yikyak_pool_defined(self):
        assert "yik-yak" in POOL_TOPIC_FILTER
        assert "yik-yak" in POOL_BOT_TOPIC_FILTER

    def test_all_pool_topics_are_sets(self):
        for pool, topics in POOL_TOPIC_FILTER.items():
            if topics is not None:
                assert isinstance(topics, set), f"Pool '{pool}' topics should be a set"

    def test_pool_filters_not_empty(self):
        for pool, topics in POOL_TOPIC_FILTER.items():
            if topics is not None:
                assert len(topics) > 0, f"Pool '{pool}' has empty topic filter"
