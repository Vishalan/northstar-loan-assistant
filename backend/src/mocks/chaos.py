"""Latency and failure injection for the mock systems.

Each system has a lognormal latency (median, p95), a failure rate and an optional hang rate.
Presets switch the whole profile at runtime. Sending `X-Chaos-Seed` makes injection deterministic
per request (used by evals and benchmarks).
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import random
from copy import deepcopy

REALISTIC = {
    "crm": {"median_ms": 80, "p95_ms": 200, "fail_rate": 0.01, "hang_rate": 0.0},
    "loans": {"median_ms": 150, "p95_ms": 350, "fail_rate": 0.02, "hang_rate": 0.0},
    "payments": {"median_ms": 600, "p95_ms": 1500, "fail_rate": 0.08, "hang_rate": 0.03, "hang_ms": 5000},
    "policy": {"median_ms": 120, "p95_ms": 250, "fail_rate": 0.0, "hang_rate": 0.0},
    "ops": {"median_ms": 600, "p95_ms": 1200, "fail_rate": 0.05, "hang_rate": 0.0},
    "cards": {"median_ms": 200, "p95_ms": 500, "fail_rate": 0.02, "hang_rate": 0.0},
}


def _calm():
    calm = deepcopy(REALISTIC)
    for profile in calm.values():
        profile["fail_rate"] = 0.0
        profile["hang_rate"] = 0.0
    return calm


def _bad_day():
    bad = deepcopy(REALISTIC)
    bad["payments"].update(fail_rate=1.0)
    bad["ops"].update(median_ms=3000, p95_ms=4500)
    return bad


def _fast():
    """No latency, no failures: unit tests and the LLM-stubbed load test of the platform itself."""
    return {name: {"median_ms": 1, "p95_ms": 2, "fail_rate": 0.0, "hang_rate": 0.0} for name in REALISTIC}


PRESETS = {"calm": _calm, "realistic": lambda: deepcopy(REALISTIC), "bad_day": _bad_day, "fast": _fast}


class Chaos:
    def __init__(self, preset: str = "realistic"):
        self.set_preset(preset)

    def set_preset(self, preset: str):
        if preset not in PRESETS:
            raise ValueError(f"unknown preset {preset}")
        self.preset = preset
        self.systems = PRESETS[preset]()

    def describe(self) -> dict:
        return {"preset": self.preset, "presets": [p for p in PRESETS if p != "fast"],
                "systems": {k: {"median_ms": v["median_ms"], "fail_rate": v["fail_rate"]}
                            for k, v in self.systems.items()}}

    def _rng(self, seed: str | None, path: str) -> random.Random:
        if seed is None:
            return random.Random()
        digest = hashlib.sha256(f"{seed}|{path}".encode()).hexdigest()
        return random.Random(int(digest[:16], 16))

    async def apply(self, system: str, path: str, seed: str | None = None) -> str | None:
        """Sleep for a sampled latency; return a failure mode ('unavailable', 'malformed') or None."""
        profile = self.systems.get(system)
        if not profile:
            return None
        rng = self._rng(seed, path)
        median, p95 = profile["median_ms"], profile["p95_ms"]
        sigma = math.log(p95 / median) / 1.645 if p95 > median else 0.0
        delay_ms = median * math.exp(rng.gauss(0, 1) * sigma)
        if rng.random() < profile.get("hang_rate", 0.0):
            delay_ms = profile.get("hang_ms", 5000)
        await asyncio.sleep(delay_ms / 1000)
        if rng.random() < profile["fail_rate"]:
            return "malformed" if system == "payments" and rng.random() < 0.2 else "unavailable"
        return None
