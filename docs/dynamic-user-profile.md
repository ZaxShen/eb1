# Dynamic User Profile (DUP)

## Overview

Dynamic User Profile is a downstream consumer of the eb1 pipeline. It queries classified chat segments — particularly user match feedback — to construct a **shadow profile** for each user: a living representation of preferences, behaviors, and social signals that the user never explicitly declares but reveals through conversation.

The core insight: **matchmaking is an Amazon shopping experience, but Amazon has hundreds of signal sources (clicks, views, carts, returns, reviews). Acme has one — chat messages.** DUP extracts maximum signal from that single source.

---

## Why DUP Matters

Traditional matchmaking optimizes for one dimension: *attraction compatibility* — how well two users' stated preferences align. This is insufficient. A high-compatibility match is worthless if one party ghosts, and a moderate-compatibility match can succeed when both parties are engaged and reliable.

DUP adds two missing dimensions:

1. **Behavioral credit** — Does this user follow through? Do they ghost, cancel, or no-show? A credit score derived from match outcomes, not self-reported behavior.
2. **Revealed preferences** — What does a user *actually* want, as opposed to what they *say* they want? Extracted from feedback on real matches.

---

## Signal Extraction

### Bidirectional Feedback Interpretation

Every piece of match feedback carries signal about **both** users involved. A single feedback event decomposes into two updates:

| Feedback | Signal for the reviewer (User A) | Signal for the reviewed (User B) |
|---|---|---|
| "User B wasn't tall enough" | A prefers taller partners (preference update) | B is perceived as not tall (shadow profile update) |
| "Great conversation, but no spark" | A values physical chemistry over conversation | B is a good conversationalist (positive trait) |
| "They were late and seemed disinterested" | A values punctuality and engagement | B has a punctuality/engagement issue (credit signal) |
| "We're going on a second date!" | A is an active, follow-through user (credit positive) | B is an active, follow-through user (credit positive) |

### Signal Categories

**1. Preference Signals** (what a user wants)
- Extracted from feedback *given* by the user about their matches
- Updates the user's revealed preference model, which may diverge from their stated preferences
- Examples: height preference, conversation style, energy level, lifestyle compatibility

**2. Shadow Profile Signals** (what a user *is*)
- Extracted from feedback *received* about the user from their matches
- Builds an external perception profile that the user cannot self-report
- Examples: perceived attractiveness, conversation quality, punctuality, authenticity vs. photos

**3. Behavioral Signals** (how a user behaves)
- Extracted from interaction patterns, not explicit feedback
- Ghosting detection: user stops responding after a match is made (invisible to Acme without chat analysis)
- Engagement level: response times, message depth, initiative in scheduling
- Platform loyalty: sustained activity over time, re-engagement after dormancy

---

## Credit Score

A composite behavioral score per user, derived from:

| Factor | Positive signal | Negative signal |
|---|---|---|
| **Follow-through** | Confirms dates, shows up, sends follow-ups | Ghosts, cancels last-minute, no-shows |
| **Engagement quality** | Thoughtful messages, asks questions, reciprocates | One-word replies, ignores messages |
| **Platform commitment** | Consistent weekly activity, responds to matches | Long dormancy, ignores match notifications |
| **Match outcomes** | Mutual positive feedback, second dates | Repeated negative feedback from matches |

Credit score is **not** a punishment mechanism — it's a matching input. High-credit users should be matched with other high-credit users, preventing reliable users from being burned by unreliable ones.

---

## Architecture

### Data Flow

```
Chat Messages
    → eb1 Pipeline (segmentation + classification)
        → Classified Segments (topic, subtopic, summary)
            → DUP Signal Extractor
                → Per-user signal events
                    → DUP Aggregator
                        → User Shadow Profile snapshot
```

### eb1 Dependency

DUP consumes eb1's classified segments, specifically:

| eb1 Segment Type | DUP Usage |
|---|---|
| **Match feedback** (user-engaged) | Primary signal source — bidirectional preference and shadow profile extraction |
| **Match outcome** (bot + user) | Behavioral signals — ghosting, follow-through, re-engagement |
| **Scheduling interactions** | Credit signals — cancellations, confirmations, no-shows |
| **Re-engagement responses** | Loyalty signals — does the user come back after dormancy? |

eb1's subtopic classification directly determines which DUP signal extractor runs. This is why eb1 accuracy — especially user-engaged subtopic accuracy — matters so much for DUP.

### Profile Snapshots

DUP profiles are **versioned snapshots**, not mutable state. Each snapshot captures:

- All accumulated signals up to a point in time
- The derived preference model
- The shadow profile
- The credit score
- The eb1 segments that contributed (audit trail)

Snapshots enable:
- **Simulation** — replay matchmaking decisions against historical profiles to evaluate algorithm changes
- **Training** — use snapshot pairs (User A profile + User B profile) with known match outcomes as training data for AI matchmaking
- **Debugging** — trace any matching decision back to the signals that informed it

---

## Downstream: AI Matchmaking

With DUP snapshots, matchmaking evolves from rule-based compatibility scoring to learned optimization:

1. **Feature set**: Each user's DUP snapshot provides a rich feature vector (revealed preferences, shadow traits, credit score, engagement patterns)
2. **Training data**: Historical match outcomes (success/failure) paired with the DUP snapshots at the time of the match
3. **Objective**: Optimize for match *outcomes* (mutual positive feedback, second dates), not just match *compatibility* (preference alignment)
4. **Simulation**: Test new matching algorithms against historical DUP snapshots before deploying to real users

This closes the loop: chat messages (eb1) become user understanding (DUP) become better matches (AI matchmaking) produce new chat messages.

---

## Relationship to eb1 Pipeline Proposals

The [pipeline improvement proposals](./pipeline-improvement-proposals.md) directly impact DUP quality:

| Proposal | DUP Impact |
|---|---|
| **P4** (scheduling rules) | Cleaner scheduling signal extraction — no more misclassified reminders polluting behavioral signals |
| **P2** (GT validation) | Fewer hallucinated subtopics means DUP signal extractors route to the correct handler |
| **P3** (pool-specific taxonomy) | Pool-aware classification improves signal relevance per user cohort |
| **P1** (skip first segment) | Minor — first automated segments carry no DUP-relevant signal |

User-engaged subtopic accuracy is the most critical eb1 metric for DUP — it determines whether feedback is routed to the correct signal extractor.
