# Journey benchmark — 2026-11-01T08:02:03+00:00

Planner: `llm` (Claude Haiku 5.5, Anthropic API, low effort) · 3 runs per journey per preset · in-process, mocks with injected latency and failures (see `src/mocks/chaos.py`). Times in ms, measured from request to event.

## Chaos preset: `realistic` (cold cache per journey)

| Journey | Turns | Completed | Degraded | First status p50 / p95 | First token p50 / p95 | Turn total p50 / p95 |
|---|---|---|---|---|---|---|
| 1 EMI change → prepayment → request | 9 | 9 | 0 | 0 / 0 | 2071 / 2823 | 2749 / 3597 |
| 2 Failed payments → dispute | 6 | 6 | 0 | 0 / 0 | 4029 / 4900 | 4861 / 9868 |
| 3 Voice: next EMI → last payment → extra ₹20,000 | 9 | 9 | 0 | 0 / 0 | 2539 / 4480 | 2702 / 4516 |
| 4 Foreclosure in lock-in → statement | 6 | 6 | 0 | 0 / 0 | 2405 / 4530 | 2856 / 5060 |
| 5 Card statement → dispute | 6 | 6 | 0 | 0 / 0 | 3005 / 3736 | 3865 / 4541 |

| System | Calls | Cache hits | Errors | Live call p50 / p95 |
|---|---|---|---|---|
| cards | 48 | 24 | 0 | 159 / 354 |
| crm | 20 | 0 | 0 | 88 / 165 |
| loans | 99 | 51 | 0 | 152 / 334 |
| ops | 4 | 0 | 2 | 667 / 947 |
| payments | 33 | 3 | 0 | 653 / 2236 |
| policy | 24 | 0 | 0 | 115 / 193 |

