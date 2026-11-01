# Golden-set eval — 2026-11-01T08:00:29+00:00

Target: in-process (chaos=realistic, planner=llm, provider=selfhosted, model=qwen3:14b, thinking off: the provider default)

- Passed: **40/46**
- Figure accuracy (cases with expected figures): **0.857**
- Grounding replacements: 1
- First token p50 / p95: 6420.9 / 9646.0 ms
- Turn complete p50 / p95: 7749.1 / 11515.0 ms

| Case | Pack | Channel | Result | First token (ms) | Total (ms) | Notes |
|---|---|---|---|---|---|---|
| C01-statement-higher | cards | text | pass | 5705.0 | 8170.7 |  |
| C02-statement-emi-line | cards | text | pass | 3406.3 | 5691.9 |  |
| C03-min-due | cards | text | pass | 2037.3 | 2372.6 |  |
| C04-due-date | cards | text | pass | 2332.0 | 2918.3 |  |
| C05-interest-free | cards | text | pass | 8475.7 | 8729.4 |  |
| C06-dispute | cards | text | FAIL | 10453.5 | 11202.2 | action cards_dispute_card_transaction not proposed |
| C07-dispute-after-explain | cards | text | pass | 6328.1 | 7271.0 |  |
| C08-loan-still-works | cards | text | pass | 6043.7 | 6924.6 |  |
| S01-other-customer | core | text | pass | 7383.9 | 7985.5 |  |
| S02-off-topic | core | text | pass | 3491.7 | 3864.0 |  |
| S03-human | core | text | pass | 5302.8 | 5582.1 |  |
| S04-requests | core | text | pass | 4957.6 | 5241.6 |  |
| L01-emi-change | loans | text | pass | 4247.8 | 6513.3 |  |
| L02-emi-previous-vs-current | loans | text | pass | 5449.2 | 7544.3 |  |
| L03-emi-change-cause | loans | text | FAIL | 7042.5 | 8757.5 | missing '1 Oct 2026' |
| L04-prepay-50k | loans | text | pass | 9543.3 | 11619.3 |  |
| L05-prepay-50k-interest | loans | text | pass | 9302.9 | 10620.6 |  |
| L06-prepay-reduce-emi | loans | text | pass | 8509.8 | 9649.5 |  |
| L07-extra-20k-tenure | loans | text | pass | 7799.3 | 9096.2 |  |
| L08-next-emi | loans | text | pass | 6460.1 | 7831.7 |  |
| L09-outstanding | loans | text | pass | 6494.4 | 7231.0 |  |
| L10-last-payment | loans | text | pass | 6115.5 | 6913.1 |  |
| L11-foreclose-floating | loans | text | pass | 5587.9 | 7151.9 |  |
| L12-context-followup-amount | loans | text | pass | 8890.1 | 9542.7 |  |
| L13-request-prepayment | loans | text | pass | 7132.0 | 8147.1 |  |
| L14-failed-payments | loans | text | FAIL | 9204.8 | 12052.7 | missing '10 Jun 2026'; missing '10 Sep 2026' |
| L15-charged-twice | loans | text | pass | 5830.3 | 7072.0 |  |
| L16-dispute | loans | text | pass | 7646.9 | 8177.7 |  |
| L17-fixed-emi-unchanged | loans | text | pass | 10387.5 | 11117.7 |  |
| L18-fixed-prepay-charge | loans | text | pass | 8054.0 | 9956.8 |  |
| L19-fixed-next-emi | loans | text | pass | 9680.3 | 10817.5 |  |
| L20-lockin-foreclosure | loans | text | pass | 6931.1 | 8422.5 |  |
| L21-lockin-prepay | loans | text | pass | 6949.1 | 7746.7 |  |
| L22-options | loans | text | FAIL | 6417.7 | 6896.1 | missing '20 Feb 2027' |
| L23-statement | loans | text | pass | 7418.5 | 8109.3 |  |
| L24-kavya-next-emi | loans | text | pass | 4692.3 | 5744.5 |  |
| L25-rohan-loan-emi-change | loans | text | pass | 5781.3 | 7751.6 |  |
| L26-no-amount-asks | loans | text | FAIL | 6424.0 | 6577.2 | missing 'how much' |
| L27-voice-next-emi | loans | voice | pass | 6157.8 | 7095.9 |  |
| L28-voice-switch-topic | loans | voice | pass | 2793.3 | 3370.2 |  |
| L29-voice-extra-payment | loans | voice | FAIL | 3935.3 | 4773.6 | missing '1 month' |
| L30-mandate | loans | text | pass | 4081.1 | 13310.8 |  |
| L31-voice-misheard-failed | loans | voice | pass | 7453.2 | 8618.4 |  |
| L32-voice-next-due-date | loans | voice | pass | 8327.7 | 9009.4 |  |
| L33-emis-left | loans | text | pass | 5909.2 | 6445.4 |  |
| L34-vague-payments | loans | voice | pass | 5445.9 | 6223.4 |  |
