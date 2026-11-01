# Journey benchmark — 2026-10-27T06:38:17+00:00

Planner: `fallback` · 20 runs per journey per preset · in-process, mocks with injected latency and failures (see `src/mocks/chaos.py`). Times in ms, measured from request to event.

## Chaos preset: `realistic` (warm cache shared across runs)

| Journey | Turns | Completed | Degraded | First status p50 / p95 | First token p50 / p95 | Turn total p50 / p95 |
|---|---|---|---|---|---|---|
| 1 EMI change → prepayment → request | 60 | 60 | 0 | 0 / 2 | 2 / 462 | 4 / 465 |
| 2 Failed payments → dispute | 40 | 40 | 1 | 0 / 0 | 1 / 1410 | 2 / 1412 |
| 3 Voice: next EMI → last payment → extra ₹20,000 | 60 | 60 | 0 | 0 / 0 | 1 / 712 | 2 / 713 |
| 4 Foreclosure in lock-in → statement | 40 | 40 | 0 | 0 / 0 | 256 / 1128 | 257 / 1129 |
| 5 Card statement → dispute | 40 | 40 | 0 | 0 / 3 | 1 / 366 | 4 / 370 |

| System | Calls | Cache hits | Errors | Live call p50 / p95 |
|---|---|---|---|---|
| cards | 318 | 280 | 0 | 166 / 426 |
| crm | 105 | 87 | 0 | 72 / 137 |
| loans | 657 | 575 | 0 | 167 / 419 |
| ops | 20 | 0 | 0 | 572 / 1390 |
| payments | 201 | 137 | 1 | 529 / 1324 |
| policy | 157 | 137 | 0 | 124 / 166 |

## Chaos preset: `bad_day` (warm cache shared across runs)

| Journey | Turns | Completed | Degraded | First status p50 / p95 | First token p50 / p95 | Turn total p50 / p95 |
|---|---|---|---|---|---|---|
| 1 EMI change → prepayment → request | 60 | 60 | 0 | 0 / 1 | 1 / 487 | 4 / 492 |
| 2 Failed payments → dispute | 40 | 40 | 20 | 0 / 0 | 0 / 1995 | 1 / 1996 |
| 3 Voice: next EMI → last payment → extra ₹20,000 | 60 | 60 | 40 | 0 / 0 | 1 / 2 | 1 / 3 |
| 4 Foreclosure in lock-in → statement | 40 | 40 | 1 | 0 / 0 | 1305 / 7519 | 1305 / 7520 |
| 5 Card statement → dispute | 40 | 40 | 0 | 0 / 1 | 1 / 9 | 2 / 11 |

| System | Calls | Cache hits | Errors | Live call p50 / p95 |
|---|---|---|---|---|
| cards | 322 | 295 | 0 | 231 / 801 |
| crm | 105 | 88 | 0 | 121 / 250 |
| loans | 642 | 575 | 1 | 167 / 665 |
| ops | 23 | 0 | 6 | 3140 / 4132 |
| payments | 212 | 1 | 197 | 0 / 1506 |
| policy | 121 | 110 | 0 | 163 / 240 |

