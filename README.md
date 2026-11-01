# Northstar — AI loan servicing assistant

A working proof of concept: customers chat or talk to an assistant that answers from their own loan and
card records, shows the evidence behind every figure, and files service requests (prepayment, dispute,
foreclosure, statement) with confirmation and OTP. Built on a reusable platform core; credit cards are a
second workflow added as a pack.

- Architecture, decisions, measured results and deviations from the original design: [ARCHITECTURE.md](ARCHITECTURE.md)
- API and event contract: [docs/api-contract.md](docs/api-contract.md)
- Evidence: [docs/evals/latest.md](docs/evals/latest.md), [docs/perf/](docs/perf/), [docs/screenshots/](docs/screenshots/)

## Run it (no keys needed)

Requirements: [uv](https://docs.astral.sh/uv/) and Node 20+. Chrome for voice.

```bash
cp .env.example .env          # optional; defaults work
make install                  # uv sync + npm ci
make up                       # mocks :8100, orchestrator :8000, web :3000
open http://localhost:3000    # pick a demo customer; the OTP is shown on screen
make stop
```

Or run them in separate terminals: `make mocks`, `make api`, `make web`, and on Apple Silicon `make speech`.

**Speech recognition:** on Apple Silicon, `make up` also starts a local speech service (`speech/`, port 8200) that
runs NVIDIA's Parakeet TDT 0.6B v3 via MLX: about 140 ms to transcribe a 4-second question, nothing sent to Google.
The voice bar shows "On-device recognition" when it is used; without it the app falls back to Chrome's recogniser.
English only for now (Parakeet v3 has no Hindi). Measurements: `research_notes/Local speech stack/`.
With Docker: `docker compose up --build` (written, not verified on the build machine).

**Claude planner:** set `ANTHROPIC_API_KEY` in `.env` (or `ant auth login`) and restart `make api`. Without
credentials the orchestrator uses the deterministic intent planner, which handles the demo journeys.
`GET http://localhost:8000/readyz` shows which planner is active.

## Demo customers and journeys

| Customer | Try |
|---|---|
| Priya Sharma | "My EMI increased this month. Why?" → "If I prepay ₹50,000 today, how much interest would I save?" → "Go ahead, reduce my tenure" (OTP) |
| Priya (voice) | Mic → "What's my next EMI?" → interrupt: "Actually, check my last payment first" → "Would paying ₹20,000 extra reduce my tenure?" |
| Arjun Mehta | "Show me the payments that failed in the last six months" → "Raise a dispute for the duplicate charge" |
| Kavya Iyer | "Am I eligible for foreclosure without a penalty?" → "What are my options?" → "Send me a statement" |
| Rohan Das | "Why is my card statement higher this month?" → "Dispute the ₹4,299 charge" (credit card pack) |

Add `?demo=1` to the URL for the chaos controls (calm / realistic / bad day). `/latency` shows measured
latency per stage and per system; `/evals` shows the last golden-set run.

## Tests and evidence

```bash
make test     # backend pytest (58) + web unit tests, typecheck, lint
make eval     # golden set: 42 questions across 3 packs -> docs/evals/latest.md
make bench    # journey latency, cold cache, realistic and bad-day backends -> docs/perf/
make load     # 1,000 concurrent sessions (start the API with LLM_MODE=stub TURN_RATE_LIMIT=100000)
```

## Layout

```
backend/
  src/nsplatform/   platform core: connector gateway, calculators, policy engine, action executor, pack loader
  src/orchestrator/ API, turn runner (Claude agent loop + deterministic planner), grounding check
  src/mocks/        CRM, Loan Mgmt, Payments, Policy, Service Ops, Cards — seeded data + chaos injection
  packs/            core, loans, cards — manifest, handlers, rules, prompts, golden evals
  tests/ evals/ bench/ loadtest/
web/                Next.js app: chat, voice, account panel, requests, latency, evals
docs/               API contract, eval and performance reports, screenshots
```

All data is synthetic. Northstar Finance is fictional.
