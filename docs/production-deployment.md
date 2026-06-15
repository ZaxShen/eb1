# Production Deployment Guide

The eb1 pipeline segments and classifies 3M+ chat messages via LLM. This page covers the first backfill, weekly scheduling, cost, and observability.

**PROD numbers (queried 2026-03-28):** 135K users, 3.1M messages, avg 23 msgs/chat. Weekly active: ~6.5K users, ~98K messages.

---

## FAQ

### How does the pipeline scale — per message or per user?

**Per user.** Each user's chat history is split into chunks (bot-only vs user-engaged) by a deterministic pre-segmenter. Each chunk that doesn't match a known template gets one LLM call. The 200-message windowing threshold is rarely hit (avg 23 msgs/chat), so most users need 2–4 LLM calls depending on how many conversation chunks they have.

### How many LLM calls does the first backfill require?

Conservative estimate: **~350K LLM calls** (118K chats x ~3 calls avg).

Template matching skips bot-only chunks that match known automated messages, which may reduce the total by 20–30%.

| Messages per chat | Chats  | LLM calls per chat |
|-------------------|--------|--------------------|
| 1–4               | 9,882  | ~1–2               |
| 5–19              | 58,905 | ~2–4               |
| 20–49             | 35,826 | ~3–6               |
| 50–199            | 12,815 | ~4–12              |
| 200+              | 766    | ~8–100+            |

### How long will the backfill take?

| Concurrency | Estimated time (at ~5s per call) |
|-------------|----------------------------------|
| 32 workers  | ~15 hours                        |
| 64 workers  | ~8 hours                         |

The actual ceiling depends on the AI Gateway rate limit — see the open question below.

### Do we need distributed computing?

**No.** The pipeline is I/O-bound (waiting on LLM API responses), not CPU-bound. A single machine with 32–64 concurrent HTTP connections saturates the LLM gateway. Distributing across machines only helps if the gateway supports 100+ req/s AND a single machine can't maintain that many concurrent connections — both unlikely. A standard 4-core k8s pod with good network handles this easily.

### Where do we deploy?

Acme runs **Kubernetes**. Deployment plan:

1. **Backfill** — a one-time k8s Job. Run `uv run python -m pipeline` with high concurrency. Monitor via `eb1_pipeline_logs` and pod logs. Idempotent — safe to re-run on failure.
2. **Weekly runs** — a k8s CronJob scheduled for **Monday** (before Wednesday matchmaking). Incremental mode skips users with no new messages.

Both use the same Docker image, just different concurrency settings and entrypoints.

### What models do we use?

- **Production model:** GPT-5.4 (best classification accuracy)
- **Backfill model:** GPT-5.2-chat (strong performance at lower cost)

The system prompt (segmentation, summarization, and classification instructions) is the token-heavy part of each API call — the actual user messages are small (avg 23 msgs). **Prompt caching** is critical for cost efficiency: the system prompt is identical across all calls, so a caching-aware gateway avoids re-tokenizing it every time.

### How does the weekly run work?

- **Schedule:** Monday (before Wednesday matchmaking)
- **Scope:** ~6.5K active users per week, ~6.5K LLM calls (1 call per user in incremental mode — only new messages since last run)
- **Duration:** ~17 minutes at concurrency=32
- **Safety:** Fully idempotent. If it fails midway, re-run picks up where it left off

### What about observability and reliability?

The pipeline needs to be robust, reliable, and auditable for prod:

- **Run-level logging** — start/end timestamps, users processed/skipped/failed, total LLM calls, avg latency, error counts. Logged to `eb1_pipeline_logs` with `event_type = 'run_summary'`
- **Taxonomy remap logging** — bidirectional guard catches LLM hallucinations (bot topic on user segment or vice versa), retries once, remaps if still wrong. All remaps logged to `eb1_pipeline_logs` with full context
- **Resume mechanism** — pipeline skips already-processed users (sentinel: existing segments with `classified_at` set). Safe to restart after any failure
- **Re-run mechanism** — `--force` flag re-processes all users; `--relabel` clears AI fields on unreviewed segments and re-classifies
- **FK constraints** — PostgreSQL foreign keys enforce that every segment topic exists in the taxonomy. Prevents orphan data

---

## Open Questions

**Blocker: AI Gateway rate limit.** We need to know the throughput ceiling on `ai-gateway.vercel.sh` before finalizing the backfill concurrency. Options if the gateway is the bottleneck:
- Request a higher quota from the gateway provider
- Use the direct OpenAI endpoint for the backfill
- Enable prompt caching to reduce per-call cost and latency

Action: Discuss with CTO.

**Prompt caching.** The system prompt is the token-heavy part of each call. If the gateway or OpenAI API supports prompt caching, it significantly reduces both cost and latency for the backfill. Verify whether `ai-gateway.vercel.sh` passes through OpenAI's prompt caching headers.

**Alerting.** Weekly runs should notify on failure — Slack alert, email, or similar. Mechanism TBD based on existing Acme infra.
