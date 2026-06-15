# LLM Benchmark — Model Comparison for Analyzer

> Tested 2026-03-17 via Vercel AI Gateway (`https://ai-gateway.vercel.sh/v1`).
> Task: chat topic segmentation + classification (structured JSON output).

---

## Use Case Requirements

The Analyzer receives a user's chat history and must:

1. **Group messages into topic segments** — each segment covers exactly one topic
2. **Handle non-contiguous grouping** — messages about the same topic may be scattered across the conversation (e.g., user discusses match timing at messages 0-1, switches to a tech issue, then returns to match timing at messages 5,7,8 — all must merge into ONE segment)
3. **Handle multi-topic messages** — a single message may cover multiple topics and must appear in multiple segments (e.g., "Still no match and the photo upload is STILL broken" covers both `match_status` and `technical_access`)
4. **Return valid structured JSON** with `messageIndices`, `summary`, `topic`, `subTopic`, `sentiment`, `labelConfidence`, `isNewTopic`

Constraint: prompt engineering only — no RAG, no fine-tuning.

---

## Test Methodology

10 models tested on a 10-message chat with 3 interleaved topics and multi-topic messages. Two rounds:

- **Round 1 (with hints):** Prompt explicitly tells the model about multi-topic messages and non-contiguous grouping. All 10 models scored 3/3.
- **Round 2 (no hints):** Prompt states the rules but does NOT hint at specific messages. Tests whether the model applies the rules autonomously. This is the realistic scenario — our production prompt won't hand-hold per message.

Scoring criteria (Round 2):
- **3 topics identified** — did the model find `match_status`, `technical_access`, and `account_profile`?
- **Multi-topic (msg 5)** — does message "Still no match and the photo upload is STILL broken" appear in 2+ segments?
- **Non-contiguous grouping** — are all match_status messages in ONE segment (not fragmented into separate contiguous blocks)?

---

## Results — Round 2 (No Hints)

| Model | Score | Latency | Cost/call | Tokens (in/out) | Non-contiguous | Notes |
|---|---|---|---|---|---|---|
| **openai/gpt-5.4-mini** | **3/3** | **1.5s** | **~$0.00** | 397/268 | PASS | Best overall — fastest, cheapest, perfect |
| **google/gemini-3-flash** | **3/3** | 9.4s | ~$0.00 | 409/302 | PASS | Correct but 6x slower |
| **deepseek/deepseek-v3.2** | **3/3** | 7.4s | $0.0002 | 409/303 | PASS | Correct, very cheap |
| **openai/gpt-5-mini** | **3/3** | 32.0s | ~$0.00 | 397/1620 | PASS | Correct but extremely slow, verbose output |
| anthropic/claude-sonnet-4.6 | 2/3 | 8.6s | $0.0092 | 447/522 | FAIL (5 segs) | Over-segments, most expensive |
| anthropic/claude-haiku-4.5 | 2/3 | 5.0s | $0.0037 | 446/657 | FAIL (7 segs) | Over-segments |
| openai/gpt-5.4-nano | 2/3 | 3.4s | ~$0.00 | 397/545 | FAIL (6 segs) | Over-segments |
| xai/grok-4.1-fast-non-reasoning | 2/3 | 2.0s | $0.0002 | 553/269 | FAIL (5 segs) | Fast but over-segments |
| mistral/mistral-large-3 | 2/3 | 7.0s | $0.0010 | 411/530 | FAIL (6 segs) | Over-segments |
| google/gemini-2.5-flash | 2/3 | 17.1s | ~$0.00 | 409/988 | FAIL (12 segs!) | 1 segment per message |

---

## Analysis

### Non-contiguous grouping is the differentiator

All 10 models correctly identified 3 topics and handled multi-topic messages. The hard problem is **merging distant messages about the same topic into one segment**. Only 4/10 models did this without explicit hints.

Models that failed created separate segments like `[0,1]` and `[5,7,8]` for match_status — treating conversation flow as the grouping boundary instead of topic identity.

### Anthropic models over-segment

Both Claude Sonnet 4.6 and Haiku 4.5 consistently split same-topic messages into separate segments. Claude Sonnet is also the most expensive model tested ($0.009/call vs ~$0 for GPT-5.4-mini) — 40x+ cost premium for worse results on this task.

### Cost comparison (projected for full pipeline)

Estimated cost per 1,000 users (assuming ~20 messages avg, single LLM call per user):

| Model | Cost / 1K users | Relative |
|---|---|---|
| openai/gpt-5.4-mini | ~$0.00 (free tier?) | 1x |
| deepseek/deepseek-v3.2 | ~$0.24 | baseline |
| xai/grok-4.1-fast | ~$0.22 | ~1x |
| mistral/mistral-large-3 | ~$1.00 | ~4x |
| anthropic/claude-haiku-4.5 | ~$3.73 | ~16x |
| anthropic/claude-sonnet-4.6 | ~$9.17 | ~38x |

Note: GPT-5.4-mini showing $0 cost may reflect a free tier or cost not yet reported by the gateway. Actual production pricing should be verified.

---

## Recommendation

### Primary: `openai/gpt-5.4-mini`

- Perfect score on both challenges (non-contiguous + multi-topic)
- Fastest latency (1.5s)
- Cheapest cost
- Clean JSON output, no markdown fences

### Benchmark lineup (for `benchmark.toml`)

| Run | Model | Rationale |
|---|---|---|
| 1 | `openai/gpt-5.4-mini` | Top pick — fast, correct, cheap |
| 2 | `google/gemini-3-flash` | Correct, Google's latest, provider diversity |
| 3 | `deepseek/deepseek-v3.2` | Correct, cheapest per token |
| 4 | `anthropic/claude-sonnet-4.6` | Premium baseline — test if prompt v1 can fix over-segmentation |

### Not recommended

- `openai/gpt-5-mini` — correct but 32s latency is impractical
- `google/gemini-2.5-flash` — created 12 segments (1 per message), slowest
- `xai/grok-4.1-fast-non-reasoning` — fast but fails non-contiguous grouping
- `anthropic/claude-haiku-4.5` — over-segments and expensive for what it delivers

---

## Vercel AI Gateway Configuration

```
Base URL:  https://ai-gateway.vercel.sh/v1
Auth:      Authorization: Bearer $AI_GATEWAY_API_KEY
Format:    OpenAI-compatible (chat/completions)
Models:    245 available (provider/model-name format)
```

All models accessible with a single `AI_GATEWAY_API_KEY` — no per-provider keys needed.
