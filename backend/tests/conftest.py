"""Test harness: mocks + orchestrator wired in-process (no network, no LLM, no latency)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="northstar-tests-")
os.environ.setdefault("CHAOS_PRESET", "fast")
os.environ["DEMO_MODE"] = "true"
os.environ.setdefault("MOCKS_DB", str(Path(_tmp) / "mocks.db"))
os.environ.setdefault("APP_DB", str(Path(_tmp) / "app.db"))
os.environ["LLM_MODE"] = "fallback"
os.environ.pop("REDIS_URL", None)

import httpx  # noqa: E402
import pytest  # noqa: E402

from nsplatform.runtime import build_platform  # noqa: E402
from mocks.app import app as mocks_app  # noqa: E402
from mocks.app import chaos  # noqa: E402
from orchestrator.app import create_app  # noqa: E402
from orchestrator.config import BACKEND_DIR, Settings  # noqa: E402

SYSTEMS = ["crm", "loans", "payments", "policy", "ops", "cards"]


def make_platform(only_packs=None):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mocks_app))
    return build_platform(BACKEND_DIR / "packs", {n: "http://mocks" for n in SYSTEMS}, demo_mode=True,
                          client=client, only_packs=only_packs)


@pytest.fixture
def platform():
    chaos.set_preset("fast")
    return make_platform()


@pytest.fixture
def api(platform):
    settings = Settings()
    settings.mocks_url = "http://mocks"
    app = create_app(settings, platform)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


PHONES = {"C1001": "9876543101", "C1002": "9876543102", "C1003": "9876543103", "C1004": "9876543104"}


async def login(api, customer_id: str) -> dict:
    start = (await api.post("/v1/auth/otp/start", json={"phone": PHONES[customer_id]})).json()
    tok = (await api.post("/v1/auth/otp/verify", json={"challenge_id": start["challenge_id"],
                                                        "code": start["demo_code"]})).json()
    headers = {"Authorization": f"Bearer {tok['access_token']}"}
    session = (await api.post("/v1/sessions", json={}, headers=headers)).json()
    return {"headers": headers, "session": session}


async def turn(api, auth: dict, text: str, channel: str = "text") -> list[tuple[str, dict]]:
    resp = await api.post(f"/v1/sessions/{auth['session']['session_id']}/turns",
                          json={"text": text, "channel": channel}, headers=auth["headers"])
    assert resp.status_code == 200, resp.text
    events = []
    for frame in resp.text.split("\n\n"):
        if not frame.strip():
            continue
        lines = dict(line.split(": ", 1) for line in frame.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def answer(events) -> str:
    verified = [d for e, d in events if e == "answer.verified" and d.get("replaced_text")]
    if verified:
        return verified[-1]["replaced_text"]
    return "".join(d["text"] for e, d in events if e == "answer.delta")
