# Latency and performance

Every number here comes from a report in this repo, linked next to it, and can be rerun with the command shown.
The app also records latency live for every turn and shows it at http://localhost:3000/latency while it runs.

## Conversational latency

| Measurement | Result | Report | Rerun |
|---|---|---|---|
| Claude Haiku 5.5, 46 golden questions | first answer token p50 **2.0 s**, p95 3.1 s; turn complete p50 2.6 s | [claude-haiku-5-5.md](evals/claude-haiku-5-5.md) | `LLM_MODE=llm make eval` |
| Claude Haiku 5.5, full journeys, cold cache | 36/36 turns completed; first answer token p50 **2.1–4.0 s**, p95 2.8–4.9 s by journey | [journeys-claude-haiku-5-5-cold.md](perf/journeys-claude-haiku-5-5-cold.md) | `LLM_MODE=llm uv run python bench/journeys.py --runs 3 --presets realistic --cold` |
| Deterministic planner (fallback), full journeys, cold cache | first answer token p50 **120–873 ms**, p95 0.66–2.2 s by journey | [journeys-fallback-cold.md](perf/journeys-fallback-cold.md) | `make bench` |
| Self-hosted Qwen3 14B on an RTX 3090 | turn complete p50 **7.7 s** (thinking off), 31.6 s (thinking on) | [selfhosted-qwen3-14b.md](evals/selfhosted-qwen3-14b.md) | see [deploy/selfhosted](../deploy/selfhosted/README.md) |

The first status line ("Checking your loan…") reaches the screen in under 5 ms in every run, so the customer
sees progress immediately; the model's first token is the largest part of the wait.

## Voice

| Measurement | Result | Where |
|---|---|---|
| Speech recognition, Parakeet TDT 0.6B on a Mac (M4, MLX), 2–4 s question | **130–250 ms** | `speech/tests` |
| Speech recognition, faster-whisper large-v3-turbo on an RTX 3090 over Tailscale | **~280 ms** | [deploy/selfhosted](../deploy/selfhosted/README.md) |
| Server voice, Kokoro-82M on an RTX 3090 over Tailscale, 90-character sentence | **300–380 ms** | [deploy/selfhosted](../deploy/selfhosted/README.md) |
| End of speech → first audio, barge-in → audio stopped, synthesis per sentence | recorded live from each browser session | http://localhost:3000/latency |

Answers are spoken sentence by sentence as each one passes the grounding check, and a short filler is spoken if
the first sentence is slow, so the caller is never left in silence.

## Backend systems with varied latency and failures

The six mock systems inject latency and failures (`backend/src/mocks/chaos.py`). Live call p50 / p95 on the
realistic preset: CRM 78 / 191 ms, Policy 120 / 234 ms, Loans 155 / 367 ms, Cards 225 / 508 ms,
Service Ops 559 / 1,135 ms, Payments 601 / 1,520 ms ([report](perf/journeys-fallback-cold.md)).

| Preset | What happens | Result |
|---|---|---|
| Realistic | slow Payments, occasional errors | every turn completed; a few degraded with a stated reason |
| Bad day | Payments down (191 of 191 calls failed), Service Ops ~3 s | **240/240 turns completed**; Payments-dependent answers say what could not be checked; the circuit breaker stops calling Payments |

## Accuracy

| Set | Deterministic planner | Claude Haiku 5.5 | Report |
|---|---|---|---|
| Golden, 46 questions across 3 packs | 46/46 | 46/46, figure accuracy 1.0 | [latest.md](evals/latest.md), [claude-haiku-5-5.md](evals/claude-haiku-5-5.md) |
| Held-out, 17 reworded questions never used to tune the intents | 12/17 | 16/17, figure accuracy 1.0 | [heldout-fallback.md](evals/heldout-fallback.md), [heldout-claude-haiku-5-5.md](evals/heldout-claude-haiku-5-5.md) |

Rerun with `make eval` and `make eval-heldout` (add `LLM_MODE=llm` for Claude).

## Load

1,000 concurrent sessions for 4 minutes against one orchestrator process on a laptop, with the model replaced by
a fixed 400 ms + 600 ms delay so the platform itself is what is measured
([load-1000-users_stats.csv](perf/load-1000-users_stats.csv)):

| | |
|---|---|
| Turns | **9,455, 0 failures** |
| Throughput | ≈40 turns/s from one process |
| First answer token | p50 410 ms (400 ms of it is the simulated model), p95 1.0 s, p99 2.0 s |

Rerun: start the API with `LLM_MODE=stub TURN_RATE_LIMIT=100000 make api`, then `make load`.

What this means at 1,000 real concurrent conversations (about 50 turns a second): see the scale section of
[ARCHITECTURE.md](../ARCHITECTURE.md#scale-2-million-customers-100000-interactions-a-day-1000-concurrent-conversations)
and the interactive simulator linked from the [README](../README.md).
