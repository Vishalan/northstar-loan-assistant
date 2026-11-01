# Held-out eval (reworded questions) — 2026-11-01T08:17:35+00:00

Target: in-process (chaos=realistic, planner=llm, provider=native, model=claude-haiku-5-5)

- Passed: **16/17**
- Figure accuracy (cases with expected figures): **1.0**
- Grounding replacements: 1
- First token p50 / p95: 1950.2 / 3422.4 ms
- Turn complete p50 / p95: 2670.6 / 5137.7 ms

| Case | Pack | Channel | Result | First token (ms) | Total (ms) | Notes |
|---|---|---|---|---|---|---|
| H-C01-bill-higher | cards | text | pass | 2075.5 | 5712.0 |  |
| H-C02-contest | cards | text | FAIL | 2409.1 | 2952.6 | action cards_dispute_card_transaction not proposed |
| H-C03-hinglish-due | cards | text | pass | 1950.2 | 2670.6 |  |
| H-L01-instalment-up | loans | text | pass | 3064.0 | 3806.3 |  |
| H-L02-hinglish-why | loans | text | pass | 1523.5 | 3506.6 |  |
| H-L03-50k-colloquial | loans | text | pass | 1974.9 | 2589.9 |  |
| H-L04-next-due-reworded | loans | text | pass | 1732.9 | 2087.9 |  |
| H-L05-hinglish-next | loans | text | pass | 1487.3 | 2053.1 |  |
| H-L06-two-part | loans | text | pass | 1818.8 | 2630.0 |  |
| H-L07-hinglish-two-part | loans | text | pass | 2656.1 | 3779.8 |  |
| H-L08-typo | loans | text | pass | 1428.9 | 1639.4 |  |
| H-L09-bounced | loans | text | pass | 3621.3 | 4994.1 |  |
| H-L10-charge-reason | loans | text | pass | 3030.8 | 4101.4 |  |
| H-L11-no-dispute | loans | text | pass | 3372.7 | 4392.1 |  |
| H-L12-close-early | loans | text | pass | 1540.4 | 2227.6 |  |
| H-L13-no-statement | loans | text | pass | 1546.6 | 1611.5 |  |
| H-L14-nothing-to-file | loans | text | pass | 1407.4 | 1604.6 |  |
