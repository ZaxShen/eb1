# What eb1 Brings to Acme Matchmaking

> eb1 is an analysis pipeline that transforms raw chat data into structured, actionable user intelligence for Acme's matchmaking system.

---

## The Problem

Acme sits on **2.97 million chat messages** across 128K users, but today this data is opaque — it's raw text in a database. No one can answer "what do users talk about?" without manually reading conversations. Match outcomes (accepted, rejected, ghosted) exist in isolation, disconnected from the conversations that surrounded them.

---

## 1. Turns 3M Unstructured Messages into Actionable User Intelligence

eb1 transforms raw chat history into a structured, queryable knowledge base:

- Every message is assigned to a **topic segment** (pre-match inquiry, post-match feedback, scheduling conflicts, safety concerns, etc.)
- Each segment carries a **summary**, **sentiment**, and **confidence score**
- The result: `sms_chat_segments` becomes the **single source of truth** for what users care about, feel, and struggle with — queryable by topic, sentiment, time period, or user cohort

| Before eb1 | After eb1 |
|---|---|
| 2.97M raw text messages | Classified topic segments with summaries |
| "What do users complain about?" → read 1,000 chats | Query `topic = "complaints_or_support"` → instant answer |
| No sentiment data | Per-segment sentiment: positive / negative / neutral / mixed |
| No structure | 9 user topics, 7 bot topics, 40+ subtopics — and growing |

---

## 2. Connects User Conversations to Match Outcomes

eb1 extracts **binary match outcome signals** (True Positive / False Positive) from 7,100+ matchings and links them to chat segments. This enables questions no matchmaking system typically answers:

- **What topics dominate before a failed match?** If FP users disproportionately discuss `scheduling_conflict` or `match_rejection`, the matching algorithm or scheduling flow may need adjustment
- **Do TP users have different sentiment patterns?** A user who's `positive` during `pre_match_inquiry` may be a stronger match signal than profile compatibility alone
- **Which complaints predict churn?** If `frustration` segments cluster before account deactivation, we should get an early warning

**Conversation content becomes a matching quality signal** — not just profile data.

---

## 3. Discovers What the Taxonomy Doesn't Know Yet

The pipeline doesn't just classify against a fixed list — it **discovers new topics** the product team hasn't codified:

- `isNewTopic` / `isNewSubTopic` flags surface emerging user concerns automatically
- The **offline quality layer** (HDBSCAN clustering on segment embeddings) validates whether LLM-assigned topics form coherent clusters, and flags when clusters suggest a missing taxonomy entry
- Human review of flagged segments feeds back into the taxonomy — the system gets smarter over time

Acme's understanding of user needs **evolves with the user base** rather than staying frozen at whatever the product team assumed at launch.

---

## 4. Makes Bot Performance Measurable

Every segment tracks engagement metrics:

| Metric | What it measures |
|---|---|
| `hasUserEngagement` | Did the user actually respond? |
| `responseRate` | Ratio of user responses to bot prompts (0.0–1.0) |
| `hasBotFailure` | Did the bot leave a user message unanswered? |

This gives the ops and AI teams hard data on bot effectiveness by topic:

- "Users respond to 80% of onboarding prompts but only 30% of reengagement messages" → rewrite reengagement templates
- "Bot failure rate is 15% during scheduling segments" → the assistant drops the ball on date logistics
- "Automated template messages have 0% engagement on `weekly_update`" → these messages may be not effective for user

---

## 5. Separates Bot-Initiated Noise from User-Initiated Signal

The **three-tier routing system** distinguishes:

| Tier | What it is | What it tells you |
|---|---|---|
| Pure automated (108 templates) | System-sent messages with no user reply | Operational baseline — what does the bot say to everyone? |
| Mixed bot (assistant/team) | AI or human operator messages without user engagement | Where the bot tries and fails to engage |
| User-engaged | Conversations where the user actually participated | **The real signal** — what users voluntarily talk about |

Without this separation, automated onboarding messages drown out genuine user feedback in any aggregate analysis. eb1 ensures that when you query "what are users frustrated about?", you get real frustration — not bot templates misclassified as negative sentiment.

---

## 6. Enables Human-in-the-Loop Quality at Scale

The review routing system creates a **prioritized queue** for human labelers:

| Priority | Trigger | Purpose |
|---|---|---|
| P1 | `isNewTopic = true` | Expand product understanding |
| P2 | `isNewSubTopic = true` | Refine topic granularity |
| P3 | Low `labelConfidence` | Correct LLM mistakes |

Each human review writes `trueTopic` / `trueSubTopic` back to the segment, which:

- Becomes **immutable training data** — reviewed segments survive pipeline re-runs
- Feeds **label accuracy metrics** — measurable improvement over time
- Eventually enables **supervised classification** (Phase 3) when 50–200 labels per topic accumulate

This is a flywheel: more reviews → better LLM accuracy → fewer reviews needed → humans focus on edge cases only.

---

## 7. Benchmark Infrastructure for LLM Selection

The benchmark system evaluates **any LLM** on the same user conversations:

- Run GPT-5.4-mini, Claude Sonnet, Gemini Flash, DeepSeek, Llama, etc. side-by-side
- Each run writes to its own collection with full provenance (`analyzerMeta`: model, prompt version, temperature, duration)
- Compare topic agreement, confidence calibration, and processing speed across models

The team makes **data-driven model decisions** rather than guesses. When a new model drops, run the benchmark on a sample in minutes and see if it's better.

---

## 8. Concrete Downstream Applications

### Data Science Team

| Application | How eb1 Enables It |
|---|---|
| **Matching algorithm improvement** | Topic + sentiment distributions per TP/FP cohort reveal which user states predict good vs bad matches. Feed segment features into the matching score model as conversation-derived signals. |
| **Intention prediction** | Segment sentiment trends over time → predict user intent (likely to accept match, about to ghost, ready to churn) before it happens. Train classifiers on the labeled segment history. |
| **User lifecycle modeling** | Segment timestamps + topics trace each user's journey (onboarding → pre-match → post-match → feedback). Identify where users drop off and which paths lead to successful dates. |
| **Cohort analysis** | Slice segment data by school, pool, signup date, or match history. Compare topic distributions across cohorts — e.g. "USC users have 3x more `event_inquiry` segments than UCLA users." |
| **Engagement scoring** | Combine `responseRate`, `hasUserEngagement`, and segment count into a per-user engagement score. Correlate with match success to weight active users higher in the matching pool. |
| **Sentiment-driven match timing** | Analyze sentiment trends to find optimal windows for sending matches — users in a `positive` sentiment streak may be more receptive than users mid-`frustration` segment. |
| **Feature engineering for ML** | Segment-level features (topic distribution, avg sentiment, response rate, bot failure rate) become columns in any downstream ML model — churn prediction, match quality prediction, LTV estimation. |

### AI / Chatbot Team

| Application | How eb1 Enables It |
|---|---|
| **Bot prompt optimization** | Response rate per topic per template → A/B test bot messages with ground truth. Know exactly which automated messages users ignore vs engage with. |
| **Conversation flow redesign** | `hasBotFailure` pinpoints where the bot drops user messages. Map failure patterns by topic to find systematic gaps in the bot's intent handling. |
| **Template effectiveness ranking** | 108 classified templates × engagement data → rank every automated message by actual user response rate. Kill underperforming templates, double down on effective ones. |
| **Context-aware responses** | The bot can query a user's recent segments before responding. A user whose last 3 segments are `pre_match_inquiry` with `negative` sentiment needs a different tone than a first-time onboarder. |
| **Intent detection training data** | Reviewed segments with `trueTopic` / `trueSubTopic` become labeled training data for fine-tuning the bot's intent classifier — no separate labeling effort needed. |
| **Response rate benchmarking** | Track `responseRate` over time as the bot is updated. Measure whether prompt changes actually improve user engagement, broken down by topic. |
| **Escalation triggers** | Auto-detect segments with `urgent_safety_issues` or repeated `complaints_or_support` with `negative` sentiment → trigger human handoff before the user has to ask. |
| **Bot persona calibration** | Sentiment data per topic reveals where the bot's tone mismatches user expectations. `negative` sentiment on `scheduling` segments may mean the bot sounds too casual about logistics. |

### Product Team

| Application | How eb1 Enables It |
|---|---|
| **Product roadmap prioritization** | Topic distribution across 130K users → data-backed feature decisions. "42% of complaints are about scheduling" is a concrete argument for building a better scheduling UX. |
| **Feature gap discovery** | `isNewTopic` and `isNewSubTopic` segments surface user needs the product doesn't address yet. New topics appearing across multiple users = unmet demand. |
| **Event ROI measurement** | `event_inquiry` segments per event (yik-yak, love-yacht, nyc-gala) × sentiment → measure which events generate excitement vs confusion. Track pre-event vs post-event sentiment shift. |
| **Onboarding funnel analysis** | Segment the onboarding flow by subtopic (`welcome`, `photo_request`, `email_verify`, `app_completion`). Measure drop-off between each step using engagement data — find exactly where users stall. |
| **Safety & trust metrics** | Track `urgent_safety_issues` volume over time as a product health metric. Report `harassment`, `privacy_breach`, `unsafe_situation` counts to leadership with trend lines. |
| **User voice for stakeholders** | Segment summaries are LLM-generated natural language. Export topic clusters with representative summaries for investor decks, board reports, or user research presentations — no manual reading required. |
| **Match quality feedback loop** | `post_match_inquiry` segments with subtopics like `match_rejection` (reason) and `post_date_feedback` (what worked) feed directly into matching criteria refinement. Know *why* users reject matches, not just *that* they do. |
| **Notification strategy** | Template engagement data reveals which automated messages users care about. Product can redesign notification cadence — fewer ignored messages, higher signal-to-noise ratio in the user's chat. |
| **School-level insights** | Segment data sliced by `users.school` → per-campus dashboards. Different universities may have different dominant topics, event interest levels, or safety concern rates. Tailor the product per campus. |

---

## Pipeline at a Glance

```
signal → segment → validate → evaluate
  │         │          │          │
  │         │          │          └─ Topic distribution, confidence metrics,
  │         │          │             taxonomy novelty, review routing
  │         │          │
  │         │          └─ 33 deterministic graders (L0–L4):
  │         │             data integrity, segmentation quality,
  │         │             cluster quality, label quality, signal correlation
  │         │
  │         └─ Three-tier routing:
  │            • Automated → Python template match (no LLM)
  │            • Mixed bot → LLM + bot taxonomy
  │            • User-engaged → LLM + user taxonomy
  │
  └─ TP/FP signal extraction from 7,100+ matchings
```

### Offline Quality Layer (periodic)

```
embed summaries → UMAP + HDBSCAN → cluster validation → taxonomy discovery
```

---

## 9. Three-Tier Routing: Token Savings and Time Efficiency

The pipeline evolved from sending **every message** to an LLM, to a three-tier routing system that classifies bot-only automated messages with Python (`difflib` template matching) — zero LLM cost, near-zero latency.

### What changed

| Approach | How bot-only automated messages are classified |
|---|---|
| **Old (pure LLM)** | Every chunk — including pure automated templates — sent to LLM. Each call carries ~2,861 tokens of prompt overhead (system prompt + taxonomy). |
| **New (three-tier)** | Pure automated chunks → Python `difflib` template matching (~0.1ms per chunk). Only unmatched automated + mixed bot + user-engaged chunks go to LLM. |

### Messages routed to Python

Based on sampling 2,000 PROD chats against 2.97M messages:

| Metric | Value |
|---|---|
| Messages classified by Python (no LLM) | **174,302** |
| LLM calls eliminated | **26,015** |
| Python processing time for all 26K chunks | **2.6 seconds** total |
| % of all messages handled without LLM | **5.9%** |

> 91.7% of bot-only chunk messages are pure `automated` type — ideal candidates for template matching.

### Token savings (per full pipeline run across 130K users)

| | Input tokens saved | Output tokens saved | Total tokens saved |
|---|---|---|---|
| Message content tokens | 5,403,362 | — | 5,403,362 |
| Prompt overhead (26K fewer LLM calls x 2,861 tokens) | 74,428,915 | — | 74,428,915 |
| LLM response tokens (26K fewer segment JSONs) | — | 3,902,250 | 3,902,250 |
| **Total** | **79,832,277** | **3,902,250** | **83,734,527** |

**~83.7M tokens saved per full run — 43.5% reduction in total token volume.**

### Cost savings per full pipeline run

| Model | Full run cost (old) | Savings | % saved |
|---|---|---|---|
| GPT-4.1-mini | $146 | **$38** | 26.1% |
| GPT-4.1 | $732 | **$191** | 26.1% |
| Claude Sonnet 4 | $1,272 | **$298** | 23.4% |
| Claude Opus 4 | $6,359 | **$1,490** | 23.4% |

### Time efficiency (wall-clock with 4x concurrency)

| Model | Old wall time | New wall time | Time saved | Speed improvement |
|---|---|---|---|---|
| Local Ollama (20B) | 11.4 hours | 4.1 hours | **7.2 hours** | **63.6% faster** |
| GPT-4.1-mini (API) | 4.3 hours | 1.5 hours | **2.7 hours** | **63.6% faster** |
| Claude Sonnet 4 (API) | 5.7 hours | 2.1 hours | **3.6 hours** | **63.6% faster** |

> Python template matching replaces 26,015 LLM calls with 2.6 seconds of `difflib` computation. The pipeline runs **~64% faster** at scale.

### Why the savings are larger than 5.9%

While only 5.9% of messages are routed to Python, each eliminated LLM call also removes **2,861 tokens of prompt overhead** (system prompt + taxonomy injection). With 26,015 fewer calls, the overhead savings alone account for 74M tokens — far more than the message content savings. This is why the total reduction reaches 43.5%.

---

## The Bottom Line

Without eb1, Acme has **profiles and match outcomes**.

With eb1, Acme has **profiles, match outcomes, and everything users said in between** — structured, classified, and queryable.

That middle layer is where the insight lives: why matches succeed, why they fail, what users want that they're not getting, and how the bot can do better.

---

## Scale

| Data | Count |
|---|---|
| PROD users | 130,703 |
| PROD matchings | 7,104 |
| PROD chat sessions | 128,489 |
| PROD messages | 2,974,056 |
| PROD message templates | 144 |
| Extracted match signals | 2,373 |
| Classified templates | 82 |
| User topic categories | 9 |
| Bot topic categories | 7 |
| Subtopics (combined) | 40+ |
| Quality graders | 33 (14 implemented) |
| Automated tests | 147 |
