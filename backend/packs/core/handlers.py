"""Core pack: capabilities every workflow shares (policy search, escalation)."""

from __future__ import annotations

from nsplatform.connector import CallPolicy
from nsplatform.packs import Proposal, ToolContext, ToolOutput


async def policy_search(ctx: ToolContext, query: str) -> ToolOutput:
    res = await ctx.registry.gateway.request(
        "policy", "POST", "/policy/clauses/search", customer_id=ctx.customer_id, body={"query": query, "k": 3},
        policy=CallPolicy(timeout_ms=600, retries=1, cache_s=600), tool="core_policy_search")
    if not res.ok:
        return ToolOutput("unavailable", message="Policy Knowledge is not responding")
    clauses = res.data["clauses"]
    return ToolOutput("ok", {"general_policy_only": True,
                             "clauses": [{"clause_id": c["clause_id"], "section": c["section"], "text": c["text"]}
                                         for c in clauses]},
                      sources=[{"kind": "policy", "ref": c["clause_id"], "text": c["text"]} for c in clauses])


async def prepare_escalation(ctx: ToolContext, reason: str):
    summary = [{"label": "Hand-off", "value": "Customer care agent"}, {"label": "Issue", "value": reason[:140]},
               {"label": "Expected contact", "value": "Within 1 working day"}]
    return Proposal("Hand-off to an agent", summary, "escalation", {"reason": reason},
                    f"AI assistant hand-off: {reason[:200]}",
                    "I can hand this to a customer care agent with a summary of our conversation. Shall I?")
