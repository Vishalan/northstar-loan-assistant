"""Journey benchmark: replay the demo journeys N times per chaos preset and report latency per stage.

    uv run python bench/journeys.py --runs 50            # realistic + bad_day, deterministic planner
    LLM_MODE=stub uv run python bench/journeys.py         # with simulated LLM latency

Measured in-process through the real API surface (auth, sessions, SSE turns, connector gateway, mocks with
injected latency/failures). Writes docs/perf/journeys.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
tmp = tempfile.mkdtemp(prefix="northstar-bench-")
os.environ.setdefault("MOCKS_DB", str(Path(tmp) / "mocks.db"))
os.environ.setdefault("APP_DB", str(Path(tmp) / "app.db"))
os.environ.setdefault("LLM_MODE", "fallback")
os.environ.setdefault("DEMO_MODE", "true")  # logs in with the on-screen demo OTP
os.environ.setdefault("TURN_RATE_LIMIT", "100000")

JOURNEYS = {
    "1 EMI change → prepayment → request": ("9876543101", ["My EMI increased this month. Why?",
                                                          "If I make a ₹50,000 prepayment today, how much interest would I save?",
                                                          "Go ahead and request a prepayment of ₹50,000 to reduce my tenure"]),
    "2 Failed payments → dispute": ("9876543102", ["Show me the payments that failed in the last six months",
                                                   "Raise a dispute for the duplicate charge"]),
    "3 Voice: next EMI → last payment → extra ₹20,000": ("9876543101", ["What's my next EMI?",
                                                                       "Actually, check my last payment first",
                                                                       "Okay, now would paying ₹20,000 extra reduce my tenure?"]),
    "4 Foreclosure in lock-in → statement": ("9876543103", ["Am I eligible for foreclosure without a penalty?",
                                                            "Send me a statement"]),
    "5 Card statement → dispute": ("9876543104", ["Why is my card statement higher this month?",
                                                  "Dispute the ₹4,299 charge from 12 October"]),
}


def pct(values, p):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    k = (len(values) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo))


async def run_preset(preset: str, runs: int, cold: bool):
    import httpx

    from nsplatform import telemetry
    from nsplatform.db import get_db
    from nsplatform.runtime import build_platform
    from mocks.app import app as mocks_app
    from mocks.app import chaos
    from orchestrator.app import create_app
    from orchestrator.config import Settings
    from run import final_answer, parse_sse

    chaos.set_preset(preset)
    get_db().execute("DELETE FROM spans")
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mocks_app))
    platform = build_platform(ROOT / "packs", {n: "http://mocks" for n in
                                               ["crm", "loans", "payments", "policy", "ops", "cards"]}, client=client)
    settings = Settings()
    settings.mocks_url = "http://mocks"
    api = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(settings, platform)), base_url="http://api",
                            timeout=60)
    tokens = {}
    per_journey: dict[str, list[dict]] = {name: [] for name in JOURNEYS}
    sem = asyncio.Semaphore(1 if cold else 8)

    async def one(name, phone, questions, i):
        async with sem:
            if cold:  # drop cached system responses: only the login prefetch warms the session
                store = platform.store
                for key in [k for k in getattr(store, "_data", {}) if k.startswith("cache:")]:
                    store._data.pop(key, None)
            if phone not in tokens:
                s = (await api.post("/v1/auth/otp/start", json={"phone": phone})).json()
                tokens[phone] = (await api.post("/v1/auth/otp/verify", json={"challenge_id": s["challenge_id"],
                                                                              "code": s["demo_code"]})).json()["access_token"]
            headers = {"Authorization": f"Bearer {tokens[phone]}"}
            sid = (await api.post("/v1/sessions", json={}, headers=headers)).json()["session_id"]
            channel = "voice" if name.startswith("3") else "text"
            for q in questions:
                r = await api.post(f"/v1/sessions/{sid}/turns", json={"text": q, "channel": channel}, headers=headers)
                events = parse_sse(r.text)
                done = next((d for e, d in events if e == "turn.completed"), None)
                tools = [d for e, d in events if e == "tool.finished"]
                per_journey[name].append({
                    "ok": done is not None and bool(final_answer(events)),
                    "degraded": any(t["status"] != "ok" for t in tools),
                    "first_status_ms": done and done["timings"]["first_status_ms"],
                    "first_token_ms": done and done["timings"]["first_token_ms"],
                    "total_ms": done and done["timings"]["total_ms"]})

    for name, (phone, questions) in JOURNEYS.items():
        s = (await api.post("/v1/auth/otp/start", json={"phone": phone})).json()
        tokens[phone] = (await api.post("/v1/auth/otp/verify", json={"challenge_id": s["challenge_id"],
                                                                      "code": s["demo_code"]})).json()["access_token"]
    await asyncio.gather(*(one(n, p, q, i) for n, (p, q) in JOURNEYS.items() for i in range(runs)))
    telemetry.flush()
    systems = {}
    for row in get_db().query("SELECT system, duration_ms, status FROM spans WHERE name='connector.call'"):
        systems.setdefault(row["system"], []).append(row)
    return per_journey, systems


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=50)
    ap.add_argument("--presets", default="realistic,bad_day")
    ap.add_argument("--cold", action="store_true", help="clear the connector cache before every journey run")
    args = ap.parse_args()
    lines = [f"# Journey benchmark — {datetime.now(timezone.utc).isoformat(timespec='seconds')}", "",
             f"Planner: `{os.environ['LLM_MODE']}` · {args.runs} runs per journey per preset · in-process, mocks with "
             "injected latency and failures (see `src/mocks/chaos.py`). Times in ms, measured from request to event.", ""]
    for preset in args.presets.split(","):
        per_journey, systems = await run_preset(preset, args.runs, args.cold)
        lines += [f"## Chaos preset: `{preset}` ({'cold cache per journey' if args.cold else 'warm cache shared across runs'})", "",
                  "| Journey | Turns | Completed | Degraded | First status p50 / p95 | First token p50 / p95 | Turn total p50 / p95 |",
                  "|---|---|---|---|---|---|---|"]
        for name, rows in per_journey.items():
            lines.append(f"| {name} | {len(rows)} | {sum(r['ok'] for r in rows)} | {sum(r['degraded'] for r in rows)} | "
                         f"{pct([r['first_status_ms'] for r in rows], .5)} / {pct([r['first_status_ms'] for r in rows], .95)} | "
                         f"{pct([r['first_token_ms'] for r in rows], .5)} / {pct([r['first_token_ms'] for r in rows], .95)} | "
                         f"{pct([r['total_ms'] for r in rows], .5)} / {pct([r['total_ms'] for r in rows], .95)} |")
        lines += ["", "| System | Calls | Cache hits | Errors | Live call p50 / p95 |", "|---|---|---|---|---|"]
        for system, rows in sorted(systems.items()):
            live = [r["duration_ms"] for r in rows if r["status"] != "cache_hit"]
            lines.append(f"| {system} | {len(rows)} | {sum(r['status'] == 'cache_hit' for r in rows)} | "
                         f"{sum(r['status'] in ('unavailable', 'error') for r in rows)} | {pct(live, .5)} / {pct(live, .95)} |")
        lines.append("")
    out = ROOT.parent / "docs" / "perf"
    out.mkdir(parents=True, exist_ok=True)
    planner = os.environ["LLM_MODE"]
    if planner == "llm":  # name the report after the model that ran, e.g. journeys-claude-haiku-5-5-cold.md
        from orchestrator.config import Settings
        from orchestrator.llm import PROVIDERS
        settings = Settings()
        planner = settings.models_for(PROVIDERS[settings.llm_provider])[0].replace(":", "-")
    name = f"journeys-{planner}-{'cold' if args.cold else 'warm'}.md"
    (out / name).write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())
