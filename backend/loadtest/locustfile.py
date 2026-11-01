"""Load test: simulated customers holding a conversation.

Each simulated user opens a session and sends a turn every 15-30 s, cycling through common questions.
Run against an orchestrator started with LLM_MODE=stub (model-like latency, no API spend) and a high
TURN_RATE_LIMIT, so the test measures the platform, the connector gateway and the mocks under load:

    LLM_MODE=stub TURN_RATE_LIMIT=100000 uv run uvicorn orchestrator.app:app --port 8000
    uv run locust -f loadtest/locustfile.py --host http://localhost:8000 --headless \
        -u 1000 -r 10 -t 6m --csv var/load/run
"""

from __future__ import annotations

import random
import threading
import time

from locust import HttpUser, between, events, task

from mocks.seed import build_dataset

PHONES = [c["phone"] for c in build_dataset()["customers"]]
QUESTIONS = ["What's my next EMI?", "Why did my EMI change this month?", "What if I prepay ₹50,000?",
             "Show my failed payments in the last six months", "Can I foreclose my loan without a penalty?",
             "How much do I still owe?", "Would paying ₹20,000 extra reduce my tenure?"]
_tokens: dict[str, str] = {}
_lock = threading.Lock()


class Customer(HttpUser):
    wait_time = between(15, 30)

    def on_start(self):
        self.phone = random.choice(PHONES)
        with _lock:  # one login per phone (the OTP endpoint is rate limited per phone); held across the login
            token = _tokens.get(self.phone)
            if token is None:
                start = self.client.post("/v1/auth/otp/start", json={"phone": self.phone}, name="auth").json()
                tok = self.client.post("/v1/auth/otp/verify", json={"challenge_id": start["challenge_id"],
                                                                     "code": start["demo_code"]}, name="auth").json()
                token = _tokens[self.phone] = tok["access_token"]
        self.headers = {"Authorization": f"Bearer {token}"}
        self.session_id = self.client.post("/v1/sessions", json={}, headers=self.headers,
                                           name="/v1/sessions").json()["session_id"]

    @task
    def ask(self):
        started = time.perf_counter()
        first_token = None
        with self.client.post(f"/v1/sessions/{self.session_id}/turns", json={"text": random.choice(QUESTIONS)},
                              headers=self.headers, name="turn (response headers)", stream=True,
                              catch_response=True) as resp:
            body = b""
            for chunk in resp.iter_content(chunk_size=None):
                body += chunk
                if first_token is None and b"event: answer.delta" in body:
                    first_token = (time.perf_counter() - started) * 1000
            if b"event: turn.completed" not in body:
                resp.failure("turn did not complete")
            else:
                resp.success()
        if first_token is not None:
            events.request.fire(request_type="SSE", name="turn first token", response_time=first_token,
                                response_length=0, exception=None, context={})
