"""Orchestrator API (see docs/api-contract.md).

Run: uvicorn orchestrator.app:app --port 8000
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from nsplatform import telemetry
from nsplatform.connector import CallPolicy
from nsplatform.db import get_db
from nsplatform.money import add_months
from nsplatform.packs import ToolContext, match_intents
from nsplatform.runtime import build_platform
from mocks.seed import PERSONAS
from orchestrator.config import BACKEND_DIR, Settings
from orchestrator.llm import LLM, PROVIDERS
from orchestrator.parsing import normalize_speech
from orchestrator.turn import Turn

SESSION_TTL_S = 1800
ACCESS_TTL_S = 3600
TURNS_PER_MINUTE = int(os.environ.get("TURN_RATE_LIMIT", "20"))


class Services:
    def __init__(self, settings: Settings, platform=None):
        self.settings = settings
        self.platform = platform or build_platform(settings.packs_dir, settings.system_urls(), settings.demo_mode)
        self.store = self.platform.store
        self.db = get_db()
        self.llm = None
        if settings.llm_enabled:
            if settings.anthropic_mode not in PROVIDERS:
                raise RuntimeError(f"ANTHROPIC_MODE must be one of {list(PROVIDERS)}")
            provider = PROVIDERS[settings.anthropic_mode]
            self.llm = LLM(provider, settings.api_key(), settings.model_planner, settings.planner_effort,
                           settings.model_failover or None, settings.llm_fallbacks,
                           base_url=settings.abhi_base_url if provider.name == "abhi" else None)
            for warning in self.llm.warnings:
                logging.getLogger("orchestrator").warning(warning)
        self.turns: dict[str, tuple[Turn, asyncio.Task]] = {}


def create_app(settings: Settings | None = None, platform=None) -> FastAPI:
    settings = settings or Settings()
    holder: dict[str, Services] = {}

    @asynccontextmanager
    async def lifespan(_app):
        svc()
        yield
        telemetry.flush()

    app = FastAPI(title="Northstar orchestrator", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                       allow_headers=["*"], allow_credentials=True)

    def svc() -> Services:
        if "svc" not in holder:  # lifespan does not run under every ASGI transport (e.g. in tests)
            holder["svc"] = app.state.services = Services(settings, platform)
        return holder["svc"]

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        code = exc.detail if isinstance(exc.detail, str) and " " not in exc.detail else "error"
        message = exc.detail if code == "error" else code.replace("_", " ")
        return JSONResponse(status_code=exc.status_code,
                            content={"error": {"code": code, "message": message, "retryable": exc.status_code >= 500
                                               or exc.status_code == 429}})

    # ------------------------------------------------------------------ auth
    def issue_token(customer_id: str, name: str) -> str:
        now = int(time.time())
        return jwt.encode({"sub": customer_id, "name": name, "iat": now, "exp": now + ACCESS_TTL_S},
                          settings.jwt_secret, algorithm="HS256")

    def current_customer(authorization: str = Header(default=""), token: str | None = Query(default=None)) -> dict:
        raw = authorization.removeprefix("Bearer ").strip() or token
        if not raw:
            raise HTTPException(401, "auth_required")
        try:
            claims = jwt.decode(raw, settings.jwt_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError as e:
            raise HTTPException(401, "auth_expired") from e
        except jwt.InvalidTokenError as e:
            raise HTTPException(401, "auth_invalid") from e
        return {"customer_id": claims["sub"], "name": claims["name"]}

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/readyz")
    async def readyz():
        s = svc()
        res = await s.platform.gateway.request("crm", "GET", "/healthz", customer_id=None,
                                               policy=CallPolicy(timeout_ms=1000, retries=0))
        return {"ok": res.status == "ok", "llm": "enabled" if s.llm else "fallback",
                "provider": s.llm.provider.name if s.llm else None,
                "model": s.llm.model if s.llm else None, "failover_model": s.llm.failover_model if s.llm else None,
                "warnings": s.llm.warnings if s.llm else [],
                "breakers": s.platform.gateway.health(),
                "packs": {p.name: p.version for p in s.platform.registry.packs.values()}}

    # ------------------------------------------------------------------ model hot-swap (operator, not customer)
    def require_admin(x_admin_token: str = Header(default="")) -> None:
        if not hmac.compare_digest(x_admin_token, settings.admin_token):
            raise HTTPException(401, "admin_token_required")

    @app.get("/v1/admin/model")
    async def get_model(_: None = Depends(require_admin)):
        s = svc()
        if not s.llm:
            raise HTTPException(409, "llm_disabled")
        return s.llm.describe()

    @app.put("/v1/admin/model")
    async def put_model(body: dict, _: None = Depends(require_admin)):
        """Swap the planner model at runtime; turns already running finish on the model they started with."""
        s = svc()
        if not s.llm:
            raise HTTPException(409, "llm_disabled")
        try:
            s.llm.swap(str(body.get("model", "")), body.get("failover_model"))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        telemetry.record("llm.swap", 0, model=s.llm.model, failover=s.llm.failover_model)
        return s.llm.describe()

    @app.get("/v1/personas")
    async def personas():
        return PERSONAS if settings.demo_mode else []

    @app.post("/v1/auth/otp/start")
    async def otp_start(body: dict):
        s = svc()
        phone = "".join(ch for ch in str(body.get("phone", "")) if ch.isdigit())[-10:]
        res = await s.platform.gateway.request("crm", "GET", "/crm/lookup", customer_id=None, params={"phone": phone},
                                               policy=CallPolicy(timeout_ms=1500, retries=1))
        if res.status == "error":
            raise HTTPException(404, "unknown_phone")
        if not res.ok:
            raise HTTPException(503, "crm_unavailable")
        if await s.store.incr(f"otp_rate:{phone}", 900) > 5:
            raise HTTPException(429, "too_many_attempts")
        challenge_id = "otp_" + secrets.token_hex(8)
        code = f"{secrets.randbelow(10**6):06d}"
        digest = hmac.new(settings.jwt_secret.encode(), f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()
        await s.store.set(f"otp:{challenge_id}", {"customer": res.data, "hash": digest, "attempts": 0}, ttl_s=300)
        return {"challenge_id": challenge_id, **({"demo_code": code} if settings.demo_mode else {})}

    @app.post("/v1/auth/otp/verify")
    async def otp_verify(body: dict):
        s = svc()
        challenge = await s.store.get(f"otp:{body.get('challenge_id')}")
        if not challenge:
            raise HTTPException(400, "otp_expired")
        digest = hmac.new(settings.jwt_secret.encode(), f"{body.get('challenge_id')}:{str(body.get('code', '')).strip()}".encode(),
                          hashlib.sha256).hexdigest()
        if not hmac.compare_digest(digest, challenge["hash"]):
            challenge["attempts"] += 1
            if challenge["attempts"] >= 3:
                await s.store.delete(f"otp:{body.get('challenge_id')}")
                raise HTTPException(400, "otp_locked")
            await s.store.set(f"otp:{body.get('challenge_id')}", challenge, ttl_s=300)
            raise HTTPException(400, "otp_invalid")
        await s.store.delete(f"otp:{body.get('challenge_id')}")
        c = challenge["customer"]
        return {"access_token": issue_token(c["customer_id"], c["name"]), "expires_in": ACCESS_TTL_S,
                "customer": {"customer_id": c["customer_id"], "name": c["name"]}}

    # ------------------------------------------------------------------ sessions
    async def discover_products(s: Services, ctx: ToolContext) -> list[dict]:
        products = []
        packs = [p for p in s.platform.registry.packs.values() if p.products]
        outs = await asyncio.gather(*(s.platform.registry.run_tool(p.products["tool"], {}, ctx) for p in packs))
        for pack, out in zip(packs, outs):
            cfg = pack.products
            for item in out.data.get(cfg["list_key"], []) if out.status in ("ok", "degraded") else []:
                if cfg.get("active_field") and item.get(cfg["active_field"]) != cfg.get("active_value"):
                    continue
                products.append({"type": cfg["type"], "id": item[cfg["id_field"]], "label": cfg["label"].format(**item),
                                 "pack": pack.name})
        return products

    async def warm(s: Services, session: dict) -> None:
        """Prefetch so the first questions are answered from cache (spans show the effect)."""
        ctx = ToolContext(s.platform.registry, session["customer_id"], dict(session), settings.today)
        calls = []
        for p in s.platform.registry.packs.values():
            for tool in p.tools.values():
                if tool.prefetch and not tool.required:
                    calls.append(s.platform.registry.run_tool(tool.name, {}, ctx))
            if p.products and p.products.get("warm"):
                for prod in session["products"]:
                    if prod["pack"] == p.name:
                        id_param = p.products["id_field"]
                        calls.append(s.platform.registry.run_tool(p.products["warm"], {id_param: prod["id"]}, ctx))
        with telemetry.span("session.prefetch"):
            await asyncio.gather(*calls, return_exceptions=True)

    async def load_session(s: Services, session_id: str, customer: dict) -> dict:
        session = await s.store.get(f"session:{session_id}")
        if not session or session["customer_id"] != customer["customer_id"]:
            raise HTTPException(404, "session_not_found")
        return session

    async def save_session(s: Services, session: dict) -> None:
        await s.store.set(f"session:{session['session_id']}", session, ttl_s=SESSION_TTL_S)

    @app.post("/v1/sessions")
    async def create_session(customer: dict = Depends(current_customer)):
        s = svc()
        session = {"session_id": "ses_" + secrets.token_hex(8), "customer_id": customer["customer_id"],
                   "customer_name": customer["name"], "products": [], "focus": None, "entities": {}, "history": [],
                   "facts": [], "pending_action": None,
                   "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        ctx = ToolContext(s.platform.registry, customer["customer_id"], session, settings.today)
        session["products"] = await discover_products(s, ctx)
        if len(session["products"]) == 1:
            session["focus"] = session["products"][0]["id"]
        await save_session(s, session)
        index_key = f"customer_sessions:{customer['customer_id']}"
        await s.store.set(index_key, ((await s.store.get(index_key)) or [])[-4:] + [session["session_id"]],
                          ttl_s=SESSION_TTL_S)
        asyncio.create_task(warm(s, session))
        packs = s.platform.registry.active_packs(session["products"])
        suggestions = [x for p in packs for x in p.suggestions][:4]
        return {"session_id": session["session_id"], "customer": customer,
                "products": [{k: v for k, v in p.items() if k != "pack"} for p in session["products"]],
                "suggestions": suggestions}

    @app.post("/v1/sessions/{session_id}/turns")
    async def turn(session_id: str, body: dict, customer: dict = Depends(current_customer)):
        s = svc()
        session = await load_session(s, session_id, customer)
        text = str(body.get("text", "")).strip()
        if not text:
            raise HTTPException(400, "empty_message")
        if len(text) > 2000:
            raise HTTPException(400, "message_too_long")
        if await s.store.incr(f"turn_rate:{customer['customer_id']}:{int(time.time() // 60)}", 70) > TURNS_PER_MINUTE:
            raise HTTPException(429, "rate_limited")
        for tid, (t, task) in list(s.turns.items()):  # one in-flight turn per session: a new one cancels the old
            if t.session["session_id"] == session_id and not task.done():
                task.cancel()
        channel = "voice" if body.get("channel") == "voice" else "text"
        t = Turn(s, session, text, channel)
        task = asyncio.create_task(t.run())
        s.turns[t.turn_id] = (t, task)

        async def stream():
            try:
                while True:
                    item = await t.queue.get()
                    if item is None:
                        break
                    event, data = item
                    yield f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"
            finally:
                if not task.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=30)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        pass
                await save_session(s, t.session)
                s.turns.pop(t.turn_id, None)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/v1/turns/{turn_id}/cancel")
    async def cancel_turn(turn_id: str, body: dict | None = None, customer: dict = Depends(current_customer)):
        s = svc()
        entry = s.turns.get(turn_id)
        if entry and entry[0].session["customer_id"] == customer["customer_id"]:
            t, task = entry
            spoken = (body or {}).get("spoken_text")
            if spoken is not None:
                t.answer = spoken
            telemetry.record("turn.cancel", t._ms(), channel=t.channel)
            task.cancel()
        return {"ok": True}

    @app.post("/v1/sessions/{session_id}/prefetch")
    async def prefetch(session_id: str, body: dict, customer: dict = Depends(current_customer)):
        """Speculative read-only prefetch from an interim voice transcript."""
        s = svc()
        session = await load_session(s, session_id, customer)
        packs = s.platform.registry.active_packs(session["products"])
        intents = [i for i in match_intents(packs, normalize_speech(str(body.get("text", "")))) if i.speculative][:1]
        warmed = []
        for intent in intents:
            spec = s.platform.registry.tools.get(intent.tool)
            if spec and not spec.required:
                key = f"spec:{session_id}:{intent.tool}"
                if await s.store.get(key):
                    continue
                await s.store.set(key, 1, ttl_s=20)
                ctx = ToolContext(s.platform.registry, customer["customer_id"], dict(session), settings.today)
                asyncio.create_task(s.platform.registry.run_tool(intent.tool, {}, ctx))
                warmed.append(intent.tool)
        telemetry.record("voice.speculative_prefetch", 0, tools=warmed)
        return {"warmed": warmed}

    # ------------------------------------------------------------------ actions
    @app.post("/v1/actions/{action_id}/confirm")
    async def confirm(action_id: str, body: dict | None = None, customer: dict = Depends(current_customer)):
        s = svc()
        body = body or {}
        result = await s.platform.executor.confirm(action_id, customer["customer_id"], body.get("otp"),
                                                   body.get("via", "button"))
        await forget_pending(s, body.get("session_id"), customer, action_id, result)
        return result

    @app.post("/v1/actions/{action_id}/cancel")
    async def cancel_action(action_id: str, body: dict | None = None, customer: dict = Depends(current_customer)):
        s = svc()
        result = await s.platform.executor.cancel(action_id, customer["customer_id"])
        await forget_pending(s, (body or {}).get("session_id"), customer, action_id, result)
        return result

    async def forget_pending(s: Services, session_id: str | None, customer: dict, action_id: str, result: dict) -> None:
        if result["status"] == "otp_invalid":
            return
        sessions = [session_id] if session_id else (await s.store.get(f"customer_sessions:{customer['customer_id']}") or [])
        for sid in sessions:
            session = await s.store.get(f"session:{sid}")
            if session and session.get("pending_action", {}) and session["pending_action"].get("action_id") == action_id:
                session["pending_action"] = None
                session.setdefault("facts", []).append(result.get("message", ""))
                await save_session(s, session)

    # ------------------------------------------------------------------ account
    @app.get("/v1/account/overview")
    async def overview(customer: dict = Depends(current_customer)):
        s = svc()
        registry = s.platform.registry
        ctx = ToolContext(registry, customer["customer_id"], {}, settings.today)
        result = {"customer": {"customer_id": customer["customer_id"], "name": customer["name"], "segment": "retail"},
                  "loans": [], "cards": [], "payments": [], "requests": [], "degraded": []}
        hooks = [pack.overview(ctx) for pack in registry.packs.values() if pack.overview]
        partials = await asyncio.gather(*hooks, return_exceptions=True)
        for part in partials:
            if isinstance(part, Exception):
                result["degraded"].append("overview")
                continue
            for key, value in part.items():
                if isinstance(value, list):
                    result[key] = result.get(key, []) + value
                else:
                    result[key] = value
        req = await registry.run_tool("core_service_requests", {}, ctx)
        if req.status in ("ok", "degraded"):
            result["requests"] = [{"request_id": r["request_id"], "type": r["type"], "status": r["status"],
                                   "created_at": r["created_at"], "sla_due": r["sla_due"], "summary": r["summary"]}
                                  for r in req.data.get("requests", [])]
        else:
            result["degraded"].append("Service Operations")
        result["payments"].sort(key=lambda p: p["date"], reverse=True)
        return result

    @app.get("/v1/requests")
    async def requests_list(customer: dict = Depends(current_customer)):
        s = svc()
        ctx = ToolContext(s.platform.registry, customer["customer_id"], {}, settings.today)
        req = await s.platform.registry.run_tool("core_service_requests", {}, ctx)
        if req.status not in ("ok", "degraded"):
            raise HTTPException(503, "ops_unavailable")
        return [{"request_id": r["request_id"], "type": r["type"], "status": r["status"], "created_at": r["created_at"],
                 "sla_due": r["sla_due"], "summary": r["summary"]} for r in req.data.get("requests", [])]

    @app.get("/v1/statements/{request_id}")
    async def statement(request_id: str, customer: dict = Depends(current_customer)):
        s = svc()
        gw = s.platform.gateway
        cfg = gw.systems["ops"]
        resp = await gw.client.get(f"{cfg.base_url}/ops/statements/{request_id}.pdf",
                                   headers={"x-service-token": gw.service_token, "x-customer-id": customer["customer_id"]},
                                   timeout=10)
        if resp.status_code != 200:
            raise HTTPException(resp.status_code if resp.status_code < 500 else 503, "statement_unavailable")
        return Response(resp.content, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{request_id}.pdf"'})

    # ------------------------------------------------------------------ metrics, demo, evals
    @app.get("/v1/metrics/latency")
    async def latency(window: int = 200, customer: dict = Depends(current_customer)):
        db = get_db()
        telemetry.flush()

        def stat(name: str, extra: str = "", params: tuple = ()):
            rows = db.query(f"SELECT duration_ms FROM spans WHERE name=? {extra} ORDER BY id DESC LIMIT ?",
                            (name, *params, window))
            values = [r["duration_ms"] for r in rows]
            return {"count": len(values), "p50_ms": telemetry.percentile(values, 0.5),
                    "p95_ms": telemetry.percentile(values, 0.95)}

        stages = []
        for name, label in [("turn.first_status", "Text: first status"), ("turn.first_token", "First answer token"),
                            ("turn.total", "Turn complete"), ("llm.ttft", "LLM time to first token"),
                            ("llm.call", "LLM call"), ("tool.run", "Tool (composite) run"),
                            ("policy.evaluate", "Policy evaluation"), ("grounding.check", "Grounding check"),
                            ("session.prefetch", "Session prefetch"), ("turn.cancel", "Barge-in cancel (server)")]:
            st = stat(name)
            if st["count"]:
                stages.append({"name": label, **st})
        for channel in ("text", "voice"):
            st = stat("turn.first_token", "AND attrs LIKE ?", (f'%"channel": "{channel}"%',))
            if st["count"]:
                stages.append({"name": f"First answer token ({channel})", **st})
        systems = []
        for row in db.query("SELECT DISTINCT system FROM spans WHERE name='connector.call' AND system IS NOT NULL"):
            rows = db.query("SELECT duration_ms, status FROM spans WHERE name='connector.call' AND system=? "
                            "ORDER BY id DESC LIMIT ?", (row["system"], window))
            live = [r["duration_ms"] for r in rows if r["status"] != "cache_hit"]
            errors = sum(1 for r in rows if r["status"] in ("unavailable", "error"))
            systems.append({"system": svc().platform.gateway.systems[row["system"]].display_name, "count": len(rows),
                            "p50_ms": telemetry.percentile(live, 0.5), "p95_ms": telemetry.percentile(live, 0.95),
                            "error_rate": round(errors / len(rows), 3) if rows else 0,
                            "cache_hit_rate": round(sum(1 for r in rows if r["status"] == "cache_hit") / len(rows), 3)
                            if rows else 0})
        turns = db.query("SELECT turn_id, channel, mode, first_token_ms, total_ms, at FROM turns ORDER BY at DESC LIMIT 50")
        client = []
        for row in db.query("SELECT DISTINCT name FROM client_metrics"):
            values = [r["ms"] for r in db.query("SELECT ms FROM client_metrics WHERE name=? ORDER BY id DESC LIMIT ?",
                                                (row["name"], window))]
            client.append({"name": row["name"], "count": len(values), "p50_ms": telemetry.percentile(values, 0.5),
                           "p95_ms": telemetry.percentile(values, 0.95)})
        llm = []
        for row in db.query("SELECT attrs, duration_ms FROM spans WHERE name='llm.call' ORDER BY id DESC LIMIT ?", (window,)):
            a = json.loads(row["attrs"] or "{}")
            m = next((x for x in llm if x["model"] == a.get("model")), None)
            if m is None:
                m = {"model": a.get("model"), "calls": 0, "cost_usd": 0.0, "durations": []}
                llm.append(m)
            m["calls"] += 1
            m["cost_usd"] += a.get("cost_usd") or 0
            m["durations"].append(row["duration_ms"])
        for m in llm:
            d = m.pop("durations")
            m.update(cost_usd=round(m["cost_usd"], 5), avg_cost_per_call_usd=round(m["cost_usd"] / m["calls"], 6),
                     p50_ms=telemetry.percentile(d, 0.5), p95_ms=telemetry.percentile(d, 0.95))
        return {"stages": stages, "systems": systems, "turns": turns, "client": client, "llm": llm}

    @app.post("/v1/metrics/client")
    async def client_metric(body: dict, customer: dict = Depends(current_customer)):
        name = str(body.get("name", ""))[:64]
        ms = float(body.get("ms", 0))
        if not name or ms < 0 or ms > 120000:
            raise HTTPException(400, "invalid_metric")
        get_db().execute("INSERT INTO client_metrics (name, ms, meta, at) VALUES (?,?,?,?)",
                         (name, ms, json.dumps(body.get("meta") or {}), datetime.now(timezone.utc).isoformat()))
        return {"ok": True}

    async def chaos_call(method: str, body: dict | None = None) -> dict:
        gw = svc().platform.gateway
        resp = await gw.client.request(method, f"{settings.mocks_url}/admin/chaos", json=body,
                                       headers={"x-admin-token": settings.admin_token}, timeout=5)
        if resp.status_code != 200:
            raise HTTPException(400, "invalid_preset")
        return resp.json()

    @app.get("/v1/demo/chaos")
    async def get_chaos(customer: dict = Depends(current_customer)):
        return await chaos_call("GET")

    @app.put("/v1/demo/chaos")
    async def put_chaos(body: dict, customer: dict = Depends(current_customer)):
        if not settings.demo_mode:
            raise HTTPException(403, "demo_mode_off")
        return await chaos_call("PUT", {"preset": body.get("preset", "realistic")})

    @app.get("/v1/evals/latest")
    async def evals_latest(customer: dict = Depends(current_customer)):
        path = BACKEND_DIR / "var" / "evals" / "latest.json"
        return json.loads(path.read_text()) if path.exists() else {}

    return app


app = create_app()
