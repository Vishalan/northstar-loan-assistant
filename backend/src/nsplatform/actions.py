"""Action executor: the only path to a write in an enterprise system.

proposed -> awaiting_confirmation -> (awaiting_otp) -> executing -> succeeded | failed | expired | cancelled

The model can propose an action; it cannot confirm one, change its tier, or alter its parameters after
the customer has seen them (the parameters are frozen under a hash). Writes carry an idempotency key and
are reconciled, never blindly retried, when the outcome is unknown. Every outcome is audited.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from nsplatform.connector import CallPolicy
from nsplatform.money import fmt_date
from nsplatform.packs import Proposal, Registry, ToolContext, ToolOutput, _validate

IST = timezone(timedelta(hours=5, minutes=30))
ACTION_TTL_S = 600
OTP_TTL_S = 300
OTP_MAX_ATTEMPTS = 3


def _hash(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


class ActionExecutor:
    def __init__(self, registry: Registry, store, db, demo_mode: bool = True):
        self.registry = registry
        self.store = store
        self.db = db
        self.demo_mode = demo_mode
        self.otp_secret = os.environ.get("JWT_SECRET", "dev-jwt-secret-change-me-in-production-0123").encode()

    def _otp_hash(self, action_id: str, code: str) -> str:
        return hmac.new(self.otp_secret, f"{action_id}:{code}".encode(), hashlib.sha256).hexdigest()

    async def propose(self, name: str, args: dict, ctx: ToolContext, session_id: str, turn_id: str):
        """Returns (model_output, proposal_event | None, immediate_result | None)."""
        spec = self.registry.actions[name]
        problem = _validate(spec.params, spec.required, args)
        if problem:
            return ToolOutput("error", message=f"invalid arguments: {problem}"), None, None
        prepared = await spec.prepare(ctx, **args)
        if isinstance(prepared, ToolOutput):  # refused by policy, or a system was unavailable
            return prepared, None, None
        assert isinstance(prepared, Proposal)

        action_id = "act_" + secrets.token_hex(6)
        expires = datetime.now(IST) + timedelta(seconds=ACTION_TTL_S)
        pending = {
            "action_id": action_id, "action": name, "tier": spec.tier, "system": spec.system,
            "customer_id": ctx.customer_id, "session_id": session_id, "turn_id": turn_id,
            "request_type": prepared.request_type, "payload": prepared.payload,
            "request_summary": prepared.request_summary, "title": prepared.title, "summary": prepared.summary,
            "spoken": prepared.spoken, "expires_at": expires.isoformat(timespec="seconds"),
            "params_hash": _hash(name, ctx.customer_id, prepared.request_type, prepared.payload),
        }

        if spec.tier == "read":
            result = await self._execute(pending, {"via": "auto", "tier": "read"})
            out = ToolOutput("ok", {"result": result["status"], "request_id": result.get("request_id"),
                                    "message": result["message"]}, prepared.cards, prepared.sources,
                             figures={"request_id": result.get("request_id")})
            return out, None, result

        event = {"action_id": action_id, "action": name, "title": prepared.title, "summary": prepared.summary,
                 "tier": spec.tier, "expires_at": pending["expires_at"]}
        if spec.tier == "confirm_otp":
            code = f"{secrets.randbelow(10**6):06d}"
            pending["otp_hash"] = self._otp_hash(action_id, code)
            pending["otp_attempts"] = 0
            if self.demo_mode:
                event["demo_otp"] = code
        await self.store.set(f"action:{action_id}", pending, ttl_s=ACTION_TTL_S)
        ctx.session["pending_action"] = {k: pending[k] for k in ("action_id", "action", "title", "tier", "expires_at")}

        needs = "confirm on screen or say yes" if spec.tier == "confirm" else \
            "confirm with the one-time password sent to their registered mobile"
        out = ToolOutput("ok", {"result": "awaiting_customer_confirmation", "action_id": action_id,
                                "what_will_be_filed": {row["label"]: row["value"] for row in prepared.summary},
                                "customer_must": needs, "read_back": prepared.spoken},
                         prepared.cards, prepared.sources)
        return out, event, None

    async def confirm(self, action_id: str, customer_id: str, otp: str | None, via: str) -> dict:
        pending = await self.store.get(f"action:{action_id}")
        if pending is None:
            return {"action_id": action_id, "status": "expired",
                    "message": "This request has expired. Ask me again and I'll set it up."}
        if pending["customer_id"] != customer_id:
            return {"action_id": action_id, "status": "failed", "message": "This request belongs to another session."}
        if datetime.fromisoformat(pending["expires_at"]) < datetime.now(IST):
            await self.store.delete(f"action:{action_id}")
            return {"action_id": action_id, "status": "expired", "message": "This request has expired."}
        if pending["params_hash"] != _hash(pending["action"], customer_id, pending["request_type"], pending["payload"]):
            return {"action_id": action_id, "status": "failed", "message": "Request details changed; not filed."}
        if pending["tier"] == "confirm_otp":
            if not otp or not hmac.compare_digest(self._otp_hash(action_id, otp.strip()), pending["otp_hash"]):
                pending["otp_attempts"] += 1
                if pending["otp_attempts"] >= OTP_MAX_ATTEMPTS:
                    await self.store.delete(f"action:{action_id}")
                    self._audit(pending, {"via": via, "otp_verified": False}, "otp_locked", None)
                    return {"action_id": action_id, "status": "failed",
                            "message": "Too many incorrect codes. For your security this request was cancelled."}
                await self.store.set(f"action:{action_id}", pending, ttl_s=ACTION_TTL_S)
                left = OTP_MAX_ATTEMPTS - pending["otp_attempts"]
                return {"action_id": action_id, "status": "otp_invalid",
                        "message": f"That code didn't match. {left} attempt{'s' if left != 1 else ''} left."}
        await self.store.delete(f"action:{action_id}")
        return await self._execute(pending, {"via": via, "otp_verified": pending["tier"] == "confirm_otp"})

    async def cancel(self, action_id: str, customer_id: str) -> dict:
        pending = await self.store.get(f"action:{action_id}")
        if pending and pending["customer_id"] == customer_id:
            await self.store.delete(f"action:{action_id}")
            self._audit(pending, {"via": "customer"}, "cancelled", None)
        return {"action_id": action_id, "status": "cancelled", "message": "Cancelled. Nothing was filed."}

    async def _execute(self, pending: dict, confirmation: dict) -> dict:
        gateway = self.registry.gateway
        key = _hash(pending["session_id"], pending["action"], pending["params_hash"])[:32]
        body = {"customer_id": pending["customer_id"], "type": pending["request_type"], "payload": pending["payload"],
                "summary": pending["request_summary"]}
        res = await gateway.request(pending["system"], "POST", "/ops/requests", customer_id=pending["customer_id"],
                                    body=body, headers={"idempotency-key": key},
                                    policy=CallPolicy(timeout_ms=4000, retries=0, write=True),
                                    tool=pending["action"])
        if res.status == "unavailable":
            # outcome unknown: reconcile by idempotency key instead of re-sending the write
            check = await gateway.request(pending["system"], "GET", "/ops/requests", customer_id=pending["customer_id"],
                                          params={"idempotency_key": key},
                                          policy=CallPolicy(timeout_ms=2000, retries=1), tool="reconcile")
            if check.status == "ok":
                res = check
        if res.status == "ok":
            req = res.data["request"]
            result = {"action_id": pending["action_id"], "status": "succeeded", "request_id": req["request_id"],
                      "sla_due": req["sla_due"], "request_type": req["type"],
                      "message": f"Done. Your {pending['title'].lower()} is filed as {req['request_id']}"
                                 + (". The statement is ready to download." if req["type"] == "statement"
                                    else f" and will be completed by {fmt_date(req['sla_due'])}.")}
        else:
            result = {"action_id": pending["action_id"], "status": "failed", "retryable": res.status == "unavailable",
                      "message": "I couldn't file that right now because Service Operations isn't responding. "
                                 "Nothing was submitted; please try again in a minute."
                      if res.status == "unavailable" else f"The request was not accepted: {res.message}"}
        self._audit(pending, confirmation, result["status"], result.get("request_id"))
        return result

    def _audit(self, pending: dict, confirmation: dict, result: str, request_id: str | None) -> None:
        self.db.audit(at=datetime.now(IST).isoformat(timespec="seconds"), actor="customer",
                      customer_id=pending["customer_id"], session_id=pending["session_id"],
                      turn_id=pending["turn_id"], action=pending["action"], tier=pending["tier"],
                      params_hash=pending["params_hash"], confirmation=confirmation, result=result,
                      request_id=request_id)
