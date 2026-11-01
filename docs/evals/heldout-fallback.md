# Held-out eval (reworded questions) — 2026-11-01T08:17:10+00:00

Target: in-process (chaos=realistic, planner=fallback)

- Passed: **12/17**
- Figure accuracy (cases with expected figures): **0.786**
- Grounding replacements: 0
- First token p50 / p95: 324.7 / 1609.0 ms
- Turn complete p50 / p95: 326.3 / 1610.5 ms

| Case | Pack | Channel | Result | First token (ms) | Total (ms) | Notes |
|---|---|---|---|---|---|---|
| H-C01-bill-higher | cards | text | pass | 1524.0 | 1525.7 |  |
| H-C02-contest | cards | text | FAIL | 0.4 | 0.9 | action cards_dispute_card_transaction not proposed |
| H-C03-hinglish-due | cards | text | pass | 263.3 | 264.4 |  |
| H-L01-instalment-up | loans | text | pass | 324.7 | 326.3 |  |
| H-L02-hinglish-why | loans | text | FAIL | 531.5 | 532.6 | tool loans_explain_emi_change not called (called: ['loans_loan_overview']) |
| H-L03-50k-colloquial | loans | text | FAIL | 0.3 | 0.6 | missing '₹22,883'; tool loans_prepayment_options not called (called: none) |
| H-L04-next-due-reworded | loans | text | pass | 646.5 | 646.9 |  |
| H-L05-hinglish-next | loans | text | pass | 1949.1 | 1949.9 |  |
| H-L06-two-part | loans | text | FAIL | 1.2 | 2.1 | missing '₹9,483'; tool loans_prepayment_options not called (called: ['loans_loan_overview']) |
| H-L07-hinglish-two-part | loans | text | pass | 229.2 | 230.2 |  |
| H-L08-typo | loans | text | pass | 0.4 | 0.7 |  |
| H-L09-bounced | loans | text | pass | 952.3 | 956.0 |  |
| H-L10-charge-reason | loans | text | pass | 1038.6 | 1040.2 |  |
| H-L11-no-dispute | loans | text | FAIL | 0.4 | 0.8 | missing '₹590' |
| H-L12-close-early | loans | text | pass | 415.8 | 416.9 |  |
| H-L13-no-statement | loans | text | pass | 408.6 | 409.6 |  |
| H-L14-nothing-to-file | loans | text | pass | 0.6 | 1.3 |  |
