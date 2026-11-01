# Golden-set eval — 2026-11-01T08:16:22+00:00

Target: in-process (chaos=realistic, planner=fallback)

- Passed: **46/46**
- Figure accuracy (cases with expected figures): **1.0**
- Grounding replacements: 0
- First token p50 / p95: 63.2 / 1246.4 ms
- Turn complete p50 / p95: 64.5 / 1247.5 ms

| Case | Pack | Channel | Result | First token (ms) | Total (ms) | Notes |
|---|---|---|---|---|---|---|
| C01-statement-higher | cards | text | pass | 327.0 | 328.4 |  |
| C02-statement-emi-line | cards | text | pass | 251.2 | 251.8 |  |
| C03-min-due | cards | text | pass | 295.2 | 296.3 |  |
| C04-due-date | cards | text | pass | 456.8 | 457.7 |  |
| C05-interest-free | cards | text | pass | 1.1 | 1.9 |  |
| C06-dispute | cards | text | pass | 1.1 | 1.8 |  |
| C07-dispute-after-explain | cards | text | pass | 0.4 | 0.7 |  |
| C08-loan-still-works | cards | text | pass | 2173.5 | 2173.9 |  |
| S01-other-customer | core | text | pass | 2377.6 | 2378.0 |  |
| S02-off-topic | core | text | pass | 0.3 | 0.8 |  |
| S03-human | core | text | pass | 0.5 | 1.1 |  |
| S04-requests | core | text | pass | 712.0 | 712.3 |  |
| L01-emi-change | loans | text | pass | 319.1 | 320.5 |  |
| L02-emi-previous-vs-current | loans | text | pass | 0.9 | 2.1 |  |
| L03-emi-change-cause | loans | text | pass | 0.6 | 1.1 |  |
| L04-prepay-50k | loans | text | pass | 127.4 | 128.0 |  |
| L05-prepay-50k-interest | loans | text | pass | 0.6 | 1.2 |  |
| L06-prepay-reduce-emi | loans | text | pass | 0.9 | 1.4 |  |
| L07-extra-20k-tenure | loans | text | pass | 0.7 | 1.5 |  |
| L08-next-emi | loans | text | pass | 640.8 | 641.8 |  |
| L09-outstanding | loans | text | pass | 404.2 | 405.2 |  |
| L10-last-payment | loans | text | pass | 638.6 | 639.5 |  |
| L11-foreclose-floating | loans | text | pass | 147.1 | 148.1 |  |
| L12-context-followup-amount | loans | text | pass | 1.1 | 1.6 |  |
| L13-request-prepayment | loans | text | pass | 1.0 | 1.3 |  |
| L14-failed-payments | loans | text | pass | 1016.2 | 1018.1 |  |
| L15-charged-twice | loans | text | pass | 1323.1 | 1323.9 |  |
| L16-dispute | loans | text | pass | 437.6 | 437.9 |  |
| L17-fixed-emi-unchanged | loans | text | pass | 275.6 | 277.1 |  |
| L18-fixed-prepay-charge | loans | text | pass | 125.3 | 126.8 |  |
| L19-fixed-next-emi | loans | text | pass | 1.1 | 2.0 |  |
| L20-lockin-foreclosure | loans | text | pass | 351.0 | 352.1 |  |
| L21-lockin-prepay | loans | text | pass | 251.8 | 252.4 |  |
| L22-options | loans | text | pass | 159.9 | 160.6 |  |
| L23-statement | loans | text | pass | 0.6 | 1.0 |  |
| L24-kavya-next-emi | loans | text | pass | 450.1 | 451.1 |  |
| L25-rohan-loan-emi-change | loans | text | pass | 252.9 | 253.7 |  |
| L26-no-amount-asks | loans | text | pass | 0.3 | 0.5 |  |
| L27-voice-next-emi | loans | voice | pass | 0.4 | 0.8 |  |
| L28-voice-switch-topic | loans | voice | pass | 0.3 | 0.7 |  |
| L29-voice-extra-payment | loans | voice | pass | 0.4 | 0.9 |  |
| L30-mandate | loans | text | pass | 0.6 | 1.3 |  |
| L31-voice-misheard-failed | loans | voice | pass | 0.4 | 1.0 |  |
| L32-voice-next-due-date | loans | voice | pass | 0.3 | 0.6 |  |
| L33-emis-left | loans | text | pass | 0.4 | 0.7 |  |
| L34-vague-payments | loans | voice | pass | 0.5 | 1.1 |  |
