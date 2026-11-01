"""Credit card servicing pack: the second workflow, built only from platform capabilities.

Reuses the connector gateway, policy engine, clause citations, action executor (tiers, confirmation,
idempotency, audit), session context, voice and the generic card UI. Adds card calculators and rules.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from nsplatform.calculators.loans import CalcResult
from nsplatform.money import D, add_months, fmt_date, inr, to_rupee
from nsplatform.packs import Proposal, ToolContext, ToolOutput


def _record(res) -> list[dict]:
    if not res or not res.source_ref:
        return []
    ref = res.source_ref
    return [{"kind": "record", "system": ref.get("system"), "ref": ref.get("record_id"), "as_of": ref.get("as_of")}]


# --------------------------------------------------------------------------- calculators (pack-local)
def minimum_due(statement: dict, emi_plans: list[dict], excluded: float = 0, pct=5, floor=200) -> CalcResult:
    lines = statement["lines"]
    emi = sum(D(line["amount"]) for line in lines if line["label"].startswith("EMI "))
    fees = sum(D(line["amount"]) for line in lines if "fee" in line["label"].lower() or "gst" in line["label"].lower())
    balance = D(statement["total_due"]) - emi - fees - D(excluded)
    base = max(to_rupee(balance * D(pct) / 100), D(floor))
    mad = to_rupee(base + emi + fees)
    steps = [f"Statement total {inr(statement['total_due'])}; EMI instalments {inr(emi)}; fees and GST {inr(fees)}"
             + (f"; disputed amount excluded {inr(excluded)}" if excluded else "") + ".",
             f"{pct}% of the remaining balance {inr(balance)} = {inr(balance * D(pct) / 100)} (minimum {inr(floor)}).",
             f"Minimum due = {inr(base)} + {inr(emi)} + {inr(fees)} = {inr(mad)}."]
    return CalcResult("card_minimum_due", {"minimum_due": mad, "emi_instalments": emi, "fees": fees,
                                           "revolving_balance": to_rupee(balance)}, steps)


def interest_free_days(purchase_day: date, billing_day: int = 15, due_after: int = 20) -> CalcResult:
    statement = purchase_day.replace(day=billing_day)
    if purchase_day.day > billing_day:
        statement = add_months(statement, 1)
    due = date.fromordinal(statement.toordinal() + due_after)
    days = (due - purchase_day).days
    return CalcResult("interest_free_days", {"days": days, "statement_date": statement, "due_date": due},
                      [f"A purchase on {fmt_date(purchase_day)} is billed on {fmt_date(statement)} and due on "
                       f"{fmt_date(due)}: {days} interest-free days."])


def statement_diff(prev: dict, cur: dict, txns: list[dict]) -> CalcResult:
    prev_lines = {line["label"]: D(line["amount"]) for line in prev["lines"]}
    changes = []
    for line in cur["lines"]:
        before = prev_lines.get(line["label"], D(0))
        changes.append({"label": line["label"], "before": to_rupee(before), "now": to_rupee(line["amount"]),
                        "change": to_rupee(D(line["amount"]) - before)})
    cycle = [t for t in txns if cur["from"] <= t["date"] <= cur["to"] and not t["emi_converted"]]
    largest = sorted(cycle, key=lambda t: -t["amount"])[:3]
    total_change = to_rupee(D(cur["total_due"]) - D(prev["total_due"]))
    steps = [f"Previous statement ({fmt_date(prev['statement_date'])}): {inr(prev['total_due'])}. "
             f"Latest ({fmt_date(cur['statement_date'])}): {inr(cur['total_due'])}. Change {inr(total_change)}."]
    steps += [f"{c['label']}: {inr(c['before'])} → {inr(c['now'])}" for c in changes]
    return CalcResult("statement_diff", {"previous_total": to_rupee(prev["total_due"]), "current_total": to_rupee(cur["total_due"]),
                                         "change": total_change, "lines": changes,
                                         "largest_purchases": [{"txn_id": t["txn_id"], "merchant": t["merchant"],
                                                                "date": t["date"], "amount": t["amount"]} for t in largest]},
                      steps)


# --------------------------------------------------------------------------- helpers
async def resolve_card(ctx: ToolContext, card_id: str | None):
    if not card_id:
        focus = ctx.session.get("focus")
        if focus and focus.startswith("CC-"):
            card_id = focus
        else:
            listing = await ctx.call("cards_list_cards")
            if not listing.ok:
                return None, ToolOutput("unavailable", message=listing.message or "Cards system not responding")
            cards = listing.data["cards"]
            if not cards:
                return None, ToolOutput("error", message="The customer has no credit card.")
            card_id = cards[0]["card_id"]
    listing = await ctx.call("cards_list_cards")
    if not listing.ok:
        return None, ToolOutput("unavailable", message=listing.message or "Cards system not responding")
    card = next((c for c in listing.data["cards"] if c["card_id"] == card_id), None)
    if card is None:
        return None, ToolOutput("error", message=f"No card {card_id} for this customer.")
    return card, None


# --------------------------------------------------------------------------- composite tools
async def card_summary(ctx: ToolContext, card_id: str | None = None) -> ToolOutput:
    card, problem = await resolve_card(ctx, card_id)
    if problem:
        return problem
    stmts, plans = await ctx.call_many([("cards_get_statements", {"card_id": card["card_id"]}),
                                        ("cards_get_emi_plans", {"card_id": card["card_id"]})])
    if not stmts.ok:
        return ToolOutput("unavailable", message=stmts.message)
    latest = stmts.data["statements"][-1]
    rule = ctx.decide("card_minimum_due", {})
    mad = minimum_due(latest, plans.data["emi_plans"] if plans.ok else [], pct=rule.params["pct_of_balance"],
                      floor=rule.params["floor"])
    ifd = interest_free_days(ctx.today, card["billing_day"], card["due_days_after_statement"])
    clauses = await ctx.cite(rule.clause_ids + ["CARD-TNC-4.2"])
    data = {"card_id": card["card_id"], "last4": card["last4"], "limit": card["limit"],
            "statement_total": latest["total_due"], "minimum_due": int(mad.figures["minimum_due"]),
            "due_date": latest["due_date"], "status": latest["status"],
            "interest_free_days_if_bought_today": ifd.figures["days"],
            "summary": (f"Your card statement of {inr(latest['total_due'])} is due on {fmt_date(latest['due_date'])}; "
                        f"the minimum due is {inr(mad.figures['minimum_due'])}. A purchase made today gets "
                        f"{ifd.figures['days']} interest-free days.")}
    sources = _record(stmts) + clauses + [{"kind": "calc", "ref": mad.name, "steps": mad.steps},
                                          {"kind": "calc", "ref": ifd.name, "steps": ifd.steps}]
    card_ui = {"type": "card_summary", "title": f"Card ••{card['last4']}", "subtitle": card["product"],
               "metrics": [{"label": "Statement total", "value": inr(latest["total_due"]), "emphasis": True},
                           {"label": "Minimum due", "value": inr(mad.figures["minimum_due"])},
                           {"label": "Due on", "value": fmt_date(latest["due_date"])},
                           {"label": "Interest-free days today", "value": str(ifd.figures["days"])}],
               "notes": [rule.explanation], "sources": sources}
    return ToolOutput("ok", data, [card_ui], sources, figures={**mad.figures, **ifd.figures}, focus=card["card_id"])


async def explain_statement(ctx: ToolContext, card_id: str | None = None) -> ToolOutput:
    card, problem = await resolve_card(ctx, card_id)
    if problem:
        return problem
    stmts, txns, plans = await ctx.call_many([("cards_get_statements", {"card_id": card["card_id"]}),
                                              ("cards_get_transactions", {"card_id": card["card_id"]}),
                                              ("cards_get_emi_plans", {"card_id": card["card_id"]})])
    if not stmts.ok or not txns.ok:
        return ToolOutput("unavailable", message=(stmts if not stmts.ok else txns).message)
    prev, cur = stmts.data["statements"][-2], stmts.data["statements"][-1]
    diff = statement_diff(prev, cur, txns.data["transactions"])
    f = diff.figures
    plan = (plans.data["emi_plans"] if plans.ok else [None])[0]
    new_lines = [c for c in f["lines"] if c["before"] == 0 and c["now"] > 0 and c["label"] != "Purchases"]
    purchases = next((c for c in f["lines"] if c["label"] == "Purchases"), None)
    ctx.session.setdefault("entities", {})["card_txns"] = [p["txn_id"] for p in f["largest_purchases"]]
    clauses = await ctx.cite(["CARD-TNC-5.1", "CARD-TNC-3.1"])
    reasons = []
    if purchases:
        reasons.append(f"purchases went from {inr(purchases['before'])} to {inr(purchases['now'])}")
    if new_lines:
        reasons.append("new this month: " + ", ".join(f"{c['label']} {inr(c['now'])}" for c in new_lines))
    summary = (f"Your latest statement is {inr(f['current_total'])}, up {inr(f['change'])} from {inr(f['previous_total'])}: "
               + "; ".join(reasons) + ". The largest purchase this cycle was "
               + (f"{f['largest_purchases'][0]['merchant']} for {inr(f['largest_purchases'][0]['amount'])} on "
                  f"{fmt_date(f['largest_purchases'][0]['date'])}." if f["largest_purchases"] else "none."))
    data = {"card_id": card["card_id"], "previous_total": int(f["previous_total"]), "current_total": int(f["current_total"]),
            "change": int(f["change"]), "lines": [{k: (int(v) if isinstance(v, Decimal) else v) for k, v in c.items()}
                                                  for c in f["lines"]],
            "emi_plan": {"principal": plan["principal"], "rate_pct": plan["rate"], "months": plan["months"],
                         "instalment": plan["instalment"]} if plan else None,
            "largest_purchases": f["largest_purchases"], "summary": summary}
    sources = _record(stmts) + _record(txns) + clauses + [{"kind": "calc", "ref": diff.name, "steps": diff.steps}]
    card_ui = {"type": "statement_breakdown", "title": "Why your card statement is higher",
               "subtitle": f"••{card['last4']} · {fmt_date(prev['statement_date'])} vs {fmt_date(cur['statement_date'])}",
               "metrics": [{"label": "Previous", "value": inr(f["previous_total"])},
                           {"label": "Latest", "value": inr(f["current_total"]), "emphasis": True,
                            "delta": f"+{inr(f['change'])}"}],
               "table": {"columns": ["Line", "Previous", "Latest", "Change"],
                         "rows": [[c["label"], inr(c["before"]), inr(c["now"]), inr(c["change"])] for c in f["lines"]],
                         "row_status": ["warn" if c["before"] == 0 and c["now"] > 0 else None for c in f["lines"]]},
               "notes": [f"Largest purchases: " + ", ".join(f"{p['merchant']} {inr(p['amount'])} ({fmt_date(p['date'])})"
                                                           for p in f["largest_purchases"])],
               "actions": [{"label": f"Dispute {p['merchant']} {inr(p['amount'])}",
                            "prompt": f"Dispute the {inr(p['amount'])} charge from {p['merchant']} on {fmt_date(p['date'])}"}
                           for p in f["largest_purchases"][:2]],
               "sources": sources}
    return ToolOutput("ok", data, [card_ui], sources, figures=f, focus=card["card_id"])


# --------------------------------------------------------------------------- action
async def prepare_card_dispute(ctx: ToolContext, reason: str, card_id: str | None = None, txn_id: str | None = None,
                               amount: float | None = None):
    card, problem = await resolve_card(ctx, card_id)
    if problem:
        return problem
    res = await ctx.call("cards_get_transactions", card_id=card["card_id"])
    if not res.ok:
        return ToolOutput("unavailable", message=res.message)
    txns = res.data["transactions"]
    txn = next((t for t in txns if t["txn_id"] == txn_id), None) if txn_id else None
    if txn is None and amount is not None:
        matches = [t for t in txns if abs(t["amount"] - amount) < 1]
        txn = matches[0] if len(matches) == 1 else None
    if txn is None:
        return ToolOutput("error", message="Which transaction? Ask for the amount and merchant, or use explain_statement.")
    stmts = await ctx.call("cards_get_statements", card_id=card["card_id"])
    statement = next((s for s in (stmts.data or {}).get("statements", []) if s["from"] <= txn["date"] <= s["to"]), None)
    days = (ctx.today - date.fromisoformat(statement["statement_date"])).days if statement else 0
    decision = ctx.decide("card_dispute", {"txn": {"days_since_statement": days, "emi_converted": txn["emi_converted"]}})
    if not decision.allowed:
        return ToolOutput("refused", {"allowed": False, "policy": decision.explanation},
                          message=f"Not allowed: {decision.explanation}")
    summary = [{"label": "Card", "value": f"••{card['last4']}"},
               {"label": "Transaction", "value": f"{txn['merchant']} · {fmt_date(txn['date'])}"},
               {"label": "Amount", "value": inr(txn["amount"])}, {"label": "Reason", "value": reason[:120]},
               {"label": "Meanwhile", "value": "Excluded from minimum due"}]
    return Proposal("Card transaction dispute", summary, "card_dispute",
                    {"card_id": card["card_id"], "txn_id": txn["txn_id"], "amount": txn["amount"], "reason": reason},
                    f"Card dispute {inr(txn['amount'])} {txn['merchant']} {txn['date']}",
                    f"To confirm: I'll dispute the {inr(txn['amount'])} charge from {txn['merchant']} on "
                    f"{fmt_date(txn['date'])}. {decision.explanation} Shall I go ahead?")


# --------------------------------------------------------------------------- account panel
async def overview(ctx: ToolContext) -> dict:
    listing = await ctx.call("cards_list_cards")
    if not listing.ok:
        return {"degraded": ["Cards"]}
    out = []
    for card in listing.data["cards"]:
        stmts = await ctx.call("cards_get_statements", card_id=card["card_id"])
        if not stmts.ok:
            continue
        latest = stmts.data["statements"][-1]
        mad = minimum_due(latest, [])
        out.append({"card_id": card["card_id"], "last4": card["last4"], "limit": card["limit"],
                    "outstanding": card["outstanding"], "min_due": int(mad.figures["minimum_due"]),
                    "due_date": latest["due_date"], "statement_total": latest["total_due"]})
    return {"cards": out}
