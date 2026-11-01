"""Spans for every hop: turn, plan, tool calls, connector calls, calculators, grounding.

Spans are buffered and flushed to the `spans` table, which feeds the /latency page and the
benchmark exports. Names follow OpenTelemetry style (`connector.call`, `llm.first_token`).
"""

from __future__ import annotations

import contextvars
import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from nsplatform.db import get_db

current_trace: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_trace", default=None)
_buffer: list[tuple] = []


def record(name: str, duration_ms: float, *, system: str | None = None, status: str = "ok", **attrs) -> None:
    _buffer.append((current_trace.get(), name, system, status, round(duration_ms, 2),
                    json.dumps(attrs, default=str) if attrs else None,
                    datetime.now(timezone.utc).isoformat(timespec="milliseconds")))
    if len(_buffer) >= 50:
        flush()


def flush() -> None:
    if not _buffer:
        return
    rows = _buffer[:]
    _buffer.clear()
    get_db().executemany("INSERT INTO spans (trace_id, name, system, status, duration_ms, attrs, at) "
                         "VALUES (?,?,?,?,?,?,?)", rows)


@contextmanager
def span(name: str, *, system: str | None = None, **attrs):
    start = time.perf_counter()
    state = {"status": "ok"}
    try:
        yield state
    except Exception:
        state["status"] = "error"
        raise
    finally:
        record(name, (time.perf_counter() - start) * 1000, system=system, status=state["status"], **attrs)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 1)
