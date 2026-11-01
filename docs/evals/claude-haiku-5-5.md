# Golden-set eval — 2026-10-31T10:44:59+00:00

Target: in-process (chaos=realistic, planner=llm, model=claude-haiku-5-5)

- Passed: **46/46**
- Figure accuracy (cases with expected figures): **1.0**
- Grounding replacements: 7
- First token p50 / p95: 1999.9 / 3136.7 ms
- Turn complete p50 / p95: 2634.6 / 5787.3 ms

| Case | Pack | Channel | Result | First token (ms) | Total (ms) | Notes |
|---|---|---|---|---|---|---|
| C01-statement-higher | cards | text | pass | 2041.7 | 5885.6 |  |
| C02-statement-emi-line | cards | text | pass | 2287.2 | 6156.1 |  |
| C03-min-due | cards | text | pass | 1796.9 | 2142.0 |  |
| C04-due-date | cards | text | pass | 1714.5 | 1864.7 |  |
| C05-interest-free | cards | text | pass | 2242.4 | 2486.6 |  |
| C06-dispute | cards | text | pass | 3137.5 | 3654.6 |  |
| C07-dispute-after-explain | cards | text | pass | 2692.4 | 3151.3 |  |
| C08-loan-still-works | cards | text | pass | 1735.2 | 2045.8 |  |
| S01-other-customer | core | text | pass | 2994.2 | 6775.6 |  |
| S02-off-topic | core | text | pass | 822.0 | 2588.4 |  |
| S03-human | core | text | pass | 2459.0 | 2965.5 |  |
| S04-requests | core | text | pass | 1791.9 | 2314.8 |  |
| L01-emi-change | loans | text | pass | 2257.0 | 2993.8 |  |
| L02-emi-previous-vs-current | loans | text | pass | 1792.8 | 2428.6 |  |
| L03-emi-change-cause | loans | text | pass | 1816.9 | 2447.8 |  |
| L04-prepay-50k | loans | text | pass | 1871.7 | 2768.0 |  |
| L05-prepay-50k-interest | loans | text | pass | 1723.9 | 2592.7 |  |
| L06-prepay-reduce-emi | loans | text | pass | 1797.3 | 2493.7 |  |
| L07-extra-20k-tenure | loans | text | pass | 1970.7 | 2905.1 |  |
| L08-next-emi | loans | text | pass | 1763.2 | 2063.9 |  |
| L09-outstanding | loans | text | pass | 1566.4 | 1875.6 |  |
| L10-last-payment | loans | text | pass | 2397.6 | 2684.2 |  |
| L11-foreclose-floating | loans | text | pass | 1875.4 | 2619.2 |  |
| L12-context-followup-amount | loans | text | pass | 1974.5 | 3668.5 |  |
| L13-request-prepayment | loans | text | pass | 2942.4 | 3463.5 |  |
| L14-failed-payments | loans | text | pass | 3809.4 | 5492.3 |  |
| L15-charged-twice | loans | text | pass | 2111.2 | 2930.4 |  |
| L16-dispute | loans | text | pass | 3134.3 | 3535.9 |  |
| L17-fixed-emi-unchanged | loans | text | pass | 1993.4 | 2291.6 |  |
| L18-fixed-prepay-charge | loans | text | pass | 2454.8 | 3130.2 |  |
| L19-fixed-next-emi | loans | text | pass | 1593.1 | 1844.9 |  |
| L20-lockin-foreclosure | loans | text | pass | 2023.7 | 2599.3 |  |
| L21-lockin-prepay | loans | text | pass | 2166.1 | 2584.0 |  |
| L22-options | loans | text | pass | 1967.1 | 2649.9 |  |
| L23-statement | loans | text | pass | 2077.8 | 3169.4 |  |
| L24-kavya-next-emi | loans | text | pass | 1676.8 | 1908.5 |  |
| L25-rohan-loan-emi-change | loans | text | pass | 2792.3 | 3374.0 |  |
| L26-no-amount-asks | loans | text | pass | 802.8 | 2101.9 |  |
| L27-voice-next-emi | loans | voice | pass | 2624.6 | 2775.1 |  |
| L28-voice-switch-topic | loans | voice | pass | 1985.3 | 2097.4 |  |
| L29-voice-extra-payment | loans | voice | pass | 2006.4 | 2157.6 |  |
| L30-mandate | loans | text | pass | 2148.5 | 2946.0 |  |
| L31-voice-misheard-failed | loans | voice | pass | 2452.8 | 2690.6 |  |
| L32-voice-next-due-date | loans | voice | pass | 1862.7 | 1879.5 |  |
| L33-emis-left | loans | text | pass | 1975.0 | 2111.1 |  |
| L34-vague-payments | loans | voice | pass | 3608.2 | 3851.8 |  |
