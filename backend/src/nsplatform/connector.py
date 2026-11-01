"""Connector gateway: the only way any workflow reaches an enterprise system.

Per call: bulkhead (max in-flight per system), cache (read calls), timeout, one jittered retry on
retryable failures (reads only), a circuit breaker per system, and stale-on-error. It never raises
to the caller; it returns a ToolResult whose status says what happened.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import os
import random
import time
from collections import deque
from dataclasses import dataclass, field

import httpx

from nsplatform import telemetry

chaos_seed: contextvars.ContextVar[str | None] = contextvars.ContextVar("chaos_seed", default=None)


@dataclass
class SystemConfig:
    name: str
    display_name: str
    base_url: str
    max_concurrency: int = 50


@dataclass
class CallPolicy:
    timeout_ms: int = 800
    retries: int = 1
    cache_s: float = 0
    stale_ok_s: float = 0
    write: bool = False


@dataclass
class ToolResult:
    status: str  # ok | degraded | unavailable | error
    data: dict | None = None
    source_ref: dict | None = None
    latency_ms: float = 0
    attempts: int = 0
    from_cache: bool = False
    error_code: str | None = None
    message: str | None = None
    http_status: int | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "degraded")


class Breaker:
    """Opens after `threshold` failures within `window_s`; half-opens after `cooldown_s`."""

    def __init__(self, threshold: int = 5, window_s: float = 30, cooldown_s: float = 15):
        self.threshold, self.window_s, self.cooldown_s = threshold, window_s, cooldown_s
        self.failures: deque[float] = deque()
        self.open_until = 0.0
        self.probing = False

    def allow(self) -> bool:
        now = time.monotonic()
        if now < self.open_until:
            return False
        if self.open_until and not self.probing:
            self.probing = True  # one half-open probe at a time
            return True
        return not self.probing

    def success(self) -> None:
        self.failures.clear()
        self.open_until = 0.0
        self.probing = False

    def failure(self) -> None:
        now = time.monotonic()
        if self.probing:
            self.probing = False
            self.open_until = now + self.cooldown_s
            return
        self.failures.append(now)
        while self.failures and self.failures[0] < now - self.window_s:
            self.failures.popleft()
        if len(self.failures) >= self.threshold:
            self.open_until = now + self.cooldown_s
            self.failures.clear()

    @property
    def state(self) -> str:
        if time.monotonic() < self.open_until:
            return "open"
        return "half_open" if self.open_until else "closed"


class ConnectorGateway:
    def __init__(self, systems: dict[str, SystemConfig], store, client: httpx.AsyncClient | None = None):
        self.systems = systems
        self.store = store
        self.client = client or httpx.AsyncClient(limits=httpx.Limits(max_connections=400, max_keepalive_connections=100))
        self.breakers = {name: Breaker() for name in systems}
        self.bulkheads = {name: asyncio.Semaphore(cfg.max_concurrency) for name, cfg in systems.items()}
        self.service_token = os.environ.get("SERVICE_TOKEN", "dev-service-token")

    def add_system(self, cfg: SystemConfig) -> None:
        if cfg.name not in self.systems:
            self.systems[cfg.name] = cfg
            self.breakers[cfg.name] = Breaker()
            self.bulkheads[cfg.name] = asyncio.Semaphore(cfg.max_concurrency)

    @staticmethod
    def _cache_key(customer_id: str, system: str, method: str, path: str, params: dict | None) -> str:
        return f"cache:{customer_id}:{system}:{method}:{path}:{json.dumps(params or {}, sort_keys=True)}"

    async def request(self, system: str, method: str, path: str, *, customer_id: str | None,
                      params: dict | None = None, body: dict | None = None, headers: dict | None = None,
                      policy: CallPolicy | None = None, tool: str | None = None) -> ToolResult:
        policy = policy or CallPolicy()
        cfg = self.systems[system]
        started = time.perf_counter()
        key = self._cache_key(customer_id or "-", system, method, path, params) if not policy.write else None

        cached = await self.store.get(key) if key and (policy.cache_s or policy.stale_ok_s) else None
        if cached and time.time() - cached["at"] < policy.cache_s:
            result = ToolResult("ok", cached["data"], cached["source_ref"], 0.0, 0, True)
            telemetry.record("connector.call", 0.0, system=system, status="cache_hit", tool=tool)
            return result

        breaker = self.breakers[system]
        result: ToolResult | None = None
        attempts = 0
        if not breaker.allow():
            result = ToolResult("unavailable", error_code="circuit_open",
                                message=f"{cfg.display_name} is unavailable (circuit open)")
        else:
            max_attempts = 1 if policy.write else 1 + policy.retries
            async with self.bulkheads[system]:
                while attempts < max_attempts:
                    attempts += 1
                    result = await self._attempt(cfg, method, path, customer_id, params, body, headers, policy)
                    if result.status == "ok" or result.error_code not in ("timeout", "unavailable", "malformed"):
                        break
                    if attempts < max_attempts:
                        await asyncio.sleep(random.uniform(0.05, 0.15))
            if result.status == "ok" or result.error_code not in ("timeout", "unavailable", "malformed"):
                breaker.success()
            else:
                breaker.failure()

        result.attempts = attempts
        result.latency_ms = round((time.perf_counter() - started) * 1000, 1)

        if result.status == "ok" and key and (policy.cache_s or policy.stale_ok_s):
            await self.store.set(key, {"data": result.data, "source_ref": result.source_ref, "at": time.time()},
                                 ttl_s=max(policy.cache_s, policy.stale_ok_s))
        elif result.status == "unavailable" and cached and time.time() - cached["at"] < policy.stale_ok_s:
            result = ToolResult("degraded", cached["data"], cached["source_ref"], result.latency_ms, attempts, True,
                                result.error_code, f"{cfg.display_name} unavailable; showing data as of "
                                f"{cached['source_ref'].get('as_of', 'earlier')}")

        telemetry.record("connector.call", result.latency_ms, system=system, status=result.status, tool=tool,
                         attempts=attempts, error=result.error_code)
        return result

    async def _attempt(self, cfg, method, path, customer_id, params, body, headers, policy) -> ToolResult:
        hdrs = {"x-service-token": self.service_token, **(headers or {})}
        if customer_id:
            hdrs["x-customer-id"] = customer_id
        seed = chaos_seed.get()
        if seed:
            hdrs["x-chaos-seed"] = seed
        budget = policy.timeout_ms / 1000
        try:
            # httpx timeouts are per socket operation; wait_for enforces the total budget for the call
            resp = await asyncio.wait_for(self.client.request(method, cfg.base_url + path, params=params, json=body,
                                                              headers=hdrs, timeout=budget), budget)
        except (httpx.TimeoutException, asyncio.TimeoutError):
            return ToolResult("unavailable", error_code="timeout",
                              message=f"{cfg.display_name} did not respond within {policy.timeout_ms} ms")
        except httpx.HTTPError as e:
            return ToolResult("unavailable", error_code="unavailable", message=f"{cfg.display_name}: {e}")
        try:
            payload = resp.json()
        except ValueError:
            return ToolResult("unavailable", error_code="malformed", http_status=resp.status_code,
                              message=f"{cfg.display_name} returned an unreadable response")
        if resp.status_code >= 500:
            return ToolResult("unavailable", error_code="unavailable", http_status=resp.status_code,
                              message=payload.get("error", {}).get("message", f"{cfg.display_name} error"))
        if resp.status_code == 409:
            return ToolResult("ok", payload, payload.get("source_ref"), http_status=409)
        if resp.status_code >= 400:
            e = payload.get("error", {})
            return ToolResult("error", None, None, error_code=e.get("code", "error"), http_status=resp.status_code,
                              message=e.get("message", "request failed"))
        return ToolResult("ok", payload, payload.get("source_ref"), http_status=resp.status_code)

    async def gather(self, calls: list, deadline_s: float | None = None) -> list:
        """Run independent awaitables concurrently with an overall deadline; late ones become unavailable."""
        tasks = [asyncio.ensure_future(c) for c in calls]
        done, pending = await asyncio.wait(tasks, timeout=deadline_s)
        for t in pending:
            t.cancel()
        out = []
        for t in tasks:
            if t in done and not t.cancelled() and t.exception() is None:
                out.append(t.result())
            else:
                out.append(ToolResult("unavailable", error_code="deadline"))  # callers word it per system
        return out

    def health(self) -> dict:
        return {name: self.breakers[name].state for name in self.systems}
