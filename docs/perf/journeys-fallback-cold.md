# Journey benchmark — 2026-10-27T06:32:52+00:00

Planner: `fallback` · 20 runs per journey per preset · in-process, mocks with injected latency and failures (see `src/mocks/chaos.py`). Times in ms, measured from request to event.

## Chaos preset: `realistic` (cold cache per journey)

| Journey | Turns | Completed | Degraded | First status p50 / p95 | First token p50 / p95 | Turn total p50 / p95 |
|---|---|---|---|---|---|---|
| 1 EMI change → prepayment → request | 60 | 60 | 0 | 0 / 0 | 120 / 664 | 120 / 665 |
| 2 Failed payments → dispute | 40 | 40 | 3 | 0 / 0 | 873 / 2056 | 874 / 2056 |
| 3 Voice: next EMI → last payment → extra ₹20,000 | 60 | 60 | 4 | 0 / 0 | 842 / 2169 | 843 / 2170 |
| 4 Foreclosure in lock-in → statement | 40 | 40 | 0 | 0 / 0 | 383 / 1148 | 383 / 1148 |
| 5 Card statement → dispute | 40 | 40 | 0 | 0 / 0 | 145 / 764 | 146 / 766 |

| System | Calls | Cache hits | Errors | Live call p50 / p95 |
|---|---|---|---|---|
| cards | 320 | 126 | 0 | 225 / 508 |
| crm | 105 | 0 | 0 | 78 / 191 |
| loans | 657 | 231 | 1 | 155 / 367 |
| ops | 21 | 0 | 2 | 559 / 1135 |
| payments | 207 | 17 | 4 | 601 / 1520 |
| policy | 158 | 6 | 0 | 120 / 234 |

## Chaos preset: `bad_day` (cold cache per journey)

| Journey | Turns | Completed | Degraded | First status p50 / p95 | First token p50 / p95 | Turn total p50 / p95 |
|---|---|---|---|---|---|---|
| 1 EMI change → prepayment → request | 60 | 60 | 0 | 0 / 0 | 106 / 701 | 108 / 702 |
| 2 Failed payments → dispute | 40 | 40 | 19 | 0 / 0 | 0 / 209 | 1 / 209 |
| 3 Voice: next EMI → last payment → extra ₹20,000 | 60 | 60 | 40 | 0 / 0 | 105 / 441 | 106 / 442 |
| 4 Foreclosure in lock-in → statement | 40 | 40 | 0 | 0 / 0 | 1402 / 8071 | 1402 / 8072 |
| 5 Card statement → dispute | 40 | 40 | 0 | 0 / 0 | 103 / 814 | 105 / 816 |

| System | Calls | Cache hits | Errors | Live call p50 / p95 |
|---|---|---|---|---|
| cards | 320 | 122 | 0 | 216 / 490 |
| crm | 105 | 7 | 0 | 98 / 192 |
| loans | 637 | 227 | 2 | 156 / 409 |
| ops | 23 | 0 | 6 | 3287 / 4089 |
| payments | 191 | 0 | 191 | 0 / 0 |
| policy | 120 | 5 | 0 | 118 / 225 |

