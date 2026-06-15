"""Shared test fixtures for the analysis pipeline tests."""

import pipeline.config.loader as _loader


def pytest_configure(config):
    """Populate taxonomy module-level dicts with test data.

    The real pipeline calls ``init_taxonomy(db)`` at startup.  Tests don't
    have a DB connection, so we inject a minimal taxonomy here so that
    INITIAL_TAXONOMY / KNOWN_SUBTOPICS / SUBTOPIC_DESCRIPTIONS are available
    for any test that imports them (e.g. segmenter, reporter).
    """
    _loader.INITIAL_TAXONOMY.update({
        "pre_match_inquiry": "Questions about pending match assignment",
        "post_match_inquiry": "Feedback or changes after dating",
        "technical_issues": "Technical & Access Issues",
        "account_management": "User-initiated account changes",
        "requests_or_improvements": "Requests affecting matching outcomes",
        "complaints_or_support": "Negative experiences or emotional expression",
        "urgent_safety_issues": "High-priority situations",
        "event_inquiry": "Campaign or event questions",
        "gibberish": "Nonsense or irrelevant messages",
    })
    _loader.KNOWN_SUBTOPICS.update({
        "pre_match_inquiry": {
            "match_release_inquiry", "match_status_inquiry",
            "pool_enrollment_inquiry", "pre_match_feedback",
        },
        "post_match_inquiry": {
            "match_rejection", "scheduling_conflict",
            "cancellation_noshow", "post_date_feedback",
        },
        "technical_issues": {
            "message_not_received", "upload_failure", "app_glitch",
            "verification_issue", "login_problem",
        },
        "account_management": {
            "update_bio", "improve_profile_request",
            "update_contact_info", "pause_or_deactivate",
        },
        "requests_or_improvements": {
            "priority_request", "rematch_request",
            "better_match_advice", "uncaptured_preferences",
        },
        "complaints_or_support": {
            "frustration", "safety_concern",
            "dating_anxiety", "personal_sharing",
        },
        "urgent_safety_issues": {
            "harassment", "unsafe_situation",
            "privacy_breach", "account_protection",
        },
        "event_inquiry": {
            "event_eligibility", "rsvp_confirmation", "event_logistics",
            "transportation_checkin", "timing_inquiry", "event_changes",
            "waitlist_status", "guest_policy",
        },
        "gibberish": {
            "mistaken_message", "random_test", "off_product_question",
        },
    })
    _loader.SUBTOPIC_DESCRIPTIONS.update({
        slug: {st: "" for st in subs}
        for slug, subs in _loader.KNOWN_SUBTOPICS.items()
    })
    _loader.TOPIC_CONFIRMED.update({
        slug: True for slug in _loader.INITIAL_TAXONOMY
    })
    _loader.SUBTOPIC_CONFIRMED.update({
        slug: {st: True for st in subs}
        for slug, subs in _loader.KNOWN_SUBTOPICS.items()
    })

    # ── Template (bot) taxonomy ──────────────────────────────────────────────
    _loader.BOT_TAXONOMY.update({
        "account": "Account status — issue resolution, seasonal pauses",
        "events": "Special events and campaigns — invitations, reminders, tickets",
        "matching": "Match discovery, reveals, engagement, and reactivation",
        "onboarding": "New user setup — welcome, application, photos, verification",
        "promotions": "Giveaways and reward claims",
        "scheduling": "Date logistics — availability, confirmation, rescheduling, followup",
        "system": "Malformed or non-user-facing messages",
    })
    _loader.BOT_KNOWN_SUBTOPICS.update({
        "account": {"holiday_pause", "issue_resolved", "winter_pause"},
        "events": {"invitation", "reminder", "ticket_guest", "waitlist"},
        "matching": {
            "intro_reveal", "reengagement", "resume_weekly",
            "time_selected", "weekly_update",
        },
        "onboarding": {
            "app_completion", "email_verify", "issue_resolved",
            "photo_request", "welcome",
        },
        "promotions": {"giveaway_claim"},
        "scheduling": {
            "availability_reminder", "availability_request",
            "confirmed", "no_show_reason", "post_date_check",
            "reschedule", "time_selected",
        },
        "system": {"malformed_payload"},
    })
    _loader.BOT_SUBTOPIC_DESCRIPTIONS.update({
        slug: {st: "" for st in subs}
        for slug, subs in _loader.BOT_KNOWN_SUBTOPICS.items()
    })
    _loader.BOT_TOPIC_CONFIRMED.update({
        slug: True for slug in _loader.BOT_TAXONOMY
    })
    _loader.BOT_SUBTOPIC_CONFIRMED.update({
        slug: {st: True for st in subs}
        for slug, subs in _loader.BOT_KNOWN_SUBTOPICS.items()
    })
