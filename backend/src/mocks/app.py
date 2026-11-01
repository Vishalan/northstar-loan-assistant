"""Mock enterprise systems: CRM, Loan Management, Payments, Policy Knowledge, Service Operations, Cards.

One FastAPI process, one router per system under its own prefix, so each system has its own base URL,
latency profile and failure rate. Every call needs the service token; customer data needs `X-Customer-Id`
and is refused (403) when the record belongs to someone else.

Run: uvicorn mocks.app:app --port 8100
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from nsplatform.calculators.loans import amortize, foreclosure_quote
from mocks.chaos import Chaos
from mocks.policy_docs import CLAUSES
from mocks.seed import build_dataset

IST = timezone(timedelta(hours=5, minutes=30))
SERVICE_TOKEN = os.environ.get("SERVICE_TOKEN", "dev-service-token")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "dev-admin-token")
DB_PATH = Path(os.environ.get("MOCKS_DB", Path(__file__).resolve().parents[2] / "var" / "mocks.db"))
SYSTEM_NAMES = {"crm": "Customer CRM", "loans": "Loan Management", "payments": "Payments",
                "policy": "Policy Knowledge", "ops": "Service Operations", "cards": "Cards"}

DATA = build_dataset()
TODAY = date.fromisoformat(DATA["today"])
chaos = Chaos(os.environ.get("CHAOS_PRESET", "realistic"))


def now_iso() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def source(system: str, record_id: str) -> dict:
    return {"system": SYSTEM_NAMES[system], "record_id": record_id, "as_of": now_iso()}


def err(status: int, code: str, message: str, retryable: bool = False):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "retryable": retryable}})


# --------------------------------------------------------------------------- service-ops store
class RequestStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS requests (
              request_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL,
              summary TEXT NOT NULL, status TEXT NOT NULL, idempotency_key TEXT UNIQUE NOT NULL,
              created_at TEXT NOT NULL, sla_due TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS request_events (
              request_id TEXT NOT NULL, status TEXT NOT NULL, note TEXT, at TEXT NOT NULL);
        """)

    def row(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        d["payload"] = json.loads(d["payload"])
        return d

    def by_key(self, key: str):
        with self.lock:
            r = self.db.execute("SELECT * FROM requests WHERE idempotency_key=?", (key,)).fetchone()
        return self.row(r) if r else None

    def get(self, request_id: str):
        with self.lock:
            r = self.db.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
        return self.row(r) if r else None

    def for_customer(self, customer_id: str):
        with self.lock:
            rows = self.db.execute("SELECT * FROM requests WHERE customer_id=? ORDER BY created_at DESC",
                                   (customer_id,)).fetchall()
        return [self.row(r) for r in rows]

    def create(self, rec: dict):
        with self.lock:
            self.db.execute("INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?)", (
                rec["request_id"], rec["customer_id"], rec["type"], json.dumps(rec["payload"]), rec["summary"],
                rec["status"], rec["idempotency_key"], rec["created_at"], rec["sla_due"]))
            self.db.execute("INSERT INTO request_events VALUES (?,?,?,?)",
                            (rec["request_id"], rec["status"], "Created via AI assistant", rec["created_at"]))
            self.db.commit()

    def set_status(self, request_id: str, status: str, note: str):
        with self.lock:
            self.db.execute("UPDATE requests SET status=? WHERE request_id=?", (status, request_id))
            self.db.execute("INSERT INTO request_events VALUES (?,?,?,?)", (request_id, status, note, now_iso()))
            self.db.commit()

    def events(self, request_id: str):
        with self.lock:
            rows = self.db.execute("SELECT status, note, at FROM request_events WHERE request_id=? ORDER BY at",
                                   (request_id,)).fetchall()
        return [dict(r) for r in rows]


store = RequestStore(DB_PATH)

# --------------------------------------------------------------------------- app + middleware
app = FastAPI(title="Northstar mock enterprise systems")
_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict"}


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return err(exc.status_code, _CODES.get(exc.status_code, "error"), str(exc.detail))


@app.middleware("http")
async def gate(request: Request, call_next):
    parts = request.url.path.strip("/").split("/")
    system = parts[0] if parts else ""
    if system in ("healthz", "admin", "docs", "openapi.json"):
        return await call_next(request)
    if request.headers.get("x-service-token") != SERVICE_TOKEN:
        return err(401, "unauthorized", "missing or invalid service token")
    failure = await chaos.apply(system, request.url.path, request.headers.get("x-chaos-seed"))
    if failure == "unavailable":
        return err(503, "unavailable", f"{SYSTEM_NAMES.get(system, system)} is temporarily unavailable", True)
    if failure == "malformed":
        return PlainTextResponse("<html>upstream error</html>", status_code=500)
    return await call_next(request)


@app.get("/healthz")
def healthz():
    return {"ok": True, "chaos": chaos.preset}


@app.get("/admin/chaos")
def get_chaos():
    return chaos.describe()


@app.put("/admin/chaos")
async def put_chaos(request: Request, x_admin_token: str = Header(default="")):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "admin token required")
    body = await request.json()
    try:
        chaos.set_preset(body.get("preset", "realistic"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return chaos.describe()


def customer_header(x_customer_id: str = Header(...)) -> str:
    return x_customer_id


def owned(record: dict | None, customer_id: str, what: str) -> dict:
    if record is None:
        raise HTTPException(404, f"{what} not found")
    if record["customer_id"] != customer_id:
        raise HTTPException(403, f"{what} belongs to another customer")
    return record


def _index(rows, key):
    return {r[key]: r for r in rows}


CUSTOMERS = _index(DATA["customers"], "customer_id")
LOANS = _index(DATA["loans"], "loan_id")
CARDS = _index(DATA["cards"], "card_id")
TXNS = _index(DATA["transactions"], "txn_id")
PRODUCTS = _index(DATA["products"], "product_code")

# --------------------------------------------------------------------------- CRM
crm = APIRouter(prefix="/crm")


@crm.get("/lookup")
def crm_lookup(phone: str):
    """Identity lookup used by the login flow (no customer header: this is how we find the customer)."""
    for c in DATA["customers"]:
        if c["phone"] == phone:
            return {"customer_id": c["customer_id"], "name": c["name"]}
    raise HTTPException(404, "no customer with that phone")


@crm.get("/customers/{customer_id}")
def crm_customer(customer_id: str, cid: str = Depends(customer_header)):
    c = owned(CUSTOMERS.get(customer_id), cid, "customer")
    profile = {k: v for k, v in c.items() if k != "phone"}
    return {"customer": profile, "source_ref": source("crm", f"customers/{customer_id}")}


@crm.get("/customers/{customer_id}/interactions")
def crm_interactions(customer_id: str, limit: int = 10, cid: str = Depends(customer_header)):
    owned(CUSTOMERS.get(customer_id), cid, "customer")
    rows = [i for i in DATA["interactions"] if i["customer_id"] == customer_id][-limit:]
    return {"interactions": rows, "source_ref": source("crm", f"interactions/{customer_id}")}


@crm.post("/customers/{customer_id}/interactions")
async def crm_log_interaction(customer_id: str, request: Request, cid: str = Depends(customer_header)):
    owned(CUSTOMERS.get(customer_id), cid, "customer")
    body = await request.json()
    rec = {"interaction_id": f"IN-{uuid.uuid4().hex[:8]}", "customer_id": customer_id,
           "channel": body.get("channel", "ai_assistant"), "summary": body.get("summary", ""), "created_at": now_iso()}
    DATA["interactions"].append(rec)
    return rec


# --------------------------------------------------------------------------- Loan management
loans = APIRouter(prefix="/loans")


def loan_view(loan: dict) -> dict:
    product = PRODUCTS[loan["product_code"]]
    lock_in_until = None
    if product["lock_in_months"]:
        from nsplatform.money import add_months
        lock_in_until = add_months(date.fromisoformat(loan["disbursed_on"]), product["lock_in_months"]).isoformat()
    return {**loan, "benchmark": product["benchmark"], "lock_in_months": product["lock_in_months"],
            "lock_in_until": lock_in_until}


@loans.get("/customers/{customer_id}/loans")
def loans_for_customer(customer_id: str, cid: str = Depends(customer_header)):
    owned(CUSTOMERS.get(customer_id), cid, "customer")
    rows = [loan_view(loan) for loan in DATA["loans"] if loan["customer_id"] == customer_id]
    return {"loans": rows, "source_ref": source("loans", f"customers/{customer_id}/loans")}


@loans.get("/loans/{loan_id}")
def loan_detail(loan_id: str, cid: str = Depends(customer_header)):
    loan = owned(LOANS.get(loan_id), cid, "loan")
    return {"loan": loan_view(loan), "source_ref": source("loans", f"loans/{loan_id}")}


@loans.get("/loans/{loan_id}/rate-history")
def loan_rates(loan_id: str, cid: str = Depends(customer_header)):
    owned(LOANS.get(loan_id), cid, "loan")
    rows = [h for h in DATA["rate_history"] if h["loan_id"] == loan_id]
    return {"rate_history": rows, "source_ref": source("loans", f"rate_history/{loan_id}")}


@loans.get("/loans/{loan_id}/schedule")
def loan_schedule(loan_id: str, last: int = 6, upcoming: int = 3, cid: str = Depends(customer_header)):
    loan = owned(LOANS.get(loan_id), cid, "loan")
    paid = DATA["schedules"][loan_id][-last:]
    future = []
    if loan["status"] == "active":
        from nsplatform.money import add_months
        rows = amortize(loan["outstanding_principal"], loan["current_rate"], loan["emi"])[:upcoming]
        start = date.fromisoformat(loan["next_due_date"])
        future = [{"n": loan["instalments_paid"] + r.n, "due_date": add_months(start, r.n - 1).isoformat(),
                   "emi": float(r.emi), "interest": float(r.interest), "principal": float(r.principal),
                   "balance": float(r.balance), "rate": loan["current_rate"]} for r in rows]
    return {"paid": paid, "upcoming": future, "source_ref": source("loans", f"schedule/{loan_id}")}


@loans.get("/loans/{loan_id}/foreclosure-quote")
def loan_foreclosure(loan_id: str, as_of: str | None = None, cid: str = Depends(customer_header)):
    loan = loan_view(owned(LOANS.get(loan_id), cid, "loan"))
    day = date.fromisoformat(as_of) if as_of else TODAY
    allowed = not loan["lock_in_until"] or day >= date.fromisoformat(loan["lock_in_until"])
    charge_pct = 3 if loan["rate_type"] == "fixed" else 0
    q = foreclosure_quote(outstanding=loan["outstanding_principal"], annual_rate=loan["current_rate"],
                          last_due=date.fromisoformat(loan["last_due_date"]), as_of=day,
                          charge_pct=charge_pct, gst_pct=18, allowed=allowed)
    return {"quote": q.as_dict()["figures"], "source_ref": source("loans", f"foreclosure/{loan_id}")}


# --------------------------------------------------------------------------- Payments
payments = APIRouter(prefix="/payments")


@payments.get("/loans/{loan_id}/transactions")
def loan_transactions(loan_id: str, since: str | None = None, status: str | None = None,
                      cid: str = Depends(customer_header)):
    owned(LOANS.get(loan_id), cid, "loan")
    rows = [t for t in DATA["transactions"] if t["loan_id"] == loan_id]
    if since:
        rows = [t for t in rows if t["attempted_at"][:10] >= since]
    if status:
        rows = [t for t in rows if t["status"] == status]
    rows.sort(key=lambda t: t["attempted_at"], reverse=True)
    return {"transactions": rows, "source_ref": source("payments", f"transactions/{loan_id}")}


@payments.get("/loans/{loan_id}/mandates")
def loan_mandates(loan_id: str, cid: str = Depends(customer_header)):
    owned(LOANS.get(loan_id), cid, "loan")
    rows = [m for m in DATA["mandates"] if m["loan_id"] == loan_id]
    return {"mandates": rows, "source_ref": source("payments", f"mandates/{loan_id}")}


@payments.get("/transactions/{txn_id}")
def transaction(txn_id: str, cid: str = Depends(customer_header)):
    t = TXNS.get(txn_id)
    if t is None:
        raise HTTPException(404, "transaction not found")
    owned(LOANS.get(t["loan_id"]), cid, "transaction")
    return {"transaction": t, "source_ref": source("payments", f"transactions/{txn_id}")}


# --------------------------------------------------------------------------- Policy knowledge
policy = APIRouter(prefix="/policy")
CLAUSE_INDEX = _index(CLAUSES, "clause_id")
_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


_DOCS = [(c, Counter(_tokens(f"{c['section']} {c['text']}"))) for c in CLAUSES]
_AVGDL = sum(sum(tf.values()) for _, tf in _DOCS) / len(_DOCS)
_DF = Counter(term for _, tf in _DOCS for term in tf)


def bm25(query: str, k: int = 4, prefix: str | None = None) -> list[dict]:
    terms = _tokens(query)
    scored = []
    for clause, tf in _DOCS:
        if prefix and not clause["clause_id"].startswith(prefix):
            continue
        dl = sum(tf.values())
        score = 0.0
        for t in terms:
            if t not in tf:
                continue
            idf = math.log(1 + (len(_DOCS) - _DF[t] + 0.5) / (_DF[t] + 0.5))
            score += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * dl / _AVGDL))
        if score > 0:
            scored.append((score, clause))
    scored.sort(key=lambda s: -s[0])
    return [{**c, "score": round(s, 3)} for s, c in scored[:k]]


@policy.get("/clauses")
def clauses(ids: str):
    rows = [CLAUSE_INDEX[i] for i in ids.split(",") if i in CLAUSE_INDEX]
    return {"clauses": rows, "source_ref": source("policy", f"clauses/{ids}")}


@policy.post("/clauses/search")
async def clause_search(request: Request):
    body = await request.json()
    rows = bm25(body.get("query", ""), int(body.get("k", 4)), body.get("prefix"))
    return {"clauses": rows, "source_ref": source("policy", "clauses/search")}


# --------------------------------------------------------------------------- Service operations
ops = APIRouter(prefix="/ops")
SLA_DAYS = {"prepayment": 2, "foreclosure": 3, "payment_dispute": 7, "statement": 1, "ticket": 2,
            "escalation": 1, "card_dispute": 30, "mandate_renewal": 3}


def _working_days(start: date, days: int) -> date:
    d = start
    while days:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days -= 1
    return d


@ops.post("/requests")
async def create_request(request: Request, cid: str = Depends(customer_header),
                         idempotency_key: str = Header(...)):
    existing = store.by_key(idempotency_key)
    if existing:
        return JSONResponse(status_code=409, content={"request": existing, "duplicate": True})
    body = await request.json()
    if body.get("customer_id") != cid:
        raise HTTPException(403, "request customer does not match caller")
    rtype = body["type"]
    if rtype not in SLA_DAYS:
        raise HTTPException(400, f"unknown request type {rtype}")
    created = datetime.now(IST)
    rec = {"request_id": f"SR-{created:%y%m%d}-{uuid.uuid4().hex[:6].upper()}", "customer_id": cid, "type": rtype,
           "payload": body.get("payload", {}), "summary": body.get("summary", rtype),
           "status": "completed" if rtype == "statement" else "submitted", "idempotency_key": idempotency_key,
           "created_at": created.isoformat(timespec="seconds"),
           "sla_due": _working_days(created.date(), SLA_DAYS[rtype]).isoformat()}
    store.create(rec)
    return {"request": rec, "source_ref": source("ops", f"requests/{rec['request_id']}")}


@ops.get("/requests")
def find_request(idempotency_key: str, cid: str = Depends(customer_header)):
    rec = store.by_key(idempotency_key)
    if rec is None:
        raise HTTPException(404, "no request for that key")
    return {"request": owned(rec, cid, "request")}


@ops.get("/requests/{request_id}")
def get_request(request_id: str, cid: str = Depends(customer_header)):
    rec = owned(store.get(request_id), cid, "request")
    return {"request": rec, "events": store.events(request_id), "source_ref": source("ops", f"requests/{request_id}")}


@ops.get("/customers/{customer_id}/requests")
def customer_requests(customer_id: str, cid: str = Depends(customer_header)):
    owned(CUSTOMERS.get(customer_id), cid, "customer")
    return {"requests": store.for_customer(customer_id), "source_ref": source("ops", f"requests/{customer_id}")}


@ops.post("/requests/{request_id}/escalate")
async def escalate(request_id: str, request: Request, cid: str = Depends(customer_header)):
    owned(store.get(request_id), cid, "request")
    body = await request.json()
    store.set_status(request_id, "escalated", body.get("reason", "Customer asked for escalation"))
    return {"request": store.get(request_id)}


@ops.get("/statements/{request_id}.pdf")
def statement_pdf(request_id: str, cid: str = Depends(customer_header)):
    rec = owned(store.get(request_id), cid, "request")
    if rec["type"] != "statement":
        raise HTTPException(400, "not a statement request")
    loan = owned(LOANS.get(rec["payload"].get("loan_id")), cid, "loan")
    customer = CUSTOMERS[cid]
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Northstar Finance - Repayment statement", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    for line in [f"Customer: {customer['name']} ({cid})", f"Loan: {loan['loan_id']} - {loan['product_name']}",
                 f"Principal: Rs {loan['principal']:,}   Rate: {loan['current_rate']}%   EMI: Rs {loan['emi']:,}",
                 f"Outstanding principal: Rs {loan['outstanding_principal']:,.2f}   Next due: {loan['next_due_date']}",
                 f"Statement request {request_id}, generated {now_iso()}"]:
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 9)
    widths = [12, 28, 28, 30, 30, 36]
    for w, h in zip(widths, ["No.", "Due date", "EMI", "Interest", "Principal", "Balance"]):
        pdf.cell(w, 6, h, border=1)
    pdf.ln()
    pdf.set_font("Helvetica", size=9)
    for row in DATA["schedules"][loan["loan_id"]]:
        for w, v in zip(widths, [row["n"], row["due_date"], f"{row['emi']:,}", f"{row['interest']:,.2f}",
                                 f"{row['principal']:,.2f}", f"{row['balance']:,.2f}"]):
            pdf.cell(w, 5, str(v), border=1)
        pdf.ln()
    pdf.ln(4)
    pdf.cell(0, 6, "Synthetic demo data. Northstar Finance is fictional.")
    return Response(bytes(pdf.output()), media_type="application/pdf")


# --------------------------------------------------------------------------- Cards (workflow pack 2)
cards = APIRouter(prefix="/cards")


@cards.get("/customers/{customer_id}/cards")
def customer_cards(customer_id: str, cid: str = Depends(customer_header)):
    owned(CUSTOMERS.get(customer_id), cid, "customer")
    rows = [c for c in DATA["cards"] if c["customer_id"] == customer_id]
    return {"cards": rows, "source_ref": source("cards", f"customers/{customer_id}/cards")}


@cards.get("/cards/{card_id}/statements")
def card_statements(card_id: str, cid: str = Depends(customer_header)):
    owned(CARDS.get(card_id), cid, "card")
    rows = [s for s in DATA["card_statements"] if s["card_id"] == card_id]
    return {"statements": rows, "source_ref": source("cards", f"statements/{card_id}")}


@cards.get("/cards/{card_id}/transactions")
def card_transactions(card_id: str, since: str | None = None, until: str | None = None,
                      cid: str = Depends(customer_header)):
    owned(CARDS.get(card_id), cid, "card")
    rows = [t for t in DATA["card_transactions"] if t["card_id"] == card_id
            and (not since or t["date"] >= since) and (not until or t["date"] <= until)]
    return {"transactions": rows, "source_ref": source("cards", f"transactions/{card_id}")}


@cards.get("/cards/{card_id}/emi-plans")
def card_emi_plans(card_id: str, cid: str = Depends(customer_header)):
    owned(CARDS.get(card_id), cid, "card")
    rows = [p for p in DATA["card_emi_plans"] if p["card_id"] == card_id]
    return {"emi_plans": rows, "source_ref": source("cards", f"emi_plans/{card_id}")}


for router in (crm, loans, payments, policy, ops, cards):
    app.include_router(router)
