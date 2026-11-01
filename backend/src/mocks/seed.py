"""Deterministic synthetic data for the mock enterprise systems.

Loans are simulated month by month from disbursal to DEMO_TODAY, applying rate resets the way
the lender's (synthetic) policy says: tenure unchanged, EMI recomputed on the outstanding balance.
Four hand-built personas carry the demo scenarios; 46 generated customers fill out the book.

Run `python -m mocks.seed` to dump the dataset as JSON for inspection.
"""

from __future__ import annotations

import json
import os
import random
from datetime import date, timedelta
from decimal import Decimal

from nsplatform.calculators.loans import amortize, emi
from nsplatform.money import D, add_months, to_paisa, to_rupee

DEMO_TODAY = date.fromisoformat(os.environ.get("DEMO_TODAY", "2026-10-27"))
EBLR_RESET = date(2026, 10, 1)
BOUNCE_CHARGE = 590  # ₹500 + 18% GST, per policy LOAN-TNC-9.2

PRODUCTS = {
    "PL-FLEXI": {"product_code": "PL-FLEXI", "name": "Personal Loan Flexi", "rate_type": "floating",
                 "benchmark": "EBLR", "lock_in_months": 0, "policy_ref": "LOAN-TNC"},
    "PL-FIXED": {"product_code": "PL-FIXED", "name": "Personal Loan Fixed", "rate_type": "fixed",
                 "benchmark": None, "lock_in_months": 12, "policy_ref": "LOAN-TNC"},
}

FIRST = ["Aarav", "Vivaan", "Aditya", "Ishaan", "Sai", "Ananya", "Diya", "Meera", "Neha", "Pooja", "Rahul",
         "Sneha", "Vikram", "Kiran", "Lakshmi", "Nikhil", "Rhea", "Sanjay", "Tara", "Varun", "Zoya", "Farhan",
         "Gauri", "Harsh"]
LAST = ["Agarwal", "Bose", "Chopra", "Desai", "Gupta", "Joshi", "Kapoor", "Khan", "Menon", "Nair", "Patel",
        "Reddy", "Rao", "Saxena", "Singh", "Verma", "Pillai", "Kulkarni", "Banerjee", "Shetty"]
BANKS = ["HDFC Bank", "ICICI Bank", "State Bank of India", "Axis Bank", "Kotak Mahindra Bank"]


def _mask_phone(phone: str) -> str:
    return "•••• " + phone[-4:]


def _customer(cid, name, phone, segment="retail", dob="1990-01-01", pan_last="1234F"):
    first = name.split()[0].lower()
    return {"customer_id": cid, "name": name, "phone": phone, "phone_masked": _mask_phone(phone),
            "email": f"{first}.{cid.lower()}@example.in", "pan_masked": f"•••••{pan_last}", "dob": dob,
            "kyc_status": "verified", "segment": segment, "preferred_language": "en"}


def simulate_loan(loan_id, customer_id, product_code, principal, tenure, disbursed: date, rate_events,
                  today: date = DEMO_TODAY):
    """Replay a loan to `today`. rate_events: [(effective_from, annual_rate, reason)] sorted, first = sanction."""
    balance = D(principal)
    rate = D(rate_events[0][1])
    current_emi = emi(balance, rate, tenure)
    history = [{"loan_id": loan_id, "effective_from": rate_events[0][0].isoformat(), "rate": float(rate),
                "reason": rate_events[0][2], "emi_after": int(current_emi),
                "outstanding_at_change": int(to_rupee(balance)), "instalments_left_at_change": tenure}]
    pending = list(rate_events[1:])
    paid = []
    k = 0
    while k < tenure:
        due = add_months(disbursed, k + 1)
        # apply any reset effective on or before this due date
        while pending and pending[0][0] <= due and pending[0][0] <= today:
            eff, new_rate, reason = pending.pop(0)
            months_left = tenure - k
            rate = D(new_rate)
            current_emi = emi(balance, rate, months_left)
            history.append({"loan_id": loan_id, "effective_from": eff.isoformat(), "rate": float(rate),
                            "reason": reason, "emi_after": int(current_emi),
                            "outstanding_at_change": int(to_rupee(balance)), "instalments_left_at_change": months_left})
        if due > today:
            break
        interest = to_paisa(balance * rate / 1200)
        principal_part = min(current_emi - interest, balance)
        balance = to_paisa(balance - principal_part)
        paid.append({"n": k + 1, "due_date": due.isoformat(), "emi": int(to_rupee(interest + principal_part)),
                     "interest": float(interest), "principal": float(principal_part), "balance": float(balance),
                     "rate": float(rate)})
        k += 1
    next_due = add_months(disbursed, k + 1) if k < tenure else None
    loan = {
        "loan_id": loan_id, "customer_id": customer_id, "product_code": product_code,
        "product_name": PRODUCTS[product_code]["name"], "rate_type": PRODUCTS[product_code]["rate_type"],
        "principal": int(principal), "disbursed_on": disbursed.isoformat(), "tenure_months": tenure,
        "current_rate": float(rate), "emi": int(current_emi), "outstanding_principal": float(balance),
        "next_due_date": next_due.isoformat() if next_due else None, "instalments_paid": k,
        "tenure_left_months": len(amortize(balance, rate, current_emi)) if balance > 0 else 0,
        "last_due_date": paid[-1]["due_date"] if paid else disbursed.isoformat(),
        "status": "active" if balance > 0 else "closed",
    }
    return loan, history, paid


def _debits(loan, paid, rng, failure_plan=None, random_failures=True):
    """One debit per paid instalment; failure_plan maps due_date -> list of attempt dicts."""
    txns = []
    for inst in paid:
        due = inst["due_date"]
        plan = (failure_plan or {}).get(due)
        if plan is None and random_failures and rng.random() < 0.03:
            retry = (date.fromisoformat(due) + timedelta(days=3)).isoformat()
            plan = [{"at": due, "status": "failed", "code": "INSUFFICIENT_FUNDS", "charges": [BOUNCE_CHARGE]},
                    {"at": retry, "status": "success", "channel": "NACH"}]
        for i, attempt in enumerate(plan or [{"at": due, "status": "success", "channel": "NACH"}]):
            txns.append({
                "txn_id": f"TX-{loan['loan_id'][3:]}-{due.replace('-', '')}-{i + 1}",
                "loan_id": loan["loan_id"], "due_date": due, "attempted_at": f"{attempt['at']}T06:00:00+05:30",
                "amount": inst["emi"], "status": attempt["status"], "channel": attempt.get("channel", "NACH"),
                "failure_code": attempt.get("code"), "charges": attempt.get("charges", []),
            })
    return txns


def _card_dataset():
    """Rohan's card: September statement vs a higher October one (EMI conversion + a disputed charge)."""
    card = {"card_id": "CC-4417", "customer_id": "C1004", "last4": "4417", "product": "Northstar Platinum",
            "limit": 200000, "billing_day": 15, "due_days_after_statement": 20}
    conversion_emi = emi(12000, 15, 6)
    sep_txns = [("2026-08-18", "Swiggy", "5812", 640), ("2026-08-22", "Indian Oil", "5541", 3200),
                ("2026-08-27", "BigBasket", "5411", 4310), ("2026-09-02", "Amazon India", "5311", 6150),
                ("2026-09-09", "PVR Cinemas", "7832", 1150), ("2026-09-12", "Airtel Postpaid", "4814", 2999)]
    oct_txns = [("2026-09-18", "BigBasket", "5411", 3870), ("2026-09-20", "Croma (converted to EMI)", "5732", 12000),
                ("2026-09-26", "Indian Oil", "5541", 3400), ("2026-10-01", "Airtel Postpaid", "4814", 2999),
                ("2026-10-04", "Swiggy", "5812", 1260), ("2026-10-07", "Amazon India", "5311", 7840),
                ("2026-10-12", "QuickMart Online", "5999", 4299)]
    txns = []
    for i, (d, merchant, mcc, amt) in enumerate(sep_txns + oct_txns):
        txns.append({"txn_id": f"CT-4417-{i + 1:03d}", "card_id": "CC-4417", "date": d, "merchant": merchant,
                     "mcc": mcc, "amount": amt, "type": "purchase",
                     "emi_converted": merchant.startswith("Croma"), "disputed": False})
    sep_total = sum(a for *_, a in sep_txns)
    oct_regular = sum(a for _, m, _, a in oct_txns if not m.startswith("Croma"))
    fee, fee_gst = 199, to_rupee(D(199) * Decimal("0.18"))
    oct_lines = [
        {"label": "Purchases", "amount": oct_regular},
        {"label": "EMI 1 of 6: Croma ₹12,000 at 15% p.a.", "amount": int(conversion_emi)},
        {"label": "EMI processing fee", "amount": fee},
        {"label": "GST on fees", "amount": int(fee_gst)},
    ]
    statements = [
        {"card_id": "CC-4417", "period": "2026-09", "from": "2026-08-16", "to": "2026-09-15",
         "statement_date": "2026-09-15", "due_date": "2026-10-05", "total_due": sep_total,
         "lines": [{"label": "Purchases", "amount": sep_total}], "paid": sep_total, "status": "paid"},
        {"card_id": "CC-4417", "period": "2026-10", "from": "2026-09-16", "to": "2026-10-15",
         "statement_date": "2026-10-15", "due_date": "2026-11-04",
         "total_due": int(sum(D(line["amount"]) for line in oct_lines)), "lines": oct_lines, "paid": 0,
         "status": "unpaid"},
    ]
    emi_plans = [{"plan_id": "EMI-4417-01", "card_id": "CC-4417", "source_txn": "CT-4417-008", "principal": 12000,
                  "rate": 15.0, "months": 6, "instalment": int(conversion_emi), "instalments_billed": 1,
                  "processing_fee": fee}]
    card["outstanding"] = statements[-1]["total_due"]
    return [card], txns, statements, emi_plans


def build_dataset(today: date = DEMO_TODAY, seed: int = 42) -> dict:
    rng = random.Random(seed)
    customers, loans, rate_history, schedules, mandates, transactions, interactions = [], [], [], {}, [], [], []
    eblr_reason = "EBLR reset: the external benchmark rose from 6.50% to 7.25% on 1 Oct 2026"

    def add_loan(cid, loan_id, product, principal, tenure, disbursed, events, failure_plan=None,
                 random_failures=True, mandate=None):
        loan, history, paid = simulate_loan(loan_id, cid, product, principal, tenure, disbursed, events, today)
        loans.append(loan)
        rate_history.extend(history)
        schedules[loan_id] = paid
        transactions.extend(_debits(loan, paid, rng, failure_plan, random_failures))
        mandates.extend(mandate or [{"mandate_id": f"MD-{loan_id[3:]}", "loan_id": loan_id, "type": "NACH",
                                     "bank": rng.choice(BANKS), "status": "active",
                                     "expires_on": add_months(disbursed, tenure + 1).isoformat()}])
        return loan

    # --- personas ---------------------------------------------------------------------------------
    customers.append(_customer("C1001", "Priya Sharma", "9876543101", dob="1991-06-14", pan_last="4521K"))
    add_loan("C1001", "PL-20391", "PL-FLEXI", 800000, 60, date(2025, 4, 5),
             [(date(2025, 4, 5), 10.50, "Sanctioned rate: EBLR 6.50% + spread 4.00%"),
              (EBLR_RESET, 11.25, eblr_reason)], random_failures=False)

    customers.append(_customer("C1002", "Arjun Mehta", "9876543102", dob="1988-11-02", pan_last="7810L"))
    arjun_plan = {
        "2026-06-10": [{"at": "2026-06-10", "status": "failed", "code": "INSUFFICIENT_FUNDS",
                        "charges": [BOUNCE_CHARGE]},
                       {"at": "2026-06-14", "status": "success", "channel": "NACH"}],
        "2026-09-10": [{"at": "2026-09-10", "status": "failed", "code": "MANDATE_EXPIRED",
                        "charges": [BOUNCE_CHARGE, BOUNCE_CHARGE]},
                       {"at": "2026-09-12", "status": "success", "channel": "UPI"}],
    }
    add_loan("C1002", "PL-18822", "PL-FIXED", 500000, 48, date(2025, 3, 10),
             [(date(2025, 3, 10), 12.00, "Fixed rate at sanction")], arjun_plan, random_failures=False,
             mandate=[{"mandate_id": "MD-18822", "loan_id": "PL-18822", "type": "NACH", "bank": "HDFC Bank",
                       "status": "expired", "expires_on": "2026-09-01"},
                      {"mandate_id": "MD-18822-B", "loan_id": "PL-18822", "type": "UPI AutoPay",
                       "bank": "HDFC Bank", "status": "active", "expires_on": "2029-04-10"}])

    customers.append(_customer("C1003", "Kavya Iyer", "9876543103", dob="1995-02-27", pan_last="3392M"))
    add_loan("C1003", "PL-21507", "PL-FIXED", 300000, 36, date(2026, 2, 20),
             [(date(2026, 2, 20), 13.50, "Fixed rate at sanction")], random_failures=False)

    customers.append(_customer("C1004", "Rohan Das", "9876543104", dob="1986-09-09", pan_last="5567P"))
    add_loan("C1004", "PL-22010", "PL-FLEXI", 100000, 24, date(2025, 12, 1),
             [(date(2025, 12, 1), 11.00, "Sanctioned rate: EBLR 6.50% + spread 4.50%"),
              (EBLR_RESET, 11.75, eblr_reason)], random_failures=False)

    # --- generated book ---------------------------------------------------------------------------
    for i in range(46):
        cid = f"C{2001 + i}"
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        customers.append(_customer(cid, name, f"98{rng.randint(10000000, 99999999)}",
                                   dob=f"19{rng.randint(70, 99)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                                   pan_last=f"{rng.randint(1000, 9999)}{chr(65 + rng.randint(0, 25))}"))
        product = rng.choice(["PL-FLEXI", "PL-FIXED"])
        principal = rng.choice([150000, 250000, 300000, 400000, 500000, 750000, 1000000])
        tenure = rng.choice([24, 36, 48, 60])
        disbursed = today - timedelta(days=rng.randint(60, 700))
        base = round(rng.uniform(10.25, 14.5) * 4) / 4
        events = [(disbursed, base, "Rate at sanction")]
        if product == "PL-FLEXI" and disbursed < EBLR_RESET:
            events.append((EBLR_RESET, base + 0.75, eblr_reason))
        add_loan(cid, f"PL-{30001 + i}", product, principal, tenure, disbursed, events)

    for c in customers[:4]:
        interactions.append({"interaction_id": f"IN-{c['customer_id']}-1", "customer_id": c["customer_id"],
                             "channel": "app", "summary": "Viewed loan summary", "created_at": "2026-10-20T19:12:00+05:30"})

    cards, card_txns, statements, emi_plans = _card_dataset()
    return {
        "today": today.isoformat(), "products": list(PRODUCTS.values()), "customers": customers, "loans": loans,
        "rate_history": rate_history, "schedules": schedules, "mandates": mandates, "transactions": transactions,
        "interactions": interactions, "cards": cards, "card_transactions": card_txns,
        "card_statements": statements, "card_emi_plans": emi_plans,
    }


PERSONAS = [
    {"customer_id": "C1001", "name": "Priya Sharma", "phone": "9876543101",
     "summary": "Floating-rate personal loan; EMI went up this month"},
    {"customer_id": "C1002", "name": "Arjun Mehta", "phone": "9876543102",
     "summary": "Fixed-rate loan with two failed EMI debits"},
    {"customer_id": "C1003", "name": "Kavya Iyer", "phone": "9876543103",
     "summary": "New fixed-rate loan, still in lock-in"},
    {"customer_id": "C1004", "name": "Rohan Das", "phone": "9876543104",
     "summary": "Credit card statement went up; small loan"},
]


if __name__ == "__main__":
    data = build_dataset()
    print(json.dumps({k: v for k, v in data.items() if k != "schedules"}, indent=2, default=str)[:4000])
    for loan in data["loans"][:4]:
        print(loan["loan_id"], loan["emi"], loan["outstanding_principal"], loan["next_due_date"], loan["tenure_left_months"])
