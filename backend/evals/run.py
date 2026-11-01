"""Golden-set evaluation: accuracy and latency, reported together.

Runs every case in packs/*/evals/golden.yaml through the real API surface (login, session, turns) and
checks the reply's figures, the tools that ran, proposed actions and forbidden content.

    uv run python evals/run.py                       # in-process, deterministic planner, realistic chaos
    uv run python evals/run.py --chaos calm          # no injected failures
    uv run python evals/run.py --url http://localhost:8000   # against running servers (uses their LLM mode)
    LLM_MODE=llm uv run python evals/run.py          # in-process with the Claude planner

Writes var/evals/latest.json (served at /v1/evals/latest) and docs/evals/latest.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))


def _planner_model(settings) -> str:
    from orchestrator.llm import PROVIDERS
    return settings.models_for(PROVIDERS[settings.llm_provider])[0]


def load_cases(only: str | None) -> list[dict]:
    import yaml

    cases = []
    for file in sorted((ROOT / "packs").glob("*/evals/golden.yaml")):
        for case in yaml.safe_load(file.read_text())["cases"]:
            case["pack"] = file.parts[-3]
            if not only or case["id"].startswith(only):
                cases.append(case)
    return cases


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for frame in text.split("\n\n"):
        if frame.strip():
            lines = dict(line.split(": ", 1) for line in frame.splitlines() if ": " in line)
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def final_answer(events) -> str:
    replaced = [d["replaced_text"] for e, d in events if e == "answer.verified" and d.get("replaced_text")]
    return replaced[-1] if replaced else "".join(d["text"] for e, d in events if e == "answer.delta")


_tokens: dict[str, str] = {}
_login_lock = asyncio.Lock()


async def login_once(api, phone: str) -> str:
    """One login per customer (the OTP endpoint is rate limited, as it should be); a new session per case."""
    async with _login_lock:
        if phone not in _tokens:
            start = (await api.post("/v1/auth/otp/start", json={"phone": phone})).json()
            tok = (await api.post("/v1/auth/otp/verify", json={"challenge_id": start["challenge_id"],
                                                                "code": start["demo_code"]})).json()
            _tokens[phone] = tok["access_token"]
        return _tokens[phone]


async def run_case(api, case: dict, seed: str) -> dict:
    from conftest import PHONES

    started = time.perf_counter()
    token = await login_once(api, PHONES[case["customer"]])
    headers = {"Authorization": f"Bearer {token}", "X-Chaos-Seed": seed}
    session = (await api.post("/v1/sessions", json={}, headers=headers)).json()
    channel = case.get("channel", "text")

    async def ask(text: str):
        r = await api.post(f"/v1/sessions/{session['session_id']}/turns", json={"text": text, "channel": channel},
                           headers=headers, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"turn returned HTTP {r.status_code}: {r.text[:200]}")
        return parse_sse(r.text)

    for prior in case.get("history", []):
        await ask(prior)
    events = await ask(case["question"])
    reply = final_answer(events)
    # spoken-style answers write small numbers as words ("one month"); match them as digits too
    words = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]
    digits = re.sub(r"\b(" + "|".join(words) + r")\b", lambda m: str(words.index(m.group(1).lower()) + 1), reply,
                    flags=re.I)
    haystack = reply + "\n" + digits
    haystack = haystack.lower() if case.get("case_insensitive") else haystack
    tools = [d["tool"] for e, d in events if e == "tool.started"]
    proposed = [d["action"] for e, d in events if e == "action.proposed"]
    completed = next((d for e, d in events if e == "turn.completed"), None)
    failures = []
    for s in case.get("contains", []):
        if (s.lower() if case.get("case_insensitive") else s) not in haystack:
            failures.append(f"missing '{s}'")
    for s in case.get("forbid", []):
        if s.lower() in reply.lower():
            failures.append(f"contains forbidden '{s}'")
    for t in case.get("tools", []):
        if t not in tools:
            failures.append(f"tool {t} not called (called: {tools or 'none'})")
    if case.get("action") and case["action"] not in proposed and case["action"] not in tools:
        failures.append(f"action {case['action']} not proposed")
    if completed is None:
        failures.append("turn did not complete")
    verified = next((d for e, d in events if e == "answer.verified"), {})
    return {"id": case["id"], "pack": case["pack"], "question": case["question"], "channel": channel,
            "passed": not failures, "reason": "; ".join(failures), "reply": reply[:600], "tools": tools,
            "figures_ok": not any(f.startswith("missing") for f in failures) if case.get("contains") else None,
            "grounded": verified.get("ok", False) or bool(verified.get("replaced_text")),
            "grounding_replaced": bool(verified.get("replaced_text")),
            "mode": (completed or {}).get("mode"),
            "first_token_ms": (completed or {}).get("timings", {}).get("first_token_ms"),
            "total_ms": (completed or {}).get("timings", {}).get("total_ms"),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1)}


def pct(values, p):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    k = (len(values) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo), 1)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="run against a live orchestrator instead of in-process")
    ap.add_argument("--chaos", default="realistic", help="in-process chaos preset: calm | realistic | bad_day | fast")
    ap.add_argument("--only", help="run case ids starting with this prefix")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    import httpx

    planner = os.environ.get("LLM_MODE", "fallback")  # captured before the test fixtures are imported (they reset it)
    if args.url:
        api = httpx.AsyncClient(base_url=args.url, timeout=60)
    else:
        tmp = tempfile.mkdtemp(prefix="northstar-evals-")
        os.environ.setdefault("MOCKS_DB", str(Path(tmp) / "mocks.db"))
        os.environ.setdefault("APP_DB", str(Path(tmp) / "app.db"))
        os.environ["CHAOS_PRESET"] = args.chaos
        os.environ.setdefault("LLM_MODE", "fallback")
        os.environ.setdefault("DEMO_MODE", "true")  # logs in with the on-screen demo OTP
        os.environ.setdefault("TURN_RATE_LIMIT", "1000")  # the eval replays many turns per customer
        from nsplatform.runtime import build_platform
        from mocks.app import app as mocks_app
        from mocks.app import chaos
        from orchestrator.app import create_app
        from orchestrator.config import Settings

        chaos.set_preset(args.chaos)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mocks_app))
        platform = build_platform(ROOT / "packs", {n: "http://mocks" for n in
                                                   ["crm", "loans", "payments", "policy", "ops", "cards"]}, client=client)
        settings = Settings()
        settings.mocks_url = "http://mocks"
        api = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(settings, platform)),
                                base_url="http://api", timeout=60)

    cases = load_cases(args.only)
    sem = asyncio.Semaphore(args.concurrency)

    async def guarded(i, case):
        async with sem:
            try:
                return await run_case(api, case, seed=f"eval-{case['id']}")
            except Exception as e:  # report, don't crash the run
                return {"id": case["id"], "pack": case["pack"], "question": case["question"], "passed": False,
                        "reason": f"error: {type(e).__name__}: {e}", "figures_ok": False if case.get("contains") else None}

    results = await asyncio.gather(*(guarded(i, c) for i, c in enumerate(cases)))
    with_figures = [r for r in results if r.get("figures_ok") is not None]
    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": args.url or f"in-process (chaos={args.chaos}, planner={planner}"
                  + (f", provider={settings.llm_provider}, model={_planner_model(settings)}" if planner == "llm" else "")
                  + ")",
        "total": len(results), "passed": sum(r["passed"] for r in results),
        "figure_accuracy": round(sum(r["figures_ok"] for r in with_figures) / len(with_figures), 3) if with_figures else None,
        "grounding_replacements": sum(1 for r in results if r.get("grounding_replaced")),
        "first_token_p50_ms": pct([r.get("first_token_ms") for r in results], 0.5),
        "first_token_p95_ms": pct([r.get("first_token_ms") for r in results], 0.95),
        "turn_total_p50_ms": pct([r.get("total_ms") for r in results], 0.5),
        "turn_total_p95_ms": pct([r.get("total_ms") for r in results], 0.95),
        "cases": results,
    }
    out = ROOT / "var" / "evals"
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    docs = ROOT.parent / "docs" / "evals"
    docs.mkdir(parents=True, exist_ok=True)
    lines = [f"# Golden-set eval — {summary['run_at']}", "", f"Target: {summary['target']}", "",
             f"- Passed: **{summary['passed']}/{summary['total']}**",
             f"- Figure accuracy (cases with expected figures): **{summary['figure_accuracy']}**",
             f"- Grounding replacements: {summary['grounding_replacements']}",
             f"- First token p50 / p95: {summary['first_token_p50_ms']} / {summary['first_token_p95_ms']} ms",
             f"- Turn complete p50 / p95: {summary['turn_total_p50_ms']} / {summary['turn_total_p95_ms']} ms", "",
             "| Case | Pack | Channel | Result | First token (ms) | Total (ms) | Notes |", "|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['id']} | {r['pack']} | {r.get('channel', 'text')} | {'pass' if r['passed'] else 'FAIL'} | "
                     f"{r.get('first_token_ms') or ''} | {r.get('total_ms') or ''} | {r.get('reason', '')} |")
    (docs / "latest.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:9]))
    for r in results:
        if not r["passed"]:
            print(f"  FAIL {r['id']}: {r['reason']}\n        reply: {r.get('reply', '')[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
