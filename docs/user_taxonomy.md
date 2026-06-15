# User Taxonomy — User Message Classification

Use this taxonomy to classify chat message segments from Acme, a university matchmaking app. Each segment covers exactly one topic. Select the topic and subtopic whose description best matches what the user is doing in the segment.

---

## `technical_issues`

The user reports that a Acme product feature is broken, blocked, or behaving unexpectedly. The problem is caused by a system error, not by user preference or match outcome. Does NOT include: account changes the user initiates voluntarily (→ `account_management`), or match-related dissatisfaction without a technical root cause (→ `complaints_or_support`).

| Subtopic | Description |
|---|---|
| `message_not_received` | User reports that a message was not delivered or arrived with a significant delay. Does NOT include: bot automated messages the user finds unhelpful (→ `complaints_or_support`). |
| `upload_failure` | User reports that a photo, video, or profile content item failed to upload or is not displaying correctly. |
| `app_glitch` | User reports unexpected app behavior: crashes, blank screens, repeated prompts, loops, or UI errors that are not related to login or upload. |
| `verification_issue` | User is blocked at an email or phone verification step and cannot proceed. Does NOT include: forgotten password or locked account (→ `login_problem`). |
| `login_problem` | User cannot log in or access their account due to a forgotten password, locked account, or authentication error. Does NOT include: phone or email verification failures before the account exists (→ `verification_issue`). |

## `pre_match_inquiry`

The user asks about the status or timeline of their upcoming match while no active match has been assigned yet. The user is waiting in the pool. Does NOT include: questions about a match that has already been sent (→ `post_match_inquiry`).

| Subtopic | Description |
|---|---|
| `match_release_inquiry` | User asks when their match will be released or sent — focused on the release date or schedule ("When do I get my match?"). Does NOT include: questions about where the match process currently stands (→ `match_status_inquiry`). ← CHANGED |
| `match_status_inquiry` | User asks for a progress update on their match processing — focused on current state, not timing ("Is my match being processed? Has anything changed?"). Does NOT include: questions about the release date or schedule (→ `match_release_inquiry`). ← CHANGED |
| `pool_enrollment_inquiry` | User asks whether they are currently enrolled in or active within the matching pool ("Am I still in the pool? Did my sign-up go through?"). ← CHANGED |
| `pre_match_feedback` | User provides unsolicited opinions, complaints, or suggestions about the matching process or their experience while still waiting for a match — before any match has been sent. Includes: expressing dissatisfaction with wait time, commenting on the process quality, or offering suggestions for improvement. Does NOT include: questions about timing or status (→ `match_release_inquiry`, `match_status_inquiry`). ← CHANGED |

## `post_match_inquiry`

The user is responding to or asking about a match that has already been sent. The match exists. Does NOT include: questions asked before any match is assigned (→ `pre_match_inquiry`).

| Subtopic | Description |
|---|---|
| `match_candidate_info` | User asks Acme for more information about their assigned match candidate — their personality, background, appearance, contact details, or social profiles. Does NOT include: asking whether the candidate has responded or chosen a time (→ `match_engagement_info`). ← CHANGED |
| `match_engagement_info` | User asks whether their match candidate has responded, picked a date/time, or what the candidate thinks of them. Focused on the candidate's actions or interest level. Does NOT include: requests for biographical or profile information about the candidate (→ `match_candidate_info`). ← CHANGED |
| `match_availability` | User and their match candidate have a scheduling conflict: the user cannot meet at the proposed time, or dates are not overlapping. The match is still active and the user wants to reschedule, not cancel. Does NOT include: cancelling the match outright (→ `match_management`). |
| `match_management` | User rejects, cancels, or goes unresponsive on an active match. Includes: declining a match outright (not their type, already know them), cancelling a confirmed date, and no-reply to match prompts. Does NOT include: scheduling conflicts where the user still wants to meet (→ `match_availability`), post-date quality feedback (→ `date_feedback`), or no-shows reported on the day of the date (→ `date_execution`). |
| `date_execution` | User reports an outcome at the point the date was supposed to happen: a no-show, a ghost, a request to skip to the next match, or a signal that the date occurred. This is about events on or after the date day. Does NOT include: cancellations made in advance (→ `match_management`) or reflective feedback after the date (→ `date_feedback`). ← CHANGED |
| `date_feedback` | User shares reflective feedback about a date that has already taken place — what they liked, what did not work, whether they want to see the person again. Does NOT include: reporting a no-show or ghost on the date day (→ `date_execution`), or rejecting a match before the date happens (→ `match_management`). ← CHANGED |

## `account_management`

The user voluntarily requests a change to their own account or profile. The user is initiating the action, not reporting a system error. Does NOT include: system errors that prevent account actions (→ `technical_issues`).

| Subtopic | Description |
|---|---|
| `update_bio` | User asks to update their photos, written prompts, or bio text. Does NOT include: requests for advice on how to improve the profile (→ `improve_profile_request`). ← CHANGED |
| `improve_profile_request` | User asks Acme to review or suggest improvements to their existing profile quality — photos, prompts, or overall attractiveness to matches. Does NOT include: simply submitting new content to replace existing content (→ `update_bio`). ← CHANGED |
| `update_contact_info` | User requests a change to their phone number or school/university affiliation on their account. |
| `pause_or_deactivate` | User requests to pause matching activity temporarily or deactivate their account entirely. |

## `requests_or_improvements`

The user makes a forward-looking request intended to influence future match quality or priority. Does NOT include: feedback about a specific past match (→ `post_match_inquiry`) or general dissatisfaction without a specific ask (→ `complaints_or_support`).

| Subtopic | Description |
|---|---|
| `priority_request` | User explicitly asks to be moved up in the matching queue or given priority treatment. ← CHANGED |
| `rematch_request` | User asks to be re-entered into the pool or matched again after a previous match ended. ← CHANGED |
| `better_match_advice` | User asks Acme what they can do to receive better or more compatible matches in the future — seeking actionable advice. Does NOT include: stating preferences the user wants the system to record (→ `preferences_sharing`). ← CHANGED |
| `preferences_sharing` | User states specific preferences — such as age range, major, personality traits, or lifestyle — that are not currently captured in their profile and wants Acme to factor into matching. Does NOT include: asking what to do to get better matches (→ `better_match_advice`). ← CHANGED |

## `complaints_or_support`

The user expresses a negative emotion, personal concern, or interpersonal situation that does not fit a specific operational category. No concrete product action is being requested. Does NOT include: specific product requests (→ `requests_or_improvements`), non-urgent safety concerns that name a specific person or incident (→ `urgent_safety_issues`).

| Subtopic | Description |
|---|---|
| `frustration` | User expresses anger, annoyance, or disappointment directed at the Acme product, service, or process — without requesting a specific change. Includes: venting about wait times, bad match quality, or the app in general. Does NOT include: anxiety or worry about the future (→ `dating_anxiety`), or sharing personal life context unrelated to the product (→ `personal_sharing`). ← CHANGED |
| `safety_concern` | User raises a non-urgent privacy or safety concern — such as worrying about who can see their profile, being uncomfortable with data usage, or feeling uneasy about a match — without reporting an active incident. Does NOT include: active harassment, threats, or ongoing unsafe situations (→ `urgent_safety_issues`). ← CHANGED |
| `dating_anxiety` | User expresses worry, nervousness, or self-doubt related to dating or the waiting process — not anger at the product. Includes: fear of rejection, insecurity about attractiveness, nervousness about meeting someone. Does NOT include: anger or frustration directed at Acme (→ `frustration`), or sharing personal life updates unrelated to dating anxiety (→ `personal_sharing`). ← CHANGED |
| `personal_sharing` | User shares personal life context, stories, or emotional updates that are not complaints about Acme and not requests for action. Includes: talking about their day, sharing life events, or explaining personal circumstances. Does NOT include: product feedback or frustration (→ `frustration`), or anxiety specifically about dating or the app wait (→ `dating_anxiety`). ← CHANGED |

## `urgent_safety_issues`

The user reports an active, serious incident involving their safety, privacy, or account security that requires immediate human attention. These messages must not be auto-accepted. Does NOT include: general discomfort or non-urgent concerns (→ `complaints_or_support → safety_concern`).

| Subtopic | Description |
|---|---|
| `harassment` | User reports that another user or person has sent threatening, sexually explicit, abusive, or persistently unwanted messages. Includes: reports about a match or any other person on or off the platform. ← CHANGED |
| `unsafe_situation` | User reports being in or recently experiencing a physically or emotionally unsafe situation connected to a Acme match or event. Includes: feeling threatened in person, coercion, or a dangerous meeting. Does NOT include: inappropriate messages only (→ `harassment`). ← CHANGED |
| `privacy_breach` | User reports that their personal information — phone number, photos, school, or identity — has been shared, exposed, or used without consent. Does NOT include: general discomfort with privacy settings (→ `complaints_or_support → safety_concern`). ← CHANGED |
| `account_protection` | User reports urgent unauthorized access to their account: a suspected hack, unauthorized login, or requests to lock or recover the account immediately. Does NOT include: routine forgotten-password issues (→ `technical_issues → login_problem`). ← CHANGED |

## `event_inquiry`

The user asks about or has an issue with a specific Acme event or campaign. Known events include: yik-yak, la-love-yacht, love-yacht, nyc-gala. Does NOT include: general matching questions unrelated to a named event (→ `pre_match_inquiry` or `post_match_inquiry`). ← CHANGED

| Subtopic | Description |
|---|---|
| `event_eligibility` | User asks whether they qualify for or have been invited to a specific event. ← CHANGED |
| `rsvp_confirmation` | User confirms their RSVP, asks whether their sign-up was received, or opts in to an event. ← CHANGED |
| `event_logistics` | User asks about the practical details of the event: time, location, dress code, rules, or what to expect. Does NOT include: how to get there or check in (→ `transportation_checkin`). ← CHANGED |
| `transportation_checkin` | User asks about transportation to the event venue or the check-in process on arrival. Does NOT include: general event details such as time and dress code (→ `event_logistics`). ← CHANGED |
| `timing_inquiry` | User asks about when or how their match will be revealed in the context of the event — for example, whether the reveal happens at the event or beforehand. ← CHANGED |
| `event_changes` | User asks about or reacts to a change in event plans: a cancellation, date shift, venue change, or modification to the format. ← CHANGED |
| `waitlist_status` | User asks whether they are on the waitlist for an event and whether their status has changed. ← CHANGED |
| `guest_policy` | User asks whether they can bring a guest to the event or asks about the rules around plus-ones. ← CHANGED |

## `gibberish`

The user's message contains no actionable content related to the Acme product. Assign this topic only when no other topic applies. Does NOT include: emotional venting or off-topic personal sharing that still warrants a response (→ `complaints_or_support → personal_sharing`). ← CHANGED

| Subtopic | Description |
|---|---|
| `mistaken_message` | User sent a message to Acme that was clearly intended for someone else — for example, a message addressed to a friend or containing a private conversation. ← CHANGED |
| `random_test` | User sent random characters, numbers, or nonsense words to test whether Acme is working. ← CHANGED |
| `off_product_question` | User asks Acme a question that has no relation to the product — such as weather, trivia, homework help, or general life questions. ← CHANGED |

---

**Additional note on interpreting chats:** Internal system logs may show a message as sent or delivered when the user did not actually receive the full content. Treat user reports of non-delivery as credible even when system logs indicate success.

---

## Rewritten Output

See above — the full rewritten taxonomy is the body of this document. All changes are marked with `← CHANGED`.

## Flags

- **[FLAG-1] `match_release_inquiry` vs `match_status_inquiry` (still potentially confusable):** Both subtopics live under `pre_match_inquiry` and both involve asking about a pending match. The rewrite distinguishes "when" (release timing) from "where in the process" (status), but a user message like "What's happening with my match?" could plausibly land in either. Recommend: consider merging these two subtopics into a single `match_status_inquiry` with the combined description, unless analytics data shows they cluster separately.

- **[FLAG-2] `better_match_advice` vs `preferences_sharing` (still potentially confusable):** The rewrite draws the line at "seeking advice" vs "stating a preference to record." However, users often do both in the same message ("I prefer someone athletic — how do I make sure I get matched with one?"). This pair may generate mixed-topic segments frequently. Recommend: verify with real chat examples that these two reliably appear as separate intents before keeping them as distinct subtopics.

- **[FLAG-3] `frustration` vs `dating_anxiety` (still potentially confusable):** Both are negative emotional states. The rewrite directs `frustration` at product-directed anger and `dating_anxiety` at inward-directed worry. In practice, a user may express both simultaneously ("I've been waiting so long and I'm scared I'll never find someone"). The LLM will need to split this into two segments or pick the dominant tone. Human verification of boundary cases is recommended.

- **[FLAG-4] `pre_match_feedback` — judgment call on scope:** The original description ("Feedback before match sent") was too vague to distinguish from status inquiries. The rewrite defines it as unsolicited commentary or suggestions about the process itself. Verify with the product team whether this subtopic is intended to capture formal feedback submissions or informal venting, as those may need separate labels.

- **[FLAG-5] Topic slug naming inconsistency between `user_taxonomy.md` and `taxonomy.yaml`:** The slugs in this document (`technical_issues`, `pre_match_inquiry`, `post_match_inquiry`, `account_management`, `requests_or_improvements`, `complaints_or_support`, `urgent_safety_issues`) do not match the slugs in `pipeline/config/taxonomy.yaml` (`technical_access`, `match_status`, `match_feedback`, `account_profile`, `requests_improvements`, `complaints_emotional`, `safety_urgent`). The LLM is injected with `taxonomy.yaml` slugs at runtime. This document should either be updated to match `taxonomy.yaml` slugs exactly, or explicitly marked as a human-facing reference that does not reflect the runtime taxonomy. Current mismatch risks confusing anyone who uses this document to audit or debug LLM outputs.

- **[FLAG-6] `date_execution` structural placement — judgment call:** `date_execution` covers events at the time the date was supposed to happen (no-show, ghost, skip, date-happened signal). This sits alongside `date_feedback` (post-date reflection) and `match_management` (pre-date cancellation). The three form a natural timeline sequence, but the boundary between `date_execution` and `match_management` (same-day cancellation vs. advance cancellation) may be unclear in practice. Human review of edge cases recommended.

- **[FLAG-7] `off_product_question` slug mismatch:** This document uses `off_product_question`; `taxonomy.yaml` uses `off_topic_question`. Align to one slug.
