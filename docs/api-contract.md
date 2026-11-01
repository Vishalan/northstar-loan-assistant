# Orchestrator API contract (v1)

Base URL: `http://localhost:8000` (env `NEXT_PUBLIC_API_URL` in the web app).
All JSON. Auth: `Authorization: Bearer <access_token>` on every `/v1` call except auth and personas.
Errors: HTTP 4xx/5xx with body `{"error": {"code": str, "message": str, "retryable": bool}}`.

## Auth

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/v1/personas` | – | `[{customer_id, name, phone, summary}]` (demo login picker) |
| POST | `/v1/auth/otp/start` | `{phone}` | `{challenge_id, demo_code}` (`demo_code` only in demo mode) |
| POST | `/v1/auth/otp/verify` | `{challenge_id, code}` | `{access_token, expires_in, customer: {customer_id, name}}` |

## Sessions and turns

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/v1/sessions` | `{}` | `{session_id, customer: {customer_id, name}, products: [{type: "loan"\|"card", id, label}], suggestions: [str]}` |
| POST | `/v1/sessions/{session_id}/turns` | `{text, channel: "text"\|"voice"}` | **SSE stream** (below) |
| POST | `/v1/sessions/{session_id}/prefetch` | `{text}` | `{warmed: [tool names]}` — call with interim voice transcripts (speculative read-only prefetch) |
| POST | `/v1/turns/{turn_id}/cancel` | `{spoken_text?}` | `{ok: true}` — barge-in; `spoken_text` = what was already spoken aloud |
| POST | `/v1/actions/{action_id}/confirm` | `{otp?: str, via: "button"\|"voice"}` | `{action_id, status: "succeeded"\|"failed"\|"otp_invalid"\|"expired", request_id?, sla_due?, message}` |
| POST | `/v1/actions/{action_id}/cancel` | `{}` | `{action_id, status: "cancelled"}` |

### SSE stream format

`Content-Type: text/event-stream`. Each event: `event: <name>\ndata: <json>\n\n`. Every data object has `turn_id`, `seq`, `ts` (epoch ms) plus:

| event | data fields |
|---|---|
| `turn.started` | `session_id, channel` |
| `status` | `text` — human progress line, e.g. "Checking your recent payments…" |
| `tool.started` | `call_id, tool, system, label` |
| `tool.finished` | `call_id, tool, status: "ok"\|"degraded"\|"unavailable", latency_ms, from_cache` |
| `focus` | `product_id` — highlight this product in the account panel |
| `answer.delta` | `text` — append to the current assistant message |
| `answer.verified` | `ok: bool, replaced_text?: str` — if `replaced_text` present, replace the whole assistant message text with it |
| `card` | a Card (below) |
| `action.proposed` | an ActionProposal (below) |
| `suggestions` | `chips: [str]` |
| `turn.completed` | `timings: {first_status_ms, first_token_ms, total_ms, llm_ms, tools_ms}, mode: "llm"\|"fallback"` |
| `turn.error` | `code, message, retryable` |

A turn always ends with `turn.completed` or `turn.error`. A cancelled turn ends with `turn.error` code `cancelled`.

### Card (generic — the UI renders every card type with one component)

```json
{
  "type": "emi_change",            // free-form id; UI may special-case but must render any type
  "title": "Why your EMI changed",
  "subtitle": "Loan PL-20391",
  "metrics": [ {"label": "Old EMI", "value": "₹17,195", "emphasis": false},
               {"label": "New EMI", "value": "₹17,486", "emphasis": true, "delta": "+₹291"} ],
  "columns": [ {"label": "Reduce tenure", "metrics": [ {"label": "Interest saved", "value": "₹31,200"} ]} ],  // optional side-by-side comparison
  "table": {"columns": ["Date", "Amount", "Status", "Reason"], "rows": [["10 Jun 2026", "₹13,167", "Failed", "Insufficient funds"]], "row_status": ["bad"]},  // optional; row_status per row: "ok"|"warn"|"bad"|null
  "notes": ["Floating rate linked to EBLR; no prepayment charge applies."],
  "actions": [ {"label": "Request this prepayment", "prompt": "Go ahead and request a ₹50,000 prepayment to reduce my tenure"} ],  // clicking sends `prompt` as a new user turn
  "sources": [ {"kind": "record", "system": "Loan Management", "ref": "rate_history/PL-20391", "as_of": "2026-10-27T10:00:00+05:30"},
               {"kind": "policy", "ref": "LOAN-TNC-7.2", "text": "Clause text..."},
               {"kind": "calc", "ref": "prepayment_savings", "steps": ["Outstanding ₹6,62,410 …", "…"]} ]
}
```

### ActionProposal

```json
{
  "action_id": "act_…",
  "action": "create_prepayment_request",
  "title": "Prepayment request",
  "summary": [ {"label": "Loan", "value": "PL-20391"}, {"label": "Amount", "value": "₹50,000"} ],
  "tier": "read" | "confirm" | "confirm_otp",
  "expires_at": "ISO-8601",
  "demo_otp": "123456"            // only for confirm_otp in demo mode
}
```

## Account and requests

| Method | Path | Response |
|---|---|---|
| GET | `/v1/account/overview` | `{customer: {customer_id, name, segment}, loans: [Loan], cards: [Card], payments: [Payment], requests: [Request], degraded: [system names unavailable]}` |
| GET | `/v1/requests` | `[Request]` |

- Loan: `{loan_id, product_name, rate_type, current_rate, emi, outstanding_principal, next_due_date, tenure_left_months, principal, status}`
- Card: `{card_id, last4, limit, outstanding, min_due, due_date, statement_total}`
- Payment: `{txn_id, loan_id, date, amount, status: "success"|"failed"|"reversed", failure_reason?, charge?}` (last 6 months, newest first)
- Request: `{request_id, type, status, created_at, sla_due, summary}`

Money values in these objects are numbers (rupees); format client-side with `Intl.NumberFormat('en-IN', {style:'currency', currency:'INR', maximumFractionDigits: 0})`.

## Metrics, demo controls, evals

| Method | Path | Body / Response |
|---|---|---|
| GET | `/v1/metrics/latency?window=200` | `{stages: [{name, count, p50_ms, p95_ms}], systems: [{system, count, p50_ms, p95_ms, error_rate}], turns: [{turn_id, channel, mode, first_token_ms, total_ms, at}], client: [{name, count, p50_ms, p95_ms}]}` |
| POST | `/v1/metrics/client` | `{name: "voice.eos_to_first_audio"\|"voice.bargein_stop"\|"text.first_token_render", ms, meta?}` → `{ok: true}` |
| GET | `/v1/demo/chaos` | `{preset, presets: [str], systems: {name: {median_ms, fail_rate}}}` |
| PUT | `/v1/demo/chaos` | `{preset: "calm"\|"realistic"\|"bad_day"}` → same as GET |
| GET | `/v1/evals/latest` | `{run_at, total, passed, figure_accuracy, cases: [{id, pack, question, passed, reason, latency_ms}]}` or `{}` if none |
| GET | `/v1/statements/{request_id}` | `application/pdf` (auth via `?token=` query param allowed for download links) |
