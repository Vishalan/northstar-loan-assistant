"""One conversational turn, for text and voice alike.

A Turn streams typed events (see docs/api-contract.md) through a queue that the SSE response drains.
It plans with the LLM agent loop when available, or with the deterministic intent planner otherwise
(also the fallback when the LLM fails). Tools and actions run through the platform; every number in
the reply is checked against tool outputs before the answer is marked verified.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
from datetime import datetime, timezone

import anthropic

from nsplatform import telemetry
from nsplatform.money import fmt_date
from nsplatform.packs import ToolContext, ToolOutput, match_intents, plan_intents, tool_label
from orchestrator import grounding
from orchestrator.parsing import is_affirmative, normalize_speech, parse_amount, parse_mode, parse_txn
from orchestrator.llm import cost_usd, is_retryable, same_model
from orchestrator.prompts import VOICE, system_prompt

# A reply that only announces a lookup ("Let me check…", "I'll look into your foreclosure options")
PROMISE = re.compile(r"\b(let me|i'?ll|i will|i'?m going to|i am going to|allow me to|give me a (moment|second))\b"
                     r".{0,40}\b(check|look|pull|find|calculate|work out|see|review|fetch|get)\b", re.I)

HELP = ("I can explain changes to your EMI, work out what a prepayment would save, check failed or recent "
        "payments, tell you whether you can foreclose, raise a dispute or a prepayment request, and send you a "
        "statement. What would you like to do?")


class Turn:
    def __init__(self, svc, session: dict, text: str, channel: str):
        self.svc = svc
        self.session = session
        self.text = text.strip()
        self.channel = channel
        self.turn_id = "turn_" + secrets.token_hex(6)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.seq = 0
        self.t0 = time.perf_counter()
        self.first_status_ms: float | None = None
        self.first_token_ms: float | None = None
        self.llm_ms = 0.0
        self.tools_ms = 0.0
        self.answer = ""
        self.voice_buffer = ""
        self.voice_blocked = False
        self.outputs: list[tuple[str, ToolOutput]] = []
        self.mode = "llm" if svc.llm else "fallback"
        self.model = svc.llm.model if svc.llm else None  # pinned for the turn; a runtime swap applies to the next one
        self.cost_usd = 0.0
        self.served_model: str | None = None  # what the endpoint says actually answered
        self.status = "running"
        self.ctx = ToolContext(svc.platform.registry, session["customer_id"], session, svc.settings.today)

    # ------------------------------------------------------------------ events
    def _ms(self) -> float:
        return round((time.perf_counter() - self.t0) * 1000, 1)

    async def emit(self, event: str, **data) -> None:
        self.seq += 1
        if event in ("status", "tool.started") and self.first_status_ms is None:
            self.first_status_ms = self._ms()
        await self.queue.put((event, {"turn_id": self.turn_id, "seq": self.seq,
                                      "ts": int(time.time() * 1000), **data}))

    async def _emit_text(self, text: str) -> None:
        if not text:
            return
        if self.first_token_ms is None:
            self.first_token_ms = self._ms()
        self.answer += text
        await self.emit("answer.delta", text=text)

    async def on_model_text(self, delta: str) -> None:
        """Text streams straight through; voice is released sentence by sentence after a number check."""
        if self.channel != "voice":
            await self._emit_text(delta)
            return
        if self.voice_blocked:
            return
        self.voice_buffer += delta
        sentences, self.voice_buffer = grounding.split_sentences(self.voice_buffer)
        for sentence in sentences:
            if not await self._release_sentence(sentence):
                return

    async def _release_sentence(self, sentence: str) -> bool:
        bad = grounding.unsupported(sentence, self.allowed_numbers())
        if bad:
            self.voice_blocked = True
            telemetry.record("grounding.voice_block", 0, status="blocked", numbers=bad)
            return False
        await self._emit_text(sentence.strip() + " ")
        return True

    # ------------------------------------------------------------------ lifecycle
    async def run(self) -> None:
        telemetry.current_trace.set(self.turn_id)
        await self.emit("turn.started", session_id=self.session["session_id"], channel=self.channel)
        await self.emit("status", text="Looking into it…")
        try:
            if self.svc.llm:
                try:
                    await self.run_llm()
                except (anthropic.APIError, asyncio.TimeoutError) as e:
                    telemetry.record("llm.error", 0, status="error", error=type(e).__name__, model=self.model)
                    llm = self.svc.llm
                    nothing_done = not self.answer and not self.outputs  # safe to rerun: no tool or action ran
                    if llm.disable_server_fallbacks_if(e):
                        await self.run_llm()
                    elif nothing_done and llm.failover_model and is_retryable(e):
                        telemetry.record("llm.failover", 0, status="failover", frm=self.model, to=llm.failover_model)
                        self.model = llm.failover_model
                        try:
                            await self.run_llm()
                        except (anthropic.APIError, asyncio.TimeoutError):
                            await self._planner_fallback()
                    else:
                        await self._planner_fallback()
            else:
                if self.svc.settings.llm_mode == "stub":  # load tests: model-like latency, no API spend
                    self.mode = "stub"
                    await asyncio.sleep(0.4)  # time to first token of a planning call
                    self.llm_ms += 400
                await self.run_fallback()
                if self.svc.settings.llm_mode == "stub":
                    await asyncio.sleep(0.6)  # composing call after the tool round
                    self.llm_ms += 600
            await self.finish()
            self.status = "completed"
        except asyncio.CancelledError:
            self.status = "cancelled"
            await self.emit("turn.error", code="cancelled", message="Turn cancelled", retryable=False)
            self.save(interrupted=True)
            raise
        except Exception as e:  # never leave the client hanging
            self.status = "error"
            telemetry.record("turn.error", self._ms(), status="error", error=repr(e))
            await self.emit("turn.error", code="internal", message="Something went wrong on our side.", retryable=True)
        finally:
            await self.queue.put(None)
            telemetry.flush()

    async def _planner_fallback(self) -> None:
        """The model is unavailable: answer with the deterministic planner, or from tool results already in hand."""
        if not self.answer and not self.outputs:
            self.mode = "fallback"
            await self.run_fallback()
        else:
            await self._emit_text(" (I lost my connection while answering; here is what I found.) " + self.template_answer())

    async def finish(self) -> None:
        if self.channel == "voice" and self.voice_buffer.strip() and not self.voice_blocked:
            await self._release_sentence(self.voice_buffer)
            self.voice_buffer = ""
        with telemetry.span("grounding.check"):
            bad = grounding.unsupported(self.answer, self.allowed_numbers())
        if self.channel == "voice" and self.voice_blocked:
            replacement = self.template_answer()
            await self._emit_text(replacement)
            await self.emit("answer.verified", ok=False, replaced_text=self.answer)
        elif bad:
            replacement = await self.rewrite(bad)
            self.answer = replacement
            await self.emit("answer.verified", ok=False, replaced_text=replacement)
        else:
            await self.emit("answer.verified", ok=True)
        await self.emit("suggestions", chips=self.suggestions())
        total = self._ms()
        timings = {"first_status_ms": self.first_status_ms, "first_token_ms": self.first_token_ms,
                   "total_ms": total, "llm_ms": round(self.llm_ms, 1), "tools_ms": round(self.tools_ms, 1)}
        telemetry.record("turn.total", total, channel=self.channel, mode=self.mode)
        if self.first_status_ms is not None:
            telemetry.record("turn.first_status", self.first_status_ms, channel=self.channel)
        if self.first_token_ms is not None:
            telemetry.record("turn.first_token", self.first_token_ms, channel=self.channel, mode=self.mode)
        self.save()
        await self.emit("turn.completed", timings=timings, mode=self.mode, model=self.model if self.mode == "llm" else None,
                        served_model=self.served_model if self.mode == "llm" else None,
                        cost_usd=round(self.cost_usd, 6))

    def save(self, interrupted: bool = False) -> None:
        history = self.session.setdefault("history", [])
        history.append({"user": self.text, "assistant": self.answer.strip() or "(no answer)",
                        "tools": [n for n, _ in self.outputs], "interrupted": interrupted, "channel": self.channel})
        del history[:-8]
        facts = self.session.setdefault("facts", [])
        for _, out in self.outputs:
            if out.data.get("summary"):
                facts.append(out.data["summary"])
        del facts[:-10]
        self.svc.db.save_turn(
            (self.turn_id, self.session["session_id"], self.session["customer_id"], self.channel, self.mode,
             self.text, self.answer, json.dumps([n for n, _ in self.outputs]),
             "interrupted" if interrupted else self.status, self.first_status_ms, self.first_token_ms, self._ms(),
             datetime.now(timezone.utc).isoformat(timespec="seconds")))

    # ------------------------------------------------------------------ tools
    async def call_tool(self, name: str, args: dict) -> ToolOutput:
        registry = self.svc.platform.registry
        call_id = "call_" + secrets.token_hex(4)
        label = tool_label(registry, name)
        system = registry.tools[name].system if name in registry.tools else "ops"
        await self.emit("tool.started", call_id=call_id, tool=name, system=system, label=label)
        await self.emit("status", text=label + "…")
        started = time.perf_counter()
        if name in registry.actions:
            out, proposal, result = await self.svc.platform.executor.propose(
                name, args, self.ctx, self.session["session_id"], self.turn_id)
            if proposal:
                await self.emit("action.proposed", **proposal)
            if result:
                out.cards.append(action_result_card(result))
        elif name in registry.tools:
            out = await registry.run_tool(name, args, self.ctx)
        else:
            out = ToolOutput("error", message=f"unknown tool {name}")
        elapsed = (time.perf_counter() - started) * 1000
        self.tools_ms += elapsed
        await self.emit("tool.finished", call_id=call_id, tool=name, status=out.status if out.status in
                        ("ok", "degraded", "unavailable") else ("ok" if out.status == "refused" else "unavailable"),
                        latency_ms=round(elapsed, 1), from_cache=out.from_cache)
        for card in out.cards:
            await self.emit("card", **card)
        if out.focus and out.focus != self.session.get("focus"):
            self.session["focus"] = out.focus
            await self.emit("focus", product_id=out.focus)
        self.outputs.append((name, out))
        return out

    def allowed_numbers(self):
        objects = [self.text, str(self.svc.settings.today.year), self.session.get("facts", []),
                   [p["id"] for p in self.session.get("products", [])],
                   self.session.get("pending_action") or {},
                   [h.get("user", "") for h in self.session.get("history", [])]]
        for _, out in self.outputs:
            objects += [out.for_model(), out.cards, out.figures]
        return grounding.collect_allowed(*objects)

    def template_answer(self) -> str:
        parts = []
        for _, out in self.outputs:
            text = out.data.get("summary") or out.data.get("read_back") or out.data.get("message") or out.message
            if text:
                parts.append(text)
        return " ".join(parts) or "I couldn't confirm the figures for that, so I won't guess. Could you ask again?"

    async def rewrite(self, bad: list[str]) -> str:
        """Regenerate once with the unsupported figures named; fall back to the deterministic template."""
        if self.svc.llm:
            try:
                evidence = json.dumps([{"tool": n, "result": o.for_model()} for n, o in self.outputs], default=str)
                text = await self.svc.llm.complete(
                    system=[{"type": "text", "text": "Rewrite the assistant's answer so that every number in it appears "
                             "in the tool results. Keep it short and in the same voice. Output only the answer."}],
                    messages=[{"role": "user", "content": f"Tool results: {evidence}\n\nAnswer: {self.answer}\n\n"
                               f"These figures do not appear in the tool results: {', '.join(bad)}"}])
                if text and not grounding.unsupported(text, self.allowed_numbers()):
                    telemetry.record("grounding.rewrite", 0, status="ok")
                    return text
            except anthropic.APIError:
                pass
        telemetry.record("grounding.fallback", 0, status="template", numbers=bad)
        return self.template_answer()

    def suggestions(self) -> list[str]:
        asked = {h["user"].lower() for h in self.session.get("history", [])} | {self.text.lower()}
        chips = []
        for _, out in self.outputs:
            for card in out.cards:
                for a in card.get("actions", []):
                    chips.append(a["prompt"])
        packs = self.svc.platform.registry.active_packs(self.session["products"])
        for pack in packs:
            chips += pack.suggestions
        # skip chips that would re-run something already answered, however it was phrased
        used = {t for h in self.session.get("history", []) for t in h.get("tools", [])} | {n for n, _ in self.outputs}
        seen, result = set(), []
        for c in chips:
            intents = match_intents(packs, c)
            if intents and intents[0].tool in used:
                continue
            if c.lower() not in asked and c not in seen:
                seen.add(c)
                result.append(c)
        return result[:3]

    # ------------------------------------------------------------------ LLM planner
    def _context_block(self) -> str:
        s = self.session
        lines = [f"Customer: {s['customer_name']} (authenticated)", f"Today: {fmt_date(self.svc.settings.today)}",
                 f"Channel: {self.channel}",
                 "Products: " + "; ".join(f"{p['type']} {p['id']} ({p['label']})" for p in s["products"]),
                 f"In focus: {s.get('focus') or 'none'}"]
        entities = s.get("entities") or {}
        if entities:
            lines.append("Mentioned earlier: " + ", ".join(f"{k}={v}" for k, v in entities.items()))
        if s.get("pending_action"):
            p = s["pending_action"]
            lines.append(f"Awaiting customer confirmation: {p['title']} ({p['action_id']}), expires {p['expires_at']}")
        if s.get("history") and s["history"][-1].get("interrupted"):
            lines.append(f"The customer interrupted your previous answer after: \"{s['history'][-1]['assistant'][:300]}\"")
        if s.get("facts"):
            lines.append("Established earlier: " + " | ".join(s["facts"][-4:]))
        return "<session_context>\n" + "\n".join(lines) + "\n</session_context>"

    def _messages(self) -> list[dict]:
        messages = []
        for h in self.session.get("history", [])[-6:]:
            messages.append({"role": "user", "content": h["user"]})
            reply = h["assistant"] + (" [interrupted by the customer]" if h.get("interrupted") else "")
            messages.append({"role": "assistant", "content": reply})
        content = self._context_block() + "\n\n" + self.text
        if self.channel == "voice":
            content += "\n\n" + VOICE
        messages.append({"role": "user", "content": content})
        return messages

    async def run_llm(self) -> None:
        registry = self.svc.platform.registry
        packs = registry.active_packs(self.session["products"])
        system = [{"type": "text", "text": system_prompt([p.prompt for p in packs]), "cache_control": {"type": "ephemeral"}}]
        tools = [{**d, "eager_input_streaming": True} for d in registry.definitions(packs)]
        messages = self._messages()
        nudged = False
        for round_no in range(self.svc.settings.max_tool_rounds + 1):
            last_round = round_no == self.svc.settings.max_tool_rounds
            started = time.perf_counter()
            first_delta_at = None
            async with self.svc.llm.stream(model=self.model, system=system, tools=tools, messages=messages,
                                           tool_choice={"type": "none"} if last_round else None) as stream:
                async for event in stream:
                    if event.type == "text":
                        if first_delta_at is None:
                            first_delta_at = time.perf_counter()
                            telemetry.record("llm.ttft", (first_delta_at - started) * 1000, round=round_no, model=self.model)
                        await self.on_model_text(event.text)
                final = await stream.get_final_message()
            elapsed = (time.perf_counter() - started) * 1000
            self.llm_ms += elapsed
            usage = final.usage
            self.served_model = getattr(final, "model", None) or self.model
            if not same_model(self.model, self.served_model):
                telemetry.record("llm.model_substituted", 0, status="warning", asked=self.model, served=self.served_model)
            call_cost = cost_usd(self.model, usage)
            self.cost_usd += call_cost
            telemetry.record("llm.call", elapsed, round=round_no, model=self.model, served=self.served_model, cost_usd=call_cost,
                             input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                             cache_read=getattr(usage, "cache_read_input_tokens", 0))
            if final.stop_reason == "refusal":
                await self._emit_text("I'm not able to help with that here. I can hand you to a customer care agent if you like.")
                return
            tool_uses = [b for b in final.content if b.type == "tool_use"]
            messages.append({"role": "assistant", "content": final.content})
            if not tool_uses:
                said = "".join(b.text for b in final.content if b.type == "text")
                if not self.outputs and PROMISE.search(said) and not last_round:
                    # The model announced a lookup but did not make it: hold it to its word once.
                    if not nudged:
                        nudged = True
                        telemetry.record("llm.promise_without_tool", 0, status="nudged", model=self.model)
                        messages.append({"role": "user", "content": "You said you would check, but you did not call "
                                         "a tool. Call the right tool now, then answer."})
                        continue
                    # Still nothing: answer with the deterministic planner rather than leave the customer waiting.
                    telemetry.record("llm.promise_without_tool", 0, status="planner", model=self.model)
                    await self.run_fallback()
                return
            if final.stop_reason == "max_tokens":
                await self._emit_text(self.template_answer())
                return
            if self.answer and not self.answer.endswith((" ", "\n")):
                await self._emit_text("\n\n")
            outputs = await asyncio.gather(*(self.call_tool(b.name, b.input if isinstance(b.input, dict) else {})
                                             for b in tool_uses))
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": b.id, "is_error": out.status == "error",
                 "content": json.dumps(out.for_model(), default=str)} for b, out in zip(tool_uses, outputs)]})

    # ------------------------------------------------------------------ deterministic planner
    def _resolve_args(self, spec_args: dict) -> dict:
        entities = self.session.setdefault("entities", {})
        args = {}
        for key, ref in spec_args.items():
            if ref == "$amount":
                value = parse_amount(self.text) or entities.get("amount")
            elif ref == "$mode":
                value = parse_mode(self.text) or ("reduce_tenure" if re.search(r"tenure", self.text, re.I) else None)
            elif ref == "$last_txn":
                value = parse_txn(self.text) or entities.get("last_txn")
            elif ref == "$text":
                value = self.text
            else:
                value = ref
            if value is not None:
                args[key] = value
        if "amount" in args:
            entities["amount"] = args["amount"]
        return args

    async def _speak(self, text: str) -> None:
        sentences, rest = grounding.split_sentences(text)
        for s in sentences + ([rest] if rest.strip() else []):
            await self._emit_text(s.strip() + " ")
            await asyncio.sleep(0)

    async def run_fallback(self) -> None:
        registry = self.svc.platform.registry
        pending = self.session.get("pending_action")
        if pending and is_affirmative(self.text):
            await self._speak("Please confirm with the button on your screen"
                              + (" and enter the one-time password." if pending["tier"] == "confirm_otp" else "."))
            return
        packs = registry.active_packs(self.session["products"])
        heard = normalize_speech(self.text)
        intents = plan_intents(packs, heard, set(registry.tools))
        if not intents:
            declined = any(i.tool in registry.actions for i in match_intents(packs, heard))
            await self._speak("Okay, I won't file anything. " + HELP if declined else HELP)
            return
        runnable, ask = [], None
        for intent in intents:
            args = self._resolve_args(intent.args)
            target = registry.tools.get(intent.tool) or registry.actions.get(intent.tool)
            missing = [r for r in target.required if r not in args]
            if not missing:
                runnable.append((intent, args))
            elif ask is None:
                ask = ("How much would you like to pay towards the loan?" if missing == ["amount"] else
                       "Would you prefer to keep your EMI and finish sooner, or keep the tenure and lower your EMI?"
                       if missing == ["mode"] else "I need a little more detail for that. " + HELP)
        # several read-only questions in one message run in parallel and are answered in the order asked about
        outs = await asyncio.gather(*(self.call_tool(i.tool, a) for i, a in runnable))
        parts = [self._fallback_text(out) for out in outs]
        if ask:
            parts.append(ask)
        await self._speak(" ".join(p for p in parts if p))

    def _fallback_text(self, out: ToolOutput) -> str:
        if out.status in ("ok", "degraded"):
            text = out.data.get("summary") or out.data.get("read_back") or out.data.get("message") or ""
            if out.data.get("result") == "awaiting_customer_confirmation":
                text = out.data["read_back"]
                if self.channel == "text":  # read-backs are written for voice; on screen the customer types the code
                    text = text.replace("Please read out the six-digit code", "Please enter the six-digit code") \
                               .replace("Shall I go ahead?", "Confirm on screen to file it.")
            if out.status == "degraded" and out.message:
                text += f" Note: {out.message}"
            return text or "Done."
        if out.status == "refused":
            return out.data.get("policy") or out.message or "That isn't possible on this account."
        return (out.message or "That system isn't responding").rstrip(".") + \
            ". I can try again in a moment, or raise a ticket for you."


def action_result_card(result: dict) -> dict:
    ok = result["status"] == "succeeded"
    metrics = [{"label": "Status", "value": "Done" if ok else "Not filed", "emphasis": True}]
    if result.get("request_id"):
        metrics.append({"label": "Request", "value": result["request_id"]})
    notes = [result["message"]]
    if result.get("request_type") == "statement":
        notes.append("Download it from the Requests page.")
    return {"type": "action_result", "title": "Request filed" if ok else "Request not filed", "metrics": metrics,
            "notes": notes, "sources": [{"kind": "record", "system": "Service Operations",
                                         "ref": f"requests/{result.get('request_id')}", "as_of": None}] if ok else []}
