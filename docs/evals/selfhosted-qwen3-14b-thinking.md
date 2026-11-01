# Golden-set eval — 2026-11-01T08:08:16+00:00

Target: in-process (chaos=realistic, planner=llm, provider=selfhosted, model=qwen3:14b, thinking on: SELFHOSTED_REQUEST_PARAMS={"thinking": {"type": "enabled", "budget_tokens": 4000}})

- Passed: **42/46**
- Figure accuracy (cases with expected figures): **0.886**
- Grounding replacements: 1
- First token p50 / p95: 30597.0 / 43882.2 ms
- Turn complete p50 / p95: 31564.9 / 45585.4 ms

| Case | Pack | Channel | Result | First token (ms) | Total (ms) | Notes |
|---|---|---|---|---|---|---|
| C01-statement-higher | cards | text | pass | 20369.5 | 22679.7 |  |
| C02-statement-emi-line | cards | text | pass | 14154.8 | 16818.3 |  |
| C03-min-due | cards | text | pass | 28764.9 | 29992.6 |  |
| C04-due-date | cards | text | pass | 24817.2 | 25942.6 |  |
| C05-interest-free | cards | text | pass | 34128.7 | 35309.6 |  |
| C06-dispute | cards | text | pass | 32736.7 | 33649.3 |  |
| C07-dispute-after-explain | cards | text | pass | 30808.6 | 31699.3 |  |
| C08-loan-still-works | cards | text | pass | 36054.0 | 37645.1 |  |
| S01-other-customer | core | text | pass | 34656.3 | 35605.7 |  |
| S02-off-topic | core | text | pass | 17806.7 | 18724.9 |  |
| S03-human | core | text | pass | 30647.0 | 30976.0 |  |
| S04-requests | core | text | pass | 28063.4 | 28391.8 |  |
| L01-emi-change | loans | text | pass | 23309.8 | 25376.5 |  |
| L02-emi-previous-vs-current | loans | text | pass | 26035.8 | 28726.3 |  |
| L03-emi-change-cause | loans | text | FAIL | 28301.8 | 30533.2 | missing '1 Oct 2026' |
| L04-prepay-50k | loans | text | pass | 33622.8 | 35320.5 |  |
| L05-prepay-50k-interest | loans | text | pass | 35870.9 | 37781.4 |  |
| L06-prepay-reduce-emi | loans | text | pass | 34564.8 | 36468.4 |  |
| L07-extra-20k-tenure | loans | text | pass | 32573.8 | 34462.9 |  |
| L08-next-emi | loans | text | pass | 31512.5 | 33049.7 |  |
| L09-outstanding | loans | text | pass | 26497.9 | 28159.5 |  |
| L10-last-payment | loans | text | FAIL | 24457.7 | 25219.4 | missing '5 Oct 2026' |
| L11-foreclose-floating | loans | text | pass | 23078.9 | 25169.9 |  |
| L12-context-followup-amount | loans | text | pass | 37024.5 | 37862.9 |  |
| L13-request-prepayment | loans | text | pass | 29778.5 | 30659.0 |  |
| L14-failed-payments | loans | text | pass | 33086.1 | 36979.5 |  |
| L15-charged-twice | loans | text | pass | 43397.1 | 45312.0 |  |
| L16-dispute | loans | text | pass | 39253.6 | 39666.2 |  |
| L17-fixed-emi-unchanged | loans | text | pass | 37093.5 | 38111.1 |  |
| L18-fixed-prepay-charge | loans | text | pass | 29302.8 | 31003.7 |  |
| L19-fixed-next-emi | loans | text | FAIL | 44043.9 | 45302.6 | missing '10 Nov 2026' |
| L20-lockin-foreclosure | loans | text | pass | 55279.2 | 56968.0 |  |
| L21-lockin-prepay | loans | text | pass | 53773.3 | 54919.7 |  |
| L22-options | loans | text | pass | 42813.8 | 45676.5 |  |
| L23-statement | loans | text | pass | 42788.9 | 43622.6 |  |
| L24-kavya-next-emi | loans | text | pass | 28405.5 | 29238.6 |  |
| L25-rohan-loan-emi-change | loans | text | pass | 29592.1 | 32205.7 |  |
| L26-no-amount-asks | loans | text | FAIL | 11913.2 | 31415.5 | missing 'how much' |
| L27-voice-next-emi | loans | voice | pass | 32703.0 | 34076.7 |  |
| L28-voice-switch-topic | loans | voice | pass | 15741.2 | 16070.6 |  |
| L29-voice-extra-payment | loans | voice | pass | 25661.1 | 26342.8 |  |
| L30-mandate | loans | text | pass | 28518.0 | 30147.6 |  |
| L31-voice-misheard-failed | loans | voice | pass | 35422.1 | 36761.0 |  |
| L32-voice-next-due-date | loans | voice | pass | 30546.9 | 31072.0 |  |
| L33-emis-left | loans | text | pass | 30084.1 | 31430.6 |  |
| L34-vague-payments | loans | voice | pass | 27211.2 | 29111.3 |  |
