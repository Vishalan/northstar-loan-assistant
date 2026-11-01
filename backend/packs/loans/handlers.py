"""Loan servicing pack: composite tools and action preparers.

Each composite fetches what it needs through the connector (in parallel where independent), asks the
policy engine for the decision, runs a calculator, and returns: compact data for the model, a card for
the screen, and sources (records, clauses, calculation steps) so every figure is traceable.
"""

from __future__ import annotations

from datetime import date, timedelta

from nsplatform.calculators.loans import (explain_emi_change as calc_emi_change, failed_payment_summary,
                                          foreclosure_quote, prepayment_savings)
from nsplatform.money import add_months, fmt_date, inr, months_between, pct
from nsplatform.packs import Proposal, ToolContext, ToolOutput

FAILURE_TEXT = {
    "INSUFFICIENT_FUNDS": "the bank declined the debit because the account balance was insufficient",
    "MANDATE_EXPIRED": "the auto-debit mandate had expired, so the debit could not be presented",
    "ACCOUNT_CLOSED": "the linked bank account was closed",
    "TECHNICAL": "a technical error at the bank",
}


def _record(res) -> list[dict]:
    if not res or not res.source_ref:
        return []
    ref = res.source_ref
    return [{"kind": "record", "system": ref.get("system"), "ref": ref.get("record_id"), "as_of": ref.get("as_of")}]


def _calc_source(calc) -> dict:
    return {"kind": "calc", "ref": calc.name, "steps": calc.steps}


def _unavailable(res, what: str) -> ToolOutput:
    return ToolOutput("unavailable", message=res.message or f"{what} is not responding right now")


async def resolve_loan(ctx: ToolContext, loan_id: str | None):
    """Pick the loan: explicit id, else the loan in focus, else the customer's only loan."""
    if not loan_id:
        focus = ctx.session.get("focus")
        if focus and focus.startswith("PL-"):
            loan_id = focus
        else:
            listing = await ctx.call("loans_list_loans")
            if not listing.ok:
                return None, None, _unavailable(listing, "Loan Management")
            loans = [loan for loan in listing.data["loans"] if loan["status"] == "active"]
            if not loans:
                return None, None, ToolOutput("error", message="The customer has no active loans.")
            if len(loans) > 1:
                return None, None, ToolOutput("error", {"loans": [{"loan_id": loan["loan_id"],
                                                                    "product": loan["product_name"]} for loan in loans]},
                                              message="Several loans: ask the customer which one they mean.")
            loan_id = loans[0]["loan_id"]
    res = await ctx.call("loans_get_loan", loan_id=loan_id)
    if res.status == "error":
        return None, None, ToolOutput("error", message=f"No loan {loan_id} was found for this customer.")
    if not res.ok:
        return None, None, _unavailable(res, "Loan Management")
    return res.data["loan"], res, None


def loan_facts(loan: dict, today: date, amount=None) -> dict:
    return {"product": {"rate_type": loan["rate_type"], "code": loan["product_code"]},
            "loan": {"months_since_disbursal": months_between(date.fromisoformat(loan["disbursed_on"]), today),
                     "lock_in_until": fmt_date(loan["lock_in_until"]) if loan.get("lock_in_until") else None,
                     "lock_in_until_iso": loan.get("lock_in_until"), "prepayments_this_fy": 0,
                     "outstanding": loan["outstanding_principal"]},
            "request": {"amount": amount}}


# --------------------------------------------------------------------------- composite tools
async def loan_overview(ctx: ToolContext, loan_id: str | None = None) -> ToolOutput:
    loan, loan_res, problem = await resolve_loan(ctx, loan_id)
    if problem:
        return problem
    since = (ctx.today - timedelta(days=62)).isoformat()
    sched, txns = await ctx.call_many([("loans_get_schedule", {"loan_id": loan["loan_id"]}),
                                       ("loans_get_transactions", {"loan_id": loan["loan_id"], "since": since})])
    next_row = sched.data["upcoming"][0] if sched.ok and sched.data.get("upcoming") else None
    last = None
    if txns.ok:
        done = [t for t in txns.data["transactions"]]
        last = done[0] if done else None
    data = {"loan_id": loan["loan_id"], "product": loan["product_name"], "rate_type": loan["rate_type"],
            "current_rate_pct": loan["current_rate"], "emi": loan["emi"],
            "outstanding_principal": round(loan["outstanding_principal"]),
            "next_due_date": loan["next_due_date"], "tenure_left_months": loan["tenure_left_months"],
            "last_emi_date": add_months(date.fromisoformat(loan["next_due_date"]),
                                        loan["tenure_left_months"] - 1).isoformat() if loan["next_due_date"] else None}
    if next_row:
        data["next_emi_split"] = {"interest": round(next_row["interest"]), "principal": round(next_row["principal"])}
    if last:
        data["last_payment"] = {"txn_id": last["txn_id"], "date": last["attempted_at"][:10], "amount": last["amount"],
                                "status": last["status"], "channel": last["channel"],
                                "failure_reason": FAILURE_TEXT.get(last["failure_code"]) if last["failure_code"] else None}
    elif not txns.ok:
        data["last_payment"] = "unavailable: Payments system not responding"
    summary = (f"Your next EMI of {inr(loan['emi'])} is due on {fmt_date(loan['next_due_date'])}. "
               f"Outstanding principal is {inr(loan['outstanding_principal'])} at {pct(loan['current_rate'])}, "
               f"with {loan['tenure_left_months']} EMIs left"
               + (f"; the last one is due on {fmt_date(data['last_emi_date'])}." if data.get("last_emi_date") else "."))
    if last:
        summary += (f" Your last payment of {inr(last['amount'])} on {fmt_date(last['attempted_at'])} "
                    f"{'went through' if last['status'] == 'success' else 'failed'}"
                    f"{' via ' + last['channel'] if last['status'] == 'success' else ''}.")
    data["summary"] = summary
    metrics = [{"label": "Next EMI", "value": inr(loan["emi"]), "emphasis": True},
               {"label": "Due on", "value": fmt_date(loan["next_due_date"])},
               {"label": "Outstanding", "value": inr(loan["outstanding_principal"])},
               {"label": "Rate", "value": f"{pct(loan['current_rate'])} {loan['rate_type']}"},
               {"label": "EMIs left", "value": str(loan["tenure_left_months"])}]
    if data.get("last_emi_date"):
        metrics.append({"label": "Last EMI", "value": fmt_date(data["last_emi_date"])})
    if last:
        metrics.append({"label": "Last payment", "value": f"{inr(last['amount'])} · {fmt_date(last['attempted_at'])} · "
                                                         f"{'paid' if last['status'] == 'success' else 'failed'}"})
    sources = _record(loan_res) + _record(sched if sched.ok else None) + _record(txns if txns.ok else None)
    card = {"type": "loan_summary", "title": "Your loan", "subtitle": f"{loan['product_name']} · {loan['loan_id']}",
            "metrics": metrics, "sources": sources}
    if next_row:
        card["notes"] = [f"Of your next EMI, {inr(next_row['interest'])} is interest and {inr(next_row['principal'])} "
                         f"reduces the principal."]
    status = "ok" if txns.ok else "degraded"
    return ToolOutput(status, data, [card], sources, focus=loan["loan_id"],
                      message=None if txns.ok else "Payments did not respond; last payment not shown.",
                      from_cache=loan_res.from_cache)


async def explain_emi_change(ctx: ToolContext, loan_id: str | None = None) -> ToolOutput:
    loan, loan_res, problem = await resolve_loan(ctx, loan_id)
    if problem:
        return problem
    hist_res, sched_res = await ctx.call_many([("loans_get_rate_history", {"loan_id": loan["loan_id"]}),
                                               ("loans_get_schedule", {"loan_id": loan["loan_id"]})])
    if not hist_res.ok:
        return _unavailable(hist_res, "Loan Management")
    history = [h for h in hist_res.data["rate_history"] if h["effective_from"] <= ctx.today.isoformat()]
    decision = ctx.decide("rate_reset", loan_facts(loan, ctx.today))
    clauses = await ctx.cite(decision.clause_ids)
    paid = sched_res.data["paid"] if sched_res.ok else []
    if len(history) < 2:
        data = {"loan_id": loan["loan_id"], "emi_changed": False, "emi": loan["emi"],
                "rate_pct": loan["current_rate"], "rate_type": loan["rate_type"],
                "summary": f"Your EMI has not changed: it has been {inr(loan['emi'])} at "
                           f"{pct(loan['current_rate'])} since the loan started. {decision.explanation}"}
        card = {"type": "emi_change", "title": "Your EMI has not changed", "subtitle": loan["loan_id"],
                "metrics": [{"label": "EMI", "value": inr(loan["emi"]), "emphasis": True},
                            {"label": "Rate", "value": pct(loan["current_rate"])}],
                "notes": [decision.explanation], "sources": _record(hist_res) + clauses}
        return ToolOutput("ok", data, [card], card["sources"], focus=loan["loan_id"])
    prev, cur = history[-2], history[-1]
    calc = calc_emi_change(loan_id=loan["loan_id"], old_rate=prev["rate"], new_rate=cur["rate"],
                           old_emi=prev["emi_after"], new_emi=cur["emi_after"], effective_from=cur["effective_from"],
                           reason=cur["reason"], outstanding_at_reset=cur["outstanding_at_change"],
                           months_left_at_reset=cur["instalments_left_at_change"])
    f = calc.figures
    debits = [{"due_date": p["due_date"], "emi": p["emi"], "rate": p["rate"]} for p in paid[-2:]]
    summary = (f"Your EMI went from {inr(f['old_emi'])} to {inr(f['new_emi'])} (+{inr(f['emi_change'])} a month) "
               f"because your rate was reset from {pct(f['old_rate'])} to {pct(f['new_rate'])} on "
               f"{fmt_date(f['effective_from'])}. {cur['reason']}. {decision.explanation}")
    data = {"loan_id": loan["loan_id"], "emi_changed": True, "old_emi": int(f["old_emi"]), "new_emi": int(f["new_emi"]),
            "emi_change": int(f["emi_change"]), "old_rate_pct": prev["rate"], "new_rate_pct": cur["rate"],
            "rate_change_pct": float(f["rate_change"]), "effective_from": cur["effective_from"], "cause": cur["reason"],
            "outstanding_at_reset": cur["outstanding_at_change"], "instalments_left_at_reset": cur["instalments_left_at_change"],
            "tenure_unchanged": bool(decision.params.get("tenure_unchanged")), "policy": decision.explanation,
            "last_two_debits": debits, "summary": summary}
    sources = _record(hist_res) + (_record(sched_res) if sched_res.ok else []) + clauses + [_calc_source(calc)]
    card = {"type": "emi_change", "title": "Why your EMI changed", "subtitle": f"{loan['product_name']} · {loan['loan_id']}",
            "metrics": [{"label": "Previous EMI", "value": inr(f["old_emi"])},
                        {"label": "Current EMI", "value": inr(f["new_emi"]), "emphasis": True,
                         "delta": f"+{inr(f['emi_change'])}"},
                        {"label": "Rate", "value": f"{pct(f['old_rate'])} → {pct(f['new_rate'])}"},
                        {"label": "Effective", "value": fmt_date(f["effective_from"])}],
            "notes": [cur["reason"] + ".", decision.explanation],
            "actions": [{"label": "What if I prepay ₹50,000?", "prompt": "If I prepay ₹50,000 today, how much interest would I save?"}],
            "sources": sources}
    if debits:
        card["table"] = {"columns": ["Due date", "EMI debited", "Rate"],
                         "rows": [[fmt_date(d["due_date"]), inr(d["emi"]), pct(d["rate"])] for d in debits],
                         "row_status": [None] * len(debits)}
    return ToolOutput("ok", data, [card], sources, figures=calc.figures, focus=loan["loan_id"],
                      from_cache=loan_res.from_cache)


async def prepayment_options(ctx: ToolContext, amount: float, loan_id: str | None = None) -> ToolOutput:
    loan, loan_res, problem = await resolve_loan(ctx, loan_id)
    if problem:
        return problem
    ctx.session.setdefault("entities", {})["amount"] = amount
    decision = ctx.decide("prepayment", loan_facts(loan, ctx.today, amount))
    clauses = await ctx.cite(decision.clause_ids)
    if not decision.allowed:
        data = {"loan_id": loan["loan_id"], "amount": amount, "allowed": False,
                "reason": decision.params.get("reason"), "policy": decision.explanation,
                "summary": f"A part-prepayment of {inr(amount)} isn't possible right now. {decision.explanation}"}
        card = {"type": "prepayment_options", "title": "Prepayment not available", "subtitle": loan["loan_id"],
                "metrics": [{"label": "Amount", "value": inr(amount)}], "notes": [decision.explanation],
                "sources": _record(loan_res) + clauses}
        return ToolOutput("ok", data, [card], card["sources"], focus=loan["loan_id"])
    if amount >= loan["outstanding_principal"]:
        return ToolOutput("ok", {"allowed": False, "reason": "covers_whole_loan",
                                 "summary": f"{inr(amount)} covers the whole outstanding principal of "
                                            f"{inr(loan['outstanding_principal'])}; that is a foreclosure."},
                          focus=loan["loan_id"])
    calc = prepayment_savings(outstanding=loan["outstanding_principal"], annual_rate=loan["current_rate"],
                              current_emi=loan["emi"], months_left=loan["tenure_left_months"], amount=amount,
                              charge_pct=decision.params.get("charge_pct", 0), gst_pct=decision.params.get("gst_pct", 0))
    f = calc.figures
    t, e = f["reduce_tenure"], f["reduce_emi"]
    data = {"loan_id": loan["loan_id"], "amount": int(f["amount"]), "allowed": True, "policy": decision.explanation,
            "total_charge": int(f["total_charge"]), "interest_remaining_now": int(f["interest_remaining"]),
            "reduce_tenure": {"emi": int(t["emi"]), "months_saved": t["months_saved"], "instalments_left": t["instalments"],
                              "interest_saved": int(t["interest_saved"]), "net_saving": int(t["net_saving"])},
            "reduce_emi": {"new_emi": int(e["emi"]), "emi_reduction": int(e["emi_reduction"]),
                           "instalments_left": e["instalments"], "interest_saved": int(e["interest_saved"]),
                           "net_saving": int(e["net_saving"])},
            "summary": (f"Prepaying {inr(amount)} saves {inr(t['interest_saved'])} in interest if you keep the EMI and "
                        f"shorten the loan by {months(t['months_saved'])}, or {inr(e['interest_saved'])} if you keep the "
                        f"tenure and lower the EMI by {inr(e['emi_reduction'])} to {inr(e['emi'])}. "
                        + ("No prepayment charge applies." if not f["total_charge"] else
                           f"A charge of {inr(f['total_charge'])} including GST applies."))}
    sources = _record(loan_res) + clauses + [_calc_source(calc)]
    card = {"type": "prepayment_options", "title": f"Prepaying {inr(amount)}",
            "subtitle": f"{loan['loan_id']} · outstanding {inr(loan['outstanding_principal'])}",
            "columns": [
                {"label": "Reduce tenure (keep EMI)", "metrics": [
                    {"label": "Interest saved", "value": inr(t["interest_saved"]), "emphasis": True},
                    {"label": "Months saved", "value": str(t["months_saved"])},
                    {"label": "EMI", "value": inr(t["emi"])},
                    {"label": "EMIs left", "value": str(t["instalments"])}]},
                {"label": "Reduce EMI (keep tenure)", "metrics": [
                    {"label": "Interest saved", "value": inr(e["interest_saved"]), "emphasis": True},
                    {"label": "New EMI", "value": inr(e["emi"]), "delta": f"-{inr(e['emi_reduction'])}"},
                    {"label": "EMIs left", "value": str(e["instalments"])}]}],
            "metrics": [{"label": "Prepayment charge", "value": inr(f["total_charge"]) if f["total_charge"] else "None"}],
            "notes": [decision.explanation],
            "actions": [{"label": "Request it, reduce tenure",
                         "prompt": f"Go ahead and request a prepayment of {inr(amount)} to reduce my tenure"},
                        {"label": "Request it, reduce EMI",
                         "prompt": f"Go ahead and request a prepayment of {inr(amount)} to reduce my EMI"}],
            "sources": sources}
    return ToolOutput("ok", data, [card], sources, figures=calc.figures, focus=loan["loan_id"],
                      from_cache=loan_res.from_cache)


async def payment_history(ctx: ToolContext, loan_id: str | None = None, months: int = 6) -> ToolOutput:
    loan, loan_res, problem = await resolve_loan(ctx, loan_id)
    if problem:
        return problem
    since = add_months(ctx.today, -months)
    txn_res, mandate_res = await ctx.call_many([
        ("loans_get_transactions", {"loan_id": loan["loan_id"], "since": since.isoformat()}),
        ("loans_get_mandates", {"loan_id": loan["loan_id"]})])
    if not txn_res.ok:
        return _unavailable(txn_res, "Payments")
    txns = txn_res.data["transactions"]
    calc = failed_payment_summary(txns, since)
    f = calc.figures
    charge_rule = ctx.decide("dishonour_charge", {})
    clause_ids = list(charge_rule.clause_ids)
    disputes = []
    for d in f["duplicates"]:
        txn = next(t for t in txns if t["txn_id"] == d["txn_id"])
        days = (ctx.today - date.fromisoformat(txn["attempted_at"][:10])).days
        dec = ctx.decide("dispute_eligibility", {"charge": {"days_since": days, "is_duplicate": True}})
        clause_ids += [c for c in dec.clause_ids if c not in clause_ids]
        disputes.append({"txn_id": d["txn_id"], "excess_charge": int(d["excess"]), "dispute_allowed": dec.allowed,
                         "policy": dec.explanation})
    clauses = await ctx.cite(clause_ids)
    mandates = mandate_res.data["mandates"] if mandate_res.ok else []
    failed = []
    for row in f["failed"]:
        txn = next(t for t in txns if t["txn_id"] == row["txn_id"])
        retry = next((t for t in txns if t["due_date"] == txn["due_date"] and t["status"] == "success"), None)
        failed.append({"txn_id": row["txn_id"], "date": row["date"], "amount": int(row["amount"]),
                       "reason_code": row["reason"], "what_happened": FAILURE_TEXT.get(row["reason"], row["reason"]),
                       "charges": [int(c) for c in row["charges"]],
                       "recovered": f"paid on {fmt_date(retry['attempted_at'])} via {retry['channel']}" if retry
                       else "not yet paid"})
    entities = ctx.session.setdefault("entities", {})
    if disputes:
        entities["last_txn"] = disputes[0]["txn_id"]
    elif failed:
        entities["last_txn"] = failed[-1]["txn_id"]
    data = {"loan_id": loan["loan_id"], "window": f"since {since.isoformat()}", "failed_count": f["failed_count"],
            "failed": failed, "total_charges": int(f["total_charges"]), "duplicate_charges": disputes,
            "charge_policy": charge_rule.explanation,
            "mandates": [{"type": m["type"], "bank": m["bank"], "status": m["status"], "expires_on": m["expires_on"]}
                         for m in mandates],
            "successful_debits": sum(1 for t in txns if t["status"] == "success"),
            "latest_debit": {"date": txns[0]["attempted_at"][:10], "amount": txns[0]["amount"],
                             "status": txns[0]["status"], "channel": txns[0]["channel"]} if txns else None}
    if not mandate_res.ok:
        data["mandates"] = "unavailable"
    parts = []
    if txns:
        latest = txns[0]
        parts.append(f"Your last payment attempt, {inr(latest['amount'])} on {fmt_date(latest['attempted_at'])}, "
                     + (f"went through via {latest['channel']}." if latest["status"] == "success" else "failed."))
    parts.append("No debits failed since " + fmt_date(since) + "." if not f["failed_count"] else
                 f"{f['failed_count']} debit{'s' if f['failed_count'] != 1 else ''} failed since {fmt_date(since)}.")
    for row in failed:
        parts.append(f"On {fmt_date(row['date'])} the {inr(row['amount'])} EMI debit failed: {row['what_happened']}. "
                     f"It was {row['recovered']}.")
    for d in disputes:
        parts.append(f"{d['txn_id']} was charged twice; {inr(d['excess_charge'])} is a duplicate you can dispute.")
    active = [m for m in mandates if m["status"] == "active"]
    if active:
        parts.append(f"Your repayment mandate is active: {active[0]['type']} with {active[0]['bank']}.")
    elif mandates:
        parts.append(f"Your {mandates[0]['type']} mandate has expired; please renew it so EMIs can be collected.")
    data["summary"] = " ".join(parts)
    rows, status = [], []
    for t in txns:
        rows.append([fmt_date(t["attempted_at"]), inr(t["amount"]), "Paid" if t["status"] == "success" else "Failed",
                     t["channel"] if t["status"] == "success" else FAILURE_TEXT.get(t["failure_code"], t["failure_code"]).capitalize(),
                     " + ".join(inr(c) for c in t["charges"]) or "–"])
        status.append("ok" if t["status"] == "success" else "bad")
    sources = _record(txn_res) + (_record(mandate_res) if mandate_res.ok else []) + clauses + [_calc_source(calc)]
    card = {"type": "payment_timeline", "title": f"Payments since {fmt_date(since)}", "subtitle": loan["loan_id"],
            "metrics": [{"label": "Failed debits", "value": str(f["failed_count"]), "emphasis": f["failed_count"] > 0},
                        {"label": "Charges levied", "value": inr(f["total_charges"])}],
            "table": {"columns": ["Date", "Amount", "Status", "Detail", "Charges"], "rows": rows, "row_status": status},
            "notes": [charge_rule.explanation], "sources": sources}
    if disputes:
        card["metrics"].append({"label": "Duplicate charge", "value": inr(disputes[0]["excess_charge"]), "emphasis": True})
        card["actions"] = [{"label": f"Dispute the duplicate {inr(disputes[0]['excess_charge'])}",
                            "prompt": f"Raise a dispute for the duplicate charge on {disputes[0]['txn_id']}"}]
    expired = [m for m in mandates if m["status"] == "expired"]
    if expired:
        card["notes"].append(f"Your {expired[0]['type']} mandate with {expired[0]['bank']} expired on "
                             f"{fmt_date(expired[0]['expires_on'])}; "
                             + ("a new one is active." if any(m["status"] == "active" for m in mandates) else
                                "please renew it."))
    return ToolOutput("ok", data, [card], sources, figures=calc.figures, focus=loan["loan_id"])


async def foreclosure_options(ctx: ToolContext, loan_id: str | None = None) -> ToolOutput:
    loan, loan_res, problem = await resolve_loan(ctx, loan_id)
    if problem:
        return problem
    facts = loan_facts(loan, ctx.today)
    decision = ctx.decide("foreclosure", facts)
    prepay = ctx.decide("prepayment", facts)
    clauses = await ctx.cite(list(dict.fromkeys(decision.clause_ids + prepay.clause_ids)))
    quote = foreclosure_quote(outstanding=loan["outstanding_principal"], annual_rate=loan["current_rate"],
                              last_due=date.fromisoformat(loan["last_due_date"]), as_of=ctx.today,
                              charge_pct=decision.params.get("charge_pct", 0), gst_pct=decision.params.get("gst_pct", 0),
                              allowed=decision.allowed)
    q = quote.figures
    options = []
    if decision.allowed:
        options.append(f"Foreclose now by paying {inr(q['payable'])}"
                       + (" with no charge." if not q["charge"] else f", including a charge of {inr(q['charge'] + q['gst'])}."))
    else:
        options.append(f"Foreclosure becomes possible on {decision.params.get('allowed_from')}; "
                       f"a {decision.params.get('charge_pct')}% charge plus GST applies then.")
    if prepay.allowed:
        options.append("Make a part-prepayment to cut interest without closing the loan.")
    else:
        options.append("Part-prepayment is also locked until the same date.")
    options.append(f"Keep paying your EMI of {inr(loan['emi'])}; {loan['tenure_left_months']} EMIs are left.")
    options.append("Download a repayment statement at no charge.")
    data = {"loan_id": loan["loan_id"], "foreclosure_allowed": decision.allowed, "policy": decision.explanation,
            "allowed_from": decision.params.get("allowed_from"), "charge_pct": decision.params.get("charge_pct", 0),
            "quote_today": {"outstanding": int(q["outstanding"]), "accrued_interest": int(q["accrued_interest"]),
                            "charge": int(q["charge"]), "gst": int(q["gst"]), "payable": int(q["payable"])},
            "part_prepayment_allowed": prepay.allowed, "options": options, "emi": loan["emi"],
            "tenure_left_months": loan["tenure_left_months"],
            "summary": (f"{'Yes' if decision.allowed and not q['charge'] else 'No'}: {decision.explanation} "
                        + (f"To close it today you would pay {inr(q['payable'])}." if decision.allowed else ""))}
    if not decision.allowed:
        data.pop("quote_today")
    metrics = [{"label": "Foreclosure", "value": "Allowed" if decision.allowed else "Not yet", "emphasis": True}]
    if decision.allowed:
        metrics += [{"label": "Payable today", "value": inr(q["payable"]), "emphasis": True},
                    {"label": "Charge", "value": inr(q["charge"] + q["gst"]) if q["charge"] else "None"}]
    else:
        metrics.append({"label": "Eligible from", "value": decision.params.get("allowed_from")})
    sources = _record(loan_res) + clauses + ([_calc_source(quote)] if decision.allowed else [])
    actions = [{"label": "Get my statement", "prompt": "Send me a repayment statement"}]
    if decision.allowed:
        actions.insert(0, {"label": "Request foreclosure", "prompt": "Go ahead and request foreclosure of my loan"})
    card = {"type": "foreclosure_quote", "title": "Foreclosure and your options", "subtitle": loan["loan_id"],
            "metrics": metrics, "notes": options, "actions": actions, "sources": sources}
    return ToolOutput("ok", data, [card], sources, figures=quote.figures, focus=loan["loan_id"])


# --------------------------------------------------------------------------- action preparers
def months(n: int) -> str:
    return f"{n} month{'s' if n != 1 else ''}"


MODE_LABEL = {"reduce_tenure": "Reduce tenure", "reduce_emi": "Reduce EMI"}


async def prepare_prepayment(ctx: ToolContext, amount: float, mode: str, loan_id: str | None = None):
    loan, loan_res, problem = await resolve_loan(ctx, loan_id)
    if problem:
        return problem
    decision = ctx.decide("prepayment", loan_facts(loan, ctx.today, amount))
    if not decision.allowed:
        return ToolOutput("refused", {"allowed": False, "policy": decision.explanation},
                          message=f"Not allowed: {decision.explanation}")
    if amount >= loan["outstanding_principal"]:
        return ToolOutput("refused", message="Amount covers the whole loan; offer a foreclosure instead.")
    calc = prepayment_savings(outstanding=loan["outstanding_principal"], annual_rate=loan["current_rate"],
                              current_emi=loan["emi"], months_left=loan["tenure_left_months"], amount=amount,
                              charge_pct=decision.params.get("charge_pct", 0), gst_pct=decision.params.get("gst_pct", 0))
    f = calc.figures
    effect = (f"{f['reduce_tenure']['months_saved']} fewer EMIs" if mode == "reduce_tenure"
              else f"EMI {inr(f['reduce_emi']['emi'])}")
    saved = f[mode]["interest_saved"]
    summary = [{"label": "Loan", "value": loan["loan_id"]}, {"label": "Amount", "value": inr(amount)},
               {"label": "Mode", "value": MODE_LABEL[mode]}, {"label": "Effect", "value": effect},
               {"label": "Interest saved", "value": inr(saved)},
               {"label": "Charge", "value": inr(f["total_charge"]) if f["total_charge"] else "None"}]
    spoken = (f"To confirm: a prepayment of {inr(amount)} on loan {loan['loan_id']}, "
              f"{'reducing your tenure by ' + months(f['reduce_tenure']['months_saved']) if mode == 'reduce_tenure' else 'lowering your EMI to ' + inr(f['reduce_emi']['emi'])}. "
              "Please read out the six-digit code sent to your phone.")
    return Proposal("Prepayment request", summary, "prepayment",
                    {"loan_id": loan["loan_id"], "amount": float(amount), "mode": mode,
                     "charge": int(f["total_charge"]), "expected_interest_saved": int(saved)},
                    f"Part-prepayment {inr(amount)} ({MODE_LABEL[mode].lower()}) on {loan['loan_id']}", spoken,
                    sources=[_calc_source(calc)])


async def prepare_foreclosure(ctx: ToolContext, loan_id: str | None = None):
    loan, _, problem = await resolve_loan(ctx, loan_id)
    if problem:
        return problem
    decision = ctx.decide("foreclosure", loan_facts(loan, ctx.today))
    if not decision.allowed:
        return ToolOutput("refused", {"allowed": False, "policy": decision.explanation},
                          message=f"Not allowed: {decision.explanation}")
    quote = foreclosure_quote(outstanding=loan["outstanding_principal"], annual_rate=loan["current_rate"],
                              last_due=date.fromisoformat(loan["last_due_date"]), as_of=ctx.today,
                              charge_pct=decision.params.get("charge_pct", 0), gst_pct=decision.params.get("gst_pct", 0))
    q = quote.figures
    summary = [{"label": "Loan", "value": loan["loan_id"]}, {"label": "Payable", "value": inr(q["payable"])},
               {"label": "Charge", "value": inr(q["charge"] + q["gst"]) if q["charge"] else "None"},
               {"label": "Quote valid", "value": fmt_date(ctx.today)}]
    return Proposal("Foreclosure request", summary, "foreclosure",
                    {"loan_id": loan["loan_id"], "payable": int(q["payable"]), "as_of": ctx.today.isoformat()},
                    f"Foreclosure of {loan['loan_id']} at {inr(q['payable'])}",
                    f"To confirm: close loan {loan['loan_id']} by paying {inr(q['payable'])}. "
                    "Please read out the six-digit code sent to your phone.", sources=[_calc_source(quote)])


async def prepare_dispute(ctx: ToolContext, txn_id: str, reason: str, loan_id: str | None = None):
    loan, _, problem = await resolve_loan(ctx, loan_id)
    if problem:
        return problem
    res = await ctx.call("loans_get_transactions", loan_id=loan["loan_id"])
    if not res.ok:
        return _unavailable(res, "Payments")
    txn = next((t for t in res.data["transactions"] if t["txn_id"] == txn_id), None)
    if txn is None:
        return ToolOutput("error", message=f"No transaction {txn_id} on loan {loan['loan_id']}.")
    charges = txn.get("charges") or []
    days = (ctx.today - date.fromisoformat(txn["attempted_at"][:10])).days
    duplicate = len(charges) > 1
    decision = ctx.decide("dispute_eligibility", {"charge": {"days_since": days, "is_duplicate": duplicate}})
    if not decision.allowed:
        return ToolOutput("refused", {"allowed": False, "policy": decision.explanation},
                          message=f"Not allowed: {decision.explanation}")
    disputed = sum(charges[1:]) if duplicate else sum(charges)
    summary = [{"label": "Loan", "value": loan["loan_id"]}, {"label": "Transaction", "value": txn_id},
               {"label": "Disputed amount", "value": inr(disputed)},
               {"label": "Reason", "value": "Duplicate dishonour charge" if duplicate else reason},
               {"label": "Expected", "value": "Reversal within 7 working days" if duplicate else "Review"}]
    return Proposal("Payment dispute", summary, "payment_dispute",
                    {"loan_id": loan["loan_id"], "txn_id": txn_id, "amount": disputed, "reason": reason,
                     "duplicate": duplicate},
                    f"Dispute {inr(disputed)} on {txn_id}: {reason}",
                    f"To confirm: I'll raise a dispute for {inr(disputed)} on the {fmt_date(txn['attempted_at'])} debit. "
                    "Shall I go ahead?")


async def prepare_statement(ctx: ToolContext, loan_id: str | None = None):
    loan, _, problem = await resolve_loan(ctx, loan_id)
    if problem:
        return problem
    summary = [{"label": "Loan", "value": loan["loan_id"]}, {"label": "Format", "value": "PDF"}]
    return Proposal("Repayment statement", summary, "statement", {"loan_id": loan["loan_id"]},
                    f"Repayment statement for {loan['loan_id']}", "Your statement is ready.")


# --------------------------------------------------------------------------- account panel
async def overview(ctx: ToolContext) -> dict:
    listing = await ctx.call("loans_list_loans")
    if not listing.ok:
        return {"degraded": ["Loan Management"]}
    loans = [loan for loan in listing.data["loans"] if loan["status"] == "active"]
    since = add_months(ctx.today, -6).isoformat()
    txn_results = await ctx.call_many([("loans_get_transactions", {"loan_id": loan["loan_id"], "since": since})
                                       for loan in loans], deadline_s=2.5)
    payments, degraded = [], []
    for loan, res in zip(loans, txn_results):
        if not res.ok:
            degraded.append("Payments")
            continue
        for t in res.data["transactions"]:
            payments.append({"txn_id": t["txn_id"], "loan_id": t["loan_id"], "date": t["attempted_at"][:10],
                             "amount": t["amount"], "status": t["status"],
                             "failure_reason": FAILURE_TEXT.get(t["failure_code"]) if t["failure_code"] else None,
                             "charge": sum(t["charges"]) or None})
    return {"loans": [{"loan_id": loan["loan_id"], "product_name": loan["product_name"], "rate_type": loan["rate_type"],
                       "current_rate": loan["current_rate"], "emi": loan["emi"],
                       "outstanding_principal": round(loan["outstanding_principal"]),
                       "next_due_date": loan["next_due_date"], "tenure_left_months": loan["tenure_left_months"],
                       "principal": loan["principal"], "status": loan["status"]} for loan in loans],
            "payments": payments, "degraded": sorted(set(degraded))}
