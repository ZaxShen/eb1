# Datasets — Founder Review List

Decisions pending from the Founder on Q1 (primary public corpus) and Q2 (secondary / SuperDialseg keep-or-drop) of the 2026-04-20 public-vs-synthetic roundtable. Founder constraint: **user-bot conversation only** (no user-user corpora).

Candidates summarized below from `bro/roundtable/2026-04-20-1623-public-vs-synthetic-roundtable.xml` (CTO Round 1 trap analysis + CEO reframe for memory-system framing).

---

## Primary candidates — real user↔LLM, long, natural topic drift, user-bot

All three serve the "reliable LLM memory over 400K–800K+ tokens" terminal claim natively. None require contrived session concatenation.

### WildChat (AllenAI, Zhao et al. 2024)

- **Size**: ~1M user↔ChatGPT conversations collected via public chatbot
- **Format**: user-bot, user ↔ GPT-3.5 / GPT-4
- **Length**: long sessions; many multi-turn, multi-topic
- **Gold labels**: none for segmentation; rich metadata (model, timestamp, language, toxicity)
- **License**: AI2 ImpACT LR — permissive for research, some restrictions on redistribution
- **Ingestion cost (CTO est.)**: ~25h including licensing + PII scrubbing
- **CEO lean (before Founder review)**: primary candidate

### LMSYS-Chat-1M (LMSYS, Zheng et al. 2024)

- **Size**: 1M conversations across 25+ LLMs (GPT-4, Claude, Llama, Vicuna, etc.)
- **Format**: user-bot, user ↔ various LLMs
- **Length**: varies, some very long
- **Gold labels**: none for segmentation; language + model metadata
- **License**: cleaner than WildChat per CTO / community
- **Ingestion cost**: similar ~25h
- **CEO lean (before Founder review)**: primary; preferred over WildChat on license cleanliness

### ShareGPT

- **Size**: ~90K conversations scraped from sharegpt.com
- **Format**: user ↔ GPT (mostly)
- **Length**: variable
- **Gold labels**: none
- **License**: **murky** — ToS disputes; OpenAI ToS compliance unclear for redistribution
- **Ingestion cost**: low (~10h) but license risk adds overhead
- **CEO lean**: backup only; license risk kills it for open-source release

---

## Secondary candidate — gold-labeled, smaller scope, user-bot task-oriented

### SuperDialseg (Jiang et al. 2023)

- **Size**: ~9K dialogues, derived from MultiWOZ / DSTC / SGD sources
- **Format**: user-bot task-oriented
- **Length**: moderate (task sessions)
- **Gold labels**: **YES — segmentation boundaries** (this is the only candidate with gold segmentation labels)
- **License**: research-open
- **Ingestion cost (CTO est.)**: ~12–18h
- **CEO lean (before Founder review)**: KEEP as secondary — provides single gold-backed F1 anchor for segmentation-as-instrumental-metric claim. Dropping it forfeits the only objective segmentation gold in the paper.

---

## Out (for context — Founder ruled these out or CTO marked as trap)

| Corpus | Why out |
|---|---|
| TIAGE | user-user chitchat (Founder: user-bot only) |
| MultiWOZ | user-bot but intents orthogonal to eb1 topic; ≤7 coarse classes = too shallow; memory stress weak |
| Doc2Dial | user-bot but document-grounded — document IS the memory, breaks the claim |
| SAMSum / DialogSum | user-user (Founder: user-bot only) |
| DSTC series | highly variable per track; not recommended as primary |

---

## Decision needed (for Founder)

1. **Primary corpus**: WildChat OR LMSYS-Chat-1M (CEO lean: LMSYS for license). Or a combination.
2. **SuperDialseg**: keep as secondary (CEO lean: keep), or drop to simplify.
3. **Multi-corpus count**: 1 primary = workshop-minimum viable; 2 primary (WildChat + LMSYS) = stronger non-cherry-picking defense; + SuperDialseg as anchor = full set.

Annotate your call directly in this file or route back through me (Secretary).
