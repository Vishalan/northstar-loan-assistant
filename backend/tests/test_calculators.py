"""Calculators: hand-worked cases and invariants."""

from datetime import date
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from nsplatform.calculators.loans import (amortize, emi, explain_emi_change, extra_payment_tenure_impact,
                                          failed_payment_summary, foreclosure_quote, prepayment_savings, total_interest)
from nsplatform.money import add_months, group_indian, inr, months_between


def test_emi_hand_worked():
    # P=8,00,000, 10.5% p.a., 60 months: standard EMI tables give 17,195
    assert emi(800000, 10.5, 60) == Decimal("17195")
    assert emi(500000, 12, 48) == Decimal("13167")
    assert emi(120000, 0, 12) == Decimal("10000")


def test_indian_grouping():
    assert group_indian("800000") == "8,00,000"
    assert group_indian("12345678") == "1,23,45,678"
    assert inr(602345.83) == "₹6,02,346"
    assert inr(-221) == "-₹221"
    assert inr(590) == "₹590"


def test_dates():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert months_between(date(2026, 2, 20), date(2026, 10, 27)) == 8
    assert months_between(date(2026, 2, 20), date(2027, 2, 19)) == 11


def test_schedule_clears_principal_exactly():
    rows = amortize(800000, 10.5, emi(800000, 10.5, 60))
    assert len(rows) == 60
    assert rows[-1].balance == 0
    assert sum(r.principal for r in rows) == Decimal("800000.00")


def test_emi_change_explainer_matches_persona():
    r = explain_emi_change(loan_id="PL-20391", old_rate=10.5, new_rate=11.25, old_emi=17195, new_emi=17416,
                           effective_from="2026-10-01", reason="EBLR reset", outstanding_at_reset=614006,
                           months_left_at_reset=43)
    assert r.figures["emi_change"] == 221
    assert r.figures["recomputed_emi"] == 17416
    assert any("₹17,416" in s for s in r.steps)


def test_prepayment_both_modes():
    r = prepayment_savings(outstanding=602345.83, annual_rate=11.25, current_emi=17416, months_left=42, amount=50000)
    t, e = r.figures["reduce_tenure"], r.figures["reduce_emi"]
    assert t["interest_saved"] > e["interest_saved"] > 0  # shortening the tenure always saves more
    assert t["months_saved"] == 4 and t["emi"] == 17416
    assert e["instalments"] == 42 and e["emi"] < 17416
    assert r.figures["total_charge"] == 0


def test_prepayment_charge_reduces_net_saving():
    r = prepayment_savings(outstanding=330037, annual_rate=12, current_emi=13167, months_left=29, amount=50000,
                           charge_pct=3, gst_pct=18)
    assert r.figures["charge"] == 1500 and r.figures["gst"] == 270
    assert r.figures["reduce_tenure"]["net_saving"] == r.figures["reduce_tenure"]["interest_saved"] - 1770


def test_extra_payment_tenure_impact():
    r = extra_payment_tenure_impact(outstanding=602345.83, annual_rate=11.25, current_emi=17416, amount=20000)
    assert r.figures["months_saved"] >= 1 and r.figures["instalments_after"] < r.figures["instalments_before"]


def test_foreclosure_quote():
    q = foreclosure_quote(outstanding=243359.18, annual_rate=13.5, last_due=date(2026, 10, 20), as_of=date(2026, 10, 27),
                          charge_pct=3, gst_pct=18)
    assert q.figures["days_accrued"] == 7
    assert q.figures["accrued_interest"] == 630  # 2,43,359 x 13.5% x 7/365
    assert q.figures["charge"] == 7301 and q.figures["gst"] == 1314
    assert q.figures["payable"] == 243359 + 630 + 7301 + 1314


def test_failed_payment_summary_detects_duplicates():
    txns = [{"txn_id": "A", "status": "failed", "attempted_at": "2026-09-10T06:00", "amount": 13167,
             "failure_code": "MANDATE_EXPIRED", "charges": [590, 590]},
            {"txn_id": "B", "status": "failed", "attempted_at": "2026-06-10T06:00", "amount": 13167,
             "failure_code": "INSUFFICIENT_FUNDS", "charges": [590]},
            {"txn_id": "C", "status": "success", "attempted_at": "2026-10-10T06:00", "amount": 13167,
             "failure_code": None, "charges": []}]
    r = failed_payment_summary(txns, date(2026, 4, 27))
    assert r.figures["failed_count"] == 2 and r.figures["total_charges"] == 1770
    assert r.figures["duplicates"] == [{"txn_id": "A", "charge": 590, "times": 2, "excess": 590}]


@settings(max_examples=150, deadline=None)
@given(principal=st.integers(50_000, 2_000_000), rate=st.floats(6, 24), months=st.integers(6, 84))
def test_schedule_invariants(principal, rate, months):
    rate = round(rate, 2)
    pay = emi(principal, rate, months)
    rows = amortize(principal, rate, pay)
    assert abs(len(rows) - months) <= 1
    assert rows[-1].balance == 0
    assert sum(r.principal for r in rows) == Decimal(principal)
    assert all(r.interest >= 0 for r in rows)


@settings(max_examples=100, deadline=None)
@given(principal=st.integers(100_000, 1_500_000), rate=st.floats(8, 20), months=st.integers(12, 72),
       share=st.floats(0.02, 0.6))
def test_prepayment_invariants(principal, rate, months, share):
    rate = round(rate, 2)
    pay = emi(principal, rate, months)
    amount = int(principal * share)
    r = prepayment_savings(outstanding=principal, annual_rate=rate, current_emi=pay, months_left=months, amount=amount)
    t, e = r.figures["reduce_tenure"], r.figures["reduce_emi"]
    assert t["interest_saved"] >= 0 and e["interest_saved"] >= 0
    assert t["interest_saved"] >= e["interest_saved"]
    assert 0 <= t["months_saved"] <= months
    assert total_interest(amortize(principal - amount, rate, pay)) <= total_interest(amortize(principal, rate, pay))
