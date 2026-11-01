# Golden-set eval — 2026-11-01T07:10:17+00:00

Target: in-process (chaos=realistic, planner=fallback)

- Passed: **46/46**
- Figure accuracy (cases with expected figures): **1.0**
- Grounding replacements: 0
- First token p50 / p95: 143.8 / 1107.8 ms
- Turn complete p50 / p95: 144.9 / 1109.5 ms

| Case | Pack | Channel | Result | First token (ms) | Total (ms) | Notes |
|---|---|---|---|---|---|---|
| C01-statement-higher | cards | text | pass | 505.8 | 507.5 |  |
| C02-statement-emi-line | cards | text | pass | 643.0 | 644.8 |  |
| C03-min-due | cards | text | pass | 229.9 | 231.9 |  |
| C04-due-date | cards | text | pass | 325.4 | 326.6 |  |
| C05-interest-free | cards | text | pass | 1.2 | 2.1 |  |
| C06-dispute | cards | text | pass | 303.6 | 304.3 |  |
| C07-dispute-after-explain | cards | text | pass | 0.8 | 1.6 |  |
| C08-loan-still-works | cards | text | pass | 1014.2 | 1015.0 |  |
| S01-other-customer | core | text | pass | 1711.6 | 1712.1 |  |
| S02-off-topic | core | text | pass | 0.3 | 0.6 |  |
| S03-human | core | text | pass | 0.6 | 1.1 |  |
| S04-requests | core | text | pass | 551.2 | 551.6 |  |
| L01-emi-change | loans | text | pass | 283.4 | 284.7 |  |
| L02-emi-previous-vs-current | loans | text | pass | 374.5 | 375.4 |  |
| L03-emi-change-cause | loans | text | pass | 164.0 | 165.6 |  |
| L04-prepay-50k | loans | text | pass | 86.0 | 87.1 |  |
| L05-prepay-50k-interest | loans | text | pass | 172.8 | 173.6 |  |
| L06-prepay-reduce-emi | loans | text | pass | 0.8 | 1.7 |  |
| L07-extra-20k-tenure | loans | text | pass | 0.7 | 1.6 |  |
| L08-next-emi | loans | text | pass | 0.6 | 1.2 |  |
| L09-outstanding | loans | text | pass | 0.4 | 1.0 |  |
| L10-last-payment | loans | text | pass | 938.2 | 939.4 |  |
| L11-foreclose-floating | loans | text | pass | 196.3 | 197.2 |  |
| L12-context-followup-amount | loans | text | pass | 0.7 | 1.0 |  |
| L13-request-prepayment | loans | text | pass | 0.6 | 1.0 |  |
| L14-failed-payments | loans | text | pass | 993.0 | 995.3 |  |
| L15-charged-twice | loans | text | pass | 1139.0 | 1141.0 |  |
| L16-dispute | loans | text | pass | 639.9 | 640.7 |  |
| L17-fixed-emi-unchanged | loans | text | pass | 367.5 | 368.2 |  |
| L18-fixed-prepay-charge | loans | text | pass | 84.5 | 85.7 |  |
| L19-fixed-next-emi | loans | text | pass | 0.7 | 1.7 |  |
| L20-lockin-foreclosure | loans | text | pass | 123.5 | 124.2 |  |
| L21-lockin-prepay | loans | text | pass | 198.2 | 198.6 |  |
| L22-options | loans | text | pass | 262.1 | 262.4 |  |
| L23-statement | loans | text | pass | 729.3 | 729.7 |  |
| L24-kavya-next-emi | loans | text | pass | 1419.5 | 1420.6 |  |
| L25-rohan-loan-emi-change | loans | text | pass | 277.1 | 278.1 |  |
| L26-no-amount-asks | loans | text | pass | 0.3 | 0.5 |  |
| L27-voice-next-emi | loans | voice | pass | 0.4 | 1.1 |  |
| L28-voice-switch-topic | loans | voice | pass | 0.4 | 1.0 |  |
| L29-voice-extra-payment | loans | voice | pass | 0.5 | 1.2 |  |
| L30-mandate | loans | text | pass | 0.5 | 1.5 |  |
| L31-voice-misheard-failed | loans | voice | pass | 0.5 | 1.4 |  |
| L32-voice-next-due-date | loans | voice | pass | 0.3 | 0.7 |  |
| L33-emis-left | loans | text | pass | 0.3 | 0.8 |  |
| L34-vague-payments | loans | voice | pass | 0.7 | 1.6 |  |
