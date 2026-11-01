"""Deterministic loan calculators.

Every function is pure, works in Decimal, and returns a `CalcResult` whose `figures`
are the only numbers the assistant may state and whose `steps` show the working.
Convention: monthly reducing balance, r = annual_rate / 12 / 100, EMI rounded to the rupee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from nsplatform.money import D, ZERO, fmt_date, inr, pct, to_paisa, to_rupee


@dataclass
class CalcResult:
    name: str
    figures: dict[str, object]
    steps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"calculator": self.name, "figures": _jsonable(self.figures), "steps": self.steps}


def _jsonable(value):
    if isinstance(value, Decimal):
        return float(value) if value != value.to_integral_value() else int(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def monthly_rate(annual_rate) -> Decimal:
    return D(annual_rate) / Decimal(1200)


def emi(principal, annual_rate, months: int) -> Decimal:
    """Equated monthly instalment, rounded to the rupee."""
    p, n = D(principal), int(months)
    if n <= 0:
        raise ValueError("months must be positive")
    r = monthly_rate(annual_rate)
    if r == 0:
        return to_rupee(p / n)
    growth = (1 + r) ** n
    return to_rupee(p * r * growth / (growth - 1))


@dataclass
class Row:
    n: int
    emi: Decimal
    interest: Decimal
    principal: Decimal
    balance: Decimal


def amortize(principal, annual_rate, instalment, max_months: int = 600) -> list[Row]:
    """Schedule until the balance is cleared; the last instalment is trimmed."""
    balance, r, pay = D(principal), monthly_rate(annual_rate), D(instalment)
    rows: list[Row] = []
    n = 0
    while balance > ZERO and n < max_months:
        n += 1
        interest = to_paisa(balance * r)
        if pay <= interest:
            raise ValueError("instalment does not cover interest")
        principal_part = min(pay - interest, balance)
        # a residue left by rupee-rounding of the EMI is absorbed into the final instalment
        if ZERO < balance - principal_part < pay * Decimal("0.02"):
            principal_part = balance
        balance = to_paisa(balance - principal_part)
        rows.append(Row(n, to_paisa(interest + principal_part), interest, to_paisa(principal_part), balance))
    return rows


def total_interest(rows: list[Row]) -> Decimal:
    return to_paisa(sum((row.interest for row in rows), ZERO))


def explain_emi_change(*, loan_id: str, old_rate, new_rate, old_emi, new_emi, effective_from: str,
                       reason: str, outstanding_at_reset, months_left_at_reset: int,
                       benchmark: str | None = None) -> CalcResult:
    """Why the EMI moved: recompute the new EMI from the reset inputs and attribute the change."""
    recomputed = emi(outstanding_at_reset, new_rate, months_left_at_reset)
    rate_delta = D(new_rate) - D(old_rate)
    emi_delta = D(new_emi) - D(old_emi)
    steps = [
        f"Before {fmt_date(effective_from)} the rate was {pct(old_rate)} and the EMI {inr(old_emi)}.",
        f"From {fmt_date(effective_from)} the rate is {pct(new_rate)} ({'+' if rate_delta >= 0 else ''}"
        f"{pct(rate_delta)}), because of: {reason}.",
        f"Outstanding principal at the reset: {inr(outstanding_at_reset)}; instalments left: {months_left_at_reset}.",
        f"EMI = P x r x (1+r)^n / ((1+r)^n - 1) with r = {pct(new_rate)}/12 gives {inr(recomputed)}.",
        f"Change per month: {'+' if emi_delta >= 0 else ''}{inr(emi_delta)}.",
    ]
    if recomputed != to_rupee(new_emi):
        steps.append(f"Note: system EMI {inr(new_emi)} differs from recomputed {inr(recomputed)}.")
    return CalcResult("emi_change_explainer", {
        "loan_id": loan_id,
        "old_rate": D(old_rate), "new_rate": D(new_rate), "rate_change": rate_delta,
        "old_emi": to_rupee(old_emi), "new_emi": to_rupee(new_emi), "emi_change": to_rupee(emi_delta),
        "recomputed_emi": recomputed, "effective_from": effective_from,
        "outstanding_at_reset": to_rupee(outstanding_at_reset), "months_left_at_reset": months_left_at_reset,
        "reason": reason, "benchmark": benchmark,
    }, steps)


def prepayment_savings(*, outstanding, annual_rate, current_emi, months_left: int, amount,
                       charge_pct=0, gst_pct=0) -> CalcResult:
    """Interest saved by a lump-sum prepayment, in both modes, net of charges."""
    outstanding, amount = D(outstanding), D(amount)
    if amount <= 0:
        raise ValueError("amount must be positive")
    if amount >= outstanding:
        raise ValueError("amount covers the whole loan; use a foreclosure quote instead")
    base_rows = amortize(outstanding, annual_rate, current_emi)
    base_interest = total_interest(base_rows)
    new_principal = outstanding - amount

    tenure_rows = amortize(new_principal, annual_rate, current_emi)
    tenure_interest = total_interest(tenure_rows)

    reduced_emi = emi(new_principal, annual_rate, months_left)
    emi_rows = amortize(new_principal, annual_rate, reduced_emi)
    emi_interest = total_interest(emi_rows)

    charge = to_rupee(amount * D(charge_pct) / 100)
    gst = to_rupee(charge * D(gst_pct) / 100)
    total_charge = charge + gst
    saved_tenure = to_rupee(base_interest - tenure_interest)
    saved_emi = to_rupee(base_interest - emi_interest)
    months_saved = len(base_rows) - len(tenure_rows)

    steps = [
        f"Outstanding principal {inr(outstanding)} at {pct(annual_rate)}, EMI {inr(current_emi)}, "
        f"{len(base_rows)} instalments left. Interest still to pay: {inr(base_interest)}.",
        f"After prepaying {inr(amount)} the principal becomes {inr(new_principal)}.",
        f"Reduce tenure: keep EMI {inr(current_emi)}; loan ends in {len(tenure_rows)} instalments "
        f"({months_saved} fewer); interest {inr(tenure_interest)}; saving {inr(saved_tenure)}.",
        f"Reduce EMI: keep {months_left} instalments; new EMI {inr(reduced_emi)} "
        f"({inr(D(current_emi) - reduced_emi)} less per month); interest {inr(emi_interest)}; saving {inr(saved_emi)}.",
    ]
    if total_charge:
        steps.append(f"Prepayment charge {pct(charge_pct)} = {inr(charge)} plus GST {inr(gst)} = {inr(total_charge)}.")
    else:
        steps.append("No prepayment charge applies.")
    return CalcResult("prepayment_savings", {
        "amount": to_rupee(amount), "outstanding": to_rupee(outstanding), "new_principal": to_rupee(new_principal),
        "current_emi": to_rupee(current_emi), "annual_rate": D(annual_rate),
        "instalments_left": len(base_rows), "interest_remaining": to_rupee(base_interest),
        "reduce_tenure": {
            "emi": to_rupee(current_emi), "instalments": len(tenure_rows), "months_saved": months_saved,
            "interest": to_rupee(tenure_interest), "interest_saved": saved_tenure,
            "net_saving": saved_tenure - total_charge,
        },
        "reduce_emi": {
            "emi": reduced_emi, "emi_reduction": to_rupee(D(current_emi) - reduced_emi),
            "instalments": months_left, "interest": to_rupee(emi_interest), "interest_saved": saved_emi,
            "net_saving": saved_emi - total_charge,
        },
        "charge": charge, "gst": gst, "total_charge": total_charge,
    }, steps)


def extra_payment_tenure_impact(*, outstanding, annual_rate, current_emi, amount) -> CalcResult:
    """Does a one-time extra payment shorten the tenure, and by how much (EMI unchanged)?"""
    result = prepayment_savings(outstanding=outstanding, annual_rate=annual_rate, current_emi=current_emi,
                                months_left=len(amortize(outstanding, annual_rate, current_emi)), amount=amount)
    t = result.figures["reduce_tenure"]
    steps = result.steps[:3]
    return CalcResult("extra_payment_tenure_impact", {
        "amount": result.figures["amount"], "instalments_before": result.figures["instalments_left"],
        "instalments_after": t["instalments"], "months_saved": t["months_saved"],
        "interest_saved": t["interest_saved"], "emi": t["emi"],
    }, steps)


def foreclosure_quote(*, outstanding, annual_rate, last_due: date, as_of: date, charge_pct=0, gst_pct=0,
                      allowed: bool = True) -> CalcResult:
    """Amount to close the loan today: principal + interest accrued since the last due date + charges."""
    days = max((as_of - last_due).days, 0)
    accrued = to_rupee(D(outstanding) * D(annual_rate) / 100 * days / 365)
    charge = to_rupee(D(outstanding) * D(charge_pct) / 100)
    gst = to_rupee(charge * D(gst_pct) / 100)
    payable = to_rupee(D(outstanding) + accrued + charge + gst)
    steps = [
        f"Outstanding principal {inr(outstanding)}.",
        f"Interest accrued for {days} days since {fmt_date(last_due)} at {pct(annual_rate)}: {inr(accrued)}.",
        f"Foreclosure charge {pct(charge_pct)}: {inr(charge)}; GST: {inr(gst)}." if charge else
        "No foreclosure charge applies.",
        f"Payable on {fmt_date(as_of)}: {inr(payable)}.",
    ]
    return CalcResult("foreclosure_quote", {
        "outstanding": to_rupee(outstanding), "accrued_interest": accrued, "days_accrued": days,
        "charge": charge, "gst": gst, "payable": payable, "as_of": as_of, "allowed": allowed,
    }, steps)


def failed_payment_summary(transactions: list[dict], since: date) -> CalcResult:
    """Group failed debit attempts, total the charges and flag duplicate charges on one attempt."""
    failed = [t for t in transactions if t["status"] == "failed" and date.fromisoformat(t["attempted_at"][:10]) >= since]
    failed.sort(key=lambda t: t["attempted_at"])
    by_reason: dict[str, int] = {}
    charges = ZERO
    duplicates = []
    for t in failed:
        by_reason[t["failure_code"]] = by_reason.get(t["failure_code"], 0) + 1
        applied = [D(c) for c in t.get("charges", [])]
        charges += sum(applied, ZERO)
        if len(applied) > 1:
            duplicates.append({"txn_id": t["txn_id"], "charge": to_rupee(applied[0]),
                               "times": len(applied), "excess": to_rupee(sum(applied[1:], ZERO))})
    steps = [f"{len(failed)} failed debit attempt(s) since {fmt_date(since)}."]
    steps += [f"{t['txn_id']} on {fmt_date(t['attempted_at'])}: {inr(t['amount'])}, {t['failure_code']}, "
              f"charges {', '.join(inr(c) for c in t.get('charges', [])) or 'none'}." for t in failed]
    for d in duplicates:
        steps.append(f"{d['txn_id']} was charged {d['times']} times; excess {inr(d['excess'])}.")
    return CalcResult("failed_payment_summary", {
        "failed_count": len(failed), "by_reason": by_reason, "total_charges": to_rupee(charges),
        "duplicates": duplicates, "failed": [{"txn_id": t["txn_id"], "date": t["attempted_at"][:10],
                                              "amount": to_rupee(t["amount"]), "reason": t["failure_code"],
                                              "charges": [to_rupee(c) for c in t.get("charges", [])]}
                                             for t in failed],
    }, steps)
